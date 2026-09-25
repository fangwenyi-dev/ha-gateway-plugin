# -*- coding: utf-8 -*-
"""加载项必须采用 hub 回的权威值（expiresInSec / bindExpire / membersMax），本地常量只兜底。

缺陷形态：hub 回 `expiresInSec`（store.js rotateBindCode）与 `membersMax`（store.js
listMembers），加载项两个都丢掉，用自己的 BIND_CODE_TTL_S / HUB_MEMBERS_MAX 覆盖。
hub 把 TTL 改短之后，面板会对一个云端**已作废**的码继续倒计时 ⇒ 用户扫到 code_invalid
且无人解释；上限改了同理（面板说"还能加"，hub 回 members_full）。

向后兼容：TTL 要落进身份文件（否则重启后又只能回落常量），而**老身份文件没有这个字段**
⇒ 读不到就走兜底，不得崩、不得把码判成"刚过期"。
"""
import asyncio
import time
from pathlib import Path

import pytest

from custom_components.window_controller_gateway import hub_client as hc


def _client(tmp_path, with_identity=True):
    c = hc.HubClient([], config_dir=str(tmp_path), session=object())
    if with_identity:
        c.instance_id, c._secret = "inst-1", "sec-1"
    return c


def _stub(client, replies):
    async def fake(path, payload):
        item = replies[path]
        if isinstance(item, Exception):
            raise item
        return dict(item)
    client._http = fake


# ── 注册：绝对到期时刻 → TTL ─────────────────────────────────────────
def test_register_adopts_hub_bind_expire(tmp_path):
    client = _client(tmp_path, with_identity=False)
    _stub(client, {"/agent/register": {
        "ok": True, "instanceId": "i1", "secret": "s" * 32, "bindCode": "123456",
        "bindExpire": int((time.time() + 120) * 1000)}})          # hub 说只剩 2 分钟

    asyncio.run(client._ensure_registered())

    assert client.bind_code_ttl_s() == pytest.approx(120, abs=3)
    assert 100 < client.bind_code_expires_in() <= 120
    assert client.status_view()["bindCodeTtlS"] == pytest.approx(120, abs=3)
    # 落盘：HA 重启后仍按云端给的 TTL 判过期，而不是回落 600 又开始骗人
    assert hc.load_identity(str(tmp_path))["bindCodeTtl"] == pytest.approx(120, abs=3)


def test_register_without_bind_expire_falls_back(tmp_path):
    client = _client(tmp_path, with_identity=False)
    _stub(client, {"/agent/register": {
        "ok": True, "instanceId": "i1", "secret": "s" * 32, "bindCode": "123456"}})

    asyncio.run(client._ensure_registered())

    assert client.bind_code_ttl_s() == hc.BIND_CODE_TTL_S, "老 hub 不回 bindExpire ⇒ 必须回落本地常量"
    assert 0 < client.bind_code_expires_in() <= hc.BIND_CODE_TTL_S


def test_shortened_ttl_expires_the_code_when_the_hub_says_so(tmp_path):
    """核心用户可见缺陷：hub 把 TTL 改短后，面板不得对一张已作废的码继续倒计时。"""
    client = _client(tmp_path)
    client.bind_code = "123456"
    client._bind_code_at = time.time() - 90          # 90 秒前签发
    client._bind_code_ttl_s = 60                     # hub 说有效期只有 60 秒

    assert client.bind_code_expires_in() < 0, "云端已作废的码仍在倒计时（用户扫到 code_invalid 无人解释）"
    assert client.status_view()["bindCodeExpired"] is True


# ── 换码：expiresInSec ───────────────────────────────────────────────
def test_refresh_adopts_expires_in_sec_for_owner_code(tmp_path):
    client = _client(tmp_path)
    client.bind_code, client._bind_code_at = "111111", time.time() - 9999
    _stub(client, {"/agent/bindcode": {"ok": True, "bindCode": "222222", "expiresInSec": 180}})

    assert asyncio.run(client.refresh_bind_code()) is True

    assert client.bind_code_ttl_s() == 180
    assert 160 < client.bind_code_expires_in() <= 180
    assert hc.load_identity(str(tmp_path))["bindCodeTtl"] == 180


def test_refresh_adopts_expires_in_sec_for_member_code(tmp_path):
    client = _client(tmp_path)
    _stub(client, {"/agent/bindcode": {"ok": True, "bindCode": "654321",
                                      "expiresInSec": 300, "kind": "member"}})

    assert asyncio.run(client.refresh_bind_code("member")) is True

    assert client.member_code_ttl_s() == 300
    assert 280 < client.member_code_expires_in() <= 300
    assert client.status_view()["memberCodeTtlS"] == 300
    assert client.bind_code_ttl_s() == hc.BIND_CODE_TTL_S, "成员码的 TTL 不得污染 owner 码"
    # 成员码不落身份文件（v1.7.47 纪律），所以它的 TTL 也不落
    assert "memberCode" not in hc.load_identity(str(tmp_path))


def test_refresh_without_expires_in_sec_falls_back(tmp_path):
    client = _client(tmp_path)
    _stub(client, {"/agent/bindcode": {"ok": True, "bindCode": "222222"}})

    asyncio.run(client.refresh_bind_code())

    assert client.bind_code_ttl_s() == hc.BIND_CODE_TTL_S


def test_garbage_ttl_values_never_win(tmp_path):
    """云端回垃圾（bool/字符串/负数/0）一律当"没给"：0 会让码当场判过期，负数更荒谬。"""
    for junk in (True, False, "abc", -5, 0, None, float("nan"), [], {}):
        client = _client(tmp_path)
        client.bind_code, client._bind_code_at = "111111", time.time()
        client._bind_code_ttl_s = hc._positive_int(junk)
        assert client.bind_code_ttl_s() == hc.BIND_CODE_TTL_S, "%r 竟被当成 TTL" % (junk,)
        assert client.bind_code_expires_in() > 0


def test_identity_file_without_ttl_field_reads_as_unknown(tmp_path):
    """向后兼容：老身份文件（v1.7.49 及以前写的）没有 bindCodeTtl。"""
    hc.save_identity(str(tmp_path), {"instanceId": "i1", "secret": "s" * 32,
                                     "bindCode": "123456", "bindCodeAt": time.time()})
    client = _client(tmp_path)
    asyncio.run(client._load_identity())
    assert client.bind_code == "123456"
    assert client.bind_code_ttl_s() == hc.BIND_CODE_TTL_S
    assert client.status_view()["bindCodeExpired"] is False, "老身份文件不得把活码判成刚过期"


def test_identity_file_with_ttl_field_is_reused(tmp_path):
    hc.save_identity(str(tmp_path), {"instanceId": "i1", "secret": "s" * 32, "bindCode": "123456",
                                     "bindCodeAt": time.time() - 130, "bindCodeTtl": 120})
    client = _client(tmp_path)
    asyncio.run(client._load_identity())
    assert client.bind_code_ttl_s() == 120
    assert client.bind_code_expires_in() < 0, "重启后仍按云端 TTL 判过期（这才是落盘的意义）"


# ── 成员上限 ─────────────────────────────────────────────────────────
def test_members_max_comes_from_the_hub(tmp_path):
    client = _client(tmp_path)
    _stub(client, {"/agent/members": {"ok": True, "members": [], "membersMax": 5,
                                     "ownerMasked": "oFa…01"}})

    assert asyncio.run(client.list_members()) is True
    assert client.status_view()["membersMax"] == 5, "hub 改了上限，面板还在说 8"


def test_members_max_falls_back_when_absent_or_garbage(tmp_path):
    for reply in ({"ok": True, "members": []},
                  {"ok": True, "members": [], "membersMax": "8"},
                  {"ok": True, "members": [], "membersMax": 0},
                  {"ok": True, "members": [], "membersMax": -3},
                  {"ok": True, "members": [], "membersMax": True}):
        client = _client(tmp_path)
        _stub(client, {"/agent/members": reply})
        asyncio.run(client.list_members())
        assert client.status_view()["membersMax"] == hc.HUB_MEMBERS_MAX, "%r 竟改了上限" % reply


def test_local_constants_are_documented_as_fallbacks():
    """常量保留为兜底，但必须写清"权威值在云端"（否则下一个人又会拿它当真相）。"""
    src = Path(hc.__file__).read_text(encoding="utf-8")
    for const in ("BIND_CODE_TTL_S = 600", "HUB_MEMBERS_MAX = 8"):
        i = src.index(const)
        window = src[max(0, i - 400):i + 200]
        assert "权威值在云端" in window, "%s 没说清权威值在云端" % const
