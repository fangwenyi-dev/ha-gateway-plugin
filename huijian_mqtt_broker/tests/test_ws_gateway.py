"""v1.6.15 小程序 WS 网关（路线 A）回归测试。

钉死与固件 app_ws_gateway.c 逐行核对出的协议契约（静默失效面，全部断言实参）：
1. 握手令牌：Sec-WebSocket-Protocol 候选拆分（','/' ' 分隔）、精确匹配、
   空令牌 = 不认证（B16 bootstrap 前提）
2. set_token 校验链与固件消息逐字对齐
3. 命令 dispatch：missing cmd / unknown command / ping→pong
4. control 路由与 004 透传实参（含设备→网关映射缺失时广播在线网关）
5. pair/unbind 前置校验与如实 ack（L5/M6 语义）
6. gateway_list/device_list/device_update 字段拼写与 -1=未知约定
7. aiohttp 子协议回显 E2E（握手层真实验证，模拟小程序 wx.connectSocket）
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from custom_components.window_controller_gateway.ws_gateway import (
    WsGatewayServer,
    device_ws_view,
    handshake_token_ok,
    offered_subprotocols,
    validate_new_token,
    ws_gateway_wanted,
    WS_GATEWAY_DATA_KEY,
    _MSG_BAD_CHARS,
    _MSG_MISSING_NEW,
    _MSG_OLD_MISMATCH,
    _MSG_TOO_LONG,
    _MSG_TOO_SHORT,
)
from custom_components.window_controller_gateway.const import (
    CONF_WS_GATEWAY_ENABLED,
    CONF_WS_GATEWAY_PORT,
    CONF_WS_GATEWAY_TOKEN,
    DEFAULT_WS_GATEWAY_TOKEN,
    DOMAIN,
    DEVICE_TO_GATEWAY_MAPPING,
)


# ==================== 替身 ====================

class FakeDM:
    def __init__(self, devices=None, gateway_sn="GW"):
        self.devices = devices if devices is not None else {}
        self.gateway_sn = gateway_sn
        self.listeners = []
        self.status_calls = []

    def add_status_listener(self, cb):
        if cb not in self.listeners:
            self.listeners.append(cb)

    def remove_status_listener(self, cb):
        if cb in self.listeners:
            self.listeners.remove(cb)

    async def update_gateway_status(self, status):
        self.status_calls.append(status)


class FakeHandler:
    def __init__(self, gateway_sn, connected=True, fail004=False):
        self.gateway_sn = gateway_sn
        self.connected = connected
        self.raw004 = []
        self.commands = []
        self.fail004 = fail004
        self.unbinds = []

    async def send_ws_raw_004(self, device_sn, attribute, value):
        self.raw004.append((device_sn, attribute, value))
        return not self.fail004

    async def send_command(self, sn, command, params=None):
        self.commands.append((sn, command))
        return True

    async def unbind_device(self, device_sn):
        self.unbinds.append(device_sn)


class FakeHass:
    def __init__(self, domain_data):
        self.data = {DOMAIN: domain_data}
        self.tasks = []
        self.loop = None
        self.config = SimpleNamespace(config_dir=".")

    def async_create_task(self, coro, **kwargs):
        # 保留协程引用；需要执行时由测试驱动（不隐式起事件循环任务）
        if asyncio.iscoroutine(coro):
            coro.close()
        return None


def make_server(token="tok12345", entries=None, hass=None):
    """entries: {gateway_sn: (handler, dm)}；dm.devices 由调用方填充"""
    if hass is None:
        data = {}
        for gw, (h, dm) in (entries or {}).items():
            data[f"entry_{gw}"] = {
                "_setup_complete": True,
                "gateway_sn": gw,
                "mqtt_handler": h,
                "device_manager": dm,
            }
        hass = FakeHass(data)
    return WsGatewayServer(hass, host="127.0.0.1", port=9999, token=token)


# ==================== 1. 握手令牌 ====================

class TestHandshakeToken:
    def test_offereds_split_by_comma_and_space(self):
        assert offered_subprotocols("a, b") == ["a", "b"]
        assert offered_subprotocols("x y") == ["x", "y"]
        assert offered_subprotocols(" tok12345 ") == ["tok12345"]
        assert offered_subprotocols("") == []
        assert offered_subprotocols(None) == []

    def test_exact_match_required(self):
        assert handshake_token_ok("tok12345", "tok12345") is True
        assert handshake_token_ok("other, tok12345", "tok12345") is True
        assert handshake_token_ok("tok1234", "tok12345") is False
        # 前缀命中不是命中（固件 strtok 精确 strcmp）
        assert handshake_token_ok("tok123456", "tok12345") is False

    def test_empty_token_disables_auth(self):
        assert handshake_token_ok(None, "") is True
        assert handshake_token_ok("whatever", "") is True


# ==================== 2. set_token 校验链 ====================

class TestValidateNewToken:
    def test_missing_new(self):
        assert validate_new_token("", "", "cur") == _MSG_MISSING_NEW
        assert validate_new_token(None, "", "cur") == _MSG_MISSING_NEW

    def test_too_short(self):
        assert validate_new_token("a" * 7, "x" * 7, "x" * 7) == _MSG_TOO_SHORT

    def test_too_long_rejects_63(self):
        # 固件 s_ws_token[64]：strlen>=63 拒绝 → 62 合法、63 非法
        assert validate_new_token("a" * 62, "a" * 62, "a" * 62) is None
        assert validate_new_token("a" * 63, "", "") == _MSG_TOO_LONG

    def test_bad_charset(self):
        assert validate_new_token("bad token!", "", "") == _MSG_BAD_CHARS
        assert validate_new_token("ok_1-ABCD", "", "") is None

    def test_old_mismatch_only_when_auth_active(self):
        assert validate_new_token("newtoken1", "wrong", "current1") == _MSG_OLD_MISMATCH
        assert validate_new_token("newtoken1", "current1", "current1") is None
        # B16 bootstrap：认证未启用（current 为空）跳过 oldToken 匹配
        assert validate_new_token("newtoken1", "", "") is None
        assert validate_new_token("newtoken1", None, "") is None


# ==================== 3. device_ws_view -1 约定与换算 ====================

class TestDeviceView:
    def test_full_state(self):
        dev = {"attributes": {"r_travel": 42, "voltage": 24.0}}
        v = device_ws_view("5005A1", "GW1", dev)
        assert v == {"sn": "5005A1", "gwSn": "GW1", "position": 42,
                     "battery": 240, "state": 1}

    def test_closed(self):
        v = device_ws_view("D", "G", {"attributes": {"r_travel": 0, "voltage": 12.3}})
        assert v["position"] == 0 and v["state"] == 0 and v["battery"] == 123

    def test_unknown_fields_are_minus_one(self):
        v = device_ws_view("D", "G", {})
        assert v == {"sn": "D", "gwSn": "G", "position": -1, "battery": -1, "state": -1}

    def test_bad_voltage_falls_to_minus_one(self):
        v = device_ws_view("D", "G", {"attributes": {"voltage": "abc", "r_travel": 5}})
        assert v["battery"] == -1 and v["state"] == 1


# ==================== 4. dispatch 核心语义 ====================

class TestDispatch:
    @pytest.mark.asyncio
    async def test_missing_cmd_and_unknown(self):
        s = make_server()
        assert await s.handle_json_message("{}") == {"type": "error", "msg": "missing cmd"}
        assert await s.handle_json_message("not json") == {"type": "error", "msg": "missing cmd"}
        assert await s.handle_json_message('{"cmd":"nope"}') == {
            "type": "error", "msg": "unknown command: nope"}
        assert await s.handle_json_message('{"cmd":""}') == {
            "type": "error", "msg": "missing cmd"}
        assert await s.handle_json_message('{"cmd":"ping"}') == {"type": "pong"}

    @pytest.mark.asyncio
    async def test_gateway_list_shape(self):
        h = FakeHandler("GW1", connected=True)
        s = make_server(entries={"GW1": (h, FakeDM(gateway_sn="GW1"))})
        out = await s.handle_json_message('{"cmd":"get_gateways"}')
        assert out == {"type": "gateway_list", "gateways": [{"sn": "GW1", "online": True}]}

    @pytest.mark.asyncio
    async def test_device_list_shape(self):
        dm = FakeDM(devices={"5005A": {"attributes": {"r_travel": 0}}}, gateway_sn="GW1")
        s = make_server(entries={"GW1": (FakeHandler("GW1"), dm)})
        out = await s.handle_json_message('{"cmd":"get_devices"}')
        assert out == {"type": "device_list", "devices": [
            {"sn": "5005A", "gwSn": "GW1", "position": 0, "battery": -1, "state": 0}]}

    @pytest.mark.asyncio
    async def test_control_routes_to_owning_gateway_with_raw_args(self):
        dm = FakeDM(devices={"5005A": {}}, gateway_sn="GW1")
        h1, h2 = FakeHandler("GW1"), FakeHandler("GW2")
        s = make_server(entries={"GW1": (h1, dm), "GW2": (h2, FakeDM(gateway_sn="GW2"))})
        out = await s.handle_json_message(json.dumps({
            "cmd": "control", "gwSn": "IGNORED", "devSn": "5005A",
            "attribute": "w_travel", "value": "100"}))
        assert out == {"type": "control_ack", "ok": True, "msg": "ok"}
        assert h1.raw004 == [("5005A", "w_travel", "100")]
        assert h2.raw004 == []  # 定向，不广播

    @pytest.mark.asyncio
    async def test_control_broadcasts_only_to_online_on_mapping_miss(self):
        h_on, h_off = FakeHandler("GW1"), FakeHandler("GW2", connected=False)
        s = make_server(entries={"GW1": (h_on, FakeDM(gateway_sn="GW1")),
                                 "GW2": (h_off, FakeDM(gateway_sn="GW2"))})
        out = await s.handle_json_message(json.dumps({
            "cmd": "control", "gwSn": "X", "devSn": "UNKNOWN_DEV",
            "attribute": "rwp_wind_lock_mode", "value": 0}))
        assert out["ok"] is True
        assert h_on.raw004 == [("UNKNOWN_DEV", "rwp_wind_lock_mode", "0")]
        assert h_off.raw004 == []  # 离线网关不收广播（固件同语义）

    @pytest.mark.asyncio
    async def test_control_global_mapping_hit(self):
        """设备经全局 DEVICE_TO_GATEWAY_MAPPING 归属（缓存里还没有该设备）"""
        hass_data = {
            "entry_GW1": {"_setup_complete": True, "gateway_sn": "GW1",
                          "mqtt_handler": (h1 := FakeHandler("GW1")),
                          "device_manager": FakeDM(gateway_sn="GW1")},
            "entry_GW2": {"_setup_complete": True, "gateway_sn": "GW2",
                          "mqtt_handler": (h2 := FakeHandler("GW2")),
                          "device_manager": FakeDM(gateway_sn="GW2")},
            DEVICE_TO_GATEWAY_MAPPING: {"5005A": "gw1"},  # 大小写不敏感
        }
        s = make_server(entries=None, hass=FakeHass(hass_data))
        await s.handle_json_message(json.dumps({
            "cmd": "control", "gwSn": "X", "devSn": "5005A",
            "attribute": "w_travel", "value": "50"}))
        assert h1.raw004 == [("5005A", "w_travel", "50")]
        assert h2.raw004 == []

    @pytest.mark.asyncio
    async def test_control_missing_fields(self):
        s = make_server()
        out = await s.handle_json_message(json.dumps(
            {"cmd": "control", "gwSn": "G", "devSn": "", "attribute": "w_travel", "value": "0"}))
        assert out == {"type": "control_ack", "ok": False, "msg": "missing fields"}
        # value 缺失同样拒绝
        out = await s.handle_json_message(json.dumps(
            {"cmd": "control", "gwSn": "G", "devSn": "D", "attribute": "w_travel"}))
        assert out == {"type": "control_ack", "ok": False, "msg": "missing fields"}

    @pytest.mark.asyncio
    async def test_control_send_failure_reports_send_failed_not_ok(self):
        """publish 失败必须回 ok:false "send failed"——假成功是历史 bug 家族"""
        h = FakeHandler("GW1", fail004=True)
        dm = FakeDM(devices={"5005A": {}}, gateway_sn="GW1")
        s = make_server(entries={"GW1": (h, dm)})
        out = await s.handle_json_message(json.dumps({
            "cmd": "control", "gwSn": "GW1", "devSn": "5005A",
            "attribute": "w_travel", "value": "100"}))
        assert out == {"type": "control_ack", "ok": False, "msg": "send failed"}
        # 广播路径同样如实
        s2 = make_server(entries={"GW1": (FakeHandler("GW1", fail004=True),
                                          FakeDM(gateway_sn="GW1"))})
        out = await s2.handle_json_message(json.dumps({
            "cmd": "control", "gwSn": "X", "devSn": "UNKNOWN",
            "attribute": "w_travel", "value": "0"}))
        assert out == {"type": "control_ack", "ok": False, "msg": "send failed"}

    @pytest.mark.asyncio
    async def test_pair_gated_on_gateway_online(self):
        h_off = FakeHandler("GW1", connected=False)
        h_on = FakeHandler("GW2")
        s = make_server(entries={"GW1": (h_off, FakeDM(gateway_sn="GW1")),
                                 "GW2": (h_on, FakeDM(gateway_sn="GW2"))})
        out = await s.handle_json_message('{"cmd":"pair","gwSn":"GW1"}')
        assert out == {"type": "pair_ack", "ok": False,
                       "msg": "gateway offline or not registered"}
        out = await s.handle_json_message('{"cmd":"pair","gwSn":"NOPE"}')
        assert out["ok"] is False  # 未注册网关
        out = await s.handle_json_message('{"cmd":"pair","gwSn":"GW2"}')
        assert out == {"type": "pair_ack", "ok": True}
        assert h_on.commands == [("GW2", "start_pairing")]

    @pytest.mark.asyncio
    async def test_pair_broadcast_without_gwsn(self):
        h1, h2 = FakeHandler("GW1"), FakeHandler("GW2", connected=False)
        s = make_server(entries={"GW1": (h1, FakeDM(gateway_sn="GW1")),
                                 "GW2": (h2, FakeDM(gateway_sn="GW2"))})
        out = await s.handle_json_message('{"cmd":"pair"}')
        assert out == {"type": "pair_ack", "ok": True}
        assert h1.commands == [("GW1", "start_pairing")]
        assert h2.commands == [("GW2", "start_pairing")]  # 广播含离线（固件同语义）

    @pytest.mark.asyncio
    async def test_unbind_prechecks_and_passthrough(self):
        dm = FakeDM(devices={"5005A": {}}, gateway_sn="GW1")
        h = FakeHandler("GW1")
        s = make_server(entries={"GW1": (h, dm)})
        # 缺字段
        out = await s.handle_json_message('{"cmd":"unbind","gwSn":"GW1"}')
        assert out == {"type": "unbind_ack", "ok": False, "msg": "missing gwSn or devSn"}
        # 设备未知
        out = await s.handle_json_message('{"cmd":"unbind","gwSn":"GW1","devSn":"ZZ"}')
        assert out == {"type": "unbind_ack", "ok": False,
                       "msg": "gateway offline or device unknown"}
        # 正常路径
        out = await s.handle_json_message('{"cmd":"unbind","gwSn":"GW1","devSn":"5005A"}')
        assert out == {"type": "unbind_ack", "ok": True}
        assert h.unbinds == ["5005A"]


# ==================== 5. set_token 与 device_update 推送 ====================

class TestSetTokenAndPush:
    @pytest.mark.asyncio
    async def test_set_token_updates_runtime_and_persists(self):
        s = make_server(token="current1")
        resp = await s.handle_json_message(json.dumps(
            {"cmd": "set_token", "oldToken": "wrong!!", "newToken": "brandnew1"}))
        assert resp == {"type": "set_token_ack", "ok": False, "msg": "old token mismatch"}
        assert s._token == "current1"  # 失败不得改运行时

        resp = await s.handle_json_message(json.dumps(
            {"cmd": "set_token", "oldToken": "current1", "newToken": "brandnew1"}))
        assert resp == {"type": "set_token_ack", "ok": True, "msg": "token updated"}
        assert s._token == "brandnew1"

        # 持久化链：写入主控 entry options
        entry = SimpleNamespace(entry_id="e1", options={CONF_WS_GATEWAY_ENABLED: True})
        updated = {}

        class CE:
            def async_entries(self, domain):
                assert domain == DOMAIN
                return [entry]

            def async_update_entry(self, e, options=None):
                updated["options"] = options

        s.hass.config_entries = CE()
        await s._persist_token("brandnew1")
        assert updated["options"][CONF_WS_GATEWAY_TOKEN] == "brandnew1"

    def test_device_update_payload(self):
        dm = FakeDM(devices={"5005A": {"attributes": {
            "r_travel": 30, "voltage": 24.0, "wind_lock_mode": "1"}}}, gateway_sn="GW1")
        s = make_server(entries={"GW1": (FakeHandler("GW1"), dm)})
        p = s._device_update_payload("GW1", "5005A")
        assert p == {"type": "device_update", "gwSn": "GW1", "devSn": "5005A",
                     "position": 30, "battery": 240, "state": 1, "windLockMode": 1}
        # 未知网关/设备 → None（不推）
        assert s._device_update_payload("NOPE", "5005A") is None
        assert s._device_update_payload("GW1", "ZZ") is None


# ==================== 6. 聚合配置 ====================

class TestWantedConfig:
    class _CE:
        def __init__(self, entries):
            self._e = entries

        def async_entries(self, domain):
            return self._e

    def _hass(self, options_list):
        entries = [SimpleNamespace(entry_id=f"e{i}", options=opt)
                   for i, opt in enumerate(options_list)]
        return SimpleNamespace(config_entries=self._CE(entries))

    def test_none_when_disabled(self):
        assert ws_gateway_wanted(self._hass([{CONF_WS_GATEWAY_ENABLED: False}])) is None
        assert ws_gateway_wanted(self._hass([{}])) is None

    def test_first_enabled_wins_defaults(self):
        w = ws_gateway_wanted(self._hass([
            {}, {CONF_WS_GATEWAY_ENABLED: True}]))
        assert w == (9001, DEFAULT_WS_GATEWAY_TOKEN)

    def test_custom_port_token(self):
        w = ws_gateway_wanted(self._hass([
            {CONF_WS_GATEWAY_ENABLED: True, CONF_WS_GATEWAY_PORT: "9100",
             CONF_WS_GATEWAY_TOKEN: "my-token_1"}]))
        assert w == (9100, "my-token_1")

    def test_empty_token_string_means_no_auth(self):
        w = ws_gateway_wanted(self._hass([
            {CONF_WS_GATEWAY_ENABLED: True, CONF_WS_GATEWAY_TOKEN: ""}]))
        assert w == (9001, "")

    def test_invalid_port_falls_back(self):
        w = ws_gateway_wanted(self._hass([
            {CONF_WS_GATEWAY_ENABLED: True, CONF_WS_GATEWAY_PORT: "66000"}]))
        assert w == (9001, DEFAULT_WS_GATEWAY_TOKEN)


# ==================== 7. send_ws_raw_004 线格式（真 handler） ====================

class TestWire004:
    """control 的 MQTT 出口逐字节钉死——LoRa 网关按 $SH 004 解析，
    键名/id 类型/QoS/topic 任一漂移都是静默失效面（实参断言纪律）"""

    @pytest.mark.asyncio
    async def test_wire_payload_topic_qos(self, monkeypatch):
        import custom_components.window_controller_gateway.mqtt_handler as mh_mod
        from custom_components.window_controller_gateway.mqtt_handler import (
            WindowControllerMQTTHandler,
        )

        captured = []

        async def fake_publish(hass, topic, payload, qos, retain):
            captured.append((topic, payload, qos, retain))

        monkeypatch.setattr(mh_mod.mqtt, "async_publish", fake_publish)
        handler = WindowControllerMQTTHandler(FakeHass({}), "GW9",
                                              FakeDM(gateway_sn="GW9"))
        before = handler.command_id
        ok = await handler.send_ws_raw_004("5005B", "w_travel", "100")
        assert ok is True
        topic, payload, qos, retain = captured[0]
        assert topic == "gateway/GW9/req"
        assert qos == 1 and retain is False
        obj = json.loads(payload)
        assert obj == {"head": "$SH", "ctype": "004", "id": before,
                       "data": {"sn": "5005B", "attribute": "w_travel",
                                "value": "100"},
                       "sn": "GW9"}
        assert isinstance(obj["id"], int)
        assert handler.command_id == before + 1  # id 递增与 send_command 同计数器

    @pytest.mark.asyncio
    async def test_publish_failure_returns_false_and_marks_offline(self, monkeypatch):
        import custom_components.window_controller_gateway.mqtt_handler as mh_mod
        from custom_components.window_controller_gateway.mqtt_handler import (
            WindowControllerMQTTHandler,
        )

        async def boom(*args, **kwargs):
            raise RuntimeError("broker gone")

        monkeypatch.setattr(mh_mod.mqtt, "async_publish", boom)
        dm = FakeDM(gateway_sn="GW9")
        hass = FakeHass({})
        hass.loop = asyncio.get_running_loop()  # _schedule_async_task 判定路径

        def _real_task(coro, **kw):
            return asyncio.ensure_future(coro)

        hass.async_create_task = _real_task
        handler = WindowControllerMQTTHandler(hass, "GW9", dm)
        handler.connected = True
        notified = []
        monkeypatch.setattr(handler, "_notify_status_change",
                            lambda: notified.append(1))
        ok = await handler.send_ws_raw_004("D", "w_travel", "0")
        await asyncio.sleep(0)  # 让离线同步任务跑完
        assert ok is False  # WS control_ack 据此回 send failed（不得假成功）
        assert handler.connected is False
        assert notified == [1]
        assert dm.status_calls == ["offline"]  # 双状态源同步（v1.6.11 #4 定式）


# ==================== 8. aiohttp 握手/子协议回显 E2E ====================

class TestE2E:
    @pytest.mark.asyncio
    async def test_handshake_auth_and_roundtrip(self):
        """真 aiohttp 握手：模拟小程序 wx.connectSocket 的
        Sec-WebSocket-Protocol 头——无令牌 401、错令牌 401、
        正确令牌 101+子协议回显+get_gateways/device_update 全链路。"""
        from aiohttp import ClientSession
        from aiohttp.client_exceptions import WSServerHandshakeError

        dm = FakeDM(devices={}, gateway_sn="GW1")
        handler = FakeHandler("GW1")
        data = {"entry_GW1": {"_setup_complete": True, "gateway_sn": "GW1",
                              "mqtt_handler": handler, "device_manager": dm}}

        class RunHass(FakeHass):
            def async_create_task(self, coro, **kwargs):
                return asyncio.ensure_future(coro)

        hass = RunHass(data)
        # 找一个空闲端口
        import socket as _sock
        probe = _sock.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        server = WsGatewayServer(hass, host="127.0.0.1", port=port, token="tok-e2e-1")
        await server.async_start()
        server._attach_listeners([dm])
        try:
            url = f"ws://127.0.0.1:{port}/ws"
            async with ClientSession() as sess:
                # 无令牌 → 401
                with pytest.raises(WSServerHandshakeError) as ei:
                    async with sess.ws_connect(url) as _ws:
                        pass
                assert ei.value.status == 401
                # 错令牌 → 401
                with pytest.raises(WSServerHandshakeError) as ei:
                    async with sess.ws_connect(url, protocols=["wrong-token"]) as _ws:
                        pass
                assert ei.value.status == 401
                # 正确令牌 → 101 + 101 响应头回显子协议（esp_http_server
                # supported_subprotocol 同款行为；aiohttp 客户端无公开
                # 属性，_response 私有但 3.x 长期稳定）+ 往返
                async with sess.ws_connect(url, protocols=["tok-e2e-1"]) as ws:
                    assert ws._response.headers.get("Sec-WebSocket-Protocol") == "tok-e2e-1"
                    await ws.send_str('{"cmd":"get_gateways"}')
                    msg = await ws.receive(timeout=5)
                    assert json.loads(msg.data) == {
                        "type": "gateway_list",
                        "gateways": [{"sn": "GW1", "online": True}]}
                    # 设备状态变化 → device_update 主动推送（监听器已挂）
                    dm.devices["5005B"] = {"attributes": {"r_travel": 0, "voltage": 25.0}}
                    for listener in dm.listeners:
                        listener("GW1", "5005B")
                    msg = await ws.receive(timeout=5)
                    pushed = json.loads(msg.data)
                    assert pushed["type"] == "device_update"
                    assert pushed["devSn"] == "5005B"
                    assert pushed["position"] == 0 and pushed["battery"] == 250
                    # control 经 WS → 网关 handler 实参
                    await ws.send_str(json.dumps(
                        {"cmd": "control", "gwSn": "GW1", "devSn": "5005B",
                         "attribute": "w_travel", "value": "100"}))
                    msg = await ws.receive(timeout=5)
                    assert json.loads(msg.data)["type"] == "control_ack"
                    assert handler.raw004 == [("5005B", "w_travel", "100")]
                    # ping → pong
                    await ws.send_str('{"cmd":"ping"}')
                    msg = await ws.receive(timeout=5)
                    assert json.loads(msg.data) == {"type": "pong"}
            # 全部会话结束后连接数归零（等服务器处理 close 帧）
            for _ in range(50):
                if not server._clients:
                    break
                await asyncio.sleep(0.05)
            assert server._clients == set()
        finally:
            await server.async_stop()
