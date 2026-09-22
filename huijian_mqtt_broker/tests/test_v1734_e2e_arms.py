"""v1.7.34 钉桩：真栈 E2E driver 新增 K/L 两臂（CI 硬门禁，本地无 docker）。

K 臂：未配置网关首报 001 → `gateway/{sn}/req` 上**恰好一条**同型代答
      （head/ctype/id/sn 回带 + data.errcode:0 + uuid）+ 发现卡挂起。
L 臂：空 SN 等待条目 + 首报 → SN 自动填进**同一条目**、条目 loaded、
      子设备真注册、**零**发现卡（"直接添加到集成"零点击契约），
      且两耳并存（handler 耳 + 心跳耳）时仍 1 请求 1 答。

本地无 docker（run_local.sh 走 WSL），故两臂的 CI 真栈结果由 e2e job 承担；
本文件守两件事：①两臂不被悄悄删掉/断言被稀释；②两臂的判定助手**本身**
不是空转——把 `_check_single_ack` / `_wait_acks` 从 driver 源文本抽出真跑，
多答/错形/漏 uuid 必须真 die（否则 CI 绿是假的）。
"""
import json
import pathlib
import time
from types import SimpleNamespace

HERE = pathlib.Path(__file__).resolve().parent
DRIVER = HERE / "e2e" / "ha_e2e_driver.py"
SRC = DRIVER.read_text(encoding="utf-8")

NEW_GW = "E2EGW0000002"
AUTO_GW = "E2EGW0000003"
AUTO_DEV = "500700000002"


# ============ ① 两臂存在性与断言强度（静态钉） ============
class TestArmsPresent:
    def test_arm_k_first_report(self):
        assert f'NEW_GW = "{NEW_GW}"' in SRC
        i_k = SRC.index('step("K"')
        assert 'pc.publish("gateway/rpt_rsp", json.dumps(_first_report(NEW_GW, 7101)))' \
            in SRC[i_k:], "K 臂必须真发首报 001（不是只订不发的空转臂）"
        assert "_check_single_ack(_k_acks, NEW_GW, 7101" in SRC[i_k:], \
            "K 臂必须走恰好一答判定"
        assert "_cards_for(NEW_GW)" in SRC[i_k:], "K 臂必须验发现卡挂起"

    def test_arm_l_zero_click(self):
        assert f'AUTO_GW = "{AUTO_GW}"' in SRC
        i_l = SRC.index(f'AUTO_GW = "{AUTO_GW}"')   # 从常量块起（含 AUTO_DEV）
        seg = SRC[i_l:]
        assert '{"gateway_sn": "", "gateway_name": ""}' in seg, \
            "L 臂必须用发现代理同款空 SN REST 路径建等待条目"
        assert "if filled_id != awaiting_id:" in seg, \
            "L 臂必须验 SN 填进的是**同一条**等待条目（新建条目=零点击契约破）"
        assert 'if filled_state != "loaded":' in seg, \
            "L 臂必须验填充后条目真 loaded（update listener 单驱动 reload）"
        assert "_stray" in seg and "不得再弹发现卡" in seg, \
            "L 臂必须验零发现卡（弹卡=用户被要求确认已加进来的网关）"
        assert AUTO_DEV in seg and "config_entry_id={filled_id}" in seg, \
            "L 臂必须验填充后的条目真接管上报（子设备注册）"
        assert "_check_single_ack(_l_acks, AUTO_GW, 7202" in seg, \
            "L 臂必须验两耳并存时仍恰好一答"

    def test_arms_run_before_soak(self):
        """顺序钉：两臂必须在 J 段 500 条 soak 之前——否则 req 主题被洪水
        污染，恰好一答的计数无从判读。"""
        assert SRC.index('step("K"') < SRC.index('step("J"')
        assert SRC.index('step("L"') < SRC.index('step("J"')
        assert SRC.index('step("K"') < SRC.index('step("L"'), \
            "K 臂（单耳）必须先于 L 臂（两耳）——应答者数量是递增的"

    def test_ack_recording_keeps_topic(self):
        """计数按主题甄别：只记 payload 的老形态无法区分代答归属。"""
        assert "ack_msgs.append((msg.topic, raw))" in SRC
        assert "acks.append(raw)" in SRC, "旧 acks 列表不得删（H/H2 段仍用）"

    def test_summary_reports_both_arms(self):
        i = SRC.index("GITHUB_STEP_SUMMARY")
        assert "首报 001 代答" in SRC[i:] and "零点击自动添加" in SRC[i:]


# ============ ② 判定助手真跑（防空转绿） ============
def _load_helpers(ack_msgs=None, die_calls=None):
    """从 driver 源文本抽出两个助手真跑——driver 是脚本（导入即执行 A 段），
    只能按锚切片 exec。切片锚丢失即 KeyError，静态钉会先红。"""
    start = SRC.index("def _wait_acks(")
    end = SRC.index("# ---------- K.")
    ns = {"json": json, "time": time, "ack_msgs": ack_msgs if ack_msgs is not None else []}

    def die(msg):
        if die_calls is not None:
            die_calls.append(msg)
        raise SystemExit(msg)

    ns["die"] = die
    exec(compile(SRC[start:end], str(DRIVER), "exec"), ns)  # noqa: S102
    return ns


def _ack(sn, msg_id, uuid="84cfcfbf-0000-0000-0000-000000000000", ctype="001",
         errcode=0, head="$SH"):
    data = {} if uuid is None else {"errcode": errcode, "uuid": uuid}
    if errcode is None:
        data.pop("errcode", None)
    return (f"gateway/{sn}/req",
            json.dumps({"head": head, "ctype": ctype, "id": msg_id,
                        "sn": sn, "data": data}))


class TestCheckSingleAck:
    def _run(self, seen, sn=NEW_GW, msg_id=7101):
        calls = []
        ns = _load_helpers(die_calls=calls)
        try:
            ns["_check_single_ack"](seen, sn, msg_id, "T")
        except SystemExit:
            pass
        return calls

    def test_one_good_ack_passes(self):
        assert self._run([_ack(NEW_GW, 7101)]) == []

    def test_two_acks_die(self):
        """仲裁失效（v1.7.30 前的 1 请求 2~3 答）必须真红。"""
        calls = self._run([_ack(NEW_GW, 7101), _ack(NEW_GW, 7101)])
        assert len(calls) == 1 and "恰好 1 条" in calls[0]

    def test_zero_ack_dies(self):
        calls = self._run([])
        assert len(calls) == 1 and "实得 0" in calls[0]

    def test_wrong_id_dies(self):
        calls = self._run([_ack(NEW_GW, 9999)])
        assert len(calls) == 1 and "不同形" in calls[0]

    def test_missing_uuid_dies(self):
        calls = self._run([_ack(NEW_GW, 7101, uuid=None)])
        assert len(calls) == 1 and "uuid" in calls[0]

    def test_nonzero_errcode_dies(self):
        calls = self._run([_ack(NEW_GW, 7101, errcode=5)])
        assert len(calls) == 1 and "errcode" in calls[0]

    def test_unrelated_traffic_on_same_topic_ignored(self):
        """同主题的非 001 报文（handler 自身业务）不计入代答数。"""
        assert self._run([_ack(NEW_GW, 7101, ctype="002"),
                          _ack(NEW_GW, 7101)]) == []

    def test_other_topic_not_counted_by_wait(self):
        msgs = [_ack("E2EGW0000009", 7101), _ack(NEW_GW, 7101)]
        ns = _load_helpers(ack_msgs=msgs)
        got = ns["_wait_acks"](f"gateway/{NEW_GW}/req", 0, timeout=1, settle=0)
        assert [t for t, _ in got] == [f"gateway/{NEW_GW}/req"]


class TestWaitAcksSettles:
    def test_late_second_ack_is_caught(self):
        """反假绿：只等到第一条就返回会漏掉晚到的第二个应答者——助手必须
        在凑够 want 条后再静置 settle 秒重新计数（settle=0 即失效）。"""
        msgs = [_ack(NEW_GW, 7101)]
        ns = _load_helpers(ack_msgs=msgs)
        real_sleep = time.sleep

        def fake_sleep(sec):
            if sec == 0.3 and len(msgs) == 1:
                msgs.append(_ack(NEW_GW, 7101))   # settle 期间第二答到达
            real_sleep(0)

        ns["time"] = SimpleNamespace(sleep=fake_sleep, time=time.time)
        got = ns["_wait_acks"](f"gateway/{NEW_GW}/req", 0, want=1,
                               timeout=2, settle=0.3)
        assert len(got) == 2, f"晚到的第二答必须被计入，实得 {got}"

    def test_settle_constant_is_nonzero(self):
        """静置窗不得被调成 0（调 0 = 本臂退化为"只等第一答"的假绿）。"""
        assert "def _wait_acks(topic, since, want=1, timeout=30, settle=2.0):" in SRC
