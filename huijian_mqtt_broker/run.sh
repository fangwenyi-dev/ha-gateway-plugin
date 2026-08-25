#!/usr/bin/with-contenv bashio
# =============================================================================
# 慧尖 LoRa 网关一体化插件 — 启动脚本
#
# 功能：
#   1. 从插件配置读取 username / password / mdns_hostname
#   2. 配置并启动 avahi-daemon（mDNS 广播 <hostname>.local）
#   3. 从插件配置读取 username / password，动态生成 mosquitto 密码文件
#   4. 创建持久化目录
#   5. 自动安装慧尖网关集成到 HA custom_components（如果启用）
#   6. 后台启动 mosquitto 检测就绪
#   7. 自动配置 HA MQTT 集成（如果启用）
#   8. 前台运行 mosquitto（Docker CMD 要求前台运行）
#
# MQTT 主题协议（与 ha-window-controller-gateway 集成 const.py 完全一致）：
#   gateway/{gateway_sn}/req   — HA 发布命令，LoRa 网关订阅
#   gateway/rpt_rsp            — LoRa 网关发布上报，HA 订阅
# =============================================================================

set -e

USERNAME=$(bashio::config 'username')
PASSWORD=$(bashio::config 'password')
AUTO_SETUP=$(bashio::config 'auto_setup_ha_mqtt')
MDNS_HOSTNAME=$(bashio::config 'mdns_hostname')
INSTALL_INTEGRATION=$(bashio::config 'install_integration')

echo "============================================"
echo "  慧尖 LoRa 网关一体化插件启动中..."
echo "============================================"
echo "[配置] MQTT 用户名: ${USERNAME}"
echo "[配置] mDNS 主机名: ${MDNS_HOSTNAME}.local"
echo "[配置] 自动配置 HA MQTT 集成: ${AUTO_SETUP}"
echo "[配置] 自动安装网关集成: ${INSTALL_INTEGRATION}"
echo ""

# ---------- 1. 配置并启动 mDNS (avahi) ----------
echo "[mDNS] 配置 avahi-daemon..."

# avahi 需要 dbus 运行
mkdir -p /run/dbus
dbus-daemon --system --fork 2>/dev/null || true

# 生成 avahi 配置文件
cat > /etc/avahi/avahi-daemon.conf <<EOF
[server]
host-name=${MDNS_HOSTNAME}
use-ipv4=yes
use-ipv6=no
enable-dbus=yes
publish-hostname=yes
publish-addresses=yes
publish-hinfo=yes
publish-workstation=yes
publish-domain=yes

[wide-area]
enable-wide-area=yes

[rlimits]
rlimit-core=0
rlimit-data=4194304
rlimit-fsize=0
rlimit-nofile=768
rlimit-stack=4194304
rlimit-nproc=3
EOF

# 启动 avahi-daemon
avahi-daemon -D 2>/dev/null || {
    echo "[mDNS] avahi-daemon 启动失败，LoRa 网关请使用 HA 的 IP 地址"
    echo "[mDNS] 而非 ${MDNS_HOSTNAME}.local"
}

# 等待 avahi 就绪并验证
sleep 1
if avahi-resolve-host-name "${MDNS_HOSTNAME}.local" >/dev/null 2>&1; then
    echo "[mDNS] OK — ${MDNS_HOSTNAME}.local 可解析"
else
    # avahi-resolve 可能无法在容器内自解析，但外部设备可以
    echo "[mDNS] avahi-daemon 已启动，广播 ${MDNS_HOSTNAME}.local"
fi
echo ""

# ---------- 2. 生成密码文件 ----------
PASSWD_FILE="/etc/mosquitto/passwd"

if ! mosquitto_passwd -b -c "${PASSWD_FILE}" "${USERNAME}" "${PASSWORD}" 2>/dev/null; then
    echo "[错误] 创建用户 ${USERNAME} 密码失败"
    exit 1
fi
chmod 600 "${PASSWD_FILE}"
echo "[OK] 密码文件已生成: ${PASSWD_FILE}"

# ---------- 3. 创建持久化目录 ----------
mkdir -p /data/mosquitto
chmod 755 /data/mosquitto
echo "[OK] 持久化目录已创建: /data/mosquitto"

# ---------- 4. 自动安装慧尖网关集成 ----------
if [ "${INSTALL_INTEGRATION}" = "true" ]; then
    echo ""
    echo "============================================"
    echo "  安装慧尖网关集成到 HA custom_components..."
    echo "============================================"

    # HA 配置目录路径（通过 homeassistant_config 映射）
    HA_CONFIG_DIR="/homeassistant"
    if [ ! -d "${HA_CONFIG_DIR}" ]; then
        # 某些 HA 版本映射为 /config
        HA_CONFIG_DIR="/config"
    fi

    if [ -d "${HA_CONFIG_DIR}" ]; then
        INTEGRATION_SRC="/data/custom_components/window_controller_gateway"
        INTEGRATION_DST="${HA_CONFIG_DIR}/custom_components/window_controller_gateway"

        if [ -d "${INTEGRATION_SRC}" ]; then
            mkdir -p "${HA_CONFIG_DIR}/custom_components"

            # 检查版本，仅在版本更新时才覆盖
            NEED_UPDATE=false
            if [ -f "${INTEGRATION_DST}/manifest.json" ]; then
                EXISTING_VERSION=$(cat "${INTEGRATION_DST}/manifest.json" | jq -r '.version // "0"' 2>/dev/null || echo "0")
                NEW_VERSION=$(cat "${INTEGRATION_SRC}/manifest.json" | jq -r '.version // "0"' 2>/dev/null || echo "0")
                if [ "${NEW_VERSION}" != "${EXISTING_VERSION}" ]; then
                    NEED_UPDATE=true
                    echo "[集成] 版本变化: ${EXISTING_VERSION} → ${NEW_VERSION}，更新集成"
                else
                    echo "[集成] 版本相同 (${NEW_VERSION})，跳过更新"
                fi
            else
                NEED_UPDATE=true
                echo "[集成] 首次安装集成"
            fi

            if [ "${NEED_UPDATE}" = "true" ]; then
                # 备份旧集成的持久化数据文件（如有）
                PERSIST_FILE="${HA_CONFIG_DIR}/window_controller_gateway_data.json"
                BACKUP_PERSIST=false
                if [ -f "${PERSIST_FILE}" ]; then
                    cp "${PERSIST_FILE}" "/tmp/window_controller_gateway_data.json.bak"
                    BACKUP_PERSIST=true
                fi

                # 覆盖安装集成代码
                rm -rf "${INTEGRATION_DST}"
                cp -r "${INTEGRATION_SRC}" "${INTEGRATION_DST}"
                echo "[集成] 集成代码已安装到 ${INTEGRATION_DST}"

                # 恢复持久化数据文件
                if [ "${BACKUP_PERSIST}" = "true" ]; then
                    cp "/tmp/window_controller_gateway_data.json.bak" "${PERSIST_FILE}"
                    echo "[集成] 已恢复持久化数据文件"
                fi
            fi

            echo "[集成] OK — 网关集成已就绪"
            echo "[集成] 重启 HA 后，设置 → 设备与服务 → 添加集成 → 搜索「慧尖」"
        else
            echo "[集成] 警告: 集成源码目录不存在: ${INTEGRATION_SRC}"
        fi
    else
        echo "[集成] 警告: HA 配置目录未找到（/homeassistant 和 /config 均不存在）"
        echo "[集成] 请确保插件配置中已映射 homeassistant_config"
    fi
fi

# ---------- 5. 后台启动 mosquitto 检测就绪 ----------
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
echo "  慧尖 LoRa 网关一体化插件已就绪"
echo "============================================"
echo ""
echo "MQTT Broker: 0.0.0.0:1883"
echo "mDNS 主机名: ${MDNS_HOSTNAME}.local"
echo "MQTT 用户名: ${USERNAME}"
echo ""
echo "LoRa 网关配置:"
echo "  Broker 地址: ${MDNS_HOSTNAME}.local (或 HA 的 IP)"
echo "  端口: 1883"
echo "  用户名: ${USERNAME}"
echo "  密码: ${PASSWORD}"
echo ""

# ---------- 6. 自动配置 HA MQTT 集成 ----------
if [ "${AUTO_SETUP}" = "true" ]; then
    echo "============================================"
    echo "  自动配置 HA MQTT 集成..."
    echo "============================================"
    /auto_setup_mqtt.sh || true
    echo ""
fi

# ---------- 7. 停止后台 mosquitto，前台运行 ----------
# Docker CMD 必须前台运行，否则容器会立即退出
pkill mosquitto 2>/dev/null || true
sleep 1

echo "[运行] Broker 以前台模式运行..."

exec mosquitto -c /etc/mosquitto/mosquitto.conf
