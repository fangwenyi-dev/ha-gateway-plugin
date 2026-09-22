#!/usr/bin/env bash
# hub 生命周期真栈 e2e（v1.7.42）：真 node hub 进程 + 真 HubClient + 真 /bind。
#
# 与 run_e2e.sh（HA 真栈）的分工：那条跑的是"网关→HA→发现/配对/仲裁"，
# 本条跑的是"加载项⇄慧尖云 hub"的**身份生命周期**——注册、保盘重启、抹盘重启。
# 第三条是 v1.7.41 的盲区：线上 hub 重新部署会抹掉容器本地盘的注册表，
# 加载项抱着死身份无限重连，面板显示的是当前 hub 从未签发的码 ⇒ 必然 code_invalid。
#
# 依赖 huijian-cloud-hub（私有仓）⇒ CI 侧拿不到，此时以 exit 3 **响亮跳过**并由
# tests/test_v1742_hub_identity.py 钉住"跳过必须可见"，绝不降级成"静默通过"。
# 本地跑：HUB_REPO=/e/AI/huijian-cloud-hub bash huijian_mqtt_broker/tests/e2e/hub_lifecycle_e2e.sh
set -Eeuo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"          # huijian_mqtt_broker/
HUB_REPO="${HUB_REPO:-}"

for c in node python; do
    command -v "$c" >/dev/null || { echo "!! 缺 $c，无法跑 hub 生命周期 e2e"; exit 1; }
done

if [ ! -f "$HUB_REPO/src/server.js" ]; then
    echo "SKIP hub 生命周期 e2e：HUB_REPO 未指向 huijian-cloud-hub（当前='${HUB_REPO:-未设置}'）"
    echo "     这条不是可选加分项——它测的是 v1.7.41 修的那条线上事故链。"
    echo "     本地补跑：HUB_REPO=<hub 仓路径> bash $0"
    exit 3
fi

export HUB_REPO
# PYTHONIOENCODING：中文断言在 GBK 控制台下会变成乱码，红的时候读不到判据＝等于没取证
export PYTHONIOENCODING=utf-8
echo "==== hub 生命周期真栈（hub=${HUB_REPO}） ===="
python "$DIR/hub_lifecycle_driver.py"
