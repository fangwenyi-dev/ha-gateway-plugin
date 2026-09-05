"""v1.7.12 第 6 轮全谱审计修复钉桩（dsh-review-loop 5 路审计 + 父级独立核验）。

每个用例对应一条已核实并修复的真实问题；静态钉桩断言的是"修复形态"，
功能用例则在 fake-ha 上真实执行修复路径。回归时禁止用改测试迁就实现——
若确需变更形态，先想清楚原缺陷是否仍被防住。

清单（编号=审计报告）：
F-1  run.sh 凭据自动恢复（config 漂移 → 启动即回到固件内置值）
F-1b watchdog `RC=0; cmd || RC=$?`（bash -e 子壳继承下旧形态恒死）
F-2  run.sh heredoc ≡ ingress.conf 机械 diff（兑现 ingress.conf 头注释承诺）
B-1  MQTT client 换代订阅重建（_ensure_mqtt_subscription）
B-2  bootstrap 密码比较 + !secret 豁免
B-6  005 未知设备 auto_discovery 门禁（ack 契约不破）
B-9  去重记账失败回滚
B-10 "0" 字符串 id 直发旁路
DM-F1 首报 last_update 播种（30s 窗口期误判离线）
E-1  忽略网关跨重启持久（persist JSON + 共享 set）
CF-F1 空 SN 幽灵 unique_id 清除（行为钉在 test_audit_round6）
I-*  CI 加固（VERSION fail-fast / e2e 语法门 / fetch-depth / Gitee 兜底）
M-*/L-* Web 语义与卫生修复（静态形态）
"""
import asyncio
import json
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]          # huijian_mqtt_broker/
PKG = ROOT / "custom_components" / "window_controller_gateway"
MW = PKG / "mqtt_handler"

import custom_components.window_controller_gateway.mqtt_handler as mh_mod  # noqa: E402
from custom_components.window_controller_gateway.mqtt_handler import (  # noqa: E402
    WindowControllerMQTTHandler,
)
from custom_components.window_controller_gateway import const as c  # noqa: E402

GW_SN = "100122501203"
DEV_SN = "50022E010603"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ==================== 功能测试夹具（与 ack 契约测试同构） ====================

class _Hass:
    def __init__(self):
        self.data = {c.DOMAIN: {}}
        self.config = SimpleNamespace(config_dir=".")

    def async_create_task(self, coro):
        coro.close()
        return None


class _MockDM:
    def __init__(self, devices=None):
        self.devices = devices or {}
        self.status_updates = []
        self.added = []

    def get_device(self, sn):
        return self.devices.get(sn)

    def get_all_devices(self):
        return list(self.devices.values())

    def is_device_manually_removed(self, sn):
        return False

    def _notify_status_listeners(self, sn):
        pass

    async def add_device(self, sn, name, typ=None, force=False,
                         is_manual_pairing=False):
        self.added.append(sn)

    async def update_device_status(self, sn, status, attributes=None):
        self.status_updates.append((sn, status))

    async def update_gateway_status(self, status):
        pass

    def get_gateway_info(self):
        return {"name": "GW", "status": "online"}


class _Publisher:
    def __init__(self):
        self.published = []

    async def __call__(self, hass, topic, payload, qos=0, retain=False):
        self.published.append((topic, json.loads(payload)))

    def by_ctype(self, ctype):
        return [p for _, p in self.published if p.get("ctype") == ctype]


def _mk(monkeypatch, dm=None):
    pub = _Publisher()
    monkeypatch.setattr(mh_mod.mqtt, "async_publish", pub)
    handler = WindowControllerMQTTHandler(_Hass(), GW_SN, dm or _MockDM())
    return handler, pub


def _envelope(ctype, msg_id, data):
    return {"head": c.PROTOCOL_HEAD, "ctype": ctype, "id": msg_id,
            "sn": GW_SN, "data": data}


# ==================== F-1 / F-1b / F-2：run.sh 与 ingress 双拷贝 ====================

class TestRunShCredentialRestoreAndWatchdog:

    def test_credential_auto_restore_block(self):
        sh = _read(ROOT / "run.sh")
        assert 'FIRMWARE_MQTT_USER="huijian"' in sh, "凭据恢复常量丢失"
        assert 'FIRMWARE_MQTT_PASS="huijian2022"' in sh
        # 恢复块必须在 mosquitto 口令文件生成之前（先恢复后使用）
        i_restore = sh.index("凭据自动恢复")
        assert sh.index("mosquitto_passwd -c -b") > i_restore, \
            "口令文件生成先于凭据恢复：漂移值照样落盘（顺序错误）"
        # 两个方向都要恢复（用户名 + 密码），且不回显密码本身
        assert 'if [ "${USERNAME}" != ' in sh or sh.count('if [ "${USERNAME}" != ') >= 1
        assert 'if [ "${PASSWORD}" != ' in sh
        assert 'echo "[凭据自动恢复] 配置用户名' in sh
        # 严禁把恢复后的密码值打进启动日志（提示行本身允许存在）
        assert '恢复默认（密码不回显' in sh
        assert not re.search(r'echo[^"\n]*\$\{?PASSWORD', sh), \
            "密码回显面：echo 行引用了 ${PASSWORD}"

    def test_config_yaml_schema_defaults(self):
        cfg = _read(ROOT / "config.yaml")
        assert re.search(r"^\s+username:\s+str=huijian\s*$", cfg, re.M), \
            "schema 默认值未对齐固件内置用户名"
        assert re.search(r"^\s+password:\s+password=huijian2022\s*$", cfg, re.M), \
            "schema 默认值未对齐固件内置密码"

    def test_watchdog_rc_form(self):
        """bash -e 子壳继承下 `cmd; RC=$?` 恒死（v1.6.3 C3 同族）：
        失败在 cmd 行终止子壳，RC 永不赋值，判活逻辑全部不可达。
        注：修复说明注释里合法含有旧形态字样——只对非注释行判形态。"""
        sh = _read(ROOT / "run.sh")
        code = "\n".join(l for l in sh.splitlines()
                         if not l.strip().startswith("#"))
        assert code.count("|| RC=$?") >= 2, "watchdog 修复形态（|| RC=$?）丢失"
        assert "; RC=$?" not in code and "\nRC=$?" not in code, \
            "旧死亡形态回潮（分号/换行后裸 RC=$? 在 set -e 下不可达）"
        assert code.count("RC=0") >= code.count("|| RC=$?"), \
            "|| RC=$? 缺 RC=0 预置配对"


class TestIngressMechanicalDiff:
    """ingress.conf 头注释承诺"与 run.sh heredoc 同步"——本测试让承诺成真的
    机械门禁（v1.7.12 审计：此前该声明不实，三次漂移全靠人工）。"""

    def test_heredoc_equals_template(self):
        sh = _read(ROOT / "run.sh")
        m = re.search(
            r"cat > /etc/nginx/http\.d/ingress\.conf <<NGINXEOF\n(.*?)\nNGINXEOF",
            sh, re.S)
        assert m, "run.sh 内 ingress.conf heredoc 丢失"
        body = m.group(1)
        # 运行期变量 → 模板占位的三个已知映射
        norm = (body
                .replace("${SUPERVISOR_HOST}", "supervisor")
                .replace("${HA_SUPERVISOR_TOKEN}", "DYNAMIC_TOKEN")
                .replace(r"\"", "'")
                .replace(r"\$", "$"))
        a = [l.strip() for l in norm.splitlines()
             if l.strip() and not l.strip().startswith("#")]
        b = [l.strip() for l in _read(ROOT / "ingress.conf").splitlines()
             if l.strip() and not l.strip().startswith("#")]
        assert a == b, (
            "run.sh heredoc 与 ingress.conf 漂移：\n"
            + "\n".join(f"  L{i}: {x!r} != {y!r}" for i, (x, y)
                        in enumerate(zip(a, b)) if x != y)
        )


# ==================== B-1/B-3/B-9/B-10：协议层功能钉桩 ====================

class TestSubscriptionRebuild:

    @pytest.mark.asyncio
    async def test_no_rebuild_when_client_unchanged_or_unsubscribed(self, monkeypatch):
        handler, _ = _mk(monkeypatch)
        handler._mqtt_client_id = None
        assert await handler._ensure_mqtt_subscription() is False, \
            "从未订阅（身份 None）不得触发动作"
        handler.hass.data["mqtt"] = object()
        handler._mqtt_client_id = id(handler.hass.data["mqtt"])
        assert await handler._ensure_mqtt_subscription() is False, \
            "client 未换代不得重订阅（每 30s 全量重订=抖动源）"

    @pytest.mark.asyncio
    async def test_rebuild_on_client_identity_change(self, monkeypatch):
        handler, _ = _mk(monkeypatch)
        old_client = object()
        handler.hass.data["mqtt"] = old_client
        handler._mqtt_client_id = id(old_client)

        calls = []

        async def fake_subscribe():
            calls.append(1)
            handler._mqtt_client_id = id(handler.hass.data.get("mqtt"))
            return True

        handler._subscribe_topics = fake_subscribe
        handler.hass.data["mqtt"] = object()  # 模拟条目 reload 换 client
        assert await handler._ensure_mqtt_subscription() is True
        assert calls == [1], "换代后必须重建订阅（否则入站永久失聪）"
        assert await handler._ensure_mqtt_subscription() is False, \
            "重建成功后身份须更新，下轮巡检不得重复重建"

    @pytest.mark.asyncio
    async def test_rebuild_failure_reschedules(self, monkeypatch):
        handler, _ = _mk(monkeypatch)
        handler.hass.data["mqtt"] = object()
        handler._mqtt_client_id = id(handler.hass.data["mqtt"])

        async def fake_subscribe():
            return False

        handler._subscribe_topics = fake_subscribe
        sched = []
        handler._schedule_reconnect = lambda: sched.append(1)
        handler.hass.data["mqtt"] = object()
        assert await handler._ensure_mqtt_subscription() is True
        assert handler._mqtt_client_id is None, \
            "订阅失败必须重置身份，让下轮巡检再试"


class TestDedupRollback:

    @pytest.mark.asyncio
    async def test_handler_exception_rolls_back_accounting(self, monkeypatch):
        """B-9：处理失败回滚记账——否则网关 2s 重发被 5s 去重窗吞掉。"""
        handler, _ = _mk(monkeypatch)
        now = 12345.0

        async def boom():
            raise RuntimeError("transient")

        with pytest.raises(RuntimeError):
            await handler._dispatch_with_dedup(boom(), "005_9_SN", now)
        assert "005_9_SN" not in handler._processed_messages, \
            "失败报文不得残留去重记账（重发必须放行）"

        done = []

        async def ok():
            done.append(1)

        await handler._dispatch_with_dedup(ok(), "005_9_SN", now + 1)
        assert done == [1], "回滚后同键重发必须正常处理"
        # 成功处理后记账在场：同键再来被去重
        await handler._dispatch_with_dedup(ok(), "005_9_SN", now + 2)
        assert done == [1], "正常去重语义必须保留（重放只处理一次）"

    def test_string_zero_id_bypasses_dedup(self):
        """B-10：_norm_cmd_id("0") == 0（假值）→ 直发旁路命中；
        旧版字符串 "0" 为真值参与去重，合法回包被静默丢弃。"""
        assert WindowControllerMQTTHandler._norm_cmd_id("0") == 0
        assert not WindowControllerMQTTHandler._norm_cmd_id("0")
        src = _read(MW / "_protocol.py")
        m = re.search(
            r'msg_id = self\._norm_cmd_id\(payload\.get\("id", 0\)\)\s*\n\s*if not msg_id:',
            src)
        assert m, "去重旁路未走归一化形态（B-10 回潮）"


class TestCtype005Gate:

    @pytest.mark.asyncio
    async def test_unknown_device_blocked_when_auto_discovery_off_ack_still_sent(
            self, monkeypatch):
        """B-6：关自动发现后未知设备 005 不得入库，但 ack 契约（005 必 ack）
        绝不许被门禁破坏——漏 ack = 网关 2s 重传风暴。"""
        dm = _MockDM()
        handler, pub = _mk(monkeypatch, dm)
        handler._auto_discovery_enabled = lambda: False
        payload = _envelope("005", 11, {"sn": DEV_SN, "status": "open",
                                        "position": 50})
        await handler._handle_ctype_005(payload, "005", payload["data"])
        assert dm.status_updates == [] and dm.added == [], \
            "门禁未拦截：未知设备仍然入库"
        acks = pub.by_ctype("005")
        assert len(acks) == 1 and acks[0]["id"] == 11, \
            "ack 必须照发且恰好 1 次（协议契约）"

    @pytest.mark.asyncio
    async def test_unknown_device_passes_when_auto_discovery_on(self, monkeypatch):
        dm = _MockDM()
        handler, pub = _mk(monkeypatch, dm)
        handler._auto_discovery_enabled = lambda: True
        payload = _envelope("005", 12, {"sn": DEV_SN, "status": "open",
                                        "position": 50})
        await handler._handle_ctype_005(payload, "005", payload["data"])
        assert dm.status_updates == [(DEV_SN, "open")], \
            "门禁开启时正常上报路径不得被误伤"
        assert len(pub.by_ctype("005")) == 1


class TestProtocolStaticPins:

    def test_subscribe_returns_bool_and_records_identity(self):
        src = _read(MW / "_protocol.py")
        head, rest = src.split("async def _subscribe_topics(self)", 1)
        sig = rest[:80]
        assert "-> bool" in sig, "订阅入口未返回成败（B-3 判据回潮）"
        body = rest.split("async def ")[0]
        assert "self._mqtt_client_id = id(" in body
        assert body.count("self._schedule_reconnect()") >= 1, \
            "订阅失败不补重连调度（B-3 回潮）"
        assert "return False" in body and "return True" in body

    def test_lifecycle_hooks(self):
        src = _read(MW / "_lifecycle.py")
        assert "async def _check_gateway_timeout" in src
        region = src[src.index("async def _check_gateway_timeout"):]
        assert "await self._ensure_mqtt_subscription()" in region, \
            "B-1：30s 巡检未挂钩订阅重建（client 换代后入站永久失聪）"
        idx_ensure = region.index("await self._ensure_mqtt_subscription()")
        idx_sleep = region.index("asyncio.sleep")
        assert idx_sleep < idx_ensure, "巡检须先 sleep 后 ensure（避免与启动订阅相争）"
        assert "MQTT 重新订阅失败" in src, "B-3：重连路径订阅失败未升级为异常"
        m2 = re.search(r"if self\._closing:.*?return.*?self\._check_task = "
                       r"asyncio\.create_task", src, re.S)
        assert m2, "B-4：create_task 前缺 _closing 复检（孤儿巡检任务复活面）"

    def test_hardening_forms(self):
        proto = _read(MW / "_protocol.py")
        ctypes = _read(MW / "_ctypes.py")
        assert "payload[:256]" in proto, "B-12：坏 JSON 日志未截断"
        assert "not isinstance(attrs, list)" in ctypes and \
            "not isinstance(attr, dict)" in ctypes, "B-7：attrs 双层类型守卫丢失"
        assert "errcode %d" not in ctypes and "errcode: %d" not in ctypes, \
            "B-11：errcode 非 int 时 %d 格式化抛错炸 handler（回潮）"
        assert ctypes.count("errcode") >= 3


# ==================== DM-F1/F3/F4 + E-1 忽略持久化 ====================

class TestDeviceManagerPins:

    def test_last_update_seeded_and_bumped(self):
        src = _read(PKG / "device_manager.py")
        # 种子（add_device 字典字面量）+ 刷新（update_device_status 索引赋值）
        assert src.count('"last_update": time.time()') >= 1, \
            "DM-F1：add_device 首建未播种 last_update"
        assert src.count('["last_update"] = time.time()') >= 3, \
            "DM-F1：上报路径 last_update 刷新缺位"
        m = re.search(r"def _notify_device_added_callbacks(.*?)def ",
                      src, re.S)
        assert m and "return_exceptions=True" in m.group(1) \
            and "BaseException" in m.group(1), \
            "DM-F4：回调 gather 裸抛 + 异常不可见"

    def test_race_rollback_branch(self):
        src = _read(PKG / "device_manager.py")
        assert "竞态" in src or "_manually_removed_devices" in src
        m = re.search(r"if \(device_sn in self\._manually_removed_devices(.*?)return None",
                      src, re.S)
        assert m, "DM-F3：手动删除竞态回滚分支丢失"
        assert "async_remove_device" in m.group(1), "回滚须清注册表幽灵设备"

    def test_mapping_written_on_add(self):
        src = _read(PKG / "device_manager.py")
        assert "_mapping[device_sn] = self.gateway_sn" in src or \
            "DEVICE_TO_GATEWAY_MAPPING" in src, "DM-F2：add_device 映射写入丢失"


class _PersistHass:
    def __init__(self, config_dir):
        self.config = SimpleNamespace(config_dir=config_dir)
        self.data = {c.DOMAIN: {}}

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


class TestIgnorePersistence:
    """E-1/CF-F2：忽略网关列表跨 HA 重启（persist JSON + 共享 set 对象）。"""

    def test_const_exists(self):
        assert c.GLOBAL_IGNORED_GATEWAYS == "global_ignored_gateways"

    @pytest.mark.asyncio
    async def test_roundtrip(self):
        from custom_components.window_controller_gateway import persist
        with tempfile.TemporaryDirectory() as tmp:
            hass = _PersistHass(tmp)
            ignored = {"100122501203", "100122501208"}
            hass.data[c.DOMAIN][c.DEVICE_TO_GATEWAY_MAPPING] = {}
            hass.data[c.DOMAIN][c.GLOBAL_IGNORED_GATEWAYS] = ignored
            await persist.save_persistent_data(hass)
            raw = json.loads(
                (Path(tmp) / persist.PERSISTENT_DATA_FILE).read_text(
                    encoding="utf-8"))
            assert raw["ignored_gateways"] == sorted(ignored), \
                "落盘必须为稳定序 list（diff 友好 + 去重语义）"
            hass2 = _PersistHass(tmp)
            await persist.load_persistent_data(hass2)
            assert hass2.data[c.DOMAIN][c.GLOBAL_IGNORED_GATEWAYS] == ignored

    def test_discovery_shares_and_saves(self):
        src = _read(PKG / "discovery.py")
        assert src.count("GLOBAL_IGNORED_GATEWAYS") >= 3, \
            "E-1：discovery 未与全局持久键共享 set（import+两处 setdefault）"
        # ignore/unignore 都必须调度落盘
        assert src.count("save_persistent_data(hass)") >= 2, \
            "E-1：忽略/取消忽略未触发持久化"
        assert 'update_kwargs["unique_id"] = gateway_key' in src, \
            "E-4：步骤 3.5 自动填充未回填 unique_id"
        assert "async_entry_for_domain_unique_id" in src, \
            "E-4：unique_id 占用者判重缺失（撞车即 InvalidData）"

    def test_backup_failure_is_loud(self):
        from custom_components.window_controller_gateway import persist
        src = _read(PKG / "persist.py")
        assert "备份轮转失败" in src, "E-8：.bak 轮转失败回潮静默"
        assert "降级直写主文件" in src, "E-8：非原子降级回潮静默"


# ==================== 配置流 / 发现 / api / utils ====================

class TestConfigFlowAndSurroundings:

    def test_cf_f1_ghost_uid_clear_call_shape(self):
        src = _read(PKG / "config_flow.py")
        assert "async_set_unique_id(None, raise_on_progress=False)" in src, \
            "CF-F1：清除幽灵 unique_id 形态丢失（raise_on_progress 必须 False）"

    def test_e11_exception_logging(self):
        src = _read(PKG / "config_flow.py")
        assert "_LOGGER.exception(" in src, "E-11：cannot_connect 吞异常无堆栈"

    def test_e5_replace_walrus_guard(self):
        src = _read(PKG / "config_flow.py")
        assert "(sn := entry.data.get(CONF_GATEWAY_SN))" in src, \
            "E-5：replace 步骤对空 SN 引导条目 KeyError 回潮"

    def test_api_l11_scope_narrowing(self):
        src = _read(PKG / "api.py")
        m = re.search(r"if not config_entry_id:(.*?)return self\.json\(own\)",
                      src, re.S)
        assert m and "i[0] == DOMAIN" in m.group(1), \
            "L-11：devices 视图缺参回潮返回全设备注册表"

    def test_utils_e10_child_reverse_lookup(self):
        src = _read(PKG / "utils.py")
        region = src[src.index("def find_gateway_by_device_id"):]
        assert "DEVICE_TO_GATEWAY_MAPPING" in region, \
            "E-10：子设备 UUID → 映射反查所属网关的最后一跳丢失"

    def test_bootstrap_b2_and_broker_guard(self):
        src = _read(PKG / "mqtt_bootstrap.py")
        assert 'entry_password.startswith("!")' in src, \
            "B-2：!secret/!env_var 托管凭据豁免丢失"
        assert "entry_password == (password or" in src, \
            "B-2：密码一致性比较缺失（凭据漂移不再修复）"
        gi = src.index("bootstrap 标记缺少 broker")
        ui = src.index("自动更新 MQTT")  # 凭据/条目更新分支
        assert gi < ui, "broker 空值熔断必须在条目增改分支之前（P0-1 回潮）"


# ==================== WS 网关 F2/F3/F6 ====================

class TestWsGatewayPins:

    def test_f2_identity_pop_and_stopping_guards(self):
        src = _read(PKG / "ws_gateway.py")
        assert "domain_data.get(WS_GATEWAY_DATA_KEY) is server" in src, \
            "F2：OSError 分支无条件 pop 回潮（误删并发成功方注册→孤儿监听）"
        assert "not current._stopping" in src, \
            "F2：热同步命中将停实例回潮（令牌同步静默失效）"
        assert "existing is not server" in src, \
            "F2：迟到撞车让位复检丢失"

    def test_f3_parallel_close(self):
        src = _read(PKG / "ws_gateway.py")
        m = re.search(r"async def async_stop.*?_bg_tasks", src, re.S)
        assert m and "asyncio.gather(" in m.group(0), \
            "F3：串行 ws.close（各 10s 超时叠加卡死 STOP 路径）回潮"

    def test_f6_value_whitelist(self):
        src = _read(PKG / "ws_gateway.py")
        assert 'not isinstance(value, (str, int, float))' in src, \
            "F6：dict/list value 透传假成功回潮"


# ==================== Web UI 静态形态（M/L 组） ====================

JS = _read(ROOT / "www" / "js" / "huijian.js")
HTML = _read(ROOT / "www" / "index.html")


class TestWebPins:

    def test_m1_empty_devices_not_offline(self):
        # 懒惰有界匹配（[^;] 含换行会跨语句误捕，禁用字符类贪婪）
        m = re.search(
            r"if \(!devices \|\| devices\.length === 0\) \{"
            r".{0,500}?updateGatewayStatus\(statusEl, '(\w+)'\)",
            JS, re.S)
        assert m, "M-1 锚点丢失"
        assert m.group(1) == "unknown", \
            f"M-1 回潮：空设备列表又直接标 {m.group(1)}"

    def test_m2_honest_broker_label(self):
        assert "MQTT 客户端" in HTML and 'id="haMqttStatus"' in HTML, \
            "M-2：index.html 标签未订正（或 JS 契约 id 被误改）"
        assert "客户端在线 (" in JS, "M-2：JS 文案未订正"

    def test_m3_toast_dedup(self):
        assert "querySelectorAll('.toast')" in JS, "M-3：toast 叠字回潮"

    def test_l2_position_null_guard(self):
        assert "pos !== undefined && pos !== null" in JS, \
            "L-2：position=null 渲染 'null%' / slider 置 'null' 回潮"

    def test_l3_pairing_window(self):
        assert "PAIRING_UNTIL" in JS, "L-3：配对窗口守卫丢失（黄徽被静默刷新覆写）"
        assert JS.count("delete PAIRING_UNTIL") >= 3, \
            "L-3：失败/收尾路径未清窗口"

    def test_l9_jsquote_line_terminators(self):
        m = re.search(r"function jsQuote\(v\) \{(.*?)\}", JS, re.S)
        body = m.group(1)
        assert r"\u2028" in body and r"\u2029" in body, \
            "L-9：JS 行终止符转义丢失"
        # 反斜杠加倍转义必须最先（顺序错=后续转义全被二次污染）
        assert body.index(r"replace(/\\/g") < body.index(r"replace(/\r/g"), \
            "L-9：反斜杠转义不在最前"

    def test_l10_sn_map_reset(self):
        assert "delete GATEWAY_SN_BY_ENTRY" in JS, \
            "L-10：全量重建前未清 SN 映射（残留脏 SN 发控制）"

    def test_l6_rename_validation(self):
        assert "cleaned.length > 64" in JS and r"\u001f" in JS, \
            "L-6：改名客户端校验回潮"

    def test_l4_refresh_reentry_guard(self):
        assert "_refreshAllBusy" in JS, "L-4：refreshAll 防重入丢失"


# ==================== 发现代理 F7 + CI 加固 I 组 ====================

class TestProxyAndCI:

    def test_f7_replay_after_successful_publish(self):
        src = _read(ROOT / "gateway_discovery_proxy.py")
        i_pub = src.index("ok1 = self._pub")
        i_add = src.index("self._replayed.add(sn)")
        assert i_pub < i_add, \
            "F7：_replayed 先于发布消费（失败即永久漏放）回潮"
        assert "if ok1 is False" in src, "F7：发布失败留痕/重试丢失"
        assert "return r.returncode == 0" in src, "F7：_pub 未回传成败"

    def test_ci_fail_fast_and_gates(self):
        ci = _read(ROOT.parent / ".github" / "workflows" / "ci.yaml")
        assert ci.count("版本提取失败") >= 2, "I-1：VERSION 空值 fail-fast 丢失"
        assert "tests/e2e/*.sh" in ci, "I-2：e2e 脚本未入 bash -n 语法门"
        assert "fetch-depth: 20" in ci, "I-3：changelog 兜底 git log 深度不足"
        assert "PREPARED:" in ci, "I-4：Gitee 正文未复用 prepare 产物"

    def test_manifest_http_dependency(self):
        mf = json.loads(_read(PKG / "manifest.json"))
        assert "http" in mf.get("dependencies", []), \
            "api.py 注册 HomeAssistantView 依赖 http，manifest 须显式声明"
