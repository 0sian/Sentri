# Companion wire protocol

The contract between the Android app and the PC daemon. Don't change v1 unilaterally:
new message types or fields go under **Proposed** first and need agreement from both
sides (the app owner and the daemon owner). Additive, backwards-compatible changes can
be proposed freely.

## v1 (current)

JSON text frames over WebSocket, default port 8765. Plain `ws://`, so LAN or Tailscale only.

### Handshake
1. Server: `{"t":"challenge","nonce":"<hex>"}`
2. Client: `{"t":"auth","hmac":"<hex>"}` where hmac = lowercase-hex HMAC-SHA256(key = token UTF-8, msg = nonce UTF-8)
3. Server: `{"t":"ok","host":"<hostname>"}` or `{"t":"denied"}` and then closes.

A newer authenticated client replaces an older one. The old one is closed with code
4000, and the app does not auto-reconnect on 4000.

### Client -> server (after auth)
| msg | fields | meaning |
|---|---|---|
| `mv` | `dx`,`dy` (float px) | relative pointer move. The daemon carries fractional remainders and clamps each message to +/-`--max-step` (400) |
| `sc` | `dx`,`dy` (float, wheel notches) | scroll. Kernel sign convention: dy>0 = wheel up, dx>0 = scroll right. The app applies natural/traditional scrolling before sending |
| `btn` | `b`: left/right/middle, `s`: down/up/click | mouse button |
| `text` | `s` (<=2000 chars) | type text. The daemon maps characters through the compositor's active XKB keymap; anything the keymap can't produce is pasted via the clipboard |
| `key` | `k` (name), `mods` (list of ctrl/alt/shift/super/altgr) | key tap with modifiers. Names: enter backspace tab esc space delete arrows (up down left right) home end pageup pagedown insert menu print f1-f12, volup voldown mute playpause next prev brightup brightdown, bare `super`/`alt`/`ctrl`/`shift`, single letters/digits |
| `ping` | - | no-op |

### Invariants
- The token file is `~/.config/companion/token`, mode 600. The token never crosses the wire.
- On client disconnect, every held button and modifier is released.
- Malformed messages are ignored and never kill the connection.

## Proposed

### `ping` gets a `pong` (additive, daemon side)
Client may send `{"t":"ping","id":<int>}`. If `id` is present, the server replies
`{"t":"pong","id":<same>}`. Old clients that send `ping` without an id get no reply,
as now. Purpose: the app can show the real phone -> PC round-trip time, which is the
only way to measure latency over Wi-Fi.
Status: proposed by the daemon side, 2026-10-22, not implemented.
