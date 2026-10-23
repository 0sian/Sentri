#!/usr/bin/env python3
"""KDE Plasma paths with fakes: KWin window control, launch_app focus-first, and computer-use
screenshot geometry (multi-monitor, fractional scaling). Nothing touches the real desktop."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

import cu
import kwin
import pc_tools as t

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


WIN_A = "{349ed4d3-b431-453f-9c05-c9406490b531}"
WIN_B = "{51c454bc-eaf4-4ae6-a076-d5c7b7e94994}"
bodies = []
state = {"cursor": [2500.0, 300.0], "active": {"id": WIN_A, "cls": "vivaldi-stable", "title": "YouTube"}}


async def fake_eval(body):
    bodies.append(body)
    if "cursorPos" in body:
        return state["cursor"]
    if "windowList().filter" in body:
        return [{"id": WIN_A, "cls": "vivaldi-stable", "title": "YouTube - Vivaldi", "active": True, "desktop": "Desktop 1"},
                {"id": WIN_B, "cls": "steam", "title": "Steam", "active": False, "desktop": "Desktop 1"},
                {"id": "not-a-uuid'); evil(); ('", "cls": "x", "title": "x", "active": False, "desktop": "x"}]
    if "activeWindow; return w ? {" in body:
        return state["active"]
    if "activeWindow; return w ? String" in body:
        return state["active"]["cls"]
    if "closeWindow" in body or "workspace.activeWindow = w" in body:
        return WIN_A in body or WIN_B in body
    raise AssertionError(body)


kwin.evaluate = fake_eval
kwin.available = lambda: True
t._hyprland = lambda: False


async def window_tests():
    wins = await t.all_windows()
    check("KDE window list from KWin; malformed ids dropped", [w["id"] for w in wins] == [WIN_A, WIN_B], wins)
    out = await t.ListWindows().run({})
    check("list_windows shows KWin ids, class, title, desktop, focus",
          f"id {WIN_A}: vivaldi-stable: YouTube - Vivaldi [Desktop 1] (focused)" in out, out)
    fw = t.FocusWindow()
    a = await fw.prepare({"window": WIN_B})
    bodies.clear()
    await fw.run(a)
    check("focus_window on KDE: summary names the app, KWin script carries only the validated id",
          fw.summary(a) == "Switch to steam" and WIN_B in bodies[-1] and "workspace.activeWindow = w" in bodies[-1])
    bad = ["{x'); workspace.windowList().forEach(w => w.closeWindow()); ('}", "0x1; rm -rf", "steam", ""]
    rejected = 0
    for b in bad:
        try:
            fw.validate({"window": b})
        except t.ToolError:
            rejected += 1
    check("ids that aren't a KWin uuid or Hyprland address are refused before any script", rejected == len(bad))
    for f in (kwin.focus, kwin.close):
        try:
            await f("{x'); evil(); ('}")
            ok = False
        except t.ToolError:
            ok = True
        if not ok:
            check("kwin helpers re-check ids themselves", False)
    check("kwin helpers re-check ids themselves", True)
    cw = t.CloseWindow()
    a = await cw.prepare({"window": WIN_B})
    bodies.clear()
    out = await cw.run(a)
    check("close_window on KDE", cw.summary(a) == "Close steam: Steam" and "closeWindow" in bodies[-1] and out == "Closed steam")

    la = t.LaunchApp()
    t.installed_apps = lambda: [t.DesktopApp("vivaldi-stable.desktop", "Vivaldi", "Web Browser", "vivaldi-stable"),
                                t.DesktopApp("firefox.desktop", "Firefox")]
    a = await la.prepare({"app": "vivaldi"})
    bodies.clear()
    out = await la.run(a)
    check("launch_app focus-first on KDE", la.summary(a) == "Switch to Vivaldi (already open)" and a["existing"] == WIN_A
          and "already open" in out and WIN_A in bodies[-1], (la.summary(a), out))
    a = await la.prepare({"app": "firefox"})
    check("not open on KDE -> launch", a["existing"] is None and la.summary(a) == "Open Firefox")
    check("type_text focus guard sees the KDE focused window", await t._focused() == (WIN_A, "vivaldi-stable"))


async def geometry_tests():
    kde = cu.KDEDesktop(None, None)
    tmp = Path(tempfile.mkdtemp())
    t.desktop_env = lambda: {"XDG_RUNTIME_DIR": str(tmp), "WAYLAND_DISPLAY": "w"}
    image = {"size": (2560, 1440)}
    calls = []

    async def capture(env, d, pointer=False):
        calls.append(("spectacle", pointer))
        p = d / "shot.png"
        p.write_bytes(b"png")
        return p

    async def fake_run(*argv, env=None):
        if argv[:2] == ("magick", "identify"):
            return f"{image['size'][0]} {image['size'][1]}"
        raise AssertionError(argv)

    async def fake_bytes(*argv, env=None, **kw):
        calls.append(argv)
        Path(argv[-1]).write_bytes(b"\xff\xd8jpg")
        return b""
    t.spectacle_capture, t.run, t.run_bytes = capture, fake_run, fake_bytes

    async def monitors():
        return state["mons"]
    kwin.monitors = monitors

    # one 2560x1440 monitor at scale 1
    state["mons"] = [{"name": "DP-3", "x": 0.0, "y": 0.0, "w": 2560.0, "h": 1440.0}]
    state["cursor"] = [100.0, 100.0]
    data, g = await kde.screenshot()
    check("KDE single monitor: 2560x1440 -> 1280x720 shot, pointer included, centre maps to centre",
          g.shot_size == (1280, 720) and g.to_layout(640, 360) == (1280.0, 720.0) and calls[0] == ("spectacle", True)
          and "1280x720!" in calls[1], (g.shot_size, g.to_layout(640, 360), calls[:2]))

    # two monitors: 1920x1080 at 0,0 and a 2560x1440 panel at 1.5x scaling to its right (logical 1706.67x960)
    state["mons"] = [{"name": "HDMI-1", "x": 0.0, "y": 0.0, "w": 1920.0, "h": 1080.0},
                     {"name": "DP-3", "x": 1920.0, "y": 0.0, "w": 2560 / 1.5, "h": 960.0}]
    state["cursor"] = [2500.0, 300.0]  # pointer on the scaled monitor: that's what Spectacle -m captures
    for label, size in (("physical pixels", (2560, 1440)), ("logical pixels", (1707, 960))):
        image["size"] = size
        _, g = await kde.screenshot()
        lx, ly = g.to_layout(640, 360)
        check(f"KDE multi-monitor 1.5x, Spectacle rendering {label}: shot centre -> that monitor's centre",
              abs(lx - (1920 + 2560 / 1.5 / 2)) < 1.5 and abs(ly - 480) < 1.5, (lx, ly, g.shot_size))
        cx, cy = g.to_layout(5000, 5000)
        check(f"... and clamped inside it ({label})", cx < 1920 + 2560 / 1.5 and cy < 960 and cx > 1920, (cx, cy))

    image["size"] = (1000, 1000)
    try:
        await kde.screenshot()
        msg = ""
    except t.ToolError as ex:
        msg = str(ex)
    check("capture that matches no monitor's shape is refused", "which monitor" in msg, msg)

    image["size"] = (2560, 1440)
    _, g = await kde.screenshot()
    calls.clear()
    await kde.screenshot([100, 50, 300, 150], g)  # shot px; shot_scale 0.5 -> image px x2
    crop = next(c for c in calls if c[0] == "magick")
    check("zoom crops the right image pixels", "400x200+200+100" in crop, crop)
    check("temp files cleaned up", not any(tmp.iterdir()), list(tmp.iterdir()))


async def guard_tests():
    kde = cu.KDEDesktop(None, None)
    for cls, want in (("plasmashell", "launcher"), ("org.kde.krunner", "launcher"),
                      ("ksmserver-logout-greeter", "power menu"), ("vivaldi-stable", None)):
        state["active"] = {"id": WIN_A, "cls": cls, "title": ""}
        got = await kde.overlay_open()
        if got != want:
            check(f"Plasma overlay guard for {cls}", False, got)
    check("Plasma guards: launcher/KRunner block typing, the logout screen blocks everything", True)
    s = cu.Session(cu.CUConfig(), None, kde, "g", lambda *a: asyncio.sleep(0), lambda: None, lambda *a: None)
    s.geom = cu.Geometry(0, 0, 1.0, 2560, 1440, 0.5)
    state["active"] = {"id": WIN_A, "cls": "plasmashell", "title": ""}
    try:
        await s.act("type", {"text": "konsole"})
        refused = False
    except t.ToolError:
        refused = True
    check("typing into the Plasma launcher is refused in a session", refused)

    router = cu.AutoDesktop(None, None)
    kwin.available = lambda: False
    check("router: unsupported desktop -> not available", not router.available())
    try:
        await router.screenshot()
        msg = ""
    except t.ToolError as ex:
        msg = str(ex)
    check("router: clear 'computer use isn't supported on this desktop yet'",
          msg == "computer use isn't supported on this desktop yet", msg)


async def main():
    await window_tests()
    await geometry_tests()
    await guard_tests()
    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        sys.exit(1)
    print("all tests passed")


asyncio.run(main())
