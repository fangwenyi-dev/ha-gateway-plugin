#!/usr/bin/env bash
# 本地真栈一键迭代（WSL，无 docker）：重置 HA 配置 → 拉起 HA Core →
# 跑与 CI 同一份 ha_e2e_driver.py → 失败自动落 HA 日志尾部。
# 前置（一次性）：uv venv 装 homeassistant（HA_PY 指向其 python3）、
# 免 root mosquitto 解包（MOSQ_DIR，默认 ~/local/mosq）。CI 侧由
# run_e2e.sh 用 docker 编排后在 HA 容器内跑同一 driver——契约同源。
set -uo pipefail

HA_PY=${HA_PY:-$HOME/local/havenv/bin/python3}
MOSQ_DIR=${MOSQ_DIR:-$HOME/local/mosq}
CFG=$HOME/local/ha-e2e-config
REPO=$(cd "$(dirname "$0")/../../.." && pwd)   # 仓库根

pkill -f "python[0-9.]* -m home[a]ssistant" 2>/dev/null
# 关键：HA 退出前会把 .storage 刷盘——必须等进程真正消失后再 rm config，
# 否则 shutdown 回写把 onboarding done 状态复活（本地实锤 403 竞态）
for i in $(seq 1 20); do pgrep -f "python[0-9.]* -m home[a]ssistant" >/dev/null || break; sleep 1; done
sleep 1
if ! ss -ltn 2>/dev/null | grep -q ":2022 "; then
    export LD_LIBRARY_PATH=$MOSQ_DIR/usr/lib/x86_64-linux-gnu
    nohup "$MOSQ_DIR/usr/sbin/mosquitto" -c "$MOSQ_DIR/e2e.conf" >>/tmp/mosq.log 2>&1 &
    sleep 1
fi

rm -rf "$CFG"; mkdir -p "$CFG/custom_components"
cp -r "$REPO/huijian_mqtt_broker/custom_components/window_controller_gateway" \
    "$CFG/custom_components/"
cp "$REPO/huijian_mqtt_broker/tests/e2e/ha_e2e_driver.py" "$CFG/"
printf 'homeassistant:\n  name: E2E Local\nconfig:\napi:\nauth:\nonboarding:\nperson:\nhttp:\n' \
    > "$CFG/configuration.yaml"

echo "启动本地 HA Core（首轮约 60-120s）..."
(setsid "$HA_PY" -m homeassistant --config "$CFG" >/tmp/ha-e2e.log 2>&1 &)
C=000
for i in $(seq 1 60); do sleep 3
    C=$(curl -s -o /dev/null -w "%{http_code}" -m 3 http://127.0.0.1:8123/api/)
    [ "$C" = "401" ] && break
done
if [ "$C" != "401" ]; then echo "!! HA 未就绪（HTTP $C）"; tail -20 /tmp/ha-e2e.log; exit 1; fi

"$HA_PY" "$CFG/ha_e2e_driver.py"; RC=$?
if [ $RC -ne 0 ]; then
    echo "── HA 日志相关行 ──"
    grep -E "ERROR|Traceback|window_controller|mqtt" /tmp/ha-e2e.log | tail -25
fi
exit $RC
