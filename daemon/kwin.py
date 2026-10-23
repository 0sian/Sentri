"""
Talking to KWin (KDE Plasma's compositor) through its scripting interface, the same way kdotool
does, but with nothing extra installed: write a tiny script, load and run it over D-Bus, read
its print() output back from the user journal by a one-off tag, unload it.

Every value interpolated into a script is either produced here or a window id that has been
checked against WINDOW_ID first, so nothing the model says can become KWin script code.
"""
import asyncio
import json
import os
import re
import secrets
import tempfile
from pathlib import Path

import pc_tools
from pc_tools import ToolError, clean

WINDOW_ID = re.compile(r"^\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}$")
POLL = 0.05
TIMEOUT = 3.0


def available() -> bool:
    import shutil
    import session
    return "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper() and bool(shutil.which("qdbus6")) \
        and session.desktop_ready()


async def evaluate(body: str):
    """Run `body` (a JS function body that returns something JSON-able) inside KWin."""
    env = pc_tools.desktop_env()
    tag = "COMPANION_KWIN_" + secrets.token_hex(6)
    name = tag.lower()
    tmp = Path(tempfile.mkdtemp(prefix="companion-kwin-", dir=env.get("XDG_RUNTIME_DIR")))
    script = tmp / "s.js"
    script.write_text(f'print("{tag} " + JSON.stringify((function() {{ {body} }})()));\n')
    try:
        sid = (await pc_tools.run("qdbus6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.loadScript",
                                  str(script), name, env=env)).strip()
        if not sid.lstrip("-").isdigit() or int(sid) < 0:
            raise ToolError("KWin wouldn't load the helper script")
        await pc_tools.run("qdbus6", "org.kde.KWin", f"/Scripting/Script{sid}", "org.kde.kwin.Script.run", env=env)
        for _ in range(int(TIMEOUT / POLL)):
            await asyncio.sleep(POLL)
            out = await pc_tools.run("journalctl", "--user", "--since", "-15s", "--no-pager", "-o", "cat",
                                     "--grep", tag, env=env)
            for line in out.splitlines():
                if line.startswith(tag + " "):
                    return json.loads(line[len(tag) + 1:])
        raise ToolError("KWin didn't answer")
    except ValueError:
        raise ToolError("KWin returned something unexpected")
    finally:
        try:
            await pc_tools.run("qdbus6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript",
                               name, env=env)
        except ToolError:
            pass
        script.unlink(missing_ok=True)
        tmp.rmdir()


async def cursor():
    x, y = await evaluate("return [workspace.cursorPos.x, workspace.cursorPos.y];")
    return float(x), float(y)


async def active_class() -> str:
    return str(await evaluate("var w = workspace.activeWindow; return w ? String(w.resourceClass) : '';")).lower()


async def windows() -> list:
    """Normal windows: [{id, cls, title, active, desktop}]. Titles are untrusted."""
    rows = await evaluate(
        "return workspace.windowList().filter(function(w) { return w.normalWindow && !w.skipTaskbar; })"
        ".map(function(w) { return {id: String(w.internalId), cls: String(w.resourceClass), "
        "title: String(w.caption), active: w === workspace.activeWindow, "
        "desktop: w.desktops.length ? String(w.desktops[0].name) : 'all'}; });")
    return [r for r in rows if isinstance(r, dict) and WINDOW_ID.match(str(r.get("id", "")))]


def _check(window_id: str):
    if not WINDOW_ID.match(window_id):
        raise ToolError("not a window id")


async def focus(window_id: str):
    _check(window_id)
    ok = await evaluate(
        f"var w = workspace.windowList().find(function(w) {{ return String(w.internalId) === '{window_id}'; }});"
        " if (!w) return false; w.minimized = false; workspace.activeWindow = w; return true;")
    if ok is not True:
        raise ToolError("that window doesn't exist any more")


async def close(window_id: str):
    _check(window_id)
    ok = await evaluate(
        f"var w = workspace.windowList().find(function(w) {{ return String(w.internalId) === '{window_id}'; }});"
        " if (!w) return false; w.closeWindow(); return true;")
    if ok is not True:
        raise ToolError("that window doesn't exist any more")


async def monitors() -> list:
    """Enabled outputs in layout (logical) coordinates: [{name, x, y, w, h}]."""
    try:
        data = json.loads(await pc_tools.run("kscreen-doctor", "-j", env=pc_tools.desktop_env()))
    except ValueError:
        raise ToolError("kscreen-doctor returned something unexpected")
    out = []
    for o in data.get("outputs", []):
        if not o.get("enabled"):
            continue
        scale = float(o.get("scale") or 1.0)
        w, h = o["size"]["width"], o["size"]["height"]
        if o.get("rotation") in (2, 8):  # left / right: portrait
            w, h = h, w
        out.append({"name": clean(o.get("name", "?"), 20), "x": float(o["pos"]["x"]), "y": float(o["pos"]["y"]),
                    "w": w / scale, "h": h / scale})
    return out


async def active() -> dict:
    """The focused window: {id, cls, title}, or {} when nothing is focused."""
    w = await evaluate("var w = workspace.activeWindow; return w ? {id: String(w.internalId), "
                       "cls: String(w.resourceClass), title: String(w.caption)} : {};")
    return w if isinstance(w, dict) else {}
