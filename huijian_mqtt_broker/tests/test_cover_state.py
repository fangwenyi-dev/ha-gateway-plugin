"""v1.6.8 修复回归：cover.is_closed 由网关上报状态推导真实开/闭。

背景：v1.0.1 起 is_closed 写死 return None，导致 HA 标准 state 计算
（homeassistant/components/cover：is_closed=None → state=None）使
cover.state **永远输出 unknown**，Web 状态行、历史曲线、自动化、LLM
语义控制全部拿不到真实开/关。这里断言 is_closed 读 device_manager 缓存。
这是"静默失效面"——旧测试从不构造 device，故 is_closed 恒 None 也无人报错。
"""
import asyncio
from types import SimpleNamespace

from custom_components.window_controller_gateway.cover import WindowControllerCover
from custom_components.window_controller_gateway.const import (
    DEVICE_STATUS_OPEN,
    DEVICE_STATUS_CLOSED,
    DEVICE_STATUS_UNKNOWN,
    DEVICE_STATUS_CONNECTED,
)


class FakeDeviceManager:
    def __init__(self, status=None, attributes=None):
        self._device = None
        if status is not None:
            self._device = {"sn": "5005X", "status": status, "attributes": attributes or {}}
        self.updated = None

    def get_device(self, device_sn):
        return self._device

    async def update_device_status(self, device_sn, status, attributes=None):
        self.updated = (device_sn, status, attributes)


def _make_cover(status):
    return WindowControllerCover(
        hass=None,
        device_manager=FakeDeviceManager(status),
        mqtt_handler=None,
        gateway_sn="GW1",
        device_sn="5005X",
        device_name="窗",
    )


def _make_cover_attrs(status, attributes):
    return WindowControllerCover(
        hass=None,
        device_manager=FakeDeviceManager(status, attributes),
        mqtt_handler=None,
        gateway_sn="GW1",
        device_sn="5005X",
        device_name="窗",
    )


class TestIsClosed:
    def test_closed_when_device_status_closed(self):
        assert _make_cover(DEVICE_STATUS_CLOSED).is_closed is True

    def test_open_when_device_status_open(self):
        assert _make_cover(DEVICE_STATUS_OPEN).is_closed is False

    def test_none_when_unknown(self):
        # 未收到上报：返回 None（state 仍 unknown，但 Web 有 device_status 兜底）
        assert _make_cover(DEVICE_STATUS_UNKNOWN).is_closed is None

    def test_none_when_connected(self):
        assert _make_cover(DEVICE_STATUS_CONNECTED).is_closed is None

    def test_none_when_no_device(self):
        assert _make_cover(None).is_closed is None


class TestStatePositionSync:
    """用户定案：状态与位置同步——r_travel 0=关，>0=开。

    status 尚未有效（unknown/connected）但已收到 position 上报时，
    is_closed 必须直接按位置推导，否则出现「待上报 + 位置 65%」矛盾。
    """

    def test_position_zero_is_closed(self):
        c = _make_cover_attrs(DEVICE_STATUS_UNKNOWN, {"r_travel": 0})
        assert c.is_closed is True

    def test_position_positive_is_open(self):
        c = _make_cover_attrs(DEVICE_STATUS_UNKNOWN, {"r_travel": 40})
        assert c.is_closed is False

    def test_position_string_numeric_supported(self):
        c = _make_cover_attrs(DEVICE_STATUS_CONNECTED, {"r_travel": "0"})
        assert c.is_closed is True
        c2 = _make_cover_attrs(DEVICE_STATUS_CONNECTED, {"r_travel": "88"})
        assert c2.is_closed is False

    def test_explicit_status_takes_precedence_over_position(self):
        # status 已明确 closed 时即便 position 脏值仍以 status 为准
        c = _make_cover_attrs(DEVICE_STATUS_CLOSED, {"r_travel": 50})
        assert c.is_closed is True

    def test_no_position_still_none(self):
        c = _make_cover_attrs(DEVICE_STATUS_UNKNOWN, {})
        assert c.is_closed is None


class TestRestoreOnAdd:
    def _run_added(self, cover, last_state):
        cover.async_get_last_state = lambda: asyncio.sleep(0, result=last_state)
        asyncio.run(cover.async_added_to_hass())

    def test_restores_closed_state(self):
        cover = _make_cover(DEVICE_STATUS_UNKNOWN)
        self._run_added(cover, SimpleNamespace(state="closed", attributes={"position": 0}))
        sn, status, attrs = cover.device_manager.updated
        assert (sn, status) == ("5005X", DEVICE_STATUS_CLOSED)
        assert attrs == {"r_travel": 0}

    def test_restores_open_with_position(self):
        cover = _make_cover(DEVICE_STATUS_UNKNOWN)
        self._run_added(cover, SimpleNamespace(state="open", attributes={"position": 55}))
        assert cover.device_manager.updated[1] == DEVICE_STATUS_OPEN
        assert cover.device_manager.updated[2] == {"r_travel": 55}

    def test_does_not_overwrite_live_data(self):
        cover = _make_cover(DEVICE_STATUS_OPEN)  # 已有实时数据
        self._run_added(cover, SimpleNamespace(state="closed", attributes={"position": 0}))
        assert cover.device_manager.updated is None  # 未回写

    def test_ignores_non_open_closed_last_state(self):
        cover = _make_cover(DEVICE_STATUS_UNKNOWN)
        self._run_added(cover, SimpleNamespace(state="unknown", attributes={}))
        assert cover.device_manager.updated is None

    def test_no_last_state_no_write(self):
        cover = _make_cover(DEVICE_STATUS_UNKNOWN)
        self._run_added(cover, None)
        assert cover.device_manager.updated is None
