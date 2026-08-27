# 慧尖 HA 网关插件仓库

慧尖开窗器 LoRa 网关的 Home Assistant 一体化插件。**安装一个插件即可获得全部能力**，无需额外安装集成。

## 可用插件

| 插件 | 版本 | 说明 |
|------|------|------|
| [慧尖 LoRa 网关](./huijian_mqtt_broker/) | v1.3.2 | 内置 Mosquitto Broker + mDNS 广播 + 网关集成，安装即用 |

## 安装方法

1. 在 HA 中打开 **设置 → 加载项 → 加载项商店 → ⋮ → 仓库**
2. 添加仓库地址：`https://github.com/fangwenyi-dev/ha-gateway-plugin`
3. 在加载项商店中找到「慧尖 LoRa 网关」并安装
4. 点击启动 — 全部自动完成：
   - ✅ Mosquitto broker 启动，监听 2022 端口
   - ✅ mDNS 广播 `huijian.local`，LoRa 网关可自动发现
   - ✅ 密码文件自动生成（使用预设用户名密码）
   - ✅ HA MQTT 集成自动配置（连接到 172.30.32.1:2022）
   - ✅ 慧尖网关集成自动安装到 custom_components
5. **重启 HA**（首次安装必须，让自动安装的集成生效）
6. 重启后在 **设置 → 设备与服务 → 添加集成 → 搜索「慧尖」** 添加网关

### 什么时候需要重启 HA？

| 场景 | 需要重启 HA？ | 说明 |
|------|-------------|------|
| 首次安装插件 | ✅ 必须 | 集成代码首次部署到 custom_components，HA 需要重启加载 |
| 插件版本更新（集成代码有变更） | ✅ 必须 | 新版本集成代码需要重启 HA 才能生效 |
| 插件版本更新（仅 addon 代码变更） | ❌ 不需要 | 重启插件即可，集成代码未变 |
| 插件重启 | ❌ 不需要 | MQTT broker 重启，集成保持运行 |
| HA 重启后 | ❌ 不需要 | 集成代码已在 custom_components 中，HA 启动时自动加载 |

> **简单判断**：如果 `custom_components/window_controller_gateway/` 下的 Python 文件有更新，就需要重启 HA。如果是 `run.sh`、`mosquitto.conf` 等 addon 文件更新，只需重启插件。

## 一体化架构

```
LoRa 网关 (MQTT 客户端)
    │
    │ MQTT TCP → huijian.local:2022 (mDNS 自动发现)
    ▼
┌──────────────────────────────────────────────────┐
│ 慧尖 LoRa 网关一体化插件 (Docker 容器)             │
│                                                  │
│  ┌──────────────┐  ┌──────────────┐             │
│  │ Avahi mDNS   │  │ Mosquitto    │             │
│  │ 广播 .local  │  │ Broker :2022 │             │
│  └──────────────┘  └──────────────┘             │
│                                                  │
│  ┌────────────────────────────────────────────┐  │
│  │ 自动安装慧尖网关集成                        │  │
│  │ → 复制到 /homeassistant/custom_components  │  │
│  │ → Cover/Button/Sensor/Number 实体          │  │
│  │ → 设备管理/配对/迁移/服务                   │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  ┌────────────────────────────────────────────┐  │
│  │ 自动配置 HA MQTT 集成                       │  │
│  │ → 连接 172.30.32.1:2022                    │  │
│  │ → 预设凭据，无需手动填写                    │  │
│  └────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
    │
    │ HA MQTT 集成 (172.30.32.1:2022，自动配置)
    ▼
慧尖网关集成 (custom_components/window_controller_gateway)
    └→ Cover 实体（开/关/停窗户）
    └→ Button 实体（开启/暂停/关闭/内倒/配对/删除设备）
    └→ Sensor 实体（电池电压/窗户状态/网关在线）
    └→ Number 实体（开窗速度/力度滑动条）
    └→ 服务（配对/重命名/转移设备等）
```

## 与旧版分离方案的区别

| 对比项 | 旧版（分离安装） | 新版（一体化插件） |
|--------|-----------------|-------------------|
| 安装步骤 | 安装插件 + 通过 HACS 安装集成 | 只安装插件 |
| mDNS | 未实现，`huijian.local` 不可用 | ✅ avahi-daemon 广播 `huijian.local` |
| MQTT 集成 | 需手动配置 | ✅ 自动配置 |
| 网关集成 | 需通过 HACS 安装 | ✅ 自动安装 |
| 左侧导航栏 | 无（只有加载项页面） | ✅ 有设备实体入口 |
| 可视化配置 | 仅 broker 配置 | ✅ broker + 集成 config_flow |

## 更新日志

### v1.3.2 (2026-08-27)
- **P1 修复**：18 处 async 操作补全 await，修复删除设备/重命名/转移后实体残留
- **P1 修复**：persist.py 添加 .bak 备份恢复，JSON 损坏时自动恢复
- **P1 修复**：device_manager.setup() 异常不再吞掉，改为 raise ConfigEntryNotReady
- **修复**：button.py _fix_entity_categories / _cleanup_unsupported_buttons 改为 async
- ⚠️ **需要重启 HA**（集成代码有更新）

### v1.3.1 (2026-08-27)
- 修复 Mosquitto 启动崩溃问题
- Web UI 新增网关配对、子设备控制、状态显示
- Web UI 新增版本检查/更新功能
- MQTT broker 自动配置修复
- ⚠️ **需要重启 HA**（集成代码有更新）

### v1.3.0 (2026-08-26)
- 一体化插件架构：内置 Mosquitto Broker + 网关集成
- mDNS 广播 `huijian.local`
- HA MQTT 集成自动配置
- Web UI 全面升级
- ⚠️ **需要重启 HA**（首次安装或集成代码有更新）

## ⚠️ 安全提醒

- **修改默认密码**：插件默认 MQTT 密码为 `huijian2022`，仅供初次测试。**生产环境请务必在插件配置中修改 `username` 和 `password`**。
- **备份数据**：升级或重新安装插件前，建议备份 HA 配置目录。网关持久化数据存储在 `window_controller_gateway_data.json` 中，升级时会自动备份恢复。
- **full_access 权限**：插件需要 `full_access: true` 权限以运行 avahi-daemon（mDNS 广播），这是 HA 插件系统的正常行为。
