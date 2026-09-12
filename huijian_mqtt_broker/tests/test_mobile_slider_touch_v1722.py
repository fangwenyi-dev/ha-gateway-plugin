"""v1.7.22 手机端三滑块防误触（用户报：位置/速度/力度距离过近，手动
调节容易误触发）。纯 CSS 批——静默失效面，按 CLAUDE.md 铁律钉断言：
① 触摸能力查询 (hover: none) and (pointer: coarse) 存在且包住滑块规则
   （按能力判定而非宽度断点，手机横屏/小平板同样生效）；
② 行距 18px + 命中区 30px（透明 padding + background-clip: content-box
   保 6px 细轨外观）→ 轨距 48px ≥ HIG 44px；
③ 拇指珠放大 26px（webkit）/ 22px（moz）；
④ 桌面基线不得回潮：基类 gap 7px / 命中 6px 不变（本批只加不改）。
"""
import pathlib
import re

CSS = (pathlib.Path(__file__).resolve().parents[1] / "www" / "css" / "huijian.css"
       ).read_text(encoding="utf-8")


def _touch_block() -> str:
    m = re.search(r"@media \(hover: none\) and \(pointer: coarse\) \{(.*?)\n\}", CSS, re.S)
    assert m, "缺少触摸能力查询块——手机端滑块防误触规则整体丢失"
    return m.group(1)


class TestTouchSliderErgonomics:
    def test_block_exists_and_is_ordered_before_reduce_motion(self):
        """插入位置契约：必须在 640px 块之后、reduce 块之前——
        test_starsky_v1627 的 reduce 段切片断言不受本批污染的前提"""
        i_touch = CSS.index("@media (hover: none) and (pointer: coarse)")
        assert CSS.index("@media (max-width: 640px)") < i_touch
        assert i_touch < CSS.index("@media (prefers-reduced-motion: reduce)")

    def test_row_gap_enlarged_for_touch(self):
        body = _touch_block()
        m = re.search(r"\.slider-group \{ gap: (\d+)px; \}", body)
        assert m, "触摸块内缺 .slider-group 行距规则"
        assert int(m.group(1)) >= 16, f"行距 {m.group(1)}px 不足以形成相邻滑杆安全带"

    def test_hit_area_grown_with_visual_track_preserved(self):
        """padding 撑命中、background-clip 收外观：height-padding 差必须
        恰好等于基类 6px 可见轨道，否则手机端轨道变粗/ thumb 偏心回潮"""
        body = _touch_block()
        m = re.search(r"input\[type=\"range\"\] \{([^}]*)\}", body, re.S)
        assert m, "触摸块内缺 input[type=range] 命中区规则"
        rule = m.group(1)
        h = int(re.search(r"height: (\d+)px", rule).group(1))
        p = int(re.search(r"padding: (\d+)px 0", rule).group(1))
        assert h - 2 * p == 6, "可见轨道必须仍是 6px（background-clip 口径的前提）"
        assert h >= 28, f"命中高度 {h}px 达不到 28px 触控下限"
        assert "background-clip: content-box" in rule, \
            "缺 background-clip——padding 会把轨道渲染成 30px 粗条"

    def test_thumbs_enlarged_for_touch(self):
        body = _touch_block()
        wk = re.search(r"::-webkit-slider-thumb \{ width: (\d+)px; height: \1px; \}", body)
        assert wk and int(wk.group(1)) >= 24, "webkit 拇指珠未放大到 ≥24px"
        moz = re.search(r"::-moz-range-thumb \{ width: (\d+)px; height: \1px; \}", body)
        assert moz and int(moz.group(1)) >= 20, "Firefox 拇指珠未放大到 ≥20px"

    def test_desktop_baseline_untouched(self):
        """基类规则钉死（本批只加不改）：gap 7px、input 6px、thumb 19px"""
        base = re.search(r"^\.slider-group \{[^}]*\}", CSS, re.M).group(0)
        assert "gap: 7px" in base
        base_input = re.search(r"^input\[type=\"range\"\] \{([^}]*)\}", CSS, re.M | re.S).group(1)
        assert "height: 6px" in base_input
        assert "background-clip" not in base_input, "桌面基类被污染——宽轨道回潮"
        wk = re.search(r"input\[type=\"range\"\]::-webkit-slider-thumb \{([^}]*)\}", CSS, re.S).group(1)
        assert "width: 19px" in wk


class TestNoBehaviorChange:
    def test_js_untouched_by_this_batch(self):
        """防误触纯 CSS 批：JS 不得出现为滑块新增的 pointer/touch 事件劫持
        （松手才发令的 change 语义 + v1.7.21 位置合并是唯一提交闸口）"""
        js = (pathlib.Path(__file__).resolve().parents[1] / "www" / "js" / "huijian.js"
              ).read_text(encoding="utf-8")
        for slider in ("position-slider", "speed-slider", "strength-slider"):
            assert js.count(slider) >= 2, f"{slider} 渲染/静默更新引用丢失"
        assert "touchstart" not in js and "pointerdown" not in js, \
            "滑块新增触摸劫持与本批口径不符（误触根因是间距，不是事件）"
