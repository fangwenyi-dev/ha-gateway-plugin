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

_LOGGER = logging.getLogger(__name__)


def async_setup_api(hass: HomeAssistant) -> None:
    """Register the device-list REST view."""
    hass.http.register_view(WindowGatewayDevicesView())


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
            })

        if not config_entry_id:
            return self.json(all_devices)

        parent_ids = {
            d["id"] for d in all_devices if config_entry_id in d["config_entries"]
        }
        result = [d for d in all_devices if d["id"] in parent_ids]
        for d in all_devices:
            vid = d.get("via_device_id")
            if vid and vid in parent_ids and d["id"] not in parent_ids:
                result.append(d)
        return self.json(result)
