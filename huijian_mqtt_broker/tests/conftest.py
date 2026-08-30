"""pytest 共享配置：注入完整的假 homeassistant 包树，使集成模块可在无 HA 环境 import。

覆盖 window_controller_gateway/__init__.py 及其依赖模块的 import 链。
"""
import enum
import os
import sys
import types


def _pkg(name):
    mod = types.ModuleType(name)
    mod.__path__ = []  # 标记为包（允许子模块导入）
    sys.modules[name] = mod
    return mod


# ---- homeassistant 包树 ----
ha = _pkg("homeassistant")
ha_core = _pkg("homeassistant.core")
ha_const = _pkg("homeassistant.const")
ha_exceptions = _pkg("homeassistant.exceptions")
ha_config_entries = _pkg("homeassistant.config_entries")
ha_data_entry_flow = _pkg("homeassistant.data_entry_flow")
ha_helpers = _pkg("homeassistant.helpers")
ha_helpers_event = _pkg("homeassistant.helpers.event")
ha_helpers_entity = _pkg("homeassistant.helpers.entity")
ha_helpers_entity_platform = _pkg("homeassistant.helpers.entity_platform")
ha_helpers_device_registry = _pkg("homeassistant.helpers.device_registry")
ha_helpers_entity_registry = _pkg("homeassistant.helpers.entity_registry")
ha_helpers_config_validation = _pkg("homeassistant.helpers.config_validation")
ha_helpers_restore_state = _pkg("homeassistant.helpers.restore_state")
ha_components = _pkg("homeassistant.components")
ha_components_http = _pkg("homeassistant.components.http")
ha_components_mqtt = _pkg("homeassistant.components.mqtt")
ha_components_button = _pkg("homeassistant.components.button")
ha_components_binary_sensor = _pkg("homeassistant.components.binary_sensor")
ha_components_sensor = _pkg("homeassistant.components.sensor")
ha_components_cover = _pkg("homeassistant.components.cover")
ha_components_number = _pkg("homeassistant.components.number")


# ---- core ----
class HomeAssistant:
    """最小可用的假 HomeAssistant 实例"""

    def __init__(self):
        self.data = {}
        self.config = types.SimpleNamespace(config_dir=".")
        self.loop = None

    def async_create_task(self, coro):
        return coro

    def add_job(self, job, *args):
        if callable(job):
            return job(*args)
        return None


ha_core.HomeAssistant = HomeAssistant
ha_core.ServiceCall = type("ServiceCall", (), {})
# v1.6.11：config_flow 首次被测试导入（审计 #6 钉桩）——homeassistant.core.callback
# 是恒等标记装饰器，真实实现即返回原函数
ha_core.callback = lambda func: func


# ---- const ----
class Platform(enum.Enum):
    BINARY_SENSOR = "binary_sensor"
    BUTTON = "button"
    NUMBER = "number"
    SENSOR = "sensor"
    COVER = "cover"


ha_const.Platform = Platform
ha_const.EVENT_HOMEASSISTANT_STOP = "homeassistant_stop"
ha_const.__version__ = "2026.8.0"


# ---- exceptions ----
class HomeAssistantError(Exception):
    pass


class ConfigEntryNotReady(Exception):
    pass


ha_exceptions.ConfigEntryNotReady = ConfigEntryNotReady
ha_exceptions.HomeAssistantError = HomeAssistantError
# v1.6.9：cover.py/button.py/gateway.py 硬 import HomeAssistantError（控制命令
# 假成功根治），假环境必须提供，否则 import 期 AttributeError


# ---- config_entries ----
class ConfigEntry:
    def __init__(self, data=None, options=None, entry_id="test", title="test"):
        self.data = data or {}
        self.options = options or {}
        self.entry_id = entry_id
        self.title = title


ha_config_entries.ConfigEntry = ConfigEntry
ha_config_entries.SOURCE_DISCOVERY = "discovery"
ha_config_entries.SOURCE_USER = "user"


# v1.6.11（审计 #6 钉桩）：config_flow.py 首次被测试导入——类定义
# `class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN)` 需要能消化
# domain= 关键字基类（真实 HA 靠 __init_subclass__），OptionsFlow 为普通基类
class _ConfigFlowBase:
    def __init_subclass__(cls, **kwargs):
        pass


ha_config_entries.ConfigFlow = _ConfigFlowBase
ha_config_entries.OptionsFlow = type("OptionsFlow", (), {})


# ---- data_entry_flow ----
class FlowResultType(enum.Enum):
    FORM = "form"
    CREATE_ENTRY = "create_entry"
    ABORT = "abort"
    MENU = "menu"


ha_data_entry_flow.FlowResult = dict
ha_data_entry_flow.FlowResultType = FlowResultType


# ---- helpers ----
def _noop(*args, **kwargs):
    return None


ha_helpers_event.async_track_time_interval = lambda *a, **k: (lambda: None)
ha_helpers_device_registry.async_get = lambda hass: None
ha_helpers_entity_registry.async_get = lambda hass: None


class EntityCategory(enum.Enum):
    CONFIG = "config"
    DIAGNOSTIC = "diagnostic"


ha_helpers_entity.DeviceInfo = dict
ha_helpers_entity.EntityCategory = EntityCategory
ha_helpers_entity_platform.AddEntitiesCallback = type("AddEntitiesCallback", (), {})
ha_helpers_config_validation.string = lambda v: v
ha_helpers_config_validation.positive_int = lambda v: v
ha_helpers_config_validation.boolean = lambda v: v


# ---- components ----
ha_components_http.HomeAssistantView = type("HomeAssistantView", (), {})
ha_components_mqtt.async_connected = lambda hass: True
ha_components_mqtt.async_publish = _noop
ha_components_mqtt.async_subscribe = _noop
ha_components_button.ButtonEntity = type("ButtonEntity", (), {})
ha_components_binary_sensor.BinarySensorEntity = type("BinarySensorEntity", (), {})
ha_components_binary_sensor.BinarySensorDeviceClass = type(
    "BinarySensorDeviceClass", (), {"CONNECTIVITY": "connectivity"}
)
ha_components_sensor.SensorEntity = type("SensorEntity", (), {})
ha_components_sensor.SensorDeviceClass = type(
    "SensorDeviceClass", (), {"VOLTAGE": "voltage", "ENUM": "enum"}
)
ha_components_sensor.SensorStateClass = type(
    "SensorStateClass", (), {"MEASUREMENT": "measurement"}
)
ha_components_cover.CoverEntity = type("CoverEntity", (), {})
ha_components_cover.CoverEntityFeature = type(
    "CoverEntityFeature", (), {"OPEN": 1, "CLOSE": 2, "STOP": 4}
)
ha_components_cover.CoverDeviceClass = type("CoverDeviceClass", (), {"WINDOW": "window"})
ha_components_number.NumberEntity = type("NumberEntity", (), {})
ha_components_number.NumberMode = type("NumberMode", (), {"SLIDER": "slider"})

# ---- restore_state（v1.6.8：RestoreEntity 假基类，模拟真实异步接口契约）----
class FakeRestoreEntity:
    async def async_added_to_hass(self):
        pass

    async def async_get_last_state(self):
        return None


ha_helpers_restore_state.RestoreEntity = FakeRestoreEntity

# ---- v1.6.9：base_entity 生命周期方法链补 super() 后，真实 HA 里
# Entity 基类（homeassistant/helpers/entity.py）对两个钩子都有空实现，
# 假实体类必须同样提供，否则测试 MRO 里 super() 落到 object 抛 AttributeError
async def _noop_async(self):
    return None


for _fake in (
    ha_components_button.ButtonEntity,
    ha_components_binary_sensor.BinarySensorEntity,
    ha_components_sensor.SensorEntity,
    ha_components_cover.CoverEntity,
    ha_components_number.NumberEntity,
    FakeRestoreEntity,
):
    _fake.async_added_to_hass = _noop_async
    _fake.async_will_remove_from_hass = _noop_async


# ---- 加入 custom_components 路径（测试文件在 huijian_mqtt_broker/tests/）----
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
