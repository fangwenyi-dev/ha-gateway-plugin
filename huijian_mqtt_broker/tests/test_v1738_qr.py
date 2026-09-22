# -*- coding: utf-8 -*-
"""v1.7.38 钉桩：面板二维码（www/js/qr.js）——自研编码器的正确性 + 零依赖。

为什么自研：ingress iframe 有 CSP、本仓前端从不连外网，引不了 CDN 库；绑定码
要显示成二维码（用户要求"logo 旁自动出现一个二维码，点击刷新"），只能自带实现。

怎么保证对：**跟独立实现逐格对账**，不靠自证——
  1) 显式掩码下，本实现的模块矩阵必须与 Python `qrcode`（另一套独立实现，
     且是业界长期使用的库）逐格一致（版本 1–6 里的 2/3/4/5 都覆盖到：
     单块、多块、两组块三种分块形态）；
  2) 自动选掩码时，本实现的输出必须等于"参考实现在同一掩码下的矩阵"
     ——掩码编号写在格式信息里，解码器按它解，所以掩码选哪个都能读，
     但符号本身必须合法；
  3) 有条件时再用 ZXing（独立解码器）**真解一遍**：矩阵 → 位图 → 文本回读。
     没有 zxing-cpp 时显式 skip 并写明原因（不静默）。

另钉零依赖：qr.js 里不得出现任何网络 API / 远程 URL（SVG 命名空间除外）。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import qrcode                      # 硬依赖：缺了就红，不允许静默跳过
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q
from qrcode.util import MODE_8BIT_BYTE, QRData

ROOT = Path(__file__).resolve().parents[1]
QR_JS = ROOT / "www" / "js" / "qr.js"
NODE = shutil.which("node")

LEVELS = {"L": ERROR_CORRECT_L, "M": ERROR_CORRECT_M, "Q": ERROR_CORRECT_Q, "H": ERROR_CORRECT_H}
PAYLOAD = "HUJIAN-BIND:1:123456"      # 面板实际编码的载荷形态


def reference(payload: str, ecc: str = "M", mask=None) -> list:
    """Python qrcode 的字节模式矩阵（独立实现 = 标准答案）。"""
    qr = qrcode.QRCode(version=None, error_correction=LEVELS[ecc], box_size=1, border=0,
                       mask_pattern=mask)
    qr.add_data(QRData(payload.encode("utf-8"), mode=MODE_8BIT_BYTE))
    qr.make(fit=True)
    return ["".join("1" if m else "0" for m in row) for row in qr.modules]


def js_matrices(cases: list) -> list:
    """把用例交给 node 里的 qr.js 算，回 [{rows, mask, size}, ...]。"""
    if NODE is None:
        pytest.fail("找不到 node——面板二维码的矩阵算不出来（CI 有 node，本机需装）")
    script = (
        "const qr = require(process.argv[1]);"
        "let raw='';process.stdin.on('data',d=>raw+=d);"
        "process.stdin.on('end',()=>{"
        "  const cases=JSON.parse(raw);"
        "  const out=cases.map(c=>{const o={ecc:c.ecc};if(c.mask!==null&&c.mask!==undefined)o.mask=c.mask;"
        "    const r=qr.matrix(c.payload,o);"
        "    return {rows:r.modules.map(x=>x.join('')),mask:r.mask,size:r.size};});"
        "  process.stdout.write(JSON.stringify(out));});"
    )
    proc = subprocess.run([NODE, "-e", script, str(QR_JS)], input=json.dumps(cases),
                          capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        pytest.fail("node 跑 qr.js 失败：%s" % (proc.stderr or proc.stdout)[:500])
    return json.loads(proc.stdout)


def diff_rows(got: list, want: list) -> str:
    if len(got) != len(want):
        return "尺寸不符 %d vs %d" % (len(got), len(want))
    bad = [i for i in range(len(got)) if got[i] != want[i]]
    return "差异行 %d 处（前几行 %s）" % (len(bad), bad[:5]) if bad else ""


# ── 1) 显式掩码：与参考实现逐格一致 ──────────────────────────────
@pytest.mark.parametrize("mask", [0, 1, 2, 3, 4, 5, 6, 7])
def test_matrix_matches_reference_for_every_mask(mask):
    got = js_matrices([{"payload": PAYLOAD, "ecc": "M", "mask": mask}])[0]
    want = reference(PAYLOAD, "M", mask)
    assert not diff_rows(got["rows"], want), "掩码 %d 下矩阵与参考实现不一致：%s" % (
        mask, diff_rows(got["rows"], want))


@pytest.mark.parametrize("ecc", ["L", "M", "Q", "H"])
def test_matrix_matches_reference_for_every_ecc(ecc):
    got = js_matrices([{"payload": PAYLOAD, "ecc": ecc, "mask": 2}])[0]   # 固定掩码才可逐格比
    want = reference(PAYLOAD, ecc, 2)
    assert not diff_rows(got["rows"], want), "纠错级别 %s 不一致：%s" % (
        ecc, diff_rows(got["rows"], want))


def test_matrix_matches_reference_for_multiblock_versions():
    """版本 4-H（4 块）与版本 5-Q（两组块）——分块交织写错时只有这两种形态会暴露。"""
    cases = [{"payload": "Y" * 32, "ecc": "H", "mask": 5},
             {"payload": "X" * 60, "ecc": "Q", "mask": 5}]
    for c, g in zip(cases, js_matrices(cases)):
        want = reference(c["payload"], c["ecc"], c["mask"])
        assert not diff_rows(g["rows"], want), "%s/%s 多块交织不一致：%s" % (
            c["ecc"], c["mask"], diff_rows(g["rows"], want))


# ── 2) 自动选掩码：符号本身必须合法 ─────────────────────────────
@pytest.mark.parametrize("ecc", ["L", "M", "Q", "H"])
def test_auto_mask_symbol_is_valid(ecc):
    got = js_matrices([{"payload": PAYLOAD, "ecc": ecc, "mask": None}])[0]
    assert 0 <= got["mask"] <= 7, "掩码编号越界: %r" % got["mask"]
    want = reference(PAYLOAD, ecc, got["mask"])
    assert not diff_rows(got["rows"], want), (
        "自选掩码 %d 下的矩阵不是合法符号：%s" % (got["mask"], diff_rows(got["rows"], want)))


def test_auto_mask_is_stable_for_panel_payload():
    """面板每次刷新都用同一个载荷——矩阵必须稳定（否则二维码看着在变，用户以为码换了）。"""
    a = js_matrices([{"payload": PAYLOAD, "ecc": "M", "mask": None}])[0]
    b = js_matrices([{"payload": PAYLOAD, "ecc": "M", "mask": None}])[0]
    assert a["rows"] == b["rows"] and a["mask"] == b["mask"], "同一载荷两次生成结果不同"


def test_too_long_payload_raises_instead_of_truncating():
    """超长载荷必须显式报错——静默截断会印出一个"扫出来是别的码"的二维码。"""
    if NODE is None:
        pytest.skip("无 node")
    script = ("const qr=require(process.argv[1]);"
              "try{qr.matrix('Z'.repeat(400));process.stdout.write('NO_THROW')}"
              "catch(e){process.stdout.write('THROW:'+e.message)}")
    proc = subprocess.run([NODE, "-e", script, str(QR_JS)], capture_output=True, text=True, encoding="utf-8")
    assert proc.stdout.startswith("THROW:"), "超长载荷没有抛错：%r" % proc.stdout[:120]


# ── 3) ZXing 真解码（有条件）────────────────────────────────────
def test_decodes_with_zxing_roundtrip():
    zxingcpp = pytest.importorskip("zxingcpp", reason="未装 zxing-cpp（pip install zxing-cpp）——本用例是"
                                                   "在矩阵对照之外的独立解码器复核")
    PIL_Image = pytest.importorskip("PIL.Image", reason="未装 Pillow")
    cases = [{"payload": PAYLOAD, "ecc": e, "mask": None} for e in ("L", "M", "Q", "H")]
    cases += [{"payload": PAYLOAD, "ecc": "M", "mask": m} for m in range(8)]
    for c, got in zip(cases, js_matrices(cases)):
        rows, n, quiet, scale = got["rows"], got["size"], 4, 6
        img = PIL_Image.new("L", ((n + quiet * 2) * scale, (n + quiet * 2) * scale), 255)
        px = img.load()
        for r in range(n):
            for col in range(n):
                if rows[r][col] == "1":
                    for dy in range(scale):
                        for dx in range(scale):
                            px[(col + quiet) * scale + dx, (r + quiet) * scale + dy] = 0
        res = zxingcpp.read_barcode(img)
        assert res is not None and res.text == c["payload"], \
            "ZXing 解不出/解错（ecc=%s mask=%s）：%r" % (c["ecc"], c["mask"], res and res.text)


# ── 零依赖：不许有网络 API ──────────────────────────────────────
def test_qr_js_has_no_network_or_dom_strings():
    src = QR_JS.read_text(encoding="utf-8")
    banned = ["fetch(", "XMLHttpRequest", "importScripts", "new Image", "innerHTML",
              "document.write", "WebSocket", "sendBeacon", "eval("]
    hit = [b for b in banned if b in src]
    assert not hit, "qr.js 出现被禁 API（面板在 ingress 里、且不该有注入面）: %s" % hit
    urls = [u for u in re.findall(r"https?://[^\s'\"]+", src) if "www.w3.org" not in u]
    assert not urls, "qr.js 出现外部 URL（CSP 会拦、且等于偷偷联网）: %s" % urls
