#!/usr/bin/env bash
# 跨仓契约钉（v1.7.47）：三端各写一份、谁都不会替谁报错的东西，第一次有测试对账。
#
# 为什么必须有：二维码载荷版本位、错误码表、kind/mid 字段名、成员上限、端点名——
# 这些在 hub / 加载项 / 小程序里各存一份，**没有任何编译期或单测能发现漂移**。
# 实测（2026-09-23 审查）：一侧把载荷版本位从 1 升到 2，另一侧不会红；hub 新增
# members_full，小程序没有中文文案，用户看到的就是兜底句。
#
# 缺对端仓时以 **rc=3 响亮跳过**（照 hub_lifecycle_driver.py:36-38 的纪律）：
# skip 变 exit 0 就等于门禁不存在——tests/test_v1747_cross_repo_contract.py 里有一条
# 元钉真跑"无对端仓"路径断言 rc==3。
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
WSGW="$PLUGIN_REPO/huijian_mqtt_broker/custom_components/window_controller_gateway/ws_gateway.py"
HUBSRV="$HUB_REPO/src/server.js"
HUBSTORE="$HUB_REPO/src/store.js"
CGW="$MINIPROGRAM_REPO/miniprogram/utils/cloud-gw.js"
GWR="$MINIPROGRAM_REPO/miniprogram/utils/gw-router.js"
WSJS="$MINIPROGRAM_REPO/miniprogram/utils/ws-gateway.js"
PAGE="$MINIPROGRAM_REPO/miniprogram/pages/broker-gateways/broker-gateways.js"
DEVPAGE="$MINIPROGRAM_REPO/miniprogram/pages/broker-device/broker-device.js"
for f in "$JS" "$PYHUB"; do [ -f "$f" ] || { echo "SKIP 加载项文件缺失: $f"; exit 3; }; done

pass=0; fail=0
check() {  # check <名称> <shell 命令串>
  local name="$1"; shift
  if bash -c "$1" >/dev/null 2>&1; then pass=$((pass+1)); echo "PASS $name";
  else fail=$((fail+1)); echo "FAIL $name"; fi
}

echo "==== 跨仓契约（hub=$HUB_REPO 小程序=$MINIPROGRAM_REPO） ===="
# ① 二维码载荷：插件写什么，小程序就得认什么（版本位不认即拒，所以漂移＝扫码全废）
check "载荷前缀：插件写的版本位 = 小程序认的版本位" \
  "grep -qF \"BIND_PAYLOAD_PREFIX = 'HUJIAN-BIND:1:'\" '$JS' && grep -qF \"m[1] === '1'\" '$CGW'"
# ② 成员上限：hub 常量 = 加载项常量 = 小程序文案里的数字（文案写错＝用户以为还能加）
check "成员上限：hub 常量 = 加载项常量" \
  "grep -qE 'HUB_MEMBERS_MAX = 8' '$HUBSTORE' && grep -qE 'HUB_MEMBERS_MAX = 8' '$PYHUB'"
check "成员上限：小程序文案里的数字 = 8" "grep -qF '8 人' '$PAGE'"
# ③ 字段名：两侧各写一份的 JSON 键（拼错＝静默失效，hub 只会当成缺省值）
check "kind 字段名：加载项发 = hub 读" \
  "grep -qF '\"kind\": kind' '$PYHUB' && grep -qF 'body.kind' '$HUBSRV'"
check "mid 字段名：加载项发 = hub 从 body 解构并按 mid 定位" \
  "grep -qF '\"mid\": str(mid)' '$PYHUB' && grep -qF 'secret, mid } = body' '$HUBSRV' && grep -qF 'removeMemberByMid(' '$HUBSRV'"
check "ownerMasked 字段名：hub 回 = 加载项读" \
  "grep -qF 'ownerMasked' '$HUBSTORE' && grep -qF 'ownerMasked' '$PYHUB'"
# ④ 端点存在性：客户端调的每个路径，对端必须真的实现（否则线上必然 404）
for ep in /agent/register /agent/bindcode /agent/members /agent/unbind; do
  check "加载项调的 $ep 在 hub 侧存在" \
    "grep -qF \"$ep\" '$PYHUB' && grep -qF \"p === '$ep'\" '$HUBSRV'"
done
for ep in /bind /state /cmd /unbind; do
  check "小程序调的 $ep 在 hub 侧存在" \
    "grep -qF \"'$ep'\" '$CGW' && grep -qF \"p === '$ep'\" '$HUBSRV'"
done
# ⑤ 错误码：hub 会回的，用户侧必须有中文文案（否则用户看到裸英文或兜底句）
for code in members_full no_owner owner_cannot_leave unknown_member already_bound code_invalid; do
  check "绑定错误码 $code：hub 会回 且 小程序有中文文案" \
    "grep -qF \"$code\" '$HUBSTORE' && grep -qF \"$code:\" '$PAGE'"
done
for code in offline timeout forbidden send_failed; do
  check "控制错误码 $code：小程序有中文文案（云模式直接 toast）" \
    "grep -qF \"$code:\" '$GWR'"
done
# ⑥ role：hub 回、小程序存（老 hub 不回时小程序兜 owner，这条钉的是"两侧都知道有 role"）
#    role 的字面量在 hub 的 store.js（bindByCode 的返回体），server.js 只是透传+记日志
check "role 字段：hub 回字面量 owner/member = 小程序读 res.role" \
  "grep -qF \"role: 'owner'\" '$HUBSTORE' && grep -qF \"role: 'member'\" '$HUBSTORE' && grep -qF 'res.role' '$CGW'"
# ⑦ 速度/力度**回显**字段：加载项发 = 小程序读（v1.7.47 之前加载项两条通道都不回传，
#    小程序滑块只能显示本地记忆值 ⇒ 换手机/在 HA 里调过就对不上，用户报"调了没反应"）
for f in winactSpeed winactStrength; do
  check "回显字段 $f：加载项发 且 小程序 LAN+云两侧都读" \
    "grep -qF \"$f\" '$WSGW' && grep -qF \"$f\" '$WSJS' && grep -qF \"$f\" '$CGW'"
done
check "回显字段 windLockMode：加载项列表视图也带（此前只有推送与云端带）" \
  "grep -qF 'windLockMode' '$WSGW' && grep -qF 'windLockMode' '$WSJS'"
# ⑧ 百分比入参口径：加载项 int()+裁剪+不可解析即拒；小程序必须同口径（取整 + NaN 不发）
check "速度/力度入参：小程序取整且拒绝不可解析值（与加载项 int() 同口径）" \
  "grep -qF 'Math.round' '$GWR' && grep -qF 'isFinite' '$GWR' && grep -qF 'Math.round' '$DEVPAGE'"

# ⑨ WS 凭据走请求头（secret 不再进 URL query ⇒ 不落任何记 request line 的中间层日志）。
#    hub 侧的 query 兜底是**发版顺序安全网**：必须 hub 先上，老加载项（仍发 query）才不断；
#    删掉兜底＝发版顺序一反就全员掉线，所以这条钉的是"兜底不许被顺手清理掉"。
check "WS 凭据头 x-hub-instance-id：加载项发 = hub 读" \
  "grep -qF 'x-hub-instance-id' '$PYHUB' && grep -qF \"h['x-hub-instance-id']\" '$HUBSRV'"
check "WS 凭据头 x-hub-secret：加载项发 = hub 读" \
  "grep -qF 'x-hub-secret' '$PYHUB' && grep -qF \"h['x-hub-secret']\" '$HUBSRV'"
check "hub 保留 query 兜底（发版顺序安全网，不许清理）" \
  "grep -qF \"searchParams.get('instanceId')\" '$HUBSRV' && grep -qF \"searchParams.get('secret')\" '$HUBSRV'"
check "加载项不再把凭据拼进 WS URL query" \
  "! grep -qF 'agent/ws?instanceId' '$PYHUB'"

# ⑩ WS 消息词汇：加载项与 hub 各写一份，任一侧改字面量＝命令或状态整条静默失效
check "WS 下行命令 t='cmd'：hub 发 = 加载项认" \
  "grep -qF \"t: 'cmd'\" '$HUBSRV' && grep -qF '\"t\") != \"cmd\"' '$PYHUB'"
check "WS 回执 t='cmd_result'：加载项发 = hub 认" \
  "grep -qF '\"t\": \"cmd_result\"' '$PYHUB' && grep -qF \"msg.t === 'cmd_result'\" '$HUBSRV'"
check "WS 状态 t='state'：加载项发 = hub 认" \
  "grep -qF '\"t\": \"state\"' '$PYHUB' && grep -qF \"msg.t === 'state'\" '$HUBSRV'"
check "WS 命令号 cmdsn：加载项回 = hub 用它配对回执" \
  "grep -qF 'cmdsn' '$PYHUB' && grep -qF 'msg.cmdsn' '$HUBSRV'"
check "WS 状态批量键 items：加载项发 = hub 读" \
  "grep -qF '\"items\": items' '$PYHUB' && grep -qF 'msg.items' '$HUBSRV'"
check "命令参数键 attribute：加载项校验 = 小程序下发" \
  "grep -qF 'params.get(\"attribute\")' '$PYHUB' && grep -qF 'attribute' '$CGW'"

# ⑪ 操作判别键在两条通道**故意不同名**：LAN 是 cmd、云是 action。今天两端各自对得上，
#    谁"顺手统一"一下就静默断一边（加载项回 unknown_action，用户只看到"不支持的操作"）。
check "LAN 判别键 cmd:'control'：加载项认 = 小程序发" \
  "grep -qF 'cmd == \"control\"' '$WSGW' && grep -qF \"cmd: 'control'\" '$WSJS'"
check "云 判别键 action:'control'：加载项认 = 小程序发（与 LAN 故意不同名，别去统一）" \
  "grep -qF 'msg.get(\"action\") != \"control\"' '$PYHUB' && grep -qF \"action: 'control'\" '$CGW'"

# ⑫ 绑定码 TTL 三处各写一份：hub 的毫秒常量、加载项的兜底秒常量、面板给用户看的文案。
#    漂移的形态是"面板对着一张云端已作废的码继续倒计时"，用户扫到 code_invalid 且无人解释。
check "绑定码 TTL 三处对账：hub 600000ms / 加载项 600s 兜底 / 面板 10 分钟文案" \
  "grep -qF '10 * 60 * 1000' '$HUBSTORE' && grep -qE 'BIND_CODE_TTL_S = 600' '$PYHUB' && grep -qF '10 分钟' '$JS'"

# ⑬ 权威值在云端：hub 回 expiresInSec / membersMax，加载项必须优先采用、本地常量只当兜底。
#    用自己的常量盖掉云端值＝hub 一改上限或有效期，面板就开始对用户说谎。
check "加载项优先采用 hub 回的 expiresInSec（本地 TTL 只兜底）" \
  "grep -qF 'data.get(\"expiresInSec\")' '$PYHUB' && grep -qF 'expiresInSec' '$HUBSTORE'"
check "加载项优先采用 hub 回的 membersMax（本地常量只兜底）" \
  "grep -qF 'data.get(\"membersMax\")' '$PYHUB' && grep -qF 'membersMax' '$HUBSTORE'"

# ⑭ hub 新增错误码：会回就必须两端都有中文文案（否则用户看到裸英文或笼统兜底句）
for code in registry_full rate_limited superseded; do
  check "新错误码 $code：hub 会回 且 加载项面板有中文文案" \
    "grep -qF '$code' '$HUBSRV' '$HUBSTORE' && grep -qF \"case '$code':\" '$JS'"
done
check "新错误码 rate_limited：小程序绑定失败也有中文文案" \
  "grep -qF 'rate_limited:' '$PAGE'"
check "新错误码 superseded：小程序控制面有中文文案" \
  "grep -qF 'superseded:' '$GWR'"

# ⑮ 加载项自己产的回执错误码（经 hub 原样透传给小程序）：此前无人对账，改名不会红
for code in control_failed control_unavailable invalid_params unknown_action; do
  check "加载项回执码 $code：加载项会回 且 小程序有中文文案" \
    "grep -qF '\"$code\"' '$PYHUB' && grep -qF '$code:' '$GWR'"
done

# ⑯ 数据流贯通（治假绿）：字段"在某文件里出现过"证明不了它走到了页面。
#    v1.4.28 的速度/力度回显就是这么漏的——normalizeStates 产出了 winact*，但 gw-router
#    的云缓存构造把它们丢了，而钉只 grep 了 cloud-gw.js ⇒ 字符串在、值不在，28 条全绿。
for f in winactSpeed winactStrength; do
  check "回显字段 $f 必须走到云缓存层 gw-router（只钉 normalize 层＝假绿）" \
    "grep -qF '$f' '$GWR'"
done

echo
echo "跨仓契约: $pass passed, $fail failed"
[ "$fail" -eq 0 ] || exit 1
exit 0
