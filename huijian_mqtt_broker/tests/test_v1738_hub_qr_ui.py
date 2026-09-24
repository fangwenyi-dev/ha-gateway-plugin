# -*- coding: utf-8 -*-
"""v1.7.38 钉桩：面板「绑定码二维码 + 复制」接线（v1.7.39 位置改为「远程控制」卡右侧）。

用户要求：v1.7.38 把二维码摆到页头 logo 旁（"太突兀"），v1.7.39 令挪进「远程控制（慧尖云）」
卡的右侧——点击刷新、自动出现、复制这些行为不变。本文件钉**接线**（编码器正确性在
test_v1738_qr.py 里对账）：

  1) 位置：二维码块必须在 #remoteCard 内（且在 hub-main 之后＝右侧），页头不许残留；
  2) 接线活着：`renderBindQr` 在 loadRemoteControl 的**三条出口**（有码/未启用/读取失败）
     都被调到——漏一条就会残留上一次的码（过期码看着像当前码，比不显示更坏）；
     点击二维码 = `refreshBindQr` → `loadRemoteControl()`（重新拉码，不是重画旧码）；
  3) 载荷契约：二维码内容是 `HUJIAN-BIND:<载荷版本>:<6 位码>`，且该载荷必须真的能被
     自带编码器编出来（前缀变长到编不动时当场红）；小程序侧解析同一格式；
  4) 样式陷阱：`.hub-qr` 自带 display:flex，必须有 `[hidden]` 复位规则，否则没码时
     会摆一个空白方块；二维码渲染尺寸下限（太小扫不动）；
  5) 脚本顺序：qr.js 必须在 huijian.js 之前（HjQr 先存在）。
"""
import re
from pathlib import Path
import subprocess
import shutil

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "www" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "www" / "js" / "huijian.js").read_text(encoding="utf-8")
CSS = (ROOT / "www" / "css" / "huijian.css").read_text(encoding="utf-8")

PAYLOAD_SAMPLE = "HUJIAN-BIND:1:123456"      # 两端共同约定的载荷样本（小程序测试用同一串）
PANEL_BINDCODE_PATH = "/window_controller_gateway/hub/bindcode"   # 换码路由（POST；注册真值钉在 v1737 测试里）


def _element(html, marker):
    """按 <div …> 配平抽取元素块——锚点式/定宽窗切片会被新嵌套顶掉（本仓踩过多次）。"""
    i = html.index(marker)
    start = html.rindex("<div", 0, i)
    depth, j = 0, start
    while j < len(html):
        if html.startswith("<div", j):
            depth += 1
            j += 4
            continue
        if html.startswith("</div>", j):
            depth -= 1
            j += 6
            if depth == 0:
                return html[start:j]
            continue
        j += 1
    raise AssertionError("元素未闭合: " + marker)


def _fn(name):
    # 断言"只有一处定义"：本文件那条"除统一出口外不得直调 renderBindQr"的反钉曾被
    # 重复定义的旧版 loadRemoteControl 绕过（index 只取第一处＝验到死码），详见
    # test_v1746_panel_unique_funcs.py 的 docstring。
    hits = [m.start() for m in re.finditer(r"function\s+" + re.escape(name) + r"\s*\(", JS)]
    assert len(hits) == 1, \
        "函数 %s 出现 %d 次（应为 1；重名＝后者覆盖前者，钉会验到死码）" % (name, len(hits))
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


def test_qr_lives_in_remote_card_on_the_right():
    card = _element(HTML, 'id="remoteCard"')
    assert 'id="hubQr"' in card, "二维码块不在「远程控制」卡里（v1.7.39 用户令：从页头挪进卡右侧）"
    assert 'id="hubQrBox"' in card and 'id="hubQrTip"' in card, "二维码容器/码值标签丢失"
    assert card.index('id="hubQr"') > card.index('class="hub-main"'), \
        "二维码块在内容区之前（应在卡右侧，排在 hub-main 之后）"
    assert "hub-row" in card, "卡片缺 .hub-row 两栏容器（左侧状态+说明 / 右侧二维码）"
    header = _element(HTML, 'class="header"')
    assert "hubQr" not in header, "页头仍残留二维码块（用户在 v1.7.38 明确说那里太突兀）"
    assert "brand-qr" not in HTML, "旧 .brand-qr 残留"


def test_qr_block_has_both_refresh_paths_and_defaults_hidden():
    card = _element(HTML, 'id="remoteCard"')
    assert 'onclick="refreshBindQr()"' in card, "点击刷新未接线"
    assert "onkeydown" in card and "Enter" in card, "键盘无法触发刷新（只做了鼠标）"
    assert re.search(r'id="hubQr"[^>]*hidden', card), "二维码块默认不是隐藏的（加载中就摆空盒子）"


def test_panel_copy_points_to_the_qr_next_to_it():
    card = _element(HTML, 'id="remoteCard"')
    assert "二维码" in card and "扫一扫" in card, "卡片文案没指示可用扫一扫"
    assert "logo 旁" not in card, "文案仍说二维码在 logo 旁（v1.7.39 已挪位，用户会找不到）"
    # v1.7.40（用户令）：小程序在微信里叫「小慧语音」——只写"打开小程序"客户搜不到
    assert "小慧语音" in card, "文案缺可搜索的小程序名「小慧语音」（照文案搜不到＝没有入口）"


def test_render_bind_qr_is_called_on_every_exit_path():
    """单一渲染出口：GET 状态与 POST 换码都必须经 applyHubStatus，才不会有路径漏渲染。"""
    apply_body = _fn("applyHubStatus")
    assert "renderBindQr('')" in apply_body, "未启用分支没有清掉二维码（会残留上一次的码）"
    assert "renderBindQr(_bindCode)" in apply_body, "正常分支没有渲染二维码"
    for name in ("loadRemoteControl", "refreshBindCode"):
        assert "applyHubStatus(" in _fn(name), "%s 没走统一渲染出口" % name
    others = [n for n in re.findall(r"function (\w+)", JS)
              if n not in ("applyHubStatus", "renderBindQr") and "renderBindQr(" in _fn(n)]
    assert others == [], "除统一出口外还有函数直接渲染二维码（会绕过过期/未启用处理）: %s" % others
    render = _fn("renderBindQr")
    assert "wrap.hidden = true" in render and "wrap.hidden = false" in render, \
        "renderBindQr 没有显式开关显隐"
    assert "HjQr" in render, "renderBindQr 没走自带编码器"


def test_click_rotates_code_with_get_fallback():
    """点击＝换新码（POST），不是重读同一个码——过期码只读刷新刷不出可用的码。"""
    assert "refreshBindCode()" in _fn("refreshBindQr"), "点击二维码没有走换码路径"
    body = _fn("refreshBindCode")
    assert "haApi('%s', 'POST')" % PANEL_BINDCODE_PATH in body, "换码没走 POST 路由"
    assert "loadRemoteControl()" in body, "老集成没有换码路由时缺只读回退（会显示成读取失败）"


def test_panel_shows_expiry_and_points_to_the_click_to_renew():
    """码会过期：必须把"还剩多久/已过期＋点二维码换新码"摆出来，而不是等扫码失败才发现。"""
    card = _element(HTML, 'id="remoteCard"')
    assert 'id="hubCodeExp"' in card, "缺有效期提示元素"
    body = _fn("applyHubStatus")
    assert "bindCodeExpiresIn" in body and "bindCodeExpired" in body, "未读取过期字段"
    assert "剩余 " in body, "没有剩余时间文案"
    assert "已过期" in body and "点右边的二维码" in body, "过期后没有指路（用户只能反复扫死码）"
    assert re.search(r"\.hub-code-exp\.expired", CSS), "缺过期态样式（过期与正常看不出区别）"


def test_payload_contract_and_encoder_capacity():
    assert "BIND_PAYLOAD_PREFIX = 'HUJIAN-BIND:1:'" in JS, "载荷前缀被改（小程序按同一格式解析）"
    render = _fn("renderBindQr")
    assert "BIND_PAYLOAD_PREFIX + code" in render, "二维码内容不是 前缀+码（可能拼了别的字段）"
    assert PAYLOAD_SAMPLE.startswith("HUJIAN-BIND:1:"), "样本串与实现不一致"
    node = shutil.which("node")
    if node is None:
        return
    # 面板真载荷必须编得出来（前缀/码长一变就可能超容量——当场红，别等到真机扫不出）
    script = ("const qr=require(process.argv[1]);const r=qr.matrix(process.argv[2],{ecc:'M'});"
              "process.stdout.write(String(r.size))")
    proc = subprocess.run([node, "-e", script, str(ROOT / "www" / "js" / "qr.js"), PAYLOAD_SAMPLE],
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0 and proc.stdout.isdigit(), \
        "面板载荷编不出二维码：%s" % (proc.stderr or proc.stdout)[:200]


def test_copy_button_wired_with_fallback():
    assert 'id="copyCodeBtn"' in HTML and 'onclick="copyBindCode()"' in HTML, "复制按钮未接线"
    body = _fn("copyBindCode")
    assert "navigator.clipboard" in body and "writeText" in body, "没走剪贴板 API"
    assert "selectNodeContents" in body, "剪贴板被拒时没有退路（选中文本让用户自己复制）"
    assert "已复制" in body, "点完没有反馈（用户不知道成没成）"


def test_css_hidden_rule_and_touchable_size():
    assert re.search(r"\.hub-qr\[hidden\]\s*\{\s*display:\s*none", CSS), \
        ".hub-qr 缺 [hidden] 复位（自带 display:flex 会盖掉 hidden 属性）"
    assert re.search(r"\.hub-row\s*\{[^}]*display:\s*flex", CSS), "缺 .hub-row 两栏布局（二维码会掉到下一行）"
    m = re.search(r"\.hub-qr-box\s*\{([^}]*)\}", CSS)
    assert m, "缺 .hub-qr-box 样式"
    w = int(re.search(r"width:\s*(\d+)px", m.group(1)).group(1))
    assert w >= 56, "二维码渲染尺寸 %dpx 太小，手机可能扫不动" % w


def test_qr_script_loaded_before_huijian():
    i_qr = HTML.index("js/qr.js")
    i_hj = HTML.index("js/huijian.js")
    assert i_qr < i_hj, "qr.js 必须在 huijian.js 之前加载（否则 HjQr 未定义）"
