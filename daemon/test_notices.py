#!/usr/bin/env python3
"""Timers / reminders and process watches: persistence, firing, caps, the two tools, and the Assistant wiring."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import ai
import notices
import pc_tools
from pc_tools import ToolError

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class Clock:
    def __init__(self): self.t = 1_000_000.0
    def __call__(self): return self.t


async def raises(coro_or_fn, text=""):
    try:
        r = coro_or_fn() if callable(coro_or_fn) else coro_or_fn
        if asyncio.iscoroutine(r):
            await r
    except ToolError as ex:
        return text in str(ex)
    return False


async def main():
    check("fmt", notices.fmt(272) == "4:32" and notices.fmt(3725) == "1:02:05" and notices.fmt(-5) == "0:00" and notices.fmt(0.4) == "0:00")

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "timers.json"
        clk, fired, synced = Clock(), [], []

        async def fire(label, late): fired.append((label, round(late)))
        tm = notices.Timers(fire, lambda items: synced.append(items), path, clk)

        tid = tm.add(600, "Tea")
        check("add: listed with an absolute end, pushed to the notch, saved", tm.listing() == [{"id": tid, "label": "Tea", "end": clk.t + 600}]
              and synced[-1] == tm.listing() and json.loads(path.read_text())[tid]["label"] == "Tea")
        check("the saved file is private", oct(path.stat().st_mode & 0o777) == "0o600")
        tm.add(60, "Short")
        check("listing is soonest first", [i["label"] for i in tm.listing()] == ["Short", "Tea"])
        check("cancel one", tm.cancel(tid) == 1 and [i["label"] for i in tm.listing()] == ["Short"] and synced[-1] == tm.listing())
        check("cancel unknown is a no-op", tm.cancel("nope") == 0)
        check("cancel all", tm.cancel("all") == 1 and tm.listing() == [] and synced[-1] == [])
        for i in range(notices.MAX_TIMERS):
            tm.add(100 + i, f"t{i}")
        check("timer cap", await raises(lambda: tm.add(5, "x"), "already"))
        tm.cancel("all")
        check("control characters in labels are cleaned", "\n" not in (tm.items[tm.add(30, "a\nb\x07c")]["label"]))
        tm.cancel("all")

        # real firing, with a short real timer
        quick = notices.Timers(fire, lambda items: None, Path(td) / "q.json")   # real clock
        quick.add(1, "Ping")
        await asyncio.sleep(1.4)
        check("a due timer fires once and is removed", fired == [("Ping", 0)] and quick.listing() == [], (fired, quick.listing()))
        check("...and is removed from the saved file", json.loads((Path(td) / "q.json").read_text()) == {})

        # restart: saved timers are re-armed; late ones announced; very late ones dropped
        fired.clear()
        path.write_text(json.dumps({"a": {"label": "Soon", "end": clk.t + 1}, "b": {"label": "Late", "end": clk.t - 300},
                                    "c": {"label": "Ancient", "end": clk.t - 7200}, "d": "junk", "e": {"label": 5, "end": "x"}}))
        tm2 = notices.Timers(fire, lambda items: None, path, clk)
        tm2.start()
        check("start: junk ignored, ancient dropped, late kept", sorted(tm2.items) == ["a", "b"], tm2.items)
        await asyncio.sleep(0.3)
        check("start: a timer that came due while we were down fires at once, with how late", fired == [("Late", 300)], fired)
        tm2.stop()
        path.write_text("not json")
        tm3 = notices.Timers(fire, lambda items: None, path, clk); tm3.start()
        check("a corrupt file is just empty", tm3.items == {})

        # tool
        tool = notices.TimerTool(notices.Timers(fire, lambda i: None, Path(td) / "t.json", clk))
        a = tool.validate({"action": "set", "seconds": 600, "label": "Tea"})
        check("tool: set summary and run", tool.summary(a) == "Set a timer for 10:00: Tea" and "set for 10:00" in await tool.run(a))
        check("tool: list", "Tea, 10:00 left" in await tool.run(tool.validate({"action": "list"})))
        tid = tool.timers.listing()[0]["id"]
        check("tool: cancel by id", "Cancelled 1" in await tool.run(tool.validate({"action": "cancel", "id": tid})))
        check("tool: nothing running", await tool.run(tool.validate({"action": "list"})) == "No timers running")
        for bad in ({"action": "set"}, {"action": "set", "seconds": 0}, {"action": "set", "seconds": 90000}, {"action": "set", "seconds": "5"},
                    {"action": "set", "seconds": True}, {"action": "cancel"}, {"action": "boom"}, {}):
            if not await raises(lambda bad=bad: tool.validate(bad)):
                check(f"tool: rejects {bad}", False); break
        else:
            check("tool: bad arguments are rejected", True)
        check("tool needs no card", tool.risk is None and not tool.needs_confirm({}))
        tool.timers.stop()

    # ---- process watches ----
    alive = {1234: 111}
    done = []

    def info(pid):
        if pid not in alive:
            raise ToolError(f"no process with PID {pid}")
        return {"pid": pid, "name": "makepkg", "start": alive[pid]}

    async def announce(name): done.append(name)
    w = notices.Watches(announce, poll=0.05, info=info)
    check("watch: unknown pid refused", await raises(lambda: w.add(999), "no process"))
    name = w.add(1234)
    check("watch: uses the process name by default", name == "makepkg" and 1234 in w.tasks)
    check("watch: the same pid twice refused", await raises(lambda: w.add(1234), "already"))
    await asyncio.sleep(0.2)
    check("watch: still running -> nothing yet", done == [])
    del alive[1234]
    await asyncio.sleep(0.2)
    check("watch: announced when the process ends, then forgotten", done == ["makepkg"] and 1234 not in w.tasks, (done, w.tasks))
    alive[77] = 5; done.clear()
    w.add(77, "my build")
    alive[77] = 6          # the pid was reused by a different process
    await asyncio.sleep(0.2)
    check("watch: a reused pid counts as finished; custom label used", done == ["my build"], done)
    for p in range(100, 100 + notices.MAX_WATCHES):
        alive[p] = 1; w.add(p)
    alive[200] = 1
    check("watch cap", await raises(lambda: w.add(200), "already watching"))
    w.stop()
    wt = notices.WatchProcessTool(w)
    check("watch tool validates pids", await raises(lambda: wt.validate({"pid": 1})) and await raises(lambda: wt.validate({"pid": "x"})) and wt.validate({"pid": 50, "label": "x\ny"})["label"] == "x y")
    check("watch tool needs no card", wt.risk is None)

    # ---- Assistant wiring ----
    sent = []

    class Ov:
        async def send(self, msg, spawn=True): sent.append((msg, spawn)); return True
        def _alive(self): return True

    with tempfile.TemporaryDirectory() as td:
        cfg = ai.AIConfig(api_key="x")
        a = ai.Assistant(cfg, backend=SimpleNamespace(), usage_file=Path(td) / "u.json", desktop=object(), overlay=Ov())
        check("assistant registers timer and watch_process when there is a desktop", isinstance(a.tools.get("timer"), notices.TimerTool) and "watch_process" in a.tools)
        check("...after the older tools (the order is part of the cached prompt)", list(a.tools)[-3:] == ["timer", "watch_process", "guide_steps"], list(a.tools)[-4:])
        a.timers.path = Path(td) / "t.json"
        a.timers.add(300, "Tea")
        await asyncio.sleep(0.05)
        check("setting a timer pushes the list to the notch without starting it", sent and sent[-1][0]["cmd"] == "timers" and sent[-1][0]["items"][0]["label"] == "Tea" and sent[-1][1] is False, sent)
        sent.clear()
        await a._timer_fire("Tea", 0)
        peek = [m for m, _ in sent if m["cmd"] == "peek"][0]
        check("a fired timer shows a sticky peek, spawning the notch", peek["sticky"] is True and peek["rows"][0]["t"] == "Tea" and [s for m, s in sent if m["cmd"] == "peek"] == [True], sent)
        sent.clear()
        await a._timer_fire("Late one", 600)
        check("a late timer says how late", "was due 10 min ago" in [m for m, _ in sent if m["cmd"] == "peek"][0]["rows"][0]["t"])
        sent.clear()
        await a._watch_done("makepkg")
        p2 = [m for m, _ in sent if m["cmd"] == "peek"][0]
        check("a finished process shows a short peek", p2["title"] == "Finished" and p2["rows"][0]["t"] == "makepkg finished" and p2["ttl"] == 15 and "sticky" not in p2)
        a.timers.stop(); a.watches.stop()
        b = ai.Assistant(cfg, backend=SimpleNamespace(), usage_file=Path(td) / "u2.json")
        check("no desktop: no timer tools", "timer" not in b.tools)

    if failures:
        print(f"{len(failures)} FAILED: {failures}"); sys.exit(1)
    print("all tests passed")

asyncio.run(main())
