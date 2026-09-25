# -*- coding: utf-8 -*-
"""云通道错误呈现（服务端侧）：两个错误槽 + 带状态码的 HTTP 异常 + 真实 err 不被压扁。

三处缺陷同一套设计：
  (a) 误导文案——hub 对无主人实例回 no_owner，加载项把它压成 bindcode_rejected，面板
      只能说"稍后再试"，而正解是"先自己扫码成为主人"，重试永远不会成功；
  (b) 粘滞错误——8 个失败写入点、只有 WS 连上那一个清零点，所有成功路径都不清 ⇒
      一次瞬时失败后，面板长期在一张**刚签发的有效码**旁边喊"码可能已过期"，
      同一个槽还让面板操作失败盖掉 identity_rejected_loop 这条最有诊断价值的信息；
  (c) 成员类错误零反馈——member_remove_failed/members_unavailable 之类不在面板映射表里。

设计：`last_error` 只放**连接类**（身份被拒 / 主循环异常 / WS 异常类型名），
`last_op_error` 放**操作类**（换码 / 成员 / 踢人），并在**同族**操作成功时清零——
不同族的成功证明不了另一族恢复了（换码走 /agent/bindcode、成员走 /agent/members）。
"""
import asyncio
import inspect
import json

import pytest

from custom_components.window_controller_gateway import hub_client as hc


class FakeResp:
    def __init__(self, payload, status=200, raw=None):
        self._payload = payload
        self.status = status
        self._raw = raw

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        if self._raw is not None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, resp):
        self._resp = resp
        self.closed = False

    def post(self, url, json=None):                                    # noqa: A002
        self.url, self.payload = url, json
        return self._resp


def _client(tmp_path, resp=None):
    session = FakeSession(resp if resp is not None else FakeResp({"ok": True}))
    c = hc.HubClient([], config_dir=str(tmp_path), session=session)
    c.instance_id, c._secret = "inst-1", "sec-1"
    return c, session


# ── HubHttpError：状态码是一等公民 ────────────────────────────────────
def test_http_error_is_a_runtime_error_carrying_status():
    """继承 RuntimeError 是刻意的（既有调用点/测试都按 RuntimeError 兜），但判据走 status。"""
    e = hc.HubHttpError("/agent/members", 404, "unknown_instance")
    assert isinstance(e, RuntimeError)
    assert e.status == 404 and e.err == "unknown_instance" and e.path == "/agent/members"
    assert str(e) == "hub /agent/members -> 404", "消息格式变了＝既有日志判据（含 502）会失效"
    with pytest.raises(RuntimeError):
        raise hc.HubHttpError("/agent/bindcode", 502)


def test_http_raises_status_bearing_error_and_reads_hub_err(tmp_path):
    client, _ = _client(tmp_path, FakeResp({"ok": False, "err": "no_owner"}, status=409))
    with pytest.raises(hc.HubHttpError) as ei:
        asyncio.run(client._http("/agent/bindcode", {}))
    assert ei.value.status == 409 and ei.value.err == "no_owner"


def test_http_error_without_json_body_has_no_err(tmp_path):
    """反代错误页/空体：err 必须是 None（调用方据此回落本地降级值），不许猜。"""
    client, _ = _client(tmp_path, FakeResp(None, status=502, raw="<html>502</html>"))
    with pytest.raises(hc.HubHttpError) as ei:
        asyncio.run(client._http("/agent/members", {}))
    assert ei.value.status == 502 and ei.value.err is None


def test_callers_branch_on_status_not_on_message_text():
    """反钉：判"老 hub"必须走 HubHttpError.status/err，不得靠解析错误消息里的数字。"""
    src = inspect.getsource(hc.HubClient.list_members)
    assert "except HubHttpError" in src, "list_members 必须接住带状态码的异常"
    assert "e.status == 404" in src, "必须按状态码判'老 hub'（其余一律是读取失败）"
    assert "e.err" in src, "必须读 hub 的应用级 err——404 也可能是 unknown_instance，不是老 hub"
    whole = inspect.getsource(hc)
    for bad in ('"404" in str', "'404' in str", 'str(e).find(', 'str(e).endswith('):
        assert bad not in whole, "出现了靠消息文本判状态码的写法：%r" % bad


# ── (a) 真实 err 不被压扁 ────────────────────────────────────────────
def test_bindcode_rejection_keeps_the_hub_err(tmp_path):
    client, _ = _client(tmp_path)

    async def reject(path, payload, timeout_s=None):
        return {"ok": False, "err": "no_owner"}

    client._http = reject
    assert asyncio.run(client.refresh_bind_code("member")) is False
    assert client.last_op_error == "no_owner", "压成笼统值＝面板只能说'稍后再试'（重试永远不会成功）"
    assert client.last_error is None, "操作类失败不得污染连接类槽"


def test_bindcode_rejection_without_err_falls_back_to_local_value(tmp_path):
    client, _ = _client(tmp_path)

    async def reject(path, payload, timeout_s=None):
        return {"ok": False}

    client._http = reject
    asyncio.run(client.refresh_bind_code())
    assert client.last_op_error == "bindcode_rejected"


def test_member_removal_keeps_the_hub_err(tmp_path):
    client, _ = _client(tmp_path)

    async def reject(path, payload, timeout_s=None):
        return {"ok": False, "err": "owner_cannot_leave"}

    client._http = reject
    assert asyncio.run(client.remove_member("a" * 12)) is False
    assert client.last_op_error == "owner_cannot_leave"


def test_http_level_member_failure_keeps_status_err(tmp_path):
    client, _ = _client(tmp_path)

    async def boom(path, payload, timeout_s=None):
        raise hc.HubHttpError(path, 403, "bad_secret")

    client._http = boom
    assert asyncio.run(client.list_members()) is False
    assert client.last_op_error == "bad_secret"
    assert client.members_supported is True, "403 不是'老 hub'，不得据此禁用成员区"


# ── (b) 成功路径清错误（按族）────────────────────────────────────────
def test_successful_refresh_clears_only_the_bindcode_family(tmp_path):
    client, _ = _client(tmp_path)

    async def reject(path, payload, timeout_s=None):
        return {"ok": False, "err": "rate_limited"}

    client._http = reject
    asyncio.run(client.refresh_bind_code())
    assert client.last_op_error == "rate_limited"
    client._set_op_error(hc.OP_MEMBERS, "members_unavailable")     # 另一族也失败过

    async def ok(path, payload, timeout_s=None):
        return {"ok": True, "bindCode": "222222", "expiresInSec": 600}

    client._http = ok
    assert asyncio.run(client.refresh_bind_code()) is True
    assert client.last_op_error == "members_unavailable", \
        "换码成功证明不了成员读取恢复了（跨族清零＝把还没恢复的故障藏起来）"

    async def members_ok(path, payload, timeout_s=None):
        return {"ok": True, "members": [], "membersMax": 8}

    client._http = members_ok
    assert asyncio.run(client.list_members()) is True
    assert client.last_op_error is None, "同族成功必须清零（否则错误永久粘在面板上）"


def test_successful_removal_clears_its_own_family(tmp_path):
    client, _ = _client(tmp_path)
    client._set_op_error(hc.OP_MEMBER_REMOVE, "member_remove_failed")

    async def ok(path, payload, timeout_s=None):
        if path == "/agent/unbind":
            return {"ok": True, "remaining": 0}
        return {"ok": True, "members": [], "membersMax": 8}

    client._http = ok
    assert asyncio.run(client.remove_member("a" * 12)) is True
    assert client.last_op_error is None


def test_ws_connect_clears_connection_error_but_not_operation_error(tmp_path):
    """连上只证明长连通了：操作类错误必须由对应操作的成功来清（否则又是一次粘滞）。"""
    client, _ = _client(tmp_path)
    client.last_error = "ClientConnectorError"
    client._set_op_error(hc.OP_BINDCODE, "bindcode_failed")
    src = inspect.getsource(hc.HubClient._session_once)
    assert "self.last_error = None" in src, "连上必须清连接类错误"
    assert "last_op_error" not in src, "_session_once 不得顺手清操作类错误"


def test_connection_errors_stay_in_the_connection_slot():
    """反钉：连接类的三个写入点不许挪去操作槽（否则 WS 异常会被操作成功清掉）。"""
    src = inspect.getsource(hc.HubClient)
    for anchor in ('self.last_error = type(e).__name__', 'self.last_error = "loop_%s" % type(e).__name__',
                   'self.last_error = "identity_rejected_loop"', 'self.last_error = "identity_rejected"'):
        assert anchor in src, "连接类写入点漂移：%r" % anchor
    for gone in ('self.last_error = "bindcode_failed"', 'self.last_error = "bindcode_rejected"',
                 'self.last_error = "members_unavailable"', 'self.last_error = "members_rejected"',
                 'self.last_error = "member_remove_failed"', 'self.last_error = "member_remove_rejected"',
                 'self.last_error = "hub_too_old_for_member_code"'):
        assert gone not in src, "操作类错误又写回连接槽了：%r" % gone


# ── 视图与 api 透传 ──────────────────────────────────────────────────
def test_status_view_exposes_both_slots(tmp_path):
    client, _ = _client(tmp_path)
    view = client.status_view()
    assert view["lastError"] is None and view["lastOpError"] is None
    client.last_error = "identity_rejected"
    client._set_op_error(hc.OP_BINDCODE, "no_owner")
    view = client.status_view()
    assert view["lastError"] == "identity_rejected" and view["lastOpError"] == "no_owner"
    assert "sec-1" not in json.dumps(view, ensure_ascii=False), "视图不得回显 secret"


def test_unknown_op_error_value_is_never_a_credential(tmp_path):
    """hub 回什么就存什么，但绝不存本地凭据（错误槽会原样进面板 JSON）。"""
    client, _ = _client(tmp_path)

    async def boom(path, payload, timeout_s=None):
        raise RuntimeError("POST /agent/bindcode?secret=sec-1 failed")

    client._http = boom
    asyncio.run(client.refresh_bind_code())
    assert "sec-1" not in (client.last_op_error or "")
    assert client.last_op_error == "bindcode_failed"
