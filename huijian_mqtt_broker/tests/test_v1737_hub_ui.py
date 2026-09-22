# -*- coding: utf-8 -*-
"""v1.7.37 钉桩：插件页「远程控制（慧尖云）」绑定卡。

P0 通道（加载项出站长连 hub + 小程序 callContainer）在 v1.7.35/36 打通后，
用户手上还缺"在哪看绑定码、在哪输"这一环——绑定码只存在于
`GET /api/window_controller_gateway/hub` 的 JSON 里，页面不渲染就等于没有入口。
本测试守三件事：

  1) 卡片结构在位（id 契约：hubDot/hubStatus/hubCode/hubGateway），文案含
     「远程控制」「绑定码」，且明确指向小程序里的入口名——改文案漏改另一侧
     会直接红（跨仓口径写死在两处，见 tests/remote-bind-entry 的小程序侧）；
  2) 前端真的会去读那个路由，而且**不是死码**（`refreshAll` 必须调用它）——
     只断言"函数存在"是半条钉：把调用删掉页面照样空白而测试全绿；
  3) 路由字符串单一真源：面板里拼的路径必须等于 `api.py` 注册的 url（去掉
     `/api/` 前缀）——漂移即 404，而 404 只会显示成"读取失败"，没人会立刻
     联想到是路径拼错。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "www" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "www" / "js" / "huijian.js").read_text(encoding="utf-8")
API = (ROOT / "custom_components" / "window_controller_gateway" / "api.py").read_text(encoding="utf-8")

VIEW_URL = "/api/window_controller_gateway/hub"          # api.py 里注册的路由
PANEL_PATH = "/window_controller_gateway/hub"            # haApi() 前缀 /api/ha/ 之后的路径


def _card():
    """按 <div …> 配平抽取 #remoteCard 整块（定宽窗/锚点式切片会被新嵌套顶掉）。"""
    marker = 'id="remoteCard"'
    i = HTML.index(marker)
    start = HTML.rindex("<div", 0, i)
    depth, j = 0, start
    while j < len(HTML):
        if HTML.startswith("<div", j):
            depth += 1
            j += 4
            continue
        if HTML.startswith("</div>", j):
            depth -= 1
            j += 6
            if depth == 0:
                return HTML[start:j]
            continue
        j += 1
    raise AssertionError("远程控制卡未闭合（#remoteCard）")


def _func(name):
    """按花括号计数抽整个函数体（定宽窗口会被新注释顶出）。"""
    i = JS.index("function %s(" % name)
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


def test_card_structure_and_copy():
    card = _card()
    for el_id in ("hubDot", "hubStatus", "hubCode", "hubGateway"):
        assert f'id="{el_id}"' in card, f"绑定卡缺元素 #{el_id}"
    assert "远程控制" in card, "卡片标题丢了「远程控制」"
    assert "绑定码" in card, "卡片没有「绑定码」字样（用户找不到要抄什么）"
    # 跨仓口径：小程序侧的入口文案必须与这里指的同一处（另一侧由小程序仓钉住）
    assert "LoRa 网关" in card and "绑定微信远程控制" in card, \
        "卡片未写清小程序入口路径（用户不知道去哪里输码）"
    assert "10 分钟" in card, "未说明绑定码有效期（过期会让用户以为坏了）"


def test_panel_reads_the_view_and_call_is_live():
    body = _func("loadRemoteControl")
    assert "haApi('%s')" % PANEL_PATH in body, "绑定卡没有读集成侧 hub 视图"
    # 防死码凑数：函数必须真被刷新主流程调用
    refresh = _func("refreshAll")
    assert "loadRemoteControl()" in refresh, "loadRemoteControl 未被 refreshAll 调用（死码）"


def test_panel_route_matches_registered_view():
    urls = re.findall(r'url\s*=\s*"([^"]+)"', API)
    assert VIEW_URL in urls, f"api.py 未注册 {VIEW_URL}：{urls}"
    # 真值从面板源码里抽，不是再抄一遍常量——否则这条钉只证明了常量等于自己
    m = re.search(r"haApi\('([^']+)'\)", _func("loadRemoteControl"))
    assert m, "loadRemoteControl 里找不到 haApi 调用锚点"
    assert m.group(1) == VIEW_URL[len("/api"):], \
        f"面板路径 {m.group(1)} 与 api.py 注册路由 {VIEW_URL} 漂移"


def test_panel_handles_disabled_and_error_states():
    body = _func("loadRemoteControl")
    assert "!info.enabled" in body and "未启用" in body, "老集成没有该路由时未降级为「未启用」"
    assert "读取失败" in body, "读取失败态缺失（页面会一直显示检测中）"
    assert "dot-ok" in body and "dot-warn" in body, "连接状态未区分已连接/未连接"
    # secret 绝不出现在前端：视图本就不下发，前端更不该有渲染点
    assert "secret" not in body.lower(), "前端出现 secret 字段引用（凭据面收口纪律）"
    assert "secret" not in HTML.lower(), "页面 HTML 出现 secret 字样"


def test_bind_code_style_is_readable():
    css = (ROOT / "www" / "css" / "huijian.css").read_text(encoding="utf-8")
    m = re.search(r"\.hub-code\s*\{(.*?)\}", css, re.S)
    assert m, "缺少 .hub-code 样式（6 位码要等宽+字距，手抄才不出错）"
    block = m.group(1)
    assert "monospace" in block and "letter-spacing" in block, "绑定码未用等宽+字距排版"
