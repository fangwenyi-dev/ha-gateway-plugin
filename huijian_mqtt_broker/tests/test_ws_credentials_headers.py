# -*- coding: utf-8 -*-
"""WS 长连凭据不得进 URL query（改走 x-hub-instance-id / x-hub-secret 请求头）。

为什么是缺陷：任何记 request line 的中间层（云托管访问日志、反代、错误上报）都会把明文
secret 留档，与本项目"凭据不回显"纪律相悖——HTTP 的 /agent/* 一直走 body，唯独 WS 例外。
更近的隐患：加载项很小心地只记 type(e).__name__，但 aiohttp 的 ClientResponseError.__str__
是**带 URL** 的，将来谁写一句 str(e) 就把 secret 送进 HA 日志。

发版顺序：hub 侧改成"先读头、缺失回落 query"，**必须 hub 先上**（跨仓钉对账头名与兜底）。
"""
import asyncio
import inspect

import aiohttp

from custom_components.window_controller_gateway import hub_client as hc


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


class FakeWS:
    def __aiter__(self):
        async def gen():
            return
            yield None
        return gen()


class RecordingSession:
    """记下每次 ws_connect 的 url 与 headers；可按脚本在握手时抛错。"""

    def __init__(self, script=None, register_payload=None):
        self.script = list(script or [])
        self.connects = []
        self.posted = []
        self.closed = False
        self.register_payload = register_payload or {
            "ok": True, "instanceId": "i2", "secret": "NEWSECRET", "bindCode": "654321"}

    def post(self, url, json=None):                                    # noqa: A002
        self.posted.append((url, json))
        return _FakeResp(self.register_payload)

    def ws_connect(self, url, headers=None, heartbeat=None):
        self.connects.append({"url": url, "headers": headers, "heartbeat": heartbeat})
        kind = self.script.pop(0) if self.script else None
        if kind is not None:
            raise kind
        return FakeCM(FakeWS())

    async def close(self):
        self.closed = True


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload, self.status = payload, status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return self._payload


def _hs(status):
    return aiohttp.WSServerHandshakeError(
        request_info=None, history=(), status=status, message=str(status), headers=None)


def _client(tmp_path, session):
    c = hc.HubClient([], config_dir=str(tmp_path), session=session)
    c.instance_id, c._secret = "inst-1", "SUPERSECRETVALUE"
    return c


# ── URL 与头 ─────────────────────────────────────────────────────────
def test_header_names_are_the_agreed_lowercase_pair():
    """跨仓增量：两侧逐字一致（大小写不敏感是 HTTP 的事，但契约写死小写免得各自发挥）。"""
    assert hc.WS_HEADER_INSTANCE_ID == "x-hub-instance-id"
    assert hc.WS_HEADER_SECRET == "x-hub-secret"


def test_ws_url_has_no_query_at_all(tmp_path):
    client = _client(tmp_path, RecordingSession())
    url = client._ws_url()
    assert url == "wss://" + hc.HUB_DEFAULT_BASE[len("https://"):] + "/agent/ws"
    assert "?" not in url and "SUPERSECRETVALUE" not in url and "inst-1" not in url
    client.base = "http://127.0.0.1:18311"
    assert client._ws_url() == "ws://127.0.0.1:18311/agent/ws"


def test_ws_headers_carry_the_credentials(tmp_path):
    client = _client(tmp_path, RecordingSession())
    assert client._ws_headers() == {"x-hub-instance-id": "inst-1",
                                    "x-hub-secret": "SUPERSECRETVALUE"}


def test_every_handshake_sends_headers_and_never_a_credentialed_url(tmp_path):
    """被拒后重注册再连一次：两次握手都必须带头（且带的是各自当时的凭据），URL 都不含凭据。"""
    session = RecordingSession(script=[_hs(401)])
    client = _client(tmp_path, session)

    assert asyncio.run(client._session_once()) is True

    assert len(session.connects) == 2, "首连 + 被拒后重连"
    assert session.connects[0]["headers"] == {"x-hub-instance-id": "inst-1",
                                              "x-hub-secret": "SUPERSECRETVALUE"}
    assert session.connects[1]["headers"] == {"x-hub-instance-id": "i2",
                                              "x-hub-secret": "NEWSECRET"}, \
        "重注册后的第二次握手必须用新凭据（仍旧凭据＝再被拒一次，白造孤儿实例）"
    for c in session.connects:
        assert "?" not in c["url"], "凭据又回 URL 了：%s" % c["url"]
        assert "SUPERSECRETVALUE" not in c["url"] and "NEWSECRET" not in c["url"]
        assert c["heartbeat"] == 25.0, "心跳口径被改了（hub 侧按 60s 判活）"


def test_no_query_credential_pattern_left_in_the_module():
    src = inspect.getsource(hc)
    for gone in ("secret=%s", "instanceId=%s", "?instanceId="):
        assert gone not in src, "URL 里拼凭据的写法还在：%r" % gone
    assert "headers=self._ws_headers()" in src, "握手必须显式带凭据头"
    assert inspect.getsource(hc.HubClient._open_ws).count("session.ws_connect") == 2, \
        "首连 + 被拒后重连，多一次就是重试风暴"


def test_secret_never_reaches_the_logger(tmp_path, caplog):
    """凭据不回显：连接失败时日志里也不得出现 secret（str(e) 带 URL 正是这条的动机）。"""
    import logging

    class BoomSession(RecordingSession):
        def ws_connect(self, url, headers=None, heartbeat=None):
            self.connects.append({"url": url, "headers": headers})
            raise aiohttp.ClientConnectionError("cannot connect to %s" % url)

    client = _client(tmp_path, BoomSession())
    caplog.set_level(logging.DEBUG, logger=client._logger.name)
    try:
        asyncio.run(client._session_once())
    except Exception:  # noqa: BLE001 - 交给外层退避
        pass
    logs = " ".join(r.getMessage() for r in caplog.records)
    assert "SUPERSECRETVALUE" not in logs, "日志回显了凭据：%s" % logs
