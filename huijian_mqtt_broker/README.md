# 慧尖 LoRa 网关一体化插件

[![版本](https://img.shields.io/badge/version-1.1.5-blue)]()
[![HA Add-on](https://img.shields.io/badge/HA-Add--on-green)]()

慧尖开窗器 LoRa 网关的 Home Assistant 一体化插件。**内置 Mosquitto Broker + 网关集成，安装一个插件即可获得全部能力**。

## 工作原理

```
LoRa 网关 (MQTT 客户端)
    │
    │ MQTT TCP → HA_IP:1885 (Docker 端口映射)
    ▼
┌───────────────────────────────────────────────┐
│ 慧尖 LoRa 网关一体化插件 (Docker 容器)          │
│                                               │
│  ┌──────────────────────────────────────┐    │
│  │ Mosquitto Broker                     │    │
│  │ 监听 0.0.0.0:1883 (映射到主机 1885) │    │
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
│  │ → 通过 Supervisor API 创建配置条目    │    │
│  │ → 连接 172.30.32.1:1885             │    │
│  └──────────────────────────────────────┘    │
└───────────────────────────────────────────────┘
    │
    │ HA MQTT 集成 (172.30.32.1:1885，自动配置)
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
- ✅ Mosquitto broker 启动，容器内监听 1883，主机映射 1885
- ✅ 密码文件自动生成（使用预设用户名密码）
- ✅ HA MQTT 集成自动配置（连接到 172.30.32.1:1885）
- ✅ 慧尖网关集成自动安装到 `custom_components`

### 4. 重启 HA

重启 Home Assistant，让自动安装的网关集成生效。

### 5. 配置 LoRa 网关

在 LoRa 网关的配置界面中填写：

| 字段 | 值 |
|------|-----|
| Broker 地址 | HA 的 IP 地址 |
| 端口 | `1885`（可在插件配置中修改） |
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

> **注意**：MQTT 端口固定为 `1885`（主机）→ `1883`（容器内），在 `config.yaml` 的 `ports` 中定义，不可在插件配置中修改。这样避免与 HA 官方 Mosquitto broker 的 1883 端口冲突，两个 broker 可以共存。

## 常见问题

### Q: 启动后日志显示"Address in use"？

主机端口 1885 已被其他服务占用。可在插件配置中修改 `mqtt_port` 为其他端口。

### Q: LoRa 网关连接的 Broker 地址填什么？

填 HA 的 IP 地址（不是 `huijian.local`）。本插件不再使用 host_network 模式，LoRa 网关通过 HA 的 IP 地址连接。

### Q: 可以和 HA 官方 Mosquitto broker 附加组件共存吗？

可以共存。本插件默认使用主机端口 1885（容器内 1883），不会与 HA 官方 Mosquitto broker 的 1883 冲突。
