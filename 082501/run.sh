#!/usr/bin/with-contenv bashio
# =============================================================================
# 慧尖 MQTT Broker — 启动脚本
#
# 功能：
#   1. 从插件配置读取 username / password，动态生成 mosquitto 密码文件
#   2. 创建持久化目录
#   3. 启动 mosquitto broker（后台运行）
#   4. 等待 broker 就绪
#   5. 自动配置 HA MQTT 集成（如果启用）
#   6. 监控 broker 进程存活
#
# MQTT 主题协议（与 ha-window-controller-gateway 集成 const.py 完全一致）：
#   gateway/{gateway_sn}/req   — HA 发布命令，LoRa 网关订阅
#   gateway/rpt_rsp            — LoRa 网关发布上报，HA 订阅
#
# 协议消息类型（ctype）：
#   001: 网关绑定（网关发起，HA 回复 errcode:0 + uuid）
#   002: 网关状态上报（网关发起，HA 回复 errcode:0 确认）
#   003: 配对/解绑子设备（HA 发起，网关回复 errcode）
#   004: 设备控制（HA 发起，网关回复 errcode）
#   005: 设备状态上报（网关发起，HA 回复 errcode:0 确认）
#   006: 设置参数（HA 发起）
#   007: 查询参数（HA 发起）
# =============================================================================

set -e

USERNAME=$(bashio::config 'username')
PASSWORD=$(bashio::config 'password')
AUTO_SETUP=$(bashio::config 'auto_setup_ha_mqtt')

echo "============================================"
echo "  慧尖 MQTT Broker 启动中..."
echo "============================================"
echo "[配置] 用户名: ${USERNAME}"
echo "[配置] 自动配置 HA MQTT 集成: ${AUTO_SETUP}"
echo ""

# ---------- 1. 生成密码文件 ----------
PASSWD_FILE="/etc/mosquitto/passwd"

if ! mosquitto_passwd -b "${PASSWD_FILE}" "${USERNAME}" "${PASSWORD}" 2>/dev/null; then
    echo "[错误] 创建用户 ${USERNAME} 密码失败"
    exit 1
fi
chmod 600 "${PASSWD_FILE}"
echo "[OK] 密码文件已生成: ${PASSWD_FILE}"

# ---------- 2. 创建持久化目录 ----------
mkdir -p /data/mosquitto
chmod 755 /data/mosquitto
echo "[OK] 持久化目录已创建: /data/mosquitto"

# ---------- 3. 启动 mosquitto broker（后台） ----------
echo ""
echo "[启动] 正在启动 mosquitto broker..."
echo "[启动] 监听: 0.0.0.0:1883 (MQTT TCP)"
echo "[启动] ACL: gateway/+/req, gateway/rpt_rsp"

mosquitto -c /etc/mosquitto/mosquitto.conf -d
MOSQ_PID=$!

# ---------- 4. 等待 broker 就绪 ----------
echo -n "[启动] 等待 broker 就绪..."
RETRY=0
MAX_RETRIES=10
while [ ${RETRY} -lt ${MAX_RETRIES} ]; do
    if mosquitto_sub -h 127.0.0.1 -p 1883 -u "${USERNAME}" -P "${PASSWORD}" \
        -t "test/ping" -C 1 -W 1 -q 0 2>/dev/null || \
       nc -z 127.0.0.1 1883 2>/dev/null; then
        echo " OK"
        break
    fi
    echo -n "."
    RETRY=$((RETRY + 1))
    sleep 0.5
done

if [ ${RETRY} -ge ${MAX_RETRIES} ]; then
    echo " FAILED"
    echo "[错误] Broker 启动失败"
    exit 1
fi

echo ""
echo "============================================"
echo "  慧尖 MQTT Broker 已就绪"
echo "============================================"
echo ""
echo "MQTT Broker: 0.0.0.0:1883"
echo "用户名: ${USERNAME}"
echo "密码: ${PASSWORD}"
echo ""
echo "LoRa 网关配置:"
echo "  Broker 地址: huijian.local (或 HA 的 IP)"
echo "  端口: 1883"
echo "  用户名: ${USERNAME}"
echo "  密码: ${PASSWORD}"
echo ""

# ---------- 5. 自动配置 HA MQTT 集成 ----------
if [ "${AUTO_SETUP}" = "true" ]; then
    echo "============================================"
    echo "  自动配置 HA MQTT 集成..."
    echo "============================================"
    /auto_setup_mqtt.sh || true
    echo ""
fi

# ---------- 6. 监控 broker 进程 ----------
echo "[运行] Broker 正在运行 (PID: ${MOSQ_PID})，等待退出..."

# 等待 mosquitto 进程退出
wait ${MOSQ_PID} 2>/dev/null
EXIT_CODE=$?

echo "[退出] Broker 进程退出，代码: ${EXIT_CODE}"
exit ${EXIT_CODE}
