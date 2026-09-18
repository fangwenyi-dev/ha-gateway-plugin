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
DEV_SN = "500700000001"     # v1.7.21：SN 前四位=机型码，5007 支持百分比
DEV_SN_5002 = "500200000001"  # 5002 平开窗：暂不支持百分比（走三态形态）
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
    # v1.7.21：双机型同报——SN 前四位即机型码，能力逐机型不同。
    # 5007 后装开窗电机（支持百分比）+ 5002 平开窗（暂不支持，r_travel=255
    # 即实机"未校准"形态）。两条分支都必须在真栈上被证伪/证实。
    payload = {"head": {"cmdid": "002", "id": rid}, "ctype": "002", "id": rid,
               "sn": GW_SN, "data": {"status": 1, "devices": [
                   {"sn": DEV_SN, "model": "5007", "battery": 1210,
                    "r_travel": rtravel},
                   {"sn": DEV_SN_5002, "model": "5002", "battery": 1200,
                    "r_travel": 255}]}}
    pc.publish("gateway/rpt_rsp", json.dumps(payload)).wait_for_publish(timeout=5)


publish_002(9001, 50)

step("H", "轮询集成自带 devices 视图：gateway_online + 子设备")
deadline = time.time() + 60
online = found = False
while time.time() < deadline:
    st, devs = call("GET", f"/api/window_controller_gateway/devices?config_entry_id={entry}")
    if st == 200 and isinstance(devs, list) and devs:
        online = any(d.get("gateway_online") is True for d in devs)
        # v1.7.21：视图是扁平设备列表（网关 + 各子设备各自一条），
        # 按 identifiers 取 SN 集合判两台子设备都已注册
        _sns = {i[1] for d in devs for i in (d.get("identifiers") or [])
                if isinstance(i, list) and len(i) > 1}
        found = DEV_SN in _sns and DEV_SN_5002 in _sns
        if online and found:
            break
    time.sleep(3)
if not online:
    die("gateway_online 未在 60s 内转 true（connected 判定链路异常）")
if not found:
    die("002 子设备未进入设备注册表（_quick_add_device/registry 链路异常）")
step("H", f"MQTT→handler→registry→REST 全链路实证 ✓（ack 捕获 {len(acks)} 条→req）")

# ---------- H2. v1.7.20 HomeKit Window 契约（真栈实证） ----------
# 上游 homeassistant/components/homekit/type_covers.py 实证：Window
# accessory 判据 = device_class window + supported_features & SET_POSITION
# (4) + current_position 数值（"must support set_cover_position"）。
# 本段用真实 HA 核对该实体状态三输入，并走一次
# cover.set_cover_position 服务 → 真 broker req 主题捕获 004——即
# Apple Home 滑块拖动的完整链路（只差 HAP 协议层，那层由用户模板实证）。
step("H2", "cover 实体 HomeKit Window 输入面 + set_cover_position 真发 004")


def _cover_entities_by_sn(devs):
    """devices 视图 → {子设备SN: cover 实体}（identifiers 带 SN，零猜测）"""
    out = {}
    for d in devs or []:
        if not isinstance(d, dict):
            continue
        sns = [i[1] for i in (d.get("identifiers") or []) if isinstance(i, list) and len(i) > 1]
        if not sns:
            continue
        for e in (d.get("entities") or []):
            if e.get("domain") == "cover":
                out[sns[0]] = e["entity_id"]
    return out


_cover_map = _cover_entities_by_sn(devs)
_eid_5007 = _cover_map.get(DEV_SN)
_eid_5002 = _cover_map.get(DEV_SN_5002)
if not _eid_5007 or not _eid_5002:
    die(f"devices 视图未见两台子设备的 cover 实体（{_cover_map}）")


def _state_attrs(eid, want_position=None):
    """轮询实体状态直到出现期望形态（cover 实体异步创建）"""
    attrs, state = {}, {}
    deadline = time.time() + 20
    while time.time() < deadline:
        st, body = call("GET", f"/api/states/{eid}")
        if st == 200:
            attrs = (body or {}).get("attributes", {})
            state = body or {}
            if want_position is None or isinstance(attrs.get("current_position"), int):
                break
        time.sleep(2)
    return attrs, state


# --- 支持百分比的机型（5007）：Window 形态三输入 + 004 真发 ---
cov_attrs, cov_state = _state_attrs(_eid_5007, want_position=True)
if not cov_attrs.get("supported_features", 0) & 4:
    die(f"5007 supported_features 缺 SET_POSITION(4)（={cov_attrs.get('supported_features')}）")
if cov_attrs.get("device_class") != "window":
    die(f"5007 device_class != window（={cov_attrs.get('device_class')}）")
if cov_attrs.get("current_position") != 50:
    die(f"r_travel=50 上报后 current_position 应为 50（={cov_attrs.get('current_position')}）")
if cov_attrs.get("position_capable") is not True:
    die("5007 的 position_capable 属性应为 True")
# 状态口径钉死（v1.6.8 定案）：status 推导 open=50≠0；即便按位置分支计算
# 的 HA 旧版 state 逻辑，50>0 同判 open——两代口径下该断言恒成立。
if (cov_state or {}).get("state") != "open":
    die(f"cover.state 应为 open（={cov_state}）——位置暴露不得改变状态口径")
_n0 = len(acks)
st_scp, scp_resp = call("POST", "/api/services/cover/set_cover_position",
                        json_body={"entity_id": _eid_5007, "position": 37})
if st_scp >= 300:
    die(f"5007 cover.set_cover_position 服务调用失败: HTTP {st_scp} {scp_resp}")
_pos_seen = False
_dead = time.time() + 15
while time.time() < _dead and not _pos_seen:
    for raw in acks[_n0:]:
        try:
            j = json.loads(raw)
        except Exception:
            continue
        dat = j.get("data") or {}
        if (str(dat.get("value")) == "37"
                and dat.get("attribute") == "w_travel"
                and dat.get("sn") == DEV_SN):
            _pos_seen = True
            break
    time.sleep(0.5)
if not _pos_seen:
    die("req 主题未捕获 value=37/w_travel 的 004 报文（服务→MQTT 下发链路断）")

# --- 无百分比的机型（5002）：必须落回三态形态，且位置服务被拒 ---
cov2_attrs, cov2_state = _state_attrs(_eid_5002)
if cov2_attrs.get("supported_features", 0) & 4:
    die(f"5002 不应声明 SET_POSITION（={cov2_attrs.get('supported_features')}）——"
        "否则 HomeKit 出现假滑块且丢失三段式暂停")
if cov2_attrs.get("position_capable") is not False:
    die("5002 的 position_capable 属性应为 False")
if cov2_attrs.get("device_class") != "window":
    die(f"5002 device_class 应仍为 window（={cov2_attrs.get('device_class')}）")
st_rej, rej_body = call("POST", "/api/services/cover/set_cover_position",
                        json_body={"entity_id": _eid_5002, "position": 37})
if st_rej < 400:
    die(f"5002 的位置服务调用应被 HA 拒绝（HTTP {st_rej}）——无百分比硬件不得受理")
_n1 = len(acks)
time.sleep(2)
_leaked = [a for a in acks[_n1:] if DEV_SN_5002 in a and "w_travel" in a]
if _leaked:
    die(f"5002 的无效位置指令泄漏到 LoRa 空口：{_leaked[:1]}")
step("H2", "HomeKit 双机型实证：5007 Window(SET_POSITION+position=50+004 真发) / "
           "5002 三态(无位置位、位置服务被拒、无空口泄漏) ✓")

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

# v1.7.31（B-2 真栈门禁）：带合法子协议令牌但**非 WS 升级**的 GET 必须收到
# 显式 4xx 状态行。回归到"return 未 prepared 的 ws"形态时，aiohttp
# finish_response 二次 prepare 抛 HTTPBadRequest 逃逸成 Unhandled ERROR、
# 连接无状态行即被掐（0918 台架栈实锤）——这里以裸 socket 读原始响应验证。
req = (b"GET /ws HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n"
       b"Sec-WebSocket-Protocol: hIZ56jhQ-wzA3ENiP2xGzo55PXsewUWM\r\n"
       b"Connection: keep-alive\r\n\r\n") % WS_PORT
try:
    with socket.create_connection(("127.0.0.1", WS_PORT), timeout=5) as sk:
        sk.sendall(req)
        resp = sk.recv(256)
    head = resp.split(b"\r\n", 1)[0].decode(errors="replace")
    if not head.startswith("HTTP/1.1 4"):
        die(f"B-2 回归：GET(带令牌,非升级) 响应 {head!r}——应为 4xx 显式回复")
    step("I", f"非升级 GET 显式 {head.split()[1]} 回复 ✓（B-2 守护）")
except OSError as e:
    die(f"B-2 探测连接失败：{e}")

# ---------- J. soak ----------
step("J", "500 条 002 上报吞吐与稳定性 soak")
t0 = time.time()
for i in range(500):
    payload = {"head": {"cmdid": "002", "id": 10000 + i}, "ctype": "002",
               "id": 10000 + i, "sn": GW_SN, "data": {"status": 1, "devices": [
                   {"sn": DEV_SN, "model": "5007", "battery": 1210,
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
                "- HomeKit 双机型：5007 Window(SET_POSITION/position/004 真发)、5002 三态(位置服务被拒) ✓\n"
                f"- soak 500 条注入 ~{rate:.0f}/s，HA 全程可用\n")

pc.loop_stop()
print("E2E 全部断言通过 ✅")
