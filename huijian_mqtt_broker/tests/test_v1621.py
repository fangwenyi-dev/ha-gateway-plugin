"""v1.6.21 批次钉桩：默认凭据提示 / Gitee Release 自动化 / 真栈 E2E 挂载。

背景（第七轮评分定案）：
- 默认 WS 令牌/默认 MQTT 密码与小程序、固件公开同串——Web UI 需提示改密
  （只提示绝不自动改：令牌双侧同步是既定契约，自动轮换=全客户 401）。
- Gitee Release 手工 POST 属人肉流程，CI 自动化消除。
- 279 单测全在 fake homeassistant mock 上跑——补真栈 E2E（CI 有 docker，
  本地没有），首阶段 continue-on-error 盲调试，连绿后升硬门禁。
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).parent
PKG = HERE.parent / "custom_components" / "window_controller_gateway"


# ---------- security 视图行为 ----------

@pytest.fixture
def security_view(monkeypatch):
    from homeassistant.components import http as ha_http
    monkeypatch.setattr(
        ha_http.HomeAssistantView, "json",
        lambda self, data: data, raising=False)
    from custom_components.window_controller_gateway.api import (
        WindowGatewaySecurityView)
    return WindowGatewaySecurityView()


def _req(entries):
    hass = SimpleNamespace(config_entries=SimpleNamespace(
        async_entries=lambda domain: entries))
    return SimpleNamespace(app={"hass": hass})


def test_security_ws_token_default_detected(security_view):
    from custom_components.window_controller_gateway.const import (
        CONF_WS_GATEWAY_TOKEN, DEFAULT_WS_GATEWAY_TOKEN)

    def run(entries):
        import asyncio
        return asyncio.run(security_view.get(_req(entries)))

    # options 未设置 → 用默认值 → true
    r = run([SimpleNamespace(options={})])
    assert r["ws_token_is_default"] is True
    # 自定义令牌 → false
    r = run([SimpleNamespace(
        options={CONF_WS_GATEWAY_TOKEN: "a-custom-secret-token-9999"})])
    assert r["ws_token_is_default"] is False
    # 多条目任一未改 → true（安全口径取严）
    r = run([
        SimpleNamespace(options={CONF_WS_GATEWAY_TOKEN: "custom-x-123456789"}),
        SimpleNamespace(options={}),
    ])
    assert r["ws_token_is_default"] is True
    # 无条目 → None（无从判定，UI 降级不误报）
    r = run([])
    assert r["ws_token_is_default"] is None
    # 响应绝不含令牌明文
    assert DEFAULT_WS_GATEWAY_TOKEN not in json.dumps(r)


def test_security_view_registered():
    src = (PKG / "api.py").read_text(encoding="utf-8")
    assert "register_view(WindowGatewaySecurityView())" in src
    assert 'url = "/api/window_controller_gateway/security"' in src
    # 只读视图：无 POST/DELETE 面
    seg = src[src.index("class WindowGatewaySecurityView"):]
    seg = seg[:seg.index("class ") if "class " in seg[10:] else len(seg)]
    assert "async def post" not in seg and "async def delete" not in seg


# ---------- 默认凭据交叉锚（改默认值必须三处同动的防线） ----------

def test_default_password_cross_anchor():
    from custom_components.window_controller_gateway.const import (
        DEFAULT_MQTT_PASSWORD)
    assert DEFAULT_MQTT_PASSWORD == "huijian2022"
    cfg = (HERE.parent / "config.yaml").read_text(encoding="utf-8")
    # options 块默认值直写（schema 只声明 type: password）
    assert f"password: {DEFAULT_MQTT_PASSWORD}" in cfg
    run_sh = (HERE.parent / "run.sh").read_text(encoding="utf-8")
    assert f'= "{DEFAULT_MQTT_PASSWORD}"' in run_sh, \
        "run.sh 默认密码判定与 const 脱节"


def test_status_json_carries_default_flag():
    run_sh = (HERE.parent / "run.sh").read_text(encoding="utf-8")
    assert "mqtt_password_is_default:$dp" in run_sh
    assert "DP_IS_DEFAULT" in run_sh


# ---------- Web UI 提示面 ----------

def test_webui_credential_status_wired():
    html = (HERE.parent / "www" / "index.html").read_text(encoding="utf-8")
    assert 'id="credStatus"' in html
    assert "api/window_controller_gateway/security" in html
    assert "mqtt_password_is_default" in html
    # 明文令牌/密码不得出现在前端比较逻辑（只消费布尔）
    assert "hIZ56jhQ" not in html


# ---------- CI 挂载 ----------

def test_ci_e2e_and_gitee_jobs():
    ci = (HERE.parent.parent / ".github" / "workflows" / "ci.yaml").read_text(
        encoding="utf-8")
    assert "bash huijian_mqtt_broker/tests/e2e/run_e2e.sh" in ci
    assert "continue-on-error: true" in ci  # 盲调试期约定，连绿后摘除
    assert "Create Gitee Release (idempotent)" in ci
    assert "target_commitish" in ci
    # BOM 防线：token 必须 ASCII（.gitee_token 曾带 BOM 打崩 API）
    assert "isascii" in ci


def test_e2e_script_key_steps():
    s = (HERE / "e2e" / "run_e2e.sh").read_text(encoding="utf-8")
    assert s.startswith("#!/usr/bin/env bash")
    assert "set -Eeuo pipefail" in s
    for anchor in ("api/onboarding/users", "gateway/rpt_rsp",
                   "window_controller_gateway", "config_entries/flow",
                   "/api/window_controller_gateway/devices",
                   "mosquitto_pub", "GITHUB_STEP_SUMMARY"):
        assert anchor in s, f"E2E 缺关键步骤锚: {anchor}"
