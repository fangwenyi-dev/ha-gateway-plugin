"""ACL 权限矩阵测试 — 模拟 run.sh 生成的双用户 ACL，验证 mosquitto 匹配语义。"""
import re

# 与 run.sh 生成逻辑一致（HA_MQTT_USER_CREATED=true 分支）
ACL = """
user huijian
topic readwrite gateway/+
topic readwrite gateway/+/req
topic readwrite gateway/rpt_rsp
topic readwrite homeassistant/status
topic readwrite test/#
topic read $SYS/#

user ha_mqtt
topic readwrite homeassistant/#
topic readwrite zigbee2mqtt/#
topic readwrite gateway/+
topic readwrite gateway/+/req
topic readwrite gateway/rpt_rsp
topic read $SYS/#

user huijian_z2m
topic readwrite zigbee2mqtt/#
topic readwrite homeassistant/#
topic read $SYS/#
"""

# 回退分支（ha_mqtt 创建失败时）：ACL 只有 huijian 块，末尾追加的
# topic 归属最近的 user（huijian）—— mosquitto 的 topic 归属语义。
ACL_FALLBACK = """
user huijian
topic readwrite gateway/+
topic readwrite gateway/+/req
topic readwrite gateway/rpt_rsp
topic readwrite homeassistant/status
topic readwrite test/#
topic read $SYS/#

# 回退：ha_mqtt 创建失败，huijian 保留 HA discovery 权限
topic readwrite homeassistant/#
"""


def parse_acl(text):
    acl = {}
    current_user = None
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("user "):
            current_user = line.split()[1]
            acl.setdefault(current_user, [])
        elif line.startswith("topic "):
            parts = line.split()
            acl.setdefault(current_user, []).append((parts[1], parts[2]))
    return acl


def mqtt_match(pattern, topic):
    # MQTT 规范（mosquitto ACL 同语义）：通配符订阅不匹配 $ 前缀系统主题
    if topic.startswith("$") and pattern.split("/")[0] in ("#", "+"):
        return False
    regex_parts = []
    for p in pattern.split("/"):
        if p == "#":
            regex_parts.append(".*")
        elif p == "+":
            regex_parts.append("[^/]+")
        else:
            regex_parts.append(re.escape(p))
    return re.fullmatch("/".join(regex_parts), topic) is not None


def check(acl, user, topic, operation):
    """返回 (是否允许, 原因)。

    v1.6.12（第五轮审计）：未列用户改判**默认拒绝**——此前按 mosquitto 1.x
    旧语义钉成"默认允许全部"，而本项目实跑 mosquitto 2.x：官方迁移文档
    （https://mosquitto.org/documentation/migrating-to-2-0/）明确 2.0 起
    用户名不在 acl_file 中不再享有全量访问。测试模型必须与运行时一致，
    否则日后新增不经 run.sh 生成 ACL 的用户会出现"测试绿、真机全拒"。
    """
    if user not in acl:
        return False, "用户未在 ACL 中定义（mosquitto 2.x 默认拒绝）"
    for action, pattern in acl[user]:
        if mqtt_match(pattern, topic):
            if action == "readwrite":
                return True, f"匹配 {pattern}"
            if action == "read":
                return operation == "read", f"匹配只读 {pattern}"
            if action == "deny":
                return False, f"匹配 deny {pattern}"
    return False, "无匹配规则"


class TestGatewayUser:
    def setup_method(self):
        self.acl = parse_acl(ACL)

    def test_subscribe_command_topic(self):
        ok, _ = check(self.acl, "huijian", "gateway/100122501207/req", "read")
        assert ok

    def test_publish_status(self):
        ok, _ = check(self.acl, "huijian", "gateway/rpt_rsp", "write")
        assert ok

    def test_publish_birth_will(self):
        ok, _ = check(self.acl, "huijian", "homeassistant/status", "write")
        assert ok

    def test_publish_health_check(self):
        ok, _ = check(self.acl, "huijian", "test/ping", "write")
        assert ok

    def test_read_sys(self):
        ok, _ = check(self.acl, "huijian", "$SYS/broker/version", "read")
        assert ok

    def test_security_cannot_write_discovery(self):
        """安全关键：huijian（网关）不能写 homeassistant/#（防伪造 HA 发现）"""
        ok, _ = check(self.acl, "huijian", "homeassistant/sensor/abc/config", "write")
        assert not ok

    def test_security_cannot_read_discovery(self):
        ok, _ = check(self.acl, "huijian", "homeassistant/switch/abc/config", "read")
        assert not ok


class TestHaMqttUser:
    def setup_method(self):
        self.acl = parse_acl(ACL)

    def test_write_discovery(self):
        ok, _ = check(self.acl, "ha_mqtt", "homeassistant/sensor/abc/config", "write")
        assert ok

    def test_read_discovery(self):
        ok, _ = check(self.acl, "ha_mqtt", "homeassistant/switch/abc/config", "read")
        assert ok

    def test_subscribe_gateway_response(self):
        ok, _ = check(self.acl, "ha_mqtt", "gateway/rpt_rsp", "read")
        assert ok

    def test_send_pair_command(self):
        ok, _ = check(self.acl, "ha_mqtt", "gateway/100122501207/req", "write")
        assert ok

    def test_read_sys(self):
        ok, _ = check(self.acl, "ha_mqtt", "$SYS/broker/clients/total", "read")
        assert ok


class TestFallbackAcl:
    def test_fallback_grants_huijian_discovery(self):
        """ha_mqtt 创建失败的回退：huijian 必须保留 homeassistant/# 权限（旧行为）"""
        acl = parse_acl(ACL_FALLBACK)
        ok, _ = check(acl, "huijian", "homeassistant/sensor/abc/config", "write")
        assert ok


class TestUnknownUserDefaultDeny:
    def test_unknown_user_denied(self):
        """mosquitto 2.x 语义：ACL 中未定义的用户默认拒绝一切访问"""
        acl = parse_acl(ACL)
        ok, _ = check(acl, "some_other_client", "homeassistant/anything/#", "write")
        assert not ok
        ok, _ = check(acl, "some_other_client", "gateway/100122501207/req", "read")
        assert not ok


class TestBridgeEraSemantics:
    """v1.6.24：桥时代 ACL 语义（审计 C-A1 整改——含变更动机断言）"""
    def setup_method(self):
        self.acl = parse_acl(ACL)

    def test_ha_mqtt_reads_bridge_topics(self):
        ok, _ = check(self.acl, "ha_mqtt", "zigbee2mqtt/lamp/state", "read")
        assert ok, "桥 in 腿注入的 z2m 状态 HA 必须可订阅（变更核心动机）"
        ok, _ = check(self.acl, "ha_mqtt", "zigbee2mqtt/lamp/set", "write")
        assert ok, "HA 下发 z2m 命令（out 腿）必须可发布"

    def test_ha_mqtt_no_wildcard_escalation(self):
        ok, _ = check(self.acl, "ha_mqtt", "someother/plugin/topic", "write")
        assert not ok, "白名单外第三方主题必须拒（readwrite # 已按评审摘除）"

    def test_z2m_direct_user_matrix(self):
        acl = self.acl
        ok, _ = check(acl, "huijian_z2m", "zigbee2mqtt/bridge/state", "write")
        assert ok
        ok, _ = check(acl, "huijian_z2m", "homeassistant/sensor/z/config", "write")
        assert ok, "z2m 需发布 discovery 配置"
        ok, _ = check(acl, "huijian_z2m", "gateway/rpt_rsp", "write")
        assert not ok, "z2m 账号不得触慧尖网关域（与桥白名单同边界）"
        ok, _ = check(acl, "huijian_z2m", "$SYS/broker/version", "write")
        assert not ok, "$SYS 只读（通配符不匹配 $ 前缀的规范语义亦被钉）"


class TestAclCouplingWithRunSh:
    """审计 C-A1 整改：夹具与 run.sh 生成逻辑必须耦合——run.sh 改 ACL
    而忘改夹具时，本测试红（v1.6.24 的静默漂移即历史实例）。"""

    @staticmethod
    def _gen_lines(text, start_pat, end_pat):
        m = re.search(start_pat, text)
        assert m, "run.sh ACL 段结构变了（同步夹具前先对齐这里）"
        rest = text[m.end():]
        e = re.search(end_pat, rest)
        assert e, "ACL 段终点锚缺失"
        return [l.strip() for l in rest[:e.start()].splitlines()
                if l.strip().startswith("topic")]

    def test_ha_mqtt_section_matches_fixture(self):
        from pathlib import Path
        text = Path(__file__).resolve().parents[1].joinpath("run.sh").read_text(encoding="utf-8")
        gen = self._gen_lines(text, r"user \$\{HA_MQTT_USERNAME\}", r"\nEOF\n    else")
        assert len(gen) == 6, f"ha_mqtt 段生效 topic 行数变了: {gen}"
        # 生成器含转义 \$SYS，夹具字面 $SYS——归一比对
        gen_norm = [g.replace("\\$SYS", "$SYS") for g in gen]
        fx_norm = [f"topic {a} {p}" for (a, p) in parse_acl(ACL)["ha_mqtt"]]
        assert gen_norm == fx_norm, f"漂移: gen={gen_norm} fixture={fx_norm}"

    def test_z2m_direct_section_matches_fixture(self):
        from pathlib import Path
        text = Path(__file__).resolve().parents[1].joinpath("run.sh").read_text(encoding="utf-8")
        gen = self._gen_lines(text, r"user \$\{Z2M_USERNAME\}", r"\nEOF\n\} > ")
        fx = [f"topic {a} {p}" for (a, p) in parse_acl(ACL)["huijian_z2m"]]
        gen_norm = [g.replace("\\$SYS", "$SYS") for g in gen]
        assert gen_norm == fx, f"z2m 段漂移: gen={gen_norm} fixture={fx}"
