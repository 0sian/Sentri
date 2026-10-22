#!/usr/bin/env python3
"""
Mock AI daemon: speaks PROTOCOL-AI.md so the Companion app's chat UI can be tested with no LLM.

  python mock_ai_server.py [--port 8766] [--token mock]

Point the app at <PC address>:8766 with the token it prints. Try these messages:
  hello            -> streamed reply
  open firefox     -> reply + auto tool line (running -> ok) + more text
  type something   -> approval card (low risk); Allow / Deny / ignore for 20 s
  screenshot       -> approval card (HIGH risk, red)
  error            -> chat_error
Needs only `pip install websockets`. Not a real daemon: it ignores mouse/keyboard messages.
"""
import argparse
import asyncio
import hashlib
import hmac
import itertools
import json
import secrets
import socket

import websockets

counter = itertools.count(1)


async def handle(ws, token):
    nonce = secrets.token_hex(16)
    await ws.send(json.dumps({"t": "challenge", "nonce": nonce}))
    try:
        msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
    except (asyncio.TimeoutError, json.JSONDecodeError, websockets.ConnectionClosed):
        return
    expected = hmac.new(token.encode(), nonce.encode(), hashlib.sha256).hexdigest()
    if msg.get("t") != "auth" or not hmac.compare_digest(str(msg.get("hmac", "")), expected):
        await ws.send(json.dumps({"t": "denied"}))
        return
    await ws.send(json.dumps({"t": "ok", "host": socket.gethostname() + " (mock)",
                              "caps": ["chat"], "model": "mock-1"}))

    loop = asyncio.get_running_loop()
    pending = {}  # call -> Future[bool]
    turn = None

    async def send(**kw):
        await ws.send(json.dumps(kw))

    async def stream(tid, text):
        for word in text.split(" "):
            await send(t="chat_delta", id=tid, text=word + " ")
            await asyncio.sleep(0.06)

    async def tool(tid, call, name, summary, state, detail=None):
        kw = dict(t="tool", id=tid, call=call, name=name, summary=summary, state=state)
        if detail:
            kw["detail"] = detail
        await send(**kw)

    async def gated(tid, name, summary, risk, then_text):
        call = f"c{next(counter)}"
        fut = loop.create_future()
        pending[call] = fut
        await send(t="confirm_req", id=tid, call=call, name=name, summary=summary, risk=risk, timeout=20)
        try:
            allow = await asyncio.wait_for(fut, 20)
        except asyncio.TimeoutError:
            await tool(tid, call, name, summary, "denied", "timeout")
            await stream(tid, "No answer, so I skipped it.")
            return
        finally:
            pending.pop(call, None)
        if allow:
            await tool(tid, call, name, summary, "running")
            await asyncio.sleep(0.8)
            await tool(tid, call, name, summary, "ok")
            await stream(tid, then_text)
        else:
            await tool(tid, call, name, summary, "denied", "user")
            await stream(tid, "Okay, I won't.")

    async def run_turn(tid, text):
        low = text.lower()
        try:
            if "error" in low:
                await asyncio.sleep(0.4)
                await send(t="chat_error", id=tid, msg="Mock error: the model API said no.")
                return
            await asyncio.sleep(0.5)  # "thinking"
            await stream(tid, "Okay!")
            if "open" in low:
                call = f"c{next(counter)}"
                await tool(tid, call, "launch_app", "Open Firefox", "running")
                await asyncio.sleep(1.2)
                await tool(tid, call, "launch_app", "Open Firefox", "ok")
                await stream(tid, "Opened it.")
            elif "screenshot" in low:
                await gated(tid, "screenshot",
                            "Take a screenshot and send it to the AI provider", "high", "Here's what I can see: a mock desktop.")
            elif "type" in low:
                await gated(tid, "type_text",
                            'Type "hello world" into the focused window (Firefox)', "low", "Typed it.")
            else:
                await stream(tid, f"You said: {text}. This is a mock reply, so nothing real happened.")
            await send(t="chat_done", id=tid, usage={"in": 10, "out": 20})
        except asyncio.CancelledError:
            await send(t="chat_done", id=tid, cancelled=True)
            raise

    try:
        async for raw in ws:
            try:
                m = json.loads(raw)
            except json.JSONDecodeError:
                continue
            t = m.get("t")
            if t == "ping" and isinstance(m.get("id"), int):
                await send(t="pong", id=m["id"])
            elif t == "chat":
                if turn is not None and not turn.done():
                    await send(t="chat_error", id=m.get("id"), msg="Busy")
                else:
                    turn = asyncio.create_task(run_turn(m.get("id"), str(m.get("text", ""))))
            elif t == "chat_cancel" and turn is not None and not turn.done():
                turn.cancel()
            elif t == "confirm":
                fut = pending.get(m.get("call"))
                if fut is not None and not fut.done():
                    fut.set_result(bool(m.get("allow")))
    except websockets.ConnectionClosed:
        pass
    finally:
        if turn is not None and not turn.done():
            turn.cancel()


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--token", default="mock")
    a = p.parse_args()
    print(f"Mock AI daemon on {lan_ip()}:{a.port}  token: {a.token}")
    async with websockets.serve(lambda ws: handle(ws, a.token), "0.0.0.0", a.port,
                                ping_interval=15, ping_timeout=10):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
