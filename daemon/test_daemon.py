#!/usr/bin/env python3
"""Protocol + event-mapping tests. Uses a recording fake in place of /dev/uinput."""
import asyncio
import hashlib
import hmac
import json
import sys

import websockets
from evdev import ecodes as e

import companion_daemon as cd


class FakeUInput:
    def __init__(self, *a, **k):
        self.events = []  # (type, code, value)
        self.syns = 0

    def write(self, t, c, v):
        self.events.append((t, c, v))

    def syn(self):
        self.syns += 1

    def close(self):
        pass


cd.UInput = FakeUInput  # monkeypatch before VirtualInput is built


class FakePaster:
    """Records what would be pasted instead of touching the real clipboard."""
    def __init__(self):
        self.log = []

    async def snapshot(self):
        self.log.append("snapshot")
        return {"saved": True}

    async def paste(self, text, tap):
        self.log.append(("paste", text))
        tap(e.KEY_INSERT, [e.KEY_LEFTSHIFT])

    async def restore(self, saved):
        self.log.append(("restore", saved))

TOKEN = "test-token"
PORT = 18765
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


async def connect_authed(token=TOKEN):
    ws = await websockets.connect(f"ws://127.0.0.1:{PORT}")
    ch = json.loads(await ws.recv())
    mac = hmac.new(token.encode(), ch["nonce"].encode(), hashlib.sha256).hexdigest()
    await ws.send(json.dumps({"t": "auth", "hmac": mac}))
    return ws, json.loads(await ws.recv())


async def main():
    vin = cd.VirtualInput("uk")
    srv = cd.Server(vin, TOKEN, 400.0)
    async with websockets.serve(srv.handler, "127.0.0.1", PORT):
        # --- auth ---
        ws, reply = await connect_authed("wrong")
        check("bad token is denied", reply.get("t") == "denied", reply)
        await ws.close()

        ws, reply = await connect_authed()
        check("good token accepted", reply.get("t") == "ok", reply)

        # --- pointer ---
        vin.ui.events.clear()
        await ws.send(json.dumps({"t": "mv", "dx": 5.4, "dy": -3.2}))
        await asyncio.sleep(0.05)
        check("move emits REL_X/REL_Y", (e.EV_REL, e.REL_X, 5) in vin.ui.events and (e.EV_REL, e.REL_Y, -3) in vin.ui.events, vin.ui.events)

        vin.ui.events.clear()
        for _ in range(4):
            await ws.send(json.dumps({"t": "mv", "dx": 0.3, "dy": 0}))
        await asyncio.sleep(0.05)
        total = sum(v for t, c, v in vin.ui.events if c == e.REL_X)
        check("fractional movement accumulates (4x0.3 -> 1px)", total == 1, total)

        vin.ui.events.clear()
        await ws.send(json.dumps({"t": "mv", "dx": 99999, "dy": 0}))
        await asyncio.sleep(0.05)
        check("oversized move is clamped", (e.EV_REL, e.REL_X, 400) in vin.ui.events, vin.ui.events)

        # --- buttons ---
        vin.ui.events.clear()
        await ws.send(json.dumps({"t": "btn", "b": "left", "s": "click"}))
        await asyncio.sleep(0.05)
        check("left click = down then up",
              vin.ui.events == [(e.EV_KEY, e.BTN_LEFT, 1), (e.EV_KEY, e.BTN_LEFT, 0)], vin.ui.events)

        # --- scroll ---
        vin.ui.events.clear()
        await ws.send(json.dumps({"t": "sc", "dx": 0, "dy": 1.0}))
        await asyncio.sleep(0.05)
        check("one notch scroll emits hi-res 120 + legacy 1",
              (e.EV_REL, e.REL_WHEEL_HI_RES, 120) in vin.ui.events and (e.EV_REL, e.REL_WHEEL, 1) in vin.ui.events, vin.ui.events)

        vin.ui.events.clear()
        for _ in range(4):
            await ws.send(json.dumps({"t": "sc", "dx": 0, "dy": -0.25}))
        await asyncio.sleep(0.05)
        hi = sum(v for t, c, v in vin.ui.events if c == e.REL_WHEEL_HI_RES)
        lo = [v for t, c, v in vin.ui.events if c == e.REL_WHEEL]
        check("4 quarter notches -> hi-res -120 total + exactly one legacy -1", hi == -120 and lo == [-1], vin.ui.events)

        # --- text on UK layout ---
        vin.ui.events.clear()
        await ws.send(json.dumps({"t": "text", "s": 'A@"£#'}))
        await asyncio.sleep(0.05)
        keys_down = [(c) for t, c, v in vin.ui.events if t == e.EV_KEY and v == 1]
        expect = [e.KEY_LEFTSHIFT, e.KEY_A,           # A
                  e.KEY_LEFTSHIFT, e.KEY_APOSTROPHE,  # @ (UK: shift+')
                  e.KEY_LEFTSHIFT, e.KEY_2,           # " (UK: shift+2)
                  e.KEY_LEFTSHIFT, e.KEY_3,           # £ (UK: shift+3)
                  e.KEY_BACKSLASH]                    # # (UK: key left of Enter)
        check("UK layout maps A @ \" £ #", keys_down == expect, keys_down)

        # --- named key with modifiers ---
        vin.ui.events.clear()
        await ws.send(json.dumps({"t": "key", "k": "c", "mods": ["ctrl"]}))
        await asyncio.sleep(0.05)
        check("ctrl+c",
              [(c, v) for t, c, v in vin.ui.events if t == e.EV_KEY][:3] ==
              [(e.KEY_LEFTCTRL, 1), (e.KEY_C, 1), (e.KEY_C, 0)], vin.ui.events)

        vin.ui.events.clear()
        await ws.send(json.dumps({"t": "key", "k": "q", "mods": ["super"]}))
        await asyncio.sleep(0.05)
        check("super+q (Hyprland-style bind)", (e.EV_KEY, e.KEY_LEFTMETA, 1) in vin.ui.events and (e.EV_KEY, e.KEY_Q, 1) in vin.ui.events, vin.ui.events)

        vin.ui.events.clear()
        await ws.send(json.dumps({"t": "key", "k": "playpause"}))
        await asyncio.sleep(0.05)
        check("media key", (e.EV_KEY, e.KEY_PLAYPAUSE, 1) in vin.ui.events, vin.ui.events)

        # --- garbage doesn't kill the connection ---
        await ws.send("not json")
        await ws.send(json.dumps({"t": "mv"}))  # missing fields
        vin.ui.events.clear()
        await ws.send(json.dumps({"t": "mv", "dx": 2, "dy": 0}))
        await asyncio.sleep(0.05)
        check("survives malformed messages", (e.EV_REL, e.REL_X, 2) in vin.ui.events)

        # --- held button released on disconnect ---
        await ws.send(json.dumps({"t": "btn", "b": "left", "s": "down"}))
        await asyncio.sleep(0.05)
        vin.ui.events.clear()
        await ws.close()
        await asyncio.sleep(0.1)
        check("held button released on disconnect", (e.EV_KEY, e.BTN_LEFT, 0) in vin.ui.events, vin.ui.events)

        # --- newest client replaces old ---
        ws1, _ = await connect_authed()
        ws2, _ = await connect_authed()
        await asyncio.sleep(0.1)
        try:
            await asyncio.wait_for(ws1.recv(), timeout=1)
            replaced = False
        except websockets.ConnectionClosed as ex:
            replaced = True
        except asyncio.TimeoutError:
            replaced = False
        check("second client replaces first", replaced)
        await ws2.close()

    await keymap_tests()
    await queue_tests()

    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        sys.exit(1)
    print("all tests passed")


class SlowPaster(FakePaster):
    async def paste(self, text, tap):
        await super().paste(text, tap)
        await asyncio.sleep(0.5)


async def queue_tests():
    vin = cd.VirtualInput("uk", SlowPaster())
    srv = cd.Server(vin, TOKEN, 400.0)
    async with websockets.serve(srv.handler, "127.0.0.1", PORT + 1):
        ws = await websockets.connect(f"ws://127.0.0.1:{PORT + 1}")
        ch = json.loads(await ws.recv())
        await ws.send(json.dumps({"t": "auth", "hmac": hmac.new(TOKEN.encode(), ch["nonce"].encode(), hashlib.sha256).hexdigest()}))
        await ws.recv()

        await ws.send(json.dumps({"t": "ping", "id": 7}))
        reply = json.loads(await asyncio.wait_for(ws.recv(), 1))
        check("ping with id gets pong with same id", reply == {"t": "pong", "id": 7}, reply)

        await ws.send(json.dumps({"t": "ping"}))
        await ws.send(json.dumps({"t": "ping", "id": "x"}))
        try:
            extra = await asyncio.wait_for(ws.recv(), 0.2)
        except asyncio.TimeoutError:
            extra = None
        check("ping without (int) id: no reply", extra is None, extra)

        vin.ui.events.clear()
        await ws.send(json.dumps({"t": "text", "s": "ŵ"}))  # paste takes 0.5 s
        await ws.send(json.dumps({"t": "mv", "dx": 3, "dy": 0}))
        await ws.send(json.dumps({"t": "ping", "id": 8}))
        t0 = asyncio.get_running_loop().time()
        reply = json.loads(await asyncio.wait_for(ws.recv(), 1))
        dt = asyncio.get_running_loop().time() - t0
        check("pong not queued behind a slow paste", reply == {"t": "pong", "id": 8} and dt < 0.2, (reply, dt))
        moved_early = (e.EV_REL, e.REL_X, 3) in vin.ui.events
        await asyncio.sleep(0.7)
        check("input after a paste stays in order", not moved_early and (e.EV_REL, e.REL_X, 3) in vin.ui.events,
              vin.ui.events)
        await ws.close()

    fp = FakePaster()
    many = cd.VirtualInput("uk", fp)
    await many.text("aŵbŵcŵdŵe")
    check("more than MAX_PASTE_RUNS runs: rest of message pasted whole",
          [x for x in fp.log if isinstance(x, tuple) and x[0] == "paste"] == [("paste", "ŵbŵcŵdŵe")], fp.log)


def keys_down(vin):
    return [c for t, c, v in vin.ui.events if t == e.EV_KEY and v == 1]


async def keymap_tests():
    us = cd.VirtualInput("us")
    await us.text('@"#\\')
    check("US layout maps @ \" # \\",
          keys_down(us) == [e.KEY_LEFTSHIFT, e.KEY_2, e.KEY_LEFTSHIFT, e.KEY_APOSTROPHE,
                            e.KEY_LEFTSHIFT, e.KEY_3, e.KEY_BACKSLASH], keys_down(us))

    uk = cd.VirtualInput("uk")
    await uk.text("\\|€")
    check("UK layout: \\ | on the ISO key, € on AltGr+4",
          keys_down(uk) == [e.KEY_102ND, e.KEY_LEFTSHIFT, e.KEY_102ND, e.KEY_RIGHTALT, e.KEY_4], keys_down(uk))

    # no paster: untypeable characters are dropped, the rest still typed
    uk.ui.events.clear()
    await uk.text("aŵb")
    check("untypeable chars skipped without a paster", keys_down(uk) == [e.KEY_A, e.KEY_B], keys_down(uk))

    fp = FakePaster()
    cy = cd.VirtualInput("uk", fp)
    await cy.text("aŵŷbô")
    check("untypeable runs pasted with Shift+Insert, in order",
          keys_down(cy) == [e.KEY_A, e.KEY_LEFTSHIFT, e.KEY_INSERT, e.KEY_B, e.KEY_LEFTSHIFT, e.KEY_INSERT],
          keys_down(cy))
    check("clipboard snapshotted once and restored once",
          fp.log == ["snapshot", ("paste", "ŵŷ"), ("paste", "ô"), ("restore", {"saved": True})], fp.log)

    fp.log.clear()
    await cy.text("plain")
    check("clipboard untouched when everything is typeable", fp.log == [], fp.log)

    # auto layout re-detects on refresh (i.e. on every connect)
    detected = [({"layout": "us"}, 0, "test"), ({"layout": "gb"}, 0, "test")]
    real_detect = cd.keymap.detect
    cd.keymap.detect = lambda name: detected.pop(0)
    try:
        auto = cd.VirtualInput("auto")
        at_us = auto.charmap["@"]
        auto.refresh_keymap()
        at_gb = auto.charmap["@"]
    finally:
        cd.keymap.detect = real_detect
    check("auto layout follows re-detection", at_us == (e.KEY_2, True, False) and at_gb == (e.KEY_APOSTROPHE, True, False),
          (at_us, at_gb))


asyncio.run(main())
