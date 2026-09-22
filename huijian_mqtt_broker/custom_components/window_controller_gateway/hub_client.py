"""慧尖云 hub 出站客户端（P0）——加载项主动长连到慧尖云，供小程序远程控制。

方案背景（2026-09-22 定线）：小程序正式版只能连"已备案域名 + wss"，而客户 HA 都在
家里 NAT 后面；故方向反过来——**加载项出站长连**到慧尖在微信云托管的 hub，小程序经
`wx.cloud.callContainer`（免配服务器域名，已真栈验证）发命令、拉状态。

设计要点（逐条对齐本仓既有纪律与历史事故）：
· **出站 wss（aiohttp）+ 指数退避重连**，睡眠一律 30s 切片——照 mqtt_bootstrap 的
  "长睡烧 HA 停机预算"教训（:500-516）与"恒频重试给对端施压"教训（:481-494）。
· **实例身份本地持久化**（instanceId/secret）：重启复用、不重复注册；连不上再重新
  注册（此时换新绑定码，需用户重新扫一次）。
· **状态上行复用 device_manager 状态监听**，条目形状与 LAN WS 网关同源（由调用方注入
  ws_gateway.device_ws_view 构造），保证"小程序看到的字段"两条通道完全一致。
· **命令下行**：action='control' + params{attribute,value}，值校验与 LAN `_cmd_control`
  同口径（空串/bool/非 str-int-float/非法数值一律拒），执行走调用方注入的 control_fn
  （与 LAN 同一条 send_ws_raw_004 路径）。
· **凭据不回显**：日志只记 cred_brief（长度+首字节），绝不落 secret/bindCode 明文。

本模块**不 import HA**（只 aiohttp+标准库）——便于在 tests/conftest 的假 HA 树下直接测。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

import aiohttp

_LOGGER = logging.getLogger(__name__)

# 慧尖云 hub 默认端点（P0）。客户零配置：加载项内置默认值，慧尖换域名只改默认值或
# entry.options 覆盖（hub_base / hub_install_key）。
HUB_DEFAULT_BASE = "https://huijian-hub-318191-7-1412991472.sh.run.tcloudbase.com"
HUB_DEFAULT_INSTALL_KEY = "c019cee1ef3c68ceea68cfdbcc121b6f"

HUB_RECONNECT_BASE_S = 5.0
HUB_RECONNECT_MAX_S = 300.0
HUB_SLEEP_SLICE_S = 30.0          # 长睡切片（停机时最多 30s 内让出）
HUB_STATE_DEBOUNCE_S = 0.3        # 状态上行合并窗
HUB_KEEPALIVE_S = 300.0           # 保活重推：让 hub 侧 updatedAt 反映 agent 存活
BIND_CODE_TTL_S = 600             # 绑定码有效期（与 hub 侧 bindTtlMs 同口径；过期即作废）
BIND_CODE_RENEW_BEFORE_S = 120    # 剩余不足这么久就自动换新码（用户不必自己发现过期）
HUB_HTTP_TIMEOUT_S = 15.0
HUB_IDENTITY_FILE = "huijian_hub_identity.json"
# 长连握手被这些状态明确拒了＝"云端不认识本机身份"（hub 重新部署抹了注册表的主形态），
# 值得重注册；其余失败一律按网络问题处理，继续抱身份退避重试。
IDENTITY_REJECTED_HTTP = (401, 403)
# 连续多少次【被拒 - 重注册 - 再被拒】就熔断（不再自动重注册）。病态形态＝云托管多副本
# 且注册表不共享：register 落到 A、握手落到 B，每轮退避都会白造一个新实例。
HUB_REREGISTER_FUSE = 3

_VALUE_RE = re.compile(r"-?\d+(\.\d+)?")


def hub_reconnect_delay(attempt: int) -> float:
    """指数退避：5s×2^(n-1)，封顶 5min（防恒频重试给 hub 施压）。"""
    if attempt < 1:
        attempt = 1
    return min(HUB_RECONNECT_BASE_S * (2 ** (attempt - 1)), HUB_RECONNECT_MAX_S)


async def interruptible_sleep(seconds: float, is_stopping: Callable[[], bool]) -> None:
    """30s 切片睡眠：停机时最多 30s 内让出（对齐 mqtt_bootstrap 同款纪律）。"""
    remaining = max(0.0, float(seconds))
    while remaining > 0:
        if is_stopping():
            return
        await asyncio.sleep(min(HUB_SLEEP_SLICE_S, remaining))
        remaining -= HUB_SLEEP_SLICE_S


def _attr_int(dev: Any, key: str) -> int:
    """设备属性安全取整（-1=未知约定；bool/None/不可解析/非有限数一律 -1）。

    与 ws_gateway._as_int 同口径：`int(float('inf'))` 抛 OverflowError、
    JSON 里 `1e999` 就能造出 inf，故必须把 OverflowError 一起接住。
    """
    raw = (dev or {}).get("attributes") if isinstance(dev, dict) else None
    value = (raw or {}).get(key) if isinstance(raw, dict) else None
    if value is None or isinstance(value, bool):
        return -1
    try:
        return int(value)
    except (ValueError, TypeError, OverflowError):
        return -1


def cred_brief(value: Any) -> str:
    """凭据摘要：只回长度+首字节（日志/视图都不回显明文）。"""
    if not value:
        return "(空)"
    s = str(value)
    return "len=%d head=%s" % (len(s), s[:2])


def identity_path(config_dir: str) -> str:
    return os.path.join(config_dir, HUB_IDENTITY_FILE)


def load_identity(config_dir: str) -> Dict[str, Any]:
    """读实例身份；无/损坏一律回空 dict（损坏时改名留证，不静默丢状态）。"""
    path = identity_path(config_dir)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        return {}
    except Exception as e:  # noqa: BLE001 - 任何读取异常都不该拖垮集成
        _LOGGER.warning("hub 身份文件读取失败（%s），按未注册处理", type(e).__name__)
        try:
            os.replace(path, path + ".bad")
        except Exception:  # noqa: BLE001
            pass
    return {}


def save_identity(config_dir: str, data: Dict[str, Any]) -> None:
    """原子写实例身份（tmp+replace），避免断电留半截文件。"""
    path = identity_path(config_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, path)


def validate_control_params(attribute: Any, value: Any) -> Optional[str]:
    """命令参数校验——与 LAN `_cmd_control` 同口径。

    返回规范化后的 value 字符串；不合法返回 None：
    空串/bool 拒（固件把空串按缺失字段拒、bool 经 str() 是 'True'/'False' 不可解析）；
    仅 str/int/float 可转线值（dict/list 经 str() 出 Python repr，固件不可解析，
    而调用方已收到假成功——v1.7.12 F6）；数值形态再过十进制格式校验
    （inf/nan/1e999 等 str() 出设备不可解析字面量——v1.7.18 BUG-16）。
    """
    if not isinstance(attribute, str) or not attribute:
        return None
    if value is None or value == "" or isinstance(value, bool):
        return None
    if not isinstance(value, (str, int, float)):
        return None
    value_s = str(value)
    if not isinstance(value, str) and not _VALUE_RE.fullmatch(value_s):
        return None
    return value_s


class HubClient:
    """出站长连客户端（一 entry 一实例；由 __init__.py 的 _bg_tasks 拉起与取消）。"""

    def __init__(
        self,
        device_manager: Any,
        *,
        config_dir: str,
        base: str = HUB_DEFAULT_BASE,
        install_key: str = HUB_DEFAULT_INSTALL_KEY,
        control_fn: Optional[Callable[[str, str, str], Awaitable[bool]]] = None,
        view_builder: Optional[Callable[[str, str, Dict[str, Any]], Dict[str, Any]]] = None,
        session: Optional[aiohttp.ClientSession] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.device_manager = device_manager
        self.config_dir = config_dir
        self.base = (base or HUB_DEFAULT_BASE).rstrip("/")
        self.install_key = install_key or HUB_DEFAULT_INSTALL_KEY
        self.control_fn = control_fn
        self.view_builder = view_builder
        self._session = session
        self._own_session = session is None
        self._logger = logger or _LOGGER

        self.instance_id: Optional[str] = None
        self._secret: Optional[str] = None
        self.bind_code: Optional[str] = None
        self._bind_code_at: float = 0.0      # 当前码的签发时刻（epoch 秒；0=未知）
        self._rereg_streak: int = 0        # 连续【被拒 - 重注册】计数（见 HUB_REREGISTER_FUSE）
        self.connected = False
        self.last_error: Optional[str] = None

        self._task: Optional[asyncio.Task] = None
        self._stopping = False           # 停机闩锁（照 _lifecycle._closing 纪律）
        self._state_dirty = asyncio.Event()
        self._send_lock: Optional[asyncio.Lock] = None

    # ── 生命周期 ──────────────────────────────────────────────────
    async def async_start(self) -> None:
        """在运行中的事件循环里拉起（HA setup 路径；测试用 asyncio.run 驱动）。"""
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._send_lock = asyncio.Lock()
        self._load_identity()
        try:
            self.device_manager.add_status_listener(self._on_device_status)
        except Exception as e:  # noqa: BLE001
            self._logger.warning("hub 状态监听注册失败：%s", type(e).__name__)
        self._task = asyncio.ensure_future(self._run_forever())

    async def async_stop(self) -> None:
        self._stopping = True
        try:
            self.device_manager.remove_status_listener(self._on_device_status)
        except Exception:  # noqa: BLE001
            pass
        task, self._task = self._task, None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._own_session and self._session is not None:
            try:
                await self._session.close()
            except Exception:  # noqa: BLE001
                pass
        self._session = None
        self.connected = False

    # ── 连接主循环 ────────────────────────────────────────────────
    async def _run_forever(self) -> None:
        attempt = 0
        while not self._stopping:
            try:
                if await self._session_once():
                    attempt = 0
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - 任何异常都只降级重连
                self.last_error = type(e).__name__
                self._logger.warning("hub 连接异常（%s），准备重连", type(e).__name__)
            finally:
                self.connected = False
            if self._stopping:
                return
            attempt += 1
            delay = hub_reconnect_delay(attempt)
            self._logger.info("hub 重连退避 %.0fs（第 %d 次）", delay, attempt)
            await interruptible_sleep(delay, lambda: self._stopping)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=HUB_HTTP_TIMEOUT_S)
            self._session = aiohttp.ClientSession(timeout=timeout)
            self._own_session = True
        return self._session

    async def _http(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        session = await self._ensure_session()
        async with session.post(self.base + path, json=payload) as resp:
            if resp.status != 200:
                raise RuntimeError("hub %s -> %d" % (path, resp.status))
            return await resp.json()

    def _load_identity(self) -> None:
        """读本地身份（重启复用；文件缺失/损坏按未注册处理）。"""
        ident = load_identity(self.config_dir)
        self.instance_id = ident.get("instanceId") or None
        self._secret = ident.get("secret") or None
        self.bind_code = self.bind_code or ident.get("bindCode") or None
        if not self._bind_code_at:
            try:
                self._bind_code_at = float(ident.get("bindCodeAt") or 0)
            except (TypeError, ValueError):
                self._bind_code_at = 0.0

    async def _ensure_registered(self) -> None:
        """有身份则直接连；无身份（或上次被拒）则注册一次拿 instanceId/secret/绑定码。"""
        if self.instance_id is None:
            self._load_identity()
        if self.instance_id and self._secret:
            return
        sn = ""
        try:
            sn = getattr(self.device_manager, "gateway_sn", "") or ""
        except Exception:  # noqa: BLE001
            sn = ""
        data = await self._http("/agent/register", {
            "installKey": self.install_key,
            "sn": sn,
            "fw": "huijian-gateway-plugin/hub-p0",
        })
        if not data.get("ok"):
            raise RuntimeError("register rejected: %s" % data.get("err"))
        self.instance_id = data["instanceId"]
        self._secret = data["secret"]
        self.bind_code = data.get("bindCode")
        self._bind_code_at = time.time()
        self._save_identity()
        # 绑定码要让用户看得到，但日志只记摘要（凭据不回显纪律）
        self._logger.info("hub 注册成功 instance=%s 绑定码=%s（请在插件页查看完整码）",
                          self.instance_id, cred_brief(self.bind_code))

    def _save_identity(self) -> None:
        """落盘实例身份（含绑定码签发时刻——否则重启后无从判断码是否已过期）。"""
        save_identity(self.config_dir, {
            "instanceId": self.instance_id,
            "secret": self._secret,
            "bindCode": self.bind_code,
            "bindCodeAt": round(self._bind_code_at, 3),
        })

    def bind_code_expires_in(self) -> int:
        """当前绑定码剩余秒数（负数=已过期；0 是签发时刻未知＝按过期处理）。"""
        if not self.bind_code or not self._bind_code_at:
            return -1
        return int(BIND_CODE_TTL_S - (time.time() - self._bind_code_at))

    async def refresh_bind_code(self) -> bool:
        """向 hub 换一个新绑定码（旧码当场作废）。

        面板"点二维码/刷新"与自动补发都走这里。失败只记日志回 False——绑定码拿不到
        不影响本地控制与云通道本身。
        """
        if not (self.instance_id and self._secret):
            self._load_identity()
        if not (self.instance_id and self._secret):
            return False
        try:
            data = await self._http("/agent/bindcode", {
                "instanceId": self.instance_id,
                "secret": self._secret,
            })
        except Exception as e:  # noqa: BLE001 - 网络/旧 hub 无此端点都只降级
            self._logger.warning("hub 换绑定码失败（%s）", type(e).__name__)
            return False
        if not data.get("ok") or not data.get("bindCode"):
            self._logger.warning("hub 换绑定码被拒：%s", data.get("err"))
            return False
        self.bind_code = data["bindCode"]
        self._bind_code_at = time.time()
        self._save_identity()
        self._logger.info("hub 绑定码已更新（%s）", cred_brief(self.bind_code))
        return True

    async def _renew_bind_code_if_stale(self) -> None:
        """快到期/已过期就自动换新码——面板上显示的码因此始终可用。"""
        if self.bind_code_expires_in() >= BIND_CODE_RENEW_BEFORE_S:
            return
        if await self.refresh_bind_code():
            self._logger.info("绑定码自动补发完成（原码已作废，请以面板显示为准）")
        else:
            self._logger.warning("绑定码已过期且自动补发失败——面板点一下二维码可重试")

    def _ws_url(self) -> str:
        base = self.base
        if base.startswith("https://"):
            base = "wss://" + base[len("https://"):]
        elif base.startswith("http://"):
            base = "ws://" + base[len("http://"):]
        return "%s/agent/ws?instanceId=%s&secret=%s" % (base, self.instance_id, self._secret)

    async def _open_ws(self, session: aiohttp.ClientSession):
        """建长连；云端明确"不认识这个身份"时当场重注册再连一次（只补一次）。

        为什么必须显式判 HTTP 状态：hub 抹掉注册表（云托管重新部署 ⇒ /data 是容器本地盘）
        后，本机身份对它而言就是陌生凭据。旧版 hub 是裸 destroy，客户端只能看到
        ServerDisconnectedError＝与"网络抖一下"同形 ⇒ 抱着死身份无限退避重连，
        面板显示的码是当前 hub 从未签发过的，小程序侧必然 code_invalid 且永不自愈。
        现在 hub 被拒时回 401（见 huijian-cloud-hub src/server.js），据此才敢重注册：
        **网络层失败一律不清身份**，否则每次抖动都多发一次 register、把用户手上的活码换掉。
        """
        try:
            return await session.ws_connect(self._ws_url(), heartbeat=25.0)
        except aiohttp.WSServerHandshakeError as e:
            if e.status not in IDENTITY_REJECTED_HTTP:
                raise
            if self._rereg_streak >= HUB_REREGISTER_FUSE:
                # 连续被拒不是"hub 忘了我"这一件事，而是每次 register 落到另一个容器：
                # 云托管多副本且注册表不共享（没配存储挂载）时正是这个形态。继续重注册只会
                # 无限造孤儿实例 + 反复作废用户手上的绑定码 ⇒ 停在熔断上，把根因写给运维。
                self.last_error = "identity_rejected_loop"
                self._logger.error(
                    "hub 连续 %d 次拒本机身份，已停止自动重注册。根因几乎总是云端注册表不共享："
                    "①确认云托管「存储挂载」已挂到 /mnt（否则每次部署即抹）；"
                    "②确认服务实例数固定为 1（/cmd 按容器内存里的长连表转发，多副本必然随机 offline）",
                    self._rereg_streak)
                raise
            self._invalidate_identity("云端拒绝身份（HTTP %s）" % e.status)
            await self._ensure_registered()
            return await session.ws_connect(self._ws_url(), heartbeat=25.0)

    def _invalidate_identity(self, reason: str) -> None:
        """清空本地身份并落盘：下次连接必然重新注册（换新 instanceId + 新绑定码）。

        代价要说清：注册表没了意味着**绑定关系也没了**，各微信号都要重新扫一次码——
        这一步不能替用户偷偷完成，所以只记 WARNING 指路，不假装什么都没发生。
        """
        self.instance_id = None
        self._secret = None
        self.bind_code = None
        self._bind_code_at = 0.0
        self._save_identity()
        self._rereg_streak += 1
        self.last_error = "identity_rejected"
        self._logger.warning(
            "hub 身份失效（%s）：已清空本地身份并将重新注册，绑定码随之换发——"
            "云端注册表重置会同时丢掉绑定关系，请在小程序重新绑定一次", reason)

    async def _session_once(self) -> bool:
        """建一次长连，收消息直到断开；返回 True 表示"干净断开可立即重连"。"""
        await self._ensure_registered()
        session = await self._ensure_session()
        self._logger.info("hub 连接中：%s（凭据 %s）", self.base, cred_brief(self.instance_id))
        async with await self._open_ws(session) as ws:
            self.connected = True
            self.last_error = None
            self._rereg_streak = 0        # 连上过＝云端确实认识当前身份，熔断计数归零
            self._logger.info("hub 已连接（instance=%s）", self.instance_id)
            self._state_dirty.set()          # 上线先全量推一次
            await self._renew_bind_code_if_stale()   # 上线自检：过期码当场换新
            flush = asyncio.ensure_future(self._flush_loop(ws))
            keepalive = asyncio.ensure_future(self._keepalive_loop())
            try:
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    try:
                        data = json.loads(msg.data)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(data, dict) or data.get("t") != "cmd":
                        continue
                    result = await self._handle_cmd(data)
                    await ws.send_json({
                        "t": "cmd_result",
                        "cmdsn": data.get("cmdsn"),
                        "ok": bool(result.get("ok")),
                        "data": result.get("data"),
                        "err": result.get("err"),
                    })
            finally:
                for task in (flush, keepalive):
                    task.cancel()
                await asyncio.gather(flush, keepalive, return_exceptions=True)
        return True

    async def _keepalive_loop(self) -> None:
        """周期标脏重推：状态长时间不变时也要刷新 hub 侧 updatedAt。

        否则"设备一直没人动"与"agent 已死"在云端是同一种形态（updatedAt 越来越旧），
        小程序侧无法区分。睡眠按 30s 切片（停机时最多 30s 内让出）。
        """
        while not self._stopping:
            await interruptible_sleep(HUB_KEEPALIVE_S, lambda: self._stopping)
            if self._stopping:
                return
            await self._renew_bind_code_if_stale()
            self._state_dirty.set()

    # ── 状态上行 ──────────────────────────────────────────────────
    def _on_device_status(self, gateway_sn: str, device_sn: str) -> None:  # noqa: ARG002
        """device_manager 状态监听（同步回调）→ 只标脏 + 唤醒上行协程。"""
        if self._stopping:
            return
        if self._state_dirty is not None:
            self._state_dirty.set()

    def collect_state_items(self) -> List[Dict[str, Any]]:
        """按 LAN 同源视图构造状态条目（跟小程序 LAN 通道看到的字段一字不差）。"""
        items: List[Dict[str, Any]] = []
        manager = self.device_manager
        try:
            devices = getattr(manager, "devices", {}) or {}
            gateway_sn = getattr(manager, "gateway_sn", "") or ""
        except Exception:  # noqa: BLE001
            return items
        builder = self.view_builder
        if builder is None:
            try:  # 懒 import：模块本体不依赖 HA，注入缺省时才碰 ws_gateway
                from .ws_gateway import device_ws_view as builder  # type: ignore
            except Exception:  # noqa: BLE001
                return items
        for dev_sn, dev in list(devices.items()):
            try:
                view = builder(dev_sn, gateway_sn, dev or {})
            except Exception:  # noqa: BLE001
                continue
            if isinstance(view, dict) and view.get("sn"):
                # 云通道没有 LAN 那路 device_update 实时推送，锁定模式只能靠
                # 状态上行带过去——device_ws_view 是 device_list 项视图（不含它），
                # 这里补上与 LAN `_device_update_payload` 同源的字段。
                view["windLockMode"] = _attr_int(dev, "wind_lock_mode")
                items.append(view)
        return items

    async def _flush_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        while not self._stopping:
            await self._state_dirty.wait()
            self._state_dirty.clear()
            await asyncio.sleep(HUB_STATE_DEBOUNCE_S)
            items = self.collect_state_items()
            if not items:
                continue
            try:
                await ws.send_json({"t": "state", "items": items})
            except Exception as e:  # noqa: BLE001 - 发送失败交给外层重连
                self._logger.debug("hub 状态上行失败：%s", type(e).__name__)
                return

    # ── 命令下行 ──────────────────────────────────────────────────
    async def _handle_cmd(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        if msg.get("action") != "control":
            return {"ok": False, "err": "unknown_action"}
        dev_sn = msg.get("sn")
        params = msg.get("params") or {}
        value_s = validate_control_params(params.get("attribute"), params.get("value"))
        if not isinstance(dev_sn, str) or not dev_sn or value_s is None:
            return {"ok": False, "err": "invalid_params"}
        if self.control_fn is None:
            return {"ok": False, "err": "control_unavailable"}
        try:
            ok = await self.control_fn(dev_sn, params["attribute"], value_s)
        except Exception as e:  # noqa: BLE001
            self._logger.warning("hub 命令执行异常：%s", type(e).__name__)
            return {"ok": False, "err": "control_failed"}
        # 语义与 LAN 一致：ok = 004 已发布到 broker（设备是否执行靠状态上报）
        return {"ok": bool(ok), "data": {"published": bool(ok)}}

    # ── 视图（供插件页展示）──────────────────────────────────────
    def status_view(self) -> Dict[str, Any]:
        """给插件页/排障用：**不回显 secret**；绑定码本就是给用户看的，可回显。"""
        gateway_sn = ""
        try:
            gateway_sn = getattr(self.device_manager, "gateway_sn", "") or ""
        except Exception:  # noqa: BLE001 - 视图绝不因取 SN 抛错
            gateway_sn = ""
        expires_in = self.bind_code_expires_in()
        return {
            "connected": bool(self.connected),
            "instanceId": self.instance_id,
            "bindCode": self.bind_code,
            "bindCodeExpiresIn": expires_in,
            "bindCodeExpired": bool(self.bind_code) and expires_in <= 0,
            "gatewaySn": gateway_sn,
            "hub": self.base,
            "lastError": self.last_error,
        }
