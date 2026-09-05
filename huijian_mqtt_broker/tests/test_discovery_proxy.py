"""v1.7.11 快速自动发现代理单测：解析防御 / 耳朵引导编排 / 重放与退避。

真栈端到端（代理→REST 建条目→心跳监听器→发现卡片）在
tests/e2e/fast_discovery_e2e.sh 验证；本文件锁纯逻辑面。
"""
import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "gateway_discovery_proxy",
    Path(__file__).resolve().parents[1] / "gateway_discovery_proxy.py",
)
gdp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gdp)

# 用户 HA2 现场抓包原样（005 设备上报，top sn=网关）
FIELD_005 = json.dumps({
    "head": "$SH", "id": 101, "ctype": "005", "sn": "100122501203",
    "data": {"rssi": 65472, "sn": "500700000001",
             "attrs": [{"attribute": "r_travel", "value": "100"},
                       {"attribute": "heartbeat_time", "value": "10"}]},
}, ensure_ascii=False)


class TestParseReport:
    def test_field_sample_005_triggers(self):
        assert gdp.parse_report(FIELD_005) == ("100122501203", "005")

    def test_001_and_002_trigger(self):
        for ct in ("001", "002"):
            raw = json.dumps({"head": "$SH", "id": 1, "ctype": ct,
                              "sn": "100122501203", "data": {}})
            assert gdp.parse_report(raw) == ("100122501203", ct)

    def test_numeric_sn_coerced(self):
        raw = json.dumps({"head": "$SH", "id": 1, "ctype": "002",
                          "sn": 100122501203, "data": {}})
        assert gdp.parse_report(raw) == ("100122501203", "002")

    @pytest.mark.parametrize("raw", [
        "not json",
        "",
        json.dumps(["list"]),
        json.dumps({"ctype": "002", "sn": "100122501203"}),          # 缺 head
        json.dumps({"head": "XX", "ctype": "002", "sn": "100122501203"}),
        json.dumps({"head": "$SH", "ctype": "004", "sn": "100122501203", "data": {}}),
        json.dumps({"head": "$SH", "ctype": "002"}),                  # 缺 sn
        json.dumps({"head": "$SH", "ctype": "002", "sn": True}),       # bool 守卫
        json.dumps({"head": "$SH", "ctype": "002", "sn": {"a": 1}}),   # dict 守卫
        json.dumps({"head": "$SH", "ctype": "002", "sn": "short1"}),   # 格式非法
    ])
    def test_rejects(self, raw):
        assert gdp.parse_report(raw) is None


def _proxy(entries=None, create_outcome="created", list_fails=False):
    log, pubs, calls = [], [], {"n": 0}

    def list_entries():
        calls["n"] += 1
        if list_fails:
            return None
        return entries if entries is not None else []

    def create():
        return create_outcome

    def pub(line):
        pubs.append(line)

    clock = {"t": 1000.0}

    def _sleep(s):
        clock["t"] += s

    p = gdp.DiscoveryProxy(list_entries, create, pub,
                           now=lambda: clock["t"], log=log.append, sleep=_sleep)
    return p, pubs, log, clock


class TestBootstrap:
    def test_first_report_creates_ears_and_replays_twice(self):
        p, pubs, log, _ = _proxy(entries=[])
        p.handle_line(FIELD_005)
        assert len(pubs) == 2 and pubs[0] == FIELD_005   # 立即 + 3s 兜底
        assert any("等待配置" in m for m in log)

    def test_existing_entry_no_action(self):
        p, pubs, log, _ = _proxy(entries=[{"domain": "window_controller_gateway"}])
        p.handle_line(FIELD_005)
        assert pubs == [] and log == []

    def test_ears_confirmed_cached_across_reports(self):
        p, pubs, _, _ = _proxy(entries=[])
        p.handle_line(FIELD_005)
        pubs.clear()
        p.handle_line(FIELD_005)          # 第二条上报：耳朵已确认，不再动作
        assert pubs == []

    def test_second_gateway_no_replay(self):
        p, pubs, _, _ = _proxy(entries=[])
        p.handle_line(FIELD_005)
        other = json.dumps({"head": "$SH", "id": 2, "ctype": "002",
                            "sn": "100199999999", "data": {}})
        p.handle_line(other)
        assert len(pubs) == 2   # 只有首 SN 的重放

    def test_create_fail_backs_off_30s(self):
        p, pubs, log, clock = _proxy(entries=[], create_outcome=False)
        p.handle_line(FIELD_005)
        assert pubs == []                     # 建条目失败 → 不重放（静默退避）
        clock["t"] += 29
        p.handle_line(FIELD_005)
        assert pubs == []                     # 退避窗口内
        clock["t"] += 2
        p.handle_line(FIELD_005)              # 到期重试仍失败（本桩 create 恒 False）
        assert pubs == []

    def test_list_query_failure_backs_off(self):
        p, pubs, log, _ = _proxy(list_fails=True)
        p.handle_line(FIELD_005)
        assert pubs == [] and any("重试" in m for m in log)

    def test_exists_outcome_no_replay_no_loop(self):
        """并发窗口：has_entries 假 → create 撞 already_configured abort →
        视为耳朵已在，不重放、也不再 list。"""
        p, pubs, log, _ = _proxy(entries=[], create_outcome="exists")
        p.handle_line(FIELD_005)
        assert pubs == [] and any("耳朵就位" in m for m in log)
        p.handle_line(FIELD_005)
        assert pubs == []

    def test_non_trigger_lines_inert(self):
        p, pubs, _, _ = _proxy(entries=[])
        p.handle_line("garbage")
        p.handle_line(json.dumps({"head": "$SH", "ctype": "003", "sn": "100122501203"}))
        assert pubs == []
