"""工具模块 - 存放通用辅助函数"""
import asyncio
import json
import logging
import time
import uuid
from typing import Dict, Any, Optional, Tuple
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PROTOCOL_HEAD, TOPIC_GATEWAY_REQ_FORMAT

_LOGGER = logging.getLogger(__name__)


def iter_devices(device_registry) -> list:
    """设备注册表全量条目遍历（v1.7.28，双 HA 形态兼容）。

    新 HA：`devices` 是可直接迭代出 DeviceEntry 的集合（frame 告警原话
    "iterate it to get the device entries"），映射查找法 .values()/.items()/
    .get() 已弃用（2027.9 停摆）；旧 HA：`devices` 仍是 Mapping，直接迭代
    拿到的是 key 字符串。探测首元素类型自动回退，两种形态都拿到条目列表。
    注意：DeviceRegistry 与 EntityRegistry 均无 async_entries()——CI E2E
    两轮实锤，臆造 API 由 tests/test_v1728_registry_api.py 反钉。
    """
    col = device_registry.devices
    items = list(col)
    if items and isinstance(items[0], str):
        # 旧 Mapping 形态：迭代得键，回退 .values()（此路径仅在旧 HA 触发，
        # 旧版 .values() 合法无告警；新 HA 永不走到）
        items = list(col.values())
    return items


def gateway_instance_uuid(hass: HomeAssistant) -> str:
    """服务端实例指纹：uuid5(NAMESPACE_DNS, config_dir)。

    与 mqtt_handler._lifecycle 同式（该处已改为调用本函数）——确定性、跨
    重启/跨 handler 稳定，保证 v1.7.27 起耳朵 001 代答的 uuid 与转正后
    正式 handler 的应答逐字一致，固件无需处理两个指纹。
    """
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, hass.config.config_dir))


def should_ear_ack_001(ctype: Any, data: Any) -> bool:
    """耳朵级代答门（v1.7.26 用户裁定 A）：仅"未配置网关的 001 绑定请求"可代答。

    与 2026-09-02 五条 ack 方向契约同门：data 带 errcode 的 001 是网关对我方
    报文的回复，绝不再答；002/005 等其余上报在耳朵层不代答（绑定请求语义仅 001）。
    """
    return (ctype == "001" and isinstance(data, dict) and "errcode" not in data)


async def async_ack_gateway_001(hass: HomeAssistant, gateway_sn: str,
                                 msg_id: Any) -> bool:
    """向未绑定网关的 001 绑定请求代答同型 ack（发 gateway/{sn}/req）。

    背景（用户 2026-09-17 裁定 A）：固件首配期每 5s 重发 001，直到收到应答；
    旧链条里应答只在"条目转正→reload→正式 handler 订阅"之后才发出，转正链
    任一环节断裂即成无限重试风暴。耳朵（心跳监听器/_protocol 他网关分支）
    听到未配置网关的 001 时当场代答，风暴即停。

    格式（v1.7.27 用户现场定稿，与正式 handler 应答完全同形）：
    {"head":"$SH","ctype":"001","id":<回带>,"sn":<网关SN>,
    "data":{"errcode":0,"uuid":<实例指纹>}}——uuid 由 gateway_instance_uuid
    确定性计算，与转正后正式 handler 发的逐字一致（固件要求应答必带 uuid，
    2026-09-17 用户实锤格式）。
    返回发布是否成功（失败由调用方留痕，不抛出——代答永不反噬发现主流程）。
    """
    from homeassistant.components import mqtt
    payload = {
        "head": PROTOCOL_HEAD,
        "ctype": "001",
        "id": msg_id,
        "sn": gateway_sn,
        "data": {"errcode": 0, "uuid": gateway_instance_uuid(hass)},
    }
    try:
        await mqtt.async_publish(
            hass,
            TOPIC_GATEWAY_REQ_FORMAT.format(gateway_sn=gateway_sn),
            json.dumps(payload),
            1,
            False,
        )
        return True
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("耳朵代答 001 发布失败（不阻塞发现）: %s", e)
        return False


# ==================== v1.7.30 ②③：代答单点仲裁 + 转正留痕看守 ====================
#
# 台架实锤（2026-09-17 真栈 A/B 双臂）：两处耳朵对同一条 001 各自
# 独立代答——每个已配置条目的 _protocol 他网关分支都是应答者，外加每条等待
# 条目的心跳监听器——实测 1 请求 → 2~3 条同 uuid 应答（倍数=应答者数）。
# 报文无害但属噪声，且"固件对重复 ack 幂等"只是文档主张、未真机实证。
# 正解：以 (sn, id) 为键的进程内认领仲裁——第一个耳朵发布，其余抑制；
# 固件重试换新 id 仍可得一次应答（止血语义不变），重发同 id 超 TTL 后补答
#（丢包保险）。TTL 30s 远大于并发应答者间 ~40ms 的实测散布，收紧到
# 重复风暴消失即可。

EAR_ACK_CLAIM_TTL = 30.0
EAR_ACK_CLAIM_MAX = 256
EAR_PROMOTION_WATCH_SECONDS = 30.0
EAR_PROMOTION_WATCH_LOG_TTL = 600.0


def ear_ack_claim(hass: HomeAssistant, gateway_sn: str, msg_id: Any) -> bool:
    """代答认领（v1.7.30 ②）：同一 (SN, id) 在 TTL 内只放行一个应答者。

    返回 True=本调用获得发布权；False=另一耳朵已答/在答，必须抑制。
    HA 单事件循环内全部调用点在循环线程执行（同步回调/已派发协程），
    无需加锁；容量闸防畸形流量下 dict 无界增长。
    """
    runtime = hass.data.setdefault(DOMAIN, {})
    claims = runtime.setdefault("_ear_ack_claims", {})
    now = time.monotonic()
    for stale in [k for k, ts in claims.items() if now - ts > EAR_ACK_CLAIM_TTL]:
        claims.pop(stale, None)
    key = (str(gateway_sn).lower(), str(msg_id))
    if key in claims:
        return False
    claims[key] = now
    if len(claims) > EAR_ACK_CLAIM_MAX:
        claims.pop(min(claims, key=claims.get), None)
    return True


def _watch_ear_promotion(hass: HomeAssistant, gateway_sn: str) -> None:
    """代答成功后的转正看守（v1.7.30 ③）：30s 未转正且无待确认卡片 → WARNING。

    旧症状"固件停发 001 但设备列表永不出现"只有 INFO 留痕——现场 WARNING+
    级日志采集根本看不见（0917 取证铁律：归因行必须 WARNING），故障被代答
    的"成功表象"抹掉。看守区分两种停发：
    - discovery 卡片已挂起等用户确认（第二台网关的正常形态）→ 不打扰；
    - 代答后既无条目也无卡片（发现/转正链静默断）→ loud 告警指排障方向。
    每 SN 10 分钟窗口只起一个看守、最多留一条痕（防每 5s 重试刷屏）。
    """
    runtime = hass.data.setdefault(DOMAIN, {})
    watched = runtime.setdefault("_ear_promotion_watched", {})
    now = time.monotonic()
    for stale in [k for k, ts in watched.items() if now - ts > EAR_PROMOTION_WATCH_LOG_TTL]:
        watched.pop(stale, None)
    key = str(gateway_sn).lower()
    if key in watched:
        return
    watched[key] = now

    async def _check():
        from .const import CONF_GATEWAY_SN
        try:
            await asyncio.sleep(EAR_PROMOTION_WATCH_SECONDS)
            if getattr(hass, "is_stopping", False):
                return
            for entry in hass.config_entries.async_entries(DOMAIN):
                if str((getattr(entry, "data", None) or {}).get(
                        CONF_GATEWAY_SN, "")).lower() == key:
                    return  # 已转正——正常，静默退场
            try:
                for flow in hass.config_entries.flow.async_progress():
                    ctx = flow.get("context") or {}
                    if (flow.get("handler") == DOMAIN
                            and str(ctx.get("unique_id") or "").lower() == key):
                        return  # 发现卡片挂起待确认——正常形态，不误报
            except Exception:  # noqa: BLE001 — flow 查询失败按"无卡片"从严处理
                pass
            _LOGGER.warning(
                "网关 %s 获耳朵代答 001 后 %ds 未转为配置条目、且无待确认发现卡片"
                "——绑定停在发现/转正链（检查 设置→设备与服务 的发现卡与「HA MQTT "
                "通道」就绪态），本留痕每网关 10 分钟去重",
                gateway_sn, int(EAR_PROMOTION_WATCH_SECONDS),
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — 看守绝不反噬代答主流程
            _LOGGER.debug("网关 %s 转正看守异常（忽略）", gateway_sn, exc_info=True)

    tasks = runtime.setdefault("_ear_watch_tasks", set())
    task = hass.async_create_task(_check(), name=f"{DOMAIN}_ear_promotion_watch_{key}")
    tasks.add(task)
    task.add_done_callback(tasks.discard)


async def async_ear_ack_001_arbitrated(hass: HomeAssistant, gateway_sn: str,
                                       msg_id: Any) -> bool:
    """两处耳朵的统一代答入口（v1.7.30）：认领 → 发布 → 转正看守。

    返回 True 仅当本调用实际发布了代答；被仲裁抑制与发布失败都返回 False。
    调用方不得再直接 await async_ack_gateway_001（守卫反钉），否则 N+1
    重复应答面复活。
    """
    if not ear_ack_claim(hass, gateway_sn, msg_id):
        _LOGGER.debug("001 代答被仲裁抑制（另一耳朵已答）: sn=%s id=%s",
                      gateway_sn, msg_id)
        return False
    ok = await async_ack_gateway_001(hass, gateway_sn, msg_id)
    if ok:
        _watch_ear_promotion(hass, gateway_sn)
    return ok


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
    （device_registry.async_get、async_get_device、entity_registry.async_get 等）
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