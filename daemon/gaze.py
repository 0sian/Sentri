"""Cursor position for the notch's eyes. Hyprland only (its IPC socket answers in ~0.1 ms; KWin would
need a script load per sample, so KDE keeps the idle glances). Nothing is sent unless the cursor
moved, and the poll slows right down once it has been still for a few seconds."""
import asyncio
import json
import logging
import os
from pathlib import Path

import pc_tools

log = logging.getLogger("companion.gaze")

FAST, SLOW, STILL_AFTER = 0.04, 0.25, 5.0   # seconds between polls (moving / still), and the still threshold


def _ipc_path():
    env = pc_tools.desktop_env()
    sig = env.get("HYPRLAND_INSTANCE_SIGNATURE")
    rt = env.get("XDG_RUNTIME_DIR") or os.environ.get("XDG_RUNTIME_DIR")
    return Path(rt) / "hypr" / sig / ".socket.sock" if sig and rt else None


async def hypr_cursor():
    """(x, y) in layout px, or None if there is no Hyprland to ask."""
    path = _ipc_path()
    if path is None:
        return None
    try:
        r, w = await asyncio.wait_for(asyncio.open_unix_connection(str(path)), 1.0)
        try:
            w.write(b"j/cursorpos")
            await w.drain()
            d = json.loads(await asyncio.wait_for(r.read(), 1.0))
        finally:
            w.close()
        return int(d["x"]), int(d["y"])
    except (OSError, asyncio.TimeoutError, ValueError, KeyError, TypeError):
        return None


async def watch(send, alive, source=hypr_cursor):
    """Run until cancelled. send({"cmd":"cursor",...}) delivers to the overlay; alive() says whether
    the overlay is up (the loop idles while it isn't, and never starts it)."""
    last, still_since = None, 0.0
    loop = asyncio.get_running_loop()
    while True:
        if not alive():
            last = None
            await asyncio.sleep(1.0)
            continue
        pos = await source()
        now = loop.time()
        if pos is None:
            await asyncio.sleep(2.0)
            continue
        if pos != last:
            last, still_since = pos, now
            try:
                await send({"cmd": "cursor", "x": pos[0], "y": pos[1]})
            except Exception:
                log.debug("cursor not delivered")
        await asyncio.sleep(SLOW if now - still_since > STILL_AFTER else FAST)
