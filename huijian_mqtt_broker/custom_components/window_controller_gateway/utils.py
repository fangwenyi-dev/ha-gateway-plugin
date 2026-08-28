"""工具模块 - 存放通用辅助函数"""
import logging
from typing import Dict, Any, Optional, Tuple
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def is_mqtt_loaded(hass: HomeAssistant) -> bool:
    """MQTT 集成是否已加载。

    兼容新旧 HA：mqtt 集成 setup 完成会写入 ``hass.data["mqtt"]``，
    这是长期稳定的契约（官方推荐的可用性判断方式之一）。
    集中于此判断，未来 HA 若调整存储方式只需改此处。
    """
    return hass.data.get("mqtt") is not None


def is_mqtt_connected(hass: HomeAssistant) -> bool:
    """MQTT broker 是否已连接（官方 API，带兼容回退）。

    ``homeassistant.components.mqtt.async_connected(hass)`` 是 2023.5+ 官方
    辅助函数；旧版不存在时回退为"集成已加载即视为可用"。
    """
    try:
        from homeassistant.components.mqtt import async_connected
        return bool(async_connected(hass))
    except (ImportError, AttributeError):
        return is_mqtt_loaded(hass)


def get_entity_registry(hass: HomeAssistant):
    """获取实体注册表

    Args:
        hass: Home Assistant实例

    Returns:
        EntityRegistry: 实体注册表
    """
    from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
    return async_get_entity_registry(hass)


async def async_get_entity_id(
    hass: HomeAssistant, platform: str, unique_id: str
) -> Optional[str]:
    """按 unique_id 查找实体的 entity_id（兼容新旧 HA）。

    背景（2026-08-28 实测）：HA registry 异步化重构期间，不同版本中
    ``EntityRegistry.async_get_entity_id()`` 可能是 async（返回 coroutine，
    await 后为 RegistryEntry）或 sync（直接返回 str）。本函数统一处理，
    返回 entity_id 字符串；不存在返回 None。
    """
    entity_registry = get_entity_registry(hass)
    result = await call_registry_method(
        entity_registry.async_get_entity_id, "entity", DOMAIN, unique_id
    )
    if result is None:
        return None
    # 新版返回 RegistryEntry，旧版返回 str
    if hasattr(result, "entity_id"):
        return result.entity_id
    return str(result)


async def call_registry_method(method, *args, **kwargs):
    """调用 registry 方法并兼容同步/异步两种实现（HA registry 异步化过渡期）。

    背景（2026-08-28 实测）：Home Assistant 对 EntityRegistry/DeviceRegistry
    的异步化重构尚未完成，同一方法在不同版本中可能是：
    - 同步方法（``@callback def ...``）：直接执行并返回结果（新版 master 如此，
      如 async_remove 返回 None、async_update_entity 返回 RegistryEntry）
    - 异步方法（``async def ...``）：返回 coroutine（部分过渡版本如此）

    本函数统一处理：调用后若返回值是 coroutine 则 await，否则原样返回。
    避免 ``await`` 同步方法（返回 None/RegistryEntry）导致
    "'NoneType' object can't be awaited" / "'RegistryEntry' object can't be awaited"。
    """
    result = method(*args, **kwargs)
    if hasattr(result, "__await__"):
        return await result
    return result


def clear_entity_registry_cache(hass=None):
    """清理实体注册表缓存（兼容接口，实际不再需要缓存管理）"""
    pass


def _resolve_domain_identifier(hass: Any, device_id: str) -> Optional[str]:
    """将 HA 设备注册表 ID（UUID）解析为集成标识符值（网关SN/设备SN）

    服务的 device_id 参数可能来自设备详情页复制的 HA 设备注册表 UUID，
    此函数通过注册表按设备ID直接查找，返回匹配设备的 (DOMAIN, sn) 标识符值。
    找不到或解析失败时返回 None。
    """
    try:
        from homeassistant.helpers.device_registry import async_get as async_get_device_registry
        device_registry = async_get_device_registry(hass)
        entry = device_registry.async_get(device_id)
        if entry:
            for identifier in entry.identifiers:
                if identifier[0] == DOMAIN:
                    return identifier[1]
    except Exception as e:
        _LOGGER.debug("解析设备注册表ID失败（可忽略）: %s", e)
    return None


def find_gateway_by_device_id(hass: Any, device_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """根据设备ID查找对应的网关
    
    Args:
        hass: Home Assistant实例
        device_id: 设备ID，包含网关SN、设备SN，或 HA 设备注册表ID（UUID）
        
    Returns:
        Tuple[Optional[Dict[str, Any]], Optional[str]]: (网关数据, 网关SN) 如果找到，否则 (None, None)
    """
    if DOMAIN not in hass.data or not hass.data[DOMAIN]:
        _LOGGER.error("服务调用失败：集成尚未完成初始化或没有已配置的网关。")
        return None, None

    for entry_id, data in hass.data[DOMAIN].items():
        if isinstance(data, dict):
            gateway_sn = data.get("gateway_sn", "")
            if gateway_sn and gateway_sn in device_id.split("_"):
                return data, gateway_sn
            
            # 检查是否包含设备SN
            device_manager = data.get("device_manager")
            if device_manager:
                devices = device_manager.get_all_devices()
                id_parts = device_id.split("_")
                for device in devices:
                    device_sn = device.get("sn", "")
                    if device_sn in id_parts:
                        return data, gateway_sn
    
    # 兜底：device_id 可能是 HA 设备注册表ID（UUID）
    gateway_sn = _resolve_domain_identifier(hass, device_id)
    if gateway_sn:
        for entry_id, data in hass.data[DOMAIN].items():
            if isinstance(data, dict) and data.get("gateway_sn", "").lower() == gateway_sn.lower():
                return data, gateway_sn

    return None, None


def find_device_by_device_id(hass: Any, device_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str]]:
    """根据设备ID查找对应的设备和网关
    
    Args:
        hass: Home Assistant实例
        device_id: 设备ID，包含设备SN，或 HA 设备注册表ID（UUID）
        
    Returns:
        Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str]]: (设备数据, 网关数据, 网关SN) 如果找到，否则 (None, None, None)
    """
    if DOMAIN not in hass.data or not hass.data[DOMAIN]:
        _LOGGER.error("服务调用失败：集成尚未完成初始化或没有已配置的网关。")
        return None, None, None

    for entry_id, data in hass.data[DOMAIN].items():
        if isinstance(data, dict):
            device_manager = data.get("device_manager")
            if device_manager:
                devices = device_manager.get_all_devices()
                id_parts = device_id.split("_")
                for device in devices:
                    device_sn = device.get("sn", "")
                    if device_sn in id_parts:
                        return device, data, data.get("gateway_sn", "")

    # 兜底：device_id 可能是 HA 设备注册表ID（UUID）
    device_sn = _resolve_domain_identifier(hass, device_id)
    if device_sn:
        for entry_id, data in hass.data[DOMAIN].items():
            if isinstance(data, dict):
                device_manager = data.get("device_manager")
                if device_manager:
                    device = device_manager.get_device(device_sn)
                    if device:
                        return device, data, data.get("gateway_sn", "")

    return None, None, None


def get_device_gateway_mapping(hass: HomeAssistant, device_sn: str) -> Optional[str]:
    """获取设备关联的网关SN
    
    Args:
        hass: Home Assistant实例
        device_sn: 设备SN
    
    Returns:
        Optional[str]: 网关SN，如果未找到返回None
    """
    try:
        from .const import DEVICE_TO_GATEWAY_MAPPING
        if DOMAIN in hass.data and DEVICE_TO_GATEWAY_MAPPING in hass.data[DOMAIN]:
            device_to_gateway_mapping = hass.data[DOMAIN][DEVICE_TO_GATEWAY_MAPPING]
            if device_sn in device_to_gateway_mapping:
                return device_to_gateway_mapping[device_sn]
    except Exception as e:
        _LOGGER.error("获取设备网关映射失败: %s", e)
    return None