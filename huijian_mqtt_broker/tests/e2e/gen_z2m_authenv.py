#!/usr/bin/env python3
"""z2m 直连实证用：**逐字抽取** run.sh 的 passwd+ACL 生成区，在本地生成
与生产完全同形态的认证环境（allow_anonymous false / password_file /
acl_file / 三账号）。防手抄漂移——测的就是生产代码生成的那份凭据（v1.6.24
惯例，同 gen_bridge_harness）。
"""
import re
import sys
from pathlib import Path

RUN = Path(__file__).resolve().parents[2] / "run.sh"

def main(d: str, port: str, password: str):
    text = RUN.read_text(encoding="utf-8")
    m = re.search(
        r'(USERNAME=\$\(bashio::config \'username\'\).*?chown mosquitto:mosquitto "\$\{ACL_FILE\}"[^\n]*\n)',
        text, re.S)
    assert m, "run.sh 凭据生成区锚缺失（passwd/ACL 区被移动——同步本脚本）"
    src = (m.group(1)
           .replace('USERNAME=$(bashio::config \'username\')', 'USERNAME="huijian"')
           .replace("PASSWORD=$(bashio::config 'password')", f'PASSWORD="{password}"')
           .replace('HA_MQTT_USERNAME=$(bashio::config \'ha_mqtt_username\')',
                    'HA_MQTT_USERNAME="ha_mqtt"')
           .replace("/etc/mosquitto/passwd", f"{d}/passwd")
           .replace("/etc/mosquitto/acl", f"{d}/acl"))
    # bashio 桩：其余 config 读取（options 默认值语义）
    src = re.sub(r"\$\(bashio::config '[^']+'\)", '""', src)
    script = f"""#!/bin/bash
set -uo pipefail
export PATH="{Path.home()}/local/mosq/usr/bin:$PATH"
D="{d}"; mkdir -p "$D"
# —— 以下为 run.sh 原文（仅路径/取值桩替换）——
{src}
# —— 生产静态 mosquitto.conf 同形态（端口→沙盒）——
sed -e "s|listener 2022 0.0.0.0|listener {port} 0.0.0.0|" \\
    -e "s|/etc/mosquitto/passwd|{d}/passwd|" \\
    -e "s|/etc/mosquitto/acl|{d}/acl|" \\
    -e "s|persistence_location /data/mosquitto/|persistence_location {d}/persist/|" \\
    "{RUN.parent}/mosquitto.conf" > "{d}/auth.conf"
echo "listener-file: {d}/auth.conf"
"""
    Path(d).mkdir(parents=True, exist_ok=True)
    out = Path(d) / "gen_env.sh"
    out.write_text(script, encoding="utf-8")
    print(str(out))

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
