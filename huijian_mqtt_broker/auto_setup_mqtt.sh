#!/usr/bin/with-contenv bashio
# =============================================================================
# 慧尖 LoRa 网关一体化插件 — 自动配置 HA MQTT 集成
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

# 等待 broker 完全启动（exec mosquitto 后需要时间初始化）
sleep 5

# 循环等待 broker 可连接
RETRY=0
while [ ${RETRY} -lt 20 ]; do
    if mosquitto_pub -h 127.0.0.1 -p 1883 -u "${USERNAME}" -P "${PASSWORD}" \
        -t "test/ping" -m "ok" -q 0 2>/dev/null; then
        echo "[自动配置] broker 已就绪"
        break
    fi
    echo "[自动配置] 等待 broker 启动... (${RETRY}/20)"
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

# 检查创建是否成功：HA API 成功时返回 JSON 含 entry_id 或 require_restart 字段，
# 失败时返回空对象 {} 或含 message 字段的错误对象。
# 修复原逻辑：`.entry_id // .require_restart // true` 恒为 true（因为 // 的兜底是 true），
# 改为显式检查成功字段是否存在。
if echo "${CREATE_RESULT}" | jq -e 'has("entry_id") or has("require_restart")' > /dev/null 2>&1; then
    echo "[自动配置] MQTT 集成已自动创建"
    echo "[自动配置] 用户无需手动配置 MQTT 集成"
elif echo "${CREATE_RESULT}" | jq -e 'has("message")' > /dev/null 2>&1; then
    # HA 返回了错误信息
    ERROR_MSG=$(echo "${CREATE_RESULT}" | jq -r '.message // "未知错误"')
    echo "[自动配置] 自动创建失败: ${ERROR_MSG}"
    echo "[自动配置] 如需手动配置："
    echo "[自动配置]   设置 → 设备与服务 → 添加集成 → MQTT"
    echo "[自动配置]   Broker: 127.0.0.1, 端口: 1883"
    echo "[自动配置]   用户名: ${USERNAME}, 密码: ${PASSWORD}"
else
    # 返回空或无法解析，可能是网络问题
    echo "[自动配置] 自动创建可能失败（未收到有效响应），请检查 HA 日志"
    echo "[自动配置] 如需手动配置："
    echo "[自动配置]   设置 → 设备与服务 → 添加集成 → MQTT"
    echo "[自动配置]   Broker: 127.0.0.1, 端口: 1883"
    echo "[自动配置]   用户名: ${USERNAME}, 密码: ${PASSWORD}"
fi
