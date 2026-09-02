"""v1.6.11 审计第三轮修复批的钉桩测试（#2/#3/#4/#6）。

对应裁决：#2 迟到/非请求 003 不得掐掉当前配对会话（会话退出限定
bind_op=="bind"）；#3 cleanup 快照迭代防回调收缩列表跳项；#4 publish
失败置 connected=False 时同步 gateway_status("offline")（同族路径对齐）；
#6 config_flow 连接测试 mock 补齐 allocate_device_number 契约面。

#1（订阅永久失效）经查证为误报（HA 托管订阅自动重订阅），不设测试；
#5 为时钟源替换（time.time→monotonic），既有 003 处理用例已全链路过；
#7 cosmetic 未修。
"""
import asyncio

import pytest

import custom_components.window_controller_gateway.mqtt_handler as mh_mod
from custom_components.window_controller_gateway.mqtt_handler import (
    WindowControllerMQTTHandler,
)
from custom_components.window_controller_gateway.device_manager import (
    WindowControllerDeviceManager,
)
from custom_components.window_controller_gateway.config_flow import MockDeviceManager
from custom_components.window_controller_gateway import const as c

GW_SN = "100122501207"


class _MockDM:
    def __init__(self):
        self.devices = {}
        self._manually_removed_devices = set()
        self.status_updates = []
        self.added = []
        self._next_number = 1

    def get_device(self, sn):
        return self.devices.get(sn)

    def get_all_devices(self):
        return list(self.devices.values())

    def _notify_status_listeners(self, sn):
        # v1.6.17 联审F2：003 绑定确认后新增的 WS device_update 通知
        pass

    def is_device_manually_removed(self, sn):
        return sn in self._manually_removed_devices

    def allocate_device_number(self):
        n = self._next_number
        self._next_number += 1
        return n

    async def add_device(self, sn, name, typ=None, force=False, is_manual_pairing=False):
        self.added.append(sn)
        self.devices[sn] = {"sn": sn, "name": name, "status": "connected", "attributes": {}}
        return sn

    async def update_gateway_status(self, status):
        self.status_updates.append(status)

    def get_gateway_info(self):
        return {"name": "GW", "status": "online"}


class _Hass:
    def __init__(self, loop=None):
        self.data = {c.DOMAIN: {}}
        self.loop = loop
        self.config = __import__("types").SimpleNamespace(config_dir=".")

    def async_create_task(self, coro):
        if self.loop is not None and self.loop.is_running():
            return self.loop.create_task(coro)
        coro.close()
        return None

    def add_job(self, job, *args):
        if callable(job):
            return job(*args)
        return None


def _payload(cmd_id, device_sn, errcode=0):
    return {
        "head": c.PROTOCOL_HEAD,
        "ctype": "003",
        "id": cmd_id,
        "sn": GW_SN,
        "data": {"sn": device_sn, "errcode": errcode, "devtype": "curtain_ctr"},
    }


class TestLate003DoesNotEndCurrentSession:
    """审计 #2：会话退出（cancel 定时器/pairing_active 复位/状态恢复）必须
    限定在我们记账过的 bind（bind_op=="bind"）。"""

    @pytest.mark.asyncio
    async def test_unrecorded_late_003_keeps_pairing_session(self):
        dm = _MockDM()
        handler = WindowControllerMQTTHandler(_Hass(), GW_SN, dm)
        cancelled = []
        handler.pairing_active = True
        handler.pairing_timeout_handle = __import__("types").SimpleNamespace(
            cancel=lambda: cancelled.append(1)
        )
        p = _payload(77, "5002LATE0001")  # 未发起过的 id、设备不存在
        await handler._handle_ctype_003(p, "003", p["data"])
        assert dm.added == ["5002LATE0001"], "绑定确认事实仍须添加设备"
        assert handler.pairing_active is True, "迟到 003 不得退出当前配对会话"
        assert cancelled == [], "当前会话定时器不得被 cancel"
        assert dm.status_updates == [], "非我方发起不得改写网关状态机"

    @pytest.mark.asyncio
    async def test_recorded_bind_still_exits_session(self):
        # 回归护栏：我方发起的配对确认仍要立刻退出会话（N1 语义不回退）
        dm = _MockDM()
        handler = WindowControllerMQTTHandler(_Hass(), GW_SN, dm)
        handler.pairing_active = True
        handler.pairing_timeout_handle = None
        handler._record_bind_op(81, "bind")
        p = _payload(81, "5002NEW00001")
        await handler._handle_ctype_003(p, "003", p["data"])
        assert dm.added == ["5002NEW00001"]
        assert handler.pairing_active is False
        assert dm.status_updates == ["online"]


class TestCleanupSnapshotIteration:
    """审计 #3：cleanup 两个循环必须遍历快照——任务完成时的
    add_done_callback(remove)（见 :166）会在 await 让出控制权时原地收缩
    列表，索引迭代跳项。**跳项的后果**：被跳过任务的终态异常从未被
    await 消费（asyncio 只缓存不重放），"cleanup 后状态必无任务触碰"
    的保证被破。用 boom 任务（cancel 后改抛 ValueError）+ 日志计数做
    确定性红绿验证：修复后 6 条全消费，修复前首个 await 让出时列表被
    回调清空、其余 5 条漏消费。"""

    @pytest.mark.asyncio
    async def test_every_task_awaited_despite_removing_callbacks(self, caplog):
        import logging

        dm = WindowControllerDeviceManager.__new__(WindowControllerDeviceManager)
        dm._background_tasks = []
        dm.devices = {"x": 1}
        dm._device_registry_cache = None
        dm._device_added_callbacks = []
        dm._device_removed_callbacks = []
        dm._device_update_callbacks = {}

        async def boom_task():
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                raise ValueError("boom")

        tasks = []
        for i in range(6):
            t = asyncio.create_task(boom_task())
            # 复刻 :166 的真实回调：完成即从列表 remove
            t.add_done_callback(
                lambda tt: dm._background_tasks.remove(tt)
                if tt in dm._background_tasks else None
            )
            tasks.append(t)
            dm._background_tasks.append(t)

        # 让全部任务起步（协程进入 sleep 挂起）——未起步即 cancel 的任务
        # 协程直接 close，body 里的 except 合法不执行，测不到终态异常消费
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        with caplog.at_level(logging.DEBUG):
            await dm.cleanup()

        consumed = sum(
            1 for r in caplog.records if "后台任务取消异常" in r.getMessage()
        )
        assert consumed == 6, (
            f"每个任务的终态异常都必须被 await 消费（快照迭代回归钉）：{consumed}/6"
        )
        assert all(t.done() for t in tasks)
        assert dm._background_tasks == []


class TestPublishFailureAlignsGatewayStatus:
    """审计 #4：publish 异常置 connected=False 的同一分支必须同步
    gateway_status("offline")——与 check_connection/重连放弃路径对齐。"""

    @pytest.mark.asyncio
    async def test_publish_exception_sets_offline(self, monkeypatch):
        dm = _MockDM()
        loop = asyncio.get_running_loop()
        handler = WindowControllerMQTTHandler(_Hass(loop=loop), GW_SN, dm)
        handler.connected = True

        async def boom(*args, **kwargs):
            raise RuntimeError("broker client gone")

        monkeypatch.setattr(mh_mod.mqtt, "async_publish", boom)
        ok = await handler.send_command(GW_SN, "start_pairing")
        assert ok is False
        assert handler.connected is False
        # 给 _schedule_async_task 的 create_task 一个执行回合
        await asyncio.sleep(0)
        assert dm.status_updates == ["offline"], (
            "publish 失败路径的 gateway_status 同步缺失（#4 回归钉）"
        )


class TestConfigFlowMockContract:
    """审计 #6：连接测试期 mock 必须覆盖 _quick_add_device 用到的契约面。"""

    def test_mock_has_allocate_device_number(self):
        assert MockDeviceManager().allocate_device_number() == 1
