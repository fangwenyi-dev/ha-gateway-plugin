"""v1.7.33 全量审计修复批（D 组）：协议链加固。

钉桩清单（全部为只读审计实锤、修复在批 D）：
1. 心跳耳补入站尺寸闸（旧版只有 `_protocol` 耳有，而干净主机首配期只有
   心跳耳——一条大报文即在事件循环线程卡死 HA）；
2. 代答认领在发布失败时必须撤销（否则固件 5s 重发的同 id 请求在 TTL 内
   被全体耳朵抑制，止血目标反被放大成 6 次不应答）；
3. 订阅代际改用弱引用（裸 id 在 reload 后可能被新对象复用地址 → "client
   未变"假阴性 → B-1 形态复活且零日志）；
4. 订阅重建加并发闸（重连任务 × 30s 巡检并发进入 → 句柄互相覆盖、前一个
   回调永久泄漏 → 每条上报双份处理）；
5. 002 的 ack 先于全量批处理下发（旧序跨让出点，满负载超过 5s 去重窗后
   同一条 002 整批重跑）；
6. 接管 MQTT 条目时清除与明文内置 broker 不兼容的键（TLS/WebSocket），
   否则条目永久连不上且无纠偏出口；
7. `_schedule_async_task` 在 cleanup 闩锁后不再拉起新任务。
"""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.window_controller_gateway import const as c
import custom_components.window_controller_gateway.utils as u
import custom_components.window_controller_gateway.mqtt_handler as mh_mod
import custom_components.window_controller_gateway.mqtt_bootstrap as bs_mod
from custom_components.window_controller_gateway.mqtt_handler import (
    WindowControllerMQTTHandler,
)

PKG = Path(__file__).resolve().parents[1] / "custom_components" / "window_controller_gateway"
GW_SN = "100122501207"
DEV_SN = "500500000001"


class _Client:
    """可弱引用的 client 替身（SimpleNamespace 不支持弱引用，会走退化路径）。"""


class _Publisher:
    def __init__(self, order=None):
        self.published = []
        self.order = order if order is not None else []

    async def __call__(self, hass, topic, payload, qos=0, retain=False):
        p = json.loads(payload)
        self.published.append((topic, p))
        self.order.append(("publish", p.get("ctype"), p.get("data")))


class _DM:
    def __init__(self):
        self.devices = {}
        self.gateway_status = []

    def get_device(self, sn):
        return self.devices.get(sn)

    async def update_gateway_status(self, status):
        self.gateway_status.append(status)

    def _notify_status_listeners(self, sn):
        pass


class _Hass:
    def __init__(self, loop, mqtt_client=None):
        self.data = {c.DOMAIN: {}}
        self.loop = loop
        self.config = SimpleNamespace(config_dir=".")
        if mqtt_client is not None:
            self.data["mqtt"] = mqtt_client

    def async_create_task(self, coro):
        if self.loop is not None and self.loop.is_running():
            return self.loop.create_task(coro)
        coro.close()
        return None

    def add_job(self, job, *args):
        return job(*args) if callable(job) else None


def _mk(monkeypatch, mqtt_client=None, order=None):
    pub = _Publisher(order)
    monkeypatch.setattr(mh_mod.mqtt, "async_publish", pub)
    hass = _Hass(asyncio.get_running_loop(), mqtt_client)
    handler = WindowControllerMQTTHandler(hass, GW_SN, _DM())
    handler.gateway_sn = GW_SN
    return handler, pub


# ==================== 1. 入站尺寸闸（单点 + 双耳在场） ====================

class TestInboundSizeGate:
    def test_boundary(self):
        assert u.inbound_payload_ok(SimpleNamespace(payload=b"x" * (64 * 1024))) is True
        assert u.inbound_payload_ok(SimpleNamespace(payload=b"x" * (64 * 1024 + 1))) is False

    def test_nonstandard_payload_passes_through(self):
        """payload 非常规类型不得在闸上抛（交给下游归一/兜底）。"""
        assert u.inbound_payload_ok(SimpleNamespace(payload=None)) is True

    def test_heartbeat_ear_uses_shared_gate(self):
        src = (PKG / "__init__.py").read_text(encoding="utf-8")
        listener = src.split("async def _heartbeat_listener(msg):", 1)[1]
        listener = listener.split("async def ", 1)[0]
        assert "inbound_payload_ok(msg)" in listener, (
            "心跳耳未接共用入站闸——干净主机首配期只有这只耳，大报文直接卡死 HA"
        )
        idx_gate = listener.index("inbound_payload_ok(msg)")
        idx_loads = listener.index("json.loads(msg.payload)")
        assert idx_gate < idx_loads, "尺寸闸必须在 json.loads 之前"


# ==================== 2. 认领撤销 ====================

class TestEarAckClaimRelease:
    def _hass(self):
        return SimpleNamespace(data={c.DOMAIN: {}})

    def test_release_allows_reclaim(self):
        hass = self._hass()
        assert u.ear_ack_claim(hass, GW_SN, 7) is True
        assert u.ear_ack_claim(hass, GW_SN, 7) is False, "同 id 应被仲裁抑制"
        u.ear_ack_release(hass, GW_SN, 7)
        assert u.ear_ack_claim(hass, GW_SN, 7) is True, (
            "发布失败撤销后必须允许重新认领（否则 5s 重发持续被抑制）"
        )

    def test_release_is_case_insensitive(self):
        hass = self._hass()
        assert u.ear_ack_claim(hass, GW_SN, "9") is True
        u.ear_ack_release(hass, GW_SN.lower(), 9)
        assert u.ear_ack_claim(hass, GW_SN, "9") is True

    @pytest.mark.asyncio
    async def test_publish_failure_releases_claim(self, monkeypatch):
        hass = self._hass()
        calls = []

        async def fake_ack(_hass, _sn, _id):
            calls.append((_sn, _id))
            return False          # 发布失败

        monkeypatch.setattr(u, "async_ack_gateway_001", fake_ack)
        assert await u.async_ear_ack_001_arbitrated(hass, GW_SN, 11) is False
        assert len(calls) == 1
        assert u.ear_ack_claim(hass, GW_SN, 11) is True, (
            "发布失败未撤销认领 → 固件重发被抑制（止血目标反被放大）"
        )


# ==================== 3/4. 订阅代际与并发闸 ====================

class TestSubscriptionGeneration:
    @pytest.mark.asyncio
    async def test_same_client_no_rebuild_replaced_client_rebuilds(self, monkeypatch):
        client = _Client()
        handler, _ = _mk(monkeypatch, mqtt_client=client)
        subs = []

        async def fake_sub(hass, topic, cb, qos):
            subs.append(topic)
            return lambda: None

        monkeypatch.setattr(mh_mod.mqtt, "async_subscribe", fake_sub)
        assert await handler._subscribe_topics() is True
        assert len(subs) == 1
        assert await handler._ensure_mqtt_subscription() is False, \
            "同一 client 不应重建"
        handler.hass.data["mqtt"] = _Client()
        assert await handler._ensure_mqtt_subscription() is True, "换代必须重建"
        assert len(subs) == 2

    @pytest.mark.asyncio
    async def test_released_client_is_detected(self, monkeypatch):
        """旧 client 被释放（弱引用死亡）也必须判为换代。"""
        client = _Client()
        handler, _ = _mk(monkeypatch, mqtt_client=client)

        async def fake_sub(hass, topic, cb, qos):
            return lambda: None

        monkeypatch.setattr(mh_mod.mqtt, "async_subscribe", fake_sub)
        await handler._subscribe_topics()
        assert handler._mqtt_client_ref is not None, "应持弱引用"
        del client
        handler.hass.data.pop("mqtt", None)
        import gc
        gc.collect()
        assert await handler._ensure_mqtt_subscription() is False, \
            "client 缺席时不得空转重建（等它出现，下轮再判）"
        handler.hass.data["mqtt"] = _Client()
        assert await handler._ensure_mqtt_subscription() is True, \
            "旧引用已死 + 新 client 出现 = 换代，必须重建"

    @pytest.mark.asyncio
    async def test_concurrent_subscribe_is_rejected(self, monkeypatch):
        handler, _ = _mk(monkeypatch, mqtt_client=_Client())
        calls = []

        async def fake_sub(hass, topic, cb, qos):
            calls.append(topic)
            return lambda: None

        monkeypatch.setattr(mh_mod.mqtt, "async_subscribe", fake_sub)
        async with handler._sub_lock:
            assert await handler._subscribe_topics() is False, "并发进入必须被挡"
        assert calls == [], "被挡时不得发生第二次订阅（句柄覆盖面）"

    @pytest.mark.asyncio
    async def test_handle_handover_sets_new_before_cancelling_old(self, monkeypatch):
        handler, _ = _mk(monkeypatch, mqtt_client=_Client())
        events = []

        async def fake_sub(hass, topic, cb, qos):
            events.append("subscribe")
            return lambda: events.append("unsub")

        monkeypatch.setattr(mh_mod.mqtt, "async_subscribe", fake_sub)
        await handler._subscribe_topics()
        await handler._subscribe_topics()          # 第二次触发旧句柄退订
        assert events == ["subscribe", "subscribe", "unsub"], (
            "句柄交接必须是「先落新的、再退旧的」（旧序失败会留订阅空窗）"
        )

    @pytest.mark.asyncio
    async def test_non_weakrefable_client_falls_back_to_id(self, monkeypatch):
        """不可弱引用的替身（历史测试桩形态）退回身份整数路径，不得静默失能。"""
        old_client = SimpleNamespace()          # 持引用：防地址被新对象复用
        handler, _ = _mk(monkeypatch, mqtt_client=old_client)

        async def fake_sub(hass, topic, cb, qos):
            return lambda: None

        monkeypatch.setattr(mh_mod.mqtt, "async_subscribe", fake_sub)
        assert await handler._subscribe_topics() is True
        assert handler._mqtt_client_ref is None, "SimpleNamespace 不可弱引用"
        assert handler._mqtt_client_id is not None, "退化路径必须记下身份整数"
        assert await handler._ensure_mqtt_subscription() is False
        handler.hass.data["mqtt"] = _Client()
        assert await handler._ensure_mqtt_subscription() is True, "换代仍须识别"
        assert old_client is not None


# ==================== 5. 002 先应答后处理 ====================

class TestAckBeforeBatch:
    @pytest.mark.asyncio
    async def test_ack_precedes_batch_and_survives_batch_error(self, monkeypatch):
        order = []
        handler, pub = _mk(monkeypatch, order=order)

        async def slow_batch(tasks, label="处理"):
            order.append(("batch", label, None))
            for t in tasks:                    # 收尾未消费的协程，保持告警洁净
                if asyncio.iscoroutine(t):
                    t.close()
            raise RuntimeError("registry exploded")

        monkeypatch.setattr(handler, "_batch_process_tasks", slow_batch)
        payload = {"head": c.PROTOCOL_HEAD, "ctype": "002", "id": 5,
                   "sn": GW_SN, "data": {"status": "online",
                                         "devices": [{"sn": DEV_SN}]}}
        await handler._handle_ctype_002(payload, "002", payload["data"])

        kinds = [k for k, _c, _d in order]
        assert "publish" in kinds and "batch" in kinds
        assert kinds.index("publish") < kinds.index("batch"), (
            "002 必须先 ack 再批处理——否则满负载跨 5s 去重窗后整批重跑"
        )
        acks = [p for _t, p in pub.published
                if p.get("ctype") == "002" and p.get("data", {}).get("errcode") == 0]
        assert len(acks) == 1, "批处理异常也必须已 ack（契约：002 必 ack）"


# ==================== 6. 接管条目清洗不兼容键 ====================

class TestTakeoverPurgesIncompatibleKeys:
    @pytest.mark.asyncio
    async def test_tls_and_ws_keys_removed(self, monkeypatch):
        captured = {}

        class _Entry:
            entry_id = "e1"
            data = {"broker": "old.example", "port": 8883,
                    "certificate": "/ssl/ca.pem", "tls_insecure": True,
                    "transport": "websockets", "ws_path": "/mqtt",
                    "discovery": True}

        hass = SimpleNamespace(
            config_entries=SimpleNamespace(
                async_update_entry=lambda entry, data=None: captured.update(data or {})))

        async def _noop(*a, **k):
            return None

        monkeypatch.setattr(bs_mod, "async_reload_entry", _noop, raising=False)
        await bs_mod._update_mqtt_entry(hass, _Entry(), "127.0.0.1", 2022,
                                       "huijian", "huijian2022")
        for bad in ("certificate", "tls_insecure", "transport", "ws_path"):
            assert bad not in captured, f"{bad} 未清除——条目按 TLS/WS 连明文口必失败"
        assert captured["broker"] == "127.0.0.1" and captured["port"] == 2022
        assert captured.get("discovery") is True, "无关键不得误删"


# ==================== 7. cleanup 闩锁后不再派发 ====================

class TestClosingLatchBlocksDispatch:
    @pytest.mark.asyncio
    async def test_schedule_after_closing_is_dropped(self, monkeypatch):
        handler, pub = _mk(monkeypatch, mqtt_client=_Client())
        handler._closing = True
        ran = []

        async def job():
            ran.append(1)

        handler._schedule_async_task(job())
        await asyncio.sleep(0)
        assert ran == [], "cleanup 闩锁后不得再拉起新任务（逃过 A-6 快照）"

    @pytest.mark.asyncio
    async def test_cleanup_unsubscribes_before_first_await(self, monkeypatch):
        handler, _ = _mk(monkeypatch, mqtt_client=_Client())
        unsubbed = []

        async def fake_sub(hass, topic, cb, qos):
            return lambda: unsubbed.append(1)

        monkeypatch.setattr(mh_mod.mqtt, "async_subscribe", fake_sub)
        await handler._subscribe_topics()
        handler._check_task = asyncio.get_running_loop().create_task(asyncio.sleep(5))
        await handler.cleanup()
        assert unsubbed == [1], "cleanup 必须在首个 await 前退订（用尽订阅面早退）"
