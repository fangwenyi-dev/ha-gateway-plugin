# 变更日志

所有版本变更记录在此文件中。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [1.1.0] - 2026-08-26

### 修复（关键）
- **端口冲突彻底解决**：MQTT 端口改为可配置（`mqtt_port`），默认 1885，避免与 HA 官方 MQTT 集成的 1883 端口冲突
- **自动配置 MQTT 集成失败**：`curl` 改用 `-s`（去掉 `-f`），不再在 HTTP 错误时返回空字符串；输出 HTTP 状态码和完整响应体便于诊断
- **mosquitto.conf 动态端口**：配置文件中用 `__MQTT_PORT__` 占位符，`run.sh` 启动时用 `sed` 替换为实际端口

### 变更
- 新增 `mqtt_port` 配置项（默认 1885）
- `watchdog` 改为 `tcp://[HOST]:1885`
- Docker 端口映射改为 `1885:1885`
- 插件版本号 1.0.9 → 1.1.0
- 集成版本保持 1.4.4

## [1.0.9] - 2026-08-26

### 修复
- 移除 `host_network: true`，使用 Docker 端口映射
- mosquitto 文件权限 0700
- 移除 mDNS/avahi 依赖

## [1.0.8] - 2026-08-26

### 修复
- 端口冲突检测
- avahi-daemon 修复

## [1.0.7] - 2026-08-26

### 修复
- Mosquitto 启动流程重写
- Web UI 动态化
- GitHub Actions 自动 Release
