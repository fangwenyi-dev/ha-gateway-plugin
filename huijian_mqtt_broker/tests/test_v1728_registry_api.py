"""v1.7.28 HA 注册表弃用面清零守卫（2026-09-17 现场告警实锤）。

HA helpers/frame 告警：`device_registry.devices` 映射访问（api.py:99）已弃用，
HA 2027.9.0 停摆。本文件做两件事：
1. 全集成源码扫描——禁止再出现注册表映射直读（registry.devices /
   entity_registry.entities 的 .values()/.items()/.get()/len()），一律走
   async_entries()/async_get()。device_manager 自有的 self.devices 缓存字典
   不在此列（那是集成内部结构，非 HA 注册表）。
2. 心跳武装"120s 即弃"反钉——必须无限期等待（while not await
   async_wait_mqtt_loaded），旧放弃文案不得复活。
"""
import pathlib
import re

PKG = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "window_controller_gateway"

# 注册表映射直读的禁型（子串级即可命中全部形态：.values()/.items()/.get()/len()）
FORBIDDEN = (
    "registry.devices",            # 同时覆盖 device_registry.devices / registry.devices
    "entity_registry.entities",
    ".entities.values(",
    ".entities.items(",
    ".entities.get(",
)


def _py_sources():
    for p in sorted(PKG.rglob("*.py")):
        yield p, p.read_text(encoding="utf-8")


class TestRegistryApiMigration:
    def test_no_deprecated_registry_mapping_access(self):
        hits = []
        for path, src in _py_sources():
            for ln, line in enumerate(src.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue  # 注释/墓碑允许提及旧形态（历史说明）
                for pat in FORBIDDEN:
                    if pat in line:
                        hits.append(f"{path.name}:{ln}: {stripped[:100]}")
        assert not hits, "注册表映射直读回潮（HA 2027.9 停摆）:\n" + "\n".join(hits)

    def test_async_entries_in_use(self):
        """迁移确实发生：核心文件必须出现 async_entries()/async_get() 消费。"""
        api = (PKG / "api.py").read_text(encoding="utf-8")
        assert "registry.async_entries()" in api and "entity_registry.async_entries()" in api
        dm = (PKG / "device_manager.py").read_text(encoding="utf-8")
        assert dm.count("async_entries()") >= 5, "device_manager 五处循环+快照均应迁移"
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
        """无限循环必须保留卸载自检（data_now/entry_id is None → return）。"""
        src = (PKG / "__init__.py").read_text(encoding="utf-8")
        i = src.index("while not await async_wait_mqtt_loaded")
        seg = src[i:i + 700]
        assert "entry.entry_id) is None" in seg, "等待循环内必须检查条目存活，防悬挂任务"
