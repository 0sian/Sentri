# Companion daemon

Turns your phone into a trackpad + keyboard for this PC. Works on KDE Plasma and
Hyprland (it injects through `/dev/uinput`, below the compositor).

## Install (CachyOS / Arch)

```fish
cd companion/daemon
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Runtime tools: `libxkbcommon` (any Wayland desktop has it) and `wl-clipboard` for the
paste fallback.

## uinput permission

Check first: `getfacl /dev/uinput`. If your user is listed (`user:<you>:rw-`), you're
done. The Steam and KDE Connect udev rules already tag uinput `uaccess` for the
logged-in user. Otherwise, tag it the same way:

```fish
sudo cp 70-companion-uinput.rules /etc/udev/rules.d/
sudo udevadm control --reload; and sudo udevadm trigger
```

Avoid adding yourself to the `input` group: it also gives every process you run read
access to your physical keyboard.

## Run

```fish
.venv/bin/python companion_daemon.py              # layout follows the compositor
.venv/bin/python companion_daemon.py --layout gb  # or force an XKB layout
.venv/bin/python companion_daemon.py --no-clipboard
```

It prints the LAN address and the pairing token (also stored in
`~/.config/companion/token`). Enter both in the phone app once.

## Typing

The daemon reads the keymap the compositor is using (Hyprland: `hyprctl devices`,
KDE: `~/.config/kxkbrc`, else `localectl`) on every connection and types through it.
Characters the layout can't produce (ŵ ŷ, emoji, etc.) are pasted: the daemon puts
them on the clipboard marked sensitive (so cliphist/Klipper skip them), sends Shift+Insert
(Ctrl+Shift+V for terminals on Hyprland), then restores your previous clipboard. Only
one format of the old clipboard is restored (e.g. plain text from a browser copy,
not its rich-text version).

## Autostart (KDE and Hyprland)

```fish
mkdir -p ~/.config/systemd/user
ln -s ~/companion/daemon/companion.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now companion.service
```

It's tied to `graphical-session.target`: it starts with either session and stops
on logout.

## Security notes

- The token never crosses the network: the phone proves it knows it with an
  HMAC over a one-time nonce.
- Traffic itself is plain `ws://`. Fine on your home LAN. Away from home, go over
  Tailscale/WireGuard rather than exposing port 8765 to the internet.
- Whoever has the token controls your mouse and keyboard. Keep the token file private
  (it is created `chmod 600`). Delete it and restart to rotate.
- Firewall: allow TCP 8765 from the LAN only, e.g. `sudo ufw allow from 192.168.1.0/24 to any port 8765 proto tcp`.

On KDE the unit also sets flat pointer acceleration for the virtual device only
(`kcminputrc`, group `[Libinput][4660][22136][companion-virtual-input]`), so KWin doesn't
apply its own acceleration on top of the app's.

## AI chat (optional)

Put an Anthropic API key in `~/.config/companion/ai.toml` (the daemon enforces mode 600)
and restart the service. Other settings are documented at the top of `ai.py`:

```toml
api_key = "sk-ant-..."
```

With no key, the daemon doesn't advertise `chat` and the app hides the chat UI. The key
never leaves the PC and is never logged. Set `daily_token_cap` to bound the spend.

Things the AI does that you might not want (typing, closing windows, opening links,
screenshots, reading the clipboard, running your saved commands) always show an
Allow/Deny card on the phone first, and no answer means no. To give it a few safe
commands, list them in `ai.toml`; it can only pick a name, never add arguments:

```toml
open_url_allow = ["youtube.com"]   # links to these open without a card

[commands.updates]
description = "Check for package updates"
argv = ["checkupdates"]
```

Routines are saved sequences it can run by name, with one Allow/Deny card if any step
needs approval. Steps use the tools' own arguments:

```toml
[routines.work]
description = "Start work: browser, quiet volume"
steps = [
  { tool = "launch_app", app = "firefox" },
  { tool = "set_volume", action = "set", percent = 30 },
]
```

Bad routines are skipped at startup with a line in `journalctl --user -u companion`.
Things you ask it to remember go in `~/.local/share/companion/memory.toml`, which you can
edit by hand. It refuses anything that looks like a password or key.
