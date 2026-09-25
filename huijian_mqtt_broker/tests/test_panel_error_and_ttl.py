# -*- coding: utf-8 -*-
"""面板文案：有效期/上限一律优先用服务端回的权威值，硬编字面量只当兜底。

缺陷形态：面板把"10 分钟""8 人"写死在 HTML 与 JS 里，而这两个值的真相在 hub
（store.js 的 bindTtlMs / HUB_MEMBERS_MAX，经 expiresInSec / membersMax 回给加载项）。
hub 一改，面板就对着一张云端已作废的码继续倒计时、对已满的家庭说"还能加"。
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "www" / "js" / "huijian.js").read_text(encoding="utf-8")
HTML = (ROOT / "www" / "index.html").read_text(encoding="utf-8")


def _fn(name):
    hits = [m.start() for m in re.finditer(r"function\s+" + re.escape(name) + r"\s*\(", JS)]
    assert len(hits) == 1, "函数 %s 出现 %d 次（应为 1；重名＝后者覆盖前者）" % (name, len(hits))
    i = hits[0]
    j = JS.index("{", i)
    depth = 0
    for k in range(j, len(JS)):
        if JS[k] == "{":
            depth += 1
        elif JS[k] == "}":
            depth -= 1
            if depth == 0:
                return JS[i:k + 1]
    raise AssertionError("函数 %s 未闭合" % name)


def _body(name):
    """函数体（不含签名）——扫描型守卫必须用它，否则 `function foo(` 这一行
    自己就含 `foo(`，定义处会被当成调用处（守卫扫到自己＝恒红或恒绿的来源）。"""
    src = _fn(name)
    return src[src.index("{") + 1:]


def _node(script):
    if shutil.which("node") is None:
        raise AssertionError("node 不可用，无法真跑")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.js"
        p.write_text(script, encoding="utf-8")
        r = subprocess.run(["node", str(p)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
        assert r.returncode == 0 and "OK" in r.stdout, "node 真跑失败：%s%s" % (r.stdout, r.stderr)


# ── DOM：可被服务端值覆盖的文案点 ─────────────────────────────────────
def test_ttl_copy_has_a_server_driven_element_with_literal_fallback():
    card = HTML.split('id="remoteCard"', 1)[1]
    assert 'id="hubCodeTtl"' in card, "绑定码有效期文案没有可写的元素（只能硬编）"
    assert 'id="hubMemberTip"' in card, "成员码提示没有 id（JS 无法按服务端 TTL 改写）"
    # 静态兜底仍在：JS 没跑起来/老集成不回 TTL 时，页面不能空着
    assert re.search(r'id="hubCodeTtl">10 分钟</span>', HTML), "缺 10 分钟静态兜底"
    assert "10 分钟" in card, "卡片必须写清有效期（用户不知道该多快扫）"


def test_apply_hub_status_writes_both_ttl_copy_points():
    body = _fn("applyHubStatus")
    assert "hubCodeTtl" in body and "bindCodeTtlS" in body, "统一出口没写绑定码有效期文案"
    assert "hubMemberTip" in body and "memberCodeTtlS" in body, "统一出口没写成员码有效期文案"
    assert body.count("ttlMinutes(") >= 2


def test_no_hardcoded_member_cap_copy():
    """上限文案只能来自 membersMax（|| 8 只是兜底），不许出现写死的"最多 8 人"。"""
    for bad in ("最多 8 人", "8 人上限", "限 8 人"):
        assert bad not in JS and bad not in HTML, "面板写死了成员上限文案：%s" % bad
    assert "info.membersMax || 8" in _fn("membersText")
    assert "(usable && info.membersMax) || 8" in _fn("renderMembers")


# ── 纯函数真跑 ──────────────────────────────────────────────────────
def test_ttl_minutes_really_runs_in_node():
    _node(_fn("ttlMinutes") + """
const cases = [
  [600, 10, 10], [300, 10, 5], [90, 10, 2], [60, 10, 1], [1, 10, 1],
  [undefined, 10, 10], [null, 10, 10], [0, 10, 10], [-60, 10, 10],
  ['abc', 10, 10], [NaN, 10, 10], [Infinity, 10, 10], [{}, 10, 10],
];
for (const [got, fb, want] of cases) {
  const v = ttlMinutes(got, fb);
  if (v !== want) { console.log('FAIL', String(got), '->', v, 'want', want); process.exit(1) }
}
console.log('OK');
""")


def test_members_read_failed_really_runs_in_node():
    _node(_fn("membersReadFailed") + """
const yes = [{lastOpError:'members_unavailable'}, {lastOpError:'members_rejected'}];
const no = [null, {}, {lastOpError:null}, {lastOpError:'no_owner'},
            {lastOpError:'member_remove_failed'}, {lastOpError:'bindcode_failed'}];
for (const i of yes) { if (membersReadFailed(i) !== true) { console.log('FAIL 应判读取失败', JSON.stringify(i)); process.exit(1) } }
for (const i of no) { if (membersReadFailed(i) !== false) { console.log('FAIL 不该判读取失败', JSON.stringify(i)); process.exit(1) } }
console.log('OK');
""")


# ── 单一出口纪律 ────────────────────────────────────────────────────
def test_op_error_text_is_rendered_only_by_the_single_exit():
    """操作类错误只能在 applyHubStatus 里渲染：多一个出口＝总有一条路径漏渲染/渲染旧值。"""
    callers = [n for n in re.findall(r"function (\w+)", JS)
               if n != "applyHubStatus" and "hubOpErrorText(" in _body(n)]
    assert callers == [], "除统一出口外还有函数渲染操作类错误：%s" % callers
    assert "hubOpErrorText(" in _fn("applyHubStatus")
    # 成员区/二维码的渲染点数目同样钉死（定义 + 失败分支 + 正常分支）
    assert JS.count("renderMembers(") == 3, JS.count("renderMembers(")
    assert JS.count("renderMemberQr(") == 3, JS.count("renderMemberQr(")


def test_server_side_produces_every_code_the_panel_maps():
    """反向对账：面板映射的本地降级值必须真是加载项会产生的（否则是在验死码）。"""
    py = (ROOT / "custom_components" / "window_controller_gateway" / "hub_client.py").read_text(encoding="utf-8")
    for code in re.findall(r"case '([a-z_]+)':", _fn("hubOpErrorText")):
        if code in ("no_owner", "members_full", "rate_limited", "registry_full", "superseded",
                    "bad_secret", "unknown_instance", "unknown_member", "owner_cannot_leave"):
            continue                      # 这些是 hub 回的真实 err，由跨仓契约钉对账
        assert '"%s"' % code in py, "面板映射了加载项不会产生的码 %s（死映射）" % code
