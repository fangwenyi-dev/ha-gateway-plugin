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
check "mid 字段名：加载项发 = hub 读" \
  "grep -qF '\"mid\": str(mid)' '$PYHUB' && grep -qF 'mid' '$HUBSRV'"
check "ownerMasked 字段名：hub 回 = 加载项读" \
  "grep -qF 'ownerMasked' '$HUBSTORE' && grep -qF 'ownerMasked' '$PYHUB'"
# ④ 端点存在性：客户端调的每个路径，对端必须真的实现（否则线上必然 404）
for ep in /agent/bindcode /agent/members /agent/unbind; do
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
check "role 字段：hub 回 = 小程序存" \
  "grep -qF 'role:' '$HUBSTORE' && grep -qF 'res.role' '$CGW'"
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

echo
echo "跨仓契约: $pass passed, $fail failed"
[ "$fail" -eq 0 ] || exit 1
exit 0
