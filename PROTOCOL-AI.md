# PROTOCOL addendum: AI chat (proposed v1.1, additive)

**Status: PROPOSED by the app side.** PC session: review, and object or amend *in writing* before you implement.
Everything here is additive. v1 phones and v1 daemons keep working unchanged.

## Architecture
```
phone  --chat / confirm-->  daemon  --Anthropic API-->  model
phone  <--text / tool status / confirm requests--  daemon  (daemon runs the tool loop)
```
- The API key lives **only on the PC**. It is never sent to the phone, never logged.
- The phone only ever sees: streamed text, short tool-status lines, and confirmation prompts.
- Default model: `claude-haiku-5-5`, configurable on the daemon. The phone is model-agnostic.

## Capability handshake
`ok` gains optional fields:
```json
{"t":"ok","host":"mypc","caps":["chat"],"model":"claude-haiku-5-5"}
```
The app shows the chat UI only if `"chat"` is in `caps`. A daemon without AI configured omits `caps`.
Unknown fields/messages must be ignored by both sides.

## Phone -> daemon
| msg | fields | meaning |
|---|---|---|
| `chat` | `id` (int, phone-assigned, unique per connection), `text` (<=4000 chars) | start a turn. If a turn is already active: reply `chat_error` for that id with msg "Busy" |
| `chat_cancel` | `id` | stop the active turn; daemon replies `chat_done` with `"cancelled":true` |
| `chat_reset` | - | forget the conversation context |
| `confirm` | `call` (string), `allow` (bool) | answer to a `confirm_req` |

## Daemon -> phone
| msg | fields | meaning |
|---|---|---|
| `chat_delta` | `id`, `text` | streamed assistant text (append) |
| `tool` | `id`, `call`, `name`, `summary`, `state`, `detail?` | tool activity. `state`: `running` / `ok` / `error` / `denied`. `denied` carries `detail`: `user` or `timeout`. May be sent repeatedly per `call` (running, then ok/error) |
| `confirm_req` | `id`, `call`, `name`, `summary`, `risk` (`low`/`high`), `timeout` (s) | ask the user to approve one specific action |
| `chat_done` | `id`, `usage?` `{"in":int,"out":int}`, `cancelled?` | turn finished. Exactly one of `chat_done` / `chat_error` ends every turn |
| `chat_error` | `id`, `msg` (short, user-readable) | turn failed (API error, budget reached, busy, ...) |

Ordering for a turn: any mix of `chat_delta` / `tool` / `confirm_req`, then exactly one `chat_done` or `chat_error`.
After a `confirm_req`, the daemon **always** follows with a `tool` event for that `call` (running/ok/error if
allowed, `denied` if refused or timed out), so the phone can resolve the card.

## Rules
1. **One turn at a time.** Chat work runs in its own task and **must not delay** pointer/key input or `pong`.
2. **`summary` is built by the daemon from the validated tool arguments**, never copied from model prose.
   The user approves what will actually happen, e.g. `Type "hello" into the focused window (Firefox)`.
3. **Confirmations default to deny.** Timeout (default 60 s) -> deny. Phone disconnects -> all pending denied,
   the active turn is cancelled. A new client replacing an old one has the same effect on the old connection.
4. `call` ids are unique per daemon run and are never reused.
5. Conversation context lives in daemon memory until `chat_reset` or restart. The phone's transcript is only a
   display; it can be cleared independently (the app sends `chat_reset` when the user taps Clear).
6. Tool results are **untrusted data** (window titles, clipboard, page text, screenshots can contain injected
   instructions). The system prompt must say so, and the confirm gates below are the real defence, not the prompt.

## Tool tiers (daemon policy, not wire protocol)
| tier | behaviour | examples |
|---|---|---|
| auto | runs immediately, shown as a status line | `launch_app` (known .desktop names only), `set_volume`, `media_control`, `get_status`, `list_windows`, `focus_window` |
| confirm (`low`) | needs a phone tap | `type_text`, `press_keys`, `close_window`, `open_url` (unless host is on a configured allowlist) |
| confirm (`high`) | needs a phone tap, shown in red | `screenshot` (sends your screen to the API provider), `read_clipboard`, `run_named_command` |
| never | not offered to the model | raw shell, `sudo`, writing/deleting files, arbitrary network requests |

## Cost and abuse controls (daemon)
- `max_tokens` per reply, max 8 tool rounds per turn, optional daily token cap -> `chat_error` "Daily AI budget reached".
- Prompt-cache the system prompt + tool definitions.
- Never log message bodies at INFO; never log the API key.

## What the app does with this
- Blob goes to "thinking" while a turn is active, "happy" on `chat_done`, "surprised" when a `confirm_req` arrives.
- Tool lines render as small status rows, confirmations as an inline card with Allow / Deny.
- If the connection drops mid-turn the app shows "Connection lost" and expires any pending card.

## PC-side review (2026-10-22)
No objections to the wire format. Phase A is built as specced. These are clarifications of
behaviour the spec leaves open. None of them adds a message or field:

1. **`usage.in`** = all input tokens for the turn: uncached + cache writes + cache reads, summed over
   every API round in the turn (there's more than one once tools exist). `out` = output tokens,
   thinking included. The daily cap counts `in + out`.
2. **History on cancel/error.** The API requires history to be append-only (on Haiku 5.5, editing earlier
   turns makes the replayed thinking blocks a 400). So a turn is committed to context only when it
   ends. Cancelled with some text streamed: the user message + the text so far are kept (marked
   "[cancelled]"), so the model knows what it said. Tool rounds that completed (call + result) are
   always kept, even after an error or cancel, because those actions really happened; a tool call
   whose result never arrived is dropped. Anything else from an errored or refused turn is dropped.
3. **Context growth.** When a turn's input exceeds `history_token_limit` (default 30k), the oldest
   exchanges are dropped and thinking blocks are stripped from what's left (that's the only
   edit the API allows). One cache miss, no error. `chat_reset` is still the normal way to clear.
4. **`chat` edge cases** -> `chat_error` for that id: text over 4000 chars ("Message too long"),
   AI not configured on a daemon that got `chat` anyway ("AI isn't set up on this PC"), model refusal
   ("I can't help with that one"). `chat_reset` during an active turn cancels the turn first
   (the phone gets its `chat_done` with `cancelled:true`), then clears.
5. **One turn per daemon**, not per connection. A replacing client's `chat` may briefly get "Busy"
   while the old connection's turn is being cancelled.
6. **Phase C note:** `type_text` / `press_keys` go through the same ordered input queue as the phone's
   own `text`/`key` messages, so tool typing never interleaves with your typing.
