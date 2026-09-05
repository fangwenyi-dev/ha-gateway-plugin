# 变更日志

所有版本变更记录在此文件中。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [1.7.10] - 2026-09-07

### Fixed
- **run.sh 桥接 heredoc 反引号 bug**（HA2 现场实锤：`/run.sh: line 664:
  password: command not found`）：v1.6.26 在共存桥 heredoc 体注释里写的
  「反引号 password 反引号」被未引号 `<<EOF` 当作命令替换执行——函数无害
  （rc 被忽略、mosquitto.conf 正常写入、broker 正常启动），但每次启动污染
  日志且严重误导排障。改为普通引号，并新增回归钉桩
  `tests/test_runsh_heredoc_v1710.py`（静态扫描全部未引号 heredoc 体禁
  反引号 + bash -c 新旧写法对照）；桥 harness 同步再生成

## [1.7.9] - 2026-09-07

### Changed
- **Web 端（桌面）改回 v1.7.7 样式**（用户令「web 端改回去」）：`.page`
  max-width 1400→**1140px** 复原；`.device-list` 恢复 **auto-fill +
  minmax(280px,340px)** 轨道封顶（v1.7.8 的 auto-fit 等分撑满作废）；
  `.device-item` 移除 680px 封顶兜底
- **手机端全对齐（v1.7.8）保留不变**：≤640px 全部 .card 统一 360px 居中；
  闪屏修复（v1.7.5）保留不变

## [1.7.8] - 2026-09-07

### Fixed
- **手机端卡片左缘不对齐**（用户附实拍图指认）：设备卡 360px 居中而连接
  信息卡全宽，两卡左缘错位——改为 ≤640px 下**全部 .card 统一 360px 居中**
  （横向内边距收 2px 对齐 card-flush，卡内网关卡/设备瓦片/连接瓦片/蓝色
  说明框回归自然撑满内容区）；v1.7.5~1.7.7 的 gateway-item/conn-item/
  info-box 单独封顶与 calc 抵消方案全部作废

### Changed
- **Web 端两边太空**（用户附桌面截图）：`.page` max-width 1140→**1400px**；
  设备瓦片轨道 auto-fill+340px 封顶 → **auto-fit minmax(300px,1fr)** 等分
  撑满整行（v1.6.29「轨道封顶保留」口径按用户新令作废），单设备由
  `.device-item` max-width:680px 居中兜底防拉成一条
- 闪屏修复（v1.7.5 静默更新）保持不变

## [1.7.7] - 2026-09-07

### Changed
- **手机端网关卡（含子设备瓦片）320px→360px 居中**（用户改令与底部蓝色
  玻璃统一宽度）：≤640px 下 `.gateway-item` max-width 360px 居中，
  card-flush 无内边距 max-width 直接生效；`.conn-item`/`.info-box` 维持
  v1.7.6 的 360px 不变；手机端闪屏修复（v1.7.5 静默更新）保持不变

## [1.7.6] - 2026-09-07

### Changed
- **手机端底部蓝色玻璃统一 360px 居中**（用户令「底部蓝色玻璃全部统一
  宽度，说明框 360px 居中」）：`.conn-item` 连接瓦片与 `.info-box` 说明
  框统一 360px 居中收窄；网关卡（含子设备瓦片）保持 v1.7.5 的 320px
- v1.7.5 的手机端闪屏修复（控制后走静默更新不重建）保持不变

## [1.7.5] - 2026-09-07

### Fixed
- **手机端控制后"闪一下"**（电脑端无感）：开/关/停/内倒等控制与「检查状态」
  后 2s 的刷新由 `loadGatewayDevices`（innerHTML 全量重建）改为
  `updateGatewayDevices`（静默只更新状态）——重建会重放 `.device-item`
  的 fadeUp 入场动画 + backdrop-filter 重排，手机慢渲染即肉眼可见的
  整列闪烁；静默版自带设备增删检测（有变化自动升级重建，不漏更新）。
  重命名保留重建（名称文本只在重建时刷新，低频可接受）

### Changed
- **手机端卡片收窄**（用户令"太宽了不好看"）：≤640px 下网关卡（含内部
  子设备瓦片）与底部蓝色玻璃说明框（.info-box）统一 **320px 居中**，
  两侧留空让星空透出

## [1.7.4] - 2026-09-07

### Changed
- **流星三色（用户令对照官网）**：7 道流星按官网 createMeteor 配比
  60% 白 / 25% 蓝 / 15% 琥珀（白 4 + `m-blue`×2 + `m-amber`×1），蓝尾
  #38bdf8、琥珀尾 #fbbf24，各带同色 drop-shadow 辉光
- **新增星团层（用户令「多颗星星聚一团、明暗变化」附官网截图）**：
  starsky.js `makeClusters()` 固定种子生成 4 团（屏中上带 14/40/67/86%），
  每团 6~8 颗聚簇（±4.5%×6% 散布），每团 1~2 颗核心大星（2.6~3.4px +
  8px 白晕，官网 canvas 大星 glow size×4 的 CSS 对应物）；正弦明暗
  .1↔.9、三色配比同星点、reduce 豁免同星点层

## [1.7.3] - 2026-09-07

### Changed
- **星点按官网母本放大提亮（用户令"星星尺寸过小，对照官网调整"）**：
  far 0.6~1.4px→**1.8~2.5px**、near 1.2~2.2px→**2.5~3.2px**（官网
  2/2.5/3 三档）；明灭由"单峰触零"改官网**正弦 .1↔.9 永不黑**
  （峰亮度 far .55~.75、near .8~.95，下限 `--floor`=峰×.13）；周期统一
  官网 3~7s；新增官网三色（白 60% / 蓝 #38bdf8 20% / 琥珀 #fbbf24 20%）
  与大星 4px 白晕（near ≥2.9px）。行星群 16 颗口径不动（其"单峰触零 +
  双层独立时钟"是小程序标准，与官网星点是两套母本各管各层）
- 静态资源 cache-bust query 升至 `?v=1.7.3`

## [1.7.2] - 2026-09-07

### Changed
- **取消顶部页头玻璃（用户令，留空原则扩到头栏）**：`.header` 容器
  background/border/backdrop-filter/box-shadow 全清、右上装饰高光
  `::after` 移除——只留布局与 logo/标题/按钮自身（玻璃仍自持在
  网关头 `.gateway-header` 与设备瓷砖 `.device-item` 上，不受影响）
- 静态资源 cache-bust query 升至 `?v=1.7.2`

## [1.7.1] - 2026-09-07

### Changed
- **页头 logo 外框正圆 + 发光强化（用户令）**：`border-radius: 14px→50%`
  圆盘（img 同步圆形裁切），新增内层径向发光盘面 `::before`
  （rgba(125,211,252,.5)→transparent），双环光晕+本体 drop-shadow 保留，
  「最大一颗星」观感整体成形
- **减弱动画下星云漂移纳入豁免（用户令「没有星云」）**：三团 α.07~.10
  静止态在深底上不可辨、运动才可见——`.nebula::before/::after/.nebula3`
  恢复 45/50/60s 超慢漂移（比星点更温和，符合"宁慢勿快"；用户授权对
  官网母本的增强偏差）

### Changed
- **静态资源 cache-bust（根因修复）**：`huijian.css / starsky.js / huijian.js`
  引用统一挂 `?v=版本号`。现场实证：Supervisor update 实体
  `installed_version=1.7.0`（容器确为新版），但用户浏览器呈现的仍是
  ≤1.6.29 旧界面（星星停闪/星云不见/服务状态长玻璃/logo 无光晕）——
  nginx `no-store` 无法穿透 Service Worker/国产浏览器壳等一切客户端缓存
  形态，URL 恒定则旧缓存永生。此后每次发布 query 随版本变化强制穿透；
  钉桩禁止任何裸 css/js 引用

## [1.7.0] - 2026-09-07

### Fixed
- **减弱动画下星云星星"消失/不闪"（用户令对照小程序标准）**：官网星星为
  canvas rAF 驱动（CSS 守卫拦不住）、小程序双层独立时钟常动——插件星点/
  行星群此前只靠 CSS 动画，reduce 下被守卫冻停。现星点明灭 `var(--dur)`、
  行星漂移 `var(--drift)`（55~75s）、行星辉光闪烁 `var(--twk)`（3.5~7s）
  三层同流星一样在 reduce 下按各自周期复流（仅星空装饰层豁免，内容层
  转场仍静止合规）；星云三团漂移不豁免（官网 CSS 层同停）

### Changed
- **背景按小程序标准加一点紫（用户定案"紫仅限氛围底色层"）**：底靛云
  α.12→.16 且中心回收进视口，右上角弱青上叠 #8b5cf6 靛紫云 .09；
  星点/行星/星云/按钮等前景一律不加紫
- **子设备控制按键与数值框透明化（用户令）**：开/关/停/内倒四键由实心
  渐变块改透明 ghost（currentColor 描边 + 同色文字承载语义，hover 轻提亮），
  `.slider-value` 数值小框去底去边框——玻璃层级只留瓷砖本体，与留空原则
  同系；作用域限 `.control-row`，网关区配对/状态键与模式键不受影响
- **页头慧尖 logo 发光（用户令，对齐小程序标准③「logo＝最大一颗星」）**：
  玻璃盘外晕升级为双环光晕（近环 22px/α.55 提形 + 远环 56px/α.22 铺氛围），
  logo 图本体加 `drop-shadow(6px)` 沿 alpha 轮廓发光，随 hero-breathe 呼吸
  脉动、reduce 下静止但仍亮；PIL 像素实测近环带 (63,146,158) vs 基准
  (4,29,48)、远环带 (45,117,144) 光晕成形
- **页头下方"服务状态"长玻璃板取消**（用户令，留空原则扩面）：状态卡加
  `card-flush`——面板背景/边框/阴影/模糊全部透明透星空，仅保留紧凑
  padding；三个状态胶囊（`.status-item` 自带浅玻璃+状态色描边）不受影响
  照常浮于星空上，与网关/设备区容器同款口径

## [1.6.29] - 2026-09-07

### Fixed
- **减弱动画下"没动图没流星"（用户同浏览器对照官网实证）**：官网尾注注入
  `.meteor { animation-duration: 12s !important }` 级联穿透其自身 reduce
  守卫——官网在系统关动画时流星照流。母本行为即标准：本插件 reduce 守卫
  同开流星例外（`meteor-fall-slow` 温和关键帧：峰 .9 尾 .5 程 850px，
  保留各自 10~16s 周期与负延迟相位、infinite），星点/行星/星云在 reduce
  下仍静止合规。CDP 实测 reduce 态流星 opacity 0.88/0.72/0.50 在途、
  整屏动帧 diff 0.85%（旧两版口径——全隐身、静态冻结——均作废）

### Changed
- **子设备玻璃统一按 5005 高度**（用户改令，作废 v1.6.27"各自 hug"口径）：
  行内 stretch + `.device-item` min-height 262px 双保险，无 5005 的行也齐高
- **页头采用慧尖真 logo**：`www/img/logo.png`（563×563，取自插件
  `logo.png` 素材）替换 📡 emoji，玻璃盘呼吸/悬浮动画保留；素材随
  Dockerfile `COPY www/` 整目录进镜像

## [1.6.28] - 2026-09-07

### Fixed
- **空态提示被 grid 轨道挤偏**：`empty-hint`（"暂无子设备，点击「配对」
  按钮添加"）是 `.device-list` 的子 `<p>`，v1.6.27 把该容器改成 grid 后
  提示被塞进首根 ≤340px 轨道左偏显示——补
  `.device-list .empty-hint { grid-column: 1 / -1; }` 横跨整行居中
  （教训泛化：容器布局体系切换时必须清点容器内**非主内容子元素**的
  全行语义）。CDP 真实 DOM 实测三视口（1280/760/390）：提示占满行、
  所有瓷砖零横向溢出、按钮行零溢出、瓷砖高 262/132/96 各自 hug 内容

### Changed
- CHANGELOG 1.6.27「活的宇宙」条星云口径措辞订正（单团旧述→官网三团），
  消除与同节「星云＝官网母本口径」条的自相矛盾

## [1.6.27] - 2026-09-07

### Changed（Web UI「星辰大海」重设计——对齐小程序 UI 设计标准）
- **视觉体系整体切换**：旧版浅色靛紫主题（#4f46e5 主系）作废，按小程序
  「星辰大海」唯一权威标准（记忆条 0d2200c5）移植：深空 `#030712` 底 +
  青蓝令牌系（--primary #0ea5e9 / accent #06b6d4 / 提亮 #7dd3fc），紫仅
  保留在氛围底色层（星点/图标/按钮一律无紫）；卡片/头部/徽章/弹层全部
  改透明玻璃悬浮（--bg-card .07 + --card-border .14 + backdrop-blur）
- **活的宇宙背景层**（新增 `www/js/starsky.js`，mulberry32 固定种子＝
  全站同一片天）：三档氛围角云底 → 官网口径三团星云（蓝左上/金中上/青右下）
  → 双层视差星点（明灭单峰触零）→ 行星群 16 颗（3/4/6px 三档、辉光宁淡
  α.35/4~7px、双层独立时钟：漂移 55~75s 与明灭 3.5~7s 解耦）→ 流星 7 颗
  （10~16s linear 全周期坠落、行程 1100px、只准向下）；`prefers-reduced-
  motion` 全停
- **logo＝最大一颗星**：玻璃盘提亮（32% 盘 + 38% 亮环 + #7dd3fc 光环，
  深空必须）+ 呼吸 0.7→1 与悬浮双动画并行（品牌永不触零）
- 语义色按暗底重排（badge/toast/slider/状态点低 α 化），布局与全部
  DOM 钩子不变（huijian.js 零改动）；移动端断点与无障碍焦点样式保留
- **留空原则（用户校准）**：网关与子设备区容器不再整块铺玻璃底
  （`.card-flush`），未添加的位置直接透出星空；玻璃只落在真实存在的
  悬浮件上——网关头部条与设备瓷砖各自自持 `--bg-card + backdrop-blur`
  （对齐小程序标准⑤"白垫底透光/磨砂磨糊星星均被否"同源教训）
- **设备玻璃框只包自身内容**：`.device-list` 加 `align-items: start`——
  原默认 `stretch` 会把矮内容瓷砖纵向拉高去齐平同行最高框，多出一段
  无内容的空玻璃；现每张开窗器玻璃只比其单独设备内容大一圈（用户校准），
  各框互不等高、间隙透出星空
- **星云＝官网母本口径（用户校准）**：作废单团适配版，逐字移植
  v0.0.1 L105-117 三团结构——蓝团 `.nebula::before`（左上 .10/45s）+
  青团 `::after`（右下 .08/50s）+ 金团 `.nebula3`（中上 .07/60s，新增
  DOM 元素）与 aurora-move1/2/3 关键帧；三团皆 radial 柔边、无 blur、
  无内核白雾（官网原文）
- **行星偏置区随官网三团重排**：starsky.js 的 60% 星云偏置不再指旧单团
  左下（x2-52/y52-96），改按官网蓝团（左上 2-42×2-45）/金团（中上
  55-88×8-48）/青团（右下 60-97×42-85）三区轮分；钉桩锁旧坐标禁回潮
- **单设备行右侧留空**：`.device-list` 轨道 1fr→封顶 340px
  （`minmax(280px, 340px)`）——一行只有一个开窗器时玻璃框只占一轨，
  右侧整段透出星空，不再拉成超宽玻璃板
- **流星负相位进场**：7 颗 `--mdelay` 全改负值（-1s~-12s）——原正延迟
  使打开页面头 1~11s 一颗流星都看不到（用户实测"没看到流星"根因）；
  10~16s 全周期节奏与只准向下、1100px 行程不变
- 版本徽章链路不变：`theme-color` 随主色改深空，页脚/页头版本号仍由
  /api/version 事实回填（W-6/E 系列修复不回退）

## [1.6.26] - 2026-09-07

### Fixed（第八轮全量审计批：5 路独立只读审计 + 母节点逐条实证复核）
- **多网关发现 / 替换网关整链失效**（阻断级）：v1.6.25 mqtt_handler 拆包时
  函数体内惰性导入未随物理下沉升层（`from .discovery` → `mqtt_handler`
  包内不存在该模块，ModuleNotFoundError 被外层 except 吞成一行 error 日志）。
  改 `..discovery` + 补该分支实参断言测试（此前零覆盖——314 测试全绿与
  真栈 E2E 均拦不住，教训已录 CLAUDE.md 同族规范）
- **WS 令牌清空后握手 500**："空串=不认证"是 config_flow 明文支持的形态，
  但 aiohttp≥3.9 的 `WebSocketResponse(protocols=None)` 收到带子协议头的
  请求（微信 connectSocket 恒带）在 _handshake 抛 TypeError。改空元组，
  免认证直连态恢复（aiohttp 3.13.5 活体 A/B 复现取证）
- **半填桥凭据会打死内置 broker**：只填用户名时旧模板展开 `password `
  空值行——mosquitto 2.x 解析器对空值判错**拒载整份 conf**。现凭据双非空
  才成对输出，半填形态降级匿名桥并打警告；e2e harness 由 run.sh 现文重
  生成，新增生成物漂移防护测试
- **awaiting 条目"添加网关"后配置静默不生效**：该路径从不注册 update
  listener、v1.6.19 删掉的显式 reload 兜底前提为假 → 用户见"已保存"但
  无 handler/无实体，须重启 HA。现 setup 完成即注册，条目变更自动重载
- **未校准设备重启后被写成"全开 100%"**：r_travel=255（未校准标记）经
  钳制持久化再恢复被洗成 100。现持久化原始值，恢复仅 0-100 界内回填
  位置，界外只恢复开关态、位置保持未知（固件"255 丢弃"口径维持）
- **幽灵设备复活**：remove_device 在设备不在内存缓存时全部清理（映射/
  注册表/setpoints/回调/bind_ops）静默整体跳过。现缓存无关清理无条件
  幂等执行，缓存缺失打 warning，返回 bool
- setup 在平台转发后失败不卸载平台 → 条目进错误态而实体残留（僵尸实体）
- MQTT 尚未加载时心跳监听器永不武装（自动发现静默失效、无重试）→
  后台等待 MQTT 就绪再武装（120s 上限，订阅前后条目存活双检）
- awaiting-only 安装不启动小程序 WS 网关，与"条目存在即监听"定案口径
  不符 → awaiting setup 同样 ensure
- 含字母 SN 录错大小写呈现"在线但指令全无反应"（入站匹配不敏感、下发
  主题敏感）→ 以网关实际上报形态内存自纠 gateway_sn 并打 warning
- 选项添加网关 unique_id 撞车预检：HA 2026.x `async_update_entry` 对重复
  uid **不抛异常**（仅 error 日志），旧 except 兜底永不触发（源码实证）
- 配置流向导 MockDeviceManager 补齐 003 分支所需属性面（连接测试窗口内
  到达的 003 曾抛 AttributeError 被任务面吞没）

### 安全 / 门禁加固
- nginx ingress.conf（含明文 SUPERVISOR_TOKEN）权限收紧 600——与
  passwd/acl 600/700 同口径，堵容器内低权进程读 token 经代理打 HA API
- 桥段写入后 mosquitto.conf 收紧 600（conf 含对端凭据时不再全局可读）
- 崩溃诊断打印 mosquitto.conf 时 username/password 行脱敏（防密码入
  Supervisor 日志，与 v1.6.3 "passwd 只 cut 用户名"定案同口径）
- CI 语法门 `py_compile *.py` → `compileall` 递归（mqtt_handler 子包不再
  漏出语法门——正是 A-1 那类拆包事故的第二道闸）；Release 正文 awk 补回
  `## [版本]` 标题行；warm-mirrors 镜像仓名改由 image 字段派生（自定义
  镜像改名后预热不再静默失效）

### Added
- **共存桥总开关 `coexist_bridge_enabled`**（默认 true 零感知）：桥判据是
  "本机 :1883 有进程在听"，宿主第三方进程占口存在误桥面（out 腿外送控制
  命令/in 腿注入 discovery，桥消息不受本地 ACL 约束）；置 false 熔断：
  不建新桥、已建桥对账循环自动拆除（README 已加误桥警示）
- Web 页脚版本改 JS 回填占位：消灭遗留硬编码 v1.5.1 的错版闪现
- nginx 启动失败现场取证改用 /proc/net/tcp{,6} 扫描（base 镜像无
  netstat，旧取证行恒空输出——恰在端口被占最需要时无声）

### Changed（文档口径订正）
- CLAUDE.md：更新检查订正为"Gitee+GitHub 双源并集取版本号最大者"（与
  huijian.js v1.6.7 定案一致，旧"默认源→回退"记载与代码不符）；本地
  回归命令同步 compileall；Web UI 架构描述三文件化
- 根 README 与加载项 README 的版本硬字符串改动态引用（曾滞后 8 个版本）；
  共存 FAQ 增补误桥警示/总开关/凭据成对填写要求；run_e2e.sh 过时的
  "首阶段 continue-on-error"注释订正为 v1.6.22 起硬门禁
- config.yaml 共存凭据注释归属订正（v1.6.24 引入、随 v1.6.25 首发——
  历史版本号曾被 bump 全局 sed 漂错）

### 特性公开归并（v1.6.24 未单独发布，本版本起对外可见——详情见 [1.6.24] 段）
- **第三方共存自动桥**：官方 Mosquitto 在跑时自动搭方向分离桥
  （仅 `zigbee2mqtt/#` 双向 + `homeassistant/#` 单向入），z2m 零配置共存；
  对端消失自动拆桥，120s 冷却防抖；`gateway/#` 永久禁跨桥（安全评审定案）
- 可选配置 `coexist_official_user/password`：官方加载项 7.x 强制认证时
  填其 logins 任一账号即带认证建桥；**v1.6.26 起两字段必须成对填写**
- z2m 直连账号 `huijian_z2m`（推荐路径，不装官方 Mosquitto 即可共存）
- `status.json` 诊断位 `coexist_bridge` / `official_peer_up`（无 UI 展示面）

## [1.6.25] - 2026-09-06

### Changed（纯重构批，行为零变化）
- **mqtt_handler 拆包**：1774 行单文件 → `mqtt_handler/` 包（组合类 + 5 个按消息
  生命周期内聚的 mixin：lifecycle/protocol/ctypes/commands/callbacks，全部 <600 行）。
  机械逐字拆分（1514 个非空正文行多重集比对逐字节一致）；对外 import 面、ack 方向
  契约、dedup 语义、weakref 回调设计零触碰；logger 名钉死拆分前值
- **Web UI 三文件化**：index.html 1468 → 90 行；内联样式/脚本逐字节外置为
  `www/css/huijian.css`(356) + `www/js/huijian.js`(1022)（唯一形态变化：
  CURRENT_VERSION 语句逐字移至 index.html 内联单行，全仓唯一声明面有钉桩守护）；
  外置脚本保持 body 末尾同步执行（与原内联时序严格一致）；css/js 自动继承
  `location /` 的 no-store 缓存定案（新增双份配置防回退钉桩，nginx 零改动）
- **run.sh 维持单文件的定案**：加载项规范要求唯一入口，且 30+ 测试锚/桥 e2e/
  凭据生成资产逐字锚定该文件——拆 shell 会连锁重写全部实证资产，风险收益倒挂

### Added
- `tests/e2e/z2m_direct_e2e.sh` + `gen_z2m_authenv.py`：zigbee2mqtt 直连慧尖全链路
  实证（生产认证形态 Z1-Z4 用 run.sh 原文生成区逐字产出 + 真 HA 消费 Z5），
  实测全绿；实证 mosquitto 2.x 对 ACL 拒绝 PUBLISH 静默丢弃不断连（零投递硬断言）
- `ARCHITECTURE.md`：mermaid 全拓扑 + ASCII 简版（Gitee 兜底）+ 三条连接主线
  （分发/数据/接口）+ 安全边界索引；README 挂链
- `tests/test_webui_split_v1625.py`：三文件化 8 项钉桩（字节搬运/相对路径/
  no-store 覆盖/脚本时序/onclick 可得性）

### Notes
- z2m 直连交付结论定案：只装慧尖即可——z2m 配 `mqtt://<host>:2022` +
  `huijian_z2m` 账号；Supervisor 源码证实 `mqtt:need` 无启动闸，官方
  Mosquitto 非 z2m 启动前提
- 全量回归 314 绿（含本批新增 8 项）+ 真 HA 栈 E2E 全断言（HA 实载拆包代码）
  + Z 矩阵重跑；bash -n / py_compile 全过

## [1.6.24] - 2026-09-06

### Added
- **第三方共存自动桥**：慧尖内置 broker 每 30s 探测本机 `1883`——检测到官方
  「Mosquitto broker」加载项（zigbee2mqtt 默认依赖）时自动向其建立**方向分离
  桥**（仅 `zigbee2mqtt/#` 双向 + `homeassistant/#` 单向入），z2m 用户无需改
  慧尖任何配置即可与慧尖共存；官方 broker 停止/卸载后桥自动拆除。桥状态
  变更走"计划内重启"（kill → 主自愈循环 5s 复活），120s 冷却防抖，仅在真实
  状态迁移时记冷却戳（noop 续期缺陷已修）。纯慧尖客户桥**完全不存在**，零感知
- 官方加载项 **7.x 起 go-auth 强制认证**（源码实锤），匿名桥会被拒——新增可选
  配置 `coexist_official_user/password`（慧尖配置页），填官方 logins 任一账号
  即带认证建桥（实测端到端穿透）；留空=匿名桥兼容老版官方。桥不通仅影响共存，
  慧尖自身服务无恙（实测降级边界）
- **z2m 直连账号 `huijian_z2m`**（推荐路径）：broker 启动时自动创建，ACL 仅
  `zigbee2mqtt/# + homeassistant/#`，z2m 的 `mqtt.server` 填
  `mqtt://<主机>:2022` 即可不装官方 Mosquitto 直接共存
- `status.json` 诊断位 `coexist_bridge` / `official_peer_up`（无 UI 展示面，
  与凭据诊断位同边界）

### Changed
- `ha_mqtt`（HA 集成账号）ACL 段新增 `zigbee2mqtt/#`（消费桥入向消息所必需），
  保持白名单式（评审否决 `readwrite #` 通配方案——同密码换用户名的提权链
  爆炸半径不超桥主题白名单）；LoRa 网关账号 `huijian` 权限保持最小不变

### Fixed / 安全定案（三路独立审计 + 真栈取证，1.6.24 未发布故记于本段）
- **摘除 gateway/# 跨桥双腿**：匿名/弱认证官方 broker 场景下，`in` 腿等于把
  对端信任域直连慧尖执行器——真栈实锤"匿名@1883 publish req → 桥 → 固件"
  未认证物理开窗攻击链，已封堵并加负向 e2e 钉桩（S3：注入 req/rsp 零穿透）
- mosquitto 桥块红线（两轮 crash-loop 实证教训）：禁 `topic # both`
  （2.0.22 无 origin 防环，retained 乒乓风暴实测）、禁未实证选项
  （`try_initialize`/`notification_interval` 等 unknown 变量 = broker 整进程
  拒启）；`notifications false` 为实测可用形态（防桥在官方侧残留
  `mosquitto/online` retained 痕迹）
- 巡检子 shell `set -e` 隐患清除（`x && y` 短路行尾返回 false 会静默杀死
  巡检循环——v1.6.3/1.6.4 同族教训）；`/run/bridge_last_ts` 垃圾内容净化
  （防算术展开炸循环）；初启对账 `|| true` 包裹（写失败不得杀死 broker 启动）
- `test_acl.py` 夹具与 run.sh 生成逻辑加**逐行耦合测试**（本次 v1.6.24 期间
  夹具静默漂移被审计抓获的根因整改）；mqtt_match 测试模型修正 MQTT 规范
  语义（通配符不匹配 `$` 前缀系统主题）

### 验证
- 真栈机制实证（rootless mosquitto 2.0.22 双实例 + run.sh 原文函数抽取执行，
  已固化为 `tests/e2e/bridge_coexist_e2e.sh` 永久资产）：S0-S6 状态机（无 peer
  不建桥→探测→建桥→计划内重启激活→z2m 三向语义逐条恰 1→gateway 双向零穿透
  →peer 消失拆桥→服务无恙→可逆重装）+ T1-T2 认证环境（匿名桥被拒但慧尖自身
  正常→填凭据端到端穿透）全通过
- 官方加载项行为源码实锤：home-assistant/addons `mosquitto` 7.1.0 go-auth
  模板 + init 脚本逐行核对；全量回归 306 绿（含 v1.6.24 新增 14 项：test_v1624 9 + test_acl 5）

。

## [1.6.23] - 2026-09-05

### Added
- 集成「配置 → 选项」新增**「以窗帘身份暴露开窗器」**开关（默认关闭）：
  vivo 官方 ha_vivohomebridge 桥的 cover 枚举仅放行 `device_class == curtain`
  （其 vbridge.py 源码实证），开窗器默认的 `window` 类目会被过滤导致在
  vivo 智慧生活中选不到设备。勾选后（条目自动重载、秒级生效、双向可逆）
  cover 以窗帘身份暴露，vivo 端可正常添加并开/关/停控制。
- 默认关闭保证存量用户零影响（HA 原生语义仍为"窗"）；控制路径与
  device_class 无关（开/关/停命令构建逐字节一致，真栈实证）。
- tests/test_v1623.py 六条钉桩：默认值、双向 device_class、options 接线、
  两处 setup 读取、双语描述完整性。

### Fixed
- 测试基建：conftest fake `CoverDeviceClass` 补 CURTAIN 成员；
  round5 lifecycle fixture 如实模拟 `entry.options`（本功能首次真实消费
  该属性暴露的代理对象缺口）。

## [1.6.22] - 2026-09-05

### Removed
- **Web UI 移除「凭据状态」提示项**（用户定案）：MQTT 密码/小程序令牌
  轮换必须与 LoRa 网关固件侧同步修改，终端用户无处置能力，展示
  "仍是默认值"只会造成困惑。后端只读诊断面保留：集成
  `/api/window_controller_gateway/security` 视图与 status.json 的
  `mqtt_password_is_default` 字段继续存在（零展示面，供远程支持排查），
  UI 钉桩转负向防复活（tests/test_v1621.py）。

### Infrastructure（同批推送，不改变已发布行为）
- 真栈 E2E 驱动器定稿（tests/e2e/ha_e2e_driver.py + run_local.sh）：
  本地 WSL 真 HA Core + 真 mosquitto 六轮迭代全绿——onboarding
  IndieAuth URL client_id 契约、confirm_add 二步流、500 条上报
  ~199/s soak、ack 现场实证；CI 编排 summary 断链修复。

## [1.6.21] - 2026-09-04

### 新增（第七轮评分扣分项优化批——不动现有功能，纯增量）

- **默认凭据提示（Web UI 概览新增"凭据状态"项）**：默认 MQTT 密码与默认
  小程序 WS 令牌是公开同串（知道 SN + 内网即可连），此前无任何提醒。
  现 run.sh status.json 输出 `mqtt_password_is_default`，集成新增只读视图
  `/api/window_controller_gateway/security` 输出 `ws_token_is_default`
  （仅布尔，零明文回显；无网关条目时 null 不误导）。概览页合并判定为
  warn 提示。**只提示绝不自动改**——令牌双侧同步是既定契约，自动轮换
  等于全客户永久 401。const.py 增 DEFAULT_MQTT_PASSWORD 交叉锚，测试钉
  三处字面量同步。
- **Gitee Release CI 自动化**（gitee-release job）：消除"发版后手动补
  最新一条"人肉步骤；body 自动取 CHANGELOG 版本段、target_commitish 必
  带、同 tag 幂等跳过、非 ASCII token（BOM）前置拦截报错。需仓库
  Secrets 配置 GITEE_TOKEN（本次已配）。
- **真栈 E2E job**（tests/e2e/run_e2e.sh）：eclipse-mosquitto:2 + HA Core
  真实容器、REST onboarding、config flow 建 MQTT/慧尖 entry、真 MQTT 002
  报文驱动、断言 entry loaded + 集成 devices 视图 gateway_online/子设备 +
  WS 9001 常听 + 500 条 soak 吞吐。补"279 单测全在 mock 上"的真伪验证
  债；盲调试期 continue-on-error，连绿后升硬门禁（脚本内注明）。

### 明确不做（本批）

- `mqtt_handler.py` 物理拆分：纯重构收益仅开发体验，风险波及 279 项内部
  结构钉桩与六轮审计建立的行级熟悉度，与"不影响现有功能"约束冲突——
  记为技术债非缺陷。
- `huijian.local` A 记录冲突裁决：需真机现场（插件与固件同广播），无法
  我方实证，维持文档"待真机验证"口径。

## [1.6.20] - 2026-09-04

### 变更（镜像主源回退 ghcr.io 源站——1.6.19 升级现场实测决策）

1.6.19 把主源切到 ghcr.nju.edu.cn 后，用户升级实测卡在低百分比：nju 对
aarch64 新 tag 的 21MB 大层回源同步近乎冻结（我方两次实测 4.3KB/s →
311B/s 递减），"慢而稳"的预估不成立——**假活慢滴比明确失败更糟**；
ghcr.1ms.run 同期认证端点仍故障（"专属域名获取失败"）。源站 ghcr.io
实测 216KB/s 稳定无闪断，42MB 全量约 3-4 分钟，可接受——主源回退源站。

- 镜像站降级为**手动加速可选项**：追求首包极致（热缓存 1ms ~5MB/s）的
  用户仍可在加载项「配置 → 镜像(Image)」覆盖，README FAQ 同步改口径
  （可用性随时间波动，不作任何默认保证）。
- CI warm-mirrors 保留（对换源用户尽力预热，continue-on-error 不阻塞）。
- 本次无代码逻辑变更；`config.yaml`/`www/version.json`/`www/index.html`/
  `manifest.json` 四处版本同步 1.6.20；测试钉桩同步
  （`test_config_primary_is_ghcr_io_source_1620`）。

## [1.6.19] - 2026-09-04

### 变更（镜像主源回退 ghcr.nju.edu.cn —— v1.6.18 方案实测翻车纠偏）

v1.6.18 把主源切到 ghcr.1ms.run（热缓存 5MB/s），发版当日实测打脸：1ms 是
多边缘 LB，对**新 tag 冷缓存**的各边缘同步完成前返回 404，200/404 按边缘
闪断、分钟~小时级自愈——"发版后首装"恰是它最不可用的窗口，warm-mirrors
预热也只能打到部分边缘。nju 为同步 pull-through：慢（42MB 数分钟）但回源
确定性 200。首装体验"慢而稳"优于"快而随机失败"，主源回退 nju；1ms 降级为
手动快通道（老 tag 已缓存后求快可在加载项配置「镜像(Image)」覆盖）。
README FAQ 同步把 v1.6.18"预热消掉冷缓存概率"的过度承诺改为如实描述。

### 修复（第六轮四路并行审计：MQTT 核心 / 实体与配置 / 基础设施 / WS 契约）

**崩溃与毒报文（HIGH）**
- `mqtt_handler`：显式 `"data": null` 报文会让 001 处理在 ack 前抛
  AttributeError → 网关无限重传毒报文；dispatch 入口统一归一化
  （非 dict → `{}`+告警），一处收口保护全部 ctype 分支。
- 电压解析 `1e999` → `float("inf")` 合法解析后 `int(inf)` 抛
  OverflowError——三处电压点 + `_as_int` + WS 视图 battery 全部加
  `math.isfinite` 判式与 OverflowError 捕获；r_travel/speed/strength
  四个 int 解析点同步加捕。
- `handle_gateway_response` 增加 64KB 入站载荷上限（防畸形超大 JSON 打满
  CPU/内存的 DoS 面）。

**生命周期与状态一致性（MED）**
- `_closing` 闩锁：cleanup 让出点期间重连成功路径不再复活
  `_check_gateway_timeout` 循环（泄漏 task）。
- WS `_cmd_unbind`：sleep 让出后**重解析**条目（reload 竞态下旧 manager
  已清空 devices，remove_device 整体 no-op → 幽灵设备复活）；本地删除
  失败如实回 `ok:false`（原唯一谎报点）。
- WS `_persist_token`：写成功后回灌内存令牌（热同步覆写窗口）；一个
  enabled 条目都没命中时也回滚内存（原"空转正常结束"路径=静默不持久化，
  小程序已存新令牌/重启回退旧令牌的 401 漂移从此路漏出）。
- 配置流"忽略"按钮整体空转实锤：HA ignore_flow **另起新流**只带原流
  unique_id，旧实现读 `self.context`（新流里恒无 gateway_sn）→ 忽略永不
  生效、重启卡片复活。发现流补 `async_set_unique_id`，ignore 步按
  user_input→context 顺序取 SN 并执行 async_ignore_gateway。
- `add_gateway`（选项流）三连修：create_entry(data={}) 会清空条目全部
  options（用户配过的 WS 端口/令牌被抹）→ 原样保留；显式 reload 与
  update-listener 双路径重载 → 删显式；顺手写 unique_id（撞车按已配置
  回显）。
- `persist.py` 内层类型过滤：mapping 值非字符串（base_entity .lower()
  炸）、setpoints 值非 dict（number 实体 __init__ 炸→整平台 setup 失败）
  两类手工编辑/半损坏脏数据逐键丢弃+告警。
- cover `is_closed` 接入 sensor 同款 15 分钟时效判据（SENSOR_TIMEOUT_
  MINUTES）：网关长期失联不再永久冻结最后已知值与 sensor 矛盾显示；重启
  恢复快照获 15 分钟信任窗（与 v1.6.8 恢复设计自洽）。

**健壮性与口径（LOW）**
- 握手 `ws.prepare()` 的计数递减移入 finally：CancelledError（STOP 级联/
  runner 强拆）不再泄漏预约槽，攒满 4 个即本实例永久 503 的路径封死。
- 设备状态广播 task 登记 `_bg_tasks`、stop 时统一取消（"Task was
  destroyed" 尾噪；帧序由 aiohttp _send_lock FIFO 保证，无需额外排队）。
- `set_position/speed/strength` 非法参数从"静默按 0 下发"改为拒绝
  （0="关窗"是反向动作，误执行比失败更糟）。
- 003 绑定回执 id 匹配前 `_norm_cmd_id` 归一（JSON 浮点 id `12.0` 与登记
  键 `12` 失配丢回执）。
- cover/number/sensor 移除路径补 unique_id 优先定位（button v1.6.3 定案
  同款）：配对后秒级解绑时实体未获派 entity_id 不再悬挂注册表条目、
  重配对永久缺实体的竞态封死。
- 无 SN 安装分支查重（连点"下一步"不再造多个空条目）+ ensure 任意异常
  不再打穿"不阻塞安装"承诺；WS 端口选项拒绝本栈保留口 2022/8099/8123/
  1883（撞口 bind 失败属静默失联）；strings/zh-CN 补 invalid_ws_token、
  ws_port_reserved、required、already_configured 四条缺失文案。
- `start_pairing` duration schema 收 10-300s（服务调用与 UI 选择器同界；
  003 报文不携带时长，纯本地兜底）；`refresh_devices`/
  `check_gateway_status` 描述纠偏为如实语义（空操作/仅日志，行为未变）。
- CI warm-mirrors 四修：OCI 平台过滤 `arm64`≠`aarch64`（旧过滤永不命中
  落 ms[0] 可能取到 attestation 摘要）、MAN/BLOBS 判空防"ok=0 fail=0"
  假绿、计数按 arch 归零、1ms 改单轮+300s 一次性复查（密集短重试对
  分钟级闪断无效且反触发限流）。

**文档**
- `CLAUDE.md` 命令表线值勘误：open/close/stop 实为 "100"/"0"/"101"
  （字符串；旧表 0/1/2 是废弃固件时代记载，v1.6.17 已对照固件实证）。
- ws_gateway 文档字符串纠偏（set_token 不触发 reload，热同步语义）。

## [1.6.18] - 2026-09-03

### 修复（Web UI 侧边栏启动失败：nginx 抢绑宿主 80——v1.6.4 半截工程实锤）

现场日志（v1.6.17，2026-09-02）：`bind() to 0.0.0.0:80 failed (98: Address
in use)` ×8 + `still could not bind()` → nginx master 直接退出，8099 连坐，
侧边栏全挂；mosquitto/mDNS/集成一切正常。根因：alpine nginx 包自带
`/etc/nginx/http.d/default.conf`（`listen 80 default_server; listen [::]:80;`），
被重写版 nginx.conf 的 `include /etc/nginx/http.d/*.conf` 拉入，而
host_network: true 使这个默认站一直绑的是**宿主** 80——宿主 80 空闲时表现为
"插件白占 80"（NAS 部署副作用），被占时（DSM 反代等常态）bind 失败打死整个
nginx。v1.6.4 的 Dockerfile 注释"移除默认 server 块"只删了 nginx.conf 内嵌
默认块，从未删过 http.d 文件，属静默失效面（此前所有版本都带病）。

- `Dockerfile`：构建期 `RUN rm -f /etc/nginx/http.d/default.conf` + 定案注释。
- `run.sh`：启动期兜底清扫 http.d 中一切 `listen 80/[::]:80` 杂散 conf
  （防基础镜像或 apk 升级带回）；nginx 失败改"5 秒重试一次"（宿主服务重启
  竞态窗口）后再打印 `netstat` 占用取证，不再只留 syntax-ok 假象。
- 回归钉桩 `tests/test_ingress_port80.py`：Dockerfile rm 行 / nginx.conf 重写
  段零 listen / 清扫先于 nginx 启动 / 模板与 heredoc 仅监听 8099 / 失败路径
  带重试与取证，共 7 项断言防复发。
- README 新增「侧边栏打不开/bind 80」FAQ。

### 改进（安装提速 v2：镜像主源切国内加速 + CI 镜像站自动预热）

用户实报"用 Gitee 仓库在 HA 里装插件仍特别慢"。拨测定案：慢不在 Gitee——
商店元数据 git 包 <1MB 秒级；真正大头是 Supervisor 拉 **42MB 运行镜像**走
容器 Registry，而 **Gitee 无镜像仓库服务**，此步与商店源地址无关（v1.6.17
及之前 image 指 ghcr.io 境外直连，家宽实测 ~84KB/s≈8 分钟且常超时）。

- **家宽同链路实测对比**：ghcr.io ~84KB/s；v1.6.16 主源 ghcr.nju.edu.cn
  0.02~0.1MB/s 波动大、新 tag 冷缓存回源偶发 404；**ghcr.1ms.run（毫秒
  镜像）4.6~5.2MB/s，全镜像≈10s**，匿名 token 流程，双架构/版本/latest/
  历史 tag 全链路验证 200；同 IP 短时间 ~150MB 测试级流量会触发其数十
  分钟 404 惩罚窗（疑单 IP 限流）后自愈，正常单次安装 42MB 不触发——
  主源仍定 1ms.run，nju 列第一备源，README FAQ 给出换源步骤。
- `config.yaml`：`image:` 主源切 `ghcr.1ms.run/fangwenyi-dev/{arch}-
  huijian-mqtt-broker`；注释定案 Supervisor **image 单 URL、无原生多源
  故障转移**，手动换源三级（1ms.run → nju.edu.cn → ghcr.io）与商店
  "检查更新"刷新缓存前置步骤全部写入注释与 README FAQ。
- **CI 新增 `warm-mirrors` 作业**（needs manifest、continue-on-error 不
  阻塞发布）：每次发版自动把新版本双架构全部 blobs 经 1ms.run 与 nju
  完整拉一遍预热边缘缓存——把"多路径"落到发布环节：客户无论走主源还是
  手动换到备用源，首装即热缓存，消掉冷缓存 404/慢回源概率。
- 加载项 README FAQ 重写：讲清"Gitee 商店源 ≠ 镜像下载源"的两段式下载，
  给出检查更新→手动换源→等仓库切换主源三步自助恢复路径。
- 版本同步 bump：config.yaml / version.json / index.html / manifest.json
  → 1.6.18（镜像本体不变，Supervisor 按新版本号才会重新拉取换源后的镜像）。

## [1.6.17] - 2026-09-03

### 修复（小程序 ↔ 插件联审：四路独立审计 × 一手复核定案的 WS 联动缺陷批）

流程：按 dsh-review-loop 四路并行只读审计（消息契约层/业务语义联动层/
发现与网络配置层/握手会话层），所有 HIGH/MED 结论均由父代理对照固件
`app_ws_gateway.c`/`app_protocol_bridge.cpp` 一手复核后才动手。
**结论：协议骨架（cmd/type 键、令牌子协议握手、错误文案、-1 约定、
帧限/槽位/心跳）三方逐字对齐**，真实缺口集中在视图层与解绑闭环。

#### 插件侧（本仓库）

- **WS 解绑幽灵设备（HIGH）**：`_cmd_unbind` 此前只发 003 bind=0 即
  ack ok——本地删除在插件里由「设备→删除」按钮流程负责，003 解绑
  确认分支明确注释"本地删除已由删除按钮流程完成"，而 **WS 通道不
  经过按钮**：小程序解绑后设备永远留在缓存/注册表/映射，下次
  get_devices 原样复活。修复：镜像按钮流程（发布 003 → 等
  GATEWAY_READY_DELAY → `remove_device` 本地删除并登记手动删除
  列表）；发布失败如实 ack `send failed`，不谎报 ok
- **设备视图无入界校验（HIGH）**：`device_ws_view` 把 r_travel=255
  （固件"未校准/离线"标记）原样显示为 255% 且推导 state=1（"已开"），
  battery 垃圾值（voltage=0 → 0、过期缓存 → 240）照发。修复：与固件
  同口径——position 仅接受 0..100 否则 -1、state 从钳制后值推导、
  电池 raw 仅接受 [80,140]（固件 BATTERY_RAW_MIN/MAX，12V 锂电
  9.5-12.6V 放宽 8-14V）否则 -1；HA 侧"未校准"sensor 语义不动
- **control 脏值透传（MED）**：`value:""`（空串）与 bool（str() 出
  "True"）此前放行发布 004；按固件语义拒为 missing fields；数字 0
  仍合法（falsy 误杀回归护栏测试钉住）
- **control 广播分歧（MED）**：映射缺失广播分支跳过 connected=False
  网关——connected 是"1800s 无上报"业务口径，与 MQTT 发布成败无关；
  固件 P2 定式无条件向全部网关发布。已对齐
- **gateway_list online 比固件乐观（MED）**：固件 900s 无上报即显示
  离线（GATEWAY_OFFLINE_TIMEOUT_SEC），插件 connected 位 1800s 才灭。
  WS 视图层新增 `WS_GATEWAY_ONLINE_STALE_SECONDS=900` 双条件判定
  （connected ∧ 900s 内有真实上报），HA 内部超时不动
- **手动配对即时推送缺失（MED）**：003 绑定确认走 add_device 直达，
  不经 update_device_status 的 device_update 推送漏斗——新设备要等
  下次上报才出现在小程序。绑定分支补一次监听器通知（全 -1 视图，
  与固件 pair 后推送语义等价）
- **set_token 持久化失败漂移（LOW）**：固件 NVS 写失败回滚运行时
  令牌；插件此前只告警——会形成"小程序已存新令牌、HA 重启回退旧
  令牌"的永久 401。补同口径回滚
- **槽位检查非原子（LOW）**：`len(_clients)>=4` 与 prepare 后入册之间
  有 await 挂起点，并发握手可瞬时超 4；补在途握手预约计数
- **重连风暴日志刷屏（LOW）**：aiohttp AppRunner access_log 默认每
  连接一条 INFO，改 access_log=None（本模块已有中文连接/断开日志）
- **文档**：options 端口文案加"改端口=直连失联"警示（微信 mDNS 不透传
  TXT，小程序恒拨 9001）；加载项 README FAQ 补四条——连上但列表为空
  （半开口径）、端口耦合、与固件共存实例区分、huijian.local A 记录
  冲突提示

#### 小程序侧（E:\AI\ha-yy\weichat-huijian-hz，同批修复）

- **发现服务名恒 undefined**：读 `res.name`，当前微信 API 字段是
  `serviceName`（真机日志"发现服务: undefined"根因）；补读正确字段
  + 剥 mDNS 后缀 + 按 IP+实例名去重（固件/插件共存时第二台不再被藏）
- **配对失败无感知**：`pair_ack ok:false` 此前只 console，页面照旧
  轮询 60 秒黑洞才报"未发现新设备"；新增 `EVENT_PAIR_ACK` 事件并由
  网关页消费——被拒立即退出配对态并 toast 原因；`type:"error"` 同样
  透传 UI
- **重连阶梯被无限续命**：真机日志"第1→4次→回到第1次"根因实锤——
  页面 onShow/前台恢复走 `connect()` 默认手动语义清零计数且不清在途
  定时器；`connect()` 入口统一清 `_reconnectTimer`，三处自动语义调用
  点（index/app.js/broker-gateways.checkConnection）改传
  `connect(false)`，仅「重连」按钮保留手动语义
- **改令牌泄漏僵尸连接**：broker-setup 改令牌/换网关流程调
  `_cleanup()` 只丢引用不 close——服务端旧连接占槽最长 300s（满 4 槽
  即 503 拒新），且继续吃 device_update；`_cleanup` 补幂等 close
- **fail 回调断自动链**：`wx.connectSocket` 的 fail 在部分平台是唯一
  失败信号，此前不调 `_scheduleReconnect`——自动重连静默死亡；补上

### 测试

- 新增 9 项回归：position 255/越界/字符串形态、battery 固件域内外、
  control 空串/bool 拒绝与 0 值护栏、广播含离线网关、gateway_list
  900s 新鲜度、unbind 本地闭环与发布失败如实 ack、set_token 回滚、
  配对通知记账；全量 **231 通过**，py_compile/JSON 校验绿

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
