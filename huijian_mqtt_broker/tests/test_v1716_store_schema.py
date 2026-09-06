# -*- coding: utf-8 -*-
"""v1.7.16 钉桩：config.yaml 的商店契约——schema/watchdog 必须过 Supervisor 真实校验。

背景（2026-09-06 现网事故）：v1.7.12 把 schema 写成 `username: str=huijian` /
`password: password=huijian2022`——`=默认值` 是臆造语法。Supervisor 校验 schema
元素的 RE_SCHEMA_ELEMENT（supervisor/apps/options.py；2026.05.1 前在
supervisor/addons/options.py）只接受 类型、类型(min,max)、尾缀 ? 三种形态，
一手源码 + 全历史（0.62→2026.09 各 tag）实证从无 `=`。后果：商店刷新时该
schema 元素校验 vol.Invalid → store/data.py 记 WARNING "Can't read ...
config.yaml" 后 `continue` → **加载项从商店整体静默消失**（仓库本身仍显示
正常），新装用户加了仓库链接也找不到"慧尖 LoRa 网关"。此前 463 个测试全部
没按 Supervisor 真实语法校验过 schema——静默失效面重演 CLAUDE.md 教训，本钉
桩补上。

下方两条正则逐字抄自上游（两代文件路径实证一致）；上游若演进语法，同步本钉
并复核，而不是给 config.yaml 塞回 `=`。默认值的正规供给面永远是 options: 块
+ run.sh 启动期凭据自动恢复。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = (ROOT / "config.yaml").read_text(encoding="utf-8")

# —— 逐字抄自 home-assistant/supervisor apps/options.py::RE_SCHEMA_ELEMENT
#    (2026.05.0 时代同物在 addons/options.py，两代一致) ——
RE_SCHEMA_ELEMENT = re.compile(
    r"^(?:"
    r"|bool"
    r"|email"
    r"|url"
    r"|port"
    r"|device(?:\((?P<filter>subsystem=[a-z]+)\))?"
    r"|str(?:\((?P<s_min>\d+)?,(?P<s_max>\d+)?\))?"
    r"|password(?:\((?P<p_min>\d+)?,(?P<p_max>\d+)?\))?"
    r"|int(?:\((?P<i_min>-?\d+)?,(?P<i_max>-?\d+)?\))?"
    r"|float(?:\((?P<f_min>-?\d*\.?\d+)?,(?P<f_max>-?\d*\.?\d+)?\))?"
    r"|match\((?P<match>.*)\)"
    r"|list\((?P<list>.+)\)"
    r")\??$"
)

# —— 逐字抄自 supervisor/apps/validate.py::_SCHEMA_APP_CONFIG["watchdog"] ——
RE_WATCHDOG = re.compile(
    r"^(?:https?|\[PROTO:\w+\]|tcp):\/\/\[HOST\]:(\[PORT:\d+\]|\d+).*$"
)


def _block(name):
    """顶层键块（到下一个顶格键为止），剔除注释与空行后的 (键, 值) 对。"""
    m = re.search(rf"^{name}:\n(.*?)(?=^\S|\Z)", CFG, re.M | re.S)
    assert m, f"config.yaml {name}: 块锚丢失"
    pairs = []
    for line in m.group(1).splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        km = re.match(r"\s*(\w+):\s*(.+?)\s*$", line)
        if km:
            pairs.append((km.group(1), km.group(2)))
    return pairs


def test_every_schema_element_passes_supervisor_regex():
    """每个 schema 类型串必须匹配上游 RE_SCHEMA_ELEMENT——
    否则商店刷新整份 config.yaml 被拒、加载项静默消失（2026-09-06 事故）。"""
    pairs = _block("schema")
    assert pairs, "schema 块解析为空？"
    bad = [(k, t) for k, t in pairs if not RE_SCHEMA_ELEMENT.match(t)]
    assert not bad, (
        f"schema 值不是 Supervisor 合法类型 token（商店会静默跳过本加载项）: {bad}"
        " ——默认值请放 options: 块，勿在类型上挂 `=`"
    )


def test_no_equals_default_notation_anywhere_in_schema():
    """事故形态点名防回潮：`=值` 语法在上游任何版本都不存在。"""
    for k, t in _block("schema"):
        assert "=" not in t, f"schema {k}: `{t}` 复发 `=默认值` 假语法"


def test_required_schema_keys_have_options_defaults():
    """非 `?`（必填）schema 键必须在 options: 有默认值——
    这才是 Supervisor 新装零配置的唯一供给途径（v1.7.12 误以为 `=` 可行）。"""
    options_keys = {k for k, _ in _block("options")}
    missing = [k for k, t in _block("schema")
               if not t.endswith("?") and k not in options_keys]
    assert not missing, f"必填 schema 键缺 options 默认值（新装将零配置破功）: {missing}"


def test_watchdog_matches_upstream_regex():
    """watchdog 必须匹配官方 RE_WATCHDOG（tcp 协议 + [HOST] 占位为强制形态）。"""
    m = re.search(r"^watchdog:\s*(.+?)\s*$", CFG, re.M)
    assert m, "watchdog 键锚丢失"
    assert RE_WATCHDOG.match(m.group(1)), \
        f"watchdog `{m.group(1)}` 不符合上游商店校验正则——加载项会被拒收"
