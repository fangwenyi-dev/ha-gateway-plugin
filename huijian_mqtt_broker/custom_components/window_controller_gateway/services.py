"""服务处理与注册 - 开窗器网关的服务处理器与服务注册"""
import logging
import re
import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    CONF_GATEWAY_SN,
    SERVICE_START_PAIRING,
    SERVICE_REFRESH_DEVICES,
    SERVICE_MIGRATE_DEVICES,
    SERVICE_RENAME_DEVICE,
    SERVICE_TRANSFER_DEVICE,
    ATTR_NEW_NAME,
    DEVICE_TO_GATEWAY_MAPPING,
    GATEWAY_PAIRING_TIMEOUT,
    POSITION_MIN,
    POSITION_MAX,
    COMMAND_SET_POSITION,
)

# 导入辅助函数
from .utils import find_gateway_by_device_id, find_device_by_device_id

_LOGGER = logging.getLogger(__name__)


def _reject_bool_position(value):
    """拒绝布尔位置参数

    Python 中 bool 是 int 子类，`vol.Coerce(int)` 会把 True 静默转为 1，
    必须在 Coerce 之前显式拒绝，避免 `position: true` 被当作位置 1 下发。
    """
    if type(value) is bool:
        raise vol.Invalid("position 不能是布尔值")
    return value


async def handle_start_pairing(hass: HomeAssistant, call: ServiceCall) -> None:
    """处理开始配对服务调用"""
    device_id = call.data.get("device_id")
    duration = call.data.get("duration", GATEWAY_PAIRING_TIMEOUT)

    if not device_id:
        _LOGGER.error("开始配对服务调用失败：未指定设备ID")
        return

    _LOGGER.info("收到开始配对请求，设备ID: %s，持续时间: %d秒", device_id, duration)
    
    gateway_data, gateway_sn = find_gateway_by_device_id(hass, device_id)
    if not gateway_data:
        _LOGGER.error("未找到设备ID %s 对应的网关", device_id)
        return

    mqtt_handler = gateway_data.get("mqtt_handler")
    if not mqtt_handler:
        _LOGGER.error("未找到MQTT处理器")
        return

    try:
        # P1 修复：使用 mqtt_handler.pairing_timeout_handle 统一管理配对超时，
        # 确保服务调用和按钮按下共享同一个超时句柄，避免重复超时回调。
        if mqtt_handler.pairing_timeout_handle:
            mqtt_handler.pairing_timeout_handle.cancel()
            mqtt_handler.pairing_timeout_handle = None

        success = await mqtt_handler.send_command(mqtt_handler.gateway_sn, "start_pairing")
        if not success:
            _LOGGER.error("发送配对命令失败")
            return

        mqtt_handler.pairing_active = True
        mqtt_handler._notify_status_change()

        _pairing_status_task = hass.async_create_task(
            gateway_data["device_manager"].update_gateway_status("pairing")
        )
        # 任务引用存入条目 _bg_tasks，供卸载时统一取消
        gateway_data.setdefault("_bg_tasks", []).append(_pairing_status_task)

        _LOGGER.info("已为网关 %s 发起配对，持续时间: %d秒", gateway_sn, duration)

        def pairing_timeout():
            mqtt_handler.pairing_timeout_handle = None
            mqtt_handler.pairing_active = False
            mqtt_handler._notify_status_change()
            _status_restore_task = hass.async_create_task(
                gateway_data["device_manager"].update_gateway_status(
                    "online" if mqtt_handler.connected else "offline"
                )
            )
            # 任务引用存入条目 _bg_tasks，供卸载时统一取消
            gateway_data.setdefault("_bg_tasks", []).append(_status_restore_task)
            _LOGGER.info("配对模式已超时，恢复正常状态")

        mqtt_handler.pairing_timeout_handle = hass.loop.call_later(duration, pairing_timeout)
    except (ConnectionError, TimeoutError) as e:
        _LOGGER.error("网关 %s 连接或超时错误: %s", gateway_sn, e)
    except (KeyError, AttributeError) as e:
        _LOGGER.error("网关 %s MQTT处理器未找到或配置错误: %s", gateway_sn, e)
    except Exception as e:
        _LOGGER.error("网关 %s 执行配对命令失败: %s", gateway_sn, e)

async def handle_rename_device(hass: HomeAssistant, call: ServiceCall) -> None:
    """处理重命名设备服务调用"""
    device_id = call.data.get("device_id")
    new_name = call.data.get(ATTR_NEW_NAME)

    if not device_id or not new_name:
        _LOGGER.error("重命名设备服务调用失败：参数不完整")
        return

    # P0 修复：使用 find_device_by_device_id 解析出设备 SN，
    # 而非直接把 device_id（可能是 HA 设备 ID）传给 rename_device。
    device, gateway_data, gateway_sn = find_device_by_device_id(hass, device_id)
    if not device or not gateway_data:
        _LOGGER.error("未找到设备ID %s 对应的设备", device_id)
        return

    device_manager = gateway_data.get("device_manager")
    if not device_manager:
        _LOGGER.error("未找到设备管理器")
        return

    try:
        device_sn = device["sn"]
        success = await device_manager.rename_device(device_sn, new_name)
        if success:
            _LOGGER.info("设备 %s 已重命名为 %s", device_sn, new_name)
    except Exception as e:
        _LOGGER.error("设备 %s 重命名失败: %s", device_id, e)

async def handle_refresh_devices(hass: HomeAssistant, call: ServiceCall) -> None:
    """处理刷新设备服务调用

    协议说明：002 是网关主动发起的上报，HA 无法主动触发设备发现。
    设备列表更新完全依赖网关主动发送 002 消息，HA 被动接收。
    """
    device_id = call.data.get("device_id")

    if not device_id:
        _LOGGER.error("刷新设备服务调用失败：未指定设备ID")
        return

    gateway_data, gateway_sn = find_gateway_by_device_id(hass, device_id)
    if not gateway_data:
        _LOGGER.error("未找到设备ID %s 对应的网关", device_id)
        return

    # 协议说明：002 是网关主动发起，HA 无法主动触发设备发现
    # 设备列表更新依赖网关定期主动上报 002 消息
    _LOGGER.info(
        "网关 %s 的设备列表更新依赖网关主动上报（002），HA 无法主动触发。"
        "请等待网关下一次自动上报，或重启网关触发上报。",
        gateway_sn
    )

async def handle_set_position(hass: HomeAssistant, call: ServiceCall) -> None:
    """处理设置位置服务调用 - 优化版，减少阻塞"""
    device_id = call.data.get("device_id")
    position = call.data.get("position")

    if not device_id:
        _LOGGER.error("设置位置服务调用失败：未指定设备ID")
        return

    if position is None:
        _LOGGER.error("设置位置服务调用失败：未指定位置")
        return

    # 加强位置参数验证（type() is int 排除 bool：Python 中 bool 是 int 子类，
    # isinstance(True, int) 为 True，会导致 position: true 被静默转为位置 1）
    if type(position) is not int or position < 0 or position > 100:
        _LOGGER.error("设置位置服务调用失败：位置必须是0-100之间的整数")
        return

    _LOGGER.info("收到设置位置请求，设备ID: %s，位置: %d", device_id, position)
    
    device, gateway_data, gateway_sn = find_device_by_device_id(hass, device_id)
    if not device or not gateway_data:
        _LOGGER.error("未找到设备ID %s 对应的设备", device_id)
        return

    mqtt_handler = gateway_data.get("mqtt_handler")
    if not mqtt_handler:
        _LOGGER.error("未找到MQTT处理器")
        return

    # 使用异步任务执行，减少阻塞
    async def set_position_async():
        try:
            await mqtt_handler.send_command(
                device["sn"], 
                "set_position", 
                {"position": position}
            )
            _LOGGER.info("已为设备 %s 设置位置: %d", device["sn"], position)
        except (ConnectionError, TimeoutError) as e:
            _LOGGER.error("设备 %s 连接或超时错误: %s", device["sn"], e)
        except (KeyError, AttributeError) as e:
            _LOGGER.error("设备 %s MQTT处理器配置错误: %s", device["sn"], e)
        except Exception as e:
            _LOGGER.error("设置设备位置失败: %s", e)
    
    # 创建异步任务，立即返回
    hass.async_create_task(set_position_async())
    _LOGGER.info("设置位置服务调用已提交，设备ID: %s，位置: %d", device_id, position)

async def handle_check_gateway_status(hass: HomeAssistant, call: ServiceCall) -> None:
    """处理检查网关状态服务调用"""
    device_id = call.data.get("device_id")
    gateway_sn = call.data.get("gateway_sn")

    if not device_id and not gateway_sn:
        _LOGGER.error("检查网关状态服务调用失败：未指定设备ID或网关SN")
        return

    # 优先使用 device_id 查找，其次使用 gateway_sn
    gateway_data = None
    resolved_sn = None
    if device_id:
        gateway_data, resolved_sn = find_gateway_by_device_id(hass, device_id)
    elif gateway_sn:
        # 通过 gateway_sn 直接查找
        for entry_id, data in hass.data.get(DOMAIN, {}).items():
            if isinstance(data, dict) and data.get("gateway_sn", "").lower() == gateway_sn.lower():
                gateway_data = data
                resolved_sn = gateway_sn
                break

    if not gateway_data:
        target = device_id or gateway_sn
        _LOGGER.error("未找到对应的网关: %s", target)
        return

    _LOGGER.info("收到检查网关状态请求，网关SN: %s", resolved_sn)
    
    try:
        is_connected = await gateway_data["mqtt_handler"].check_connection()
        gateway_info = gateway_data["device_manager"].get_gateway_info()
        _LOGGER.info("网关 %s 状态检查结果: 在线=%s, 信息=%s", 
                    gateway_info.get("name"), is_connected, gateway_info)
    except (ConnectionError, TimeoutError) as e:
        _LOGGER.error("网关 %s 连接或超时错误: %s", resolved_sn, e)
    except (KeyError, AttributeError) as e:
        _LOGGER.error("网关 %s 配置错误: %s", resolved_sn, e)
    except Exception as e:
        _LOGGER.error("检查网关状态失败: %s", e)

async def handle_migrate_devices(hass: HomeAssistant, call: ServiceCall) -> None:
    """完善的设备迁移服务"""
    old_gateway_sn = call.data.get("old_gateway_sn")  # 旧网关SN
    new_gateway_sn = call.data.get("new_gateway_sn")  # 新网关SN
    remove_old_gateway = call.data.get("remove_old_gateway", False)  # 是否移除旧网关

    # 添加更严格的参数验证
    if not isinstance(old_gateway_sn, str) or len(old_gateway_sn) < 10:
        _LOGGER.error("旧网关SN格式无效: %s", old_gateway_sn)
        return
    
    if not isinstance(new_gateway_sn, str) or len(new_gateway_sn) < 10:
        _LOGGER.error("新网关SN格式无效: %s", new_gateway_sn)
        return
    
    # 验证SN格式：与 config_flow.py 的 validate_gateway_sn 保持一致，允许所有字母和数字
    if not re.match(r'^[a-zA-Z0-9]+$', old_gateway_sn):
        _LOGGER.error("旧网关SN格式无效，只允许字母和数字: %s", old_gateway_sn)
        return
    
    if not re.match(r'^[a-zA-Z0-9]+$', new_gateway_sn):
        _LOGGER.error("新网关SN格式无效，只允许字母和数字: %s", new_gateway_sn)
        return
    
    if not isinstance(remove_old_gateway, bool):
        _LOGGER.error("remove_old_gateway参数必须是布尔值: %s", remove_old_gateway)
        return

    # 检查新旧网关是否相同
    if old_gateway_sn.lower() == new_gateway_sn.lower():
        _LOGGER.error("新旧网关不能相同: %s", old_gateway_sn)
        return

    _LOGGER.info("开始设备迁移，新网关: %s, 旧网关: %s", new_gateway_sn, old_gateway_sn)

    # 1. 验证网关存在
    def find_gateway_entry(gateway_sn):
        for entry in hass.config_entries.async_entries(DOMAIN):
            if CONF_GATEWAY_SN in entry.data and entry.data[CONF_GATEWAY_SN].lower() == gateway_sn.lower():
                return entry
        return None

    old_gateway_entry = find_gateway_entry(old_gateway_sn)
    new_gateway_entry = find_gateway_entry(new_gateway_sn)

    if not old_gateway_entry or not new_gateway_entry:
        _LOGGER.error("网关不存在，旧网关SN: %s, 新网关SN: %s", old_gateway_sn, new_gateway_sn)
        return

    _LOGGER.info("找到网关条目，旧网关: %s, 新网关: %s", old_gateway_entry.entry_id, new_gateway_entry.entry_id)

    # 2. 获取设备管理器
    old_manager = None
    new_manager = None

    if old_gateway_entry.entry_id in hass.data[DOMAIN]:
        old_manager = hass.data[DOMAIN][old_gateway_entry.entry_id].get("device_manager")

    if new_gateway_entry.entry_id in hass.data[DOMAIN]:
        new_manager = hass.data[DOMAIN][new_gateway_entry.entry_id].get("device_manager")

    if not old_manager or not new_manager:
        _LOGGER.error("设备管理器不存在")
        return

    # 3. 执行迁移
    try:
        # 发送迁移开始事件
        hass.bus.async_fire(
            f"{DOMAIN}_migration_progress",
            {
                "old_gateway_sn": old_gateway_sn,
                "new_gateway_sn": new_gateway_sn,
                "status": "started",
                "progress": 0,
                "message": "开始设备迁移"
            }
        )
        
        # 使用安全迁移方法，支持旧网关不在线的情况
        success, migrated_devices = await new_manager.safe_migrate_devices(
            old_gateway_sn,
            new_gateway_sn
        )

        if success:
            # 发送迁移完成事件
            hass.bus.async_fire(
                f"{DOMAIN}_migration_progress",
                {
                    "old_gateway_sn": old_gateway_sn,
                    "new_gateway_sn": new_gateway_sn,
                    "status": "devices_migrated",
                    "progress": 50,
                    "message": "设备迁移完成，开始验证实体"
                }
            )
            
            _LOGGER.info("设备迁移成功")
            
            # 直接发送迁移成功事件
            hass.bus.async_fire(
                f"{DOMAIN}_migration_progress",
                {
                    "old_gateway_sn": old_gateway_sn,
                    "new_gateway_sn": new_gateway_sn,
                    "status": "verified",
                    "progress": 75,
                    "message": "设备迁移完成"
                }
            )
            
            # 5. 不再重新加载平台，而是发送事件让前端刷新
            try:
                _LOGGER.info("发送迁移完成事件，通知前端刷新")
                
                # 发送事件通知前端刷新
                hass.bus.async_fire(
                    f"{DOMAIN}_devices_migrated",
                    {
                        "old_gateway_sn": old_gateway_sn,
                        "new_gateway_sn": new_gateway_sn,
                        "success": True,
                        "device_count": len(migrated_devices)
                    }
                )
                
                # P1 修复：移除不存在的 homeassistant/reload_entities 事件（死代码），
                # 该事件并非 HA 标准事件，不会触发任何 UI 刷新。
                _LOGGER.info("已通知前端刷新，用户可能需要手动刷新页面或等待自动更新")
                
            except Exception as reload_error:
                _LOGGER.error("发送刷新事件失败: %s", reload_error)

            # 6. 可选：卸载旧网关
            if remove_old_gateway:
                try:
                    _LOGGER.info("移除旧网关: %s", old_gateway_entry.entry_id)
                    # 发送移除旧网关事件
                    hass.bus.async_fire(
                        f"{DOMAIN}_migration_progress",
                        {
                            "old_gateway_sn": old_gateway_sn,
                            "new_gateway_sn": new_gateway_sn,
                            "status": "removing_old_gateway",
                            "progress": 95,
                            "message": "正在移除旧网关"
                        }
                    )
                    
                    # 先清理旧网关的设备注册，再删除配置条目
                    await old_manager._cleanup_old_gateway(old_gateway_sn)
                    await hass.config_entries.async_remove(old_gateway_entry.entry_id)
                    _LOGGER.info("旧网关移除成功")
                except Exception as remove_error:
                    _LOGGER.error("移除旧网关失败: %s", remove_error)
            else:
                # 保留旧网关时，重载其平台以清理已迁移设备的旧实体
                try:
                    _LOGGER.info("重载旧网关 %s 的平台，清理已迁移设备实体", old_gateway_sn)
                    await hass.config_entries.async_reload(old_gateway_entry.entry_id)
                except Exception as reload_error:
                    _LOGGER.warning("重载旧网关平台失败: %s", reload_error)
            
            # 发送迁移完成事件
            hass.bus.async_fire(
                f"{DOMAIN}_migration_progress",
                {
                    "old_gateway_sn": old_gateway_sn,
                    "new_gateway_sn": new_gateway_sn,
                    "status": "completed",
                    "progress": 100,
                    "message": "迁移完成"
                }
            )
            
            # 重新加载新网关的平台，确保实体正确显示
            try:
                _LOGGER.info("重新加载新网关 %s 的平台", new_gateway_sn)
                await hass.config_entries.async_reload(new_gateway_entry.entry_id)
                _LOGGER.info("新网关平台重新加载完成")
            except Exception as reload_error:
                _LOGGER.error("重新加载新网关平台失败: %s", reload_error)
                    
    except Exception as e:
        _LOGGER.error("迁移失败: %s", e)
        import traceback
        _LOGGER.error("详细错误信息: %s", traceback.format_exc())
        # 发送错误通知
        hass.bus.async_fire(
            f"{DOMAIN}_migration_failed",
            {
                "old_gateway_sn": old_gateway_sn,
                "new_gateway_sn": new_gateway_sn,
                "error": str(e)
            }
        )
        # 发送迁移失败事件
        hass.bus.async_fire(
            f"{DOMAIN}_migration_progress",
            {
                "old_gateway_sn": old_gateway_sn,
                "new_gateway_sn": new_gateway_sn,
                "status": "failed",
                "progress": 0,
                "message": f"迁移失败: {str(e)}"
            }
        )

async def handle_transfer_device(hass: HomeAssistant, call: ServiceCall) -> None:
    """处理转移设备服务调用"""
    device_id = call.data.get("device_id")
    new_gateway_sn = call.data.get("new_gateway_sn")

    if not device_id or not new_gateway_sn:
        _LOGGER.error("转移设备服务调用失败：参数不完整")
        return

    _LOGGER.info("收到转移设备请求，设备ID: %s，目标网关: %s", device_id, new_gateway_sn)

    # 解析设备SN（支持直接传入设备SN或HA设备ID）
    device_sn = None

    # 方法1：直接检查 device_id 是否是映射表中的设备SN
    if DOMAIN in hass.data and DEVICE_TO_GATEWAY_MAPPING in hass.data[DOMAIN]:
        mapping = hass.data[DOMAIN][DEVICE_TO_GATEWAY_MAPPING]
        if device_id in mapping:
            device_sn = device_id

    # 方法2：通过设备注册表查找（device_id 可能是 HA 设备注册表 ID）
    if not device_sn:
        try:
            from homeassistant.helpers.device_registry import async_get as async_get_device_registry
            dr = async_get_device_registry(hass)
            device_entry = dr.async_get(device_id)
            if device_entry:
                for identifier in device_entry.identifiers:
                    if identifier[0] == DOMAIN:
                        device_sn = identifier[1]
                        break
        except Exception as e:
            # 保持韧性：注册表解析失败不阻断转移，但必须留下可排查日志
            _LOGGER.warning(
                "通过设备注册表解析设备SN失败（将尝试其他方式）: %s", e, exc_info=True
            )

    # 方法3：在所有设备管理器的设备列表中查找
    if not device_sn:
        for entry_id, data in hass.data[DOMAIN].items():
            if isinstance(data, dict):
                dm = data.get("device_manager")
                if dm:
                    for device in dm.get_all_devices():
                        device_sn_candidate = device.get("sn", "")
                        # 使用精确匹配：device_id 等于 SN，或 SN 是 device_id 按 _ 分割后的某一段
                        if device_id == device_sn_candidate or device_sn_candidate in device_id.split("_"):
                            device_sn = device_sn_candidate
                            break
                    if device_sn:
                        break

    if not device_sn:
        _LOGGER.error("未找到设备ID %s 对应的设备SN", device_id)
        return

    # 查找任意一个设备管理器实例来执行转移
    device_manager = None
    for entry_id, data in hass.data[DOMAIN].items():
        if isinstance(data, dict) and data.get("device_manager"):
            device_manager = data["device_manager"]
            break

    if not device_manager:
        _LOGGER.error("未找到可用的设备管理器")
        return

    # 执行转移
    try:
        success = await device_manager.transfer_device(device_sn, new_gateway_sn)
        if success:
            _LOGGER.info("设备 %s 已成功转移到网关 %s", device_sn, new_gateway_sn)
        else:
            _LOGGER.error("设备 %s 转移失败", device_sn)
    except Exception as e:
        _LOGGER.error("转移设备失败: %s", e)


def register_services(hass: HomeAssistant) -> bool:
    """注册服务"""
    # 注册服务
    try:
        hass.services.async_register(
            DOMAIN,
            SERVICE_START_PAIRING,
            lambda call: handle_start_pairing(hass, call),
            schema=vol.Schema({
                vol.Required("device_id"): cv.string,
                vol.Optional("duration", default=GATEWAY_PAIRING_TIMEOUT): cv.positive_int,
            })
        )

        hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH_DEVICES,
            lambda call: handle_refresh_devices(hass, call),
            schema=vol.Schema({
                vol.Required("device_id"): cv.string,
            })
        )

        hass.services.async_register(
            DOMAIN,
            COMMAND_SET_POSITION,
            lambda call: handle_set_position(hass, call),
            schema=vol.Schema({
                vol.Required("device_id"): cv.string,
                vol.Required("position"): vol.All(
                    _reject_bool_position,
                    vol.Coerce(int),
                    vol.Range(min=POSITION_MIN, max=POSITION_MAX),
                ),
            })
        )

        hass.services.async_register(
            DOMAIN,
            "check_gateway_status",
            lambda call: handle_check_gateway_status(hass, call),
            schema=vol.Schema({
                vol.Optional("device_id"): cv.string,
                vol.Optional("gateway_sn"): cv.string,
            })
        )

        # ============ 迁移服务（migrate_devices）暂禁用 ============
        # 设备迁移功能先不使用：协议/迁移逻辑待后续版本完善后再启用。
        # 若需重新启用，取消下面 async_register 的注释即可。
        # hass.services.async_register(
        #     DOMAIN,
        #     SERVICE_MIGRATE_DEVICES,
        #     lambda call: handle_migrate_devices(hass, call),
        #     schema=vol.Schema({
        #         vol.Required("old_gateway_sn"): cv.string,
        #         vol.Required("new_gateway_sn"): cv.string,
        #         vol.Optional("remove_old_gateway", default=False): cv.boolean,
        #     })
        # )

        hass.services.async_register(
            DOMAIN,
            SERVICE_RENAME_DEVICE,
            lambda call: handle_rename_device(hass, call),
            schema=vol.Schema({
                vol.Required("device_id"): cv.string,
                vol.Required(ATTR_NEW_NAME): cv.string,
            })
        )

        hass.services.async_register(
            DOMAIN,
            SERVICE_TRANSFER_DEVICE,
            lambda call: handle_transfer_device(hass, call),
            schema=vol.Schema({
                vol.Required("device_id"): cv.string,
                vol.Required("new_gateway_sn"): cv.string,
            })
        )

        _LOGGER.info("开窗器网关服务注册成功")
    except vol.Invalid as e:
        _LOGGER.error("服务参数模式无效: %s", e)
        return False
    except Exception as e:
        _LOGGER.error("注册服务时发生意外错误: %s", e)
        return False

    return True
