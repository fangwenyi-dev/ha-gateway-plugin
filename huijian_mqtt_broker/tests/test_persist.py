"""persist.py 持久化读写测试（使用假 hass，无 HA 环境依赖）。"""
import asyncio
import json
import os
import tempfile
from types import SimpleNamespace

from custom_components.window_controller_gateway.const import DOMAIN
from custom_components.window_controller_gateway import persist


class FakeHass:
    """最小可用的假 hass：提供 config.config_dir 与 async_add_executor_job。"""

    def __init__(self, config_dir, mqtt_loaded=True):
        self.config = SimpleNamespace(config_dir=config_dir)
        self.data = {
            "mqtt": object() if mqtt_loaded else None,
            DOMAIN: {
                "device_to_gateway_mapping": {"dev500534380262": "gw100122501207"},
                "global_manually_removed_devices": {"dev500534380263"},
                "device_setpoints": {"dev500534380262": {"speed": 50, "strength": 70}},
            },
        }

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


def _run(coro):
    return asyncio.run(coro)


class TestPersistRoundTrip:
    def test_save_then_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            hass = FakeHass(tmp)
            _run(persist.save_persistent_data(hass))

            data_file = os.path.join(tmp, persist.PERSISTENT_DATA_FILE)
            assert os.path.exists(data_file)

            # 新 hass 加载
            hass2 = FakeHass(tmp)
            hass2.data[DOMAIN] = {}
            _run(persist.load_persistent_data(hass2))

            loaded = hass2.data[DOMAIN]
            assert loaded["device_to_gateway_mapping"] == {
                "dev500534380262": "gw100122501207"
            }
            assert loaded["global_manually_removed_devices"] == {"dev500534380263"}
            assert loaded["device_setpoints"] == {
                "dev500534380262": {"speed": 50, "strength": 70}
            }

    def test_save_creates_bak_on_second_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            hass = FakeHass(tmp)
            _run(persist.save_persistent_data(hass))
            # 第二次保存应生成 .bak
            hass.data[DOMAIN]["device_to_gateway_mapping"]["new_dev"] = "gw1"
            _run(persist.save_persistent_data(hass))
            bak_file = os.path.join(tmp, persist.PERSISTENT_DATA_FILE + ".bak")
            assert os.path.exists(bak_file)

    def test_load_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            hass = FakeHass(tmp)
            hass.data[DOMAIN] = {}
            _run(persist.load_persistent_data(hass))
            # v1.6.12（第五轮审计）契约更新：主文件缺失且无 .bak 时走
            # "数据完全不可用"分支——映射/删除列表不产生（保持 async_setup 的
            # setdefault 初值），DEVICE_SETPOINTS 兜底初始化（防 setup 顺序变化
            # 时下游 KeyError）
            assert hass.data[DOMAIN] == {"device_setpoints": {}}

    def test_load_corrupt_file_falls_back_to_bak(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_file = os.path.join(tmp, persist.PERSISTENT_DATA_FILE)
            bak_file = data_file + ".bak"
            # 主文件损坏
            with open(data_file, "w", encoding="utf-8") as f:
                f.write("{corrupt json")
            # .bak 有效
            with open(bak_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "schema_version": 1,
                        "device_to_gateway_mapping": {"dev1": "gw1"},
                        "manually_removed_devices": [],
                    },
                    f,
                )
            hass = FakeHass(tmp)
            hass.data[DOMAIN] = {}
            _run(persist.load_persistent_data(hass))
            assert hass.data[DOMAIN]["device_to_gateway_mapping"] == {"dev1": "gw1"}

    def test_schema_version_field_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            hass = FakeHass(tmp)
            _run(persist.save_persistent_data(hass))
            data_file = os.path.join(tmp, persist.PERSISTENT_DATA_FILE)
            with open(data_file, encoding="utf-8") as f:
                data = json.load(f)
            assert data["schema_version"] == persist.SCHEMA_VERSION
