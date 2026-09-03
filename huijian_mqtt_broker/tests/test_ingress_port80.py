"""v1.6.18 事故回归：加载项（host_network）绝不允许监听宿主 80。

2026-09-02 现场日志实锤：alpine nginx 包自带 /etc/nginx/http.d/default.conf
（listen 80 default_server; listen [::]:80）被 Dockerfile 重写后的
nginx.conf 以 `include /etc/nginx/http.d/*.conf` 拉入——宿主 80 空闲时插件
白占 80；宿主 80 被占时（NAS 部署常态）bind 失败打死整个 nginx master，
8099 侧边栏连坐全挂。旧 Dockerfile 注释"移除默认 server 块"是半截工程：
只删了 nginx.conf 内嵌默认块，从未删过 http.d 下的文件。

本文件钉桩三个静默失效面：
1. Dockerfile 构建期删除 default.conf，且重写版 nginx.conf 不含任何 listen；
2. run.sh 启动期先清扫 http.d 中一切 listen 80 杂散 conf，再启动 nginx；
3. 生成的 ingress 配置（模板文件 + run.sh 内 heredoc）只监听 8099。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# listen 80 / listen [::]:80（含 default_server 等后缀），但不误伤 8099
LISTEN_80 = re.compile(r"^\s*listen\s+(\[::\]:)?80(\s|;|$)", re.M)


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


class TestDockerfileNoHost80:
    def test_default_conf_removed_at_build(self):
        dockerfile = _read("Dockerfile")
        assert "RUN rm -f /etc/nginx/http.d/default.conf" in dockerfile, (
            "Dockerfile 必须构建期删除 alpine 默认站 conf，"
            "否则 host_network 下插件抢绑宿主 80（v1.6.18 事故）"
        )

    def test_rewrite_nginx_conf_has_no_listen(self):
        dockerfile = _read("Dockerfile")
        # 重写的 nginx.conf 全部 echo 行里不得出现 listen 指令
        nginx_conf_lines = [
            line for line in dockerfile.splitlines()
            if "/etc/nginx/nginx.conf" in line and "echo" in line
        ]
        assert nginx_conf_lines, "nginx.conf 重写段丢失？"
        for line in nginx_conf_lines:
            assert not LISTEN_80.search(line), f"nginx.conf 重写段混入 listen 80: {line}"
            assert not re.search(r"\becho\s+'[^\s']*listen\s", line), (
                f"nginx.conf 重写段不应内嵌任何 listen server: {line}"
            )


class TestRunShRuntimeGuard:
    def setup_method(self):
        self.run_sh = _read("run.sh")

    def test_runtime_sweep_present(self):
        assert "杂散默认站" in self.run_sh or "移除杂散" in self.run_sh, (
            "run.sh 缺少 http.d listen-80 运行期清扫兜底"
        )
        assert re.search(r"listen\[\[:space:\]\]", self.run_sh) or "grep -Eq" in self.run_sh

    def test_sweep_before_nginx_start(self):
        sweep = self.run_sh.find("移除杂散")
        start = self.run_sh.find("\nnginx ||")
        assert 0 <= sweep < start, "清扫必须发生在 nginx 首次启动之前，否则形同虚设"

    def test_start_failure_diagnostics(self):
        # v1.6.4 教训延续：失败路径必须带现场取证，不得只剩 syntax ok 假象
        block = self.run_sh[self.run_sh.find("\nnginx ||"):]
        assert "重试" in block.split("}")[0], "nginx 启动失败须有一次重试（宿主服务竞态窗口）"
        # v1.6.26（第八轮审计 E-4）：取证必须用 /proc/net/tcp{,6} 扫描——
        # alpine base 镜像**没有** netstat（本文件 §7 的 v1.6.4 注释早已
        # 实锤据此改道，唯独这处取证漏改，恰在最需要时无输出）。
        # 钉桩：新法在场 + **命令级** netstat 不得回潮（历史解释注释允许
        # 提及 netstat 字样，故只禁行首命令形态）。
        assert "/proc/net/tcp" in block, "取证须用 /proc/net/tcp 扫描（镜像内无 netstat）"
        assert "0A" in block, "取证须按 LISTEN 态(0A)过滤端口"
        assert not re.search(r"^\s*netstat\s", block, re.M), \
            "netstat 命令在 HA alpine base 不存在，取证禁止回潮"

    def test_generated_ingress_conf_only_8099(self):
        m = re.search(
            r"cat > /etc/nginx/http\.d/ingress\.conf <<NGINXEOF\n(.*?)\nNGINXEOF",
            self.run_sh, re.S)
        assert m, "run.sh 内 ingress.conf heredoc 丢失"
        body = m.group(1)
        listens = re.findall(r"^\s*listen\s+[^;]+;", body, re.M)
        assert listens and all("8099" in l for l in listens), (
            f"生成的 ingress 配置只能监听 8099，实际: {listens}"
        )
        assert not LISTEN_80.search(body)


class TestIngressTemplate:
    def test_repo_template_only_8099(self):
        template = _read("ingress.conf")
        listens = re.findall(r"^\s*listen\s+[^;]+;", template, re.M)
        assert listens, "模板里一个 listen 都没有？"
        assert all("8099" in l for l in listens), f"模板混入非 8099 监听: {listens}"
        assert not LISTEN_80.search(template)
