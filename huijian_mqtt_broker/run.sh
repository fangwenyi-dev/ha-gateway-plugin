#!/usr/bin/with-contenv bashio
# =============================================================================
# 慧尖 MQTT Broker — 启动脚本
#
# 功能：
#   1. 从插件配置读取 username / password，动态生成 mosquitto 密码文件
#   2. 创建持久化目录
#   3. 后台启动 mosquitto 检测就绪
#   4. 自动配置 HA MQTT 集成（如果启用）
#   5. 前台运行 mosquitto（Docker CMD 要求前台运行）
#
# MQTT 主题协议（与 ha-window-controller-gateway 集成 const.py 完全一致）：
#   gateway/{gateway_sn}/req   — HA 发布命令，LoRa 网关订阅
#   gateway/rpt_rsp            — LoRa 网关发布上报，HA 订阅
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

if ! mosquitto_passwd -b -c "${PASSWD_FILE}" "${USERNAME}" "${PASSWORD}" 2>/dev/null; then
    echo "[错误] 创建用户 ${USERNAME} 密码失败"
    exit 1
fi
chmod 600 "${PASSWD_FILE}"
echo "[OK] 密码文件已生成: ${PASSWD_FILE}"

# ---------- 2. 创建持久化目录 ----------
mkdir -p /data/mosquitto
chmod 755 /data/mosquitto
echo "[OK] 持久化目录已创建: /data/mosquitto"

# ---------- 3. 后台启动 mosquitto 检测就绪 ----------
echo ""
echo "[启动] 正在启动 mosquitto broker..."
echo "[启动] 监听: 0.0.0.0:1883 (MQTT TCP)"
echo "[启动] ACL: gateway/+/req, gateway/rpt_rsp"

mosquitto -c /etc/mosquitto/mosquitto.conf -d

# 等待端口就绪
echo -n "[启动] 等待 broker 就绪..."
RETRY=0
MAX_RETRIES=10
while [ ${RETRY} -lt ${MAX_RETRIES} ]; do
    if mosquitto_pub -h 127.0.0.1 -p 1883 -u "${USERNAME}" -P "${PASSWORD}" \
        -t "test/ping" -m "ok" -q 0 2>/dev/null; then
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
    # 停止后台进程
    pkill mosquitto 2>/dev/null || true
    exit 1
fi

echo ""
echo "============================================"
echo "  慧尖 MQTT Broker 已就绪"
echo "============================================"
echo ""
echo "MQTT Broker: 0.0.0.0:1883"
echo "用户名: ${USERNAME}"
echo ""
echo "LoRa 网关配置:"
echo "  Broker 地址: huijian.local (或 HA 的 IP)"
echo "  端口: 1883"
echo "  用户名: ${USERNAME}"
echo "  密码: ${PASSWORD}"
echo ""

# ---------- 4. 自动配置 HA MQTT 集成 ----------
if [ "${AUTO_SETUP}" = "true" ]; then
    echo "============================================"
    echo "  自动配置 HA MQTT 集成..."
    echo "============================================"
    /auto_setup_mqtt.sh || true
    echo ""
fi

# ---------- 5. 停止后台 mosquitto，前台运行 ----------
# Docker CMD 必须前台运行，否则容器会立即退出
pkill mosquitto 2>/dev/null || true
sleep 1

echo "[运行] Broker 以前台模式运行..."

exec mosquitto -c /etc/mosquitto/mosquitto.conf
