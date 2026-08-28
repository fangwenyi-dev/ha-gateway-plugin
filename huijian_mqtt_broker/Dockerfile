ARG BUILD_ARCH
# 基础镜像使用 HA 官方 base 镜像（不固定 Alpine 版本号，避免 tag 不存在导致安装失败）
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base:latest

# 安装依赖包（v1.6.4 分层重构：此前 apk+pip 挤在同一个 RUN，任何一侧
# 小改动都令 pip 走网络的层全量重建——Supervisor 源码安装表现为
# "一直安装不成功"。拆层后各层独立命中缓存。
# 注意：RUN 续行体内不能插 # 注释行——sh 会把 `\`+注释行的线拼断，
# 后续包名/命令脱链成为独立命令造成构建期事故）
# - mosquitto/mosquitto-clients: MQTT broker + 客户端工具
# - curl/jq: HA API 调用
# - nginx: Ingress Web UI
# - python3/py3-pip: 运行 zeroconf mDNS 广播脚本
# - openssl: base 镜像只有 libssl 库没有 CLI，run.sh 密码哈希兜底需要
RUN apk add --no-cache \
    mosquitto \
    mosquitto-clients \
    curl \
    jq \
    nginx \
    python3 \
    py3-pip \
    openssl

# zeroconf: 纯 Python mDNS 库，不依赖 D-Bus/avahi（HAOS 端口冲突定案）。
# pip 多级回退：pypi 直连 → 清华 → 阿里（--timeout 防挂死，国内链路慢时
# 快速失败立刻切镜像源）。首条不带 --break-system-packages 是 alpine
# EXTERNALLY-MANAGED 下秒败的兼容位，真实下载从第二条开始
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --timeout 30 --retries 2 -r /tmp/requirements.txt \
    || pip3 install --no-cache-dir --break-system-packages --timeout 30 --retries 2 -r /tmp/requirements.txt \
    || pip3 install --no-cache-dir --break-system-packages --timeout 60 -i https://pypi.tuna.tsinghua.edu.cn/simple -r /tmp/requirements.txt \
    || pip3 install --no-cache-dir --break-system-packages --timeout 60 -i https://mirrors.aliyun.com/pypi/simple -r /tmp/requirements.txt

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
