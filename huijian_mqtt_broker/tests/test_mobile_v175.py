"""v1.7.5 手机端两修：控制后不闪 + 卡片收窄
①控制/状态检查后 2s 走 updateGatewayDevices（静默只更新状态）——旧
  loadGatewayDevices innerHTML 全量重建会重放 .device-item fadeUp 入场
  动画 + backdrop-filter 重排，手机端慢渲染＝"控制后闪一下"根因；
  重命名保留重建（名称文本只在重建时刷新，低频可接受）
②手机端 .gateway-item（含内部子设备瓦片）与 .info-box（底部蓝色玻璃）
  320px 居中收窄
"""
import pathlib
import re

WWW = pathlib.Path(__file__).resolve().parents[1] / "www"
JS = (WWW / "js/huijian.js").read_text(encoding="utf-8")
CSS = (WWW / "css/huijian.css").read_text(encoding="utf-8")


class TestNoFlickerAfterControl:
    def test_control_and_status_use_silent_update(self):
        # 控制路径 + 状态检查路径：2s 后静默更新
        assert JS.count("setTimeout(() => updateGatewayDevices(") >= 2, \
            "控制/状态检查后须走 updateGatewayDevices（不重建=不闪）"
        # 控制路径 catch 紧跟的那次延时不得再是 loadGatewayDevices
        seg = JS[JS.index("控制失败") - 400:JS.index("控制失败")]
        assert "updateGatewayDevices" in seg and "loadGatewayDevices" not in seg
        # 重命名保留完整重建（名称只在重建刷新）
        rseg = JS[JS.index("重命名成功"):JS.index("重命名成功") + 200]
        assert "loadGatewayDevices" in rseg, "重命名后仍需重建刷新名称"

    def test_silent_update_has_rebuild_escalation(self):
        # 静默版必须自带集合变化升级重建，否则新设备永远等不到（v1.6.6 教训）
        body = JS[JS.index("async function updateGatewayDevices"):]
        body = body[:body.index("async function", 10)]
        assert "serverIds !== renderedIds" in body, "设备增删须自动升级完整重建"


class TestMobileNarrowCards:
    def _mobile_block(self):
        i = CSS.index("@media (max-width: 640px)")
        return CSS[i:]

    def test_gateway_and_info_box_capped(self):
        block = self._mobile_block()
        gw = re.search(r"\.gateway-item \{([^}]*)\}", block).group(1)
        ib = re.search(r"\.info-box \{([^}]*)\}", block).group(1)
        assert "max-width: 320px" in gw and "auto" in gw, "网关卡（含子设备）320 居中"
        assert "max-width: 320px" in ib and "auto" in ib, "底部蓝色玻璃 320 居中"
