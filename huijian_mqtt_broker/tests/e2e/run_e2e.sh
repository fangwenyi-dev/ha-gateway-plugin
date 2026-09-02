#!/usr/bin/env bash
# v1.6.21 真栈 E2E：真 HA Core 容器 + 真 mosquitto 容器闭环验证慧尖集成。
#
# 动机（第七轮评分定案）：279 项单测全部跑在 fake homeassistant mock 上，
# 六轮审计查出的多个真 bug（via_device_id、ignore_flow 语义、
# DeviceEntry 属性面）恰是 mock 与真实 HA 行为差异处——mock 测试"像真"
# 而非"真"。本脚本在 GitHub runner（有 docker）上拉起最小生产形态栈：
#   eclipse-mosquitto:2 :2022（E2E 专用，allow_anonymous）
#   + home-assistant:stable --network host（bind 挂载本集成）
# 走 REST 完成 onboarding → 建 MQTT entry → 建本集成 entry → 以真 MQTT
# 报文驱动 002 上报 → 断言 entry loaded / 集成自带 devices API 返回
# gateway_online 与子设备 / WS 9001 监听，并做 500 条上报吞吐 soak。
#
# 首阶段 ci.yaml 挂 continue-on-error（盲开发期不阻塞发布），连续绿后
# 摘除升为硬门禁。调试线索全量落盘（失败 trap 打印两侧容器日志尾部）。
set -Eeuo pipefail

GW_SN="E2EGW0000001"
DEV_SN="100020003001"
HA_PORT=8123
MQTT_PORT=2022
WS_PORT=9001
CFG=/tmp/e2e-ha-config
TOKEN=""

log()  { printf '\n==== %s ====\n' "$*"; }
diag() {
    echo "!! E2E 失败于: ${1:-unknown}"
    docker logs --tail 40 mosq-e2e 2>&1 || true
    docker logs --tail 120 ha-e2e 2>&1 | grep -v "^\s*$" | tail -80 || true
}
trap 'diag "line $LINENO"' ERR

ha() { # REST 调用（带 owner token）
    curl -sf -m 20 -H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json' "$@"
}

log "1. 启动 mosquitto :${MQTT_PORT}"
cat > /tmp/e2e-mosq.conf <<EOF
listener ${MQTT_PORT}
allow_anonymous true
message_size_limit 1048576
EOF
docker run -d --name mosq-e2e --network host \
    -v /tmp/e2e-mosq.conf:/mosquitto/config/mosquitto.conf \
    eclipse-mosquitto:2 >/dev/null

log "2. 启动 HA Core（stable，bind 挂载本集成）"
rm -rf "$CFG"; mkdir -p "$CFG/custom_components"
cp -r "$(dirname "$0")/../../custom_components/window_controller_gateway" \
    "$CFG/custom_components/"
chmod -R 777 "$CFG"
docker run -d --name ha-e2e --network host \
    -e "TZ=Etc/UTC" -v "$CFG:/config" \
    ghcr.io/home-assistant/home-assistant:stable >/dev/null

log "3. 等待 HA API 就绪"
ok=""
for _ in $(seq 1 60); do
    if curl -s -m 5 -o /dev/null "http://localhost:${HA_PORT}/api/"; then ok=1; break; fi
    sleep 5
done
[ -n "$ok" ] || { diag "HA 未在 5 分钟内响应"; exit 1; }
echo "HA API 端口就绪（401 属预期，未 onboarding）"

log "4. Headless onboarding（owner + 长期令牌）"
OB=$(curl -sf -m 15 -X POST "http://localhost:${HA_PORT}/api/onboarding/users" \
    -H 'Content-Type: application/json' \
    -d '{"username":"e2e-admin","password":"e2e-e2e-e2e","name":"E2E Admin"}')
echo "onboarding 响应: ${OB:0:200}"
TOKEN=$(echo "$OB" | jq -r '.long_lived_access_token // empty')
[ -n "$TOKEN" ] || { diag "onboarding 未返回 long_lived_access_token"; exit 1; }

log "5. 建立 HA MQTT 集成（127.0.0.1:${MQTT_PORT}）"
FL=$(ha -X POST "http://localhost:${HA_PORT}/api/config/config_entries/flow" \
    -d '{"handler":"mqtt","show_advanced_options":false}' | jq -r '.flow_id')
RES=$(ha -X POST "http://localhost:${HA_PORT}/api/config/config_entries/flow/${FL}" \
    -d "{\"broker\":\"127.0.0.1\",\"port\":\"${MQTT_PORT}\"}")
echo "mqtt flow 结果: ${RES:0:160}"
[ "$(echo "$RES" | jq -r '.type')" = "create_entry" ] || { diag "MQTT entry 创建失败"; exit 1; }

log "6. 等待 MQTT 集成 loaded"
for _ in $(seq 1 24); do
    S=$(ha "http://localhost:${HA_PORT}/api/config/config_entries/entry" \
        | jq -r '.entries[] | select(.domain=="mqtt") | .state')
    [ "$S" = "loaded" ] && break
    sleep 5
done
[ "$S" = "loaded" ] || { diag "MQTT 集成 2 分钟未 loaded（state=$S）"; exit 1; }

log "7. 建立慧尖网关集成条目（config flow user 步骤）"
FL=$(ha -X POST "http://localhost:${HA_PORT}/api/config/config_entries/flow" \
    -d "{\"handler\":\"window_controller_gateway\",\"context\":{\"title_param\":\"E2E\"}}" \
    | jq -r '.flow_id')
RES=$(ha -X POST "http://localhost:${HA_PORT}/api/config/config_entries/flow/${FL}" \
    -d "{\"gateway_sn\":\"${GW_SN}\",\"gateway_name\":\"E2E网关\"}")
echo "huijian flow 结果: ${RES:0:160}"
ENTRY=$(echo "$RES" | jq -r '.result // empty')
[ -n "$ENTRY" ] || { diag "慧尖 entry 未创建"; exit 1; }

log "8. 等待慧尖 entry loaded"
for _ in $(seq 1 24); do
    S=$(ha "http://localhost:${HA_PORT}/api/config/config_entries/entry/${ENTRY}" | jq -r '.state')
    [ "$S" = "loaded" ] && break
    sleep 5
done
[ "$S" = "loaded" ] || { diag "慧尖 entry 2 分钟未 loaded（state=$S）"; exit 1; }
echo "entry loaded ✓（真 HA setup 全链路：mqtt 订阅/bootstrap/persist 无 mock）"

log "9. 模拟网关 002 上报（真 MQTT 报文，经真 broker）"
report() {
    local rid="$1" rtrav="$2"
    docker exec mosq-e2e mosquitto_pub -h 127.0.0.1 -p "$MQTT_PORT" -t gateway/rpt_rsp -m \
        "{\"head\":{\"cmdid\":\"002\",\"id\":${rid}},\"ctype\":\"002\",\"id\":${rid},\"sn\":\"${GW_SN}\",\"data\":{\"status\":1,\"devices\":[{\"sn\":\"${DEV_SN}\",\"model\":\"5005\",\"battery\":1210,\"r_travel\":${rtrav}}]}}"
}
report 9001 50
sleep 8

log "10. 断言：集成自带 devices API 返回 gateway_online 与子设备"
DEVS=$(ha "http://localhost:${HA_PORT}/api/window_controller_gateway/devices?config_entry_id=${ENTRY}")
echo "$DEVS" | jq -c '[.[] | {name, gateway_online}]' | head -5
echo "$DEVS" | grep -q '"gateway_online": *true\|"gateway_online":true' || { diag "gateway_online 未转 true"; exit 1; }
echo "$DEVS" | grep -q "$DEV_SN" || { diag "上报的子设备未进入设备注册表"; exit 1; }
echo "MQTT→handler→device_manager→registry→REST 视图 全链路实证 ✓"

log "11. 断言：WS 网关 9001 默认监听（v1.6.16 常听语义）"
timeout 5 bash -c "exec 3<>/dev/tcp/127.0.0.1/${WS_PORT}" 2>/dev/null \
    || { diag "WS ${WS_PORT} 未监听（默认开语义被破坏？）"; exit 1; }
echo "WS 端口监听 ✓"

log "12. Soak：容器内连发 500 条 002 上报，测吞吐与稳定"
T0=$(date +%s)
docker exec mosq-e2e sh -c "i=0; while [ \$i -lt 500 ]; do \
  mosquitto_pub -h 127.0.0.1 -p ${MQTT_PORT} -t gateway/rpt_rsp -m \
  \"{\\\"head\\\":{\\\"cmdid\\\":\\\"002\\\",\\\"id\\\":\\\$((10000+\\\$i))\\\"},\\\"ctype\\\":\\\"002\\\",\\\"id\\\":\\\$((10000+\\\$i)),\\\"sn\\\":\\\"${GW_SN}\\\",\\\"data\\\":{\\\"status\\\":1,\\\"devices\\\":[{\\\"sn\\\":\\\"${DEV_SN}\\\",\\\"model\\\":\\\"5005\\\",\\\"battery\\\":1210,\\\"r_travel\\\":\\\$((\\\$i % 101))}]}}\"; \
  i=\$((i+1)); done"
T1=$(date +%s)
sleep 10
API_OK=$(curl -s -m 10 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${TOKEN}" \
    "http://localhost:${HA_PORT}/api/states")
RATE=$(awk -v n=500 -v t=$((T1-T0)) 'BEGIN{printf "%.1f", n/(t>0?t:1)}')
echo "500 条注入耗时 $((T1-T0))s（${RATE}/s），soak 后 HA /api/states HTTP ${API_OK}"
[ "$API_OK" = "200" ] || { diag "soak 后 HA API 不再 200"; exit 1; }

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    {
        echo "## E2E 真栈结果"
        echo "- entry setup→loaded：真 HA + 真 mosquitto ✓"
        echo "- 002 上报 → gateway_online/子设备注册 ✓"
        echo "- WS ${WS_PORT} 默认监听 ✓"
        echo "- soak 500 条 ${RATE}/s 注入，HA 全程可用"
    } >> "$GITHUB_STEP_SUMMARY"
fi

log "E2E 全部断言通过 ✅"
docker logs --tail 25 ha-e2e 2>&1 | grep -i "window_controller\|error" | tail -12 || true
