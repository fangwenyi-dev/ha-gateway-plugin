#!/usr/bin/env python3
"""从 run.sh 原文**逐字抽取**共存桥函数区，生成实证 harness lib
（bridge_harness_lib.sh）——e2e 跑的永远是生产代码本体而非手抄副本
（v1.6.24 惯例：机制实证必须用真实函数文本，防"测过了≠上线了"）。

路径替换（仅此几类）：
  /etc/mosquitto/mosquitto.conf → $MOSQ_LOCAL/e2e.conf
  /run/mosquitto.pid            → $PIDFILE
  /run/bridge_last_ts           → $MOSQ_LOCAL/bridge_last_ts
  对端 127.0.0.1:1883 → 1884（e2e 沙盒端口，避开本机常驻服务；机制与端口无关）
  bashio::config 'coexist_official_*' → 测试环境变量（source 时求值）
   bashio::config 'coexist_bridge_enabled' → TEST_BRIDGE_ENABLED（v1.6.26）

lib 为纯生成物：整文件覆写，无增量合并（历史事故：增量保留过旧 selfheal）。
mock selfheal 必须**逐行对齐生产主循环**（v1.6.24 教训：mock 凭记忆写了
生产没有的 RC=0→break，制造了 8 轮假故障）。
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = HERE.parents[1] / "run.sh"
OUT = HERE / "bridge_harness_lib.sh"

text = RUN.read_text(encoding="utf-8")
m = re.search(r'(BRIDGE_MARKER="AUTO-COEXIST-BRIDGE".*?)(?=\nPORT_HEX=)', text, re.S)
assert m, "run.sh 桥函数区锚缺失（7b 节被移动/改名——同步本脚本正则）"
fns = (m.group(1)
       .replace("/etc/mosquitto/mosquitto.conf", "$MOSQ_LOCAL/e2e.conf")
       .replace('kill -TERM "$(cat /run/mosquitto.pid 2>/dev/null)"',
                'kill -TERM "$(cat $PIDFILE 2>/dev/null)"')
       .replace("/run/bridge_last_ts", "$MOSQ_LOCAL/bridge_last_ts")
       .replace("127.0.0.1:1883", "127.0.0.1:1884")
       .replace("bashio::config 'coexist_official_user'",
                'echo "${TEST_BRIDGE_USER:-}"')
       .replace("bashio::config 'coexist_official_password'",
                'echo "${TEST_BRIDGE_PASS:-}"')
        # v1.6.26（D-3）：总开关进 harness（默认 true=生产默认；e2e 可置
        # TEST_BRIDGE_ENABLED=false 验证熔断/拆桥）
        .replace("bashio::config 'coexist_bridge_enabled'",
                 'echo "${TEST_BRIDGE_ENABLED:-true}"'))

MOCK = """
# —— 主自愈循环模拟：**逐行对齐 run.sh 真实主循环**（v1.6.20 语义）：
# `wait || EXIT_CODE=$?` 后**无条件重启**，仅"连续崩溃计数"设闸（生产无
# RC=0→break 分支——mosquitto 收 TERM 优雅退出码=0，曾凭想象加 break 制造
# S2 假故障三连，mock 不同构=测的是 harness 自己的 bug）。
RS=0
start_broker() {
    "$MOSQ_BIN" -c "$MOSQ_LOCAL/e2e.conf" >> "$MOSQ_LOCAL/e2e.out" 2>&1 &
    BROKER_PID=$!
    echo "$BROKER_PID" > "$PIDFILE"
}
selfheal() {
    start_broker
    while true; do
        WAIT_START=$(date +%s)
        RC=0
        wait "$BROKER_PID" 2>/dev/null || RC=$?
        # 生产是 60（RUN_SECS>=60 视为稳定恢复清零）；e2e 时间尺度压缩到
        # 5——生产桥动作受 120s 冷却约束，间隔恒 >60s，闸门只防真崩溃循环；
        # e2e 背靠背 on/off 若无此适配会把计数攒爆误杀 broker（833 现场实锤）
        [ $(( $(date +%s) - WAIT_START )) -ge 5 ] && RS=0
        RS=$((RS + 1))
        if [ "$RS" -gt 5 ]; then
            echo "[selfheal] 连续退出 5 次，停止重启（对齐生产闸）" >> "$MOSQ_LOCAL/e2e.out"
            break
        fi
        sleep 5
        start_broker
    done
}
"""

OUT.write_text(
    "# 生成文件——由 gen_bridge_harness.py 从 run.sh 原文抽取，勿手改\n" + fns + MOCK,
    encoding="utf-8")
print(f"generated {OUT}", file=sys.stderr)
