# -*- coding: utf-8 -*-
"""身份文件并发写竞态（v1.7.49 把写入移进 asyncio.to_thread 时引入的回归）。

改动前 `save_identity` 是事件循环里的同步调用 ⇒ 单线程天然串行、不可能竞态；
移进线程池后两个协程可真并发写同一个 `.tmp`：交错截断 ⇒ os.replace 落地半截/混合
JSON ⇒ 读回时判损坏改名 `.bad` ⇒ 重新注册 ⇒ **换 instanceId、作废所有人手上的绑定码、
云端多一条孤儿实例**。最易触发的两条路径：面板连点两次二维码（显式换码刻意不受 120s
节流）、用户点刷新与保活 tick 的自动补发重叠。

两道防线都要钉：① `_save_identity` 外层实例级锁（事件循环侧先串行化再进线程池）；
② `save_identity` 的 tmp 名唯一 + 异常清理。仓内先例是 persist.py 的模块级 `_save_lock`，
其注释原话就是"确保不会有两个协程同时写同一个 .tmp 文件"。
"""
import asyncio
import inspect
import json
import os
import re
import threading
import time

import pytest

from custom_components.window_controller_gateway import hub_client as hc

BIG = 300_000          # 撑大写入窗口：真实 secret 只有 48 字节，一次 write 就完事，抓不到交错


def _client(tmp_path, secret_len=BIG):
    c = hc.HubClient([], config_dir=str(tmp_path), session=object())
    c.instance_id = "inst-1"
    c._secret = "s" * secret_len
    c.bind_code = "111111"
    c._bind_code_at = 1.0
    return c


# ── ① 锁：两次写入在时间上绝不重叠 ────────────────────────────────────
def test_save_identity_calls_never_overlap(tmp_path, monkeypatch):
    """锁的行为钉：并发 gather 三个 _save_identity，被调的 sync worker 不得同时在里面。

    sleep 是刻意放大窗口——没有锁时三个 to_thread 必然重叠，这条立刻红。
    """
    client = _client(tmp_path, secret_len=64)
    inside = {"n": 0}
    overlaps = []
    real = hc.save_identity

    def watched(config_dir, data):
        inside["n"] += 1
        if inside["n"] > 1:
            overlaps.append(inside["n"])
        try:
            time.sleep(0.02)
            real(config_dir, data)
        finally:
            inside["n"] -= 1

    monkeypatch.setattr(hc, "save_identity", watched)

    async def run():
        await asyncio.gather(*[client._save_identity() for _ in range(3)])

    asyncio.run(run())
    assert overlaps == [], "两个协程同时进了身份写入＝锁没生效（.tmp 会被交错截断）"
    assert json.loads(open(hc.identity_path(str(tmp_path)), encoding="utf-8").read())["instanceId"] == "inst-1"


def test_identity_write_path_is_lock_protected():
    """结构钉：写入路径必须过实例级 asyncio.Lock，且锁按事件循环懒建（跨循环复用会 RuntimeError）。"""
    src = inspect.getsource(hc.HubClient._save_identity)
    assert re.search(r"async with self\._identity_write_lock\(\)", src), \
        "_save_identity 没有加锁（to_thread 下两个协程可真并发写同一个 .tmp）"
    assert "to_thread" in src, "身份写入必须仍在线程池里（HA 阻塞 IO 检测）"
    lock_src = inspect.getsource(hc.HubClient._identity_write_lock)
    assert "asyncio.Lock()" in lock_src and "get_running_loop" in lock_src, \
        "锁必须按当前事件循环懒建"


# ── ② 唯一 tmp 名：真多线程对撞也不出混合体 ───────────────────────────
def test_save_identity_tmp_name_is_unique():
    """结构钉：tmp 名必须由 mkstemp 生成（唯一），不得是拼出来的固定名。

    判据用正则锚定赋值语句而不是裸搜文本：docstring 里就写着 `path + ".tmp"` 这个反面
    例子，裸文本匹配会钉到注释（本仓踩过：钉到永不执行的那份代码）。
    """
    src = inspect.getsource(hc.save_identity)
    assert re.search(r"^\s*(?:\w+\s*,\s*)?tmp\s*=\s*tempfile\.mkstemp\(", src, re.M), \
        "tmp 名必须由 tempfile.mkstemp 生成（固定名＝并发写会互相截断）"
    assert "dir=config_dir" in src, "tmp 必须与目标同目录（跨盘 os.replace 会失败）"
    assert "os.replace(tmp, path)" in src, "写完必须原子替换到主文件"


def test_concurrent_saves_from_threads_never_mix(tmp_path):
    """8 个真线程同时写 300KB 身份：落地文件必须是**某一次的完整内容**，不是混合体。"""
    d = str(tmp_path)
    payloads = [{"instanceId": "inst-%d" % i, "secret": ("%d" % i) * BIG, "bindCode": "%06d" % i}
                for i in range(8)]
    errors = []

    def worker(payload):
        for _ in range(12):
            try:
                hc.save_identity(d, payload)
            except PermissionError:
                # Windows：两个线程同时 os.replace 同一个**目的**文件会撞共享冲突。
                # 那不是损坏（生产路径由 _save_identity 的锁串行化，走不到这里），
                # 本条要抓的是"落地内容成了混合体"。
                pass
            except Exception as e:  # noqa: BLE001 - 其余失败要如实报出来
                errors.append(repr(e))

    threads = [threading.Thread(target=worker, args=(p,)) for p in payloads]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    got = json.loads(open(hc.identity_path(d), encoding="utf-8").read())   # 解析失败＝落地了半截
    assert got in payloads, "落地文件是混合体（既不是这一次也不是那一次的完整内容）"
    assert got["secret"] == got["instanceId"][-1] * BIG, "字段来自两次不同的写入＝混合体"


def test_concurrent_async_saves_land_a_whole_file(tmp_path):
    """同一件事走 asyncio 路径（gather 两个 _save_identity）：最终文件必须是合法 JSON。"""
    client = _client(tmp_path)
    outcomes = []

    async def writer(tag):
        client.bind_code = "%06d" % tag
        client._bind_code_at = float(tag)
        await client._save_identity()
        outcomes.append(tag)

    async def run():
        await asyncio.gather(writer(1), writer(2))

    asyncio.run(run())
    assert sorted(outcomes) == [1, 2]
    got = json.loads(open(hc.identity_path(str(tmp_path)), encoding="utf-8").read())
    assert got["bindCode"] in ("000001", "000002"), "落地内容不是任何一次写入的完整结果：%r" % got["bindCode"]
    assert got["secret"] == "s" * BIG


def test_failed_save_leaves_no_tmp_behind(tmp_path):
    """写失败要清掉残留 tmp：留在 config_dir 里的垃圾文件没人会去收。"""
    with pytest.raises(TypeError):
        hc.save_identity(str(tmp_path), {"instanceId": object()})
    leftovers = [n for n in os.listdir(str(tmp_path)) if n.endswith(".tmp")]
    assert leftovers == [], "失败写入留下残留 tmp：%s" % leftovers
    assert not os.path.exists(hc.identity_path(str(tmp_path))), "失败写入不得留下半截主文件"


def test_lock_survives_a_new_event_loop(tmp_path):
    """锁按循环懒建：同一实例在两个 asyncio.run 里连续写不得 RuntimeError（绑定到旧循环）。"""
    client = _client(tmp_path, secret_len=64)
    asyncio.run(client._save_identity())
    client.bind_code = "222222"
    asyncio.run(client._save_identity())
    assert hc.load_identity(str(tmp_path))["bindCode"] == "222222"
