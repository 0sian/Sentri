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

### Quick actions (2026-11-26, additive; `caps` contains `"actions"`)
One-tap actions that need no AI: lock, sleep, screen off, log out, restart, shut down, a couple of Caelestia
toggles (game mode, do not disturb) and Osian's own routines. The list comes from the daemon, so it
only offers what this PC can do. Receivers ignore unknown messages, so old apps and old daemons are unaffected.

| direction | message | meaning |
|---|---|---|
| phone -> PC | `{"t":"actions_get"}` | ask for the list (send after `ok` when `caps` has `actions`) |
| PC -> phone | `{"t":"actions","items":[{"id","label","group","confirm"?,"danger"?}]}` | `group` is a section title (Session, Desktop, Power, Routines). `confirm` is the text of a dialog the phone **must** show first; `danger` means draw it red |
| phone -> PC | `{"t":"action","id":"logout","rid":3,"confirmed":true}` | run one action by exact id; `rid` (int) is echoed back; `confirmed:true` is required exactly when the item had `confirm` |
| PC -> phone | `{"t":"action_result","rid":3,"id":"logout","ok":true,"msg":"Logging out"}` | `ok:false` carries a short reason (e.g. "Can't sleep yet: media-idle-inhibit: Media is actively playing") |

Actions that end the session or the link (sleep, log out, restart, shut down) are acknowledged first and
carried out about 0.4 s later, so the reply arrives. One action runs at a time ("busy with another action").
Every run is written to the audit log as tool `quick_action`, approval `phone button`. Routines run exactly
as `run_routine` would, with the phone's confirm dialog standing in for the approval card (the dialog text
is the routine's own summary). Example:
```json
-> {"t":"actions_get"}
<- {"t":"actions","items":[{"id":"lock","label":"Lock","group":"Session"},{"id":"logout","label":"Log out","group":"Session","confirm":"Log out? Open apps will be closed.","danger":true}]}
-> {"t":"action","id":"lock","rid":1}
<- {"t":"action_result","rid":1,"id":"lock","ok":true,"msg":"Locked"}
```

### Activity, memory and routines (2026-11-26, additive; `caps` may contain `audit`, `memory`, `routines`)
Read the audit log, manage the AI's memory and see the routines, from the phone. Each capability is only
announced when the PC has it (`routines` only if ai.toml defines some). Routines are read-only here: they live in
ai.toml (which holds the API key and decides what may run), so the phone can list them and run them through
Quick actions (`routine:<name>`), but never edit them.

| direction | message | meaning |
|---|---|---|
| phone -> PC | `{"t":"audit_get","n":50}` | last `n` (1-200, default 50) tool calls |
| PC -> phone | `{"t":"audit","items":[{"ts","tool","summary","approval","result","detail"?,"session"?}]}` | oldest first. `approval`: auto / allowed / denied / timeout / `phone button` (Quick actions) / `phone` (memory edits). `result`: ok / error / not run. Typed text is already cut to 40 chars; no tool output is ever stored |
| phone -> PC | `{"t":"memory_get"}` | the memory list |
| PC -> phone | `{"t":"memory","items":[{"id","text","created"}],"max":100,"max_text":200,"broken":false}` | `broken: true` means the memory file has a syntax error: every edit is refused until it is fixed on the PC |
| phone -> PC | `{"t":"memory_add","text","rid"}` `{"t":"memory_edit","id","text","rid"}` `{"t":"memory_forget","id","rid"}` | Osian's own edits. Same checks as the AI's tools (length, no secrets, size cap); a near-duplicate add updates the old one |
| PC -> phone | `{"t":"memory_result","rid","ok","msg"}` then, if `ok`, a fresh `memory` | `msg` is a short reason when refused |
| phone -> PC | `{"t":"routines_get"}` | the routines list |
| PC -> phone | `{"t":"routines","items":[{"name","description","risk"?,"steps":["Open Firefox",...]}]}` | `risk` is `low` / `high` when the routine needs approval |

The AI reads memory as a snapshot taken when a conversation starts (this keeps its prompt cache valid), so edits
made here apply from the next conversation (`chat_reset`, a daemon restart or a context trim), not mid-chat.
Memory changes made here are written to the audit log as tool `memory`, approval `phone` (what changed is not logged).

## Changes since v0.1
- 2026-11-26: activity / memory / routines messages and `caps` `audit` `memory` `routines`, additive.
- 2026-11-26: quick actions (`actions_get`, `actions`, `action`, `action_result`, `caps: actions`), additive.
- 2026-10-22: `ping` `id` / `pong` added (additive).
- 2026-10-22: `ok.mac` and close codes 1001/1008 (above), both additive. The
  keymap detection and paste fallback change what `text` produces on screen, not the messages.

## Proposed
(nothing open)
