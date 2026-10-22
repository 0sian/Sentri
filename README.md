# Companion v0.1 - phone as trackpad + keyboard

```
phone (Companion.apk)  --ws:// + HMAC auth-->  PC daemon  --/dev/uinput-->  KDE / Hyprland
```

## 1. PC side (once)
See `daemon/README.md`: venv + `pip install -r requirements.txt`, the udev rule, `input` group,
then `./companion_daemon.py`. It prints your LAN address and pairing token.

## 2. Phone side
Install `Companion-0.1.0.apk`, open it, enter the PC address, port (8765) and token, tap Connect.
Later builds are signed with the same key, so they install over this one and keep your pairing.

## Gestures
| Gesture | Action |
|---|---|
| One finger drag | Move pointer (speed-sensitive) |
| Tap | Left click |
| Two-finger tap | Right click |
| Three-finger tap | Middle click |
| Two-finger drag | Scroll (natural or traditional, in Settings) |
| Tap, then touch and hold + drag | Click-drag (select, move windows) |
| Left / Right click buttons | Hold to drag |

Keyboard button opens the phone keyboard; everything typed goes to the PC (UK layout by default,
`--layout us` on the daemon otherwise). Ctrl/Alt/Shift/Super are one-shot: tap, then the next key or
letter carries the modifier (so Super + arrow works for Hyprland). Long-press a modifier to tap it alone.

## Known limits in v0.1
- Characters outside the layout table (emoji, ŵ ŷ and other accents) are skipped when typing.
- Plain ws:// - use LAN or Tailscale, don't port-forward it.
- Not yet built: the AI brain and the blob character. The input link is what they'll sit on.

## Rebuilding the app
`cd android && gradle assembleDebug` (needs JDK 17+ and the Android SDK; `local.properties` -> `sdk.dir`).
If Maven Central rate-limits you, `settings.gradle.kts` already prefers the Google-hosted mirror.
