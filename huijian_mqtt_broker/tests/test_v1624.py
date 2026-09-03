"""v1.6.24 钉桩：第三方共存自动桥（z2m 零配置改动 + 慧尖零配置改动）。

产品需求（用户 2026-09-06 两条定案）：
 1. 纯慧尖客户：只装慧尖插件即可用（不装/不配置任何 Mosquitto）
    → 桥默认不存在，仅当探测到 127.0.0.1:1883 LISTEN 才写入
 2. 后装 zigbee2mqtt：不修改慧尖任何配置，两插件同时可用
    → watchdog 自动搭桥到官方 Mosquitto + ha_mqtt ACL 放开 #
机制真栈实证见本批次会话（run.sh 原文函数抽取 harness：peer 出现→
桥写入→自愈重启→双向穿桥→peer 消失→拆桥→重装可逆，全通过）。
"""
import re
import subprocess
from pathlib import Path

RUN = Path(__file__).resolve().parents[1] / "run.sh"
TEXT = RUN.read_text(encoding="utf-8")


def _seg(start_pat: str, end_pat: str, name: str) -> str:
    m = re.search(start_pat, TEXT)
    assert m, f"{name} 起点缺失"
    m2 = re.search(end_pat, TEXT[m.start():])
    assert m2, f"{name} 终点缺失"
    return TEXT[m.start(): m.start() + m2.start()]


def _posix_candidates(p):
    """同一路径的多种 POSIX 形态：CI(ubuntu) 原生；Windows 本地 python 起
    的 bash 可能是 Git Bash(/e/…) 或默认 WSL 发行版(/mnt/e/…)，逐个试"""
    st = str(p)
    if len(st) > 1 and st[1] == ":":
        body = st[2:].replace("\\", "/")
        return [st, f"/{st[0].lower()}{body}", f"/mnt/{st[0].lower()}{body}"]
    return [st]


def test_shell_syntax():
    """run.sh 是生产心脏，语法门必须钉进 pytest（CI lint job 顺带执行）"""
    last = None
    for cand in _posix_candidates(RUN):
        r = subprocess.run(["bash", "-n", cand], capture_output=True, text=True)
        if r.returncode == 0:
            return
        last = r
        if "No such file" in (r.stderr or ""):
            continue  # 路径形态不匹配当前 bash 环境，换下一种
        break
    assert last is not None and last.returncode == 0, \
        f"bash -n 失败: {last.stderr or last.stdout}"


def test_bridge_functions_present():
    """桥状态机四要素：探测(复用/proc/net/tcp)、幂等写、区间删、计划内重启"""
    for anchor in (
        '_bridge_peer_up()',
        '_bridge_present()',
        '_bridge_on()',
        '_bridge_off()',
        'connection core_mosquitto',
        'address 127.0.0.1:1883',
        'topic zigbee2mqtt/# out 1',
        'topic zigbee2mqtt/# in 1',
        'topic homeassistant/# in 1',
        '# BEGIN ${BRIDGE_MARKER}',
        '# END ${BRIDGE_MARKER}',
    ):
        assert anchor in TEXT, f"桥函数区缺锚点: {anchor}"
    # sed 必须用区间删除（BEGIN..END），防误删其它配置
    assert re.search(r'sed -i "/# BEGIN \$\{BRIDGE_MARKER\}/,/# END \$\{BRIDGE_MARKER\}/d"', TEXT), \
        "拆桥须按标记区间精确删除"


def test_bridge_default_absent_neutral_customers():
    """需求1 的静态面：桥配置只由 watchdog/初启对账按需写入——
    仓库内 mosquitto.conf 基线不得含桥块/不得监听 1883（1883 归官方加载项）"""
    base_conf = (RUN.parent / "mosquitto.conf").read_text(encoding="utf-8")
    assert "core_mosquitto" not in base_conf
    assert not re.search(r'listener\s+\S*\s*1883', base_conf), "内置 broker 禁占 1883"


def test_watchdog_tick_and_cooldown():
    """30s 对账节奏 + 120s 冷却 + 双向状态机（在→on / 不在→off）"""
    tick_seg = _seg(r'BRIDGE_TICK=\$\(\(BRIDGE_TICK \+ 1\)\)', r'CONN_STATS=', "watchdog tick")
    assert "% 6" in tick_seg, "对账周期应为 6 tick（30s）"
    assert "-ge 120" in tick_seg, "须有 120s 冷却防 1883 抖动连环重启"
    assert "_bridge_peer_up" in tick_seg and "_bridge_on" in tick_seg \
        and "_bridge_off" in tick_seg, "tick 须含双向对账分支"
    # 冷却戳只在真实状态迁移时写（noop 续期会让桥永远拆不掉——自查实证缺陷）
    assert tick_seg.count('> /run/bridge_last_ts') == 2, \
        "冷却戳只允许在 on/off 两个迁移分支内写（读除外），不得无条件续期"


def test_boot_reconcile_before_first_start():
    """官方已在运行时的安装序：初启对账须先于 mosquitto 首次拉起
    （启动前写 conf = 零额外重启）"""
    boot = TEXT.index('if _bridge_peer_up; then\n    _bridge_on')
    first_start = TEXT.index('MOSQUITTO_PID=$!')
    assert boot < first_start, "初启对账必须在首次启动 mosquitto 之前"


def test_ha_mqtt_acl_wide_but_gateway_minimal():
    """ha_mqtt（HA 集成账号）放开 # ——桥转发来的 zigbee2mqtt/# 等主题
    HA 须可订阅；同时负向钉桩：LoRa 网关账号 huijian 维持最小权限，
    全文件 `topic readwrite #` 只允许出现在 HA_MQTT 段（=恰 1 处）。"""
    assert TEXT.count("topic readwrite #") == 1, "readwrite # 必须唯一"
    pos_wide = TEXT.index("topic readwrite #")
    pos_ha_user = TEXT.index("user ${HA_MQTT_USERNAME}")
    pos_gw_user = TEXT.index("user ${USERNAME}")
    assert pos_gw_user < pos_ha_user < pos_wide, \
        "readwrite # 必须位于 HA_MQTT 用户段（网关用户段之后），防网关账号越权"
    # 回退分支（HA_MQTT 创建失败，huijian 兼权）不得带 #——仅 homeassistant/#
    fb_seg = _seg(r"回退：\$\{HA_MQTT_USERNAME\} 创建失败", r'\} > "\$\{ACL_FILE\}"', "ACL 回退段")
    assert "topic readwrite #" not in fb_seg, "回退段禁止全主题放开"


def test_status_diagnostics_fields():
    """支持面只读字段（产品定案：无 UI 展示面，与 mqtt_password_is_default 同边界）"""
    assert "coexist_bridge:$bc" in TEXT and "official_peer_up:$pu" in TEXT


def test_bridge_conf_format_redline():
    """真栈实证教训钉桩（bash-27/28 两轮 crash-loop 根因）：
    真栈两轮 crash-loop 教训：notification_interval / try_initialize 等未测
    桥选项在 mosquitto 2.0.22 为 unknown 变量 → broker 整进程拒启；
    `topic # both` 引发 retained 乒乓风暴。桥块严格锁定为已实证的 5 配置行
    （connection/address/两 in 一 out 方向分离），任何增减都须先过真栈。"""
    seg = _seg(r"connection core_mosquitto", r"# END \$\{BRIDGE_MARKER\}", "桥配置块")
    lines = [l for l in seg.splitlines() if l.strip() and not l.strip().startswith("#")]
    assert lines == [
        "connection core_mosquitto",
        "address 127.0.0.1:1883",
        "topic zigbee2mqtt/# out 1",
        "topic zigbee2mqtt/# in 1",
        "topic homeassistant/# in 1",
        "topic gateway/# out 1",
        "topic gateway/# in 1",
    ], f"桥块出现未实证行: {lines}"
    # both = 真栈实测 retained 乒乓风暴（无 origin 防环），配置行红线禁用
    # （注释里出现 "both" 是解释禁因，只检查生效行）
    assert not any(" both " in l for l in lines), "桥禁 both 方向（乒乓自激实证）"
    code = "\n".join(lines)
    for banned in ("try_initialize", "notification", "roundrobin", "bridge_attempt",
                   "cleansession", "local_protocol"):
        assert banned not in code, f"禁入桥块的未测选项: {banned}"


def test_planned_restart_uses_selfheal_semantics():
    """桥变更走 kill → 主自愈循环 sleep5 重启路径（run.sh 既有能力），
    不引入第二套进程管理；两处函数各自 kill 一次"""
    fn_seg = _seg(r'_bridge_on\(\) \{', r'PORT_HEX=', "桥函数区")
    assert fn_seg.count('kill -TERM') == 2, "on/off 各计划内重启一次"
