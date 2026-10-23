#!/usr/bin/env python3
"""Before-login operation: session tracking, desktop gating, and no typed text in any log."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

import websockets
from evdev import ecodes as e

import ai
import companion_daemon as cd
import pc_tools
import session

TMP = Path(tempfile.mkdtemp())
TOKEN = "test-token"
PORT = 18815
failures = []
SECRET = "hunter2-SECRET-xyz"


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
os.environ["XDG_RUNTIME_DIR"] = str(TMP)
for k in session.SESSION_VARS:
    os.environ.pop(k, None)


def session_tests():
    env = {"WAYLAND_DISPLAY": "wayland-1", "HYPRLAND_INSTANCE_SIGNATURE": "abc", "XDG_CURRENT_DESKTOP": "Hyprland"}
    check("at the login screen: nothing set, desktop not ready",
          not session.refresh(lambda: env) and not session.desktop_ready() and session.describe() == "none (login screen)")
    (TMP / "wayland-1").touch()
    (TMP / "hypr" / "abc").mkdir(parents=True)
    check("after login: variables picked up from the user manager", session.refresh(lambda: env)
          and session.desktop_ready() and os.environ["HYPRLAND_INSTANCE_SIGNATURE"] == "abc"
          and session.describe() == "Hyprland")
    check("no change -> refresh reports nothing", not session.refresh(lambda: env))
    (TMP / "wayland-1").unlink()
    changed = session.refresh(lambda: env)
    check("after logout: stale variables dropped even though the manager still lists them",
          changed and not session.desktop_ready() and "WAYLAND_DISPLAY" not in os.environ
          and "HYPRLAND_INSTANCE_SIGNATURE" not in os.environ)
    check("all session variables cleared at the login screen",
          not any(k in os.environ for k in session.SESSION_VARS), {k: os.environ.get(k) for k in session.SESSION_VARS})


async def gating_tests():
    reg = pc_tools.registry(injector=object(), commands=[pc_tools.NamedCommand("x", "x", ["true"])])
    login_screen_ok = sorted(n for n, t in reg.items() if not t.needs_desktop)
    check("tools that work at the login screen", login_screen_ok ==
          ["get_status", "media_control", "run_named_command", "set_volume"], login_screen_ok)

    class Needs(pc_tools.Tool):
        name = "launch_app"

        async def run(self, a):
            return "ran"

    class NoNeed(Needs):
        name = "set_volume"
        needs_desktop = False

    class Backend:
        def __init__(self):
            self.scripts = []
            self.calls = []

        async def complete(self, system, messages, on_text, tools, **kw):
            self.calls.append(messages)
            return self.scripts.pop(0)

    be = Backend()
    a = ai.Assistant(ai.AIConfig(api_key="k"), be, usage_file=TMP / "u.json",
                     tools={"launch_app": Needs(), "set_volume": NoNeed()})
    for name in ("launch_app", "set_volume"):
        be.scripts += [ai.Reply([{"type": "tool_use", "id": "t", "name": name, "input": {}}], "tool_use", 1, 1),
                       ai.Reply([{"type": "text", "text": "ok"}], "end_turn", 1, 1)]
        assert a.claim()
        await a.turn("x", lambda s: asyncio.sleep(0))
    results = [m[-1]["content"][0] for m in be.calls[1::2]]
    check("desktop tool -> clean 'no desktop session yet' error; login-screen tool runs",
          results[0]["is_error"] and results[0]["content"] == session.NO_DESKTOP
          and results[1]["content"] == "ran", results)

    rs = pc_tools.load_routines({"r": {"steps": [{"tool": "set_volume", "action": "mute"},
                                                 {"tool": "launch_app", "app": "nonexistent-app-zzz"}]}},
                                pc_tools.registry())
    check("routine with a missing app is still skipped at load", rs == [])
    real = pc_tools.registry()
    routine = pc_tools.Routine("r", "r", [pc_tools.Step(real["launch_app"], {"app": "x"}, False, "Open x")], None)
    try:
        await pc_tools.RunRoutine([routine]).run({"routine": routine})
        msg = ""
    except pc_tools.ToolError as ex:
        msg = str(ex)
    check("routine step needing the desktop fails cleanly", session.NO_DESKTOP in msg, msg)


async def input_and_logging_tests():
    records = []

    class Grab(logging.Handler):
        def emit(self, r):
            records.append(r.getMessage())
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # as with -v
    root.addHandler(Grab())
    logging.getLogger("websockets").setLevel(logging.INFO)  # what main() does

    class Paster:
        def __init__(self):
            self.used = False

        def available(self):
            return session.desktop_ready()

        async def snapshot(self):
            self.used = True
            return {}

        async def paste(self, text, tap):
            self.used = True

        async def restore(self, saved):
            pass

    p = Paster()
    vin = cd.VirtualInput("us", p)
    srv = cd.Server(vin, TOKEN, 400.0)
    async with websockets.serve(srv.handler, "127.0.0.1", PORT):
        ws = await websockets.connect(f"ws://127.0.0.1:{PORT}")
        ch = json.loads(await ws.recv())
        await ws.send(json.dumps({"t": "auth", "hmac": hmac.new(TOKEN.encode(), ch["nonce"].encode(), hashlib.sha256).hexdigest()}))
        await ws.recv()
        vin.ui.events.clear()
        await ws.send(json.dumps({"t": "text", "s": "ab👍" + SECRET}))
        await ws.send(json.dumps({"t": "key", "k": SECRET}))
        await ws.send(json.dumps({"t": "text", "s": None, "junk": SECRET}))
        await ws.send("not json " + SECRET)
        await ws.send(json.dumps({"t": "chat", "id": 1, "text": SECRET}))
        await asyncio.sleep(0.3)
        keys = [c for t, c, v in vin.ui.events if t == e.EV_KEY and v == 1]
        check("login screen: phone typing still works, paste fallback not attempted",
              keys[:2] == [e.KEY_A, e.KEY_B] and not p.used, keys[:4])
        await ws.close()
        await asyncio.sleep(0.1)
    leaked = [m for m in records if SECRET in m or "hunter2" in m]
    check("no typed, key, chat or malformed text in any log record (debug level)", not leaked and len(records) > 3,
          leaked[:3])

    # control: without the pin, the websockets library itself logs frame payloads at debug,
    # which is exactly what main() prevents
    records.clear()
    logging.getLogger("websockets").setLevel(logging.DEBUG)
    async with websockets.serve(srv.handler, "127.0.0.1", PORT + 1):
        ws = await websockets.connect(f"ws://127.0.0.1:{PORT + 1}")
        ch = json.loads(await ws.recv())
        await ws.send(json.dumps({"t": "auth", "hmac": hmac.new(TOKEN.encode(), ch["nonce"].encode(), hashlib.sha256).hexdigest()}))
        await ws.recv()
        await ws.send(json.dumps({"t": "text", "s": SECRET}))
        await asyncio.sleep(0.2)
        await ws.close()
    logging.getLogger("websockets").setLevel(logging.INFO)
    check("control: unpinned websockets debug logging would have leaked it", any(SECRET in m for m in records))


async def main():
    session_tests()
    await gating_tests()
    await input_and_logging_tests()
    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        sys.exit(1)
    print("all tests passed")


asyncio.run(main())
