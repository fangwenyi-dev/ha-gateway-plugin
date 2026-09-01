"""v1.6.13 MQTT 就绪门禁加固回归测试（客户现场 mqtt_not_available 误报根治）。

背景：客户安装加载项后在集成里添加网关报 "mqtt_not_available"。
根因（本轮修复）：
  1. config flow 在 ensure_mqtt_connection 之后**立即同步**检查
     hass.data["mqtt"]——条目刚创建/重载时 MQTT setup 尚未异步完成，
     正常时序被误判为"MQTT 未启用"。
  2. 两种完全不同的故障（从未配置 MQTT / 内置 broker 未就绪）复用
     同一误导文案。
  3. ensure 的"已等满 30s 仍未就绪"与门禁宽限窗口会串行叠加。

审计定案后的标记语义（勿再改回）：
  - CREATE_ENTRY 超时 → **保留**标记（条目未落地时下次可重建，独立价值）
  - 更新/降级路径 → 条目数据已落地且必然匹配、匹配分支秒删，保留无消费
    出口还会在 Supervisor 覆盖场景形成 reload 环 → **无条件删除**，
    连接由 MQTT 集成自身重试负责（返回值 False 告知调用方勿再空等）。

桩形态说明：EnsureHass 默认走"Core 直装"形态（init→FORM→configure）；
HAOS/Supervisor 真实形态（init→MENU→configure 导航→configure 提交）由
test_haos_menu_navigation 钉死。
"""

import asyncio
import json
import types

import pytest

from custom_components.window_controller_gateway import mqtt_bootstrap as mb_mod
from custom_components.window_controller_gateway import config_flow as cf_mod
from custom_components.window_controller_gateway.config_flow import ConfigFlow
from custom_components.window_controller_gateway.const import (
    CONF_GATEWAY_NAME,
    CONF_GATEWAY_SN,
    DOMAIN,
)
from custom_components.window_controller_gateway.utils import (
    async_wait_mqtt_loaded,
)
from custom_components.window_controller_gateway.mqtt_bootstrap import (
    BOOTSTRAP_FILENAME,
    has_bootstrap_marker,
)


# ==================== 共用 Fake ====================

class GateHass:
    """门禁所需的最小 hass 面：hass.data + config_entries.async_entries。"""

    def __init__(self, mqtt=None, mqtt_entries=None):
        self.data = {} if mqtt is None else {"mqtt": mqtt}
        entries = list(mqtt_entries or [])
        self.config_entries = types.SimpleNamespace(
            async_entries=lambda domain: entries if domain == "mqtt" else []
        )


class MarkerHass:
    """has_bootstrap_marker 所需：config.path + 直通 executor。"""

    def __init__(self, marker_path):
        self._marker_path = marker_path
        self.config = types.SimpleNamespace(
            path=lambda name: (
                str(self._marker_path)
                if name == BOOTSTRAP_FILENAME
                else f"/config/{name}"
            )
        )

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class EnsureHass(MarkerHass):
    """ensure_mqtt_connection 走创建/更新路径所需的完整面。"""

    def __init__(self, marker_path, flow_results, mqtt_entries=None):
        super().__init__(marker_path)
        entries = list(mqtt_entries or [])
        self.removed_entries = []
        self.flow = types.SimpleNamespace(calls=[], _results=list(flow_results))

        async def _async_init(domain, context=None):
            self.flow.calls.append(("init", domain, context))
            return self.flow._results.pop(0)

        async def _async_configure(flow_id, user_input=None):
            self.flow.calls.append(("configure", flow_id, user_input))
            return self.flow._results.pop(0)

        async def _async_abort(flow_id):
            self.flow.calls.append(("abort", flow_id))

        self.flow.async_init = _async_init
        self.flow.async_configure = _async_configure
        self.flow.async_abort = _async_abort

        self.config_entries = types.SimpleNamespace(
            async_entries=lambda domain: entries if domain == "mqtt" else [],
            flow=self.flow,
            async_update_entry=lambda entry, data=None: entry.data.update(
                data or {}
            ),
        )

        async def _async_remove(eid):
            self.removed_entries.append(eid)

        self.config_entries.async_remove = _async_remove
        self.reload_calls = []

        async def _fake_reload(eid):
            self.reload_calls.append(eid)

        self.config_entries.async_reload = _fake_reload


# ==================== A. async_wait_mqtt_loaded ====================

class TestAsyncWaitMqttLoaded:
    @pytest.mark.asyncio
    async def test_returns_true_immediately_when_loaded(self):
        """已就绪：不进入轮询，立即 True（interval 取大值证明零等待）。"""
        hass = GateHass(mqtt=object())
        assert await async_wait_mqtt_loaded(hass, timeout=5.0, interval=5.0) is True

    @pytest.mark.asyncio
    async def test_returns_true_on_late_setup(self):
        """客户场景：条目创建后 setup 异步完成——宽限窗口内命中必须返回 True。"""
        hass = GateHass()

        async def _late_setup():
            await asyncio.sleep(0.05)
            hass.data["mqtt"] = object()

        task = asyncio.ensure_future(_late_setup())
        assert await async_wait_mqtt_loaded(hass, timeout=2.0, interval=0.02) is True
        await task

    @pytest.mark.asyncio
    async def test_returns_false_on_timeout(self):
        """永不就绪：timeout 后返回 False（快速失败，不无限等）。"""
        hass = GateHass()
        assert await async_wait_mqtt_loaded(hass, timeout=0.15, interval=0.05) is False


# ==================== B. has_bootstrap_marker ====================

class TestHasBootstrapMarker:
    @pytest.mark.asyncio
    async def test_true_when_marker_file_exists(self, tmp_path):
        p = tmp_path / BOOTSTRAP_FILENAME
        p.write_text("{}", encoding="utf-8")
        assert await has_bootstrap_marker(MarkerHass(p)) is True

    @pytest.mark.asyncio
    async def test_false_when_absent(self, tmp_path):
        assert (
            await has_bootstrap_marker(MarkerHass(tmp_path / BOOTSTRAP_FILENAME))
            is False
        )

    @pytest.mark.asyncio
    async def test_false_on_probe_exception(self):
        """探针异常必须按 False 处理——门禁不许被检查失败打断。"""

        class BoomHass(MarkerHass):
            async def async_add_executor_job(self, func, *args):
                raise RuntimeError("executor down")

        assert await has_bootstrap_marker(BoomHass("/x")) is False


# ==================== C. _async_gate_mqtt_ready 分流 ====================

class TestMqttReadyGate:
    def _flow(self, hass):
        f = ConfigFlow.__new__(ConfigFlow)  # 绕开 HA 基类 __init__（假环境无）
        f.hass = hass
        return f

    @pytest.mark.asyncio
    async def test_loaded_passes_without_waiting(self, monkeypatch):
        hass = GateHass(mqtt=object())

        def _boom(*a, **k):
            raise AssertionError("loaded 时门禁不得再等待")

        monkeypatch.setattr(cf_mod, "async_wait_mqtt_loaded", _boom)
        errors = {}
        assert await self._flow(hass)._async_gate_mqtt_ready(errors) is True
        assert errors == {}

    @pytest.mark.asyncio
    async def test_no_entries_no_marker_fails_fast(self, monkeypatch):
        """无 MQTT 条目且无引导标记 = 真·未启用：立即 mqtt_not_available，不空耗 10s。"""
        hass = GateHass()

        async def fake_marker(h):
            return False

        wait_calls = []

        async def fake_wait(h, timeout):
            wait_calls.append(timeout)
            return False

        monkeypatch.setattr(cf_mod, "has_bootstrap_marker", fake_marker)
        monkeypatch.setattr(cf_mod, "async_wait_mqtt_loaded", fake_wait)
        errors = {}
        assert await self._flow(hass)._async_gate_mqtt_ready(errors) is False
        assert errors["base"] == "mqtt_not_available"
        assert wait_calls == []  # 钉死：此形态不进入宽限等待

    @pytest.mark.asyncio
    async def test_existing_entry_skips_marker_probe(self, monkeypatch):
        """短路守护（审计#5）：有 MQTT 条目时禁止探测标记文件（省 executor 往返）。"""
        hass = GateHass(mqtt_entries=[types.SimpleNamespace(entry_id="m1")])

        def _boom(*a, **k):
            raise AssertionError("has_entries 时不得探测标记")

        async def fake_wait(h, timeout):
            return False

        monkeypatch.setattr(cf_mod, "has_bootstrap_marker", _boom)
        monkeypatch.setattr(cf_mod, "async_wait_mqtt_loaded", fake_wait)
        errors = {}
        assert await self._flow(hass)._async_gate_mqtt_ready(errors) is False
        assert errors["base"] == "broker_not_ready"

    @pytest.mark.asyncio
    async def test_marker_present_not_ready_maps_to_broker_not_ready(self, monkeypatch):
        """标记存在（自动引导进行中）但未就绪 → broker_not_ready，且走过宽限窗口。"""
        hass = GateHass()

        async def fake_marker(h):
            return True

        seen = {}

        async def fake_wait(h, timeout):
            seen["timeout"] = timeout
            return False

        monkeypatch.setattr(cf_mod, "has_bootstrap_marker", fake_marker)
        monkeypatch.setattr(cf_mod, "async_wait_mqtt_loaded", fake_wait)
        errors = {}
        assert await self._flow(hass)._async_gate_mqtt_ready(errors) is False
        assert errors["base"] == "broker_not_ready"
        assert seen["timeout"] == cf_mod.MQTT_READY_GRACE_SECONDS  # 用真实常量

    @pytest.mark.asyncio
    async def test_already_waited_skips_grace(self, monkeypatch):
        """ensure 返回 False（已等满 30s）→ 门禁不得再叠加宽限（审计#3）。"""
        hass = GateHass(mqtt_entries=[types.SimpleNamespace(entry_id="m1")])

        def _boom(*a, **k):
            raise AssertionError("already_waited=True 时不得再宽限等待")

        monkeypatch.setattr(cf_mod, "async_wait_mqtt_loaded", _boom)
        errors = {}
        assert (
            await self._flow(hass)._async_gate_mqtt_ready(errors, already_waited=True)
            is False
        )
        assert errors["base"] == "broker_not_ready"

    @pytest.mark.asyncio
    async def test_late_ready_passes_gate(self, monkeypatch):
        """宽限窗口内就绪 → 放行且不带错误码（误报根治的正例）。"""
        hass = GateHass()

        async def fake_marker(h):
            return True

        async def fake_wait(h, timeout):
            return True

        monkeypatch.setattr(cf_mod, "has_bootstrap_marker", fake_marker)
        monkeypatch.setattr(cf_mod, "async_wait_mqtt_loaded", fake_wait)
        errors = {}
        assert await self._flow(hass)._async_gate_mqtt_ready(errors) is True
        assert errors == {}


# ==================== D. ensure_mqtt_connection 标记生命周期 + 返回值 ====================

def _marker(tmp_path, **over):
    data = {
        "broker": "127.0.0.1",
        "port": 2022,
        "username": "ha_mqtt",
        "password": "pw",
    }
    data.update(over)
    p = tmp_path / BOOTSTRAP_FILENAME
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _form_results():
    from homeassistant.data_entry_flow import FlowResultType

    return [
        {"flow_id": "f1", "type": FlowResultType.FORM},
        {"type": FlowResultType.CREATE_ENTRY},
    ]


class TestEnsureMarkerLifecycle:
    @pytest.mark.asyncio
    async def test_create_entry_client_timeout_keeps_marker(self, tmp_path, monkeypatch):
        """CREATE_ENTRY + 客户端未连上 → 保留标记 + 返回 False（勿删——更新
        路径的保留无消费出口，本路径的保留有：条目未落地时下次可重建）。"""
        _marker(tmp_path)

        hass = EnsureHass(tmp_path / BOOTSTRAP_FILENAME, flow_results=_form_results())

        async def fake_wait(h):
            return False

        monkeypatch.setattr(mb_mod, "_wait_for_mqtt_client", fake_wait)
        result = await mb_mod.ensure_mqtt_connection(hass)

        assert result is False  # 审计#3 契约：等满一轮仍未就绪
        assert (tmp_path / BOOTSTRAP_FILENAME).exists(), "客户端未就绪时标记必须保留"
        # 钉死 init 实参（审计#5）：domain + SOURCE_USER context
        assert hass.flow.calls[0] == ("init", "mqtt", {"source": "user"})
        # 钉死提交参数：broker/port/username/password 逐字段来自标记（防 schema 漂移）
        configure = [c for c in hass.flow.calls if c[0] == "configure"]
        assert configure, "应已提交 MQTT flow"
        assert configure[0][2] == {
            "broker": "127.0.0.1",
            "port": 2022,
            "username": "ha_mqtt",
            "password": "pw",
        }

    @pytest.mark.asyncio
    async def test_create_entry_client_ready_removes_marker(self, tmp_path, monkeypatch):
        """CREATE_ENTRY + 客户端就绪 → 删标记 + 返回 True（引导完成语义成立）。"""
        _marker(tmp_path)

        hass = EnsureHass(tmp_path / BOOTSTRAP_FILENAME, flow_results=_form_results())

        async def fake_wait(h):
            return True

        monkeypatch.setattr(mb_mod, "_wait_for_mqtt_client", fake_wait)
        result = await mb_mod.ensure_mqtt_connection(hass)
        assert result is True
        assert not (tmp_path / BOOTSTRAP_FILENAME).exists()

    @pytest.mark.asyncio
    async def test_haos_menu_navigation_reaches_broker_form(self, tmp_path, monkeypatch):
        """HAOS/Supervisor 真实形态：init→MENU→configure(next_step_id=broker)
        →configure(提交) → CREATE_ENTRY。钉死菜单导航一步（v1.6.2 实测定案）。"""
        from homeassistant.data_entry_flow import FlowResultType

        _marker(tmp_path)
        hass = EnsureHass(
            tmp_path / BOOTSTRAP_FILENAME,
            flow_results=[
                {"flow_id": "f1", "type": FlowResultType.MENU},
                {"flow_id": "f1", "type": FlowResultType.FORM},
                {"type": FlowResultType.CREATE_ENTRY},
            ],
        )

        async def fake_wait(h):
            return True

        monkeypatch.setattr(mb_mod, "_wait_for_mqtt_client", fake_wait)
        result = await mb_mod.ensure_mqtt_connection(hass)
        assert result is True
        configure = [c for c in hass.flow.calls if c[0] == "configure"]
        assert configure[0][2] == {"next_step_id": "broker"}  # 菜单导航
        assert configure[1][2]["broker"] == "127.0.0.1"  # 真正的表单提交
        assert not (tmp_path / BOOTSTRAP_FILENAME).exists()

    @pytest.mark.asyncio
    async def test_user_entry_update_deletes_marker_and_reports_not_ready(
        self, tmp_path, monkeypatch
    ):
        """已有 user 源条目但 broker 不符 → 更新落地即删标记；客户端未就绪
        返回 False（审计#1 定案：更新后条目必匹配、匹配分支秒删，保留标记
        无消费出口且可形成 reload 环——删除才是诚实语义）。"""
        _marker(tmp_path)
        entry = types.SimpleNamespace(
            entry_id="m1",
            source="user",
            data={"broker": "other-host", "port": 1883, "username": "someone"},
        )
        hass = EnsureHass(
            tmp_path / BOOTSTRAP_FILENAME, flow_results=[], mqtt_entries=[entry]
        )

        async def fake_wait(h):
            return False

        monkeypatch.setattr(mb_mod, "_wait_for_mqtt_client", fake_wait)
        result = await mb_mod.ensure_mqtt_connection(hass)

        assert result is False
        assert hass.reload_calls == ["m1"]
        assert not (tmp_path / BOOTSTRAP_FILENAME).exists()
        # 审计#5：钉死 _update_mqtt_entry 真把条目刷成标记值
        assert entry.data == {
            "broker": "127.0.0.1",
            "port": 2022,
            "username": "ha_mqtt",
            "password": "pw",
        }

    @pytest.mark.asyncio
    async def test_hassio_takeover_degrade_deletes_marker(
        self, tmp_path, monkeypatch
    ):
        """hassio 源条目 + async_remove 失败 → 降级更新：reload + 删标记 +
        返回 False（v1.6.13 曾一度在此"保留标记"，审计#1 判定为注释与行为
        相反缺陷的复发变体——本用例钉死最终定案）。"""
        _marker(tmp_path)
        entry = types.SimpleNamespace(
            entry_id="m1",
            source="hassio",
            data={"broker": "supervisor-host", "port": 1883, "username": "hassio"},
        )
        hass = EnsureHass(
            tmp_path / BOOTSTRAP_FILENAME, flow_results=[], mqtt_entries=[entry]
        )

        async def _remove_fails(eid):
            raise RuntimeError("Supervisor 锁定该条目")

        hass.config_entries.async_remove = _remove_fails

        async def fake_wait(h):
            return False

        monkeypatch.setattr(mb_mod, "_wait_for_mqtt_client", fake_wait)
        result = await mb_mod.ensure_mqtt_connection(hass)

        assert result is False
        assert hass.reload_calls == ["m1"]  # 降级 = 更新 + reload
        assert not (tmp_path / BOOTSTRAP_FILENAME).exists()
        assert entry.data["broker"] == "127.0.0.1"
        assert hass.removed_entries == []  # remove 失败被吞，未谎报删除成功

    @pytest.mark.asyncio
    async def test_existing_match_removes_marker_and_returns_none(self, tmp_path):
        """条目与标记完全一致：删标记返回 None（本次未做连接等待——就绪与否
        交由调用方判断；"引导配置已落地"职责在条目匹配时即完成）。"""
        _marker(tmp_path)
        hass = EnsureHass(
            tmp_path / BOOTSTRAP_FILENAME,
            flow_results=[],
            mqtt_entries=[
                types.SimpleNamespace(
                    entry_id="m1",
                    source="user",
                    data={
                        "broker": "127.0.0.1",
                        "port": 2022,
                        "username": "ha_mqtt",
                        "password": "pw",
                    },
                )
            ],
        )
        assert await mb_mod.ensure_mqtt_connection(hass) is None
        assert not (tmp_path / BOOTSTRAP_FILENAME).exists()


# ==================== E. async_step_user 调用点接线（审计·测试#1） ====================
# gate 方法自身的单测无法守护接线：若 L126 被删/恢复旧两行判错，客户可见
# 症状原样复发而 C/D 类全绿。本组端到端直调 async_step_user 钉死分流接线。

class TestUserStepWiring:
    def _flow(self, hass):
        f = ConfigFlow.__new__(ConfigFlow)
        f.hass = hass
        f.context = {}
        f.form_calls = []

        async def _set_uid(uid):
            f.unique_id_seen = uid

        f.async_set_unique_id = _set_uid
        f._abort_if_unique_id_configured = lambda: None

        def _show_form(step_id=None, data_schema=None, errors=None, **kw):
            f.form_calls.append(dict(errors or {}))
            return {"type": "form", "step_id": step_id, "errors": dict(errors or {})}

        f.async_show_form = _show_form
        f.async_create_entry = lambda title=None, data=None: {
            "type": "create_entry",
            "title": title,
            "data": data,
        }
        return f

    @pytest.mark.asyncio
    async def test_cenr_rerouted_through_gate_not_hardcoded(
        self, monkeypatch
    ):
        """ensure 抛 CENR + 有条目未就绪 → 表单错误必须是 gate 给的
        broker_not_ready（旧代码硬编码 mqtt_not_available 即本 bug 本体）。"""
        from homeassistant.exceptions import ConfigEntryNotReady

        hass = GateHass(mqtt_entries=[types.SimpleNamespace(entry_id="m1")])

        async def ensure_raises(h):
            raise ConfigEntryNotReady("自动连接 MQTT 失败（cannot_connect），稍后自动重试")

        async def fake_wait(h, timeout):
            return False

        monkeypatch.setattr(cf_mod, "ensure_mqtt_connection", ensure_raises)
        monkeypatch.setattr(cf_mod, "async_wait_mqtt_loaded", fake_wait)

        f = self._flow(hass)

        async def no_test(sn):
            raise AssertionError("gate 未就绪时不得进入连接测试")

        f._test_gateway_connectivity = no_test
        result = await f.async_step_user(
            {CONF_GATEWAY_SN: "100121501186", CONF_GATEWAY_NAME: ""}
        )
        assert result["type"] == "form"
        assert result["errors"]["base"] == "broker_not_ready"

    @pytest.mark.asyncio
    async def test_already_waited_passed_from_ensure_result(self, monkeypatch):
        """ensure 返回 False → 接线必须转成 gate 的 already_waited=True
        （门禁不得再叠加宽限；audit#3 端到端钉桩）。"""
        hass = GateHass(mqtt_entries=[types.SimpleNamespace(entry_id="m1")])

        async def ensure_false(h):
            return False

        def _boom(*a, **k):
            raise AssertionError("already_waited 接线被破坏：门禁不得再宽限等待")

        monkeypatch.setattr(cf_mod, "ensure_mqtt_connection", ensure_false)
        monkeypatch.setattr(cf_mod, "async_wait_mqtt_loaded", _boom)

        f = self._flow(hass)
        result = await f.async_step_user(
            {CONF_GATEWAY_SN: "100121501186", CONF_GATEWAY_NAME: ""}
        )
        assert result["errors"]["base"] == "broker_not_ready"

    @pytest.mark.asyncio
    async def test_loaded_runs_connectivity_test_and_creates_entry(self, monkeypatch):
        """正方向接线：MQTT 已就绪 → 必须进入连接测试；测试通过 → 建条目。"""
        hass = GateHass(mqtt=object())

        async def ensure_none(h):
            return None

        monkeypatch.setattr(cf_mod, "ensure_mqtt_connection", ensure_none)

        f = self._flow(hass)
        tested = []

        async def fake_test(sn):
            tested.append(sn)
            return True

        f._test_gateway_connectivity = fake_test
        result = await f.async_step_user(
            {CONF_GATEWAY_SN: "100121501186", CONF_GATEWAY_NAME: "客厅"}
        )
        assert tested == ["100121501186"]
        assert result["type"] == "create_entry"
        assert result["data"][CONF_GATEWAY_SN] == "100121501186"

    @pytest.mark.asyncio
    async def test_not_responding_gateway_goes_confirm_add(self, monkeypatch):
        """就绪但网关未上报 → 转 confirm_add 步骤（而非错误码），确认两段语义不互踩。"""
        hass = GateHass(mqtt=object())

        async def ensure_none(h):
            return None

        monkeypatch.setattr(cf_mod, "ensure_mqtt_connection", ensure_none)

        f = self._flow(hass)

        async def fake_test(sn):
            return False

        async def fake_confirm():
            return {"type": "form", "step_id": "confirm_add", "errors": {}}

        f._test_gateway_connectivity = fake_test
        f.async_step_confirm_add = fake_confirm
        result = await f.async_step_user(
            {CONF_GATEWAY_SN: "100121501186", CONF_GATEWAY_NAME: ""}
        )
        assert result["step_id"] == "confirm_add"
        assert f._pending_gateway_sn == "100121501186"
