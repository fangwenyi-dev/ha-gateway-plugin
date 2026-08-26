ARG BUILD_ARCH
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base:latest

# 安装 mosquitto + curl + jq + avahi + nginx（mDNS 广播 + Ingress Web UI）
# 注意: Alpine 中 avahi 包名是 "avahi"（不是 Debian 的 "avahi-daemon"）
RUN apk add --no-cache \
    mosquitto \
    mosquitto-clients \
    curl \
    jq \
    avahi \
    avahi-tools \
    dbus \
    nginx

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
COPY ingress.conf /etc/nginx/http.d/ingress.conf
COPY www/ /usr/share/nginx/html/

# 创建持久化目录，设置权限
RUN mkdir -p /data/mosquitto && \
    chmod 755 /data/mosquitto && \
    chmod +x /run.sh /auto_setup_mqtt.sh && \
    mkdir -p /run/nginx

CMD ["/run.sh"]
