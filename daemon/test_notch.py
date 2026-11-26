#!/usr/bin/env python3
"""The notch eye states the daemon sends while a chat turn runs (ai.Assistant.notch + ChatSession hooks)."""
import asyncio
import sys

import ai

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class RecOverlay:
    def __init__(self):
        self.rows = []

    async def send(self, msg, spawn=True):
        self.rows.append((msg.get("name"), spawn))
        return True


class BrokenOverlay:
    async def send(self, msg, spawn=True):
        raise RuntimeError("no desktop")


class StubAssistant:
    """Just what ChatSession touches; turn() plays a scripted sequence of callbacks."""
    notch = ai.Assistant.notch
    _notch_send = ai.Assistant._notch_send

    def __init__(self, overlay, script):
        self.overlay, self.script = overlay, script
        self._notch_last, self._notch_tasks = None, set()
        self.busy = False
        self.cfg = ai.AIConfig(api_key="x")
        self.cu = type("C", (), {"send": None})()

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

    if failures:
        print(f"{len(failures)} FAILED: {failures}"); sys.exit(1)
    print("all tests passed")

asyncio.run(main())
