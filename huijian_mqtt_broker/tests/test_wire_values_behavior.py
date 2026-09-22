"""控制命令线值的**出站行为**覆盖守卫（v1.7.32 全量审计 G1）。

背景：open/close/stop/a 与 wind_lock 两式的值（100/0/101/200/0/1）是本仓
唯一决定"窗往哪个方向走"的常量，但修复前全测试树对它们的覆盖是——
`assert '| `open` | "100" |' in CLAUDE.md`（文档 markdown 字符串对字面量），
出站 payload 里从未断言过这四枚值，`send_command` 真实调用点只有
start_pairing/set_position/set_speed 三种命令。把 COMMAND_VALUE_OPEN 与
CLOSE 对调、或退回 CLAUDE.md 明写为"废弃固件时代记载"的旧表
open=0/close=1/stop=2，655 条测试与 CI 全绿而现网每台窗反向动作。

三面钉桩：
1. 正向行为：逐命令驱动 send_command，断言发布主题/ctype/attribute/
   data.sn/**value 字面量**，并钉 value 必须是 str（线值为字符串口径）；
2. 接线真实性（反钉）：monkeypatch `_commands.COMMAND_VALUE_OPEN` 后发布值
   必须随之改变——证明代码真读常量而非内联字面量，否则第 1 面是套套逻辑；
3. 常量↔固件契约↔CLAUDE.md 表格三方同源：文档表格从常量派生比对，
   且命中行数必须等于预期（防"一条都没匹配上"的假绿）。
"""
import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import custom_components.window_controller_gateway.mqtt_handler as mh_mod
import custom_components.window_controller_gateway.mqtt_handler._commands as cmd_mod
from custom_components.window_controller_gateway.mqtt_handler import (
    WindowControllerMQTTHandler,
)
from custom_components.window_controller_gateway import const as c

GW_SN = "100122501207"
DEV_SN = "5005DEV00002"
HERE = Path(__file__).resolve().parent

# 固件契约一手记载（CLAUDE.md 命令表，v1.6.17 对照 app_mqtt_business.c）
FIRMWARE_WIRE_VALUES = {
    "open": "100",
    "close": "0",
    "stop": "101",
    "a": "200",
    "wind_lock_tilt": "0",
    "wind_lock_flat": "1",
}

# 命令 → 其值应当落在哪个 attribute 上（值离开 attribute 就没有语义）
EXPECTED_ATTR_FOR_COMMAND = {
    "open": c.ATTRIBUTE_W_TRAVEL,
    "close": c.ATTRIBUTE_W_TRAVEL,
    "stop": c.ATTRIBUTE_W_TRAVEL,
    "a": c.ATTRIBUTE_W_TRAVEL,
    "wind_lock_tilt": c.ATTRIBUTE_WIND_LOCK_MODE,
    "wind_lock_flat": c.ATTRIBUTE_WIND_LOCK_MODE,
}

# 命令 → 承载该值的常量名（用于反钉时精确改一处）
CONST_NAME_FOR_COMMAND = {
    "open": "COMMAND_VALUE_OPEN",
    "close": "COMMAND_VALUE_CLOSE",
    "stop": "COMMAND_VALUE_STOP",
    "a": "COMMAND_VALUE_TOGGLE",
    "wind_lock_tilt": "COMMAND_VALUE_WIND_LOCK_TILT",
    "wind_lock_flat": "COMMAND_VALUE_WIND_LOCK_FLAT",
}


class _MockDM:
    """只暴露 send_command 实际触到的契约面。"""

    def __init__(self):
        self.devices = {}
        self.entry = SimpleNamespace(options={})

    def get_device(self, sn):
        return self.devices.get(sn)

    def _notify_status_listeners(self, sn):
        pass

    async def update_gateway_status(self, status):
        pass


class _Hass:
    def __init__(self, loop):
        self.data = {c.DOMAIN: {}}
        self.loop = loop
        self.config = SimpleNamespace(config_dir=".")

    def async_create_task(self, coro):
        if self.loop is not None and self.loop.is_running():
            return self.loop.create_task(coro)
        coro.close()
        return None

    def add_job(self, job, *args):
        return job(*args) if callable(job) else None


class _Publisher:
    def __init__(self):
        self.published = []

    async def __call__(self, hass, topic, payload, qos=0, retain=False):
        self.published.append((topic, json.loads(payload), qos, retain))


def _mk_handler(monkeypatch):
    pub = _Publisher()
    monkeypatch.setattr(mh_mod.mqtt, "async_publish", pub)
    handler = WindowControllerMQTTHandler(
        _Hass(loop=asyncio.get_running_loop()), GW_SN, _MockDM())
    handler.gateway_sn = GW_SN
    return handler, pub


class TestOutboundWireValues:
    """第 1 面：逐命令断言出站报文（含值字面量）。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("command", sorted(FIRMWARE_WIRE_VALUES))
    async def test_payload_carries_firmware_wire_value(self, monkeypatch, command):
        handler, pub = _mk_handler(monkeypatch)
        assert await handler.send_command(DEV_SN, command) is True
        assert len(pub.published) == 1, "一条命令只应发布一条报文"
        topic, payload, qos, retain = pub.published[0]

        assert topic == f"gateway/{GW_SN}/req"
        assert qos == 1 and retain is False, "控制下行必须 QoS1 且非 retain"
        assert payload["head"] == c.PROTOCOL_HEAD
        assert payload["ctype"] == "004"
        assert payload["sn"] == GW_SN
        assert payload["data"]["sn"] == DEV_SN
        assert payload["data"]["attribute"] == EXPECTED_ATTR_FOR_COMMAND[command]

        value = payload["data"]["value"]
        assert isinstance(value, str), f"线值必须是字符串，实得 {type(value)}"
        assert value == FIRMWARE_WIRE_VALUES[command], (
            f"命令 {command} 的线值偏离固件契约 {FIRMWARE_WIRE_VALUES[command]!r}"
            f"（实得 {value!r}）——窗会往反方向走"
        )

    @pytest.mark.asyncio
    async def test_set_position_value_is_string_of_int(self, monkeypatch):
        handler, pub = _mk_handler(monkeypatch)
        assert await handler.send_command(DEV_SN, "set_position",
                                          {"position": 65}) is True
        data = pub.published[-1][1]["data"]
        assert data["attribute"] == c.ATTRIBUTE_W_TRAVEL
        assert data["value"] == "65" and isinstance(data["value"], str)

    def test_every_command_value_constant_is_str(self):
        """常量层反钉：任何一枚线值写成 int 都会让固件侧解析分歧。"""
        names = sorted(set(CONST_NAME_FOR_COMMAND.values()))
        assert len(names) == 6, "命令覆盖被悄悄缩减"
        for name in names:
            value = getattr(c, name)
            assert isinstance(value, str), f"const.{name} 必须是字符串，实得 {value!r}"
            assert value.strip() == value and value != "", f"const.{name} 形态异常"


class TestWiringNotLiteral:
    """第 2 面（反钉）：改常量必须改变出站值，否则第 1 面是套套逻辑。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("command", sorted(FIRMWARE_WIRE_VALUES))
    async def test_value_follows_module_constant(self, monkeypatch, command):
        monkeypatch.setattr(cmd_mod, CONST_NAME_FOR_COMMAND[command], "999")
        handler, pub = _mk_handler(monkeypatch)
        assert await handler.send_command(DEV_SN, command) is True
        const_name = CONST_NAME_FOR_COMMAND[command]
        assert pub.published[-1][1]["data"]["value"] == "999", (
            f"send_command 里命令 {command} 的值没有走 const.{const_name}"
            "——内联字面量复活，第 1 面断言将是套套逻辑"
        )


class TestDocAndConstantSingleSource:
    """第 3 面：CLAUDE.md 命令表必须与常量同源（文档不再是第二真值源）。"""

    DOC_COMMANDS = ("open", "close", "stop", "a")

    def test_claude_table_matches_constants_row_by_row(self):
        src = (HERE.parent.parent / "CLAUDE.md").read_text(encoding="utf-8")
        rows = dict(re.findall(
            r'^\|\s*`([a-z_]+)`\s*\|\s*["`]?(-?\d+)["`]?\s*\|', src, re.M))
        assert rows, "CLAUDE.md 命令表解析为空（表格形态变了？守卫会瞎）"
        for cmd in self.DOC_COMMANDS:
            assert cmd in rows, f"CLAUDE.md 命令表缺 {cmd} 行"
        expect = {
            "open": c.COMMAND_VALUE_OPEN,
            "close": c.COMMAND_VALUE_CLOSE,
            "stop": c.COMMAND_VALUE_STOP,
            "a": c.COMMAND_VALUE_TOGGLE,
        }
        for cmd, want in expect.items():
            assert rows[cmd] == want, (
                f"CLAUDE.md 记 {cmd}={rows[cmd]!r} 而 const 为 {want!r}——"
                "文档与代码分叉，改文档或改常量，勿留两处"
            )
        # 计数钉：防"匹配到的行全是死码凑出来的"——表里必须真解析出这四行
        assert len([r for r in self.DOC_COMMANDS if r in rows]) == 4
