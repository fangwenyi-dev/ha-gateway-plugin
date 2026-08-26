ARG BUILD_ARCH
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base:latest

# 安装 mosquitto + curl + jq + avahi（mDNS 广播 huijian.local）
# 注意: Alpine 中 avahi 包名是 "avahi"（不是 Debian 的 "avahi-daemon"）
#       avahi-tools 在 Alpine community 仓库中，需要一并安装
RUN apk add --no-cache \
    mosquitto \
    mosquitto-clients \
    curl \
    jq \
    avahi \
    avahi-tools \
    dbus

# 复制配置文件
COPY mosquitto.conf /etc/mosquitto/mosquitto.conf
COPY acl /etc/mosquitto/acl
COPY run.sh /run.sh
COPY auto_setup_mqtt.sh /auto_setup_mqtt.sh

# 复制慧尖网关集成代码（启动时自动安装到 HA custom_components）
COPY custom_components /data/custom_components

# 创建持久化目录，设置权限
RUN mkdir -p /data/mosquitto && \
    chmod 755 /data/mosquitto && \
    chmod +x /run.sh /auto_setup_mqtt.sh

CMD ["/run.sh"]
