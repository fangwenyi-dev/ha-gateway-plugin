"""慧尖一体化插件 — HA 与内置 Mosquitto 的 MQTT 连接自动引导。

背景：插件的 run.sh 启动时会把内置 Mosquitto 的连接信息写入 HA 配置目录下的
``window_controller_gateway_mqtt_bootstrap.json``。本模块在集成侧消费该标记：

1. HA 中已存在 MQTT 配置条目（用户自行配置过其他 Broker）→ 尊重现状，删除标记。
   若已配置的 Broker 与内置 Broker 不一致，输出明确告警帮助定位"网关上报发到了
   内置 Broker 而 HA 却连接着别的 Broker"的分裂脑问题。
2. 不存在 MQTT 条目且标记存在 → 通过程序化 config flow 自动创建指向内置
   Mosquitto 的配置条目，成功后删除标记。

独立安装（HACS）场景下不存在标记文件，所有函数立即返回，行为与旧版完全一致。

为什么不用 REST API（历史方案的失败原因）：HA Core 的 REST API 从未提供"创建
配置条目"的端点——``/api/config/config_entries/entry`` 仅支持 GET 列表，
``/api/config/config_entries/entry/{entry_id}`` 仅支持 DELETE。插件容器无论用
何种有效 token 调 POST 都不可能成功。而本模块运行在 HA Core 进程内部，直接调用
稳定的 Python API（config flow），无认证、无代理、无版本兼容问题。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

BOOTSTRAP_FILENAME = "window_controller_gateway_mqtt_bootstrap.json"

# 模块级锁：多个 entry / 配置流并发触发时只创建一次 MQTT 条目。
# 与 persist.py 相同的模式：HA 单事件循环内安全；asyncio.Lock 延迟绑定事件循环。
_create_lock: Optional[asyncio.Lock] = None


def _get_lock() -> asyncio.Lock:
    """惰性创建模块级锁（避免在导入期绑定事件循环）。"""
    global _create_lock
    if _create_lock is None:
        _create_lock = asyncio.Lock()
    return _create_lock


def _read_marker(path: str) -> Optional[Dict[str, Any]]:
    """读取引导标记文件；不存在或不可解析时返回 None。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as err:
        _LOGGER.warning("MQTT 引导标记文件无法读取（忽略）: %s", err)
        return None
    return data if isinstance(data, dict) else None


def _remove_marker(path: str) -> None:
    """删除引导标记文件（内含凭据，用完即删）；失败仅记录不抛出。"""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as err:
        _LOGGER.warning("删除 MQTT 引导标记文件失败: %s", err)


async def _wait_for_mqtt_client(hass: HomeAssistant) -> bool:
    """等待 MQTT 客户端连接就绪，最多 30 秒。

    注意：async_wait_for_mqtt_client（2023.5+）不抛超时异常而是返回 False，
    必须检查布尔返回值；任何异常一律视为未就绪。
    """
    from homeassistant.components import mqtt

    wait_fn = getattr(mqtt, "async_wait_for_mqtt_client", None)
    if wait_fn is not None:
        try:
            return bool(await asyncio.wait_for(wait_fn(hass), timeout=30))
        except asyncio.TimeoutError:
            return False
        except Exception:  # noqa: BLE001 — mqtt 集成尚未就绪时辅助函数可能抛错
            _LOGGER.debug("async_wait_for_mqtt_client 异常，视为未就绪", exc_info=True)
            return False
    # 兜底：极老版本无该辅助函数时轮询 hass.data（mqtt 集成 setup 完成即写入）
    for _ in range(30):
        if hass.data.get("mqtt"):
            return True
        await asyncio.sleep(1)
    return hass.data.get("mqtt") is not None


def _ha_supports_broker_sections() -> bool:
    """检测当前 HA 是否为要求 other_settings 段的新版本（2026.8+/dev）。

    新版 mqtt config flow 的 broker 校验器直接索引 user_input[OTHER_SETTINGS]，
    缺失该键会抛 KeyError 导致 setup 进入 SETUP_ERROR（无重试）。
    """
    try:
        from homeassistant.const import __version__

        parts = str(__version__).split(".")[:2]
        major, minor = int(parts[0]), int(parts[1])
        return (major, minor) >= (2026, 8)
    except (ImportError, ValueError, IndexError):
        return False


async def _quietly_abort_flow(hass: HomeAssistant, flow_id: str) -> None:
    """中止残留的进行中流程，避免每次重试都堆积一个悬挂 flow。"""
    try:
        await hass.config_entries.flow.async_abort(flow_id)
    except Exception:  # noqa: BLE001 — 流程可能已自行结束
        _LOGGER.debug("中止 MQTT 配置流程 %s 失败（可能已结束）", flow_id)


async def _update_mqtt_entry(
    hass: HomeAssistant, entry: Any, broker: str, port: int,
    username: Optional[str], password: Optional[str],
) -> None:
    """更新已有 MQTT 配置条目的 broker 连接信息。

    一体化插件场景：用户安装插件后，可能已有其他 broker 的 MQTT 条目
    （如官方 Mosquitto 插件、EMQX 等）。本函数将该条目更新为指向
    插件内置 broker，确保 HA 能接收到 LoRa 网关的数据。
    """
    new_data = dict(entry.data)
    new_data["broker"] = broker
    new_data["port"] = port
    if username is not None:
        new_data["username"] = username
    if password is not None:
        new_data["password"] = password
    hass.config_entries.async_update_entry(entry, data=new_data)
    _LOGGER.info(
        "已将 MQTT 配置条目 %s 更新为内置 Broker %s:%s",
        entry.entry_id, broker, port,
    )


async def ensure_mqtt_connection(hass: HomeAssistant) -> None:
    """确保 HA 的 MQTT 集成已连接到内置 Broker（需要时自动创建/更新配置条目）。

    - 标记不存在（HACS 独立安装等场景）→ 立即返回，不做任何事。
    - 已有 MQTT 条目但 broker 地址不一致 → 自动更新为内置 Broker 地址。
    - 已有 MQTT 条目且地址一致 → 保持现状，删除标记。
    - 无条目且有标记 → 程序化运行 mqtt config flow 创建条目并等待连接。

    抛出 :class:`ConfigEntryNotReady` 表示暂时无法完成（典型为内置 Broker 尚未
    就绪），调用方应让 setup 流程稍后自动重试。
    """
    marker_path = hass.config.path(BOOTSTRAP_FILENAME)
    data = await hass.async_add_executor_job(_read_marker, marker_path)

    # 无标记：非一体化安装或插件未启用 auto_setup_ha_mqtt —— 保持旧行为
    if data is None:
        return

    broker = str(data.get("broker") or "").strip()
    try:
        port = int(data.get("port") or 1883)
    except (TypeError, ValueError):
        port = 1883
    username = data.get("username") or None
    password = data.get("password") or None

    existing_entries = hass.config_entries.async_entries("mqtt")

    if existing_entries:
        first = existing_entries[0]
        cur_broker = first.data.get("broker")
        cur_port = first.data.get("port")

        if cur_broker == broker and str(cur_port) == str(port):
            _LOGGER.debug(
                "MQTT 配置条目已指向内置 Broker %s:%s，无需更新",
                broker, port,
            )
            await hass.async_add_executor_job(_remove_marker, marker_path)
            return

        # broker 地址不一致，需要更新
        _LOGGER.warning(
            "MQTT 集成已连接到 %s:%s，但本插件内置 Broker 为 %s:%s；"
            "正在自动更新 MQTT 配置条目以使用内置 Broker。",
            cur_broker, cur_port, broker, port,
        )

        # source=hassio 条目由 Supervisor 管理，async_update_entry 的数据
        # 会在 reload 时被 Supervisor 覆盖回原 broker 地址。
        # 禁用（disabled_by）也不行——MQTT config flow 的 _async_current_entries()
        # 仍会返回 disabled 条目，触发 single_instance_allowed 中止。
        # 唯一方案：删除 hassio 条目 → 走下方 create_new_entry 路径。
        if getattr(first, "source", None) == "hassio":
            _LOGGER.warning(
                "MQTT 条目 %s 由 Supervisor 管理 (source=hassio)，"
                "删除后创建新的 USER 源条目指向内置 Broker。",
                first.entry_id,
            )
            try:
                await hass.config_entries.async_remove(first.entry_id)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("删除 hassio MQTT 条目失败: %s", err)
                await hass.async_add_executor_job(_remove_marker, marker_path)
                return
            # 不删标记——让后续 create_new_entry 路径接管
        else:
            # 非 hassio 条目（用户手动创建等）：直接更新数据
            await _update_mqtt_entry(hass, first, broker, port, username, password)
            await hass.config_entries.async_reload(first.entry_id)
            _LOGGER.info("等待 MQTT 客户端重连到内置 Broker...")
            if not await _wait_for_mqtt_client(hass):
                _LOGGER.warning("MQTT 客户端重连超时，但配置已更新，继续启动")
            await hass.async_add_executor_job(_remove_marker, marker_path)
            return

    if not broker:
        _LOGGER.warning("MQTT 引导标记缺少 broker 字段，跳过自动配置")
        await hass.async_add_executor_job(_remove_marker, marker_path)
        return

    async with _get_lock():
        # 双重检查：等待锁期间可能已被并发触发的流程创建。
        # hassio 条目已在上方被删除（async_remove），此处只检查是否还有其他活跃条目。
        if hass.config_entries.async_entries("mqtt"):
            await hass.async_add_executor_job(_remove_marker, marker_path)
            return

        from homeassistant.config_entries import SOURCE_USER
        from homeassistant.data_entry_flow import FlowResultType

        _LOGGER.info(
            "检测到插件引导标记，正在自动创建 MQTT 配置条目 (%s:%s)", broker, port
        )
        result = await hass.config_entries.flow.async_init(
            "mqtt", context={"source": SOURCE_USER}
        )
        flow_id = result["flow_id"]

        # 2024.9+ 在 Supervisor 环境（HAOS/Supervised，即本插件的运行环境）下，
        # mqtt 的 user 步骤返回菜单（addon/broker）而非表单；必须显式导航到
        # "broker" 子步骤。Core 容器安装则直接返回 broker 表单。
        if result.get("type") == FlowResultType.MENU:
            result = await hass.config_entries.flow.async_configure(
                flow_id, user_input={"next_step_id": "broker"}
            )

        result_type = result.get("type")
        if result_type != FlowResultType.FORM:
            await _quietly_abort_flow(hass, flow_id)
            raise ConfigEntryNotReady(
                f"MQTT 配置流程未能进入表单步骤（type={result_type}）"
            )

        user_input: Dict[str, Any] = {"broker": broker, "port": port}
        if username:
            user_input["username"] = username
        if password:
            user_input["password"] = password

        # 新版（2026.8+/dev）要求 other_settings 段，缺失会在校验时抛 KeyError；
        # 旧版 schema 不认识该键，按版本探测决定是否附带。
        if _ha_supports_broker_sections():
            user_input["other_settings"] = {
                "set_ca_cert": "off",
                "set_client_cert": False,
                "transport": "tcp",
            }

        try:
            result = await hass.config_entries.flow.async_configure(
                flow_id, user_input=user_input
            )
        except Exception as err:  # noqa: BLE001 — 校验器内部异常不能炸掉 setup
            await _quietly_abort_flow(hass, flow_id)
            _LOGGER.warning("提交 MQTT 配置流程失败: %s", err)
            raise ConfigEntryNotReady(f"MQTT 配置流程提交失败，稍后重试") from err

        result_type = result.get("type")

        if result_type == FlowResultType.CREATE_ENTRY:
            _LOGGER.info("已自动创建 MQTT 配置条目，等待客户端连接…")
            if not await _wait_for_mqtt_client(hass):
                # 条目已创建，仅客户端暂未连上（Broker 可能仍在启动）。
                # 不回滚：订阅层具备重试机制；删除标记避免重复创建。
                _LOGGER.warning("MQTT 客户端 30 秒内未完成连接，将继续启动")
            await hass.async_add_executor_job(_remove_marker, marker_path)
            return

        if result_type == FlowResultType.ABORT:
            reason = result.get("reason")
            if reason == "single_instance_allowed":
                # 已有 MQTT 条目（或 HA 核心层单实例拦截）：按已存在处理
                _LOGGER.info("MQTT 配置流程中止（%s），视为已有配置", reason)
                await hass.async_add_executor_job(_remove_marker, marker_path)
                return
            # 其他中止原因：保守处理——保留标记待下次重试
            _LOGGER.warning(
                "MQTT 配置流程意外中止（reason=%s），保留引导标记待下次重试",
                reason,
            )
            raise ConfigEntryNotReady(f"MQTT 配置流程中止（{reason}），稍后重试")

        # 表单校验失败（典型为 cannot_connect：内置 Broker 尚未就绪）
        errors = result.get("errors") or {}
        _LOGGER.warning(
            "自动创建 MQTT 条目未成功（errors=%s），保留引导标记待下次重试",
            errors,
        )
        await _quietly_abort_flow(hass, flow_id)
        raise ConfigEntryNotReady(
            f"自动连接 MQTT 失败（{errors.get('base') or '未知原因'}），稍后自动重试"
        )
