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
import shutil
import subprocess
import sys
import tempfile
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
    if shutil.which("bash") is None:
        pytest.skip("本机无 bash（Windows 开发机无 Git Bash/WSL），跳过语法检查")
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
    boot = TEXT.index('if [ "${BRIDGE_ENABLED}" = "true" ] && _bridge_peer_up; then\n    # || true')
    first_start = TEXT.index('MOSQUITTO_PID=$!')
    assert boot < first_start, "初启对账必须在首次启动 mosquitto 之前"


def test_acl_bridge_alignment_no_wildcard():
    """v1.6.24 安全评审定案（推翻早先 readwrite # 方案）：ha_mqtt 白名单
    与桥主题腿逐条对齐（discovery + zigbee2mqtt + 网关协议），全文件禁止
    `topic readwrite #` 通配——爆炸半径不超桥白名单；未来扩桥腿须同步扩
    ACL（本测试的逐条相等断言即耦合点）。"""
    assert "topic readwrite #" not in TEXT, \
        "禁全主题通配（同密码换用户名提权链的放大器，审计定案摘除）"
    ha_seg = _seg(r"user \$\{HA_MQTT_USERNAME\}", r"\$SYS 主题（只读）", "ha_mqtt ACL 段")
    for need in ("topic readwrite homeassistant/#",
                 "topic readwrite zigbee2mqtt/#",     # 桥 in 腿注入主题 HA 须可订阅
                 "topic readwrite gateway/+",          # 慧尖协议三行自 1.6.x 沿用
                 ):
        assert need in ha_seg, f"ha_mqtt 段缺 {need}"
    # LoRa 网关用户段不得含 zigbee2mqtt/#（z2m 域隔离）
    gw_seg = _seg(r"\$\{USERNAME\}（LoRa 网关", r"\$SYS 主题（只读）", "huijian ACL 段")
    assert "zigbee2mqtt" not in gw_seg, "网关账号不得触 z2m 域"
    # z2m 直连专用账号存在且最小（不含 gateway/#）
    z2m_seg = _seg(r"user \$\{Z2M_USERNAME\}", r'\} > "\$\{ACL_FILE\}"', "z2m ACL 段")
    assert "topic readwrite zigbee2mqtt/#" in z2m_seg and "gateway" not in z2m_seg


def test_status_diagnostics_fields():
    """支持面只读字段（产品定案：无 UI 展示面，与 mqtt_password_is_default 同边界）"""
    assert "coexist_bridge:$bc" in TEXT and "official_peer_up:$pu" in TEXT


def test_bridge_conf_format_redline():
    """真栈实证教训钉桩（bash-27/28 两轮 crash-loop 根因）：
    真栈两轮 crash-loop 教训：notification_interval / try_initialize 等未测
    桥选项在 mosquitto 2.0.22 为 unknown 变量 → broker 整进程拒启；
    `topic # both` 引发 retained 乒乓风暴。桥块严格锁定为已实证的配置行
    （connection/address/两 in 一 out 方向分离），任何增减都须先过真栈。"""
    seg = _seg(r"connection core_mosquitto", r"# END \$\{BRIDGE_MARKER\}", "桥配置块")
    lines = [l for l in seg.splitlines() if l.strip() and not l.strip().startswith("#")]
    assert lines == [
        "connection core_mosquitto",
        "address 127.0.0.1:1883",
        "notifications false",                                    # 2.0.22 实测可用
        "${BRIDGE_CREDS}",      # v1.6.26（D-2）双非空才成对输出，见下行测试
        "topic zigbee2mqtt/# out 1",
        "topic zigbee2mqtt/# in 1",
        "topic homeassistant/# in 1",
    ], f"桥块出现未实证行: {lines}"
    # gateway 腿永久摘除的钉桩（匿名@1883 穿桥控固件=实锤攻击链，安全评审
    # 定案）：桥块与 ACL 白名单都不得出现跨桥 gateway 的 topic 行
    assert not any("topic gateway" in l for l in lines), \
        "禁 gateway/# 跨桥（v1.6.24 安全评审：in 腿=未认证物理控制）"
    # both = 真栈实测 retained 乒乓风暴（无 origin 防环），配置行红线禁用
    # （注释里出现 "both" 是解释禁因，只检查生效行）
    assert not any(" both " in l for l in lines), "桥禁 both 方向（乒乓自激实证）"
    code = "\n".join(lines)
    for banned in ("try_initialize", "notification_interval", "roundrobin",
                   "bridge_attempt", "cleansession", "local_protocol"):
        assert banned not in code, f"禁入桥块的未测选项: {banned}"


def test_planned_restart_uses_selfheal_semantics():
    """桥变更走 kill → 主自愈循环 sleep5 重启路径（run.sh 既有能力），
    不引入第二套进程管理；两处函数各自 kill 一次"""
    fn_seg = _seg(r'_bridge_on\(\) \{', r'PORT_HEX=', "桥函数区")
    assert fn_seg.count('kill -TERM') == 2, "on/off 各计划内重启一次"


# ============ v1.6.26 第八轮审计：D-2 凭据成对性 / D-3 总开关 / 生成物漂移 ============

def _run_bridge_creds_case(user: str, password: str):
    """把 run.sh 里**真实的** BRIDGE_CREDS 预构造段抽出来在 bash 里执行，
    返回 (creds, stdout)。注入变量置于段首，段文本与生产逐字一致。
    ⚠️ 必须走临时**文件**而非 `bash -c` argv：Windows→WSL 的 wsl.exe 参数
    转译会吞掉 `$`（本机实锤 X=u3;echo F[$X] → F[]），argv 形态下本测试
    在开发机恒假失败；ubuntu CI 原生 bash 两种都行，文件形态通吃。"""
    seg = _seg(r'BRIDGE_CREDS=""', r'OFFICIAL_PORT_HEX=', "桥凭据预构造段")
    script = (f"BRIDGE_PEER_USER='{user}'\nBRIDGE_PEER_PASSWORD='{password}'\n"
              + seg + 'printf "CREDS<%s>\\n" "$BRIDGE_CREDS"\n')
    import os
    fd, tmp = tempfile.mkstemp(suffix=".sh")
    try:
        # newline="\n" 关键：Windows 文本模式默认写 CRLF，WSL bash 对
        # `"..."\r` 后续行会报 syntax error near unexpected token `elif`
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(script)
        last = None
        for cand in _posix_candidates(Path(tmp)):
            # 二进制捕获后按 UTF-8 解码——Windows Python text=True 默认
            # 用 GBK 解码子进程输出，中文警告会变乱码致断言假阴
            r = subprocess.run(["bash", cand], capture_output=True)
            r.stdout = r.stdout.decode("utf-8", "replace")
            r.stderr = r.stderr.decode("utf-8", "replace")
            if r.returncode == 0 and "CREDS<" in (r.stdout or ""):
                break
            last = r
            if "No such file" in (r.stderr or ""):
                continue
        else:
            raise AssertionError(f"bash 执行凭据段失败: {last.stderr if last else '?'}")
        out = r.stdout
    finally:
        os.unlink(tmp)
    creds = re.search(r"CREDS<(.*?)>\n", out, re.S).group(1)
    return creds, out


def test_bridge_creds_pairwise_no_empty_password_line():
    """D-2（mosquitto v2.0.22 conf.c 实锤）：`password `（空值行）会让
    conf__parse_string 判 MOSQ_ERR_INVAL **拒载整份 conf** → 内置 broker
    拒启、加载项全挂。旧实现 `${USER:+password ${PASS}}` 按 USER 门控
    PASSWORD，"只填用户名"恰 produce 该毒行。现四形态行为钉死："""
    if shutil.which("bash") is None:
        import pytest
        pytest.skip("本机无 bash")
    both, _ = _run_bridge_creds_case("u1", "p1")
    assert both.splitlines() == ["username u1", "password p1"], \
        "双非空 → 恰好两行成对凭据"
    only_u, out_u = _run_bridge_creds_case("u1", "")
    assert "password" not in only_u and "username" not in only_u, \
        f"只填用户名不得产出任何凭据行（毒行零复现）: {only_u!r}"
    assert "警告" in out_u, "半填形态须大声降级警告"
    only_p, _ = _run_bridge_creds_case("", "p1")
    assert only_p == "", "只填口令同样降级匿名（旧版此处 username/password 双双不落）"
    none, out_n = _run_bridge_creds_case("", "")
    assert none == "" and "警告" not in out_n, "全空=匿名桥（v1.6.24 语义），不警告"


def test_bridge_enabled_master_switch():
    """D-3：误桥熔断开关——判据仅"本机 :1883 LISTEN"，宿主第三方进程占口
    也会被搭桥（out 送控制命令/in 注 discovery，不受本地 ACL 约束）。
    钉桩：config.yaml 默认 true + schema bool + run.sh 两处决策点全部
    门控（对账循环 + 初启路径），false 时走 else 分支自动拆已存桥。"""
    cfg = (RUN.parent / "config.yaml").read_text(encoding="utf-8")
    assert "coexist_bridge_enabled: true" in cfg, "开关默认 true（保持零配置共存语义）"
    assert re.search(r"coexist_bridge_enabled:\s*bool", cfg), "schema 须声明 bool"
    gated = re.findall(
        r'\[\s*"\$\{BRIDGE_ENABLED\}"\s*=\s*"true"\s*\]\s*&&\s*_bridge_peer_up', TEXT)
    assert len(gated) == 2, \
        f"对账循环+初启两处决策点都须门控，实际 {len(gated)} 处"
    assert "BRIDGE_ENABLED=$(bashio::config 'coexist_bridge_enabled')" in TEXT


def test_bridge_harness_lib_in_sync_with_run_sh():
    """生成物漂移防护：bridge_harness_lib.sh 必须由 gen_bridge_harness.py
    从 run.sh 现文逐字生成（v1.6.24 惯例"e2e 跑生产代码本体"的前提就是
    零漂移）。该文件 gitignored——CI fresh checkout 没有它（e2e 脚本自身
    先跑生成器），此时改在沙盒验证生成链完整 + 关键映射在场；本地存在时
    则逐字比对，改 run.sh 忘重生成 → 当场红。"""
    gen = Path(__file__).resolve().parent / "e2e" / "gen_bridge_harness.py"
    lib = gen.parent / "bridge_harness_lib.sh"
    committed = lib.read_text(encoding="utf-8") if lib.exists() else None
    with tempfile.TemporaryDirectory() as td:
        # 复刻仓库相对布局（生成器按 __file__ 父级定位 run.sh），在沙盒里
        # 重生成——不触碰工作树
        root = Path(td) / "huijian_mqtt_broker"
        (root / "tests" / "e2e").mkdir(parents=True)
        shutil.copy(RUN, root / "run.sh")
        shutil.copy(gen, root / "tests" / "e2e" / "gen_bridge_harness.py")
        r = subprocess.run(
            [sys.executable, str(root / "tests" / "e2e" / "gen_bridge_harness.py")],
            capture_output=True, text=True)
        assert r.returncode == 0, f"生成器锚丢失（run.sh 桥区被移动/改名）: {r.stderr}"
        fresh = (root / "tests" / "e2e" / "bridge_harness_lib.sh").read_text(
            encoding="utf-8")
    if committed is None:
        assert "${BRIDGE_CREDS}" in fresh, "v1.6.26（D-2）凭据形态未进 harness"
        assert 'TEST_BRIDGE_ENABLED:-true' in fresh, "v1.6.26（D-3）开关未进 harness"
        assert "bashio" not in fresh, "harness 残留 bashio 调用（替换清单缺项）"
        return
    assert fresh == committed, (
        "bridge_harness_lib.sh 与 run.sh 漂移——重跑 "
        "python3 huijian_mqtt_broker/tests/e2e/gen_bridge_harness.py")
