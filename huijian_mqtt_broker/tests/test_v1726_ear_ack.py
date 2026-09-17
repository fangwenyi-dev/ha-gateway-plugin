"""v1.7.26 耳朵级 001 代答（用户裁定 A）钉桩。

背景：固件首配期每 5s 重发 001 直到收到应答；旧链条中应答只在"条目转正 →
reload → 正式 handler 订阅"后发出，转正链断裂即无限重试风暴（客户现场实锤：
gateway 1001215011a3 首报 001 无人应答）。现耳朵（心跳监听器 + _protocol 他
网关分支）听到未配置网关的 001 绑定请求当场同型代答 {errcode:0}（不带 uuid，
uuid 仍归转正后的正式 handler——ack 契约规则 1 不变）。

守门面（静默失效面，CLAUDE.md 教训）：
- 谓词必须只放"001 且 data 无 errcode"——data 带 errcode 的 001 是网关对我方
  报文的回复，再答即成回环（契约规则 1）；002/005 不在耳朵层代答。
- 代答报文逐字：head/ctype/id 回带/sn 回带/data.errcode=0，且**不得含 uuid**。
- 两处接线位置：心跳监听器必须在"已配置 return"之后（已绑定网关由正式
  handler 应答，防双答）；_protocol 必须在 not already_configured 分支内。
"""
import json
from pathlib import Path

import pytest

import homeassistant.components.mqtt as fake_mqtt
from custom_components.window_controller_gateway.utils import (
    should_ear_ack_001, async_ack_gateway_001)

HERE = Path(__file__).resolve().parent
PKG = HERE.parent / "custom_components" / "window_controller_gateway"

GW = "1001215011a3"


# ============ 谓词：门必须精确 ============
class TestGate:
    @pytest.mark.parametrize("ctype,data,expected", [
        ("001", {"vesion": "V3.55", "model": "YGZN_GW001",
                 "userid": 0, "familyid": 0}, True),          # 首报绑定请求
        ("001", {}, True),                                      # 空 data 的 001 仍算请求
        ("001", {"errcode": 0}, False),                         # 规则1：网关回复不再答
        ("001", {"errcode": 5}, False),
        ("002", {"status": "online"}, False),                   # 002 不在耳朵层代答
        ("005", {"sn": "50022E010603"}, False),
        ("001", None, False),                                   # 非 dict 归一防御
        ("001", "x", False),
        (None, {}, False),
    ])
    def test_predicate(self, ctype, data, expected):
        assert should_ear_ack_001(ctype, data) is expected


# ============ helper：报文逐字与发布参数 ============
class _Hass:
    def __init__(self):
        self.data = {}


class _Pub:
    def __init__(self, fail=False):
        self.calls = []
        self._fail = fail

    async def __call__(self, hass, topic, payload, qos=0, retain=False):
        if self._fail:
            raise RuntimeError("broker down")
        self.calls.append((topic, json.loads(payload), qos, retain))


class TestAckHelper:
    @pytest.mark.asyncio
    async def test_payload_verbatim(self, monkeypatch):
        pub = _Pub()
        monkeypatch.setattr(fake_mqtt, "async_publish", pub)
        ok = await async_ack_gateway_001(_Hass(), GW, 118)
        assert ok is True
        topic, payload, qos, retain = pub.calls[0]
        assert topic == f"gateway/{GW}/req", "代答必须发到该 SN 的 req 主题"
        assert payload == {"head": "$SH", "ctype": "001", "id": 118,
                           "sn": GW, "data": {"errcode": 0}}, \
            "同型 echo：id/sn 回带，仅 errcode——uuid 归正式 handler"
        assert "uuid" not in payload["data"]
        assert qos == 1 and retain is False

    @pytest.mark.asyncio
    async def test_publish_failure_returns_false_no_raise(self, monkeypatch):
        monkeypatch.setattr(fake_mqtt, "async_publish", _Pub(fail=True))
        assert await async_ack_gateway_001(_Hass(), GW, 1) is False, \
            "代答失败不得抛出反噬发现主流程"


# ============ 接线位置：两处调用点 ============
class TestWiring:
    def test_heartbeat_listener_acks_after_configured_check(self):
        src = (PKG / "__init__.py").read_text(encoding="utf-8")
        i_ret = src.index('if e.data.get(CONF_GATEWAY_SN, "").lower() == response_sn.lower():')
        i_ack = src.index("should_ear_ack_001(payload.get(\"ctype\"), payload.get(\"data\"))")
        i_log = src.index("心跳监听器发现新网关")
        assert i_ret < i_ack < i_log, \
            "代答必须在『已配置 return』之后（防与正式 handler 双答）且触发发现前"
        assert "async_ack_gateway_001" in src[i_ack:i_log]

    def test_protocol_other_sn_branch_acks_inside_not_configured(self):
        src = (PKG / "mqtt_handler" / "_protocol.py").read_text(encoding="utf-8")
        i_branch = src.index("if not already_configured:")
        i_ack = src.index("should_ear_ack_001(ctype, data)")
        i_disc = src.index("from ..discovery import async_discover_gateway")
        assert i_branch < i_ack < i_disc, \
            "代答必须圈在 not already_configured 分支内（已配置他网关由其自身 handler 应答）"

    def test_handler_path_untouched(self):
        """转正后的 001 应答语义（含 uuid）归 _handle_ctype_001——本批不得触碰。"""
        src = (PKG / "mqtt_handler" / "_ctypes.py").read_text(encoding="utf-8")
        seg = src[src.index("async def _handle_ctype_001"):
                  src.index("async def _handle_ctype_002")]
        assert '"ctype": "001"' in seg and "self.instance_uuid" in seg
        assert "should_ear_ack_001" not in seg
