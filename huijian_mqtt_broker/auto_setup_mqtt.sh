#!/usr/bin/with-contenv bashio
# =============================================================================
# 慧尖 LoRa 网关一体化插件 — 自动配置 HA MQTT 集成
#
# 使用 bashio shebang 确保 SUPERVISOR_TOKEN 从 container-env 正确加载
# 配置变量通过环境变量传递，用 :- 提供默认值避免 set -u 报错
#
# 架构：
#   - 容器内 mosquitto 监听 2022
#   - Docker 端口映射: 主机 2022 → 容器 2022
#   - 本脚本用 127.0.0.1:2022 检测 broker 可达性（容器内部）
#   - 告诉 HA MQTT 集成连接 172.30.32.1:2022（Docker 网桥网关 + 主机端口）
# =============================================================================

set -e

# 从环境变量读取（run.sh 中显式传递的，加默认值避免 bashio set -u 报错）
USERNAME="${USERNAME:-huijian}"
PASSWORD="${PASSWORD:-huijian2022}"
MQTT_PORT="${MQTT_PORT:-2022}"
INTERNAL_PORT="${INTERNAL_PORT:-2022}"

# HA Supervisor API — with-contenv 会从 /run/s6/container-env 加载正确的 SUPERVISOR_TOKEN
HA_API="http://supervisor/core/api"
HA_TOKEN="${SUPERVISOR_TOKEN:-}"

# HA Core 连接 broker 的地址（Docker 网桥网关 + 主机映射端口）
BROKER_ADDR="172.30.32.1"
BROKER_PORT="${MQTT_PORT}"

if [ -z "${HA_TOKEN}" ]; then
    echo "[自动配置] 未找到 SUPERVISOR_TOKEN，跳过自动配置"
    echo "[自动配置] 请手动在 HA 中添加 MQTT 集成："
    echo "[自动配置]   Broker: ${BROKER_ADDR}, 端口: ${BROKER_PORT}"
    echo "[自动配置]   用户名: ${USERNAME}, 密码: ${PASSWORD}"
    exit 0
fi

# 调试: 输出 token 前缀确认是否有效
echo "[自动配置] SUPERVISOR_TOKEN 前缀: ${HA_TOKEN:0:8}..."
echo "[自动配置] 正在检查 HA MQTT 集成状态..."

# 等待 broker 完全启动
sleep 3

# 循环等待 broker 可连接（容器内 127.0.0.1:2022）
RETRY=0
while [ ${RETRY} -lt 30 ]; do
    if mosquitto_pub -h 127.0.0.1 -p ${INTERNAL_PORT} -u "${USERNAME}" -P "${PASSWORD}" \
        -t "test/ping" -m "ok" -q 0 2>/dev/null; then
        echo "[自动配置] broker 已就绪 (容器内 127.0.0.1:${INTERNAL_PORT})"
        break
    fi
    echo "[自动配置] 等待 broker 启动... (${RETRY}/30)"
    RETRY=$((RETRY + 1))
    sleep 1
done

# ---------- 1. 检查是否已有 MQTT 配置条目 ----------
echo "[自动配置] 检查已有 MQTT 集成..."
MQTT_ENTRIES=$(curl -s -X GET \
    -H "Authorization: Bearer ${HA_TOKEN}" \
    -H "Content-Type: application/json" \
    "${HA_API}/config/config_entries/entry?domain=mqtt" 2>/dev/null || echo "[]")

ENTRY_COUNT=$(echo "${MQTT_ENTRIES}" | jq 'length' 2>/dev/null || echo "0")
echo "[自动配置] 找到 ${ENTRY_COUNT} 个 MQTT 集成条目"

if [ "${ENTRY_COUNT}" -gt 0 ]; then
    echo "[自动配置] MQTT 集成已存在，检查配置..."

    ENTRY_ID=$(echo "${MQTT_ENTRIES}" | jq -r '.[0].entry_id')
    CURRENT_BROKER=$(echo "${MQTT_ENTRIES}" | jq -r '.[0].data.broker // ""')
    CURRENT_PORT=$(echo "${MQTT_ENTRIES}" | jq -r '.[0].data.port // 0')

    if [ "${CURRENT_BROKER}" = "${BROKER_ADDR}" ] && [ "${CURRENT_PORT}" = "${BROKER_PORT}" ]; then
        echo "[自动配置] MQTT 集成已配置为 ${BROKER_ADDR}:${BROKER_PORT}，无需更新"
        exit 0
    fi

    echo "[自动配置] 当前 broker=${CURRENT_BROKER}:${CURRENT_PORT}，更新为 ${BROKER_ADDR}:${BROKER_PORT}..."

    UPDATE_RESULT=$(curl -s -w "\n%{http_code}" -X POST \
        -H "Authorization: Bearer ${HA_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"broker\":\"${BROKER_ADDR}\",\"port\":${BROKER_PORT},\"username\":\"${USERNAME}\",\"password\":\"${PASSWORD}\"}" \
        "${HA_API}/config/config_entries/entry/${ENTRY_ID}" 2>/dev/null || echo "{}\n0")

    UPDATE_HTTP=$(echo "${UPDATE_RESULT}" | tail -1)
    UPDATE_BODY=$(echo "${UPDATE_RESULT}" | sed '$d')
    echo "[自动配置] 更新 HTTP ${UPDATE_HTTP}: ${UPDATE_BODY}"
    exit 0
fi

# ---------- 2. 创建新的 MQTT 配置条目 ----------
echo "[自动配置] 未找到 MQTT 集成，正在自动创建..."
echo "[自动配置] Broker: ${BROKER_ADDR}:${BROKER_PORT}, 用户: ${USERNAME}"

# 不用 -f，因为 HA API 创建失败时会返回 HTTP 错误码和 JSON 错误信息
# -s 静默模式，-w 输出 HTTP 状态码
CREATE_RESULT=$(curl -s -w "\n%{http_code}" -X POST \
    -H "Authorization: Bearer ${HA_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"慧尖 MQTT Broker\",\"title\":\"慧尖 MQTT Broker\",\"data\":{\"broker\":\"${BROKER_ADDR}\",\"port\":${BROKER_PORT},\"username\":\"${USERNAME}\",\"password\":\"${PASSWORD}\",\"discovery\":true,\"protocol\":\"3.1.1\"}}" \
    "${HA_API}/config/config_entries/entry/mqtt" 2>/dev/null || echo "{}\n0")

# 分离响应体和 HTTP 状态码
HTTP_CODE=$(echo "${CREATE_RESULT}" | tail -1)
RESPONSE_BODY=$(echo "${CREATE_RESULT}" | sed '$d')

echo "[自动配置] HTTP 状态码: ${HTTP_CODE}"
echo "[自动配置] 响应: ${RESPONSE_BODY}"

if echo "${RESPONSE_BODY}" | jq -e 'has("entry_id") or has("require_restart")' > /dev/null 2>&1; then
    echo "[自动配置] ✅ MQTT 集成已自动创建"
    echo "[自动配置] 用户无需手动配置 MQTT 集成"
elif echo "${RESPONSE_BODY}" | jq -e 'has("message")' > /dev/null 2>&1; then
    ERROR_MSG=$(echo "${RESPONSE_BODY}" | jq -r '.message // "未知错误"')
    echo "[自动配置] ❌ 自动创建失败: ${ERROR_MSG}"
    echo "[自动配置] 如需手动配置："
    echo "[自动配置]   设置 → 设备与服务 → 添加集成 → MQTT"
    echo "[自动配置]   Broker: ${BROKER_ADDR}, 端口: ${BROKER_PORT}"
    echo "[自动配置]   用户名: ${USERNAME}, 密码: ${PASSWORD}"
else
    echo "[自动配置] ❌ 自动创建可能失败（HTTP ${HTTP_CODE}）"
    echo "[自动配置] 响应内容: ${RESPONSE_BODY}"
    echo "[自动配置] 如需手动配置："
    echo "[自动配置]   设置 → 设备与服务 → 添加集成 → MQTT"
    echo "[自动配置]   Broker: ${BROKER_ADDR}, 端口: ${BROKER_PORT}"
    echo "[自动配置]   用户名: ${USERNAME}, 密码: ${PASSWORD}"
fi
