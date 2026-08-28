# 变更日志

所有版本变更记录在此文件中。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。












## [1.6.3] - 2026-08-29

### 修复（Critical）
- **注册表查找实参回归（utils.py）**：v1.6.0 重构把 `async_get_entity_id()`
  第一实参误写为字面量 `"entity"` 并丢弃调用方传入的实体域，HA 真实签名
  `(domain, platform, unique_id)` 的索引键永不命中——重命名别名同步、删除按钮
  精确定位、`_fix_entity_categories`/`_cleanup_unsupported_buttons`、
  on_device_added 查重等 13 处调用全部静默失效。已还原正确转发（并恢复
  TypeError 兜底），新增 RecordingEntityRegistry 实参断言单测防再犯
- **Web UI 事件属性 XSS（index.html）**：onclick/onchange 参数转义顺序颠倒
  （`jsQuote(escapeHtml(x))` 使 `'` 先变 `&#39;`，浏览器解码后 JS 单引号字符串
  可被含引号的设备昵称闭合注入）。新增 `jsAttr()=escapeHtml(jsQuote(x))` 用于
  全部 13 处事件属性；滑块 state/min/max/单位等拼接一并补转义
- **Broker 崩溃自愈失效（run.sh）**：主循环区 `set -e` 生效下
  `wait $PID; EXIT_CODE=$?`——wait 非零返回直接杀死脚本，重启逻辑成为死代码。
  改为 `|| EXIT_CODE=$?`；重启计数按"连续崩溃"语义在稳定运行 60 秒后清零
  （旧实现生命周期内累计 5 次即永久放弃）

### 修复（High）
- **number 移除竞态崩溃**：`_send_value`/`_revert_to_saved`/防抖链路补
  `hass is None` 守卫（拖滑块后立即删设备不再复现 v1.6.1 类 traceback）
- **实体重复创建**：on_device_added 增加会话内 created_* 字典幂等短路，
  设备重同步不再叠加 add_status_callback（旧实例回调无人摘除的泄漏路径）
- **凭据与攻击面收敛**：删除 nginx `/api/supervisor/` 死代理（带完整
  Supervisor token、前端零调用）及 config.yaml `hassio_api` 权限；
  mosquitto `log_type all` 降为 warning+error（不再把主题/SN 全量入日志）；
  删除启动日志打印密码哈希片段；printf 密码文件写法改 `%s` 格式串并校验
  用户名白名单（含 `%`/`\` 不再损坏哈希）
- **镜像发布链路**：CI 构建后自动把 ghcr 包设为 public（成功后可在
  config.yaml 启用 image: 字段）；Dockerfile 构建排除 `__pycache__`/`tests`
  （新增 .dockerignore）

### 修复（Medium/Low）
- `/api/status` 由 nginx 硬编码 "running" 改为后台探活循环写 status.json
  （2022 端口 LISTEN 判活，broker 挂时页面如实显示已停止）
- mDNS：IP 探测失败不再广播 127.0.0.1（改退出交由看门狗 10 秒重试）；
  run.sh 增加监督循环（进程异常退出自动重启）；每 30 秒检测 IP 变化自动重注册
- Web UI：「未知」占位符不再污染网关 SN 映射与状态/配对请求（改实时读
  GATEWAY_SN_BY_ENTRY）；identifiers 锚点改为按集成 DOMAIN 匹配；
  删除 controlDevice/controlDevicePosition 中拉而未用的全量 /states 请求
  （其失败会拦死控制按钮）；set_position 钳制 0-100 并拒绝 NaN；
  Gitee 无 Release 返回 200+[] 时正确回退 GitHub；页头/页脚版本号不再
  硬编码过期值；隐藏页暂停 30 秒轮询；删除 refreshDevices/transferDevice
  死代码（字段有误，注释留修复指引）
- mqtt_bootstrap 端口回退 1883→2022（1883 根本不监听，死配置）
- check_gateway_status 服务找不到网关时抛 ServiceValidationError
  （REST 400），前端不再收到 200 弹「已发送」假成功
- device_manager：8 处 registry 写操作统一收口 call_registry_method
  （约定已写入 utils.py docstring）；迁移兜底循环补 list() 快照
  （循环内有 await，防注册表并发变更）；button 删除按钮双路径落空补 warning 日志

### 工具链
- CI lint job 新增 pytest 步骤（38→47 项测试；曾整体漏掉 C1 的兼容层
  现有单测首次进入 CI）；版本一致性检查覆盖 manifest.json 与
  version.json 双字段；.gitattributes 补 Dockerfile/*.txt/LICENSE LF 规则；
  .gitignore 排除 会话纪要/ 与 .pytest_cache/
- CLAUDE.md 纠偏：删除「/addons/self/update 免认证」「一键升级依赖
  hassio_api」等与实测定案矛盾的记载，补 MQTT 端口 2022 事实与回归测试纪律

## [1.6.2] - 2026-08-28

### 修复
- **Web 移除按钮"未找到删除按钮实体"**：根因是删除按钮实体
  （GatewayDeviceRemoveButton.device_info 用网关 SN，gateway.py:240）
  归属于网关设备，不在子设备实体列表里。v1.5.5 起前端 remove 分支只在
  子设备实体列表中按 unique_id 查找（v1.5.9 双锚点仍未跳出子设备实体
  列表），导致恒报"未找到删除按钮实体"。修复：新增 findRemoveButtonEntity，
  在 API 返回的整个设备列表（网关 parent + 子设备）中按 _remove_{sn}
  锚点精确定位删除按钮实体，触发 button/press 删除
- 版本号统一为 1.6.2（插件 + 集成）

## [1.6.1] - 2026-08-28

### 修复
- **删除设备后实体残留崩溃（'NoneType' object has no attribute 'data'）**：
  实体从注册表删除后 HA 仍周期性调用 async_update，此时 self.hass 已为 None。
  number/sensor/cover 的 async_update 与 base_entity 的
  get_current_gateway_sn/_get_mqtt_handler 均加 hass 守卫
- **移除按钮实体未删除**：删除按钮改用 unique_id 精确定位删除
  （_aget_eid），不再依赖动态添加实体的 entity_id 赋值时机，带兜底
- **日志级别优化**：自动发现跳过被删设备、手动配对重新添加被删设备日志降为 debug
- 版本号统一为 1.6.1（插件 + 集成）
## [1.6.0] - 2026-08-28

### 修复
- **删除设备批量报错 'NoneType' object can't be awaited**：新版 HA 中
  EntityRegistry/DeviceRegistry 的 async_remove/async_remove_device/async_update_entity
  等均为同步方法（@callback def，直接返回结果），代码中 await 同步方法导致
  'NoneType'/'RegistryEntry' object can't be awaited。新增 utils.call_registry_method
  兼容层（自动探测返回类型，coroutine 则 await，否则直接用），全项目 22 处
  registry 调用统一修复，兼容新旧 HA
- 修复范围：删除设备/子设备、重命名、设备转移、网关迁移、禁用实体恢复、发现忽略等
- 版本号统一为 1.6.0（插件 + 集成）
## [1.5.9] - 2026-08-28

### 修复
- **Web 界面"删除"按钮找不到实体**：删除按钮 unique_id 格式为 {gw}_remove_{sn}
  （gateway.py:228，remove 在设备 SN 前），与常规实体 {gw}_{sn}_{suffix} 布局不同，
  导致 findEntityByUniqueId 按 _{sn}_remove 锚点匹配失败。改为双锚点匹配
  （_{sn}_{suffix} 与 _{suffix}_{sn} 两种布局）
- 版本号统一为 1.5.9（插件 + 集成）
## [1.5.8] - 2026-08-28

### 修复
- **重命名设备报错 'RegistryEntry' object can't be awaited**：HA 新版将
  EntityRegistry.async_get_entity_id 改为 async 方法（返回 coroutine，await 后为
  RegistryEntry），项目 12 处调用均未 await。新增 utils.async_get_entity_id 兼容
  辅助函数（自动探测同步/异步 API，统一返回 entity_id），全部调用点已修复
- **Web 界面"内倒"按钮不发送命令**：controlDevice 缺少 'a' 命令分支，点内倒
  落入"未知命令"；新增分支按 button 实体 unique_id 后缀 _a 精确查找并调用
  button/press 触发内倒（004 命令 value=200）
- 版本号统一为 1.5.8（插件 + 集成）
## [1.5.7] - 2026-08-28

### 优化
- **Web 界面子设备速度/力度滑块始终可用**：移除无初始上报数据时的 disabled 逻辑，
  与 HA 集成 number 实体行为一致（无需先在集成中调整，Web 界面直接可拖动设置；
  有上报数据时回显当前值）
- 版本号统一为 1.5.7（插件 + 集成）
## [1.5.6] - 2026-08-28

### 修复
- **Web 界面网关状态"未知"**：网关在线状态改为直接读取 mqtt_handler.connected
  （收到网关上报即在线，超时置离线），通过设备 API 的 gateway_online 字段返回，
  不再依赖 binary_sensor 在线实体（实体未创建/匹配失败时不再显示"未知"）
- **Web 界面网关 SN"未知"**：从设备注册表 identifiers 提取真实 SN 更新显示，
  解决无 SN 等待模式下 entry.data.gateway_sn 为空导致的"未知"
- 版本号统一为 1.5.6（插件 + 集成）
## [1.5.5] - 2026-08-28

### 修复
- **Web 界面无法控制子设备（"未找到设备 cover 实体"）**：Web UI 用设备 SN 后 6 位
  模糊匹配 entity_id，但设备显示名只含 SN 后 4 位（get_device_display_name 用
  device_sn[-4:]，HA 生成的实体名不含后 6 位）→ 匹配永远失败。
  修复：设备列表 API（/window_controller_gateway/devices）为每个设备返回精确实体列表
  （entity_id/domain/unique_id），Web UI 按 unique_id 锚点（_{device_sn}_{suffix}）
  精确查找，替代字符串模糊匹配。修复范围：开/关/停、位置滑块、速度/力度滑块、
  内倒/风锁模式按钮、删除按钮、在线状态、电池电压显示
- 版本号统一为 1.5.5（插件 + 集成）
## [1.5.4] - 2026-08-28

### 修复
- **手动配对无法重新添加被删子设备**：手动删除过的设备进入全局手动删除列表后，
  `_handle_ctype_003` 的"设备复活守卫"无条件拦截，导致手动配对（003 绑定确认）
  也无法重新添加（2026-08-27 实测）。修复：手动配对确认（bind_op=bind）
  允许重新添加并从删除列表移除；自动发现（002）仍拦截，保持防复活语义
- 新增 003 绑定确认诊断日志（id/errcode/sn/bind_op/手动删除列表）
- 新增 5 个回归测试（test_mqtt_bind.py）
- 版本号统一为 1.5.4（插件 + 集成）
## [1.5.3] - 2026-08-27

### 修复
- **一键升级 400/403 根因修复**：Supervisor 安全设计（2025 年引入）禁止插件通过 API 自我更新——
  `/addons/self/update` 与 `/store/addons/{slug}/update` 检查 REQUEST_FROM 返回 403，
  `hassio.addon_update`（HA Core 服务）返回 400（add-on token 调服务 API 权限不足）。
  将 Web UI「一键升级」改为跳转 Supervisor 加载项页面，以管理员身份点击「更新」（唯一可靠路径）
- 版本号统一为 1.5.3（插件 + 集成）
## [1.5.2] - 2026-08-27

### 优化
- **Web UI 视觉体验优化**：精简布局、优化控件样式与交互细节
- **README 精简优化**：文档结构整理，更清晰易读
- 版本号统一为 1.5.2（插件 + 集成）
## [1.5.1] - 2026-08-27

### 修复
- **一键升级失败诊断增强（Bug A）**：区分 400（hassio 集成未加载/权限不足）与 403（Supervisor 自我更新限制），新增打开加载项页面引导
- **run.sh 密码兜底格式无效（Bug B）**：`openssl dgst -sha256` 拼 `$6$` 前缀为无效格式，改用 `openssl passwd -6`（SHA-512 crypt）
- **静默接管 MQTT 配置（Bug C）**：删除 hassio 源 MQTT 条目前发送持久化通知告知用户
- **设备编号竞态（Bug D）**：新增原子自增计数器 `allocate_device_number()`，批量添加编号不再重复
- **无 SN 模式平台注册（Bug E）**：不再 forward 空平台，消除平台 setup 错误日志
- **墙钟超时误判（Bug F）**：网关/传感器超时改用 `time.monotonic()` 单调时钟
- 版本号统一为 1.5.1（插件 + 集成）
## [1.2.9] - 2026-08-26

### 修复
- **Web UI "HA MQTT 未连接" 根因修复**：addon 的 `config.yaml` 缺少 `homeassistant_api: true` 权限声明，导致 Supervisor 的 `/core/api/` 代理返回 401。所有 haApi() 调用（网关列表、设备、状态、服务）全部失败，前端显示"未连接"。添加该权限后，SUPERVISOR_TOKEN 可通过代理访问 HA Core REST API

## [1.2.8] - 2026-08-26

### 修复
- **一键升级 403 根因修复**：nginx 将 `/api/supervisor/` 代理到 `http://supervisor/supervisor/`，但 Supervisor API 路由是 `/addons/{slug}/...`（无 `/supervisor/` 前缀），导致路径不匹配返回 403。修正为 `proxy_pass http://supervisor/`

## [1.2.7] - 2026-08-26

### 改进
- **自动发现心跳监听器**：无 SN 模式下订阅 `gateway/rpt_rsp` 主题，网关上电后自动触发发现流程，实现"先装集成、后上电网关"的零配置体验

## [1.2.6] - 2026-08-26

### 改进
- **安装流程简化**：`async_step_user` 网关 SN 改为可选项，用户可先安装集成（点"下一步"），之后通过选项页添加网关或等待自动发现
- **选项页支持添加网关**：OptionsFlow 新增 `add_gateway` 步骤，无网关 SN 时自动进入添加表单
- **自动发现填充空条目**：网关被发现时，若已有空 SN 的集成条目，自动填充该条目而非创建新流程
- **无 SN 优雅降级**：`async_setup_entry` 在无网关 SN 时注册空平台并返回，不崩溃

## [1.2.5] - 2026-08-26

### 修复
- **集成版本强制升级 1.4.6→1.4.7**：设备上旧的/损坏的集成代码因版本号恰好已是 1.4.6 导致 run.sh 跳过更新，集成无法加载。强制版本升级确保 run.sh 重新拷贝全部集成文件

## [1.2.4] - 2026-08-26

### 修复
- **一键升级 403 修复**：升级函数调用 `/addons/{slug}/update`（需 admin 权限），addon 的 SUPERVISOR_TOKEN 无权限被 Supervisor 拒绝。改用 `/addons/self/update`（免 admin 路径，Supervisor 自动识别调用者身份）

## [1.2.3] - 2026-08-26

### 修复
- **服务处理器 `hass` 变量修复**：v1.2.0 将 7 个服务处理器从 `__init__.py` 拆分到 `services.py` 时，处理器由闭包函数变为模块级函数，丢失了对 `hass` 变量的闭包访问，导致所有服务调用（配对/重命名/设位置/检查状态/转移设备）触发 `NameError`。修复方案：7 个处理器签名增加显式 `hass: HomeAssistant` 形参，注册时通过 lambda 绑定，兼容所有 HA 版本
- **面板网关列表 401 降级提示**：`loadGateways()` 依赖 HA Core REST API 读取配置条目（插件 token 无权访问），catch 块已改为区分 401 与连接失败，显示对应引导提示而非原始错误

## [1.2.2] - 2026-08-26

### 修复
- **Web UI 状态检查改用插件本地事实**：HA Core 拒绝插件 SUPERVISOR_TOKEN 访问 Core REST API（401），导致面板「网关集成/HA MQTT」永远显示"认证失败"。现改为：网关集成状态读取 run.sh 安装集成时写入的 `integration.json`（`/api/integration`）；MQTT 状态读取 broker 实际 ESTABLISHED 连接数（后台循环每 10 秒写入 `broker_status.json`，`/api/broker`）——面板不再依赖任何 HA API 认证
- **修复 `/api/ha/` 双斜杠**：`haApi` 拼接路径时剥离前导斜杠，消除 `/api/ha//config/...` 形式的请求

## [1.2.1] - 2026-08-26

### 修复
- **移除 `image:` 强制镜像拉取,改回设备本地构建**：GHCR 包可见性反复被重置为 private（匿名拉取报 401/denied），导致 1.2.0 在部分环境无法安装。移除 image 键后，Supervisor 直接在设备上从源码构建镜像，不再依赖任何镜像仓库的可用性与可见性；GHCR 镜像仍由 CI 持续发布，供网络环境良好的用户选用

## [1.2.0] - 2026-08-26

### 修复（核心）
- **MQTT 自动配置根本重写**：旧方案通过 HA Core REST API 自动创建 MQTT 配置条目，但 HA Core REST API 从未提供"创建配置条目"端点（`/api/config/config_entries/entry` 仅支持 GET 列表，`/api/config/config_entries/entry/{entry_id}` 仅支持 DELETE），导致所有版本的自动配置静默失败。新方案改用标记文件机制：插件 `run.sh` 启动时将 broker 连接信息写入 HA 配置目录下的 `window_controller_gateway_mqtt_bootstrap.json`，集成侧新增 `mqtt_bootstrap.py` 模块在 `async_setup_entry` 时读取标记并通过程序化 config flow 自动创建 MQTT 配置条目
- **依赖声明修正**：`manifest.json` 中 `dependencies` 改为 `after_dependencies`，避免鸡生蛋问题（集成需要 MQTT 但 bootstrap 在集成 setup 时创建 MQTT 条目）
- **密码和 token 不再打印到容器日志**：`run.sh` 移除密码明文输出和 SUPERVISOR_TOKEN 前缀输出，符合安全最佳实践
- **新增集成版本下限**：`manifest.json` 添加 `"homeassistant": "2023.8.0"` 最低版本要求

### 改进
- **插件镜像声明**：`config.yaml` 添加 `image:` 键，支持从 GHCR 拉取预构建镜像而非本地构建
- **CI lint 列表同步**：移除已删除的 `auto_setup_mqtt.sh` 引用
- **版本号同步**：插件版本 1.1.9 → 1.2.0，集成版本 1.4.4 → 1.4.5

### 修复（回归审查轮）
- **Supervisor 环境菜单流程适配**：HA 2024.9+ 在 HAOS/Supervised 安装上，MQTT config flow 首步返回 menu（addon/broker 选择）而非表单；bootstrap 现在自动导航到 broker 子步骤，否则自动配置会无限重试永不完成
- **新版 broker schema 兼容**：2026.8+ 校验器要求 `other_settings` 段，缺失直接 KeyError 导致 SETUP_ERROR 无重试；按 `__version__` 探测决定是否附带
- **`async_wait_for_mqtt_client` 用法修正**：该辅助函数超时返回 `False` 而非抛异常，原实现忽略返回值误报连接成功；所有失败路径现在会中止残留流程避免堆积
- **陈旧标记清理**：关闭 `auto_setup_ha_mqtt` 选项后启动时删除历史引导标记文件，避免集成读到过期凭据无限重试
- **前端 Ingress 全量修复**：API 基路径改为从 `location.pathname` 推导（此前在 HA 侧边栏 iframe 中所有请求打到 HA 根路径全部 404）；位置滑块改调集成真实服务 `set_position`（cover 实体无 SET_POSITION 特性）；在线徽章空 SN 误匹配守卫；一键升级动态发现插件 slug（git 仓库安装的 slug 带仓库前缀）并正确区分"已是最新 / 任务进行中 / 已中止"
- **集成运行时缺陷**：畸形 sn 类型帧不再因 AttributeError 导致整帧丢弃（含心跳，避免网关被误判离线）；persist 深拷贝消除并发持久化静默丢失；已手动删除的设备不再被晚到的绑定确认复活；后台任务随配置条目卸载取消；补齐 `invalid_input` 中止翻译键

### 安全加固
- nginx ingress 仅允许 HA Core（172.30.32.2）来源访问
- Docker 基础镜像固定为 `ghcr.io/home-assistant/{arch}-base:3.21`（amd64/aarch64 双架构经 GHCR registry 验证）
- 移除 services.yaml 中未注册的幽灵服务声明 `migrate_devices`
- `full_access` 经 Supervisor app schema 核验后保留（当前 schema 无 `host_name` 选项，且 `host_network` 会与 HAOS 系统 avahi 冲突抢占 UDP 5353）

## [1.1.9] - 2026-08-26

### 新功能
- **Web UI 一键升级**：检查更新发现新版本时，点击「一键升级」按钮直接调用 Supervisor API 更新插件，无需手动操作 HA 插件商店
- **nginx 新增 Supervisor API 代理**：`/api/supervisor/` 代理到 `http://supervisor/supervisor/`，支持前端直接调用插件更新/重启等 Supervisor 端点
- **GitHub API 代理修复**：检查更新改为通过 nginx `/api/github/` 代理，避免 Ingress iframe 中 CSP 拦截外部 `api.github.com` 请求

### 优化（Web UI 全面重构）
- **CSS 变量化**：使用 `:root` CSS 变量统一管理颜色，全站一致
- **配色现代化**：主色改为 #5b6ee1，状态色用绿/黄/红+对应浅色背景，视觉层次更清晰
- **卡片/按钮/徽章重设计**：圆角、阴影、hover 过渡效果统一
- **状态指示器优化**：带 `box-shadow` 光环的圆点，更醒目
- **响应式适配**：窄屏状态网格自动折叠为单列
- **代码精简**：`checkServiceStatus` 和 `loadDeviceState` 去重，逻辑更紧凑

### 修复（关键 - Web UI 状态检测三项全失败）
- **MQTT Broker 状态"无法连接"**：`/api/status` 由 nginx 直接返回，但 nginx 启动失败时不可达。添加 `nginx -t` 诊断输出，同时 `add_header` 添加 `always` 确保错误响应也带 Content-Type
- **网关集成/HA MQTT 检测"检测失败"**：nginx 代理到 Supervisor API 时 `supervisor` 主机名在 `full_access: true` 模式下可能无法解析。添加 `getent hosts` DNS 解析检测，失败时兜底为 Supervisor 固定 IP `172.30.32.2`
- **SUPERVISOR_TOKEN 为空导致 401**：`run.sh` 中 `HA_SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"` 可能为空（`with-contenv` 未正确加载时）。添加从 `/run/s6/container-env` 手动 source 的兜底逻辑，并输出 token 前缀确认

### 修复（关键 - 根本原因）
- **auto_setup_mqtt.sh HTTP 401 Unauthorized（最终修复）**：`run.sh` 通过 `SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}" /auto_setup_mqtt.sh &` 显式传递环境变量，但这个旧 token 会覆盖 `with-contenv` 从 `/run/s6/container-env` 加载的最新有效 token。改为不传递 `SUPERVISOR_TOKEN`，让 `auto_setup_mqtt.sh` 的 `with-contenv` shebang 自动加载正确 token
- **auto_setup_mqtt.sh Supervisor 主机解析兜底**：与 `run.sh` 一致，添加 `getent hosts` 检测，失败时使用 `172.30.32.2`

### 改进（前端容错）
- **`haApi` 函数不再 throw**：改为始终返回 `resp` 对象，由调用方检查 `resp.ok` 和 `resp.status`，可区分 401（认证失败）、502（代理连接失败）等不同错误
- **`checkServiceStatus` 错误分类**：401 显示"认证失败"（红色），代理连接异常显示"代理失败"（红色），其他 HTTP 错误显示状态码（黄色）
- **所有 `haApi` 调用方添加 `resp.ok` 检查**：`loadGateways`、`loadGatewayDevices`、`startPairing`、`controlDevice`、`controlDevicePosition` 均添加

## [1.1.8] - 2026-08-26

### 修复（关键 - 根本原因）
- **auto_setup_mqtt.sh HTTP 401 Unauthorized（根本原因）**：`#!/bin/bash` 不通过 `with-contenv`，无法从 `/run/s6/container-env` 加载最新的 `SUPERVISOR_TOKEN`，导致 token 虽有值但被 Supervisor 拒绝。恢复 `#!/usr/bin/with-contenv bashio` shebang，同时所有配置变量用 `${var:-default}` 避免 bashio `set -u` 报错
- **avahi-daemon 启动逻辑矛盾**：失败时仍输出"已启动"。修复为 `if/else` 逻辑，失败时提示改用 IP 地址
- **dbus 启动失败**：容器中缺少 `/run/dbus` 目录，Dockerfile 和 run.sh 均添加 `mkdir -p /run/dbus`

### 变更
- `auto_setup_mqtt.sh` shebang 从 `#!/bin/bash` 恢复为 `#!/usr/bin/with-contenv bashio`
- `run.sh` avahi-daemon 启动逻辑改为 `if/else`，添加 `mkdir -p /run/dbus` 和 `sleep 1` 等待 dbus
- Dockerfile 添加 `mkdir -p /run/dbus`
- **config.yaml 添加 `full_access: true`**：avahi-daemon + dbus 需要系统总线权限才能运行 mDNS 广播
- **前端 XSS 修复**：`renderGateway` / `renderDevice` 中所有用户可控字段（网关名称、设备名称、SN、ID）添加 `escapeHtml` 转义
- **Dockerfile 注释修复**：`dbbus` 拼写错误 → `dbus`
- **auto_setup_mqtt.sh 注释修复**：过时的 `127.0.0.1:1883` → `127.0.0.1:2022`
- **顶层 README.md 同步**：架构图和安装说明中的 1883 端口 → 2022，mDNS 描述对齐
- **前端连接信息更新**：MQTT 地址显示 `huijian.local:2022`，配置提示支持 mDNS
- **CI 质量门禁**：添加 lint job，检查 shell 语法、YAML/JSON 语法、版本号一致性
- **安全文档**：README 添加修改默认密码和备份提醒
- 版本号 1.1.7 → 1.1.8

## [1.1.7] - 2026-08-26

### 修复
- **auto_setup_mqtt.sh HTTP 401**：bashio shebang (`#!/usr/bin/with-contenv bashio`) 可能重新加载环境覆盖了 SUPERVISOR_TOKEN，改用 `#!/bin/bash` 普通解释器
- 新增调试日志：输出 SUPERVISOR_TOKEN 前缀确认是否有效传递

### 新增
- **mDNS 支持**：Dockerfile 添加 avahi + dbus 依赖，run.sh 添加 avahi-daemon 配置和启动，LoRa 网关可通过 `huijian.local` 发现 HA 主机

### 变更
- `auto_setup_mqtt.sh` shebang 从 bashio 改为普通 bash
- Dockerfile 添加 avahi、avahi-compat-libdns_sd、dbus 包
- README 更新 LoRa 网关地址说明，支持 `huijian.local`
- 版本号 1.1.6 → 1.1.7

## [1.1.6] - 2026-08-26

### 修复（关键 - 根本原因）
- **端口冲突彻底解决**：主机端口和容器端口统一改为 `2022`，完全不使用 1883/1885，与 HA 官方 Mosquitto broker 零冲突
- `config.yaml` `ports` 改为 `2022/tcp: 2022`
- `mosquitto.conf` 监听端口改为 `2022`
- `run.sh` 中 `MQTT_PORT` 和 `INTERNAL_PORT` 均改为 `2022`

### 变更
- 所有端口引用从 1885/1883 统一改为 2022
- 版本号 1.1.5 → 1.1.6

## [1.1.5] - 2026-08-26

### 修复（关键 - 根本原因）
- **端口 1883 冲突（根本原因）**：`config.yaml` 中 `services: - mqtt:provide` 导致 HA Supervisor 自动将 1883 端口分配给插件，与官方 Mosquitto broker 的 1883 冲突。移除 `services: mqtt:provide`，插件不再向 HA 声明为 MQTT 服务提供者，HA MQTT 集成通过 auto_setup_mqtt.sh 手动配置连接到 172.30.32.1:1885

### 变更
- `config.yaml` 移除 `services: - mqtt:provide`
- 版本号 1.1.4 → 1.1.5

## [1.1.4] - 2026-08-26

### 修复（关键）
- **端口 1883 冲突**：移除 `mqtt_port` 可配置项，Docker 端口映射固定为 `1885:1883`（主机 1885 → 容器 1883），避免用户误配 `mqtt_port` 为 1883 与 HA 官方 Mosquitto 冲突
- **`mqtt_port` 与 `ports` 脱节**：之前 `mqtt_port` 配置项只影响显示和 auto_setup，不改变 Docker 实际端口映射，容易造成混淆

### 变更
- `config.yaml` 移除 `mqtt_port` 配置项和 schema
- `run.sh` 中 `MQTT_PORT` 固定为 1885，不再从 bashio::config 读取
- 版本号 1.1.3 → 1.1.4

## [1.1.3] - 2026-08-26

### 修复（关键）
- **auto_setup_mqtt.sh HTTP 401 Unauthorized**：`SUPERVISOR_TOKEN` 未显式传递给子进程，导致调用 HA Supervisor API 认证失败
- **README 端口信息过时**：文档中 LoRa 网关端口仍写 1883，实际应为 1885

### 变更
- `run.sh` 显式传递 `SUPERVISOR_TOKEN` 给 `auto_setup_mqtt.sh`
- `auto_setup_mqtt.sh` 中 `HA_TOKEN` 添加默认值防止 `set -u` 报错
- README 全部端口信息更新为 1885
- 版本号 1.1.2 → 1.1.3

## [1.1.2] - 2026-08-26

### 修复（关键）
- **Web UI「MQTT Broker无法连接」**：nginx ingress 配置了 `allow/deny` IP 限制，Ingress 模式下来源 IP 不固定导致 403，移除 IP 限制
- **Web UI「网关集成检测失败」「HA MQTT检测失败」**：默认 `ingress.conf` 缺少 `/api/ha/` 代理配置，添加 HA API 代理
- **Web UI「检查更新」无反应**：直接请求 `https://api.github.com` 被 Ingress iframe CSP 拦截，改为通过 nginx `/api/github/` 代理
- **auto_setup_mqtt.sh 崩溃**：`USERNAME: unbound variable` — bashio 的 `set -u` 导致子 shell 中未定义变量报错，为所有变量添加默认值

### 变更
- `run.sh` 中显式传递环境变量给 `auto_setup_mqtt.sh` 子进程
- `ingress.conf` 默认配置同步添加 `/api/ha/` 和 `/api/github/` 代理
- Web UI 新增 `updateConnectionInfo()` 从 `/api/status` 动态读取端口显示
- 版本号 1.1.1 → 1.1.2

## [1.1.1] - 2026-08-26

### 修复（关键）
- **端口映射架构修正**：`config.yaml` 端口映射改为 `1885:1883`（主机 1885 → 容器 1883），mosquitto 容器内固定监听 1883
- **auto_setup 检测修正**：broker 可达性检测用 `127.0.0.1:1883`（容器内），HA MQTT 集成连接用 `172.30.32.1:1885`（主机映射端口）
- **auto_setup 更新也输出 HTTP 状态码**：之前更新分支没有输出 HTTP 状态码，无法诊断失败原因

## [1.1.0] - 2026-08-26

### 修复（关键）
- **端口冲突彻底解决**：MQTT 端口改为可配置（`mqtt_port`），默认 1885，避免与 HA 官方 MQTT 集成的 1883 端口冲突
- **自动配置 MQTT 集成失败**：`curl` 改用 `-s`（去掉 `-f`），不再在 HTTP 错误时返回空字符串；输出 HTTP 状态码和完整响应体便于诊断
- **mosquitto.conf 动态端口**：配置文件中用 `__MQTT_PORT__` 占位符，`run.sh` 启动时用 `sed` 替换为实际端口

### 变更
- 新增 `mqtt_port` 配置项（默认 1885）
- `watchdog` 改为 `tcp://[HOST]:1885`
- Docker 端口映射改为 `1885:1885`
- 插件版本号 1.0.9 → 1.1.0
- 集成版本保持 1.4.4

## [1.0.9] - 2026-08-26

### 修复
- 移除 `host_network: true`，使用 Docker 端口映射
- mosquitto 文件权限 0700
- 移除 mDNS/avahi 依赖

## [1.0.8] - 2026-08-26

### 修复
- 端口冲突检测
- avahi-daemon 修复

## [1.0.7] - 2026-08-26

### 修复
- Mosquitto 启动流程重写
- Web UI 动态化
- GitHub Actions 自动 Release
