# CLAUDE.md - 慧尖 Gateway Plugin 开发指南

## 核心规则

### 推送与验证流程
**每次推送 GitHub 和 Gitee 后，必须检查 GitHub Actions CI 状态：**

```bash
# 1. 推送代码
git push origin main
git push gitee main

# 2. 等待 CI 启动
Start-Sleep -Seconds 30

# 3. 检查 CI 状态
gh run list --repo fangwenyi-dev/ha-gateway-plugin --limit 3

# 4. 如果有失败，查看详情并修复
gh run view <run-id> --repo fangwenyi-dev/ha-gateway-plugin --log-failed
```

**CI 状态说明：**
- `success` ✅ — 通过
- `failure` ❌ — 需要修复
- `startup_failure` ⚠️ — workflow 文件问题
- `queued` ⏳ — 等待执行

**发现问题必须：**
1. 查看失败日志
2. 修复问题
3. 重新推送
4. 再次验证 CI 通过

---

## 项目架构

### 一体化插件
- **插件**: `huijian_mqtt_broker/` — Mosquitto Broker + mDNS + 网关集成
- **集成**: `huijian_mqtt_broker/custom_components/window_controller_gateway/`
- **Web UI**: `huijian_mqtt_broker/www/index.html`

### 版本管理
- `config.yaml` — 插件版本
- `www/version.json` — 版本号
- `www/index.html` — `CURRENT_VERSION` 变量
- `custom_components/.../manifest.json` — 集成版本

**所有版本号必须一致！**

---

## MQTT 协议

### 主题
| 主题 | 方向 |
|------|------|
| `gateway/{gateway_sn}/req` | HA → 网关 |
| `gateway/rpt_rsp` | 网关 → HA |

### 命令
| 命令 | 值 | 说明 |
|------|-----|------|
| `open` | 0 | 开窗 |
| `close` | 1 | 关窗 |
| `stop` | 2 | 停止 |
| `a` | 200 | 内倒 (toggle) |
| `wind_lock_tilt` | 0 | 内倒模式 |
| `wind_lock_flat` | 1 | 平开模式 |
| `set_position` | 0-100 | 设置位置 |
| `set_speed` | 0-100 | 设置速度 |
| `set_strength` | 0-100 | 设置力度 |

---

## 设备类型

### 5005 设备（支持内倒）
- 开/关/停
- 位置滑块 0-100%
- 速度/力度滑块
- 内倒按钮 (command "a", value 200)
- 平开模式/内倒模式按钮
- 重命名/移除

### 非5005 设备
- 开/关/停
- 位置滑块 0-100%
- 速度/力度滑块
- 重命名/移除

---

## Supvervsor API

### 权限要求
```yaml
# config.yaml 必须包含
homeassistant_api: true  # 访问 HA Core API
hassio_api: true         # 访问 Supervisor API
```

### API 代理路径
- Supervisor API: `/addons/self/update` (免认证)
- HA Core API: `/core/api/` (需要 homeassistant_api: true)
- nginx 代理: `/api/supervisor/` → `http://supervisor/`

---

## 常见问题

### CI startup_failure
通常是 workflow 文件问题，检查：
1. YAML 语法
2. Action 版本
3. Secrets 配置

### 401 Unauthorized
检查 `config.yaml` 是否包含 `homeassistant_api: true`

### 内倒按钮不工作
确认使用 command `"a"` 和 value `200`，不是 `wind_lock_tilt`
