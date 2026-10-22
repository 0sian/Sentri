"""
Character -> key mapping built from the keymap the compositor is actually using.

uinput sends physical keycodes; the compositor's XKB keymap decides which character
comes out. Rather than hand-maintaining per-layout tables, we ask libxkbcommon
(present on every Wayland desktop, loaded via ctypes so there's no extra pip
dependency) what each key produces with no modifiers, Shift, AltGr and Shift+AltGr,
and invert that.

Layout detection, in order:
  1. Hyprland: `hyprctl devices -j`, the entry for our own virtual keyboard
  2. KDE: ~/.config/kxkbrc
  3. system default from `localectl` (what KWin uses when kxkbrc doesn't exist)
"""
import configparser
import ctypes
import ctypes.util
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

from evdev import ecodes as e

log = logging.getLogger("companion")

# Main alphanumeric block only. No keypad (terminals in application-keypad mode send
# different sequences for those) and Enter/Tab/Backspace are handled explicitly.
_SKIP = {e.KEY_BACKSPACE, e.KEY_TAB, e.KEY_ENTER, e.KEY_LEFTCTRL, e.KEY_LEFTSHIFT,
         e.KEY_RIGHTSHIFT, e.KEY_KPASTERISK, e.KEY_LEFTALT}
MAIN_KEYS = [k for k in range(e.KEY_1, e.KEY_SPACE + 1) if k not in _SKIP]
# The ISO key between left Shift and Z. Preferred after main-block keys with the
# same modifiers, so US-style layouts don't route '<' through it.
ISO_KEY = e.KEY_102ND
CANDIDATE_KEYS = MAIN_KEYS + [ISO_KEY]

# (shift, altgr) combinations, simplest first
_COMBOS = [(False, False), (True, False), (False, True), (True, True)]
_EVDEV_OFFSET = 8  # xkb keycode = evdev keycode + 8
_KEY_DOWN = 1

ALIASES = {"uk": "gb"}  # the old --layout uk/us flag values


class _RuleNames(ctypes.Structure):
    _fields_ = [(n, ctypes.c_char_p) for n in ("rules", "model", "layout", "variant", "options")]


_lib = None


def _xkb():
    global _lib
    if _lib is None:
        lib = ctypes.CDLL(ctypes.util.find_library("xkbcommon") or "libxkbcommon.so.0")
        lib.xkb_context_new.restype = ctypes.c_void_p
        lib.xkb_context_new.argtypes = [ctypes.c_int]
        lib.xkb_context_unref.argtypes = [ctypes.c_void_p]
        lib.xkb_keymap_new_from_names.restype = ctypes.c_void_p
        lib.xkb_keymap_new_from_names.argtypes = [ctypes.c_void_p, ctypes.POINTER(_RuleNames), ctypes.c_int]
        lib.xkb_keymap_unref.argtypes = [ctypes.c_void_p]
        lib.xkb_state_new.restype = ctypes.c_void_p
        lib.xkb_state_new.argtypes = [ctypes.c_void_p]
        lib.xkb_state_unref.argtypes = [ctypes.c_void_p]
        lib.xkb_state_update_key.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int]
        lib.xkb_state_update_mask.argtypes = [ctypes.c_void_p] + [ctypes.c_uint32] * 6
        lib.xkb_state_key_get_utf32.restype = ctypes.c_uint32
        lib.xkb_state_key_get_utf32.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        _lib = lib
    return _lib


def build_charmap(rmlvo: dict, group: int = 0) -> dict:
    """{char: (evdev keycode, shift, altgr)} for the given XKB rules/model/layout/variant/options.
    Raises ValueError if the keymap doesn't compile."""
    lib = _xkb()
    names = _RuleNames(*((rmlvo.get(f) or "").encode() or None
                         for f in ("rules", "model", "layout", "variant", "options")))
    ctx = lib.xkb_context_new(0)
    keymap = lib.xkb_keymap_new_from_names(ctx, ctypes.byref(names), 0)
    if not keymap:
        lib.xkb_context_unref(ctx)
        raise ValueError(f"xkbcommon could not compile keymap {rmlvo}")
    out = {"\n": (e.KEY_ENTER, False, False), "\t": (e.KEY_TAB, False, False)}
    try:
        for shift, altgr in _COMBOS:
            for keys in (MAIN_KEYS, [ISO_KEY]):
                state = lib.xkb_state_new(keymap)
                if group:
                    lib.xkb_state_update_mask(state, 0, 0, 0, 0, 0, group)
                if shift:
                    lib.xkb_state_update_key(state, e.KEY_LEFTSHIFT + _EVDEV_OFFSET, _KEY_DOWN)
                if altgr:
                    lib.xkb_state_update_key(state, e.KEY_RIGHTALT + _EVDEV_OFFSET, _KEY_DOWN)
                for k in keys:
                    cp = lib.xkb_state_key_get_utf32(state, k + _EVDEV_OFFSET)
                    if cp >= 0x20 and cp != 0x7F:
                        out.setdefault(chr(cp), (k, shift, altgr))
                lib.xkb_state_unref(state)
    finally:
        lib.xkb_keymap_unref(keymap)
        lib.xkb_context_unref(ctx)
    return out


def _run(cmd) -> str:
    if not shutil.which(cmd[0]):
        return ""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _from_hyprland(device_name: str):
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return None
    try:
        keyboards = json.loads(_run(["hyprctl", "devices", "-j"]))["keyboards"]
    except (ValueError, KeyError, TypeError):
        return None
    for kb in keyboards:
        if kb.get("name") == device_name:
            rmlvo = {f: kb.get(f, "") for f in ("rules", "model", "layout", "variant", "options")}
            return rmlvo, int(kb.get("active_layout_index", 0)), "hyprland"
    return None


def _from_kde():
    if "KDE" not in os.environ.get("XDG_CURRENT_DESKTOP", ""):
        return None
    path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kxkbrc"
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    try:
        cp.read(path)
        sec = cp["Layout"]
    except (configparser.Error, KeyError):
        return None
    if sec.get("Use", "false").lower() != "true" or not sec.get("LayoutList"):
        return None
    rmlvo = {"rules": "", "model": sec.get("Model", ""), "layout": sec.get("LayoutList", ""),
             "variant": sec.get("VariantList", ""), "options": sec.get("Options", "")}
    return rmlvo, 0, "kxkbrc"


def _from_localectl():
    fields = {"X11 Layout": "layout", "X11 Model": "model", "X11 Variant": "variant", "X11 Options": "options"}
    rmlvo = {"rules": "", "model": "", "layout": "", "variant": "", "options": ""}
    for line in _run(["localectl", "status"]).splitlines():
        k, _, v = line.strip().partition(":")
        if k in fields:
            rmlvo[fields[k]] = v.strip()
    return (rmlvo, 0, "localectl") if rmlvo["layout"] else None


def detect(device_name: str):
    """(rmlvo dict, active group index, source name) for the session we're running in."""
    for probe in (lambda: _from_hyprland(device_name), _from_kde, _from_localectl):
        found = probe()
        if found:
            return found
    return {"layout": "us"}, 0, "fallback"


def static(layout: str):
    """rmlvo for an explicit --layout value (e.g. uk, us, gb, custom)."""
    return {"layout": ALIASES.get(layout, layout)}
