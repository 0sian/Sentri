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
