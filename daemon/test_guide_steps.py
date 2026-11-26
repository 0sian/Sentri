#!/usr/bin/env python3
"""Multi-step guides (guide_steps): validation, step 1, the notch's Next button, a fresh privacy check and locate
per step, retry when a target isn't found, ending, and the Assistant wiring. In-memory fakes, no overlay process."""
import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import ai
import cu
import guide
import pc_tools
import sensitivity
import session

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class Ov:
    def __init__(self): self.sent, self.visible_until = [], 0.0
    def available(self): return True
    async def warm(self): pass
    def guide_may_be_showing(self): return False
    async def send(self, msg, spawn=True): self.sent.append(msg); return True
    def cmds(self): return [m["cmd"] for m in self.sent]


class Desk:
    geom = cu.Geometry(0, 0, 1.0, 1920, 1080, 1.0)
    def available(self): return True
    async def screenshot(self, zoom_region=None, geom=None, edge=cu.SHOT_EDGE): return b"\xff\xd8jpeg", self.geom


class Loc:
    def __init__(self, answers): self.answers, self.calls = list(answers), []
    async def locate(self, b64, w, h, target):
        self.calls.append(target)
        return self.answers.pop(0) if self.answers else (100.0, 100.0)


async def settle(tool):
    while tool._tasks:
        await asyncio.gather(*list(tool._tasks))


async def raises(f, text=""):
    try:
        r = f()
        if asyncio.iscoroutine(r):
            await r
    except pc_tools.ToolError as ex:
        return text in str(ex)
    return False


STEPS = [{"target": "the File menu", "instructions": "Open File."}, {"target": "Save As", "instructions": "Pick Save As."},
         {"target": "the Save button", "instructions": "Click Save."}]


def make(answers=(), windows=None, ask=None):
    ov, loc = Ov(), Loc(answers)
    wins = {"w": windows or [{"cls": "systemsettings", "title": "Display"}]}

    async def fake_windows(): return wins["w"]
    tool = guide.GuideSteps(ov, Desk(), loc, windows=fake_windows, ask=ask)
    return tool, ov, loc, wins


async def main():
    session.desktop_ready = lambda: True
    pc_tools.desktop_env = lambda: {"XDG_RUNTIME_DIR": "/tmp"}
    guide.HIDE_SETTLE = 0.01

    tool, ov, loc, wins = make()
    v = tool.validate({"steps": STEPS, "title": "Saving a copy"})
    check("validate: steps cleaned, first target kept for the card", len(v["steps"]) == 3 and v["target"] == "the File menu" and v["title"] == "Saving a copy")
    for bad, why in (({"steps": []}, "empty"), ({"steps": STEPS * 3}, "too many"), ({"steps": "x"}, "not a list"), ({}, "missing"),
                     ({"steps": [{"target": "a"}]}, "no instructions"), ({"steps": [5]}, "not a dict"),
                     ({"steps": [{"target": " ", "instructions": "x"}]}, "blank target")):
        if not await raises(lambda bad=bad: tool.validate(bad)):
            check(f"validate rejects {why}", False); break
    else:
        check("validate rejects empty / too many / malformed steps", True)
    check("validate cleans control characters", "\n" not in tool.validate({"steps": [{"target": "a\nb", "instructions": "c\x07d"}]})["steps"][0]["target"])
    check("one tool object, risk is dynamic like point_at_screen", tool.risk_for({"_ask": "x"}) == "low" and tool.risk_for({}) is None)
    d = tool.definition()
    check("schema is a strict object with an array of step objects", d.get("strict") is True and d["input_schema"]["properties"]["steps"]["type"] == "array")

    # prepare / summary
    a = await tool.prepare({"steps": STEPS})
    check("harmless windows: no card, summary names the step count", a["_ask"] == "" and "3 steps" in tool.summary(a) and "the File menu" in tool.summary(a), tool.summary(a))
    tool2, *_ = make(windows=[{"cls": "discord", "title": "Chat"}])
    a2 = await tool2.prepare({"steps": STEPS})
    check("a private-looking window: a card is asked for, with the reason", a2["_ask"] and "Asking first because" in tool2.summary(a2) and "3 steps" in tool2.summary(a2), tool2.summary(a2))

    # step 1
    out = await tool.run(a)
    p = [m for m in ov.sent if m["cmd"] == "point"][0]
    check("step 1 is drawn with Step 1 of 3 and a long ttl", p["step"] == {"i": 1, "n": 3} and p["title"] == "Step 1 of 3" and p["ttl"] == guide.STEP_TTL and p["text"] == "Open File.", p)
    check("the model is told what happens next", "Next on the notch" in out and "step 1 of 3" in out.lower())
    check("a session is running", tool.session is not None and tool.session.i == 0 and tool.session.shown)
    check("title is added to each step's heading", (lambda t: t._title() if (setattr(t, "i", 1) or True) else "")(guide.StepSession(tool, STEPS, "Saving", False)) == "Step 2 of 3: Saving")

    # Next -> step 2 (hold, fresh locate)
    ov.sent.clear()
    tool.on_overlay_event({"event": "guide_next"}); await settle(tool)
    check("Next: hides the rope, then shows step 2 on a fresh locate", ov.cmds() == ["hold", "point"] and ov.sent[1]["step"] == {"i": 2, "n": 3} and loc.calls[-1] == "Save As", (ov.cmds(), loc.calls))
    # last step
    ov.sent.clear()
    tool.on_overlay_event({"event": "guide_next"}); await settle(tool)
    check("Next again: step 3 is the last", ov.sent[-1]["step"] == {"i": 3, "n": 3})
    ov.sent.clear()
    tool.on_overlay_event({"event": "guide_next"}); await settle(tool)
    check("Next on the last step clears the guide and ends the session", ov.cmds() == ["clear"] and tool.session is None, (ov.cmds(), tool.session))
    tool.on_overlay_event({"event": "guide_next"}); await settle(tool)
    check("Next with no session does nothing", ov.cmds() == ["clear"])

    # step 1 not found -> no session
    t3, ov3, loc3, _ = make(answers=[None])
    out = await t3.run(await t3.prepare({"steps": STEPS}))
    check("step 1 not visible: clear message, no session, nothing drawn", "Couldn't see" in out and t3.session is None and "point" not in ov3.cmds())

    # step 2 not found -> stepinfo note, Next retries the SAME step
    t4, ov4, loc4, _ = make(answers=[(10.0, 10.0), None, (50.0, 50.0), (60.0, 60.0)])
    await t4.run(await t4.prepare({"steps": STEPS}))
    ov4.sent.clear()
    t4.on_overlay_event({"event": "guide_next"}); await settle(t4)
    info = [m for m in ov4.sent if m["cmd"] == "stepinfo"]
    check("step 2 not found: the notch says so, showing step 2 of 3", len(info) == 1 and info[0]["i"] == 2 and "tap Next" in info[0]["note"], ov4.sent)
    ov4.sent.clear()
    t4.on_overlay_event({"event": "guide_next"}); await settle(t4)
    pts = [m for m in ov4.sent if m["cmd"] == "point"]
    check("Next retries step 2 (it doesn't skip ahead)", len(pts) == 1 and pts[0]["step"]["i"] == 2 and loc4.calls[-2:] == ["Save As", "Save As"], (ov4.sent, loc4.calls))
    ov4.sent.clear()
    t4.on_overlay_event({"event": "guide_next"}); await settle(t4)
    check("and then moves on to step 3", [m for m in ov4.sent if m["cmd"] == "point"][0]["step"]["i"] == 3)

    # privacy re-check on later steps
    asked = []

    async def deny(summary): asked.append(summary); return False

    async def allow(summary): asked.append(summary); return True
    t5, ov5, loc5, w5 = make(ask=deny)
    await t5.run(await t5.prepare({"steps": STEPS}))
    w5["w"] = [{"cls": "discord", "title": "Chat"}]      # the user navigated to something private
    ov5.sent.clear()
    t5.on_overlay_event({"event": "guide_next"}); await settle(t5)
    check("a private window at step 2: asked on the notch (names the step, never the title)", len(asked) == 1 and "step 2" in asked[0] and "Save As" in asked[0] and "Chat" not in asked[0], asked)
    check("denied: no screenshot is located, the guide is cleared and ended", ov5.cmds() == ["hold", "clear"] and t5.session is None and loc5.calls == ["the File menu"], (ov5.cmds(), loc5.calls))
    t6, ov6, loc6, w6 = make(ask=allow)
    await t6.run(await t6.prepare({"steps": STEPS}))
    w6["w"] = [{"cls": "discord", "title": "Chat"}]
    t6.on_overlay_event({"event": "guide_next"}); await settle(t6)
    check("allowed: the step is shown", loc6.calls[-1] == "Save As" and t6.session is not None)
    t7, ov7, loc7, w7 = make(ask=None)
    await t7.run(await t7.prepare({"steps": STEPS}))
    w7["w"] = [{"cls": "discord", "title": "Chat"}]
    t7.on_overlay_event({"event": "guide_next"}); await settle(t7)
    check("no way to ask: a private step is never located", loc7.calls == ["the File menu"] and t7.session is None)

    # ending
    t8, ov8, *_ = make()
    await t8.run(await t8.prepare({"steps": STEPS}))
    t8.on_overlay_event({"event": "guide_end"}); await settle(t8)
    check("guide_end (tap, timeout, clear) ends the session", t8.session is None)
    old = None
    t9, ov9, *_ = make()
    await t9.run(await t9.prepare({"steps": STEPS})); old = t9.session
    await t9.run(await t9.prepare({"steps": STEPS}))
    check("starting a new guide ends the old session", old.alive is False and t9.session is not old and t9.session.alive)

    # double Next
    t10, ov10, loc10, _ = make()
    await t10.run(await t10.prepare({"steps": STEPS}))
    t10.on_overlay_event({"event": "guide_next"}); t10.on_overlay_event({"event": "guide_next"}); await settle(t10)
    check("a double tap on Next advances once", t10.session.i == 1 and loc10.calls.count("Save As") == 1, (t10.session.i, loc10.calls))

    # ---- Assistant wiring ----
    sent = []

    class AOv(Ov):
        async def send(self, msg, spawn=True): sent.append(msg); return True
        def _alive(self): return True

    with tempfile.TemporaryDirectory() as td:
        a = ai.Assistant(ai.AIConfig(api_key="x"), backend=SimpleNamespace(), usage_file=Path(td) / "u.json", desktop=Desk(), overlay=AOv())
        check("assistant registers guide_steps, last", isinstance(a.tools.get("guide_steps"), guide.GuideSteps) and list(a.tools)[-1] == "guide_steps", list(a.tools)[-3:])
        check("strict tool count still within the limit", sum(1 for d in a.tool_defs if d.get("strict")) <= pc_tools.MAX_STRICT)
        got = []
        a.tools["guide_steps"].on_overlay_event = lambda ev: got.append(ev)
        a._overlay_event({"event": "guide_next"}); a._overlay_event({"event": "guide_end"}); a._overlay_event({"event": "other"})
        check("overlay guide events reach the tool", [e["event"] for e in got] == ["guide_next", "guide_end"])
        a.cu = SimpleNamespace(active=True)
        check("no notch approval while computer use is active", await a._guide_ask("x") is False)
        a.cu = SimpleNamespace(active=False)

        async def click_allow():
            await asyncio.sleep(0.05)
            call = next(iter(a._card_waiters))
            a._overlay_event({"event": "confirm", "call": call, "allow": True})
        t = asyncio.ensure_future(click_allow())
        check("an Allow on the notch approves the step", await a._guide_ask("Look at your screen again for step 2: x.") is True)
        await t
        await asyncio.sleep(0.1)
        check("the card is cleared afterwards", a._card_waiters == {} and sent[-1]["cmd"] == "confirm_clear", sent[-1])
        a.timers.stop(); a.watches.stop()

    if failures:
        print(f"{len(failures)} FAILED: {failures}"); sys.exit(1)
    print("all tests passed")

asyncio.run(main())
