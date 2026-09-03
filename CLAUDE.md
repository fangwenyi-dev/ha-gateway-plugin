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
# v1.6.26（审计 A-2）：必须 compileall 递归——py_compile 的 `*.py` glob 只
# 匹配顶层，mqtt_handler/ 子包（v1.6.25 拆包引入）会整体漏出语法门。
python -m compileall -q custom_components/window_controller_gateway
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
- **Web UI**: `huijian_mqtt_broker/www/`（三文件化：`index.html` 骨架 +
  `css/huijian.css` + `js/huijian.js`，v1.6.25 起；`version.json` 供更新检查）

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
> 线值均为**字符串**（const.py COMMAND_VALUE_*，v1.6.17 对照固件
> app_mqtt_business.c 逐一实证）。旧表 open=0/close=1/stop=2 是废弃固件
> 时代记载，已按现网订正——改动命令映射前以 const.py 与固件为准，勿信旧文档。

| 命令 | 值 | 说明 |
|------|-----|------|
| `open` | "100" | 开窗 |
| `close` | "0" | 关窗 |
| `stop` | "101" | 停止 |
| `a` | "200" | 内倒 (toggle) |
| `wind_lock_tilt` | "0" | 内倒模式 |
| `wind_lock_flat` | "1" | 平开模式 |
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

## 小程序局域网直连 WS 网关（v1.6.15 引入，v1.6.16 默认开定案）

- 集成内置 aiohttp WS 服务器（`ws_gateway.py`），1:1 复刻固件
  `app_ws_gateway.c` 的 JSON-over-WebSocket 协议：`ws://<HA主机>:9001/ws`，
  令牌走 Sec-WebSocket-Protocol 子协议头握手（不匹配不发 101）。
- **默认开**（`DEFAULT_WS_GATEWAY_ENABLED=True`）：对齐固件"配网完成即
  常听"语义（matter-broker main.cpp 无条件 `app_ws_gateway_start`，无用户
  开关）。教训实锤（2026-09-02）：默认关导致小程序 mDNS 发现网关后
  9001 恒 Connection refused，且客户无从知晓该隐藏开关。
- 安全门禁与固件同构：令牌握手 401 拒连（默认令牌 = 小程序内置同值，
  **自定义令牌必须两侧同步**，否则握手全拒）、认证成功才占槽（≤4）、
  空闲 300s 断开、帧长上限；options 可显式关闭/改端口/令牌。
- 生效条件：加载项升级后必须 **重启 HA**（集成代码随加载项落盘、HA 启动
  时加载，运行中容器不换代码）。1.6.15 在线实例可先在「集成→慧尖→
  选项」勾选"小程序局域网直连"立即启用。

### 与小程序/固件联审定案（v1.6.17，四路独立审计 + 一手复核）

四路并行只读审计（消息契约 / 业务语义联动 / 发现与网络配置 / 握手会话）
结论：**协议骨架三方逐字对齐**（`cmd` 请求键 vs `type` 响应键、子协议
令牌握手、错误文案、-1=未知、帧长/槽位/空闲超时）。真实缺口不在协议，
在下面这些**语义与生命周期**上，改动本模块前务必对照：

- **视图层必须做固件同款入界钳制**：`device_ws_view` 是唯一出口——
  position 只接受 0..100（r_travel=255 是"未校准/离线"标记，固件
  `app_protocol_bridge.cpp:2133/2781` 直接丢弃），state 从**钳制后**的
  position 推导；电池 raw 只接受 [80,140]（固件 BATTERY_RAW_MIN/MAX，
  12V 锂电 9.5–12.6V 放宽到 8–14V）。HA 侧 sensor 的"未校准"文案语义
  不受影响（钳制只在 WS 视图层收敛）。
- **WS 通道不经过 HA「删除」按钮，必须自己闭环本地删除**：003 解绑
  确认分支注释"本地删除已由删除按钮流程完成"，所以 `_cmd_unbind` 不
  remove_device 的话设备永远留在缓存/注册表/映射并在下次 get_devices
  复活（幽灵设备）。同理 003 绑定确认走 `add_device` 直达、不经
  `update_device_status` 推送漏斗，需补一次 `_notify_status_listeners`
  新设备才能即时出现在小程序。
- **`connected` 是业务口径（1800s 无上报），不等于"MQTT 发布成败"**：
  control 映射缺失时广播给**全部**已注册网关（固件 P2 定式），跳过
  connected=False 网关属行为分歧；而 gateway_list 的 online 反过来要
  比固件更严——`WS_GATEWAY_ONLINE_STALE_SECONDS=900` 新鲜度双条件。
- **令牌持久化失败必须回滚内存值**：否则形成"小程序已存新令牌、HA
  重启回退旧令牌"的永久 401（固件 NVS 写失败同款回滚语义）。
- **改「小程序 WS 网关端口」= 直连静默失联**：微信 mDNS **不透传 TXT
  记录**，小程序恒拨 9001，端口无法协商下发；options 文案与 README
  FAQ 已警示。
- **半开口径**：WS 能连 ≠ 可控。服务器任一网关条目存在即监听，但列表
  只反映**已注册的集成条目**——小程序连上后列表为空属正常，需先在
  集成中添加该 LoRa 网关。
- **与固件网关共存**：两者都广播 `_mqtt._tcp`，实例名分别为
  `huijian-mqtt`（插件，mdns_publisher.py:88）与 `huijian`（固件），
  小程序必须读 `res.serviceName`（**`res.name` 恒 undefined**——
  "发现服务: undefined" 根因）才能区分；两者还都广播主机名
  `huijian.local`（A 记录冲突，待真机验证，建议只保留一个广播者）。
- 小程序会话层定案（已在小程序仓库同批修复）：onShow/前台恢复传
  `connect(false)` 且 `connect()` 入口清 `_reconnectTimer`（否则重连
  阶梯无限续命，"第1→4→回到1"日志根因）；`_cleanup()` 要 close 底层
  socket（防服务端僵尸连接占槽）；`pair_ack`/`type:"error"` 必须发
  事件让 UI 可见。

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
- 更新检查: `/api/gitee/releases` + `/api/github/releases` **双源并集取版本号
  最大者**（v1.6.7 定案，见 huijian.js fetchLatestRelease；旧"默认源→失败回退"
  记载与代码不符——Gitee Release 自 v1.6.21 起才由 CI 自动补发且可能滞后，
  单信任何一源都会把"最新发布版"误判成旧值）
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
