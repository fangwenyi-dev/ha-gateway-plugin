# -*- coding: utf-8 -*-
"""v1.7.42 守卫：hub 身份生命周期（抹盘后必须自愈）+ 真栈 e2e 不能被静默阉掉。

背景（用户真机第二条日志）：`[bind] 载荷解析: 命中` → `绑定返回: code_invalid`。
线上取证 `GET /healthz` 回 instances:0 / uptime:104s ⇒ hub 刚重启、注册表空
（`HUB_STORE=/data/store.json` 在云托管容器本地盘，每次部署即抹）。此前加载项抱着
死身份无限重连，面板显示的码是当前 hub 从未签发过的 ⇒ 永不自愈。

这里钉的是"三臂 e2e 与判据不漂移"，行为面本体在 test_hub_client.py（401/403 清身份、
5xx 与裸断不清）——本文件不重复断同一件事，只防两向漂移：
  1) e2e 三臂/文件被删或被稀释成摆设 → 红；
  2) e2e 在拿不到 hub 仓时"静默通过"（skip 不响亮＝门禁不存在）→ 红。
"""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E2E = ROOT / "tests" / "e2e"
DRIVER = E2E / "hub_lifecycle_driver.py"
SH = E2E / "hub_lifecycle_e2e.sh"
HARNESS = E2E / "hub_lifecycle_harness.js"

SRC = DRIVER.read_text(encoding="utf-8")
SH_SRC = SH.read_text(encoding="utf-8")


def test_files_exist():
    """三件套防删：driver 单独存在没用，起进程的那半被删就跑不起来。"""
    for p in (DRIVER, SH, HARNESS):
        assert p.exists(), "hub 生命周期真栈缺文件: %s" % p.name


def test_three_arms_are_real_checks():
    """防稀释：按 check( 真调用计数，注释里写"三臂"不算数。"""
    arms = ["A 长连建立并拿到 6 位绑定码", "B 保盘重启后 instanceId 未变",
            "C 抹盘重启后插件自愈并重连", "C 新码真能被 /bind 接受"]
    for a in arms:
        assert ('"%s"' % a) in SRC or ("%s" % a) in SRC, "缺臂: %s" % a
    assert SRC.count("check(") >= 13, "真栈断言只剩 %d 条，疑似被砍" % SRC.count("check(")


def test_cmd_arm_does_not_pass_on_forbidden():
    """/cmd 臂只判 err!=offline 会被 403 forbidden 蒙过（身份没自愈时正是 forbidden）。
    首轮实发踩过这条——断言必须要求"回执真来自长连那侧"。"""
    body = SRC[SRC.index('"/cmd"'):]
    seg = body[:body.index("check(") + 260]
    assert "control_unavailable" in seg, "/cmd 臂退回判 err!=offline＝假绿"


def test_wipe_is_genuine_store_deletion():
    """抹盘必须真删 storeFile——只重启进程＝只测了 B 臂，C 臂会伪装成通过。"""
    assert "STORE.unlink()" in SRC, "没真删注册表文件＝C 臂测的不是线上形态"
    assert "wipe=True" in SRC


def test_skip_is_loud_not_silent():
    """CI 拿不到私有 hub 仓 ⇒ 必须以非 0（3）退出并打印 SKIP，绝不能 exit 0。"""
    assert "sys.exit(3)" in SRC and 'SKIP' in SRC, "driver 的 skip 不响亮"
    assert "exit 3" in SH_SRC, "shell 包装的 skip 不响亮"


def test_skip_path_actually_exits_nonzero():
    """把上一条的叙述变成真执行：不带 HUB_REPO 跑 shell，必须非 0 且话里带 SKIP。"""
    env = dict(os.environ, HUB_REPO="", PYTHONIOENCODING="utf-8")
    r = subprocess.run(["bash", str(SH)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    out = r.stdout + r.stderr
    assert r.returncode == 3, "无 hub 仓时 rc=%s（0＝静默放行）: %s" % (r.returncode, out[:200])
    assert "SKIP" in out, "跳过时没留下可见痕迹"


def test_harness_uses_the_real_hub_source():
    """起的是 hub 仓的 createHub，不是本仓复制的协议影子（复制一份就是一份会漂移的契约）。"""
    js = HARNESS.read_text(encoding="utf-8")
    assert "require(path.join(repo, 'src', 'server.js'))" in js, "harness 不再引用真 hub 源码"
    assert "createHub(" in js
