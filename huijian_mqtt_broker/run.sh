#!/usr/bin/with-contenv bashio
# =============================================================================
# 慧尖 LoRa 网关一体化插件 — 启动脚本 v1.0.9
#
# 架构变更：
#   移除 host_network，使用 Docker 端口映射，避免与 HA core-mosquitto 端口冲突
#
# 启动流程：
#   1. 生成 mosquitto 密码文件和 ACL
#   2. 启动 nginx（Ingress Web UI）
#   3. 自动安装慧尖网关集成
#   4. 后台启动 auto_setup_mqtt.sh
#   5. exec mosquitto 前台运行
# =============================================================================

set -e

USERNAME=$(bashio::config 'username')
PASSWORD=$(bashio::config 'password')
AUTO_SETUP=$(bashio::config 'auto_setup_ha_mqtt')
INSTALL_INTEGRATION=$(bashio::config 'install_integration')

echo "============================================"
echo "  慧尖 LoRa 网关一体化插件启动中..."
echo "============================================"
echo "[配置] MQTT 用户名: ${USERNAME}"
echo "[配置] 自动配置 HA MQTT 集成: ${AUTO_SETUP}"
echo "[配置] 自动安装网关集成: ${INSTALL_INTEGRATION}"
echo ""

# ---------- 1. 生成密码文件 ----------
PASSWD_FILE="/etc/mosquitto/passwd"

if ! mosquitto_passwd -b -c "${PASSWD_FILE}" "${USERNAME}" "${PASSWORD}" 2>/dev/null; then
    echo "[错误] 创建用户 ${USERNAME} 密码失败"
    exit 1
fi
# mosquitto 2.x 要求密码文件权限 0700
chmod 700 "${PASSWD_FILE}"
chown mosquitto:mosquitto "${PASSWD_FILE}" 2>/dev/null || true
echo "[OK] 密码文件已生成"

# ---------- 1b. 动态生成 ACL 文件 ----------
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
# mosquitto 2.x 要求 ACL 文件权限 0700
chmod 700 "${ACL_FILE}"
chown mosquitto:mosquitto "${ACL_FILE}" 2>/dev/null || true
echo "[OK] ACL 文件已生成 (用户: ${USERNAME})"

# ---------- 2. 创建持久化目录 ----------
mkdir -p /data/mosquitto
chmod 755 /data/mosquitto
chown mosquitto:mosquitto /data/mosquitto 2>/dev/null || true
echo "[OK] 持久化目录已创建"

# ---------- 3. 配置并启动 nginx（Ingress Web UI） ----------
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
        fi
    else
        echo "[集成] 警告: HA 配置目录未找到"
    fi
fi

# ---------- 5. 确保 mosquitto 用户权限 ----------
echo ""
echo "[启动] 正在配置 mosquitto broker..."
chown -R mosquitto:mosquitto /etc/mosquitto/ 2>/dev/null || true
chown -R mosquitto:mosquitto /data/mosquitto/ 2>/dev/null || true
# 再次确保文件权限正确（mosquitto 2.x 要求 0700）
chmod 700 /etc/mosquitto/passwd 2>/dev/null || true
chmod 700 /etc/mosquitto/acl 2>/dev/null || true

# ---------- 6. 启动信息 ----------
echo "[启动] 启动 mosquitto broker（前台模式）..."
echo "[启动] 监听: 0.0.0.0:1883 (MQTT TCP)"

echo ""
echo "============================================"
echo "  慧尖 LoRa 网关一体化插件已就绪"
echo "============================================"
echo ""
echo "MQTT Broker: 0.0.0.0:1883"
echo "Ingress Web UI: 8099 (侧边栏)"
echo "MQTT 用户名: ${USERNAME}"
echo ""
echo "LoRa 网关配置:"
echo "  Broker 地址: HA 的 IP 地址"
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
