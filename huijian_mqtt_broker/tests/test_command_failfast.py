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
    handle_transfer_device,
    handle_check_gateway_status,
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
        self.aborted = 0
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

    def abort_pairing_if_active(self):
        # 镜像真实 MqttHandler.abort_pairing_if_active（v1.6.10 审计 B2）
        self.aborted += 1
        if self.pairing_timeout_handle is not None:
            self.pairing_timeout_handle = None
        if self.pairing_active:
            self.pairing_active = False
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


# ================= v1.6.10 审计批次（B1/B2/B3）=================


class TestStartPairingStuckRecovery:
    """审计 B2（P1）：再次点配对时旧超时定时器先被 cancel；若发送失败抛错，
    pairing_active 残留上次成功置的 True 且无人再清 → 网关永久卡「配对中」。
    契约：start_pairing 所有失败路径必须先调 abort_pairing_if_active 复位。"""

    def _patch(self, monkeypatch, handler, dm=None):
        data = {"mqtt_handler": handler}
        if dm is not None:
            data["device_manager"] = dm
        monkeypatch.setattr(services_mod, "find_gateway_by_device_id",
                            lambda hass, did: (data, "GW1"))

    @pytest.mark.asyncio
    async def test_second_click_failure_resets_leftover(self, monkeypatch):
        # 第一次配对成功：pairing_active=True 且挂了超时句柄
        handler = RecHandler(result=True)
        self._patch(monkeypatch, handler,
                    dm=SimpleNamespace(update_gateway_status=lambda s: _noop_coro()))
        await handle_start_pairing(_FakeHass(), _call(device_id="x"))
        assert handler.pairing_active is True
        assert handler.pairing_timeout_handle is not None
        # 第二次点击时链路断（网关已离线）：raise + 残留必须被清理
        handler._result = False
        with pytest.raises(ServiceValidationError):
            await handle_start_pairing(_FakeHass(), _call(device_id="x"))
        assert handler.aborted >= 1
        assert handler.pairing_active is False, "配对中状态卡死回归"

    @pytest.mark.asyncio
    async def test_send_exception_path_also_resets(self, monkeypatch):
        handler = RecHandler(exc=ConnectionError("down"))
        handler.pairing_active = True  # 上次成功的残留
        self._patch(monkeypatch, handler)
        with pytest.raises(ServiceValidationError):
            await handle_start_pairing(_FakeHass(), _call(device_id="x"))
        assert handler.aborted >= 1
        assert handler.pairing_active is False


class TestAbortPairingHelper:
    """真实 MqttHandler.abort_pairing_if_active 单元语义（幂等、双态）。"""

    def _bare_handler(self, active, with_handle):
        from custom_components.window_controller_gateway.mqtt_handler import (
            WindowControllerMQTTHandler as MqttHandler,
        )
        h = MqttHandler.__new__(MqttHandler)  # 绕开 __init__，仅测助手方法
        h.pairing_active = active
        cancelled = []
        h.pairing_timeout_handle = (
            SimpleNamespace(cancel=lambda: cancelled.append(1)) if with_handle else None
        )
        h._status_callbacks = {}
        h.hass = None            # hass/device_manager 缺席 → 跳过错落恢复分支
        h.device_manager = None
        h.connected = False
        return h, cancelled

    def test_active_path_cancels_and_resets(self):
        h, cancelled = self._bare_handler(active=True, with_handle=True)
        h.abort_pairing_if_active()
        assert cancelled == [1]
        assert h.pairing_timeout_handle is None
        assert h.pairing_active is False

    def test_noop_when_not_active(self):
        h, cancelled = self._bare_handler(active=False, with_handle=False)
        h.abort_pairing_if_active()  # 不得抛
        assert cancelled == []
        assert h.pairing_active is False

    def test_idempotent_double_call(self):
        h, cancelled = self._bare_handler(active=True, with_handle=True)
        h.abort_pairing_if_active()
        h.abort_pairing_if_active()  # 第二次仅重复 cancel 判定（handle 已 None）
        assert cancelled == [1]
        assert h.pairing_active is False


class _TransferDM:
    def __init__(self, result=None, exc=None):
        self.result, self.exc = result, exc
        self.called = None

    async def transfer_device(self, sn, gsn):
        self.called = (sn, gsn)
        if self.exc is not None:
            raise self.exc
        return self.result


class TestTransferDeviceFailfast:
    """审计 B1（P1）：transfer 已注册可达，执行 False/异常此前仅日志 → 200 假成功。"""

    def _hass(self, dm):
        return SimpleNamespace(data={services_mod.DOMAIN: {
            # 方法1解析：device_id 直接命中映射表
            "device_to_gateway_mapping": {"SN0123456789A": "GW1"},
            "entry1": {"device_manager": dm},
        }})

    @pytest.mark.asyncio
    async def test_execution_false_raises(self):
        dm = _TransferDM(result=False)
        with pytest.raises(ServiceValidationError):
            await handle_transfer_device(
                self._hass(dm), _call(device_id="SN0123456789A", new_gateway_sn="GW2"))
        assert dm.called == ("SN0123456789A", "GW2")

    @pytest.mark.asyncio
    async def test_execution_exception_raises(self):
        dm = _TransferDM(exc=RuntimeError("boom"))
        with pytest.raises(ServiceValidationError):
            await handle_transfer_device(
                self._hass(dm), _call(device_id="SN0123456789A", new_gateway_sn="GW2"))

    @pytest.mark.asyncio
    async def test_success_no_raise(self):
        dm = _TransferDM(result=True)
        await handle_transfer_device(
            self._hass(dm), _call(device_id="SN0123456789A", new_gateway_sn="GW2"))
        assert dm.called == ("SN0123456789A", "GW2")


class _CheckH:
    def __init__(self, exc=None, connected=True):
        self.exc, self.connected = exc, connected

    async def check_connection(self):
        if self.exc is not None:
            raise self.exc
        return self.connected


class TestCheckGatewayStatusFailfast:
    """审计 B3（P2）：check 执行异常此前仅日志 → 200「已发送」。
    注意语义边界：check_connection 返回 False 是合法检查结果（离线），不抛。"""

    def _hass(self, h):
        return SimpleNamespace(data={services_mod.DOMAIN: {
            "entry1": {
                "gateway_sn": "GW1",
                "mqtt_handler": h,
                "device_manager": SimpleNamespace(get_gateway_info=lambda: {"name": "G"}),
            },
        }})

    @pytest.mark.asyncio
    async def test_exception_raises(self):
        with pytest.raises(ServiceValidationError):
            await handle_check_gateway_status(self._hass(_CheckH(exc=ConnectionError())), _call(gateway_sn="gw1"))

    @pytest.mark.asyncio
    async def test_offline_result_no_raise(self):
        await handle_check_gateway_status(self._hass(_CheckH(connected=False)), _call(gateway_sn="GW1"))
