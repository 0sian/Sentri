"""
Fallback for characters the active keymap can't type (ŵ ŷ, other accents, emoji).

Puts the text on both CLIPBOARD and PRIMARY, then taps Shift+Insert. GUI toolkits
(GTK, Qt, Chromium, Firefox, Electron) paste CLIPBOARD on Shift+Insert and terminals
(foot, kitty, alacritty, ghostty, Konsole) paste PRIMARY, so mostly no per-app
detection is needed. Exception: Hyprland with misc:middle_click_paste = false hides
PRIMARY from apps, so there we look up the focused window and use Ctrl+Shift+V for
terminals. Offered with --sensitive so cliphist/Klipper don't record it. The previous
contents of each selection (one MIME type) are restored when the text is done.
"""
import asyncio
import logging
import os
import json
import shutil

from evdev import ecodes as e

log = logging.getLogger("companion")

PREFERRED_TYPES = ("text/plain;charset=utf-8", "UTF8_STRING", "text/plain")
TERMINAL_CLASSES = {"foot", "footclient", "kitty", "alacritty", "com.mitchellh.ghostty",
                    "org.wezfurlong.wezterm", "org.kde.konsole", "xterm", "org.gnome.terminal",
                    "org.gnome.ptyxis", "com.system76.cosmicterm"}
SHIFT_INSERT = (e.KEY_INSERT, [e.KEY_LEFTSHIFT])
CTRL_SHIFT_V = (e.KEY_V, [e.KEY_LEFTCTRL, e.KEY_LEFTSHIFT])


async def _exec(*cmd, stdin: bytes = None) -> tuple[int, bytes]:
    # wl-copy forks a child that keeps serving the selection; don't hand it our stdout
    # pipe or communicate() would wait for that child too
    capture = cmd[0] != "wl-copy"
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE if capture else asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(stdin), timeout=2)
    except asyncio.TimeoutError:
        proc.kill()
        return -1, b""
    return proc.returncode, out or b""


class ClipboardPaste:
    def __init__(self, settle: float = 0.15):
        # how long to give the focused app to fetch the selection before moving on
        self.settle = settle

    @staticmethod
    def available() -> bool:
        return bool(os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy") and shutil.which("wl-paste"))

    async def snapshot(self):
        """{primary: (mime, data) or None} for both selections."""
        saved = {}
        for primary in (False, True):
            p = ["--primary"] if primary else []
            rc, out = await _exec("wl-paste", *p, "--list-types")
            types = out.decode(errors="replace").split() if rc == 0 else []
            mime = next((t for t in PREFERRED_TYPES if t in types), types[0] if types else None)
            saved[primary] = None
            if mime:
                rc, data = await _exec("wl-paste", *p, "--no-newline", "--type", mime)
                if rc == 0:
                    saved[primary] = (mime, data)
        return saved

    async def paste_key(self):
        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
            rc, out = await _exec("hyprctl", "activewindow", "-j")
            try:
                cls = json.loads(out).get("class", "").lower() if rc == 0 else ""
            except ValueError:
                cls = ""
            if cls in TERMINAL_CLASSES:
                return CTRL_SHIFT_V
        return SHIFT_INSERT

    async def paste(self, text: str, tap):
        """tap(keycode, modifier_keycodes) sends the paste shortcut."""
        for p in ([], ["--primary"]):
            await _exec("wl-copy", *p, "--sensitive", "--type", "text/plain;charset=utf-8",
                        stdin=text.encode())
        tap(*await self.paste_key())
        await asyncio.sleep(self.settle)

    async def restore(self, saved):
        for primary, item in saved.items():
            p = ["--primary"] if primary else []
            if item is None:
                await _exec("wl-copy", *p, "--clear")
            else:
                mime, data = item
                await _exec("wl-copy", *p, "--type", mime, stdin=data)
