ARG BUILD_ARCH
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base:latest

# 安装依赖包
# - mosquitto/mosquitto-clients: MQTT broker + 客户端工具
# - curl/jq: HA API 调用
# - avahi/avahi-tools/dbus: mDNS 广播（需要 dbus 和 machine-id）
# - nginx: Ingress Web UI
# - net-tools/procps: 调试工具（netstat/ps）
RUN apk add --no-cache \
    mosquitto \
    mosquitto-clients \
    curl \
    jq \
    avahi \
    avahi-tools \
    avahi-compat-libdns_sd \
    dbus \
    dbus-libs \
    nginx \
    net-tools \
    procps \
    util-linux

# 创建 avahi/dbus 所需的目录和 machine-id
RUN mkdir -p /run/dbus /var/lib/dbus /etc/avahi && \
    echo "huijian" > /etc/machine-id && \
    cp /etc/machine-id /var/lib/dbus/machine-id 2>/dev/null || true

# 复制配置文件
COPY mosquitto.conf /etc/mosquitto/mosquitto.conf
COPY acl /etc/mosquitto/acl
COPY run.sh /run.sh
COPY auto_setup_mqtt.sh /auto_setup_mqtt.sh

# 复制慧尖网关集成代码
# 注意: /data 在运行时是 HA 挂载的持久化卷，会覆盖镜像内容
#       所以同时复制到 /usr/share 作为备份，run.sh 会从备份路径查找
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
    chmod +x /run.sh /auto_setup_mqtt.sh && \
    mkdir -p /run/nginx

CMD ["/run.sh"]
