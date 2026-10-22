#!/usr/bin/env python3
"""
Companion daemon: lets your phone act as a trackpad + keyboard for this PC.

Works on KDE Plasma (Wayland/X11) and Hyprland because it injects events at the
kernel level through /dev/uinput, below any compositor.

Auth: challenge-response. The server sends a random nonce, the client answers with
HMAC-SHA256(token, nonce). The token itself never crosses the wire.

Run:  ./companion_daemon.py            (see README for the uinput permission setup)
"""
import argparse
import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import socket
import sys
from pathlib import Path

import websockets
from evdev import UInput, ecodes as e

import ai
import keymap
import memory
from clipboard import ClipboardPaste

log = logging.getLogger("companion")

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "companion"
TOKEN_FILE = CONFIG_DIR / "token"
DEFAULT_PORT = 8765
DEVICE_NAME = "companion-virtual-input"
QUEUE_LIMIT = 1000  # pending input messages per connection before new ones are dropped
CHAT_TYPES = {"chat", "chat_cancel", "chat_reset", "confirm"}
MAX_PASTE_RUNS = 3  # a text message needing more separate pastes than this is pasted whole

LETTERS = {c: getattr(e, f"KEY_{c.upper()}") for c in "abcdefghijklmnopqrstuvwxyz"}
DIGITS = {str(i): getattr(e, f"KEY_{i}") for i in range(10)}


NAMED_KEYS = {
    "enter": e.KEY_ENTER, "backspace": e.KEY_BACKSPACE, "tab": e.KEY_TAB,
    "esc": e.KEY_ESC, "space": e.KEY_SPACE, "delete": e.KEY_DELETE,
    "up": e.KEY_UP, "down": e.KEY_DOWN, "left": e.KEY_LEFT, "right": e.KEY_RIGHT,
    "home": e.KEY_HOME, "end": e.KEY_END, "pageup": e.KEY_PAGEUP, "pagedown": e.KEY_PAGEDOWN,
    "insert": e.KEY_INSERT, "menu": e.KEY_MENU, "print": e.KEY_SYSRQ,
    # bare modifier taps (e.g. Super alone opens the launcher on KDE)
    "super": e.KEY_LEFTMETA, "alt": e.KEY_LEFTALT, "ctrl": e.KEY_LEFTCTRL, "shift": e.KEY_LEFTSHIFT,
    "f1": e.KEY_F1, "f2": e.KEY_F2, "f3": e.KEY_F3, "f4": e.KEY_F4, "f5": e.KEY_F5,
    "f6": e.KEY_F6, "f7": e.KEY_F7, "f8": e.KEY_F8, "f9": e.KEY_F9, "f10": e.KEY_F10,
    "f11": e.KEY_F11, "f12": e.KEY_F12,
    # media
    "volup": e.KEY_VOLUMEUP, "voldown": e.KEY_VOLUMEDOWN, "mute": e.KEY_MUTE,
    "playpause": e.KEY_PLAYPAUSE, "next": e.KEY_NEXTSONG, "prev": e.KEY_PREVIOUSSONG,
    "brightup": e.KEY_BRIGHTNESSUP, "brightdown": e.KEY_BRIGHTNESSDOWN,
}
# single letters/digits are also valid "key" names, handled in resolve_key()

MODIFIERS = {
    "ctrl": e.KEY_LEFTCTRL, "alt": e.KEY_LEFTALT, "shift": e.KEY_LEFTSHIFT,
    "super": e.KEY_LEFTMETA, "altgr": e.KEY_RIGHTALT,
}

BUTTONS = {"left": e.BTN_LEFT, "right": e.BTN_RIGHT, "middle": e.BTN_MIDDLE}


def resolve_key(name: str):
    name = name.lower()
    if name in NAMED_KEYS:
        return NAMED_KEYS[name]
    if len(name) == 1 and name in LETTERS:
        return LETTERS[name]
    if len(name) == 1 and name in DIGITS:
        return DIGITS[name]
    return None


class VirtualInput:
    """One virtual device that is both a mouse and a keyboard."""

    def __init__(self, layout: str = "auto", paster: ClipboardPaste = None):
        """layout: "auto" follows the compositor's keymap (re-read on every connect),
        anything else is an XKB layout name ("uk" is accepted for "gb")."""
        self.auto_layout = layout == "auto"
        self.charmap = {}
        self.paster = paster
        keys = set(NAMED_KEYS.values()) | set(MODIFIERS.values()) | set(BUTTONS.values())
        keys |= set(LETTERS.values()) | set(DIGITS.values()) | set(keymap.CANDIDATE_KEYS)
        caps = {
            e.EV_KEY: sorted(keys),
            e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_HWHEEL,
                       e.REL_WHEEL_HI_RES, e.REL_HWHEEL_HI_RES],
        }
        self.ui = UInput(caps, name=DEVICE_NAME, vendor=0x1234, product=0x5678)
        self._rx = 0.0
        self._ry = 0.0
        self._wheel_acc = 0.0
        self._hwheel_acc = 0.0
        self._wheel_lo = 0  # hi-res units not yet reported as a legacy notch
        self._hwheel_lo = 0
        self._held_buttons = set()
        self._held_mods = set()
        if not self.auto_layout:
            self._load_keymap(keymap.static(layout), 0, "--layout")
        else:
            self.refresh_keymap()

    def _load_keymap(self, rmlvo: dict, group: int, source: str):
        try:
            self.charmap = keymap.build_charmap(rmlvo, group)
            log.info("keymap from %s: %s (group %d), %d chars", source,
                     rmlvo.get("layout"), group, len(self.charmap))
        except (OSError, ValueError) as ex:
            log.error("keymap %s unusable (%s), falling back to us", rmlvo, ex)
            self.charmap = keymap.build_charmap({"layout": "us"})

    def refresh_keymap(self):
        """Re-detect the layout. Called per connection so a KDE <-> Hyprland switch or a
        layout change is picked up without restarting the daemon."""
        if self.auto_layout:
            self._load_keymap(*keymap.detect(DEVICE_NAME))

    # -- pointer -----------------------------------------------------------
    def move(self, dx: float, dy: float):
        # carry fractional remainders so slow movement isn't lost to rounding
        self._rx += dx
        self._ry += dy
        ix, iy = int(self._rx), int(self._ry)
        self._rx -= ix
        self._ry -= iy
        if ix:
            self.ui.write(e.EV_REL, e.REL_X, ix)
        if iy:
            self.ui.write(e.EV_REL, e.REL_Y, iy)
        if ix or iy:
            self.ui.syn()

    def scroll(self, dx: float, dy: float):
        """dx/dy in wheel 'notches' (1.0 == one click), kernel sign convention:
        dy > 0 = wheel up (view scrolls up), dx > 0 = scroll right.
        The client decides natural vs traditional direction before sending."""
        self._wheel_acc += dy
        self._hwheel_acc += dx
        wrote = False
        for acc_name, lo_name, hi, lo in (("_wheel_acc", "_wheel_lo", e.REL_WHEEL_HI_RES, e.REL_WHEEL),
                                          ("_hwheel_acc", "_hwheel_lo", e.REL_HWHEEL_HI_RES, e.REL_HWHEEL)):
            acc = getattr(self, acc_name)
            hi_units = int(acc * 120)
            if hi_units:
                self.ui.write(e.EV_REL, hi, hi_units)
                setattr(self, acc_name, acc - hi_units / 120.0)
                # legacy low-res event each time the running hi-res total crosses a full
                # notch, like the kernel's HID driver. libinput ignores it when hi-res
                # exists (verified on Hyprland: no double scroll), but other readers need it.
                lo_acc = getattr(self, lo_name) + hi_units
                notches = int(lo_acc / 120)
                if notches:
                    self.ui.write(e.EV_REL, lo, notches)
                setattr(self, lo_name, lo_acc - notches * 120)
                wrote = True
        if wrote:
            self.ui.syn()

    def button(self, name: str, state: str):
        code = BUTTONS.get(name)
        if code is None:
            return
        if state == "down":
            self._held_buttons.add(code)
            self.ui.write(e.EV_KEY, code, 1)
            self.ui.syn()
        elif state == "up":
            self._held_buttons.discard(code)
            self.ui.write(e.EV_KEY, code, 0)
            self.ui.syn()
        elif state == "click":
            self.ui.write(e.EV_KEY, code, 1)
            self.ui.syn()
            self.ui.write(e.EV_KEY, code, 0)
            self.ui.syn()

    # -- keyboard ----------------------------------------------------------
    def _tap(self, code: int, extra_mods=()):
        for m in extra_mods:
            self.ui.write(e.EV_KEY, m, 1)
        self.ui.write(e.EV_KEY, code, 1)
        self.ui.syn()
        self.ui.write(e.EV_KEY, code, 0)
        for m in reversed(extra_mods):
            self.ui.write(e.EV_KEY, m, 0)
        self.ui.syn()

    def key(self, name: str, mods=()):
        code = resolve_key(name)
        if code is None:
            log.warning("unknown key %r", name)
            return
        mod_codes = [MODIFIERS[m] for m in mods if m in MODIFIERS]
        self._tap(code, mod_codes)

    async def text(self, s: str):
        """Type s. Characters the keymap can't produce are pasted via the clipboard if a
        paster is set (each run in one go; if that would take more than MAX_PASTE_RUNS
        pastes, everything from the first one onwards in one go), otherwise skipped."""
        saved = None
        # each paste costs ~the paster's settle time, so bound how many one message can do
        runs = sum(1 for k, ch in enumerate(s)
                   if ch not in self.charmap and (k == 0 or s[k - 1] in self.charmap))
        paste_whole = runs > MAX_PASTE_RUNS
        try:
            i = 0
            while i < len(s):
                spec = self.charmap.get(s[i])
                if spec is not None:
                    code, shift, altgr = spec
                    mods = []
                    if shift:
                        mods.append(e.KEY_LEFTSHIFT)
                    if altgr:
                        mods.append(e.KEY_RIGHTALT)
                    self._tap(code, mods)
                    i += 1
                    continue
                j = i
                while j < len(s) and s[j] not in self.charmap:
                    j += 1
                if self.paster is not None and paste_whole:
                    j = len(s)
                if self.paster is None:
                    log.debug("no keymap for %r, skipped", s[i:j])
                else:
                    if saved is None:
                        saved = await self.paster.snapshot()
                    await self.paster.paste(s[i:j], self._tap)
                i = j
        finally:
            if saved is not None:
                await self.paster.restore(saved)

    def release_all(self):
        """Never leave a button or modifier stuck if a client disconnects mid-gesture."""
        for b in list(self._held_buttons):
            self.ui.write(e.EV_KEY, b, 0)
        self._held_buttons.clear()
        for m in MODIFIERS.values():
            self.ui.write(e.EV_KEY, m, 0)
        self.ui.syn()

    def close(self):
        self.release_all()
        self.ui.close()


def load_or_create_token() -> str:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    token = secrets.token_urlsafe(24)
    TOKEN_FILE.write_text(token + "\n")
    TOKEN_FILE.chmod(0o600)
    return token


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class ToolInput:
    """Keyboard access for the AI's type_text / press_keys tools. Shares the input lock with
    the phone's input worker, so tool typing never interleaves with a phone message."""

    def __init__(self, vin: VirtualInput, lock: asyncio.Lock):
        self.vin = vin
        self.lock = lock

    def valid_key(self, name: str) -> bool:
        return resolve_key(name) is not None

    async def type(self, s: str):
        async with self.lock:
            await self.vin.text(s)

    async def keys(self, key: str, mods):
        async with self.lock:
            self.vin.key(key, mods)


class Server:
    def __init__(self, vin: VirtualInput, token: str, max_step: float, assistant: ai.Assistant = None,
                 input_lock: asyncio.Lock = None):
        self.vin = vin
        self.input_lock = input_lock or asyncio.Lock()
        self.token = token.encode()
        self.max_step = max_step
        self.assistant = assistant  # None when no API key is configured
        self.active = None  # only one controlling client at a time

    async def handler(self, ws):
        peer = ws.remote_address
        nonce = secrets.token_hex(16)
        try:
            await ws.send(json.dumps({"t": "challenge", "nonce": nonce}))
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            msg = json.loads(raw)
            expected = hmac.new(self.token, nonce.encode(), hashlib.sha256).hexdigest()
            if msg.get("t") != "auth" or not hmac.compare_digest(str(msg.get("hmac", "")), expected):
                await ws.send(json.dumps({"t": "denied"}))
                log.warning("auth failed from %s", peer)
                return
        except (asyncio.TimeoutError, json.JSONDecodeError, websockets.ConnectionClosed):
            return

        # newest client wins; kick the old one so a dropped connection never blocks you
        if self.active is not None and self.active is not ws:
            try:
                await self.active.close(code=4000, reason="replaced")
            except Exception:
                pass
        self.active = ws
        await asyncio.to_thread(self.vin.refresh_keymap)
        ok = {"t": "ok", "host": socket.gethostname()}
        if self.assistant:
            ok.update(caps=["chat"], model=self.assistant.cfg.model)
        await ws.send(json.dumps(ok))
        log.info("client connected: %s", peer)

        async def send(msg: dict):
            try:
                await ws.send(json.dumps(msg))
            except websockets.ConnectionClosed:
                pass

        chat = ai.ChatSession(self.assistant, send) if self.assistant else None

        # Input is applied in order by a worker so a paste (which awaits the clipboard)
        # never holds up reading the socket; pings are answered straight from the read loop.
        queue = asyncio.Queue(maxsize=QUEUE_LIMIT)
        worker = asyncio.create_task(self._apply_input(queue))
        try:
            async for raw in ws:
                try:
                    m = json.loads(raw)
                    if m["t"] == "ping":
                        if isinstance(m.get("id"), int) and not isinstance(m["id"], bool):
                            await ws.send(json.dumps({"t": "pong", "id": m["id"]}))
                    elif m["t"] in CHAT_TYPES:
                        # chat runs in its own task; handle() only starts or cancels it
                        if chat:
                            await chat.handle(m)
                        elif m["t"] == "chat":
                            await send({"t": "chat_error", "id": m.get("id"), "msg": "AI isn't set up on this PC"})
                    else:
                        queue.put_nowait(m)
                except asyncio.QueueFull:
                    log.warning("input queue full, dropping %r", raw[:80])
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as ex:
                    log.debug("bad message %r: %s", raw, ex)
        except websockets.ConnectionClosed:
            pass
        finally:
            if chat:
                await chat.cancel()
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
            self.vin.release_all()
            if self.active is ws:
                self.active = None
            log.info("client disconnected: %s", peer)

    async def _apply_input(self, queue: asyncio.Queue):
        while True:
            m = await queue.get()
            try:
                async with self.input_lock:
                    await self.dispatch(m)
            except (KeyError, TypeError, ValueError) as ex:
                log.debug("bad message %r: %s", m, ex)

    def _clamp(self, v: float) -> float:
        return max(-self.max_step, min(self.max_step, float(v)))

    async def dispatch(self, m: dict):
        t = m["t"]
        if t == "mv":
            self.vin.move(self._clamp(m["dx"]), self._clamp(m["dy"]))
        elif t == "sc":
            self.vin.scroll(self._clamp(m.get("dx", 0)) , self._clamp(m.get("dy", 0)))
        elif t == "btn":
            self.vin.button(m["b"], m["s"])
        elif t == "text":
            await self.vin.text(str(m["s"])[:2000])
        elif t == "key":
            self.vin.key(m["k"], m.get("mods", ()))


async def amain(args):
    token = load_or_create_token()
    paster = None
    if not args.no_clipboard:
        if ClipboardPaste.available():
            paster = ClipboardPaste()
        else:
            log.warning("wl-copy/wl-paste or WAYLAND_DISPLAY missing: untypeable characters will be skipped")
    vin = VirtualInput(args.layout, paster)
    cfg = ai.load_config()
    input_lock = asyncio.Lock()
    assistant = ai.Assistant(cfg, injector=ToolInput(vin, input_lock), store=memory.MemoryStore()) if cfg else None
    log.info("AI chat %s", f"enabled ({cfg.model}, effort {cfg.effort})" if cfg else
             f"off (no api_key in {ai.AI_CONFIG} or ANTHROPIC_API_KEY)")
    srv = Server(vin, token, args.max_step, assistant, input_lock)
    ip = lan_ip()
    print(f"\nCompanion daemon listening on ws://{args.host}:{args.port}  (layout: {args.layout})")
    print(f"  LAN address : {ip}:{args.port}")
    print(f"  Token       : {token}")
    print(f"  Token file  : {TOKEN_FILE}\n")
    try:
        async with websockets.serve(srv.handler, args.host, args.port,
                                    ping_interval=15, ping_timeout=10, max_size=64 * 1024):
            await asyncio.Future()
    finally:
        vin.close()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="0.0.0.0", help="bind address (default 0.0.0.0)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--layout", default="auto",
                   help="XKB layout used to type text from the phone: 'auto' (default) follows the "
                        "compositor, or name one, e.g. gb/uk, us, custom")
    p.add_argument("--no-clipboard", action="store_true",
                   help="skip characters the layout can't type instead of pasting them via the clipboard")
    p.add_argument("--max-step", type=float, default=400.0,
                   help="clamp on a single movement/scroll message (safety)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(amain(args))
    except PermissionError:
        sys.exit("Cannot open /dev/uinput. See README: add a udev rule and join the 'input' group.")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
