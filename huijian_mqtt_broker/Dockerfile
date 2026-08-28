ARG BUILD_ARCH
# 基础镜像使用 HA 官方 base 镜像（不固定 Alpine 版本号，避免 tag 不存在导致安装失败）
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base:latest

# 安装依赖包
# - mosquitto/mosquitto-clients: MQTT broker + 客户端工具
# - curl/jq: HA API 调用
# - nginx: Ingress Web UI
# - python3/py3-pip: 运行 zeroconf mDNS 广播脚本
# - zeroconf: 纯 Python mDNS 库，不依赖 D-Bus/avahi-daemon，避免 HAOS 端口冲突
# 先复制 requirements.txt（pip install 需要用）
COPY requirements.txt /tmp/requirements.txt

# v1.6.4：显式装 openssl CLI——base 镜像只有 libssl 库没有命令行，
# run.sh 密码哈希的 mosquitto_passwd 兜底路径此前是死路（command not found 被吞）。
# 注意：RUN 续行体内不能插 # 注释行——sh 会把 `\`+注释行的线拼断，
# 后续包名/命令脱链成为独立命令造成构建期事故。
RUN apk add --no-cache \
    mosquitto \
    mosquitto-clients \
    curl \
    jq \
    nginx \
    python3 \
    py3-pip \
    openssl \
    && pip3 install --no-cache-dir -r /tmp/requirements.txt \
    || pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

# 复制 mDNS 广播脚本（纯 Python zeroconf，不依赖 avahi/D-Bus）
COPY mdns_publisher.py /usr/bin/mdns_publisher.py
RUN chmod +x /usr/bin/mdns_publisher.py

# 复制配置文件
COPY mosquitto.conf /etc/mosquitto/mosquitto.conf
COPY run.sh /run.sh

# 复制慧尖网关集成代码
# /usr/share：run.sh 集成安装/升级链的第一查找路径（生产实际使用）
# /data：运行时会被 HA 挂载的持久化卷覆盖，看似死层，但它是 run.sh
# INTEGRATION_SRC 回退链的第二路径（`for src in /usr/share/... /data/...`）——
# 不带卷挂载直接 docker run 调试镜像时 /usr/share 缺失则靠它兜底。
# v1.6.3 审查定论：保留勿删；构建体积已由 .dockerignore 排除 __pycache__/tests
COPY custom_components /usr/share/custom_components
COPY custom_components /data/custom_components

# 复制 Ingress Web UI
# ingress.conf 在 run.sh 启动时会动态重新生成（注入 SUPERVISOR_TOKEN）
COPY ingress.conf /etc/nginx/http.d/ingress.conf
COPY www/ /usr/share/nginx/html/

# 覆盖默认 nginx.conf，移除默认 server 块避免端口冲突
RUN echo 'user nginx;' > /etc/nginx/nginx.conf && \
    echo 'worker_processes auto;' >> /etc/nginx/nginx.conf && \
    echo 'error_log /dev/stderr warn;' >> /etc/nginx/nginx.conf && \
    echo 'pid /run/nginx.pid;' >> /etc/nginx/nginx.conf && \
    echo 'events { worker_connections 768; }' >> /etc/nginx/nginx.conf && \
    echo 'http {' >> /etc/nginx/nginx.conf && \
    echo '    include /etc/nginx/mime.types;' >> /etc/nginx/nginx.conf && \
    echo '    default_type application/octet-stream;' >> /etc/nginx/nginx.conf && \
    echo '    access_log /dev/stdout;' >> /etc/nginx/nginx.conf && \
    echo '    sendfile on;' >> /etc/nginx/nginx.conf && \
    echo '    keepalive_timeout 65;' >> /etc/nginx/nginx.conf && \
    echo '    include /etc/nginx/http.d/*.conf;' >> /etc/nginx/nginx.conf && \
    echo '}' >> /etc/nginx/nginx.conf

# 创建持久化目录，设置权限
RUN mkdir -p /data/mosquitto && \
    chmod 755 /data/mosquitto && \
    chmod +x /run.sh && \
    mkdir -p /run/nginx

CMD ["/run.sh"]
