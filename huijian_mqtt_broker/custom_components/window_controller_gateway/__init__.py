"""开窗器网关集成"""
import logging
import asyncio
from datetime import timedelta
from typing import Any, Dict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform, EVENT_HOMEASSISTANT_STOP
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    DOMAIN, 
    CONF_GATEWAY_SN, 
    CONF_GATEWAY_NAME,
    DEFAULT_GATEWAY_NAME,
    SCAN_INTERVAL,
    DEVICE_TO_GATEWAY_MAPPING,
    GLOBAL_MANUALLY_REMOVED_DEVICES,
    DEVICE_SETPOINTS,
    RESTART_DELAY,
)
from .persist import load_persistent_data, save_persistent_data
from .services import register_services
from .api import async_setup_api
from .utils import is_mqtt_loaded

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.NUMBER, Platform.SENSOR, Platform.COVER]

# 发现平台名称
DISCOVERY_PLATFORM = "window_controller_gateway"

# 记录已开启 debug_logging 的配置条目。
# 模块 logger 由多个 entry 共享，直接 setLevel 会互相覆盖且在卸载后不恢复，
# 因此用引用计数：任一 entry 开启则 DEBUG，全部关闭/卸载后恢复 NOTSET（继承 HA logger 配置）。
_debug_logging_entries: set = set()



async def async_setup(hass: HomeAssistant, config: Dict[str, Any]) -> bool:
    """设置集成 - Home Assistant调用此函数加载集成"""
    _LOGGER.info("=== 开窗器网关集成初始化 ===")
    hass.data.setdefault(DOMAIN, {})
    
    # 初始化全局设备到网关映射表
    hass.data[DOMAIN].setdefault(DEVICE_TO_GATEWAY_MAPPING, {})
    hass.data[DOMAIN].setdefault(GLOBAL_MANUALLY_REMOVED_DEVICES, set())
    hass.data[DOMAIN].setdefault(DEVICE_SETPOINTS, {})
    
    # 加载持久化数据
    await load_persistent_data(hass)
    
    # 设置发现平台
    try:
        from .discovery import async_setup_discovery_platform
        await async_setup_discovery_platform(hass)
        _LOGGER.info("开窗器网关发现平台设置成功")
    except Exception as e:
        _LOGGER.error("设置开窗器网关发现平台失败: %s", e)
    

    if not register_services(hass):
        return False

    # 注册供插件 Web UI 调用的设备列表 REST 端点。
    # 背景：HA Core 仅通过 WebSocket 暴露 device_registry（config/device_registry/list），
    # 不提供 REST 端点；而插件 Web UI（ingress）只能经 Supervisor 代理走 REST
    # （/api/ha/ -> http://supervisor/core/api/）。此视图在 HA 内部序列化设备注册表，
    # 使 Web UI 能列出某配置条目下的网关（父）与子设备。
    async_setup_api(hass)

    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """设置配置条目

    支持两种模式：
    - 有 gateway_sn：完整设置（MQTT + 设备管理器）
    - 无 gateway_sn：最小设置（仅注册平台），等待用户通过选项页或自动发现添加网关
    """
    gateway_sn = entry.data.get(CONF_GATEWAY_SN, "")
    _LOGGER.info("=== 开始设置配置条目: %s, gateway: %s ===", entry.entry_id, gateway_sn or "(待配置)")
    
    try:
        from .device_manager import WindowControllerDeviceManager
        from .mqtt_handler import WindowControllerMQTTHandler
    except ImportError as e:
        _LOGGER.critical("导入核心模块失败: %s", e)
        return False

    # ---- 无网关 SN：最小设置，等待后续配置 ----
    if not gateway_sn:
        _LOGGER.info("网关 SN 未配置，进入等待模式（可通过选项页或自动发现添加）")
        hass.data[DOMAIN].setdefault(entry.entry_id, {})
        hass.data[DOMAIN][entry.entry_id]["gateway_sn"] = ""
        hass.data[DOMAIN][entry.entry_id]["_awaiting_gateway"] = True
        # 无网关 SN：不 forward 任何平台实体。
        # 历史实现 forward 了 4 个空平台，但各平台 async_setup_entry 在
        # device_manager 缺失时会打 error 日志（"设备管理器未找到"），
        # 且与完整 PLATFORMS 的卸载集合不一致。config entry 的加载状态
        # 由 async_setup_entry 返回值决定，与是否 forward 平台无关，
        # 因此 forward 空列表即可。
        # v1.7.12（第 6 轮审计 E-6）注释订正：旧尾句"卸载时 PLATFORMS 对未
        # 加载平台是安全 no-op"已被 v1.7.11 真栈证伪——HA≥2024 平台组件对
        # never-loaded 条目 async_unload_entry 抛 ValueError "Config entry
        # was never loaded!"（ERROR 风暴），卸载必须按 _platforms_forwarded
        # 实际转发记录门禁（见 :356 定义与卸载分支），勿回退。

        # 轻量级心跳监听器：订阅 gateway/rpt_rsp，发现新网关时自动触发发现流程
        # 这让"先装集成、后上电网关"的自动发现流程成为可能
        try:
            from .const import TOPIC_GATEWAY_RSP
            from .discovery import async_discover_gateway

            _unsub_heartbeat = None

            async def _heartbeat_listener(msg):
                """监听网关心跳，触发自动发现"""
                try:
                    import json
                    payload = json.loads(msg.payload)
                    if "head" not in payload or "ctype" not in payload:
                        return
                    response_sn = payload.get("sn")
                    if not response_sn or not isinstance(response_sn, (str, int, float)):
                        return
                    if isinstance(response_sn, bool):
                        return
                    response_sn = str(response_sn)
                    import re
                    if not re.match(r"^[a-zA-Z0-9]{10,}$", response_sn):
                        return

                    # 检查是否已配置
                    for e in hass.config_entries.async_entries(DOMAIN):
                        if e.data.get(CONF_GATEWAY_SN, "").lower() == response_sn.lower():
                            return

                    gateway_name = f"慧尖网关 {response_sn[-4:]}"
                    _LOGGER.info("心跳监听器发现新网关: %s (SN: %s)", gateway_name, response_sn)
                    await async_discover_gateway(hass, response_sn, gateway_name)
                except Exception as e:
                    _LOGGER.debug("心跳监听器处理消息出错: %s", e)

            # v1.7.11：awaiting 条目自身也要驱动 MQTT bootstrap——客户可能
            # 从未走过 config_flow（快速发现代理建的正是这种零交互等待条目），
            # 干净主机上 mqtt 条目不存在时心跳监听器会等 120s 超时失效，
            # 整条自动发现链静默断掉。语义与 config_flow 空 SN 分支同款：
            # 尽力而为，失败不阻塞（稍后就绪即可，武装任务会等到）。
            try:
                from .mqtt_bootstrap import ensure_mqtt_connection
                await ensure_mqtt_connection(hass)
            except ConfigEntryNotReady:
                pass  # broker 稍后就绪（加载项启动竞态窗口），武装任务兜底
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("等待模式 MQTT 引导异常（不阻塞，后台武装兜底）: %s", e)

            _subscribed_now = False
            if is_mqtt_loaded(hass):
                from homeassistant.components import mqtt as mqtt_comp
                # v1.7.12（第 6 轮审计 CF-F4）：即时订阅单独兜异常——旧版
                # subscribe 抛错直接落最外层 except，else 分支的后台武装被
                # 整体跳过，本条目生命周期内自动发现静默死亡。失败转入武装
                # 重试路径（同下方 A-2 设计）。
                try:
                    _unsub_heartbeat = await mqtt_comp.async_subscribe(
                        hass, TOPIC_GATEWAY_RSP, _heartbeat_listener, 1
                    )
                    hass.data[DOMAIN][entry.entry_id]["_unsub_heartbeat"] = _unsub_heartbeat
                    _LOGGER.info("已启动网关心跳监听器，等待网关上电...")
                    _subscribed_now = True
                except Exception as sub_e:  # noqa: BLE001
                    _LOGGER.warning(
                        "心跳即时订阅失败（%s），转入后台武装重试", sub_e)

            if not _subscribed_now:
                # v1.6.26（第八轮审计 A-2）：旧实现只武装一次——加载项首启的
                # 典型时序里 MQTT 条目由本集成的 bootstrap 稍后异步创建，
                # is_mqtt_loaded 此刻为假即永久放弃，自动发现整链静默失效。
                # 改为后台任务等待 MQTT 就绪后再订阅（进 _bg_tasks，卸载/
                # 重载时统一取消；订阅前后双重检查条目数据仍在，防悬挂资源）。
                async def _arm_heartbeat_when_mqtt_ready():
                    from homeassistant.components import mqtt as mqtt_comp
                    from .utils import async_wait_mqtt_loaded
                    if not await async_wait_mqtt_loaded(hass, timeout=120.0):
                        _LOGGER.warning(
                            "等待 MQTT 集成 120s 仍未就绪，心跳监听器未武装"
                            "（网关需在集成页手动添加 SN，MQTT 恢复后重载条目即可）"
                        )
                        return
                    data_now = hass.data.get(DOMAIN, {}).get(entry.entry_id)
                    if data_now is None:
                        return  # 条目已卸载/重载，放弃武装
                    # v1.7.12（审计 CF-F4）：武装协程内订阅同样兜异常——旧版
                    # subscribe 抛错=task 未检索异常静默放弃，本条目再无人监听
                    try:
                        unsub = await mqtt_comp.async_subscribe(
                            hass, TOPIC_GATEWAY_RSP, _heartbeat_listener, 1
                        )
                    except Exception as sub_e:  # noqa: BLE001
                        _LOGGER.warning(
                            "心跳武装订阅失败（网关需手动添加 SN，或重载本条目）: %s",
                            sub_e)
                        return
                    data_now = hass.data.get(DOMAIN, {}).get(entry.entry_id)
                    if data_now is None:
                        if unsub:
                            unsub()
                        return
                    if unsub:
                        data_now["_unsub_heartbeat"] = unsub
                        _LOGGER.info("MQTT 就绪，已补装网关心跳监听器，等待网关上电...")

                _arm_task = hass.async_create_task(
                    _arm_heartbeat_when_mqtt_ready(),
                    name=f"{DOMAIN}_heartbeat_arm_{entry.entry_id}",
                )
                hass.data[DOMAIN][entry.entry_id].setdefault("_bg_tasks", []).append(_arm_task)
                _LOGGER.info("MQTT 尚未就绪，心跳监听器转入后台等待武装")
        except Exception as e:
            _LOGGER.warning("启动心跳监听器失败: %s（不影响手动添加）", e)

        # v1.6.26（第八轮审计 B-1）：awaiting 条目的唯一"转正"入口是
        # config_flow「添加网关」的 async_update_entry(data=+SN)——此前
        # update listener 只在完整设置分支注册，awaiting 条目改 data 后无人
        # 触发重载，配置静默不生效直至 HA 重启（v1.6.19 删显式 reload 时
        # 注释的"listener 已覆盖"前提对该分支为假）。按完整分支同款注册；
        # async_update_options 仅调 async_reload，awaiting 期重载是安全的。
        entry.async_on_unload(entry.add_update_listener(async_update_options))

        # v1.6.26（第八轮审计 A-3）：v1.6.16「半开口径」——条目存在即应监听
        # 9001（小程序可连、列表为空属正常）。awaiting-only 安装此前从不
        # 启动 WS 单例，小程序 mDNS 发现后恒 Connection refused。
        try:
            from .ws_gateway import async_ensure_ws_gateway
            await async_ensure_ws_gateway(hass)
        except Exception as e:
            _LOGGER.error("小程序 WS 网关检查失败（不影响其余功能）: %s", e, exc_info=True)

        return True

    # ---- 有网关 SN：完整设置 ----
    gateway_name = entry.data.get(CONF_GATEWAY_NAME, f"{DEFAULT_GATEWAY_NAME} {gateway_sn[-4:]}")
    
    device_manager = None
    mqtt_handler = None
    unsub_listeners = []

    try:
        # 先存储一个占位数据，确保平台设置时能够访问到基础数据
        hass.data[DOMAIN].setdefault(entry.entry_id, {})
        hass.data[DOMAIN][entry.entry_id]["gateway_sn"] = gateway_sn
        hass.data[DOMAIN][entry.entry_id]["gateway_name"] = gateway_name
        # v1.7.12（第 6 轮审计改进项）：删除死键 "_setup_in_progress"——
        # 全仓无任何读取方（含历史版本），纯占位误导维护者以为有防重入语义

        # 一体化插件：确保 MQTT 集成已建立连接（需要时按引导标记自动创建条目）。
        # 必须在创建 MQTT 处理器之前完成，否则订阅会因 MQTT 未就绪而失败。
        from .mqtt_bootstrap import ensure_mqtt_connection
        await ensure_mqtt_connection(hass)

        # 创建设备管理器
        _LOGGER.debug("正在创建设备管理器...")
        device_manager = WindowControllerDeviceManager(hass, entry)

        # 快速注册网关设备（立即返回，给用户即时反馈）
        _LOGGER.debug("正在注册网关设备实体...")
        await device_manager.register_gateway_device()

        # 创建MQTT处理器（快速初始化，不等待连接）
        _LOGGER.debug("正在创建MQTT处理器...")
        mqtt_handler = WindowControllerMQTTHandler(hass, gateway_sn, device_manager)
        mqtt_setup_ok = await mqtt_handler.setup()
        if not mqtt_setup_ok:
            _LOGGER.error("MQTT处理器初始化失败，MQTT集成可能未启用")
            raise ConfigEntryNotReady("MQTT集成未启用，请先在Home Assistant中启用MQTT集成")
        
        # 预先将 device_manager 和 mqtt_handler 存储到 entry_data
        # 确保在设备加载回调触发时，平台可以访问到这些对象
        hass.data[DOMAIN][entry.entry_id]["device_manager"] = device_manager
        hass.data[DOMAIN][entry.entry_id]["mqtt_handler"] = mqtt_handler
        hass.data[DOMAIN][entry.entry_id]["gateway_sn"] = gateway_sn
        hass.data[DOMAIN][entry.entry_id]["gateway_name"] = gateway_name

        # 立即加载设备（在平台设置之前）
        _LOGGER.info("正在加载已存在的设备: %s, entry_id: %s", gateway_sn, entry.entry_id)
        try:
            await device_manager.setup()
        except Exception as e:
            _LOGGER.error("加载设备失败: %s", e)
            import traceback
            _LOGGER.error("堆栈跟踪: %s", traceback.format_exc())
            # P1 修复：抛出 ConfigEntryNotReady 让 HA 知道 setup 失败并自动重试，
            # 而不是静默继续（集成"看似在线实则无设备"，永不重试）
            raise ConfigEntryNotReady(f"设备加载失败: {e}") from e
        
        # 检查设备加载结果
        devices = device_manager.get_all_devices()
        _LOGGER.info("设备加载完成，共 %d 个设备: %s", len(devices), [d.get("sn") for d in devices])

        # 获取配置选项
        options = entry.options
        discovery_interval = options.get("discovery_interval", SCAN_INTERVAL)
        debug_logging = options.get("debug_logging", False)
        
        # P1 修复：启用/禁用调试日志时使用引用计数控制模块 logger 级别。
        # 不再无条件 setLevel，避免多网关互相覆盖、卸载后不恢复。
        if debug_logging:
            _debug_logging_entries.add(entry.entry_id)
            _LOGGER.setLevel(logging.DEBUG)
            _LOGGER.info("调试日志已启用")
        else:
            _debug_logging_entries.discard(entry.entry_id)
            if not _debug_logging_entries:
                _LOGGER.setLevel(logging.NOTSET)  # 恢复为继承 HA logger 配置
                _LOGGER.info("调试日志已关闭（模块日志级别恢复为继承设置）")

        # 设置状态定期更新（取消定时设备发现，只保留连接检查）
        async def periodic_update(_now):
            """定期检查连接状态"""
            try:
                await mqtt_handler.check_connection()
            except Exception as e:
                _LOGGER.warning("定期连接检查时出错: %s", e)

        seconds = discovery_interval.total_seconds() if isinstance(discovery_interval, timedelta) else discovery_interval
        remove_interval = async_track_time_interval(hass, periodic_update, timedelta(seconds=seconds))
        unsub_listeners.append(remove_interval)

        # 更新完整运行数据
        entry_data = {
            "gateway_sn": gateway_sn,
            "gateway_name": gateway_name,
            "device_manager": device_manager,
            "mqtt_handler": mqtt_handler,
            "unsub_listeners": unsub_listeners,
            "_setup_complete": True
        }
        # 合并已有数据（保留平台可能附加的键，如 created_remove_buttons）
        previous = hass.data[DOMAIN].get(entry.entry_id, {})
        previous.update(entry_data)
        hass.data[DOMAIN][entry.entry_id] = previous

        # 恢复被 HA 自动禁用的实体（disabled_by="integration"）。
        # 背景：实体注册表中同一 unique_id 的平台/配置变迁（如旧版本按钮由其他
        # 平台创建、或升级后 domain 变化）会导致 HA 自动禁用实体，前端显示为
        # "已禁用"灰色。用户手动禁用的（disabled_by="user"）不做处理。
        # 必须在平台 forward 之前恢复，实体创建时即处于启用状态。
        try:
            entity_registry = er.async_get(hass)
            from .utils import call_registry_method as _call_reg
            restored_count = 0
            for entity_entry in list(entity_registry.entities.values()):
                if (entity_entry.platform == DOMAIN
                        and entity_entry.config_entry_id == entry.entry_id
                        and entity_entry.disabled_by is not None
                        and entity_entry.disabled_by != "user"):
                    await _call_reg(
                        entity_registry.async_update_entity,
                        entity_entry.entity_id, disabled_by=None
                    )
                    restored_count += 1
            if restored_count:
                _LOGGER.info("已恢复 %d 个被自动禁用的实体", restored_count)
        except Exception as e:
            _LOGGER.debug("恢复自动禁用实体失败（可忽略）: %s", e)

        # 设置平台（快速返回，不等待实体创建完成）
        _LOGGER.debug("正在设置前端平台组件...")
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        # v1.7.11：记录「本条目真的 forward 过平台」——async_unload_entry /
        # _cleanup_partial_setup 以此决定要不要按 PLATFORMS 卸载。awaiting
        # 条目从不 forward，硬编码卸载会让 HA≥2024 的平台组件对 never-loaded
        # 条目抛 ValueError "Config entry was never loaded!"，每个平台打一条
        # ERROR traceback（真栈实锤：代理自动填充触发的首个 reload 刷屏）。
        hass.data[DOMAIN][entry.entry_id]["_platforms_forwarded"] = True

        # 监听HA停止事件
        hass.data[DOMAIN][entry.entry_id]["_stop_unsub"] = hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _make_shutdown_handler(hass, entry))

        # P0 修复 Bug #1：注册选项更新监听器，使配置选项变更即时生效
        entry.async_on_unload(entry.add_update_listener(async_update_options))

        # 创建后台任务，延迟触发发现；任务引用存入 _bg_tasks 供卸载时取消，
        # 避免任务在条目卸载/重载后继续存活并访问已清理的对象
        _bg_task = hass.async_create_task(
            _background_initialization(hass, entry.entry_id, mqtt_handler),
            eager_start=True,
            name=f"{DOMAIN}_background_init_{entry.entry_id}",
        )
        hass.data[DOMAIN][entry.entry_id].setdefault("_bg_tasks", []).append(_bg_task)

        # ============ 自动设备迁移（替换网关流程）暂禁用 ============
        # 迁移功能先不使用：即使 entry.data 中带 migration_info（替换网关流程
        # 创建的 entry），也不再自动触发设备迁移。重新启用时取消下面注释。
        # _LOGGER.info("检查是否需要执行设备迁移，entry.data: %s", entry.data)
        # migration_info = entry.data.get("migration_info")
        # if migration_info:
        #     old_gateway_sn = migration_info.get("old_gateway_sn")
        #     remove_old_gateway = migration_info.get("remove_old_gateway", False)
        #     if old_gateway_sn and old_gateway_sn.lower() != gateway_sn.lower():
        #         hass.async_create_task(_migrate_devices_async(hass, old_gateway_sn, gateway_sn, remove_old_gateway), name=f"{DOMAIN}_migrate_{entry.entry_id}")

        # v1.6.15：小程序局域网 WS 网关——任一 entry 选项开启即启动单例，
        # 失败只记日志（不阻断集成其余功能）
        try:
            from .ws_gateway import async_ensure_ws_gateway
            await async_ensure_ws_gateway(hass)
        except Exception as e:
            _LOGGER.error("小程序 WS 网关检查失败（不影响其余功能）: %s", e, exc_info=True)

        _LOGGER.info("开窗器网关 [%s] 设置完成", gateway_name)
        return True

    except ConfigEntryNotReady:
        # 不二次包装：保留原始 ConfigEntryNotReady 的可重试提示信息（HA 会展示给用户）
        # 清理 debug_logging 引用计数，避免失败 entry 永久占用 DEBUG 级别
        _debug_logging_entries.discard(entry.entry_id)
        if not _debug_logging_entries:
            _LOGGER.setLevel(logging.NOTSET)
        await _cleanup_partial_setup(mqtt_handler, device_manager, unsub_listeners,
                                     hass=hass, entry=entry)
        # 清理残留的 entry 数据，避免重试时读到脏状态
        hass.data[DOMAIN].pop(entry.entry_id, None)
        _LOGGER.warning("设置网关 [%s] 失败（可重试），已清理部分初始化资源", gateway_name)
        raise
    except Exception as e:
        _LOGGER.error("设置网关 [%s] 过程中失败: %s", gateway_name, e, exc_info=True)
        # 清理 debug_logging 引用计数，避免失败 entry 永久占用 DEBUG 级别
        _debug_logging_entries.discard(entry.entry_id)
        if not _debug_logging_entries:
            _LOGGER.setLevel(logging.NOTSET)
        await _cleanup_partial_setup(mqtt_handler, device_manager, unsub_listeners,
                                     hass=hass, entry=entry)
        # 清理残留的 entry 数据，避免后续操作读到已清理的 manager 引用
        hass.data[DOMAIN].pop(entry.entry_id, None)
        return False

async def _cleanup_partial_setup(mqtt_handler, device_manager, unsub_listeners,
                                 hass=None, entry=None) -> None:
    """清理 async_setup_entry 中途失败时已创建的部分资源（幂等，各步骤独立容错）"""
    if mqtt_handler:
        try:
            await mqtt_handler.cleanup()
        except Exception as e:
            _LOGGER.debug("清理MQTT处理器异常: %s", e)
    if device_manager and hasattr(device_manager, 'cleanup'):
        try:
            await device_manager.cleanup()
        except Exception as e:
            _LOGGER.debug("清理设备管理器异常: %s", e)
    for unsub in (unsub_listeners or []):
        try:
            unsub()
        except Exception as e:
            _LOGGER.debug("取消监听器异常: %s", e)
    # v1.6.26（第八轮审计 A-1B）：forward 之后（:286 起）才抛异常的失败路径，
    # 5 个平台已加载——不清则僵尸实体持已 cleanup 的 manager/handler 引用，
    # "存在但永不更新"。v1.7.11 起以 _platforms_forwarded 为门禁：forward
    # 之前的失败（含 awaiting 分支复用清理）平台从未加载，HA 平台组件对
    # never-loaded 条目抛 ValueError 刷 ERROR traceback，必须跳过。
    if hass is not None and entry is not None:
        _rt = hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}
        if _rt.get("_platforms_forwarded"):
            try:
                await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
            except Exception as e:
                _LOGGER.debug("失败清理时卸载平台异常: %s", e)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载配置条目"""
    entry_id = entry.entry_id
    _LOGGER.info("正在卸载配置条目: %s", entry_id)

    if DOMAIN not in hass.data or entry_id not in hass.data[DOMAIN]:
        _LOGGER.debug("要卸载的条目 %s 未在数据中找到（可能已被清理），视为卸载成功", entry_id)
        return True

    data = hass.data[DOMAIN][entry_id]
    unload_successful = True

    # 0. 保存持久化数据（在清理之前）
    await save_persistent_data(hass)

    # 1. 取消停止事件监听器
    stop_unsub = data.get("_stop_unsub")
    if stop_unsub:
        try:
            stop_unsub()
        except Exception as e:
            _LOGGER.debug("取消停止监听器时出错: %s", e)

    # 1.1 取消心跳监听器（无 SN 模式下的自动发现）
    heartbeat_unsub = data.get("_unsub_heartbeat")
    if heartbeat_unsub:
        try:
            heartbeat_unsub()
            _LOGGER.debug("心跳监听器已取消")
        except Exception as e:
            _LOGGER.debug("取消心跳监听器时出错: %s", e)

    # 1.5 取消后台任务（_bg_tasks），避免任务在卸载后继续执行
    for bg_task in data.get("_bg_tasks", []):
        if bg_task and not bg_task.done():
            try:
                bg_task.cancel()
                try:
                    await bg_task
                except asyncio.CancelledError:
                    _LOGGER.debug("后台任务已取消")
                except Exception as e:
                    _LOGGER.debug("后台任务异常: %s", e)
            except Exception as e:
                _LOGGER.warning("取消后台任务时出错: %s", e)

    # 2. 先停止所有定时任务和监听器
    for unsub in data.get("unsub_listeners", []):
        try:
            unsub()
        except Exception as e:
            _LOGGER.warning("取消监听器时出错: %s", e)
            unload_successful = False

    # 2. 停止后台检查任务
    if "mqtt_handler" in data and data["mqtt_handler"]:
        if hasattr(data["mqtt_handler"], '_check_task') and data["mqtt_handler"]._check_task:
            try:
                data["mqtt_handler"]._check_task.cancel()
                try:
                    await data["mqtt_handler"]._check_task
                except asyncio.CancelledError:
                    _LOGGER.debug("MQTT检查任务已取消")
                except Exception as e:
                    _LOGGER.debug("MQTT检查任务异常: %s", e)
                _LOGGER.info("已停止MQTT后台检查任务")
            except Exception as e:
                _LOGGER.warning("停止MQTT后台检查任务时出错: %s", e)
                unload_successful = False

    # 3. 卸载平台实体（v1.7.11：仅对真 forward 过平台的条目执行——
    # awaiting 条目从未加载任何平台，强卸 PLATFORMS 会被 HA 平台组件对
    # never-loaded 条目抛 ValueError，每平台一条 ERROR traceback）
    if data.get("_platforms_forwarded"):
        try:
            await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
            _LOGGER.info("平台实体卸载完成")
        except Exception as e:
            _LOGGER.error("卸载平台时出错: %s", e)
            unload_successful = False
    else:
        _LOGGER.debug("本条目未 forward 平台（awaiting），跳过平台卸载")

    # 4. 清理MQTT处理器
    try:
        if "mqtt_handler" in data and data["mqtt_handler"]:
            await data["mqtt_handler"].cleanup()
            _LOGGER.info("MQTT处理器清理完成")
    except Exception as e:
        _LOGGER.error("清理MQTT处理器时出错: %s", e)
        unload_successful = False

    # 5. 清理设备管理器
    try:
        if "device_manager" in data and data["device_manager"]:
            await data["device_manager"].cleanup()
            _LOGGER.info("设备管理器清理完成")
    except Exception as e:
        _LOGGER.error("清理设备管理器时出错: %s", e)
        unload_successful = False

    # 6. 最后移除数据
    # 恢复调试日志引用计数：卸载的 entry 不再占用 DEBUG 级别
    if entry_id in _debug_logging_entries:
        _debug_logging_entries.discard(entry_id)
        if not _debug_logging_entries:
            _LOGGER.setLevel(logging.NOTSET)
    if unload_successful:
        hass.data[DOMAIN].pop(entry_id, None)
        _LOGGER.info("配置条目 %s 卸载成功", entry_id)
    else:
        _LOGGER.warning("配置条目 %s 卸载完成，但部分清理操作遇到问题", entry_id)

    # v1.6.15：本 entry 离场后重新聚合 WS 网关（全部关闭则停止单例；
    # 幂等，HA STOP 路径复用）
    try:
        from .ws_gateway import async_ensure_ws_gateway
        await async_ensure_ws_gateway(hass)
    except Exception as e:
        _LOGGER.warning("小程序 WS 网关状态同步失败: %s", e)

    return unload_successful

async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """更新配置选项"""
    _LOGGER.info("更新配置选项: %s", entry.entry_id)
    
    # 重新加载配置条目
    await hass.config_entries.async_reload(entry.entry_id)

async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """删除配置条目"""
    gateway_sn = entry.data.get(CONF_GATEWAY_SN, "unknown")
    _LOGGER.info("从配置中永久移除开窗器网关: %s", gateway_sn)
    
    # 重置该网关的发现去重/忽略记录，使删除后的网关可被再次自动发现。
    # 否则 announced_gateways 中残留的"已通知"记录会永久屏蔽该网关。
    try:
        discovery = hass.data[DOMAIN].get("discovery", {})
        gateway_key = gateway_sn.lower()
        discovery.setdefault("announced_gateways", set()).discard(gateway_key)
        discovery.setdefault("ignored_gateways", set()).discard(gateway_key)
        discovery.setdefault("last_discovery_time", {}).pop(gateway_key, None)
    except Exception as e:
        _LOGGER.debug("重置网关 %s 的发现记录失败（可忽略）: %s", gateway_sn, e)
    
    # 保存当前的持久化数据
    await save_persistent_data(hass)
    
    # 清理设备到网关映射表中属于该网关的映射关系
    # 否则这些设备会被永久锁死在已删除的网关上，无法被新网关发现和添加
    if DOMAIN in hass.data and DEVICE_TO_GATEWAY_MAPPING in hass.data[DOMAIN]:
        device_to_gateway_mapping = hass.data[DOMAIN][DEVICE_TO_GATEWAY_MAPPING]
        devices_to_remove = []
        
        # 找出所有映射到该网关的设备（大小写不敏感）
        for device_sn, mapped_gateway_sn in list(device_to_gateway_mapping.items()):
            if mapped_gateway_sn.lower() == gateway_sn.lower():
                devices_to_remove.append(device_sn)
                del device_to_gateway_mapping[device_sn]
        
        _LOGGER.info("已清理 %d 个设备的网关映射关系（网关 %s 已删除）", len(devices_to_remove), gateway_sn)
        
        # v1.7.12（第 6 轮审计 E-9）：这些子设备的速度/力度设定值同步清除——
        # 旧版残留 hass.data 与持久 JSON，同 SN 设备重配到其他网关时
        # number 实体回显陈旧设定值、误导用户以为已生效
        try:
            sp = hass.data[DOMAIN].get(DEVICE_SETPOINTS) or {}
            for dsn in devices_to_remove:
                sp.pop(dsn, None)
                for k in [k for k in sp if str(k).lower() == str(dsn).lower() and k != dsn]:
                    sp.pop(k, None)
        except Exception as spe:  # noqa: BLE001
            _LOGGER.warning("清理设备设定值失败（不影响删除流程）: %s", spe)
        
        # 保存更新后的持久化数据
        await save_persistent_data(hass)
    
    # 清理设备注册表中该网关的设备条目（含其下实体）。
    # 若残留，async_discover_gateway 的"已在设备注册表中"检查会永久屏蔽该网关，
    # 导致删除后的网关再也无法被自动发现，只能手动添加。
    gateway_device_id = None  # v1.6.12：子设备匹配用（删除前捕获）
    try:
        device_registry = dr.async_get(hass)
        gateway_device = device_registry.async_get_device(
            identifiers={(DOMAIN, gateway_sn)}
        )
        if gateway_device:
            gateway_device_id = gateway_device.id
            # 仅当该设备只关联到当前（被删除的）配置条目时才整删。
            # 若被其他 entry 共享（罕见：同 SN 多 entry），整删会误伤另一网关。
            # v1.6.12（第五轮审计 #6）：原读一个不存在的复数属性名——DeviceEntry 上
            # 从未有过它（正确为 config_entries/旧版 config_entry_id），
            # getattr 恒 None 使共享保护形同虚设，统一走 utils 双读兼容
            from .utils import get_device_config_entry_ids
            entry_ids = get_device_config_entry_ids(gateway_device)
            if entry_ids and entry_ids != {entry.entry_id}:
                _LOGGER.info(
                    "网关设备 %s 同时关联其他配置条目（%s），仅清理映射、保留设备注册表条目",
                    gateway_sn, sorted(entry_ids - {entry.entry_id}),
                )
            else:
                # 先删除该网关设备下的所有实体，避免留下孤儿实体
                from .utils import call_registry_method as _call_reg
                entity_registry = er.async_get(hass)
                for entity_entry in list(entity_registry.entities.values()):
                    if entity_entry.device_id == gateway_device.id:
                        await _call_reg(entity_registry.async_remove, entity_entry.entity_id)
                # 再删除网关设备条目本身
                await _call_reg(device_registry.async_remove_device, gateway_device.id)
                _LOGGER.info("已删除网关 %s 的设备注册表条目（含其下实体）", gateway_sn)
    except Exception as e:
        _LOGGER.error("删除网关 %s 的设备注册表条目失败: %s", gateway_sn, e)

    # 清理该网关的子设备注册表条目（via_device_id 指向该网关）。
    # 否则子设备条目残留为孤儿设备（config_entry 已删，无法被管理，脏数据）。
    # v1.6.12（第五轮审计 #6）：原读一个不存在的设备属性（hasattr/getattr 恒
    # None——测试钉桩见 tests/test_audit_round5.py 的静态扫描）
    # 不存在、恒 None，且旧值形态也非 (DOMAIN, sn) 元组，本段"意图 100% 落空"
    # 从未清理过任何子设备。改为按父设备 id 匹配（网关设备 id 已在上一步捕获，
    # 即便其注册表条目已被删，子设备 via_device_id 仍指向该 id，字符串可比）
    try:
        from .utils import call_registry_method as _call_reg
        from .utils import get_via_device_id
        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)
        for device in list(device_registry.devices.values()):
            via_id = get_via_device_id(device)
            if gateway_device_id and via_id == gateway_device_id:
                # 先删除该子设备下的实体（仅限属于被删除网关 entry 的实体），
                # 再删除设备条目本身
                for entity_entry in list(entity_registry.entities.values()):
                    if (entity_entry.device_id == device.id
                            and entity_entry.config_entry_id == entry.entry_id):
                        await _call_reg(entity_registry.async_remove, entity_entry.entity_id)
                await _call_reg(device_registry.async_remove_device, device.id)
                _LOGGER.info("已删除网关 %s 的子设备注册表条目: %s", gateway_sn, device.id)
    except Exception as e:
        _LOGGER.error("删除网关 %s 的子设备注册表条目失败: %s", gateway_sn, e)

    # v1.6.15：entry 此时已不在 config_entries 表中，重新聚合 WS 网关——
    # 删除最后一个（或唯一开启 WS 的）entry 后服务器必须停止，
    # 否则 9001 监听面在无任何网关时空转残留（unload 时机做不到：
    # 彼时本 entry 仍在表内，wanted 判定恒为开）
    try:
        from .ws_gateway import async_ensure_ws_gateway
        await async_ensure_ws_gateway(hass)
    except Exception as e:
        _LOGGER.warning("小程序 WS 网关状态同步失败（删除条目后）: %s", e)


async def _background_initialization(hass, entry_id, mqtt_handler):
    """后台初始化任务，不阻塞主流程"""
    try:
        await asyncio.sleep(0.5)
        # P0 守卫：条目已被卸载/重载（hass.data 中已无该条目数据）时
        # 直接返回，不访问已清理的 mqtt_handler 等对象。
        if DOMAIN not in hass.data or entry_id not in hass.data[DOMAIN]:
            _LOGGER.debug("后台初始化任务：条目 %s 已卸载，跳过初始化", entry_id)
            return
        _LOGGER.debug("后台任务：正在触发快速设备发现...")
        await mqtt_handler.fast_discovery()
        _LOGGER.debug("后台任务：初始化完成")
    except Exception as e:
        _LOGGER.warning("后台初始化任务出错: %s", e)


async def _migrate_devices_async(hass, old_gateway_sn, gateway_sn, remove_old_gateway):
    """异步执行设备迁移"""
    try:
        _LOGGER.info("开始异步设备迁移，旧网关: %s, 新网关: %s", old_gateway_sn, gateway_sn)
        await asyncio.sleep(RESTART_DELAY)

        # 执行迁移前清除 migration_info：防止迁移执行中（服务内会 reload）
        # 再次触发迁移形成循环。注意：async_update_entry 会经 add_update_listener
        # 触发 async_reload（异步任务），此处不可再显式 async_reload（会与
        # listener 的 reload 并发竞态），改为轮询等待该 entry 完成 reload。
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_GATEWAY_SN, "").lower() == gateway_sn.lower() and entry.data.get("migration_info"):
                new_data = {k: v for k, v in entry.data.items() if k != "migration_info"}
                hass.config_entries.async_update_entry(entry, data=new_data)
                _LOGGER.info("已清除 migration_info，等待重载完成")
                # 轮询等待 reload 完成（setup 完成后会写入 _setup_complete），
                # 避免与 listener 触发的 reload 并发；最多等待 5 秒
                for _ in range(25):
                    await asyncio.sleep(0.2)
                    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
                    if entry_data.get("_setup_complete"):
                        break
                break

        _LOGGER.info("调用迁移服务...")
        await hass.services.async_call(
            DOMAIN,
            "migrate_devices",
            {
                "old_gateway_sn": old_gateway_sn,
                "new_gateway_sn": gateway_sn,
                "remove_old_gateway": remove_old_gateway
            },
            blocking=True
        )
        _LOGGER.info("设备迁移任务已提交并完成")
    except Exception as e:
        _LOGGER.error("异步执行设备迁移失败: %s", e, exc_info=True)


def _make_shutdown_handler(hass, entry):
    """创建HA停止时的清理回调"""
    async def async_shutdown(event):
        _LOGGER.info("Home Assistant停止，保存持久化数据...")
        await save_persistent_data(hass)
        _LOGGER.info("Home Assistant停止，清理网关资源...")
        await async_unload_entry(hass, entry)
    return async_shutdown
