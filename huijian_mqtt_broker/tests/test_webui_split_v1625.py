"""v1.6.25 Web UI 三文件化钉桩测试。

拆分定案：www/index.html 的内联 <style>/<script> 字节无损搬至
www/css/huijian.css 与 www/js/huijian.js（搬运 diff 见提交说明），
CURRENT_VERSION 声明因测试锚留在 index.html 本体。本文件只钉"拆分
不破坏托管链路"的不变量：

1. 三文件齐备非空；index.html 无残留大块内联样式/脚本；
2. 资源引用必须相对路径——HA ingress 路径前缀可变，根绝对路径会被
   前缀打挂（同 v1.6.6 教训的 ingress 变体）；
3. CURRENT_VERSION 跨脚本声明有且仅有一处且在 index.html——huijian.js
   依赖该全局 let 绑定，重复声明是 SyntaxError 级破坏；
4. css/js 由 nginx `location /` 供出，该 location 必须带 no-store
   （ingress.conf 模板与 run.sh 生成版双查）——否则重演"插件升级了
   界面没变"的启发式缓存事故；
5. 外置脚本保持原内联位置（body 末尾、无 defer/async），且静态按钮
   onclick 调用的函数在 huijian.js 顶层有定义（classic script 的
   函数声明落 window，内联属性处理器才可解析）。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WWW = ROOT / "www"


def _read(rel: str) -> str:
    return (WWW / rel).read_text(encoding="utf-8")


def test_split_files_exist_nonempty():
    for rel in ("index.html", "css/huijian.css", "js/huijian.js"):
        assert _read(rel).strip(), f"{rel} 缺失或为空——三文件化不完整"


def test_index_html_no_bulk_inline_left():
    html = _read("index.html")
    assert "<style" not in html and "</style" not in html, "index.html 残留 <style> 大块"
    # 唯一允许的内联 script：CURRENT_VERSION 单行声明（测试锚要求留在本体）
    inline = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert len(inline) == 1, f"内联 script 段数异常: {inline}"
    assert re.fullmatch(r"\s*let CURRENT_VERSION = '[\d.]+';\s*", inline[0]), \
        f"残留内联脚本不是 CURRENT_VERSION 声明: {inline[0]!r}"
    assert "function" not in html.split("</head>")[0], "head 区混入 JS 残留"


def test_asset_refs_are_relative_paths():
    html = _read("index.html")
    # v1.7.1 cache-bust：引用可带 ?v=query，但仍必须相对路径。
    # 具体 ?v 与版本一致性由 test_audit_round8.TestVersionFields 钉死。
    assert re.search(r'href="css/huijian\.css(\?v=[\d.]+)?"', html), "缺相对路径样式引用"
    assert re.search(r'src="js/huijian\.js(\?v=[\d.]+)?"', html), "缺相对路径脚本引用"
    assert 'href="/' not in html and 'src="/' not in html, \
        "禁止根绝对路径资源引用——ingress 前缀会把 /css、/js 打挂"


def test_current_version_declared_once_in_index_only():
    html, js = _read("index.html"), _read("js/huijian.js")
    assert html.count("let CURRENT_VERSION") == 1
    assert "let CURRENT_VERSION" not in js and "const CURRENT_VERSION" not in js \
        and "var CURRENT_VERSION" not in js, \
        "huijian.js 重复声明 CURRENT_VERSION 会抛 SyntaxError（let 跨脚本不可重宣）"


def _static_location_block(text: str, label: str) -> str:
    m = re.search(r"location / \{(.*?)\n    \}", text, re.S)
    assert m, f"{label}: 找不到 location / 静态块——css/js 的 no-store 前提被改动"
    blk = m.group(1)
    assert "root /usr/share/nginx/html;" in blk, \
        f"{label}: location / root 变了，www/ 子目录（css/ js/）还由它供吗？复核本钉桩"
    assert "try_files" in blk and "/index.html" in blk, f"{label}: location / try_files 结构漂移"
    assert 'add_header Cache-Control "no-store" always;' in blk, \
        f"{label}: location / 缺 no-store——拆出的 css/js 会落入浏览器启发式缓存，" \
        "重演 v1.6.6『插件升级了界面没变』事故"


def test_static_assets_covered_by_no_store_template():
    _static_location_block((ROOT / "ingress.conf").read_text(encoding="utf-8"),
                           "ingress.conf")


def test_static_assets_covered_by_no_store_runtime():
    run_sh = (ROOT / "run.sh").read_text(encoding="utf-8")
    m = re.search(r"cat > /etc/nginx/http\.d/ingress\.conf <<NGINXEOF\n(.*?)\nNGINXEOF",
                  run_sh, re.S)
    assert m, "run.sh 内 ingress.conf heredoc 丢失"
    _static_location_block(m.group(1), "run.sh heredoc")


def test_external_script_keeps_inline_position_and_no_defer():
    html = _read("index.html")
    assert "defer" not in html and "async" not in html, \
        "原内联脚本是 body 末尾同步执行，defer/async 会改变执行时机语义"
    assert html.rindex('<script src="js/huijian.js') < html.rindex("</body>"), \
        "外置脚本必须在 body 末尾（与原内联位置一致，DOM 先于脚本就绪）"
    assert html.rindex('<script src="js/huijian.js') > html.rindex('<div class="footer"'), \
        "外置脚本必须落在正文之后"


def test_static_onclick_handlers_defined_in_js():
    html, js = _read("index.html"), _read("js/huijian.js")
    handlers = set(re.findall(r'onclick="(\w+)\(', html))
    assert handlers, "index.html 静态 onclick 丢失？钉桩前提变化需复核"
    for fn in handlers:
        assert re.search(rf"\bfunction {fn}\s*\(", js), \
            f"index.html 调用 {fn}()，但 huijian.js 顶层无此函数定义——拆分搬运不完整"
