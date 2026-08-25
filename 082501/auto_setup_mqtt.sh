#!/usr/bin/with-contenv bashio
# =============================================================================
# 慧尖 MQTT Broker — 自动配置 HA MQTT 集成
#
# 功能：
#   通过 HA REST API 自动创建/更新 MQTT 集成配置条目，
#   连接到本插件内置的 Mosquitto broker（127.0.0.1:1883），
#   用户无需手动在 HA 中配置 MQTT 集成。
#
# 原理：
#   HA 插件可通过 Supervisor API 调用 HA 的 REST API。
#   1. 检查是否已有 MQTT 配置条目
#   2. 如果没有，创建新的配置条目
#   3. 如果有但配置不同，更新配置条目
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
    echo "[自动配置]   Broker: 127.0.0.1"
    echo "[自动配置]   端口: 1883"
    echo "[自动配置]   用户名: ${USERNAME}"
    echo "[自动配置]   密码: ${PASSWORD}"
    exit 0
fi

echo "[自动配置] 正在检查 HA MQTT 集成状态..."

# 等待 broker 完全启动
sleep 2

# ---------- 1. 检查是否已有 MQTT 配置条目 ----------
MQTT_ENTRIES=$(curl -s -X GET \
    -H "Authorization: Bearer ${HA_TOKEN}" \
    -H "Content-Type: application/json" \
    "${HA_API}/config/config_entries/entry?domain=mqtt")

# 检查是否有现有条目
ENTRY_COUNT=$(echo "${MQTT_ENTRIES}" | jq 'length')

if [ "${ENTRY_COUNT}" -gt 0 ]; then
    echo "[自动配置] MQTT 集成已存在（${ENTRY_COUNT} 个条目），检查配置..."

    # 获取第一个条目的 ID
    ENTRY_ID=$(echo "${MQTT_ENTRIES}" | jq -r '.[0].entry_id')

    # 检查当前配置是否匹配
    CURRENT_BROKER=$(echo "${MQTT_ENTRIES}" | jq -r '.[0].data.broker // ""')
    CURRENT_PORT=$(echo "${MQTT_ENTRIES}" | jq -r '.[0].data.port // 0')

    if [ "${CURRENT_BROKER}" = "127.0.0.1" ] || [ "${CURRENT_BROKER}" = "core-mosquitto" ]; then
        echo "[自动配置] MQTT 集成已配置为本地 broker，无需更新"
        exit 0
    fi

    echo "[自动配置] 当前 broker=${CURRENT_BROKER}:${CURRENT_PORT}，更新为 127.0.0.1:1883..."

    # 更新配置条目
    UPDATE_RESULT=$(curl -s -X POST \
        -H "Authorization: Bearer ${HA_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"broker\":\"127.0.0.1\",\"port\":1883,\"username\":\"${USERNAME}\",\"password\":\"${PASSWORD}\"}" \
        "${HA_API}/config/config_entries/entry/${ENTRY_ID}")

    echo "[自动配置] 更新结果: ${UPDATE_RESULT}"
    echo "[自动配置] MQTT 集成配置已更新"
    exit 0
fi

# ---------- 2. 创建新的 MQTT 配置条目 ----------
echo "[自动配置] 未找到 MQTT 集成，正在自动创建..."

CREATE_PAYLOAD=$(cat <<EOF
{
    "name": "慧尖 MQTT Broker",
    "title": "慧尖 MQTT Broker",
    "data": {
        "broker": "127.0.0.1",
        "port": 1883,
        "username": "${USERNAME}",
        "password": "${PASSWORD}",
        "discovery": true,
        "protocol": "3.1.1"
    }
}
EOF
)

CREATE_RESULT=$(curl -s -X POST \
    -H "Authorization: Bearer ${HA_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "${CREATE_PAYLOAD}" \
    "${HA_API}/config/config_entries/entry")

echo "[自动配置] 创建结果: ${CREATE_RESULT}"

# 检查是否创建成功
if echo "${CREATE_RESULT}" | jq -e '.entry_id' > /dev/null 2>&1; then
    ENTRY_ID=$(echo "${CREATE_RESULT}" | jq -r '.entry_id')
    echo "[自动配置] MQTT 集成已自动创建，entry_id: ${ENTRY_ID}"
    echo "[自动配置] 用户无需手动配置 MQTT 集成"
else
    echo "[自动配置] 自动创建可能失败，请检查 HA 日志"
    echo "[自动配置] 如需手动配置："
    echo "[自动配置]   设置 → 设备与服务 → 添加集成 → MQTT"
    echo "[自动配置]   Broker: 127.0.0.1, 端口: 1883"
    echo "[自动配置]   用户名: ${USERNAME}, 密码: ${PASSWORD}"
fi
