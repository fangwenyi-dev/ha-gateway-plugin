"""utils.py 的 MQTT 就绪判断辅助函数测试。"""

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
