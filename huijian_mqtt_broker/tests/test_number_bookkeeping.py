"""v1.6.10 审计 N9：number 命令已送达后，本地簿记失败不得回退 UI 显示。

场景：send_command 返回 True（命令已交付 broker）之后，成功分支还会做
setpoints 写入 + create_task(save_persistent_data)。此前这段位于外层 try
内——簿记抛错（如 hass 关闭期 async_create_task 抛 RuntimeError）会落入
外层 except 触发 _revert_to_saved()，把已经生效的滑块错误回弹。
契约：送达=成功；簿记失败仅告警；未送达才回退。
"""
import pytest

from custom_components.window_controller_gateway.number import (
    WindowControllerRangeNumber,
)


class _Handler:
    def __init__(self, success):
        self.success = success

    async def send_command(self, sn, command, params=None):
        return self.success


class _ExplodingDict(dict):
    """模拟 hass 关闭期 hass.data 操作抛错"""

    def setdefault(self, *args, **kwargs):
        raise RuntimeError("bound to a different event loop")


class _Hass:
    def __init__(self):
        self.data = _ExplodingDict()

    def async_create_task(self, coro):
        coro.close()
        return None


def _entity(handler, hass):
    e = WindowControllerRangeNumber.__new__(WindowControllerRangeNumber)
    e.hass = hass
    e.device_sn = "SN0123456789"
    e._command = "set_speed"
    e._param_key = "speed"
    e._entity_label = "速度"
    e._get_mqtt_handler = lambda: handler
    reverted = []
    e._revert_to_saved = lambda: reverted.append(1)
    return e, reverted


class TestNumberBookkeepingNoRevert:
    @pytest.mark.asyncio
    async def test_delivered_but_bookkeeping_fails_does_not_revert(self):
        e, reverted = _entity(_Handler(True), _Hass())
        await e._send_value(60)  # 不得抛出
        assert reverted == [], "命令已送达时簿记失败禁止回退（N9 回归钉）"

    @pytest.mark.asyncio
    async def test_undelivered_still_reverts(self):
        e, reverted = _entity(_Handler(False), _Hass())
        await e._send_value(60)
        assert reverted == [1], "未送达仍须回退显示（不得顺手改坏原语义）"
