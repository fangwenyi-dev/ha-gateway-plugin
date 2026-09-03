"""v1.6.23 钉桩：cover 以"窗帘"身份暴露的可选项（vivo HomeBridge 适配）。

背景（vbridge.py 源码实证）：vivohomebridge 的 cover 枚举分支仅放行
device_class == curtain，本集成默认 WINDOW 会被过滤 → vivo 端选不到
开窗器；button 域不在其白名单且 vivo 协议无按钮类目，不作适配（窗帘
设备本身含开/关/停/位置，控制能力已覆盖）。

兼容铁律：默认必须仍是 WINDOW——存量用户 HA 卡片图标/语义零变化，
只有显式勾选 options 才切换。
"""
from pathlib import Path

from custom_components.window_controller_gateway.const import (
    CONF_EXPOSE_COVER_AS_CURTAIN,
    DEFAULT_EXPOSE_COVER_AS_CURTAIN,
)
from custom_components.window_controller_gateway.cover import (
    WindowControllerCover,
)

PKG = Path(__file__).resolve().parents[1] / "custom_components" / \
    "window_controller_gateway"


class _FakeDM:
    async def get_device(self, sn):
        return None

    async def update_device_status(self, *a, **k):
        return None


def _cover(as_curtain=None):
    kw = {} if as_curtain is None else {"as_curtain": as_curtain}
    return WindowControllerCover(
        hass=None, device_manager=_FakeDM(), mqtt_handler=None,
        gateway_sn="GW1", device_sn="5005X", device_name="窗", **kw)


def test_default_off_for_existing_users():
    assert DEFAULT_EXPOSE_COVER_AS_CURTAIN is False
    assert CONF_EXPOSE_COVER_AS_CURTAIN == "expose_cover_as_curtain"


def test_device_class_window_by_default():
    from homeassistant.components.cover import CoverDeviceClass
    # 不传参（存量调用形态）与显式 False 都必须是 WINDOW
    assert _cover()._attr_device_class == CoverDeviceClass.WINDOW
    assert _cover(False)._attr_device_class == CoverDeviceClass.WINDOW


def test_device_class_curtain_when_opted_in():
    from homeassistant.components.cover import CoverDeviceClass
    assert _cover(True)._attr_device_class == CoverDeviceClass.CURTAIN


def test_options_flow_wires_the_toggle():
    src = (PKG / "config_flow.py").read_text(encoding="utf-8")
    assert "CONF_EXPOSE_COVER_AS_CURTAIN" in src
    # schema 挂在 options 步（默认值从 entry.options 回填）
    i = src.index("async def async_step_options")
    seg = src[i:]
    assert "CONF_EXPOSE_COVER_AS_CURTAIN" in seg.split("async_show_form")[1]


def test_setup_entry_passes_option():
    src = (PKG / "cover.py").read_text(encoding="utf-8")
    # 动态添加与启动循环两处构造点都读取 options
    assert src.count("as_curtain=bool(entry.options.get(") == 2


def test_strings_have_field_descriptions():
    import json
    en = json.loads((PKG / "strings.json").read_text(encoding="utf-8"))
    zh = json.loads((PKG / "translations" / "zh-CN.json").read_text(
        encoding="utf-8"))
    for doc in (en, zh):
        data = doc["options"]["step"]["options"]["data"]
        assert "expose_cover_as_curtain" in data
        # 文案必须提示生效条件与影响面（面向用户的诚实描述）
        text = data["expose_cover_as_curtain"]
        assert ("vivo" in text or "Vivo" in text)
