# -*- coding: utf-8 -*-
"""跨仓契约钉的 pytest 入口 + "缺仓必须响亮跳过"元钉。

为什么要元钉：这类门禁最危险的失效方式不是红，而是**在对端仓不可见的环境里静默变绿**
（CI 拿不到私有的 hub / 小程序仓）。所以除了跑真对账，还要真跑一次"没有对端仓"的路径，
断言 rc==3——照 test_v1742_hub_identity.py 的既有纪律。
"""
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tests" / "e2e" / "cross_repo_contract.sh"
HUB_REPO = os.environ.get("HUB_REPO", r"E:\AI\huijian-cloud-hub")
MP_REPO = os.environ.get("MINIPROGRAM_REPO", r"E:\AI\ha-yy\weichat-huijian-hz")


def _run(env_extra):
    env = dict(os.environ)
    env.update(env_extra)
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, timeout=300, env=env)


def _text(r):
    return (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")


def test_contract_holds_across_three_repos():
    if not (Path(HUB_REPO) / "src" / "server.js").exists() or \
       not (Path(MP_REPO) / "miniprogram" / "utils" / "cloud-gw.js").exists():
        pytest.skip("对端仓不可见（HUB_REPO / MINIPROGRAM_REPO）；rc=3 路径由下一条钉住")
    r = _run({"HUB_REPO": HUB_REPO, "MINIPROGRAM_REPO": MP_REPO})
    out = _text(r)
    assert r.returncode == 0, "跨仓契约漂移：\n%s" % out
    assert "跨仓契约: " in out and " 0 failed" in out, out[-500:]
    # 防空跑：至少要对账这么多条，少了说明脚本被改瘪了。
    # 110 = v1.7.51 复审批的 100 + v1.7.52 新增 10（LAN 回执关联字段 3 / 004 属性名两侧 4 /
    # 两条通道格式模式同串 1 / 小程序线值全十进制 1 / VALUE_* 抽取量元钉 1 / 页面真读字段 1）。
    # 取精确下限：条数掉下来必须有人来解释，而不是静默变绿。
    assert out.count("PASS ") >= 110, "对账条数异常（%d，应≥110），脚本可能被改瘪" % out.count("PASS ")


def test_missing_repo_skips_loudly_with_rc3():
    """元钉：缺对端仓必须 rc=3（不是 0）。skip 变 exit 0 就等于门禁不存在。"""
    r = _run({"HUB_REPO": "", "MINIPROGRAM_REPO": ""})
    out = _text(r)
    assert r.returncode == 3, "缺仓时应 rc=3，实得 %d：%s" % (r.returncode, out)
    assert "SKIP" in out, "缺仓时必须打印 SKIP 说明（静默退出＝没人知道门禁没跑）"


def test_bogus_repo_path_also_skips_loudly():
    """路径存在但不是那个仓 ⇒ 同样 rc=3（防"指错目录还以为对过账"）。"""
    r = _run({"HUB_REPO": str(Path(__file__).resolve().parents[1]),
              "MINIPROGRAM_REPO": str(Path(__file__).resolve().parents[1])})
    assert r.returncode == 3, "指错仓时应 rc=3，实得 %d" % r.returncode
