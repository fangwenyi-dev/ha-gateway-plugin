"""慧尖小程序局域网 WS 网关（v1.6.15，路线 A）

让微信「慧尖」小程序（weichat-huijian-hz）的「Matter 网关」入口在局域网
直连 HA：小程序经 mDNS `_mqtt._tcp`（由慧尖加载项广播）发现本机后，固定
拨 `ws://<IP>:<port>/ws` 并只讲 JSON-over-WebSocket——插件此前只有
Mosquitto@2022 与 nginx@8099，"能看到但连不上"即因 9001 无监听者。

本模块在集成内实现与固件 main/app_ws_gateway.c（E:\\AI\\matter-broker）
1:1 对等的 WS-JSON 网关，作为 HA 的"第二张脸"：

  - 命令下行：control 透传 004（mqtt_handler.send_ws_raw_004，逐字节
    等形于固件 app_protocol_bridge_control_device），pair→003 bind=1，
    unbind→003 bind=0（复用集成既有解绑链）；
  - 状态上行：网关/设备视图直接读各 entry 的 mqtt_handler.connected 与
    device_manager.devices 缓存；device_update 推送挂在
    device_manager.add_status_listener（update_device_status 是 002/005
    的唯一漏斗）；
  - 本模块【不】新建第二条 MQTT $SH 桥——ACK、去重、绑定记账仍全部由
    mqtt_handler 单点承担，避免双桥状态分叉。

与固件的有意差异（行为超集，不与小程序现有链路冲突）：
  - set_token 持久化走 config entry options（HA 惯例，reload 生效）而非
    NVS；reload 会短暂断开现有 WS 连接，小程序自动重连后以新令牌握手。

协议契约（固件源码逐行核对）：
  - 握手：客户端以 Sec-WebSocket-Protocol 携带预共享令牌；令牌非空时
    必须精确命中其一（','/' '分隔），否则拒绝握手（不回 101）。
    令牌为空 = 不认证（固件同款语义，含 B16 bootstrap：可在已连接会话
    上 set_token 直接启用认证）。
  - JSON 文本帧，入站载荷 ≤1024B，超限回 {"type":"error",
    "msg":"command too long"} 并断开；非文本帧消费丢弃；空帧忽略。
  - cmd：get_gateways / get_devices / control / pair / unbind / ping /
    set_token；未知 cmd → error "unknown command: <cmd>"；缺 cmd →
    error "missing cmd"。
  - type：gateway_list / device_list / control_ack / pair_ack /
    unbind_ack / pong / set_token_ack / error；主动推送 device_update
    （含 windLockMode；-1 = 未知约定）。
  - 会话：并发 ≤4（认证成功才占槽，固件 M4 定式）；空闲 300s 断连
    （小程序 60s get_gateways 心跳保活）。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from aiohttp import WSMsgType, web

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_WS_GATEWAY_ENABLED,
    CONF_WS_GATEWAY_PORT,
    CONF_WS_GATEWAY_TOKEN,
    DEFAULT_WS_GATEWAY_ENABLED,
    DEFAULT_WS_GATEWAY_PORT,
    DEFAULT_WS_GATEWAY_TOKEN,
    DEVICE_TO_GATEWAY_MAPPING,
    DOMAIN,
    WS_GATEWAY_PATH,
    WS_MAX_CLIENTS,
    WS_MAX_FRAME_BYTES,
    WS_RECV_TIMEOUT_SECONDS,
    WS_TOKEN_CHARSET,
    WS_TOKEN_MAX_LEN,
    WS_TOKEN_MIN_LEN,
)

_LOGGER = logging.getLogger(__name__)

# 小程序 WS 服务器在 hass.data[DOMAIN] 中的单例键（跨 config entry 共享：
# 一台 HA 只监听一个端口，网关/设备视图聚合全部已完成设置的 entry）
WS_GATEWAY_DATA_KEY = "_ws_gateway"
# HA STOP 闩锁：关机序列中 entry 逐个 unload 不得把服务器重新拉起
WS_GATEWAY_STOPPED_KEY = "_ws_gateway_stopped"

# set_token 校验消息——与固件 app_ws_gateway.c 逐字对齐（小程序侧按 msg 提示）
_MSG_MISSING_NEW = "missing newToken"
_MSG_TOO_SHORT = "newToken too short (min 8)"
_MSG_TOO_LONG = "newToken too long"
_MSG_BAD_CHARS = "newToken invalid chars (A-Za-z0-9_- only)"
_MSG_OLD_MISMATCH = "old token mismatch"


# ==================== 纯函数（握手/校验/视图——单测直接驱动） ====================

def offered_subprotocols(header_value: Optional[str]) -> List[str]:
    """解析 Sec-WebSocket-Protocol 头为候选列表。

    固件以 strtok_r(", ") 拆分（',' 与 ' ' 任一均为分隔符），逐字对齐：
    按 ',' 拆分后 strip 空白（含 ' '）。
    """
    if not header_value:
        return []
    return [p for p in header_value.replace(",", " ").split() if p]


def handshake_token_ok(header_value: Optional[str], token: str) -> bool:
    """握手令牌校验：令牌为空 = 不认证放行；否则候选中须有精确匹配。"""
    if not token:
        return True
    return token in offered_subprotocols(header_value)


def token_charset_ok(token: str) -> bool:
    """固件 ws_token_charset_ok：仅 [A-Za-z0-9_-]（RFC6455 子协议安全字符集）。"""
    return all(c in WS_TOKEN_CHARSET for c in token)


def validate_new_token(new_token: Any, old_token: Any, current_token: str) -> Optional[str]:
    """set_token 校验链，返回错误消息（None = 通过）。固件顺序 1:1：
    missing → min 长度 → max 长度 → 字符集 → （认证启用时）oldToken 匹配。
    认证未启用（current 为空）走 B16 bootstrap：跳过 oldToken 匹配。
    """
    if not isinstance(new_token, str) or new_token == "":
        return _MSG_MISSING_NEW
    if len(new_token) < WS_TOKEN_MIN_LEN:
        return _MSG_TOO_SHORT
    if len(new_token) >= WS_TOKEN_MAX_LEN:
        return _MSG_TOO_LONG
    if not token_charset_ok(new_token):
        return _MSG_BAD_CHARS
    auth_active = bool(current_token)
    if auth_active and (not isinstance(old_token, str) or old_token != current_token):
        return _MSG_OLD_MISMATCH
    return None


def _as_int(value: Any) -> int:
    """固件 -1=未知约定的安全取整：不可解析/None → -1。"""
    if value is None or isinstance(value, bool):
        return -1
    try:
        return int(value)
    except (ValueError, TypeError):
        return -1


def device_ws_view(device_sn: str, gateway_sn: str, device: Dict[str, Any]) -> Dict[str, Any]:
    """由 device_manager 设备缓存条目构造小程序视图。

    字段拼写/类型与固件 get_devices_json + notify_device_update 对齐：
    position=r_travel（-1 未知）；battery=电压×10 的原始值（固件定式
    "HA 集成上报值 ×10 = 毫伏，/100 前即 voltage_mv"，等价 raw），
    -1 未知；state 按 r_travel==0→0 / >0→1 推导（与集成 DEVICE_STATUS
    推导同源），无 r_travel 时 -1。
    """
    attrs = device.get("attributes") or {}
    position = attrs.get("r_travel")
    voltage = attrs.get("voltage")
    if voltage is None:
        battery = -1
    else:
        try:
            battery = int(round(float(voltage) * 10))
        except (ValueError, TypeError):
            battery = -1
    if position is None:
        state = -1
        position_i = -1
    else:
        position_i = _as_int(position)
        state = 0 if position_i == 0 else (1 if position_i > 0 else -1)
    return {
        "sn": device_sn,
        "gwSn": gateway_sn,
        "position": position_i,
        "battery": battery,
        "state": state,
    }


# ==================== 服务器 ====================

class WsGatewayServer:
    """慧尖小程序 WS-JSON 网关服务器（aiohttp，HA 事件循环内运行）。

    生命周期由 async_ensure_ws_gateway 管理：任一 entry 的 options 开启
    ws_gateway_enabled 即启动（单例）；全部关闭/卸载即停止。命令处理
    每次实时遍历 hass.data[DOMAIN] 取当前 entry 集合，entry 增删无需
    重启服务器。
    """

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        host: str = "0.0.0.0",
        port: int,
        token: str,
    ) -> None:
        self.hass = hass
        self.host = host
        self.port = port
        # 运行时令牌。set_token 成功后：本连接立即生效（内存），并异步
        # 持久化到主控 entry options（latest-wins）。options 重启时回灌。
        self._token = token
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._clients: set = set()
        self._listener: Optional[Callable[[str, str], None]] = None
        self._listener_managers: List[Any] = []
        self._stopping = False

    # ---------- 生命周期 ----------

    async def async_start(self) -> None:
        """绑定 TCP 并启动。失败抛异常（由 ensure 侧捕获记日志）。"""
        app = web.Application()
        app.router.add_get(WS_GATEWAY_PATH, self._handle_ws)
        runner = web.AppRunner(app, handle_signals=False)
        await runner.setup()
        try:
            site = web.TCPSite(runner, self.host, self.port)
            await site.start()
        except OSError:
            await runner.cleanup()
            raise
        self._app = app
        self._runner = runner
        _LOGGER.warning(
            "小程序 WS 网关已启动: ws://%s:%d%s（局域网直连，令牌%s）",
            self.host, self.port, WS_GATEWAY_PATH,
            "已启用" if self._token else "未启用=无认证",
        )

    async def async_stop(self) -> None:
        """注销设备监听、踢下全部客户端并释放端口（幂等）。"""
        if self._stopping:
            return
        self._stopping = True
        self._detach_listeners()
        clients = list(self._clients)
        for ws in clients:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001 - 关闭尽力而为
                pass
        self._clients.clear()
        if self._runner is not None:
            try:
                await self._runner.cleanup()
            except Exception as e:  # noqa: BLE001
                _LOGGER.debug("WS 网关 runner cleanup 异常: %s", e)
            self._runner = None
        _LOGGER.info("小程序 WS 网关已停止")

    def _attach_listeners(self, managers: List[Any]) -> None:
        """把 device_update 推送监听挂到全部网关的 device_manager。"""
        self._detach_listeners()
        self._listener = self._on_device_status
        for dm in managers:
            try:
                dm.add_status_listener(self._listener)
                self._listener_managers.append(dm)
            except Exception as e:  # noqa: BLE001
                _LOGGER.error("挂载设备状态监听失败: %s", e)

    def _detach_listeners(self) -> None:
        if self._listener is None:
            return
        for dm in self._listener_managers:
            try:
                dm.remove_status_listener(self._listener)
            except Exception as e:  # noqa: BLE001
                _LOGGER.debug("摘除设备状态监听失败: %s", e)
        self._listener_managers = []
        self._listener = None

    # ---------- 运行期数据视图（实时遍历，不缓存引用） ----------

    def _entries_data(self) -> List[Tuple[str, Dict[str, Any]]]:
        """全部已完成设置网关的 (gateway_sn, entry_data) 快照。"""
        out: List[Tuple[str, Dict[str, Any]]] = []
        domain_data = self.hass.data.get(DOMAIN, {})
        for entry_id, data in domain_data.items():
            if not isinstance(entry_id, str) or not isinstance(data, dict):
                continue
            if not data.get("_setup_complete"):
                continue
            gw = data.get("gateway_sn")
            handler = data.get("mqtt_handler")
            manager = data.get("device_manager")
            if gw and handler is not None and manager is not None:
                out.append((gw, data))
        return out

    def _find_entry(self, gateway_sn: str) -> Optional[Dict[str, Any]]:
        want = (gateway_sn or "").lower()
        for gw, data in self._entries_data():
            if gw.lower() == want:
                return data
        return None

    def _device_gateway(self, device_sn: str) -> Optional[Dict[str, Any]]:
        """设备→网关路由：先查全局映射表（忽略大小写），再查各网关缓存。"""
        mapping = self.hass.data.get(DOMAIN, {}).get(DEVICE_TO_GATEWAY_MAPPING, {})
        mapped = None
        for dev_key, gw_key in mapping.items():
            if str(dev_key).lower() == device_sn.lower():
                mapped = gw_key
                break
        if mapped:
            data = self._find_entry(str(mapped))
            if data is not None:
                return data
        for _gw, data in self._entries_data():
            if device_sn in data["device_manager"].devices:
                return data
        return None

    def _gateway_list_payload(self) -> Dict[str, Any]:
        gateways = [
            {"sn": gw, "online": bool(data["mqtt_handler"].connected)}
            for gw, data in self._entries_data()
        ]
        return {"type": "gateway_list", "gateways": gateways}

    def _device_list_payload(self) -> Dict[str, Any]:
        devices: List[Dict[str, Any]] = []
        for gw, data in self._entries_data():
            manager = data["device_manager"]
            for dev_sn, dev in manager.devices.items():
                devices.append(device_ws_view(dev_sn, gw, dev))
        return {"type": "device_list", "devices": devices}

    # ---------- 命令分发（纯 JSON 进出，便于单测直接驱动） ----------

    async def handle_json_message(self, text: str) -> Optional[Dict[str, Any]]:
        """处理一条入站 JSON 文本，返回应回发的 dict（None = 静默）。"""
        try:
            msg = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {"type": "error", "msg": "missing cmd"}
        if not isinstance(msg, dict):
            return {"type": "error", "msg": "missing cmd"}
        cmd = msg.get("cmd")
        if not isinstance(cmd, str) or not cmd:
            return {"type": "error", "msg": "missing cmd"}
        if cmd == "get_gateways":
            return self._gateway_list_payload()
        if cmd == "get_devices":
            return self._device_list_payload()
        if cmd == "control":
            return await self._cmd_control(msg)
        if cmd == "pair":
            return await self._cmd_pair(msg)
        if cmd == "unbind":
            return await self._cmd_unbind(msg)
        if cmd == "ping":
            return {"type": "pong"}
        if cmd == "set_token":
            return await self._cmd_set_token(msg)
        return {"type": "error", "msg": f"unknown command: {cmd}"}

    async def _cmd_control(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """固件 control：四字段（gwSn/devSn/attribute/value）均须非空，
        value 一律转字符串透传 004；路由 = 设备映射网关，缺失时广播到
        全部在线网关（send_004_command_all_gateways 定式）。
        """
        gw_sn = msg.get("gwSn")
        dev_sn = msg.get("devSn")
        attribute = msg.get("attribute")
        value = msg.get("value")
        if not all(isinstance(x, str) and x for x in (gw_sn, dev_sn, attribute)) or value is None:
            return {"type": "control_ack", "ok": False, "msg": "missing fields"}
        value_s = str(value)
        data = self._device_gateway(dev_sn)
        if data is not None:
            ok = await data["mqtt_handler"].send_ws_raw_004(dev_sn, attribute, value_s)
            return {"type": "control_ack", "ok": bool(ok), "msg": "ok" if ok else "send failed"}
        # 映射缺失 → 广播到所有在线网关；无在线网关时固件仍返回 ESP_OK
        # （设备后续上线自然收敛），保持一致：不回失败假象。
        publish_failed = False
        for _gw, edata in self._entries_data():
            handler = edata["mqtt_handler"]
            if not handler.connected:
                continue
            if not await handler.send_ws_raw_004(dev_sn, attribute, value_s):
                publish_failed = True
        if publish_failed:
            return {"type": "control_ack", "ok": False, "msg": "send failed"}
        return {"type": "control_ack", "ok": True, "msg": "ok"}

    async def _cmd_pair(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """固件 pair：gwSn 指定时须已注册且在线（L5/M6 如实 ack）；
        不带 gwSn 广播给全部已注册网关后恒 ok。"""
        gw_sn = msg.get("gwSn")
        if isinstance(gw_sn, str) and gw_sn:
            data = self._find_entry(gw_sn)
            handler = data["mqtt_handler"] if data else None
            if handler is None or not handler.connected:
                return {"type": "pair_ack", "ok": False,
                        "msg": "gateway offline or not registered"}
            ok = await handler.send_command(handler.gateway_sn, "start_pairing")
            if ok:
                return {"type": "pair_ack", "ok": True}
            return {"type": "pair_ack", "ok": False,
                    "msg": "gateway offline or not registered"}
        for _gw, edata in self._entries_data():
            handler = edata["mqtt_handler"]
            try:
                await handler.send_command(handler.gateway_sn, "start_pairing")
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("pair 广播下发失败（gw=%s）: %s", _gw, e)
        return {"type": "pair_ack", "ok": True}

    async def _cmd_unbind(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """固件 unbind：gwSn+devSn 必填；网关须已注册且在线、设备须在该
        网关缓存（M6/L3 如实 ack）；下发复用集成既有 003 bind=0 链。"""
        gw_sn = msg.get("gwSn")
        dev_sn = msg.get("devSn")
        if not (isinstance(gw_sn, str) and gw_sn and isinstance(dev_sn, str) and dev_sn):
            return {"type": "unbind_ack", "ok": False, "msg": "missing gwSn or devSn"}
        data = self._find_entry(gw_sn)
        handler = data["mqtt_handler"] if data else None
        manager = data["device_manager"] if data else None
        known = bool(manager is not None and dev_sn in manager.devices)
        if handler is None or not handler.connected or not known:
            return {"type": "unbind_ack", "ok": False, "msg": "gateway offline or device unknown"}
        await handler.unbind_device(dev_sn)
        return {"type": "unbind_ack", "ok": True}

    async def _cmd_set_token(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """固件 set_token：校验链 1:1；成功后内存即时生效 + 异步持久化
        到主控 entry options（reload 生效，当前连接保持）。"""
        err = validate_new_token(msg.get("newToken"), msg.get("oldToken"), self._token)
        if err:
            _LOGGER.warning("set_token 被拒绝: %s", err)
            return {"type": "set_token_ack", "ok": False, "msg": err}
        new_token = msg["newToken"]
        auth_was_active = bool(self._token)
        self._token = new_token
        if not auth_was_active:
            _LOGGER.warning("WS 网关令牌从未启用状态被引导开启（固件 B16 bootstrap 同款）")
        self.hass.async_create_task(self._persist_token(new_token))
        return {"type": "set_token_ack", "ok": True, "msg": "token updated"}

    async def _persist_token(self, new_token: str) -> None:
        """把新令牌写入主控 entry options；写失败仅告警（内存已生效，
        重启后回退 options 旧值——固件 NVS 写失败的等价语义）。"""
        try:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                options = dict(entry.options or {})
                if options.get(CONF_WS_GATEWAY_ENABLED, DEFAULT_WS_GATEWAY_ENABLED):
                    if options.get(CONF_WS_GATEWAY_TOKEN, DEFAULT_WS_GATEWAY_TOKEN) == new_token:
                        return
                    options[CONF_WS_GATEWAY_TOKEN] = new_token
                    self.hass.config_entries.async_update_entry(entry, options=options)
                    _LOGGER.info("WS 网关令牌已持久化到集成选项（条目 %s）", entry.entry_id)
                    return
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("WS 令牌持久化到 options 失败（重启后将回退）: %s", e)

    # ---------- 主动推送 ----------

    def _on_device_status(self, gateway_sn: str, device_sn: str) -> None:
        """device_manager 状态监听器（同步、事件循环内被调）。"""
        if self._stopping or not self._clients:
            return
        payload = self._device_update_payload(gateway_sn, device_sn)
        if payload is None:
            return
        self.hass.async_create_task(self._broadcast(payload))

    def _device_update_payload(self, gateway_sn: str, device_sn: str) -> Optional[Dict[str, Any]]:
        data = self._find_entry(gateway_sn)
        if data is None:
            return None
        dev = data["device_manager"].devices.get(device_sn)
        if dev is None:
            return None
        view = device_ws_view(device_sn, gateway_sn, dev)
        # 固件 device_update 模板（main.cpp:252）七键：type/gwSn/devSn/
        # position/battery/state/windLockMode——注意设备键是 devSn 而非
        # device_list 的 sn，小程序两处的取值代码不同，拼错即静默丢更新
        return {
            "type": "device_update",
            "gwSn": view["gwSn"],
            "devSn": device_sn,
            "position": view["position"],
            "battery": view["battery"],
            "state": view["state"],
            "windLockMode": _as_int((dev.get("attributes") or {}).get("wind_lock_mode")),
        }

    async def _broadcast(self, payload: Dict[str, Any]) -> None:
        dead = []
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        for ws in list(self._clients):
            try:
                await ws.send_str(text)
            except Exception:  # noqa: BLE001 - 发送失败按断连处理
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    # ---------- aiohttp 连接处理 ----------

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        header = request.headers.get("Sec-WebSocket-Protocol")
        if not handshake_token_ok(header, self._token):
            # 固件语义：拒绝握手（不返回 101）。aiohttp 层用 401 显式表达。
            _LOGGER.warning("WS 握手令牌校验失败，拒绝连接（来源 %s）",
                            request.remote)
            return web.Response(status=401, text="unauthorized")
        if len(self._clients) >= WS_MAX_CLIENTS:
            _LOGGER.warning("WS 连接数已满（%d），拒绝新连接", WS_MAX_CLIENTS)
            return web.Response(status=503, text="busy")
        # 认证成功才占槽（固件 M4 定式）：protocols 传入选中的令牌，
        # 使 101 回显 Sec-WebSocket-Protocol（对齐 esp_http_server 行为）
        protocols = {self._token} if self._token else None
        ws = web.WebSocketResponse(
            protocols=protocols,
            autoclose=True,
            heartbeat=None,
        )
        try:
            await ws.prepare(request)
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("WS 握手完成失败: %s", e)
            return ws
        self._clients.add(ws)
        _LOGGER.info("小程序 WS 已连接（来源 %s，在线 %d/%d）",
                     request.remote, len(self._clients), WS_MAX_CLIENTS)
        try:
            await self._session(ws)
        finally:
            self._clients.discard(ws)
            if not ws.closed:
                try:
                    await ws.close()
                except Exception:  # noqa: BLE001
                    pass
            _LOGGER.info("小程序 WS 断开（在线 %d/%d）", len(self._clients), WS_MAX_CLIENTS)
        return ws

    async def _session(self, ws: web.WebSocketResponse) -> None:
        """读取循环：固件 recv_wait_timeout=300s 同款空闲超时（小程序
        60s get_gateways 心跳足以保活）。"""
        while not ws.closed:
            try:
                msg = await asyncio.wait_for(
                    ws.receive(), timeout=WS_RECV_TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                _LOGGER.info("WS 空闲超 %ds，断开连接", WS_RECV_TIMEOUT_SECONDS)
                return
            if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED,
                            WSMsgType.ERROR):
                return
            if msg.type == WSMsgType.TEXT:
                if len(msg.data.encode("utf-8", errors="replace")) > WS_MAX_FRAME_BYTES:
                    try:
                        await ws.send_str(
                            json.dumps({"type": "error", "msg": "command too long"})
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    return
                if not msg.data:
                    continue  # 空帧：固件忽略
                try:
                    resp = await self.handle_json_message(msg.data)
                except Exception as e:  # noqa: BLE001 - 单条命令异常不断会话
                    _LOGGER.error("WS 命令处理异常: %s", e, exc_info=True)
                    continue
                if resp is not None:
                    try:
                        await ws.send_str(
                            json.dumps(resp, ensure_ascii=False, separators=(",", ":"))
                        )
                    except Exception:  # noqa: BLE001
                        return
            # BINARY/PING/PONG：固件非文本帧消费丢弃（PING 由 aiohttp 自动 PONG），
            # 循环自然继续


# ==================== 生命周期入口（__init__.py 调用） ====================

def ws_gateway_wanted(hass: HomeAssistant) -> Optional[Tuple[int, str]]:
    """聚合各 entry options：返回 (port, token)——取第一个开启 WS 的
    entry 的配置；无任何 entry 开启 → None。"""
    for entry in hass.config_entries.async_entries(DOMAIN):
        options = entry.options or {}
        if not options.get(CONF_WS_GATEWAY_ENABLED, DEFAULT_WS_GATEWAY_ENABLED):
            continue
        raw_port = options.get(CONF_WS_GATEWAY_PORT, DEFAULT_WS_GATEWAY_PORT)
        try:
            port = int(raw_port)
            if port < 1024 or port > 65535:
                raise ValueError
        except (ValueError, TypeError):
            port = DEFAULT_WS_GATEWAY_PORT
        token = options.get(CONF_WS_GATEWAY_TOKEN, DEFAULT_WS_GATEWAY_TOKEN)
        if not isinstance(token, str):
            token = DEFAULT_WS_GATEWAY_TOKEN
        return port, token
    return None


async def async_ensure_ws_gateway(hass: HomeAssistant) -> None:
    """按当前 options 聚合结果，启动/重启/停止单例 WS 服务器。

    幂等：在任一 config entry setup/unload 尾部与 HA STOP 时调用。
    服务器启动失败（端口被占等）只记 error，不影响集成其余功能。
    """
    if DOMAIN not in hass.data:
        return
    domain_data = hass.data[DOMAIN]
    current: Optional[WsGatewayServer] = domain_data.get(WS_GATEWAY_DATA_KEY)
    wanted = ws_gateway_wanted(hass)

    if wanted is None:
        if current is not None:
            await current.async_stop()
            domain_data.pop(WS_GATEWAY_DATA_KEY, None)
        return

    port, token = wanted
    if current is not None and current.port == port and current._runner is not None:
        # 端口未变：仅热同步令牌（options 被 UI 改过）与监听器
        current._token = token
        current._attach_listeners([data["device_manager"] for _gw, data in current._entries_data()])
        return

    if current is not None:
        await current.async_stop()

    if domain_data.get(WS_GATEWAY_STOPPED_KEY):
        # HA 正在停止：STOP 后 entry 逐个 unload 也会调本函数，若无此
        # 闩锁会把刚停掉的服务器在关机过程中重新拉起
        return

    server = WsGatewayServer(hass, port=port, token=token)
    try:
        await server.async_start()
    except OSError as e:
        _LOGGER.error("小程序 WS 网关启动失败（端口 %d 被占用或无权限？不影响其余功能）: %s", port, e)
        domain_data.pop(WS_GATEWAY_DATA_KEY, None)
        return
    except Exception as e:  # noqa: BLE001
        _LOGGER.error("小程序 WS 网关启动异常（不影响其余功能）: %s", e, exc_info=True)
        return
    domain_data[WS_GATEWAY_DATA_KEY] = server
    server._attach_listeners([data["device_manager"] for _gw, data in server._entries_data()])

    from homeassistant.const import EVENT_HOMEASSISTANT_STOP

    async def _on_ha_stop(_event) -> None:
        await async_stop_ws_gateway(hass)

    try:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_ha_stop)
    except Exception as e:  # noqa: BLE001 - 无 bus 环境（测试桩）不应阻断服务器
        _LOGGER.debug("注册 WS 网关 STOP 监听失败: %s", e)


async def async_stop_ws_gateway(hass: HomeAssistant) -> None:
    """HA STOP 时强制停止并闩锁（幂等；闩锁后 ensure 不再重新拉起）。"""
    domain_data = hass.data.get(DOMAIN)
    if not isinstance(domain_data, dict):
        return
    domain_data[WS_GATEWAY_STOPPED_KEY] = True
    current = domain_data.get(WS_GATEWAY_DATA_KEY)
    if current is not None:
        await current.async_stop()
        domain_data.pop(WS_GATEWAY_DATA_KEY, None)
