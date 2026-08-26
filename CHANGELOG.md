# 变更日志

所有版本变更记录在此文件中。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [1.0.9] - 2026-08-26

### 修复（关键）
- **端口 1883 冲突根因修复**：移除 `host_network: true`，改用 Docker 端口映射，彻底避免与 HA core-mosquitto 或其他服务端口冲突
- **mosquitto 文件权限警告**：passwd 和 acl 文件权限改为 `0700`（mosquitto 2.x 要求）
- **auto_setup_mqtt.sh**：broker 地址从 `127.0.0.1` 改为 `172.30.32.1`（Docker 网桥网关地址），适配非 host_network 模式

### 变更
- **移除 mDNS/avahi**：不再使用 `host_network`，avahi 无法在容器内广播到局域网，移除相关依赖
- **移除 mdns_hostname 配置项**：LoRa 网关使用 HA 的 IP 地址连接
- Dockerfile 精简：移除 avahi/dbus/net-tools/procps 包
- 插件版本号 1.0.8 → 1.0.9
- 集成版本保持 1.4.4

## [1.0.8] - 2026-08-26

### 修复
- 端口 1883 冲突检测
- avahi-daemon 启动修复（machine-id）

## [1.0.7] - 2026-08-26

### 修复
- Mosquitto 启动流程重写
- Nginx 配置动态生成
- Web UI 动态化
- GitHub Actions 自动 Release

## [1.0.5] - 2026-08-25

### 新增
- Ingress Web UI
- 侧边栏面板
- 动态 ACL
- 自动安装集成
- 自动配置 MQTT 集成

## [1.0.0] - 2026-08-20

### 初始版本
- 慧尖 LoRa 网关一体化 HA 插件
