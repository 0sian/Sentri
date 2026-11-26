#!/usr/bin/env python3
"""Activity screen backend: audit log view, memory add/edit/forget from the phone, routines list."""
import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import audit
import companion_daemon as cd
import library
import memory

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


async def main():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        au = audit.AuditLog(td / "audit.jsonl")
        for i in range(5):
            au.record("launch_app", f"Open app {i}", "auto", "ok")
        au.record("type_text", 'Type "' + "x" * 80 + '" into foot', "allowed", "ok")
        au.record("close_window", "Close Steam", "denied", "not run", detail="user")
        st = memory.MemoryStore(td / "memory.toml")
        routines = {"work": SimpleNamespace(name="work", description="Work setup", risk=None,
                                            steps=[SimpleNamespace(summary="Open Firefox"), SimpleNamespace(summary="Set volume to 30%")]),
                    "wipe": SimpleNamespace(name="wipe", description="Danger", risk="high", steps=[SimpleNamespace(summary="Close all windows")])}
        lib = library.Library(au, st, routines)

        check("caps lists what is available", lib.caps() == ["audit", "memory", "routines"], lib.caps())
        check("no routines -> no routines cap", library.Library(au, st, {}).caps() == ["audit", "memory"])
        check("nothing configured -> no caps", library.Library().caps() == [])

        items = lib.audit_items(3)
        check("audit: the last n, oldest first", [i["summary"].split(" ")[0] for i in items] == ["Open", "Type", "Close"] and len(items) == 3, items)
        check("audit: typed text is already cut by the log", len(items[1]["summary"]) < 100)
        check("audit: keeps result and detail", items[2]["result"] == "not run" and items[2]["detail"] == "user" and items[2]["approval"] == "denied")
        check("audit: n is clamped and junk becomes the default", len(lib.audit_items(10_000)) == 7 and len(lib.audit_items("x")) == 7 and len(lib.audit_items(0)) == 1 and len(lib.audit_items(True)) == 7)

        mv = lib.memory_view()
        check("memory: empty view", mv["items"] == [] and mv["max"] == memory.MAX_ENTRIES and mv["max_text"] == memory.MAX_TEXT and mv["broken"] is False, mv)
        ok, msg = lib.memory_op({"t": "memory_add", "text": "Main browser is Vivaldi"})
        check("memory: add", ok and msg == "Saved" and lib.memory_view()["items"][0]["text"] == "Main browser is Vivaldi", (ok, msg))
        mid = lib.memory_view()["items"][0]["id"]
        ok, msg = lib.memory_op({"t": "memory_add", "text": "Main browser is Vivaldi."})
        check("memory: a near-duplicate updates instead of adding", ok and msg == "Updated an existing memory" and len(lib.memory_view()["items"]) == 1, (ok, msg))
        ok, msg = lib.memory_op({"t": "memory_edit", "id": mid, "text": "Main browser is Firefox"})
        check("memory: edit keeps id and date", ok and lib.memory_view()["items"][0]["text"] == "Main browser is Firefox" and lib.memory_view()["items"][0]["id"] == mid, (ok, msg))
        for bad, why in ((" ", "nothing"), ("x" * 300, "too long"), ("my password is hunter2", "secret"), ("key sk-abcdef123456789", "secret")):
            ok, msg = lib.memory_op({"t": "memory_add", "text": bad})
            check(f"memory: refuses {why}", not ok and msg, (ok, msg))
        ok, msg = lib.memory_op({"t": "memory_edit", "id": "m99", "text": "hello there"})
        check("memory: edit of a missing id", not ok and "no memory" in msg, msg)
        ok, msg = lib.memory_op({"t": "memory_edit", "text": "hello there"})
        check("memory: edit without id", not ok, msg)
        ok, msg = lib.memory_op({"t": "memory_add", "text": 5})
        check("memory: non-string text refused", not ok, msg)
        ok, msg = lib.memory_op({"t": "memory_forget", "id": mid})
        check("memory: forget", ok and lib.memory_view()["items"] == [], (ok, msg))
        ok, msg = lib.memory_op({"t": "memory_forget", "id": mid})
        check("memory: forgetting twice is a clean error", not ok, msg)
        check("memory changes are audited without the text", any(e["tool"] == "memory" and e["approval"] == "phone" and "Firefox" not in e["summary"] for e in au.tail(50)))

        (td / "bad.toml").write_text("[[memory]\nbroken")
        broken = library.Library(au, memory.MemoryStore(td / "bad.toml"), {})
        ok, msg = broken.memory_op({"t": "memory_add", "text": "something to remember"})
        check("memory: a broken file is never overwritten", not ok and "syntax error" in msg and broken.memory_view()["broken"] is True and (td / "bad.toml").read_text().endswith("broken"), msg)

        r = lib.routine_items()
        check("routines: sorted, with steps and risk", [x["name"] for x in r] == ["wipe", "work"], r)
        check("routines: steps are summaries", {x["name"]: x["steps"] for x in r}["work"] == ["Open Firefox", "Set volume to 30%"])
        check("routines: risk passed through", {x["name"]: x["risk"] for x in r} == {"work": None, "wipe": "high"})

        # protocol wiring
        srv = cd.Server(None, "tok", 400, None, None, None, lib)
        sent = []

        async def send(m): sent.append(m)
        await srv._library({"t": "audit_get", "n": 2}, send)
        check("audit_get -> audit", sent[-1]["t"] == "audit" and len(sent[-1]["items"]) == 2)
        await srv._library({"t": "memory_get"}, send)
        check("memory_get -> memory", sent[-1]["t"] == "memory" and "max" in sent[-1])
        await srv._library({"t": "routines_get"}, send)
        check("routines_get -> routines", sent[-1]["t"] == "routines" and len(sent[-1]["items"]) == 2)
        sent.clear()
        await srv._library({"t": "memory_add", "text": "Prefers dark themes", "rid": 4}, send)
        check("memory_add -> result then the fresh list", [m["t"] for m in sent] == ["memory_result", "memory"] and sent[0] == {"t": "memory_result", "rid": 4, "ok": True, "msg": "Saved"} and sent[1]["items"][0]["text"] == "Prefers dark themes", sent)
        sent.clear()
        await srv._library({"t": "memory_add", "text": "my password is hunter2", "rid": 5}, send)
        check("a refused add sends only the result", [m["t"] for m in sent] == ["memory_result"] and sent[0]["ok"] is False, sent)
        sent.clear()
        await srv._library({"t": "memory_add", "text": "fine text here", "rid": True}, send)
        await srv._library({"t": "memory_add", "text": "fine text here", "rid": "7"}, send)
        check("bad rid is ignored", sent == [])

    if failures:
        print(f"{len(failures)} FAILED: {failures}"); sys.exit(1)
    print("all tests passed")

asyncio.run(main())
