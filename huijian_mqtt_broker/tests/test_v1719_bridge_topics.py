"""v1.7.19（方案一：桥主题白名单可配置化）回归钉桩。

背景（共存根因）：HA 的 MQTT 集成全局单条目且必须钉在慧尖内置 broker
(:2022)——官方 Mosquitto 上其他 MQTT 加载项与 HA 互通的唯一通道是共存桥。
旧桥写死 zigbee2mqtt/# 双向 + homeassistant/# 进，其他生态"能发现、控不了"。
本批新增 coexist_bridge_topics 追加白名单（run.sh §1a+ 净化器渲染
BRIDGE_TOPICS_EXTRA 桥腿 + BRIDGE_ACL_EXTRA 逐条对齐 ha_mqtt ACL）。

安全红线（代码级，配置不可解除）逐条用**生产 bash 段真实执行**实证——
沿用 test_v1624 D-2 的文件注入手法（Windows→WSL argv 吞 `$`，argv 形态
在开发机恒假失败；临时文件通吃）。
"""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

RUN_SH = Path(__file__).resolve().parents[1] / "run.sh"
TEXT = RUN_SH.read_text(encoding="utf-8")


def _posix_candidates(p):
    st = str(p)
    if len(st) > 1 and st[1] == ":":
        body = st[2:].replace("\\", "/")
        return [st, f"/{st[0].lower()}{body}", f"/mnt/{st[0].lower()}{body}"]
    return [st]


def _sanitizer_segment():
    m = re.search(
        r"BEGIN BRIDGE-TOPICS-SANITIZER.*?\n(.*?)# END BRIDGE-TOPICS-SANITIZER",
        TEXT, re.S)
    assert m, "run.sh 净化器抽取锚丢失（BEGIN/END BRIDGE-TOPICS-SANITIZER）"
    return m.group(1)


def _run_sanitizer(raw: str):
    """在 bash 里执行 run.sh 里**逐字同源**的净化器段（stub bashio::config
    回灌 TEST_RAW），返回 (topics_out, acl_out, stdout)。

    raw 用 base64 内嵌而非旁路文件：Windows 临时文件路径（C:\\Users\\...）
    在 WSL/Git Bash 里须各自换算 POSIX 形态，换算失败时 `cat` 静默空输入
    ——拒绝类断言会因"恒空产出"集体假阴（开发期实锤）。base64 字符集对
    任何 shell 引号规则免疫；RAWLEN 自检把"喂进去的值 ≠ 想测的值"钉死。"""
    import base64
    if shutil.which("bash") is None:
        pytest.skip("本机无 bash（Windows 开发机无 Git Bash/WSL）")
    b64 = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    fd, tmp = tempfile.mkstemp(suffix=".sh")
    script = (
        "set -e\n"
        'TEST_RAW=$(printf %s "' + b64 + '" | base64 -d)\n'
        'printf "RAWLEN<%s>\\n" "${#TEST_RAW}"\n'
        "bashio::config() { printf '%s' \"${TEST_RAW}\"; }\n"
        + _sanitizer_segment()
        + '\nprintf "TOPICS<\\x01%s\\x01>\\n" "$BRIDGE_TOPICS_EXTRA"\n'
          'printf "ACL<\\x01%s\\x01>\\n" "$BRIDGE_ACL_EXTRA"\n')
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(script)
        last = None
        for cand in _posix_candidates(Path(tmp)):
            r = subprocess.run(["bash", cand], capture_output=True)
            r.stdout = r.stdout.decode("utf-8", "replace")
            r.stderr = r.stderr.decode("utf-8", "replace")
            if r.returncode == 0 and "TOPICS<" in (r.stdout or ""):
                break
            last = r
            if "No such file" in (r.stderr or ""):
                continue
        else:
            raise AssertionError(f"bash 执行净化器段失败: {last.stderr if last else '?'}")
    finally:
        os.unlink(tmp)
    got_len = re.search(r"RAWLEN<(\d+)>", r.stdout).group(1)
    assert got_len == str(len(raw)), \
        f"raw 值经 shell 通道变形（期望 len={len(raw)} 实得 {got_len}）：{raw!r}"
    topics = re.search(r"TOPICS<\x01(.*?)\x01>\n", r.stdout, re.S).group(1)
    acl = re.search(r"ACL<\x01(.*?)\x01>\n", r.stdout, re.S).group(1)
    return ([l for l in topics.splitlines() if l.strip()],
            [l for l in acl.splitlines() if l.strip()], r.stdout)


# ---------- 功能实证：默认与合法追加 ----------

def test_empty_config_adds_nothing():
    t, a, _ = _run_sanitizer("")
    assert t == [] and a == [], "空配置零追加（默认三腿行为完全不变）"


def test_both_direction_emits_symmetric_legs():
    t, a, _ = _run_sanitizer("esphome/#")
    assert t == ["topic esphome/# out 1", "topic esphome/# in 1"]
    assert a == ["topic readwrite esphome/#"]


def test_mixed_directions_acl_alignment():
    """v1.6.24 不变量的可配置形态：每条桥腿在 ha_mqtt ACL 有对应方向权限，
    in→read / out→write / both→readwrite，一条不多一条不少。"""
    t, a, _ = _run_sanitizer("tele/#:in, stat/#:in,cmnd/#:out")
    assert t == ["topic tele/# in 1", "topic stat/# in 1", "topic cmnd/# out 1"]
    assert a == ["topic read tele/#", "topic read stat/#", "topic write cmnd/#"]


def test_plus_wildcard_whole_level_allowed():
    t, a, _ = _run_sanitizer("esphome/+/status")
    assert t == ["topic esphome/+/status out 1", "topic esphome/+/status in 1"]
    assert a == ["topic readwrite esphome/+/status"]


def test_duplicates_collapse():
    t, a, _ = _run_sanitizer("esphome/#,esphome/#:out")
    assert t == ["topic esphome/# out 1", "topic esphome/# in 1"], \
        "同树去重（首见方向生效），不得产出重复 conf 行"
    assert len(a) == 1


# ---------- 功能实证：安全红线 ----------

@pytest.mark.parametrize("raw", [
    "gateway/#", "gateway/abc/req:in", "Gateway/x/y", "GATEWAY/#:both",
])
def test_gateway_tree_always_rejected(raw):
    """v1.6.24 安全评审定案红线：匿名@1883 穿桥 publish gateway/{sn}/req =
    未认证物理开窗。大小写不敏感拒绝（MQTT 主题区分大小写，但 Gateway/
    形态同样按保留字处理，不给混淆留门缝）。"""
    t, a, out = _run_sanitizer(raw)
    assert t == [] and a == [], f"gateway 树必须零产出: {t!r}/{a!r}"
    assert "拒绝" in out and "gateway" in out


@pytest.mark.parametrize("raw", ["test/#", "TEST/ha/health:in"])
def test_healthcheck_tree_rejected(raw):
    t, a, out = _run_sanitizer(raw)
    assert t == [] and a == []
    assert "拒绝" in out


@pytest.mark.parametrize("raw", [
    "#", "#:both", "+", "+/x", "+/#", "gateway", "test",
])
def test_matchall_and_leading_wildcard_rejected(raw):
    """首层必须具名字面量——`#/…`、`+/…` 会匹配（圈进）慧尖保留树，
    等于变相解除 gateway 红线，一律拒绝。"""
    t, a, out = _run_sanitizer(raw)
    assert t == [] and a == [], f"全匹配/通配首层零产出: {t!r}"
    assert "拒绝" in out


@pytest.mark.parametrize("raw", [
    "a/#/b",                # # 非末层：mosquitto conf 拒载形态，写入门拦截
    "e+home/#",             # + 混入层内：非法通配
    "esphome/#/#",          # 双末层 #
    "foo/#:SIDE",           # 方向非法
    "foo/#:both:extra",     # 多冒号
])
def test_malformed_patterns_rejected(raw):
    t, a, out = _run_sanitizer(raw)
    assert t == [] and a == []
    assert "拒绝" in out


@pytest.mark.parametrize("raw", [
    "ev`id`/#",             # v1.7.9 heredoc 反引号命令替换事故同款
    "a/#;connection evil",  # conf 伪造行注入
    "$SYS/#",               # $ 不在字符白名单（命令替换/$SYS 双堵）
    "a/#$(id)",             # $() 注入
    'a/#",username x,"',    # 逗号旁路尝试（token 内含引号）
    "foo/#\naddress 1.2.3.4",  # 换行注入 conf 行
])
def test_injection_shapes_never_reach_output(raw):
    """加载项配置值直通 heredoc = 注入面。字符白名单 + 方向枚举必须把
    任何可成形的 conf/ACL 注入载荷挡在输出之外。"""
    t, a, out = _run_sanitizer(raw)
    for line in t + a:
        assert not re.match(r"^\s*(address|connection|username|password)\b", line), \
            f"注入行穿透: {line!r}"
        assert "`" not in line and "$" not in line and ";" not in line
    assert not any("address 1.2.3.4" in l for l in t)
    if raw.startswith("ev"):
        assert t == [] and "拒绝" in out


def test_homeassistant_and_zigbee_defaults_not_duplicated():
    """默认双腿（z2m 双向 + homeassistant in）已在桥/ACL 里字面量存在——
    用户重复请求只提示忽略、绝不产出第二份（防 conf 重复腿行为未测形态，
    也钉死 zigbee 双 t 拼写：开发期曾漏 [Tt][Tt] 令其漏过忽略分支）。"""
    for raw in ("homeassistant/#", "homeassistant/#:both", "HomeAssistant/#:out",
                "zigbee2mqtt/#", "ZigBee2MQTT/#:in", "zigbee2mqtt/x:out"):
        t, a, out = _run_sanitizer(raw)
        assert t == [] and a == [], f"默认树重复请求应零产出: {raw} → {t!r}"
        assert "忽略" in out or "默认桥已" in out, raw


def test_tree_cap_16():
    raw = ",".join(f"tree{i}/#" for i in range(20))
    t, a, out = _run_sanitizer(raw)
    assert len([l for l in t if l.endswith(" out 1")]) == 16
    assert len(a) == 16
    assert "上限" in out


def test_overlong_pattern_rejected():
    t, a, out = _run_sanitizer("a" * 150 + "/#")
    assert t == [] and a == []
    assert "拒绝" in out


# ---------- 静态契约：配置面与渲染面咬合 ----------

def test_config_surface_registered():
    cfg = (RUN_SH.parent / "config.yaml").read_text(encoding="utf-8")
    assert re.search(r"^\s+coexist_bridge_topics: \"\"", cfg, re.M), \
        "options 须有默认空串（空=纯默认腿，向后兼容）"
    assert re.search(r"^\s+coexist_bridge_topics: str\?\s*$", cfg, re.M), \
        "schema 须为可选 str（v1.7.16 定案：仅官方语法，无 =默认值 形态）"


def test_render_targets_wired():
    """两组净化产物必须同时进桥块与 ha_mqtt ACL（缺一边=半残或爆炸半径
    超桥：只进 ACL = 白给权限无桥腿；只进桥 = HA 收不了/发不出）。"""
    bridge_seg = TEXT[TEXT.index("connection core_mosquitto"):
                      TEXT.index("# END ${BRIDGE_MARKER}")]
    assert "${BRIDGE_TOPICS_EXTRA}" in bridge_seg
    assert bridge_seg.index("topic homeassistant/# in 1") < \
        bridge_seg.index("${BRIDGE_TOPICS_EXTRA}"), "追加腿须在默认腿之后"
    _ha_start = TEXT.index("user ${HA_MQTT_USERNAME}")
    _ha_end = TEXT.index("$SYS 主题（只读）", _ha_start)  # huijian 段先含同名尾锚
    acl_seg = TEXT[_ha_start:_ha_end]
    assert "${BRIDGE_ACL_EXTRA}" in acl_seg, "动态 ACL 未进 ha_mqtt 段"


def test_acl_lines_carry_no_bare_wildcard():
    """净化器输出面全局红线：任何产出行不得等于 `topic readwrite #` 等
    全匹配（同文件既有钉桩 test_v1624 的运行时补位——那里查源码字面，
    这里查渲染逻辑）。"""
    for raw in ("foo/#", "bar:in", "baz:out", "#", "+", "#:both"):
        t, a, _ = _run_sanitizer(raw)
        for line in t + a:
            parts = line.split()
            pat = parts[2] if parts[1] in ("read", "write", "readwrite") else parts[1]
            assert pat not in ("#", "+") and not pat.startswith("#") \
                and not pat.startswith("+"), f"非法产出: {line}"


def test_gen_harness_wired_for_extra_topics():
    gen = (RUN_SH.parent / "tests" / "e2e" / "gen_bridge_harness.py").read_text(
        encoding="utf-8")
    assert "${TEST_BRIDGE_TOPICS_EXTRA:-}" in gen, \
        "e2e harness 未接追加腿占位（生成后桥块将引用未定义变量）"
