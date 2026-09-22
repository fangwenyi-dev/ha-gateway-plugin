"""Ingress/MQTT 端口的多真值源相等守卫（v1.7.32 全量审计 G2）。

v1.7.32 把 Web UI 端口从 8099 迁到 10998，立意是"五处收口一处不落"，但机
械对账只覆盖到其中四处：`test_v1712_audit.py` 做 run.sh heredoc ≡
ingress.conf 的逐行 diff、`test_ingress_port80.py` 钉两处 listen 只含
10998、`test_audit_round6.py` 钉 WS_RESERVED_PORTS 集合。**`config.yaml`
的 `ingress_port` 在 tests/ 与 .github/ 里零引用**（改它 → 655 全绿 +
Supervisor 注册的口与 nginx 实际 listen 不一致 → 侧边栏 502）。
同族第二处漏网：run.sh 取证门 `awk -v p99=':2AF6$'` 是手写十六进制，而
同文件另两处（MQTT/1883）走 `printf '%04X'` 派生——v1.7.32 commit message
自己点名"漏改则端口占用取证恒空"，却没配套守卫。
第三处：options 步的撞口文案漏报 8123，而代码确实拒绝 8123。

本文件把这些口按"值 → 出现处"逐一对账成集合等式。
"""
import re
from pathlib import Path

from custom_components.window_controller_gateway import const as c

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "custom_components" / "window_controller_gateway"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _config_yaml_ingress_port() -> int:
    m = re.search(r"^ingress_port:\s*(\d+)\s*$", _read(ROOT / "config.yaml"), re.M)
    assert m, "config.yaml 丢失 ingress_port 键"
    return int(m.group(1))


def _listen_ports(text: str) -> set:
    return {int(m) for m in re.findall(r"^\s*listen\s+(\d+)\s*;", text, re.M)}


def _run_sh_heredoc() -> str:
    src = _read(ROOT / "run.sh")
    m = re.search(
        r"cat > /etc/nginx/http\.d/ingress\.conf <<NGINXEOF\n(.*?)\nNGINXEOF",
        src, re.S)
    assert m, "run.sh 内 ingress.conf heredoc 丢失"
    return m.group(1)


class TestIngressPortSingleSource:
    def test_five_sources_agree(self):
        ingress_port = _config_yaml_ingress_port()
        assert ingress_port == c.INGRESS_PORT, (
            f"config.yaml ingress_port={ingress_port} ≠ const.INGRESS_PORT="
            f"{c.INGRESS_PORT}"
        )
        assert _listen_ports(_read(ROOT / "ingress.conf")) == {ingress_port}
        assert _listen_ports(_run_sh_heredoc()) == {ingress_port}
        assert ingress_port in c.WS_RESERVED_PORTS, (
            "ingress 口必须在 WS 网关保留口集合内，否则用户可把小程序直连"
            "端口配成同一值撞死 nginx"
        )

    def test_forensics_hex_matches_ingress_port(self):
        """run.sh 的 /proc/net/tcp 取证门十六进制必须等于 ingress 口。

        该处是手写 `:2AF6$`（同文件 MQTT/1883 两处走 printf 派生），端口一
        动即"取证恒空"——v1.7.32 commit message 自己点名的失效形态。守卫不
        要求改写形态，只要求值与真值源相等，且旧口残留必须清零。
        """
        src = _read(ROOT / "run.sh")
        ingress_hex = f":{format(c.INGRESS_PORT, '04X')}$"
        assert ingress_hex in src, (
            f"run.sh 缺少 ingress 口取证门 {ingress_hex}——换口后宿主端口被占"
            "时现场取证恒空"
        )
        assert "1F9B" not in src, "run.sh 残留旧 ingress 口（8099=1F9B）十六进制"
        assert ":0050$" in src, "宿主 80 占用取证门丢失（v1.6.18 事故面）"


class TestReservedPortMessageMatchesSet:
    """撞口文案里点名的端口集合 == WS_RESERVED_PORTS（两语言、两步骤）。"""

    def _texts(self):
        for name in ("strings.json", "translations/zh-CN.json"):
            src = _read(PKG / name)
            for key in ("ws_port_reserved",):
                for m in re.finditer(rf'"{key}":\s*"([^"]+)"', src):
                    yield name, m.group(1)

    def test_message_enumerates_exact_reserved_set(self):
        seen = list(self._texts())
        assert len(seen) >= 4, (
            f"撞口文案实例数缩水为 {len(seen)}（strings/zh-CN × config/options "
            "应有 4 处）——少一处，守卫就瞎一处"
        )
        want = c.WS_RESERVED_PORTS
        for name, text in seen:
            listed = {int(p) for p in re.findall(r"\d+", text)}
            assert listed == set(want), (
                f"{name} 的 ws_port_reserved 文案点名 {sorted(listed)} ≠ "
                f"WS_RESERVED_PORTS {sorted(want)}——用户按文案理解，代码却按"
                "集合拒绝"
            )
