# -*- coding: utf-8 -*-
"""钉桩：HUIJIAN_HUB_BASE 环境杠杆——真栈 e2e 不得再往生产 hub 注册孤儿实例。

实发缺陷（2026-09-24 生产取证）：docker e2e（run_e2e.sh）与 WSL 本地 e2e
（run_local.sh）跑的都是**真实** async_setup_entry，会在 async_ensure_hub_client
里拿内置生产默认 HUB_DEFAULT_BASE 去 /agent/register——每次 CI 都在生产 hub 注册表
留一条 sn=E2EGW0000001 的孤儿实例（生产 /healthz 一度 instances=4，其中两条时间戳
精确对上 v1.7.46/v1.7.47 两次 CI）。ha_e2e_driver.py 对 hub 零断言，所以这条泄漏
从不让 e2e 变红＝纯静默污染。

修法：hub base 解析加环境变量档（resolve_hub_base：option > HUIJIAN_HUB_BASE >
默认），两 harness 把它设成 http://127.0.0.1:1 黑洞——注册秒失败（拒连→WARNING→
退避），全程不触网；未设变量时逐字节回退到内置生产默认（defaults-off，生产零影响）。

三条腿：① resolve_hub_base 纯函数优先级；② 走真 async_ensure_hub_client 的接线行为
（env 真能把 base 掰成黑洞、默认路径仍是生产、option 压过 env）；③ 两 harness 脚本
确实把变量设成非生产黑洞（防未来编辑静默删掉再泄漏——这正是本缺陷能发布的原因）。
"""
import asyncio
import re
import types
from pathlib import Path
from urllib.parse import urlparse

import pytest

import custom_components.window_controller_gateway as pkg
from custom_components.window_controller_gateway.const import DOMAIN
from custom_components.window_controller_gateway.hub_client import (
    HUB_BASE_ENV, HUB_DEFAULT_BASE, resolve_hub_base)

ROOT = Path(__file__).resolve().parents[1]
E2E = ROOT / "tests" / "e2e"
RUN_E2E = E2E / "run_e2e.sh"
RUN_LOCAL = E2E / "run_local.sh"
PROD_HOST = urlparse(HUB_DEFAULT_BASE).netloc


# ============ ① 纯函数优先级 ============
def test_option_beats_env_beats_default():
    """显式 option > 环境变量 > 内置默认——三档逐级回退，一档都不能错位。"""
    env = {HUB_BASE_ENV: "http://env-black-hole:1"}
    assert resolve_hub_base("http://user-option", env=env) == "http://user-option"
    assert resolve_hub_base("", env=env) == "http://env-black-hole:1"
    assert resolve_hub_base("", env={}) == HUB_DEFAULT_BASE


def test_blank_and_whitespace_fall_through():
    """空串/纯空白（option 或 env）都算"没配"，必须继续回退，不得当成有效 base。"""
    assert resolve_hub_base("   ", env={HUB_BASE_ENV: "  "}) == HUB_DEFAULT_BASE
    assert resolve_hub_base(None, env=None) == HUB_DEFAULT_BASE


def test_env_default_is_off_in_production():
    """defaults-off 硬钉：进程环境里没有 HUIJIAN_HUB_BASE 时，必须回内置生产默认。

    这条挡住"把 env 读取写成无条件覆盖"的回归——生产 HA 不设此变量，行为须与
    加杠杆之前逐字节相同（否则等于给生产塞了一个谁都没注意的隐藏开关）。
    """
    import os
    assert HUB_BASE_ENV not in os.environ, \
        "测试进程里不该预置 %s（会污染本条判据）" % HUB_BASE_ENV
    assert resolve_hub_base("") == HUB_DEFAULT_BASE


# ============ ② 接线行为：走真 async_ensure_hub_client ============
class FakeManager:
    def __init__(self, gateway_sn="GW1"):
        self.gateway_sn = gateway_sn

    def add_status_listener(self, cb):
        pass

    def remove_status_listener(self, cb):
        pass


class FakeHub:
    made = []

    def __init__(self, managers=None, **kw):
        self.managers = list(managers or [])
        self.kw = kw
        FakeHub.made.append(self)

    def attach_managers(self, managers):
        self.managers = list(managers)

    async def async_start(self):
        pass

    async def async_stop(self):
        pass


def _hass_with_one_gateway(tmp_path, hub_base_option=""):
    """最小但真实的 hass：一条 _setup_complete 的条目（device_manager 就位）。

    config_entries.async_entries 回一条带 options 的条目——让 _hub_option 走真路径
    （option 非空时压过 env，正是本杠杆声明的优先级）。
    """
    entry = types.SimpleNamespace(options=({"hub_base": hub_base_option}
                                           if hub_base_option else {}))
    return types.SimpleNamespace(
        data={DOMAIN: {"e1": {"_setup_complete": True,
                              "device_manager": FakeManager()}}},
        config=types.SimpleNamespace(config_dir=str(tmp_path)),
        config_entries=types.SimpleNamespace(async_entries=lambda domain: [entry]),
        bus=types.SimpleNamespace(async_listen_once=lambda *a, **k: (lambda: None)),
    )


def _ensure_base(monkeypatch, tmp_path, env_value=None, option=""):
    """跑真 async_ensure_hub_client，回它构造 HubClient 时用的 base。"""
    FakeHub.made = []
    monkeypatch.setattr(pkg, "HubClient", FakeHub)
    if env_value is None:
        monkeypatch.delenv(HUB_BASE_ENV, raising=False)
    else:
        monkeypatch.setenv(HUB_BASE_ENV, env_value)
    hass = _hass_with_one_gateway(tmp_path, option)
    asyncio.run(pkg.async_ensure_hub_client(hass))
    assert FakeHub.made, "async_ensure_hub_client 没构造 HubClient＝接线本身断了"
    return FakeHub.made[-1].kw["base"]


def test_wiring_env_reaches_the_client(monkeypatch, tmp_path):
    """环境变量真能把接线里的 base 掰成黑洞——否则 harness 设了也白设。"""
    base = _ensure_base(monkeypatch, tmp_path, env_value="http://127.0.0.1:1")
    assert base == "http://127.0.0.1:1"


def test_wiring_default_path_unchanged(monkeypatch, tmp_path):
    """无 env、无 option：接线仍用内置生产默认（defaults-off 的接线侧证据）。"""
    base = _ensure_base(monkeypatch, tmp_path, env_value=None, option="")
    assert base == HUB_DEFAULT_BASE


def test_wiring_option_beats_env(monkeypatch, tmp_path):
    """用户显式 option 压过环境变量：env 是基础设施杠杆，不该盖掉用户主动配置。"""
    base = _ensure_base(monkeypatch, tmp_path, env_value="http://127.0.0.1:1",
                        option="https://user-hub.example")
    assert base == "https://user-hub.example"


# ============ ③ harness 脚本必须把变量设成非生产黑洞 ============
# 提取纪律：只认「非注释行 + 值是真 URL」的赋值。裸 `HUIJIAN_HUB_BASE=(\S+)` 会
# 先命中我写在脚本里的解释性注释（"HUIJIAN_HUB_BASE=黑洞：…"）＝守卫扫到自己、
# 把散文当成配置（本仓"扫描型守卫别扫到自己"那条教训的又一次实锤）。
_ENV_ASSIGN = re.compile(r"""HUIJIAN_HUB_BASE=["']?(https?://[^\s"'\\]+)""")


def _harness_hub_base(script):
    """从 harness 脚本里取出真正生效的 HUIJIAN_HUB_BASE 值（跳过注释行）。"""
    code = "\n".join(ln for ln in script.read_text(encoding="utf-8").splitlines()
                     if not ln.lstrip().startswith("#"))
    m = _ENV_ASSIGN.search(code)
    return m.group(1) if m else None


@pytest.mark.parametrize("script", [RUN_E2E, RUN_LOCAL],
                         ids=["run_e2e.sh", "run_local.sh"])
def test_harness_points_hub_at_black_hole(script):
    """两个真栈 harness 都得设 HUIJIAN_HUB_BASE，且值必须是非生产黑洞。

    这条是防复发的核心：本缺陷能发布，正因为没有任何判据盯着"harness 把 hub
    指向哪"。判据双侧——① 变量在（漏设＝泄漏回潮）；② 值不是生产 host（设成
    生产＝等于没隔离）。任一被未来编辑破坏即红。
    """
    assert script.exists(), "harness 脚本缺失: %s" % script.name
    val = _harness_hub_base(script)
    assert val, "%s 没设生效的 HUIJIAN_HUB_BASE（URL 值）＝真栈会往生产 hub 注册孤儿实例" % script.name
    host = urlparse(val).netloc
    assert host and PROD_HOST not in host, \
        "%s 的 hub base 指向生产（%s）＝隔离失效" % (script.name, val)
    assert host.startswith("127.0.0.1") or host.startswith("localhost"), \
        "%s 的 hub base 不是本地黑洞（%s）——e2e 不该触网" % (script.name, val)


def test_black_hole_value_is_consistent_across_harnesses():
    """单一事实源：两 harness 用同一个 env 名与同一个黑洞值（漂移即有一处没隔离）。"""
    vals = [_harness_hub_base(s) for s in (RUN_E2E, RUN_LOCAL)]
    assert all(vals), "有 harness 未设生效的 HUIJIAN_HUB_BASE: %s" % vals
    assert len(set(vals)) == 1, "两 harness 的黑洞值不一致: %s" % vals


def test_resolver_is_not_dead_code():
    """接线真在用 resolve_hub_base（防"加了纯函数却没人调"＝钉验死码）。"""
    init_src = (ROOT / "custom_components" / "window_controller_gateway"
                / "__init__.py").read_text(encoding="utf-8")
    assert "resolve_hub_base(" in init_src, \
        "__init__.py 没调 resolve_hub_base——env 杠杆是死码，harness 设了不生效"
