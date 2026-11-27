#!/usr/bin/env python3
"""The demo daemon (tools/demo_server.py): it must speak the protocol the real app expects, so the demo stays honest."""
import asyncio
import hashlib
import hmac
import json
import sys
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).parent / "tools"))
import demo_server as demo  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


async def connect(port, token):
    ws = await websockets.connect(f"ws://127.0.0.1:{port}")
    ch = json.loads(await ws.recv())
    await ws.send(json.dumps({"t": "auth", "hmac": hmac.new(token.encode(), ch["nonce"].encode(), hashlib.sha256).hexdigest()}))
    return ws, json.loads(await ws.recv())


async def ask(ws, msg, want):
    await ws.send(json.dumps(msg))
    while True:
        m = json.loads(await asyncio.wait_for(ws.recv(), 10))
        if m.get("t") == want:
            return m


async def turn(ws, tid, text, allow=True):
    await ws.send(json.dumps({"t": "chat", "id": tid, "text": text}))
    events, moods = [], 0
    while True:
        m = json.loads(await asyncio.wait_for(ws.recv(), 30))
        t = m["t"]
        if t == "confirm_req":
            events.append(("confirm", m["risk"]))
            await ws.send(json.dumps({"t": "confirm", "call": m["call"], "allow": allow}))
        elif t == "chat_mood":
            moods += 1
            events.append(("mood", m["mood"]))
        elif t in ("tool", "cu_session"):
            events.append((t, m.get("state")))
        elif t in ("chat_done", "chat_error"):
            events.append((t, None))
            return events, moods, m


async def main():
    server = await websockets.serve(lambda ws: demo.handle(ws, "demo"), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        bad, reply = await connect(port, "wrong")
        check("a wrong token is refused", reply.get("t") == "denied")
        ws, ok = await connect(port, "demo")
        check("the right token is accepted", ok.get("t") == "ok")
        check("it advertises every capability the app uses", {"chat", "cu", "actions", "audit", "memory", "routines"} <= set(ok["caps"]))
        mac = ok.get("mac", "")
        check("the MAC it reports is a documentation-style placeholder", mac.startswith("02:") and mac.count(":") == 5)

        acts = (await ask(ws, {"t": "actions_get"}, "actions"))["items"]
        check("quick actions come in the documented shape", all({"id", "label", "group"} <= set(a) for a in acts))
        check("destructive actions carry a confirm text and danger", all(a.get("confirm") and a.get("danger") for a in acts if a["id"] in ("logout", "restart", "shutdown")))
        r = await ask(ws, {"t": "action", "id": "lock", "rid": 5}, "action_result")
        check("an action echoes its rid and succeeds", r["rid"] == 5 and r["ok"] is True)
        r = await ask(ws, {"t": "action", "id": "no-such-action", "rid": 6}, "action_result")
        check("an unknown action fails cleanly", r["ok"] is False)

        audit = (await ask(ws, {"t": "audit_get", "n": 50}, "audit"))["items"]
        check("the audit log has ISO timestamps, oldest first", len(audit) >= 8 and [a["ts"] for a in audit] == sorted(a["ts"] for a in audit))
        check("audit items use the documented approval values", {a["approval"] for a in audit} <= {"auto", "allowed", "denied", "timeout", "phone button", "phone"})
        routines = (await ask(ws, {"t": "routines_get"}, "routines"))["items"]
        check("routines have steps", routines and all(r["steps"] for r in routines))

        mem = await ask(ws, {"t": "memory_get"}, "memory")
        n = len(mem["items"])
        await ws.send(json.dumps({"t": "memory_add", "text": "Likes tea.", "rid": 1}))
        res = json.loads(await ws.recv())
        after = json.loads(await ws.recv())
        check("adding a memory reports ok then sends the fresh list", res["t"] == "memory_result" and res["ok"] and len(after["items"]) == n + 1)
        await ws.send(json.dumps({"t": "memory_forget", "id": after["items"][-1]["id"], "rid": 2}))
        res = json.loads(await ws.recv())
        after = json.loads(await ws.recv())
        check("forgetting a memory removes it", res["ok"] and len(after["items"]) == n)

        i = 0
        for text, allow, must in (
            ("hello", True, [("chat_done", None)]),
            ("open firefox", True, [("tool", "running"), ("tool", "ok")]),
            ("type something", True, [("confirm", "low"), ("tool", "ok")]),
            ("type something", False, [("confirm", "low"), ("tool", "denied")]),
            ("screenshot", True, [("confirm", "high")]),
            ("how do I find wifi", True, [("tool", "running"), ("tool", "ok")]),
            ("use the computer", True, [("confirm", "high"), ("cu_session", "active"), ("cu_session", "ended")]),
            ("system health", True, [("tool", "ok")]),
        ):
            i += 1
            events, moods, done = await turn(ws, i, text, allow)
            check(f"chat '{text}' (allow={allow}) plays the expected events", all(e in events for e in must), str(events))
            check(f"chat '{text}' ends exactly once and sends at most one mood", events[-1][0] == "chat_done" and moods <= 1, str(events))
        check("every finished turn reports spend against a budget", done.get("budget_usd") == 1.0 and done.get("today_usd", 0) > 0)
        events, _, done = await turn(ws, 99, "error")
        check("an error turn ends with chat_error", done["t"] == "chat_error")

        await ws.close()
    finally:
        server.close()
        await server.wait_closed()
    print("all tests passed" if not failures else f"{len(failures)} FAILED: {failures}")
    sys.exit(1 if failures else 0)


asyncio.run(main())
