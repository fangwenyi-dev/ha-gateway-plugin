"""服务 handler 失败分支必须抛错（反「假成功」护栏）

v1.6.3/v1.6.4 连续修复了 check_gateway_status / start_pairing / rename_device
的 error-log-then-return 静默假成功（REST 返回 200，Web UI 弹「已发送/成功」
假 toast）。本文件钉死"调用即失败 ⇒ 抛 ServiceValidationError"契约，
防止未来重构把 raise 改回 return。

v1.6.8 追加：refresh_devices / set_position / migrate_devices / transfer_device
同样必须抛错，不能静默 return 200。
"""
from types import SimpleNamespace

import pytest

from custom_components.window_controller_gateway import services
from custom_components.window_controller_gateway.services import (
    ServiceValidationError,
    handle_check_gateway_status,
    handle_rename_device,
    handle_start_pairing,
    handle_refresh_devices,
    handle_set_position,
    handle_migrate_devices,
    handle_transfer_device,
)


def _call(**data):
    return SimpleNamespace(data=data)


class TestFailFastRaises:
    """参数缺失/目标不存在路径必须在触碰 hass 之前 raise"""

    @pytest.mark.asyncio
    async def test_check_gateway_status_no_args(self):
        with pytest.raises(ServiceValidationError):
            await handle_check_gateway_status(SimpleNamespace(), _call())

    @pytest.mark.asyncio
    async def test_start_pairing_missing_device_id(self):
        with pytest.raises(ServiceValidationError):
            await handle_start_pairing(SimpleNamespace(), _call())

    @pytest.mark.asyncio
    async def test_rename_device_missing_params(self):
        with pytest.raises(ServiceValidationError):
            await handle_rename_device(SimpleNamespace(), _call(device_id="x"))
        with pytest.raises(ServiceValidationError):
            await handle_rename_device(SimpleNamespace(), _call(name="n"))

    @pytest.mark.asyncio
    async def test_check_gateway_status_gateway_not_found(self):
        # hass.data 里没有任何配置条目 → 未找到网关，必须抛而非静默 200
        hass = SimpleNamespace(data={})
        with pytest.raises(ServiceValidationError):
            await handle_check_gateway_status(hass, _call(gateway_sn="SN-MISSING"))

    @pytest.mark.asyncio
    async def test_start_pairing_gateway_not_found(self):
        # hass.data 无 DOMAIN 条目 → find_gateway_by_device_id 返回 (None, None)
        # → 必抛（旧行为：error log + 静默 return 200 假成功）
        hass = SimpleNamespace(data={})
        with pytest.raises(ServiceValidationError):
            await handle_start_pairing(hass, _call(device_id="no-such"))

    @pytest.mark.asyncio
    async def test_refresh_devices_missing_device_id(self):
        with pytest.raises(ServiceValidationError):
            await handle_refresh_devices(SimpleNamespace(), _call())

    @pytest.mark.asyncio
    async def test_refresh_devices_gateway_not_found(self):
        hass = SimpleNamespace(data={})
        with pytest.raises(ServiceValidationError):
            await handle_refresh_devices(hass, _call(device_id="no-such"))

    @pytest.mark.asyncio
    async def test_set_position_missing_device_id(self):
        with pytest.raises(ServiceValidationError):
            await handle_set_position(SimpleNamespace(), _call())

    @pytest.mark.asyncio
    async def test_set_position_missing_position(self):
        with pytest.raises(ServiceValidationError):
            await handle_set_position(SimpleNamespace(), _call(device_id="x"))

    @pytest.mark.asyncio
    async def test_set_position_invalid_position(self):
        # bool 是 int 子类，type() is int 必须拦截
        with pytest.raises(ServiceValidationError):
            await handle_set_position(SimpleNamespace(), _call(device_id="x", position=True))
        with pytest.raises(ServiceValidationError):
            await handle_set_position(SimpleNamespace(), _call(device_id="x", position=-1))
        with pytest.raises(ServiceValidationError):
            await handle_set_position(SimpleNamespace(), _call(device_id="x", position=101))

    @pytest.mark.asyncio
    async def test_set_position_device_not_found(self):
        hass = SimpleNamespace(data={})
        with pytest.raises(ServiceValidationError):
            await handle_set_position(hass, _call(device_id="no-such", position=50))

    @pytest.mark.asyncio
    async def test_migrate_devices_invalid_args(self):
        hass = SimpleNamespace(data={}, config_entries=SimpleNamespace(async_entries=lambda: []))
        with pytest.raises(ServiceValidationError):
            await handle_migrate_devices(hass, _call(old_gateway_sn="short", new_gateway_sn="also"))
        with pytest.raises(ServiceValidationError):
            await handle_migrate_devices(hass, _call(old_gateway_sn="SN12345678", new_gateway_sn="SN12345678"))

    @pytest.mark.asyncio
    async def test_transfer_device_missing_args(self):
        with pytest.raises(ServiceValidationError):
            await handle_transfer_device(SimpleNamespace(), _call())
        with pytest.raises(ServiceValidationError):
            await handle_transfer_device(SimpleNamespace(), _call(device_id="x"))
        with pytest.raises(ServiceValidationError):
            await handle_transfer_device(SimpleNamespace(), _call(new_gateway_sn="y"))


class TestValidationErrorContract:
    def test_message_preserved(self):
        err = ServiceValidationError("未找到对应的网关: SN123")
        assert "SN123" in str(err)

    def test_class_importable_from_real_path_or_fallback(self):
        # 真实 HA 环境取 homeassistant.exceptions 官方类；
        # 测试假环境取 services 内联回退——两者都必须存在且可 raise
        assert issubclass(ServiceValidationError, Exception)
