#!/usr/bin/with-contenv bashio
# =============================================================================
# 慧尖 LoRa 网关一体化插件 — 启动脚本（版本号以 config.yaml 为准）
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

# v1.6.3：用户名白名单校验（H4 根治）——用户名会拼进密码文件/ACL/heredoc，
# 含 % \ 换行等字符可破坏 printf 输出与 acl 解析；非法则拒绝启动，明确报错
case "${USERNAME}" in
    ''|*[!A-Za-z0-9_-]*)
        echo "[错误] MQTT 用户名非法（仅允许字母/数字/下划线/连字符）: '${USERNAME}'"
        exit 1
        ;;
esac

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
    # Mosquitto 2.x 密码文件支持格式：
    #   $7$（PBKDF2，mosquitto_passwd 默认）、$6$（SHA-512 crypt）、
    #   {SHA}/{SSHA}/{BCRYPT} 前缀。
    # openssl passwd -6 生成 $6$（SHA-512 crypt）格式，Mosquitto 可直接验证。
    # 注意：不能用 openssl dgst -sha256 手动拼 $6$ 前缀——那是无效格式，
    # 会导致所有客户端认证失败（此前的历史 bug，已修复）。
    echo "[警告] mosquitto_passwd 失败，尝试用 openssl passwd 创建密码文件"
    SALT=$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c 16)
    HASH=$(printf "%s\n" "${PASSWORD}" | openssl passwd -6 -salt "${SALT}" -stdin 2>/dev/null)
    if [ -n "${HASH}" ]; then
        # v1.6.3：必须用 printf '%s:%s\n'——直接把变量当格式串时，
        # 用户名含 % 或反斜杠转义（如 %s、\c）会被 printf 解释，写出损坏的哈希行
        printf '%s:%s\n' "${USERNAME}" "${HASH}" > "${PASSWD_FILE}" 2>/dev/null || {
            echo "[错误] 无法创建密码文件"
            exit 1
        }
        echo "[OK] 已用 openssl passwd 生成密码文件（$6$ SHA-512 crypt 格式）"
    else
        echo "[错误] openssl passwd 不可用，无法创建密码文件"
        exit 1
    fi
fi

# 验证密码文件非空
if [ ! -s "${PASSWD_FILE}" ]; then
    echo "[错误] 密码文件为空"
    exit 1
fi

# ---------- 1a. 创建 ha_mqtt 用户（HA MQTT 集成专用） ----------
# Bug5 修复：分离用户收紧权限。
# - ${USERNAME}（huijian）：LoRa 网关 / 客户端使用，ACL 仅授权网关协议主题，
#   不能读写 homeassistant/#（防凭据泄露后被用来伪造 HA 发现消息）。
# - ha_mqtt：HA MQTT 集成使用，ACL 授权 homeassistant/#（MQTT discovery 必需）。
# 密码与 ${PASSWORD} 相同（均来自插件配置），权限隔离按用户名由 ACL 保证。
HA_MQTT_USERNAME="ha_mqtt"
HA_MQTT_USER_CREATED=false
if command -v mosquitto_passwd >/dev/null 2>&1; then
    if mosquitto_passwd -b "${PASSWD_FILE}" "${HA_MQTT_USERNAME}" "${PASSWORD}" 2>/dev/null; then
        HA_MQTT_USER_CREATED=true
        echo "[OK] HA MQTT 用户已创建: ${HA_MQTT_USERNAME}"
    else
        echo "[警告] 创建 HA MQTT 用户失败（降级：HA 集成将使用 ${USERNAME} 连接）"
    fi
else
    # 兜底：手动用 openssl 追加哈希（mosquitto_passwd 不可用场景）
    # openssl passwd -6 生成 $6$（SHA-512 crypt），Mosquitto 2.x 可验证
    HA_SALT=$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c 16)
    HASH=$(printf "%s\n" "${PASSWORD}" | openssl passwd -6 -salt "${HA_SALT}" -stdin 2>/dev/null)
    if [ -n "${HASH}" ]; then
        printf '%s:%s\n' "${HA_MQTT_USERNAME}" "${HASH}" >> "${PASSWD_FILE}" 2>/dev/null && HA_MQTT_USER_CREATED=true
    fi
fi

# v1.6.24：z2m 直连慧尖内置 broker 的专用最小权限账号（官方 7.x 强制认证
# 环境下的推荐共存路径：z2m 加载项配置 mqtt://<本机>:2022 + 本账号）。
# 创建失败仅影响直连路径（桥路径不依赖），不降级不告警刷屏。
Z2M_USERNAME="huijian_z2m"
if command -v mosquitto_passwd >/dev/null 2>&1; then
    mosquitto_passwd -b "${PASSWD_FILE}" "${Z2M_USERNAME}" "${PASSWORD}" 2>/dev/null \
        && echo "[OK] z2m 直连账号已创建: ${Z2M_USERNAME}" \
        || echo "[提示] z2m 直连账号创建失败（不影响桥共存路径）"
fi

# bootstrap 标记使用哪个用户：ha_mqtt 创建成功才用，否则回退 ${USERNAME}
BOOTSTRAP_USERNAME="${USERNAME}"
if [ "${HA_MQTT_USER_CREATED}" = "true" ]; then
    BOOTSTRAP_USERNAME="${HA_MQTT_USERNAME}"
fi

chmod 600 "${PASSWD_FILE}"
chown mosquitto:mosquitto "${PASSWD_FILE}" 2>/dev/null || true
echo "[OK] 密码文件权限已设置 (600, mosquitto:mosquitto)"

# v1.6.3：删除"密码文件内容诊断"打印——即使命令端截断，前 20 字符
# 已足够泄露盐值与算法参数，属凭据外泄面

# ---------- 1b. 动态生成 ACL 文件 ----------
ACL_FILE="/etc/mosquitto/acl"
{
    cat <<EOF
# 动态生成 — 按用户隔离权限
#
# ${USERNAME}（LoRa 网关 / 调试客户端）：
#   仅网关协议主题 + 状态心跳，不能读写 homeassistant/#（防伪造 HA 发现）
user ${USERNAME}

# 慧尖网关协议主题
topic readwrite gateway/+
topic readwrite gateway/+/req
topic readwrite gateway/rpt_rsp

# 网关 birth/will 与 HA 状态心跳
topic readwrite homeassistant/status

# 健康检查主题
topic readwrite test/#

# \$SYS 主题（只读）
topic read \$SYS/#
EOF
    if [ "${HA_MQTT_USER_CREATED}" = "true" ]; then
        cat <<EOF

# ${HA_MQTT_USERNAME}（HA MQTT 集成）：白名单与共存桥主题腿逐条对齐
# （v1.6.24 安全评审定案：不用 readwrite # ——爆炸半径不超桥白名单；
# HA 消费面 = discovery + 桥入向 zigbee2mqtt/# + 慧尖网关协议）。
# 未来新增桥主题腿时必须同步扩本白名单（test_v1624 对齐钉桩）。
user ${HA_MQTT_USERNAME}

topic readwrite homeassistant/#
topic readwrite zigbee2mqtt/#

# 慧尖网关协议主题
topic readwrite gateway/+
topic readwrite gateway/+/req
topic readwrite gateway/rpt_rsp

# \$SYS 主题（只读）
topic read \$SYS/#
EOF
    else
        cat <<EOF

# 回退：${HA_MQTT_USERNAME} 创建失败，${USERNAME} 保留 HA discovery 权限（旧行为）
topic readwrite homeassistant/#
EOF
    fi
    cat <<EOF

# ${Z2M_USERNAME}（zigbee2mqtt 直连慧尖内置 broker，v1.6.24）：
# z2m 自身主题 + HA discovery（z2m 要发布发现配置）——不含 gateway/#，
# 与桥白名单同边界。
user ${Z2M_USERNAME}
topic readwrite zigbee2mqtt/#
topic readwrite homeassistant/#
topic read \$SYS/#
EOF
} > "${ACL_FILE}"
chmod 600 "${ACL_FILE}"
chown mosquitto:mosquitto "${ACL_FILE}" 2>/dev/null || true
echo "[OK] ACL 文件已生成 (用户: ${USERNAME} + ${HA_MQTT_USERNAME})"

# ---------- 2. 创建持久化目录 ----------
mkdir -p /data/mosquitto
chmod 755 /data/mosquitto
chown mosquitto:mosquitto /data/mosquitto 2>/dev/null || true
echo "[OK] 持久化目录已创建"

# ---------- 3. 配置并启动 nginx（Ingress Web UI） ----------
echo "[Ingress] 配置 nginx Web UI..."
mkdir -p /run/nginx

# SUPERVISOR_TOKEN 由 shebang 的 with-contenv 注入环境（s6-overlay v3 的
# /run/s6/container_environment 是"每变量一文件"的目录，不存在可 source 的
# container-env 单文件——v1.6.4 删除该死回退分支，旧代码 source 恒不执行）。
HA_SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"

if [ -z "${HA_SUPERVISOR_TOKEN}" ]; then
    echo "[Ingress] 警告: SUPERVISOR_TOKEN 为空，HA API 代理将返回 401"
fi

if [ -n "${HA_SUPERVISOR_TOKEN}" ]; then
    echo "[Ingress] SUPERVISOR_TOKEN 已加载"
else
    echo "[Ingress] 错误: SUPERVISOR_TOKEN 仍为空，Web UI 状态检测将不可用"
fi

# HA Supervisor 地址：优先用主机名，兜底用固定 IP（host_network 下 DNS 可能不解析）
# v1.6.4 修复：旧判活命令 getent 在 alpine/musl 体系根本不存在（busybox 未编该
# applet、aports 无此包——netstat 事故同构），错误被吞导致恒走固定 IP 分支
# 且每次启动打印误导日志。改用 base 镜像 bind-tools 提供的 host 命令。
SUPERVISOR_HOST="supervisor"
if ! host supervisor >/dev/null 2>&1; then
    echo "[Ingress] supervisor 主机名无法解析，使用固定 IP 172.30.32.2"
    SUPERVISOR_HOST="172.30.32.2"
fi

cat > /etc/nginx/http.d/ingress.conf <<NGINXEOF
server {
    listen 8099;

    # host_network 模式：允许 Supervisor/HA Core (172.30.32.x) 和本地回环。
    # TODO(设备上验证一次 ingress 实际源 IP 后可收紧为具体 IP；当前 supervisor
    # 的 hassio 网桥源地址随部署形态变化，贸然收窄会整站 403)
    allow 127.0.0.1;
    allow 172.30.32.0/24;
    deny all;

    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files \$uri \$uri/ /index.html;
        # v1.6.6：静态页必须 no-store——插件更新后 ingress 会话 token 路径
        # 不变，浏览器对无 Cache-Control 的 index.html 做启发式缓存，
        # 导致容器已是新版、页面却停留在旧版（1.6.5 更新后 Web 显示
        # 1.6.4 实锤）。UI 只有单个 html+几个 json，无缓存代价。
        add_header Cache-Control "no-store" always;
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
        # v1.6.9：补 no-store（此前唯一漏网：设备/实体/条目 JSON 无缓存头，
        # 会被浏览器启发式缓存 → UI 显示陈旧数据）
        add_header Cache-Control "no-store" always;
    }

    # v1.6.3：删除 /api/supervisor/ 死代理。Supervisor 安全设计禁止插件经 API
    # 自我更新（/addons/self/update 恒 403，2026-08-27 实测定案），Web UI
    # 自 v1.5.3 起零调用；留着只是把一个带完整 Supervisor token 的通道
    # 暴露给同网段其它加载项容器，纯攻击面。

    # MQTT Broker 状态检测 — 由后台探活循环写 status.json（约 5 秒粒度），
    # 真实反映 mosquitto 存活。v1.6.3 前此处是 nginx return 硬编码
    # "running"，broker 崩溃期间页面仍显示运行中，掩盖故障。
    # 文件不存在（循环未就绪/容器早期）返回 404，前端显示 "HTTP 404" 异常态
    location = /api/status {
        add_header Cache-Control "no-store" always;
        root /usr/share/nginx/html;
        try_files /status.json =404;
    }

    # v1.6.6：version.json / integration.json 是容器启动时生成的事实文件，
    # 同样补 no-store（此前无任何缓存头，会被启发式缓存）
    location /api/version {
        add_header Cache-Control "no-store" always;
        root /usr/share/nginx/html;
        try_files /version.json =404;
    }

    # 集成安装状态 — 插件本地事实（integration.json 由本脚本写入），不依赖 HA API
    location = /api/integration {
        add_header Cache-Control "no-store" always;
        root /usr/share/nginx/html;
        try_files /integration.json =404;
    }

    # Broker 客户端连接数 — broker_status.json 由后台循环每 5 秒刷新
    location = /api/broker {
        add_header Cache-Control "no-store" always;
        root /usr/share/nginx/html;
        try_files /broker_status.json =404;
    }

    # 代理 GitHub API（检查更新用），避免 Ingress iframe 中 CSP 拦截外部请求
    # v1.6.6：GitHub 上游自带 Cache-Control（public, max-age=60）会透传给
    # iframe 浏览器、拖慢「有可用升级」发现——hide 后统一改 no-store
    location /api/github/ {
        proxy_pass https://api.github.com/;
        proxy_set_header Host api.github.com;
        proxy_ssl_server_name on;
        proxy_read_timeout 15s;
        proxy_connect_timeout 10s;
        proxy_hide_header Cache-Control;
        add_header Cache-Control "no-store" always;
    }

    # 代理 Gitee API（默认更新源，无速率限制）
    location /api/gitee/ {
        proxy_pass https://gitee.com/api/v5/;
        proxy_set_header Host gitee.com;
        proxy_ssl_server_name on;
        proxy_read_timeout 15s;
        proxy_connect_timeout 10s;
        proxy_hide_header Cache-Control;
        add_header Cache-Control "no-store" always;
    }
}
NGINXEOF

# v1.6.26（第八轮审计 W-1）：本文件含 nginx 注入用的明文 SUPERVISOR_TOKEN
# ——与 passwd/acl 的 600/700 同口径收紧（同族"静默失防面"：passwd/acl 都
# 有 chmod，唯独此文件默认 umask 022 → 644，容器内任何低权进程可读 token
# 并经 /api/ha/ 代理调用 HA Core 全套 REST API）。nginx master 以 root 读
# 配置、worker 不读 conf，600 不影响运行。
chmod 600 /etc/nginx/http.d/ingress.conf 2>/dev/null || true

# v1.6.18 运行期兜底：alpine nginx 包自带 http.d/default.conf（listen 80
# default_server + listen [::]:80）。本加载项 host_network，该默认站会抢绑
# 宿主 80——宿主 80 空闲时是"插件白占 80"，被占时（NAS 常见：DSM 反代/其他
# 容器）bind 失败打死整个 nginx master，8099 侧边栏连坐全挂（2026-09-02 实锤）。
# Dockerfile 已 rm，这里再防基础镜像/apk 升级带回同名文件，顺带清掉其他
# 监听 80 的杂散 conf（本插件只应监听 8099）。
for f in /etc/nginx/http.d/*.conf; do
    [ -e "$f" ] || continue
    [ "$f" = "/etc/nginx/http.d/ingress.conf" ] && continue
    if grep -Eq '^[[:space:]]*listen[[:space:]]+(\[::\]:)?80([[:space:];]|$)' "$f"; then
        echo "[Ingress] 移除杂散默认站 conf: $f"
        rm -f "$f"
    fi
done

# v1.6.4：不再 2>/dev/null 吞启动错误——nginx 起不来最常见是 8099 被占/权限，
# 旧写法把真实报错丢了，只剩 nginx -t"配置语法正常"的假象，Web UI 静默瘫痪
# v1.6.18：bind 失败先试一次兜底重启（宿主 80 服务重启竞态窗口），仍失败则
# 打印占用诊断，不再只留 syntax ok 假象
nginx || {
    echo "[Ingress] nginx 首启失败，5 秒后重试一次…"
    sleep 5
    nginx && echo "[Ingress] nginx 重试启动成功" || {
        echo "[Ingress] nginx 启动失败（错误见上），侧边栏可能不可用"
        # 追加配置语法测试辅助定位（语法问题与运行时问题分开看）
        nginx -t 2>&1 || true
        # 端口占用现场取证（v1.6.26 第八轮审计 E-4 根治）：旧版用 netstat，
        # 但 HA alpine base 镜像没有 netstat（本文件 §7 的 v1.6.4 注释早已
        # 实锤"apk 包仅 bash/bind-tools/…"且据此改用 /proc 方案——当时漏改
        # 了这处取证，宿主 80/8099 被占时恰在最需要时无输出）。复用
        # /proc/net/tcp{,6} 扫描：state 0A=LISTEN；80=0050、8099=1F9B
        awk -v p80=':0050$' -v p99=':1F9B$' \
            'FNR>1 && ($2 ~ p80 || $2 ~ p99) && $4=="0A" { print "  [取证] LISTEN " $2 }' \
            /proc/net/tcp /proc/net/tcp6 2>/dev/null
    }
}

# ---------- 3b. 配置并启动 mDNS 广播 ----------
echo "[mDNS] 配置 mDNS 广播..."

# mDNS 相关命令不能因 set -e 而终止整个脚本
set +e

# 清理函数：mosquitto 退出时同时清理 mDNS 后台进程
# v1.6.3：mDNS 现在是看门狗子 shell（MDNS_PID）+ 其 python 子进程，
# kill 子 shell 不会带走 python，须一并 pkill，否则残留进程继续占用 5353
MDNS_PID=""
MOSQUITTO_PID=""
cleanup_mdns() {
    if [ -n "${MDNS_PID}" ]; then
        kill "${MDNS_PID}" 2>/dev/null || true
    fi
    pkill -f mdns_publisher.py 2>/dev/null || true
}
# v1.6.4 停机路径根修：旧写法 trap cleanup_mdns EXIT INT TERM 的处理函数
# 只清理不退出——SIGTERM 到达后 bash 跑完 handler 从被中断的 wait 返回
# （rc=143），主循环把它当崩溃继续计数并重启 mosquitto，直到 docker 宽限期
# 结束 SIGKILL：broker 从未收到 TERM 优雅落盘（persistence 最坏丢 30 分钟
# retained 状态）、add-on 每次 stop/restart 都拖满超时。现 INT/TERM 显式
# 转发 TERM 给 broker、清理、exit 143。
shutdown_handler() {
    if [ -n "${MOSQUITTO_PID}" ]; then
        kill -TERM "${MOSQUITTO_PID}" 2>/dev/null || true
        # 给 broker 落盘 persistence（retained 消息）的窗口——脚本 exit 后
        # s6 即拆容器进程树，不留窗口 mosquitto 可能带着未保存状态被杀
        sleep 1 2>/dev/null || true
    fi
    cleanup_mdns
    exit 143
}
trap cleanup_mdns EXIT
trap shutdown_handler INT TERM

# mDNS 实现方案（v1.4.2+）：
#
# 之前使用 avahi-publish + D-Bus 连接宿主 avahi-daemon 的方案存在问题：
# 1. HAOS 容器内 D-Bus socket (/run/dbus/system_bus_socket) 不一定可用
# 2. 回退到容器内启动 avahi-daemon 会与宿主 avahi-daemon 端口冲突（5353）
# 3. BusyBox 的 grep 不支持 -P（Perl 正则），导致 IP 检测失败
#
# 新方案：使用 Python zeroconf 库，纯 Python 实现的 mDNS/DNS-SD 协议，
# 直接通过 UDP multicast 在 5353 端口广播，不需要 D-Bus，
# 不需要 avahi-daemon，不会和宿主 avahi-daemon 冲突
# （multicast 是共享的，多个进程可以同时响应 mDNS 查询）。

echo "[mDNS] 使用 Python zeroconf 广播 mDNS 服务..."

# 启动 mDNS 广播（v1.6.3 看门狗监督）：
# 旧实现单发启动 + 3 秒存活检查，进程因网络抖动/IP 变更/异常退出后
# 广播永久消失（LoRa 网关再也发现不了 huijian.local），且无人重启。
# 现由子 shell 循环监督：异常退出 10 秒后重启；正常退出（主动停止）则结束。
if [ -f /usr/bin/mdns_publisher.py ] && command -v python3 >/dev/null 2>&1; then
    (
        while true; do
            python3 /usr/bin/mdns_publisher.py "${MQTT_PORT}"
            RC=$?
            if [ "${RC}" -eq 0 ]; then
                echo "[mDNS] 广播进程正常退出，不再重启"
                break
            fi
            echo "[mDNS] 广播进程异常退出 (code ${RC})，10 秒后重启..."
            sleep 10
        done
    ) &
    MDNS_PID=$!
    echo "[mDNS] mDNS 广播已启动 (看门狗 PID: ${MDNS_PID})"

    # 等待 mDNS 服务注册（zeroconf 需要几秒初始化）
    sleep 3

    # 检查看门狗是否存活（python 崩溃重启间隔内看门狗仍在循环）
    if ! kill -0 "${MDNS_PID}" 2>/dev/null; then
        echo "[mDNS] mDNS 看门狗已退出，检查 zeroconf 是否安装正确"
        MDNS_PID=""
    else
        echo "[mDNS] mDNS 广播中（异常时自动重启）"
        echo "[mDNS] LoRa 网关可通过 huijian.local:${MQTT_PORT} 连接"
    fi
else
    echo "[mDNS] mdns_publisher.py 或 python3 不可用"
    echo "[mDNS] mDNS 不可用，LoRa 网关需手动填写 HA IP 地址连接"
fi

# 恢复 set -e
set -e

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
                # v1.6.4：jq 直读文件——旧 cat|jq 管道里 cat 失败被 2>/dev/null 吞、
                # jq 收空输入 rc=0 输出空串，|| echo "0" 兜底永不触发（管道状态掩蔽）
                EXISTING_VERSION=$(jq -r '.version // "0"' "${INTEGRATION_DST}/manifest.json" 2>/dev/null || echo "0")
                NEW_VERSION=$(jq -r '.version // "0"' "${INTEGRATION_SRC}/manifest.json" 2>/dev/null || echo "0")
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
        # Bug5 修复：写入 ha_mqtt 用户（ACL 全权限），HA 集成用其连接
        if jq -n \
            --arg broker "127.0.0.1" \
            --argjson port "${MQTT_PORT}" \
            --arg username "${BOOTSTRAP_USERNAME}" \
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

# ---------- 7b. Broker 连接数与存活状态后台采集（Web UI 本地读取，不依赖 HA API） ----------
# 每 5 秒：统计 :2022 上的 ESTABLISHED 连接数写 broker_status.json；
# 并写 status.json（nginx /api/status 的真实数据源，v1.6.3 取代硬编码 return 200）。
# v1.6.4 根修：HA alpine base 镜像【没有 netstat】（apk 包仅 bash/bind-tools/
# ca-certificates/curl/jq/libstdc++/tzdata/xz），旧 netstat 判活恒空输出——
# status.json 永远 stopped、clients 永远 0（双双假状态）。改用 base 必有的
# /proc/net/tcp{,6} + busybox awk：state 0A=LISTEN、01=ESTABLISHED，
# 端口比对用 printf '%04X' 动态十六进制（kernel 输出为大写，无硬编码）。
# host_network 下容器网络命名空间=主机，看到的即真实监听。
# 本循环是后台子 shell；v1.6.3 起主脚本无 exec 语义（wait 自愈循环常驻），
# 主脚本退出后由 init 接管继续运行。
# ---------- 7b. 第三方共存自动桥（v1.6.24） ----------
# 场景：用户后装官方「Mosquitto broker」加载项 + zigbee2mqtt（z2m 默认连
# core-mosquitto:1883；host_network 下即主机 127.0.0.1:1883）。HA MQTT 集成
# 全局唯一、已由慧尖指向内置 :2022——为让两个插件"零配置改动"共存，内置
# broker 自动向 1883 搭**方向分离桥**（仅 z2m 生态主题，见 _bridge_on 内
# 红线注释；全量 both 桥实测 retained 乒乓风暴已禁用，gateway/# 跨桥因
# 匿名注入攻击链实锤被安全评审摘除）：z2m 的发现/状态经 in 注入内置
# broker → HA 可见；HA 的 z2m 控制命令经 out 送达官方 broker。
# 状态机：每 30s 对账一次——1883 在且无桥→写 conf 并由主自愈循环重启
# mosquitto（计划内重启：RUN_SECS>=60 时崩溃计数器归零，不触发
# MAX_MOSQUITTO_RESTARTS 防护）；1883 消失且桥在→删段重启。冷却 120s 防抖。
BRIDGE_MARKER="AUTO-COEXIST-BRIDGE"
MOSQ_CONF="/etc/mosquitto/mosquitto.conf"
# v1.6.26（第八轮审计 D-3）：共存桥总开关（默认开=保持 v1.6.24"零配置
# 共存"语义）。判据只认本机 :1883 LISTEN，宿主上任何第三方进程占该口都会
# 被当官方 broker 搭桥（out 腿送 z2m 控制命令、in 腿注入 discovery——桥
# 消息不受本地 ACL 约束）。给谨慎用户一个显式熔断：置 false 后不建新桥，
# 已存在的桥由对账循环自动拆除。
BRIDGE_ENABLED=$(bashio::config 'coexist_bridge_enabled')
# 官方 broker 侧桥凭据（可选，见桥块注释）。净化防换行注入——加载项配置
# 值直通 heredoc 会允许在 mosquitto.conf 里伪造任意配置行
BRIDGE_PEER_USER=$(bashio::config 'coexist_official_user')
BRIDGE_PEER_PASSWORD=$(bashio::config 'coexist_official_password')
BRIDGE_PEER_USER=$(printf '%s' "${BRIDGE_PEER_USER}" | tr -cd 'A-Za-z0-9_-')
BRIDGE_PEER_PASSWORD=$(printf '%s' "${BRIDGE_PEER_PASSWORD}" | tr -d '\n\r')
# v1.6.26（第八轮审计 D-2）：凭据只在**双非空**时成对输出——旧实现 password
# 行按 USER 非空门控，"只填用户名"会展开 `password `（空值行），mosquitto
# 2.x conf__parse_string 对空值直接判 Error 拒载**整份 conf**（上游 v2.0.22
# conf.c 实锤）→ 内置 broker 拒启、加载项全挂。半填形态降级为匿名桥并大声
# 警告（对端 7.x 强制认证时桥不通，但慧尖自身服务无恙）。
BRIDGE_CREDS=""
if [ -n "${BRIDGE_PEER_USER}" ] && [ -n "${BRIDGE_PEER_PASSWORD}" ]; then
    BRIDGE_CREDS="username ${BRIDGE_PEER_USER}
password ${BRIDGE_PEER_PASSWORD}"
elif [ -n "${BRIDGE_PEER_USER}" ] || [ -n "${BRIDGE_PEER_PASSWORD}" ]; then
    echo "[共存] 警告: coexist_official_user/password 须成对填写（当前只填了一边）→ 桥按匿名方式连接"
fi
OFFICIAL_PORT_HEX=$(printf '%04X' 1883)
_bridge_peer_up() {
    # 复用本脚本的 /proc/net/tcp 扫描法（busybox 环境零进程开销）：
    # 本地任意地址 LISTEN(0A) 端口 :1883
    awk -v pat=":${OFFICIAL_PORT_HEX}$" 'FNR>1 && $2 ~ pat && $4=="0A" {found=1} END{exit !found}' \
        /proc/net/tcp /proc/net/tcp6 2>/dev/null
}
_bridge_present() { grep -q "BEGIN ${BRIDGE_MARKER}" "${MOSQ_CONF}" 2>/dev/null; }
_bridge_on() {
    _bridge_present && return 0
    cat >> "${MOSQ_CONF}" <<EOF

# BEGIN ${BRIDGE_MARKER}（自动管理——1883 官方 broker 出现/消失时对账同步）
connection core_mosquitto
address 127.0.0.1:1883
# 方向分离桥（真栈风暴实证禁 both：mosquitto 2.0.22 桥对 both 模式无
# origin 防环，retained 消息两 broker 间乒乓自激复制）——
# out：HA 侧经内置 broker 发的 z2m 控制命令送出去；
# in：z2m 状态 + MQTT discovery 配置注入内置 broker 供 HA 消费。
# homeassistant/# 只进不出（HA 不发 discovery 主题，且防慧尖网关侧
# 心跳主题回灌官方 broker 干扰其用户）。
notifications false
# 官方加载项 7.x 起 go-auth 强制认证（源码实锤 addons/mosquitto gtpl，
# allow_anonymous 时代终结）——匿名桥会被对端拒绝（实测：桥不通但慧尖
# 自身服务无恙）。在插件配置填官方 broker 有效凭据即带认证建桥（实测
# 端到端穿透）；留空=匿名，兼容老版官方/customize 关认证场景。
# v1.6.26（D-2）：改由 BRIDGE_CREDS 预构造（双非空才成对输出，杜绝
# `password ` 空值行拒载整份 conf，见 §7b 头部注释）。
${BRIDGE_CREDS}
topic zigbee2mqtt/# out 1
topic zigbee2mqtt/# in 1
topic homeassistant/# in 1
# 禁 gateway/# 跨桥（v1.6.24 安全评审定案，实测取证）：in 腿等于把对端
# 信任域直连慧尖执行器——匿名@1883 publish gateway/{sn}/req 可穿桥达固件
# 实现未认证物理开窗。慧尖流量隔离在本 broker；若 HA 的 MQTT 条目被其他
# broker 抢走，慧尖需人工把条目改回 127.0.0.1:2022（README 已知边界）。
# END ${BRIDGE_MARKER}
EOF
    # v1.6.26（第八轮审计 D-5）：桥段刚写入即含对端凭据（若配置了），与
    # passwd/acl 同口径收紧 600——mosquitto 以 root 读 conf（进程内降权后
    # 不再回读），容器内 nginx worker/mosquitto 用户等低权进程不再可读。
    chmod 600 "${MOSQ_CONF}" 2>/dev/null || true
    echo "[共存] 检测到官方 Mosquitto(:1883) → 自动写入桥接，重启 broker 生效"
    kill -TERM "$(cat /run/mosquitto.pid 2>/dev/null)" 2>/dev/null || true
}
_bridge_off() {
    _bridge_present || return 0
    sed -i "/# BEGIN ${BRIDGE_MARKER}/,/# END ${BRIDGE_MARKER}/d" "${MOSQ_CONF}"
    echo "[共存] 官方 Mosquitto(:1883) 已消失 → 移除桥接，重启 broker 生效"
    kill -TERM "$(cat /run/mosquitto.pid 2>/dev/null)" 2>/dev/null || true
}

PORT_HEX=$(printf '%04X' "${MQTT_PORT}")
BRIDGE_TICK=0
(
    while true; do
        # v1.6.24 共存桥对账：每 30s（6×5s tick）一次；动作后冷却 120s，
        # 防官方 Mosquitto 安装中/重启期端口闪现闪无导致 broker 连环重启
        BRIDGE_TICK=$((BRIDGE_TICK + 1))
        if [ $((BRIDGE_TICK % 6)) -eq 0 ]; then
            LAST_TS=$(cat /run/bridge_last_ts 2>/dev/null || echo 0)
            # 净化（审计定案）：含非数字的垃圾会让 $((...)) 语法错误杀死
            # 整个巡检子 shell（v1.6.3 静默死同族故障）；空/非数字按 0 处理
            # 并留意 0 开头会走八进制坑——一律归 0
            case "${LAST_TS}" in
                ''|*[!0-9]*) LAST_TS=0 ;;
            esac
            NOW_TS=$(date +%s)
            if [ $((NOW_TS - LAST_TS)) -ge 120 ] 2>/dev/null; then
                # 仅"真实状态迁移"（peer 在而无桥 / 桥在而无 peer）才动作并
                # 记录冷却时间戳——noop tick 不续期，否则冷却永不过期、
                # 桥拆不掉（本行缺陷为自查实证发现，冷却语义=两次"重启动作"
                # 的最小间隔）
                # v1.6.26（D-3）：coexist_bridge_enabled=false 时短路 peer 判定
                # → 走 else 分支拆已有桥，且不再建新桥
                if [ "${BRIDGE_ENABLED}" = "true" ] && _bridge_peer_up; then
                    if ! _bridge_present; then
                        _bridge_on || true
                        echo "${NOW_TS}" > /run/bridge_last_ts
                    fi
                else
                    if _bridge_present; then
                        _bridge_off || true
                        echo "${NOW_TS}" > /run/bridge_last_ts
                    fi
                fi
            fi
        fi
        # 单次扫描同时得到 ESTABLISHED 连接数与 LISTEN 套接字数
        CONN_STATS=$(awk -v pat=":${PORT_HEX}$" 'FNR>1 && $2 ~ pat {
                            if ($4 == "01") c++; else if ($4 == "0A") l++
                        } END { print c+0, l+0 }' \
                        /proc/net/tcp /proc/net/tcp6 2>/dev/null || echo "0 0")
        CLIENTS=${CONN_STATS% *}
        LISTENERS=${CONN_STATS#* }
        # tmp+mv 原子替换：jq>file 先截断，nginx 高轮询下可能读到半截/空文件。
        # v1.6.4：写失败必须发声——否则 status.json 冻结在最后成功值，
        # broker 死后页面永远"运行中"（v1.6.2 硬编码 200 的隐蔽复刻）
        jq -n --argjson c "${CLIENTS:-0}" \
            '{clients:$c, connected:$c, updated:(now|todate)}' \
            > /usr/share/nginx/html/broker_status.json.tmp 2>/dev/null \
            && mv /usr/share/nginx/html/broker_status.json.tmp /usr/share/nginx/html/broker_status.json 2>/dev/null \
            || echo "[警告] broker_status.json 写入失败（检查 /usr/share/nginx/html 可写性/磁盘）"
        # 存活判据：MQTT 端口有 LISTEN 套接字（比 PID 检查更真实——僵而不死时端口已丢）
        if [ "${LISTENERS:-0}" -gt 0 ] 2>/dev/null; then
            RUNNING=true
        else
            RUNNING=false
        fi
        PID_NOW=$(cat /run/mosquitto.pid 2>/dev/null || echo 0)
        # v1.6.21: 默认密码提示位——与 config.yaml schema default 同串（交叉
        # 引用见 const.py DEFAULT_MQTT_PASSWORD 注释）；Web UI 概览据此提示改密
        DP_IS_DEFAULT=false
        if [ "${PASSWORD}" = "huijian2022" ]; then DP_IS_DEFAULT=true; fi
        # v1.6.24 共存桥状态位（诊断/支持用，无展示面——产品定案同凭据提示）
        # 必须 if 形：`x && y` 短路 false 的行尾返回值会触发本 subshell 继承
        # 的 set -e（v1.6.3 :343 起生效），巡检循环会被静默杀死（v1.6.4 的
        # || echo 防御与 v1.6.2 假状态是同族教训）
        BRIDGE_ON_F=false
        if _bridge_present; then BRIDGE_ON_F=true; fi
        PEER_UP_F=false
        if _bridge_peer_up; then PEER_UP_F=true; fi
        jq -n --argjson r "${RUNNING}" --argjson p "${PID_NOW:-0}" --argjson l "${LISTENERS:-0}" --argjson pt "${MQTT_PORT}" --argjson dp "${DP_IS_DEFAULT}" --argjson bc "${BRIDGE_ON_F}" --argjson pu "${PEER_UP_F}" \
            '{status:(if $r then "running" else "stopped" end), running:$r, broker:"mosquitto", port:$pt, pid:$p, listeners:$l, mqtt_password_is_default:$dp, coexist_bridge:$bc, official_peer_up:$pu, updated:(now|todate)}' \
            > /usr/share/nginx/html/status.json.tmp 2>/dev/null \
            && mv /usr/share/nginx/html/status.json.tmp /usr/share/nginx/html/status.json 2>/dev/null \
            || echo "[警告] status.json 写入失败——页面状态将冻结，重点排查"
        sleep 5
    done
) &

# ---------- 8. 后台启动 mosquitto，验证 MQTT 协议可用后再继续 ----------
echo "[运行] Broker 以前台模式运行..."

# v1.6.24：官方 Mosquitto 若已在运行，先写桥再接管启动（免一次计划内重启）
# v1.6.26（D-3）：同样受 coexist_bridge_enabled 总开关约束
if [ "${BRIDGE_ENABLED}" = "true" ] && _bridge_peer_up; then
    # || true：初启路径在 set -e 主 shell、mosquitto 首启之前——写失败
    # （盘满等）不能杀死整个 run.sh（比循环死重得多），留给 tick 对账重试
    _bridge_on || true
    date +%s > /run/bridge_last_ts 2>/dev/null || true
fi

# 先后台启动 mosquitto
mosquitto -c /etc/mosquitto/mosquitto.conf &
MOSQUITTO_PID=$!
echo "${MOSQUITTO_PID}" > /run/mosquitto.pid
echo "[运行] Mosquitto PID: ${MOSQUITTO_PID}"

# 等待 Mosquitto 进程启动（最多5秒）
MOSQUITTO_READY=false
for i in 1 2 3 4 5; do
    if ! kill -0 "${MOSQUITTO_PID}" 2>/dev/null; then
        echo "[错误] Mosquitto 进程已退出（PID=${MOSQUITTO_PID}）"
        echo "[诊断] 检查密码文件与 ACL 文件是否存在/非空（不打印内容，防哈希入日志）"
        [ -s /etc/mosquitto/passwd ] && echo "  passwd: 存在且非空" || echo "  passwd: 缺失或为空 ← 重点排查"
        [ -s /etc/mosquitto/acl ] && echo "  acl: 存在且非空" || echo "  acl: 缺失或为空 ← 重点排查"
        exit 1
    fi
    # 尝试 TCP 连接到 localhost:${MQTT_PORT}
    # v1.6.3：/dev/tcp 是 bashism，base 镜像的 sh（BusyBox ash）不支持，
    # 旧写法恒失败、就绪检查形同虚设——改用 bash -c
    # v1.6.9：端口改用 $MQTT_PORT（原硬编码 2022 与配置变量不一致）
    if timeout 1 bash -c "echo >/dev/tcp/127.0.0.1/${MQTT_PORT}" 2>/dev/null; then
        MOSQUITTO_READY=true
        break
    fi
    sleep 1
done

if [ "${MOSQUITTO_READY}" = "true" ]; then
    echo "[OK] Mosquitto TCP 端口 ${MQTT_PORT} 已就绪"
else
    echo "[警告] Mosquitto TCP 端口5秒内未就绪，继续启动..."
fi

# 等待 Mosquitto MQTT 协议响应（用 mosquitto_pub 测试）
if command -v mosquitto_pub >/dev/null 2>&1; then
    if mosquitto_pub -h 127.0.0.1 -p "${MQTT_PORT}" -u "${USERNAME}" -P "${PASSWORD}" -t "test/ping" -m "ok" 2>/dev/null; then
        echo "[OK] Mosquitto MQTT 协议验证通过（mosquitto_pub 成功）"
    else
        echo "[警告] mosquitto_pub 测试失败（broker 可能仍在初始化或密码配置有误）"
        # v1.6.3：只打印用户名，不 head 完整哈希行
        # v1.6.4：cut|tr||echo 的兜底是死代码（管道 rc 取 tr，恒 0）——改显式存在性判断
        if [ -f /etc/mosquitto/passwd ]; then
            echo "[诊断] /etc/mosquitto/passwd 用户: $(cut -d: -f1 /etc/mosquitto/passwd | tr '\n' ' ')"
        else
            echo "[诊断] /etc/mosquitto/passwd 文件不存在 ← 重点排查"
        fi
        echo "[诊断] mosquitto.conf 内容（凭据已脱敏，v1.6.26 第八轮审计 D-4——与 v1.6.3 'passwd 只 cut 用户名防哈希入日志'定案同口径；桥块含对端 username/password，此前全文入 Supervisor 日志）:"
        sed -E 's/^([[:space:]]*)(password|remote_password|username|remote_username)([[:space:]]+).*/\1\2 ***REDACTED***/' \
            /etc/mosquitto/mosquitto.conf 2>/dev/null | sed 's/^/  /'
    fi
fi

# 等待 Mosquitto 退出并自愈：
# mosquitto 退出后 trap cleanup_mdns 自动清理 mDNS 后台进程相关资源。
# Bug2 修复：限制连续重启次数。mosquitto 因配置损坏（passwd/acl 格式错误等）
# 反复崩溃时，无限重启会刷屏且无助于恢复；连续 MAX_MOSQUITTO_RESTARTS 次
# 崩溃后退出并保留现场（日志/配置），便于排查。
# C3 修复（v1.6.3）：主循环区 set -e 是生效的（343 行恢复），而崩溃退出时
# `wait` 返回非零——旧写法 `wait ...; EXIT_CODE=$?` 的第二条语句永远执行不到，
# 脚本在到达重启逻辑前就被 set -e 杀死，"自愈"实为死代码。改为 `|| EXIT_CODE=$?`。
# 计数重置（v1.6.3）：旧实现计数只增不减，进程生命周期内累计 5 次崩溃
# （哪怕间隔数月）即永久放弃；现按"连续"语义——上次运行满 60 秒即视为
# 已恢复稳定，计数清零，符合 MAX_MOSQUITTO_RESTARTS 的设计初衷。
MAX_MOSQUITTO_RESTARTS=5
MOSQUITTO_RESTART_COUNT=0
while true; do
    WAIT_START=$(date +%s)
    EXIT_CODE=0
    wait "${MOSQUITTO_PID}" 2>/dev/null || EXIT_CODE=$?
    RUN_SECS=$(( $(date +%s) - WAIT_START ))
    if [ "${RUN_SECS}" -ge 60 ]; then
        MOSQUITTO_RESTART_COUNT=0
    fi
    MOSQUITTO_RESTART_COUNT=$((MOSQUITTO_RESTART_COUNT + 1))
    if [ "${MOSQUITTO_RESTART_COUNT}" -gt "${MAX_MOSQUITTO_RESTARTS}" ]; then
        echo "[错误] Mosquitto 连续退出 ${MAX_MOSQUITTO_RESTARTS} 次（最近 exit code: ${EXIT_CODE}），停止重启"
        echo "[诊断] 请检查 /etc/mosquitto/mosquitto.conf、passwd、acl 配置后手动重启插件"
        exit 1
    fi
    echo "[运行] Mosquitto 已退出 (exit code: ${EXIT_CODE}，本次运行 ${RUN_SECS}s)，5 秒后重启 (${MOSQUITTO_RESTART_COUNT}/${MAX_MOSQUITTO_RESTARTS})..."
    sleep 5
    mosquitto -c /etc/mosquitto/mosquitto.conf &
    MOSQUITTO_PID=$!
    echo "${MOSQUITTO_PID}" > /run/mosquitto.pid
    echo "[运行] Mosquitto 已重启 (PID: ${MOSQUITTO_PID})"
done
