#!/usr/bin/env python3
"""Local sensitivity rules for the screen guide: what skips the approval card and what doesn't."""
import asyncio
import sys

import guide
import pc_tools
import sensitivity

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def win(cls, title=""):
    return {"cls": cls, "title": title}


P = sensitivity.Policy()


def ask(windows, flag=False, policy=P):
    return policy.assess(windows, flag)[0]


# --- things Osian listed as fine without a card ---
check("settings app: no card", not ask([win("systemsettings", "Wi-Fi & Internet - System Settings")]))
check("settings app: no card whatever the title says", not ask([win("pavucontrol", "Volume Control - password")]))
check("browser on an ordinary page: no card", not ask([win("vivaldi-stable", "PortWatch VI: Does GTA VI run on PC yet? - Vivaldi")]))
check("browser, docs page: no card", not ask([win("firefox", "Hyprland Wiki - Mozilla Firefox")]))
check("file manager in an ordinary folder: no card", not ask([win("org.kde.dolphin", "projects — Dolphin")]))
check("file manager in Downloads: no card", not ask([win("org.kde.dolphin", "Downloads — Dolphin")]))
check("empty monitor (just the desktop): no card", not ask([]))
check("several harmless windows together: no card", not ask([win("systemsettings", "Display"), win("vivaldi-stable", "Arch Wiki")]))

# --- things that must ask ---
check("file manager in Pictures: card", ask([win("org.kde.dolphin", "Pictures — Dolphin")]))
check("file manager in Camera/Holiday folders: card", ask([win("nautilus", "Holiday 2025")]) and ask([win("thunar", "DCIM - Thunar")]))
check("file manager in a folder with a path: card", ask([win("org.kde.dolphin", "/home/user/Pictures/Family — Dolphin")]))
check("browser on a bank page: card", ask([win("vivaldi-stable", "Monzo - Log in - Vivaldi")]))
check("browser on webmail: card", ask([win("firefox", "Inbox (3) - Gmail")]))
check("browser on a login page: card", ask([win("vivaldi-stable", "Sign in to GitHub")]))
check("browser on a messaging page: card", ask([win("vivaldi-stable", "WhatsApp Web")]))
check("browser in a private window: card", ask([win("firefox", "Private Browsing - Firefox")]))
check("unknown app: card (fails closed)", ask([win("com.example.mystery", "Hello")]))
check("terminal: card", ask([win("com.mitchellh.ghostty", "~")]))
check("chat/messaging app: card", ask([win("discord", "General - Discord")]))
check("password manager: card", ask([win("org.keepassxc.keepassxc", "KeePassXC")]))
check("one private window among harmless ones: card", ask([win("systemsettings", "Display"), win("discord", "x")]))
check("windows couldn't be listed (None): card", ask(None))
check("model's sensitive flag alone: card", ask([win("systemsettings", "Display")], flag=True))
check("model can't remove a card: harmless windows + flag false still follow the rules", ask([win("discord", "x")], flag=False))

# --- word matching is on whole words, case-insensitive ---
check("whole words only: 'Taxonomy' isn't 'tax'", not ask([win("vivaldi-stable", "Taxonomy of birds - Vivaldi")]))
check("case-insensitive", ask([win("vivaldi-stable", "BANKING OVERVIEW")]))
check("'Camera' folder vs 'camera-ready' paper: whole word 'camera' matches only as a word",
      ask([win("dolphin", "camera")]))

# --- reasons name apps, never titles ---
asks, reasons = P.assess([win("org.kde.dolphin", "Pictures/Passport scans/secretname"), win("discord", "Dave - Discord")], False,
                         lambda c: {"org.kde.dolphin": "Dolphin", "discord": "Discord"}.get(c, c))
check("reasons are readable and title-free", asks and reasons == ["Dolphin is showing a folder that may be personal", "Discord is open"]
      and not any("secretname" in r or "Dave" in r for r in reasons), str(reasons))

# --- config additions ---
custom = sensitivity.Policy(safe_apps=["com.mitchellh.ghostty"], ask_words=["foobar"])
check("ai.toml safe_apps: allowed with no card", not ask([win("com.mitchellh.ghostty", "~")], policy=custom))
check("ai.toml ask_words: extra private word triggers a card", ask([win("vivaldi-stable", "foobar dashboard")], policy=custom)
      and not ask([win("vivaldi-stable", "foobar dashboard")]))
check("safe_apps entries are case-insensitive", not ask([win("com.mitchellh.ghostty")],
                                                        policy=sensitivity.Policy(safe_apps=["COM.MITCHELLH.GHOSTTY"])))

# --- visible_windows() on Hyprland: only the focused monitor's visible workspace ---
async def hypr_case():
    saved = (pc_tools._hyprland, pc_tools._hypr_json)
    pc_tools._hyprland = lambda: True

    async def fake(*what):
        if what == ("monitors",):
            return [{"id": 0, "focused": True, "activeWorkspace": {"id": 2}, "specialWorkspace": {"id": 0}},
                    {"id": 1, "focused": False, "activeWorkspace": {"id": 5}, "specialWorkspace": {"id": 0}}]
        return [{"class": "a", "title": "t", "monitor": 0, "workspace": {"id": 2}, "mapped": True},
                {"class": "other-ws", "title": "t", "monitor": 0, "workspace": {"id": 1}, "mapped": True},
                {"class": "other-mon", "title": "t", "monitor": 1, "workspace": {"id": 5}, "mapped": True},
                {"class": "hidden", "title": "t", "monitor": 0, "workspace": {"id": 2}, "mapped": True, "hidden": True}]
    pc_tools._hypr_json = fake
    try:
        got = await guide.visible_windows()
        check("hyprland: only visible windows on the focused monitor", [w["cls"] for w in got] == ["a"], str(got))

        async def boom(*what):
            raise pc_tools.ToolError("hyprctl failed")
        pc_tools._hypr_json = boom
        check("hyprland: an error means 'couldn't tell' (None)", await guide.visible_windows() is None)
    finally:
        pc_tools._hyprland, pc_tools._hypr_json = saved

asyncio.run(hypr_case())

if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("all tests passed")
