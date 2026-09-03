#!/usr/bin/env bash
# v1.6.21 真栈 E2E（CI 侧编排）：eclipse-mosquitto:2 + HA Core 真实容器，
# 全部业务断言在 tests/e2e/ha_e2e_driver.py（本地/CI 单一事实源——auth
# 契约经读 HA 2026.7.1 源码实证后重写，终止两轮 CI 盲打）。
#
# 本地复跑（WSL，无 docker）：bash tests/e2e/run_local.sh 一键完成
# （重置→拉起 HA Core→跑同一 driver→失败落日志），契约与 CI 同源。
#
# 首阶段 ci.yaml continue-on-error（防 E2E 自身问题阻塞发布），
# 连绿后摘除升硬门禁。失败 trap 落盘两侧容器日志尾部辅助排障。
set -Eeuo pipefail

CFG=/tmp/e2e-ha-config
DIR="$(cd "$(dirname "$0")" && pwd)"

diag() {
    echo "!! E2E 编排失败于: ${1:-unknown}"
    docker logs --tail 40 mosq-e2e 2>&1 || true
    docker logs --tail 150 ha-e2e 2>&1 | grep -v "^\s*$" | tail -100 || true
}
trap 'diag "line $LINENO"' ERR

echo "==== 1. mosquitto :2022 ===="
cat > /tmp/e2e-mosq.conf <<'EOF'
listener 2022
allow_anonymous true
message_size_limit 1048576
EOF
docker run -d --name mosq-e2e --network host \
    -v /tmp/e2e-mosq.conf:/mosquitto/config/mosquitto.conf \
    eclipse-mosquitto:2 >/dev/null

echo "==== 2. HA Core（bind 挂载本集成 + driver） ===="
rm -rf "$CFG"; mkdir -p "$CFG/custom_components"
cp -r "$DIR/../../custom_components/window_controller_gateway" \
    "$CFG/custom_components/"
cp "$DIR/ha_e2e_driver.py" "$CFG/"
chmod -R 777 "$CFG"
docker run -d --name ha-e2e --network host \
    -e "TZ=Etc/UTC" -v "$CFG:/config" \
    ghcr.io/home-assistant/home-assistant:stable >/dev/null

echo "==== 3. 驱动器（等待/认证/entry/002/断言/soak 全在其内） ===="
# summary 经 $CFG（已 bind 进容器 /config）双向共享——直接指容器内路径
# （docker exec 无法临时挂载 runner 文件，第五轮自查断链修复）
RC=0
docker exec -e E2E_HA_URL=http://127.0.0.1:8123 -e E2E_MQTT_HOST=127.0.0.1 \
    -e GITHUB_STEP_SUMMARY=/config/summary.md \
    ha-e2e python3 /config/ha_e2e_driver.py || RC=$?
if [ -s "$CFG/summary.md" ] && [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    cat "$CFG/summary.md" >> "$GITHUB_STEP_SUMMARY"
fi
[ "$RC" -eq 0 ] || { diag "driver rc=$RC"; exit "$RC"; }
echo "==== E2E 编排完成 ✅ ===="
