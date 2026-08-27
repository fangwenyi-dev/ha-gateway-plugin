"""const.py 纯函数测试。"""
from custom_components.window_controller_gateway.const import (
    supports_wind_lock_mode,
    get_device_display_name,
    DOMAIN,
)


class TestSupportsWindLockMode:
    def test_5005_supported(self):
        assert supports_wind_lock_mode("500512345678") is True

    def test_5001_not_supported(self):
        assert supports_wind_lock_mode("500112345678") is False

    def test_5002_not_supported(self):
        assert supports_wind_lock_mode("500212345678") is False

    def test_5003_not_supported(self):
        assert supports_wind_lock_mode("500312345678") is False

    def test_short_sn(self):
        assert supports_wind_lock_mode("500") is False


class TestGetDeviceDisplayName:
    def test_with_number(self):
        name = get_device_display_name("100122501207", "500534380262", 3)
        assert "1207" in name
        assert "0262" in name
        assert "#03" in name

    def test_without_number(self):
        name = get_device_display_name("100122501207", "500534380262")
        assert "1207" in name
        assert "0262" in name

    def test_domain_constant(self):
        assert DOMAIN == "window_controller_gateway"
