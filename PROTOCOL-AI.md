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
| `chat_done` | `id`, `usage?` `{"in":int,"out":int}`, `cancelled?`, `today_usd?`, `budget_usd?` | turn finished. Exactly one of `chat_done` / `chat_error` ends every turn |
| `chat_error` | `id`, `msg` (short, user-readable) | turn failed (API error, budget reached, busy, ...) |
| `cu_session` | `state`: `active` (+ `secs_left`, `goal` ≤160 chars) / `ended` (+ `reason`) | computer-use session banner. `active` is sent when a session starts (and again if its deadline changes). `ended` reasons: `done` `timeout` `user` `touched` `limit` `error` `disconnected`. Added 2026-10-22 |
| `chat_mood` | `id`, `mood` | optional, at most once per turn, sent as early as possible (before the first `chat_delta` when the reply opens with it). One of: neutral attentive surprised excited happy laughing angry sad scared suspicious confused curious proud shy unimpressed (`thinking`/`alert`/`sleepy` are phone-driven, never sent). Unknown values are ignored by the phone. Added 2026-10-22 |

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
7. **Mood tags.** The model opens an emotional reply with `[mood:x]`. The daemon holds back the start
   of each reply until the tag closes (or 24 chars pass with no `]`), strips it, and sends
   `chat_mood`. The tag never appears in `chat_delta` or anything the phone shows. It *is* kept in the
   model-side context: stripping it would mean editing the model's own output before re-sending it
   (the history-editing check), and without seeing its earlier tags the model tends to stop using them.
8. **Confirm-gated tools (Phase C).** `risk` low: `type_text` (max 300 chars), `press_keys` (one combo
   per call), `close_window`, `open_url`. `risk` high: `screenshot`, `read_clipboard`,
   `run_named_command`. Behaviour the phone can rely on:
   - Only a JSON `true` in `confirm.allow` allows; anything else (false, "true", 1, missing) is a deny.
   - `summary` is at most 200 chars, built from validated args. `type_text` shows Enter/Tab as ⏎/⇥
     (they can run commands in a terminal) and names the focused app; if focus has moved by the
     time Allow arrives, nothing is typed and the tool reports `error`.
   - `open_url` shows the host as punycode when it has non-ASCII characters (look-alike domains).
     It skips the card only for hosts on Osian's `open_url_allow` list (and their subdomains);
     IP addresses always ask.
   - `run_named_command` runs only commands from Osian's `ai.toml`. The model picks a name; it
     can't add arguments.
   - Cancel/reset/disconnect with a card up: the card resolves as `tool` `denied`/`user` (if the
     socket is still open) and the turn ends `cancelled`. A late `confirm` for that call is ignored.
9. **Routines** (`list_routines` auto, `run_routine(name)`). Steps take the tool's *real* arguments
   (so `set_volume` needs `action = "set", percent = 30`, not just `percent`). Allowed step tools:
   launch_app, set_volume, media_control, get_status, type_text, press_keys, open_url,
   run_named_command. Not allowed: tools that need ephemeral ids (focus/close_window),
   screenshot/read_clipboard, memory tools, routines. Every routine is fully validated at daemon
   start (bad ones skipped with a log line) and each step is re-validated just before it runs.
   Routines are read at daemon start, so edits to ai.toml need a restart. Card: one
   `confirm_req` at the highest step risk, with `summary` like
   "Work routine: open Firefox, set volume to 30%". **Routine summaries can be up to 400 chars**
   (other cards stay at 200 or less); a routine whose card would be longer is rejected at load,
   so nothing is ever approved unseen. Progress: the routine's own `call` goes running → (one
   call per step, running → ok/error, summary "Work · Open Firefox") → ok/error.
10. **Memory.** File `~/.local/share/companion/memory.toml` (mode 600), editable by hand; a file with
   a syntax error is never overwritten. Two departures from the task, for API reasons:
   - The memory block is a **snapshot per conversation** (taken on daemon start, `chat_reset`, or a
     context trim), placed after the cached static prompt and tool definitions. Rewriting the system
     prompt mid-conversation would make Haiku 5.5 reject the replayed thinking blocks (400).
     Mid-conversation changes reach the model through the remember/forget tool results.
   - **Taint lasts for the conversation, not just the turn**: untrusted text stays in context after
     the turn that read it. Taint is set by get_status, list_windows, screenshot, read_clipboard,
     run_named_command (and routines containing those); it clears on `chat_reset`.
11. **homelab_stats(section)** (auto, untrusted for taint). Sections: cpu mem load fs network sensors
   containers uptime. URL, API prefix (default `/api/4`) and optional basic auth come only from
   `[homelab]` in ai.toml. GET only, 4 s timeout, 512 KB cap, redirects refused. A 404 is reported
   as "set api = /api/3" so a wrong prefix is obvious (the containers section falls back to the
   Glances 3 `docker` plugin first). Output is reduced to a few lines, and container, mount and
   sensor names are cleaned like window titles. Unreachable homelab means a clean tool error. No
   restart/write tools.
12. **Computer use** (`start_computer_use(goal)`, high risk; `caps` gains `"cu"`). Phone → daemon:
   `{"t":"cu_stop"}` (ignored when nothing is running). Daemon → phone: `cu_session` (table above).
   **One addition to the agreed reasons: `done`**, for when the session model finishes or reports
   it's stuck via `end_computer_use`; none of the agreed reasons fit that case.
   - The session is a sub-conversation on `cu_model` (default `claude-sonnet-5-5`), seeded with
     the goal and a first screenshot. The main chat gets only the summary, so the main history has
     no images and no model switch.
   - It uses the **native `computer_toolset_20260801`** (GA, no beta header; Sonnet 5.5 accepts only
     this form on the Claude API) with `hold_key` / `left_mouse_down` / `left_mouse_up` disabled,
     plus custom `end_computer_use` and `open_url` (still with its card). The natives map onto the
     spec's actions: left/right/middle/double/triple_click, left_click_drag, scroll, mouse_move,
     type, key, wait (capped at 5 s), screenshot, zoom, cursor_position.
   - Screenshots: focused monitor, long edge 1280, **with the real pointer drawn in** (`grim -c`)
     instead of a synthetic crosshair, so the model sees where the pointer actually is after
     each click. Coordinates are mapped through the monitor's offset and fractional scale, then
     clamped to the monitor.
   - Guardrails: `type`/`key` are refused when the focused window class is in `cu_blocklist`
     (terminals, krunner/rofi/wofi/fuzzel, password managers; ai.toml entries add to the
     defaults), and also while **Caelestia's launcher is open**. The launcher is a layer surface,
     invisible to window-class checks, and can run things, so this is checked over its IPC.
     **Every action is refused while Caelestia's power menu is open.** Super combos and Ctrl+Alt
     combos are refused, including on clicks. A batch stops at its first failure, as the API
     requires.
   - Ends on the first of: `cu_secs` (300), `cu_max_actions` (60), `cu_budget_usd` (0.25, priced
     per model from usage), `end_computer_use`, `cu_stop`, chat_cancel/reset (reason `user`),
     disconnect/replace (`disconnected`), an error, or phone input (`mv` with a non-zero delta,
     `sc`, `btn`, `key`, `text`: reason `touched`; the input itself still applies). Actions are
     at least 300 ms apart. Session tokens count toward the daily cap.
13. **Round 4 (phone 0.6.0).**
   - `open_url` gains optional `app` (a browser by name, validated like launch_app). The card and
     the result name the browser ("Open www.atlasobscura.com in Vivaldi" / "Opened … in Vivaldi"),
     taken from `xdg-settings get default-web-browser` when no app is given. An open window of
     that browser is focused first.
   - Every `chat_done` (cancelled ones too) carries `today_usd` (estimated, chat + computer use,
     priced per model from usage) and `budget_usd` when `daily_budget_usd` is set (default 1.0).
     The same numbers enforce the cap ("Daily AI budget reached").
   - Audit log `~/.local/state/companion/audit.jsonl` (600, ~5 MB × 3): ts, tool, summary,
     approval (auto/allowed/denied/timeout), result (ok/error/not run), session id for
     computer-use actions. No outputs; typed text cut to 40 chars. `recent_actions(n)` (auto,
     untrusted for taint) reads it back.
14. **Process tools** (`daemon/procs.py`).
   - `list_processes(sort, limit≤25)` and `list_startup()` are read-only and auto tier. They show
     names only (never command lines), and count as untrusted for taint, because programs choose
     their own names.
   - `kill_process(pid, force=false)` is high risk, with a card every time. It takes a PID only,
     never a name. The card is built from /proc: "End firefox (PID 1234, user, 512 MB) with
     SIGTERM", or "Force-kill … with SIGKILL".
   - It refuses: PID 1, the daemon itself and its service manager, other users' processes, and
     session/compositor processes (kwin_wayland, plasmashell, ksmserver, Hyprland, uwsm, sddm,
     systemd, Xwayland, dbus, ...).
   - Just before signalling it re-checks that the PID still has the name and start time shown on
     the card.
   - It reports honestly: exited, or "still running 3 s after SIGTERM … forcing needs force=true
     and another approval" as an error.
   - Audited like every tool, with signal and result.
   - No stop/disable-service tool.
15. **Screen guide** (`daemon/guide.py`, `overlay/`). No new wire messages are needed: it runs as two
   ordinary tools through the existing `tool` / `confirm_req` flow.
   - `point_at_screen(target, instructions, title?, sensitive?)` sends the focused monitor's screenshot
     to the AI provider, so it asks (a low-risk card: "Look at your screen and point out: <target>.
     Asking first because <reason>.") only when something private might be on screen, and otherwise just
     runs. The decision is local and fails closed (`daemon/sensitivity.py`): the apps and titles of the
     windows visible on that monitor are checked. No card is needed only if every window is a settings
     tool, a browser on a page whose title has none of the private words (bank, mail, login, messages,
     passwords, health, ...), or a file manager in a folder that doesn't look personal (pictures, photos,
     camera, family, documents, ...). Any other app (a terminal, chat app, password manager, anything
     unknown) or an unreadable window list means ask. The chat model's `sensitive=true` (his question is
     about private things) can only add a card, never remove one. Card reasons name apps, never titles.
     Optional ai.toml `[guide]`: `safe_apps = ["class", ...]` never need a card, `ask_words = ["word", ...]`
     are extra private title words. Known gaps: notification pop-ups, a browser's tab strip, and the
     contents of an allowed window with an innocent title. The daemon hides any old guide, takes the screenshot at up to 2560 px, and a
     separate one-shot Haiku call returns `{found, x, y}`. Those numbers are range-checked, and nothing
     from the screen goes back to the chat model. The tool result is "Pointing at it now…" or a "not
     visible, ask him to bring the right window forward" error. A rope then swings out from the notch
     to the target, with the instructions on a card beside it.
   - `clear_guide()` is auto tier and removes the guide. Tapping the notch on the PC does the same.
     A guide also retracts by itself after 10 s.
   - The overlay is a separate process (system Python + PyQt6 + layer-shell-qt). The daemon starts it
     on first use, with the live session's environment, and stops it on shutdown. Commands go over
     `$XDG_RUNTIME_DIR/sentri-overlay.sock` as JSON lines: `point {x,y,title,text,ttl}` (x,y are
     compositor layout px, and the monitor that contains the point gets the guide), `clear`, `expand`,
     `collapse`, `debug {on}`, `quit`.
   - **Proposed, optional:** phone → daemon `{"t":"guide_clear"}` dismisses the guide (no reply). The
     daemon already handles it; old and new apps can ignore it.
   - Tested on Hyprland, including a second monitor at scale 1.5 (virtual output). Not yet tested on KDE.

16. **Approving on the notch (PC side only, no wire change).** While a phone is connected, a `confirm_req`
    for a low-risk tool in `ai.PC_APPROVE` (`point_at_screen`, `open_url`, `close_window`) is also shown
    as a card on the PC's notch with Allow / Deny. The first answer wins; the daemon then sends the usual
    `tool` event (running / denied), so the phone resolves its card exactly as before, and the notch card
    is dismissed if the phone answered first. Never offered for high-risk tools, keystroke tools, or while
    a computer-use session is active (it moves the real mouse and could press Allow itself), and a notch
    click that arrives once a session has started is ignored. Card text is the daemon-built `summary`.
