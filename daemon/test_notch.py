#!/usr/bin/env python3
"""The notch eye states the daemon sends while a chat turn runs (ai.Assistant.notch + ChatSession hooks)."""
import asyncio
import sys

import json
import tempfile
from pathlib import Path
import types

import ai
import gaze
import pc_tools
import guide

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class RecOverlay:
    def __init__(self):
        self.rows, self.msgs = [], []

    async def send(self, msg, spawn=True):
        self.msgs.append(msg)
        self.rows.append((msg.get("name") if msg["cmd"] == "state" else msg["cmd"] + ":" + str(msg.get("name", msg.get("call"))), spawn))
        return True


class BrokenOverlay:
    async def send(self, msg, spawn=True):
        raise RuntimeError("no desktop")


class StubAssistant:
    """Just what ChatSession touches; turn() plays a scripted sequence of callbacks."""
    notch = ai.Assistant.notch
    _notch_send = ai.Assistant._notch_send
    notch_mood = ai.Assistant.notch_mood
    notch_card = ai.Assistant.notch_card
    notch_card_done = ai.Assistant.notch_card_done
    _overlay_event = ai.Assistant._overlay_event
    _fire = ai.Assistant._fire
    notch_peek = ai.Assistant.notch_peek

    def __init__(self, overlay, script):
        self.overlay, self.script = overlay, script
        self._notch_last, self._notch_tasks = None, set()
        self.busy = False
        self.cfg = ai.AIConfig(api_key="x")
        self.cu = types.SimpleNamespace(send=None, active=False)
        self._card_waiters = {}

    def claim(self):
        self.busy = True
        return True

    def spend(self):
        return {}

    async def turn(self, text, on_text, on_tool, on_mood, on_confirm):
        await self.script(on_text, on_tool, on_confirm)
        return {"in": 1, "out": 1}


async def settle():
    await asyncio.sleep(0.05)


async def run(script):
    ov = RecOverlay()
    out = []

    async def send(m):
        out.append(m["t"])

    cs = ai.ChatSession(StubAssistant(ov, script), send)
    await cs.handle({"t": "chat", "id": 1, "text": "hi"})
    await cs.task
    await settle()
    return [n for n, _ in ov.rows], [s for _, s in ov.rows], out


async def main():
    async def plain(text, tool, confirm):
        await text("a"); await text("b")
    states, spawns, out = await run(plain)
    check("plain reply: thinking, talking (once), idle", states == ["thinking", "talking", "idle"], states)
    check("state events never spawn the overlay", not any(spawns))

    async def with_tool(text, tool, confirm):
        await tool({"state": "running", "name": "x"}); await tool({"state": "ok", "name": "x"}); await text("done")
    states, _, _ = await run(with_tool)
    check("tool turn: thinking, working, thinking, talking, idle", states == ["thinking", "working", "thinking", "talking", "idle"], states)

    async def with_confirm(text, tool, confirm):
        # _confirm sends confirm_req and waits; answer it from outside
        r = asyncio.ensure_future(confirm("c1", "close_window", "Close X", "medium"))
        await asyncio.sleep(0.05)
        cs_holder[0].pending["c1"].set_result(True)
        await r
    cs_holder = []
    ov = RecOverlay()

    async def send(m): pass
    cs = ai.ChatSession(StubAssistant(ov, with_confirm), send)
    cs_holder.append(cs)
    await cs.handle({"t": "chat", "id": 1, "text": "hi"}); await cs.task; await settle()
    check("confirm card: waiting", [n for n, _ in ov.rows] == ["thinking", "waiting", "idle"], ov.rows)

    async def boom(text, tool, confirm):
        raise ai.ChatError("nope")
    states, _, out = await run(boom)
    check("error turn: thinking, error", states == ["thinking", "error"], states)
    check("error still reported to the phone", out == ["chat_error"], out)

    # a broken overlay must never disturb a turn
    cs = ai.ChatSession(StubAssistant(BrokenOverlay(), plain), send)
    await cs.handle({"t": "chat", "id": 2, "text": "hi"}); await cs.task; await settle()
    check("broken overlay doesn't break the turn", True)

    # no overlay at all
    a = StubAssistant(None, plain)
    a.notch("thinking")
    check("no overlay: notch() is a no-op", not a._notch_tasks)

    a = StubAssistant(RecOverlay(), plain)
    a.notch("wake", spawn=True); a.notch("wake", spawn=True); await settle()
    check("wake always sent (spawns the overlay)", a.overlay.rows == [("wake", True), ("wake", True)], a.overlay.rows)

    # --- PC-side approval ---
    async def card_case(name, risk, answer, cu_active=False):
        """Run a turn that asks one confirm; answer(assistant, session) plays the user. Returns
        (allowed, overlay msgs)."""
        ov = RecOverlay()
        holder = {}

        async def script(text, tool, confirm):
            holder["r"] = asyncio.ensure_future(confirm("c1", name, "Open https://example.com", risk))
            await asyncio.sleep(0.05)
            await answer(holder["a"], holder["cs"])
            holder["res"] = await holder["r"]

        a = StubAssistant(ov, script)
        a.cu.active = cu_active
        holder["a"] = a
        async def keep(m): pass
        cs = ai.ChatSession(a, keep)
        holder["cs"] = cs
        await cs.handle({"t": "chat", "id": 1, "text": "hi"}); await cs.task; await settle()
        return holder["res"], ov.msgs

    async def click(allow):
        async def f(a, cs): a._overlay_event({"event": "confirm", "call": "c1", "allow": allow})
        return f
    async def phone(allow):
        async def f(a, cs): cs.pending["c1"].set_result(allow)
        return f
    kinds = lambda msgs: [m["cmd"] for m in msgs if m["cmd"].startswith("confirm")]

    res, msgs = await card_case("open_url", "low", await click(True))
    check("notch Allow resolves the card", res == (True, None) and kinds(msgs) == ["confirm", "confirm_clear"], (res, kinds(msgs)))
    res, msgs = await card_case("open_url", "low", await click(False))
    check("notch Deny denies", res == (False, "user"), res)
    res, msgs = await card_case("open_url", "low", await phone(True))
    check("phone answering first clears the notch card", res == (True, None) and kinds(msgs) == ["confirm", "confirm_clear"], (res, kinds(msgs)))
    res, msgs = await card_case("screenshot", "high", await phone(True))
    check("high-risk / unlisted tools are phone-only (no notch card)", kinds(msgs) == [], kinds(msgs))
    res, msgs = await card_case("type_text", "low", await phone(False))
    check("low-risk but not on the PC list: phone-only", kinds(msgs) == [], kinds(msgs))
    res, msgs = await card_case("open_url", "low", await phone(True), cu_active=True)
    check("no notch card during a computer-use session", kinds(msgs) == [], kinds(msgs))

    async def bad_events(a, cs):
        for ev in ({"event": "confirm", "call": "c1", "allow": "yes"}, {"event": "confirm", "call": "c1", "allow": 1},
                   {"event": "confirm", "call": "zzz", "allow": True}, {"event": "other"}, {}):
            a._overlay_event(ev)
        cs.pending["c1"].set_result(False)
    res, _ = await card_case("open_url", "low", bad_events)
    check("junk or non-boolean overlay events are ignored", res == (False, "user"), res)

    async def late_cu(a, cs):
        a.cu.active = True          # a session started while the card was up: a notch click no longer counts
        a._overlay_event({"event": "confirm", "call": "c1", "allow": True})
        cs.pending["c1"].set_result(False)
    res, _ = await card_case("open_url", "low", late_cu)
    check("a notch click is ignored once a computer-use session is active", res == (False, "user"), res)

    # overlay -> daemon event channel (real Overlay.listen against a tiny unix server)
    with tempfile.TemporaryDirectory() as td:
        sock = Path(td) / "o.sock"
        seen = []

        async def handle(r, w):
            await r.readline()
            w.write(b'{"ok":true}\n'); await w.drain()
            w.write(b'garbage\n{"event":"confirm","call":"c7","allow":true}\n'); await w.drain()
            await asyncio.sleep(0.3)
            w.close()
        srv = await asyncio.start_unix_server(handle, str(sock))
        ov = guide.Overlay(sock=sock)
        ov.proc = types.SimpleNamespace(returncode=None)
        t = asyncio.ensure_future(ov.listen(seen.append))
        await asyncio.sleep(0.3)
        t.cancel(); srv.close()
        check("Overlay.listen delivers events and skips junk lines", seen == [{"event": "confirm", "call": "c7", "allow": True}], seen)

    # --- homelab peek ---
    rows = pc_tools.glances_peek_rows("fs", "/data (ext4): 93% of 3.6 GB (1 GB free)\n/ (ext4): 84% of 233 GB\n/boot: 12% of 1 GB")
    check("peek levels: >=90 red, >=80 amber, else ok", [r["l"] for r in rows] == [2, 1, 0], rows)
    rows = pc_tools.glances_peek_rows("containers", "web: running (3 days)\ndb: exited (1)\nq: Up 2 hours\n(+4 more)")
    check("peek containers: only not-running ones are red", [r["l"] for r in rows] == [0, 2, 0, 0], rows)
    rows = pc_tools.glances_peek_rows("sensors", "CPU: 88C\nGPU: 92C\nNVMe: 40C")
    check("peek sensors thresholds", [r["l"] for r in rows] == [1, 2, 0], rows)
    rows = pc_tools.glances_peek_rows("uptime", "\n".join(f"line {i} " + "x" * 80 for i in range(9)))
    check("peek rows capped and clipped", len(rows) == pc_tools.PEEK_ROWS and all(len(r["t"]) <= pc_tools.PEEK_WIDTH for r in rows), rows)

    ov = RecOverlay()
    h = pc_tools.HomelabStats(pc_tools.Glances("http://x", "/api/4", "", ""))
    h._get = lambda plugin: {"percent": 95.0, "used": 9e9, "total": 1e10}
    got = []
    h.peek = lambda title, rows: got.append((title, rows))
    out = await h.run({"section": "fs"})
    await asyncio.sleep(0.05)
    check("multi-line sections peek their own rows", got and got[0][0] == "disk usage", got)
    got.clear()
    out = await h.run({"section": "mem"})
    await asyncio.sleep(0.1)
    rows = got[0][1] if got else []
    check("a one-line section peeks a small overview", got and got[0][0] == "homelab" and len(rows) >= 4
          and rows[0]["t"].startswith(("Up", "CPU")) and any(r["t"].startswith("Memory 95%") and r["l"] == 2 for r in rows) and "Memory 95%" in out, got)
    h.peek = lambda title, rows: 1 / 0
    out = await h.run({"section": "mem"})
    await asyncio.sleep(0.1)
    check("a failing peek doesn't break the tool", "Memory 95%" in out)
    a = StubAssistant(ov, plain)
    a.notch_peek = lambda *x, **k: ai.Assistant.notch_peek(a, *x, **k)
    a.notch_peek("memory", [{"t": "Memory 95%", "l": 2}]); await settle()
    check("notch_peek sends a peek command without spawning", ov.msgs and ov.msgs[0]["cmd"] == "peek" and ov.msgs[0]["rows"][0]["l"] == 2 and not ov.rows[0][1], ov.msgs)

    # moods
    ov = RecOverlay()
    sent = []

    async def keep(m): sent.append(m)
    cs = ai.ChatSession(StubAssistant(ov, plain), keep)
    await cs._mood(1, "happy"); await cs._mood(1, "bogus"); await settle()
    check("mood goes to the notch and the phone", ov.rows == [("mood:happy", False)] and [m["mood"] for m in sent] == ["happy", "bogus"], (ov.rows, sent))

    # cursor watcher
    pts = iter([(1, 1), (1, 1), (5, 5), (5, 5), (9, 9)])
    got, alive = [], [True]

    async def src():
        try:
            return next(pts)
        except StopIteration:
            return (9, 9)

    async def snd(m): got.append((m["x"], m["y"]))
    gaze.FAST = gaze.SLOW = 0.001
    t = asyncio.ensure_future(gaze.watch(snd, lambda: alive[0], src))
    await asyncio.sleep(0.2)
    check("cursor: only changes are sent", got == [(1, 1), (5, 5), (9, 9)], got)
    alive[0] = False
    await asyncio.sleep(0.05)
    n = len(got)
    alive[0] = True
    await asyncio.sleep(1.3)    # the loop idles for a second while the overlay is down
    check("cursor: nothing sent while the overlay is down, resumes after", len(got) == n + 1 and got[-1] == (9, 9), got)
    t.cancel()

    if failures:
        print(f"{len(failures)} FAILED: {failures}"); sys.exit(1)
    print("all tests passed")

asyncio.run(main())
