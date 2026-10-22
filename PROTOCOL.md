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
| `text` | `s` (<=2000 chars) | type text. The daemon maps characters through the compositor's active XKB keymap; anything the keymap can't produce is pasted via the clipboard (see below) |
| `key` | `k` (name), `mods` (list of ctrl/alt/shift/super/altgr) | key tap with modifiers. Names: enter backspace tab esc space delete arrows (up down left right) home end pageup pagedown insert menu print f1-f12, volup voldown mute playpause next prev brightup brightdown, bare `super`/`alt`/`ctrl`/`shift`, single letters/digits |
| `ping` | optional `id` (int) | with `id`: server replies `{"t":"pong","id":<same>}` immediately (never queued behind input). Without `id`: no-op, no reply |

### Server -> client (after auth)
| msg | fields | meaning |
|---|---|---|
| `pong` | `id` (int) | reply to `ping` with an id, for measuring round-trip time. Added 2026-10-22 (additive; app v0.1.1 sends ping every 2 s) |

### Ordering and timing
All input messages (`mv` `sc` `btn` `text` `key`) are applied strictly in arrival order.
A `text` that needs the clipboard holds later input back for ~165 ms per paste. That's
deliberate: with focus-follows-mouse, letting a move or click overtake a paste would
send the paste to the wrong window. One message never does more than 3 separate
pastes (beyond that, the rest of the message is pasted in one go), so the stall is bounded.
Up to 1000 input messages are buffered per connection; beyond that they're dropped.

### Paste fallback for `text`
Characters the active keymap can't produce (ŵ ŷ, emoji, `$` on Osian's Hyprland layout)
are put on the clipboard marked sensitive (clipboard managers skip them), pasted with
Shift+Insert (Ctrl+Shift+V for terminals on Hyprland), then the previous clipboard is
restored. Limitation: only one format of the previous clipboard comes back (e.g. a
browser copy returns as plain text without its rich-text version). Daemon flag
`--no-clipboard` drops those characters instead.

### Invariants
- The token file is `~/.config/companion/token`, mode 600. The token never crosses the wire.
- On client disconnect, every held button and modifier is released.
- Malformed messages are ignored and never kill the connection.

### `ok` extras and close codes (2026-10-22, additive)
- `ok` may carry `"mac":"aa:bb:cc:dd:ee:ff"`: the PC's wired MAC, sent **only** when Wake-on-LAN can
  work (wired NIC on the default route, kernel wakeup flag enabled). Absent means: don't offer Wake PC.
- Close codes from the daemon: `4000` replaced by another device (don't auto-reconnect); `1001`
  daemon shutting down or restarting (SIGTERM is handled, so this is a real close frame);
  `1008` refused because this address failed authentication too often (5 failures: 30 s;
  20 failures: 10 min; cleared by a success or an hour without failures).

## Changes since v0.1
- 2026-10-22: `ping` `id` / `pong` added (additive).
- 2026-10-22: `ok.mac` and close codes 1001/1008 (above), both additive. The
  keymap detection and paste fallback change what `text` produces on screen, not the messages.

## Proposed
(nothing open)
