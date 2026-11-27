#!/usr/bin/env python3
"""
Sentri demo daemon: try the whole phone app with no PC, no API key and nothing real on screen.

It speaks PROTOCOL.md and PROTOCOL-AI.md with made-up data (chat, approval cards, computer use, the screen guide,
Quick actions, the Activity screen with audit log / memory / routines). Mouse and keyboard messages are ignored.
Nothing it says is real and nothing on your PC is touched.

  python demo_server.py [--port 8766] [--token demo] [--host 127.0.0.1]

By default it listens on this machine only. To reach it from a phone without opening a firewall port, plug the phone
in (or use wireless debugging) and run:   adb reverse tcp:8766 tcp:8766
then in the app set address 127.0.0.1, port 8766 and the token it prints.

Things to say to it in the chat:
  hello                     a greeting
  open firefox              an automatic tool call
  type something            an approval card (low risk)
  screenshot                an approval card (HIGH risk, red)
  how do I find wifi        the screen guide: it "points" at something
  use the computer          a computer-use session with the red Stop banner
  set a timer               a timer tool
  system health             the system doctor
  error                     a failed turn
Needs only `pip install websockets`.
"""
import argparse
import asyncio
import hashlib
import hmac
import itertools
import json
import secrets
import socket
from datetime import datetime, timedelta

import websockets

counter = itertools.count(1)

ACTIONS = [
    {"id": "lock", "label": "Lock", "group": "Session"},
    {"id": "logout", "label": "Log out", "group": "Session", "confirm": "Log out? Open apps will be closed.", "danger": True},
    {"id": "screenoff", "label": "Screen off", "group": "Desktop"},
    {"id": "gamemode", "label": "Game mode", "group": "Desktop"},
    {"id": "dnd", "label": "Do not disturb", "group": "Desktop"},
    {"id": "sleep", "label": "Sleep", "group": "Power"},
    {"id": "restart", "label": "Restart", "group": "Power", "confirm": "Restart the PC now?", "danger": True},
    {"id": "shutdown", "label": "Shut down", "group": "Power", "confirm": "Shut the PC down now?", "danger": True},
    {"id": "routine:focus", "label": "Focus mode", "group": "Routines",
     "confirm": "Run routine Focus mode: close chat apps, turn on Do Not Disturb, open the editor?"},
    {"id": "routine:movie", "label": "Movie night", "group": "Routines",
     "confirm": "Run routine Movie night: dim the screen, open the media player, set volume to 40%?"},
]
RESULTS = {"lock": "Locked", "screenoff": "Screen off", "gamemode": "Game mode on", "dnd": "Do not disturb on",
           "sleep": "Going to sleep", "logout": "Logging out", "restart": "Restarting", "shutdown": "Shutting down",
           "routine:focus": "Focus mode started", "routine:movie": "Movie night started"}

ROUTINES = [
    {"name": "Focus mode", "description": "Close chat apps, turn on Do Not Disturb and open the editor.", "risk": "low",
     "steps": ["Close Discord", "Turn on Do Not Disturb", "Open the code editor"]},
    {"name": "Movie night", "description": "Dim the screen and get the media player ready.", "risk": "low",
     "steps": ["Dim the screen", "Open the media player", "Set the volume to 40%"]},
    {"name": "Tidy up", "description": "Close every window except the one in front.", "risk": "high",
     "steps": ["List the open windows", "Close all but the focused one"]},
]

MEMORY = [
    {"id": "m1", "text": "Prefers short answers and a dark theme.", "created": "2026-11-02"},
    {"id": "m2", "text": "Main browser is Firefox; the editor is Code.", "created": "2026-11-03"},
    {"id": "m3", "text": "Keep the volume at or below 60%.", "created": "2026-11-09"},
    {"id": "m4", "text": "Screenshots are saved in ~/Pictures/shots.", "created": "2026-11-14"},
]


def audit_items():
    now = datetime.now().astimezone()

    def ago(minutes):
        return (now - timedelta(minutes=minutes)).isoformat(timespec="seconds")

    rows = [
        (190, "system_doctor", "Check system health", "auto", "ok", None),
        (172, "launch_app", "Open Firefox", "auto", "ok", None),
        (171, "open_url", "Open docs.python.org in Firefox", "allowed", "ok", None),
        (140, "set_volume", "Set volume to 45%", "auto", "ok", None),
        (96, "type_text", 'Type "git status" into the focused window (Terminal)', "allowed", "ok", None),
        (80, "screenshot", "Take a screenshot and send it to the AI provider", "denied", "not run", "user"),
        (66, "quick_action", "Lock", "phone button", "ok", None),
        (51, "timer", "Set a timer: 10 minutes (tea)", "auto", "ok", None),
        (33, "close_window", "Close the window Untitled Document", "timeout", "not run", "timeout"),
        (21, "memory", "Added a memory", "phone", "ok", None),
        (9, "point_at_screen", "Point out: the Wi-Fi toggle", "auto", "ok", None),
        (4, "media_control", "Pause media", "auto", "ok", None),
    ]
    out = []
    for m, tool, summary, approval, result, detail in rows:
        item = {"ts": ago(m), "tool": tool, "summary": summary, "approval": approval, "result": result}
        if detail:
            item["detail"] = detail
        out.append(item)
    return out


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
    await ws.send(json.dumps({
        "t": "ok", "host": "my-pc (demo)", "model": "demo",
        "caps": ["chat", "cu", "actions", "audit", "memory", "routines"],
        "mac": "02:00:5e:10:00:01",
    }))

    loop = asyncio.get_running_loop()
    pending = {}
    state = {"turn": None, "spent": 0.012, "memory": [dict(m) for m in MEMORY]}

    async def send(**kw):
        await ws.send(json.dumps(kw))

    async def stream(tid, text, delay=0.045):
        for word in text.split(" "):
            await send(t="chat_delta", id=tid, text=word + " ")
            await asyncio.sleep(delay)

    async def tool(tid, call, name, summary, status, detail=None):
        kw = dict(t="tool", id=tid, call=call, name=name, summary=summary, state=status)
        if detail:
            kw["detail"] = detail
        await send(**kw)

    async def run_tool(tid, name, summary, secs=1.0):
        call = f"c{next(counter)}"
        await tool(tid, call, name, summary, "running")
        await asyncio.sleep(secs)
        await tool(tid, call, name, summary, "ok")

    async def gated(tid, name, summary, risk):
        call = f"c{next(counter)}"
        fut = loop.create_future()
        pending[call] = fut
        await send(t="confirm_req", id=tid, call=call, name=name, summary=summary, risk=risk, timeout=120)
        try:
            allow = await asyncio.wait_for(fut, 120)
        except asyncio.TimeoutError:
            await tool(tid, call, name, summary, "denied", "timeout")
            return False
        finally:
            pending.pop(call, None)
        if not allow:
            await tool(tid, call, name, summary, "denied", "user")
            return False
        await tool(tid, call, name, summary, "running")
        await asyncio.sleep(0.8)
        await tool(tid, call, name, summary, "ok")
        return True

    async def computer_use(tid):
        goal = "Turn on the night light in Settings"
        await send(t="cu_session", state="active", secs_left=240, goal=goal)
        try:
            for secs, summary in ((1.6, "Click Settings"), (1.4, "Click Display"), (1.4, "Click Night light"), (1.2, "Scroll down")):
                await run_tool(tid, "computer", summary, secs)
            await send(t="cu_session", state="ended", reason="done")
        except asyncio.CancelledError:
            await send(t="cu_session", state="ended", reason="user")
            raise

    async def run_turn(tid, text):
        low = text.lower()
        try:
            await asyncio.sleep(0.6)  # "thinking"
            if "error" in low:
                await send(t="chat_error", id=tid, msg="Demo error: the model API said no.")
                return
            if any(w in low for w in ("computer", "click for me", "use the pc")):
                await send(t="chat_mood", id=tid, mood="excited")
                await stream(tid, "Sure. I'll take over the mouse for a moment, and you can stop me any time.")
                if await gated(tid, "start_computer_use", "Control the mouse and keyboard to: turn on the night light", "high"):
                    await computer_use(tid)
                    await stream(tid, "Done. The night light is on.")
                else:
                    await stream(tid, "Okay, I won't.")
            elif any(w in low for w in ("screenshot", "look at my")):
                await send(t="chat_mood", id=tid, mood="curious")
                await stream(tid, "I'd need to look at your screen for that.")
                if await gated(tid, "screenshot", "Take a screenshot and send it to the AI provider", "high"):
                    await stream(tid, "Here's what I can see: a tidy desktop with a terminal and a browser.")
                else:
                    await stream(tid, "No problem, I haven't looked.")
            elif "type" in low:
                await send(t="chat_mood", id=tid, mood="attentive")
                await stream(tid, "I can type that for you.")
                if await gated(tid, "type_text", 'Type "hello world" into the focused window (Terminal)', "low"):
                    await stream(tid, "Typed it.")
                else:
                    await stream(tid, "Okay, I won't.")
            elif any(w in low for w in ("how do i", "where", "point", "wifi", "wi-fi", "show me")):
                await send(t="chat_mood", id=tid, mood="curious")
                await stream(tid, "Let me look at your screen.")
                await run_tool(tid, "point_at_screen", "Point out: the Wi-Fi toggle", 1.4)
                await stream(tid, "It's the toggle in the top-right of the panel. I've pointed it out on your screen.")
            elif "open" in low or "launch" in low:
                await send(t="chat_mood", id=tid, mood="happy")
                await stream(tid, "On it.")
                await run_tool(tid, "launch_app", "Open Firefox", 1.2)
                await stream(tid, "Opened Firefox.")
            elif "timer" in low or "remind" in low:
                await send(t="chat_mood", id=tid, mood="proud")
                await run_tool(tid, "timer", "Set a timer: 10 minutes (tea)", 0.8)
                await stream(tid, "Timer set for ten minutes. I'll nudge you when it's up.")
            elif any(w in low for w in ("health", "doctor", "problem", "status")):
                await send(t="chat_mood", id=tid, mood="proud")
                await run_tool(tid, "system_doctor", "Check system health", 1.4)
                await stream(tid, "All clear. No failed services, disks are under 60% full, CPU temperature is 48 C and there are 3 updates waiting.")
            elif any(w in low for w in ("volume", "music", "pause")):
                await send(t="chat_mood", id=tid, mood="happy")
                await run_tool(tid, "media_control", "Pause media", 0.8)
                await stream(tid, "Paused.")
            elif any(w in low for w in ("hello", "hi", "hey")):
                await send(t="chat_mood", id=tid, mood="happy")
                await stream(tid, "Hi! I'm Sentri. I can move the mouse, type, open things and point at what's on your screen. What would you like to do?")
            else:
                await send(t="chat_mood", id=tid, mood="neutral")
                await stream(tid, f'You said "{text}". This is the demo, so I can only act out a few things. Try "open firefox", "how do I find wifi" or "use the computer".')
            state["spent"] += 0.004
            await send(t="chat_done", id=tid, usage={"in": 1200, "out": 90}, today_usd=round(state["spent"], 3), budget_usd=1.0)
        except asyncio.CancelledError:
            await send(t="chat_done", id=tid, cancelled=True)
            raise

    async def send_memory():
        await send(t="memory", items=state["memory"], max=100, max_text=200, broken=False)

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
                if state["turn"] is not None and not state["turn"].done():
                    await send(t="chat_error", id=m.get("id"), msg="Busy")
                else:
                    state["turn"] = asyncio.create_task(run_turn(m.get("id"), str(m.get("text", ""))))
            elif t in ("chat_cancel", "chat_reset", "cu_stop") and state["turn"] is not None and not state["turn"].done():
                state["turn"].cancel()
            elif t == "confirm":
                fut = pending.get(m.get("call"))
                if fut is not None and not fut.done():
                    fut.set_result(bool(m.get("allow")))
            elif t == "actions_get":
                await send(t="actions", items=ACTIONS)
            elif t == "action":
                aid = str(m.get("id", ""))
                await asyncio.sleep(0.3)
                await send(t="action_result", rid=m.get("rid"), id=aid, ok=aid in RESULTS, msg=RESULTS.get(aid, "Unknown action"))
            elif t == "audit_get":
                await send(t="audit", items=audit_items())
            elif t == "routines_get":
                await send(t="routines", items=ROUTINES)
            elif t == "memory_get":
                await send_memory()
            elif t in ("memory_add", "memory_edit", "memory_forget"):
                text = str(m.get("text", "")).strip()
                ok, msg = True, "Saved"
                if t == "memory_add":
                    if not text:
                        ok, msg = False, "Nothing to save"
                    elif len(state["memory"]) >= 100:
                        ok, msg = False, "Memory is full"
                    else:
                        state["memory"].append({"id": "u" + secrets.token_hex(3), "text": text[:200], "created": datetime.now().strftime("%Y-%m-%d")})
                elif t == "memory_edit":
                    hit = next((x for x in state["memory"] if x["id"] == m.get("id")), None)
                    if hit is None or not text:
                        ok, msg = False, "Couldn't find that memory"
                    else:
                        hit["text"] = text[:200]
                else:
                    before = len(state["memory"])
                    state["memory"] = [x for x in state["memory"] if x["id"] != m.get("id")]
                    ok, msg = len(state["memory"]) < before, "Forgotten" if len(state["memory"]) < before else "Couldn't find that memory"
                await send(t="memory_result", rid=m.get("rid"), ok=ok, msg=msg)
                if ok:
                    await send_memory()
    except websockets.ConnectionClosed:
        pass
    finally:
        if state["turn"] is not None and not state["turn"].done():
            state["turn"].cancel()


async def main():
    p = argparse.ArgumentParser(description="Fake Sentri daemon for trying the app without a PC")
    p.add_argument("--host", default="127.0.0.1", help="interface to listen on (default: this machine only)")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--token", default="demo")
    a = p.parse_args()
    print(f"Sentri demo daemon on {a.host}:{a.port}  token: {a.token}")
    if a.host in ("127.0.0.1", "localhost"):
        print(f"Phone over USB or wireless debugging:  adb reverse tcp:{a.port} tcp:{a.port}   then use address 127.0.0.1")
    async with websockets.serve(lambda ws: handle(ws, a.token), a.host, a.port, ping_interval=15, ping_timeout=10):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
