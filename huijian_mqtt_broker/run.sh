#!/usr/bin/with-contenv bashio
# =============================================================================
# 慧尖 LoRa 网关一体化插件 — 启动脚本 v1.3.9
#
# 架构（host_network 模式）：
#   - 容器直接使用主机网络，mosquitto 监听主机 2022 端口
#   - mDNS 用 avahi-publish 注册 _mqtt._tcp 服务，LoRa 网关自动发现 huijian.local
#   - auto_setup 和 HA Core 都用 127.0.0.1:2022 连接 broker
# =============================================================================

set -e

USERNAME=$(bashio::config 'username')
PASSWORD=$(bashio::config 'password')
AUTO_SETUP=$(bashio::config 'auto_setup_ha_mqtt')
INSTALL_INTEGRATION=$(bashio::config 'install_integration')

# host_network 模式：mosquitto 直接监听主机 2022 端口，无需 Docker 端口映射
MQTT_PORT=2022
INTERNAL_PORT=2022

echo "============================================"
echo "  慧尖 LoRa 网关一体化插件启动中..."
echo "============================================"
echo "[配置] MQTT 用户名: ${USERNAME}"
echo "[配置] MQTT 端口: ${MQTT_PORT} (host_network 模式)"
echo "[配置] 自动配置 HA MQTT 集成: ${AUTO_SETUP}"
echo "[配置] 自动安装网关集成: ${INSTALL_INTEGRATION}"
echo ""

# ---------- 1. 生成密码文件 ----------
PASSWD_FILE="/etc/mosquitto/passwd"

# 先删除旧密码文件（避免 -c 失败时残留损坏文件）
rm -f "${PASSWD_FILE}" 2>/dev/null || true

# 用 -c 创建新文件，-b 批量模式（不提示输入密码）
if mosquitto_passwd -c -b "${PASSWD_FILE}" "${USERNAME}" "${PASSWORD}"; then
    echo "[OK] 密码文件已生成"
else
    # 兜底：手动用 printf 写入密码哈希（适用于 mosquitto_passwd 不可用的场景）
    # Mosquitto 要求格式: user:$6$salt$hash  或  user:{bcrypt}hash
    # 这里用 $6$ 格式（SHA-256 with salt）
    echo "[警告] mosquitto_passwd 失败，尝试手动创建密码文件"
    SALT=$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c 16)
    PASSWD_HASH=$(printf "%s" "${PASSWORD}" | openssl dgst -sha256 -salt -binary 2>/dev/null | od -An -tx1 | tr -d ' \n')
    if [ -n "${PASSWD_HASH}" ]; then
        printf "${USERNAME}:\$6\$${SALT}\$${PASSWD_HASH}\n" > "${PASSWD_FILE}" 2>/dev/null || {
            echo "[错误] 无法创建密码文件"
            exit 1
        }
    else
        # 最终兜底：直接用 openssl 生成完整的 Mosquitto 密码行
        printf "${PASSWORD}\n${PASSWORD}\n" | openssl passwd -6 -salt "${SALT}" -stdin 2>/dev/null | {
            read -r HASH
            printf "${USERNAME}:${HASH}\n" > "${PASSWD_FILE}" 2>/dev/null || {
                echo "[错误] 无法创建密码文件"
                exit 1
            }
        }
    fi
fi

# 验证密码文件非空
if [ ! -s "${PASSWD_FILE}" ]; then
    echo "[错误] 密码文件为空"
    exit 1
fi

chmod 600 "${PASSWD_FILE}"
chown mosquitto:mosquitto "${PASSWD_FILE}" 2>/dev/null || true
echo "[OK] 密码文件权限已设置 (600, mosquitto:mosquitto)"

# 显示密码文件内容（诊断用，生产环境可移除）
echo "[诊断] 密码文件内容:"
head -1 "${PASSWD_FILE}" 2>/dev/null | sed 's/\(.\{20\}\).*/\1.../' || true

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
chmod 600 "${ACL_FILE}"
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

    # host_network 模式：允许 Supervisor/HA Core (172.30.32.x) 和本地回环
    allow 127.0.0.1;
    allow 172.30.32.0/24;
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
    # 注意：Supervisor 路由是 /addons/{slug}/...，不是 /supervisor/addons/...
    # proxy_pass 末尾的 / 会替换 location 匹配的前缀
    location /api/supervisor/ {
        proxy_pass http://${SUPERVISOR_HOST}/;
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

    # 代理 Gitee API（默认更新源，无速率限制）
    location /api/gitee/ {
        proxy_pass https://gitee.com/api/v5/;
        proxy_set_header Host gitee.com;
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

# ---------- 3b. 配置并启动 mDNS 广播 ----------
echo "[mDNS] 配置 mDNS 广播..."

# 设置 huijian.local 主机名
hostname huijian 2>/dev/null || true

# 创建 dbus 运行目录
mkdir -p /run/dbus

# 清理函数：mosquitto 退出时同时清理 avahi-publish 后台进程
MDNS_PIDS=""
cleanup_mdns() {
    for pid in ${MDNS_PIDS}; do
        kill "${pid}" 2>/dev/null || true
    done
}
trap cleanup_mdns EXIT INT TERM

# host_network 模式下，HAOS 宿主自带 avahi-daemon（已在物理网卡上广播 mDNS）。
# 用 avahi-publish 借用宿主 avahi-daemon 注册 _mqtt._tcp 服务，不绑定 5353 端口。
#
# 非 HAOS 环境（如 HA Supervised on Debian）宿主可能无 avahi-daemon，
# 此时启动容器内 dbus + avahi-daemon 兜底。

AVAHI_DAEMON_RUNNING=false
if pgrep -x avahi-daemon >/dev/null 2>&1; then
    AVAHI_DAEMON_RUNNING=true
    echo "[mDNS] 检测到宿主 avahi-daemon 已运行，使用 avahi-publish 注册服务"
else
    echo "[mDNS] 未检测到 avahi-daemon，启动容器内 dbus + avahi-daemon..."
    dbus-daemon --system 2>/dev/null || true
    sleep 1
    # 启动容器内 avahi-daemon（host_network 下直接在宿主网卡广播）
    if avahi-daemon -D 2>/dev/null; then
        AVAHI_DAEMON_RUNNING=true
        echo "[mDNS] 容器内 avahi-daemon 已启动"
    else
        echo "[mDNS] avahi-daemon 启动失败"
    fi
fi

# 用 avahi-publish 注册 _mqtt._tcp 服务（后台持续运行）
# avahi-publish 通过 D-Bus 向 avahi-daemon 注册服务，自身不绑定 5353 端口
# --no-reverse: 不注册反向 DNS
# --no-fail: avahi-daemon 不可用时不退出
AVAHI_PUBLISH_PID=""
if command -v avahi-publish >/dev/null 2>&1; then
    avahi-publish -R -s "huijian-mqtt" _mqtt._tcp "${MQTT_PORT}" \
        --no-reverse --no-fail &
    AVAHI_PUBLISH_PID=$!
    MDNS_PIDS="${AVAHI_PUBLISH_PID}"
    echo "[mDNS] avahi-publish 已启动 (PID: ${AVAHI_PUBLISH_PID})"
    sleep 2

    # 验证服务是否注册成功
    if command -v avahi-browse >/dev/null 2>&1; then
        if timeout 3 avahi-browse -t _mqtt._tcp 2>/dev/null | grep -q "huijian"; then
            echo "[mDNS] ✅ mDNS 服务验证通过，LoRa 网关可通过 huijian.local 发现本机"
        else
            echo "[mDNS] mDNS 服务已注册，广播中（验证可能需要几秒钟）"
        fi
    else
        echo "[mDNS] mDNS 服务已注册，广播中"
    fi
else
    echo "[mDNS] ⚠ avahi-publish 不可用（Dockerfile 缺少 avahi-tools 包？）"
    if [ "${AVAHI_DAEMON_RUNNING}" = "false" ]; then
        echo "[mDNS] ⚠ mDNS 不可用，LoRa 网关需手动填写 HA IP 地址连接"
    fi
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
echo "[启动] 监听: 0.0.0.0:${INTERNAL_PORT} (host_network 模式，直接暴露在主机)"

echo ""
echo "============================================"
echo "  慧尖 LoRa 网关一体化插件已就绪"
echo "============================================"
echo ""
echo "MQTT Broker: 0.0.0.0:${INTERNAL_PORT} (host_network)"
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
            --arg broker "127.0.0.1" \
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

# ---------- 8. 后台启动 mosquitto，验证 MQTT 协议可用后再继续 ----------
echo "[运行] Broker 以前台模式运行..."

# 先后台启动 mosquitto
mosquitto -c /etc/mosquitto/mosquitto.conf &
MOSQUITTO_PID=$!
echo "[运行] Mosquitto PID: ${MOSQUITTO_PID}"

# 等待 Mosquitto 进程启动（最多5秒）
MOSQUITTO_READY=false
for i in 1 2 3 4 5; do
    if ! kill -0 "${MOSQUITTO_PID}" 2>/dev/null; then
        echo "[错误] Mosquitto 进程已退出（PID=${MOSQUITTO_PID}）"
        echo "[诊断] 检查密码文件和 ACL 文件格式..."
        cat /etc/mosquitto/passwd 2>/dev/null | head -1 || echo "  密码文件不存在"
        cat /etc/mosquitto/acl 2>/dev/null || echo "  ACL 文件不存在"
        exit 1
    fi
    # 尝试 TCP 连接到 localhost:2022
    if timeout 1 sh -c "echo >/dev/tcp/127.0.0.1/2022" 2>/dev/null; then
        MOSQUITTO_READY=true
        break
    fi
    sleep 1
done

if [ "${MOSQUITTO_READY}" = "true" ]; then
    echo "[OK] Mosquitto TCP 端口 2022 已就绪"
else
    echo "[警告] Mosquitto TCP 端口5秒内未就绪，继续启动..."
fi

# 等待 Mosquitto MQTT 协议响应（用 mosquitto_pub 测试）
if command -v mosquitto_pub >/dev/null 2>&1; then
    if mosquitto_pub -h 127.0.0.1 -p 2022 -u "${USERNAME}" -P "${PASSWORD}" -t "test/ping" -m "ok" 2>/dev/null; then
        echo "[OK] Mosquitto MQTT 协议验证通过（mosquitto_pub 成功）"
    else
        echo "[警告] mosquitto_pub 测试失败（broker 可能仍在初始化或密码配置有误）"
        echo "[诊断] 检查 /etc/mosquitto/passwd 格式:"
        head -2 /etc/mosquitto/passwd 2>/dev/null | sed 's/^/  /' || echo "  文件不存在"
        echo "[诊断] mosquitto.conf 内容:"
        cat /etc/mosquitto/mosquitto.conf 2>/dev/null | sed 's/^/  /'
    fi
fi

# 将后台 mosquitto 转为前台运行：
# wait 阻塞等待 mosquitto 退出；mosquitto 退出后 trap cleanup_mdns 自动清理 avahi-publish。
# 如果 mosquitto 异常退出（wait 返回非零），重启 mosquitto 而非 exec 替换，
# 确保当前 shell 保持存活以执行 trap 清理逻辑。
while true; do
    wait "${MOSQUITTO_PID}" 2>/dev/null
    EXIT_CODE=$?
    echo "[运行] Mosquitto 已退出 (exit code: ${EXIT_CODE})，5 秒后重启..."
    sleep 5
    mosquitto -c /etc/mosquitto/mosquitto.conf &
    MOSQUITTO_PID=$!
    echo "[运行] Mosquitto 已重启 (PID: ${MOSQUITTO_PID})"
done
