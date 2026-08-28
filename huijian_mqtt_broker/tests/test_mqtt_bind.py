"""回归测试：003 绑定确认 — 手动配对应允许重新添加被手动删除的设备。

背景（2026-08-27 实测 bug）：设备曾在 HA 中被手动删除（进入
GLOBAL_MANUALLY_REMOVED_DEVICES），之后重新配对，网关返回 003 绑定成功
（errcode=0），但设备没有添加到集成中。

根因：_handle_ctype_003 的"设备复活守卫"无条件拦截手动删除列表中的设备，
即使本次是用户主动发起的 start_pairing（bind_op="bind"，is_manual_pairing=True）
——与 add_device 的 is_manual_pairing 语义矛盾，导致被删设备永远无法重新配对。

修复：仅当 bind_op 不是 "bind"（晚到的/自动的绑定确认）时才拒绝；
手动配对确认（bind_op="bind"）允许重新添加，并从手动删除列表移除该设备。
"""
import sys
import os
import types
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.window_controller_gateway.mqtt_handler import (
    WindowControllerMQTTHandler,
)
from custom_components.window_controller_gateway import const as c


class _MockDeviceManager:
    """最小 device_manager mock：只实现 003 处理路径用到的成员"""

    def __init__(self, devices=None, manually_removed=None):
        self.devices = devices if devices is not None else {}
        self._manually_removed_devices = set(manually_removed or [])
        self.added = []  # 记录 add_device 调用
        self.saved_removed = []  # 记录手动删除列表保存调用
        self._next_number = 1

    def get_device(self, device_sn):
        return self.devices.get(device_sn)

    def get_all_devices(self):
        return list(self.devices.values())

    def is_device_manually_removed(self, device_sn):
        return device_sn in self._manually_removed_devices

    def allocate_device_number(self):
        n = self._next_number
        self._next_number += 1
        return n

    def _save_manually_removed_devices(self):
        self.saved_removed.append(set(self._manually_removed_devices))

    async def add_device(self, device_sn, device_name, device_type, force=False, is_manual_pairing=False):
        self.added.append(
            {
                "sn": device_sn,
                "name": device_name,
                "type": device_type,
                "is_manual_pairing": is_manual_pairing,
            }
        )
        self.devices[device_sn] = {
            "sn": device_sn,
            "name": device_name,
            "type": device_type,
            "status": "connected",
            "attributes": {},
        }
        return device_sn


class _MockHass:
    def __init__(self):
        self.data = {c.DOMAIN: {}}
        self.loop = None
        self.config = types.SimpleNamespace(config_dir=".")

    def async_create_task(self, coro):
        return coro

    def add_job(self, job, *args):
        if callable(job):
            return job(*args)
        return None


def _make_handler(mock_dm, gateway_sn="100122501207"):
    hass = _MockHass()
    return WindowControllerMQTTHandler(hass, gateway_sn, mock_dm)


def _bind_payload(command_id, device_sn="50022E010603", errcode=0):
    """构造与真实固件一致的 003 绑定确认回复"""
    return {
        "head": c.PROTOCOL_HEAD,
        "ctype": "003",
        "id": command_id,
        "sn": "100122501207",
        "data": {"sn": device_sn, "errcode": errcode, "devtype": "curtain_ctr"},
    }


@pytest.mark.asyncio
async def test_manual_pairing_reattaches_manually_removed_device():
    """手动配对确认应允许重新添加被手动删除的设备（2026-08-27 修复）"""
    dm = _MockDeviceManager(manually_removed=["50022E010603"])
    handler = _make_handler(dm)

    # 模拟发送 start_pairing 时记录了 bind 方向（id=3）
    handler._record_bind_op(3, "bind")

    await handler._handle_ctype_003(_bind_payload(3), "003", _bind_payload(3)["data"])

    # 设备应被重新添加
    assert len(dm.added) == 1, f"设备应被添加，实际 added={dm.added}"
    assert dm.added[0]["sn"] == "50022E010603"
    assert dm.added[0]["is_manual_pairing"] is True
    # 应从手动删除列表移除
    assert "50022E010603" not in dm._manually_removed_devices
    assert dm.saved_removed, "应触发手动删除列表持久化保存"


@pytest.mark.asyncio
async def test_late_bind_confirmation_still_blocked_for_removed_device():
    """晚到的/自动的绑定确认（无 bind_op 匹配）仍不得复活手动删除的设备"""
    dm = _MockDeviceManager(manually_removed=["50022E010603"])
    handler = _make_handler(dm)

    # 不记录 bind_op：模拟网关主动发起/晚到的绑定确认
    await handler._handle_ctype_003(_bind_payload(99), "003", _bind_payload(99)["data"])

    assert dm.added == [], f"非手动配对的绑定确认不得添加设备，实际 added={dm.added}"
    assert "50022E010603" in dm._manually_removed_devices


@pytest.mark.asyncio
async def test_manual_pairing_adds_new_device_normally():
    """普通手动配对（设备不在手动删除列表）正常添加"""
    dm = _MockDeviceManager()
    handler = _make_handler(dm)

    handler._record_bind_op(5, "bind")
    await handler._handle_ctype_003(_bind_payload(5), "003", _bind_payload(5)["data"])

    assert len(dm.added) == 1
    assert dm.added[0]["sn"] == "50022E010603"


@pytest.mark.asyncio
async def test_unbind_confirmation_not_added():
    """解绑确认（bind_op=unbind）不得添加设备"""
    dm = _MockDeviceManager()
    handler = _make_handler(dm)

    handler._record_bind_op(7, "unbind", "50022E010603")
    await handler._handle_ctype_003(_bind_payload(7), "003", _bind_payload(7)["data"])

    assert dm.added == [], f"解绑确认不得添加设备，实际 added={dm.added}"


@pytest.mark.asyncio
async def test_pairing_timeout_handle_cleared_after_success():
    """配对成功（手动绑定确认）后应取消配对超时句柄并退出配对模式"""
    dm = _MockDeviceManager()
    handler = _make_handler(dm)
    handler.pairing_active = True
    # 用不可取消的假句柄：cancel() 置标记
    fake_handle = types.SimpleNamespace(cancelled=False)

    def _cancel():
        fake_handle.cancelled = True

    fake_handle.cancel = _cancel
    handler.pairing_timeout_handle = fake_handle

    handler._record_bind_op(9, "bind")
    await handler._handle_ctype_003(_bind_payload(9), "003", _bind_payload(9)["data"])

    assert fake_handle.cancelled, "配对超时句柄应被取消"
    assert handler.pairing_timeout_handle is None
    assert handler.pairing_active is False
