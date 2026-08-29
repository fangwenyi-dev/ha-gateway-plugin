"""v1.6.9 外部审计终审回归：控制命令「假成功」根治契约。

背景（同一 bug 家族，7 处）：send_command 返回 False（QoS1 未送达=链路断）
或抛异常时，各控制路径曾仅 _LOGGER 后正常返回——REST 200 / HA 卡片绿勾，
但命令根本没发出去。本文件钉死契约：未送达/异常 ⇒ 必须向调用方抛错
（服务路径 ServiceValidationError，实体路径 HomeAssistantError），
成功 ⇒ 正常返回且不抛。

对应修复：services.start_pairing / services.set_position、
cover 开/关/停、button 按压、gateway 配对按钮。
"""
import inspect
from types import SimpleNamespace

import pytest

import custom_components.window_controller_gateway.services as services_mod
from custom_components.window_controller_gateway.services import (
    ServiceValidationError,
    handle_start_pairing,
    handle_set_position,
)
from custom_components.window_controller_gateway.cover import WindowControllerCover
from custom_components.window_controller_gateway.button import BaseWindowControllerButton
from homeassistant.exceptions import HomeAssistantError


class RecHandler:
    """可编程 mqtt_handler 替身：result 控制返回值，exc 控制抛出异常。"""

    def __init__(self, result=True, exc=None):
        self.gateway_sn = "GW1"
        self.pairing_timeout_handle = None
        self.pairing_active = False
        self.notified = 0
        self._result = result
        self._exc = exc
        self.calls = []

    async def send_command(self, sn, command, params=None):
        self.calls.append((sn, command, params))
        if self._exc is not None:
            raise self._exc
        return self._result

    def _notify_status_change(self):
        self.notified += 1


class _FakeLoop:
    def call_later(self, delay, cb):
        return SimpleNamespace(cancel=lambda: None)


class _FakeHass:
    loop = _FakeLoop()

    def __init__(self):
        self.tasks = []

    def async_create_task(self, coro):
        if inspect.iscoroutine(coro):
            coro.close()  # 本测试不驱动后台任务，关闭避免 pending 告警
        return SimpleNamespace(cancel=lambda: None)


def _call(**data):
    return SimpleNamespace(data=data)


def _cover(handler):
    return WindowControllerCover(
        hass=None, device_manager=None, mqtt_handler=handler,
        gateway_sn="GW1", device_sn="5005X", device_name="窗",
    )


def _button(handler):
    return BaseWindowControllerButton(
        hass=None, device_manager=None, mqtt_handler=handler,
        gateway_sn="GW1", device_sn="5005X", device_name="窗",
        button_name="内倒", button_type="a", command="a", icon="mdi:open-in-app",
    )


class TestCoverCommandsFailfast:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["async_open_cover", "async_close_cover", "async_stop_cover"])
    async def test_undelivered_raises(self, method):
        c = _cover(RecHandler(result=False))
        with pytest.raises(HomeAssistantError):
            await getattr(c, method)()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["async_open_cover", "async_close_cover", "async_stop_cover"])
    async def test_exception_raises(self, method):
        c = _cover(RecHandler(exc=RuntimeError("broker down")))
        with pytest.raises(HomeAssistantError):
            await getattr(c, method)()

    @pytest.mark.asyncio
    async def test_success_no_raise(self):
        h = RecHandler(result=True)
        await _cover(h).async_open_cover()
        assert h.calls == [("5005X", "open", None)]


class TestButtonPressFailfast:
    @pytest.mark.asyncio
    async def test_undelivered_raises(self):
        b = _button(RecHandler(result=False))
        with pytest.raises(HomeAssistantError):
            await b.async_press()

    @pytest.mark.asyncio
    async def test_exception_raises(self):
        b = _button(RecHandler(exc=ConnectionError("gone")))
        with pytest.raises(HomeAssistantError):
            await b.async_press()

    @pytest.mark.asyncio
    async def test_success_no_raise(self):
        b = _button(RecHandler(result=True))
        await b.async_press()


class TestStartPairingFailfast:
    """审计确认的高严重度路径：:88 raise 曾被末尾 except Exception 吞掉。"""

    @pytest.mark.asyncio
    async def test_undelivered_propagates(self, monkeypatch):
        handler = RecHandler(result=False)
        monkeypatch.setattr(services_mod, "find_gateway_by_device_id",
                            lambda hass, did: ({"mqtt_handler": handler}, "GW1"))
        with pytest.raises(ServiceValidationError):
            await handle_start_pairing(_FakeHass(), _call(device_id="x"))
        # 且不得留下半吊子副作用：pairing_active 必须仍为 False
        assert handler.pairing_active is False

    @pytest.mark.asyncio
    async def test_send_exception_propagates(self, monkeypatch):
        # v1.6.9 同族收口：send_command 抛连接类异常 = 未送达，
        # 此前仅日志后正常返回（200 假成功），现必须如实抛 SV
        handler = RecHandler(exc=ConnectionError("down"))
        monkeypatch.setattr(services_mod, "find_gateway_by_device_id",
                            lambda hass, did: ({"mqtt_handler": handler}, "GW1"))
        with pytest.raises(ServiceValidationError):
            await handle_start_pairing(_FakeHass(), _call(device_id="x"))
        assert handler.pairing_active is False

    @pytest.mark.asyncio
    async def test_success_sets_pairing(self, monkeypatch):
        handler = RecHandler(result=True)
        dm = SimpleNamespace(update_gateway_status=lambda s: _noop_coro())
        monkeypatch.setattr(services_mod, "find_gateway_by_device_id",
                            lambda hass, did: ({"mqtt_handler": handler, "device_manager": dm}, "GW1"))
        await handle_start_pairing(_FakeHass(), _call(device_id="x"))
        assert handler.pairing_active is True
        assert handler.pairing_timeout_handle is not None


class TestSetPositionFailfast:
    """审计确认的中严重度路径：fire-and-forget 吞异常恒 200。"""

    def _patch(self, monkeypatch, handler):
        monkeypatch.setattr(services_mod, "find_device_by_device_id",
                            lambda hass, did: ({"sn": "5005X"}, {"mqtt_handler": handler}, "GW1"))

    @pytest.mark.asyncio
    async def test_undelivered_raises(self, monkeypatch):
        handler = RecHandler(result=False)
        self._patch(monkeypatch, handler)
        with pytest.raises(ServiceValidationError):
            await handle_set_position(_FakeHass(), _call(device_id="d", position=50))

    @pytest.mark.asyncio
    async def test_exception_raises(self, monkeypatch):
        self._patch(monkeypatch, RecHandler(exc=TimeoutError("mqtt timeout")))
        with pytest.raises(ServiceValidationError):
            await handle_set_position(_FakeHass(), _call(device_id="d", position=50))

    @pytest.mark.asyncio
    async def test_success_awaits_delivery(self, monkeypatch):
        handler = RecHandler(result=True)
        self._patch(monkeypatch, handler)
        await handle_set_position(_FakeHass(), _call(device_id="d", position=50))
        assert handler.calls == [("5005X", "set_position", {"position": 50})]


async def _noop_coro():
    return None
