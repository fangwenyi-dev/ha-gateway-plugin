#!/usr/bin/with-contenv bashio
# =============================================================================
# 慧尖 MQTT Broker — 自动配置 HA MQTT 集成
#
# 通过 HA Supervisor API 自动创建/更新 MQTT 集成配置条目，
# 连接到本插件内置的 Mosquitto broker（127.0.0.1:1883），
# 用户无需手动在 HA 中配置 MQTT 集成。
# =============================================================================

set -e

USERNAME=$(bashio::config 'username')
PASSWORD=$(bashio::config 'password')

# HA Supervisor API
HA_API="http://supervisor/core/api"
HA_TOKEN="${SUPERVISOR_TOKEN}"

if [ -z "${HA_TOKEN}" ]; then
    echo "[自动配置] 未找到 SUPERVISOR_TOKEN，跳过自动配置"
    echo "[自动配置] 请手动在 HA 中添加 MQTT 集成："
    echo "[自动配置]   设置 → 设备与服务 → 添加集成 → MQTT"
    echo "[自动配置]   Broker: 127.0.0.1, 端口: 1883"
    echo "[自动配置]   用户名: ${USERNAME}, 密码: ${PASSWORD}"
    exit 0
fi

echo "[自动配置] 正在检查 HA MQTT 集成状态..."

# 等待 broker 完全启动
sleep 2

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

    if [ "${CURRENT_BROKER}" = "127.0.0.1" ] || [ "${CURRENT_BROKER}" = "core-mosquitto" ]; then
        echo "[自动配置] MQTT 集成已配置为本地 broker，无需更新"
        exit 0
    fi

    echo "[自动配置] 当前 broker=${CURRENT_BROKER}，更新为 127.0.0.1:1883..."

    UPDATE_RESULT=$(curl -sf -X POST \
        -H "Authorization: Bearer ${HA_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"broker\":\"127.0.0.1\",\"port\":1883,\"username\":\"${USERNAME}\",\"password\":\"${PASSWORD}\"}" \
        "${HA_API}/config/config_entries/entry/${ENTRY_ID}" 2>/dev/null || echo "{}")

    echo "[自动配置] 更新结果: ${UPDATE_RESULT}"
    exit 0
fi

# ---------- 2. 创建新的 MQTT 配置条目 ----------
echo "[自动配置] 未找到 MQTT 集成，正在自动创建..."

CREATE_RESULT=$(curl -sf -X POST \
    -H "Authorization: Bearer ${HA_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"慧尖 MQTT Broker\",\"title\":\"慧尖 MQTT Broker\",\"data\":{\"broker\":\"127.0.0.1\",\"port\":1883,\"username\":\"${USERNAME}\",\"password\":\"${PASSWORD}\",\"discovery\":true,\"protocol\":\"3.1.1\"}}" \
    "${HA_API}/config/config_entries/entry/mqtt" 2>/dev/null || echo "{}")

echo "[自动配置] 创建结果: ${CREATE_RESULT}"

if echo "${CREATE_RESULT}" | jq -e '.entry_id // .require_restart // true' > /dev/null 2>&1; then
    echo "[自动配置] MQTT 集成已自动创建"
    echo "[自动配置] 用户无需手动配置 MQTT 集成"
else
    echo "[自动配置] 自动创建可能失败，请检查 HA 日志"
    echo "[自动配置] 如需手动配置："
    echo "[自动配置]   设置 → 设备与服务 → 添加集成 → MQTT"
    echo "[自动配置]   Broker: 127.0.0.1, 端口: 1883"
    echo "[自动配置]   用户名: ${USERNAME}, 密码: ${PASSWORD}"
fi
