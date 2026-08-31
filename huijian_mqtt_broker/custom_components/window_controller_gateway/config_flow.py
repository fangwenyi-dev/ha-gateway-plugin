"""Window Controller Gateway Configuration Flow"""
import voluptuous as vol
import re
import logging
import asyncio
from typing import Any, Dict, Optional

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    DOMAIN, 
    CONF_GATEWAY_SN, 
    CONF_GATEWAY_NAME, 
    DEFAULT_GATEWAY_NAME,
    GATEWAY_CONNECT_TIMEOUT
)
from .mqtt_handler import WindowControllerMQTTHandler
from .mqtt_bootstrap import ensure_mqtt_connection
from .utils import is_mqtt_loaded

_LOGGER = logging.getLogger(__name__)

def validate_gateway_sn(sn: str) -> bool:
    """Validate gateway serial number format"""
    if not sn or len(sn) < 10:
        return False
    return bool(re.match(r'^[a-zA-Z0-9]+$', sn))

class MockDeviceManager:
    """用于连接测试的模拟设备管理器"""
    def __init__(self):
        self._manually_removed_devices = set()
    
    async def update_gateway_status(self, status):
        pass
    
    async def update_device_status(self, device_sn, status, attributes=None):
        pass
    
    def get_gateway_info(self):
        return {"name": "Test Gateway"}
    
    def get_all_devices(self):
        return []
    
    def get_device(self, device_sn):
        return None
    
    async def add_device(self, device_sn, device_name, device_type=None, force=False, is_manual_pairing=False):
        _LOGGER.debug("模拟添加设备: %s, 名称: %s, force: %s, is_manual_pairing: %s", device_sn, device_name, force, is_manual_pairing)
        return device_sn
    
    def is_device_manually_removed(self, device_sn):
        return device_sn in self._manually_removed_devices

    def allocate_device_number(self):
        # v1.6.11（审计 #6）：连接测试期间 handler 订阅真实生效，测试窗口内
        # 到达的 005 会走 _quick_add_device → allocate_device_number——本 mock
        # 缺该方法的 AttributeError 此前被消息循环兜底 except 吞掉（丢一帧
        # +日志噪音）。补齐契约面（返回值仅测试期占位，条目创建后真实 dm 接管）
        return 1


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configuration flow handler class"""
    VERSION = 1

    def __init__(self):
        """初始化配置流"""
        super().__init__()
        # 连接测试未通过时暂存用户输入，供确认步骤使用
        self._pending_gateway_sn = None
        self._pending_gateway_name = None

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Handle user step

        网关 SN 为可选项：用户可以先安装集成（点"下一步"），
        之后通过选项页面添加网关，或等待 MQTT 自动发现。
        """
        errors = {}

        # 从上下文中获取网关SN和名称（如果是从发现流程进入）
        gateway_sn_from_context = self.context.get("gateway_sn")
        gateway_name_from_context = self.context.get("gateway_name")

        if user_input is not None:
            raw_sn = user_input.get(CONF_GATEWAY_SN, "").strip()
            raw_name = user_input.get(CONF_GATEWAY_NAME, "").strip()

            if raw_sn:
                # ---- 有 SN：走原有的验证+连接测试流程 ----
                gateway_sn = raw_sn
                gateway_name = raw_name or f"{DEFAULT_GATEWAY_NAME} {gateway_sn[-4:]}"

                if not validate_gateway_sn(gateway_sn):
                    errors[CONF_GATEWAY_SN] = "invalid_sn_format"
                else:
                    # unique_id 统一小写，避免大小写不同导致重复添加
                    await self.async_set_unique_id(gateway_sn.lower())
                    self._abort_if_unique_id_configured()
                    for entry in self.hass.config_entries.async_entries(DOMAIN):
                        if entry.data.get(CONF_GATEWAY_SN, "").lower() == gateway_sn.lower():
                            return self.async_abort(reason="already_configured")

                    try:
                        try:
                            await ensure_mqtt_connection(self.hass)
                        except ConfigEntryNotReady:
                            errors["base"] = "mqtt_not_available"

                        if not is_mqtt_loaded(self.hass):
                            errors["base"] = "mqtt_not_available"
                        else:
                            connected = await self._test_gateway_connectivity(gateway_sn)
                            if not connected:
                                self._pending_gateway_sn = gateway_sn
                                self._pending_gateway_name = gateway_name
                                return await self.async_step_confirm_add()
                    except Exception:
                        errors["base"] = "cannot_connect"

                    if not errors:
                        return self.async_create_entry(
                            title=gateway_name,
                            data={
                                CONF_GATEWAY_SN: gateway_sn,
                                CONF_GATEWAY_NAME: gateway_name
                            }
                        )
            else:
                # ---- 无 SN：直接完成安装，网关待后续添加 ----
                try:
                    await ensure_mqtt_connection(self.hass)
                except ConfigEntryNotReady:
                    pass  # MQTT 稍后就绪即可，不阻塞安装

                return self.async_create_entry(
                    title="慧尖网关",
                    data={}
                )

        # ---- 表单 ----
        default_sn = gateway_sn_from_context or (user_input.get(CONF_GATEWAY_SN, "") if user_input else "")
        if default_sn:
            default_name = gateway_name_from_context or (user_input.get(CONF_GATEWAY_NAME, f"{DEFAULT_GATEWAY_NAME} {default_sn[-4:]}") if user_input else f"{DEFAULT_GATEWAY_NAME} {default_sn[-4:]}")
        else:
            default_name = gateway_name_from_context or (user_input.get(CONF_GATEWAY_NAME, DEFAULT_GATEWAY_NAME) if user_input else DEFAULT_GATEWAY_NAME)

        data_schema = vol.Schema({
            vol.Optional(
                CONF_GATEWAY_SN,
                description={"suggested_value": default_sn},
                default=default_sn
            ): str,
            vol.Optional(
                CONF_GATEWAY_NAME,
                description={"suggested_value": default_name},
                default=default_name
            ): str,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "example_sn": "100121501186",
                "min_length": "10"
            }
        )

    async def async_step_confirm_add(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """连接测试未通过时的确认步骤：允许用户仍然添加网关

        本集成无法主动探测网关（协议规定网关只能主动上报），
        连接测试只是"在窗口内等一次上报"。网关未上电/未连 MQTT/上报间隔较长
        都会导致测试失败，不应因此阻止用户添加。
        """
        if user_input is not None:
            if user_input.get("confirm", False):
                gateway_sn = self._pending_gateway_sn
                gateway_name = self._pending_gateway_name
                if not gateway_sn:
                    return self.async_abort(reason="invalid_input")
                # 再次检查唯一性（确认期间可能已被其他流程配置；unique_id 统一小写）
                await self.async_set_unique_id(gateway_sn.lower())
                self._abort_if_unique_id_configured()
                # 兜底：兼容历史大小写原样的 entry unique_id
                for entry in self.hass.config_entries.async_entries(DOMAIN):
                    if entry.data.get(CONF_GATEWAY_SN, "").lower() == gateway_sn.lower():
                        return self.async_abort(reason="already_configured")
                return self.async_create_entry(
                    title=gateway_name,
                    data={
                        CONF_GATEWAY_SN: gateway_sn,
                        CONF_GATEWAY_NAME: gateway_name
                    }
                )
            # 用户选择返回修改：把已输入的值带回表单
            self.context["gateway_sn"] = self._pending_gateway_sn
            self.context["gateway_name"] = self._pending_gateway_name
            return await self.async_step_user()

        return self.async_show_form(
            step_id="confirm_add",
            data_schema=vol.Schema({
                vol.Required("confirm", default=False): bool,
            }),
            description_placeholders={
                "gateway_sn": self._pending_gateway_sn or "",
            },
        )

    async def async_step_replace_gateway(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Handle gateway replacement flow - 暂不支持，提示用户"""
        return self.async_abort(
            reason="migration_not_supported",
            description_placeholders={"error": "迁移功能暂未启用，请手动删除旧网关后重新添加"}
        )

    async def async_step_discovery(self, discovery_info: Dict[str, Any]) -> FlowResult:
        """Handle discovery step"""
        _LOGGER.info("处理网关发现: %s", discovery_info)
        
        gateway_sn = discovery_info.get("gateway_sn")
        # 防御：gateway_sn 缺失时避免 `gateway_sn[-4:]` 直接 TypeError
        gateway_name = discovery_info.get("gateway_name")
        if not gateway_name:
            gateway_name = f"慧尖网关 {gateway_sn[-4:]}" if gateway_sn else DEFAULT_GATEWAY_NAME
        replace_mode = discovery_info.get("replace_mode", False)
        current_gateway_sn = discovery_info.get("current_gateway_sn")
        
        # 防御校验：SN 缺失或格式非法时直接中止发现流程
        # （避免 async_set_unique_id(None) 及后续用非法 SN 生成 MQTT 主题）
        if not isinstance(gateway_sn, str) or not validate_gateway_sn(gateway_sn):
            _LOGGER.warning("发现流程收到非法网关SN，中止: %r", gateway_sn)
            return self.async_abort(reason="invalid_sn_format")
        
        # 检查是否已配置（unique_id 统一小写，避免大小写不同导致重复添加）
        await self.async_set_unique_id(gateway_sn.lower())
        self._abort_if_unique_id_configured()
        
        # 检查是否已存在配置的网关
        existing_entries = self.hass.config_entries.async_entries(DOMAIN)

        # 迁移/替换功能暂禁用：即使已配置网关也不再强制进入替换流程，
        # 新发现的网关直接走正常添加流程（支持多网关并存）
        if replace_mode:
            # 替换模式（当前无流程设置该标志，保留分支结构备用）
            _LOGGER.info("检测到替换模式，进入替换流程")
            
            # 获取第一个已配置的网关信息或使用current_gateway_sn
            existing_gateway_sn = current_gateway_sn
            if not existing_gateway_sn and existing_entries:
                if len(existing_entries) > 1:
                    # 多个网关时，让用户选择替换哪个网关
                    _LOGGER.info("存在多个已配置的网关（%d个），让用户选择替换哪个", len(existing_entries))
                    self.context.update({
                        "gateway_sn": gateway_sn,
                        "gateway_name": gateway_name,
                        "title_placeholders": {"name": gateway_name},
                        "description_placeholders": {
                            "name": gateway_name,
                            "sn": gateway_sn
                        },
                        "suggested_display_name": gateway_name,
                        "source": "discovery",
                        "replace_mode": replace_mode
                    })
                    return await self.async_step_replace()
                existing_entry = existing_entries[0]
                existing_gateway_sn = existing_entry.data.get(CONF_GATEWAY_SN)
            
            # 设置上下文信息
            # device_id应该是旧网关的SN（已配置的网关）
            # old_gateway_sn是旧网关的SN（已配置的网关）
            self.context.update({
                "gateway_sn": gateway_sn,  # 新网关的SN
                "gateway_name": gateway_name,
                "device_id": existing_gateway_sn,  # 旧网关的SN
                "old_gateway_sn": existing_gateway_sn,  # 旧网关的SN
                "new_gateway_sn": gateway_sn,  # 新网关的SN
                "title_placeholders": {
                    "name": gateway_name
                },
                "description_placeholders": {
                    "name": gateway_name,
                    "sn": gateway_sn
                },
                "suggested_display_name": gateway_name,
                "source": "discovery",
                "replace_mode": replace_mode
            })
            
            # 进入替换流程
            return await self.async_step_confirm_migration()
        else:
            # 没有已配置的网关，进入添加流程
            _LOGGER.info("没有已配置的网关，进入添加流程")
            
            # 设置上下文信息，确保Home Assistant能够显示带有"忽略"按钮的发现卡片
            self.context.update({
                "gateway_sn": gateway_sn,
                "gateway_name": gateway_name,
                "title_placeholders": {
                    "name": gateway_name
                },
                "description_placeholders": {
                    "name": gateway_name,
                    "sn": gateway_sn
                },
                "suggested_display_name": gateway_name,
                "source": "discovery"
            })
            
            # 对于发现的设备，Home Assistant会自动显示"忽略"按钮
            # 我们只需要确保流程能够正确处理
            return await self.async_step_user()
    
    async def async_step_ignore(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Handle ignore step"""
        _LOGGER.info("忽略网关: %s", self.context.get("gateway_sn"))
        
        # 调用忽略网关的方法
        gateway_sn = self.context.get("gateway_sn")
        if gateway_sn:
            from .discovery import async_ignore_gateway
            await async_ignore_gateway(self.hass, gateway_sn)
        
        # 中止流程
        return self.async_abort(reason="ignored")

    async def async_step_confirm_migration(self, user_input=None):
        """确认迁移"""
        if user_input is not None:
            if user_input.get("confirm"):
                # 保存迁移信息到数据中，以便在配置条目设置完成后使用
                migration_info = {
                    "old_gateway_sn": self.context.get("old_gateway_sn", ""),
                    "remove_old_gateway": user_input.get("remove_old", False)
                }
                
                _LOGGER.info("保存迁移信息到数据: %s", migration_info)
                
                new_gateway_sn = self.context.get("new_gateway_sn", "")
                # 防御校验：即使从发现流程绕过 replace 步骤进入，
                # SN 也必须满足格式（长度 + 字符集），避免畸形 SN 生成非法 MQTT 主题
                if not new_gateway_sn or not validate_gateway_sn(new_gateway_sn):
                    _LOGGER.error("新网关SN格式无效，取消迁移: %r", new_gateway_sn)
                    return self.async_abort(reason="invalid_sn_format")
                existing_entries = self.hass.config_entries.async_entries(DOMAIN)
                existing_entry = None
                
                for entry in existing_entries:
                    if entry.data.get(CONF_GATEWAY_SN, "").lower() == new_gateway_sn.lower():
                        existing_entry = entry
                        break
                
                if existing_entry:
                    # 如果存在，更新该条目
                    _LOGGER.info("更新现有网关配置条目: %s", existing_entry.entry_id)
                    self.hass.config_entries.async_update_entry(
                        existing_entry,
                        data={
                            **existing_entry.data,
                            "migration_info": migration_info  # 将迁移信息保存到 data 中
                        }
                    )
                    # 重新加载配置条目
                    await self.hass.config_entries.async_reload(existing_entry.entry_id)
                    return self.async_abort(reason="updated_existing_gateway")
                else:
                    # 如果不存在，创建新条目
                    _LOGGER.info("创建新网关配置条目: %s", new_gateway_sn)
                    return self.async_create_entry(
                        title=self.context.get("gateway_name", f"慧尖网关 {new_gateway_sn[-4:]}"),
                        data={
                            CONF_GATEWAY_SN: new_gateway_sn,
                            CONF_GATEWAY_NAME: self.context.get("gateway_name", f"慧尖网关 {new_gateway_sn[-4:]}"),
                            "migration_info": migration_info  # 将迁移信息保存到 data 中
                        }
                    )
        
        # 显示确认表单
        return self.async_show_form(
            step_id="confirm_migration",
            data_schema=vol.Schema({
                vol.Required("confirm", default=False): bool,
                vol.Optional("remove_old", default=False): bool,
            }),
            description_placeholders={
                "old_gateway": self.context.get("old_gateway_name", self.context.get("old_gateway_sn", "未知")),
                "new_gateway": self.context.get("new_gateway_name", self.context.get("new_gateway_sn", "未知")),
                "device_count": self.context.get("device_count", "未知")
            }
        )

    async def _test_gateway_connectivity(self, gateway_sn: str) -> bool:
        """Test gateway connectivity"""
        _LOGGER.info("Testing gateway connectivity for SN: %s", gateway_sn)

        mqtt_handler = None
        try:
            # Check if MQTT integration is available
            if not is_mqtt_loaded(self.hass):
                _LOGGER.error("MQTT integration not available")
                return False

            mock_device_manager = MockDeviceManager()
            mqtt_handler = WindowControllerMQTTHandler(self.hass, gateway_sn, mock_device_manager)

            # Setup MQTT handler
            if not await mqtt_handler.setup():
                _LOGGER.error("Failed to setup MQTT handler")
                return False

            # 协议说明：002 是网关主动发起的上报，HA 发送 002 网关不会响应。
            # 连接验证改为：只检查 MQTT 订阅是否成功（setup 返回 True 即代表订阅成功），
            # 然后等待网关主动上报（网关在线时会主动发送 001/002 消息，
            # handle_gateway_response 会设置 connected=True）。
            # 不再发送无效的 002 发现命令。
            # await mqtt_handler.check_connection()  # 旧逻辑：发送 002，网关不响应

            # 轮询等待网关主动上报：一旦收到立即通过，最多等待 GATEWAY_CONNECT_TIMEOUT 秒。
            # 固定 sleep 会漏掉上报频率较低（心跳间隔长）但实际在线的网关。
            waited = 0.0
            poll_interval = 0.5
            while waited < GATEWAY_CONNECT_TIMEOUT and not mqtt_handler.connected:
                await asyncio.sleep(poll_interval)
                waited += poll_interval

            # 检查网关是否主动上报了消息（connected 由 handle_gateway_response 设置）
            connected = mqtt_handler.connected

            if connected:
                _LOGGER.info("Gateway connectivity test passed")
            else:
                _LOGGER.warning(
                    "Gateway connectivity test failed (no response within %.0f s)",
                    GATEWAY_CONNECT_TIMEOUT,
                )

            return connected

        except Exception as e:
            _LOGGER.error("Error testing gateway connectivity: %s", e)
            return False
        finally:
            if mqtt_handler:
                try:
                    await mqtt_handler.cleanup()
                except Exception as cleanup_e:
                    _LOGGER.debug("MQTT handler cleanup error: %s", cleanup_e)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Create options flow"""
        return OptionsFlow(config_entry)

    async def async_step_replace(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Handle gateway replacement step"""
        errors = {}
        
        # 从context中获取网关信息
        gateway_sn = self.context.get("gateway_sn")
        gateway_name = self.context.get("gateway_name", f"慧尖网关 {gateway_sn[-4:]}" if gateway_sn else "慧尖网关")
        old_gateway_sn_from_context = self.context.get("old_gateway_sn")
        replace_mode = self.context.get("replace_mode", False)

        # 获取所有已配置的网关
        existing_entries = self.hass.config_entries.async_entries(DOMAIN)
        gateway_options = {
            entry.data[CONF_GATEWAY_SN]: entry.data.get(CONF_GATEWAY_NAME, f"慧尖网关 {entry.data[CONF_GATEWAY_SN][-4:]}")
            for entry in existing_entries
        }

        # 如果只有1个网关，自动选中
        if len(gateway_options) == 1 and not old_gateway_sn_from_context:
            old_gateway_sn_from_context = list(gateway_options.keys())[0]
            _LOGGER.info("自动选中唯一网关: %s", old_gateway_sn_from_context)

        if user_input is not None:
            old_gateway_sn = user_input.get("old_gateway_sn")
            
            # 在替换模式下，新网关SN总是从上下文获取，不允许修改
            if replace_mode:
                new_gateway_sn = gateway_sn
            else:
                new_gateway_sn = user_input.get("new_gateway_sn", gateway_sn)  # 使用默认值（当前发现的网关）

            if not old_gateway_sn or not validate_gateway_sn(old_gateway_sn):
                errors["old_gateway_sn"] = "invalid_sn_format"
            elif not replace_mode and (not new_gateway_sn or not validate_gateway_sn(new_gateway_sn)):
                errors["new_gateway_sn"] = "invalid_sn_format"
            else:
                # 保存到上下文
                self.context["old_gateway_sn"] = old_gateway_sn
                self.context["new_gateway_sn"] = new_gateway_sn
                self.context["old_gateway_name"] = gateway_options.get(old_gateway_sn, f"慧尖网关 {old_gateway_sn[-4:]}")
                self.context["new_gateway_name"] = gateway_name
                
                # 进入确认迁移步骤
                return await self.async_step_confirm_migration()

        # 构建数据模式，确保替换时必须输入旧网关和新网关SN
        data_schema = vol.Schema({})
        
        # 添加旧网关SN字段，使用下拉选择器
        if gateway_options:
            data_schema = data_schema.extend({
                vol.Required(
                    "old_gateway_sn",
                    default=user_input.get("old_gateway_sn", old_gateway_sn_from_context or list(gateway_options.keys())[0]) if user_input else old_gateway_sn_from_context or list(gateway_options.keys())[0]
                ): vol.In(gateway_options),
            })
        else:
            data_schema = data_schema.extend({
                vol.Required(
                    "old_gateway_sn",
                    default=user_input.get("old_gateway_sn", old_gateway_sn_from_context or "") if user_input else old_gateway_sn_from_context or ""
                ): str,
            })
        
        # 如果不是替换模式，允许用户输入新网关SN
        if not replace_mode:
            data_schema = data_schema.extend({
                vol.Required(
                    "new_gateway_sn",
                    default=user_input.get("new_gateway_sn", gateway_sn) if user_input else gateway_sn
                ): str,
            })

        return self.async_show_form(
            step_id="replace",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "gateway_name": gateway_name,
                "new_gateway_sn": gateway_sn
            }
        )

class OptionsFlow(config_entries.OptionsFlow):
    """Options flow handler class"""
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow"""
        self._config_entry = config_entry

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Manage options — 首次进入时根据是否已配置网关分流"""
        current_sn = self._config_entry.data.get(CONF_GATEWAY_SN, "")
        if not current_sn:
            # 无网关 SN：进入添加网关步骤
            return await self.async_step_add_gateway()
        # 已有网关：进入常规选项
        return await self.async_step_options()

    async def async_step_add_gateway(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """添加网关 SN（首次配置或无网关时）"""
        errors = {}
        if user_input is not None:
            gateway_sn = user_input.get(CONF_GATEWAY_SN, "").strip()
            gateway_name = user_input.get(CONF_GATEWAY_NAME, "").strip()

            if not gateway_sn:
                errors[CONF_GATEWAY_SN] = "required"
            elif not validate_gateway_sn(gateway_sn):
                errors[CONF_GATEWAY_SN] = "invalid_sn_format"
            else:
                # 检查是否已配置该网关
                for entry in self.hass.config_entries.async_entries(DOMAIN):
                    if entry.data.get(CONF_GATEWAY_SN, "").lower() == gateway_sn.lower():
                        errors[CONF_GATEWAY_SN] = "already_configured"
                        break

                if not errors:
                    if not gateway_name:
                        gateway_name = f"{DEFAULT_GATEWAY_NAME} {gateway_sn[-4:]}"

                    # 更新 config entry DATA（不是 options）
                    new_data = {
                        **self._config_entry.data,
                        CONF_GATEWAY_SN: gateway_sn,
                        CONF_GATEWAY_NAME: gateway_name,
                    }
                    self.hass.config_entries.async_update_entry(
                        self._config_entry, data=new_data
                    )
                    # 重新加载以触发 async_setup_entry
                    await self.hass.config_entries.async_reload(self._config_entry.entry_id)
                    return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="add_gateway",
            data_schema=vol.Schema({
                vol.Required(CONF_GATEWAY_SN): str,
                vol.Optional(
                    CONF_GATEWAY_NAME,
                    description={"suggested_value": "慧尖网关"}
                ): str,
            }),
            errors=errors,
            description_placeholders={
                "example_sn": "100121501186",
            },
        )

    async def async_step_options(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """常规选项（已有网关时显示）

        v1.6.12（第五轮审计 #9）：移除 gateway_sn 表单字段——setup 只读
        entry.data，写入 options 无任何消费方，是"看起来能用实则静默无效"
        的死控件（改 SN 的正确入口是「替换网关」流程）。auto_discovery
        保留并已真实接线（mqtt_handler._auto_discovery_enabled 门控 002
        自动添加）；三个字段与 strings/zh-CN 的 options.step.options 对齐。
        """
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="options",
            data_schema=vol.Schema({
                vol.Optional(
                    "discovery_interval",
                    default=self._config_entry.options.get("discovery_interval", 300)
                ): vol.All(vol.Coerce(int), vol.Range(min=60, max=3600)),
                vol.Optional(
                    "auto_discovery",
                    default=self._config_entry.options.get("auto_discovery", True)
                ): bool,
                vol.Optional(
                    "debug_logging",
                    default=self._config_entry.options.get("debug_logging", False)
                ): bool,
            })
        )

