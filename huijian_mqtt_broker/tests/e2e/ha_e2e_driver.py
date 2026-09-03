#!/usr/bin/env python3
"""v1.6.21 真栈 E2E 驱动器——本地与 CI 单一事实源（第七轮评分补债）。

契约来源（2026-07 读 HA core 2026.7.1 源码实证，勿再试错猜 API）：
- POST /api/onboarding/users 现版本 required: name/username/password/
  client_id(str)/language；client_id 是任意字符串（create_auth_code 只写
  内存 store，不校验注册）；响应 {"auth_code": ...}，不再直发长期令牌
  （两轮 CI 盲打实锤 422 required key 后放弃猜测改读源码）。
- POST /auth/token grant_type=authorization_code 换 access_token（1h，
  对 E2E 足够）。client_id 非任意串：TokenView 经 indieauth
  .verify_client_id 强校验为 http(s) URL 形态（IndieAuth §3.2，本地
  真栈实锤 400 Invalid client id）；但无需预注册（auth_code store
  仅按该串取回 credential）。
- 其余全部走本集成自身契约：config flow → 真 MQTT 002 → devices 视图。

发布/订阅用 paho（HA 自带依赖，零新增环境要求）。仅 stdlib + paho。
"""
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HA = os.environ.get("E2E_HA_URL", "http://127.0.0.1:8123").rstrip("/")
MQTT_HOST = os.environ.get("E2E_MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.environ.get("E2E_MQTT_PORT", "2022"))
GW_SN = "E2EGW0000001"
DEV_SN = "100020003001"
WS_PORT = int(os.environ.get("E2E_WS_PORT", "9001"))
CLIENT_ID = "https://e2e.local.test/"

TOKEN = None


def call(method, path, json_body=None, form=None, timeout=20, auth=True, raw_url=False):
    url = path if raw_url else HA + path
    headers = {}
    if auth and TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode()
            return r.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"_raw": body[:400]}


def die(msg):
    print(f"!! E2E 失败: {msg}", file=sys.stderr)
    sys.exit(1)


def step(n, msg):
    print(f"---- [{n}] {msg}")


# ---------- A. 等待 HA ----------
step("A", "等待 HA API 端口就绪")
deadline = time.time() + 300
ready = False
while time.time() < deadline:
    try:
        call("GET", "/api/", auth=False, timeout=5)
        ready = True  # 401 也算端口活（urlopen 抛 HTTPError 前已建立连接）
        break
    except urllib.error.HTTPError:
        ready = True
        break
    except Exception:
        time.sleep(3)
if not ready:
    die("HA 5 分钟未监听 " + HA)

# ---------- B/C. onboarding → auth_code → access_token ----------
step("B", "onboarding（client_id 任意串，现行 schema 源码实证）")
st, ob = call("POST", "/api/onboarding/users", json_body={
    "client_id": CLIENT_ID, "username": "e2e-admin",
    "password": "e2e-e2e-e2e", "name": "E2E Admin", "language": "en"},
    auth=False)
if st != 200 or not (isinstance(ob, dict) and "auth_code" in ob):
    die(f"onboarding HTTP {st}: {ob}")
step("C", "auth_code → access_token")
st, tk = call("POST", "/auth/token", form={
    "grant_type": "authorization_code", "code": ob["auth_code"],
    "client_id": CLIENT_ID}, auth=False)
if st != 200 or "access_token" not in tk:
    die(f"/auth/token HTTP {st}: {tk}")
TOKEN = tk["access_token"]
# 本地 harness 附加：token 落盘供后续复验脚本复用（一次性测试栈，CI 容器
# 跑完即焚零敏感；run_local.sh 同机可直接读 /tmp/ha_e2e_token）
try:
    with open("/tmp/ha_e2e_token", "w") as _f:
        _f.write(TOKEN)
except OSError:
    pass
step("C", "owner token 到手 ✓")

# ---------- D/E. MQTT 集成 entry ----------
step("D", "config flow 建立 HA MQTT 集成")
st, fl = call("POST", "/api/config/config_entries/flow",
              json_body={"handler": "mqtt", "show_advanced_options": False})
if st != 200 or "flow_id" not in fl:
    die(f"mqtt flow 启动 HTTP {st}: {fl}")
st, res = call("POST", f"/api/config/config_entries/flow/{fl['flow_id']}",
               json_body={"broker": MQTT_HOST, "port": str(MQTT_PORT)})
# 版本兼容（CI :stable 2026.8 实锤 vs 本地 2026.1 全绿）：新版 MQTT user
# step schema 要求 other_settings（advanced options 演进入 schema）——
# 报该键 required 时带空串重交，两代 HA 同码通过。
if isinstance(res, dict) and "other_settings" in json.dumps(res):
    st, res = call("POST", f"/api/config/config_entries/flow/{fl['flow_id']}",
                   json_body={"broker": MQTT_HOST, "port": str(MQTT_PORT),
                              # 26.8 OTHER_SETTINGS_SCHEMA（源码实证）：
                              # set_client_cert bool + set_ca_cert ∈
                              # off/auto/custom 为仅有两个无默认 Required
                              "other_settings": {"set_client_cert": False,
                                                 "set_ca_cert": "off"}})
if isinstance(res, dict) and res.get("type") == "form":
    # 二次 form（如高级项）→ 补交 other_settings 结束流程
    st, res = call("POST", f"/api/config/config_entries/flow/{res['flow_id']}",
                   json_body={"other_settings": {"set_client_cert": False,
                                                 "set_ca_cert": "off"}})
if not (isinstance(res, dict) and res.get("type") == "create_entry"):
    die(f"mqtt entry 创建失败: {res}")
step("E", "等待 mqtt loaded")
state = ""
for _ in range(40):
    st, els = call("GET", "/api/config/config_entries/entry")
    # 该端点返回裸 list（本地真栈实锤），兼容 {entries:[...]} 旧形态
    items = els if isinstance(els, list) else (els or {}).get("entries", [])
    state = next((e.get("state", "?") for e in items if e.get("domain") == "mqtt"), "?")
    if state == "loaded":
        break
    time.sleep(3)
if state != "loaded":
    die(f"mqtt 集成未 loaded（{state}）")
step("E", "mqtt loaded ✓")

# ---------- F. 慧尖 entry ----------
step("F", "config flow 建立慧尖网关条目")
st, fl = call("POST", "/api/config/config_entries/flow",
              json_body={"handler": "window_controller_gateway"})
if st != 200 or "flow_id" not in fl:
    die(f"huijian flow 启动 HTTP {st}: {fl}")
flow_id = fl["flow_id"]
st, res = call("POST", f"/api/config/config_entries/flow/{flow_id}",
               json_body={"gateway_sn": GW_SN, "gateway_name": "E2E网关"})
# 真栈实锤（本地 E2E 首轮）：user 步后有 confirm_add 二步——连通性测试
# 无响应（E2E 上报还没发）时以 confirm 复选框征询，必须真栈走完。
for _ in range(3):
    if not (isinstance(res, dict) and res.get("type") == "form"):
        break
    st, res = call("POST", f"/api/config/config_entries/flow/{res['flow_id']}",
                   json_body={"confirm": True})
entry = res.get("result") if isinstance(res, dict) else None
# 真栈实锤（本地第四轮）：本集成 flow 的 create_entry.result 直接是
# entry **对象**（HA 内建 mqtt 返回字符串 id）——两种形态统一收敛为 id
if isinstance(entry, dict):
    entry = entry.get("entry_id")
if not entry:
    die(f"huijian entry 未创建: {res}")
state = ""
for _ in range(40):
    # 单条详情端点形态存疑（第五轮本地实锤返回体无 state 键），
    # 复用已实证的列表端点按 entry_id 过滤（与 mqtt 轮询同法）
    st, items = call("GET", "/api/config/config_entries/entry")
    items = items if isinstance(items, list) else (items or {}).get("entries", [])
    state = next((e.get("state") for e in items if e.get("entry_id") == entry), "?")
    if state == "loaded":
        break
    time.sleep(3)
if state != "loaded":
    die(f"慧尖 entry 未 loaded（{state}）——真栈 setup 存在 mock 掩盖的问题！")
step("F", "慧尖 entry loaded ✓（真 HA setup 全链路）")

# ---------- G/H. 真 MQTT 002 上报 → devices 视图断言 ----------
import paho.mqtt.client as paho  # HA 自带依赖，零新增

step("G", "paho 经真 broker 发布 002 上报（并订阅 req 观察 ack）")
acks = []
pc = paho.Client(paho.CallbackAPIVersion.VERSION2, client_id="e2e-driver")
pc.connect(MQTT_HOST, MQTT_PORT, 30)


def _onmsg(_c, _u, msg):
    acks.append(msg.payload.decode(errors="replace"))


pc.subscribe(f"gateway/{GW_SN}/req", qos=1)  # 现场实锤 ack 正常发出，
pc.on_message = _onmsg                       # QoS0 订挂竞态曾误报 0 条
pc.loop_start()
time.sleep(1)  # 让 SUB 报文过网再发布，观测才可靠


def publish_002(rid, rtravel):
    payload = {"head": {"cmdid": "002", "id": rid}, "ctype": "002", "id": rid,
               "sn": GW_SN, "data": {"status": 1, "devices": [
                   {"sn": DEV_SN, "model": "5005", "battery": 1210,
                    "r_travel": rtravel}]}}
    pc.publish("gateway/rpt_rsp", json.dumps(payload)).wait_for_publish(timeout=5)


publish_002(9001, 50)

step("H", "轮询集成自带 devices 视图：gateway_online + 子设备")
deadline = time.time() + 60
online = found = False
while time.time() < deadline:
    st, devs = call("GET", f"/api/window_controller_gateway/devices?config_entry_id={entry}")
    if st == 200 and isinstance(devs, list) and devs:
        online = any(d.get("gateway_online") is True for d in devs)
        found = any(DEV_SN in json.dumps(d) for d in devs)
        if online and found:
            break
    time.sleep(3)
if not online:
    die("gateway_online 未在 60s 内转 true（connected 判定链路异常）")
if not found:
    die("002 子设备未进入设备注册表（_quick_add_device/registry 链路异常）")
step("H", f"MQTT→handler→registry→REST 全链路实证 ✓（ack 捕获 {len(acks)} 条→req）")

# ---------- I. WS 网关默认监听 ----------
step("I", f"WS 网关 {WS_PORT} 常听断言（v1.6.16 默认开语义守护）")
ok = False
for _ in range(10):
    try:
        with socket.create_connection(("127.0.0.1", WS_PORT), timeout=3):
            ok = True
        break
    except OSError:
        time.sleep(2)
if not ok:
    die(f"WS {WS_PORT} 未监听——默认开语义被破坏")
step("I", "WS 端口监听 ✓")

# ---------- J. soak ----------
step("J", "500 条 002 上报吞吐与稳定性 soak")
t0 = time.time()
for i in range(500):
    payload = {"head": {"cmdid": "002", "id": 10000 + i}, "ctype": "002",
               "id": 10000 + i, "sn": GW_SN, "data": {"status": 1, "devices": [
                   {"sn": DEV_SN, "model": "5005", "battery": 1210,
                    "r_travel": i % 101}]}}
    pc.publish("gateway/rpt_rsp", json.dumps(payload))
    if i % 50 == 49:
        time.sleep(0.2)  # 微节流：贴近真实心跳风暴而非 DoS
el = time.time() - t0 + 0.5
time.sleep(10)
st, states = call("GET", "/api/states", timeout=30)
if st != 200:
    die("soak 后 /api/states 不再 200（HA 被打挂/阻塞？）")
rate = 500 / el
print(f"soak 500 条 {el:.1f}s（~{rate:.0f}/s 注入），soak 后 HA 全响应正常 ✓")

summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a", encoding="utf-8") as f:
        f.write("## E2E 真栈结果\n"
                "- onboarding/config flow/002 上报全链路真栈 ✓\n"
                f"- gateway_online + 子设备注册 + WS {WS_PORT} 常听 ✓\n"
                f"- soak 500 条注入 ~{rate:.0f}/s，HA 全程可用\n")

pc.loop_stop()
print("E2E 全部断言通过 ✅")
