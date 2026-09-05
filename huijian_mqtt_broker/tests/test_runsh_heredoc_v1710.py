"""v1.7.10 回归钉桩：run.sh 未引号 heredoc 体内的反引号会被 bash 当命令替换执行。

v1.7.9 现场实锤（HA2 启动日志）：桥 heredoc 注释里的反引号 password 打出
"line 664: password: command not found"——未引号 <<EOF 体内 `x` 全部是命令
替换，注释也不例外。函数上无害（rc 被忽略、conf 正常），但污染日志且误导排障。
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RUN = (Path(__file__).resolve().parents[1] / "run.sh").read_text(encoding="utf-8")


def _unquoted_heredoc_bodies(text):
    """返回 [(delimiter, body)]；跳过 <<'EOF' 引号形态（体内不展开，天然安全）。"""
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        m = re.search(r"<<-?\s*(\w+)", lines[i])
        quoted = re.search(r"<<-?\s*['\"]", lines[i])
        if m and not quoted:
            delim, body = m.group(1), []
            i += 1
            while i < len(lines) and lines[i].strip() != delim:
                body.append(lines[i])
                i += 1
            out.append((delim, "\n".join(body)))
        i += 1
    return out


class TestRunshHeredocBackticks:
    def test_no_backticks_in_unquoted_heredocs(self):
        bodies = _unquoted_heredoc_bodies(RUN)
        assert len(bodies) >= 5, f"heredoc 解析数异常（{len(bodies)}），钉桩失效须先修解析"
        for delim, body in bodies:
            assert "`" not in body, (
                f"run.sh heredoc <<{delim} 体内含反引号——bash 会执行命令替换，"
                "注释里也不允许；改用普通引号或全角引号"
            )

    @pytest.mark.skipif(shutil.which("bash") is None, reason="需要 bash")
    def test_fixed_form_runs_clean(self):
        """最小复现对照（bash -c 直传源码，绕开 Windows/WSL 路径翻译坑）：
        旧写法（反引号 password）必报 command not found，新写法 stderr 干净
        ——证明钉桩针对的机制真实存在。"""
        old_src = 'cat <<EOF\n# `password ` 空值行\nEOF\n'
        r_old = subprocess.run(["bash", "-c", old_src], capture_output=True, text=True)
        assert "password: command not found" in r_old.stderr, "复现前提失效（bash 行为变了？）"
        new_src = 'cat <<EOF\n# "password" 空值行\nEOF\n'
        r_new = subprocess.run(["bash", "-c", new_src], capture_output=True, text=True)
        assert r_new.stderr == "" and r_new.returncode == 0
