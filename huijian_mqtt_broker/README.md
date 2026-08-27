# 慧尖 LoRa 网关一体化插件

[![版本](https://img.shields.io/badge/version-1.3.7-blue)]()
[![HA Add-on](https://img.shields.io/badge/HA-Add--on-green)]()

慧尖开窗器 LoRa 网关的 Home Assistant 一体化插件。**内置 Mosquitto Broker + 网关集成，安装一个插件即可获得全部能力**。

## 工作原理

```
LoRa 网关 (MQTT 客户器)
    │
    │ MQTT TCP → huijian.local:2022 (mDNS 自动发现)
    ▼
┌───────────────────────────────────────────────┐
│ 慧尖 LoRa 网关一体化插件 (Docker 容器, host_network) │
│                                               │
│  ┌──────────────────────────────────────┐    │
│  │ Avahi mDNS                          │    │
│  │ 广播 huijian.local + _mqtt._tcp     │    │
│  └──────────────────────────────────────┘    │
│                                               │
│  ┌──────────────────────────────────────┐    │
│  │ Mosquitto Broker                     │    │
│  │ 监听 0.0.0.0:2022 (直接暴露在主机)   │    │
│  │ 预设用户名/密码                      │    │
│  │ ACL: gateway/+/req, gateway/rpt_rsp │    │
│  └──────────────────────────────────────┘    │
│                                               │
│  ┌──────────────────────────────────────┐    │
│  │ 自动安装慧尖网关集成                  │    │
│  │ → 复制到 custom_components           │    │
│  │ → Cover/Button/Sensor/Number 实体    │    │
│  └──────────────────────────────────────┘    │
│                                               │
│  ┌──────────────────────────────────────┐    │
│  │ 自动配置 HA MQTT 集成                 │    │
│  │ → 连接 127.0.0.1:2022               │    │
│  │ → 预设凭据，无需手动填写             │    │
│  └──────────────────────────────────────┘    │
└───────────────────────────────────────────────┘
    │
    │ HA MQTT 集成 (127.0.0.1:2022，自动配置)
    ▼
慧尖网关集成 (custom_components/window_controller_gateway)
    └→ 通过 HA MQTT API 订阅 gateway/rpt_rsp, 发布 gateway/{sn}/req
    └→ 在 HA 中创建 Cover/Button/Sensor/Number 实体
```

## MQTT 主题协议

与慧尖网关集成 `const.py` 完全一致：

| 主题 | 方向 | 发布者 | 订阅者 |
|------|------|--------|--------|
| `gateway/{gateway_sn}/req` | HA → 网关 | HA MQTT 集成 | LoRa 网关 |
| `gateway/rpt_rsp` | 网关 → HA | LoRa 网关 | HA MQTT 集成 |

## 安装方法

### 1. 添加插件仓库

在 HA 的 **设置 → 加载项 → 加载项商店 → 右上角 ⋮ → 仓库**，添加：

```
https://github.com/fangwenyi-dev/ha-gateway-plugin
```

### 2. 安装插件

在加载项商店中找到「慧尖 LoRa 网关」，点击安装。

### 3. 启动插件

点击「启动」按钮。

**启动后自动完成：**
- ✅ Mosquitto broker 启动，监听 2022（host_network 模式直接暴露在主机）
- ✅ avahi-daemon 广播 `huijian.local` + `_mqtt._tcp` 服务（mDNS 自动发现）
- ✅ 密码文件自动生成（使用预设用户名密码）
- ✅ HA MQTT 集成自动配置（连接到 127.0.0.1:2022）
- ✅ 慧尖网关集成自动安装到 `custom_components`

### 4. 重启 HA

**首次安装必须重启 HA**，让自动安装的网关集成生效。后续插件更新时：

| 场景 | 需要重启 HA？ | 说明 |
|------|-------------|------|
| 首次安装插件 | ✅ 必须 | 集成代码首次部署，HA 需要重启加载 |
| 插件更新（集成代码有变更） | ✅ 必须 | 新版本集成代码需要重启 HA 才能生效 |
| 插件更新（仅 addon 代码变更） | ❌ 不需要 | 重启插件即可 |
| 插件重启 | ❌ 不需要 | MQTT broker 重启，集成保持运行 |

> **简单判断**：如果 `custom_components/window_controller_gateway/` 下的 Python 文件有更新，就需要重启 HA。

### 5. 配置 LoRa 网关

在 LoRa 网关的配置界面中填写：

| 字段 | 值 |
|------|-----|
| Broker 地址 | `huijian.local`（mDNS 自动发现）或 HA 的 IP 地址 |
| 端口 | `2022` |
| 用户名 | `huijian`（默认值，可在插件配置中修改） |
| 密码 | `huijian2022`（默认值，可在插件配置中修改） |

## 插件配置

在插件的「配置」标签页中可视化配置以下选项：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `username` | `huijian` | MQTT 用户名 |
| `password` | `huijian2022` | MQTT 密码 |
| `auto_setup_ha_mqtt` | `true` | 启动时自动配置 HA MQTT 集成 |
| `install_integration` | `true` | 启动时自动安装慧尖网关集成到 HA custom_components |

> **注意**：MQTT 端口固定为 `2022`（host_network 模式直接暴露在主机），在 `config.yaml` 中定义，不可在插件配置中修改。这样避免与 HA 官方 Mosquitto broker 的 1883 端口冲突，两个 broker 可以共存。

> **⚠️ 安全提醒**：默认密码 `huijian2022` 仅供初次测试使用。**请在生产环境中务必修改默认密码**，在插件「配置」标签页中修改 `username` 和 `password` 后重启插件生效。

> **备份数据**：卸载或重新安装插件会清除 `/data` 目录。网关集成持久化数据存储在 HA 配置目录的 `window_controller_gateway_data.json` 中，升级集成时会自动备份恢复。建议定期备份 HA 配置目录。

## 更新日志

### v1.4.9 (2026-08-27)
- **兼容性加固（HA 更新防护）**：
  - 删除遗留 API `homeassistant.helpers.discovery` 死导入（未来 HA 移除该模块会导致集成崩溃）
  - 清理全部 30+ 处死导入/未使用变量（pyflakes 全干净）
  - `manifest.json` 最低版本声明修正为 `2024.12.0`（与实际使用的 API 匹配）
  - `hass.loop_thread_id` 改 `getattr` 保护（低版本 HA 不退化）
- **MQTT 就绪检查统一**：新增 `is_mqtt_loaded`/`is_mqtt_connected` 辅助函数，替换 7 处隐式 `hass.data.get("mqtt")` 判断
- **MQTT 自动配置自适应**：删除硬编码版本探测，改为 KeyError 自适应补 `other_settings` 段（抗 HA schema 未来变化）
- **Web UI 更新检查**：Gitee 失败自动回退 GitHub
- **新增单元测试**：33 个测试用例（const/ACL 矩阵/persist 持久化/MQTT 就绪判断）
- ⚠️ **需要重启 HA**（集成代码有更新）

### v1.4.8 (2026-08-27)
- **修复**：Web UI「一键升级」400 错误 — 改用 Supervisor 免认证端点 `/addons/self/update`，升级超时放宽至 600s
- **修复**：MQTT 重连成功后未标记 connected，导致命令发送误判失败
- **安全加固**：ACL 分离用户 — 新增 `ha_mqtt` 用户（HA MQTT 集成专用，homeassistant/# 全权限），网关用户 `huijian` 收紧为网关协议主题（防伪造 HA 发现消息）
- **修复**：mosquitto 崩溃无限重启 — 连续 5 次重启失败后退出保留现场
- **修复**：`_reconnect_mqtt` 重连成功后立即标记连接就绪（Bug1）
- **修复**：CancelledError 规范捕获处理（不再与普通异常混为一谈）
- ⚠️ **需要重启 HA**（集成代码有更新）

### v1.4.7 (2026-08-27)
- **安全**：移除 full_access 权限，提升安全评分（zeroconf 不需要设备级权限）

### v1.4.6 (2026-08-27)
- **修复**：mDNS BadTypeInNameException — zeroconf 0.132.0 要求 type_ 和 name 以 `.local.` 结尾

### v1.4.5 (2026-08-27)
- **修复**：mDNS IPVersion.V4 错误

### v1.4.4 (2026-08-27)
- **修复**：插件无法安装 — base 镜像改用 latest tag + pip install 兼容性修复

### v1.4.3 (2026-08-27)
- **修复**：Web UI 检查更新不显示 v1.4.2（Gitee /releases/latest 返回过期数据）

### v1.4.2 (2026-08-27)
- **重构**：用 Python zeroconf 替代 avahi 体系，彻底修复 mDNS（不依赖 D-Bus / avahi-daemon）
- **修复**：Gitee Release 乱码

### v1.4.1 (2026-08-27)
- **修复**：mDNS crash loop
- **优化**：自动更新日志、升级流程

### v1.4.0 (2026-08-27)
- **修复**：mDNS huijian.local A record
- **修复**：hassio MQTT entry fallback

### v1.3.9 (2026-08-27)
- **修复**：mosquitto 退出时 trap 清理逻辑 — 用循环重启替代 exec 替换
- **修复**：mDNS — 添加 avahi-tools + nginx 安全收紧 + 进程生命周期管理

### v1.3.8 (2026-08-27)
- **回退**：host_network（v1.3.7 的改动回退）

### v1.3.7 (2026-08-27)
- **尝试**：host_network mDNS fix

### v1.3.6 (2026-08-26)
- **chore**：版本号更新

### v1.3.5 (2026-08-26)
- **修复**：服务注册协程未 await + mDNS 添加 _mqtt._tcp 服务

### v1.3.4 (2026-08-26)
- **修复**：更新检查改用 Gitee API（无速率限制）

### v1.3.3 (2026-08-27)
- **修复**：mqtt_bootstrap `ConfigEntry.hass` AttributeError（HA 新版本兼容性）
- ⚠️ **需要重启 HA**（集成代码有更新）

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

## 常见问题

### Q: 启动后日志显示"Address in use"？

主机端口 2022 已被其他服务占用。请在 `config.yaml` 中修改 `ports` 定义。

### Q: LoRa 网关连接的 Broker 地址填什么？

填 `huijian.local`（mDNS 自动发现）或 HA 的 IP 地址。插件内置 avahi-daemon，会广播 `huijian.local` 主机名。

### Q: 可以和 HA 官方 Mosquitto broker 附加组件共存吗？

可以共存。本插件使用主机端口 2022（容器内 2022），不会与 HA 官方 Mosquitto broker 的 1883 冲突。

### Q: 如何升级插件？

在 HA 的 **设置 → 加载项 → 慧尖 LoRa 网关** 中点击「更新」。升级后需要重启插件和 HA。

### Q: 升级后数据会丢失吗？

不会。网关持久化数据存储在 HA 配置目录的 `window_controller_gateway_data.json` 中，升级集成时会自动备份恢复。v1.3.2 起增加了 .bak 备份机制，JSON 损坏时可自动恢复。
