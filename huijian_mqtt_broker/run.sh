#!/usr/bin/with-contenv bashio
# =============================================================================
# 慧尖 LoRa 网关一体化插件 — 启动脚本 v1.0.8
#
# 核心修复：
#   1. 启动前检查端口 1883 是否被占用，如果被占用则停止占用进程
#   2. Mosquitto 直接前台 exec 运行
#   3. avahi-daemon 修复：创建 machine-id，前台启动后转后台
#   4. Nginx 用 heredoc 动态生成配置，直接写入 SUPERVISOR_TOKEN
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

# ---------- 0. 检查端口 1883 是否被占用 ----------
echo "[检查] 端口 1883 状态..."
if netstat -tlnp 2>/dev/null | grep -q ":1883.*LISTEN"; then
    echo "[检查] 端口 1883 已被占用！"
    # 查找占用 1883 端口的进程
    OCCUPY_PID=$(netstat -tlnp 2>/dev/null | grep ":1883.*LISTEN" | awk '{print $NF}' | awk -F'/' '{print $1}' | head -1)
    if [ -n "${OCCUPY_PID}" ] && [ "${OCCUPY_PID}" != "-" ]; then
        OCCUPY_NAME=$(ps -p ${OCCUPY_PID} -o comm= 2>/dev/null || echo "unknown")
        echo "[检查] 占用进程: ${OCCUPY_NAME} (PID: ${OCCUPY_PID})"
        echo "[检查] 停止占用进程..."
        kill ${OCCUPY_PID} 2>/dev/null || true
        sleep 2
        # 如果进程仍然存活，强制杀掉
        if kill -0 ${OCCUPY_PID} 2>/dev/null; then
            echo "[检查] 进程未停止，强制终止..."
            kill -9 ${OCCUPY_PID} 2>/dev/null || true
            sleep 1
        fi
    else
        echo "[检查] 端口被占用但无法识别进程（可能是 HA 官方 Mosquitto 插件）"
        echo "[检查] 请停止 HA 官方 Mosquitto broker 插件后重试"
        echo "[检查] 或在 HA 设置 → 加载项 → Mosquitto broker → 停止"
    fi
    # 再次检查端口
    if netstat -tlnp 2>/dev/null | grep -q ":1883.*LISTEN"; then
        echo "[检查] 端口 1883 仍被占用，无法启动 broker"
        echo "[错误] 请确保没有其他 MQTT broker 在运行"
        exit 1
    else
        echo "[检查] 端口 1883 已释放"
    fi
else
    echo "[检查] 端口 1883 空闲"
fi
echo ""

# ---------- 1. 配置并启动 mDNS (avahi) ----------
echo "[mDNS] 配置 avahi-daemon..."

# avahi 需要 dbus 和 machine-id
mkdir -p /run/dbus
if [ ! -f /etc/machine-id ]; then
    echo "${MDNS_HOSTNAME}" > /etc/machine-id 2>/dev/null || true
fi
if [ ! -f /var/lib/dbus/machine-id ]; then
    mkdir -p /var/lib/dbus 2>/dev/null || true
    cp /etc/machine-id /var/lib/dbus/machine-id 2>/dev/null || true
fi

# 启动 dbus
if ! pgrep dbus-daemon >/dev/null 2>&1; then
    dbus-daemon --system --fork 2>/dev/null || {
        echo "[mDNS] dbus-daemon 启动失败，尝试无 dbus 模式"
    }
    sleep 1
fi

# 生成 avahi 配置
mkdir -p /etc/avahi
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

# 启动 avahi-daemon（重试机制）
AVAHIPID=""
for i in 1 2 3; do
    # 前台启动一次看错误信息
    if avahi-daemon -D 2>/dev/null; then
        AVAHIPID="ok"
        break
    fi
    # 如果 -D 失败，尝试直接前台启动后转后台
    if [ ${i} -eq 1 ]; then
        avahi-daemon 2>/dev/null &
        AVAHIPID=$!
        sleep 2
        if kill -0 ${AVAHIPID} 2>/dev/null; then
            AVAHIPID="ok"
            break
        fi
    fi
    echo "[mDNS] avahi-daemon 启动重试 ${i}/3..."
    sleep 1
done

if [ -n "${AVAHIPID}" ]; then
    sleep 1
    if avahi-resolve-host-name "${MDNS_HOSTNAME}.local" >/dev/null 2>&1; then
        echo "[mDNS] OK — ${MDNS_HOSTNAME}.local 可解析"
    else
        echo "[mDNS] avahi-daemon 已启动，广播 ${MDNS_HOSTNAME}.local"
    fi
else
    echo "[mDNS] avahi-daemon 启动失败"
    echo "[mDNS] LoRa 网关请使用 HA 的 IP 地址，而非 ${MDNS_HOSTNAME}.local"
fi
echo ""

# ---------- 2. 生成密码文件 ----------
PASSWD_FILE="/etc/mosquitto/passwd"

if ! mosquitto_passwd -b -c "${PASSWD_FILE}" "${USERNAME}" "${PASSWORD}" 2>/dev/null; then
    echo "[错误] 创建用户 ${USERNAME} 密码失败"
    exit 1
fi
chmod 644 "${PASSWD_FILE}"
chown mosquitto:mosquitto "${PASSWD_FILE}" 2>/dev/null || true
echo "[OK] 密码文件已生成: ${PASSWD_FILE}"

# ---------- 2b. 动态生成 ACL 文件 ----------
ACL_FILE="/etc/mosquitto/acl"
cat > "${ACL_FILE}" <<EOF
# 动态生成 — 用户: ${USERNAME}
user ${USERNAME}

# HA MQTT 集成 discovery 主题
topic readwrite homeassistant/#

# 慧尖网关协议主题
topic readwrite gateway/+
topic readwrite gateway/+/req
topic readwrite gateway/rpt_rsp

# 健康检查主题
topic readwrite test/#

# \$SYS 主题
topic read \$SYS/#
EOF
chmod 644 "${ACL_FILE}"
chown mosquitto:mosquitto "${ACL_FILE}" 2>/dev/null || true
echo "[OK] ACL 文件已生成: ${ACL_FILE} (用户: ${USERNAME})"

# ---------- 3. 创建持久化目录 ----------
mkdir -p /data/mosquitto
chmod 755 /data/mosquitto
chown mosquitto:mosquitto /data/mosquitto 2>/dev/null || true
echo "[OK] 持久化目录已创建: /data/mosquitto"

# ---------- 3b. 配置并启动 nginx（Ingress Web UI） ----------
echo "[Ingress] 配置 nginx Web UI..."
mkdir -p /run/nginx

HA_SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"
cat > /etc/nginx/http.d/ingress.conf <<NGINXEOF
server {
    listen 8099;
    allow 172.30.32.2;
    allow 127.0.0.1;
    deny all;

    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files \$uri \$uri/ /index.html;
    }

    location /api/ha/ {
        proxy_pass http://supervisor/core/api/;
        proxy_set_header Authorization "Bearer ${HA_SUPERVISOR_TOKEN}";
        proxy_set_header Content-Type "application/json";
        proxy_read_timeout 30s;
        proxy_connect_timeout 5s;
    }

    location /api/status {
        add_header Content-Type application/json;
        return 200 '{"status":"running","broker":"mosquitto","port":1883}';
    }

    location /api/version {
        add_header Content-Type application/json;
        root /usr/share/nginx/html;
        try_files /version.json =404;
    }
}
NGINXEOF

nginx 2>/dev/null || {
    echo "[Ingress] nginx 启动失败，侧边栏可能不可用"
}

# ---------- 4. 自动安装慧尖网关集成 ----------
if [ "${INSTALL_INTEGRATION}" = "true" ]; then
    echo ""
    echo "============================================"
    echo "  安装慧尖网关集成到 HA custom_components..."
    echo "============================================"

    HA_CONFIG_DIR="/homeassistant"
    if [ ! -d "${HA_CONFIG_DIR}" ]; then
        HA_CONFIG_DIR="/config"
    fi

    if [ -d "${HA_CONFIG_DIR}" ]; then
        INTEGRATION_SRC=""
        for src in /usr/share/custom_components/window_controller_gateway /data/custom_components/window_controller_gateway; do
            if [ -d "${src}" ]; then
                INTEGRATION_SRC="${src}"
                break
            fi
        done

        if [ -n "${INTEGRATION_SRC}" ]; then
            INTEGRATION_DST="${HA_CONFIG_DIR}/custom_components/window_controller_gateway"
            mkdir -p "${HA_CONFIG_DIR}/custom_components"

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
                PERSIST_FILE="${HA_CONFIG_DIR}/window_controller_gateway_data.json"
                BACKUP_PERSIST=false
                if [ -f "${PERSIST_FILE}" ]; then
                    cp "${PERSIST_FILE}" "/tmp/window_controller_gateway_data.json.bak"
                    BACKUP_PERSIST=true
                fi

                rm -rf "${INTEGRATION_DST}"
                cp -r "${INTEGRATION_SRC}" "${INTEGRATION_DST}"
                echo "[集成] 集成代码已安装到 ${INTEGRATION_DST}"

                if [ "${BACKUP_PERSIST}" = "true" ]; then
                    cp "/tmp/window_controller_gateway_data.json.bak" "${PERSIST_FILE}"
                    echo "[集成] 已恢复持久化数据文件"
                fi
            fi

            echo "[集成] OK — 网关集成已就绪"
            echo "[集成] 重启 HA 后，设置 → 设备与服务 → 添加集成 → 搜索「慧尖」"
        else
            echo "[集成] 警告: 集成源码目录不存在"
            echo "[集成] 已搜索: /usr/share/custom_components/ 和 /data/custom_components/"
        fi
    else
        echo "[集成] 警告: HA 配置目录未找到（/homeassistant 和 /config 均不存在）"
        echo "[集成] 请确保插件配置中已映射 homeassistant_config"
    fi
fi

# ---------- 5. 确保 mosquitto 用户权限 ----------
echo ""
echo "[启动] 正在配置 mosquitto broker..."
chown -R mosquitto:mosquitto /etc/mosquitto/ 2>/dev/null || true
chown -R mosquitto:mosquitto /data/mosquitto/ 2>/dev/null || true

# 最终端口检查
if netstat -tlnp 2>/dev/null | grep -q ":1883.*LISTEN"; then
    echo "[错误] 端口 1883 仍被占用，无法启动 mosquitto"
    echo "[错误] 请停止 HA 官方 Mosquitto broker 插件后重试"
    exit 1
fi

# ---------- 6. 前台启动 mosquitto ----------
echo "[启动] 启动 mosquitto broker（前台模式）..."
echo "[启动] 监听: 0.0.0.0:1883 (MQTT TCP)"
echo "[启动] ACL: gateway/+/req, gateway/rpt_rsp"

echo ""
echo "============================================"
echo "  慧尖 LoRa 网关一体化插件已就绪"
echo "============================================"
echo ""
echo "MQTT Broker: 0.0.0.0:1883"
echo "mDNS 主机名: ${MDNS_HOSTNAME}.local"
echo "Ingress Web UI: 8099 (侧边栏)"
echo "MQTT 用户名: ${USERNAME}"
echo ""
echo "LoRa 网关配置:"
echo "  Broker 地址: ${MDNS_HOSTNAME}.local (或 HA 的 IP)"
echo "  端口: 1883"
echo "  用户名: ${USERNAME}"
echo "  密码: ${PASSWORD}"
echo ""

# ---------- 7. 自动配置 HA MQTT 集成（后台执行） ----------
if [ "${AUTO_SETUP}" = "true" ]; then
    echo "============================================"
    echo "  自动配置 HA MQTT 集成..."
    echo "============================================"
    (/auto_setup_mqtt.sh || true) &
    echo ""
fi

# ---------- 8. exec 到前台 mosquitto ----------
echo "[运行] Broker 以前台模式运行..."
exec mosquitto -c /etc/mosquitto/mosquitto.conf
