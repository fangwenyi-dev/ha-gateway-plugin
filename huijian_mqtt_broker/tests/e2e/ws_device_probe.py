#!/usr/bin/env python3
"""E2E 观测面：经 HA WebSocket API 统计 window_controller_gateway 设备数。

device_registry 无 REST list 端点（实测 404）→ 用 config/device_registry/list。
可选 argv[1]：标识符后缀过滤（如 "1203" 只看首网关相关设备）。
输出：<count>
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
            await ws.send_json({"id": 1, "type": "config/device_registry/list"})
            while True:
                msg = await ws.receive_json(timeout=15)
                if msg.get("id") == 1 and msg.get("type") == "result":
                    break
            if not msg.get("success"):
                print(f"LIST_FAIL {msg}", file=sys.stderr)
                return 2
            devs = msg.get("result") or []
            wcg = [d for d in devs
                   if any(isinstance(i, str) and i.startswith("window_controller_gateway:")
                          or (isinstance(i, (list, tuple)) and i[0] == "window_controller_gateway")
                          for i in (d.get("identifiers") or []))]
            if len(sys.argv) > 1:
                needle = sys.argv[1]
                wcg = [d for d in wcg if any(
                    str(i).endswith(needle) or needle in str(i)
                    for i in (d.get("identifiers") or []))]
            print(len(wcg))
            for d in wcg:
                print(json.dumps({"id": d.get("id"), "name": d.get("name"),
                                  "identifiers": d.get("identifiers")},
                                 ensure_ascii=False))
            return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
