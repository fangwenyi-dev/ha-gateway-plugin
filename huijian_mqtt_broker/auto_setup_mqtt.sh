#!/usr/bin/with-contenv bashio
# =============================================================================
# 慧尖 LoRa 网关一体化插件 — 自动配置 HA MQTT 集成
#
# 通过 HA Supervisor API 自动创建/更新 MQTT 集成配置条目，
# 连接到本插件内置的 Mosquitto broker。
#
# 在非 host_network 模式下，broker 地址使用 Docker 网桥网关 172.30.32.1
# （HA core 容器通过此地址访问插件端口映射的 1883 端口）
# =============================================================================

set -e

USERNAME=$(bashio::config 'username')
PASSWORD=$(bashio::config 'password')

# HA Supervisor API
HA_API="http://supervisor/core/api"
HA_TOKEN="${SUPERVISOR_TOKEN}"

# Broker 地址：Docker 网桥网关地址（HA core 通过此地址访问插件端口映射）
BROKER_ADDR="172.30.32.1"
BROKER_PORT="1883"

if [ -z "${HA_TOKEN}" ]; then
    echo "[自动配置] 未找到 SUPERVISOR_TOKEN，跳过自动配置"
    echo "[自动配置] 请手动在 HA 中添加 MQTT 集成："
    echo "[自动配置]   设置 → 设备与服务 → 添加集成 → MQTT"
    echo "[自动配置]   Broker: ${BROKER_ADDR}, 端口: ${BROKER_PORT}"
    echo "[自动配置]   用户名: ${USERNAME}, 密码: ${PASSWORD}"
    exit 0
fi

echo "[自动配置] 正在检查 HA MQTT 集成状态..."

# 等待 broker 完全启动（exec mosquitto 后需要时间初始化）
sleep 3

# 循环等待 broker 可连接
RETRY=0
while [ ${RETRY} -lt 30 ]; do
    if mosquitto_pub -h 127.0.0.1 -p 1883 -u "${USERNAME}" -P "${PASSWORD}" \
        -t "test/ping" -m "ok" -q 0 2>/dev/null; then
        echo "[自动配置] broker 已就绪"
        break
    fi
    echo "[自动配置] 等待 broker 启动... (${RETRY}/30)"
    RETRY=$((RETRY + 1))
    sleep 1
done

# ---------- 1. 检查是否已有 MQTT 配置条目 ----------
MQTT_ENTRIES=$(curl -sf -X GET \
    -H "Authorization: Bearer ${HA_TOKEN}" \
    -H "Content-Type: application/json" \
    "${HA_API}/config/config_entries/entry?domain=mqtt" 2>/dev/null || echo "[]")

ENTRY_COUNT=$(echo "${MQTT_ENTRIES}" | jq 'length' 2>/dev/null || echo "0")

if [ "${ENTRY_COUNT}" -gt 0 ]; then
    echo "[自动配置] MQTT 集成已存在（${ENTRY_COUNT} 个条目），检查配置..."

    ENTRY_ID=$(echo "${MQTT_ENTRIES}" | jq -r '.[0].entry_id')
    CURRENT_BROKER=$(echo "${MQTT_ENTRIES}" | jq -r '.[0].data.broker // ""')

    if [ "${CURRENT_BROKER}" = "${BROKER_ADDR}" ]; then
        echo "[自动配置] MQTT 集成已配置为 ${BROKER_ADDR}，无需更新"
        exit 0
    fi

    echo "[自动配置] 当前 broker=${CURRENT_BROKER}，更新为 ${BROKER_ADDR}:${BROKER_PORT}..."

    UPDATE_RESULT=$(curl -sf -X POST \
        -H "Authorization: Bearer ${HA_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"broker\":\"${BROKER_ADDR}\",\"port\":${BROKER_PORT},\"username\":\"${USERNAME}\",\"password\":\"${PASSWORD}\"}" \
        "${HA_API}/config/config_entries/entry/${ENTRY_ID}" 2>/dev/null || echo "{}")

    echo "[自动配置] 更新结果: ${UPDATE_RESULT}"
    exit 0
fi

# ---------- 2. 创建新的 MQTT 配置条目 ----------
echo "[自动配置] 未找到 MQTT 集成，正在自动创建..."

CREATE_RESULT=$(curl -sf -X POST \
    -H "Authorization: Bearer ${HA_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"慧尖 MQTT Broker\",\"title\":\"慧尖 MQTT Broker\",\"data\":{\"broker\":\"${BROKER_ADDR}\",\"port\":${BROKER_PORT},\"username\":\"${USERNAME}\",\"password\":\"${PASSWORD}\",\"discovery\":true,\"protocol\":\"3.1.1\"}}" \
    "${HA_API}/config/config_entries/entry/mqtt" 2>/dev/null || echo "{}")

echo "[自动配置] 创建结果: ${CREATE_RESULT}"

if echo "${CREATE_RESULT}" | jq -e 'has("entry_id") or has("require_restart")' > /dev/null 2>&1; then
    echo "[自动配置] MQTT 集成已自动创建"
    echo "[自动配置] 用户无需手动配置 MQTT 集成"
elif echo "${CREATE_RESULT}" | jq -e 'has("message")' > /dev/null 2>&1; then
    ERROR_MSG=$(echo "${CREATE_RESULT}" | jq -r '.message // "未知错误"')
    echo "[自动配置] 自动创建失败: ${ERROR_MSG}"
    echo "[自动配置] 如需手动配置："
    echo "[自动配置]   Broker: ${BROKER_ADDR}, 端口: ${BROKER_PORT}"
    echo "[自动配置]   用户名: ${USERNAME}, 密码: ${PASSWORD}"
else
    echo "[自动配置] 自动创建可能失败，请检查 HA 日志"
    echo "[自动配置] 如需手动配置："
    echo "[自动配置]   Broker: ${BROKER_ADDR}, 端口: ${BROKER_PORT}"
    echo "[自动配置]   用户名: ${USERNAME}, 密码: ${PASSWORD}"
fi
