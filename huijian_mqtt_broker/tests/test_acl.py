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
topic readwrite gateway/+
topic readwrite gateway/+/req
topic readwrite gateway/rpt_rsp
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
    """返回 (是否允许, 原因)。用户无定义 → 默认允许全部（mosquitto 语义）。"""
    if user not in acl:
        return True, "用户未在 ACL 中定义（默认允许）"
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


class TestUnknownUserDefaultAllow:
    def test_unknown_user_allowed(self):
        """mosquitto 语义：ACL 中未定义的用户默认允许全部（保持兼容）"""
        acl = parse_acl(ACL)
        ok, _ = check(acl, "some_other_client", "homeassistant/anything/#", "write")
        assert ok
