#!/usr/bin/env python3
"""v1.7.11 快速自动发现代理 —— 跑在加载项容器内（broker 同侧）。

背景（代码读出的结构性缺口）：HA 侧既有自动发现触发器全部挂在集成条目上——
心跳监听器挂「无 SN 等待条目」，_protocol 的其它网关发现挂「已配置条目」。
全新 HA（零条目）没有任何人订阅 gateway/rpt_rsp，网关主动上报落空，
发现卡片永远不出现（用户只能手动填 SN）。

方案（真栈实锤后定案，绕开两条死路）：
  死路 A：REST POST /config/config_entries/flow 发起 discovery——HA 的
    ConfigManagerFlowIndexView.get_context() 无条件把 source 改写为 user
    （components/config/config_entries.py 源码实锤），discovery 分支进不去；
    且 REST 无主 flow 在请求结束即被回收（实测 1 秒蒸发）。
  死路 B：WebSocket 建流——本地 HA 2026.1.3 全量注册命令里根本没有
    "config_entries/flow" 创建命令（只有 progress/subscribe/ignore 等）。
  正解：代理只做「给 HA 装耳朵」这一最小动作——捕获网关上报（001/002/005）
  后，若集成尚无任何 config entry，经 REST 创建一个 gateway_sn 留空的
  「等待模式」条目（ha_e2e_driver.py 同款 POST+step 提交，持久可靠）；该条目
  setup 时挂载既有心跳监听器（v1.6.26 A-2 已解决 MQTT 晚就绪竞态），代理随即
  把捕获的原报文经 mosquitto_pub 重放一次（仅一次/SN），新耳朵立刻听到 →
  走集成内部 async_discover_gateway → 弹标准"慧尖网关"发现卡片。此后其它
  网关/后续上报全由集成既有链路承接。

边界与语义：
- **网关卡片仍须用户点击确认**——代理创建的是零功能「等待条目」（无 SN 不
  forward 实体、不 ack、只订阅一个 topic 当耳朵），不替用户配对任何网关。
- 重放防回环：每 SN 一生至多重放一次；重放消息若被其它已配置条目处理会产生
  重复 ack，但网关侧对重复 ack 幂等（5s 去重窗），风险可忽略。
- HA 重启窗口（连不上 REST）：不记状态，下一条上报自然重试（上报节奏 ≤10s）。
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

SN_RE = re.compile(r"^[a-zA-Z0-9]{10,}$")
TRIGGER_CTYPES = {"001", "002", "005"}
DOMAIN = "window_controller_gateway"

# 默认走 Supervisor core API（加载项容器内 with-contenv 提供 supervisor 主机名
# 与 SUPERVISOR_TOKEN，与 nginx /api/ha/ 同源）；E2E/调试用环境变量覆盖直连。
DEFAULT_API = "http://supervisor/core/api"
RETRY_HTTP_FAIL = 30.0


def parse_report(raw: str):
    """解析一行 rpt_rsp；返回 (sn, ctype)，非触发报文返回 None。

    与集成内 handle_gateway_response / _heartbeat_listener 同防御口径：
    head 校验、ctype 白名单、SN 类型守卫（int/float 转 str，bool/dict 丢弃）、
    ≥10 位字母数字格式校验。
    """
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("head") != "$SH":
        return None
    ctype = payload.get("ctype")
    if ctype not in TRIGGER_CTYPES:
        return None
    sn = payload.get("sn")
    if isinstance(sn, bool) or not isinstance(sn, (str, int, float)):
        return None
    sn = str(sn) if not isinstance(sn, str) else sn
    if not SN_RE.match(sn):
        return None
    return sn, ctype


def ha_api(path: str, method: str = "GET", body=None):
    """HA Core REST（Supervisor 通道）。返回解析后的 JSON；失败抛异常。"""
    api = os.environ.get("HUIJIAN_HA_API", DEFAULT_API)
    token = os.environ.get("HUIJIAN_HA_TOKEN") or os.environ.get("SUPERVISOR_TOKEN") or ""
    if not token:
        raise RuntimeError("缺 HA/SUPERVISOR token")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        api + path, data=data, method=method,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else None


class DiscoveryProxy:
    """耳朵引导 + 重放。http/pub 注入，单测无网络。"""

    def __init__(self, list_entries, create_ears, republish,
                 now=time.monotonic, log=print, sleep=time.sleep):
        self._list = list_entries
        self._create = create_ears
        self._pub = republish
        self._now = now
        self._log = log
        self._sleep = sleep
        self._replayed = set()   # 每 SN 至多重放一次
        self._next_try = 0.0     # 全局失败退避（HA 重启窗口）
        self._ears_confirmed = False  # 已确认存在过条目（不再 list）

    def has_entries(self) -> bool:
        if self._ears_confirmed:
            return True
        entries = self._list()
        if entries is None:  # 查询失败 → 不改变结论，走重试退避
            raise RuntimeError("entries query failed")
        found = any(e.get("domain") == DOMAIN for e in entries)
        if found:
            self._ears_confirmed = True
        return found

    def run_subprocess(self, argv) -> int:
        """长驻订阅循环。mosquitto_sub 退出（broker 重启等）即非零返回，
        交给外层 shell 看门狗重启——与 mdns_publisher 监督模式同构。"""
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, bufsize=1)
        try:
            for line in proc.stdout:
                try:
                    self.handle_line(line)
                except Exception as e:  # 单行毒数据不杀循环
                    self._log(f"[发现代理] 处理上报异常（忽略该行）: {e}")
            return proc.wait() or 1  # EOF（sub 退出）一律视为异常
        finally:
            if proc.poll() is None:
                proc.kill()

    def handle_line(self, raw: str) -> None:
        parsed = parse_report(raw)
        if parsed is None:
            return
        sn, ctype = parsed
        now = self._now()
        if now < self._next_try:
            return
        try:
            if self.has_entries():
                return  # 耳朵早已在（或用户自己加了条目）——纯观察，不重放
            # 1) 建等待条目（无 SN）
            outcome = self._create()
            if outcome not in ("created", "exists"):
                self._next_try = now + RETRY_HTTP_FAIL
                return
            self._ears_confirmed = True
            if outcome == "exists":
                self._log("[发现代理] 集成条目已存在，耳朵就位（无需引导）")
                return
            self._log(f"[发现代理] 已创建「等待配置」条目装耳朵（首报网关 {sn}）")
            # 2) 重放原报文让刚挂载的心跳监听器出卡。条目 setup（订阅挂载）
            # 与 create_entry 响应之间存在毫秒级竞态——立即一次 + 3s 兜底一次
            # （监听器幂等：同 SN 已配置时 _protocol/心跳再收也只是 no-op）。
            if sn not in self._replayed:
                self._replayed.add(sn)
                self._pub(raw.strip())
                try:
                    self._sleep(3.0)
                    self._pub(raw.strip())
                except Exception:
                    pass
                self._log("[发现代理] 已重放上报×2，集成内部发现链应弹出网关卡片")
        except Exception as e:
            self._next_try = self._now() + RETRY_HTTP_FAIL
            self._log(f"[发现代理] 引导失败（{e}），{int(RETRY_HTTP_FAIL)}s 后随下一条上报重试")


def _pub_factory(broker_argv):
    def pub(raw_line: str) -> None:
        subprocess.run(broker_argv + ["-m", raw_line],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=10, check=False)
    return pub


def list_entries_impl():
    try:
        return ha_api("/config/config_entries/entry")
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError):
        return None


def create_ears_impl():
    """REST 建流 + 提交空 SN。返回 "created"（真的新建了耳朵）/ "exists"
    （abort：条目已在，无需再建）/ False（可重试的失败）。"""
    try:
        fl = ha_api("/config/config_entries/flow", "POST", {"handler": DOMAIN})
        fid = (fl or {}).get("flow_id")
        if not fid:
            return "exists" if (fl or {}).get("type") == "abort" else False
        # 等待模式：gateway_sn 留空提交（config_flow 空 SN 分支 → 挂心跳监听器）
        step = {"gateway_sn": "", "gateway_name": ""}
        res = ha_api(f"/config/config_entries/flow/{fid}", "POST", step)
        rtype = (res or {}).get("type")
        if rtype == "create_entry":
            return "created"
        if rtype == "abort":
            # already_configured（空条目全局唯一保证/并发）→ 耳朵已在
            return "exists"
        return False  # form（意外形态）等 → 重试
    except urllib.error.HTTPError as e:
        # 400/404：集成代码尚未随 HA 重启加载——可重试失败
        _ = e
        return False
    except (urllib.error.URLError, ValueError, OSError):
        return False


def main(argv) -> int:
    if len(argv) < 4:
        print("用法: gateway_discovery_proxy.py <broker_port> <mqtt_user> <mqtt_password>")
        return 2
    port, user, password = argv[1], argv[2], argv[3]
    sub_argv = ["mosquitto_sub", "-h", "127.0.0.1", "-p", port,
                "-u", user, "-P", password, "-t", "gateway/rpt_rsp"]
    pub_argv = ["mosquitto_pub", "-h", "127.0.0.1", "-p", port,
                "-u", user, "-P", password, "-t", "gateway/rpt_rsp"]
    proxy = DiscoveryProxy(list_entries_impl, create_ears_impl, _pub_factory(pub_argv))
    print(f"[发现代理] 启动：订阅 gateway/rpt_rsp（127.0.0.1:{port}，用户 {user}）")
    return proxy.run_subprocess(sub_argv)


if __name__ == "__main__":
    # 容器内 stdout 重定向到 Supervisor 日志管道：无终端走全缓冲，崩溃/关键
    # 行会滞留——强制行缓冲，日志实时可见
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, OSError):
        pass
    sys.exit(main(sys.argv))
