"""v1.7.33 全量审计修复批（C 组）：陈旧值不得冒充新鲜值。

三处实锤 + 一处漏斗补口：
1. `sensor.py` 状态传感器用 `r_travel == 0` **严格比较**推导开/闭——字符串
   "0"/"0.0"（005 上报原样入库形态）与 255（未校准/离线标记）全落 "open"，
   关着的窗显示"打开"；而 v1.7.31 起 Web 设备卡圆点的主判据就是本传感器。
2. `device_manager.setup()` 从映射回填设备时**不带 last_update**，而
   cover/sensor 的 15 分钟时效判据写作 `if _lu and …`（无时间戳=永久新鲜，
   该语义是给历史形态/测试夹具的）——重启后网关不再上报时，实体永久冻结在
   关机前的位置/电压显示。
3. `cover.extra_state_attributes` 不受时效闸约束（`current_cover_position`
   有闸、属性无闸），失联设备出现「圆点灰未知 + 状态:打开 + 位置 65%」并存。
4. `rename_device` 不走 `_notify_status_listeners` 漏斗（改名后小程序要等
   自己下次 get_devices 才见新名）。
"""
import asyncio
import time
from types import SimpleNamespace

import pytest

from custom_components.window_controller_gateway import const as c
from custom_components.window_controller_gateway.cover import WindowControllerCover
from custom_components.window_controller_gateway.sensor import (
    WindowControllerStatusSensor,
)
from custom_components.window_controller_gateway.device_manager import (
    WindowControllerDeviceManager,
)

GW_SN = "100122501207"
DEV_SN = "500500000001"


class _DM:
    """最小设备管理器替身：只暴露被测实体触到的契约面。"""

    def __init__(self, status=None, attributes=None, last_update=None):
        self._device = None
        if status is not None or attributes is not None:
            self._device = {"sn": DEV_SN, "status": status or c.DEVICE_STATUS_UNKNOWN,
                            "attributes": attributes or {}}
            if last_update is not None:
                self._device["last_update"] = last_update

    def get_device(self, sn):
        return self._device

    def get_device_setpoints(self):
        return {}


class TestStatusSensorRTravelNumeric:
    def _sensor(self, attributes):
        return WindowControllerStatusSensor(
            hass=None, device_manager=_DM(attributes=attributes),
            gateway_sn=GW_SN, device_sn=DEV_SN, device_name="窗")

    @pytest.mark.parametrize("raw,expect", [
        ("0", "closed"),          # 字符串零（005 原样入库）——旧实现判成 open
        ("0.0", "closed"),
        (0, "closed"),
        (0.0, "closed"),
        ("40", "open"),
        (65, "open"),
    ])
    def test_numeric_forms(self, raw, expect):
        s = self._sensor({"r_travel": raw})
        s._update_state()
        assert s._attr_native_value == expect, f"r_travel={raw!r} 归一失败"

    @pytest.mark.parametrize("raw", [255, 150, -1, "abc", True])
    def test_uncalibrated_or_invalid_becomes_unknown(self, raw):
        s = self._sensor({"r_travel": raw})
        s._attr_native_value = "open"          # 预置脏值，验证会被清成 None
        s._update_state()
        assert s._attr_native_value is None, (
            f"r_travel={raw!r} 非法/未校准（255=离线标记）必须转 unknown，"
            "绝不用位置反推状态"
        )

    def test_absent_r_travel_keeps_previous_value(self):
        """键缺失 = 本次无数据（≠脏数据）：保持上值，等下一次上报/超时闸。"""
        s = self._sensor({})
        s._attr_native_value = "closed"
        s._update_state()
        assert s._attr_native_value == "closed"


class TestCoverAttributesFreshnessGate:
    def _cover(self, last_update):
        dm = _DM(status=c.DEVICE_STATUS_OPEN,
                 attributes={"r_travel": 65, "voltage": 12.0},
                 last_update=last_update)
        return WindowControllerCover(hass=None, device_manager=dm, mqtt_handler=None,
                                     gateway_sn=GW_SN, device_sn=DEV_SN,
                                     device_name="窗")

    def test_fresh_device_exposes_position(self):
        cov = self._cover(time.time())
        attrs = cov.extra_state_attributes
        assert attrs.get("position") == 65
        assert not attrs.get("position_stale")

    def test_stale_device_hides_position_and_flags(self):
        stale = time.time() - (c.SENSOR_TIMEOUT_MINUTES * 60 + 60)
        attrs = self._cover(stale).extra_state_attributes
        assert "position" not in attrs, (
            "失联超时后不得再供陈旧位置（Web 面板会显示 65% 且滑块可拖）"
        )
        assert attrs.get("position_stale") is True
        assert attrs.get("device_status") == c.DEVICE_STATUS_UNKNOWN

    def test_no_timestamp_keeps_legacy_fresh_semantics(self):
        """无时间戳=新鲜 是 v1.6.19 给历史形态/夹具的兼容语义，不得误伤。"""
        attrs = self._cover(None).extra_state_attributes
        assert attrs.get("position") == 65


class TestBackfillStampsLastUpdate:
    def test_mapping_backfilled_devices_get_timestamp(self, monkeypatch):
        hass = SimpleNamespace(
            data={c.DOMAIN: {c.DEVICE_TO_GATEWAY_MAPPING: {DEV_SN: GW_SN}}},
            config=SimpleNamespace(config_dir="."),
            config_entries=SimpleNamespace(
                async_get_entry=lambda eid: None, async_entries=lambda d: []),
        )
        entry = SimpleNamespace(entry_id="e1", data={c.CONF_GATEWAY_SN: GW_SN},
                                options={})
        dm = WindowControllerDeviceManager(hass, entry)
        # 回填后立即拉起注册后台任务——测试里关掉协程，避免无谓的 registry 调用
        monkeypatch.setattr(dm, "_spawn_background_task",
                            lambda coro, name=None: coro.close())
        before = time.time()
        assert asyncio.run(dm.setup()) is not False
        dev = dm.devices.get(DEV_SN)
        assert dev is not None, "映射命中设备应回填"
        lu = dev.get("last_update")
        assert isinstance(lu, (int, float)) and before <= lu <= time.time() + 1, (
            "回填必须带 last_update，否则 15 分钟时效契约对重启后未上报设备永不生效"
        )


class TestRenameNotifiesListeners:
    def test_rename_pushes_status_listener(self, monkeypatch):
        import homeassistant.helpers.device_registry as dr_mod
        import homeassistant.helpers.entity_registry as er_mod
        monkeypatch.setattr(dr_mod, "async_get", lambda hass: SimpleNamespace(
            async_get_device=lambda identifiers=None: None))
        monkeypatch.setattr(er_mod, "async_get", lambda hass: SimpleNamespace(
            async_get_entity_id=lambda *a, **k: None,
            async_update_entity=lambda *a, **k: None))
        hass = SimpleNamespace(
            data={c.DOMAIN: {}}, config=SimpleNamespace(config_dir="."),
            config_entries=SimpleNamespace(
                async_get_entry=lambda eid: None, async_entries=lambda d: []),
        )
        entry = SimpleNamespace(entry_id="e1", data={c.CONF_GATEWAY_SN: GW_SN},
                                options={})
        dm = WindowControllerDeviceManager(hass, entry)
        dm.devices[DEV_SN] = {"sn": DEV_SN, "name": "旧名",
                              "type": c.DEVICE_TYPE_WINDOW_OPENER,
                              "status": c.DEVICE_STATUS_OPEN,
                              "attributes": {}, "last_update": time.time()}
        seen = []
        dm.add_status_listener(lambda gw, sn: seen.append((gw, sn)))
        monkeypatch.setattr(dm, "_trigger_persistent_save", lambda: None)
        assert asyncio.run(dm.rename_device(DEV_SN, "新名")) is True
        assert seen == [(GW_SN, DEV_SN)], (
            "改名必须经 _notify_status_listeners 漏斗，否则小程序端停留在旧名"
        )
