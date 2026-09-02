"""协议 ack 方向契约钉桩测试（2026-09-02 用户定案五条规则）。

权威契约（用户 2026-09-02 给出，与 mqtt_handler._send_ack 文档一致）：
1. 001 网关注册 —— 网关主动发起，HA 响应 1 次；网关若回复 001（带 errcode）
   则属于"网关对我方报文的回复"，HA 不再回复。
2. 002 网关状态上报 —— 网关主动发起，HA 响应 1 次（不 ack 网关每 2s 重发，
   实证见 matter-broker app_protocol_bridge.cpp:359 注释）。
3. 003 绑定/解绑 —— HA 主动发起，网关回复后 HA **不再回复**。
4. 004 设备控制 —— HA 主动发起，网关回复后 HA **不再回复**（回复会被网关
   误当新命令造成循环）。
5. 005 设备上报 —— 网关主动发起，HA 响应 1 次。
6. 006/007 —— 同 004，HA 主动发起命令的网关回复，一律不再回复。

背景：客户抓包核对 $SH 协议流量时指出"网关回复的消息，HA 不用再次下发"。
本文件把 3/4/6 的零回复与 1/2/5 的恰好一次回复全部钉死——这类"静默多/漏
回复面"一旦回归只能靠抓包发现，必须有断言实参的测试守护（CLAUDE.md 教训）。

002 的方向细分说明：解绑确认（data={}）形态的 002 也统一 ack——网关 002
外发通道不区分来源，未收 ack 即重发；漏 ack 的代价（2s 重传风暴）远大于
多一条 ack。此行为由本测试显式钉住，改动需先与客户固件对拍。
"""
import json
from types import SimpleNamespace

import pytest

import custom_components.window_controller_gateway.mqtt_handler as mh_mod
from custom_components.window_controller_gateway.mqtt_handler import (
    WindowControllerMQTTHandler,
)
from custom_components.window_controller_gateway import const as c

GW_SN = "100122501203"
DEV_SN = "50022E010603"


class _Hass:
    def __init__(self):
        self.data = {c.DOMAIN: {}}
        self.config = SimpleNamespace(config_dir=".")

    def async_create_task(self, coro):
        coro.close()
        return None

    def add_job(self, job, *args):
        if callable(job):
            return job(*args)
        return None


class _MockDM:
    def __init__(self):
        self.devices = {}
        self._manually_removed_devices = set()
        self.status_updates = []

    def get_device(self, sn):
        return self.devices.get(sn)

    def get_all_devices(self):
        return list(self.devices.values())

    def is_device_manually_removed(self, sn):
        return sn in self._manually_removed_devices

    def allocate_device_number(self):
        return 1

    async def add_device(self, sn, name, typ=None, force=False, is_manual_pairing=False):
        self.devices[sn] = {"sn": sn, "name": name, "status": "connected",
                            "attributes": {}, "last_update": 0}

    async def update_gateway_status(self, status):
        self.status_updates.append(status)

    async def update_device_status(self, sn, status, attributes=None):
        pass

    def get_gateway_info(self):
        return {"name": "GW", "status": "online"}


class _Publisher:
    def __init__(self):
        self.published = []

    async def __call__(self, hass, topic, payload, qos=0, retain=False):
        self.published.append((topic, json.loads(payload)))

    def by_ctype(self, ctype):
        return [p for _, p in self.published if p.get("ctype") == ctype]


def _mk(monkeypatch):
    pub = _Publisher()
    monkeypatch.setattr(mh_mod.mqtt, "async_publish", pub)
    handler = WindowControllerMQTTHandler(_Hass(), GW_SN, _MockDM())
    return handler, pub


def _envelope(ctype, msg_id, data):
    return {"head": c.PROTOCOL_HEAD, "ctype": ctype, "id": msg_id,
            "sn": GW_SN, "data": data}


# ============ 规则 1：001 网关主动发起 → 恰好 1 次响应；001 回复 → 不回复 ============
class TestRule001:
    @pytest.mark.asyncio
    async def test_gateway_initiated_bind_gets_exactly_one_reply_with_uuid(
            self, monkeypatch):
        handler, pub = _mk(monkeypatch)
        payload = _envelope("001", 5, {"vesion": "1.4.2", "model": "GW"})
        await handler._handle_ctype_001(payload, "001", payload["data"])
        replies = pub.by_ctype("001")
        assert len(replies) == 1, "网关主动注册必须恰好响应 1 次"
        assert replies[0]["id"] == 5
        assert replies[0]["data"].get("uuid") == handler.instance_uuid
        assert replies[0]["data"].get("errcode") == 0

    @pytest.mark.asyncio
    async def test_001_reply_is_not_acked(self, monkeypatch):
        """data 带 errcode 的 001 是网关对我方报文的回复——不得再回复。"""
        handler, pub = _mk(monkeypatch)
        payload = _envelope("001", 6, {"errcode": 0})
        await handler._handle_ctype_001(payload, "001", payload["data"])
        assert pub.published == [], "对网关的 001 回复不得再次下发任何消息"


# ============ 规则 2：002 网关主动上报 → 恰好 1 次 ack ============
class TestRule002:
    @pytest.mark.asyncio
    async def test_status_report_acked_exactly_once(self, monkeypatch):
        handler, pub = _mk(monkeypatch)
        payload = _envelope("002", 7, {"status": "online", "devices": []})
        await handler._handle_ctype_002(payload, "002", payload["data"])
        acks = pub.by_ctype("002")
        assert len(acks) == 1 and acks[0]["id"] == 7 and acks[0]["data"]["errcode"] == 0

    @pytest.mark.asyncio
    async def test_empty_data_002_still_acked(self, monkeypatch):
        """解绑确认形态（data={}）也 ack——网关 002 外发通道未收 ack 即 2s 重发，
        行为显式钉住；如需豁免必须先与网关固件对拍确认不再重传。"""
        handler, pub = _mk(monkeypatch)
        payload = _envelope("002", 8, {})
        await handler._handle_ctype_002(payload, "002", payload["data"])
        assert len(pub.by_ctype("002")) == 1

    @pytest.mark.asyncio
    async def test_002_poison_still_acked(self, monkeypatch):
        """异常路径（devices 非列表）ack 仍必达——防重传风暴的整体兜底。"""
        handler, pub = _mk(monkeypatch)
        payload = _envelope("002", 9, {"status": "online", "devices": 5})
        await handler._handle_ctype_002(payload, "002", payload["data"])
        assert len(pub.by_ctype("002")) == 1


# ============ 规则 3：003 是网关对 HA 命令的回复 → HA 一律不再回复 ============
class TestRule003:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("data", [
        {"sn": DEV_SN, "errcode": 0, "bind": 1},      # 绑定成功
        {"sn": DEV_SN, "errcode": 0, "bind": 0},      # 解绑成功
        {"sn": DEV_SN, "errcode": 5},                  # 失败回复
        {"errcode": 0},                                # 无 sn 的异常回复
    ], ids=["bind", "unbind", "errcode5", "no_sn"])
    async def test_003_reply_never_acked(self, monkeypatch, data):
        handler, pub = _mk(monkeypatch)
        payload = _envelope("003", 10, data)
        await handler._handle_ctype_003(payload, "003", data)
        assert pub.published == [], "003 回复绝不允许再次下发（规则 3）"

    @pytest.mark.asyncio
    async def test_bind_success_still_adds_device_without_reply(self, monkeypatch):
        """零回复不得牺牲绑定处理本体。"""
        handler, pub = _mk(monkeypatch)
        payload = _envelope("003", 11, {"sn": DEV_SN, "errcode": 0})
        await handler._handle_ctype_003(payload, "003", payload["data"])
        assert DEV_SN in handler.device_manager.devices
        assert pub.published == []


# ============ 规则 4：004 是网关对 HA 控制命令的回复 → 不再回复 ============
class TestRule004:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("data", [
        {"sn": DEV_SN, "errcode": 0},                  # 用户抓包实证形态
        {"errcode": 0},
        {"sn": DEV_SN, "errcode": 7},                  # 通讯距离失败
        {"sn": DEV_SN, "errcode": 1},                  # 通用失败
    ], ids=["ok_dev", "ok_nodn", "err7", "err1"])
    async def test_004_reply_never_acked(self, monkeypatch, data):
        handler, pub = _mk(monkeypatch)
        payload = _envelope("004", 20, data)
        await handler._handle_ctype_004(payload, "004", data)
        assert pub.published == [], "004 回复再 ack 会被网关误当新命令形成循环（规则 4）"


# ============ 规则 5：005 设备上报（网关主动）→ 恰好 1 次 ack ============
class TestRule005:
    @pytest.mark.asyncio
    async def test_report_acked_exactly_once(self, monkeypatch):
        handler, pub = _mk(monkeypatch)
        handler.device_manager.devices[DEV_SN] = {
            "sn": DEV_SN, "status": "open", "attributes": {}, "last_update": 0}
        payload = _envelope("005", 110, {
            "sn": DEV_SN, "attrs": [{"attribute": "r_travel", "value": "50"}],
            "rssi": 65502})                            # 用户抓包实证形态
        await handler._handle_ctype_005(payload, "005", payload["data"])
        acks = pub.by_ctype("005")
        assert len(acks) == 1 and acks[0]["id"] == 110
        assert acks[0]["sn"] == GW_SN and acks[0]["data"]["errcode"] == 0


# ============ 规则 6：006/007 回复 → 不再下发 ============
class TestRule006007:
    @pytest.mark.asyncio
    async def test_006_reply_never_acked(self, monkeypatch):
        handler, pub = _mk(monkeypatch)
        payload = _envelope("006", 12, {"errcode": 0})
        await handler._handle_ctype_006(payload, "006", payload["data"])
        assert pub.published == []

    @pytest.mark.asyncio
    async def test_007_reply_never_acked(self, monkeypatch):
        handler, pub = _mk(monkeypatch)
        payload = _envelope("007", 13, {"errcode": 3})
        await handler._handle_ctype_007(payload, "007", payload["data"])
        assert pub.published == []
