#!/usr/bin/with-contenv bashio
# =============================================================================
# 慧尖 LoRa 网关一体化插件 — 启动脚本 v1.2.3
#
# 架构：
#   - 容器内 mosquitto 固定监听 2022（不使用 1883，避免与 HA 官方 Mosquitto 冲突）
#   - Docker 端口映射: 主机 2022 → 容器 2022
#   - 容器内 auto_setup 用 127.0.0.1:2022 检测 broker
#   - HA Core 用 172.30.32.1:2022 连接 broker
# =============================================================================

set -e

USERNAME=$(bashio::config 'username')
PASSWORD=$(bashio::config 'password')
AUTO_SETUP=$(bashio::config 'auto_setup_ha_mqtt')
INSTALL_INTEGRATION=$(bashio::config 'install_integration')

# Docker 端口映射在 config.yaml 中固定为 2022:2022
# 容器内 mosquitto 固定监听 2022，主机映射固定 2022
MQTT_PORT=2022
INTERNAL_PORT=2022

echo "============================================"
echo "  慧尖 LoRa 网关一体化插件启动中..."
echo "============================================"
echo "[配置] MQTT 用户名: ${USERNAME}"
echo "[配置] MQTT 主机端口: ${MQTT_PORT} (映射到容器内 ${INTERNAL_PORT})"
echo "[配置] 自动配置 HA MQTT 集成: ${AUTO_SETUP}"
echo "[配置] 自动安装网关集成: ${INSTALL_INTEGRATION}"
echo ""

# ---------- 1. 生成密码文件 ----------
PASSWD_FILE="/etc/mosquitto/passwd"

if ! mosquitto_passwd -b -c "${PASSWD_FILE}" "${USERNAME}" "${PASSWORD}" 2>/dev/null; then
    echo "[错误] 创建用户 ${USERNAME} 密码失败"
    exit 1
fi
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

# SUPERVISOR_TOKEN 由 with-contenv 从 /run/s6/container-env 自动加载
HA_SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"

if [ -z "${HA_SUPERVISOR_TOKEN}" ]; then
    echo "[Ingress] 警告: SUPERVISOR_TOKEN 为空，HA API 代理将返回 401"
    echo "[Ingress] 尝试从 /run/s6/container-env 读取..."
    if [ -f /run/s6/container-env ]; then
        source /run/s6/container-env 2>/dev/null || true
        HA_SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"
    fi
fi

if [ -n "${HA_SUPERVISOR_TOKEN}" ]; then
    echo "[Ingress] SUPERVISOR_TOKEN 已加载"
else
    echo "[Ingress] 错误: SUPERVISOR_TOKEN 仍为空，Web UI 状态检测将不可用"
fi

# HA Supervisor 地址：优先用主机名，兜底用固定 IP（full_access 模式下 DNS 可能不解析）
SUPERVISOR_HOST="supervisor"
# 解析测试：如果不通则使用 Supervisor 固定 IP
if ! getent hosts supervisor >/dev/null 2>&1; then
    echo "[Ingress] supervisor 主机名无法解析，使用固定 IP 172.30.32.2"
    SUPERVISOR_HOST="172.30.32.2"
fi

cat > /etc/nginx/http.d/ingress.conf <<NGINXEOF
server {
    listen 8099;

    # 安全: 仅允许 HA Core (172.30.32.2) 访问 Ingress 端口
    allow 172.30.32.2;
    deny all;

    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files \$uri \$uri/ /index.html;
    }

    # 代理 HA Supervisor API — token 在此注入，前端无需携带
    # /api/ha/ → HA Core REST API（设备、服务、实体等）
    location /api/ha/ {
        proxy_pass http://${SUPERVISOR_HOST}/core/api/;
        proxy_set_header Authorization "Bearer ${HA_SUPERVISOR_TOKEN}";
        proxy_set_header Content-Type "application/json";
        proxy_set_header Accept "application/json";
        proxy_read_timeout 30s;
        proxy_connect_timeout 5s;
        proxy_ssl_verify off;
    }

    # /api/supervisor/ → Supervisor API（插件更新、重启等）
    location /api/supervisor/ {
        proxy_pass http://${SUPERVISOR_HOST}/supervisor/;
        proxy_set_header Authorization "Bearer ${HA_SUPERVISOR_TOKEN}";
        proxy_set_header Content-Type "application/json";
        proxy_set_header Accept "application/json";
        proxy_read_timeout 120s;
        proxy_connect_timeout 5s;
        proxy_ssl_verify off;
    }

    # MQTT Broker 状态检测 — nginx 直接返回，无需调用 HA API
    location /api/status {
        add_header Content-Type application/json always;
        return 200 '{"status":"running","broker":"mosquitto","port":${MQTT_PORT},"internal_port":${INTERNAL_PORT}}';
    }

    location /api/version {
        add_header Content-Type application/json;
        root /usr/share/nginx/html;
        try_files /version.json =404;
    }

    # 集成安装状态 — 插件本地事实（integration.json 由本脚本写入），不依赖 HA API
    location = /api/integration {
        add_header Content-Type application/json always;
        root /usr/share/nginx/html;
        try_files /integration.json =404;
    }

    # Broker 客户端连接数 — broker_status.json 由后台循环每 10 秒刷新
    location = /api/broker {
        add_header Content-Type application/json always;
        root /usr/share/nginx/html;
        try_files /broker_status.json =404;
    }

    # 代理 GitHub API（检查更新用），避免 Ingress iframe 中 CSP 拦截外部请求
    location /api/github/ {
        proxy_pass https://api.github.com/;
        proxy_set_header Host api.github.com;
        proxy_ssl_server_name on;
        proxy_read_timeout 15s;
        proxy_connect_timeout 10s;
    }
}
NGINXEOF

nginx 2>/dev/null || {
    echo "[Ingress] nginx 启动失败，侧边栏可能不可用"
    # 诊断：输出 nginx 配置测试结果
    nginx -t 2>&1 || true
}

# ---------- 3b. 配置并启动 avahi mDNS ----------
echo "[mDNS] 配置 avahi-daemon..."
# 移除默认的 avahi 服务配置（避免冲突）
cat > /etc/avahi/avahi-daemon.conf <<AVAHI_EOF
[server]
use-ipv4=yes
use-ipv6=no
enable-dbus=yes

[publish]
publish-addresses=yes
publish-hinfo=yes
publish-workstation=no
publish-domain=yes

[reflector]
enable-reflector=yes
AVAHI_EOF

# 设置 huijian.local 主机名
hostname huijian 2>/dev/null || true

# 创建 dbus 运行目录（容器中可能不存在）
mkdir -p /run/dbus

# 启动 dbus 和 avahi-daemon
dbus-daemon --system 2>/dev/null || {
    echo "[mDNS] dbus-daemon 启动失败"
}

# 等待 dbus 就绪
sleep 1

# 启动 avahi-daemon
if avahi-daemon -D 2>/dev/null; then
    echo "[mDNS] avahi-daemon 已启动，LoRa 网关可通过 huijian.local 发现本机"
else
    echo "[mDNS] avahi-daemon 启动失败，huijian.local 可能不可用"
    echo "[mDNS] LoRa 网关可改用 HA 的 IP 地址连接"
fi

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

# ---------- 4b. 写入集成安装状态（Web UI 本地读取，不依赖 HA Core API） ----------
# 背景：HA Core 会拒绝插件 SUPERVISOR_TOKEN 访问 Core REST API（401），
# 因此 Web UI 的状态检查全部改用插件本地生成的状态文件。
STATUS_CONFIG_DIR="/homeassistant"
if [ ! -d "${STATUS_CONFIG_DIR}" ]; then
    STATUS_CONFIG_DIR="/config"
fi
INTEGRATION_MANIFEST="${STATUS_CONFIG_DIR}/custom_components/window_controller_gateway/manifest.json"
if [ -f "${INTEGRATION_MANIFEST}" ]; then
    INTG_VER=$(jq -r '.version // "unknown"' "${INTEGRATION_MANIFEST}" 2>/dev/null || echo "unknown")
    if jq -n --arg v "${INTG_VER}" '{installed:true, version:$v}' > /usr/share/nginx/html/integration.json 2>/dev/null; then
        echo "[状态] 集成安装状态已写入 (v${INTG_VER})"
    fi
else
    echo '{"installed":false}' > /usr/share/nginx/html/integration.json 2>/dev/null || true
fi

# ---------- 5. 确保 mosquitto 用户权限 ----------
echo ""
echo "[启动] 正在配置 mosquitto broker..."
chown -R mosquitto:mosquitto /etc/mosquitto/ 2>/dev/null || true
chown -R mosquitto:mosquitto /data/mosquitto/ 2>/dev/null || true
chmod 700 /etc/mosquitto/passwd 2>/dev/null || true
chmod 700 /etc/mosquitto/acl 2>/dev/null || true

# ---------- 6. 启动信息 ----------
echo "[启动] 启动 mosquitto broker（前台模式）..."
echo "[启动] 容器内监听: 0.0.0.0:${INTERNAL_PORT} → 主机映射: ${MQTT_PORT}"

echo ""
echo "============================================"
echo "  慧尖 LoRa 网关一体化插件已就绪"
echo "============================================"
echo ""
echo "MQTT Broker: 0.0.0.0:${INTERNAL_PORT} (容器内)"
echo "外部访问: HA_IP:${MQTT_PORT} (Docker 映射)"
echo "Ingress Web UI: 8099 (侧边栏)"
echo "MQTT 用户名: ${USERNAME}"
echo ""

# ---------- 7. 自动写入 MQTT 引导标记（集成侧消费） ----------
# 旧方案（v1.0-v1.1.9）通过 REST API 自动创建 HA MQTT 配置条目，但 HA Core
# REST API 从未提供"创建配置条目"端点，导致所有版本的自动配置静默失败。
# 新方案（v1.2.0+）：将连接信息写入标记文件，集成侧在 async_setup_entry 时
# 读取并通过程序化 config flow 自动创建 MQTT 配置条目（详见 mqtt_bootstrap.py）。
HA_CONFIG_DIR="/homeassistant"
if [ ! -d "${HA_CONFIG_DIR}" ]; then
    HA_CONFIG_DIR="/config"
fi

if [ "${AUTO_SETUP}" = "true" ]; then
    if [ -d "${HA_CONFIG_DIR}" ]; then
        MARKER_PATH="${HA_CONFIG_DIR}/window_controller_gateway_mqtt_bootstrap.json"
        # 使用 jq 构造 JSON，正确转义密码中的特殊字符
        if jq -n \
            --arg broker "172.30.32.1" \
            --argjson port "${MQTT_PORT}" \
            --arg username "${USERNAME}" \
            --arg password "${PASSWORD}" \
            '{broker:$broker, port:$port, username:$username, password:$password}' \
            > "${MARKER_PATH}" 2>/dev/null; then
            chmod 600 "${MARKER_PATH}" 2>/dev/null || true
            echo "[自动配置] MQTT 引导标记已写入: ${MARKER_PATH}"
        else
            echo "[自动配置] 警告: 无法写入 MQTT 引导标记（jq 不可用或写入失败）"
        fi
    else
        echo "[自动配置] 警告: HA 配置目录未找到，跳过 MQTT 引导标记"
    fi
else
    # 自动配置已关闭：清理历史标记（含凭据），避免集成侧读到过期数据无限重试
    rm -f "${HA_CONFIG_DIR}/window_controller_gateway_mqtt_bootstrap.json" 2>/dev/null || true
fi

# ---------- 7b. Broker 连接数后台采集（Web UI 本地读取，不依赖 HA API） ----------
# 每 10 秒统计 :2022 上的 ESTABLISHED 连接数写入 broker_status.json。
# exec mosquitto 后此子进程继续运行（独立进程，被 init 接管）。
(
    while true; do
        CLIENTS=$(netstat -tn 2>/dev/null | grep ':2022' | grep -c 'ESTABLISHED' || true)
        jq -n --argjson c "${CLIENTS:-0}" '{clients:$c, updated:(now|todate)}' \
            > /usr/share/nginx/html/broker_status.json 2>/dev/null || true
        sleep 10
    done
) &

# ---------- 8. exec 到前台 mosquitto ----------
echo "[运行] Broker 以前台模式运行..."
exec mosquitto -c /etc/mosquitto/mosquitto.conf
