"""工具模块 - 存放通用辅助函数"""
import asyncio
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


async def async_wait_mqtt_loaded(
    hass: HomeAssistant, timeout: float = 10.0, interval: float = 0.5
) -> bool:
    """等待 MQTT 集成 setup 完成（hass.data["mqtt"] 出现），返回是否就绪。

    v1.6.13（客户现场 mqtt_not_available 误诊根治）：ensure_mqtt_connection 的
    "创建/更新 MQTT 条目"路径以提交动作为终点，而 MQTT 集成真正 setup 完成
    （``hass.data["mqtt"]`` 写入）是异步的——config flow 在 ensure 返回后立即
    同步检查 is_mqtt_loaded，会把"刚创建正在连接"的正常时序误判成失败。

    为何不用官方 async_wait_for_mqtt_client：它等待的是"客户端实际连上
    broker"（内部 30 秒超时）。本门禁的唯一判据是"下游
    mqtt.async_subscribe 是否会因 wrapper 缺失而炸"，即 hass.data 条目
    存在性——broker 永久不可达时应快速失败给出可读错误，而不是让
    表单卡 30 秒。轮询目标与 is_mqtt_loaded 保持同一谓词，
    上游改存储结构时仍只需改一处。
    """
    if is_mqtt_loaded(hass):
        return True
    waited = 0.0
    while waited < timeout:
        await asyncio.sleep(interval)
        waited += interval
        if is_mqtt_loaded(hass):
            return True
    return False


def get_via_device_id(device) -> Optional[str]:
    """读取设备的父设备 id（v1.6.12 第五轮审计，跨版本兼容）。

    DeviceEntry 上**从未存在** ``via_device`` 属性——``via_device=(DOMAIN, sn)``
    只是 ``async_get_or_create`` 的入参形式；读取端属性名是 ``via_device_id``，
    其值分两代：
    - 新版 HA：str（父设备 id），上游已列入移除遗留别名计划
    - 旧版 HA：tuple ``(config_entry_id, device_id)`` → 取 device_id
    本库此前多处 ``getattr(device, "via_device", ...)`` 恒落 None，
    网关子设备清单/迁移/删除清理整段死分支（教训与 v1.6.0 "entity"
    字面量同族：假 mock 带真机没有的属性骗过全部测试）。
    """
    via = getattr(device, "via_device_id", None)
    if isinstance(via, tuple):
        return via[1] if len(via) > 1 else None
    return via


def get_device_config_entry_ids(device) -> set:
    """读取设备关联的配置条目 id 集合（跨版本兼容，同 api.py 的双读法）。

    新版 HA 是 ``config_entries``（set），旧版是 ``config_entry_id``（str）。
    ``config_entry_ids`` 这个属性名不存在——v1.6.12 修正 __init__.py 的
    恒空读取（共享保护死分支）。
    """
    ids = set()
    ce = getattr(device, "config_entries", None)
    if ce:
        ids.update(ce)
    ce_id = getattr(device, "config_entry_id", None)
    if ce_id:
        ids.add(ce_id)
    return ids


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
    hass: HomeAssistant, domain: str, unique_id: str
) -> Optional[str]:
    """按 unique_id 查找实体的 entity_id（兼容新旧 HA）。

    HA 真实签名：``EntityRegistry.async_get_entity_id(domain, platform, unique_id)``
    - domain:   实体域（button/cover/number/sensor…，即 entity_id 前缀）
    - platform: 集成域名（本集成 DOMAIN = window_controller_gateway）

    背景（2026-08-28 实测）：HA registry 异步化重构期间，不同版本中
    该方法可能是 async（返回 coroutine，await 后为 RegistryEntry）或
    sync（直接返回 str）。本函数统一处理，返回 entity_id 字符串；不存在返回 None。

    v1.6.3 修复：v1.6.0 重构兼容层时曾把第一个实参误写为字面量 "entity"
    并丢弃调用方传入的实体域，导致索引键 ("entity", DOMAIN, uid) 永不命中、
    全集成 unique_id 反查恒返回 None（重命名别名/按钮清理/删除按钮自删等
    13 处调用点静默失效）。参数亦由 platform 更名为 domain 防再犯。
    """
    entity_registry = get_entity_registry(hass)
    try:
        result = await call_registry_method(
            entity_registry.async_get_entity_id, domain, DOMAIN, unique_id
        )
    except TypeError as e:
        # 签名不兼容（极老版本），放弃查找（v1.5.9 原有兜底，v1.6.3 恢复）。
        # v1.6.4：兜底不得无声——registry 内部真 TypeError 也会被吞成
        # "实体不存在"，与 v1.6.0 "entity" 字面量回归同构的静默失效面，
        # 必须留可观测痕迹（manifest 已钉 2024.12 下限，触发即异常事件）
        _LOGGER.warning(
            "async_get_entity_id(%s, %s) 抛出 TypeError，降级为未找到: %s",
            domain, unique_id, e,
        )
        return None
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

    收口约定（v1.6.3）：所有 registry **写操作**（async_get_or_create / async_remove /
    async_remove_device / async_update_device / async_update_entity /
    async_get_entity_id 等）一律经本函数调用，不允许直调；纯**只读查询**
    （device_registry.async_get、async_get_device、entity_registry.entities.get 等）
    在所有已知版本中均为同步 @callback，可直调，无需经过本函数。
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
        # v1.7.12（第 6 轮审计 E-10）：用户从**子设备**详情页复制"设备 ID"
        # 调服务时，_resolve 解出的是子设备 SN——旧版按"等于某网关 SN"匹配
        # 永不命中，误报"未找到对应网关"。经设备→网关映射反查补最后一跳。
        from .const import DEVICE_TO_GATEWAY_MAPPING
        mapping = hass.data[DOMAIN].get(DEVICE_TO_GATEWAY_MAPPING) or {}
        mapped = mapping.get(gateway_sn)
        if mapped is None:
            for k, v in mapping.items():
                if str(k).lower() == str(gateway_sn).lower():
                    mapped = v
                    break
        if mapped:
            for entry_id, data in hass.data[DOMAIN].items():
                if (isinstance(data, dict)
                        and str(data.get("gateway_sn", "")).lower()
                        == str(mapped).lower()):
                    return data, data.get("gateway_sn")

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