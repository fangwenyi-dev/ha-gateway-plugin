"""开窗器网关Cover平台 - 供LLM等使用Cover语义控制开窗器"""
import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.components.cover import (
    CoverEntity,
    CoverEntityFeature,
    CoverDeviceClass,
)

from .base_entity import WindowControllerBaseEntity
from .const import (
    DOMAIN,
    CONF_GATEWAY_SN,
    DEVICE_TYPE_WINDOW_OPENER,
    MANUFACTURER,
    COMMAND_OPEN,
    COMMAND_CLOSE,
    COMMAND_STOP,
    DEVICE_STATUS_OPEN,
    DEVICE_STATUS_CLOSED,
    DEVICE_STATUS_UNKNOWN,
    DEVICE_STATUS_CONNECTED,
)

_LOGGER = logging.getLogger(__name__)


from .utils import get_entity_registry


class WindowControllerCover(WindowControllerBaseEntity, RestoreEntity, CoverEntity):
    """开窗器Cover实体 - 供LLM等使用Cover语义控制"""

    def __init__(
        self,
        hass: HomeAssistant,
        device_manager,
        mqtt_handler,
        gateway_sn: str,
        device_sn: str,
        device_name: str,
        entry_id: str = None
    ):
        """初始化开窗器Cover实体"""
        super().__init__(
            hass=hass,
            device_manager=device_manager,
            mqtt_handler=mqtt_handler,
            gateway_sn=gateway_sn,
            device_sn=device_sn,
            device_name=device_name
        )

        self._attr_unique_id = f"{gateway_sn}_{device_sn}_cover"
        self._attr_device_class = CoverDeviceClass.WINDOW
        self._attr_name = "开窗器"
        self._entry_id = entry_id
        self._attr_supported_features = (
            CoverEntityFeature.OPEN |
            CoverEntityFeature.CLOSE |
            CoverEntityFeature.STOP
        )
        # 始终可用，防止变灰
        self._attr_available = True
        self._last_state_update = None

    @property
    def device_info(self) -> DeviceInfo:
        """返回设备信息"""
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_sn)},
            name=self.device_name,
            manufacturer=MANUFACTURER,
            model="开窗器",
            serial_number=self.device_sn,
            sw_version="1.0"
        )

    @property
    def is_closed(self):
        """v1.6.8：由网关上报缓存推导真实开/闭。

        v1.0.1 起这里写死 return None（本意是防原生卡片按钮变灰），
        副作用是 HA 标准 state 计算（is_closed=None → state=None）
        使 cover.state **永远输出 unknown**——历史曲线、自动化触发条件、
        LLM 语义控制与 Web 管理面板状态行全部失效。现恢复真实语义：
        窗闭合时原生卡片「关」按钮置灰属 HA 正常行为；Web 面板按钮
        为自定义控件不受影响。current_cover_position 仍返回 None，
        避免位置 0/100 端点连带置灰。
        """
        device = self.device_manager.get_device(self.device_sn)
        if device:
            status = device.get("status")
            if status == DEVICE_STATUS_CLOSED:
                return True
            if status == DEVICE_STATUS_OPEN:
                return False
            # v1.6.8（用户定案：状态与位置同步——r_travel 0=关，>0=开）：
            # 005 只报位置不带 status 字段时，缓存 r_travel 已更新而 status
            # 仍是 unknown，按同一协议语义直接从位置推导，避免
            # 「待上报 + 位置 65%」这种自相矛盾的显示
            r_travel = (device.get("attributes") or {}).get("r_travel")
            try:
                if r_travel is not None:
                    return int(r_travel) <= 0
            except (ValueError, TypeError):
                pass
        return None

    async def async_added_to_hass(self):
        """启动时把上次重启前的开/关状态与位置回填设备缓存（v1.6.8）。

        协议规定网关只能主动推送（002/005），HA 无法主动查询，而
        device_manager 缓存不跨重启——修复前每次 HA 重启后所有子设备
        状态都要等下一次网关上报才有值（unknown 窗口最长可达上报周期）。
        恢复值仅在缓存尚无实时数据时写入；真实上报到达后自然覆盖。
        """
        await super().async_added_to_hass()
        try:
            last_state = await self.async_get_last_state()
        except Exception as e:
            _LOGGER.debug("获取 %s 历史状态失败: %s", self.device_sn, e)
            return
        if not last_state or last_state.state not in ("open", "closed"):
            return
        device = self.device_manager.get_device(self.device_sn)
        if device is None:
            return
        if device.get("status") not in (None, DEVICE_STATUS_UNKNOWN, DEVICE_STATUS_CONNECTED):
            return  # 本会话已有实时上报，不覆盖
        attributes = {}
        pos = (last_state.attributes or {}).get("position")
        try:
            if pos is not None:
                attributes["r_travel"] = max(0, min(100, int(pos)))
        except (ValueError, TypeError):
            pass
        status = DEVICE_STATUS_OPEN if last_state.state == "open" else DEVICE_STATUS_CLOSED
        _LOGGER.info(
            "恢复设备 %s 重启前状态: %s%s", self.device_sn, status,
            "（位置 %s%%）" % attributes["r_travel"] if "r_travel" in attributes else ""
        )
        await self.device_manager.update_device_status(self.device_sn, status, attributes or None)

    @property
    def is_closing(self):
        """始终返回False，确保关闭按钮不会变灰"""
        return False

    @property
    def is_opening(self):
        """始终返回False，确保打开按钮不会变灰"""
        return False

    @property
    def current_cover_position(self):
        """始终返回None，HA不知道位置，所以所有按钮都可点击

        注意：如果返回 0，HA 会自动灰掉关闭按钮；
        如果返回 100，HA 会自动灰掉打开按钮。
        因此必须返回 None 来保证所有按钮始终可用。
        位置信息通过 extra_state_attributes 供用户查看。
        """
        return None

    @property
    def extra_state_attributes(self):
        """返回额外状态属性，供用户查看设备实际位置和状态"""
        attrs = {}
        device = self.device_manager.get_device(self.device_sn)
        if device:
            status = device.get("status")
            if status:
                attrs["device_status"] = status
            attributes = device.get("attributes", {})
            r_travel = attributes.get("r_travel")
            if r_travel is not None:
                try:
                    attrs["position"] = max(0, min(100, int(r_travel)))
                except (ValueError, TypeError):
                    pass
        return attrs

    async def async_update(self) -> None:
        """定期更新状态，防止实体被HA标记为unavailable"""
        # 守卫：实体被移除后 hass 为 None，残留轮询直接返回（2026-08-28 实测崩溃点）
        if self.hass is None:
            return
        self._attr_available = True
        self.async_write_ha_state()

    async def async_open_cover(self, **kwargs) -> None:
        """打开开窗器"""
        try:
            await self._get_mqtt_handler().send_command(self.device_sn, COMMAND_OPEN)
            _LOGGER.info("Cover打开: %s", self.device_sn)
        except Exception as e:
            _LOGGER.error("Cover打开失败 %s: %s", self.device_sn, e)

    async def async_close_cover(self, **kwargs) -> None:
        """关闭开窗器"""
        try:
            await self._get_mqtt_handler().send_command(self.device_sn, COMMAND_CLOSE)
            _LOGGER.info("Cover关闭: %s", self.device_sn)
        except Exception as e:
            _LOGGER.error("Cover关闭失败 %s: %s", self.device_sn, e)

    async def async_stop_cover(self, **kwargs) -> None:
        """停止开窗器"""
        try:
            await self._get_mqtt_handler().send_command(self.device_sn, COMMAND_STOP)
            _LOGGER.info("Cover停止: %s", self.device_sn)
        except Exception as e:
            _LOGGER.error("Cover停止失败 %s: %s", self.device_sn, e)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """设置Cover实体"""
    _LOGGER.info("设置Cover平台: %s", entry.entry_id)

    domain_data = hass.data[DOMAIN]
    entry_data = domain_data.get(entry.entry_id)

    if not entry_data:
        _LOGGER.error("配置条目数据未找到: %s", entry.entry_id)
        return

    device_manager = entry_data.get("device_manager")
    mqtt_handler = entry_data.get("mqtt_handler")

    if not device_manager or not mqtt_handler:
        _LOGGER.error("设备管理器或MQTT处理器未找到")
        return

    gateway_sn = entry.data[CONF_GATEWAY_SN]

    created_covers = {}

    async def on_device_added(device_sn: str, device_name: str, device_type: str):
        """设备添加回调，自动创建Cover实体"""
        if device_type == DEVICE_TYPE_WINDOW_OPENER:
            # 会话内幂等短路（v1.6.3）：设备重同步会重复触发本回调；
            # async_add_entities 到注册表落库存在窗口，注册表查重挡不住连续事件
            if device_sn in created_covers:
                _LOGGER.debug("Cover实体本会话已创建，跳过: %s", device_sn)
                return

            from .utils import async_get_entity_id as _aget_eid

            cover_unique_id = f"{gateway_sn}_{device_sn}_cover"
            # 兼容新旧 HA 的 entity 查找（新版 async_get_entity_id 为 async 方法——2026-08-28 修复）
            cover_exists = await _aget_eid(hass, "cover", cover_unique_id) is not None

            if cover_exists:
                _LOGGER.debug("Cover实体已存在，跳过创建: %s", device_sn)
                return

            cover = WindowControllerCover(
                hass,
                device_manager,
                mqtt_handler,
                gateway_sn,
                device_sn,
                device_name,
                str(entry.entry_id)
            )
            async_add_entities([cover])
            created_covers[device_sn] = cover
            _LOGGER.info("自动为设备 %s 添加Cover实体", device_name)

    async def on_device_removed(device_sn: str, device_name: str, device_type: str):
        """设备移除回调，清理相关Cover实体"""
        if device_type == DEVICE_TYPE_WINDOW_OPENER:
            if device_sn in created_covers:
                cover = created_covers[device_sn]
                del created_covers[device_sn]

                try:
                    from .utils import call_registry_method as _call_reg
                    entity_registry = get_entity_registry(hass)
                    if cover.entity_id:
                        await _call_reg(entity_registry.async_remove, cover.entity_id)
                        _LOGGER.info("已移除设备 %s 的Cover实体", device_name)
                except Exception as e:
                    _LOGGER.error("移除Cover实体失败 %s: %s", device_name, e)

    device_manager.set_device_added_callback(on_device_added)
    device_manager.set_device_removed_callback(on_device_removed)

    entities = []
    devices = device_manager.get_all_devices()
    for device in devices:
        if device.get("type") == DEVICE_TYPE_WINDOW_OPENER:
            device_sn = device["sn"]
            device_name = device["name"]

            # 启动循环无条件创建 Cover：
            # 注册表条目跨重启/重载持久保留，用注册表查重会导致重启后
            # 实体只有注册表条目、没有平台实例（不可用）。
            # 重复添加由 HA 按 unique_id 自动去重（替换更新）。
            cover = WindowControllerCover(
                hass,
                device_manager,
                mqtt_handler,
                gateway_sn,
                device_sn,
                device_name,
                str(entry.entry_id)
            )
            entities.append(cover)
            created_covers[device_sn] = cover

    if entities:
        async_add_entities(entities)
        _LOGGER.info("已添加 %d 个Cover实体", len(entities))
