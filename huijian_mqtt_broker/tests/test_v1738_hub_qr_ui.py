# -*- coding: utf-8 -*-
"""v1.7.38 钉桩：面板「logo 旁二维码 + 复制绑定码」的接线。

用户要求（2026-09-22）：绑定码"应该在 logo 旁边自动出现一个二维码，点击二维码可以刷新"。
本文件钉的是**接线**（编码器本身的正确性在 test_v1738_qr.py 里对账）：

  1) 结构：二维码块在页头 brand 里（logo 旁）、默认 hidden、带 click 与键盘两条刷新路径；
  2) 接线活着：`renderBindQr` 在 loadRemoteControl 的**三条出口**（有码/未启用/读取失败）
     都被调到——漏一条就会残留上一次的码（过期码看着像当前码，比不显示更坏）；
     点击二维码 = `refreshBindQr` → `loadRemoteControl()`（重新拉码，不是重画旧码）；
  3) 载荷契约：二维码内容是 `HUJIAN-BIND:<载荷版本>:<6 位码>`，且该载荷必须真的能被
     自带编码器编出来（前缀变长到编不动时当场红）；小程序侧解析同一格式；
  4) 样式陷阱：`.brand-qr` 自带 display:flex，必须有 `[hidden]` 复位规则，否则没码时
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


def _fn(name):
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


def _header_brand():
    m = re.search(r'<div class="brand">.*?</div>\s*</div>', HTML, re.S)
    assert m, "页头 brand 块锚点丢失"
    return m.group(0)


def test_qr_block_sits_next_to_logo_with_both_refresh_paths():
    brand = _header_brand()
    assert 'id="brandQr"' in brand, "二维码块不在页头 brand 里（用户要求 logo 旁）"
    assert 'id="brandQrBox"' in brand, "二维码容器丢失"
    assert 'onclick="refreshBindQr()"' in brand, "点击刷新未接线"
    assert "onkeydown" in brand and "Enter" in brand, "键盘无法触发刷新（只做了鼠标）"
    assert re.search(r'id="brandQr"[^>]*hidden', brand), "二维码块默认不是隐藏的（加载中就摆空盒子）"
    # 位置：在 actions 之前（logo 一侧），不是被塞到页头右端按钮后面
    assert brand.find('id="brandQr"') < HTML.find('class="actions"'), "二维码块跑到按钮后面去了"


def test_render_bind_qr_is_called_on_every_exit_path():
    body = _fn("loadRemoteControl")
    calls = body.count("renderBindQr(")
    assert calls == 3, "renderBindQr 只调了 %d 次（有码/未启用/读取失败三条出口都要调，" \
                       "漏调会残留过期码）" % calls
    render = _fn("renderBindQr")
    assert "wrap.hidden = true" in render and "wrap.hidden = false" in render, \
        "renderBindQr 没有显式开关显隐"
    assert "HjQr" in render, "renderBindQr 没走自带编码器"


def test_click_refetches_not_redraws():
    body = _fn("refreshBindQr")
    assert "loadRemoteControl()" in body, "点击二维码没有重新拉码（只重画旧码＝刷新是假的）"


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
    assert re.search(r"\.brand-qr\[hidden\]\s*\{\s*display:\s*none", CSS), \
        ".brand-qr 缺 [hidden] 复位（自带 display:flex 会盖掉 hidden 属性）"
    m = re.search(r"\.brand-qr-box\s*\{([^}]*)\}", CSS)
    assert m, "缺 .brand-qr-box 样式"
    w = int(re.search(r"width:\s*(\d+)px", m.group(1)).group(1))
    assert w >= 56, "二维码渲染尺寸 %dpx 太小，手机可能扫不动" % w


def test_qr_script_loaded_before_huijian():
    i_qr = HTML.index("js/qr.js")
    i_hj = HTML.index("js/huijian.js")
    assert i_qr < i_hj, "qr.js 必须在 huijian.js 之前加载（否则 HjQr 未定义）"
