# 慧尖 LoRa 网关一体化插件

[![版本](https://img.shields.io/badge/version-1.0.2-blue)]()
[![HA Add-on](https://img.shields.io/badge/HA-Add--on-green)]()

慧尖开窗器 LoRa 网关的 Home Assistant 一体化插件。**内置 Mosquitto Broker + mDNS 广播 + 网关集成，安装一个插件即可获得全部能力**。

## 工作原理

```
LoRa 网关 (MQTT 客户端)
    │
    │ MQTT TCP → huijian.local:1883 (mDNS 自动发现)
    ▼
┌───────────────────────────────────────────────┐
│ 慧尖 LoRa 网关一体化插件 (Docker 容器)          │
│                                               │
│  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Avahi mDNS   │  │ Mosquitto Broker     │  │
│  │ 广播 .local  │  │ 监听 0.0.0.0:1883    │  │
│  │              │  │ 预设用户名/密码      │  │
│  │              │  │ ACL: gateway/+/req   │  │
│  └──────────────┘  └──────────────────────┘  │
│                                               │
│  ┌─────────────────────────────────────────┐  │
│  │ 自动安装慧尖网关集成                     │  │
│  │ → 复制到 custom_components              │  │
│  │ → Cover/Button/Sensor/Number 实体       │  │
│  └─────────────────────────────────────────┘  │
│                                               │
│  ┌─────────────────────────────────────────┐  │
│  │ 自动配置 HA MQTT 集成                    │  │
│  │ → 通过 Supervisor API 创建配置条目       │  │
│  │ → 连接 127.0.0.1:1883                   │  │
│  └─────────────────────────────────────────┘  │
└───────────────────────────────────────────────┘
    │
    │ HA MQTT 集成 (127.0.0.1:1883，自动配置)
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

在加载项商店中找到「慧尖 LoRa 网关」，点击安装。

### 3. 启动插件

点击「启动」按钮。

**启动后自动完成：**
- ✅ mDNS 广播启动（`huijian.local` 可被 LoRa 网关发现）
- ✅ Mosquitto broker 启动，监听 1883 端口
- ✅ 密码文件自动生成（使用预设用户名密码）
- ✅ HA MQTT 集成自动配置（连接到 127.0.0.1:1883）
- ✅ 慧尖网关集成自动安装到 `custom_components`

### 4. 重启 HA

重启 Home Assistant，让自动安装的网关集成生效。

### 5. 添加网关

重启后在 **设置 → 设备与服务 → 添加集成 → 搜索「慧尖」**，输入网关 SN 即可。

**用户无需操作** — 不需要手动添加 MQTT 集成，不需要通过 HACS 安装集成，不需要填用户名密码。

### 6. 配置 LoRa 网关

在 LoRa 网关的配置界面中填写：

| 字段 | 值 |
|------|-----|
| Broker 地址 | `huijian.local`（mDNS 自动发现，或 HA 的 IP 地址） |
| 端口 | `1883` |
| 用户名 | `huijian`（默认值，可在插件配置中修改） |
| 密码 | `huijian2022`（默认值，可在插件配置中修改） |

## 插件配置

在插件的「配置」标签页中可视化配置以下选项：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `username` | `huijian` | MQTT 用户名 |
| `password` | `huijian2022` | MQTT 密码 |
| `auto_setup_ha_mqtt` | `true` | 启动时自动配置 HA MQTT 集成 |
| `mdns_hostname` | `huijian` | mDNS 广播的主机名（LoRa 网关通过 `<hostname>.local` 发现 HA） |
| `install_integration` | `true` | 启动时自动安装慧尖网关集成到 HA custom_components |

## 网关集成功能

插件自动安装的慧尖网关集成提供以下功能：

### 实体类型

| 平台 | 实体 | 说明 |
|------|------|------|
| Cover | 开窗器 | 开/关/停窗户控制（出现在设备控制栏） |
| Button | 开启/暂停/关闭 | 基础控制按钮 |
| Button | 内倒 | SN 前缀 5005 的设备才有 |
| Button | 平开模式/内倒模式 | 风锁模式切换（SN 前缀 5005 的设备） |
| Button | 配对 | 网关配对新设备 |
| Button | 移除设备 | 删除子设备 |
| Sensor | 电池电压 | 子设备电池电压（V） |
| Sensor | 状态 | 窗户开关状态 |
| Binary Sensor | 在线 | 网关在线状态 |
| Number | 速度 | 开窗速度滑动条（0-100%） |
| Number | 力度 | 开窗力度滑动条（0-100%） |

### 服务

| 服务 | 说明 |
|------|------|
| `start_pairing` | 启动网关配对模式 |
| `set_position` | 设置窗户位置 |
| `rename_device` | 重命名子设备 |
| `transfer_device` | 转移设备到另一个网关 |
| `refresh_devices` | 刷新设备列表 |
| `check_gateway_status` | 检查网关状态 |

## 文件说明

```
huijian_mqtt_broker/
├── config.yaml                      # HA 插件元信息和配置 schema
├── mosquitto.conf                   # Mosquitto broker 配置
├── acl                              # ACL 访问控制（匹配集成协议主题）
├── Dockerfile                       # Docker 镜像构建
├── run.sh                           # 启动脚本（mDNS + 密码 + 集成安装 + broker + 自动配置）
├── auto_setup_mqtt.sh               # HA MQTT 集成自动配置脚本
├── custom_components/               # 慧尖网关集成代码（自动安装到 HA）
│   └── window_controller_gateway/
│       ├── __init__.py              # 集成入口
│       ├── manifest.json            # 集成清单
│       ├── config_flow.py           # 配置流程（可视化添加网关）
│       ├── const.py                 # 常量定义
│       ├── cover.py                 # Cover 实体（开窗器控制）
│       ├── button.py                # Button 实体（控制按钮）
│       ├── sensor.py                # Sensor 实体（电池电压/状态）
│       ├── binary_sensor.py         # Binary Sensor 实体（网关在线）
│       ├── number.py                # Number 实体（速度/力度滑动条）
│       ├── gateway.py               # 网关实体（在线传感器/配对按钮/删除按钮）
│       ├── mqtt_handler.py          # MQTT 协议处理器
│       ├── device_manager.py        # 设备管理器
│       ├── discovery.py             # 网关自动发现
│       ├── persist.py               # 持久化存储
│       ├── utils.py                 # 工具函数
│       ├── base_entity.py           # 实体基类
│       ├── services.yaml            # 服务定义
│       ├── strings.json             # UI 字符串
│       └── translations/zh-CN.json  # 中文翻译
└── README.md                        # 本文档
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

### Q: 重启 HA 后找不到「慧尖」集成？

请检查插件日志中是否显示"集成代码已安装"。如果 HA 配置目录映射失败（路径不一致），可手动将插件中的 `custom_components/window_controller_gateway` 复制到 HA 的 `custom_components` 目录。

### Q: LoRa 网关无法通过 `huijian.local` 连接？

1. 确认插件日志中 mDNS 启动成功
2. 某些网络环境（如企业网络）可能阻止 mDNS 广播，请改用 HA 的 IP 地址
3. 确认 HA 主机和 LoRa 网关在同一局域网

### Q: 可以和 HA 官方 Mosquitto broker 附加组件共存吗？

不可以。两个 broker 会争用 1883 端口。请先卸载或停止 HA 官方的 Mosquitto broker 附加组件。

### Q: 修改了用户名密码后需要做什么？

1. 重启插件（会自动重新配置 HA MQTT 集成）
2. 更新 LoRa 网关的 MQTT 配置

### Q: 升级集成版本？

更新插件仓库并重新安装插件，启动时会自动检测版本变化并更新集成代码。更新后需重启 HA。
