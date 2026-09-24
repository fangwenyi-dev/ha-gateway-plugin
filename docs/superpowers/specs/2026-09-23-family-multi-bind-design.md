# 家庭多人绑定（owner + member）跨三仓设计

- 日期：2026-09-23
- 状态：**待用户审**（审过后转 writing-plans 出实施计划）
- 涉及仓：hub `E:\AI\huijian-cloud-hub`（HEAD `95e9769` v0.2.4）、加载项 `E:\AI\huijian-gateway-plugin`（HEAD `812f097` v1.7.45）、小程序 `E:\AI\ha-yy\weichat-huijian-hz`（HEAD `817a808` v1.4.25）
- 目标版本：hub **v0.2.5** / 加载项 **v1.7.46** / 小程序 **v1.4.26**，**同批发一版**（用户 2026-09-23 拍板）

---

## 0. 背景与现状证据（全部实测行号）

用户诉求："我有两个手机、两个微信，能不能同时绑定一个 HA" —— 现在**不能**。

| 事实 | 证据 |
|---|---|
| 一个实例只有一个归属 openid（单值字段） | hub `src/store.js:143`（`ownerOpenid: null`）、`:186`（`it.ownerOpenid = openid`） |
| 第二个微信号绑定被拒 | `store.js:185` → `already_bound`；`src/server.js:110` 映射 **409** |
| 每次取状态/控制都校验归属 | `server.js:117`（/state）、`:123`（/cmd）→ `store.owns()`（`store.js:193-196`，严格相等单值） |
| hub **没有解绑端点** | 全仓 grep `unbind\|解绑` 在 `src/`、`tools/` **0 命中** |
| 小程序"解绑"只清本机存储 | `miniprogram/utils/gw-router.js:187-190` → `utils/cloud-gw.js:67-71`（`wx.removeStorageSync`） |
| 一台手机只能云绑一个 HA | `cloud-gw.js:14`（`STORAGE_KEY='gwCloud'`）、`:59-65`（`setBinding` **整键覆写单对象**） |
| 两端都没有多人半成品 | 全仓 grep `member\|owners\|role\|invite` 在 hub / 插件 / 小程序 **0 命中**（插件侧 `owner` 仅 `discovery.py:103-105` 的 HA 条目归属，无关） |
| 二维码载荷与 6 位码格式两端各写一份、无对账测试 | 插件 `www/js/huijian.js:70`（`'HUJIAN-BIND:1:'`）↔ 小程序 `cloud-gw.js:112-113`（正则 + 版本位只认 `'1'`）；两侧测试互不引用对方仓 |

### 0.1 同批必须修掉的实发缺陷（线上 v1.7.45 就有）

`www/js/huijian.js` 里 **`loadRemoteControl` 被定义了两次**：`:170-179`（v1.7.41 新版，走统一渲染出口 `applyHubStatus`，`:127-168`）与 `:207-245`（v1.7.37 旧版残留）。JS 函数声明后者覆盖前者 ⇒ **页面加载与 30s 无感刷新走的都是旧版**：

- `hubCodeExp`（「已过期，点右边的二维码换新码」/「剩余 N 分钟」）**永不显示**；
- 「纳管网关 N 台 · M 个子设备」不显示（旧版只写 `info.gatewaySn`，`:232`，不调纯函数 `hubGatewayText()`，`:112-124`）；
- 只有点二维码那一下（POST 路径 `:85`）才走新版。

**为什么 940 条测试全绿**：结构钉用 `index("function loadRemoteControl(")` **只取第一处**（`tests/test_v1737_hub_ui.py:51-63`、`tests/test_v1738_hub_qr_ui.py:52-63`），而"除统一出口外不得有其他函数直调 `renderBindQr`"的反钉（`test_v1738_hub_qr_ui.py:93-107`）也因此漏判旧版的 `:225/:234/:242` 三处直调 ＝ **钉取第一处 + 死码凑数**的假绿。

不修这条，本批新增的成员数/角色/成员码字段在页面加载时同样不会渲染。

---

## 1. 已拍板的决定（用户 2026-09-23）

| # | 决定 | 选择 | 理由 |
|---|---|---|---|
| 1 | 发版编排 | **hub mirror 与多人绑定同批发一版** | mirror 生效前每次发版都让全员重扫；同批只掉绑一次。且注册表结构迁移与镜像载荷同批设计，不必做两次兼容 |
| 2 | 权限模型 | **owner + member 分级** | 必须有人能移除成员，否则码泄露一次就永久多一个能开窗的人，且无人能收回 |
| 3 | 邀请入口 | **HA 面板生成成员码** | 复用现成二维码链路（`qr.js` + `/agent/bindcode`），改动最小；家人不在家也能用——把二维码截图微信发过去 |
| 4 | 附带范围 | **修"一台手机只能云绑一个 HA"** | 与多人绑定共用同一套绑定存储改造，同批做最省 |
| 5 | `huijian.js` 重复定义 | **同批修** | 否则新功能一半不可见 |
| 6 | 成员码语义 | **10 分钟一次性 + 成员上限 8** | 与现有 owner 码同口径，最简单最安全 |
| 7 | 跨仓契约钉 | **加** | 现在一侧把载荷版本位升到 2，另一侧不会红 |

其他默认值（用户未反对，按此实现）：**成员上限 8 人**；**owner 可踢任何 member**；**member 只能退自己**；**owner 不能退自己**（否则实例无主）。

---

## 2. 数据模型（hub `src/store.js`）

选定 **A1：同文档加 `members[]`**。

```
instances[instanceId] = {
  instanceId, sn, fw, secretHash,
  ownerOpenid: string|null,        // 语义完全不变
  members: [{ openid, at }],       // 新增；上限 HUB_MEMBERS_MAX = 8
  bindCode, bindExpire,            // owner 码（现有）
  memberCode, memberCodeExpire,    // 新增：成员码，与 owner 码**分开存**
  states: {}, createdAt
}
```

**为什么成员码必须是独立字段**：现有 `rotateBindCode`（`store.js:172-179`）直接覆写 `bindCode`，而旧码**当场作废**。若成员码复用同一字段，owner 点一次「添加家人」就会把自己手上正在扫的 owner 码作废 —— 这是 v1.7.41 已经踩过的形态（"刷新只能由用户显式触发"）。

**迁移**：`_load()`（`store.js:26-36`）直接 `this.instances = raw.instances`，老文档没有 `members` ⇒ 新增 `_normalize()` 在 `_load` 与 `adoptFromMirror`（`store.js:101-130`）两处统一补齐 `members: []`、`memberCode: null`、`memberCodeExpire: 0`。**所有读路径此后可以假定字段存在**。

**镜像自动兼容（已核实，不需改 mirror.js）**：`pushMirror()`（`store.js:76-85`）是 `Object.assign({}, v, { states: {} })` 整实例浅拷贝 ⇒ `members` 自动进镜像；载荷仍是 `{v:1, instances}`，**版本号不升**。成员变更属低频事件（每人一生几次），不违反"状态不进镜像"的配额纪律（`store.js:205-208`、`tests/mirror.js:209`）。

**否掉的两个方案**：
- A2 独立成员集合：`/state`、`/cmd` 每次多一次 DB 读（或自建缓存），配额随"人数 × 调用次数"涨 —— 正好踩 20 万调用配额的方向；镜像要带两个集合、采纳顺序更复杂。
- A3 家庭组实体（group ← instances/members）：为"多 HA 归一个家庭"预留，当前无此需求（YAGNI），小程序还要多一层选择。

---

## 3. 协议（hub v0.2.5，全部向后兼容）

`openid` 取法不变：`server.js:55` `openidOf()` ＝ `x-wx-openid` 头优先、回退 `body.openid`。

| 端点 | 改动 | body | 成功 | 失败（err / HTTP） |
|---|---|---|---|---|
| `POST /agent/register` | 不变 | `{installKey,sn,fw}` | 200 | `install_key` / 403 |
| `POST /agent/bindcode` | **加 `kind:'owner'\|'member'`，不传＝owner** | `{instanceId,secret,kind?}` | 200 `{ok,bindCode,expiresInSec,kind}` | `bad_secret` / 403；`unknown_instance` / 404 |
| `POST /bind` | **按码类型分流**，返回体加 `role` | `{bindCode}` | 200 `{ok,instanceId,sn,role}` | `no_openid` / 401；`code_invalid` / 404；`already_bound` / 409；**`members_full` / 409**；**`no_owner` / 409** |
| `POST /unbind`（新，**openid 鉴权＝本人退出**） | member 退自己；owner 调 ⇒ 拒 | `{instanceId}` | 200 `{ok,removed,remaining}` | `no_openid` / 401；`forbidden` / 403（与该实例无归属，**含已退出的人再退**——前任成员与陌生人同形，不泄露"你曾是成员"）；`owner_cannot_leave` / 409；`unknown_instance` / 404 |
| `POST /agent/members`（新，**实例凭据鉴权**） | 面板列成员 | `{instanceId,secret}` | 200 `{ok,ownerMasked,members:[{mid,openidMasked,at}],membersMax}` | `bad_secret` / 403；`unknown_instance` / 404 |
| `POST /agent/unbind`（新，**实例凭据鉴权**） | 面板（＝主人）踢人 | `{instanceId,secret,mid}` | 200 `{ok,removed,remaining}` | `bad_secret` / 403；`unknown_member` / 404 |
| `POST /state` | 鉴权改 `canAccess()` | 不变 | 200 | `forbidden` / 403 |
| `POST /cmd` | 鉴权改 `canAccess()` | 不变 | 200（`offline`/`timeout` 仍 200） | `forbidden` / 403 |
| `GET /healthz` | 加 `membersTotal`（**不含 openid**） | — | 200 | — |
| `GET /agent/ws` | 不变 | query `instanceId,secret` | 101 | 401 后 destroy（`server.js:173-175`） |

**store 侧新方法/改动**
- `rotateBindCode(instanceId, kind='owner')`：按 kind 写对应字段对；owner 码轮换**不得**动成员码，反之亦然。**`kind='member'` 且 `ownerOpenid` 为空 ⇒ 拒发，回 `no_owner` / 409**（边界：没有主人就发家人码，会让第一个扫码的人成为"无人能管理的 member"——他既不能踢人也不能退成 owner，实例就此锁死）。
- `bindByCode(code, openid)`：先按 owner 码匹配（现有语义：已绑他人 → `already_bound`；同一 owner 重绑幂等），再按成员码匹配（已是成员 → 幂等 ok；`members.length >= HUB_MEMBERS_MAX` → `members_full`；否则追加）。**成员码扫完即清**（一次性），与 owner 码同口径。成员码绑定同样要求实例已有 owner（`no_owner`），双保险。
- `isOwner(instanceId, openid)` / `isMember(instanceId, openid)` / `canAccess(instanceId, openid)`（＝前两者之一）；`owns()` 保留为 `canAccess` 的别名以免调用点漏改，但**新代码一律用 `canAccess`/`isOwner`**。
- `leaveInstance(instanceId, openid)`：本人退出。无归属 → `forbidden`；actor 是 owner → `owner_cannot_leave`；不在 members → `unknown_member`。
- `removeMemberByMid(instanceId, mid)`：主人踢人，**只由 `/agent/unbind`（实例凭据）调用**。
- `listMembers(instanceId)`：返回 `{ownerMasked, members:[{mid, openidMasked, at}], membersMax}`。
- `memberMid(openid) = sha256(openid).slice(0,12)`：稳定、不可逆、可公开展示的**成员句柄**。

**⚠️ 规划阶段查出的设计缺陷（已在本版修正）**：`/members` 与踢人**不能**按 openid 鉴权——
openid 只由云托管注入到**小程序**发来的请求（`server.js:55` `openidOf`），**加载项根本没有 openid**，
它只有 instanceId+secret。所以"面板列成员/踢人"必须走**实例凭据**的 agent 通道（与 `/agent/bindcode` 同口径：
`bad_secret` 403、未知实例也不给 404 以免留存在性探测面）。面板在 HA 局域网内、且要经 HA 鉴权才能调到
插件 REST，等价于"主人本人操作"。
第二个连带问题：面板只看到**掩码** openid，无法据此定位要踢谁（掩码可能撞）⇒ 引入 `mid` 句柄。
`/unbind`（小程序侧）因此收窄成**只能退自己**，不接受 target 参数——避免"body.openid 既是调用者身份兜底、
又当踢人目标"这种一名两用的提权面（`openidOf` 在无 `x-wx-openid` 头时会回退读 `body.openid`）。

**凭据不回显纪律**（沿用三端口径）：openid 属身份标识，`/members` 与 `/healthz` 一律掩码（`oX9…3f`：前 3 + 后 2），日志同样只记掩码；`bind ok` 日志现有写法 `openid.slice(0,6)+'…'`（`server.js:111`）保持。

**二维码载荷不变**：仍是 `HUJIAN-BIND:1:<6 位>` ⇒ 小程序 `parseBindPayload`（`cloud-gw.js:109-115`）零改动。成员码与 owner 码在载荷上不可区分，**由 hub 按码查表决定角色**（不在载荷里写角色，避免载荷被篡改后提权）。

---

## 4. 加载项 v1.7.46

**`custom_components/window_controller_gateway/hub_client.py`**
- `refresh_bind_code(kind='owner')`：`POST /agent/bindcode` 载荷加 `kind`（现有实现 `:355-389`，载荷在 `:367-370`）。
- **自动补发只针对 owner 码**：`_renew_bind_code_if_stale`（`:391-406`，调用点 `_session_once:474`、`_keepalive_loop:511`）保持不变；成员码**只由面板显式生成**，不进自动轮换（理由同 §2：自动轮换会让 owner 已截图发出去的码失效）。节流常量 `BIND_CODE_RENEW_MIN_INTERVAL_S=120`（`:48`）继续只管 owner 码；**面板显式生成成员码不受节流**（与"面板点二维码不受节流"同口径）。
- `status_view()`（`:621-636`）新增键：`memberCode`、`memberCodeExpiresIn`、`memberCodeExpired`、`members`（掩码列表）、`membersCount`、`membersMax`。现有键全部保留（`connected/instanceId/bindCode/bindCodeExpiresIn/bindCodeExpired/gatewaySn/gateways/hub/lastError`）。
- 身份文件**不改**（`load_identity:106-122` / `_save_identity:340-347` 仍只存 `instanceId/secret/bindCode/bindCodeAt`）——成员关系只在 hub 侧，落本地会与 hub 真相分叉。
- 新增 `list_members()` / `remove_member(mid)`：调 hub **`/agent/members`**、**`/agent/unbind`**（都带 instanceId+secret，加载项没有 openid）；失败只降级为 `last_error`，不影响长连（与换码失败同口径）。老 hub 无这两个端点 ⇒ 404/异常时置 `membersSupported=False`，面板据此**禁用**成员区（不显示成"读取失败"）。

**`api.py`**（现有 hub 路由：`GET .../hub` `:158`、`POST .../hub/bindcode` `:179`；单例取值 `_hub_client` `:142-147`，键 `const.HUB_DATA_KEY` `const.py:265`）
- `POST /api/window_controller_gateway/hub/bindcode` 接受 `{"kind":"member"}`，回 `status_view()` + `enabled` + `refreshOk`（形状不变）。
- 新增 `GET /api/window_controller_gateway/hub/members` → `{enabled, ok, ownerMasked, members[]}`。
- 新增 `POST /api/window_controller_gateway/hub/members/remove`（body `{"openid": "..."}`）→ 同上 + `removed`。
- 鉴权沿用现状（HA 默认需鉴权 + nginx 注入 token，`run.sh:386-388`、`ingress.conf:29-31`、源网段白名单 `run.sh:488-494`）。

**面板 `www/index.html` + `www/js/huijian.js`**
- `#remoteCard`（`index.html:85`，标题「远程控制（慧尖云）」`:86`）内新增「家庭成员」区：`hubMembers`（列表容器）、`addMemberBtn`（「添加家人」）、`hubMemberQr`（成员码二维码）、`hubMemberCode`、`hubMemberExp`、每个成员一行「移除」按钮。
- 成员码二维码复用 `window.HjQr.render`（`huijian.js:99`）与同一载荷前缀常量 `:70`。
- **统一渲染出口 `applyHubStatus`（`:127-168`）扩展为唯一渲染点**，成员区也在其中渲染；**删除 `:207-245` 的旧版 `loadRemoteControl`**。
- 文案口径：标签「家庭成员」，空态「只有你一人」，成员行显示掩码 openid + 「家人」，owner 行显示「主人」+ 掩码（**面板不知道"你是谁"——HA 侧没有 openid，不能写"（你）"**）；成员码提示「10 分钟内有效，扫完即失效」；已满 8 人时按钮禁用并提示「家庭成员已满（8 人）」；**尚无主人时「添加家人」按钮禁用**并提示「请先完成主人绑定」（对应 hub 的 `no_owner`）。
- 命名纪律：文案一律「LoRa 网关」；指路小程序必须写可搜索名「小慧语音」。

---

## 5. 小程序 v1.4.26

**`utils/cloud-gw.js`**
- 绑定存储改**分桶**：`STORAGE_KEY='gwCloud'` 的值从单对象改为
  `{ v:2, active: instanceId, bindings: { [instanceId]: { sn, role, at } } }`；
  `getBinding()` 返回 active 那条（保持现有调用点签名不变），新增 `getBindings()` / `setActiveBinding(instanceId)`；
  **一次性迁移**：读到无 `v` 或 `v===1` 的老单对象（`{instanceId,sn}`）就搬进 `bindings` 并置为 active，然后回写。
  仓内已有多条目存储先例可照抄：`miniprogram/app.js:153,173,200,220,230,240` 的 `haAccounts` 数组。
- `bindByCode(code)`（`:73-81`）记录 hub 回的 `role`，写入对应桶并把 active 指过去。
- 新增 `unbind(instanceId)` → `POST /unbind`；`clearBinding()`（`:67-71`）改为只清指定桶（保留其他 HA 的绑定）。
- `callHub`（`:24-47`）**本批不加超时**（现有缺陷，记入 §9 已知限制，避免范围膨胀）。

**`utils/gw-router.js`**
- `unbindCloud()`（`:187-190`）改 async：先真调 hub `/unbind`，**失败也清本机**，但回 `{ok:false, err}` 让页面区分文案（"已解除（云端可能仍保留，稍后自动清理）" vs "已解除"）。
- 云模式选路（`connect:123-145`、`_startCloud:216-227`）使用 active 绑定；`isCloudBound`（`:171-173`）判"有无 active"。
- 新增 `switchCloudBinding(instanceId)` 供多 HA 切换。

**`pages/broker-gateways/`**
- `.wxml` 绑定卡（`:105-125`）加：我的角色（「主人」/「家人」）、多 HA 时的切换入口、成员数（若 hub 回）。
- `.js`：`refreshRemote()`（`:166-178`）带角色；`doUnbindCloud()`（`:257-268`）改 await 真解绑，按角色分文案 —— **owner 的"解绑"只清本机、云端归属不变**（owner 不能退自己），文案必须说清，否则用户以为解绑了而家人仍能控制；`_bindErrText`（`:271-281`）补 `members_full`（「家庭成员已满（8 人），请让主人先移除一位」）、`owner_cannot_leave`、`not_owner`、`unknown_member`。

---

## 6. 兼容矩阵与发版顺序（关键）

| 组合 | 行为 | 处置 |
|---|---|---|
| 老插件 × 新 hub | 不传 `kind` ⇒ owner 码，行为完全不变 | 无需处理 |
| **新插件 × 老 hub** | 老 hub 忽略 `kind`，成员码请求会**覆写 owner 码**（把用户正在扫的码作废） | **发版顺序必须 hub 先上**；插件侧判据：`/agent/bindcode` 返回体缺 `kind` 字段 ⇒ 面板提示「云端版本过旧，暂不支持添加家人」并**禁用**「添加家人」按钮（不静默失败） |
| 老小程序 × 新 hub | `/bind` 多回 `role` 字段，老小程序忽略 ⇒ 正常绑定为 owner 或 member；解绑仍只清本机（hub 侧保留） | 可接受；文案在 v1.4.26 补齐 |
| 新小程序 × 老 hub | `/unbind`、`/members` 404 ⇒ 降级为"只清本机"+提示 | 与上一条同一判据（`not_found` 视为云端过旧） |

**发版顺序（有序同批）**：
1. hub v0.2.5 部署（前提：mirror 凭据已就位，见 §7）→ 灰度 100% → `/healthz` 验 `mirror.enabled=true`；
2. **手动重启一次** → 验 `mirror.adopted.adopted=true` 且 `instances` 不归零；
3. 小程序**重扫一次码**（mirror 首次生效带来的最后一次重扫）；
4. 加载项 v1.7.46（CI 九段 + 双推 + GitHub/Gitee Release）；
5. 小程序 v1.4.26（`npm test` + 推 + Release；体验版上传由用户做）；
6. 真机端到端（§8.5）。

---

## 7. 运维与配额（实测配置为准）

云托管服务 `huijian-hub` 现配置（MCP `queryCloudRun detail` 实测，2026-09-23）：

| 项 | 现值 | 处置 | 理由 |
|---|---|---|---|
| `MaxNum` | **5** | **改 1** | 多副本会让容器本地盘注册表互相覆盖（register 落 A、握手落 B），并触发加载项熔断 `HUB_REREGISTER_FUSE=3`（`hub_client.py:56`）。只会省钱不会花钱 |
| `MinNum` | 0 | **保持 0** | mirror 生效后缩容到 0 只掉几秒长连（加载项自动重连 + 从云开发数据库找回注册表）；改 1 会让 0.25C/0.5G 变 7×24 常驻，属套餐外按量固定支出 |
| `EnvParams` | 只有 `CLOUDBASE_APIKEY`/`CLOUDBASE_APIKEY_ID` | **加 `TENCENTCLOUD_SECRETID`/`TENCENTCLOUD_SECRETKEY`**（+ 必要时 `TCB_ENV`） | 实测 `@cloudbase/node-sdk@3.18.3` 与 `@cloudbase/manager-node@5.8.8` 的 lib 里**都没有 apiKey 入口** ⇒ 平台注入的 `CLOUDBASE_APIKEY` 对 mirror 无用，只能走 CAM 密钥对 |
| `VolumesConf` | `[]` | 保持空 | 存储挂载在"云开发云存储"桶类型上必失败（平台 `mount.sh` 生成的 cosfs endpoint 缺 `http://`）；持久化靠 mirror |
| 部署记录 | 010（16:42:14，100%）、009（16:16，`ScaleStatus:"zero"`） | — | 009 缩容到零是 `MinNum=0` 的实锤；010 构建时刻早于 v0.2.4 落库 ⇒ 线上是 v0.2.3（healthz 无 `missing` 字段互证） |

**配额影响**：`/unbind`、`/members` 是"每人一生几次"的低频动作；`/state`、`/cmd` 调用次数不因成员数变化（成员共用同一份长连状态）。⇒ 270 次/人/月、20 万 ≈ 700 人·月的账**不变**；成员上限 8 也不改变装机侧调用量。

**待用户提供**：CAM `SecretId`/`SecretKey`（云开发控制台 → 授权管理 → 连接密钥，只显示一次）。两种落地方式由用户选：①自己在云托管控制台填两行自定义变量；②交给我经 MCP 写入 `EnvParams`（我不会回显，但值会留在会话记录里）。

---

## 8. 测试与守卫

### 8.1 hub（33 → 目标 ≥ 50，`npm test` = `node tests/run.js && node tests/mirror.js`）
新增用例（逐条可执行）：
1. `bindByCode` 用成员码绑定成功，返回 `role:'member'`，`members` 追加且带 `at`；
2. 同一 openid 重复扫成员码 ⇒ 幂等 ok，`members` 不重复；
3. 第 9 个成员 ⇒ `members_full`，HTTP 409；
4. member 调 `/state`、`/cmd` ⇒ 200（不再 403）；
5. 非 owner 非 member 调 `/state` ⇒ 仍 `forbidden` 403；
6. owner 踢 member ⇒ 该 member 后续 `/state` 403；
7. member 退自己 ⇒ ok；member 踢别人 ⇒ `not_owner` 403；
8. owner 退自己 ⇒ `owner_cannot_leave` 409；
9. `/members`：owner 可读、member 读 ⇒ `not_owner`；返回值**只含掩码**（断言不含完整 openid 字面量）；
10. `rotateBindCode(kind='member')` **不作废 owner 码**（反之亦然）—— 双向断言；
11. 成员码一次性：绑定成功后 `memberCode` 清空，同码再绑 ⇒ `code_invalid`；
12. 老注册表文档（无 `members` 字段）加载后可正常绑定/踢人（迁移兜底）；
13. `adoptFromMirror` 采纳的老载荷同样被规范化；
14. 镜像载荷含 `members`、仍不含 `states`、不含 secret 明文（扩 `tests/mirror.js:209` 那条配额纪律钉）；
15. `/healthz` 含 `membersTotal` 且**不含任何 openid**（扩 `run.js:279-301` 的无鉴权面不泄钉）；
16. `/agent/bindcode` 回 `kind` 字段（插件侧判据依赖它）；
17. **无主人时拒发成员码**：`kind='member'` 且 `ownerOpenid` 为空 ⇒ `no_owner` 409；此时用 owner 码绑定成功后再请求成员码 ⇒ 放行（这条钉的是"实例不会被锁死"）。

### 8.2 加载项（940 → 新增，`python3 -m pytest huijian_mqtt_broker/tests -q`）
1. `refresh_bind_code(kind='member')` 载荷带 kind、成功回填 `memberCode`/`memberCodeExpiresIn`；
2. **成员码不进自动轮换**：`_renew_bind_code_if_stale` 在成员码过期时**不发请求**（反钉）；
3. 面板显式生成成员码**不受 120s 节流**（与 owner 码面板路径同口径）；
4. `status_view()` 新键齐全且**不含完整 openid**（掩码钉）；
5. hub 回 404（老 hub）⇒ `list_members`/`remove_member` 降级不断连，`last_error` 记因；
6. api 三条新路由的**路由等式钉**（扩 `test_v1737_hub_ui.py:86-103` 的写法：从 `api.py` 抽实际注册 url 全集，与 `huijian.js` 真发出去的 path 逐字比）；
7. **重复定义钉（新）**：`huijian.js` 中 `function <name>(` 每个名字**出现次数必须 == 1**（扫全部函数名，不只 `loadRemoteControl`）；
8. **结构钉改"取全部匹配"**：`test_v1737_hub_ui.py:51-63`、`test_v1738_hub_qr_ui.py:52-63` 的 `_func` 抽取器改为"找到多处即报错"，杜绝"钉第一处 ⇒ 死码假绿"；
9. `renderBindQr` 直调反钉重新生效（旧版删除后应只剩统一出口一处）；
10. 面板成员区渲染：`applyHubStatus` 真跑（node 执行，照 `test_v1743_hub_singleton.py:196-242` 的 `hubGatewayText` 真跑写法）断言满 8 人禁用按钮、空态文案、掩码显示。

### 8.3 小程序（70 → 新增，`npm test`）
1. 老格式 `{instanceId,sn}` 一次性迁移为 v2 分桶，且 active 指向它；
2. 两个 HA 安装可并存，`switchCloudBinding` 切换后 `getBinding()` 返回对应桶；
3. `bindByCode` 落 `role`；
4. `unbindCloud()` 真发 `/unbind`（桩断言 path 与 body），失败也清本机但回 `ok:false`；
5. owner 解绑文案与 member 解绑文案不同（钉字面量）；
6. `_bindErrText` 四条新错误码各有中文文案（含兜底）；
7. 新测试文件必须挂进 `package.json` 的 `npm test` 链（`tests/all-tests-wired.test.js` 已有守卫，照它）。

### 8.4 跨仓契约钉（新增，用户已同意）
在插件 `tests/` 下新增 `test_v1746_cross_repo_contract.py`，沿用 `tests/test_v1742_hub_identity.py:57-70` 的"缺仓响亮跳过 rc=3"机制：
- 环境变量 `HUB_REPO`（已有先例，`tests/e2e/hub_lifecycle_driver.py:36-39`）+ 新增 `MINIPROGRAM_REPO`；
- 对账项：① 二维码载荷前缀/版本位（插件 `huijian.js:70` ↔ 小程序 `cloud-gw.js:112-113`）；② `/bind`、`/unbind`、`/members` 的 err 字符串全集（hub `server.js` ↔ 小程序 `_bindErrText` ↔ 插件 `last_error`）；③ `kind` 字段名（插件 ↔ hub）；④ 成员上限 8（hub 常量 ↔ 两端文案里的数字）；
- **元钉**：无 `MINIPROGRAM_REPO` 时该文件必须以 rc!=0 响亮跳过（照 `test_v1742_hub_identity.py` 真跑一次 shell 的写法），否则"跳过"等于门禁不存在。

### 8.5 真栈 e2e（18 → 新增 E 臂，`tests/e2e/hub_lifecycle_e2e.sh`）
起真 hub 进程 + 真 `HubClient` + 真 `/bind`：
- E1 owner 扫码绑定 ⇒ `role:'owner'`；
- E2 面板生成成员码（走真 `/agent/bindcode?kind=member`）⇒ owner 码仍可用（不作废）；
- E3 第二个 openid 扫成员码 ⇒ `role:'member'`，且 `/state` 200；
- E4 两个 openid 都能 `/cmd` 且**回执来自同一条长连**（不广播、不重复）；
- E5 owner 踢 member ⇒ 被踢者 `/state` 403 `forbidden`；
- E6 第 9 个成员 ⇒ `members_full`；
- E7 hub 重启（抹本地盘）后 mirror 采纳 ⇒ **owner 与全部 member 都还在**（这条同时验 §7 的持久化）。

### 8.6 变异清单（影子树逐条还原旧行为，各须精准红自己那条）
- M28 成员码复用 owner 码字段 → §8.1-10 红；
- M29 去掉成员上限 → §8.1-3 红；
- M30 `/unbind` 不校验 actor 是 owner → §8.1-7 红；
- M31 允许 owner 退自己 → §8.1-8 红；
- M32 老文档不补 `members` → §8.1-12 红；
- M33 `/members` 回完整 openid → §8.1-9 红；
- M34 `_func` 抽取器改回"只取第一处" → §8.2-8 红（这条钉的是钉本身）；
- M35 小程序解绑不发 hub → §8.3-4 红；
- M36 小程序分桶存储不迁移老格式 → §8.3-1 红；
- M37 `canAccess` 退回 `ownerOpenid ===` 单值 → §8.1-4 红 + e2e E3/E4 红；
- M38 去掉"无主人拒发成员码" → §8.1-17 红（这条变异造出的正是"实例锁死"形态）。

门禁全套（照 `.github/workflows/ci.yaml`）：`bash -n`、`compileall`、`ruff check --select F,E9,B --ignore B008,B905`、`pytest`、`node --check www/js/*.js`、e2e job；hub `npm test`；小程序 `npm test`。版本四源同步 + cache-buster；CHANGELOG 段落控制在 CI `head -50` 之内。

---

## 9. 不做（YAGNI）与已知限制

**不做**：家庭组实体、成员昵称/头像、owner 审批流、只读成员、跨 HA 的家庭、成员码多次使用、`callHub` 超时改造、hub 侧孤儿实例清理（`/healthz` `instances` 虚高那条，用户尚未拍板）。

**已知限制（写进对外文案）**：
1. **owner 手机丢失/换微信号** ⇒ 无人能管理成员。唯一出口是删 `/config/huijian_hub_identity.json` 让加载项重注册（全员重绑）。
2. 成员码是"能拍到 HA 面板的人就能成为家人"——一次性 + 10 分钟 TTL 是缓解，不是防护；面板在 HA 局域网内可达。
3. `callHub` 无超时（`cloud-gw.js:24-47`），弱网下解绑可能长时间无反馈。
4. 多副本仍不被支持（`MaxNum=1` 是硬前提）。
5. 正式版小程序能否走 LAN 明文 ws **仍未定**（旧"必拦"结论已撤回，需手机同网段实测），与本批无关但影响"家里人不在同一 Wi-Fi 时只能走云"的表述。

---

## 10. 风险与回滚

| 风险 | 处置 |
|---|---|
| 新插件 × 老 hub 把 owner 码作废 | 发版顺序 hub 先上 + 插件侧 `kind` 缺失即禁用按钮（§6） |
| mirror 凭据仍未就位就发 hub v0.2.5 | 部署前用 `/healthz` 的 `mirror.missing` 自证；缺则**不发流量**，停在旧版本 |
| 多人绑定引入鉴权放宽（member 可控制） | `canAccess` 只在 `/state`、`/cmd` 两处；`/unbind`、`/members`、`/agent/*` 仍严格 owner/secret；e2e E5 钉"踢完立即 403" |
| 回滚 | hub 可 `traffic rollback` 回 010；插件/小程序各自回上一 tag。注册表结构是**加字段**，回滚到老 hub 也能读（老代码忽略 `members`） |
