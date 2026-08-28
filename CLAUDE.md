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

### 回归测试（本地必做）
CI 的 lint job 已跑 `pytest huijian_mqtt_broker/tests`（v1.6.3 起）。
本地推送前必须同步跑通：

```bash
# Windows 侧（WSL python3 无 pytest 时用本机 python）
cd huijian_mqtt_broker
/mnt/d/progrem/python/python.exe -m pytest tests -q
bash -n run.sh                      # shell 语法
python -m py_compile custom_components/window_controller_gateway/*.py
```

给 registry 兼容层/事件属性等"静默失效面"加改动时，须补断言实参的测试
（参考 tests/test_utils.py 的 RecordingEntityRegistry 模式）——
v1.6.0 的 "entity" 字面量回归曾骗过全部 38 个测试，教训记录于此。

---

### Gitee 凭据（v1.6.3 定案：remote 不带 token）
```bash
# remote 保持干净 URL（.git/config 不落任何密钥）
git remote set-url gitee https://gitee.com/fangwenyi-dev/ha-gateway-plugin.git
```
**两条已验证的认证路径（2026-08-28 实测，均无需 URL 内嵌 token）：**
1. **Windows 侧推送**：Git Credential Manager 已存 gitee.com 条目
   （host=gitee.com, username=oauth2），`git push gitee main` 直接走 GCM
2. **WSL/agent 侧推送**：一次性注入 token，不落盘到 remote 配置：
   ```bash
   TOK=$(cat /mnt/c/Users/fangwenyi/.gitee_token | tr -d '\r\n')
   GIT_TERMINAL_PROMPT=0 git push "https://oauth2:${TOK}@gitee.com/fangwenyi-dev/ha-gateway-plugin.git" main
   ```
GitHub 同理走 `gh auth token` 注入一次性 URL（WSL 无 GCM 交互）。
禁止再把 token 写回 `git remote set-url`——历史做法会让明文 token 长期驻留
`.git/config`，任何读取该文件的工具/日志/备份都可能带出。

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

> **端口：2022**。固件 v1.4.2 起 Broker 只监听 2022（1883 已废弃，避与官方
> Mosquitto 加载项冲突）。mosquitto.conf / run.sh / mDNS / mqtt_bootstrap 全部 2022。

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

## Supervisor API（2026-08-27 实测定案，v1.6.3 纠偏）

### 权限要求
```yaml
# config.yaml
homeassistant_api: true   # Web UI 经 /api/ha/ 代理访问 HA Core REST API 的前提
# hassio_api 已移除：插件零调用 Supervisor 管理 API，权限最小化
```

### API 自更新不可行（勿再尝试）
Supervisor 安全设计禁止加载项通过任何 API 更新自身：
- `/addons/self/update`、`/store/addons/{slug}/update`：因 REQUEST_FROM 校验恒 **403**
- `hassio.addon_update`（HA Core 服务）：add-on token 调用实测 **400**

**唯一升级路径**：管理员在 Supervisor「设置 → 加载项 → 慧尖」页面点击「更新」。
Web UI 的"一键升级"按钮自 v1.5.3 起仅跳转加载项详情页（doUpgrade 无任何 API 调用）。
本节旧文档「/addons/self/update 免认证」「一键升级依赖 hassio_api」均为错误记载，
`/api/supervisor/` nginx 死代理已随之删除（run.sh 与 ingress.conf 同步）。

### API 代理路径（现状）
- HA Core API: nginx `/api/ha/` → `http://supervisor/core/api/`（token 由 nginx 注入，不进浏览器）
- 更新检查: `/api/gitee/`（默认源，200+空数组自动回退 GitHub）、`/api/github/`（回退）
- 本地状态: `/api/status`（status.json 探活）、`/api/broker`（连接数）、`/api/version`、`/api/integration`

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
