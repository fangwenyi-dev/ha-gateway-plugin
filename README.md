# 慧尖 HA 插件仓库

慧尖开窗器网关的 Home Assistant 插件集合。

## 可用插件

| 插件 | 说明 |
|------|------|
| [慧尖 MQTT Broker](./082501/) | 内置 Mosquitto broker，预设凭据，自动配置 HA MQTT 集成 |

## 安装方法

1. 在 HA 中打开 **设置 → 加载项 → 加载项商店 → ⋮ → 仓库**
2. 添加仓库地址：`https://github.com/fangwenyi-dev/ha-gateway-plugin`
3. 在加载项商店中找到「慧尖 MQTT Broker」并安装
4. 点击启动 — broker 和 MQTT 集成自动配置完成

## 相关项目

- [慧尖网关集成](https://github.com/fangwenyi-dev/ha-window-controller-gateway) — HA 自定义组件，提供开窗器实体
