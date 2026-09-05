#!/usr/bin/env python3
"""E2E 观测面：经 HA WebSocket API 列出在途 window_controller_gateway flow。

HA REST 故意不提供 flow 列表（405 设计使然）→ 用 config_entries/flow/progress
（UI 发现区同款）。可选 argv[1]：卡片名包含过滤（区分代理发起 vs 其它链触发）。
输出：<count>\n<每条 flow 一行 JSON>
环境变量：HA_URL(默认 http://127.0.0.1:8123) HA_TOKEN。
"""
import asyncio
import json
import os
import sys

import aiohttp


async def main() -> int:
    url = os.environ.get("HA_URL", "http://127.0.0.1:8123").rstrip("/") + "/api/websocket"
    token = os.environ.get("HA_TOKEN", "")
    async with aiohttp.ClientSession() as sess:
        async with sess.ws_connect(url, timeout=10) as ws:
            msg = await ws.receive_json()
            assert msg["type"] == "auth_required", msg
            await ws.send_json({"type": "auth", "access_token": token})
            msg = await ws.receive_json()
            assert msg["type"] == "auth_ok", msg
            await ws.send_json({"id": 1, "type": "config_entries/flow/progress"})
            # result = 当前在途 flow 列表（HA 2024.x+ 同款命令，UI 发现区数据源）
            while True:
                msg = await ws.receive_json(timeout=15)
                if msg.get("id") == 1 and msg.get("type") == "result":
                    break
            if not msg.get("success"):
                print(f"STREAM_FAIL {msg}", file=sys.stderr)
                return 2
            flows = msg.get("result") or []
            wcg = [f for f in flows if f.get("handler") == "window_controller_gateway"]
            if len(sys.argv) > 1:
                needle = sys.argv[1]
                wcg = [f for f in wcg
                       if needle in json.dumps(f.get("context", {}), ensure_ascii=False)]
            print(len(wcg))
            for f in wcg:
                print(json.dumps(f, ensure_ascii=False))
            await ws.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
