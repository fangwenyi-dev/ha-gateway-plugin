ARG BUILD_ARCH
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base:latest

# 安装 mosquitto + curl + jq（用于自动配置 HA MQTT 集成）
RUN apk add --no-cache \
    mosquitto \
    mosquitto-clients \
    curl \
    jq

# 复制配置文件
COPY mosquitto.conf /etc/mosquitto/mosquitto.conf
COPY acl /etc/mosquitto/acl
COPY run.sh /run.sh
COPY auto_setup_mqtt.sh /auto_setup_mqtt.sh

# 创建持久化目录，设置权限
RUN mkdir -p /data/mosquitto && \
    chmod 755 /data/mosquitto && \
    chmod +x /run.sh /auto_setup_mqtt.sh

CMD ["/run.sh"]
