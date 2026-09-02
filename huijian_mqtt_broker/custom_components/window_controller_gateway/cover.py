"""开窗器网关Cover平台 - 供LLM等使用Cover语义控制开窗器"""
import logging
import time

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
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
    SENSOR_TIMEOUT_MINUTES,
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
        # v1.6.16（用户定案：原生卡片开/关/停三键任何状态下必须可点）：
        # 置灰判据实锤于 home-assistant/frontend src/data/cover.ts——
        #   canOpen  = assumed_state || (!isFullyOpen  && !isOpening)
        #   canClose = assumed_state || (!isFullyClosed && !isClosing)
        #   canStop  = 仅排除 unavailable（从不受开/闭状态影响）
        # 即 state=open 时「开」被禁、closed 时「关」被禁——用户所见"灰色"。
        # assumed_state=True 短路前两式 → 三键恒可下发；HA 状态机
        # （CoverEntity.state 由 is_closed 计算）完全不受该属性影响，
        # v1.6.8 定案的真实 open/closed（历史曲线/自动化/LLM 语义）原样保留。
        # 语义诚实性同样成立：协议规定网关只能被动上报（002/005），HA 无法
        # 回查实际窗位，手动拉绳等旁路移动不会即时反映——本就不是可回读态。
        self._attr_assumed_state = True
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
            # v1.6.19（第六轮审计 B-MED3）：与 sensor 的 15 分钟时效同判据
            # （SENSOR_TIMEOUT_MINUTES，v1.6.12 #7 定案）。网关长期失联时
            # sensor/binary_sensor 已转 unknown，此处不设闸则 cover.state
            # 永久冻结在最后已知值——同设备两实体矛盾显示、自动化按陈旧
            # "open" 持续动作。恢复值（async_added_to_hass）在重启时刻获得
            # 时间戳，语义=「信任关机快照 15 分钟」，与 v1.6.8 恢复设计
            # 自洽；无时间戳的设备（历史形态/测试夹具）视为新鲜。
            _lu = device.get("last_update")
            if _lu and (time.time() - _lu) > SENSOR_TIMEOUT_MINUTES * 60:
                return None
            status = device.get("status")
            if status == DEVICE_STATUS_CLOSED:
                return True
            if status == DEVICE_STATUS_OPEN:
                return False
            # v1.6.8（用户定案：状态与位置同步——r_travel 0=关，>0=开）：
            # 防御性兜底。现行链路里 r_travel 总是与推导出的 status 同时写入
            # （002 _update_device_attributes 与 005 attrs 分支均如此），此分支
            # 正常不触发；保留是防固件将来「只推位置不带状态字段」时出现
            # 「待上报 + 位置 65%」的矛盾显示
            r_travel = (device.get("attributes") or {}).get("r_travel")
            try:
                if r_travel is not None:
                    # v1.6.11（外部审计 #2）：int() 截断会把 0.5 判成"关"
                    # （int(0.5)=0 ≤0），违反用户定案的">0=打开"语义。协议
                    # 规定整数 0-100，但 JSON 可携浮点——用 float 直比，
                    # 非数值串由既有 except (ValueError, TypeError) 落 None
                    return float(r_travel) <= 0
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
        """打开开窗器（v1.6.9：失败如实上抛，此前吞异常+不查返回值=假成功）"""
        try:
            success = await self._get_mqtt_handler().send_command(self.device_sn, COMMAND_OPEN)
        except Exception as e:
            _LOGGER.error("Cover打开失败 %s: %s", self.device_sn, e)
            raise HomeAssistantError(f"打开失败：{e}") from e
        if not success:
            raise HomeAssistantError("打开失败：命令未送达（网关或设备离线）")
        _LOGGER.info("Cover打开: %s", self.device_sn)

    async def async_close_cover(self, **kwargs) -> None:
        """关闭开窗器（v1.6.9：失败如实上抛）"""
        try:
            success = await self._get_mqtt_handler().send_command(self.device_sn, COMMAND_CLOSE)
        except Exception as e:
            _LOGGER.error("Cover关闭失败 %s: %s", self.device_sn, e)
            raise HomeAssistantError(f"关闭失败：{e}") from e
        if not success:
            raise HomeAssistantError("关闭失败：命令未送达（网关或设备离线）")
        _LOGGER.info("Cover关闭: %s", self.device_sn)

    async def async_stop_cover(self, **kwargs) -> None:
        """停止开窗器（v1.6.9：失败如实上抛）"""
        try:
            success = await self._get_mqtt_handler().send_command(self.device_sn, COMMAND_STOP)
        except Exception as e:
            _LOGGER.error("Cover停止失败 %s: %s", self.device_sn, e)
            raise HomeAssistantError(f"停止失败：{e}") from e
        if not success:
            raise HomeAssistantError("停止失败：命令未送达（网关或设备离线）")
        _LOGGER.info("Cover停止: %s", self.device_sn)

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
            # v1.6.12（第五轮审计 #5）：注册设备状态回调（对齐 number/sensor）——
            # 此前 cover 只靠 HA 轮询（默认 5 分钟），005 上报到达后传感器/滑块
            # 即时刷新而 cover 卡片滞后，违背 v1.6.8「cover.state 可驱动历史曲线、
            # 自动化触发条件」的定案
            mqtt_handler.add_status_callback(device_sn, cover.async_update)
            _LOGGER.info("自动为设备 %s 添加Cover实体", device_name)

    async def on_device_removed(device_sn: str, device_name: str, device_type: str):
        """设备移除回调，清理相关Cover实体"""
        if device_type == DEVICE_TYPE_WINDOW_OPENER:
            if device_sn in created_covers:
                cover = created_covers[device_sn]
                del created_covers[device_sn]
                # v1.6.12：摘除本会话注册的设备状态回调（与 number 移除路径对称）
                mqtt_handler.remove_status_callback(device_sn, cover.async_update)

                try:
                    from .utils import call_registry_method as _call_reg
                    from .utils import async_get_entity_id as _aget_eid
                    entity_registry = get_entity_registry(hass)
                    # v1.6.19（第六轮审计 B-LOW6）：unique_id 优先（button.py
                    # v1.6.3 定案同款）——配对后秒级解绑时实体可能尚未获派
                    # entity_id，原单路径落空即注册表悬挂、重配对永久缺 cover。
                    _eid = await _aget_eid(hass, "cover", cover._attr_unique_id)
                    if _eid:
                        await _call_reg(entity_registry.async_remove, _eid)
                        _LOGGER.info("已移除设备 %s 的Cover实体", device_name)
                    elif cover.entity_id:
                        await _call_reg(entity_registry.async_remove, cover.entity_id)
                        _LOGGER.info("已移除设备 %s 的Cover实体", device_name)
                    else:
                        _LOGGER.warning("Cover实体定位失败（unique_id=%s 双路径均未命中）: %s",
                                        cover._attr_unique_id, device_name)
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
            # v1.6.12（第五轮审计 #5）：启动循环同样注册状态回调，
            # 005 上报即时刷新 cover（此前只有轮询路径）
            mqtt_handler.add_status_callback(device_sn, cover.async_update)

    if entities:
        async_add_entities(entities)
        _LOGGER.info("已添加 %d 个Cover实体", len(entities))
