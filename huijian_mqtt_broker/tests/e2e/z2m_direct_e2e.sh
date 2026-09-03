#!/bin/bash
# zigbee2mqtt 直连慧尖内置 broker——生产认证形态实证（永久回归资产）
#
# 覆盖交付指引"z2m 直连 mqtt://<host>:2022 + huijian_z2m 账号"的全部断言：
#   Z1 三账号（huijian/ha_mqtt/huijian_z2m）在生产同形态认证下可连
#   Z2 broker 层跨账号：z2m 的 discovery 发布可达 ha_mqtt 订阅面
#   Z3 最小权限：huijian_z2m 触不到 gateway/#（denied → 不投递且断连）
#   Z4 错误密码被拒
#   Z5 真 HA 消费层：z2m 形态 discovery → HA MQTT 集成自动建实体 → 状态更新
#
# 环境层：auth broker 的 passwd/acl 由 gen_z2m_authenv.py **逐字抽取 run.sh
# 生成区**产出（与生产同形态，防手抄漂移）；Z5 复用 run_local.sh 已拉起的
# 真 HA 栈（token /tmp/ha_e2e_token）。
#
# 用法：bash z2m_direct_e2e.sh        （前置：../run_local.sh 已绿）
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
MOSQ_DIR=${MOSQ_DIR:-$HOME/local/mosq}
PY=${PY:-$HOME/local/havenv/bin/python3}
export LD_LIBRARY_PATH=${LD_LIBRARY_PATH:-$MOSQ_DIR/usr/lib/x86_64-linux-gnu}
TOKEN=$(cat /tmp/ha_e2e_token 2>/dev/null)
[ -n "$TOKEN" ] || { echo "缺 /tmp/ha_e2e_token（先跑 run_local.sh）"; exit 2; }
curl -s -o /dev/null -m 3 -H "Authorization: Bearer $TOKEN" \
    http://127.0.0.1:8123/api/config || { echo "真 HA 栈不在线（先跑 run_local.sh）"; exit 2; }

L=$HOME/local/z2m-e2e-$$          # 轮次独占目录（教训固化）
trap 'kill "${AB:-}" 2>/dev/null; rm -rf "$L"' EXIT

# —— 生产同形态认证环境（沙盒端口 2122，机制与端口无关）——
python3 "$HERE/gen_z2m_authenv.py" "$L" 2122 huijian2022 >/dev/null || { echo "❌ gen 抽取失败"; exit 3; }
bash "$L/gen_env.sh" >/dev/null || { echo "❌ 生产凭据生成区执行失败（run.sh 区漂移？）"; exit 3; }
grep -q "huijian_z2m" "$L/passwd" || { echo "❌ passwd 缺 huijian_z2m（run.sh z2m 用户创建未生效）"; exit 3; }
awk -v pat=":084A$" 'FNR>1 && $2~pat && $4=="0A"{f=1} END{exit !f}' /proc/net/tcp \
    && { echo "❌ 2122 被占用"; exit 2; }
"$MOSQ_DIR/usr/sbin/mosquitto" -c "$L/auth.conf" >> "$L/auth.out" 2>&1 & AB=$!
sleep 2
kill -0 "$AB" 2>/dev/null || { echo "❌ 生产形态 conf 起不来:"; tail -4 "$L/auth.out"; exit 3; }
echo "✅ 生产同形态 auth broker@2122 就绪（passwd/acl 为 run.sh 原文生成物）"

# —— Z1/Z2/Z3/Z4（paho 对生产形态断言）——
"$PY" - "$L" <<'ZZ' || exit 1
import sys, time, threading
import paho.mqtt.client as mqtt
L = sys.argv[1]
PW, HOST = "huijian2022", "127.0.0.1"

def connect(user, pw, port=2122):
    err = {}
    cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"z2m-e2e-{user}")
    cl.username_pw_set(user, pw)
    try:
        cl.connect(HOST, port, 10)
        cl.loop_start(); time.sleep(0.6)
        if not cl.is_connected():
            err["why"] = "dropped"
            cl.loop_stop(); return None, err
        return cl, None
    except Exception as e:
        err["why"] = f"{type(e).__name__}:{e}"
        return None, err

# Z1 三账号
for u in ("huijian", "ha_mqtt", "huijian_z2m"):
    c, e = connect(u, PW)
    assert c, f"Z1 {u} 应可连: {e}"
    c.loop_stop(); c.disconnect()
print("✅ Z1 生产三账号（huijian/ha_mqtt/huijian_z2m）同形态认证可连")

# Z4 错误密码
c, e = connect("huijian_z2m", "wrong-pass")
assert c is None and ("onour" in str(e) or "auth" in str(e).lower() or "drop" in str(e)), \
    f"Z4 错误密码应被拒, 实际 {e}"
print("✅ Z4 错误密码被拒")

# Z2 跨账号 discovery 面：z2m 发布 → ha_mqtt 订阅可达
got = []
sub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ha-view")
sub.username_pw_set("ha_mqtt", PW)
sub.on_message = lambda c,u,m: got.append(m.payload)
sub.connect(HOST, 2122, 10); sub.subscribe("homeassistant/#"); sub.loop_start()
time.sleep(0.8)
pub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="z2m-view")
pub.username_pw_set("huijian_z2m", PW)
pub.connect(HOST, 2122, 10); pub.loop_start(); time.sleep(0.8)
pub.publish("homeassistant/sensor/z2mprobe/config", '{"name":"p"}', qos=1, retain=True)
time.sleep(2)
assert len(got) == 1, f"Z2 discovery 应恰 1 条达 ha_mqtt 订阅面, 实际 {len(got)}"
pub.loop_stop(); sub.loop_stop()
print("✅ Z2 z2m 的 discovery 发布可达 HA 订阅面（homeassistant/# 白名单）")

# Z3 最小权限：huijian_z2m publish gateway/# → 不投递（且 mosquitto 2.x 会断连）
g = []
gsub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="gw-view")
gsub.username_pw_set("huijian", PW)
gsub.on_message = lambda c,u,m: g.append(m.topic)
gsub.connect(HOST, 2122, 10); gsub.subscribe("gateway/#"); gsub.loop_start()
time.sleep(0.8)
atk = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="z2m-evil")
atk.username_pw_set("huijian_z2m", PW)
dropped = threading.Event()
atk.on_disconnect = lambda c,u,rc: dropped.set()
atk.connect(HOST, 2122, 10); atk.loop_start(); time.sleep(0.8)
atk.publish("gateway/E2EFAKE/req", '{"ctype":"004","command":"open"}', qos=1)
time.sleep(3)
assert len(g) == 0, f"Z3 z2m 账号的消息到达了网关域 {g}——最小权限失守！"
print(f"✅ Z3 huijian_z2m 触不到 gateway/#（0 投递；连接被断={dropped.is_set()}）")
atk.loop_stop(); gsub.loop_stop()
ZZ
echo "✅ Z1-Z4 生产认证形态全部通过"

# —— Z5 真 HA 消费层（现役栈 broker@2022）：discovery→实体→状态 ——
"$PY" - "$TOKEN" <<'YY' || exit 1
import json, sys, time, urllib.request
import paho.mqtt.client as mqtt
TOKEN = sys.argv[1]
API = "http://127.0.0.1:8123/api"
def api(path, method="GET", body=None):
    req = urllib.request.Request(API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())

cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="z2m-sim")
cl.connect("127.0.0.1", 2022, 10); cl.loop_start(); time.sleep(1)
# z2m 真实报文形态（与 z2m 2.x discovery 逐字段同构）
cfg = {"availability_topic": "zigbee2mqtt/z2m_probe/availability",
       "device": {"identifiers": ["z2m_e2e_probe"], "name": "z2m_probe",
                  "manufacturer": "zigbee2mqtt", "model": "TS0601_e2e"},
       "name": None, "unique_id": "z2m_e2e_probe_temp",
       "state_topic": "zigbee2mqtt/z2m_probe",
       "unit_of_measurement": "°C", "device_class": "temperature",
       "object_id": "z2m_e2e_probe_temperature",
       "value_template": "{{ value_json.temperature }}"}
cl.publish("homeassistant/sensor/z2m_e2e/probe/config", json.dumps(cfg), retain=True)
cl.publish("zigbee2mqtt/z2m_probe/availability", "online", retain=True)
cl.publish("zigbee2mqtt/z2m_probe", json.dumps({"temperature": 21.5, "linkquality": 90}), retain=True)
eid = "sensor.z2m_e2e_probe_temperature"
st = None
for _ in range(30):
    time.sleep(2)
    try:
        st = api(f"/states/{eid}")
        break
    except Exception:
        pass
assert st, "Z5 discovery 未在 HA 建出实体（HA MQTT 集成消费链断）"
assert st["state"] == "21.5", f"Z5 实体状态错: {st['state']}"
# 控制/更新面：模拟 z2m 状态推进
cl.publish("zigbee2mqtt/z2m_probe", json.dumps({"temperature": 23.0, "linkquality": 88}), retain=True)
time.sleep(2)
st2 = api(f"/states/{eid}")
assert st2["state"] == "23.0", f"Z5 状态更新失败: {st2['state']}"
# 清理：retained 置空 + 删实体（discovery remove 语义）
cl.publish("homeassistant/sensor/z2m_e2e/probe/config", "", retain=True)
time.sleep(2); cl.loop_stop(); cl.disconnect()
print("✅ Z5 真 HA：z2m 形态 discovery→实体创建→状态更新（清理完成）")
YY
echo ""
echo "═══ zigbee2mqtt 直连慧尖全链路实证通过（生产认证形态 Z1-Z4 + 真 HA 消费 Z5）═══"
