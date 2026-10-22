#!/usr/bin/env python3
"""
Drive the running daemon from the PC for live testing:

    send.py '[{"t":"text","s":"hi"},{"t":"key","k":"enter"}]' [--delay 0.05] [--expect-class foot]

--expect-class (Hyprland only) refuses to send anything unless the focused window has
that class, so test input can't land in whatever happens to be focused.
"""
import argparse
import asyncio
import hashlib
import hmac
import json
import os
import subprocess
import sys
from pathlib import Path

import websockets

TOKEN_FILE = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "companion" / "token"


async def send(msgs, port, delay):
    token = TOKEN_FILE.read_text().strip()
    async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
        nonce = json.loads(await ws.recv())["nonce"]
        mac = hmac.new(token.encode(), nonce.encode(), hashlib.sha256).hexdigest()
        await ws.send(json.dumps({"t": "auth", "hmac": mac}))
        reply = json.loads(await ws.recv())
        if reply.get("t") != "ok":
            sys.exit(f"auth failed: {reply}")
        for m in msgs:
            await ws.send(json.dumps(m))
            await asyncio.sleep(delay)
        await asyncio.sleep(0.2)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("msgs", help="JSON list of protocol messages")
    p.add_argument("--delay", type=float, default=0.05)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--expect-class")
    a = p.parse_args()
    if a.expect_class:
        out = subprocess.run(["hyprctl", "activewindow", "-j"], capture_output=True, text=True).stdout
        active = json.loads(out or "{}").get("class")
        if active != a.expect_class:
            sys.exit(f"focused window is {active!r}, not {a.expect_class!r}: nothing sent")
    asyncio.run(send(json.loads(a.msgs), a.port, a.delay))


if __name__ == "__main__":
    main()
