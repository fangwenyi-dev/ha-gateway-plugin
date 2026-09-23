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
    """真 aiohttp 的 ws_connect() 是 awaitable 且返回值本身可 async with——桩不能比真实现窄
    （`_open_ws` 先 await 再 async with，只实现 CM 就会 TypeError）。"""

    def __init__(self, ws):
        self.ws = ws

    def __await__(self):
        async def self_await():
            return self
        return self_await().__await__()

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
    manager = kw.pop("manager", None)
    managers = kw.pop("managers", None)
    if managers is None:
        managers = [manager or FakeManager()]
    elif manager is not None:
        managers = [manager] + list(managers)
    session = kw.pop("session", None) or FakeSession()
    client = hc.HubClient(managers, config_dir=str(tmp_path), session=session, **kw)
    return client, (managers[0] if managers else None), session


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


# ── 身份被云端拒绝后的自愈（v1.7.42）────────────────────────────────
# 线上事故形态：云托管重新部署 ⇒ HUB_STORE=/data/store.json（容器本地盘）被抹，
# hub 不再认识本机 instanceId/secret。此前客户端只能看到 ServerDisconnectedError
# ＝与网络抖动同形 ⇒ 抱着死身份无限重连，面板显示的是当前 hub 从未签发的码，
# 小程序侧必然 code_invalid 且永不自愈。判据只认握手返回的 HTTP 状态。
import aiohttp


class ScriptedSession(FakeSession):
    """ws_connect 按脚本失败；注册响应逐次不同（才能证明"换了新身份"）。"""

    def __init__(self, script, payloads=None):
        super().__init__()
        self.script = list(script)
        self.payloads = list(payloads or [])
        self.ws_attempts = 0

    def post(self, url, json=None):                                    # noqa: ARG002
        self.posted.append((url, json))
        if "register" in url and self.payloads:
            return FakeResp(self.payloads.pop(0))
        return FakeResp(self.register_payload)

    def ws_connect(self, url, heartbeat=None):                         # noqa: ARG002
        self.ws_attempts += 1
        self.ws_url = url
        kind = self.script.pop(0) if self.script else None
        if kind is None:
            return FakeCM(self.ws)
        raise kind


def _hs(status):
    return aiohttp.WSServerHandshakeError(
        request_info=None, history=(), status=status, message=str(status), headers=None)


def _ident(payload):
    return {"ok": True, "instanceId": payload, "secret": payload * 2, "bindCode": payload[-6:]}


def test_401_on_handshake_clears_identity_and_reregisters(tmp_path):
    s = ScriptedSession([_hs(401)], payloads=[_ident("i0000000aaaa"), _ident("i1111111bbbb")])
    client, _, _ = make_client(tmp_path, session=s)
    assert asyncio.run(client._session_once()) is True
    assert len(s.posted) == 2 and s.ws_attempts == 2, "被拒后应重注册一次再连，且只补一次"
    assert client.instance_id == "i1111111bbbb", "仍抱旧身份＝线上永不自愈的那条路"
    assert client.bind_code == "i1111111bbbb"[-6:], "换身份后必须带出新绑定码"
    # 真文件面：清过身份要落盘，否则 HA 重启又把死身份捡回来
    assert hc.load_identity(str(tmp_path))["instanceId"] == "i1111111bbbb"


def test_403_clears_identity_too(tmp_path):
    s = ScriptedSession([_hs(403)], payloads=[_ident("i0000000aaaa"), _ident("i2222222cccc")])
    client, _, _ = make_client(tmp_path, session=s)
    assert asyncio.run(client._session_once()) is True
    assert client.instance_id == "i2222222cccc"
    assert hc.IDENTITY_REJECTED_HTTP == (401, 403), "状态集合与实现脱钩＝判据漂移"


def test_non_identity_http_failure_keeps_identity(tmp_path):
    """503/500 一类"云端还在但没答上"绝不能触发重注册：每次抖动都换码＝用户手上的活码被作废。"""
    for status in (429, 500, 502, 503):
        cfg = tmp_path / ("st%s" % status)          # 各自一份身份盘：上一轮的落盘会让本轮直接复用身份
        cfg.mkdir(parents=True, exist_ok=True)
        s = ScriptedSession([_hs(status)], payloads=[_ident("i0000000aaaa"), _ident("i9999999zzzz")])
        client, _, _ = make_client(cfg, session=s)
        try:
            asyncio.run(client._session_once())
        except aiohttp.WSServerHandshakeError:
            pass
        assert client.instance_id == "i0000000aaaa", "状态 %s 竟清了身份" % status
        assert len(s.posted) == 1, "状态 %s 竟多发了注册请求" % status


def test_transport_level_failure_keeps_identity(tmp_path):
    """裸断/连不上（旧 hub 或网络故障）：只能继续抱身份退避，不能猜成"被拒"。"""
    for n, err in enumerate((aiohttp.ServerDisconnectedError(message="reset"),
                             aiohttp.ClientOSError(113, "No route to host"))):
        cfg = tmp_path / ("net%s" % n)
        cfg.mkdir(parents=True, exist_ok=True)
        s = ScriptedSession([err], payloads=[_ident("i0000000aaaa"), _ident("i9999999zzzz")])
        client, _, _ = make_client(cfg, session=s)
        try:
            asyncio.run(client._session_once())
        except Exception:  # noqa: BLE001 - 交给外层退避，正是期望行为
            pass
        assert client.instance_id == "i0000000aaaa", "%s 竟清了身份" % type(err).__name__
        assert len(s.posted) == 1


def test_invalidate_identity_writes_cleared_file(tmp_path):
    hc.save_identity(str(tmp_path), {"instanceId": "old", "secret": "s" * 32, "bindCode": "123456",
                                     "bindCodeAt": 111.0})
    client, _, _ = make_client(tmp_path)
    client.instance_id, client._secret, client.bind_code, client._bind_code_at = "old", "s" * 32, "123456", 111.0
    client._invalidate_identity("测试")
    assert (client.instance_id, client.bind_code, client._bind_code_at) == (None, None, 0.0)
    assert not hc.load_identity(str(tmp_path)).get("instanceId"), "死身份还在盘上＝重启后复活"
    assert client.status_view()["bindCodeExpired"] is False, "无码时不得渲染成『刚过期』"


def test_open_ws_is_the_only_reject_site_and_reconnects_once():
    """接线钉：握手只允许经 _open_ws（旁路 ws_connect＝自愈失效），且重注册后只再连一次。"""
    src = inspect.getsource(hc.HubClient._session_once)
    assert "self._open_ws(session)" in src, "_session_once 又直连 ws_connect 了"
    assert "session.ws_connect" not in src, "_session_once 里出现旁路握手"
    body = inspect.getsource(hc.HubClient._open_ws)
    assert body.count("session.ws_connect") == 2, "首连 + 被拒后重连，多一次就是重试风暴"


# ── 重注册熔断（防止无限造孤儿实例）───────────────────────────────
def _hs401():
    return _hs(401)


def test_reregister_fuse_stops_after_consecutive_rejections(tmp_path, caplog):
    """病态形态：register 落到容器 A、握手落到容器 B（云托管多副本且注册表不共享）。
    不熔断就是每轮退避白造一个新实例 + 反复作废用户手上的绑定码。"""
    import logging
    s = ScriptedSession([_hs401()] * 20, payloads=[_ident("i%07d%d" % (n, n)) for n in range(20)])
    client, _, _ = make_client(tmp_path, session=s)
    for _ in range(6):
        try:
            asyncio.run(client._session_once())
        except Exception:  # noqa: BLE001 - 交给外层退避
            pass
    assert len(s.posted) == 4, "注册次数 %d＝熔断没生效，会无限造孤儿实例" % len(s.posted)
    assert client._rereg_streak == hc.HUB_REREGISTER_FUSE
    errs = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("停止自动重注册" in m for m in errs), "熔断没有可见的 ERROR（现场只会看到反复换码）"
    joined = " ".join(errs)
    assert "存储挂载" in joined and "实例数" in joined, "熔断话术没给出两个真根因，运维还得自己猜"


def test_fuse_counter_resets_after_a_successful_session(tmp_path):
    """连上过就等于"云端确实认识当前身份"，计数必须归零——否则一次故障永久废掉自愈能力。"""
    s = ScriptedSession([_hs401()] * 20, payloads=[_ident("i%07da" % n) for n in range(20)])
    client, _, _ = make_client(tmp_path, session=s)
    for _ in range(4):
        try:
            asyncio.run(client._session_once())
        except Exception:  # noqa: BLE001
            pass
    assert client._rereg_streak == hc.HUB_REREGISTER_FUSE
    del s.script[:]                          # 接下来握手一律成功
    assert asyncio.run(client._session_once()) is True
    assert client._rereg_streak == 0, "连上后没清零＝熔断只许触发一次"
    s.script.append(_hs401())
    before = len(s.posted)
    try:
        asyncio.run(client._session_once())
    except Exception:  # noqa: BLE001
        pass
    assert len(s.posted) == before + 1, "清零后仍不再自愈＝回到 v1.7.41 那个永不恢复的状态"


# ── 安装级多网关聚合（v1.7.43）────────────────────────────────────
# 背景：HubClient 原来是"每网关条目一个实例"，N 台网关就注册 N 个实例、
# 抢同一份 /config/huijian_hub_identity.json（互相覆盖），HA 重启后全部
# 用同一个 instanceId 去连 → hub 的 onAgent 把前一条顶掉 → 重连战争，
# 而小程序只看到其中一个网关。现在改成"一个 HA 安装一个实例"，实例内部
# 聚合全部条目的 manager。
def test_state_items_cover_every_gateway_not_just_the_first(tmp_path):
    m1 = FakeManager(gateway_sn="GW1", devices={"A1B2": {"attributes": {"r_travel": 30}}})
    m2 = FakeManager(gateway_sn="GW2", devices={"C3D4": {"attributes": {"r_travel": 70}}})
    client, _, _ = make_client(tmp_path, managers=[m1, m2])
    items = client.collect_state_items()
    sns = sorted(i["sn"] for i in items)
    assert sns == ["A1B2", "C3D4"], "只聚合到一条网关＝小程序永远看不到全部设备: %s" % sns
    gw = {i["sn"]: i.get("gwSn") for i in items}
    assert gw == {"A1B2": "GW1", "C3D4": "GW2"}, "gwSn 串了＝小程序按 gwSn 分桶会把两台网关混成一台: %s" % gw


def test_status_listener_attached_to_every_manager_and_detached(tmp_path):
    m1, m2 = FakeManager(gateway_sn="GW1"), FakeManager(gateway_sn="GW2")
    client, _, _ = make_client(tmp_path, managers=[m1, m2])
    client.attach_managers([m1, m2])
    assert client._on_device_status in m1.listeners and client._on_device_status in m2.listeners, \
        "监听器没挂满每个 manager＝第二台网关的状态变化不会触发上行"
    client.attach_managers([m1])          # 条目被卸载后再聚合
    assert client._on_device_status not in m2.listeners, "撤掉的 manager 没摘监听＝回调持死对象"
    client.attach_managers([m1])
    assert m1.listeners.count(client._on_device_status) == 1, "重复 ensure 不得把同一回调挂两次"


def test_status_view_lists_all_gateways_and_keeps_gateway_sn_compat(tmp_path):
    m1 = FakeManager(gateway_sn="GW1", devices={"A1": {}, "A2": {}})
    m2 = FakeManager(gateway_sn="GW2", devices={"B1": {}})
    client, _, _ = make_client(tmp_path, managers=[m1, m2])
    v = client.status_view()
    assert [g["sn"] for g in v["gateways"]] == ["GW1", "GW2"]
    assert [g["deviceCount"] for g in v["gateways"]] == [2, 1]
    assert v["gatewaySn"] == "GW1", "gatewaySn 是旧消费方的兼容字段，必须仍在"


def test_register_payload_reports_a_gateway_sn(tmp_path):
    m1 = FakeManager(gateway_sn="GW1")
    client, _, session = make_client(tmp_path, managers=[m1, FakeManager(gateway_sn="GW2")])
    asyncio.run(client._ensure_registered())
    sent = [p for (_u, p) in session.posted if p and "installKey" in p]
    assert sent and sent[0]["sn"] == "GW1", "注册载荷 sn 缺失＝hub 侧实例无从辨认"


def test_no_manager_means_empty_items_and_no_crash(tmp_path):
    """所有条目都在卸载中：宁可回空列表，也不能抛（上行协程抛错会打断长连）。"""
    client, _, _ = make_client(tmp_path, managers=[])
    assert client.collect_state_items() == []
    assert client.status_view()["gateways"] == []
