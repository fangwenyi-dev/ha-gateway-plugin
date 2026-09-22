"""hub_client 单测：出站客户端的关键语义（重连退避 / 切片睡眠 / 值校验 / 命令回执 /
身份持久化 / 状态条目不回显凭据）。全部用假对象，不打网络。"""
import ast
import asyncio
import inspect
import json
import os
import time

from custom_components.window_controller_gateway import hub_client as hc


# ── 纯函数 ────────────────────────────────────────────────────────
def test_reconnect_delay_is_exponential_capped():
    assert hc.hub_reconnect_delay(1) == 5.0
    assert hc.hub_reconnect_delay(2) == 10.0
    assert hc.hub_reconnect_delay(3) == 20.0
    assert hc.hub_reconnect_delay(20) == hc.HUB_RECONNECT_MAX_S     # 封顶 300s
    assert hc.hub_reconnect_delay(0) == 5.0                        # 0/负数按首次


def test_sleep_slices_and_yields_when_stopping(monkeypatch):
    monkeypatch.setattr(hc, "HUB_SLEEP_SLICE_S", 0.01)
    calls = {"n": 0}

    async def run():
        # 未停机：600s 只睡 3 片就人为停机（证明是切片睡、不是整睡）
        async def fake_sleep(_s):
            calls["n"] += 1
            if calls["n"] >= 3:
                state["stopping"] = True
        monkeypatch.setattr(hc.asyncio, "sleep", fake_sleep)
        state = {"stopping": False}
        await hc.interruptible_sleep(600, lambda: state["stopping"])
        assert calls["n"] == 3

    asyncio.run(run())


def test_cred_brief_never_echoes_plaintext():
    assert hc.cred_brief("31fe26cacbbefded") == "len=16 head=31"
    assert hc.cred_brief("") == "(空)"
    assert hc.cred_brief(None) == "(空)"
    assert "31fe" not in hc.cred_brief("31fe")[6:]                 # 只留首两字节


def test_validate_control_params_matches_lan_semantics():
    assert hc.validate_control_params("w_travel", "100") == "100"
    assert hc.validate_control_params("w_travel", 100) == "100"
    assert hc.validate_control_params("w_travel", 1.5) == "1.5"
    assert hc.validate_control_params("w_travel", -1) == "-1"
    # 拒：空属性 / 空串值 / bool / 容器 / nan / inf / 科学计数（设备不可解析）
    assert hc.validate_control_params("", "100") is None
    assert hc.validate_control_params("w_travel", "") is None
    assert hc.validate_control_params("w_travel", None) is None
    assert hc.validate_control_params("w_travel", True) is None
    assert hc.validate_control_params("w_travel", {"a": 1}) is None
    assert hc.validate_control_params("w_travel", float("nan")) is None
    assert hc.validate_control_params("w_travel", float("inf")) is None
    assert hc.validate_control_params("w_travel", 1e308) is None


def test_identity_roundtrip_and_corrupt_file(tmp_path):
    d = str(tmp_path)
    assert hc.load_identity(d) == {}
    hc.save_identity(d, {"instanceId": "abc123", "secret": "s" * 48, "bindCode": "012345"})
    got = hc.load_identity(d)
    assert got["instanceId"] == "abc123" and got["bindCode"] == "012345"
    with open(hc.identity_path(d), "w", encoding="utf-8") as fh:
        fh.write("{ 坏 json")
    assert hc.load_identity(d) == {}                                  # 损坏按未注册
    assert os.path.exists(hc.identity_path(d) + ".bad")               # 且留证


# ── 假对象 ────────────────────────────────────────────────────────
class FakeManager:
    def __init__(self, devices=None, gateway_sn="GW1"):
        self.devices = devices if devices is not None else {
            "A1B2": {"attributes": {"r_travel": 30, "voltage": 12.3}},
        }
        self.gateway_sn = gateway_sn
        self.listeners = []

    def add_status_listener(self, cb):
        if cb not in self.listeners:
            self.listeners.append(cb)

    def remove_status_listener(self, cb):
        if cb in self.listeners:
            self.listeners.remove(cb)


class FakeWS:
    def __init__(self, incoming=None, hold=0.0):
        self.sent = []
        self._incoming = list(incoming or [])
        self._hold = hold

    async def send_json(self, obj):
        self.sent.append(obj)

    def __aiter__(self):
        async def gen():
            for item in self._incoming:
                yield item
            if self._hold:                      # 会话别立刻断：给上行协程留出发帧窗口
                await asyncio.sleep(self._hold)
        return gen()


class FakeCM:
    def __init__(self, ws):
        self.ws = ws

    async def __aenter__(self):
        return self.ws

    async def __aexit__(self, *exc):
        return False


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return self._payload


class FakeSession:
    def __init__(self, register_payload=None, ws=None):
        self.register_payload = register_payload or {
            "ok": True, "instanceId": "9f5e4f116b05b4c3",
            "secret": "31fe26cacbbefdedc6faa8f0eeec26ad202ed61f320a65ca", "bindCode": "251562",
        }
        self.ws = ws or FakeWS()
        self.posted = []
        self.closed = False

    def post(self, url, json=None):                                    # noqa: A002 - aiohttp 同签名
        self.posted.append((url, json))
        return FakeResp(self.register_payload)

    def ws_connect(self, url, heartbeat=None):                         # noqa: ARG002
        self.ws_url = url
        return FakeCM(self.ws)

    async def close(self):
        self.closed = True


def make_client(tmp_path, **kw):
    manager = kw.pop("manager", None) or FakeManager()
    session = kw.pop("session", None) or FakeSession()
    client = hc.HubClient(manager, config_dir=str(tmp_path), session=session, **kw)
    return client, manager, session


# ── 行为 ──────────────────────────────────────────────────────────
def test_register_persists_identity_and_keeps_bind_code_out_of_logs(tmp_path, caplog):
    client, _, session = make_client(tmp_path)

    asyncio.run(client._ensure_registered())

    assert client.instance_id == "9f5e4f116b05b4c3"
    assert client.bind_code == "251562"
    assert session.posted[0][0].endswith("/agent/register")
    assert session.posted[0][1]["installKey"] == hc.HUB_DEFAULT_INSTALL_KEY
    saved = hc.load_identity(str(tmp_path))
    assert saved["secret"] == client._secret                            # 身份落盘（重启复用）
    logs = " ".join(r.getMessage() for r in caplog.records)
    assert "251562" not in logs and client._secret[:8] not in logs       # 凭据不回显


def test_register_not_repeated_when_identity_exists(tmp_path):
    hc.save_identity(str(tmp_path), {"instanceId": "abc", "secret": "s" * 32, "bindCode": "000111"})
    client, _, session = make_client(tmp_path)

    asyncio.run(client._ensure_registered())

    assert session.posted == []                                         # 有身份就不再注册
    assert client.instance_id == "abc"


def test_ws_url_switches_scheme(tmp_path):
    client, _, _ = make_client(tmp_path)
    client.instance_id, client._secret = "abc", "def"
    assert client._ws_url().startswith("wss://")
    client.base = "http://127.0.0.1:8080"
    assert client._ws_url().startswith("ws://127.0.0.1:8080/agent/ws?instanceId=abc&secret=def")


def test_collect_state_items_uses_injected_view_and_survives_bad_entries(tmp_path):
    manager = FakeManager(devices={"A1B2": {"attributes": {"wind_lock_mode": 1}}, "BAD": {}})

    def builder(sn, gw, dev):
        if sn == "BAD":
            raise ValueError("坏条目")
        return {"sn": sn, "gwSn": gw, "position": 30}

    client, _, _ = make_client(tmp_path, manager=manager, view_builder=builder)
    items = client.collect_state_items()
    # 坏条目被跳过、不炸；锁定模式随状态上行带过去（云通道没有 LAN 那路
    # device_update 实时推送，缺失即小程序永远显示"--"）
    assert items == [{"sn": "A1B2", "gwSn": "GW1", "position": 30, "windLockMode": 1}]


def test_collect_state_items_wind_lock_mode_unknown_stays_minus_one(tmp_path):
    cases = {
        "MISS": {},                                     # 无 attributes
        "NONE": {"attributes": {"wind_lock_mode": None}},
        "BOOL": {"attributes": {"wind_lock_mode": True}},   # bool 不是固件合法模式值
        "JUNK": {"attributes": {"wind_lock_mode": "abc"}},
        "INF": {"attributes": {"wind_lock_mode": float("inf")}},
        "OK0": {"attributes": {"wind_lock_mode": 0}},
    }
    manager = FakeManager(devices=cases)
    client, _, _ = make_client(tmp_path, manager=manager,
                               view_builder=lambda sn, gw, dev: {"sn": sn, "gwSn": gw})
    modes = {it["sn"]: it["windLockMode"] for it in client.collect_state_items()}
    assert modes == {"MISS": -1, "NONE": -1, "BOOL": -1, "JUNK": -1, "INF": -1, "OK0": 0}


def test_keepalive_marks_state_dirty_even_without_status_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "HUB_KEEPALIVE_S", 0.03)
    monkeypatch.setattr(hc, "HUB_SLEEP_SLICE_S", 0.01)
    client, _, _ = make_client(tmp_path)

    async def run():
        client._stopping = False
        client._state_dirty = asyncio.Event()
        task = asyncio.ensure_future(client._keepalive_loop())
        await asyncio.sleep(0.08)
        dirty = client._state_dirty.is_set()
        client._stopping = True                       # 停机闩锁 → 循环自行退出
        await asyncio.wait_for(task, timeout=1.0)
        return dirty

    assert asyncio.run(run()) is True


def test_handle_cmd_replies_and_normalizes_value(tmp_path):
    calls = []

    async def control(sn, attribute, value):
        calls.append((sn, attribute, value))
        return True

    client, _, _ = make_client(tmp_path, control_fn=control)

    ok = asyncio.run(client._handle_cmd({
        "t": "cmd", "cmdsn": "c1", "sn": "A1B2", "action": "control",
        "params": {"attribute": "w_travel", "value": 100},
    }))
    assert ok == {"ok": True, "data": {"published": True}}              # ok=已发布 broker
    assert calls == [("A1B2", "w_travel", "100")]                        # 值已规范化

    assert asyncio.run(client._handle_cmd({"action": "reboot", "sn": "A1B2"}))["err"] == "unknown_action"
    assert asyncio.run(client._handle_cmd({
        "action": "control", "sn": "", "params": {"attribute": "w_travel", "value": "100"},
    }))["err"] == "invalid_params"
    assert asyncio.run(client._handle_cmd({
        "action": "control", "sn": "A1B2", "params": {"attribute": "w_travel", "value": True},
    }))["err"] == "invalid_params"


def test_handle_cmd_without_control_fn_and_on_failure(tmp_path):
    client, _, _ = make_client(tmp_path)
    assert asyncio.run(client._handle_cmd({
        "action": "control", "sn": "A1B2", "params": {"attribute": "w_travel", "value": "100"},
    }))["err"] == "control_unavailable"

    async def boom(sn, attribute, value):                               # noqa: ARG001
        raise RuntimeError("boom")

    client2, _, _ = make_client(tmp_path, control_fn=boom)
    assert asyncio.run(client2._handle_cmd({
        "action": "control", "sn": "A1B2", "params": {"attribute": "w_travel", "value": "100"},
    }))["err"] == "control_failed"


def test_session_once_replies_cmd_result_and_flushes_state(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "HUB_STATE_DEBOUNCE_S", 0.01)
    cmd = json.dumps({"t": "cmd", "cmdsn": "c9", "sn": "A1B2",
                      "action": "control", "params": {"attribute": "w_travel", "value": "0"}})

    class Msg:
        type = 1  # aiohttp.WSMsgType.TEXT

        def __init__(self, data):
            self.data = data

    ws = FakeWS(incoming=[Msg(cmd)], hold=0.3)

    async def control(sn, attribute, value):
        return False                                                    # 发布失败 → ok False

    session = FakeSession(ws=ws)
    client, _, _ = make_client(tmp_path, session=session, control_fn=control)

    async def run():
        client._stopping = False
        client._state_dirty = asyncio.Event()
        client._send_lock = None
        done = await client._session_once()
        assert done is True
        await asyncio.sleep(0.05)                                       # 让 flush 有机会跑
        return ws.sent

    sent = asyncio.run(run())
    kinds = [m.get("t") for m in sent]
    assert "cmd_result" in kinds                                        # 回执必发
    reply = next(m for m in sent if m.get("t") == "cmd_result")
    assert reply["cmdsn"] == "c9" and reply["ok"] is False
    assert "state" in kinds                                             # 上线即全量推一次
    state = next(m for m in sent if m.get("t") == "state")
    assert state["items"] and state["items"][0]["sn"] == "A1B2"


def test_status_view_exposes_bind_code_but_never_secret(tmp_path):
    client, _, _ = make_client(tmp_path)
    client.instance_id, client._secret, client.bind_code = "abc", "S" * 48, "654321"
    view = client.status_view()
    assert view["bindCode"] == "654321"
    assert "S" * 48 not in json.dumps(view, ensure_ascii=False)          # secret 绝不外露
    assert view["connected"] is False and view["instanceId"] == "abc"
    assert view["gatewaySn"] == "GW1"                                    # 插件页"本机网关"用


def test_status_view_survives_missing_gateway_sn(tmp_path):
    class _Boom:
        @property
        def gateway_sn(self):
            raise RuntimeError("boom")

    client, _, _ = make_client(tmp_path, manager=_Boom())
    assert client.status_view()["gatewaySn"] == ""                        # 取 SN 抛错不得带崩视图


def test_stop_is_idempotent_and_detaches_listener(tmp_path):
    client, manager, session = make_client(tmp_path)
    asyncio.run(client.async_stop())                                    # 未启动也能停
    asyncio.run(client.async_start())
    assert manager.listeners                                                     # 已挂监听
    asyncio.run(client.async_stop())
    assert manager.listeners == []                                               # 已摘监听
    asyncio.run(client.async_stop())                                    # 幂等
    assert client.connected is False


# ── 绑定码：过期判定 / 轮换 / 自动补发（v1.7.41）────────────────────
def test_bind_code_expiry_math_and_view(tmp_path):
    client, _, _ = make_client(tmp_path)
    client.instance_id, client._secret = "abc", "def"
    client.bind_code, client._bind_code_at = "111111", time.time()
    assert 0 < client.bind_code_expires_in() <= hc.BIND_CODE_TTL_S
    view = client.status_view()
    assert view["bindCodeExpired"] is False and view["bindCodeExpiresIn"] > 0

    client._bind_code_at = time.time() - hc.BIND_CODE_TTL_S - 5      # 已过期
    assert client.bind_code_expires_in() < 0
    assert client.status_view()["bindCodeExpired"] is True

    client.bind_code = None                                           # 没码不算"过期"，算没有
    assert client.bind_code_expires_in() == -1
    assert client.status_view()["bindCodeExpired"] is False


def test_refresh_bind_code_persists_and_degrades(tmp_path, monkeypatch):
    client, _, _ = make_client(tmp_path)
    client.instance_id, client._secret = "abc", "def"
    client._bind_code_at = time.time() - 9999                         # 手上是死码
    calls = []

    async def ok_http(path, payload):
        calls.append((path, payload))
        return {"ok": True, "bindCode": "222222", "expiresInSec": 600}

    monkeypatch.setattr(client, "_http", ok_http)
    assert asyncio.run(client.refresh_bind_code()) is True
    assert calls[0][0] == "/agent/bindcode"
    assert calls[0][1]["instanceId"] == "abc" and calls[0][1].get("secret") == "def"
    assert client.bind_code == "222222" and client.bind_code_expires_in() > 500
    saved = hc.load_identity(str(tmp_path))
    assert saved["bindCode"] == "222222" and saved["bindCodeAt"] > 0   # 签发时刻落盘（重启后能判过期）

    async def reject_http(path, payload):                              # hub 拒绝（bad_secret 等）
        return {"ok": False, "err": "bad_secret"}

    monkeypatch.setattr(client, "_http", reject_http)
    assert asyncio.run(client.refresh_bind_code()) is False
    assert client.bind_code == "222222"                                # 失败不动手上的码

    async def boom_http(path, payload):                                # 旧 hub 没这条路由/网络断
        raise RuntimeError("net down")

    monkeypatch.setattr(client, "_http", boom_http)
    assert asyncio.run(client.refresh_bind_code()) is False


def test_renew_bind_code_if_stale_only_when_needed(tmp_path, monkeypatch):
    client, _, _ = make_client(tmp_path)
    client.instance_id, client._secret = "abc", "def"
    client.bind_code, client._bind_code_at = "111111", time.time()
    calls = []

    async def fake_http(path, payload):
        calls.append(path)
        return {"ok": True, "bindCode": "333333"}

    monkeypatch.setattr(client, "_http", fake_http)
    asyncio.run(client._renew_bind_code_if_stale())                    # 新鲜：一次都不该发
    assert calls == [] and client.bind_code == "111111"

    client._bind_code_at = time.time() - (hc.BIND_CODE_TTL_S - 10)     # 只剩 10s：该换
    asyncio.run(client._renew_bind_code_if_stale())
    assert calls == ["/agent/bindcode"] and client.bind_code == "333333"

    client.bind_code, client._bind_code_at = "444444", 0               # 签发时刻未知＝按过期处理
    asyncio.run(client._renew_bind_code_if_stale())
    assert calls[-1] == "/agent/bindcode"


def test_renew_is_wired_into_session_and_keepalive():
    """防死码凑数：自动补发必须真接在"上线自检"与"保活 tick"两条活路径上。"""
    tree = ast.parse(inspect.getsource(hc))
    want = {"_session_once", "_keepalive_loop"}
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name in want:
            found[node.name] = any(
                isinstance(n, ast.Attribute) and n.attr == "_renew_bind_code_if_stale"
                for n in ast.walk(node)
            )
    assert found == {"_session_once": True, "_keepalive_loop": True}, found
