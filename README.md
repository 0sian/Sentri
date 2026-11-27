<div align="center">

<img src="docs/banner.png" alt="Sentri: your phone as a trackpad, keyboard and AI companion for your PC" />

<br />

[![Android](https://img.shields.io/badge/Android-8.0%2B-3DDC84?logo=android&logoColor=white)](#build-it)
[![Kotlin](https://img.shields.io/badge/Kotlin-Compose-7F52FF?logo=kotlin&logoColor=white)](https://developer.android.com/jetpack/compose)
[![Python](https://img.shields.io/badge/daemon-Python-3776AB?logo=python&logoColor=white)](#the-daemon)
[![Wayland](https://img.shields.io/badge/Wayland-Hyprland%20%7C%20KDE%20Plasma-FFD60A)](#the-daemon)
[![Claude](https://img.shields.io/badge/AI-Claude%20API-D97757)](#the-ai-companion)

</div>

<br />

Sentri turns your phone into a **trackpad and keyboard for your Linux PC**, and into a small **AI companion** that can look at your screen, point things out and act on your say-so. A plain yellow cloud is its face, on the phone and as a little pair of eyes in the notch of your desktop.

It works on **KDE Plasma and Hyprland** (Wayland). Input is injected through `/dev/uinput`, below the compositor, so it needs no compositor-specific hooks, and it works at the **login screen** too.

## Features

**Trackpad and keyboard**
- One-finger move (speed-sensitive), tap to click, two-finger tap to right-click, three-finger tap to middle-click, two-finger scroll, and tap-then-hold to drag.
- Type from the phone keyboard. Ctrl, Alt, Shift and Super are one-shot, with a key strip, a shortcut strip and media keys.
- Typing follows the layout your compositor is really using. Characters the layout has no key for (`ŵ`, emoji) are pasted through the clipboard, marked sensitive so clipboard managers skip them, and your old clipboard is restored.
- The daemon starts at boot, before anyone logs in, so the phone works at the SDDM login screen after a reboot.

**The AI companion** *(optional, needs your own Anthropic API key)*
- Chat with streaming replies, short tool-status lines, and voice through Android's speech recogniser.
- **Approval cards.** Anything risky (typing, pressing keys, closing windows, opening links, screenshots, reading the clipboard, running a saved command) shows an Allow / Deny card on the phone first. No answer means no.
- **Computer use.** A short, time-boxed session where the AI looks at the screen and clicks. A red banner with a Stop button shows on every screen, and touching the trackpad takes over.
- **Screen guide.** Ask how to do something and the AI points at the thing on your actual screen with a rope from the notch, one step at a time, with a **Next** button.
- **Memory, routines and an audit log** on the phone's Activity screen: add, edit and forget what it remembers, run your saved routines, and read everything it did.
- **Timers and reminders**, a "tell me when that build finishes" process watcher, and a **system doctor** that reports failed units, full disks, hot sensors and pending updates, and can raise alerts for new problems while your phone is connected.
- A **character** that picks a mood for each reply: the cloud on the phone and the eyes on the desktop both react.
- A spend counter, and an optional daily token cap on the daemon.

**Quick actions and more**
- Lock, sleep, screen off, log out, restart, shut down, game mode and Do Not Disturb, from one screen. Destructive ones need confirmation.
- **Wake-on-LAN** from the phone when the PC reports its MAC address.

## How it works

```
phone (Kotlin + Compose)  --ws:// + HMAC auth-->  daemon (Python)  --/dev/uinput-->  KDE / Hyprland
                                                       |-- AI layer (Claude API, tools, approvals)
                                                       '-- desktop tools (hyprctl / KWin / screenshots)
                                                       '-- overlay (PyQt6 + QML notch, screen guide)
```

| Part | What it does |
| --- | --- |
| `daemon/` | WebSocket server, HMAC auth, the virtual keyboard and mouse, the keymap, the clipboard fallback and the AI layer with its tools. |
| `android/` | The Sentri app: Controller, chat, Quick actions, Activity and Settings, plus the face engine. |
| `overlay/` | The desktop overlay: notch eyes, countdowns, approve/deny buttons and the screen-guide rope, drawn with layer-shell. |
| `PROTOCOL.md`, `PROTOCOL-AI.md` | The wire protocol between phone and daemon. Changes are additive, so old phones keep working. |

### The AI companion

The API key lives **only on the PC** (in `~/.config/companion/ai.toml`, which the daemon requires to be mode 600). It is never sent to the phone and never logged. With no key the daemon doesn't offer chat at all and the app hides it. It defaults to Claude Haiku and the model is configurable.

| Tier | Behaviour | Examples |
| --- | --- | --- |
| auto | runs at once, shown as a status line | launch a known app, volume, media control, list and focus windows |
| confirm | needs a tap on the phone | type text, press keys, close a window, open a link |
| confirm (red) | needs a tap, shown in red | screenshots (they go to the API), read the clipboard, run a named command |
| never | not offered to the model | raw shell, `sudo`, writing or deleting files, arbitrary network requests |

## Security

- **The token never crosses the network.** The phone proves it knows it with an HMAC over a one-time nonce.
- **Whoever has the token controls your mouse and keyboard.** The token file is created mode 600. Delete it and restart the daemon to rotate it.
- **The link is plain `ws://`.** That's fine on a home LAN. Away from home, go over Tailscale or WireGuard, and never expose port 8765 to the internet. Allow it from your LAN only in the firewall.
- The daemon's logs hold only message types and lengths, never what you typed or chatted.
- The `uinput` group can only create virtual devices. Don't add yourself to `input`, which would also give every process of yours read access to your physical keyboard.

## The daemon

On Arch-based systems:

```sh
cd daemon
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

To make it start at boot (and so work at the login screen) it needs a `uinput` group and lingering:

```sh
sudo groupadd --system uinput
sudo usermod -aG uinput $USER
sudo install -m644 90-companion-uinput.rules /etc/udev/rules.d/
sudo install -m644 companion-uinput.conf /etc/modules-load.d/
sudo udevadm control --reload && sudo udevadm trigger --sysname-match=uinput
loginctl enable-linger $USER
systemctl --user enable "$PWD/companion.service" && systemctl --user start companion
```

The service file runs the daemon from `~/companion/daemon`. If you cloned the repo somewhere else, edit the two paths on its `ExecStart` line first.

Then reboot. Run by hand with `.venv/bin/python companion_daemon.py`: it prints the LAN address and the pairing token. Enter both in the phone app once. Full details, the layout options and the optional AI setup are in [`daemon/README.md`](daemon/README.md).

## Build it

You need JDK 17 or newer, and the Android SDK with `platforms;android-35` and `build-tools;34.0.0`. No Android Studio required.

```sh
cd android
echo "sdk.dir=$HOME/Android/Sdk" > local.properties
./gradlew :app:testDebugUnitTest      # JVM unit tests
./gradlew :app:assembleDebug          # app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

**Signing.** If `android/app/debug.keystore` exists the build signs with it, so every build installs over the last one and keeps your pairing. The keystore is deliberately not in the repo: a build signed with a different key can't be installed over an existing copy without uninstalling, which wipes the pairing.

The daemon's tests are plain Python scripts in `daemon/` (`.venv/bin/python test_daemon.py` and the other `test_*.py` files), run against a fake uinput device and a fake LLM backend, so nothing touches your desktop or the network.

## Status

Used daily on **CachyOS** with Hyprland and KDE Plasma 6. The desktop tools (windows, screenshots, computer use) were written Hyprland-first, and Plasma support is mostly done: screenshots, windows, launching and computer use work, but the notch's cursor-following and the screen guide's window sensitivity check are not yet verified on KDE.

Not done yet:
- TLS or pinned-cert pairing (or listening on Tailscale only), with QR-code pairing
- Letting a chat turn survive the phone dropping, and out-of-band notifications (KDE Connect or ntfy) so alerts and approvals reach a backgrounded phone
- A Quick Settings tile and launcher shortcuts for Quick actions
- A browser tool over CDP (tried and parked: a fresh Vivaldi profile never answered page commands)

## Credits

The face engine's approach (fixed target poses, eased transitions, deterministic blink and gaze) is inspired by the open-source Bloub avatar engine. No Bloub code is used. Built with [websockets](https://websockets.readthedocs.io), [python-evdev](https://python-evdev.readthedocs.io), the [Anthropic SDK](https://github.com/anthropics/anthropic-sdk-python), PyQt6 and layer-shell-qt.

The Android package is still `uk.osianj.companion` and the daemon's service is `companion`, from before the app was renamed Sentri.
