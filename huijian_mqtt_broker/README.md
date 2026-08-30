# 慧尖 LoRa 网关一体化插件

[![版本](https://img.shields.io/badge/version-1.6.11-blue)]()
[![HA Add-on](https://img.shields.io/badge/HA-Add--on-green)]()

慧尖开窗器 LoRa 网关的 Home Assistant 一体化插件。**内置 Mosquitto Broker + mDNS 自动发现 + 网关集成，安装一个插件即可获得全部能力**。

## 工作原理

```
LoRa 网关 (MQTT 客户端)
    │
    │ MQTT TCP → huijian.local:2022 (mDNS 自动发现)
    ▼
┌─────────────────────────────────────────────────┐
│ 慧尖 LoRa 网关一体化插件 (Docker, host_network)    │
│                                                 │
│  ┌─────────────────────────────────────────┐    │
│  │ Python zeroconf (mDNS)                  │    │
│  │ 广播 huijian.local + _mqtt._tcp        │    │
│  └─────────────────────────────────────────┘    │
│                                                 │
│  ┌─────────────────────────────────────────┐    │
│  │ Mosquitto Broker                        │    │
│  │ 监听 0.0.0.0:2022 (主机端口)            │    │
│  │ ACL 用户隔离：                           │    │
│  │   huijian → 网关协议主题                │    │
│  │   ha_mqtt → homeassistant/#            │    │
│  └─────────────────────────────────────────┘    │
│                                                 │
│  ┌─────────────────────────────────────────┐    │
│  │ 自动安装网关集成 + 自动配置 HA MQTT     │    │
│  └─────────────────────────────────────────┘    │
│                                                 │
│  ┌─────────────────────────────────────────┐    │
│  │ Ingress Web UI (nginx)                  │    │
│  │ 网关配对 / 子设备控制 / 一键升级        │    │
│  └─────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
    │
    │ HA MQTT 集成 (127.0.0.1:2022，自动配置)
    ▼
慧尖网关集成 → Cover / Button / Sensor / Number 实体
```

## 安装步骤

### 1. 添加插件仓库

HA → **设置 → 加载项 → 加载项商店 → 右上角 ⋮ → 仓库**，添加：

```
https://github.com/fangwenyi-dev/ha-gateway-plugin
```

### 2. 安装并启动

在加载项商店中找到「慧尖 LoRa 网关」，点击**安装**，然后点击**启动**。

**启动后自动完成：**
- ✅ Mosquitto Broker 启动，监听 `2022` 端口
- ✅ mDNS 广播 `huijian.local`，LoRa 网关自动发现
- ✅ ACL 用户隔离（网关用户 + HA MQTT 用户权限分离）
- ✅ HA MQTT 集成自动配置（连接 `127.0.0.1:2022`）
- ✅ 慧尖网关集成自动安装到 `custom_components`
- ✅ Web UI 可从侧边栏打开

### 3. 重启 HA

**首次安装必须重启 HA**，让自动安装的网关集成生效。

| 场景 | 需要重启 HA？ | 说明 |
|------|:---:|------|
| 首次安装插件 | ✅ | 集成代码首次部署 |
| 插件更新（集成代码有变更） | ✅ | 新版本集成代码需重启加载 |
| 插件更新（仅 addon 代码变更） | ❌ | 重启插件即可 |
| 插件重启 | ❌ | Broker 重启，集成保持运行 |

> **简单判断**：`custom_components/window_controller_gateway/` 下的 Python 文件有更新就需要重启 HA。

### 4. 配置 LoRa 网关

在 LoRa 网关的配置界面中填写：

| 字段 | 值 |
|------|-----|
| Broker 地址 | `huijian.local`（mDNS 自动发现）或 HA 的 IP |
| 端口 | `2022` |
| 用户名 | `huijian`（默认值，可在插件配置中修改） |
| 密码 | `huijian2022`（默认值，可在插件配置中修改） |

## 插件配置

在插件的「配置」标签页中可修改以下选项：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `username` | `huijian` | MQTT 用户名 |
| `password` | `huijian2022` | MQTT 密码 |
| `auto_setup_ha_mqtt` | `true` | 启动时自动配置 HA MQTT 集成 |
| `install_integration` | `true` | 启动时自动安装网关集成到 `custom_components` |

> **MQTT 端口**固定为 `2022`（`config.yaml` 定义，host_network 模式直接暴露在主机），避免与 HA 官方 Mosquitto broker 的 `1883` 端口冲突，两个 broker 可共存。

> **⚠️ 安全提醒**：默认密码仅供初次测试使用，**请在生产环境中务必修改默认密码**。

> **备份数据**：网关持久化数据存储在 HA 配置目录的 `window_controller_gateway_data.json` 中，升级时会自动备份恢复。建议定期备份 HA 配置目录。

## 设备类型

### 5005 设备（支持内倒）
- 开 / 关 / 停
- 位置滑块 0–100%
- 速度 / 力度滑块
- 内倒按钮（command `"a"`, value `200`）
- 内倒模式 / 平开模式切换
- 重命名 / 移除

### 非 5005 设备
- 开 / 关 / 停
- 位置滑块 0–100%
- 速度 / 力度滑块
- 重命名 / 移除

## 常见问题

### Q: 启动后日志显示 "Address in use"？

主机端口 2022 已被其他服务占用，请检查并释放该端口。

### Q: LoRa 网关连接的 Broker 地址填什么？

填 `huijian.local`（mDNS 自动发现）或 HA 的 IP 地址。插件内置 Python zeroconf，会广播 `huijian.local` 主机名，网关可自动发现并连接。

### Q: 可以和 HA 官方 Mosquitto broker 共存吗？

可以。本插件使用端口 `2022`，不会与官方 broker 的 `1883` 冲突，两个 broker 可同时运行。

### Q: 如何升级插件？

在插件 Web UI 侧边栏页面点击「检查更新」→「一键升级」。也可以在 **设置 → 加载项 → 慧尖 LoRa 网关** 中手动更新。升级后需重启插件，集成代码有变更时还需重启 HA。

### Q: 升级后数据会丢失吗？

不会。持久化数据存储在 HA 配置目录，升级时自动备份恢复。v1.3.2 起增加了 `.bak` 备份机制，JSON 损坏时可自动恢复。

## 更新日志

### v1.6.11 (2026-08-30)
- 第三轮审计修复：迟到/非请求 003 不再掐掉当前配对会话（会话退出限定发起方记账）
- device_manager.cleanup 快照迭代（防 done 回调收缩列表跳项，任务终态异常必被消费）
- publish 失败路径补 gateway_status("offline")（与全部 connected=False 路径对齐）
- 消息去重时间轴换 monotonic；config_flow 连接测试 mock 补齐 allocate_device_number

### v1.6.10 (2026-08-30)
- 审计批2+3（10 修 1 澄清）：二次配对卡死根治（abort 助手）、transfer/check_status/migrate
  假成功收口、silentRefresh 阻断回归自修、ingress 模板同步、绑定成功状态恢复、
  Web 全 24 请求点 fetchT 超时封装 + 刷新防重入、transfer 后置失败可见化、number 簿记不回退

### v1.6.9 (2026-08-29)
- **修复（假成功根治）**：start_pairing 失败被吞返回 200、set_position
  fire-and-forget 吞异常、cover 开/关/停与 button/配对按钮不查发送结果——
  命令未送达时全部如实报错（服务抛 ServiceValidationError，实体抛
  HomeAssistantError）
- **修复**：Web 无感刷新补网关级增删检测（此前只检测设备，第二台网关需手动刷新）
- **修复**：run.sh `/api/ha/` 代理补 no-store；就绪探测端口改用 `$MQTT_PORT`
- **加固**：CI ghcr 包可见性探测失败改为阻断发布（原仅警告会掩盖"装不上"）；
  base_entity 生命周期链补 super()；静默更新检查三重限流防 GitHub 匿名限流
- **文档**：README 更新日志收敛到仓库根 CHANGELOG.md 单一真源

完整历史见仓库根 [CHANGELOG.md](../CHANGELOG.md)。
