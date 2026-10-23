#!/usr/bin/env python3
"""Computer-use session tests: fake desktop + scripted backend, nothing touches the real screen."""
import asyncio
import hashlib
import hmac
import json
import os
import sys
import tempfile
from pathlib import Path

import websockets

import ai
import companion_daemon as cd
import cu
import pc_tools

TOKEN = "test-token"
PORT = 18795
TMP = Path(tempfile.mkdtemp())
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class FakeUInput:
    def __init__(self, *a, **k):
        self.events = []

    def write(self, *a):
        self.events.append(a)

    def syn(self):
        pass

    def close(self):
        pass


cd.UInput = FakeUInput


class FakeDesktop:
    """Records what a session does. The 'monitor' sits at x=1000 with fractional scale 1.5."""

    def __init__(self):
        self.log = []
        self.cls = "firefox"
        self.overlay = None
        self.geom = cu.Geometry(1000, 0, 1.5, 3840, 2160, cu.shot_scale_for(3840, 2160))

    def available(self):
        return True

    async def screenshot(self, zoom=None, geom=None):
        self.log.append(("shot", zoom))
        return b"\xff\xd8fake", self.geom

    async def cursor(self):
        return 1000.0, 0.0

    async def move_to(self, x, y):
        self.log.append(("move", round(x, 1), round(y, 1)))

    async def focused_class(self):
        return self.cls

    async def overlay_open(self):
        return self.overlay

    async def button(self, name, count=1, mods=()):
        self.log.append(("button", name, count, tuple(mods)))

    async def drag(self, a, b):
        self.log.append(("drag", a, b))

    async def scroll(self, dx, dy):
        self.log.append(("scroll", dx, dy))

    async def key(self, k, mods):
        self.log.append(("key", k, tuple(mods)))

    async def type(self, text):
        self.log.append(("type", text))


class Backend:
    """Main-model and session-model calls share it; `model` tells them apart."""

    def __init__(self):
        self.main, self.sess = [], []
        self.calls = []
        self.delay = 0.0
        self.usage = {"uncached": 1000, "cache_write": 0, "cache_read": 0, "out": 100}

    async def complete(self, system, messages, on_text, tools, model=None, effort=None):
        self.calls.append({"model": model, "tools": tools, "messages": list(messages)})
        queue = self.sess if model else self.main
        await asyncio.sleep(self.delay)
        script = queue.pop(0) if queue else {"content": [{"type": "text", "text": "ok"}]}
        if isinstance(script, Exception):
            raise script
        content = script["content"]
        for b in content:
            if b.get("type") == "text":
                await on_text(b["text"])
        stop = "tool_use" if any(b.get("type") == "tool_use" for b in content) else "end_turn"
        return ai.Reply(content, script.get("stop", stop), 1100, 100, dict(self.usage))


def act(name, uid="a1", **inp):
    return {"type": "tool_use", "id": uid, "name": name, "toolset_name": "computer", "input": inp}


def end(summary="All done", uid="e1"):
    return {"type": "tool_use", "id": uid, "name": "end_computer_use", "input": {"summary": summary}}


def start_call(goal="Open the first video"):
    return {"content": [{"type": "tool_use", "id": "s1", "name": "start_computer_use", "input": {"goal": goal}}]}


def make(**cfg_over):
    cfg = ai.AIConfig(api_key="k", cu=cu.CUConfig(**cfg_over))
    be, desk = Backend(), FakeDesktop()
    a = ai.Assistant(cfg, be, usage_file=TMP / f"u-{os.urandom(3).hex()}.json", tools={}, desktop=desk)
    return a, be, desk


async def connect(port):
    ws = await websockets.connect(f"ws://127.0.0.1:{port}")
    ch = json.loads(await ws.recv())
    await ws.send(json.dumps({"t": "auth", "hmac": hmac.new(TOKEN.encode(), ch["nonce"].encode(), hashlib.sha256).hexdigest()}))
    return ws, json.loads(await ws.recv())


async def until(ws, pred, timeout=5.0):
    got = []
    while True:
        m = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        got.append(m)
        if pred(m):
            return got, m


def is_t(*ts):
    return lambda m: m["t"] in ts


def ended(got):
    return [m.get("reason") for m in got if m["t"] == "cu_session" and m["state"] == "ended"]


async def socket_tests():
    a, be, desk = make()
    srv = cd.Server(cd.VirtualInput("us"), TOKEN, 400.0, a)
    async with websockets.serve(srv.handler, "127.0.0.1", PORT):
        ws, ok = await connect(PORT)
        check("caps advertise cu", ok["caps"] == ["chat", "cu"], ok)
        check("session tools never offered to the main model",
              all(t.get("name") != "end_computer_use" and t.get("type") != "computer_toolset_20260801"
                  for t in a.tool_defs) and "start_computer_use" in [t["name"] for t in a.tool_defs])

        # deny: nothing starts
        be.main += [start_call(), {"content": [{"type": "text", "text": "Fair enough."}]}]
        await ws.send(json.dumps({"t": "chat", "id": 1, "text": "click the video"}))
        _, req = await until(ws, is_t("confirm_req"))
        check("start card: high risk, plain-words scope",
              req["risk"] == "high" and req["summary"] ==
              "Let the AI look at your screen and click for up to 5 minutes: Open the first video", req)
        await ws.send(json.dumps({"t": "confirm", "call": req["call"], "allow": False}))
        got, _ = await until(ws, is_t("chat_done"))
        check("deny starts nothing", not [m for m in got if m["t"] == "cu_session"] and not be.sess and
              all(c["model"] is None for c in be.calls), got)

        async def run_session(scripts, after_req=None, msg_id=2):
            be.sess[:] = scripts
            be.main[:] = [start_call(), {"content": [{"type": "text", "text": "Done."}]}]
            await ws.send(json.dumps({"t": "chat", "id": msg_id, "text": "go"}))
            _, req = await until(ws, is_t("confirm_req"))
            await ws.send(json.dumps({"t": "confirm", "call": req["call"], "allow": True}))
            got, active = await until(ws, lambda m: m["t"] == "cu_session")
            if after_req:
                await after_req()
            more, _ = await until(ws, is_t("chat_done", "chat_error"), timeout=10)
            return got + more, active

        # allowed: active banner, actions, summary back to the main model, no images in main history
        got, active = await run_session([
            {"content": [act("left_click", coordinate=[640, 360])]},
            {"content": [act("screenshot", uid="a2")]},
            {"content": [end("Clicked the first thumbnail; it's playing.")]}])
        check("active banner: secs_left + cleaned goal", active == {"t": "cu_session", "state": "active",
              "secs_left": 300, "goal": "Open the first video"}, active)
        tools_ev = [(m["name"], m["summary"], m["state"]) for m in got if m["t"] == "tool" and m["name"] != "start_computer_use"]
        check("one tool event per action, plain summaries",
              tools_ev == [("left_click", "Click (640, 360)", "running"), ("left_click", "Click (640, 360)", "ok"),
                           ("screenshot", "Look at the screen", "running"), ("screenshot", "Look at the screen", "ok")], tools_ev)
        check("ended reason done", ended(got) == ["done"], ended(got))
        sess_calls = [c for c in be.calls if c["model"]]
        check("session uses its own model and the native toolset + end tool",
              sess_calls[0]["model"] == "claude-sonnet-5-5"
              and sess_calls[0]["tools"][0]["type"] == "computer_toolset_20260801"
              and sess_calls[0]["tools"][1]["name"] == "end_computer_use", sess_calls[0]["tools"][:2])
        res = sess_calls[1]["messages"][-1]["content"][0]
        check("computer tool_results echo toolset_name", res.get("toolset_name") == "computer" and res["content"] == "OK", res)
        summary = be.calls[-1]["messages"][-1]["content"][0]["content"]
        check("summary reaches the main model", "Clicked the first thumbnail" in summary and "finished" in summary, summary)
        flat = json.dumps(a.history)
        check("main history has no images and stays on the main model",
              '"image"' not in flat and all(c["model"] is None for c in be.calls if c not in sess_calls))
        check("tools vanish after: session state cleared", not a.cu.active)

        # touched: phone mv ends it; ping doesn't
        async def touch():
            await ws.send(json.dumps({"t": "ping", "id": 9}))
            await asyncio.sleep(0.3)
            await ws.send(json.dumps({"t": "mv", "dx": 3, "dy": 0}))
        be.delay = 0.2
        got, _ = await run_session([{"content": [act("screenshot", uid=f"w{i}")]} for i in range(40)], touch, 3)
        check("phone input ends the session as 'touched' (ping doesn't)", ended(got) == ["touched"], ended(got))

        for label, msg in (("btn", {"t": "btn", "b": "left", "s": "click"}), ("key", {"t": "key", "k": "a"}),
                           ("text", {"t": "text", "s": "x"}), ("sc", {"t": "sc", "dx": 0, "dy": 1})):
            async def touch2(msg=msg):
                await asyncio.sleep(0.3)
                await ws.send(json.dumps(msg))
            got, _ = await run_session([{"content": [act("screenshot", uid=f"w{i}")]} for i in range(40)], touch2, 4)
            check(f"phone {label} -> touched", ended(got) == ["touched"], ended(got))

        async def zero_move_then_stop():
            await ws.send(json.dumps({"t": "mv", "dx": 0, "dy": 0}))
            await asyncio.sleep(0.4)
            await ws.send(json.dumps({"t": "cu_stop"}))
        got, _ = await run_session([{"content": [act("screenshot", uid=f"w{i}")]} for i in range(40)], zero_move_then_stop, 5)
        check("zero-length move ignored; cu_stop -> user", ended(got) == ["user"], ended(got))

        async def cancel():
            await asyncio.sleep(0.3)
            await ws.send(json.dumps({"t": "chat_cancel", "id": 6}))
        got, _ = await run_session([{"content": [act("screenshot", uid=f"w{i}")]} for i in range(40)], cancel, 6)
        check("chat_cancel -> ended user, turn cancelled", ended(got) == ["user"] and got[-1].get("cancelled"), got[-2:])

        async def reset():
            await asyncio.sleep(0.3)
            await ws.send(json.dumps({"t": "chat_reset"}))
        got, _ = await run_session([{"content": [act("screenshot", uid=f"w{i}")]} for i in range(40)], reset, 7)
        check("chat_reset -> ended user", ended(got) == ["user"], ended(got))

        await ws.send(json.dumps({"t": "cu_stop"}))  # late stop: nothing active
        await ws.send(json.dumps({"t": "ping", "id": 11}))
        _, m = await until(ws, is_t("pong"))
        check("late cu_stop ignored", m["id"] == 11 and not a.cu.active)

        # second start while one runs -> clean error (validated before any card)
        a.cu.session = object()
        be.main[:] = [start_call(), {"content": [{"type": "text", "text": "busy"}]}]
        be.delay = 0
        await ws.send(json.dumps({"t": "chat", "id": 8, "text": "again"}))
        got, _ = await until(ws, is_t("chat_done"))
        check("second start refused without a card", not [m for m in got if m["t"] == "confirm_req"]
              and [m["state"] for m in got if m["t"] == "tool"] == ["error"], got)
        a.cu.session = None

        # disconnect mid-session
        be.delay = 0.2
        be.sess[:] = [{"content": [act("screenshot", uid=f"w{i}")]} for i in range(40)]
        be.main[:] = [start_call()]
        await ws.send(json.dumps({"t": "chat", "id": 9, "text": "go"}))
        _, req = await until(ws, is_t("confirm_req"))
        await ws.send(json.dumps({"t": "confirm", "call": req["call"], "allow": True}))
        await until(ws, lambda m: m["t"] == "cu_session")
        await ws.close()
        await asyncio.sleep(0.6)
        check("disconnect ends the session", not a.cu.active and not a.busy)

    # replace: new client takes over -> old session ends 'disconnected', sent to the new phone
    a, be, desk = make()
    srv = cd.Server(cd.VirtualInput("us"), TOKEN, 400.0, a)
    async with websockets.serve(srv.handler, "127.0.0.1", PORT + 1):
        ws1, _ = await connect(PORT + 1)
        be.delay = 0.2
        be.sess[:] = [{"content": [act("screenshot", uid=f"w{i}")]} for i in range(40)]
        be.main[:] = [start_call()]
        await ws1.send(json.dumps({"t": "chat", "id": 1, "text": "go"}))
        _, req = await until(ws1, is_t("confirm_req"))
        await ws1.send(json.dumps({"t": "confirm", "call": req["call"], "allow": True}))
        await until(ws1, lambda m: m["t"] == "cu_session")
        holder = {}

        async def catch():
            ws2, _ = await connect(PORT + 1)
            holder["ws2"] = ws2
        await catch()
        await asyncio.sleep(0.8)
        check("replaced connection ends the session", not a.cu.active)
        await holder["ws2"].close()


async def limit_tests():
    async def run(scripts, **over):
        a, be, desk = make(**over)
        be.sess[:] = scripts
        tool = a.tools["start_computer_use"]
        args = await tool.prepare({"goal": "Scroll the page"})
        ends = []

        async def notify(m):
            ends.append(m)
        a.cu.send = notify
        out = await tool.run(args, progress=lambda **kw: asyncio.sleep(0))
        return out, [m.get("reason") for m in ends if m.get("state") == "ended"], desk

    shots = [{"content": [act("screenshot", uid=f"w{i}")]} for i in range(100)]
    _, r, _ = await run(shots, max_actions=3)
    check("action limit -> limit", r == ["limit"], r)
    _, r, _ = await run(shots, budget_usd=0.01)  # each fake call costs ~$0.003

    # session spend lands in the daily dollar total; actions are audited with the session id
    import audit
    a, be, desk = make()
    a.audit = audit.AuditLog(TMP / f"audit-{os.urandom(3).hex()}.jsonl")
    be.sess[:] = [{"content": [act("left_click", coordinate=[5, 5])]}, {"content": [end()]}]
    be.main[:] = [start_call(), {"content": [{"type": "text", "text": "ok"}]}]

    async def allow(*x):
        return (True, None)
    assert a.claim()
    await a.turn("go", lambda s: asyncio.sleep(0), lambda e: asyncio.sleep(0), None, allow)
    rows = a.audit.tail(10)
    check("session + chat costs in today's dollars (2 Sonnet calls $0.006 + 2 Haiku calls $0.0003)",
          a.spend()["today_usd"] == 0.0063, a.spend())
    a.audit.record("x", "y", "auto", "error", detail="bad\x1b[2Jthing " + "z" * 300)
    rec = a.audit.tail(1)[0]
    check("audit detail is cleaned and capped", "\x1b" not in rec["detail"] and len(rec["detail"]) == 120, rec)
    rows = rows[:2]
    check("audit: session actions carry the session id; the start call is 'allowed'",
          [(r["tool"], r["approval"], r["result"], bool(r.get("session"))) for r in rows] ==
          [("left_click", "allowed", "ok", True), ("start_computer_use", "allowed", "ok", False)], rows)
    check("spend cap -> limit", r == ["limit"], r)
    a, be, desk = make(secs=30)
    be.delay = 0.05
    tool = a.tools["start_computer_use"]
    tool.cfg.secs = 0.3  # (config minimum is 30 s; shortened here to test the deadline)
    be.sess[:] = shots
    ends = []
    a.cu.send = lambda m: asyncio.sleep(0, ends.append(m))
    await tool.run(await tool.prepare({"goal": "x"}), progress=lambda **kw: asyncio.sleep(0))
    check("deadline -> timeout", [m.get("reason") for m in ends if m.get("state") == "ended"] == ["timeout"], ends)
    out, r, _ = await run([ai.ChatError("Can't reach the AI service.")])
    check("API error -> error, reported to the main model", r == ["error"] and "error" in out, (r, out))
    a, be, desk = make()
    a.cfg.daily_token_cap = 1
    a._add_usage(5)
    be.sess[:] = shots
    tool = a.tools["start_computer_use"]
    ends = []
    a.cu.send = lambda m: asyncio.sleep(0, ends.append(m))
    await tool.run(await tool.prepare({"goal": "x"}), progress=lambda **kw: asyncio.sleep(0))
    check("daily budget counts for sessions -> limit", [m.get("reason") for m in ends if m.get("state") == "ended"] == ["limit"], ends)


async def action_tests():
    a, be, desk = make()
    events = []

    async def ev(*x):
        events.append(x)
    s = cu.Session(a.cfg.cu, be, desk, "goal", ev, lambda: None, lambda n: None)
    await s._screenshot_block()
    g = s.geom
    check("geometry: 3840x2160 @1.5 on a monitor at x=1000 -> 1280x720 shots", g.shot_size == (1280, 720), g.shot_size)
    check("shot px -> layout px with offset and fractional scale", g.to_layout(640, 360) == (1000 + 1280.0, 720.0),
          g.to_layout(640, 360))
    check("clamped to the monitor (last shot pixel = 2558 logical)", g.to_layout(5000, -50) == (1000 + 2558.0, 0.0),
          g.to_layout(5000, -50))
    check("layout -> shot round trip", g.to_shot(*g.to_layout(321, 123)) == (321, 123))

    await s.act("left_click", {"coordinate": [640, 360], "text": "ctrl"})
    await s.act("double_click", {"coordinate": [10, 10]})
    await s.act("scroll", {"scroll_direction": "down", "scroll_amount": 3, "coordinate": [100, 100]})
    await s.act("left_click_drag", {"start_coordinate": [0, 0], "coordinate": [100, 50]})
    await s.act("key", {"text": "ctrl+t"})
    await s.act("key", {"text": "Return", "repeat": 2})
    await s.act("type", {"text": "black ops 3"})
    log = desk.log[1:]
    check("actions map onto the desktop", log == [
        ("move", 2280.0, 720.0), ("button", "left", 1, ("ctrl",)), ("move", 1020.0, 20.0), ("button", "left", 2, ()),
        ("move", 1200.0, 200.0), ("scroll", 0, -3), ("drag", (1000.0, 0.0), (1200.0, 100.0)),
        ("key", "t", ("ctrl",)), ("key", "enter", ()), ("key", "enter", ()), ("type", "black ops 3")], log)

    async def refused(name, inp):
        try:
            await s.act(name, inp)
            return False
        except pc_tools.ToolError:
            return True
    check("Super and Ctrl+Alt combos blocked",
          await refused("key", {"text": "super+q"}) and await refused("key", {"text": "ctrl+alt+Delete"})
          and await refused("left_click", {"coordinate": [1, 1], "text": "super"}))
    for cls in ("foot", "com.mitchellh.ghostty", "org.kde.konsole", "org.keepassxc.keepassxc", "org.kde.krunner"):
        desk.cls = cls
        if not (await refused("type", {"text": "rm -rf ~"}) and await refused("key", {"text": "Return"})):
            check(f"blocklisted window refuses typing: {cls}", False)
    check("blocklisted windows (terminals, launchers, password managers) refuse typing and keys", True)
    desk.cls = "firefox"
    desk.overlay = "launcher"
    check("Caelestia launcher open -> typing refused, clicks still fine",
          await refused("type", {"text": "x"}) and not await refused("left_click", {"coordinate": [1, 1]}))
    desk.overlay = "power menu"
    check("power menu open -> even clicks refused", await refused("left_click", {"coordinate": [1, 1]}))
    desk.overlay = None
    check("bad inputs refused", await refused("scroll", {"scroll_direction": "sideways"})
          and await refused("left_click", {"coordinate": "640,360"}) and await refused("key", {"text": "F13"})
          and await refused("type", {"text": "x" * 501}))

    # batch: stop at the first failure, the rest get the exact "Not executed" text
    desk.cls = "foot"
    res = await s._run_calls([act("left_click", "b1", coordinate=[1, 1]), act("type", "b2", text="ls"),
                              act("left_click", "b3", coordinate=[2, 2])])
    check("batch stops at the first failure",
          [r.get("is_error", False) for r in res] == [False, True, True]
          and res[2]["content"] == "Not executed: an earlier computer action in this turn failed."
          and all(r["toolset_name"] == "computer" for r in res), res)

    t = time_ = __import__("time")
    s.last_action = 0
    t0 = t.monotonic()
    await s._pace()
    await s._pace()
    check("at least 300 ms between actions", t.monotonic() - t0 >= 0.29)


async def main():
    await action_tests()
    await limit_tests()
    await socket_tests()
    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        sys.exit(1)
    print("all tests passed")


asyncio.run(main())
