# -*- coding: utf-8 -*-
"""v1.7.46 钉桩：面板统一渲染出口 `applyHubStatus` 的**行为**（假 DOM 里 node 真跑）。

为什么不能只靠结构钉：删掉 `loadRemoteControl` 的重复定义后，`applyHubStatus` 第一次
成为"页面加载 + 30s 无感刷新"的真实路径（此前它只在点二维码那条 POST 路径可达）。
结构钉只能证明"调用了"，证明不了"渲染对了"——而这条路径现在每次打开页面都走。

做法沿用本仓既有纪律（test_v1743_hub_singleton.py 对 hubGatewayText 的 node 真跑）：
把被测函数**连同它调用的渲染函数**原样抽出来，配一个最小假 document，在 node 里真跑
各种场景，断言用户看到的文本。不打桩被测函数本身（打桩＝把要判的东西判掉）。

⚠️ 维护提醒：`applyHubStatus` 是唯一渲染出口，它每多渲染一块（v1.7.47 加了成员区），
这里的假 DOM 与被抽取的函数集合就要跟着补——否则 node 会以 ReferenceError 崩掉。
这崩得响，是好事：说明"出口又长胖了"这件事不会被静默放过。
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "www" / "js" / "huijian.js").read_text(encoding="utf-8")


def _body(name):
    hits = [m.start() for m in re.finditer(r"function\s+" + re.escape(name) + r"\s*\(", JS)]
    assert len(hits) == 1, "函数 %s 出现 %d 次（应为 1）" % (name, len(hits))
    i = hits[0]
    j = JS.index("{", i)
    depth = 0
    for k in range(j, len(JS)):
        if JS[k] == "{":
            depth += 1
        elif JS[k] == "}":
            depth -= 1
            if depth == 0:
                return JS[i:k + 1]
    raise AssertionError("函数 %s 花括号不配平" % name)


# applyHubStatus 会调到的渲染函数，一个都不能少（少了 node 会 ReferenceError 崩）
DEPS = ("hubGatewayText", "hubErrorText", "membersText", "renderMemberQr", "renderMembers")

HARNESS_HEAD = """
// ── 最小假 DOM：只有面板真实存在的那几个 id 会被返回，其余回 null ──
let _bindCode = '';
const qrCalls = [];
const memberQrCalls = [];
function renderBindQr(code) { qrCalls.push(code); }
const KNOWN = ['hubDot', 'hubStatus', 'hubCode', 'hubGateway', 'hubGwDot', 'hubCodeExp', 'hubError',
               'hubMembersCount', 'hubMembersEmpty', 'hubMembers', 'addMemberBtn', 'hubMemberQr',
               'hubMemberQrBox', 'hubMemberCode', 'hubMemberExp'];
const els = {};
function mk(id) {
  return els[id] = els[id] || {
    id: id, textContent: '', className: '', hidden: false, disabled: false, title: '',
    children: [], attrs: {},
    appendChild: function (c) { this.children.push(c) },
    setAttribute: function (k, v) { this.attrs[k] = v }
  };
}
const document = {
  getElementById: (id) => (KNOWN.indexOf(id) >= 0 ? mk(id) : null),
  createElement: () => ({
    textContent: '', className: '', type: '', children: [], attrs: {}, onclick: null,
    appendChild: function (c) { this.children.push(c) },
    setAttribute: function (k, v) { this.attrs[k] = v }
  })
};
const window = { HjQr: { render: (box, text) => { memberQrCalls.push(text) } } };
"""

HARNESS_TAIL = """
let bad = 0;
function want(cond, msg) { if (!cond) { console.log('FAIL ' + msg); bad++; } }
function reset() { for (const k of Object.keys(els)) delete els[k]; qrCalls.length = 0; memberQrCalls.length = 0; _bindCode = ''; }

// 场景 1：正常 + 两台网关 + 码还新鲜 + 一个成员（多网关聚合文案、剩余分钟、成员区都要出来）
reset();
applyHubStatus({
  enabled: true, connected: true, bindCode: '123456', bindCodeExpiresIn: 300,
  bindCodeExpired: false, gatewaySn: 'GW1',
  gateways: [{ sn: 'GW1', deviceCount: 2 }, { sn: 'GW2', deviceCount: 3 }],
  lastError: null,
  memberCode: '654321', memberCodeExpiresIn: 420, memberCodeExpired: false,
  members: [{ mid: 'a'.repeat(12), openidMasked: 'oFa…02', at: 1 }],
  membersCount: 1, membersMax: 8, membersSupported: true, ownerMasked: 'oFa…01'
}, false);
want(els.hubStatus.textContent === '已连接', '连接态: ' + els.hubStatus.textContent);
want(els.hubCode.textContent === '123456', '绑定码: ' + els.hubCode.textContent);
want(els.hubGateway.textContent === '2 台 · 5 个子设备（GW1、GW2）',
     '多网关文案（旧渲染器只会显示单个 SN）: ' + els.hubGateway.textContent);
want(els.hubCodeExp.textContent.indexOf('剩余 5 分钟') === 0, '剩余时间: ' + els.hubCodeExp.textContent);
want(els.hubError.hidden === true && els.hubError.textContent === '', '无故障时原因行必须隐藏');
want(qrCalls.length === 1 && qrCalls[0] === '123456', '应渲染一次二维码: ' + JSON.stringify(qrCalls));
want(els.hubDot.className.indexOf('dot-ok') >= 0, '连接时圆点应是 ok 态: ' + els.hubDot.className);
want(els.hubMembersCount.textContent === '1 / 8 人', '成员计数: ' + els.hubMembersCount.textContent);
want(els.hubMembers.children.length === 1, '应渲染 1 行成员');
want(els.hubMemberQr.hidden === false, '有成员码时应摆出二维码');
want(memberQrCalls.length === 1 && memberQrCalls[0] === 'HUJIAN-BIND:1:654321',
     '成员码载荷必须与 owner 码同格式（小程序才能解析）: ' + JSON.stringify(memberQrCalls));
want(els.hubMemberExp.textContent.indexOf('剩余 7 分钟') === 0, '成员码剩余: ' + els.hubMemberExp.textContent);

// 场景 2：未连接 + 码已过期 + 有故障原因（这正是旧渲染器完全不显示的两块）
reset();
applyHubStatus({
  enabled: true, connected: false, bindCode: '654321', bindCodeExpiresIn: -10,
  bindCodeExpired: true, gatewaySn: '', gateways: [], lastError: 'bindcode_failed',
  members: [], membersMax: 8, membersSupported: true
}, false);
want(els.hubStatus.textContent === '未连接', '连接态: ' + els.hubStatus.textContent);
want(els.hubCodeExp.textContent.indexOf('已过期') === 0, '过期文案: ' + els.hubCodeExp.textContent);
want(els.hubCodeExp.className.indexOf('expired') >= 0, '过期要有区分样式: ' + els.hubCodeExp.className);
want(els.hubError.hidden === false && els.hubError.textContent.length > 4,
     '故障原因必须显示: ' + JSON.stringify(els.hubError.textContent));
want(els.hubGateway.textContent === '—', '无网关时应为破折号: ' + els.hubGateway.textContent);
want(els.hubMemberQr.hidden === true, '没有成员码时不得摆空白二维码块');

// 场景 3：读取失败（必须与"未启用"分开显示，故障伪装成正常态会让排障从第一步就走错）
reset();
applyHubStatus(null, true);
want(els.hubStatus.textContent === '读取失败', '失败态: ' + els.hubStatus.textContent);
want(els.hubCode.textContent === '------', '失败时码要清空: ' + els.hubCode.textContent);
want(els.hubError.hidden === true, '失败时不得残留上一次的故障原因');
want(qrCalls.length === 1 && qrCalls[0] === '', '失败时必须清掉二维码（残留过期码比不显示更坏）');
want(els.hubMembersCount.textContent === '—', '失败时成员计数应为破折号: ' + els.hubMembersCount.textContent);
want(els.addMemberBtn.disabled === true, '失败时「添加家人」必须禁用');

// 场景 4：未启用（老集成没有这条路由）
reset();
applyHubStatus({ enabled: false }, false);
want(els.hubStatus.textContent === '未启用', '未启用态: ' + els.hubStatus.textContent);
want(els.hubDot.className.indexOf('dot-unknown') >= 0, '未启用应是 unknown 态: ' + els.hubDot.className);
want(els.hubError.hidden === true, '未启用时不显示故障原因');

// 场景 5：未知故障码不得摆到面板上（终端用户看到 RuntimeError 只是噪声）
reset();
applyHubStatus({ enabled: true, connected: false, bindCode: '111111', bindCodeExpiresIn: 60,
                 bindCodeExpired: false, gatewaySn: 'GW1', gateways: [], lastError: 'RuntimeError',
                 members: [], membersMax: 8, membersSupported: true }, false);
want(els.hubError.hidden === true && els.hubError.textContent === '',
     '未知码必须不显示: ' + JSON.stringify(els.hubError.textContent));

// 场景 6：老 hub（membersSupported=false）——要说清是云端版本旧，且禁用按钮
reset();
applyHubStatus({ enabled: true, connected: true, bindCode: '111111', bindCodeExpiresIn: 60,
                 bindCodeExpired: false, gatewaySn: 'GW1', gateways: [], lastError: null,
                 members: [], membersMax: 8, membersSupported: false }, false);
want(els.hubMembersCount.textContent === '云端版本过旧，暂不支持', '老 hub 文案: ' + els.hubMembersCount.textContent);
want(els.addMemberBtn.disabled === true, '老 hub 必须禁用「添加家人」');

if (bad) { console.log('applyHubStatus 真跑: ' + bad + ' 处不符'); process.exit(1) }
console.log('OK');
"""


def _render_script():
    # renderMemberQr 用到 BIND_PAYLOAD_PREFIX 常量：从源码抽**真值**注入，而不是在测试里
    # 再抄一遍字面量（抄的那份会与实现漂移；且它被 try/catch 包着，缺了会静默不渲染）。
    m = re.search(r"const BIND_PAYLOAD_PREFIX = '([^']+)'", JS)
    assert m, "huijian.js 里找不到 BIND_PAYLOAD_PREFIX 常量（改名了？harness 要跟着改）"
    const = "const BIND_PAYLOAD_PREFIX = '%s';\n" % m.group(1)
    return (HARNESS_HEAD + const + "\n".join(_body(n) for n in DEPS)
            + "\n" + _body("applyHubStatus") + "\n" + HARNESS_TAIL)


def _run_node(script):
    if shutil.which("node") is None:
        raise AssertionError("node 不可用，无法真跑渲染出口")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "render.js"
        p.write_text(script, encoding="utf-8")
        r = subprocess.run(["node", str(p)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
        assert r.returncode == 0 and "OK" in r.stdout, \
            "applyHubStatus 真跑失败：\n%s%s" % (r.stdout, r.stderr)


def test_apply_hub_status_renders_every_state_in_node():
    _run_node(_render_script())


def test_single_gateway_copy_still_shows_sn():
    """一台网关时沿用旧面板"一眼看到本机网关"的好处：直接给 SN · N 个子设备。"""
    _run_node(_body("hubGatewayText") + """
const one = hubGatewayText({ gateways: [{ sn: 'GW1', deviceCount: 4 }], gatewaySn: 'GW1' });
if (one !== 'GW1 · 4 个子设备') { console.log('FAIL ' + one); process.exit(1) }
const legacy = hubGatewayText({ gatewaySn: 'GW-OLD' });      // 老集成只回 gatewaySn
if (legacy !== 'GW-OLD') { console.log('FAIL legacy ' + legacy); process.exit(1) }
const none = hubGatewayText({});
if (none !== '—') { console.log('FAIL none ' + none); process.exit(1) }
console.log('OK');
""")
