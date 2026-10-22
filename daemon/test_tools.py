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

    await confirm_tier_tests()

    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        sys.exit(1)
    print("all tests passed")


class FakeInjector:
    def __init__(self):
        self.typed, self.pressed = [], []

    def valid_key(self, k):
        return k.lower() in ("t", "enter", "f5", "q")

    async def type(self, s):
        self.typed.append(s)

    async def keys(self, k, mods):
        self.pressed.append((k, mods))


async def confirm_tier_tests():
    os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = "test"
    focused = {"address": "0xaaa", "class": "foot"}
    rec = Recorder({"hyprctl clients": '[{"address":"0xabc","class":"firefox","title":"Inbox \\u001b[2J (3)"}]',
                    "hyprctl dispatch hl.dsp.window.close": "ok"})

    async def fake_run(*argv):
        if argv[:2] == ("hyprctl", "activewindow"):
            return __import__("json").dumps(focused)
        return await rec(*argv)
    t.run = fake_run
    inj = FakeInjector()

    # --- type_text ---
    tt = t.TypeText(inj)
    check("type_text rejects empty, >300 chars, escape codes",
          rejects(tt, {"text": ""}) and rejects(tt, {"text": "x" * 301}) and rejects(tt, {"text": "a\x1b[2Jb"}))
    a = await tt.prepare({"text": "ls -la\nrm x"})
    check("type_text summary shows Enter presses and the focused app",
          tt.summary(a) == 'Type "ls -la ⏎ rm x" into foot', tt.summary(a))
    focused["address"] = "0xbbb"  # focus moved between the card and the approval
    try:
        await tt.run(a)
        moved = False
    except t.ToolError:
        moved = True
    check("type_text refuses if focus changed after asking", moved and inj.typed == [], inj.typed)
    focused["address"] = "0xaaa"
    a = await tt.prepare({"text": "hello"})
    await tt.run(a)
    check("type_text types through the injector", inj.typed == ["hello"], inj.typed)

    # --- press_keys ---
    pk = t.PressKeys(inj)
    check("press_keys rejects unknown keys, unknown or repeated mods",
          rejects(pk, {"key": "launch_missiles"}) and rejects(pk, {"key": "t", "mods": ["hyper"]})
          and rejects(pk, {"key": "t", "mods": ["ctrl", "ctrl"]}) and rejects(pk, {"key": "t", "mods": "ctrl"}))
    a = await pk.prepare({"key": "T", "mods": ["shift", "ctrl"]})
    check("press_keys summary is canonical and names the app", pk.summary(a) == "Press Ctrl+Shift+T in foot", pk.summary(a))
    await pk.run(a)
    check("press_keys sends through the injector", inj.pressed == [("t", ["ctrl", "shift"])], inj.pressed)

    # --- close_window ---
    cw = t.CloseWindow()
    check("close_window only takes a hex id", rejects(cw, {"window": "firefox"}))
    a = await cw.prepare({"window": "0xabc"})
    check("close_window summary: app + cleaned title", cw.summary(a) == "Close firefox: Inbox [2J (3)", cw.summary(a))
    rec.argv.clear()
    await cw.run(a)
    check("close_window uses the Lua close dispatcher on that address",
          rec.argv == [["hyprctl", "dispatch", "hl.dsp.window.close({window='address:0xabc'})"]], rec.argv)

    # --- open_url ---
    ou = t.OpenUrl(["youtube.com"])
    bad = ["javascript:alert(1)", "file:///etc/passwd", "data:text/html,x", "https://user:pw@example.com/",
           "https://exa mple.com", "ftp://example.com", "https://", "https://example.com/\nx"]
    check("open_url rejects non-http(s), credentials, whitespace, no host", all(rejects(ou, {"url": u}) for u in bad),
          [u for u in bad if not rejects(ou, {"url": u})])
    a = ou.validate({"url": "https://www.youtube.com/watch?v=x"})
    check("allowlisted host (and subdomain) opens without asking", not ou.needs_confirm(a))
    for u in ("https://evilyoutube.com/", "https://youtube.com.evil.net/", "http://142.250.0.1/"):
        if not ou.needs_confirm(ou.validate({"url": u})):
            check(f"look-alike/IP host needs confirmation: {u}", False)
    check("look-alike hosts and IPs still need confirmation", True)
    a = ou.validate({"url": "https://\u0430pple.com/login"})  # Cyrillic 'а'
    check("Unicode look-alike host is shown as punycode", ou.summary(a).startswith("Open xn--"), ou.summary(a))
    a = ou.validate({"url": "HTTPS://Example.COM:8443/a?b=c"})
    check("summary shows host, port, path, query", ou.summary(a) == "Open example.com:8443/a?b=c in your browser", ou.summary(a))
    rec.argv.clear()
    await ou.run(a)
    check("open_url: xdg-open in its own scope, URL as one argv item",
          rec.argv[0][-2:] == ["xdg-open", "HTTPS://Example.COM:8443/a?b=c"] and rec.argv[0][0] == "systemd-run", rec.argv)

    # --- screenshot ---
    calls = []

    async def fake_bytes(*argv, **kw):
        calls.append(list(argv))
        return b"\xff\xd8jpeg"
    t.run_bytes = fake_bytes
    rec.answers["hyprctl monitors"] = '[{"name":"DP-3","width":2560,"height":1440,"focused":true}]'
    out = await t.Screenshot().run({})
    check("screenshot: grim on the focused monitor, scaled to 1568px, jpeg image block",
          calls[0] == ["grim", "-o", "DP-3", "-t", "jpeg", "-q", "75", "-s", "0.613", "-"]
          and out[0]["type"] == "image" and out[0]["source"]["media_type"] == "image/jpeg", (calls, out[0]["type"]))
    check("screenshot is high risk", t.Screenshot.risk == "high" and t.Screenshot().needs_confirm({}))

    # --- read_clipboard ---
    rc = t.ReadClipboard()
    rec.answers = {"wl-paste --list-types": "text/plain;charset=utf-8\nx-kde-passwordManagerHint\n"}
    try:
        await rc.run({})
        refused = False
    except t.ToolError:
        refused = True
    check("read_clipboard refuses password-manager secrets", refused)
    rec.answers = {"wl-paste --list-types": "text/plain;charset=utf-8\n",
                   "wl-paste --no-newline": "hi\x1b[31m there\n" + "z" * 9000}
    out = await rc.run({})
    check("read_clipboard strips control chars, caps length, labels it as data",
          "\x1b" not in out and "cut off at 8000" in out and out.startswith("Clipboard contents (data"), out[:60])

    # --- run_named_command ---
    cmds = [t.NamedCommand("updates", "Check for package updates", ["checkupdates"])]
    rn = t.RunNamedCommand(cmds)
    check("run_named_command: enum of configured names only",
          rn.schema["properties"]["command"]["enum"] == ["updates"] and rejects(rn, {"command": "rm"}))
    a = rn.validate({"command": "updates", "args": "--evil"})
    calls.clear()
    out = await rn.run(a)
    check("run_named_command runs exactly the configured argv",
          calls == [["checkupdates"]] and rn.summary(a) == 'Run "updates": checkupdates', (calls, rn.summary(a)))

    # --- registry ---
    reg = t.registry()
    check("without an injector there are no keyboard tools; no commands -> no run_named_command",
          "type_text" not in reg and "press_keys" not in reg and "run_named_command" not in reg, list(reg))
    reg = t.registry(inj, (), cmds)
    risks = {n: x.risk for n, x in reg.items()}
    check("risk tiers match the spec", risks == {
        "launch_app": None, "set_volume": None, "media_control": None, "get_status": None, "list_windows": None,
        "focus_window": None, "type_text": "low", "press_keys": "low", "close_window": "low", "open_url": "low",
        "screenshot": "high", "read_clipboard": "high", "run_named_command": "high"}, risks)
    check("every definition strict", all(x.definition()["strict"] for x in reg.values()))


asyncio.run(main())
