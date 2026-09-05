#!/usr/bin/env bash
# v1.7.11 快速自动发现代理——真栈 A/B/C/D E2E
# 前置：bash run_local.sh（全新一键栈，token 在 /tmp/ha_e2e_token）。
# 本脚本会【删除慧尖条目】恢复零条目现场——跑完需重 run_local 复原。
#
# 语义分层（discovery.py 既有设计）：
#   首台网关：代理建「等待条目」→ 重放 → 心跳监听器 → async_discover_gateway
#     第 3.5 步【自动填充 SN + reload】——全自动配置，无需用户点击。
#   第二台起：无空条目可填 → 走 config flow discovery 卡片（用户确认）。
#
# A 相位（代理缺席）：零条目 HA 10 连发 → 无条目无卡片（现场缺口复现）。
# B 相位（代理在线）：1 条上报 → 等待条目出现并自动填充 → 子设备实体注册。
# C 相位（风暴）：30 连发 → 条目恒 1、设备恒 1（幂等）。
# D 相位（多网关）：第二 SN 上报 → 出发现卡片（不自动建条目）。
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
PROXY=$REPO/huijian_mqtt_broker/gateway_discovery_proxy.py
PY=${PY:-$(command -v python3)}
HA_PY=${HA_PY:-$HOME/local/havenv/bin/python3}
[ -x "$HA_PY" ] || HA_PY=$(command -v python3)
HA=http://127.0.0.1:8123/api
TOKEN=$(cat /tmp/ha_e2e_token 2>/dev/null || true)
MOSQ_DIR=${MOSQ_DIR:-$HOME/local/mosq}
if ! command -v mosquitto_pub >/dev/null 2>&1 && [ -x "$MOSQ_DIR/usr/bin/mosquitto_pub" ]; then
    PATH="$MOSQ_DIR/usr/bin:$PATH"
    export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-$MOSQ_DIR/usr/lib/x86_64-linux-gnu}"
fi
[ -n "$TOKEN" ] || { echo "缺 /tmp/ha_e2e_token（先跑 run_local.sh）"; exit 2; }
command -v mosquitto_pub >/dev/null 2>&1 || { echo "缺 mosquitto_pub"; exit 2; }

MSG1='{"head":"$SH","id":101,"ctype":"005","sn":"100122501203","data":{"rssi":65472,"sn":"500700000001","attrs":[{"attribute":"r_travel","value":"100"},{"attribute":"heartbeat_time","value":"10"}]}}'
MSG2='{"head":"$SH","id":7,"ctype":"002","sn":"100199999999","data":{}}'

probe() { HA_URL=http://127.0.0.1:8123 HA_TOKEN="$TOKEN" "$HA_PY" "$HERE/ws_flows_probe.py" "$1" 2>/dev/null | head -1; }
wc_entries() {
    curl -s -m 5 -H "Authorization: Bearer $TOKEN" "$HA/config/config_entries/entry" \
    | "$HA_PY" -c 'import json,sys;print(len([e for e in json.load(sys.stdin) if e["domain"]=="window_controller_gateway"]))' 2>/dev/null
}
dev_count() {  # device_registry 无 REST list（404 实测）→ WS 观测面
    local needle="${1:-}"
    if [ -n "$needle" ]; then
        HA_URL=http://127.0.0.1:8123 HA_TOKEN="$TOKEN" "$HA_PY" "$HERE/ws_device_probe.py" "$needle" 2>/dev/null | head -1
    else
        HA_URL=http://127.0.0.1:8123 HA_TOKEN="$TOKEN" "$HA_PY" "$HERE/ws_device_probe.py" 2>/dev/null | head -1
    fi
}
pub() { mosquitto_pub -h 127.0.0.1 -p 2022 -t gateway/rpt_rsp -m "$1" 2>/dev/null; }

echo "== 前置：清场 + 残卡 fail-fast =="
pkill -f 'gateway_discovery_[p]roxy' 2>/dev/null || true
"$HA_PY" - <<'PYEOF' || true
import json, urllib.request
tok = open("/tmp/ha_e2e_token").read().strip()
def req(path, method="GET"):
    r = urllib.request.Request("http://127.0.0.1:8123/api" + path, method=method,
                               headers={"Authorization": f"Bearer {tok}"})
    return json.loads(urllib.request.urlopen(r, timeout=10).read() or b"null")
for e in req("/config/config_entries/entry"):
    if e.get("domain") == "window_controller_gateway":
        try:
            req(f"/config/config_entries/entry/{e['entry_id']}", "DELETE")
            print("已删条目", e["entry_id"])
        except Exception as ex:
            print("删条目失败:", ex)
# device_registry 残留会挡 discovery step4（"已在设备注册表"）——但删条目时
# HA 级联清实体/设备（async_remove_entry），一般无需单独处理；仅提示。
try:
    pass  # 无 REST list 端点，设备残留检查由相位 A 起点断言兜底
except Exception as ex:
    print("设备注册表检查失败:", ex)
PYEOF
sleep 3
STALE=$(probe "网关")
if [ "${STALE:-0}" != "0" ]; then
    echo "  ✗ 存在上轮残卡在途 flow——集成内部 flow 无 REST 清理面，"; echo "    请重跑 run_local.sh 全新一键栈后再跑本 E2E"; exit 3
fi

FAIL=0
ck() { if [ "$2" != "$3" ]; then echo "  ✗ $1: 期望[$3] 实得[$2]"; FAIL=1; else echo "  ✓ $1"; fi; }

echo "== 相位 A：代理缺席（缺口复现） =="
ck "起点：零条目" "$(wc_entries)" "0"
for i in $(seq 1 10); do pub "$MSG1"; sleep 0.2; done
sleep 2
ck "10 连发后仍无条目（无耳朵，缺口存在）" "$(wc_entries)" "0"

echo "== 相位 B：代理在线（首报即全自动配置） =="
export HUIJIAN_HA_API="$HA" HUIJIAN_HA_TOKEN="$TOKEN"
"$PY" -u "$PROXY" 2022 anonymous unusedpw >/tmp/proxy_e2e.log 2>&1 &
PROXY_PID=$!
sleep 1.5
kill -0 "$PROXY_PID" 2>/dev/null || { echo "  ✗ 代理未能存活"; cat /tmp/proxy_e2e.log; exit 1; }
pub "$MSG1"
for i in $(seq 1 12); do sleep 1; [ "$(wc_entries)" != "0" ] && break; done
ck "耳朵条目出现（等待模式→自动填充链启动）" "$(wc_entries)" "1"
# 3.5 自动填充 + listener reload 后，后续上报由完整 mqtt_handler 处理 → 注册设备
for i in $(seq 1 8); do pub "$MSG1"; sleep 1; done
for i in $(seq 1 8); do [ "$(dev_count)" != "0" ] && break; pub "$MSG1"; sleep 1; done
ck "网关+子设备完成配置（device_registry 出现，全自动）" "$(dev_count)" "2"

echo "== 相位 C：风暴幂等 =="
for i in $(seq 1 30); do pub "$MSG1"; sleep 0.05; done
sleep 2
ck "30 连发条目恒 1" "$(wc_entries)" "1"
ck "30 连发设备恒 2（unique_id/去重幂等）" "$(dev_count)" "2"

echo "== 相位 D：第二网关出卡片（无空条目可填 → discovery flow） =="
pub "$MSG2"
for i in $(seq 1 10); do sleep 1; [ "$(probe "网关 9999")" != "0" ] && break; done
ck "第二网关发现卡片出现" "$(probe "网关 9999")" "1"
ck "第二网关不自动建条目（确认权在用户）" "$(wc_entries)" "1"

echo "== 相位 E：最脏环境（无 MQTT 条目 + 标记引导，v1.7.11 awaiting bootstrap） =="
# 模拟干净客户机：删光慧尖与 MQTT 条目、重写 bootstrap 标记、重启代理
"$HA_PY" - <<'PYEOF' || true
import json, urllib.request
tok = open("/tmp/ha_e2e_token").read().strip()
def req(path, method="GET"):
    r = urllib.request.Request("http://127.0.0.1:8123/api" + path, method=method,
        headers={"Authorization": f"Bearer {tok}"})
    return json.loads(urllib.request.urlopen(r, timeout=10).read() or b"null")
for e in req("/config/config_entries/entry"):
    if e["domain"] in ("window_controller_gateway", "mqtt"):
        try:
            req(f"/config/config_entries/entry/{e['entry_id']}", "DELETE")
            print("已删", e["domain"], "条目")
        except Exception as ex:
            print("删除失败", e["domain"], ex)
PYEOF
cat > "$HOME/local/ha-e2e-config/window_controller_gateway_mqtt_bootstrap.json" <<'JSON'
{"broker": "127.0.0.1", "port": 2022, "username": "anonymous", "password": "x"}
JSON
pkill -f 'gateway_discovery_[p]roxy' 2>/dev/null || true
sleep 1
"$PY" -u "$PROXY" 2022 anonymous unusedpw >>/tmp/proxy_e2e.log 2>&1 &
PROXY_PID=$!
sleep 1.5
pub "$MSG1"
for i in $(seq 1 12); do sleep 1; [ "$(wc_entries)" != "0" ] && break; done
ck "等待条目重建（代理→awaiting setup→bootstrap）" "$(wc_entries)" "1"
MQTT_N=$("$HA_PY" -c "
import json,urllib.request
tok=open('/tmp/ha_e2e_token').read().strip()
r=urllib.request.Request('http://127.0.0.1:8123/api/config/config_entries/entry',headers={'Authorization':'Bearer '+tok})
print(len([e for e in json.loads(urllib.request.urlopen(r,timeout=10).read()) if e['domain']=='mqtt']))" 2>/dev/null)
ck "MQTT 条目被 awaiting bootstrap 自动重建" "${MQTT_N:-0}" "1"
for i in $(seq 1 12); do pub "$MSG1"; sleep 1; [ "$(dev_count)" = "2" ] && break; done
ck "无 MQTT 条目起点下整链自动配齐（设备 2）" "$(dev_count)" "2"

[ -n "${PROXY_PID:-}" ] && kill "$PROXY_PID" 2>/dev/null
echo '── 代理日志尾部 ──'; tail -6 /tmp/proxy_e2e.log
if [ $FAIL -eq 0 ]; then echo "== FAST_DISCOVERY_E2E PASS =="; else echo "== FAST_DISCOVERY_E2E FAIL =="; fi
exit $FAIL
