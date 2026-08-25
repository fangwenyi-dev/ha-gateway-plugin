# 慧尖 MQTT Broker

[![版本](https://img.shields.io/badge/version-1.0.0-blue)]()
[![HA Add-on](https://img.shields.io/badge/HA-Add--on-green)]()

慧尖开窗器网关专用 MQTT Broker。**内置 Mosquitto + 预设凭据 + 自动配置 HA MQTT 集成**，安装即用，免去手动安装配置 Mosquitto 和 MQTT 集成的繁琐步骤。

## 工作原理

```
LoRa 网关 (MQTT 客户端)
    │
    │ MQTT TCP → huijian.local:1883
    ▼
┌─────────────────────────────────────────────┐
│ 慧尖 MQTT Broker 插件 (Docker 容器)          │
│                                             │
│  ┌───────────────────────────────────────┐  │
│  │ Mosquitto Broker                      │  │
│  │ 监听 0.0.0.0:1883                    │  │
│  │ 预设用户名/密码                       │  │
│  │ ACL: gateway/+/req, gateway/rpt_rsp  │  │
│  └───────────────────────────────────────┘  │
│                                             │
│  ┌───────────────────────────────────────┐  │
│  │ 自动配置脚本                          │  │
│  │ 启动时自动通过 Supervisor API         │  │
│  │ 创建 HA MQTT 集成配置条目             │  │
│  │ → 用户无需手动配置 MQTT 集成          │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
    │
    │ HA MQTT 集成 (127.0.0.1:1883)
    │ 自动配置，用户无需操作
    ▼
慧尖网关集成 (custom_components/window_controller_gateway)
    └→ 通过 HA MQTT API 订阅 gateway/rpt_rsp, 发布 gateway/{sn}/req
```

## MQTT 主题协议

与慧尖网关集成 `const.py` 完全一致：

| 主题 | 方向 | 发布者 | 订阅者 |
|------|------|--------|--------|
| `gateway/{gateway_sn}/req` | HA → 网关 | HA MQTT 集成 | LoRa 网关 |
| `gateway/rpt_rsp` | 网关 → HA | LoRa 网关 | HA MQTT 集成 |

## 协议消息类型

| ctype | 名称 | 方向 | 说明 |
|-------|------|------|------|
| 001 | 网关绑定 | 网关→HA | 网关主动发起，HA 回复 errcode:0 + uuid |
| 002 | 网关状态上报 | 网关→HA | 网关主动发起，HA 回复 errcode:0 确认 |
| 003 | 配对/解绑 | HA→网关 | HA 主动发起，网关回复 errcode |
| 004 | 设备控制 | HA→网关 | HA 主动发起，网关回复 errcode |
| 005 | 设备状态上报 | 网关→HA | 网关主动发起，HA 回复 errcode:0 确认 |
| 006 | 设置参数 | HA→网关 | HA 主动发起 |
| 007 | 查询参数 | HA→网关 | HA 主动发起 |

## 安装方法

### 1. 添加插件仓库

在 HA 的 **设置 → 加载项 → 加载项商店 → 右上角 ⋮ → 仓库**，添加：

```
https://github.com/fangwenyi-dev/ha-gateway-plugin
```

### 2. 安装插件

在加载项商店中找到「慧尖 MQTT Broker」，点击安装。

### 3. 启动插件

点击「启动」按钮。

**启动后自动完成：**
- ✅ Mosquitto broker 启动，监听 1883 端口
- ✅ 密码文件自动生成（使用预设用户名密码）
- ✅ ACL 访问控制生效
- ✅ HA MQTT 集成自动配置（连接到 127.0.0.1:1883）

**用户无需操作** — 不需要手动添加 MQTT 集成，不需要填用户名密码。

### 4. 配置 LoRa 网关

在 LoRa 网关的配置界面中填写：

| 字段 | 值 |
|------|-----|
| Broker 地址 | `huijian.local`（或 HA 的 IP 地址） |
| 端口 | `1883` |
| 用户名 | `huijian`（默认值，可在插件配置中修改） |
| 密码 | `huijian2022`（默认值，可在插件配置中修改） |

### 5. 安装慧尖网关集成

通过 HACS 安装慧尖网关集成，添加网关时填写网关 SN 即可。

## 插件配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `username` | `huijian` | MQTT 用户名 |
| `password` | `huijian2022` | MQTT 密码 |
| `auto_setup_ha_mqtt` | `true` | 启动时自动配置 HA MQTT 集成 |

## 文件说明

```
huijian_mqtt_broker/
├── config.yaml          # HA 插件元信息和配置 schema
├── mosquitto.conf       # Mosquitto broker 配置
├── acl                  # ACL 访问控制（匹配集成协议主题）
├── Dockerfile           # Docker 镜像构建
├── run.sh               # 启动脚本（生成密码 + 启动 broker + 自动配置）
├── auto_setup_mqtt.sh   # HA MQTT 集成自动配置脚本
└── README.md            # 本文档
```

## 端口说明

| 端口 | 协议 | 用途 |
|------|------|------|
| 1883 | MQTT TCP | LoRa 网关和 HA MQTT 集成连接 |

## 常见问题

### Q: 启动后日志显示"自动创建可能失败"？

HA 版本不同，REST API 路径可能有差异。如果自动配置失败，请手动添加 MQTT 集成：
1. 设置 → 设备与服务 → 添加集成 → 搜索 "MQTT"
2. Broker: `127.0.0.1`，端口: `1883`
3. 用户名/密码：与插件配置一致（默认 `huijian` / `huijian2022`）

### Q: 可以和 HA 官方 Mosquitto broker 附加组件共存吗？

不可以。两个 broker 会争用 1883 端口。请先卸载或停止 HA 官方的 Mosquitto broker 附加组件。

### Q: 修改了用户名密码后需要做什么？

1. 重启插件（会自动重新配置 HA MQTT 集成）
2. 更新 LoRa 网关的 MQTT 配置

### Q: 这个插件和慧尖网关集成是什么关系？

| 组件 | 类型 | 作用 |
|------|------|------|
| 慧尖 MQTT Broker（本插件） | HA Add-on | 运行 Mosquitto broker，管理 MQTT 连接 |
| 慧尖网关集成 | HA Integration | 在 HA 中创建实体（cover/sensor/button），通过 HA MQTT API 通信 |

插件提供 broker 基础设施，集成提供设备实体功能，两者配合使用。
