# 变更日志

所有版本变更记录在此文件中。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [1.6.16] - 2026-09-02

### 修复（小程序局域网直连 9001 永不监听——默认开定案）

**实证**（2026-09-02 小程序日志 + 我方端口探测）：mDNS 已发现
`_mqtt._tcp → 192.168.1.91:2022`（探活 2022 OPEN），但
`ws://192.168.1.91:9001/ws` 恒 `Connection refused(111)`。根因非小程序/
非网络：v1.6.15 集成侧 `DEFAULT_WS_GATEWAY_ENABLED=False`——WS 服务器
根本不启动，9001 无监听；而固件（matter-broker main.cpp:231/735）是
**配网完成即 `app_ws_gateway_start` 常听、无任何用户开关**。小程序按
"固件同款设备"预期直撞 9001，插件的显式 opt-in 设计打破了该预期，
客户更无从知晓存在隐藏开关。

- `DEFAULT_WS_GATEWAY_ENABLED` False → **True**：任一网关 entry 存在即默认
  监听（options 仍可显式关闭/改端口/令牌）；安全门禁不变——握手子协议
  令牌校验（默认令牌=小程序内置同值）401 拒连、认证成功才占槽（≤4）、
  空闲 300s 断开、帧长上限，与固件同构
- config_flow / ws_gateway 三处 docstring 同步定案措辞；测试改造：
  `test_none_only_when_explicitly_disabled`（仅显式 False 不启动）+
  `test_empty_options_starts_with_defaults`（老 entry 空 options 也默认
  拉起——正是本次事故形状），全量 224 通过
- **升级生效条件**：HA 重启（集成代码随加载项落盘、HA 启动时加载；
  1.6.15 在线实例默认关定死在代码里，勾选 options 可先行启用）

### 修复（cover 原生卡片开/停/关三键任何状态恒可点——用户定案）

**根因实锤**（home-assistant/frontend `src/data/cover.ts`）：
`canOpen = assumed_state || (!isFullyOpen && !isOpening)`、canClose 同理、
`canStop` 仅排除 unavailable；`isFullyOpen/Closed` 无 `current_position`
属性时回退 `state === 'open'/'closed'`。v1.0.1 把 `current_cover_position`
写死 None（注释本意即"保证所有按钮始终可用"）只堵住了位置分支——v1.6.8
恢复真实 state 后，同方向按钮被前端按 state 禁用，即用户所见
"开态灰开键/关态灰关健"。

- `cover._attr_assumed_state = True`：官方合法开关，短路 canOpen/canClose
  两式 → 三键任何状态恒可下发；HA 状态机（state 由 is_closed 计算）不受该
  属性影响，历史曲线/自动化/LLM 语义全保留；位置仍只走 extra_state_attributes。
  语义诚实性成立：协议规定网关只能被动上报（002/005），HA 无法回查实际窗位
- 新增 TestAlwaysControllableButtons 5 项钉桩（assumed 恒真 / available 不回退 /
  is_closed 保真 / current_cover_position 恒 None / STOP feature 声明），全量 223 通过
- 残余置灰仅剩条目重载/设置重试窗口（HA core 对未加载条目的统一行为，
  秒级~分钟级自愈，集成侧不可覆盖）

### 优化（升级引导补「商店断联」排障指引）

**背景**：客户点击 Web UI「去加载项页面更新」跳转
`/hassio/addon/huijian_mqtt_broker` 后报
`Error fetching addon info: App huijian_mqtt_broker does not exist in the store`。
经 Supervisor 源码定案（`supervisor/exceptions.py: StoreAppNotFoundError`、
`supervisor/apps/app.py: app_store = store.get(slug)`）：新版 Supervisor 的 App
架构中，已安装加载项的详情页与「更新」接口均依赖商店条目；若安装后仓库被删除
或商店刷新失败（国内访问 GitHub 不通常见），即出现该报错——插件本身运行正常，
属商店侧断联，非本插件 bug。

- `www/index.html` 升级卡提示：补全恢复路径文案（重新添加仓库 URL 并更新商店）
- `doUpgrade()` confirm 文案同步补一行排障提示；注释块记录 App 架构的 store 依赖定案
- 协议 ack 方向五条规则钉桩：新增 test_protocol_ack_contract.py 17 项
  （003/004/006/007 网关回复零再下发；001/002/005 恰好一次响应）
- 版本号四点同步 1.6.15 → 1.6.16（config.yaml / version.json / index.html / manifest.json）

### 发布后修正（仓库元数据，不占版本号，2026-09-02）

- **安装提速**：`config.yaml` 的 `image` 由 `ghcr.io` 改指南京大学 ghcr 透传
  镜像 `ghcr.nju.edu.cn/fangwenyi-dev/{arch}-huijian-mqtt-broker`——用户实报
  "仓库用的 Gitee 但安装显示 GitHub 且很慢"：仓库元数据走 Gitee 没问题，
  慢在镜像固定拉 ghcr.io（国内龟速/超时）。nju 全链路实测匿名 200
  （index/config/blob；amd64+aarch64、latest 与历史 tag 全通；镜像压缩
  ≈42MB）；镜像本体仍单份发布 CI 推 ghcr.io，零 CI 改动；nju 偶发不可用
  可在加载项配置页用镜像覆盖字段改回。README 同步新增两条 FAQ（安装慢、
  9001 直连排障）。**生效方式**：Supervisor 从仓库直接读取，更新商店后
  新安装即提速，无需新版本发布
- **README 收敛**：addon/根 README 仅保留 1.6.16 与「工作原理/安装启动/
  重启 HA/常见问题」板块（删配置 LoRa 网关/插件配置/设备类型/逐版本清单，
  版本历史单一真源=CHANGELOG）；根 README 修正"直连默认关闭"过期表述

## [1.6.15] - 2026-09-02

### 新增（小程序局域网直连 · 路线 A：集成内置 WS 网关，与 Matter 固件 1:1 协议对等）

**背景**：慧尖小程序经 mDNS `_mqtt._tcp`（本加载项已广播）能"看到"HA，但
随后固定拨 `ws://<IP>:9001/ws`（小程序零名称过滤、丢弃广播端口），插件
此前 9001 无监听 → "可见不可连"。matter-broker 固件的
`app_ws_gateway.c` 证明该端口/路径/子协议令牌握手即小程序的 LAN 控制协议，
本版本在集成内实现同契约服务器，小程序与固件网关在用户侧同构共存。

- **`ws_gateway.py`（新）**：aiohttp 单例服务器（`0.0.0.0:<port>/ws`），
  命令 `get_gateways/get_devices/control/pair/unbind/ping/set_token`、
  推送 `device_update` 七键；握手令牌按 `Sec-WebSocket-Protocol` 逗号/空格
  拆分精确匹配（401 拒连）、认证成功才占槽（≤4）、入站帧 >1024B 报
  `command too long` 断开、空闲 300s 断连——全部与固件定式逐字对齐；
  消息文案（`missing cmd`/`unknown command: x`/`send failed`/set_token
  五级校验链含 B16 bootstrap）逐字符钉死。`set_token` 成功即热改运行时
  令牌并异步持久化到主控 entry options
- **`mqtt_handler.send_ws_raw_004`（新）**：control 透传出口，$SH 004
  线格式与 send_command 同 id 计数器；发布失败回 `False` → `control_ack
  ok:false "send failed"`（不假成功，v1.6.9 家族契约）并同步网关离线态
- **`device_manager`**：新增 `add/remove_status_listener`（update_device_status
  成功漏斗单点挂钩，002/005 上报即推 `device_update`；cleanup 兜底清空）
- **`config_flow` OptionsFlow + strings/zh-CN**：新增 3 个选项
  `ws_gateway_enabled`（**默认关**——9001 是新增局域网监听面）、
  `ws_gateway_port`（默认 9001，1024-65535）、`ws_gateway_token`
  （默认=固件出厂令牌；留空=不认证；表单侧预校验固件字符集/长度，
  防 B4 式含空格令牌自锁）
- **生命周期**：entry setup/unload/remove 三点 `async_ensure_ws_gateway`
  幂等聚合；端口/令牌变更热切换；HA STOP 闩锁防关机过程重拉；启动失败
  （端口占用）只记日志不影响集成其余功能
- 测试：新增 33 项（握手拆分/令牌校验链/device_ws_view -1 约定/dispatch
  全命令实参/004 线格式 topic+QoS+payload 逐键/发布失败离线联动/真
  aiohttp 握手 E2E 含 101 子协议回显+device_update 推送实收）；
  全套 201 passed；`bash -n run.sh` / py_compile 全绿

## [1.6.14] - 2026-09-01

### 修复（真机 E2E 揪出的第二生产根因：HA 2026.8 MQTT 表单 schema 演化击穿自适应）

**问题**：本地真栈（WSL HA 2026.8.3 进程内 + mosquitto 2.0.21 真 broker +
假网关 MQTT 上报）A/B 实锤：客户 HA≥2026.8 首添网关时，MQTT 引导的
`async_configure` 提交**在 broker 完全健康的情况下也必然失败**——2026.8
正式版将 broker 表单的 `other_settings` 改为 `vol.Required`，缺失时由
data_entry_flow 抛 **InvalidData**，而 v1.6.5 引入的"补字段重试"自适应
只捕获 **KeyError**（那是 2026.8.0-dev 校验器直接索引的形态）。落空后
进入兜底 except → ConfigEntryNotReady：v1.6.12 误报 `mqtt_not_available`、
v1.6.13 报 `broker_not_ready`——文案更准但自动建条目依然不可用。
该分支自引入以来零测试覆盖，历轮代码审计（纯静态）均未能发现。

- `ensure_mqtt_connection` 提交重试同时捕获 `(KeyError, InvalidData)`，
  两代 2026.8 形态共用同一"补 other_settings 重试"；重试仍失败则照旧
  收敛为 CENR + abort + 保留标记（不死循环、不穿透异常）
- 旧 HA（无 other_settings 直通）不受影响：单次提交不多试
- 测试：新增 G 组 4 项（InvalidData 重试契约 / KeyError 形态不回退 /
  双失败止损 CENR / 旧版直通单次），变异验证（还原 KeyError-only）精确 2 红
- 全套 168 passed；真机矩阵复跑：健康 broker 首添一次成功（含 cover
  实体生成、网关在线判定、标记消费）

## [1.6.13] - 2026-09-01

### 修复（客户现场 mqtt_not_available 误报根治 · dsh-review-loop 双审计 + 变异测试验证）

**问题**：客户安装加载项后在集成中添加网关报 "MQTT 集成未启用"，但实际根因是
config flow 在 `ensure_mqtt_connection` 之后**立即同步**检查 `hass.data["mqtt"]`
——MQTT 条目刚创建/重载时集成 setup 尚未异步完成，正常启动时序被误判为失败；
且两种完全不同的故障（从未配置 MQTT / 内置 broker 未就绪）复用同一误导文案，
用户无从下手。

**config_flow.py（就绪门禁）**
- 新增 `_async_gate_mqtt_ready` 统一门禁：未就绪时先宽限轮询（10s）再判定；
  错误码按失败形态分流——无条目且无引导标记 → `mqtt_not_available`（快速失败，
  不空等）；有条目或有标记但未就绪 → 新增 `broker_not_ready`（如实提示内置
  broker 未起/凭据被拒，文案中性兼容 HACS 自建 broker 用户）
- `ensure_mqtt_connection` 抛 `ConfigEntryNotReady` 不再直接定错，转交门禁统一
  分流（旧行为=本 bug 本体，E 组端到端接线测试钉死防回归）

**mqtt_bootstrap.py（引导返回值契约）**
- `ensure_mqtt_connection` 返回 `True/False/None`：False=已消耗满一轮 30s 连接
  等待仍未就绪，调用方不得再叠加宽限（消除 30s+10s 串行白等）；None=本次未做
  连接等待，就绪判定交由调用方
- CREATE_ENTRY 超时**保留**标记（条目未落地时下次可重建，独立价值）；更新/
  降级路径**无条件删除**标记（条目数据已落地即引导职责完成，连接由 MQTT 集成
  自身重试负责；此前"保留"语义经审计证实无消费出口且可在 Supervisor 覆盖场景
  形成周期性 reload 环）；修复 hassio 降级分支注释与行为相反的历史漂移
- 新增 `has_bootstrap_marker` 探针（异常安全回退 False，不打断门禁）

**utils.py**
- 新增 `async_wait_mqtt_loaded(hass, timeout)`：轮询与 `is_mqtt_loaded` 同一
  谓词（下游 async_subscribe 的真实前置条件），先查后睡无忙等

**测试**（161 项全绿，新增 22 项）
- `test_mqtt_gate.py`：宽限三态 / 门禁分流 / 短路守护 / 标记生命周期（含
  HAOS MENU 导航形态、hassio 降级分支）/ async_step_user 调用点接线（E 组）
- 变异测试验证：还原旧硬编码 → E 组 4 红；更新分支改回保留标记 → 契约红；
  CREATE 分支改回无条件删 → D1 红——排除假绿

## [1.6.12] - 2026-08-30

### 修复（第五轮全量审计 16 项：4 路并行审计 + 父代理逐条实证后全部落地）

**MQTT 核心（mqtt_handler.py）**
- **005 毒消息 ack 必达（#1）**：attrs 非列表/元素 null → TypeError/AttributeError
  炸穿处理协程、尾部 `_send_ack` 不可达 → 网关对同一报文无限重传。005 处理体
  重构为 inner+wrapper：异常记录并吞掉，ack 进 finally（畸形帧仍恰 ack 一次）
- **002 属性转换吞噬（#2）**：`float(battery)`/`int(r_travel)` 对 null 抛 TypeError
  被 `except ValueError` 漏掉 → 整个属性更新协程中断且被 gather 静默。补
  (ValueError, TypeError)；`_batch_process_tasks` 的 gather 结果逐个查异常落日志
- **陈旧 bind 记账死账（#3）**：start_pairing 记录为 ("bind", None)，
  `_clear_bind_ops_for_device` 按 device_sn 匹配永不命中、超时也不清理 →
  旧会话迟到确认仍命中旧记账，bind_op=="bind" 门控下掐掉当前配对会话的定时器
  （v1.6.11 #2 的残留窗口）。新配对启动时清光全部旧 "bind" 记账（会话不变式：
  同一时刻只留最新一条）
- **auto_discovery 真实接线（#4）**：该选项在表单存在但全工程零消费，取消勾选
  静默无效。新增 `_auto_discovery_enabled()`（读 entry options，取不到默认 True
  保持历史行为），门控 002 未知设备自动添加（已有设备更新/配对路径不受影响）

**实体平台**
- **cover 状态回调缺失（#5）**：cover 是四个平台里唯一没注册
  `add_status_callback` 的——005 上报后滑块/传感器即时刷新而 cover 卡片只能等
  HA 轮询，v1.6.8「cover 驱动历史/自动化」定案的实时性半边从未兑现。启动
  循环与 on_device_added 两路径补注册，移除路径对称摘除
- **sensor 时效契约复活（#7）**：`_update_state` 每次从缓存读到值就把本地
  时效戳重置为 now，紧随其后的 SENSOR_TIMEOUT_MINUTES 判定恒为假——网关离线
  数小时电压/状态仍显示离线前值。改读设备缓存 `last_update`（真实上报墙钟），
  陈旧值如实转 unknown；永不生效的 `last_update_time` 字段删除
- **button 清理总闸（#8）**：基础按钮（open/stop/close/a/内倒两模式）的注册表
  清理整段嵌在「本会话创建过删除按钮」的 if 里——删除按钮被查重跳过时本会话
  新建的基础按钮永久滞留注册表（number/sensor v1.6.3 已修同类，button 最后
  残留）。抽模块级 `_remove_device_buttons` 无条件幂等清理

**注册表死属性簇（本轮最重，#6/#9/#10/#11 关联）**
- **`via_device` 读取簇根治**：DeviceEntry 上从未存在 `via_device` 属性
  （读取端是 `via_device_id`，值=父设备 id：新版 str/旧版 tuple），但
  device_manager 验证日志/转移短路/**`_get_gateway_devices_from_registry`**
  与 `__init__` 子设备清理全部读它且恒落 None——网关子设备清单在生产中**恒空**，
  迁移快照/实体转移/跨网关冲突通知整段静默 no-op；删除网关时子设备孤儿条目
  清理从未执行。新增 utils `get_via_device_id`/`get_device_config_entry_ids`
  双形态兼容层统一改造 5 处读取点；`config_entry_ids` 同为不存在属性名
  （正确 config_entries/旧 config_entry_id），共享保护死分支一并修复。
  附 tokenize 静态扫描测试：集成源码再现 `.via_device`/`config_entry_ids`
  读取即红（v1.6.0 "entity" 字面量同族教训的机制化防复发）
- **options 死控件（#9）**：gateway_sn 字段写入 options 后零消费（setup 只读
  entry.data），删除；真实消费三字段与翻译文案对齐
- **翻译契约（#11）**：strings/zh-CN 的 options.step 只有从不渲染的 "init"，
  补 options/add_gateway 真实步骤与 add_gateway 三个 error 键（此前 UI 裸显
  英文 key）

**持久化与配置**
- **persist .bak 救援（#10）**：主文件缺失直接 return——误删主文件后重启全量
  丢失而备份明明在；缺失与损坏同走 .bak。字段级类型校验：mapping 非 dict/
  removed 非容器此前以 len(None)/set(42) 逃逸到 setup 整挂，现丢弃+告警
- **test_acl 2.x 语义**：未知用户判定从 1.x"默认允许"翻正为 2.x"默认拒绝"
  （运行时即 2.x，测试模型与真机分叉）
- **config.yaml ssl 映射移除**：全仓对 /ssl 零引用、broker 无 TLS——与 v1.6.3
  hassio_api 移除同源的权限最小化清理

**Web UI**
- **abort reason 必须是 Error（#12）**：WHATWG fetch 以 reason 原值 reject，
  `abort('请求超时')` 字符串 reason 让全部 `e.message` toast 显示 "undefined"
  （v1.6.10 目标实际未达成）。改 `abort(new Error(...))`
- **fetchT 超时覆盖 body 读取（#13）**：`.finally(clearTimeout)` 在响应头到达
  即清 timer——代理"回头不 Body"时 resp.json() 无限悬挂，silentRefresh 防重入
  标志永不自愈。timer 延后到 json()/text() 结算；静态钉桩防回潮

**文档**
- README 端口出处纠偏（2022 由 mosquitto.conf+run.sh 定义，config.yaml 不含）；
  ingress.conf "兜底"死路径叙事更正（run.sh 必先重写它，真实角色是 heredoc
  第二拷贝）

### 测试
- 新增 `tests/test_audit_round5.py` 27 项：005 毒消息三形态 ack 恰一次、002 转换
  吞噬、bind 清账+迟到确认不掐会话、auto_discovery 门控开/关、真实 DeviceEntry
  形态（str/tuple via_device_id，刻意不带 via_device）的子设备清单命中与排除、
  静态死属性扫描、sensor 新/旧值四态、cover 注册/摘除生命周期、button 无条件
  清理、options schema 键断言、persist 救援/畸形三例、Web 契约正则、infra 断言
- `test_persist` 主文件缺失用例更新为"完全不可用"分支契约；全套 139 绿

## [1.6.11] - 2026-08-30

### 修复（第三轮外部审计 7 项：5 项落地，2 项裁决误报/维持不改）
- **迟到 003 掐掉当前配对会话（#2）**：_handle_ctype_003 成功分支无条件
  取消配对定时器并退出会话——id 无记账（_bind_ops.pop 一次性消费后）且
  设备恰好不在列表时（如刚删设备的迟到绑定确认撞上新一轮配对），会误关
  当前配对窗口。会话退出/状态恢复现限定 `bind_op == "bind"`（只允许我们
  记账发起的确认结束会话）；设备添加保留（errcode=0 即事实）
- **cleanup 遍历中列表收缩跳项（#3）**：任务 done 回调从 _background_tasks
  remove（:166），第二个循环 await 让出控制权时列表原地变异，索引迭代跳项
  → 被跳过的任务从未被 await（终态异常无人消费、"cleanup 后无任务触碰已清
  状态"保证被破）。两循环改遍历 list() 快照
- **publish 失败状态源分叉（#4）**：send_command 发布异常置 connected=False
  +notify 却漏了 update_gateway_status("offline")——其余全部 connected=False
  路径（check_connection×2/重连放弃）都同步，唯此分叉。对齐补齐
  （注：审计对症状的描述"binary sensor 离线/Web 在线"不准确——
  gateway_status 无显示面消费方，实际是内部状态源一致性问题）
- **去重时间轴 monotonic 化（#5）**：time.time() 换 time.monotonic()（唯一
  喂入点，整体同时基）。注：审计"回跳致字典无限增长"不成立——键空间
  （ctype,id,sn）有限天然有界，本项按 better-practice 顺手修
- **config_flow 连接测试 mock 缺方法（#6）**：MockDeviceManager（生产文件
  内，非测试）缺 allocate_device_number——测试窗口内到达的 005 走
  _quick_add_device 必抛 AttributeError 被消息循环兜底吞（丢一帧+噪音）。
  补齐 + conftest 增补 config_flow 导入面桩（callback/ConfigFlow 基类/
  OptionsFlow）
- **cover.is_closed 浮点截断（外部审计第四轮 #2）**：防御兜底分支
  int(r_travel) 把 0.5 截成 0 → 微开误判"关"，违反">0=打开"定案语义；
  改 float 直比（协议规定整数 0-100，本分支正常不触发，纯防御加固），
  非数值仍落 None

### 裁决为误报（不设修复）
- **#1 "MQTT 订阅永久失效"（🔴 指控最重者）**：不成立。订阅走 HA MQTT 集成
  的 async_subscribe（:403），HA core 自持 broker 重连并在恢复后自动重订阅
  全部注册项；_unsub_rsp 在放弃路径从不注销；_reconnect_mqtt 重试的只是
  冗余的再注册（本地操作，几乎首试即成）；send_command 断连时还会
  _schedule_reconnect 再拉保险。"5 次后永久失聪"的前提机制错误
- **#7 005/002 添加竞争（#NN 号抖动）**：真实存在但纯 cosmetic——
  add_device 按 sn 幂等，无数据损坏；统一命名需中等重构，不值本批动

### 测试
- 新增 5 用例（test_audit_round3.py）：迟到 003 会话保持×1、我方确认
  仍退出会话×1（N1 语义护栏）、cleanup 快照红绿双验×1（旧代码实测
  消费 5/6 确定性失败）、publish 失败 offline 对齐×1、mock 契约×1、
  is_closed 浮点/负值/非数值×1；全量 112 passed；py_compile /
  node --check（JS 无逻辑改动）全绿


## [1.6.10] - 2026-08-30

### 修复（v1.6.9 回归检查 + 第二轮外部审计 12 项 + 第三轮审计 4 项确认修复）
- **绑定成功后状态卡「配对中」（N1，P2）**：_handle_ctype_003 成功分支清了
  pairing_active、取消了超时定时器（唯一自动恢复者），却没复位
  device_manager 的 gateway_status（start_pairing 置的 "pairing"）——
  「配对中」要等下次 002 心跳才消失。成功路径就地 `update_gateway_status
  ("online")`
- **Web 全部请求零超时（N6，P2 健壮性）**：新增 `fetchT()` 统一
  AbortController 封装（HA API 12s / 本地 nginx 8s / github+gitee 更新源
  20s，abort 带「请求超时」reason），并给 silentRefresh 加防重入锁——
  HA Core 挂起不再无限卡住刷新周期或造成并发周期交错写 DOM
- **transfer_device 后置失败不可见（N8）**：映射更新后的注册表重挂/实体
  重链/旧实体清理/双端 reload 四个失败点补 exc_info 堆栈 + post_failures
  计数，尾部明确告警「映射已转移但 N 个注册表步骤失败，重载条目可修复」
  （映射=事实来源，return True 语义不变）
- **number 簿记失败错误回弹（N9）**：命令已送达后 setpoints 写入/持久化
  create_task 抛错（如 hass 关闭期 RuntimeError）此前落入外层 except
  触发 _revert_to_saved，把已生效滑块回弹。簿记独立 try，仅告警不回退；
  未送达回退语义保持（新用例钉桩）
- **二次配对卡死（B2，P1）**：start_pairing/配对按钮先 cancel 旧超时定时器
  再发送，若发送失败抛错，上次成功残留的 pairing_active 再无定时器可清 →
  网关卡片永久显示「配对中」。新增幂等助手
  `WindowControllerMQTTHandler.abort_pairing_if_active()`，services 四条失败
  分支与 gateway 按钮两条失败分支全部先清理再上抛
- **transfer_device 假成功（B1，P1）**：执行块 `transfer_device` 返回 False
  仅日志 → REST 200（校验/查找路径 v1.6.9 已收口，执行块漏网；服务已注册，
  dev tools/自动化可达）。失败/异常均抛 ServiceValidationError
- **check_gateway_status 吞异常（B3）**：执行异常仅日志 → 200「已发送」。
  同族收口抛错（is_connected=False 是合法检查结果，不抛）
- **migrate_devices 契约收口（B4）**：执行失败仅发事件照常返回——服务当前
  未注册（dead code），但按契约补 raise，防止将来重新注册复活假成功
- **silentRefresh 阻断回归（B5，v1.6.9 引入）**：config_entries 瞬断时
  catch 直接 return → 跳过本轮全部设备状态刷新（窗口状态少刷 30s 周期）。
  改为 needRebuild 标志：检测失败仅跳过增删判定，设备更新照常
- **ingress.conf 兜底模板漂移（B9）**：v1.6.9 只给 run.sh 动态生成版的
  `/api/ha/` 加 no-store，Dockerfile COPY 的兜底模板漏同步（调试模式下
  仍供出可缓存响应）。两处已一致

### 澄清（非 bug，语义边界写明）
- **send_command True 的边界（B6）**：True 仅表示 QoS1 publish 被 broker
  接收，不代表设备执行——执行实据靠 005 上报。docstring 已明确，failfast
  契约的适用范围据此界定

### 已知取舍（记录在案，本批不改）
- 004 响应 errcode≠0 无命令级 ack 回传 UI（B8）：需要请求-响应关联机制，
  属架构增强，非缺陷修复
- cover 恢复注入可能回填过期开/关状态（B7）：自愈依赖下次 005，锁不值得
- 默认凭据 huijian/huijian2022（B10）：改动会毁掉存量安装，文档已警告
- base 镜像 :latest 浮动标签（B11）：hassio base 跟踪 Alpine 源，pin 旧版
  反有 apk 仓库轮换导致构建失败的风险（本项目已实证镜像轮换之痛）
- /api/ha/ 对 172.30.32.0/24 内其他加载项可达（B12）：token 仅
  homeassistant_api 范围，run.sh 已留 TODO 待实机取证收紧

### 测试
- 新增 13 用例（stuck-recovery×2、abort 助手单元×3、transfer×3、
  check_status×2、N1 绑定状态恢复×1、N9 簿记不回退×2），全量 106 passed；
  JS node --check、bash -n、py_compile 全绿；无头 Edge 渲染断言 8/8


## [1.6.9] - 2026-08-29

### 修复（外部深度审计终审确认的 5 项真实 bug + 1 项横向扫描同族）
- **start_pairing 假成功（高）**：services.py 内 try 块的 `raise
  ServiceValidationError`（命令未送达）被末尾 `except Exception` 吞掉 →
  REST 200、Web 弹「配对模式已启动」但 pairing_active/超时定时器从未设置。
  补 `except ServiceValidationError: raise`（rename 已有同款保护，v1.6.4
  根治漏掉此路径）；连接/超时/配置类异常分支同族收口如实抛错
- **set_position 假成功（中）**：原 fire-and-forget `async_create_task` +
  内部把全部异常吞成日志 → broker 掉线时永远 200「已提交」。改为同步
  await send_command，未送达（返回 False，QoS1 发布语义无 ack 误判）或
  异常均抛 ServiceValidationError
- **控制实体假成功同族 5 处（中）**：cover 开/关/停、button 按压（普通+
  风锁）、gateway 配对按钮——send_command 返回值不检查且异常仅日志，
  HA 原生卡片/Web 控制全部假成功。统一改为查返回值+抛 HomeAssistantError
  （number 滑块已有回退可见反馈，不改）
- **Web 网关级增删检测（中低）**：silentRefresh 此前仅在卡片为 0 时重建，
  HA 中新增第二台网关页面永不出现（与 v1.6.6 设备级自动增删不对称）。
  每轮比对 config_entries 集合，不一致才整建；API 失败退回旧行为
- **run.sh `/api/ha/` 补 no-store（低）**：此前唯一无缓存头的代理块，
  HA Core REST 的 JSON 响应可被浏览器启发式缓存 → UI 显示陈旧
- **CI 包可见性检查升级为阻断（中）**：ci.yaml 的匿名拉取探测失败时仅
  ::warning，绿 CI 掩盖「用户装不上」。改为 15 秒复测一次仍失败 ⇒
  ::error + exit 1 阻断发布

### 加固（审计低危项）
- `base_entity` 两个生命周期方法补 `await super()` 链（断链曾静默跳过
  mixin 钩子；当前 HA 走 async_internal_* 功能无损，防御性修复）；
  conftest 假实体同步补空实现镜像真实契约
- Web `silentUpdateCheck` 三重限流：localStorage 跨标签页去重（5 分钟）+
  document.hidden 跳过 + 间隔 10→30 分钟（v1.6.7 双源合并后多标签轮询
  有触发 GitHub 匿名限流 60/h/IP 的现实风险）
- `cover.is_closed` 位置兜底分支注释纠偏（002/005 现行链路 r_travel 总与
  推导 status 同写，该分支为防御性冗余）
- README 收敛：两份 README 重复且过期的更新日志改为最新摘要 + 指向
  CHANGELOG.md 单一真源；徽章/版本表同步

### 已知取舍（评估后不改）
- restore 注入与实时上报的微竞态（一个事件循环 tick 窗口，下次上报自愈）
- restore 回填显示重启前状态，期间手拨窗户会短暂失真（协议不能主动查询，
  HA RestoreEntity 通用行为）

### 测试
- 新增 tests/test_command_failfast.py：16 例钉死「未送达/异常 ⇒ 必须抛错、
  成功 ⇒ 不抛且副作用正确」契约（覆盖上述全部 7 处修复路径）

## [1.6.8] - 2026-08-29

### 修复（子设备状态恒显 unknown——v1.0.1 起的历史设计缺陷）
- `cover.is_closed` 由写死 `return None` 改为按网关上报缓存推导真实开/闭：
  HA 标准 state 计算在 is_closed=None 时输出 None→`unknown`（官方源码实证），
  导致 cover.state 恒为 unknown——Web 状态行、历史曲线、自动化条件、
  LLM 语义控制全部只能拿到 unknown；真实状态此前仅存在于
  attributes.device_status。现 state 输出真实 open/closed（位置属性仍
  不出 state，保留原生卡片按钮不因位置 0/100 置灰的原始意图）
- Cover 实体接入 `RestoreEntity`：协议规定网关只主动推送（002/005），
  HA 无法查询、device_manager 缓存不跨重启——修复前每次 HA 重启后
  所有子设备状态直到下次上报都是 unknown。现启动即恢复上次开/关与
  位置（仅当无实时数据时回填，真实上报到达优先覆盖）
- Web 状态行三级兜底：cover.state → attributes.device_status →
  「待上报/离线」，不再向用户暴露英文 unknown/unavailable 裸值
- 状态与位置同步（用户定案：r_travel 0=关、>0=开）：当 status 仍为
  unknown/connected 但已有 position 上报时，is_closed 与 Web 状态行均按
  位置推导，消除「状态: 待上报 + 位置: 65%」的自相矛盾显示
- 新增 tests/test_cover_state.py：is_closed 推导×5 + 重启回填×5
  （静默失效面断言，参考 CLAUDE.md v1.6.0 教训）

## [1.6.7] - 2026-08-29

### 修复（更新检查版本源）
- `fetchLatestRelease` 由「Gitee 有数据就只用 Gitee」改为 **Gitee+GitHub
  双源并集取最大版本号**：gitee Release 不由 CI 自动创建、最大版本会陈旧
  （2026-08-29 实测停在 v1.3.0），旧逻辑会把真新版误判「已是最新版本」、
  升级徽章永不点亮；现单源失败/陈旧均不再影响判定（GitHub 条目先入列，
  同版本优先其 html_url 详情链接）

### 优化（Web 界面视觉全面翻新，纯展示层零逻辑改动）
- 设计系统升级：新色板与分层阴影、统一 16px 圆角、背景柔光径向渐变、
  数字等宽（tabular-nums）显示；字体栈补 PingFang/雅黑中文回退
- 头部：品牌区（📡 磨砂图标块 + 标题 + 版本药丸徽章）、双径向高光渐变；
  favicon/theme-color；刷新按钮加 ⟳ 图标
- 服务状态：改**单行横排**（● 状态灯 + 名称 + 右对齐状态值）——解决堆叠
  瓦片卡片过高问题，整卡高度约减半；灯保留呼吸涟漪动画、按 ok/err/warn
  整卡染色（CSS :has，不动 setStatusDot 的 DOM 契约）；手机端自动改纵向
  单列堆叠保证可读；该卡内边距收紧（.card-dense）
- 网关卡片：左侧渐变强调条 + 📡 头像；SN 改芯片样式；徽章前置状态圆点；
  「状态/改名」按钮内联色改 .btn-slate 类，「配对/内倒/内倒模式」等
  全部改渐变按钮类
- 子设备卡片：入场 fadeUp 动画（v1.6.6 新增设备自动出现时正好淡入）、
  hover 抬升；状态行改独立小面板；网格改 auto-fill minmax(280px) 自适应
- 滑块：完全自定义外观（轨道圆角、白底彩环滑块、按压缩放），位置/速度/
  力度分别用靛/紫/青强调色；数值改芯片式回显
- 更新卡片与 Toast：update-ok/update-err 类化（去内联色）；Toast 加
  ✅/⚠️/⏳ 图标、上滑动画、毛玻璃
- 新增深色模式：@media (prefers-color-scheme: dark) 全变量覆盖，
  跟随浏览器/HA 主题自动切换；内联硬编码色全部清为类，深色无漏网
- 无障碍与偏好：focus-visible 焦点环、prefers-reduced-motion 降级、
  ::selection 配色
- 约束保持：所有 JS DOM 契约不变（id/class 选择器、slider.nextElementSibling、
  badge className 覆写、.device-item 增删检测、setStatusDot 结构）

## [1.6.6] - 2026-08-29

### 修复（Web 界面设备列表不自动更新）
- **新配对子设备最迟 30 秒自动出现**：无感刷新（updateGatewayDevices）此前
  只更新页面上已存在的 `dev-*` 元素状态，新子设备没有对应 DOM、循环直接
  跳过——集成里早已注册的新设备在 Web 界面上永远等不到，只能手动点
  「刷新」或重载页面。现在每轮比对服务端设备 id 集合与已渲染集合，
  有新增/移除即升级为 loadGatewayDevices 完整重建（平时依然无闪烁）
- 同理修复反向场景：设备被整体移除后，页面残留行此前会永久滞留

### 修复（Web 界面版本陈旧：插件 1.6.5、页面显示 1.6.4）
- 根因：ingress 会话 token 路径在插件更新前后不变，而 nginx 对
  `index.html`/`/api/version`/`/api/integration` 从不发送 Cache-Control，
  浏览器启发式缓存持续供应旧版页面与旧 version.json（CI/ghcr 已核实
  1.6.5 镜像内文件均为新）
- nginx（run.sh 动态生成版与 ingress.conf 兜底版同步）：静态页与本地 json
  端点全部 `Cache-Control: no-store`；GitHub/Gitee 代理端 hide 上游自带
  Cache-Control（GitHub API 默认 public max-age=60 会透传进 iframe）后
  统一 no-store，「有可用升级」发现不再被上游缓存拖慢
- 前端 fetch 双保险：haApi、/api/version、/api/status、/api/integration、
  /api/broker、更新检查请求全部显式 `cache: 'no-store'`
- 注意：本次修复要生效一次的前提是更新到 1.6.6 后硬刷新一次（Ctrl+F5）
  ——缓存里躺着的旧页面自身没有这些修复，它救不了自己

## [1.6.5] - 2026-08-29

### 新增（Web UI 升级提醒自动化）
- **「有可用升级」徽章**：检查更新此前只能手动点按钮，页面不会主动告知
  新版本——现 init 完成后自动静默检查一次、之后每 10 分钟复查（GitHub
  匿名限流 60/h/IP，此频率安全）；发现新版头部按钮变为绿色
  「⬆️ 有可用升级 vX.Y.Z」，点击展开完整升级引导卡片（手动检查同款）
- 顺带修复三处小毛病：页头静态版本徽章硬编码 "v1.5.1"（JS 失效时陈旧）
  改为 CURRENT_VERSION 先落底；"已是最新"卡片误称数据源为 Gitee（实测
  仓库 Releases 只在 GitHub，Gitee 恒空数组走回退）改称"发布源"；
  release tag 解析加 ^\d+(\.\d+)+$ 白名单，防 -beta 类后缀把
  compareVersions 拖进 NaN 误判


### 修复（安装故障热修，用户报告"点安装一直不成功"）
- **Dockerfile 分层重构 + pip 国内镜像三级回退**：Supervisor 源码安装在
  NAS 上现场跑 `apk add + pip install zeroconf`，v1.6.4 加 openssl 使
  apk/pip 同层缓存全废、pip 直连 pypi.org 在弱网下无限卡→安装永不完成。
  现拆为 apk/pip 独立两层（后续版本改动不再连带重建依赖层），pip 依次回退
  pypi 直连(30s×2 快速失败)→清华→阿里；requirements COPY 紧随 apk 层，
  代码文件层全部后置以获得最优缓存顺序
- **ghcr 预构建镜像路线打通**（定案更新）：GitHub 无 visibility 变更 API 实锤
  （REST 4 组合 + GraphQL schema 全路径取证），但 Actions GITHUB_TOKEN 首推
  包【继承仓库可见性】——历史包 private 系 8-25 本地手工推送创建时被定死。
  修复手段：gh api DELETE 删包 → CI 重建自动 public（amd64 实测匿名拉 200，
  期间踩坑：token 探测必须带 service=ghcr.io + Accept 索引头，否则假 404）。
  config.yaml 已启用 image: ghcr.io/fangwenyi-dev/{arch}-huijian-mqtt-broker，
  安装/更新从"NAS 现场编译"变为"拉预构建镜像几十秒"；CI 探测步骤同步修正
  并改为输出"删包重推"指引

## [1.6.4] - 2026-08-29

### 修复
- **Web UI 误报「MQTT Broker 已停止」（v1.6.3 引入）**：v1.6.3 的 status.json
  探活循环用 `netstat` 判 2022 端口 LISTEN，但 HA alpine base 镜像根本不含
  netstat（apk 仅 bash/bind-tools/ca-certificates/curl/jq/libstdc++/tzdata/xz），
  `2>/dev/null` 吞掉 command-not-found 后 grep 恒失败 → status.json 永远写
  stopped。v1.6.3 之前该假状态被 nginx 硬编码 "running" 掩盖，之后则反向
  恒假。改用 base 必有的 `/proc/net/tcp{,6}` + busybox awk 解析
  （2022=0x07EA，state 0A=LISTEN/01=ESTABLISHED），一次扫描同时产出：
  status.json（running/pid/listeners）与 broker_status.json（clients/connected）
- **连接数恒 0 的连带旧 bug 一并根治**：v1.5 时代的 `netstat -tn | ... -c
  ESTABLISHED` 连接数采集同样依赖不存在的 netstat（grep -c 空输入返回 0
  伪装成功），Web「HA MQTT 连接」指示灯一直靠 0 兜底走 warn 分支

### 修复（v1.6.4 增量审查批次：两路独立审查 + 主线对抗复核）
- **run.sh `getent hosts supervisor` 恒假（netstat 同构）**：alpine/musl 体系
  不存在 getent（busybox 未编 applet、aports 无包），错误被吞后每次启动都
  走"无法解析"误导日志、主机名优先设计永久落空——改用 base 实装的
  bind-tools `host` 命令
- **停机路径根修**：`trap cleanup EXIT INT TERM` 的 handler 只清理不退出，
  SIGTERM 后从被中断的 wait 返回（rc=143）被主循环当作崩溃重启 mosquitto，
  直到 docker 宽限期 SIGKILL——broker 从未收到优雅 TERM（persistence 最坏
  丢 30 分钟 retained 状态）、每次 stop/restart 拖满超时。现 INT/TERM 显式
  转发 TERM 给 broker + 1s 落盘窗口 + exit 143（bash 行为已实证）
- **transfer_device 实体重挂从未生效**：`EntityRegistry.async_get_or_create`
  关键字白名单（2024.12→dev 全版本取证）无 name/aliases，旧代码传之
  → 该分支 100% TypeError 被外层 except 吞。已删非法 kwargs（命中既有
  实体时 registry 本就不覆盖自定义名，无需"保留"传参）
- **start_pairing/rename_device 假成功残留**：8 个 error-log-then-return
  分支（未指定参数/未找到网关设备/MQTT 发送失败/rename 返回 False）
  与 check_gateway_status 同类——REST 200 令 Web 弹「配对模式已启动」
  「重命名成功」假 toast。全部改抛 ServiceValidationError
- **check_gateway_status REST 语义纠偏（上游源码取证）**：ServiceValidationError
  实测返回 500 非注释宣称的 400（服务视图仅映射 vol.Invalid/ServiceNotFound），
  对前端 !resp.ok 判据等价；注释改实，前端失败分支补徽标回"未知"重判
- **status/broker json 探活写失败告警**：tmp+mv 链尾 `|| true` 会在 /usr
  只读/磁盘满时让 status.json 冻结在最后成功值（v1.6.2 硬编码 200 的隐蔽
  复刻），改为一行告警入容器日志
- **7b 循环端口动态化**：0x07EA 硬编码改 `printf '%04X' ${MQTT_PORT}`，
  status.json 的 port 字段跟随配置（消灭"改端口后状态说谎"面）
- **Dockerfile 显式安装 openssl CLI**：base 仅含 libssl 库，run.sh 密码哈希
  的 mosquitto_passwd 兜底路径此前是死路（command not found 被吞）
- **诊断与静默吞错清理**：nginx 启动不再 `2>/dev/null`（真实 bind 错误可见，
  此前只剩 nginx -t"语法正常"假象）；`cut|tr||echo 文件不存在` 死兜底改
  显式存在性判断；`cat|jq` 管道掩蔽（cat 失败 jq 空输入输出空串、|| echo 0
  永不触发）改 jq 直读；删除 s6-overlay v3 不存在的 /run/s6/container-env
  死回退分支；utils.async_get_entity_id 的 TypeError→None 兜底补 warning
  日志（registry 内部真 TypeError 不再无声吞成"实体不存在"）
- **number._send_value TOCTOU**：await send_command 后补二次 hass-None 守卫
  （await 窗口内实体被删时不再把"命令已成功"误记为"设置失败"并空跑回退）
- **index.html**：速度/力度 oninput 的 unit 转义序统一为 jsAttr（同类
  残留，当前不可利用但防属性来源变化）
- **services.yaml**：check_gateway_status 补 gateway_sn 字段、device_id 改
  非 required（与 Python schema 与 Web 实际调用形态对齐）
- **nginx 静态 JSON 响应头**：status/version/integration/broker 四处删除
  `add_header Content-Type application/json`（与 mime.types 默认值重复
  产生双 Content-Type 头，违反 HTTP 语义）
- **运维卫生**：run.sh 状态文件写入改 tmp+mv 原子替换（防 nginx 读半截）、
  /api/status 与 /api/broker 补 Cache-Control no-store（防浏览器启发缓存
  显示滞后状态）、头部"v1.4.2"假版本号清除、探活注释周期修正
- 审查中排除的假定性问题（勿再整改）：sensor 移除回调不删注册表条目安全
  （device_registry.async_remove_device 上游级联删除全部实体条目，删除按钮
  实体恰有 button.py 显式删除闭环）；number 启动循环与回调注册间无 await，
  无覆盖竞态窗口；`async_get_device(identifiers=set)` 在 manifest 下限
  2024.12→dev 全版本合法（HA 已标 2027.8 废弃，届时再迁）

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
