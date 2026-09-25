# -*- coding: utf-8 -*-
"""hub_client / number 的其余小修（一批已确证缺陷，逐条带变异可判据）。

1) `_send_lock` 建了从不用（死码），而状态上行与命令回执是两个并发 task 写同一条 ws；
2) `async_stop` 用 `except (CancelledError, Exception)` 把自己的取消信号也吞了；
3) 退避无 jitter ⇒ hub pod 重启后多台 agent 同步 5/10/20… 重试（惊群）；
4) `_session_once` 在进接收循环前 await 换码自检（HTTP 最坏 15s）⇒ 上线首 15s 下行命令不处理；
5) `_ensure_registered` 直接下标 data["instanceId"] ⇒ hub 回 ok:true 但缺字段时抛裸 KeyError；
6) number.py 的 `_state_key` 是死属性，还长得像"会读运行时值"，误导维护者。
"""
import asyncio
import inspect
import json
import time

import pytest

from custom_components.window_controller_gateway import hub_client as hc
from custom_components.window_controller_gateway import number as num


# ── 共用假对象 ───────────────────────────────────────────────────────
class Msg:
    type = 1                                            # aiohttp.WSMsgType.TEXT

    def __init__(self, data):
        self.data = data


class FakeWS:
    def __init__(self, incoming=None, hold=0.0):
        self.sent = []
        self.sent_at = []
        self._incoming = list(incoming or [])
        self._hold = hold

    async def send_json(self, obj):
        self.sent.append(obj)
        self.sent_at.append(time.monotonic())

    def __aiter__(self):
        async def gen():
            for item in self._incoming:
                yield item
            if self._hold:
                await asyncio.sleep(self._hold)
        return gen()


class FakeCM:
    def __init__(self, ws):
        self.ws = ws

    def __await__(self):
        async def _self():
            return self
        return _self().__await__()

    async def __aenter__(self):
        return self.ws

    async def __aexit__(self, *exc):
        return False


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload, self.status = payload, status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return self._payload


class FakeSession:
    def __init__(self, ws=None, register_payload=None):
        self.ws = ws or FakeWS()
        self.register_payload = register_payload or {
            "ok": True, "instanceId": "i1", "secret": "s" * 32, "bindCode": "123456"}
        self.posted = []
        self.closed = False

    def post(self, url, json=None):                                    # noqa: A002
        self.posted.append((url, json))
        return FakeResp(self.register_payload)

    def ws_connect(self, url, headers=None, heartbeat=None):
        return FakeCM(self.ws)

    async def close(self):
        self.closed = True


def _client(tmp_path, **kw):
    session = kw.pop("session", None) or FakeSession()
    c = hc.HubClient([], config_dir=str(tmp_path), session=session, **kw)
    c.instance_id, c._secret = "inst-1", "sec-1"
    c.bind_code, c._bind_code_at = "111111", time.time()
    return c, session


# ── 1) 出帧串行化 ────────────────────────────────────────────────────
def test_send_json_holds_the_write_lock(tmp_path):
    client, _ = _client(tmp_path)
    held = []

    class WS:
        async def send_json(self, obj):                                 # noqa: ARG002
            held.append(client._send_lock is not None and client._send_lock.locked())

    async def run():
        await client._send_json(WS(), {"t": "state"})

    asyncio.run(run())
    assert held == [True], "发送期间锁没被持有＝_send_lock 仍是死码"


def test_concurrent_senders_never_overlap(tmp_path):
    client, _ = _client(tmp_path)
    inside = {"n": 0}
    overlaps = []

    class WS:
        async def send_json(self, obj):
            inside["n"] += 1
            if inside["n"] > 1:
                overlaps.append(obj)
            await asyncio.sleep(0.02)
            inside["n"] -= 1

    async def run():
        await asyncio.gather(*[client._send_json(WS(), {"t": "state", "i": i}) for i in range(4)])

    asyncio.run(run())
    assert overlaps == [], "两个并发发送方交错了（今天靠 aiohttp 非压缩帧侥幸，deflate 一开就坏）"


def test_both_senders_go_through_the_single_exit():
    """结构钉：状态上行与命令回执都不得再直接 ws.send_json。"""
    for name in ("_flush_loop", "_session_once"):
        src = inspect.getsource(getattr(hc.HubClient, name))
        assert "ws.send_json" not in src, "%s 绕过了 _send_json（锁只在一处生效才有意义）" % name
        assert "_send_json(" in src, "%s 没走出帧唯一出口" % name


# ── 2) async_stop 不吞自己的取消 ──────────────────────────────────────
def test_async_stop_propagates_its_own_cancellation(tmp_path):
    """HA 停机路径会取消 async_stop 本身：那时必须把 CancelledError 传上去。"""
    client, _ = _client(tmp_path)

    async def stubborn():
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            await asyncio.sleep(0.2)        # 真实任务常有 finally 收尾，取消不是瞬时的
            raise

    async def run():
        client._task = asyncio.ensure_future(stubborn())
        await asyncio.sleep(0.01)
        stopper = asyncio.ensure_future(client.async_stop())
        await asyncio.sleep(0.05)
        stopper.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopper

    asyncio.run(run())


def test_plain_stop_does_not_raise_and_finishes_cleanup(tmp_path):
    """反过来：主动取消子任务的 CancelledError 不得被当成"自己被取消"传上去。"""
    client, session = _client(tmp_path)

    async def run():
        client._task = asyncio.ensure_future(asyncio.sleep(30))
        client.connected = True
        await client.async_stop()
        return client.connected

    assert asyncio.run(run()) is False
    src = inspect.getsource(hc.HubClient.async_stop)
    assert "except (asyncio.CancelledError, Exception)" not in src, \
        "又用一把 except 把取消信号吞了"


# ── 3) 抖动不得破坏地板语义 ──────────────────────────────────────────
def test_clean_close_uses_the_floor_without_jitter(tmp_path, monkeypatch):
    """干净断开＝约 1s 重连（不抖成 0，也不抖成 5s）：地板路径不许经过抖动函数。"""
    client, _ = _client(tmp_path)
    rounds = {"i": 0}

    def boom_delay(attempt):                                 # noqa: ARG001
        raise AssertionError("干净断开那条路不该调用 hub_reconnect_delay（会被抖动带偏）")

    async def fake_session():
        rounds["i"] += 1
        if rounds["i"] >= 3:
            client._stopping = True
        return True

    delays = []

    async def fake_sleep(seconds, is_stopping):
        delays.append(seconds)

    monkeypatch.setattr(hc, "hub_reconnect_delay", boom_delay)
    monkeypatch.setattr(client, "_session_once", fake_session)
    monkeypatch.setattr(hc, "interruptible_sleep", fake_sleep)
    asyncio.run(client._run_forever())
    assert delays == [hc.HUB_RECONNECT_FLOOR_S] * 2, delays


def test_jitter_constant_is_bounded():
    assert 0 < hc.HUB_RECONNECT_JITTER <= 0.5, "抖动太大就等于没有退避阶梯"
    assert all(hc.hub_reconnect_delay(n) >= hc.HUB_RECONNECT_FLOOR_S for n in range(-2, 25))


# ── 4) 上线自检不得阻塞接收循环 ──────────────────────────────────────
def test_receive_loop_is_not_blocked_by_the_bindcode_self_check(tmp_path, monkeypatch):
    """换码自检是 HTTP（最坏 HUB_HTTP_TIMEOUT_S=15s）：挡在接收循环前＝上线首 15s 命令不处理。"""
    monkeypatch.setattr(hc, "HUB_STATE_DEBOUNCE_S", 0.01)
    cmd = json.dumps({"t": "cmd", "cmdsn": "c1", "sn": "A1B2", "action": "control",
                      "params": {"attribute": "w_travel", "value": "10"}})
    ws = FakeWS(incoming=[Msg(cmd)], hold=0.2)

    async def control(sn, attribute, value):                             # noqa: ARG001
        return True

    client, _ = _client(tmp_path, session=FakeSession(ws=ws), control_fn=control)

    async def slow_renew():
        await asyncio.sleep(0.8)          # 模拟云端慢：旧实现会让回执等到它跑完

    client._renew_bind_code_if_stale = slow_renew
    started = time.monotonic()

    async def run():
        client._stopping = False
        client._state_dirty = asyncio.Event()
        await client._session_once()

    asyncio.run(run())
    replies = [(m, t) for m, t in zip(ws.sent, ws.sent_at) if m.get("t") == "cmd_result"]
    assert replies, "命令回执没发出：%s" % [m.get("t") for m in ws.sent]
    elapsed = replies[0][1] - started
    assert elapsed < 0.4, "回执被换码自检挡了 %.2fs（下行命令上线首 15s 不被处理）" % elapsed
    assert replies[0][0]["cmdsn"] == "c1"


# ── 5) 注册响应缺字段 ────────────────────────────────────────────────
def test_register_incomplete_response_raises_a_clear_error(tmp_path):
    """hub 回 ok:true 但缺凭据 ⇒ 明确的 RuntimeError，不是裸 KeyError（看着像本地 bug）。"""
    session = FakeSession(register_payload={"ok": True, "bindCode": "123456"})
    client = hc.HubClient([], config_dir=str(tmp_path), session=session)
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(client._ensure_registered())
    assert "register incomplete" in str(ei.value)
    assert not isinstance(ei.value, KeyError)
    assert client.instance_id is None, "半截响应不得留下半个身份（会被当成已注册）"


def test_register_rejected_still_reports_the_hub_err(tmp_path):
    session = FakeSession(register_payload={"ok": False, "err": "install_key"})
    client = hc.HubClient([], config_dir=str(tmp_path), session=session)
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(client._ensure_registered())
    assert "install_key" in str(ei.value)


# ── 6) number.py 死属性 ──────────────────────────────────────────────
def test_state_key_is_gone_and_divergence_is_documented():
    """`_state_key` 全仓无读取点，却长得像"会读设备回传值"——删掉并把刻意分叉写清。"""
    for cls in (num.WindowControllerRangeNumber, num.WindowControllerSpeedNumber,
                num.WindowControllerStrengthNumber):
        assert "_state_key" not in vars(cls), "%s 还带着死属性 _state_key" % cls.__name__
    assert "_state_key" not in inspect.getsource(num), "number.py 里仍有 _state_key 残留"
    doc = num.WindowControllerRangeNumber._update_state.__doc__ or ""
    assert "setpoint" in doc and "刻意分叉" in doc, \
        "_update_state 必须写明：HA 侧显示 setpoint、小程序侧显示设备回传值，这是刻意分叉"


def test_number_still_reads_setpoints_not_runtime_values():
    """正向钉（防"删死码"顺手改语义）：HA 滑块仍只显示 setpoint。"""
    src = inspect.getsource(num.WindowControllerRangeNumber._update_state)
    assert "_read_setpoint()" in src
    assert "attributes" not in src, "_update_state 不得改读设备上报值（网关空闲时上报 0，滑块会跳回 0）"
