# 变更日志

所有版本变更记录在此文件中。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [1.0.7] - 2026-08-26

### 修复（关键）
- **Mosquitto 启动崩溃**：重写启动流程，修复 `pkill` + `exec` 之间的端口 TIME_WAIT 竞态导致 mosquitto 无法绑定 1883 端口的问题
- **Nginx 配置注入**：改用 heredoc 在 `run.sh` 中动态生成 `ingress.conf`，直接写入 `SUPERVISOR_TOKEN`，不再用 `sed` 替换（更可靠）
- **集成代码查找顺序**：优先从 `/usr/share` 备份路径查找（`/data` 被卷覆盖后仍可工作）

### 新增
- **Web UI 动态化**：侧边栏界面支持网关配对、子设备控制（开/关/停/位置滑块/内倒平开）
- **状态实时显示**：网关在线状态、子设备位置/电压/开闭状态实时显示
- **版本检查/更新**：Web UI 新增「检查更新」按钮，从 GitHub API 获取最新 Release 并对比版本
- **Nginx HA API 代理**：通过 `/api/ha/` 代理 HA Supervisor API，前端无需 token
- **GitHub Actions 自动 Release**：推送代码后自动构建镜像、发布多架构 manifest、创建 GitHub Release

### 变更
- 插件版本号 1.0.6 → 1.0.7
- 集成版本保持 1.4.4

## [1.0.6] - 2026-08-26

### 修复
- Mosquitto 启动改用前台测试启动模式
- 持久化目录权限修复
- 日志输出改为 `log_type all`

## [1.0.5] - 2026-08-25

### 新增
- Ingress Web UI（Nginx 静态页面）
- 侧边栏显示「慧尖网关」面板
- 动态生成 ACL 文件
- 自动安装网关集成到 `custom_components`
- 自动配置 HA MQTT 集成（Supervisor API）
- mDNS 广播（Avahi）

## [1.0.4] - 2026-08-24

### 修复
- 仓库识别错误：`repository.yaml` 注释在 `---` 之前导致 HA 报错
- Alpine 镜像中 `avahi-daemon` 包名改为 `avahi`
- `/data` 目录被挂载卷覆盖导致集成代码丢失，改为同时复制到 `/usr/share`
- Mosquitto 无法读取 root 权限密码文件，执行 `chown mosquitto:mosquitto`

## [1.0.0] - 2026-08-20

### 初始版本
- 慧尖 LoRa 网关一体化 HA 插件
- 内置 Mosquitto Broker
- 内置网关集成代码（自动安装）
