# -*- coding: utf-8 -*-
"""v1.7.46 钉桩：面板 JS 的**重名钉**与"云通道故障原因"接线。

为什么必须有重名钉（本仓第四次同类假绿）：v1.7.41～v1.7.45 线上一直带着一个缺陷——
`www/js/huijian.js` 里 `loadRemoteControl` 被定义了两次（`:170` v1.7.41 新版走统一渲染
出口 `applyHubStatus`、`:207` v1.7.37 旧版残留）。JS 函数声明**后者覆盖前者** ⇒ 页面加载
与 30s 无感刷新跑的全是旧版：绑定码过期文案（`hubCodeExp`）永不显示、「纳管网关 N 台 ·
M 个子设备」退回只显示 `gatewaySn`；新版只在"点二维码"那条 POST 路径可达。

而 940 条测试全绿——因为所有结构钉用 `index("function loadRemoteControl(")` **只取第一处**，
钉到的是那个永不执行的版本，连"除统一出口外不得直调 renderBindQr"的反钉也一起失效
（旧版有三处直调）。教训：**钉"某函数必须做 X"的前提是"该函数只有一个"**。

本文件三件事：
  1) 重名钉：扫全部函数名，每个名字恰好出现一次（含元钉：扫到 0 个即红，防空扫假绿）；
  2) 单一渲染出口：`loadRemoteControl` 必须走 `applyHubStatus`，且旧渲染器指纹消失；
  3) `hubErrorText`：DOM/CSS/接线齐备 + **node 真跑**映射（只映射已知码，未知一律不显示）。
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "www" / "js" / "huijian.js").read_text(encoding="utf-8")
HTML = (ROOT / "www" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "www" / "css" / "huijian.css").read_text(encoding="utf-8")

_FUNC_RE = re.compile(r"^[ \t]*(?:async[ \t]+)?function[ \t]+([A-Za-z_$][\w$]*)[ \t]*\(", re.M)


def _names(src):
    return _FUNC_RE.findall(src)


def _single_func_body(src, name):
    """取唯一那个函数的花括号全体；0 处或多处都报错（绝不静默取第一处）。"""
    hits = [m.start() for m in re.finditer(r"function\s+" + re.escape(name) + r"\s*\(", src)]
    assert len(hits) == 1, \
        "函数 %s 出现 %d 次（应为 1；重名＝后者覆盖前者，钉会验到死码）" % (name, len(hits))
    i = hits[0]
    j = src.index("{", i)
    depth = 0
    for k in range(j, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    raise AssertionError("函数 %s 花括号不配平（解析锚点失效）" % name)


# ── 1) 重名钉 ────────────────────────────────────────────────────────
def test_no_duplicate_function_definitions():
    names = _names(JS)
    assert names, "解析锚点失效：一个函数都没抽到（守卫会假绿）"      # 元钉：防空扫
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert not dupes, "huijian.js 存在重复定义的函数（后者覆盖前者＝前者是死码）：%s" % dupes


def test_extractor_sees_every_definition_site():
    """元钉：抽取正则必须能看到全部定义点，否则重名钉本身会假绿。

    做法：拿 `function` 关键字的裸计数与正则抽到的名字数对账（允许 async 前缀）。
    """
    raw = len(re.findall(r"\bfunction\s+[A-Za-z_$][\w$]*\s*\(", JS))
    assert raw == len(_names(JS)), \
        "抽取正则漏了定义点：裸计数 %d vs 抽到 %d" % (raw, len(_names(JS)))
    assert raw >= 10, "面板函数数量异常（%d），锚点可能已漂移" % raw


# ── 2) 单一渲染出口 ──────────────────────────────────────────────────
def test_load_remote_control_goes_through_single_exit():
    body = _single_func_body(JS, "loadRemoteControl")
    assert "applyHubStatus(" in body, "loadRemoteControl 必须走统一渲染出口 applyHubStatus"
    assert "renderBindQr(" not in body, "不得绕过统一出口直调 renderBindQr"
    assert "hubCodeExp" not in body, "过期文案由 applyHubStatus 统一写，别在这里各写一份"


def test_old_renderer_fingerprints_are_gone():
    """旧版渲染器的指纹必须消失（只判"不存在"是单侧钉，所以配上一条正向钉）。"""
    assert JS.count("async function loadRemoteControl(") == 1, "loadRemoteControl 只能有一份定义"
    assert "info.gatewaySn || '—'" not in JS, \
        "旧版直写 gatewaySn 的残留还在（多网关用户会以为只管一台，应走 hubGatewayText）"


# ── 3) 云通道故障原因 ────────────────────────────────────────────────
def test_hub_error_element_wired():
    assert 'id="hubError"' in HTML, "index.html 缺 #hubError（lastError 有值也没处显示）"
    card = HTML.split('id="remoteCard"', 1)[1]
    assert 'id="hubError"' in card, "#hubError 必须在「远程控制（慧尖云）」卡内"
    assert re.search(r"\.hub-err\s*\{", CSS), "缺 .hub-err 样式（显示出来也没排版）"
    body = _single_func_body(JS, "applyHubStatus")
    assert "hubErrorText(" in body, "统一渲染出口没有渲染故障原因"
    assert "errEl.hidden = true" in body, "未启用/读取失败分支必须把原因藏起来（别留旧值）"


def test_hub_error_maps_only_known_codes():
    """反钉：只映射 hub_client.last_error 的已知取值，未知的一律回 ''。

    面板是给终端用户看的：把异常类名（RuntimeError 之类）摆上去只是噪声，
    而且 last_error 有一路就是 type(e).__name__（hub_client.py:269）。
    """
    body = _single_func_body(JS, "hubErrorText")
    for code in ("identity_rejected", "identity_rejected_loop", "bindcode_failed", "bindcode_rejected"):
        assert "'%s'" % code in body, "hubErrorText 漏映射 %s" % code
    assert "default:" in body and "return ''" in body, "未知码必须回空串（不显示）"


def test_hub_error_text_really_runs_in_node():
    """纯函数真跑（照 test_v1743_hub_singleton.py 的 hubGatewayText 写法）：不打桩判断。"""
    if shutil.which("node") is None:
        raise AssertionError("node 不可用，无法真跑 hubErrorText")
    body = _single_func_body(JS, "hubErrorText")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "errtext.js"
        p.write_text(body + """
const known = ['identity_rejected', 'identity_rejected_loop', 'bindcode_failed', 'bindcode_rejected'];
for (const c of known) {
  const s = hubErrorText(c);
  if (!s || s.length < 4) { console.log('FAIL 已知码没有文案:', c, JSON.stringify(s)); process.exit(1) }
  if (!/[\\u4e00-\\u9fa5]/.test(s)) { console.log('FAIL 文案必须是中文:', c, s); process.exit(1) }
}
for (const c of ['RuntimeError', 'ClientConnectorError', '', null, undefined, 'members_full']) {
  if (hubErrorText(c) !== '') { console.log('FAIL 未知码必须回空串:', c, hubErrorText(c)); process.exit(1) }
}
if (hubErrorText('identity_rejected').indexOf('重新扫码') < 0) {
  console.log('FAIL identity_rejected 必须指路重新扫码'); process.exit(1)
}
console.log('OK');
""", encoding="utf-8")
        r = subprocess.run(["node", str(p)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0 and "OK" in r.stdout, \
            "node 真跑失败：%s%s" % (r.stdout, r.stderr)
