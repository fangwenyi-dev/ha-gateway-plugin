"""utils.py 辅助函数测试：MQTT 就绪判断 + 注册表查找兼容层。"""

import pytest

from custom_components.window_controller_gateway.utils import is_mqtt_loaded, is_mqtt_connected


class FakeHass:
    def __init__(self, mqtt=None):
        self.data = {"mqtt": mqtt}


class TestIsMqttLoaded:
    def test_loaded_when_mqtt_in_data(self):
        assert is_mqtt_loaded(FakeHass(mqtt=object())) is True

    def test_not_loaded_when_mqtt_missing(self):
        assert is_mqtt_loaded(FakeHass(mqtt=None)) is False

    def test_not_loaded_when_data_empty(self):
        hass = FakeHass()
        hass.data = {}
        assert is_mqtt_loaded(hass) is False


class TestIsMqttConnected:
    def test_connected_true(self, monkeypatch):
        from homeassistant.components import mqtt as mqtt_mod
        monkeypatch.setattr(mqtt_mod, "async_connected", lambda hass: True)
        assert is_mqtt_connected(FakeHass(mqtt=object())) is True

    def test_connected_false(self, monkeypatch):
        from homeassistant.components import mqtt as mqtt_mod
        monkeypatch.setattr(mqtt_mod, "async_connected", lambda hass: False)
        assert is_mqtt_connected(FakeHass(mqtt=object())) is False

    def test_fallback_when_api_missing(self, monkeypatch):
        """旧版 HA 无 async_connected：回退为"集成已加载即视为可用"。"""
        from homeassistant.components import mqtt as mqtt_mod
        monkeypatch.delattr(mqtt_mod, "async_connected", raising=False)
        assert is_mqtt_connected(FakeHass(mqtt=object())) is True
        assert is_mqtt_connected(FakeHass(mqtt=None)) is False


# ==================== 注册表查找兼容层（v1.6.3 回归护栏） ====================
# 背景：v1.6.0 把 async_get_entity_id 的第一实参误写为字面量 "entity"
# （HA 真实签名为 (domain, platform, unique_id)），索引键永不命中，
# 全集成 13 处 unique_id 反查静默失效且 38 个单测全绿——本组测试
# 用记录实参的假注册表钉死参数顺序，防止同类回归再次溜过 CI。

from custom_components.window_controller_gateway import utils as utils_mod
from custom_components.window_controller_gateway.const import DOMAIN


class RecordingEntityRegistry:
    """记录 async_get_entity_id 实参的假注册表。async_mode=True 模拟
    过渡版本返回 coroutine 的形态。"""

    def __init__(self, result=None, async_mode=False):
        self.calls = []
        self._result = result
        self._async = async_mode

    def async_get_entity_id(self, domain, platform, unique_id):
        self.calls.append((domain, platform, unique_id))
        if self._async:
            async def _resolved():
                return self._result
            return _resolved()
        return self._result


@pytest.fixture
def patch_registry(monkeypatch):
    def _patch(reg):
        monkeypatch.setattr(utils_mod, "get_entity_registry", lambda hass: reg)
    return _patch


class TestAsyncGetEntityId:
    @pytest.mark.asyncio
    async def test_forwards_domain_as_first_arg(self, patch_registry):
        """C1 回归核心：第一参数必须是调用方传入的实体域（button/cover/…），
        而非字面量 'entity'；第二参数才是集成 DOMAIN。"""
        reg = RecordingEntityRegistry(result="button.huijian_open")
        patch_registry(reg)
        result = await utils_mod.async_get_entity_id(
            FakeHass(), "button", "GW123_456_open"
        )
        assert reg.calls == [("button", DOMAIN, "GW123_456_open")]
        assert result == "button.huijian_open"

    @pytest.mark.asyncio
    async def test_domain_arg_not_literal_entity(self, patch_registry):
        """显式钉死：任何调用都不得把 'entity' 当 domain 传给注册表。"""
        reg = RecordingEntityRegistry(result=None)
        patch_registry(reg)
        await utils_mod.async_get_entity_id(FakeHass(), "cover", "GW1_x_cover")
        assert reg.calls[0][0] != "entity"
        assert reg.calls[0][0] == "cover"

    @pytest.mark.asyncio
    async def test_coroutine_result_supported(self, patch_registry):
        """过渡版本返回 coroutine：await 后取 str。"""
        reg = RecordingEntityRegistry(result="number.huijian_speed", async_mode=True)
        patch_registry(reg)
        assert await utils_mod.async_get_entity_id(
            FakeHass(), "number", "GW1_2_speed"
        ) == "number.huijian_speed"

    @pytest.mark.asyncio
    async def test_registry_entry_result_supported(self, patch_registry):
        """新版返回 RegistryEntry：取 .entity_id。"""
        entry = type("RegistryEntry", (), {"entity_id": "sensor.huijian_battery"})()
        reg = RecordingEntityRegistry(result=entry)
        patch_registry(reg)
        assert await utils_mod.async_get_entity_id(
            FakeHass(), "sensor", "GW1_2_battery"
        ) == "sensor.huijian_battery"

    @pytest.mark.asyncio
    async def test_none_result(self, patch_registry):
        reg = RecordingEntityRegistry(result=None)
        patch_registry(reg)
        assert await utils_mod.async_get_entity_id(FakeHass(), "button", "x") is None

    @pytest.mark.asyncio
    async def test_type_error_falls_back_to_none(self, patch_registry):
        """签名不兼容（极老版本参数个数不同）：TypeError 兜底返回 None，
        不得向上抛炸调用方（v1.5.9 原有兜底，v1.6.0 误删，v1.6.3 恢复）。"""
        class LegacyRegistry:
            def async_get_entity_id(self, only_arg):  # 老签名：1 个参数
                raise TypeError("takes 2 positional arguments but 4 were given")
        patch_registry(LegacyRegistry())
        assert await utils_mod.async_get_entity_id(FakeHass(), "button", "x") is None


class TestCallRegistryMethod:
    @pytest.mark.asyncio
    async def test_sync_result_passthrough(self):
        def sync_fn(a, b=None):
            return (a, b)
        assert await utils_mod.call_registry_method(sync_fn, 1, b=2) == (1, 2)

    @pytest.mark.asyncio
    async def test_coroutine_result_awaited(self):
        async def async_fn(x):
            return x * 2
        assert await utils_mod.call_registry_method(async_fn, 21) == 42

    @pytest.mark.asyncio
    async def test_none_result_passthrough(self):
        def returns_none():
            return None
        assert await utils_mod.call_registry_method(returns_none) is None
