"""v1.7.28 HA 注册表 API 正确性守卫（2026-09-17 CI E2E 实锤双教训）。

教训一（弃用面）：helpers/frame 告警点名 `device_registry.devices` 映射直读
（api.py 原 L99），HA 2027.9.0 停摆——设备侧必须走 async_entries()。
教训二（E2E 首跑红）：EntityRegistry **根本没有 async_entries()**（真 HA
AttributeError 实锤），entities 映射在实体侧未被弃用——本守卫同时反钉
"entity_registry.async_entries" 这一臆造 API 回潮。本地 589 绿而真栈红，
再次实证"替身/无覆盖不构成证据"（CLAUDE.md 守则）。

扫描口径：
- 禁 `registry.devices`（覆盖 device_registry.devices / registry.devices 全部
  直读形态；device_manager 自有 self.devices 缓存字典不含该子串，不误伤）。
- 禁 `entity_registry.async_entries`（不存在的 API）。
- 注释行（# 开头）豁免——历史说明/墓碑允许提及旧形态。
- 心跳武装必须无限期等待（while not await async_wait_mqtt_loaded），旧
  "120s 即弃"文案不得复活，且等待循环必须保留条目存活自检。
"""
import pathlib
import re

PKG = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "window_controller_gateway"

FORBIDDEN = (
    "registry.devices",              # 设备注册表映射直读（2027.9 停摆）
    "entity_registry.async_entries", # 臆造 API：EntityRegistry 无此方法（E2E 实锤）
)


def _py_sources():
    for p in sorted(PKG.rglob("*.py")):
        yield p, p.read_text(encoding="utf-8")


class TestRegistryApiCorrectness:
    def test_no_forbidden_registry_access(self):
        hits = []
        for path, src in _py_sources():
            for ln, line in enumerate(src.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                for pat in FORBIDDEN:
                    if pat in line:
                        hits.append(f"{path.name}:{ln}: {stripped[:110]}")
        assert not hits, "注册表 API 违规回潮:\n" + "\n".join(hits)

    def test_device_side_migrated_to_real_api(self):
        """设备侧确实走 async_entries()（真存在的 DeviceRegistry API）。"""
        api = (PKG / "api.py").read_text(encoding="utf-8")
        assert "registry.async_entries()" in api, "api.py 设备遍历须走 async_entries"
        dm = (PKG / "device_manager.py").read_text(encoding="utf-8")
        assert "device_registry.async_entries()" in dm
        init = (PKG / "__init__.py").read_text(encoding="utf-8")
        assert "device_registry.async_entries()" in init

    def test_entity_side_uses_entities_mapping(self):
        """实体侧保持 entities 映射（未被弃用），查找走 async_get（真存在）。"""
        btn = (PKG / "button.py").read_text(encoding="utf-8")
        assert "entity_registry.async_get(entity_id)" in btn


class TestArmInfinitePatience:
    def test_arm_loops_instead_of_giving_up(self):
        src = (PKG / "__init__.py").read_text(encoding="utf-8")
        assert re.search(r"while not await async_wait_mqtt_loaded\(hass, timeout=120\.0\)", src), \
            "武装任务必须无限期等待（120s 一轮节流），不得一轮即弃"
        assert "仍未就绪，心跳监听器未武装" not in src, "旧放弃文案已作废，不得复活"
        assert "心跳武装持续等待" in src

    def test_arm_still_guards_unload(self):
        """无限循环必须保留卸载自检（entry_id is None → return）。"""
        src = (PKG / "__init__.py").read_text(encoding="utf-8")
        i = src.index("while not await async_wait_mqtt_loaded")
        seg = src[i:i + 700]
        assert "entry.entry_id) is None" in seg, "等待循环内必须检查条目存活，防悬挂任务"
