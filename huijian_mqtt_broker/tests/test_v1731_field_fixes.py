"""v1.7.31 现场实锤修复批（1.7.30 真机测试抓出、五路静态审计漏网的两条）。

F-A（__init__.py）：``async_listen_once`` 的 STOP 一次性监听器在事件派发时
    已被总线消费摘除；``_make_shutdown_handler`` 随后自调 ``async_unload_entry``，
    unload 步骤 1 对 ``_stop_unsub`` 再 unsub → HA core 打
    "Unable to remove unknown job listener" ERROR——现场每次停机每条目必现
    （0918 现场两条 ERROR = 1203/123f 两条目）。修复 = handler 自调 unload 前
    先 pop 掉已被消费的句柄；reload（非 STOP）路径不受影响、仍须正常退订
    （反钉防"顺手把 unsub 全删"）。

F-B（device_manager.py ×6）：``async_get_or_create`` 的 ``via_device=(DOMAIN, sn)``
    写参数面被 HA 2026.9 现场实锤弃用（每次启动一条
    "use via_device_id instead … stop working in 2027.8.0"）——v1.7.28 迁移批
    清了 devices/entities 直读面、守卫 pattern 不覆盖入参名，此为漏网面。
    修复 = 经 utils.resolve_via_device_id 解析父设备注册表 id 传 via_device_id；
    AST 守卫禁一切调用实参 ``via_device=``（docstring 提及不算），计数正钉
    6 处迁移点在位。
"""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import custom_components.window_controller_gateway as pkg
from custom_components.window_controller_gateway.const import DOMAIN
import custom_components.window_controller_gateway.device_manager as dm
from custom_components.window_controller_gateway.utils import (
    resolve_via_device_id)

_HERE = Path(__file__).resolve()
_PKG_DIR = _HERE.parents[1] / "custom_components" / "window_controller_gateway"


# ==================== F-A：STOP 监听器双重移除 ====================

class _UnsubRecorder:
    """模拟 HA core 语义：one-time 监听器被消费后再 remove → core 打
    "Unable to remove unknown job listener" ERROR。这里只记调用次数，
    行为测试断言 0（修复前=1）。"""

    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1


def _mk_runtime_hass():
    runtime = {"_stop_unsub": _UnsubRecorder()}
    hass = SimpleNamespace(
        data={DOMAIN: {"E1": runtime}},
        config_entries=SimpleNamespace(
            async_get_entry=lambda eid: None,
            async_unload_platforms=None,  # runtime 无 _platforms_forwarded 不会被调
        ),
    )
    entry = SimpleNamespace(entry_id="E1", title="慧尖网关", data={})
    return hass, entry, runtime


class TestStopHandlerNoDoubleUnsub:
    def test_handler_does_not_unsub_consumed_listener(self, monkeypatch):
        """STOP 派发形态：handler 自调 unload 不得再触碰已消费的 _stop_unsub。"""
        async def noop_save(hass):
            return None
        monkeypatch.setattr(pkg, "save_persistent_data", noop_save)
        hass, entry, runtime = _mk_runtime_hass()
        rec = runtime["_stop_unsub"]  # 先捕获引用：unload 收尾会清掉 runtime
        handler = pkg._make_shutdown_handler(hass, entry)
        asyncio.run(handler(SimpleNamespace(event_type="x")))
        assert rec.calls == 0, (
            "F-A 回归：STOP 派发时总线已消费该 one-time 监听器，"
            "unload 再 unsub 必打 'Unable to remove unknown job listener' ERROR")
        # handler 内的 unload 应真实执行（runtime 被清 = 走到 unload 收口）
        assert "E1" not in hass.data[DOMAIN], "handler 必须完成自卸载"

    def test_reload_path_still_unsubs(self, monkeypatch):
        """非 STOP（reload/手动卸载）形态：监听器仍在总线上，unload 步骤 1
        必须照常 unsub——反钉修复不越界把正常退订也删掉。"""
        async def noop_save(hass):
            return None
        monkeypatch.setattr(pkg, "save_persistent_data", noop_save)
        hass, entry, runtime = _mk_runtime_hass()
        ok = asyncio.run(pkg.async_unload_entry(hass, entry))
        assert ok is True
        assert runtime["_stop_unsub"].calls == 1, \
            "reload 路径 unload 必须退订 STOP 监听器（漏退订=条目重建后双监听器）"


# ==================== F-B：via_device 写参数面迁移 ====================

class _GatewayRegistry:
    """记录 async_get_or_create 实参的假设备注册表（实参断言，非源码钉）。

    form="new"：模拟现场 HA 2026.9.2 实态（via_device_id 存在、via_device 弃用）
    form="old"：模拟台架 HA 2026.1.3 真签名核验实态（仅 via_device）
    ——签名均显式声明参数名（非 **kwargs 吞），供 utils 的 inspect 探测分形。
    """

    def __init__(self, gateway_id="GW-REG-ID", gateway_exists=True, form="new"):
        self._gateway_id = gateway_id
        self._gateway_exists = gateway_exists
        self.kwargs = None
        if form == "new":
            async def _new(self_, *, config_entry_id=None, identifiers=None,
                           name=None, manufacturer=None, model=None,
                           via_device_id=None, **rest):
                self_.kwargs = {"config_entry_id": config_entry_id,
                                "identifiers": identifiers, "name": name,
                                "manufacturer": manufacturer, "model": model,
                                "via_device_id": via_device_id}
                return SimpleNamespace(id="DEV-1", config_entries={"E1"})
            self.async_get_or_create = _new.__get__(self)
        else:
            async def _old(self_, *, config_entry_id=None, identifiers=None,
                           name=None, manufacturer=None, model=None,
                           via_device=None, **rest):
                self_.kwargs = {"config_entry_id": config_entry_id,
                                "identifiers": identifiers, "name": name,
                                "manufacturer": manufacturer, "model": model,
                                "via_device": via_device}
                return SimpleNamespace(id="DEV-1", config_entries={"E1"})
            self.async_get_or_create = _old.__get__(self)

    def async_get_device(self, identifiers=None):
        if not self._gateway_exists:
            return None
        return SimpleNamespace(id=self._gateway_id)


def _fake_self(reg):
    async def _get_registry():
        return reg
    return SimpleNamespace(
        gateway_sn="10012250123f",
        entry=SimpleNamespace(entry_id="E1"),
        hass=SimpleNamespace(
            config_entries=SimpleNamespace(
                async_get_entry=lambda eid: object())),
        _get_device_registry=_get_registry,
    )


class TestResolveViaDeviceId:
    def test_hit_returns_device_id(self):
        reg = _GatewayRegistry(gateway_id="ABC123")
        assert resolve_via_device_id(reg, "10012250123f") == "ABC123"

    def test_miss_returns_none(self):
        reg = _GatewayRegistry(gateway_exists=False)
        assert resolve_via_device_id(reg, "10012250123f") is None

    def test_registry_error_returns_none(self):
        class _Boom:
            def async_get_device(self, **k):
                raise RuntimeError("registry 读面异常")
        assert resolve_via_device_id(_Boom(), "x") is None, \
            "宿主解析失败宁缺归属、不断子设备注册主链"

    def test_kwargs_probe_two_forms(self):
        """双形态出口按运行时签名分形（manifest 支持 2024.12 起全区间）。"""
        from custom_components.window_controller_gateway.utils import (
            via_device_kwargs)
        from custom_components.window_controller_gateway.const import DOMAIN as D
        new = _GatewayRegistry(gateway_id="NID", form="new")
        assert via_device_kwargs(new, "sn1") == {"via_device_id": "NID"}
        old = _GatewayRegistry(form="old")
        # 旧 HA 无 via_device_id：保持原 via_device=(DOMAIN, sn) 形态——
        # 无条件新写法会在旧版 TypeError 打死设备注册（台架 2026.1.3 实证）
        assert via_device_kwargs(old, "sn1") == {"via_device": (D, "sn1")}


class TestFastRegisterRealArgs:
    def test_new_ha_receives_via_device_id(self):
        reg = _GatewayRegistry(gateway_id="GW-REG-ID", form="new")
        asyncio.run(dm.WindowControllerDeviceManager
                    ._async_fast_register_device(_fake_self(reg),
                                                 "50063420020A", "开窗器"))
        assert reg.kwargs is not None, "注册调用未发生"
        assert "via_device" not in reg.kwargs, \
            "F-B 回归：新 HA 上 via_device=(DOMAIN, sn) 已弃用（2027.8 停摆）"
        assert reg.kwargs.get("via_device_id") == "GW-REG-ID", \
            "宿主归属必须传父设备注册表 id（实参断言）"

    def test_old_ha_keeps_via_device_tuple(self):
        reg = _GatewayRegistry(form="old")
        asyncio.run(dm.WindowControllerDeviceManager
                    ._async_fast_register_device(_fake_self(reg),
                                                 "50063420020A", "开窗器"))
        from custom_components.window_controller_gateway.const import DOMAIN as D
        assert reg.kwargs.get("via_device") == (D, "10012250123f"), \
            "旧 HA 兼容形态不得丢宿主归属（manifest 下限 2024.12）"
        assert "via_device_id" not in reg.kwargs

    def test_missing_gateway_omits_via(self):
        reg = _GatewayRegistry(gateway_exists=False, form="new")
        asyncio.run(dm.WindowControllerDeviceManager
                    ._async_fast_register_device(_fake_self(reg),
                                                 "50063420020A", "开窗器"))
        assert reg.kwargs.get("via_device_id") is None
        assert "via_device" not in reg.kwargs


class TestNoDeprecatedViaDeviceCall:
    """AST 守卫：全集成运行时代码禁止以 ``via_device=`` 作调用实参。

    用 AST 而非源码文本扫描——docstring/注释里提及 ``via_device=(DOMAIN, sn)``
    的历史说明（utils.get_via_device_id 等）不得误伤；只禁真实调用面。
    旧形态仅允许经 via_device_kwargs 的 dict 键出口（兼容旧 HA）。
    """

    def test_ast_forbid_via_device_kwarg(self):
        offenders = []
        for py in _PKG_DIR.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    for kw in node.keywords:
                        if kw.arg == "via_device":
                            offenders.append(f"{py.name}:{node.lineno}")
        assert not offenders, (
            f"发现弃用 via_device= 入参调用（HA 2027.8 停摆面）：{offenders}"
            "——一律改走 utils.via_device_kwargs 双形态出口")

    def test_six_migration_points_present(self):
        src = (_PKG_DIR / "device_manager.py").read_text(encoding="utf-8")
        n = src.count("**via_device_kwargs(device_registry, ")
        assert n == 6, \
            f"via_device_kwargs 迁移点须恰为 6（实得 {n}）：注册×3/更新×1/迁移×2"
