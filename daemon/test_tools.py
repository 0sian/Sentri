#!/usr/bin/env python3
"""pc_tools tests. run() is replaced by a recorder, so nothing touches the real desktop."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pc_tools as t

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class Recorder:
    """Stands in for pc_tools.run: records argv, answers from a table of prefixes."""

    def __init__(self, answers=None):
        self.argv = []
        self.answers = answers or {}

    async def __call__(self, *argv):
        self.argv.append(list(argv))
        for prefix, out in self.answers.items():
            if " ".join(argv).startswith(prefix):
                if isinstance(out, Exception):
                    raise out
                return out
        return ""


def rejects(tool, args):
    try:
        tool.validate(args)
        return False
    except t.ToolError:
        return True


async def main():
    rec = Recorder({"wpctl get-volume": "Volume: 0.40\n",
                    "playerctl -l": "spotify\nfeishin\n",
                    "playerctl -p spotify status": "Paused\n",
                    "playerctl -p feishin status": "Playing\n",
                    "hyprctl clients": '[{"address":"0xabc","class":"firefox","title":"t","workspace":{"name":"1"}}]',
                    "hyprctl dispatch hl.dsp": "ok"})
    t.run = rec
    os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = "test"

    # --- clean ---
    s = t.clean("a\x1b[2J‮b\nc\tz" + "y" * 300, 50)
    check("clean strips control/format chars and newlines, limits length",
          "\x1b" not in s and "‮" not in s and "\n" not in s and len(s) == 50 and s.endswith("…"), repr(s))

    # --- set_volume ---
    v = t.SetVolume()
    check("set_volume rejects bad input",
          rejects(v, {"action": "set"}) and rejects(v, {"action": "set", "percent": 101})
          and rejects(v, {"action": "set", "percent": True}) and rejects(v, {"action": "set", "percent": "50"})
          and rejects(v, {"action": "louder"}))
    a = v.validate({"action": "set", "percent": 40})
    rec.argv.clear()
    out = await v.run(a)
    check("set_volume set -> wpctl argv, capped at 100%, reads back",
          rec.argv[0] == ["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "0.40"] and out == "Volume is now 40%",
          (rec.argv, out))
    a = v.validate({"action": "down"})
    rec.argv.clear()
    await v.run(a)
    check("set_volume down defaults to 10%", rec.argv[0][-1] == "10%-" and v.summary(a) == "Turn volume down 10%", rec.argv)

    # --- media_control ---
    m = t.MediaControl()
    check("media_control rejects unknown action", rejects(m, {"action": "eject"}))
    rec.argv.clear()
    out = await m.run(m.validate({"action": "next"}))
    check("media_control targets the playing player", ["playerctl", "-p", "feishin", "next"] in rec.argv, rec.argv)

    # --- focus_window ---
    f = t.FocusWindow()
    check("focus_window rejects anything but a hex address",
          rejects(f, {"window": "0xabc'}) os.execute('x"}) and rejects(f, {"window": "firefox"})
          and rejects(f, {"window": 123}))
    a = await f.prepare({"window": "0xabc"})
    check("focus_window summary names the real app", f.summary(a) == "Switch to firefox", f.summary(a))
    rec.argv.clear()
    await f.run(a)
    check("focus_window uses the Lua dispatcher", rec.argv[0] == ["hyprctl", "dispatch", "hl.dsp.focus({window='address:0xabc'})"],
          rec.argv)
    try:
        await f.prepare({"window": "0xdef"})
        gone = False
    except t.ToolError:
        gone = True
    check("focus_window: unknown window -> error before anything runs", gone)
    del os.environ["HYPRLAND_INSTANCE_SIGNATURE"]
    try:
        await t.ListWindows().run({})
        unsupported = False
    except t.ToolError as ex:
        unsupported = "isn't supported" in str(ex)
    check("window tools refuse cleanly off Hyprland", unsupported)

    # --- launch_app: desktop entries ---
    tmp = Path(tempfile.mkdtemp())
    apps = tmp / "share" / "applications"
    apps.mkdir(parents=True)
    entries = {
        "firefox.desktop": "[Desktop Entry]\nType=Application\nName=Firefox\nGenericName=Web Browser\nExec=firefox %u\n",
        "vivaldi.desktop": "[Desktop Entry]\nType=Application\nName=Vivaldi\nGenericName=Web Browser\nExec=vivaldi\n",
        "hidden.desktop": "[Desktop Entry]\nType=Application\nName=Hidden Thing\nExec=x\nNoDisplay=true\n",
        "off.desktop": "[Desktop Entry]\nType=Application\nName=Power Off\nExec=systemctl poweroff\n",
        "root.desktop": "[Desktop Entry]\nType=Application\nName=Root Shell\nExec=pkexec bash\n",
        "link.desktop": "[Desktop Entry]\nType=Link\nName=Website\nURL=https://example.com\n",
        "actions.desktop": "[Desktop Entry]\nType=Application\nName=Editor\nExec=editor\n\n"
                           "[Desktop Action wipe]\nName=Wipe\nExec=rm -rf ~\n",
    }
    for name, body in entries.items():
        (apps / name).write_text(body)
    os.environ["XDG_DATA_HOME"] = str(tmp / "share")
    os.environ["XDG_DATA_DIRS"] = str(tmp / "none")
    names = sorted(x.name for x in t.installed_apps())
    check("only visible, non-risky Application entries are launchable",
          names == ["Editor", "Firefox", "Vivaldi"], names)
    la = t.LaunchApp()
    a = la.validate({"app": "firefox"})
    check("launch_app exact match + summary from the entry", la.summary(a) == "Open Firefox")
    check("launch_app: ambiguous kind -> error listing choices",
          rejects(la, {"app": "web browser"}) and rejects(la, {"app": "power off"}) and rejects(la, {"app": ""}))
    rec.argv.clear()
    await la.run(a)
    check("launch_app runs gtk-launch in its own systemd scope, no shell",
          rec.argv[0] == ["systemd-run", "--user", "--scope", "--collect", "--quiet", "--", "gtk-launch", "firefox.desktop"],
          rec.argv)

    # --- definitions are strict and closed ---
    defs = [x.definition() for x in t.AUTO_TOOLS]
    check("every tool definition is strict with additionalProperties false",
          all(d["strict"] and d["input_schema"]["additionalProperties"] is False for d in defs))
    check("tool names match the spec's auto tier",
          [d["name"] for d in defs] == ["launch_app", "set_volume", "media_control", "get_status",
                                       "list_windows", "focus_window"])

    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        sys.exit(1)
    print("all tests passed")


asyncio.run(main())
