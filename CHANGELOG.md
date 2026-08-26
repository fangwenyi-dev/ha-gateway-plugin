# 变更日志

所有版本变更记录在此文件中。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [1.1.9] - 2026-08-26

### 修复（关键 - Web UI 状态检测三项全失败）
- **MQTT Broker 状态"无法连接"**：`/api/status` 由 nginx 直接返回，但 nginx 启动失败时不可达。添加 `nginx -t` 诊断输出，同时 `add_header` 添加 `always` 确保错误响应也带 Content-Type
- **网关集成/HA MQTT 检测"检测失败"**：nginx 代理到 Supervisor API 时 `supervisor` 主机名在 `full_access: true` 模式下可能无法解析。添加 `getent hosts` DNS 解析检测，失败时兜底为 Supervisor 固定 IP `172.30.32.2`
- **SUPERVISOR_TOKEN 为空导致 401**：`run.sh` 中 `HA_SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"` 可能为空（`with-contenv` 未正确加载时）。添加从 `/run/s6/container-env` 手动 source 的兜底逻辑，并输出 token 前缀确认

### 修复（关键 - 根本原因）
- **auto_setup_mqtt.sh HTTP 401 Unauthorized（最终修复）**：`run.sh` 通过 `SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}" /auto_setup_mqtt.sh &` 显式传递环境变量，但这个旧 token 会覆盖 `with-contenv` 从 `/run/s6/container-env` 加载的最新有效 token。改为不传递 `SUPERVISOR_TOKEN`，让 `auto_setup_mqtt.sh` 的 `with-contenv` shebang 自动加载正确 token
- **auto_setup_mqtt.sh Supervisor 主机解析兜底**：与 `run.sh` 一致，添加 `getent hosts` 检测，失败时使用 `172.30.32.2`

### 改进（前端容错）
- **`haApi` 函数不再 throw**：改为始终返回 `resp` 对象，由调用方检查 `resp.ok` 和 `resp.status`，可区分 401（认证失败）、502（代理连接失败）等不同错误
- **`checkServiceStatus` 错误分类**：401 显示"认证失败"（红色），代理连接异常显示"代理连接失败"（红色），其他 HTTP 错误显示状态码（黄色）
- **所有 `haApi` 调用方添加 `resp.ok` 检查**：`loadGateways`、`loadGatewayDevices`、`startPairing`、`controlDevice`、`controlDevicePosition` 均添加

## [1.1.8] - 2026-08-26

### 修复（关键 - 根本原因）
- **auto_setup_mqtt.sh HTTP 401 Unauthorized（根本原因）**：`#!/bin/bash` 不通过 `with-contenv`，无法从 `/run/s6/container-env` 加载最新的 `SUPERVISOR_TOKEN`，导致 token 虽有值但被 Supervisor 拒绝。恢复 `#!/usr/bin/with-contenv bashio` shebang，同时所有配置变量用 `${var:-default}` 避免 bashio `set -u` 报错
- **avahi-daemon 启动逻辑矛盾**：失败时仍输出"已启动"。修复为 `if/else` 逻辑，失败时提示改用 IP 地址
- **dbus 启动失败**：容器中缺少 `/run/dbus` 目录，Dockerfile 和 run.sh 均添加 `mkdir -p /run/dbus`

### 变更
- `auto_setup_mqtt.sh` shebang 从 `#!/bin/bash` 恢复为 `#!/usr/bin/with-contenv bashio`
- `run.sh` avahi-daemon 启动逻辑改为 `if/else`，添加 `mkdir -p /run/dbus` 和 `sleep 1` 等待 dbus
- Dockerfile 添加 `mkdir -p /run/dbus`
- **config.yaml 添加 `full_access: true`**：avahi-daemon + dbus 需要系统总线权限才能运行 mDNS 广播
- **前端 XSS 修复**：`renderGateway` / `renderDevice` 中所有用户可控字段（网关名称、设备名称、SN、ID）添加 `escapeHtml` 转义
- **Dockerfile 注释修复**：`dbbus` 拼写错误 → `dbus`
- **auto_setup_mqtt.sh 注释修复**：过时的 `127.0.0.1:1883` → `127.0.0.1:2022`
- **顶层 README.md 同步**：架构图和安装说明中的 1883 端口 → 2022，mDNS 描述对齐
- **前端连接信息更新**：MQTT 地址显示 `huijian.local:2022`，配置提示支持 mDNS
- **CI 质量门禁**：添加 lint job，检查 shell 语法、YAML/JSON 语法、版本号一致性
- **安全文档**：README 添加修改默认密码和备份提醒
- 版本号 1.1.7 → 1.1.8

## [1.1.7] - 2026-08-26

### 修复
- **auto_setup_mqtt.sh HTTP 401**：bashio shebang (`#!/usr/bin/with-contenv bashio`) 可能重新加载环境覆盖了 SUPERVISOR_TOKEN，改用 `#!/bin/bash` 普通解释器
- 新增调试日志：输出 SUPERVISOR_TOKEN 前缀确认是否有效传递

### 新增
- **mDNS 支持**：Dockerfile 添加 avahi + dbus 依赖，run.sh 添加 avahi-daemon 配置和启动，LoRa 网关可通过 `huijian.local` 发现 HA 主机

### 变更
- `auto_setup_mqtt.sh` shebang 从 bashio 改为普通 bash
- Dockerfile 添加 avahi、avahi-compat-libdns_sd、dbus 包
- README 更新 LoRa 网关地址说明，支持 `huijian.local`
- 版本号 1.1.6 → 1.1.7

## [1.1.6] - 2026-08-26

### 修复（关键 - 根本原因）
- **端口冲突彻底解决**：主机端口和容器端口统一改为 `2022`，完全不使用 1883/1885，与 HA 官方 Mosquitto broker 零冲突
- `config.yaml` `ports` 改为 `2022/tcp: 2022`
- `mosquitto.conf` 监听端口改为 `2022`
- `run.sh` 中 `MQTT_PORT` 和 `INTERNAL_PORT` 均改为 `2022`

### 变更
- 所有端口引用从 1885/1883 统一改为 2022
- 版本号 1.1.5 → 1.1.6

## [1.1.5] - 2026-08-26

### 修复（关键 - 根本原因）
- **端口 1883 冲突（根本原因）**：`config.yaml` 中 `services: - mqtt:provide` 导致 HA Supervisor 自动将 1883 端口分配给插件，与官方 Mosquitto broker 的 1883 冲突。移除 `services: mqtt:provide`，插件不再向 HA 声明为 MQTT 服务提供者，HA MQTT 集成通过 auto_setup_mqtt.sh 手动配置连接到 172.30.32.1:1885

### 变更
- `config.yaml` 移除 `services: - mqtt:provide`
- 版本号 1.1.4 → 1.1.5

## [1.1.4] - 2026-08-26

### 修复（关键）
- **端口 1883 冲突**：移除 `mqtt_port` 可配置项，Docker 端口映射固定为 `1885:1883`（主机 1885 → 容器 1883），避免用户误配 `mqtt_port` 为 1883 与 HA 官方 Mosquitto 冲突
- **`mqtt_port` 与 `ports` 脱节**：之前 `mqtt_port` 配置项只影响显示和 auto_setup，不改变 Docker 实际端口映射，容易造成混淆

### 变更
- `config.yaml` 移除 `mqtt_port` 配置项和 schema
- `run.sh` 中 `MQTT_PORT` 固定为 1885，不再从 bashio::config 读取
- 版本号 1.1.3 → 1.1.4

## [1.1.3] - 2026-08-26

### 修复（关键）
- **auto_setup_mqtt.sh HTTP 401 Unauthorized**：`SUPERVISOR_TOKEN` 未显式传递给子进程，导致调用 HA Supervisor API 认证失败
- **README 端口信息过时**：文档中 LoRa 网关端口仍写 1883，实际应为 1885

### 变更
- `run.sh` 显式传递 `SUPERVISOR_TOKEN` 给 `auto_setup_mqtt.sh`
- `auto_setup_mqtt.sh` 中 `HA_TOKEN` 添加默认值防止 `set -u` 报错
- README 全部端口信息更新为 1885
- 版本号 1.1.2 → 1.1.3

## [1.1.2] - 2026-08-26

### 修复（关键）
- **Web UI「MQTT Broker无法连接」**：nginx ingress 配置了 `allow/deny` IP 限制，Ingress 模式下来源 IP 不固定导致 403，移除 IP 限制
- **Web UI「网关集成检测失败」「HA MQTT检测失败」**：默认 `ingress.conf` 缺少 `/api/ha/` 代理配置，添加 HA API 代理
- **Web UI「检查更新」无反应**：直接请求 `https://api.github.com` 被 Ingress iframe CSP 拦截，改为通过 nginx `/api/github/` 代理
- **auto_setup_mqtt.sh 崩溃**：`USERNAME: unbound variable` — bashio 的 `set -u` 导致子 shell 中未定义变量报错，为所有变量添加默认值

### 变更
- `run.sh` 中显式传递环境变量给 `auto_setup_mqtt.sh` 子进程
- `ingress.conf` 默认配置同步添加 `/api/ha/` 和 `/api/github/` 代理
- Web UI 新增 `updateConnectionInfo()` 从 `/api/status` 动态读取端口显示
- 版本号 1.1.1 → 1.1.2

## [1.1.1] - 2026-08-26

### 修复（关键）
- **端口映射架构修正**：`config.yaml` 端口映射改为 `1885:1883`（主机 1885 → 容器 1883），mosquitto 容器内固定监听 1883
- **auto_setup 检测修正**：broker 可达性检测用 `127.0.0.1:1883`（容器内），HA MQTT 集成连接用 `172.30.32.1:1885`（主机映射端口）
- **auto_setup 更新也输出 HTTP 状态码**：之前更新分支没有输出 HTTP 状态码，无法诊断失败原因

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
