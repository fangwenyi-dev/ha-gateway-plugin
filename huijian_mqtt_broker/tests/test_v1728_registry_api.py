"""v1.7.28 HA 注册表 API 正确性守卫（2026-09-17 CI E2E 两轮实锤双教训）。

教训一（弃用面）：helpers/frame 告警点名 `device_registry.devices` 的**映射
查找法**（.values()/.items()/.get()，HA 2027.9.0 停摆）；告警原话给出正解
"iterate it to get the device entries"——devices 已是可直接迭代条目的集合。
教训二（E2E 连红两轮）：`async_entries()` 在 DeviceRegistry 与 EntityRegistry
上**都不存在**（两轮真栈 AttributeError 实锤）——本守卫双向反钉臆造 API。
统一出口=utils.iter_devices()（探测首元素类型，兼容新集合/旧 Mapping 双形态）；
实体侧 entities 映射未被弃用，保持原样。本地 589 绿而真栈红，再证
"本机全绿不构成证据"（CLAUDE.md 守则）。

扫描口径：
- 禁 devices 映射查找法三型（.values(.items(.get(）——注释行豁免；
  iter_devices 内部对旧形态的 .values() 回退写作 col.values()，不命中禁型。
- 禁 registry.async_entries / entity_registry.async_entries（不存在的 API）。
- 心跳武装必须无限期等待（while not await async_wait_mqtt_loaded），旧
  "120s 即弃"文案不得复活，且等待循环必须保留条目存活自检。
"""
import pathlib
import re
from types import SimpleNamespace

PKG = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "window_controller_gateway"

FORBIDDEN = (
    "registry.devices.values(",    # 设备注册表映射查找法（2027.9 停摆）。
    "registry.devices.items(",     #   "registry.devices." 前缀同时命中 device_registry.
    "registry.devices.get(",       #   ——与集成自有 self.devices/manager.devices
                                   #   缓存字典（无 registry. 前缀）天然隔离，不误伤
    "registry.async_entries",      # 臆造 API：DeviceRegistry 无此方法（E2E 实锤）
    "entity_registry.async_entries",  # 臆造 API：EntityRegistry 无此方法（E2E 实锤）
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

    def test_device_side_goes_through_iter_devices(self):
        """设备侧遍历统一走 utils.iter_devices（双形态兼容单一出口）。"""
        api = (PKG / "api.py").read_text(encoding="utf-8")
        assert "iter_devices(registry)" in api, "api.py 设备遍历须走 iter_devices"
        dm = (PKG / "device_manager.py").read_text(encoding="utf-8")
        assert "iter_devices(device_registry)" in dm
        init = (PKG / "__init__.py").read_text(encoding="utf-8")
        assert "iter_devices(device_registry)" in init

    def test_iter_devices_dual_shape(self):
        """iter_devices：旧 Mapping（迭代得 key 字符串→回退 .values()）与新
        集合（直接迭代条目）两种形态都必须返回条目列表。"""
        from custom_components.window_controller_gateway.utils import iter_devices

        e1, e2 = object(), object()
        legacy = SimpleNamespace(devices={"id1": e1, "id2": e2})  # Mapping 形态
        assert iter_devices(legacy) == [e1, e2]
        modern = SimpleNamespace(devices=[e1, e2])                 # 集合形态
        assert iter_devices(modern) == [e1, e2]
        assert iter_devices(SimpleNamespace(devices={})) == []
        assert iter_devices(SimpleNamespace(devices=[])) == []

    def test_entity_side_untouched(self):
        """实体侧保持 entities 映射（E2E 实证未弃用、能跑）；查找用 async_get。"""
        btn = (PKG / "button.py").read_text(encoding="utf-8")
        assert "entity_registry.async_get(entity_id)" in btn
        api = (PKG / "api.py").read_text(encoding="utf-8")
        assert "entity_registry.entities.values()" in api


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
