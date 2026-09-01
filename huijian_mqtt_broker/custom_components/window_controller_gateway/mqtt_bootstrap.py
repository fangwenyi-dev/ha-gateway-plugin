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
from homeassistant.data_entry_flow import InvalidData
from homeassistant.exceptions import ConfigEntryNotReady

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


def _marker_exists(path: str) -> bool:
    return os.path.isfile(path)


async def has_bootstrap_marker(hass: HomeAssistant) -> bool:
    """引导标记是否仍存在（True = 自动配置意图尚未确认完成）。

    v1.6.13：config flow 错误码分流使用——标记存在说明加载项已声明
    "要用内置 broker 自动配置 MQTT"，此时 MQTT 未就绪的根因通常是
    内置 broker 未启动/凭据被拒，应给 broker_not_ready 而非误导性的
    "请先启用 MQTT 集成"。检查失败按 False 处理（保守：宁可少一类等待，
    不可让门禁异常打断添加流程）。
    """
    try:
        return await hass.async_add_executor_job(
            _marker_exists, hass.config.path(BOOTSTRAP_FILENAME)
        )
    except Exception:  # noqa: BLE001 — 探针失败不改变主判定
        _LOGGER.debug("检查 MQTT 引导标记失败（按不存在处理）", exc_info=True)
        return False


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
    from .utils import is_mqtt_loaded
    for _ in range(30):
        if is_mqtt_loaded(hass):
            return True
        await asyncio.sleep(1)
    return is_mqtt_loaded(hass)


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


async def ensure_mqtt_connection(hass: HomeAssistant) -> Optional[bool]:
    """确保 HA 的 MQTT 集成已连接到内置 Broker（需要时自动创建/更新配置条目）。

    - 标记不存在（HACS 独立安装等场景）→ 立即返回，不做任何事。
    - 已有 MQTT 条目但 broker 地址不一致 → 自动更新为内置 Broker 地址。
    - 已有 MQTT 条目且地址一致 → 保持现状，删除标记。
    - 无条目且有标记 → 程序化运行 mqtt config flow 创建条目并等待连接。

    返回值契约（v1.6.13 审计#3：消除调用方重复等待）：
    - ``True``  已消耗过最长 30s 的连接等待且客户端就绪；
    - ``False`` 已消耗过最长 30s 的连接等待仍未就绪——调用方**不应**再
      自行宽限轮询（同一时段内不可能凭空就绪，只会白等）；
    - ``None``  本次未做连接等待（无标记 / 条目已匹配 / 无需动作），
      就绪与否由调用方自行判断。

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
        # v1.6.3：内置 Broker 固定监听 2022（见 mosquitto.conf/run.sh），
        # 旧回退值 1883 指向根本不监听的端口，属死配置
        port = int(data.get("port") or 2022)
    except (TypeError, ValueError):
        port = 2022
    username = data.get("username") or None
    password = data.get("password") or None

    existing_entries = hass.config_entries.async_entries("mqtt")

    if existing_entries:
        first = existing_entries[0]
        cur_broker = first.data.get("broker")
        cur_port = first.data.get("port")
        cur_username = first.data.get("username")

        # Bug5 修复：仅当 broker/port/username 全部一致才视为已配置完成。
        # 旧版插件把 ${USERNAME}（huijian）写入 bootstrap 标记，HA 集成用它连接；
        # 新版分离出 ha_mqtt 用户（ACL 全权限）。升级后旧条目 username 与标记
        # 不一致，必须走更新分支把用户名/密码刷成 ha_mqtt，否则 HA 集成继续用
        # 被收紧 ACL 的 huijian 连接，MQTT discovery 收不到消息。
        if (
            cur_broker == broker
            and str(cur_port) == str(port)
            and cur_username == username
        ):
            _LOGGER.debug(
                "MQTT 配置条目已指向内置 Broker %s:%s 且用户一致，无需更新",
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
            # 破坏性操作提示：删除用户已有的 MQTT 配置条目前，
            # 通过持久化通知明确告知用户，避免静默切断其现有 MQTT 连接
            # （如官方 Mosquitto 插件 / EMQX / 其他依赖该条目的集成）。
            try:
                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": "慧尖插件正在接管 MQTT 配置",
                        "message": (
                            "检测到已有 MQTT 配置条目（由 Supervisor 管理，"
                            f"broker: {cur_broker}:{cur_port}）。\n\n"
                            "慧尖一体化插件将删除该条目并创建指向内置 Broker "
                            f"({broker}:{port}) 的新条目，以确保 LoRa 网关数据可达。\n\n"
                            "若您有其他设备/集成依赖原 MQTT broker，请知悉："
                            "它们的连接将被切换到慧尖内置 broker。"
                        ),
                        "notification_id": "huijian_mqtt_takeover",
                    },
                    blocking=False,
                )
            except Exception as err:  # noqa: BLE001 — 通知失败不影响主流程
                _LOGGER.debug("发送 MQTT 接管通知失败（可忽略）: %s", err)
            try:
                await hass.config_entries.async_remove(first.entry_id)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "删除 hassio MQTT 条目失败: %s，降级为直接更新条目数据", err,
                )
                # 降级方案：虽然 Supervisor 可能会在 reload 时覆盖回原 broker，
                # 但至少在当前会话中让 MQTT 客户端连上内置 broker。
                # v1.6.13（审计#1a）：条目数据此刻已被改写为内置 broker——
                # "引导配置已落地"这一标记职责完成，无条件删标记；
                # 连不上属 MQTT 集成自身的重连职责（HA 内置退避重试），
                # 保留标记反而会与"匹配分支即删"的真实行为自相矛盾，
                # 并在 Supervisor 持续覆盖的极端场景下形成 reload 循环。
                # 返回值如实上报"等过一轮没成就"，调用方不必重复等待。
                await _update_mqtt_entry(hass, first, broker, port, username, password)
                await hass.config_entries.async_reload(first.entry_id)
                _LOGGER.info("等待 MQTT 客户端重连到内置 Broker（降级模式）...")
                await hass.async_add_executor_job(_remove_marker, marker_path)
                if not await _wait_for_mqtt_client(hass):
                    _LOGGER.warning("MQTT 客户端重连超时（降级模式），交由 MQTT 集成自动重试")
                    return False
                return True
            # 不删标记——让后续 create_new_entry 路径接管
        else:
            # 非 hassio 条目（用户手动创建等）：直接更新数据
            # v1.6.13（审计#1a）：同上——更新落地即删标记，连接归 MQTT 集成重试。
            await _update_mqtt_entry(hass, first, broker, port, username, password)
            await hass.config_entries.async_reload(first.entry_id)
            await hass.async_add_executor_job(_remove_marker, marker_path)
            _LOGGER.info("等待 MQTT 客户端重连到内置 Broker...")
            if not await _wait_for_mqtt_client(hass):
                _LOGGER.warning("MQTT 客户端重连超时，交由 MQTT 集成自动重试")
                return False
            return True

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

        # 自适应兼容新旧 HA 的 mqtt broker 表单 schema：
        # - 旧版（<2026.8）：不认识 other_settings 键，按不含该键提交即可；
        # - 2026.8.0-dev：broker 校验器直接索引 user_input[OTHER_SETTINGS]，
        #   缺失抛 KeyError；
        # - 2026.8 正式版：schema 改为 vol.Required(OTHER_SETTINGS)，缺失由
        #   data_entry_flow 包装成 InvalidData（v1.6.14 真机 E2E 实锤：客户
        #   HA≥2026.8 首添在健康 broker 下也必然 InvalidData→旧版误报
        #   mqtt_not_available）。两种异常都触发同一"补字段重试"。
        OTHER_SETTINGS = {
            "set_ca_cert": "off",
            "set_client_cert": False,
            "transport": "tcp",
        }
        try:
            try:
                result = await hass.config_entries.flow.async_configure(
                    flow_id, user_input=user_input
                )
            except (KeyError, InvalidData):
                # 新版 HA 要求 other_settings 段：补字段后重试一次
                if "other_settings" not in user_input:
                    user_input["other_settings"] = OTHER_SETTINGS
                    result = await hass.config_entries.flow.async_configure(
                        flow_id, user_input=user_input
                    )
                else:
                    raise
        except Exception as err:  # noqa: BLE001 — 校验器内部异常不能炸掉 setup
            await _quietly_abort_flow(hass, flow_id)
            _LOGGER.warning("提交 MQTT 配置流程失败: %s", err)
            raise ConfigEntryNotReady("MQTT 配置流程提交失败，稍后重试") from err

        result_type = result.get("type")

        if result_type == FlowResultType.CREATE_ENTRY:
            _LOGGER.info("已自动创建 MQTT 配置条目，等待客户端连接…")
            if not await _wait_for_mqtt_client(hass):
                # v1.6.13（客户现场"装完立刻添加网关必报 mqtt_not_available"
                # 根修）：条目已创建但客户端 30s 内没连上（内置 Broker 仍在
                # 启动）→ **保留标记**：条目若因 HA 版本差异未真正落地，
                # 下次 ensure 仍能重建；就绪语义 = 客户端真连上才算引导完成。
                # （审计#1 复核：本路径保留有独立价值，区别于更新/降级路径
                # ——后两者条目数据已落地且必然匹配，保留标记无消费出口。）
                _LOGGER.warning("MQTT 客户端 30 秒内未完成连接，保留引导标记待下次重试")
                return False
            await hass.async_add_executor_job(_remove_marker, marker_path)
            return True

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
