# 家庭多人绑定（owner + member）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让一个 HA 安装（＝一个 hub 实例）能被最多 8 个微信号同时绑定与控制：第一个扫码的人是 owner，其余由 HA 面板签发的一次性「成员码」加入为 member；同时把小程序"一台手机只能云绑一个 HA"改成多绑定分桶，并热修面板 `loadRemoteControl` 重复定义导致 v1.7.41 渲染改进全是死码的缺陷。

**Architecture:** hub 侧在现有注册表实例文档上加 `members[]`（同文档，不新建集合、镜像载荷与版本号都不变），鉴权由单值 `ownerOpenid ===` 改为 `canAccess = isOwner || isMember`；成员码与 owner 码**分字段存放**，避免签发成员码时把用户正在扫的 owner 码作废。加载项侧走**实例凭据**（instanceId+secret）的 agent 通道列成员/踢人（它没有 openid），面板新增「家庭成员」区。小程序侧把绑定存储从单对象改成按 instanceId 分桶并带一次性迁移，解绑真通知 hub。三端同批发版，hub 先上。

**Tech Stack:** hub = Node.js 20 + 自造测试脚本（`t()/assert()` + `tests/lib.js` 的 `post/get/FakeAgent`）；加载项 = Python（HA 自定义集成）+ pytest + 原生 JS 面板（`www/js/huijian.js`，CSP 环境、自带 `qr.js` 编码器）；小程序 = 微信原生（`wx.cloud.callContainer`）+ node 测试脚本（`t()/ta()` 串行链 + 假 `wx`）。

**Spec:** `docs/superpowers/specs/2026-09-23-family-multi-bind-design.md`（已批准，含规划阶段修正的 agent 通道与 `mid` 句柄；执行时两份都要读）

## Global Constraints

- 仓路径：hub `E:\AI\huijian-cloud-hub`；加载项 `E:\AI\huijian-gateway-plugin`（代码在 `huijian_mqtt_broker/`）；小程序 `E:\AI\ha-yy\weichat-huijian-hz`（代码在 `miniprogram/`）。
- 目标版本：hub `0.2.4 → 0.2.5`；加载项 `1.7.45 → 1.7.46`；小程序 `1.4.25 → 1.4.26`。
- 成员上限 **8**（hub 常量 `HUB_MEMBERS_MAX`，加载项同名常量，两端文案里的数字由跨仓钉对账）。
- 成员码：**10 分钟一次性**，扫完即清；与 owner 码**分字段**（`memberCode`/`memberCodeExpire` vs `bindCode`/`bindExpire`）。
- 二维码载荷格式**不变**：`HUJIAN-BIND:1:<6 位>`（小程序 `parseBindPayload` 零改动）。
- 凭据不回显：openid 一律掩码 `前3…后2`；`/healthz` 与日志不得出现完整 openid；secret 永不下发到小程序、永不进日志（只 `cred_brief` 摘要）。
- 文案口径：一律「LoRa 网关」（不写 Matter）；指路小程序必须写可搜索名「小慧语音」。
- 加载项门禁（CI 同款，见 `.github/workflows/ci.yaml`）：`bash -n`、`python -m compileall`、`ruff check --select F,E9,B --ignore B008,B905`、`python3 -m pytest huijian_mqtt_broker/tests -q`、`node --check www/js/*.js`、e2e。
- hub 门禁：`npm test`（＝ `node tests/run.js && node tests/mirror.js`，本计划追加 `&& node tests/members.js`）。
- 小程序门禁：`npm test`（串行链，含 `tests/all-tests-wired.test.js` 漏挂守卫——新测试文件必须挂进 `package.json` 的 test 链）。
- **提交纪律：任何 commit / push / tag / Release 都等用户当次口令**；每个 Task 末尾的 commit 步骤仅在已拿到该批口令后执行，否则停在"工作树改动 + 门禁全绿"。
- 运维既成事实（不要再改）：云托管 `huijian-hub` 已 `MaxNum=1`、`MinNum=0`、mirror 已用子账号密钥（`QcloudTCBFullAccess`）打通并端到端验过（换 pod 后绑定存活、加载项不重注册）。
- **行号口径**：本计划所有 `文件:行号` 以各仓 **HEAD**（hub `95e9769` / 加载项 `812f097` / 小程序 `817a808`）为准。加载项与小程序的工作树已带本批前置改动（Task B1 已完成；小程序侧另有"云控制失败中文文案 + 删死码 `reconnect` + 注释纠正"），**实际行号会漂移**——一律按符号名（函数名/常量名/DOM id）定位，别按行号硬改。
- **回滚**：hub 侧 `manageCloudRun(action=traffic, trafficOp=rollback)` 回上一个稳定版；注册表改动是**加字段**，老 hub 读新库会忽略 `members`，所以回滚不需要清库。加载项/小程序各自回上一个 tag。

## File Structure

**hub** — `src/store.js`（注册表真相：`members[]` 规范化、成员码签发、绑定分流、归属判定、成员管理）、`src/server.js`（`/agent/bindcode` 加 `kind`、`/bind` 回 `role`、`/state`+`/cmd` 换 `canAccess`、新增 `/unbind`、`/agent/members`、`/agent/unbind`、`/healthz` 加 `membersTotal`）、`tests/members.js`（新，独立文件避免把 24 例的 `run.js` 撑到难读）、`package.json`（test 链 + version）、`README.md`（端点表）。

**加载项** — `www/js/huijian.js`（**先删重复定义** `:207-245`，再在统一出口 `applyHubStatus` 里加成员区渲染与成员码链路）、`www/index.html`（`#remoteCard` 内新增「家庭成员」区）、`custom_components/window_controller_gateway/hub_client.py`（`refresh_bind_code(kind)`、成员码状态、`status_view()` 新键、`list_members()`/`remove_member(mid)`）、`api.py`（bindcode 收 `kind` + 两条新路由）、新测试 `tests/test_v1746_panel_unique_funcs.py` / `tests/test_v1746_hub_members.py` / `tests/test_v1746_panel_members.py` / `tests/test_v1746_cross_repo_contract.py`、改 `tests/test_v1737_hub_ui.py` 与 `tests/test_v1738_hub_qr_ui.py` 的抽取器、`tests/e2e/hub_lifecycle_driver.py` 加 E 臂、`tests/test_v1742_hub_identity.py:40` 的防稀释计数上调。

**小程序** — `miniprogram/utils/cloud-gw.js`（绑定分桶 + 迁移 + `role` + `unbind`）、`miniprogram/utils/gw-router.js`（`unbindCloud()` 真通知 hub、`switchCloudBinding()`）、`miniprogram/pages/broker-gateways/broker-gateways.js` 与 `.wxml`（角色、多 HA 切换、解绑文案分支、错误码文案）、新测试 `tests/cloud-multi-bind.test.js`（挂进 `package.json`）、`package.json`（version）。

---

## Phase A — hub v0.2.5（必须最先完成并部署）

### Task A1: 注册表加 `members[]` 与老文档规范化

**Files:**
- Modify: `E:\AI\huijian-cloud-hub\src\store.js`（`_load` `:26-36`、`adoptFromMirror` `:126` 之后、`register` `:138-148`、导出 `:221`）
- Create: `E:\AI\huijian-cloud-hub\tests\members.js`
- Modify: `E:\AI\huijian-cloud-hub\package.json:9`

**Interfaces:**
- Consumes: `new Store(file, opts)`、`_save(opts)`、`sha256`
- Produces: 常量 `HUB_MEMBERS_MAX = 8`；`maskOpenid(s) -> string`（`前3…后2`，长度 ≤5 原样）；`memberMid(openid) -> string`（`sha256(openid).slice(0,12)`）；`Store#_normalize()`；实例文档新增 `members: [{openid, at}]`、`memberCode: string|null`、`memberCodeExpire: number`

- [ ] **Step 1: 写失败测试**（新建 `tests/members.js`，照 `tests/run.js:14-31` 的 `t/assert/startHub` 写法）

```js
// tests/members.js —— 家庭多人绑定（owner + member）行为钉。
// 与 run.js 同款：真起 hub（临时端口 + 临时 store）+ FakeAgent 真长连，不打桩协议。
const fs = require('fs')
const os = require('os')
const path = require('path')
const { createHub } = require('../src/server')
const { Store, HUB_MEMBERS_MAX, maskOpenid, memberMid } = require('../src/store')
const { post, get, sleep, FakeAgent } = require('./lib')

const INSTALL_KEY = 'itest-install-key'
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'hub-members-'))
const quiet = { log() {}, error() {}, warn() {} }

let pass = 0, fail = 0
async function t(name, fn) {
  try { await fn(); pass++; console.log('PASS ' + name) }
  catch (e) { fail++; console.log('FAIL ' + name + ' :: ' + (e && e.message)) }
}
function assert(cond, msg) { if (!cond) throw new Error(msg) }

function startHub(opts = {}) {
  const hub = createHub(Object.assign({
    storeFile: opts.storeFile || path.join(TMP, 'store.json'),
    installKey: INSTALL_KEY, cmdTimeoutMs: 400, pingIntervalMs: 60000, logger: quiet
  }, opts))
  return new Promise((resolve) => hub.listen(0, () => resolve(hub)))
}
const portOf = (hub) => hub.address().port

async function main() {
  await t('常量：成员上限是 8，掩码与 mid 形态固定', () => {
    assert(HUB_MEMBERS_MAX === 8, 'HUB_MEMBERS_MAX 应为 8，实得 ' + HUB_MEMBERS_MAX)
    // 测试样本一律用合成 openid（形状同真：o 开头 + 27 位）——真实 openid 不得进受版文件
    assert(maskOpenid('oFakeOpenidForUnitTest000001') === 'oFa…01', '掩码形态: ' + maskOpenid('oFakeOpenidForUnitTest000001'))
    assert(maskOpenid('abc') === 'abc', '短串不该被截')
    assert(/^[0-9a-f]{12}$/.test(memberMid('openid-X')), 'mid 形态: ' + memberMid('openid-X'))
    assert(memberMid('openid-X') === memberMid('openid-X'), 'mid 必须稳定（面板靠它定位要踢谁）')
  })

  await t('新注册实例自带 members:[] / memberCode:null / memberCodeExpire:0', () => {
    const f = path.join(TMP, 'a1-new.json')
    const s = new Store(f, { logger: quiet })
    const r = s.register({ sn: 'SN1', fw: 'fw' })
    const it = s.get(r.instanceId)
    assert(Array.isArray(it.members) && it.members.length === 0, 'members 必须是空数组')
    assert(it.memberCode === null && it.memberCodeExpire === 0, 'memberCode/Expire 初值错')
    const raw = JSON.parse(fs.readFileSync(f, 'utf8'))
    assert(Array.isArray(raw.instances[r.instanceId].members), '落盘必须带 members')
  })

  await t('迁移：老文档（无 members/memberCode）加载后被补齐，且 ownerOpenid 不丢', () => {
    const f = path.join(TMP, 'a1-legacy.json')
    // 逐字仿 v0.2.4 落盘形态：没有 members / memberCode / memberCodeExpire 三个字段
    fs.writeFileSync(f, JSON.stringify({ v: 1, instances: { legacy01: {
      instanceId: 'legacy01', sn: 'SN-OLD', fw: 'old', secretHash: 'x'.repeat(64),
      ownerOpenid: 'openid-legacy-owner', bindCode: null, bindExpire: 0, states: {}, createdAt: 1
    } } }))
    const s = new Store(f, { logger: quiet })
    const it = s.get('legacy01')
    assert(it, '老实例必须还在')
    assert(it.ownerOpenid === 'openid-legacy-owner', '迁移不得丢 owner（丢了＝全员掉绑）')
    assert(Array.isArray(it.members) && it.members.length === 0, 'members 应被补成 []')
    assert(it.memberCode === null && it.memberCodeExpire === 0, '成员码字段应被补齐')
  })

  await t('迁移：镜像采纳回来的老载荷同样被规范化', async () => {
    const f = path.join(TMP, 'a1-adopt.json')
    const fakeMirror = {
      status: () => ({ enabled: true, reason: '' }),
      push: async () => ({ ok: true }),
      pull: async () => ({ v: 1, instances: { mirr01: {
        instanceId: 'mirr01', sn: 'SN-M', fw: 'm', secretHash: 'y'.repeat(64),
        ownerOpenid: 'openid-mirror', bindCode: null, bindExpire: 0, states: {}, createdAt: 1
      } } })
    }
    const s = new Store(f, { logger: quiet, mirror: fakeMirror })
    const r = await s.adoptFromMirror(2000)
    assert(r.adopted === true, '应采纳成功，实得 ' + JSON.stringify(r))
    const it = s.get('mirr01')
    assert(Array.isArray(it.members), '采纳路径也要过规范化')
    assert(it.ownerOpenid === 'openid-mirror', '采纳不得丢 owner')
  })

  console.log('\nmembers: ' + pass + ' passed, ' + fail + ' failed')
  process.exit(fail ? 1 : 0)
}
main()
```

- [ ] **Step 2: 挂进门禁并确认失败**

`package.json:9` → `"test": "node tests/run.js && node tests/mirror.js && node tests/members.js"`
Run: `cd /e/AI/huijian-cloud-hub && node tests/members.js`
Expected: FAIL —— `HUB_MEMBERS_MAX`/`maskOpenid`/`memberMid` 未导出（undefined），"新注册实例自带 members" 断言失败。

- [ ] **Step 3: 实现（`src/store.js`）**

`:9` 之后加：
```js
const HUB_MEMBERS_MAX = 8            // 家庭成员上限（跨仓契约：加载项同名常量 + 两端文案里的数字由钉对账）

// openid 是身份标识：面板/healthz/日志一律掩码（沿用三端"凭据不回显"口径）
const maskOpenid = (s) => {
  const v = String(s || '')
  return v.length <= 5 ? v : v.slice(0, 3) + '…' + v.slice(-2)
}
// 成员句柄：稳定、不可逆、可公开展示——面板只看到掩码，掩码可能撞，踢人要靠它定位
const memberMid = (openid) => sha256(String(openid || '')).slice(0, 12)
```

`_load()` 结尾（`:36` 的 `}` 之前）与 `adoptFromMirror` 的 `this.instances = data.instances`（`:126`）之后各加一次 `this._normalize()`，并新增方法（放 `_load` 之后）：
```js
  // 老文档（≤v0.2.4）与镜像里的老载荷都没有 members/memberCode 三个字段。
  // 统一在两个入口补齐，之后所有读路径都能假定字段存在（少一处 if 就少一处漏判）。
  _normalize() {
    for (const id of Object.keys(this.instances)) {
      const it = this.instances[id]
      if (!it || typeof it !== 'object') continue
      if (!Array.isArray(it.members)) it.members = []
      if (it.memberCode === undefined) it.memberCode = null
      if (it.memberCodeExpire === undefined) it.memberCodeExpire = 0
    }
  }
```

`register()` 的实例字面量（`:138-148`）在 `ownerOpenid: null,` 之后加：
```js
      members: [],
      memberCode: null,
      memberCodeExpire: 0,
```

导出（`:221`）→ `module.exports = { Store, sha256, HUB_MEMBERS_MAX, maskOpenid, memberMid }`

- [ ] **Step 4: 跑测试确认全绿且旧用例未破**

Run: `cd /e/AI/huijian-cloud-hub && npm test`
Expected: `run.js` 24 passed / `mirror.js` 9 passed / `members.js` 4 passed，exit 0。

- [ ] **Step 5: Commit（等用户口令）**

```bash
git -C E:/AI/huijian-cloud-hub add src/store.js tests/members.js package.json
git -C E:/AI/huijian-cloud-hub commit -m "feat(store): 注册表加 members[] 与老文档规范化（家庭多人绑定 A1）"
```

---

### Task A2: 成员码签发（`rotateBindCode(instanceId, kind)`，无主人拒发）

**Files:**
- Modify: `E:\AI\huijian-cloud-hub\src\store.js:172-179`
- Test: `E:\AI\huijian-cloud-hub\tests\members.js`（追加）

**Interfaces:**
- Consumes: A1 的字段与常量
- Produces: `Store#rotateBindCode(instanceId, kind='owner') -> {ok:true, bindCode, expiresInSec, kind}` 或 `{ok:false, err:'unknown_instance'|'no_owner'}`

- [ ] **Step 1: 写失败测试**（追加到 `main()` 内、汇总行之前）

```js
  await t('成员码：无主人时拒发 no_owner（否则实例会被锁死）', () => {
    const s = new Store(path.join(TMP, 'a2-noowner.json'), { logger: quiet })
    const r = s.register({ sn: 'SN2', fw: 'fw' })
    const bad = s.rotateBindCode(r.instanceId, 'member')
    assert(bad.ok === false && bad.err === 'no_owner', '期望 no_owner，实得 ' + JSON.stringify(bad))
    assert(s.bindByCode(r.bindCode, 'openid-owner').ok === true, 'owner 码应能正常绑定')
    const ok = s.rotateBindCode(r.instanceId, 'member')
    assert(ok.ok === true && /^\d{6}$/.test(ok.bindCode) && ok.kind === 'member', '实得 ' + JSON.stringify(ok))
  })

  await t('成员码与 owner 码分字段：签发成员码不得作废 owner 码（双向判）', () => {
    const s = new Store(path.join(TMP, 'a2-split.json'), { logger: quiet })
    const r = s.register({ sn: 'SN2', fw: 'fw' })
    s.bindByCode(r.bindCode, 'openid-owner')
    assert(s.get(r.instanceId).bindCode === null, '绑定成功后 owner 码应已清空')
    const ownerCode = s.rotateBindCode(r.instanceId, 'owner').bindCode
    const memberCode = s.rotateBindCode(r.instanceId, 'member').bindCode
    const it = s.get(r.instanceId)
    assert(it.bindCode === ownerCode, '签发成员码把 owner 码作废了（v1.7.41 踩过的形态）')
    assert(it.memberCode === memberCode, '成员码没落到 memberCode 字段')
    assert(ownerCode !== memberCode, '两个码不该相同（相同则分流无从判起）')
    const ownerCode2 = s.rotateBindCode(r.instanceId, 'owner').bindCode   // 反向：也不得动成员码
    assert(s.get(r.instanceId).memberCode === memberCode, '签发 owner 码把成员码作废了')
    assert(ownerCode2 !== ownerCode, 'owner 码应已轮换')
  })

  await t('成员码：kind 缺省＝owner（老加载项不传 kind 时行为不变）', () => {
    const s = new Store(path.join(TMP, 'a2-default.json'), { logger: quiet })
    const r = s.register({ sn: 'SN2', fw: 'fw' })
    const res = s.rotateBindCode(r.instanceId)
    assert(res.kind === 'owner', '缺省必须是 owner，实得 ' + JSON.stringify(res))
    assert(s.get(r.instanceId).bindCode === res.bindCode, '缺省轮换的应是 owner 码')
    assert(s.get(r.instanceId).memberCode === null, '缺省轮换不得生成成员码')
  })

  await t('成员码：未知实例 → unknown_instance', () => {
    const s = new Store(path.join(TMP, 'a2-unknown.json'), { logger: quiet })
    const res = s.rotateBindCode('nosuchinstance', 'member')
    assert(res.ok === false && res.err === 'unknown_instance', JSON.stringify(res))
  })
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/AI/huijian-cloud-hub && node tests/members.js`
Expected: FAIL —— 现 `rotateBindCode` 只接一个参数，成员码会覆写 `bindCode`。

- [ ] **Step 3: 实现（替换 `store.js:172-179` 整个方法）**

```js
  /** 轮换绑定码（v0.2）：旧码立即作废、TTL 重新计时。
   *
   * v0.2.5 起分两种：kind='owner'（缺省，向后兼容老加载项）写 bindCode/bindExpire；
   * kind='member' 写 memberCode/memberCodeExpire。**必须分字段**：成员码若复用同一字段，
   * 主人在面板点一次「添加家人」就会把自己手上正在扫的 owner 码作废（v1.7.41 踩过的形态）。
   * 无主人时拒发成员码（no_owner）：否则第一个扫码的人成为 member，而 member 既不能踢人
   * 也不能升为 owner ⇒ 实例永久锁死，唯一出口是删身份文件重注册（＝全员重绑）。
   */
  rotateBindCode(instanceId, kind) {
    const it = this.get(instanceId)
    if (!it) return { ok: false, err: 'unknown_instance' }
    const wantMember = kind === 'member'
    if (wantMember && !it.ownerOpenid) return { ok: false, err: 'no_owner' }
    const code = String(crypto.randomInt(0, 1000000)).padStart(6, '0')
    const expire = Date.now() + this.bindTtlMs
    if (wantMember) { it.memberCode = code; it.memberCodeExpire = expire }
    else { it.bindCode = code; it.bindExpire = expire }
    this._save()
    return {
      ok: true,
      bindCode: code,
      expiresInSec: Math.round(this.bindTtlMs / 1000),
      kind: wantMember ? 'member' : 'owner'
    }
  }
```

- [ ] **Step 4: 跑测试确认全绿**

Run: `cd /e/AI/huijian-cloud-hub && npm test`
Expected: `members.js` 8 passed；`run.js` 24 / `mirror.js` 9 不变，exit 0。

- [ ] **Step 5: Commit（等用户口令）**

```bash
git -C E:/AI/huijian-cloud-hub add src/store.js tests/members.js
git -C E:/AI/huijian-cloud-hub commit -m "feat(store): 成员码独立签发，无主人拒发（家庭多人绑定 A2）"
```

---

### Task A3: 绑定分流（认两种码、回 `role`、上限 8、一次性）

**Files:**
- Modify: `E:\AI\huijian-cloud-hub\src\store.js:181-191`
- Test: `E:\AI\huijian-cloud-hub\tests\members.js`（追加）

**Interfaces:**
- Consumes: A2 的 `rotateBindCode(id,'member')`、A1 的 `members[]`/`HUB_MEMBERS_MAX`
- Produces: `Store#bindByCode(code, openid) -> {ok:true, instanceId, sn, role:'owner'|'member'}` 或 `{ok:false, err:'code_invalid'|'already_bound'|'members_full'|'no_owner'}`

- [ ] **Step 1: 写失败测试**

```js
  await t('绑定：成员码 → role=member，members 追加且带 at', () => {
    const s = new Store(path.join(TMP, 'a3-member.json'), { logger: quiet })
    const r = s.register({ sn: 'SN3', fw: 'fw' })
    assert(s.bindByCode(r.bindCode, 'openid-owner').role === 'owner', 'owner 码应回 role=owner')
    const mc = s.rotateBindCode(r.instanceId, 'member').bindCode
    const res = s.bindByCode(mc, 'openid-mom')
    assert(res.ok === true && res.role === 'member', JSON.stringify(res))
    assert(res.instanceId === r.instanceId && res.sn === 'SN3', 'instanceId/sn 要回给小程序')
    const ms = s.get(r.instanceId).members
    assert(ms.length === 1 && ms[0].openid === 'openid-mom' && typeof ms[0].at === 'number', JSON.stringify(ms))
  })

  await t('绑定：成员码一次性（扫完即清，同码再绑 → code_invalid）', () => {
    const s = new Store(path.join(TMP, 'a3-once.json'), { logger: quiet })
    const r = s.register({ sn: 'SN3', fw: 'fw' })
    s.bindByCode(r.bindCode, 'openid-owner')
    const mc = s.rotateBindCode(r.instanceId, 'member').bindCode
    assert(s.bindByCode(mc, 'openid-mom').ok === true, '第一次应成功')
    assert(s.get(r.instanceId).memberCode === null, '成员码应被清空')
    const again = s.bindByCode(mc, 'openid-dad')
    assert(again.ok === false && again.err === 'code_invalid', '同码再用应 code_invalid: ' + JSON.stringify(again))
    assert(s.get(r.instanceId).members.length === 1, '失败的绑定不得多出成员')
  })

  await t('绑定：同一微信号重复扫成员码 → 幂等 ok，成员不重复', () => {
    const s = new Store(path.join(TMP, 'a3-idem.json'), { logger: quiet })
    const r = s.register({ sn: 'SN3', fw: 'fw' })
    s.bindByCode(r.bindCode, 'openid-owner')
    assert(s.bindByCode(s.rotateBindCode(r.instanceId, 'member').bindCode, 'openid-mom').ok === true, '首次加入')
    const res = s.bindByCode(s.rotateBindCode(r.instanceId, 'member').bindCode, 'openid-mom')
    assert(res.ok === true && res.role === 'member', '同一人重扫应幂等: ' + JSON.stringify(res))
    assert(s.get(r.instanceId).members.length === 1, '同一个人不得占两个名额')
  })

  await t('绑定：第 9 个成员 → members_full，且不消耗成员码', () => {
    const s = new Store(path.join(TMP, 'a3-full.json'), { logger: quiet })
    const r = s.register({ sn: 'SN3', fw: 'fw' })
    s.bindByCode(r.bindCode, 'openid-owner')
    for (let i = 0; i < HUB_MEMBERS_MAX; i++) {
      const mc = s.rotateBindCode(r.instanceId, 'member').bindCode
      assert(s.bindByCode(mc, 'openid-m' + i).ok === true, '第 ' + (i + 1) + ' 人应成功')
    }
    assert(s.get(r.instanceId).members.length === HUB_MEMBERS_MAX, '应正好 8 人')
    const mc = s.rotateBindCode(r.instanceId, 'member').bindCode
    const over = s.bindByCode(mc, 'openid-m8')
    assert(over.ok === false && over.err === 'members_full', '第 9 人应 members_full: ' + JSON.stringify(over))
    assert(s.get(r.instanceId).memberCode === mc, '失败的绑定不该把码消耗掉（踢人后同一张码还能用）')
  })

  await t('绑定：owner 码语义不变（他人已绑 → already_bound，同人幂等）', () => {
    const s = new Store(path.join(TMP, 'a3-owner.json'), { logger: quiet })
    const r = s.register({ sn: 'SN3', fw: 'fw' })
    assert(s.bindByCode(r.bindCode, 'openid-owner').ok === true, '首次绑定')
    const other = s.bindByCode(s.rotateBindCode(r.instanceId, 'owner').bindCode, 'openid-stranger')
    assert(other.ok === false && other.err === 'already_bound', '换主人必须被拦: ' + JSON.stringify(other))
    const same = s.bindByCode(s.rotateBindCode(r.instanceId, 'owner').bindCode, 'openid-owner')
    assert(same.ok === true && same.role === 'owner', '同一 owner 重绑应幂等')
  })
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/AI/huijian-cloud-hub && node tests/members.js`
Expected: FAIL —— 成员码一律 `code_invalid`，且返回值没有 `role`。

- [ ] **Step 3: 实现（替换 `store.js:181-191`）**

```js
  /** 绑定：一次性码 + 归属。v0.2.5 起按码的种类分流——
   *  owner 码 → 写 ownerOpenid（语义与 v0.2 完全一致：他人已绑则 already_bound，同人幂等）；
   *  member 码 → 追加 members（上限 HUB_MEMBERS_MAX；已存在则幂等；两种码都扫完即清）。
   *  载荷里不写角色（HUJIAN-BIND:1:<码> 两端各存一份、无签名），角色一律由 hub 查表决定，
   *  这样二维码字符串被改也提不了权。
   */
  bindByCode(bindCode, openid) {
    const now = Date.now()
    const all = Object.values(this.instances)
    const owner = all.find((x) => x.bindCode && x.bindCode === bindCode && x.bindExpire > now)
    if (owner) {
      if (owner.ownerOpenid && owner.ownerOpenid !== openid) return { ok: false, err: 'already_bound' }
      owner.ownerOpenid = openid
      owner.bindCode = null
      owner.bindExpire = 0
      this._save()
      return { ok: true, instanceId: owner.instanceId, sn: owner.sn, role: 'owner' }
    }
    const host = all.find((x) => x.memberCode && x.memberCode === bindCode && x.memberCodeExpire > now)
    if (!host) return { ok: false, err: 'code_invalid' }
    // 与 rotateBindCode 双保险：老库里可能存着"没有主人却签发了成员码"的遗留数据
    if (!host.ownerOpenid) return { ok: false, err: 'no_owner' }
    if ((host.members || []).some((m) => m && m.openid === openid)) {
      host.memberCode = null
      host.memberCodeExpire = 0
      this._save()
      return { ok: true, instanceId: host.instanceId, sn: host.sn, role: 'member' }
    }
    if ((host.members || []).length >= HUB_MEMBERS_MAX) return { ok: false, err: 'members_full' }
    host.members = (host.members || []).concat([{ openid, at: now }])
    host.memberCode = null
    host.memberCodeExpire = 0
    this._save()
    return { ok: true, instanceId: host.instanceId, sn: host.sn, role: 'member' }
  }
```

- [ ] **Step 4: 跑测试确认全绿**

Run: `cd /e/AI/huijian-cloud-hub && npm test`
Expected: `run.js` 24（"绑定：对码 → ok + instanceId" 那条现在多回 `role`，仍应绿）、`members.js` 13，exit 0。

- [ ] **Step 5: Commit（等用户口令）**

```bash
git -C E:/AI/huijian-cloud-hub add src/store.js tests/members.js
git -C E:/AI/huijian-cloud-hub commit -m "feat(store): 绑定按码种分流，成员上限 8（家庭多人绑定 A3）"
```

---

### Task A4: 归属判定与成员管理

**Files:**
- Modify: `E:\AI\huijian-cloud-hub\src\store.js:193-196`（`owns`）
- Test: `E:\AI\huijian-cloud-hub\tests\members.js`（追加）

**Interfaces:**
- Consumes: A1 的 `maskOpenid`/`memberMid`、A3 的 `members[]`
- Produces: `isOwner(id,openid)->bool`、`isMember(id,openid)->bool`、`canAccess(id,openid)->bool`、`owns()`（**语义变更为 canAccess 别名**）、`leaveInstance(id,openid)->{ok,removed,remaining}|{ok:false,err:'unknown_instance'|'forbidden'|'owner_cannot_leave'|'unknown_member'}`、`removeMemberByMid(id,mid)->{ok,removed,remaining}|{ok:false,err:'unknown_instance'|'unknown_member'}`、`listMembers(id)->{ok,ownerMasked,members:[{mid,openidMasked,at}],membersMax}`

- [ ] **Step 1: 写失败测试**

```js
  // 造一个"1 owner + 2 member"的库，后续用例复用
  function familyStore(file) {
    const s = new Store(path.join(TMP, file), { logger: quiet })
    const r = s.register({ sn: 'SN-FAM', fw: 'fw' })
    s.bindByCode(r.bindCode, 'openid-owner')
    s.bindByCode(s.rotateBindCode(r.instanceId, 'member').bindCode, 'openid-mom')
    s.bindByCode(s.rotateBindCode(r.instanceId, 'member').bindCode, 'openid-dad')
    return { s, id: r.instanceId }
  }

  await t('归属：owner 与 member 都算 canAccess，陌生人不算', () => {
    const { s, id } = familyStore('a4-access.json')
    assert(s.isOwner(id, 'openid-owner') === true, 'owner 判定')
    assert(s.isMember(id, 'openid-mom') === true, 'member 判定')
    assert(s.isOwner(id, 'openid-mom') === false, 'member 不得被当成 owner')
    assert(s.canAccess(id, 'openid-owner') && s.canAccess(id, 'openid-dad'), '两者都可访问')
    assert(s.canAccess(id, 'openid-stranger') === false, '陌生人不得访问')
    assert(s.canAccess(id, '') === false && s.canAccess('nosuch', 'openid-owner') === false, '空 openid / 未知实例都要拒')
    assert(s.owns(id, 'openid-mom') === true, 'owns 必须是 canAccess 的别名（否则老调用点会静默收紧）')
  })

  await t('退出：member 可退自己，退完 canAccess 立即 false', () => {
    const { s, id } = familyStore('a4-leave.json')
    const r = s.leaveInstance(id, 'openid-mom')
    assert(r.ok === true && r.remaining === 1, JSON.stringify(r))
    assert(r.removed === maskOpenid('openid-mom'), 'removed 必须是掩码: ' + r.removed)
    assert(s.canAccess(id, 'openid-mom') === false, '退完必须立即失去访问权')
    assert(s.canAccess(id, 'openid-dad') === true, '不得误伤另一个成员')
  })

  await t('退出：owner 不能退自己（否则实例无主、没人能管成员）', () => {
    const { s, id } = familyStore('a4-owner-leave.json')
    const r = s.leaveInstance(id, 'openid-owner')
    assert(r.ok === false && r.err === 'owner_cannot_leave', JSON.stringify(r))
    assert(s.isOwner(id, 'openid-owner') === true, 'owner 归属不得被动摇')
  })

  await t('退出：陌生人 → forbidden；已退的人再退 → unknown_member；未知实例 → unknown_instance', () => {
    const { s, id } = familyStore('a4-stranger.json')
    assert(s.leaveInstance(id, 'openid-stranger').err === 'forbidden', '陌生人应 forbidden')
    s.leaveInstance(id, 'openid-mom')
    assert(s.leaveInstance(id, 'openid-mom').err === 'unknown_member', '重复退出应 unknown_member')
    assert(s.leaveInstance('nosuch', 'openid-mom').err === 'unknown_instance', '未知实例')
  })

  await t('踢人：按 mid 精确踢一个，另一个不受影响；mid 不存在 → unknown_member', () => {
    const { s, id } = familyStore('a4-kick.json')
    const list = s.listMembers(id)
    assert(list.ok === true && list.members.length === 2, JSON.stringify(list))
    const mom = list.members.find((m) => m.openidMasked === maskOpenid('openid-mom'))
    assert(mom && /^[0-9a-f]{12}$/.test(mom.mid), 'mid 形态: ' + JSON.stringify(mom))
    const r = s.removeMemberByMid(id, mom.mid)
    assert(r.ok === true && r.remaining === 1, JSON.stringify(r))
    assert(s.canAccess(id, 'openid-mom') === false, '被踢者立即失去访问权')
    assert(s.canAccess(id, 'openid-dad') === true, '不得误伤')
    assert(s.removeMemberByMid(id, mom.mid).err === 'unknown_member', '重复踢应 unknown_member')
  })

  await t('列成员：只回掩码与 mid，绝不回完整 openid', () => {
    const { s, id } = familyStore('a4-list.json')
    const r = s.listMembers(id)
    assert(r.ownerMasked === maskOpenid('openid-owner'), 'owner 也要掩码: ' + r.ownerMasked)
    assert(r.membersMax === HUB_MEMBERS_MAX, 'membersMax 要给面板判上限')
    const dump = JSON.stringify(r)
    assert(!dump.includes('openid-mom') && !dump.includes('openid-owner'), '返回体里出现完整 openid: ' + dump)
    for (const m of r.members) {
      assert(typeof m.mid === 'string' && typeof m.openidMasked === 'string' && typeof m.at === 'number', JSON.stringify(m))
    }
  })
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/AI/huijian-cloud-hub && node tests/members.js`
Expected: FAIL —— `s.isOwner is not a function`。

- [ ] **Step 3: 实现（替换 `store.js:193-196` 的 `owns`）**

```js
  isOwner(instanceId, openid) {
    const it = this.get(instanceId)
    return !!it && !!openid && it.ownerOpenid === openid
  }

  isMember(instanceId, openid) {
    const it = this.get(instanceId)
    return !!it && !!openid && Array.isArray(it.members) &&
      it.members.some((m) => m && m.openid === openid)
  }

  // /state 与 /cmd 的唯一鉴权入口（v0.2.5 起 owner 与 member 都放行）
  canAccess(instanceId, openid) {
    return this.isOwner(instanceId, openid) || this.isMember(instanceId, openid)
  }

  /** 旧名保留＝避免调用点漏改；**语义已从"仅 owner"放宽为 canAccess**。
   *  新代码一律用 canAccess/isOwner，别再用 owns（名字会说谎）。*/
  owns(instanceId, openid) {
    return this.canAccess(instanceId, openid)
  }

  /** 本人退出（member 专用）。owner 不能退：退了实例就无主，没人能再管成员，
   *  唯一出口是删身份文件重注册＝全员重绑。*/
  leaveInstance(instanceId, openid) {
    const it = this.get(instanceId)
    if (!it) return { ok: false, err: 'unknown_instance' }
    if (!this.canAccess(instanceId, openid)) return { ok: false, err: 'forbidden' }
    if (it.ownerOpenid === openid) return { ok: false, err: 'owner_cannot_leave' }
    const before = (it.members || []).length
    it.members = (it.members || []).filter((m) => !(m && m.openid === openid))
    if (it.members.length === before) return { ok: false, err: 'unknown_member' }
    this._save()
    return { ok: true, removed: maskOpenid(openid), remaining: it.members.length }
  }

  /** 主人踢人。只由 /agent/unbind（实例凭据）调用——加载项没有 openid，
   *  而面板在 HA 局域网内且要过 HA 鉴权，等价于主人本人操作。*/
  removeMemberByMid(instanceId, mid) {
    const it = this.get(instanceId)
    if (!it) return { ok: false, err: 'unknown_instance' }
    const target = (it.members || []).find((m) => m && memberMid(m.openid) === mid)
    if (!target) return { ok: false, err: 'unknown_member' }
    it.members = (it.members || []).filter((m) => m !== target)
    this._save()
    return { ok: true, removed: maskOpenid(target.openid), remaining: it.members.length }
  }

  listMembers(instanceId) {
    const it = this.get(instanceId)
    if (!it) return { ok: false, err: 'unknown_instance' }
    return {
      ok: true,
      ownerMasked: it.ownerOpenid ? maskOpenid(it.ownerOpenid) : null,
      members: (it.members || []).map((m) => ({
        mid: memberMid(m && m.openid),
        openidMasked: maskOpenid(m && m.openid),
        at: (m && m.at) || 0
      })),
      membersMax: HUB_MEMBERS_MAX
    }
  }
```

- [ ] **Step 4: 跑测试确认全绿**

Run: `cd /e/AI/huijian-cloud-hub && npm test`
Expected: `members.js` 19 passed；`run.js` 24 / `mirror.js` 9 不变，exit 0。

- [ ] **Step 5: Commit（等用户口令）**

```bash
git -C E:/AI/huijian-cloud-hub add src/store.js tests/members.js
git -C E:/AI/huijian-cloud-hub commit -m "feat(store): canAccess 归属判定 + 退出/踢人/列成员（家庭多人绑定 A4）"
```

---

### Task A5: HTTP 端点接线

**Files:**
- Modify: `E:\AI\huijian-cloud-hub\src\server.js`（`/healthz` `:61-82`、`/agent/bindcode` `:95-104`、`/bind` `:106-113`、`/state:117`、`/cmd:123`；新增三路由插在 `/cmd` 之后、`:131` 兜底 404 之前）
- Test: `E:\AI\huijian-cloud-hub\tests\members.js`（追加）

**Interfaces:**
- Consumes: A2/A3/A4 的 store 方法、`openidOf`（`:55`）、`json`（`:32`）
- Produces（对外契约，加载项与小程序都按这个写）:
  - `POST /agent/bindcode {instanceId,secret,kind?}` → 200 `{ok,bindCode,expiresInSec,kind}`；403 `bad_secret`；404 `unknown_instance`；409 `no_owner`
  - `POST /bind {bindCode}` → 200 `{ok,instanceId,sn,role}`；401 `no_openid`；404 `code_invalid`；409 `already_bound`/`members_full`/`no_owner`
  - `POST /unbind {instanceId}` → 200 `{ok,removed,remaining}`；401 `no_openid`；403 `forbidden`；409 `owner_cannot_leave`；404 `unknown_member`/`unknown_instance`
  - `POST /agent/members {instanceId,secret}` → 200 `{ok,ownerMasked,members[],membersMax}`；403 `bad_secret`；404 `unknown_instance`
  - `POST /agent/unbind {instanceId,secret,mid}` → 200 `{ok,removed,remaining}`；403 `bad_secret`；404 `unknown_member`
  - `/state`、`/cmd` 鉴权改 `canAccess`（错误码不变：403 `forbidden`）
  - `GET /healthz` 新增 `membersTotal`（数字，不含 openid）

- [ ] **Step 1: 写失败测试**

```js
  await t('HTTP：/agent/bindcode 带 kind=member 回成员码 + kind 回显（加载项据此判老 hub）', async () => {
    const hub = await startHub({ storeFile: path.join(TMP, 'a5-bindcode.json') })
    const port = portOf(hub)
    const a = new FakeAgent(port, INSTALL_KEY)
    await a.register('SN5')
    await post(port, '/bind', { bindCode: a.bindCode }, 'openid-owner')
    const r = await post(port, '/agent/bindcode', { instanceId: a.instanceId, secret: a.secret, kind: 'member' })
    assert(r.status === 200 && r.body.ok && r.body.kind === 'member', JSON.stringify(r))
    assert(/^\d{6}$/.test(r.body.bindCode), '成员码形态: ' + JSON.stringify(r.body))
    const legacy = await post(port, '/agent/bindcode', { instanceId: a.instanceId, secret: a.secret })
    assert(legacy.status === 200 && legacy.body.kind === 'owner', '不传 kind 必须回 owner: ' + JSON.stringify(legacy))
    const bad = await post(port, '/agent/bindcode', { instanceId: a.instanceId, secret: 'wrong', kind: 'member' })
    assert(bad.status === 403 && bad.body.err === 'bad_secret', JSON.stringify(bad))
    hub.close()
  })

  await t('HTTP：/bind 回 role；第 9 人 409 members_full', async () => {
    const hub = await startHub({ storeFile: path.join(TMP, 'a5-bind.json') })
    const port = portOf(hub)
    const a = new FakeAgent(port, INSTALL_KEY)
    await a.register('SN5')
    const owner = await post(port, '/bind', { bindCode: a.bindCode }, 'openid-owner')
    assert(owner.status === 200 && owner.body.role === 'owner', JSON.stringify(owner))
    for (let i = 0; i < HUB_MEMBERS_MAX; i++) {
      const mc = (await post(port, '/agent/bindcode', { instanceId: a.instanceId, secret: a.secret, kind: 'member' })).body.bindCode
      const r = await post(port, '/bind', { bindCode: mc }, 'openid-m' + i)
      assert(r.status === 200 && r.body.role === 'member', '第 ' + (i + 1) + ' 人: ' + JSON.stringify(r))
    }
    const mc = (await post(port, '/agent/bindcode', { instanceId: a.instanceId, secret: a.secret, kind: 'member' })).body.bindCode
    const over = await post(port, '/bind', { bindCode: mc }, 'openid-m8')
    assert(over.status === 409 && over.body.err === 'members_full', JSON.stringify(over))
    hub.close()
  })

  await t('HTTP：/state 与 /cmd 对 member 放行，对陌生人仍 403，命令只下发一次', async () => {
    const hub = await startHub({ storeFile: path.join(TMP, 'a5-state.json') })
    const port = portOf(hub)
    const a = new FakeAgent(port, INSTALL_KEY)
    await a.register('SN5')
    await a.connect()
    await post(port, '/bind', { bindCode: a.bindCode }, 'openid-owner')
    const mc = (await post(port, '/agent/bindcode', { instanceId: a.instanceId, secret: a.secret, kind: 'member' })).body.bindCode
    await post(port, '/bind', { bindCode: mc }, 'openid-mom')
    a.state([{ sn: 'DEV1', gwSn: 'SN5', position: 3, battery: 99, state: 1 }])
    await sleep(120)
    const st = await post(port, '/state', { instanceId: a.instanceId }, 'openid-mom')
    assert(st.status === 200 && st.body.states && st.body.states.DEV1, 'member 应能读状态: ' + JSON.stringify(st))
    const cmd = await post(port, '/cmd', { instanceId: a.instanceId, sn: 'DEV1', action: 'control', params: { attribute: 'position', value: '50' } }, 'openid-mom')
    assert(cmd.status === 200 && cmd.body.ok === true, 'member 应能控制: ' + JSON.stringify(cmd))
    assert(a.cmdCount() === 1, '命令必须只下发一次（不得因多成员而广播）: ' + a.cmdCount())
    const denied = await post(port, '/state', { instanceId: a.instanceId }, 'openid-stranger')
    assert(denied.status === 403 && denied.body.err === 'forbidden', JSON.stringify(denied))
    hub.close()
  })

  await t('HTTP：/unbind 本人退出；owner 退自己 → 409；陌生人 → 403；缺 openid → 401', async () => {
    const hub = await startHub({ storeFile: path.join(TMP, 'a5-unbind.json') })
    const port = portOf(hub)
    const a = new FakeAgent(port, INSTALL_KEY)
    await a.register('SN5')
    await post(port, '/bind', { bindCode: a.bindCode }, 'openid-owner')
    const mc = (await post(port, '/agent/bindcode', { instanceId: a.instanceId, secret: a.secret, kind: 'member' })).body.bindCode
    await post(port, '/bind', { bindCode: mc }, 'openid-mom')
    const self = await post(port, '/unbind', { instanceId: a.instanceId }, 'openid-mom')
    assert(self.status === 200 && self.body.ok && self.body.remaining === 0, JSON.stringify(self))
    assert(self.body.removed === 'ope…om', 'removed 必须是掩码: ' + self.body.removed)
    const after = await post(port, '/state', { instanceId: a.instanceId }, 'openid-mom')
    assert(after.status === 403, '退完必须立即 403: ' + JSON.stringify(after))
    const ownerLeave = await post(port, '/unbind', { instanceId: a.instanceId }, 'openid-owner')
    assert(ownerLeave.status === 409 && ownerLeave.body.err === 'owner_cannot_leave', JSON.stringify(ownerLeave))
    const stranger = await post(port, '/unbind', { instanceId: a.instanceId }, 'openid-stranger')
    assert(stranger.status === 403 && stranger.body.err === 'forbidden', JSON.stringify(stranger))
    const noopenid = await post(port, '/unbind', { instanceId: a.instanceId })
    assert(noopenid.status === 401 && noopenid.body.err === 'no_openid', JSON.stringify(noopenid))
    hub.close()
  })

  await t('HTTP：/agent/members 与 /agent/unbind 走实例凭据（加载项没有 openid）', async () => {
    const hub = await startHub({ storeFile: path.join(TMP, 'a5-agent.json') })
    const port = portOf(hub)
    const a = new FakeAgent(port, INSTALL_KEY)
    await a.register('SN5')
    await post(port, '/bind', { bindCode: a.bindCode }, 'openid-owner')
    const mc = (await post(port, '/agent/bindcode', { instanceId: a.instanceId, secret: a.secret, kind: 'member' })).body.bindCode
    await post(port, '/bind', { bindCode: mc }, 'openid-dad')
    const list = await post(port, '/agent/members', { instanceId: a.instanceId, secret: a.secret })
    assert(list.status === 200 && list.body.members.length === 1, JSON.stringify(list))
    assert(list.body.ownerMasked === 'ope…er', 'ownerMasked: ' + list.body.ownerMasked)
    const mid = list.body.members[0].mid
    const badSecret = await post(port, '/agent/members', { instanceId: a.instanceId, secret: 'wrong' })
    assert(badSecret.status === 403 && badSecret.body.err === 'bad_secret', JSON.stringify(badSecret))
    const kick = await post(port, '/agent/unbind', { instanceId: a.instanceId, secret: a.secret, mid })
    assert(kick.status === 200 && kick.body.ok && kick.body.remaining === 0, JSON.stringify(kick))
    const gone = await post(port, '/state', { instanceId: a.instanceId }, 'openid-dad')
    assert(gone.status === 403, '被踢者立即 403: ' + JSON.stringify(gone))
    const again = await post(port, '/agent/unbind', { instanceId: a.instanceId, secret: a.secret, mid })
    assert(again.status === 404 && again.body.err === 'unknown_member', JSON.stringify(again))
    hub.close()
  })

  await t('HTTP：/healthz 有 membersTotal 且不含任何 openid', async () => {
    const hub = await startHub({ storeFile: path.join(TMP, 'a5-healthz.json') })
    const port = portOf(hub)
    const a = new FakeAgent(port, INSTALL_KEY)
    await a.register('SN5')
    await post(port, '/bind', { bindCode: a.bindCode }, 'openid-owner-uniq-xyz')
    const mc = (await post(port, '/agent/bindcode', { instanceId: a.instanceId, secret: a.secret, kind: 'member' })).body.bindCode
    await post(port, '/bind', { bindCode: mc }, 'openid-member-uniq-xyz')
    const h = await get(port, '/healthz')
    assert(h.status === 200 && h.body.membersTotal === 1, 'membersTotal 应为 1: ' + JSON.stringify(h.body.membersTotal))
    const dump = JSON.stringify(h.body)
    assert(!dump.includes('openid-owner-uniq-xyz') && !dump.includes('openid-member-uniq-xyz'),
      '/healthz 是无鉴权面，出现完整 openid: ' + dump)
    hub.close()
  })
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/AI/huijian-cloud-hub && node tests/members.js`
Expected: FAIL —— 三个新路由落到兜底 `404 not_found`；`/healthz` 无 `membersTotal`。

- [ ] **Step 3: 实现（`src/server.js`）**

`/healthz` 在 `:65` 的 `agentsOnline` 之后插一行：
```js
        membersTotal: Object.values(store.instances)
          .reduce((n, x) => n + ((x && Array.isArray(x.members) && x.members.length) || 0), 0),
```

替换 `/agent/bindcode` 整块（`:95-104`）：
```js
    if (p === '/agent/bindcode') {
      // v0.2：加载项用实例凭据换一个新绑定码（面板"点二维码刷新"走这条）。
      // v0.2.5：kind='member' 换的是**成员码**（写 memberCode，不动 owner 码）。
      // 旧码当场作废——所以"刷新"必须由用户显式触发，不能自动轮换。
      const { instanceId, secret } = body
      if (!store.verifySecret(instanceId, secret)) return json(res, 403, { ok: false, err: 'bad_secret' })
      const kind = body.kind === 'member' ? 'member' : 'owner'
      const r = store.rotateBindCode(instanceId, kind)
      if (!r.ok) return json(res, r.err === 'unknown_instance' ? 404 : 409, r)
      log('agent bindcode rotated', instanceId, 'kind=' + kind)   // 只记实例号与种类，不记码值
      return json(res, 200, r)
    }
```

替换 `/bind` 整块（`:106-113`）：
```js
    if (p === '/bind') {
      const openid = openidOf(req, body)
      if (!openid) return json(res, 401, { ok: false, err: 'no_openid' })
      const r = store.bindByCode(String(body.bindCode || '').trim(), openid)
      if (!r.ok) {
        const conflict = r.err === 'already_bound' || r.err === 'members_full' || r.err === 'no_owner'
        return json(res, conflict ? 409 : 404, r)
      }
      log('bind ok', r.instanceId, 'role=' + r.role, 'openid=' + openid.slice(0, 6) + '…')
      return json(res, 200, r)
    }
```

`:117` 与 `:123` 的 `store.owns(` 各改成 `store.canAccess(`。

新增三路由（插在 `/cmd` 块之后、`:131` 之前）：
```js
    if (p === '/unbind') {
      // 本人退出（member 专用）。**不接受 target 参数**：body.openid 是 openidOf 的兜底
      // 身份来源，一名两用会变成"我声称我是你、然后把你踢了"的提权面。踢人只走 /agent/unbind。
      const openid = openidOf(req, body)
      if (!openid) return json(res, 401, { ok: false, err: 'no_openid' })
      const r = store.leaveInstance(String(body.instanceId || ''), openid)
      if (!r.ok) {
        const code = r.err === 'forbidden' ? 403
          : (r.err === 'unknown_member' || r.err === 'unknown_instance') ? 404 : 409
        return json(res, code, r)
      }
      log('unbind ok', body.instanceId, 'by=' + openid.slice(0, 6) + '…')
      return json(res, 200, r)
    }

    if (p === '/agent/members') {
      // 实例凭据鉴权：加载项没有 openid（openid 只由云托管注入到小程序请求）。
      // 面板在 HA 局域网内且要过 HA 鉴权，等价于主人本人查看。
      const { instanceId, secret } = body
      if (!store.verifySecret(instanceId, secret)) return json(res, 403, { ok: false, err: 'bad_secret' })
      const r = store.listMembers(instanceId)
      if (!r.ok) return json(res, 404, r)
      return json(res, 200, r)
    }

    if (p === '/agent/unbind') {
      const { instanceId, secret, mid } = body
      if (!store.verifySecret(instanceId, secret)) return json(res, 403, { ok: false, err: 'bad_secret' })
      const r = store.removeMemberByMid(instanceId, String(mid || ''))
      if (!r.ok) return json(res, 404, r)
      log('agent unbind ok', instanceId, 'mid=' + String(mid || '').slice(0, 6) + '…')
      return json(res, 200, r)
    }
```

- [ ] **Step 4: 跑测试确认全绿**

Run: `cd /e/AI/huijian-cloud-hub && npm test`
Expected: `members.js` 25 passed；`run.js` 24 / `mirror.js` 9 不变，exit 0。

- [ ] **Step 5: Commit（等用户口令）**

```bash
git -C E:/AI/huijian-cloud-hub add src/server.js tests/members.js
git -C E:/AI/huijian-cloud-hub commit -m "feat(server): 成员码/退出/踢人/列成员端点 + canAccess 鉴权（家庭多人绑定 A5）"
```

---

### Task A6: 镜像纪律钉 + 版本号 + README

**Files:**
- Modify: `E:\AI\huijian-cloud-hub\tests\mirror.js`（在配额纪律钉 `:209` 之后追加一条）
- Modify: `E:\AI\huijian-cloud-hub\package.json:3`、`README.md`（端点表）

**Interfaces:**
- Consumes: `pushMirror()`（`store.js:76-85`）、`_save({mirror:false})`（`:208`）
- Produces: 镜像载荷含 `members` 与 `ownerOpenid`、**不含** `states`、不含明文 secret；`package.json.version === '0.2.5'`

- [ ] **Step 1: 写测试**（追加到 `tests/mirror.js`，照它现有假 mirror 与 `t/assert` 写法）

```js
await t('镜像纪律：members 进镜像、states 不进、secret 明文不进', async () => {
  const pushed = []
  const fakeMirror = {
    status: () => ({ enabled: true, reason: '' }),
    push: async (payload) => { pushed.push(payload); return { ok: true } },
    pull: async () => null
  }
  const s = new Store(path.join(TMP, 'mirror-members.json'), { logger: quiet, mirror: fakeMirror, mirrorDebounceMs: 5 })
  const r = s.register({ sn: 'SN-M', fw: 'fw' })
  s.bindByCode(r.bindCode, 'openid-owner')
  s.bindByCode(s.rotateBindCode(r.instanceId, 'member').bindCode, 'openid-mom')
  s.setStates(r.instanceId, [{ sn: 'DEV1', gwSn: 'SN-M', position: 1 }])
  await s.flushMirror()
  const last = pushed[pushed.length - 1]
  assert(last, '应至少推过一次')
  const inst = last.instances[r.instanceId]
  assert(inst, '镜像载荷缺该实例')
  assert(Array.isArray(inst.members) && inst.members.length === 1,
    'members 必须进镜像（否则 hub 重启后全家掉绑）: ' + JSON.stringify(inst.members))
  assert(inst.members[0].openid === 'openid-mom', '成员 openid 要原样存（它是归属真相，不是凭据）')
  assert(inst.ownerOpenid === 'openid-owner', 'owner 归属必须进镜像')
  assert(Object.keys(inst.states || {}).length === 0, 'states 不得进镜像（配额纪律 M27）')
  assert(inst.secretHash && inst.secret === undefined, '只存哈希，不得出现明文 secret 字段')
  const before = pushed.length
  s.setStates(r.instanceId, [{ sn: 'DEV2', gwSn: 'SN-M', position: 2 }])
  await new Promise((res) => setTimeout(res, 30))
  assert(pushed.length === before, '状态更新不得触发镜像推送（配额纪律）')
})
```

- [ ] **Step 2: 跑测试——它应当**已经绿**（这条是防回退钉，不是驱动实现的钉）**

Run: `cd /e/AI/huijian-cloud-hub && node tests/mirror.js`
Expected: PASS（`pushMirror` 是整实例浅拷贝，`members` 自动带上）。**若不绿 ⇒ A1 的字段没落在实例文档上，回去修 A1。**

- [ ] **Step 3: 变异自证这条钉有效（影子树，绝不动活树）**

```bash
D=$(mktemp -d) && cp -r E:/AI/huijian-cloud-hub/src E:/AI/huijian-cloud-hub/tests E:/AI/huijian-cloud-hub/package.json "$D/" && cd "$D"
sed -i "s/Object.assign({}, v, { states: {} })/Object.assign({}, v, { states: {}, members: [] })/" src/store.js
grep -n "members: \[\]" src/store.js | head -2      # 阳性对照：确认变异真注入了
node tests/mirror.js; echo "M28_RC=$?"
cd / && rm -rf "$D"
```
Expected: `M28_RC=1`，FAIL 行点名"members 必须进镜像"。

- [ ] **Step 4: 版本号与 README**

`package.json:3` → `"version": "0.2.5",`；`README.md` 端点表补 `POST /unbind`（本人退出）、`POST /agent/members`（实例凭据列成员）、`POST /agent/unbind`（实例凭据按 mid 踢人），并在 `/bind` 行注明返回体新增 `role`、`/agent/bindcode` 新增 `kind`、成员上限 8。

Run: `cd /e/AI/huijian-cloud-hub && node -p "require('./package.json').version" && npm test`
Expected: `0.2.5`；`run.js` 24 / `mirror.js` 10 / `members.js` 25 全绿，exit 0。

- [ ] **Step 5: Commit（等用户口令）**

```bash
git -C E:/AI/huijian-cloud-hub add src/store.js tests/mirror.js package.json README.md
git -C E:/AI/huijian-cloud-hub commit -m "chore: v0.2.5 家庭成员镜像纪律钉 + 端点文档"
```

---

## Phase B — 加载项 v1.7.46

> **进度（2026-09-24 凌晨）**：Task **B1 已完成**（工作树未提交）——`huijian.js:207-245` 的重复定义已删，
> `test_v1737_hub_ui.py::_func` 与 `test_v1738_hub_qr_ui.py::_fn` 已改成"多处即报错"，
> 新增 `tests/test_v1746_panel_unique_funcs.py`（7 条）与 `tests/test_v1746_panel_render.py`（2 条，假 DOM 里
> node 真跑 `applyHubStatus` 五个场景）。插件门禁 949 passed、ruff/compileall/node --check/bash -n 全绿，
> 变异 M-P1～M-P5 各精准红。B2 起未开工。

### Task B1: 热修 `huijian.js` 重复定义（必须最先做，否则后续面板改动全是死码）

**Files:**
- Modify: `huijian_mqtt_broker/www/js/huijian.js:207-245`（**整段删除**旧版 `loadRemoteControl`）
- Create: `huijian_mqtt_broker/tests/test_v1746_panel_unique_funcs.py`
- Modify: `huijian_mqtt_broker/tests/test_v1737_hub_ui.py:51-63`、`huijian_mqtt_broker/tests/test_v1738_hub_qr_ui.py:52-63`（`_func` 抽取器）

**Interfaces:**
- Produces: `huijian.js` 里每个函数名唯一；`loadRemoteControl()` 只走 `applyHubStatus(info)`；测试侧帮助函数 `_single_func_body(src, name)` 语义＝"0 处或多处都报错"

- [ ] **Step 1: 写失败测试**（新建 `tests/test_v1746_panel_unique_funcs.py`）

```python
"""面板 JS 的重名钉与"单一渲染出口"钉。

为什么必须有：v1.7.41～v1.7.45 线上一直带着一个缺陷——`huijian.js` 里
`loadRemoteControl` 被定义了两次（新版走 applyHubStatus、旧版 v1.7.37 残留），
JS 函数声明后者覆盖前者 ⇒ 页面加载与 30s 无感刷新跑的都是旧版：绑定码过期文案
（hubCodeExp）永不显示、「纳管网关 N 台 · M 个子设备」退回只显示 gatewaySn。
而 940 条测试全绿，因为所有结构钉用 index("function loadRemoteControl(") **只取第一处**，
钉到的是那个永不执行的版本。教训：钉"某函数必须做 X"的前提是"该函数只有一个"。
"""
import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "www" / "js" / "huijian.js"

_FUNC_RE = re.compile(r"^[ \t]*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", re.M)


def _names(src: str):
    return _FUNC_RE.findall(src)


def _single_func_body(src: str, name: str) -> str:
    """取唯一那个函数的花括号全体；0 处或多处都报错（绝不静默取第一处）。"""
    hits = list(re.finditer(r"^[ \t]*(?:async\s+)?function\s+" + re.escape(name) + r"\s*\(", src, re.M))
    assert len(hits) == 1, "函数 %s 出现 %d 次（应为 1；重名＝后者覆盖前者，钉会验到死码）" % (name, len(hits))
    i = src.index("{", hits[0].end())
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    raise AssertionError("函数 %s 花括号不配平（解析锚点失效）" % name)


def test_no_duplicate_function_definitions():
    src = JS.read_text(encoding="utf-8")
    names = _names(src)
    assert names, "解析锚点失效：一个函数都没抽到（守卫会假绿）"        # 元钉
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert not dupes, "huijian.js 存在重复定义的函数：%s" % dupes


def test_load_remote_control_goes_through_single_exit():
    body = _single_func_body(JS.read_text(encoding="utf-8"), "loadRemoteControl")
    assert "applyHubStatus(" in body, "loadRemoteControl 必须走统一渲染出口 applyHubStatus"
    assert "renderBindQr(" not in body, "不得绕过统一出口直调 renderBindQr"
    assert "hubCodeExp" not in body, "过期文案由 applyHubStatus 统一写，别在这里各写一份"


def test_old_renderer_markers_are_gone():
    """旧版渲染器的指纹必须消失（只判"不存在"是单侧钉，所以配上面那条正向钉一起看）。"""
    src = JS.read_text(encoding="utf-8")
    assert src.count("async function loadRemoteControl(") == 1, "loadRemoteControl 只能有一份定义"
    assert "info.gatewaySn || '—'" not in src, "旧版直写 gatewaySn 的残留还在（应走 hubGatewayText）"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/AI/huijian-gateway-plugin && python -m pytest huijian_mqtt_broker/tests/test_v1746_panel_unique_funcs.py -q`
Expected: FAIL —— `test_no_duplicate_function_definitions` 报 `['loadRemoteControl']`；`_single_func_body` 断言"出现 2 次"。

- [ ] **Step 3: 删掉旧版实现**

删除 `www/js/huijian.js` 第 **207-245** 行整段（第二个 `async function loadRemoteControl() { … }`；特征：自己取 `hubDot/hubStatus/hubCode/hubGateway/hubGwDot`、直写 `info.gatewaySn || '—'`、三处直调 `renderBindQr`）。保留 `:170-179` 那份（走 `applyHubStatus`）。删完 `node --check` 必须过。

- [ ] **Step 4: 修两个既有抽取器，让它们"多处即报错"**

`tests/test_v1737_hub_ui.py:51-63` 与 `tests/test_v1738_hub_qr_ui.py:52-63` 的 `_func(src, name)`：换成与 `_single_func_body` 同语义（`len(hits) == 1` 断言 + 花括号计数取整段）。**两处都要改**——只改一处，另一处仍是假绿。

- [ ] **Step 5: 全量门禁 + Commit（等用户口令）**

Run:
```bash
cd /e/AI/huijian-gateway-plugin && node --check huijian_mqtt_broker/www/js/huijian.js && python -m pytest huijian_mqtt_broker/tests -q && ruff check --select F,E9,B --ignore B008,B905 huijian_mqtt_broker
```
Expected: `node --check` 无输出；pytest 全绿（940 + 3 = 943）；`test_v1738_hub_qr_ui.py` 的"除统一出口外不得直调 renderBindQr"反钉现在真的只看到一处出口。

```bash
git -C E:/AI/huijian-gateway-plugin add huijian_mqtt_broker/www/js/huijian.js huijian_mqtt_broker/tests/test_v1746_panel_unique_funcs.py huijian_mqtt_broker/tests/test_v1737_hub_ui.py huijian_mqtt_broker/tests/test_v1738_hub_qr_ui.py
git -C E:/AI/huijian-gateway-plugin commit -m "fix(panel): 删 loadRemoteControl 重复定义（v1.7.41 渲染改进一直是死码）+ 重名钉"
```

---

### Task B2: `hub_client.py` 成员码与成员管理

**Files:**
- Modify: `huijian_mqtt_broker/custom_components/window_controller_gateway/hub_client.py`（常量区 `:56` 后、`__init__` `:188` 后、`refresh_bind_code` `:355-389` 整体替换、`status_view` `:626-636` 追加键）
- Create: `huijian_mqtt_broker/tests/test_v1746_hub_members.py`

**Interfaces:**
- Consumes: hub `POST /agent/bindcode {instanceId,secret,kind}` → `{ok,bindCode,expiresInSec,kind}`；`POST /agent/members {instanceId,secret}` → `{ok,ownerMasked,members:[{mid,openidMasked,at}],membersMax}`；`POST /agent/unbind {instanceId,secret,mid}` → `{ok,removed,remaining}`
- Produces（api.py 与面板按这个用）:
  - 常量 `HUB_MEMBERS_MAX = 8`
  - `HubClient#refresh_bind_code(kind: str = "owner") -> bool`
  - `HubClient#member_code_expires_in() -> int`（无码/无签发时刻 → `-1`）
  - `HubClient#list_members() -> bool`、`HubClient#remove_member(mid: str) -> bool`
  - 属性 `member_code`、`members`（`list[dict]`，元素 `{"mid","openidMasked","at"}`）、`owner_masked`、`members_supported`（bool）
  - `status_view()` 新增键 `memberCode`/`memberCodeExpiresIn`/`memberCodeExpired`/`members`/`membersCount`/`membersMax`/`membersSupported`/`ownerMasked`

- [ ] **Step 1: 写失败测试**（新建 `tests/test_v1746_hub_members.py`；假 session/造客户端照 `tests/test_hub_client.py:176` 的写法）

```python
"""加载项侧的家庭成员链路：成员码签发（不受自动轮换/节流影响）、成员列表、踢人、老 hub 降级。"""
import time

import pytest

from . import hub_client as hc


@pytest.fixture
def client(tmp_path):
    c = hc.HubClient([], config_dir=str(tmp_path), session=object())
    c.instance_id = "inst-1"
    c._secret = "sec-1"
    c.bind_code = "111111"
    c._bind_code_at = time.time()
    return c


def _stub_http(client, replies):
    """把 _http 换成按路径回预置结果的假实现；记录每次调用的 (path, payload)。"""
    calls = []

    async def fake(path, payload):
        calls.append((path, payload))
        item = replies.get(path)
        if isinstance(item, Exception):
            raise item
        return dict(item) if item is not None else {"ok": False, "err": "not_found"}

    client._http = fake
    return calls


@pytest.mark.asyncio
async def test_member_code_request_carries_kind_and_lands_in_member_fields(client):
    calls = _stub_http(client, {"/agent/bindcode": {"ok": True, "bindCode": "654321", "kind": "member"}})
    assert await client.refresh_bind_code("member") is True
    assert calls[0][1]["kind"] == "member", "载荷必须带 kind，否则 hub 会当成 owner 码轮换"
    assert client.member_code == "654321"
    assert client.bind_code == "111111", "签成员码不得动 owner 码（用户可能正在扫）"
    assert client.member_code_expires_in() > 0


@pytest.mark.asyncio
async def test_old_hub_without_kind_echo_degrades_and_is_not_used_as_member_code(client):
    """老 hub 忽略 kind ⇒ 它其实轮换的是 owner 码。判据只能是响应里的 kind 回显。"""
    _stub_http(client, {"/agent/bindcode": {"ok": True, "bindCode": "999999"}})
    assert await client.refresh_bind_code("member") is False
    assert client.member_code is None, "不得把老 hub 回的 owner 码当成员码显示（家人会扫到"成为主人"的码）"
    assert client.last_error == "hub_too_old_for_member_code"
    assert client.members_supported is False


@pytest.mark.asyncio
async def test_member_code_never_auto_renews(client):
    """反钉：自动补发只服务 owner 码——成员码是显式意图，自动轮换会让主人已截图发出去的码失效。"""
    calls = _stub_http(client, {"/agent/bindcode": {"ok": True, "bindCode": "123123", "kind": "owner"}})
    client.member_code = "654321"
    client._member_code_at = time.time() - hc.BIND_CODE_TTL_S - 10      # 成员码已过期
    client._bind_code_at = time.time()                                   # owner 码还新鲜
    await client._renew_bind_code_if_stale()
    assert calls == [], "owner 码没过期就不该发请求；成员码过期也不该自动换"
    assert client.member_code == "654321"


@pytest.mark.asyncio
async def test_member_code_panel_path_is_not_throttled(client):
    """面板显式点「添加家人」不受 BIND_CODE_RENEW_MIN_INTERVAL_S 节流（与点二维码同口径）。"""
    _stub_http(client, {"/agent/bindcode": {"ok": True, "bindCode": "123123", "kind": "member"}})
    client._bind_renew_at = time.time()          # 刚刚才尝试过（若在节流窗口内）
    assert await client.refresh_bind_code("member") is True, "显式请求不得被节流挡掉"


@pytest.mark.asyncio
async def test_list_members_fills_view(client):
    _stub_http(client, {"/agent/members": {
        "ok": True, "ownerMasked": "oeh…mU", "membersMax": 8,
        "members": [{"mid": "a" * 12, "openidMasked": "ope…om", "at": 1}]}})
    assert await client.list_members() is True
    view = client.status_view()
    assert view["membersSupported"] is True
    assert view["membersCount"] == 1 and view["membersMax"] == 8
    assert view["members"][0]["openidMasked"] == "ope…om"
    assert view["ownerMasked"] == "oeh…mU"
    assert "sec-1" not in str(view), "视图不得回显 secret"


@pytest.mark.asyncio
async def test_list_members_on_old_hub_degrades_without_breaking_link(client):
    _stub_http(client, {"/agent/members": RuntimeError("hub /agent/members -> 404")})
    assert await client.list_members() is False
    assert client.members_supported is False, "老 hub 无此端点 ⇒ 面板要禁用成员区，而不是显示'读取失败'"
    assert client.last_error == "members_unavailable"


@pytest.mark.asyncio
async def test_remove_member_sends_mid_and_secret(client):
    calls = _stub_http(client, {
        "/agent/unbind": {"ok": True, "removed": "ope…om", "remaining": 0},
        "/agent/members": {"ok": True, "ownerMasked": "oeh…mU", "membersMax": 8, "members": []}})
    assert await client.remove_member("a" * 12) is True
    assert calls[0][1]["mid"] == "a" * 12
    assert calls[0][1]["instanceId"] == "inst-1" and calls[0][1]["secret"] == "sec-1"


@pytest.mark.asyncio
async def test_remove_member_failure_does_not_echo_secret(client):
    _stub_http(client, {"/agent/unbind": RuntimeError("hub /agent/unbind -> 403 sec-1")})
    assert await client.remove_member("a" * 12) is False
    assert client.last_error == "member_remove_failed"
    assert "sec-1" not in str(client.last_error), "last_error 不得回显凭据"


def test_members_max_constant_matches_hub():
    assert hc.HUB_MEMBERS_MAX == 8
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/AI/huijian-gateway-plugin && python -m pytest huijian_mqtt_broker/tests/test_v1746_hub_members.py -q`
Expected: FAIL —— `refresh_bind_code()` 不接受参数、无 `member_code`/`members_supported`、无 `list_members`/`remove_member`。

- [ ] **Step 3: 实现**

常量区（`:56` 之后）：
```python
HUB_MEMBERS_MAX = 8                 # 与 hub 的 HUB_MEMBERS_MAX 同值（跨仓钉对账：改一边必须改另一边）
```

`__init__`（`:188` `self.bind_code` 之后）：
```python
        self.member_code: Optional[str] = None   # 成员码只给面板看，**不落身份文件**（短命且属显式操作）
        self._member_code_at: float = 0.0
        self.members: List[Dict[str, Any]] = []  # hub 回的掩码成员列表（原样透传给面板）
        self.owner_masked: Optional[str] = None
        self.members_supported: bool = True      # 老 hub 无 /agent/* 成员端点时置 False，面板据此禁用成员区
```

整体替换 `refresh_bind_code`（`:355-389`），并在其后新增三个方法：
```python
    async def refresh_bind_code(self, kind: str = "owner") -> bool:
        """向 hub 换一个新绑定码（旧码当场作废）。kind='member' 换的是成员码。

        面板"点二维码/添加家人"与 owner 码的自动补发都走这里。失败只记日志回 False——
        绑定码拿不到不影响本地控制与云通道本身。
        """
        if not (self.instance_id and self._secret):
            self._load_identity()
        if not (self.instance_id and self._secret):
            return False
        kind = "member" if kind == "member" else "owner"
        self._bind_renew_at = time.time()     # 成功失败都算一次尝试（自动补发侧的节流基准）
        try:
            data = await self._http("/agent/bindcode", {
                "instanceId": self.instance_id,
                "secret": self._secret,
                "kind": kind,
            })
        except Exception as e:  # noqa: BLE001 - 网络/旧 hub 无此端点都只降级
            why = str(e) or type(e).__name__
            if self._secret and self._secret in why:
                why = type(e).__name__        # 万一消息里带上凭据，绝不回显
            self.last_error = "bindcode_failed"
            self._logger.warning("hub 换绑定码失败（kind=%s）：%s", kind, why)
            return False
        if not data.get("ok") or not data.get("bindCode"):
            self.last_error = "bindcode_rejected"
            self._logger.warning("hub 换绑定码被拒（kind=%s）：%s", kind, data.get("err"))
            return False
        if kind == "member" and data.get("kind") != "member":
            # 老 hub 忽略 kind ⇒ 它轮换的其实是 owner 码（用户正在扫的那张已作废，覆水难收）。
            # 判据只能是响应里的 kind 回显；此处必须**丢弃**返回值，否则面板会把 owner 码
            # 当成员码显示，家人扫到的就是"成为主人"的码。
            self.members_supported = False
            self.last_error = "hub_too_old_for_member_code"
            self._logger.warning("云端 hub 版本过旧（/agent/bindcode 不回 kind），已忽略成员码请求")
            return False
        if kind == "member":
            self.member_code = data["bindCode"]
            self._member_code_at = time.time()
            self._logger.info("hub 成员码已签发（%s）", cred_brief(self.member_code))
            return True
        self.bind_code = data["bindCode"]
        self._bind_code_at = time.time()
        self._save_identity()
        self._logger.info("hub 绑定码已更新（%s）", cred_brief(self.bind_code))
        return True

    def member_code_expires_in(self) -> int:
        """成员码剩余秒数（-1＝无码/签发时刻未知，与 owner 码同口径：不当"刚过期"渲染）。"""
        if not self.member_code or not self._member_code_at:
            return -1
        return int(BIND_CODE_TTL_S - (time.time() - self._member_code_at))

    async def list_members(self) -> bool:
        """拉家庭成员（掩码 + mid 句柄）。老 hub 无此端点 ⇒ 只降级，绝不影响长连。"""
        if not (self.instance_id and self._secret):
            self._load_identity()
        if not (self.instance_id and self._secret):
            return False
        try:
            data = await self._http("/agent/members", {
                "instanceId": self.instance_id,
                "secret": self._secret,
            })
        except Exception as e:  # noqa: BLE001
            why = str(e) or type(e).__name__
            if self._secret and self._secret in why:
                why = type(e).__name__
            self.members_supported = False
            self.last_error = "members_unavailable"
            self._logger.warning("hub 取家庭成员失败：%s", why)
            return False
        if not data.get("ok"):
            self.members_supported = False
            self.last_error = "members_rejected"
            self._logger.warning("hub 取家庭成员被拒：%s", data.get("err"))
            return False
        self.members_supported = True
        self.members = list(data.get("members") or [])
        self.owner_masked = data.get("ownerMasked")
        return True

    async def remove_member(self, mid: str) -> bool:
        """按 mid 踢一个成员（面板「移除」）。mid 由 list_members 给出，稳定且不可逆推。"""
        if not (self.instance_id and self._secret) or not mid:
            return False
        try:
            data = await self._http("/agent/unbind", {
                "instanceId": self.instance_id,
                "secret": self._secret,
                "mid": str(mid),
            })
        except Exception as e:  # noqa: BLE001
            why = str(e) or type(e).__name__
            if self._secret and self._secret in why:
                why = type(e).__name__
            self.last_error = "member_remove_failed"
            self._logger.warning("hub 移除成员失败：%s", why)
            return False
        if not data.get("ok"):
            self.last_error = "member_remove_rejected"
            self._logger.warning("hub 移除成员被拒：%s", data.get("err"))
            return False
        self._logger.info("家庭成员已移除（剩余 %s）", data.get("remaining"))
        await self.list_members()
        return True
```

`status_view()` 返回字典（`:626-636`）追加：
```python
            "memberCode": self.member_code,
            "memberCodeExpiresIn": self.member_code_expires_in(),
            "memberCodeExpired": bool(self.member_code) and self.member_code_expires_in() <= 0,
            "members": list(self.members),
            "membersCount": len(self.members),
            "membersMax": HUB_MEMBERS_MAX,
            "membersSupported": bool(self.members_supported),
            "ownerMasked": self.owner_masked,
```

- [ ] **Step 4: 跑测试确认全绿（含既有 41 条 hub 用例）**

Run: `cd /e/AI/huijian-gateway-plugin && python -m pytest huijian_mqtt_broker/tests/test_v1746_hub_members.py huijian_mqtt_broker/tests/test_hub_client.py -q`
Expected: 全绿（新 9 + 既有 41）。若既有换码用例红，是因为它们的假响应没有 `kind` 字段——**给桩补 `"kind": "owner"`，不要放宽实现**（桩必须不窄于真实现，本仓已三次踩过）。

- [ ] **Step 5: Commit（等用户口令）**

```bash
git -C E:/AI/huijian-gateway-plugin add huijian_mqtt_broker/custom_components/window_controller_gateway/hub_client.py huijian_mqtt_broker/tests/test_v1746_hub_members.py huijian_mqtt_broker/tests/test_hub_client.py
git -C E:/AI/huijian-gateway-plugin commit -m "feat(hub): 加载项成员码签发 + 成员列表/踢人 + 老 hub 降级"
```

---

### Task B3: `api.py` 三条路由

**Files:**
- Modify: `huijian_mqtt_broker/custom_components/window_controller_gateway/api.py`（`WindowGatewayHubBindCodeView.post` `:182-192`；文件末尾新增两个视图类；`async_setup_api` `:24-29` 注册）
- Test: `huijian_mqtt_broker/tests/test_v1746_hub_members.py`（追加）

**Interfaces:**
- Consumes: B2 的 `refresh_bind_code(kind)`/`list_members()`/`remove_member(mid)`/`status_view()`；`_hub_client(hass)`（`api.py:142-147`）
- Produces:
  - `POST /api/window_controller_gateway/hub/bindcode` body 可选 `{"kind":"member"}` → `status_view() + {enabled, refreshOk}`
  - `GET /api/window_controller_gateway/hub/members` → `{enabled, ok, ownerMasked, members, membersMax, membersSupported}`
  - `POST /api/window_controller_gateway/hub/members/remove` body `{"mid":"..."}` → 同上 + `removedOk`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_v1746_hub_members.py`）

```python
def _api_src() -> str:
    from pathlib import Path
    return (Path(__file__).resolve().parents[1] / "custom_components" /
            "window_controller_gateway" / "api.py").read_text(encoding="utf-8")


def test_api_registers_all_four_hub_routes():
    """路由存在性 + 注册齐全（面板只认这些 url，少一条就是"点了没反应"）。"""
    src = _api_src()
    for url in (
        '"/api/window_controller_gateway/hub"',
        '"/api/window_controller_gateway/hub/bindcode"',
        '"/api/window_controller_gateway/hub/members"',
        '"/api/window_controller_gateway/hub/members/remove"',
    ):
        assert url in src, "api.py 缺路由 %s" % url
    # 只定义不注册＝没接线（v1.7.44 的同型教训），所以两处都要数到
    assert src.count("WindowGatewayHubMembersView") >= 2, "成员视图既要定义也要注册"
    assert src.count("WindowGatewayHubMemberRemoveView") >= 2, "移除视图既要定义也要注册"


def test_bindcode_view_passes_kind_through():
    src = _api_src()
    assert 'payload.get("kind")' in src, "bindcode 视图必须把 kind 透传给 hub_client"
    assert 'refresh_bind_code(kind)' in src, "必须以 kind 调用，不能写死 owner"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/AI/huijian-gateway-plugin && python -m pytest huijian_mqtt_broker/tests/test_v1746_hub_members.py -q -k api or kind`
Expected: FAIL（路由与 kind 透传都不存在）。

- [ ] **Step 3: 实现**

`WindowGatewayHubBindCodeView.post` 里把 `ok = await client.refresh_bind_code()` 换成：
```python
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001 - 无体/坏体一律按 owner 码处理（老面板就是不带 body 的）
            payload = {}
        kind = "member" if isinstance(payload, dict) and payload.get("kind") == "member" else "owner"
        ok = await client.refresh_bind_code(kind)
        if kind == "member":
            await client.list_members()      # 点「添加家人」后顺手刷新成员列表，省一次往返
```

文件末尾新增：
```python
class WindowGatewayHubMembersView(http.HomeAssistantView):
    """v1.7.46: 家庭成员列表（掩码 openid + mid 句柄）。

    只读，但**必须经 hub 取**：成员关系的真相在云端，本地不留副本（留了就会与 hub 分叉）。
    老 hub 没有 /agent/members ⇒ 回 membersSupported=False，面板据此禁用成员区，
    而不是显示"读取失败"（那会让人以为云通道坏了）。
    """

    url = "/api/window_controller_gateway/hub/members"
    name = "api:window_controller_gateway:hub:members"

    async def get(self, request):
        hass = request.app["hass"]
        client = _hub_client(hass)
        if client is None:
            return self.json({"enabled": False, "ok": False, "members": [], "membersSupported": False})
        ok = await client.list_members()
        view = client.status_view()
        return self.json({
            "enabled": True,
            "ok": bool(ok),
            "ownerMasked": view.get("ownerMasked"),
            "members": view.get("members") or [],
            "membersMax": view.get("membersMax"),
            "membersSupported": bool(view.get("membersSupported")),
        })


class WindowGatewayHubMemberRemoveView(http.HomeAssistantView):
    """v1.7.46: 移除一个家庭成员（按 mid）。

    必须是 POST：这是有副作用的写操作（被踢的人立刻失去控制权），不能被"看一眼状态"顺带触发。
    """

    url = "/api/window_controller_gateway/hub/members/remove"
    name = "api:window_controller_gateway:hub:members:remove"

    async def post(self, request):
        hass = request.app["hass"]
        client = _hub_client(hass)
        if client is None:
            return self.json({"enabled": False, "removedOk": False})
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            payload = {}
        mid = str((payload or {}).get("mid") or "")
        removed = bool(mid) and await client.remove_member(mid)
        await client.list_members()
        view = client.status_view()
        return self.json({
            "enabled": True,
            "removedOk": removed,
            "ownerMasked": view.get("ownerMasked"),
            "members": view.get("members") or [],
            "membersMax": view.get("membersMax"),
            "membersSupported": bool(view.get("membersSupported")),
        })
```

`async_setup_api`（`:24-29`）照现有两行追加：
```python
    hass.http.register_view(WindowGatewayHubMembersView)
    hass.http.register_view(WindowGatewayHubMemberRemoveView)
```

- [ ] **Step 4: 跑测试确认全绿**

Run: `cd /e/AI/huijian-gateway-plugin && python -m pytest huijian_mqtt_broker/tests -q`
Expected: 全绿（新增 2 条）。

- [ ] **Step 5: Commit（等用户口令）**

```bash
git -C E:/AI/huijian-gateway-plugin add huijian_mqtt_broker/custom_components/window_controller_gateway/api.py huijian_mqtt_broker/tests/test_v1746_hub_members.py
git -C E:/AI/huijian-gateway-plugin commit -m "feat(api): 家庭成员列表与移除路由 + bindcode 收 kind"
```

---

### Task B4: 面板「家庭成员」区

**Files:**
- Modify: `huijian_mqtt_broker/www/index.html`（`#remoteCard` 内、`hubQr` 块 `:113-118` 之后）
- Modify: `huijian_mqtt_broker/www/js/huijian.js`（`applyHubStatus` `:127-168` 末尾追加渲染；新增 4 个函数；`haApi` `:432-436` 支持 body）
- Create: `huijian_mqtt_broker/tests/test_v1746_panel_members.py`
- Modify: `huijian_mqtt_broker/tests/test_v1737_hub_ui.py:86-103`（路由等式钉扩到两条新路由）

**Interfaces:**
- Consumes: B3 的三条路由；B1 的"唯一渲染出口"纪律；现有 `BIND_PAYLOAD_PREFIX`（`:70`）、`window.HjQr.render`、`haApi`、`fetchT`
- Produces: DOM id `hubMembersCount`/`hubMembersEmpty`/`hubMembers`/`addMemberBtn`/`hubMemberQr`/`hubMemberQrBox`/`hubMemberTip`/`hubMemberCode`/`hubMemberExp`；JS 函数 `membersText(info)`（纯函数，node 可真跑）、`renderMemberQr(code)`、`renderMembers(info)`、`refreshMemberCode()`、`removeMember(mid)`

- [ ] **Step 1: 写失败测试**（新建 `tests/test_v1746_panel_members.py`）

```python
"""面板成员区：DOM 齐全、渲染只走统一出口、满 8 人禁用、老 hub 禁用、node 真跑纯函数。"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "www" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "www" / "js" / "huijian.js").read_text(encoding="utf-8")

IDS = ["hubMembersCount", "hubMembersEmpty", "hubMembers", "addMemberBtn",
       "hubMemberQr", "hubMemberQrBox", "hubMemberTip", "hubMemberCode", "hubMemberExp"]


def test_member_dom_ids_all_present():
    missing = [i for i in IDS if ('id="%s"' % i) not in HTML]
    assert not missing, "index.html 缺成员区 DOM：%s" % missing


def test_member_section_lives_inside_remote_card():
    """成员区必须在「远程控制（慧尖云）」卡内（v1.7.38 用户令：别摆页头）。"""
    card = HTML.split('id="remoteCard"', 1)[1]
    for i in IDS:
        assert ('id="%s"' % i) in card, "%s 不在 #remoteCard 内" % i


def test_render_member_qr_has_exactly_one_call_site():
    """单一出口纪律：定义 1 处 + applyHubStatus 内调用 1 处，多出口＝漏渲染。"""
    hits = re.findall(r"renderMemberQr\(", JS)
    assert len(hits) == 2, "renderMemberQr 应恰好出现 2 次（定义 + 唯一调用），实得 %d" % len(hits)
    body = JS.split("function applyHubStatus(", 1)[1]
    assert "renderMemberQr(" in body and "renderMembers(" in body, "成员区渲染必须挂在统一出口里"


def test_member_code_payload_reuses_owner_prefix():
    """载荷前缀必须与 owner 码相同（角色由 hub 查表决定，不写进载荷）。"""
    assert JS.count("BIND_PAYLOAD_PREFIX + code") >= 2, "成员码二维码要用同一个前缀常量"
    assert "HUJIAN-BIND" in JS and JS.count("HUJIAN-BIND") == 1, "前缀字面量只能有一处（常量）"


def test_node_really_renders_member_states():
    """纯函数真跑（照 test_v1743_hub_singleton.py 的 hubGatewayText 写法）：不打桩判断。"""
    if shutil.which("node") is None:
        raise AssertionError("node 不可用，无法真跑渲染函数")
    m = re.search(r"function membersText\(info\) \{[\s\S]*?\n {8}\}", JS)
    assert m, "huijian.js 里必须有纯函数 membersText(info)"
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "m.js"
        p.write_text(m.group(0) + """
const cases = [
  [{membersSupported:false}, '云端版本过旧'],
  [{membersSupported:true, members:[]}, '只有你一人'],
  [{membersSupported:true, membersMax:8, members:[{openidMasked:'ope…om',at:1}]}, '1 / 8 人'],
  [{membersSupported:true, membersMax:8, members:Array.from({length:8},(_,i)=>({openidMasked:'o'+i,at:1}))}, '8 / 8 人'],
];
for (const [info, want] of cases) {
  const got = membersText(info);
  if (!got.includes(want)) { console.log('FAIL', JSON.stringify(info), '->', got, 'want~', want); process.exit(1) }
}
console.log('OK');
""", encoding="utf-8")
        r = subprocess.run(["node", str(p)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0 and "OK" in r.stdout, "node 真跑失败：%s%s" % (r.stdout, r.stderr)


def test_copy_rules():
    for s in ["添加家人", "家庭成员", "只有你一人", "移除", "小慧语音"]:
        assert s in JS or s in HTML, "缺文案：%s" % s
    assert "Matter" not in HTML and "Matter" not in JS, "文案口径：不得出现 Matter"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/AI/huijian-gateway-plugin && python -m pytest huijian_mqtt_broker/tests/test_v1746_panel_members.py -q`
Expected: FAIL（DOM、函数、文案都不存在）。

- [ ] **Step 3: 加 DOM**（`www/index.html`，`#remoteCard` 内、`hubQr` 块之后）

```html
                <div class="hub-members">
                    <div class="hub-row">
                        <span class="hub-label">家庭成员</span>
                        <span id="hubMembersCount" class="hub-value">—</span>
                        <button type="button" id="addMemberBtn" class="btn-mini"
                                onclick="refreshMemberCode()"
                                title="生成一个 10 分钟有效的一次性成员码">添加家人</button>
                    </div>
                    <div id="hubMembersEmpty" class="hub-tip">只有你一人</div>
                    <ul id="hubMembers" class="hub-member-list"></ul>
                    <div id="hubMemberQr" class="hub-qr" hidden>
                        <div id="hubMemberQrBox" class="hub-qr-box"></div>
                        <div id="hubMemberTip" class="hub-tip"></div>
                        <div class="hub-row">
                            <span id="hubMemberCode" class="hub-code">------</span>
                            <span id="hubMemberExp" class="hub-tip"></span>
                        </div>
                    </div>
                </div>
```

- [ ] **Step 4: 加 JS**（`www/js/huijian.js`，放在 `applyHubStatus` 之前）

```javascript
        /** 成员区口径文案（纯函数，便于 node 真跑）。
         *  老 hub（membersSupported=false）必须说清是"云端版本过旧"，不能显示成"读取失败"。*/
        function membersText(info) {
            if (!info || info.membersSupported === false) return '云端版本过旧，暂不支持';
            const list = Array.isArray(info.members) ? info.members : [];
            const max = info.membersMax || 8;
            if (!list.length) return '只有你一人';
            return list.length + ' / ' + max + ' 人';
        }

        function renderMemberQr(code) {
            const wrap = document.getElementById('hubMemberQr');
            const box = document.getElementById('hubMemberQrBox');
            const tip = document.getElementById('hubMemberTip');
            const codeEl = document.getElementById('hubMemberCode');
            if (!wrap || !box) return;
            if (!code || !window.HjQr) { wrap.hidden = true; return; }
            try {
                // 载荷前缀与 owner 码**完全相同**：角色由 hub 按码查表决定，不写进载荷
                window.HjQr.render(box, BIND_PAYLOAD_PREFIX + code, { ecc: 'M' });
            } catch (e) {
                wrap.hidden = true;          // 生成失败宁可不摆——扫不出来的码比没有码更坏
                console.log('成员码二维码生成失败:', e);
                return;
            }
            wrap.hidden = false;
            if (tip) tip.textContent = '家人用「小慧语音」扫一扫；10 分钟内有效，扫完即失效';
            if (codeEl) codeEl.textContent = code;
        }

        function renderMembers(info) {
            const ul = document.getElementById('hubMembers');
            const empty = document.getElementById('hubMembersEmpty');
            const countEl = document.getElementById('hubMembersCount');
            const btn = document.getElementById('addMemberBtn');
            if (!ul) return;
            const supported = !info || info.membersSupported !== false;
            const list = (info && Array.isArray(info.members)) ? info.members : [];
            const max = (info && info.membersMax) || 8;
            if (countEl) countEl.textContent = membersText(info);
            if (empty) {
                empty.textContent = supported ? '只有你一人' : '云端版本过旧，暂不支持';
                empty.hidden = supported && list.length > 0;
            }
            // 满员或老 hub 都禁用按钮：能点但必然失败，比不能点更让人困惑
            if (btn) {
                btn.disabled = !supported || list.length >= max;
                btn.title = !supported ? '云端 hub 版本过旧'
                    : (list.length >= max ? '家庭成员已满（' + max + ' 人）'
                                          : '生成一个 10 分钟有效的一次性成员码');
            }
            ul.textContent = '';
            for (const m of list) {
                if (!m || !m.mid) continue;
                const li = document.createElement('li');
                const span = document.createElement('span');
                span.textContent = m.openidMasked || '—';      // 只有掩码：hub 从不回完整 openid
                const kick = document.createElement('button');
                kick.type = 'button';
                kick.className = 'btn-mini';
                kick.textContent = '移除';
                kick.setAttribute('data-mid', String(m.mid));
                kick.onclick = function () { removeMember(String(m.mid)); };
                li.appendChild(span);
                li.appendChild(kick);
                ul.appendChild(li);
            }
        }

        /** 显式签发成员码（不受自动轮换与节流影响：这是主人的显式意图）。*/
        async function refreshMemberCode() {
            try {
                const resp = await haApi('/window_controller_gateway/hub/bindcode', 'POST', { kind: 'member' });
                if (!resp.ok) throw new Error('HA API ' + resp.status);
                applyHubStatus(await resp.json());
            } catch (e) {
                console.log('成员码签发失败:', e);
                await loadRemoteControl();
            }
        }

        async function removeMember(mid) {
            if (!mid) return;
            if (!window.confirm('移除后这位家人立刻失去远程控制权，确定？')) return;
            try {
                const resp = await haApi('/window_controller_gateway/hub/members/remove', 'POST', { mid: mid });
                if (!resp.ok) throw new Error('HA API ' + resp.status);
            } catch (e) {
                console.log('移除成员失败:', e);
            }
            await loadRemoteControl();
        }
```

`applyHubStatus`（`:127-168`）末尾（`renderBindQr(...)` 之后）追加，让它成为成员区唯一出口：
```javascript
            renderMemberQr((info && info.memberCode && !info.memberCodeExpired) ? info.memberCode : '');
            renderMembers(info);
            const memExpEl = document.getElementById('hubMemberExp');
            if (memExpEl) {
                const memIn = info ? info.memberCodeExpiresIn : -1;
                if (!info || !info.memberCode) memExpEl.textContent = '';
                else if (info.memberCodeExpired || memIn <= 0) memExpEl.textContent = '已过期，点「添加家人」换新码';
                else if (memIn < 0) memExpEl.textContent = '';
                else memExpEl.textContent = '剩余 ' + Math.max(1, Math.round(memIn / 60)) + ' 分钟';
            }
```

`haApi`（`:432-436`）加第三个参数（**改前先读它与 `fetchT` 的真实签名**，保持既有 GET 调用点行为不变）：
```javascript
        async function haApi(path, method, body) {
            const opt = { method: method || 'GET', headers: { 'content-type': 'application/json' } };
            if (body !== undefined) opt.body = JSON.stringify(body);
            return fetchT(INGRESS_BASE + 'api/ha/' + path.replace(/^\//, ''), opt);
        }
```

`tests/test_v1737_hub_ui.py:86-103` 的路由等式钉：把新路由纳入比对集合（它从 `api.py` 抽 `url="..."` 全集、与 `huijian.js` 里 `haApi('...')` 真值逐字比）——**成员移除那条必须出现在面板调用里**，否则钉会红，这正是我们要的。

- [ ] **Step 5: 门禁 + Commit（等用户口令）**

Run:
```bash
cd /e/AI/huijian-gateway-plugin && node --check huijian_mqtt_broker/www/js/huijian.js && python -m pytest huijian_mqtt_broker/tests -q && python -m compileall -q huijian_mqtt_broker/custom_components && ruff check --select F,E9,B --ignore B008,B905 huijian_mqtt_broker
```
Expected: 全绿（含 B1 的重名钉——新增 5 个函数各只定义一次）。

```bash
git -C E:/AI/huijian-gateway-plugin add huijian_mqtt_broker/www/index.html huijian_mqtt_broker/www/js/huijian.js huijian_mqtt_broker/tests/test_v1746_panel_members.py huijian_mqtt_broker/tests/test_v1737_hub_ui.py
git -C E:/AI/huijian-gateway-plugin commit -m "feat(panel): 「家庭成员」区——添加家人/成员码二维码/移除成员"
```

---

## Phase C — 小程序 v1.4.26

### Task C1: 绑定存储分桶 + 老格式迁移 + `role` + 真解绑

**Files:**
- Modify: `E:\AI\ha-yy\weichat-huijian-hz\miniprogram\utils\cloud-gw.js`（绑定区 `:49-80`、导出 `:140-154`）
- Create: `E:\AI\ha-yy\weichat-huijian-hz\tests\cloud-multi-bind.test.js`
- Modify: `E:\AI\ha-yy\weichat-huijian-hz\package.json`（test 链挂新文件；`version` → `1.4.26`）
- Modify: `E:\AI\ha-yy\weichat-huijian-hz\tests\cloud-gw.test.js:148-150`（"绑定落地"那条断言改读 `getBinding()`，不再断言单对象形状）

**Interfaces:**
- Produces:
  - 存储形态 `{ v: 2, active: <instanceId>, bindings: { [instanceId]: { sn, role, at } } }`
  - `getBinding() -> {instanceId, sn, role} | null`（active 那条；对既有调用点形状兼容，多出 `role`）
  - `getBindings() -> Array<{instanceId, sn, role, at}>`、`setActiveBinding(instanceId) -> boolean`
  - `setBinding(binding)`（落对应桶并把 active 指过去）、`clearBinding(instanceId?)`（不传＝清 active；**其余绑定保留**）
  - `bindByCode(code) -> hub 原样返回`（成功即落桶，带 `role`，缺 `role` 兜 `'owner'`）
  - `unbind(instanceId?) -> Promise<{ok, local:true, err?}>`（**真发 `/unbind`**，失败也清本机）
  - 常量 `STORAGE_VERSION = 2`

- [ ] **Step 1: 写失败测试**（新建 `tests/cloud-multi-bind.test.js`；`t/ta` + 假 `wx` 照 `tests/cloud-gw.test.js:16-66`，看门狗必须带——本仓踩过"挂死→node 静默 exit 0"）

```js
// tests/cloud-multi-bind.test.js —— 家庭多人绑定 + 多 HA 绑定分桶（v1.4.26）
const fs = require('fs')
const path = require('path')
const SRC = (p) => fs.readFileSync(path.join(__dirname, '..', p), 'utf8')

let pass = 0, fail = 0
function t(name, fn) {
  try { fn(); pass++; console.log('PASS ' + name) }
  catch (e) { fail++; console.log('FAIL ' + name + ' :: ' + e.message) }
}
function assert(c, m) { if (!c) throw new Error(m) }
const CASE_BUDGET_MS = 10000
let chain = Promise.resolve()
function ta(name, fn, ms = CASE_BUDGET_MS) {
  chain = chain.then(async () => {
    let timer
    const run = (async () => fn())()
    run.catch(() => {})                       // 看门狗已判红，别变成 unhandled rejection
    try {
      await Promise.race([run, new Promise((_, rej) => {
        timer = setTimeout(() => rej(new Error('用例超时 ' + ms + 'ms，疑似挂死')), ms)
      })])
      pass++; console.log('PASS ' + name)
    } catch (e) { fail++; console.log('FAIL ' + name + ' :: ' + e.message) }
    finally { clearTimeout(timer) }
  })
  return chain
}

const calls = { containers: [] }
let storage = {}
let containerImpl = null
global.wx = {
  getStorageSync: (k) => (k in storage ? storage[k] : ''),
  setStorageSync: (k, v) => { storage[k] = v },
  removeStorageSync: (k) => { delete storage[k] },
  showToast: () => {},
  getAccountInfoSync: () => ({ miniProgram: { envVersion: 'release' } }),
  cloud: {
    callContainer(opts) {
      calls.containers.push(opts)
      if (containerImpl) containerImpl(opts)
      else if (opts.success) opts.success({ statusCode: 200, data: { ok: true } })
    }
  }
}
const cloud = require('../miniprogram/utils/cloud-gw')
const router = require('../miniprogram/utils/gw-router')

function replyBind(instanceId, sn, role) {
  containerImpl = (o) => o.success({ statusCode: 200, data: { ok: true, instanceId, sn, role } })
}

async function main() {
  t('钉: 存储形态是 v2 分桶（不是单对象）', () => {
    const src = SRC('miniprogram/utils/cloud-gw.js')
    assert(/v:\s*STORAGE_VERSION|v:\s*2/.test(src), '必须写 v2 形态，否则迁移判据无从谈起')
    assert(/bindings/.test(src), '必须有 bindings 分桶')
  })

  storage = {}
  await ta('迁移: 老格式 {instanceId,sn} 读进来即搬进 v2 且成为 active', async () => {
    storage[cloud.STORAGE_KEY] = { instanceId: 'old-inst', sn: 'SN-OLD' }
    const b = cloud.getBinding()
    assert(b && b.instanceId === 'old-inst', '老绑定必须还能读到: ' + JSON.stringify(b))
    const raw = storage[cloud.STORAGE_KEY]
    assert(raw && raw.v === 2 && raw.active === 'old-inst', '应就地迁移成 v2: ' + JSON.stringify(raw))
    assert(raw.bindings && raw.bindings['old-inst'], '老绑定必须落进 bindings 桶')
    assert(raw.bindings['old-inst'].role === 'owner', '迁移时缺 role 应兜 owner')
  })

  await ta('两个 HA 安装可并存，setActiveBinding 切换后 getBinding 跟着变', async () => {
    storage = {}
    replyBind('inst-A', 'SN-A', 'owner')
    await cloud.bindByCode('111111')
    replyBind('inst-B', 'SN-B', 'member')
    await cloud.bindByCode('222222')
    assert(cloud.getBindings().length === 2, '应存两条: ' + JSON.stringify(cloud.getBindings()))
    assert(cloud.getBinding().instanceId === 'inst-B', 'active 应指向最后绑的那条')
    assert(cloud.setActiveBinding('inst-A') === true, '切换应成功')
    assert(cloud.getBinding().instanceId === 'inst-A', '切换后 getBinding 要跟着变')
    assert(cloud.getBinding().role === 'owner', 'role 要按桶保存')
    assert(cloud.setActiveBinding('no-such') === false, '切到不存在的绑定要回 false')
  })

  await ta('clearBinding 只清一条，另一条留着（这是"多 HA"的关键）', async () => {
    storage = {}
    replyBind('inst-A', 'SN-A', 'owner')
    await cloud.bindByCode('111111')
    replyBind('inst-B', 'SN-B', 'member')
    await cloud.bindByCode('222222')
    cloud.setActiveBinding('inst-B')
    cloud.clearBinding()
    assert(cloud.getBindings().length === 1, '应只剩一条: ' + JSON.stringify(cloud.getBindings()))
    assert(cloud.getBinding().instanceId === 'inst-A', 'active 要落到剩下那条')
    cloud.clearBinding('inst-A')
    assert(cloud.getBinding() === null, '全清完应回 null')
  })

  await ta('bindByCode 落 role；hub 不回 role 时兜 owner（老 hub 兼容）', async () => {
    storage = {}
    containerImpl = (o) => o.success({ statusCode: 200, data: { ok: true, instanceId: 'inst-C', sn: 'SN-C' } })
    await cloud.bindByCode('333333')
    assert(cloud.getBinding().role === 'owner', '缺 role 应兜 owner: ' + JSON.stringify(cloud.getBinding()))
  })

  await ta('unbindCloud 真发 /unbind；失败也清本机但回 ok:false', async () => {
    storage = {}
    calls.containers.length = 0
    replyBind('inst-U', 'SN-U', 'member')
    await cloud.bindByCode('444444')
    containerImpl = (o) => o.success({ statusCode: 200, data: { ok: true, removed: 'ope…om', remaining: 0 } })
    const r = await router.unbindCloud()
    assert(r && r.ok === true, '应回 hub 的 ok: ' + JSON.stringify(r))
    const sent = calls.containers.filter((c) => c.path === '/unbind')
    assert(sent.length === 1, '/unbind 必须真发一次，实得 ' + sent.length)
    assert(sent[0].data.instanceId === 'inst-U', 'body 要带 instanceId: ' + JSON.stringify(sent[0].data))
    assert(cloud.getBinding() === null, '本机绑定应已清')

    replyBind('inst-V', 'SN-V', 'member')
    await cloud.bindByCode('555555')
    containerImpl = (o) => o.success({ statusCode: 403, data: { ok: false, err: 'forbidden' } })
    const r2 = await router.unbindCloud()
    assert(r2 && r2.ok === false && r2.err === 'forbidden', '失败要如实回: ' + JSON.stringify(r2))
    assert(cloud.getBinding() === null, '失败也要清本机（否则页面永远显示已绑）')
  })

  await ta('switchCloudBinding 切换后 isCloudBound 与 active 一致', async () => {
    storage = {}
    replyBind('inst-A', 'SN-A', 'owner')
    await cloud.bindByCode('111111')
    replyBind('inst-B', 'SN-B', 'member')
    await cloud.bindByCode('222222')
    assert(router.switchCloudBinding('inst-A') === true, '切换应成功')
    assert(cloud.getBinding().instanceId === 'inst-A', 'active 要跟着变')
    assert(router.isCloudBound() === true, '有 active 就该算已绑')
  })

  console.log('\ncloud-multi-bind: ' + pass + ' passed, ' + fail + ' failed')
  process.exit(fail ? 1 : 0)
}
main()
```

- [ ] **Step 2: 挂进门禁并确认失败**

`package.json` 的 `test` 链尾追加 `&& node tests/cloud-multi-bind.test.js`（照现有链写法），`version` → `1.4.26`。
Run: `cd /e/AI/ha-yy/weichat-huijian-hz && node tests/cloud-multi-bind.test.js`
Expected: FAIL —— 无 `getBindings`/`setActiveBinding`/`unbind`，`getBinding()` 读的是单对象；`router.unbindCloud` 不发 `/unbind`。
另跑 `node tests/all-tests-wired.test.js` 确认新文件已被链上（漏挂守卫）。

- [ ] **Step 3: 实现（替换 `cloud-gw.js:49-80` 整段绑定区）**

```js
// ── 绑定关系（HA 实例 ↔ 微信账号）─────────────────────────────────
// v1.4.26 起按 instanceId **分桶**存多条：此前是单对象整键覆写，导致"一台手机只能
// 云绑一个 HA 安装"（绑第二处就把第一处顶掉）。形态：
//   { v: 2, active: <instanceId>, bindings: { [instanceId]: { sn, role, at } } }
// 老格式（{ instanceId, sn } 单对象）读到时**就地迁移**，用户不需要重扫。
const STORAGE_VERSION = 2

function _readRaw() {
  try {
    const raw = wx.getStorageSync(STORAGE_KEY)
    if (!raw) return null
    if (raw.v === STORAGE_VERSION && raw.bindings) return raw
    if (raw.instanceId) {                       // v1 单对象 → v2 分桶
      const migrated = { v: STORAGE_VERSION, active: raw.instanceId, bindings: {} }
      migrated.bindings[raw.instanceId] = { sn: raw.sn || '', role: raw.role || 'owner', at: Date.now() }
      try { wx.setStorageSync(STORAGE_KEY, migrated) } catch (e) { /* 迁移失败下次再迁 */ }
      return migrated
    }
    return null
  } catch (e) {
    return null
  }
}

function _writeRaw(raw) {
  try {
    wx.setStorageSync(STORAGE_KEY, raw)
  } catch (e) {
    log('[cloud-gw] 绑定关系写入失败:', e && e.message)
  }
}

function getBinding() {
  const raw = _readRaw()
  if (!raw) return null
  const b = raw.bindings[raw.active]
  return b ? { instanceId: raw.active, sn: b.sn || '', role: b.role || 'owner' } : null
}

function getBindings() {
  const raw = _readRaw()
  if (!raw) return []
  return Object.keys(raw.bindings).map((id) => ({
    instanceId: id,
    sn: (raw.bindings[id] && raw.bindings[id].sn) || '',
    role: (raw.bindings[id] && raw.bindings[id].role) || 'owner',
    at: (raw.bindings[id] && raw.bindings[id].at) || 0
  }))
}

function setActiveBinding(instanceId) {
  const raw = _readRaw()
  if (!raw || !raw.bindings[instanceId]) return false
  raw.active = instanceId
  _writeRaw(raw)
  return true
}

function setBinding(binding) {
  const b = binding || {}
  if (!b.instanceId) return
  const raw = _readRaw() || { v: STORAGE_VERSION, active: '', bindings: {} }
  raw.bindings[b.instanceId] = { sn: b.sn || '', role: b.role || 'owner', at: Date.now() }
  raw.active = b.instanceId
  _writeRaw(raw)
}

function clearBinding(instanceId) {
  const raw = _readRaw()
  if (!raw) {
    try { wx.removeStorageSync(STORAGE_KEY) } catch (e) { /* 忽略 */ }
    return
  }
  const target = instanceId || raw.active
  delete raw.bindings[target]
  const rest = Object.keys(raw.bindings)
  if (!rest.length) {
    try { wx.removeStorageSync(STORAGE_KEY) } catch (e) { /* 忽略 */ }
    return
  }
  if (raw.active === target) raw.active = rest[rest.length - 1]
  _writeRaw(raw)
}

async function bindByCode(code) {
  const res = await callHub('/bind', { bindCode: String(code || '').trim() })
  if (res && res.ok) {
    // role 由 hub 按码的种类决定（owner 码→owner，成员码→member）；老 hub 不回 role 时兜 owner
    setBinding({ instanceId: res.instanceId, sn: res.sn || '', role: res.role || 'owner' })
    log('[cloud-gw] 绑定成功 role=', res.role || 'owner')
  }
  return res
}

/** 解除绑定：真通知 hub（v1.4.26 起）。失败也清本机，但回 ok:false 让页面区分文案——
 *  只清本机会让人以为解绑了，而云端归属还在（家人仍能控制）。*/
async function unbind(instanceId) {
  const raw = _readRaw()
  const target = instanceId || (raw && raw.active)
  if (!target) return { ok: true, local: true }
  const res = await callHub('/unbind', { instanceId: target })
  clearBinding(target)
  return Object.assign({ local: true }, res || { ok: false, err: 'call_failed' })
}
```

导出块（`:140-154`）追加：`STORAGE_VERSION, getBindings, setActiveBinding, unbind`。

- [ ] **Step 4: 跑测试确认全绿**

Run: `cd /e/AI/ha-yy/weichat-huijian-hz && npm test`
Expected: 全绿。`cloud-gw.test.js:148-150` 若红，把断言从"读 storage 单对象"改成 `cloud.getBinding()`（**不要**为了让它绿而回退分桶）；`router.unbindCloud` 那条要到 C2 才绿——本步允许它红，C2 收口。

- [ ] **Step 5: Commit（等用户口令）**

```bash
git -C E:/AI/ha-yy/weichat-huijian-hz add miniprogram/utils/cloud-gw.js tests/cloud-multi-bind.test.js tests/cloud-gw.test.js package.json
git -C E:/AI/ha-yy/weichat-huijian-hz commit -m "feat(cloud-gw): 绑定按 instanceId 分桶（一台手机可云绑多个 HA）+ 真解绑"
```

---

### Task C2: `gw-router` 解绑真通知 hub + 切换绑定

**Files:**
- Modify: `miniprogram/utils/gw-router.js:177-195`（`cloudBinding`/`bindCloud`/`unbindCloud`/`parseBindPayload` 那段）
- Test: `tests/cloud-multi-bind.test.js`（C1 已写好两条：`unbindCloud 真发 /unbind`、`switchCloudBinding`）

**Interfaces:**
- Consumes: C1 的 `cloud.unbind`/`cloud.setActiveBinding`/`cloud.getBindings`/`cloud.getBinding`
- Produces: `router.unbindCloud() -> Promise<{ok, local, err?}>`（**由同步变异步**，所有调用点必须 await）；`router.switchCloudBinding(instanceId) -> boolean`；`router.cloudBindings() -> Array`

- [ ] **Step 1: 确认测试红**

Run: `cd /e/AI/ha-yy/weichat-huijian-hz && node tests/cloud-multi-bind.test.js`
Expected: FAIL —— `unbindCloud 真发 /unbind` 那条报"/unbind 必须真发一次，实得 0"。

- [ ] **Step 2: 实现（替换 `gw-router.js:177-195` 那段 facade）**

```js
  /** 当前云绑定（active 那条；形状 {instanceId, sn, role}） */
  cloudBinding() {
    return cloud.getBinding()
  }

  /** 全部云绑定（多 HA 安装时页面据此给切换入口） */
  cloudBindings() {
    return cloud.getBindings()
  }

  /** 切换当前操作的 HA 安装（切完由调用方重新 connect） */
  switchCloudBinding(instanceId) {
    const ok = cloud.setActiveBinding(instanceId)
    if (ok && this._mode === 'cloud') this.disconnect()
    return ok
  }

  /** 绑定：成功即落本地存储（失败回 {ok:false, err}，页面按 err 出中文提示） */
  async bindCloud(code) {
    return await cloud.bindByCode(code)
  }

  /** 解除绑定：**真通知 hub**（v1.4.26）。
   *  此前只清本机存储 ⇒ 云端归属还在，家人仍能控制，而用户以为解绑了。
   *  hub 拒了（403/404/网络）也照样清本机——页面不能永远显示"已绑定"——
   *  但要把 ok:false 与 err 如实回给调用方，让它出"云端可能仍保留"的文案。*/
  async unbindCloud() {
    const res = await cloud.unbind()
    if (this._mode === 'cloud') this.disconnect()
    return res
  }

  /** 解析二维码/剪贴板里的绑定载荷（认不出回 ''；页面据此给可见提示） */
  parseBindPayload(text) {
    return cloud.parseBindPayload(text)
  }
```

- [ ] **Step 3: 修所有调用点（同步 → await）**

`miniprogram/pages/broker-gateways/broker-gateways.js:263` 的 `this._broker.unbindCloud()` 改为 `const res = await this._broker.unbindCloud()`（所在方法 `doUnbindCloud` 要标 `async`）；全仓 grep `unbindCloud(` 确认没有其他遗漏调用点（`grep -rn "unbindCloud(" miniprogram/ tests/`）。

- [ ] **Step 4: 跑测试确认全绿**

Run: `cd /e/AI/ha-yy/weichat-huijian-hz && npm test`
Expected: 全绿（C1 遗留的两条现在过）；`node tests/check:syntax` 或 `npm run check:syntax` 也过。

- [ ] **Step 5: Commit（等用户口令）**

```bash
git -C E:/AI/ha-yy/weichat-huijian-hz add miniprogram/utils/gw-router.js miniprogram/pages/broker-gateways/broker-gateways.js tests/cloud-multi-bind.test.js
git -C E:/AI/ha-yy/weichat-huijian-hz commit -m "feat(gw-router): 解绑真通知 hub + 多 HA 绑定切换"
```

---

### Task C3: 「LoRa 网关」页角色/多 HA/文案

**Files:**
- Modify: `miniprogram/pages/broker-gateways/broker-gateways.wxml:105-125`（绑定卡）
- Modify: `miniprogram/pages/broker-gateways/broker-gateways.js`（`data` `:11-15`、`refreshRemote` `:166-178`、`doUnbindCloud` `:257-268`、`_bindErrText` `:271-281`；新增 `doSwitchBinding`）
- Test: `tests/cloud-multi-bind.test.js`（追加页面级钉）

**Interfaces:**
- Consumes: C1/C2 的 `cloudBindings()`/`switchCloudBinding()`/`unbindCloud()`/`getBinding().role`
- Produces: 页面 data 新增 `roleText`（`'主人'`/`'家人'`/`''`）、`bindings`（数组）、`showSwitch`（bool）；`_bindErrText` 覆盖 `members_full`/`owner_cannot_leave`/`not_owner`/`unknown_member`/`no_owner`

- [ ] **Step 1: 写失败测试**（追加到 `tests/cloud-multi-bind.test.js` 的 `main()` 内）

```js
  t('页面: 角色文案与错误码映射齐全（读源码钉字面量，页面 JS 无法在 node 里真跑）', () => {
    const js = SRC('miniprogram/pages/broker-gateways/broker-gateways.js')
    const wxml = SRC('miniprogram/pages/broker-gateways/broker-gateways.wxml')
    for (const e of ['members_full', 'owner_cannot_leave', 'unknown_member', 'no_owner']) {
      assert(js.includes(e), '_bindErrText 缺错误码 ' + e)
    }
    assert(js.includes("'主人'") && js.includes("'家人'"), '角色文案要能区分主人/家人')
    assert(js.includes('8 人') || js.includes('已满'), 'members_full 的文案要说清上限')
    assert(wxml.includes('roleText'), 'wxml 必须渲染 roleText（只在 js 里算＝用户看不到）')
    assert(wxml.includes('doSwitchBinding') || !js.includes('showSwitch'),
      '有多 HA 切换 data 就要有对应入口')
    assert(js.includes('await this._broker.unbindCloud()'), '解绑必须 await（unbindCloud 已变异步）')
    assert(js.includes('云端可能仍保留') || js.includes('已解除'), '解绑失败要有区分文案')
  })
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /e/AI/ha-yy/weichat-huijian-hz && node tests/cloud-multi-bind.test.js`
Expected: FAIL（`roleText`、四个错误码、await 都还没有）。

- [ ] **Step 3: 实现**

`broker-gateways.js` 的 `data`（`:11-15`）加三个字段：
```js
    roleText: '',          // '主人' | '家人' | ''（未绑定）
    bindings: [],          // 全部云绑定（多 HA 安装时给切换入口）
    showSwitch: false,
```

`refreshRemote()`（`:166-178`）改为（保留它现有的通道文案与失效文案逻辑，只加角色与多绑定）：
```js
  refreshRemote() {
    const b = this._broker.cloudBinding()
    const bindings = this._broker.cloudBindings()
    const roleText = b ? (b.role === 'member' ? '家人' : '主人') : ''
    this.setData({
      binding: b,
      remoteBound: !!b,
      remoteShort: b ? (b.sn || b.instanceId.slice(0, 8)) : '',
      roleText,
      bindings,
      showSwitch: bindings.length > 1,
      channelText: this._broker.mode() === 'cloud' ? '云端（慧尖云）' :
        (this._broker.mode() === 'lan' ? '本地直连' : '未连接')
    })
  },
```
（**改前先读 `:166-178` 原文**，把它现有的"失效文案"分支原样保留——那条是 v1.4.23 加的，丢了就退回"云通道被拒却不告诉用户"。）

新增切换方法：
```js
  doSwitchBinding(e) {
    const id = e && e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.instanceId
    if (!id) return
    if (this._broker.switchCloudBinding(id)) {
      this.refreshRemote()
      this._broker.connect(false)
      wx.showToast({ title: '已切换', icon: 'none' })
    }
  },
```

`doUnbindCloud()`（`:257-268`）改为 async + 按角色与结果分文案：
```js
  async doUnbindCloud() {
    const b = this._broker.cloudBinding()
    if (!b) return
    const isOwner = b.role !== 'member'
    // owner 的"解绑"只清本机：hub 侧 owner 归属不允许自己退（否则实例无主、没人能管成员）。
    // 文案必须说清，否则用户以为解绑了而家人仍能控制。
    const tip = isOwner
      ? '你是这台网关的主人。解绑只会清除本机绑定，云端归属不变（家人仍可控制）；要转移主人需在 HA 里重注册。确定？'
      : '解绑后你将失去这台网关的远程控制权（主人可随时把你加回来）。确定？'
    const ok = await new Promise((resolve) => wx.showModal({
      title: '解除绑定', content: tip, success: (r) => resolve(!!r.confirm), fail: () => resolve(false)
    }))
    if (!ok) return
    const res = await this._broker.unbindCloud()
    this.refreshRemote()
    wx.showToast({
      title: (res && res.ok) ? '已解除绑定' : '本机已解除（云端可能仍保留）',
      icon: 'none'
    })
  },
```

`_bindErrText`（`:271-281`）补齐（保留既有条目与兜底）：
```js
      members_full: '家庭成员已满（8 人），请让主人先移除一位',
      owner_cannot_leave: '主人不能退出，需在 HA 面板重注册才能转移',
      not_owner: '只有主人能做这个操作',
      unknown_member: '这位家人已经不在了',
      no_owner: '这台网关还没有主人，请先用主人码绑定',
```

`broker-gateways.wxml` 绑定卡（`:105-125`）里，在 `remoteBound` 那行之后加角色与切换入口：
```xml
      <view class="remote-row" wx:if="{{remoteBound}}">我的角色：{{roleText}}</view>
      <view class="remote-row" wx:if="{{showSwitch}}">
        <text>切换网关：</text>
        <text wx:for="{{bindings}}" wx:key="instanceId" class="remote-switch"
              data-instance-id="{{item.instanceId}}" bindtap="doSwitchBinding">
          {{item.sn || item.instanceId}}（{{item.role === 'member' ? '家人' : '主人'}}）
        </text>
      </view>
```

- [ ] **Step 4: 跑测试确认全绿**

Run: `cd /e/AI/ha-yy/weichat-huijian-hz && npm test`
Expected: 全绿（含 `remote-bind-entry.test.js` 的 23 条既有钉——若"两端文案成对"那条红，说明动了绑定卡的指路文案，按它的断言把「远程控制（慧尖云）」与「小慧语音」两个可搜索名补回去）。

- [ ] **Step 5: Commit（等用户口令）**

```bash
git -C E:/AI/ha-yy/weichat-huijian-hz add miniprogram/pages/broker-gateways/broker-gateways.js miniprogram/pages/broker-gateways/broker-gateways.wxml tests/cloud-multi-bind.test.js
git -C E:/AI/ha-yy/weichat-huijian-hz commit -m "feat(page): 我的角色 + 多 HA 切换 + 解绑文案按角色分 + 成员错误码"
```

---

## Phase D — 跨仓契约、真栈 e2e、变异核验与发版

### Task D1: 跨仓契约钉（两侧各写一份的东西，第一次有测试对账）

**Files:**
- Create: `huijian_mqtt_broker/tests/e2e/cross_repo_contract.sh`
- Create: `huijian_mqtt_broker/tests/test_v1746_cross_repo_contract.py`

**Interfaces:**
- Consumes: 环境变量 `HUB_REPO`（既有先例：`tests/e2e/hub_lifecycle_driver.py:35-38` 缺仓即 `sys.exit(3)`）、新增 `MINIPROGRAM_REPO`
- Produces: 一个可独立运行的 shell 门禁（`rc=0` 全过 / `rc=1` 有漂移 / `rc=3` 缺对端仓），以及一条 pytest 元钉证明"缺仓时不会静默变绿"

- [ ] **Step 1: 写 shell 契约钉**（新建 `tests/e2e/cross_repo_contract.sh`）

```bash
#!/usr/bin/env bash
# 跨仓契约钉：三端各写一份的东西（载荷版本位、错误码表、kind/mid 字段名、成员上限、端点名）
# 此前**没有任何测试对账**——一侧把载荷版本位升到 2，另一侧不会红（实测确认）。
# 缺对端仓时以 rc=3 响亮跳过（照 hub_lifecycle_driver.py:36-38 的纪律）：skip 变 exit 0 就是门禁不存在。
set -u
PLUGIN_REPO="${PLUGIN_REPO:-$(cd "$(dirname "$0")/../../.." && pwd)}"
HUB_REPO="${HUB_REPO:-}"
MINIPROGRAM_REPO="${MINIPROGRAM_REPO:-}"

for v in HUB_REPO MINIPROGRAM_REPO; do
  eval "val=\${$v}"
  if [ -z "$val" ]; then echo "SKIP 需要 $v 指向对端仓（私有仓，CI 侧不可见）"; exit 3; fi
done
[ -f "$HUB_REPO/src/server.js" ] || { echo "SKIP HUB_REPO 不像 hub 仓: $HUB_REPO"; exit 3; }
[ -f "$MINIPROGRAM_REPO/miniprogram/utils/cloud-gw.js" ] || { echo "SKIP MINIPROGRAM_REPO 不像小程序仓: $MINIPROGRAM_REPO"; exit 3; }

JS="$PLUGIN_REPO/huijian_mqtt_broker/www/js/huijian.js"
PYHUB="$PLUGIN_REPO/huijian_mqtt_broker/custom_components/window_controller_gateway/hub_client.py"
HUBSRV="$HUB_REPO/src/server.js"
HUBSTORE="$HUB_REPO/src/store.js"
CGW="$MINIPROGRAM_REPO/miniprogram/utils/cloud-gw.js"
PAGE="$MINIPROGRAM_REPO/miniprogram/pages/broker-gateways/broker-gateways.js"

pass=0; fail=0
check() {  # check <名称> <条件命令...>
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then pass=$((pass+1)); echo "PASS $name";
  else fail=$((fail+1)); echo "FAIL $name"; fi
}
has() { grep -qF -- "$2" "$1"; }

echo "==== 跨仓契约（hub=$HUB_REPO 小程序=$MINIPROGRAM_REPO） ===="
check "载荷前缀：插件写的版本位 = 小程序认的版本位" \
  bash -c "grep -qF \"BIND_PAYLOAD_PREFIX = 'HUJIAN-BIND:1:'\" '$JS' && grep -qF \"m[1] === '1'\" '$CGW'"
check "成员上限：hub 常量 = 加载项常量" \
  bash -c "grep -qE 'HUB_MEMBERS_MAX *= *8' '$HUBSTORE' && grep -qE 'HUB_MEMBERS_MAX *= *8' '$PYHUB'"
check "成员上限：小程序文案里的数字 = 8" bash -c "grep -qF '8 人' '$PAGE'"
check "kind 字段名：加载项发 = hub 读" \
  bash -c "grep -qF '\"kind\": kind' '$PYHUB' && grep -qF 'body.kind' '$HUBSRV'"
check "mid 字段名：加载项发 = hub 读" \
  bash -c "grep -qF '\"mid\": str(mid)' '$PYHUB' && grep -qF 'body.mid' '$HUBSRV'"
for ep in /agent/bindcode /agent/members /agent/unbind; do
  check "加载项调的 $ep 在 hub 侧存在" bash -c "grep -qF \"$ep\" '$PYHUB' && grep -qF \"p === '$ep'\" '$HUBSRV'"
done
for ep in /bind /state /cmd /unbind; do
  check "小程序调的 $ep 在 hub 侧存在" bash -c "grep -qF \"$ep\" '$CGW' && grep -qF \"p === '$ep'\" '$HUBSRV'"
done
for code in members_full no_owner owner_cannot_leave unknown_member already_bound code_invalid; do
  check "绑定错误码 $code：hub 会回 且 小程序有中文文案" \
    bash -c "grep -qF \"$code\" '$HUBSTORE' && grep -qF \"$code\" '$PAGE'"
done
for code in offline timeout forbidden send_failed; do
  check "控制错误码 $code：小程序有中文文案（云模式直接 toast）" \
    bash -c "grep -qF \"$code\" '$MINIPROGRAM_REPO/miniprogram/utils/gw-router.js'"
done

echo; echo "跨仓契约: $pass passed, $fail failed"
[ "$fail" -eq 0 ] || exit 1
exit 0
```

- [ ] **Step 2: 写 pytest 包装 + 元钉**（新建 `tests/test_v1746_cross_repo_contract.py`）

```python
# -*- coding: utf-8 -*-
"""跨仓契约钉的 pytest 入口 + "缺仓必须响亮跳过"元钉。

为什么要元钉：这类门禁最危险的失效方式不是红，而是**在对端仓不可见的环境里静默变绿**
（CI 拿不到私有仓）。所以除了跑真对账，还要真跑一次"没有对端仓"的路径，断言 rc=3。
"""
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tests" / "e2e" / "cross_repo_contract.sh"
HUB_REPO = os.environ.get("HUB_REPO", r"E:\AI\huijian-cloud-hub")
MP_REPO = os.environ.get("MINIPROGRAM_REPO", r"E:\AI\ha-yy\weichat-huijian-hz")


def _run(env_extra):
    env = dict(os.environ, **env_extra)
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=180, env=env)


def test_contract_holds_across_three_repos():
    if not (Path(HUB_REPO) / "src" / "server.js").exists() or \
       not (Path(MP_REPO) / "miniprogram" / "utils" / "cloud-gw.js").exists():
        pytest.skip("对端仓不可见（HUB_REPO / MINIPROGRAM_REPO）；rc=3 路径由下一条钉住")
    r = _run({"HUB_REPO": HUB_REPO, "MINIPROGRAM_REPO": MP_REPO})
    assert r.returncode == 0, "跨仓契约漂移：\n%s" % (r.stdout + r.stderr)
    assert "跨仓契约: " in r.stdout and " 0 failed" in r.stdout, r.stdout[-400:]


def test_missing_repo_skips_loudly_with_rc3():
    """元钉：缺对端仓必须 rc=3（不是 0）。skip 变 exit 0 就等于门禁不存在。"""
    r = _run({"HUB_REPO": "", "MINIPROGRAM_REPO": ""})
    assert r.returncode == 3, "缺仓时应 rc=3，实得 %d：%s" % (r.returncode, r.stdout + r.stderr)
    assert "SKIP" in r.stdout, "缺仓时必须打印 SKIP 说明"
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd /e/AI/huijian-gateway-plugin && HUB_REPO=E:/AI/huijian-cloud-hub MINIPROGRAM_REPO=E:/AI/ha-yy/weichat-huijian-hz python -m pytest huijian_mqtt_broker/tests/test_v1746_cross_repo_contract.py -q`
Expected: 在 A/B/C 三个 Phase 未完成前 **FAIL**（`/agent/members`、`members_full`、`8 人` 等都还不存在）；全部做完后转绿。这条钉是**跨 Phase 的收口判据**，最后跑。

- [ ] **Step 4: 三端补齐后跑到全绿**

Run: 同上 + `bash -n huijian_mqtt_broker/tests/e2e/cross_repo_contract.sh`
Expected: `跨仓契约: N passed, 0 failed`，pytest 2 passed。

- [ ] **Step 5: Commit（等用户口令）**

```bash
git -C E:/AI/huijian-gateway-plugin add huijian_mqtt_broker/tests/e2e/cross_repo_contract.sh huijian_mqtt_broker/tests/test_v1746_cross_repo_contract.py
git -C E:/AI/huijian-gateway-plugin commit -m "test: 跨仓契约钉（载荷版本位/错误码/kind/mid/上限 8）+ 缺仓 rc=3 元钉"
```

---

### Task D2: 真栈 e2e 新增 E 臂（多人绑定生命周期）

**Files:**
- Modify: `huijian_mqtt_broker/tests/e2e/hub_lifecycle_driver.py`（在 D 臂之后、汇总之前插入）
- Modify: `huijian_mqtt_broker/tests/test_v1742_hub_identity.py:40`（防稀释计数 `>= 13` → `>= 20`）

**Interfaces:**
- Consumes: 驱动既有的 `check(name, cond, detail)`、`http_json(method, path, payload)`、`start_hub()`、`INSTALL_KEY`
- Produces: 7 条 E 臂断言（真 node hub + 真 HTTP，不打桩协议）

- [ ] **Step 1: 写 E 臂**（插到 D 臂之后；`http_json` 只发 JSON body，openid 靠 hub 的 `body.openid` 兜底路径传入，与 A/C 臂同法）

```python
    # ── E 臂：家庭多人绑定（owner + member，v0.2.5 起） ─────────────────
    print("\n==== E 臂：多人绑定 ====")
    OWNER = "o_e2e_owner"
    MOM = "o_e2e_mom"
    st, reg = await http_json("POST", "/agent/register",
                              {"installKey": INSTALL_KEY, "sn": "GW-E2E-FAM", "fw": "e2e"})
    fam_id, fam_secret, fam_code = reg.get("instanceId"), reg.get("secret"), reg.get("bindCode")
    check("E 注册成功（多人绑定臂前置）", st == 200 and bool(fam_id), "%s %s" % (st, reg))

    st, b = await http_json("POST", "/bind", {"bindCode": fam_code, "openid": OWNER})
    check("E1 owner 码绑定回 role=owner", st == 200 and b.get("role") == "owner", "%s %s" % (st, b))

    st, oc = await http_json("POST", "/agent/bindcode",
                             {"instanceId": fam_id, "secret": fam_secret, "kind": "owner"})
    owner_code = oc.get("bindCode")
    st, mc = await http_json("POST", "/agent/bindcode",
                             {"instanceId": fam_id, "secret": fam_secret, "kind": "member"})
    member_code = mc.get("bindCode")
    check("E2 签发成员码不作废 owner 码（分字段的正题）",
          st == 200 and mc.get("kind") == "member" and bool(owner_code) and owner_code != member_code,
          "%s owner=%s member=%s" % (st, oc, mc))
    st, reb = await http_json("POST", "/bind", {"bindCode": owner_code, "openid": OWNER})
    check("E2b 签发成员码后 owner 码仍可用（同一 owner 幂等）",
          st == 200 and reb.get("role") == "owner", "%s %s" % (st, reb))

    st, mb = await http_json("POST", "/bind", {"bindCode": member_code, "openid": MOM})
    check("E3 第二个微信号用成员码绑定 → role=member", st == 200 and mb.get("role") == "member",
          "%s %s" % (st, mb))
    st, mst = await http_json("POST", "/state", {"instanceId": fam_id, "openid": MOM})
    check("E3b member 能读状态（不再 403）", st == 200 and mst.get("ok"), "%s %s" % (st, mst))
    st, again = await http_json("POST", "/bind", {"bindCode": member_code, "openid": "o_e2e_dad"})
    check("E3c 成员码一次性（同码再绑 → code_invalid）",
          st == 404 and again.get("err") == "code_invalid", "%s %s" % (st, again))

    # 本臂不起长连：鉴权通过的判据是"回 offline 而不是 403"（403＝鉴权没过）
    st, cmd = await http_json("POST", "/cmd", {"instanceId": fam_id, "sn": "DEV1", "action": "control",
                                              "params": {"attribute": "w_travel", "value": "100"},
                                              "openid": MOM})
    check("E4 member 发控制命令鉴权通过（无长连时回 offline，不是 403）",
          st == 200 and cmd.get("err") == "offline", "%s %s" % (st, cmd))
    st, denied = await http_json("POST", "/cmd", {"instanceId": fam_id, "sn": "DEV1", "action": "control",
                                                 "params": {"attribute": "w_travel", "value": "100"},
                                                 "openid": "o_e2e_stranger"})
    check("E4b 陌生人仍被拒（放宽只放宽到 member）", st == 403 and denied.get("err") == "forbidden",
          "%s %s" % (st, denied))

    st, mem = await http_json("POST", "/agent/members", {"instanceId": fam_id, "secret": fam_secret})
    ok_shape = (st == 200 and len(mem.get("members") or []) == 1
                and all(m.get("mid") and m.get("openidMasked") for m in mem["members"]))
    check("E5 /agent/members 用实例凭据可列成员且回 mid+掩码", ok_shape, "%s %s" % (st, mem))
    check("E5b 成员列表不回完整 openid", MOM not in json.dumps(mem, ensure_ascii=False), json.dumps(mem))

    mid = (mem.get("members") or [{}])[0].get("mid")
    st, kick = await http_json("POST", "/agent/unbind",
                               {"instanceId": fam_id, "secret": fam_secret, "mid": mid})
    check("E6 按 mid 踢人成功", st == 200 and kick.get("ok"), "%s %s" % (st, kick))
    st, after = await http_json("POST", "/state", {"instanceId": fam_id, "openid": MOM})
    check("E6b 被踢者立刻失去访问权（403）", st == 403 and after.get("err") == "forbidden",
          "%s %s" % (st, after))

    full = True
    for i in range(9):
        st, c = await http_json("POST", "/agent/bindcode",
                                {"instanceId": fam_id, "secret": fam_secret, "kind": "member"})
        st2, r2 = await http_json("POST", "/bind", {"bindCode": c.get("bindCode"), "openid": "o_e2e_m%d" % i})
        if i < 8:
            full = full and st2 == 200 and r2.get("role") == "member"
        else:
            full = full and st2 == 409 and r2.get("err") == "members_full"
    check("E7 前 8 人加入成功、第 9 人 409 members_full", full, "上限校验失败")
```

- [ ] **Step 2: 上调防稀释计数**

`tests/test_v1742_hub_identity.py:40` 的 `SRC.count("check(") >= 13` → `>= 20`（E 臂新增 12 处 `check(`；改完用 `grep -c "check(" tests/e2e/hub_lifecycle_driver.py` 核实际数，取"实际数 − 2"作为下限，留出余量但不失约束）。

- [ ] **Step 3: 跑 e2e 确认失败→成功**

Run: `cd /e/AI/huijian-gateway-plugin && HUB_REPO=E:/AI/huijian-cloud-hub bash huijian_mqtt_broker/tests/e2e/hub_lifecycle_e2e.sh`
Expected: hub 侧 A1–A5 未完成前 E 臂多条 FAIL（404 not_found）；hub 完成后 `30 passed, 0 failed`、`E2E_EXIT=0`。

- [ ] **Step 4: 跑防稀释钉**

Run: `cd /e/AI/huijian-gateway-plugin && python -m pytest huijian_mqtt_broker/tests/test_v1742_hub_identity.py -q`
Expected: 全绿（若红，说明 E 臂的 check 数没达到新下限＝臂被稀释了）。

- [ ] **Step 5: Commit（等用户口令）**

```bash
git -C E:/AI/huijian-gateway-plugin add huijian_mqtt_broker/tests/e2e/hub_lifecycle_driver.py huijian_mqtt_broker/tests/test_v1742_hub_identity.py
git -C E:/AI/huijian-gateway-plugin commit -m "test(e2e): E 臂多人绑定生命周期（12 条）+ 防稀释计数上调"
```

---

### Task D3: 变异核验（M28–M38）

**Files:** 无（影子树，跑完即删；**绝不改活树**）

- [ ] **Step 1: 建影子树并逐条注入**（每条都要有**阳性对照**：注入后先 grep 确认真的改到了，否则"没红"是假信号）

```bash
SH=$(mktemp -d) && cp -r E:/AI/huijian-cloud-hub/{src,tests,package.json} "$SH/" && cd "$SH"
# M28 成员码复用 owner 码字段
sed -i "s/if (wantMember) { it.memberCode = code; it.memberCodeExpire = expire }/if (wantMember) { it.bindCode = code; it.bindExpire = expire }/" src/store.js
grep -n "if (wantMember) { it.bindCode" src/store.js || echo "CONTROL_FAIL 变异没注入"
node tests/members.js; echo "M28_RC=$?"
```

- [ ] **Step 2: 逐条跑完下表并记录 rc**（每条都必须 `rc=1` 且 FAIL 行点名对应钉）

| 变异 | 影子树改法 | 必须红的钉 |
|---|---|---|
| M28 | 成员码写回 `bindCode/bindExpire`（复用 owner 字段） | hub `members.js`「成员码与 owner 码分字段」 |
| M29 | 删掉 `members.length >= HUB_MEMBERS_MAX` 判断 | hub「第 9 个成员 → members_full」 |
| M30 | `leaveInstance` 去掉 `canAccess` 校验 | hub「陌生人 → forbidden」 |
| M31 | 删掉 `owner_cannot_leave` 分支 | hub「owner 不能退自己」 |
| M32 | `_load`/`adoptFromMirror` 不调 `_normalize()` | hub 两条迁移用例 |
| M33 | `listMembers` 回完整 openid（去掉 `maskOpenid`） | hub「只回掩码与 mid」 |
| M34 | `pushMirror` 把 `members` 置空 | hub `mirror.js`「members 进镜像」 |
| M35 | 加载项 `refresh_bind_code` 不发 `kind` | 插件 `test_v1746_hub_members.py`「载荷必须带 kind」 |
| M36 | 加载项把老 hub 的响应当成员码用（删 `kind` 回显判断） | 插件「old_hub_without_kind_echo_degrades」 |
| M37 | `canAccess` 退回 `ownerOpenid ===` 单值 | hub「member 能读状态」+ e2e E3/E4 |
| M38 | 去掉"无主人拒发成员码" | hub「no_owner」+ e2e（若已加对应 check） |
| M39 | 小程序 `unbindCloud` 不发 `/unbind` | mp `cloud-multi-bind`「真发 /unbind」 |
| M40 | 小程序分桶存储不迁移老格式 | mp「老格式搬进 v2」 |

- [ ] **Step 3: 还原后复跑基线**（证明影子树没被改脏、活树全程未动）

Run: `cd "$SH" && git -C E:/AI/huijian-cloud-hub status --porcelain && node tests/members.js`（先把 M28 的 sed 反向还原或直接从活树重拷），随后 `rm -rf "$SH"`。
Expected: 活树 `git status` 与开工前一致；影子树基线全绿。

---

### Task D4: 版本号、CHANGELOG 与发版编排

**Files:**
- Modify: `huijian_mqtt_broker/config.yaml:2`、`huijian_mqtt_broker/custom_components/window_controller_gateway/manifest.json:4`、`huijian_mqtt_broker/www/index.html`（全部 `?v=` cache-buster，实测在 `:9,28,179,180,181,182`）、`huijian_mqtt_broker/www/version.json:2-3`、`CHANGELOG.md`
- Modify: `E:\AI\huijian-cloud-hub\package.json:3`（A6 已做）
- 小程序：**无版本串可改**（实测 `package.json` 无 `version` 字段，全仓 grep 不到 `1.4.x`）⇒ 版本只体现在 git tag 与 Release 标题

- [ ] **Step 1: 加载项版本四源 + cache-buster 同步**

把 `1.7.45` 全量替换为 `1.7.46`（**只改上面列出的四处来源**，不要动 CHANGELOG 的历史条目与 tests 里的注释）。
Run: `cd /e/AI/huijian-gateway-plugin && grep -rn "1\.7\.45" huijian_mqtt_broker/ | grep -v tests/`
Expected: **空输出**（有残留＝cache-buster 漏改，用户会拿到缓存的旧 JS/CSS）。
再核新版号齐了：`grep -rn "1\.7\.46" huijian_mqtt_broker/config.yaml huijian_mqtt_broker/custom_components/window_controller_gateway/manifest.json huijian_mqtt_broker/www/version.json && grep -c "?v=1.7.46" huijian_mqtt_broker/www/index.html`
Expected: 三处都有；`?v=1.7.46` 计数 = 改前的 `?v=1.7.45` 计数。

- [ ] **Step 2: CHANGELOG 段落**（`CHANGELOG.md` 顶部新增 `## [1.7.46] - <日期>`）

写清四件事：① 家庭多人绑定（owner + member，上限 8，面板签发一次性成员码）；② 面板 `loadRemoteControl` 重复定义热修（v1.7.41 的过期文案与「纳管网关 N 台」此前是死码）；③ 面板显示云通道故障原因；④ 小程序：一台手机可云绑多个 HA + 解绑真通知 hub + 云控制失败中文文案。
**段落控制在 50 行以内**（Gitee Release 正文按 `head -50` 截断，超出即丢）。

- [ ] **Step 3: 发版顺序（hub 必须先上，否则新插件的成员码请求会被老 hub 当 owner 码轮换）**

1. hub：commit → 轻量 tag `v0.2.5` → push（HTTPS 走系统 git 2.55）→ GitHub Release；控制台从 Git 部署新版本 → 全量流量；
   验：`curl /healthz` → `mirror.enabled=true`、出现 `membersTotal` 字段（这是 v0.2.5 在跑的版本判据）；
   再 `updateConfig` 换一次 pod → `mirror.adopted.adopted=true` 且 `instances` 不归零（**不需要用户重扫**，因为 mirror 已生效）。
2. 加载项：CI 九段全绿 → 双推（GitHub + Gitee，两侧 main 与 tag 同 SHA）→ GitHub Release（CI 建）+ Gitee Release（手工 API 建，PATCH 必须带 `tag_name`）→ 核 ghcr 三包（`huijian-mqtt-broker` / `amd64-` / `aarch64-`，**多架构索引包没有 `index-` 前缀**）匿名 GET 200。
3. 小程序：`npm test` 全绿 → push → 轻量 tag `v1.4.26` → Release；**体验版上传由用户做**（miniprogram-ci 撞密钥 IP 白名单）。

- [ ] **Step 4: 真机验收（用户侧 5 步，我这边用 MCP 同步取证）**

1. HA 升级到 1.7.46 → 面板「远程控制（慧尖云）」卡出现「家庭成员」区，显示「只有你一人」；
2. 点「添加家人」→ 出现成员码二维码（此时 owner 码不受影响，可对照两张码不同）；
3. 第二个微信号在「小慧语音」→「LoRa 网关」页扫码 → 页面显示「我的角色：家人」，且能控制子设备；
4. 面板刷新 → 「家庭成员」显示 `1 / 8 人` 与掩码 openid；点「移除」→ 家人手机立刻变「绑定已失效，请重新扫码」；
5. 我用 MCP 换一次 pod → 两边都**不需要重扫**（`/healthz` 的 `instances` 不归零、`membersTotal` 保持）。

- [ ] **Step 5: 收尾**（等用户口令）

三仓 `git status` 必须 clean；把本批的"变异核验记录 + 门禁条数 + 发版四处同 SHA + ghcr 三包 200"写进 CHANGELOG 末尾一行（沿用既有惯例）。
