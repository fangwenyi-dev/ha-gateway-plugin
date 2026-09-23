"""REST API bridge exposing the device registry to the add-on Web UI.

Home Assistant Core only exposes the device registry over WebSocket
(``config/device_registry/list``), not REST. The add-on Web UI (ingress) can
only use REST via the Supervisor proxy (``/api/ha/`` -> ``http://supervisor/core/api/``).
This view serializes the device registry from inside HA so the Web UI can list
gateway (parent) and child devices for a given config entry.
"""
from __future__ import annotations

import logging

from homeassistant.components import http
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, HUB_DATA_KEY
from .utils import iter_devices

_LOGGER = logging.getLogger(__name__)


def async_setup_api(hass: HomeAssistant) -> None:
    """Register the device-list REST view."""
    hass.http.register_view(WindowGatewayDevicesView())
    hass.http.register_view(WindowGatewaySecurityView())
    hass.http.register_view(WindowGatewayHubView())
    hass.http.register_view(WindowGatewayHubBindCodeView())


class WindowGatewaySecurityView(http.HomeAssistantView):
    """v1.6.21: 凭据健康只读视图——Web UI 用它提示"仍是默认小程序令牌"。

    默认 WS 令牌与小程序内置值同串（const.DEFAULT_WS_GATEWAY_TOKEN），
    知道 SN + 在内网即可连；提示改密是安全兜底，**绝不自动改**——
    自动轮换会造成小程序侧永久 401（令牌必须两侧同步是既定契约）。
    仅暴露布尔值，不回显任何令牌/密码明文。
    """

    url = "/api/window_controller_gateway/security"
    name = "api:window_controller_gateway:security"

    async def get(self, request):
        """任一网关注项仍是默认令牌 → true；无网关条目 → None（无从判定）。"""
        hass = request.app["hass"]
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            return self.json({"ws_token_is_default": None, "gateway_entries": 0})
        from .const import CONF_WS_GATEWAY_TOKEN, DEFAULT_WS_GATEWAY_TOKEN
        is_default = any(
            entry.options.get(CONF_WS_GATEWAY_TOKEN, DEFAULT_WS_GATEWAY_TOKEN)
            == DEFAULT_WS_GATEWAY_TOKEN
            for entry in entries
        )
        return self.json({"ws_token_is_default": is_default, "gateway_entries": len(entries)})


class WindowGatewayDevicesView(http.HomeAssistantView):
    """Return device registry devices (parent + via children) for a config entry."""

    url = "/api/window_controller_gateway/devices"
    name = "api:window_controller_gateway:devices"

    async def get(self, request):
        """Return devices belonging to the given config_entry_id (parent + via children).

        每个设备附带其下的精确实体列表（entity_id/domain/unique_id），
        供 Web UI 直接定位实体，避免用 SN 字符串模糊匹配 entity_id
        （设备显示名只含 SN 后 4 位，模糊匹配后 6 位永远失败——2026-08-28 实测）。
        """
        hass = request.app["hass"]
        registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)
        config_entry_id = request.query.get("config_entry_id")

        # 网关在线状态：直接读 mqtt_handler.connected —— 它由"收到网关上报"
        # 置 True（handle_gateway_response），网关超时置 False。语义即
        # "网关上报过 = 在线"，不依赖 binary_sensor 实体（实体可能未创建，
        # 且 v1.5.5 前 Web UI 因匹配失败一直显示"未知"——2026-08-28 实测）。
        gateway_online: bool | None = None
        if config_entry_id and DOMAIN in hass.data:
            entry_data = hass.data[DOMAIN].get(config_entry_id)
            if isinstance(entry_data, dict):
                mqtt_handler = entry_data.get("mqtt_handler")
                if mqtt_handler is not None:
                    gateway_online = bool(getattr(mqtt_handler, "connected", False))

        # 按 device_id 聚合实体（一次遍历完成，避免为每个设备再扫全表）
        entities_by_device: dict = {}
        for entity_entry in entity_registry.entities.values():  # EntityRegistry 无 async_entries（E2E 实锤），且 entities 未被弃用
            did = entity_entry.device_id
            if not did:
                continue
            entities_by_device.setdefault(did, []).append({
                "entity_id": entity_entry.entity_id,
                "domain": entity_entry.domain,
                "unique_id": entity_entry.unique_id,
            })

        all_devices = []
        for device in iter_devices(registry):  # v1.7.28：双形态兼容遍历（iter_devices 单一出口）
            # 兼容新旧 HA：config_entries (set) 取代旧版 config_entry_id (str)
            entry_ids = set()
            ce = getattr(device, "config_entries", None)
            if ce:
                entry_ids.update(ce)
            ce_id = getattr(device, "config_entry_id", None)
            if ce_id:
                entry_ids.add(ce_id)
            all_devices.append({
                "id": device.id,
                "name": device.name_by_user or device.name or "",
                "name_by_user": device.name_by_user,
                "via_device_id": getattr(device, "via_device_id", None),
                "identifiers": [[i[0], i[1]] for i in (device.identifiers or [])],
                "config_entries": list(entry_ids),
                "entities": entities_by_device.get(device.id, []),
                "gateway_online": gateway_online,
            })

        if not config_entry_id:
            # v1.7.12（第 6 轮审计 L-11）：缺参此前返回全设备注册表——本视图
            # 语义是"本集成的设备"，把他集成的设备/实体明细整体泄给 Web 调用
            # 面毫无必要。收紧为仅带本集成 identifiers 的设备（网关+其子设备），
            # 返回结构不变，对现有消费者零破坏。
            own = [d for d in all_devices
                   if any(i[0] == DOMAIN for i in d["identifiers"])]
            return self.json(own)

        parent_ids = {
            d["id"] for d in all_devices if config_entry_id in d["config_entries"]
        }
        result = [d for d in all_devices if d["id"] in parent_ids]
        for d in all_devices:
            vid = d.get("via_device_id")
            if vid and vid in parent_ids and d["id"] not in parent_ids:
                result.append(d)
        return self.json(result)


def _hub_client(hass):
    """取安装级 hub 单例（**不是**"遍历条目取第一个"——那正是只看到一台网关的根因）。"""
    domain_data = hass.data.get(DOMAIN)
    if not isinstance(domain_data, dict):
        return None
    return domain_data.get(HUB_DATA_KEY)


class WindowGatewayHubView(http.HomeAssistantView):
    """v0.1(P0): 慧尖云 hub 绑定状态只读视图——插件页展示"扫码绑定"用。

    只回 instanceId / 绑定码 / 连接状态；**绝不回显 secret**（hub 长连凭据）。
    绑定码本身就是给用户看的（扫一次完成"HA 实例 ↔ 微信账号"绑定），
    但日志侧只记摘要（见 hub_client.cred_brief）。
    """

    url = "/api/window_controller_gateway/hub"
    name = "api:window_controller_gateway:hub"

    async def get(self, request):
        """返回安装级 hub 的状态；没长连（无网关/未起）如实回 enabled=False。"""
        hass = request.app["hass"]
        client = _hub_client(hass)
        if client is None:
            return self.json({"enabled": False})
        view = client.status_view()
        view["enabled"] = True
        return self.json(view)


class WindowGatewayHubBindCodeView(http.HomeAssistantView):
    """v1.7.41: 换一个新绑定码（面板点二维码/刷新走这条）。

    为什么必须是 POST：hub 侧轮换会**当场作废旧码**（一次性语义不变），不能让
    "看一眼状态"这种读操作顺手把用户手抄到一半的码弄失效——只有用户显式点刷新才换。
    """

    url = "/api/window_controller_gateway/hub/bindcode"
    name = "api:window_controller_gateway:hub:bindcode"

    async def post(self, request):
        """换码并回新状态；集成里没有 hub 客户端（或换码失败）时如实回 refreshOk=False。"""
        hass = request.app["hass"]
        client = _hub_client(hass)
        if client is None:
            return self.json({"enabled": False, "refreshOk": False})
        ok = await client.refresh_bind_code()
        view = client.status_view()
        view["enabled"] = True
        view["refreshOk"] = bool(ok)
        return self.json(view)
