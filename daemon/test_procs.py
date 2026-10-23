#!/usr/bin/env python3
"""list_processes / list_startup / kill_process. Kills only target throwaway processes started here;
every guard case uses fake process info, so no real system process is ever a target."""
import asyncio
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import ai
import audit
import pc_tools
import procs

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


async def main():
    # --- list_processes: sorted, limited, never command lines ---
    marker = "SECRETARG" + str(os.getpid())
    p = subprocess.Popen([sys.executable, "-c", "import time; [sum(range(10**5)) for _ in iter(int, 1)]", marker])
    time.sleep(0.5)
    lp = procs.ListProcesses()
    out = await lp.run(lp.validate({"sort": "cpu", "limit": 5}))
    check("list_processes: busy process near the top, with PID/owner/CPU/RSS", f"PID {p.pid}" in out
          and "CPU" in out and "MB" in out, out)
    check("list_processes never shows command-line arguments", marker not in out)
    check("list_processes: limit and sort validated", all(await asyncio.gather(*(
        _ref(lp, a) for a in ({"limit": 26}, {"limit": 0}, {"sort": "name"}, {"limit": "5"})))))
    p.kill()
    p.wait()

    # --- list_startup: names only, capped ---
    tmp = Path(tempfile.mkdtemp())
    (tmp / "autostart").mkdir()
    (tmp / "autostart" / "a.desktop").write_text("[Desktop Entry]\nName=My Tray App\nExec=/usr/bin/secret --token abc\n")
    (tmp / "autostart" / "b.desktop").write_text("[Desktop Entry]\nName=Hidden One\nHidden=true\n")
    os.environ["XDG_CONFIG_HOME"] = str(tmp)
    out = await procs.ListStartup().run({})
    check("list_startup: user autostart by name, hidden skipped, no Exec lines, units listed",
          "My Tray App" in out and "Hidden One" not in out and "--token" not in out and "User systemd units" in out, out)

    # --- kill_process guards (fake info: no real process involved) ---
    k = procs.KillProcess()
    real_info = procs.info
    me = os.getuid()

    def fake(name, uid=me):
        return lambda pid: {"pid": pid, "name": name, "uid": uid, "user": "someone", "rss_mb": 50.0,
                            "state": "S", "start": 1, "cpu_ticks": 0}
    cases = [({"pid": 1}, None, "init"), ({"pid": os.getpid()}, None, "daemon itself"),
             ({"pid": 4242}, fake("kwin_wayland"), "session"), ({"pid": 4242}, fake("plasmashell"), "session"),
             ({"pid": 4242}, fake("Hyprland"), "session"), ({"pid": 4242}, fake("systemd"), "session"),
             ({"pid": 4242}, fake("sddm"), "session"), ({"pid": 4242}, fake("firefox", uid=0), "belongs to"),
             ({"pid": True}, None, "pid must"), ({"pid": "123"}, None, "pid must"), ({"pid": 5, "force": "yes"}, None, "force")]
    bad = []
    for args, info, want in cases:
        procs.info = info or real_info
        try:
            await k.prepare(args)
            bad.append((args, "not refused"))
        except pc_tools.ToolError as ex:
            if want not in str(ex):
                bad.append((args, str(ex)))
    procs.info = real_info
    check("kill refuses init, itself, session processes, other users' processes, bad input", not bad, bad)
    check("kill takes a PID only: no name argument exists", set(k.schema["properties"]) == {"pid", "force"})

    # --- real kills on throwaway processes ---
    p = subprocess.Popen(["sleep", "300"])
    time.sleep(0.2)
    a = await k.prepare({"pid": p.pid})
    check("card names the exact process: name, PID, owner, memory, signal",
          k.summary(a).startswith(f"End sleep (PID {p.pid}, ") and "MB) with SIGTERM" in k.summary(a), k.summary(a))
    out = await k.run(a)
    p.wait()
    check("SIGTERM: reports the exit", out == f"sleep (PID {p.pid}) exited after SIGTERM", out)
    p = subprocess.Popen([sys.executable, "-c", "import signal,time; signal.signal(15, signal.SIG_IGN); time.sleep(60)"])
    time.sleep(0.4)
    a = await k.prepare({"pid": p.pid})
    try:
        await k.run(a)
        msg = ""
    except pc_tools.ToolError as ex:
        msg = str(ex)
    check("ignored SIGTERM -> honest error, not success", "still running" in msg and "force=true" in msg, msg)
    a = await k.prepare({"pid": p.pid, "force": True})
    out = await k.run(a)
    p.wait()
    check("force -> SIGKILL, card says so", "Force-kill" in k.summary(a) and "SIGKILL" in k.summary(a)
          and out.endswith("exited after SIGKILL"), out)
    p = subprocess.Popen(["sleep", "300"])
    time.sleep(0.2)
    a = await k.prepare({"pid": p.pid})
    a["proc"]["start"] -= 1  # as if the PID had been reused since the card was shown
    try:
        await k.run(a)
        msg = ""
    except pc_tools.ToolError as ex:
        msg = str(ex)
    alive = p.poll() is None
    p.kill()
    p.wait()
    check("reused PID: nothing sent", "different process" in msg and alive, msg)

    # --- through the assistant: card every time, audit records name/PID/signal/result ---
    log = audit.AuditLog(tmp / "audit.jsonl")

    class Backend:
        def __init__(self):
            self.scripts = []

        async def complete(self, system, messages, on_text, tools, **kw):
            return self.scripts.pop(0)
    be = Backend()
    a = ai.Assistant(ai.AIConfig(api_key="k"), be, usage_file=tmp / "u.json", tools={"kill_process": k}, audit=log)
    cards = []

    async def allow(call, name, summary, risk):
        cards.append((name, risk))
        return (True, None)
    p = subprocess.Popen(["sleep", "300"])
    time.sleep(0.2)
    be.scripts += [ai.Reply([{"type": "tool_use", "id": "t", "name": "kill_process", "input": {"pid": p.pid}}], "tool_use", 1, 1),
                   ai.Reply([{"type": "text", "text": "done"}], "end_turn", 1, 1)]
    assert a.claim()
    await a.turn("stop sleep", lambda s: asyncio.sleep(0), lambda e: asyncio.sleep(0), None, allow)
    p.wait()
    row = log.tail(1)[0]
    check("kill always shows a high-risk card", cards == [("kill_process", "high")], cards)
    check("audit has kill's name, PID, signal and result",
          row["tool"] == "kill_process" and f"sleep (PID {p.pid}" in row["summary"] and "SIGTERM" in row["summary"]
          and row["approval"] == "allowed" and row["result"] == "ok", row)

    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        sys.exit(1)
    print("all tests passed")


async def _ref(tool, args):
    try:
        tool.validate(args)
        return False
    except pc_tools.ToolError:
        return True


asyncio.run(main())
