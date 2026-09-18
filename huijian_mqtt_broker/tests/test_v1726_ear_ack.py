"""v1.7.26 耳朵级 001 代答（用户裁定 A）+ v1.7.27 格式定稿钉桩。

背景：固件首配期每 5s 重发 001 直到收到应答；旧链条中应答只在"条目转正 →
reload → 正式 handler 订阅"后发出，转正链断裂即无限重试风暴（客户现场实锤：
gateway 1001215011a3 首报 001 无人应答）。现耳朵（心跳监听器 + _protocol 他
网关分支）听到未配置网关的 001 绑定请求当场同型代答。

v1.7.27 定稿（用户 2026-09-17 实锤格式）：代答与正式 handler 应答**完全同形**
——data 必含 uuid（uuid5(NAMESPACE_DNS, config_dir) 确定性同值，公式上收
utils.gateway_instance_uuid 单一真源），固件只见一个指纹。

守门面（静默失效面，CLAUDE.md 教训）：
- 谓词必须只放"001 且 data 无 errcode"——data 带 errcode 的 001 是网关对我方
  报文的回复，再答即成回环（契约规则 1）；002/005 不在耳朵层代答。
- 代答报文逐字：head/ctype/id 回带/sn 回带/data={errcode:0, uuid:指纹}。
- 两处接线位置：心跳监听器必须在"已配置 return"之后（已绑定网关由正式
  handler 应答，防双答）；_protocol 必须在 not already_configured 分支内。
"""
import json
import uuid as uuid_mod
from pathlib import Path
from types import SimpleNamespace

import pytest

import homeassistant.components.mqtt as fake_mqtt
from custom_components.window_controller_gateway.utils import (
    should_ear_ack_001, async_ack_gateway_001, gateway_instance_uuid)

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
    def __init__(self, config_dir="."):
        self.data = {}
        self.config = SimpleNamespace(config_dir=config_dir)


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
        hass = _Hass()
        ok = await async_ack_gateway_001(hass, GW, 15)
        assert ok is True
        topic, payload, qos, retain = pub.calls[0]
        assert topic == f"gateway/{GW}/req", "代答必须发到该 SN 的 req 主题"
        assert payload == {"head": "$SH", "ctype": "001", "id": 15,
                           "sn": GW, "data": {
                               "errcode": 0,
                               "uuid": str(uuid_mod.uuid5(
                                   uuid_mod.NAMESPACE_DNS, "."))}}, \
            "v1.7.27 定稿：与用户实锤格式逐字一致（必带 uuid，与正式 handler 同值）"
        assert qos == 1 and retain is False

    @pytest.mark.asyncio
    async def test_uuid_deterministic_across_ear_and_handler(self, monkeypatch):
        """耳朵代答 uuid == 正式 handler instance_uuid（单一真源公式）。"""
        pub = _Pub()
        monkeypatch.setattr(fake_mqtt, "async_publish", pub)
        hass = _Hass(config_dir="/config")
        await async_ack_gateway_001(hass, GW, 1)
        ear_uuid = pub.calls[0][1]["data"]["uuid"]
        assert ear_uuid == gateway_instance_uuid(hass)
        assert ear_uuid == str(uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, "/config"))
        # 公式单一真源：_lifecycle 不再自带 uuid5 字面量
        src = (PKG / "mqtt_handler" / "_lifecycle.py").read_text(encoding="utf-8")
        assert "gateway_instance_uuid(hass)" in src
        assert "uuid.uuid5" not in src, "指纹公式必须收敛到 utils 单一真源"

    @pytest.mark.asyncio
    async def test_publish_failure_returns_false_no_raise(self, monkeypatch):
        monkeypatch.setattr(fake_mqtt, "async_publish", _Pub(fail=True))
        assert await async_ack_gateway_001(_Hass(), GW, 1) is False, \
            "代答失败不得抛出反噬发现主流程"


# ============ 接线位置：两处调用点 ============
class TestWiring:
    def test_heartbeat_listener_acks_after_configured_check(self):
        src = (PKG / "__init__.py").read_text(encoding="utf-8")
        # v1.7.31（A-3）：旧 for-e.data 内联判定重构为 entry_state_for_sn 三态
        # 门——本钉语义不变：代答必须在"configured 判定"之后、触发发现之前。
        i_ret = src.index('if _st == "configured":')
        assert "entry_state_for_sn(hass, response_sn)" in src[:i_ret], \
            "判定必须先于代答/发现"
        # v1.7.30 审计收编：本耳补 data 归一（旧两耳不对称——001 带 data:null
        # 时 _protocol 耳照答、本耳拒答；干净主机只有本耳，该形态风暴不止血）
        assert 'payload.get("data")' in src[i_ret:], "本耳必须先取原始 data 归一"
        assert "if not isinstance(_ear_data, dict):" in src[i_ret:]
        i_ack = src.index('should_ear_ack_001(payload.get("ctype"), _ear_data)')
        i_log = src.index("心跳监听器发现新网关")
        assert i_ret < i_ack < i_log, \
            "代答必须在『已配置 return』之后（防与正式 handler 双答）且触发发现前"
        assert "async_ear_ack_001_arbitrated" in src[i_ack:i_log], \
            "v1.7.30 ②：本耳必须走仲裁统一入口"
        # A-3：disabled 态=照答止血但短路发现（禁用卡片对用户是打扰）
        i_dret = src.index('return  # 代答已做；发现卡对禁用网关是打扰')
        assert i_ack < i_dret < i_log, \
            "disabled 必须先派发代答、再于触发发现前 return"
        assert '"_hb_disabled_logged"' in src, "disabled 态必须节流 WARNING 留痕"

    def test_protocol_other_sn_branch_acks_inside_not_configured(self):
        src = (PKG / "mqtt_handler" / "_protocol.py").read_text(encoding="utf-8")
        # v1.7.31（A-3）：三态门形态——"未配置分支"= _st != "configured"
        i_branch = src.index('if _st != "configured":')
        i_ack = src.index("should_ear_ack_001(ctype, data)")
        i_disc = src.index("from ..discovery import async_discover_gateway")
        assert i_branch < i_ack < i_disc, \
            "代答必须圈在未配置分支内（已配置他网关由其自身 handler 应答）"
        assert "async_ear_ack_001_arbitrated" in src[i_ack:i_disc], \
            "v1.7.30 ②：本耳必须走仲裁统一入口"
        assert src.count('if _st == "disabled":') == 2, \
            "A-3：本耳 disabled 留痕+代答后短路发现两处俱在"
        assert "代答已派发" in src[i_ack:i_disc] or "止血代答已派发" in src, \
            "disabled 态必须在代答之后、发现触发之前 return"

    def test_wiring_sites_never_publish_raw(self):
        """v1.7.30 ②反钉：两处耳朵不得绕过仲裁直接调 async_ack_gateway_001——
        绕过一行就让"1 请求 2~3 答"的实锤噪声面复活（仲裁只在入口生效）。"""
        for path in (PKG / "__init__.py", PKG / "mqtt_handler" / "_protocol.py"):
            src = path.read_text(encoding="utf-8")
            assert "async_ack_gateway_001" not in src, \
                f"{path.name} 必须只经 async_ear_ack_001_arbitrated 发布代答"

    def test_handler_path_untouched(self):
        """转正后的 001 应答语义（含 uuid）归 _handle_ctype_001——本批不得触碰。"""
        src = (PKG / "mqtt_handler" / "_ctypes.py").read_text(encoding="utf-8")
        seg = src[src.index("async def _handle_ctype_001"):
                  src.index("async def _handle_ctype_002")]
        assert '"ctype": "001"' in seg and "self.instance_uuid" in seg
        assert "should_ear_ack_001" not in seg
