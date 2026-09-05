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

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def async_setup_api(hass: HomeAssistant) -> None:
    """Register the device-list REST view."""
    hass.http.register_view(WindowGatewayDevicesView())
    hass.http.register_view(WindowGatewaySecurityView())


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
        for entity_entry in entity_registry.entities.values():
            did = entity_entry.device_id
            if not did:
                continue
            entities_by_device.setdefault(did, []).append({
                "entity_id": entity_entry.entity_id,
                "domain": entity_entry.domain,
                "unique_id": entity_entry.unique_id,
            })

        all_devices = []
        for device in registry.devices.values():
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
