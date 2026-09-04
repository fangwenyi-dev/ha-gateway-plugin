"""v1.6.27 Web UI「星辰大海」重设计回归钉桩。

设计权威＝小程序记忆体标准条 0d2200c5（工程口径 d0c93032）+ 终版细节条
901a18df；本文件把标准里**可机器化**的硬约束钉进 CI：令牌逐值、分层规矩
（.page 无底色/.star-bg fixed z0/pointer-events:none）、流星只准向下且行程
1100px、星云一朵 45s 且宁淡、行星双层时钟解耦、固定种子确定性、旧靛紫
主题零残留、JS 用到的 class 在 CSS 必须全部有归属（防搬运式漏样式）。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WWW = ROOT / "www"
CSS = (WWW / "css/huijian.css").read_text(encoding="utf-8")
INDEX = (WWW / "index.html").read_text(encoding="utf-8")
SKY = (WWW / "js/starsky.js").read_text(encoding="utf-8")
JS = (WWW / "js/huijian.js").read_text(encoding="utf-8")


def _code(css: str) -> str:
    """去块注释后的 CSS（标准里 #4f46e5 等旧色只准出现在说明文字）。"""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


class TestDesignTokens:
    def test_standard_tokens_verbatim(self):
        code = re.sub(r"\s+", "", _code(CSS))
        for tok in ("--primary:#0ea5e9", "--primary-dark:#0284c7",
                    "--primary-light:#38bdf8", "--accent:#06b6d4",
                    "--secondary:#f59e0b", "--bg-main:#030712",
                    "--surface:#0a0f1e", "--bg-card:rgba(255,255,255,.07)",
                    "--bg-elevated:rgba(255,255,255,.10)",
                    "--card-border:rgba(255,255,255,.14)",
                    "--text-primary:#f8fafc", "--text-secondary:#94a3b8"):
            assert tok in code, f"标准令牌缺失/走样: {tok}"

    def test_old_indigo_theme_dead(self):
        code = _code(CSS)
        for dead in ("#4f46e5", "#5b52f0", "#818cf8", "#4338ca", "#312e81",
                     "#eef2ff", "#f4f6fc", "#e6eaf2"):
            assert dead not in code, f"旧靛紫主题色值回潮: {dead}"

    def test_purple_confined_to_ambient(self):
        """紫只允许出现在氛围底色层；按钮/图标前景禁紫（标准原话）。"""
        code = _code(CSS)
        tilt = re.search(r"\.btn-tilt \{[^}]*\}", code).group(0)
        assert "#8b5cf6" not in tilt and "#6366f1" not in tilt and \
            "#818cf8" not in tilt, "内倒按钮禁紫（v1.6.26 旧紫渐变回潮）"


class TestLayerArchitecture:
    def test_star_bg_fixed_z0(self):
        code = _code(CSS)
        seg = code[code.index(".star-bg {"):code.index(".nebula {")]
        assert "position: fixed" in seg and "z-index: 0" in seg
        assert "pointer-events: none" in seg, "装饰层不得吞点击"
        assert "inset: 0" in seg

    def test_page_is_z1_without_background(self):
        """规矩①：内容根不得带底色，否则整块盖住星空（标准 9 页踩坑史）。"""
        code = _code(CSS)
        page = re.search(r"\.page \{([^}]*)\}", code).group(1)
        assert "position: relative" in page and "z-index: 1" in page
        assert "background" not in page

    def test_body_has_no_maxwidth(self):
        body = re.search(r"\nbody \{(.*?)\n\}", _code(CSS), re.S).group(1)
        assert "max-width" not in body, "body 限宽会截断星空（宽度已移到 .page）"

    def test_theme_color_matches_deep_space(self):
        assert 'name="theme-color" content="#030712"' in INDEX


class TestSkyElements:
    def test_meteor_seven_downward_1100(self):
        assert INDEX.count('<span class="meteor') == 7, "流星恰 7 颗（标准）"
        seg = CSS[CSS.index("@keyframes meteor-fall"):][:700]
        assert "translateY(1100px)" in seg, "行程须 1100px（官网 700px 竖屏截断）"
        assert "translateY(-" not in seg, "流星只准向下"
        durs = [float(m) for m in re.findall(
            r"\.meteor-\d \{[^}]*?--mdur: ([\d.]+)s", CSS)]
        assert len(durs) == 7 and all(10.0 <= d <= 16.0 for d in durs), \
            f"流星 10~16s 全周期节奏: {durs}"
        delays = [float(m) for m in re.findall(
            r"\.meteor-\d \{[^}]*?--mdelay: (-?[\d.]+)s", CSS)]
        assert len(delays) == 7 and all(d < 0 for d in delays), \
            f"流星必须负相位进场（正延迟=打开页面头几秒无星可看，用户实测反馈）: {delays}"

    def test_nebula_matches_official_master(self):
        """星云＝官网母本 v0.0.1 (www/index.html L105-117) 的多团结构，
        用户 2026-09-07 校准以官网为准（覆盖小程序单团旧适配）。
        钉三团 + 三 keyframe 逐值，禁走样。"""
        assert INDEX.count('class="nebula"') == 1 and 'class="nebula3"' in INDEX
        code = _code(CSS)
        # 蓝团 ::before 左上、青团 ::after 右下、金团 .nebula3 中上（官网值）
        b = re.search(r"\.nebula::before \{([^}]*)\}", code).group(1)
        a = re.search(r"\.nebula::after \{([^}]*)\}", code).group(1)
        g = re.search(r"\.nebula3 \{([^}]*)\}", code).group(1)
        assert "rgba(14, 165, 233, .10)" in b and "top: -30%" in b and "aurora-move1 45s" in b
        assert "rgba(6, 182, 212, .08)" in a and "bottom: -20%" in a and "aurora-move2 50s" in a
        assert "rgba(245, 158, 11, .07)" in g and "aurora-move3 60s" in g
        # 三团 peak α 均 ≤.10（克制的光；官网原值）
        for blk in (b, a, g):
            alphas = [float(x) for x in re.findall(r"rgba\([\d, ]+, (\.[\d]+)\)", blk)]
            assert alphas and max(alphas) <= 0.10, f"星云团宁淡勿浓: {alphas}"
        # 三 keyframe 齐备（整体漂移，非内核缩放雾）
        for kf in ("@keyframes aurora-move1", "@keyframes aurora-move2", "@keyframes aurora-move3"):
            assert kf in code, f"缺官网漂移关键帧 {kf}"
        assert "nebula-drift" not in code, "旧单团 nebula-drift 应已移除"

    def test_reduced_motion_kill_switch(self):
        assert "@media (prefers-reduced-motion: reduce)" in CSS
    def test_logo_dual_animation(self):
        seg = re.search(r"\.brand-logo \{[^}]*\}", _code(CSS)).group(0)
        assert "hero-float" in seg and "hero-breathe" in seg, \
            "logo 呼吸+悬浮双动画并行（标准：品牌永不触零）"
        br = CSS[CSS.index("@keyframes hero-breathe"):][:200]
        assert re.search(r"opacity: \.?0?\.7", br), \
            "呼吸下限 .7（0.4 过暗被否，品牌不触零）"


class TestStarskyJs:
    def test_fixed_seed(self):
        assert "mulberry32" in SKY, "固定种子 PRNG（全站同一片天机制）"
        assert "0x5EA7C0DE" in SKY

    def test_planet_clock_contract(self):
        assert "i < 16" in SKY, "行星恰 16 颗"
        assert re.search(r"between\(55, 75\)", SKY), "漂移 55~75s"
        assert re.search(r"between\(3\.5, 7\)", SKY), "明灭 3.5~7s"
        assert "(i % 10) < 6" in SKY, "60% 星云区偏置"
        # 偏置区必须随官网三团落点重排（左上蓝/中上金/右下青），
        # 禁仍指旧单团左下（x2-52/y52-96）
        assert "between(2, 42)" in SKY and "between(55, 88)" in SKY and "between(60, 97)" in SKY, \
            "行星偏置区须对位官网三团"
        assert "between(52, 96)" not in SKY, "旧单团左下偏置区已作废"
        assert re.search(r"pick\(\[3, 3, 4, 4, 6\]\)", SKY), "3/4/6px 三档"
        # 双层独立时钟 = 两个 DOM 层各自 animation（漂移在 .orbit-wrap，
        # 明灭在 .planet）——CSS 侧耦合回潮即红
        orb = re.search(r"\.orbit-wrap \{[^}]*\}", CSS).group(0)
        pl = re.search(r"\.planet \{[^}]*\}", CSS).group(0)
        assert "planet-drift" in orb and "planet-pulse" not in orb
        assert "planet-pulse" in pl and "planet-drift" not in pl

    def test_decorative_layer_isolation(self):
        assert "fetch" not in SKY and "XMLHttpRequest" not in SKY, \
            "装饰层零网络"
        assert SKY.count("if (!host) return") >= 2, \
            "容器缺失必须静默跳过——装饰层永不反噬功能层"


class TestDomHookCoverage:
    """JS 动态模板 + 静态骨架用到的每个 class 必须在 CSS 有规则
    （重设计最容易翻车的就是漏样式导致裸元素浮在深空上）。"""

    def test_every_used_class_has_css_rule(self):
        used = set()
        for src in (JS, INDEX):
            for raw in re.findall(r'class="([^"{]+)"', src):
                for tok in raw.replace("'", " ").replace("?", " ").split():
                    if re.fullmatch(r"[A-Za-z][\w-]*", tok):
                        used.add(tok)
        # 白名单：无独立样式语义的钩子（position-slider 继承滑块主色；
        # *-value 三子类和 checkUpdateBtn 经基类 .slider-value/.btn 合成生效）
        skip = {"position-slider", "checkUpdateBtn",
                "position-value", "speed-value", "strength-value"}
        missing = {c for c in used - skip
                   if not re.search(rf"\.{re.escape(c)}\b", CSS)}
        assert not missing, f"重设计遗漏样式归属: {sorted(missing)}"

    def test_functions_called_by_onclick_survive(self):
        # 与 v1.6.25 三文件化守卫同族：骨架改动不得动到 onclick 函数面
        for fn in set(re.findall(r'onclick="(\w+)\(', INDEX)):
            assert re.search(rf"\bfunction {fn}\s*\(", JS), f"{fn}() 丢失"


class TestEmptySlotsTransparent:
    """用户校准的留空原则：网关/子设备区未添加处必须透出星空，
    玻璃只落在真实存在的悬浮件上（网关头、设备瓷砖各自自持）。"""

    def _rule(self, selector):
        m = re.search(re.escape(selector) + r" \{([^}]*)\}", _code(CSS))
        assert m, f"缺少规则 {selector}"
        return m.group(1)

    def test_gateway_card_flush(self):
        assert 'class="card card-flush"' in INDEX, "网关区须用留空卡"
        assert 'class="card card-flush card-dense"' in INDEX, \
            "服务状态板 v1.6.30 起同走留空（用户令：页头下方长玻璃取消）"
        r = self._rule(".card-flush")
        assert "background: transparent" in r and "backdrop-filter: none" in r

    def test_gateway_container_has_no_slab(self):
        r = self._rule(".gateway-item")
        assert "background" not in r, "网关容器铺底=空位也被磨成雾（违留空原则）"

    def test_glass_lives_on_real_blocks(self):
        hdr = self._rule(".gateway-header")
        assert "--bg-card" in hdr and "backdrop-filter" in hdr, "网关头部须自持玻璃"
        dev = self._rule(".device-item")
        assert "--bg-card" in dev and "backdrop-filter" in dev, "设备瓷砖须真玻璃（含磨砂）"

    def test_empty_hint_spans_row(self):
        """empty-hint 是 .device-list 的子 <p>，grid 改造后必须横跨整行，
        否则"暂无子设备"提示被挤进首根 ≤340px 轨道左偏（v1.6.28 实测逮获）"""
        rule = self._rule(".device-list .empty-hint")
        assert "grid-column: 1 / -1" in rule

    def test_tiles_uniform_5005_height(self):
        """v1.6.29 用户改令：全部子设备玻璃按 5005 统一高度——行内
        stretch 拉齐 + min-height:262px（5005 满控件实测高）双保险，
        作废 v1.6.27 的各自 hug 口径。"""
        grid = self._rule(".device-list")
        assert "align-items: start" not in grid, "hug 口径已作废，不得收缩"
        assert "minmax(280px, 340px)" in grid, \
            "轨道封顶保留（单设备行右侧留空不拉伸）"
        dev = self._rule(".device-item")
        assert "min-height: 262px" in dev, "5005 统一高度锚"
        assert "height" not in dev.replace("min-height", ""), "禁止固定高度"

    def test_reduced_motion_meteor_keeps_flowing(self):
        """v1.6.29 官网同款口径：减弱动画下流星**不停**——官网尾注注入
        duration !important 穿透其 reduce 守卫（用户同浏览器实证官网照见
        流星），母本行为即标准。流星走 slow 关键帧慢速流动、其余动画静止。
        禁回潮两版旧口径（全隐身 v1.6.28 / 静态冻结 v1.6.29 初版）"""
        seg = CSS[CSS.index("@media (prefers-reduced-motion: reduce)"):]
        m = re.search(r"\.meteor \{([^}]*)\}", seg).group(1)
        assert "animation-name: meteor-fall-slow !important" in m
        assert "animation-duration: var(--mdur, 12s) !important" in m
        assert "animation-iteration-count: infinite !important" in m
        assert "translateY(260px)" not in seg, "静态冻结口径已作废"
        kf = CSS[CSS.index("@keyframes meteor-fall-slow"):][:280]
        assert "translateY(850px)" in kf and "opacity: .9" in kf and "opacity: .5" in kf, \
            "slow 关键帧温和参数（峰 .9 尾 .5 程 850px）"

    def test_brand_logo_image(self):
        """页头＝慧尖真 logo（v1.6.29 用户指定，替换 📡 emoji），素材入 www/img
        随 Dockerfile COPY www/ 整目录进镜像"""
        assert 'class="brand-logo"><img src="img/logo.png"' in INDEX.replace("\n", " ").replace("  ", " ") or 'img/logo.png' in INDEX
        logo = Path(__file__).resolve().parents[1] / "www" / "img" / "logo.png"
        assert logo.is_file() and logo.stat().st_size > 10_000, "logo 素材随包"
        assert ".brand-logo img" in CSS, "img 铺盘样式在位"
