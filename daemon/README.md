# Companion daemon

Turns your phone into a trackpad + keyboard for this PC. Works on KDE Plasma and
Hyprland (it injects through `/dev/uinput`, below the compositor).

## Install (CachyOS / Arch)

```fish
cd companion/daemon
python -m venv .venv
source .venv/bin/activate.fish
pip install -r requirements.txt
```

## One-off uinput permission

```fish
sudo cp 99-companion-uinput.rules /etc/udev/rules.d/
sudo usermod -aG input $USER
echo uinput | sudo tee /etc/modules-load.d/uinput.conf
sudo modprobe uinput
sudo udevadm control --reload && sudo udevadm trigger
# log out and back in so the group applies
```

## Run

```fish
./companion_daemon.py                 # UK layout, port 8765
./companion_daemon.py --layout us     # if you type on a US layout
```

It prints the LAN address and the pairing token (also stored in
`~/.config/companion/token`). Enter both in the phone app once.

## Autostart (both KDE and Hyprland)

```fish
mkdir -p ~/.config/systemd/user
cp companion.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now companion.service
```

Edit the `ExecStart=` path in `companion.service` first if you don't keep it in
`~/companion/daemon`.

## Security notes

- The token never crosses the network: the phone proves it knows it with an
  HMAC over a one-time nonce.
- Traffic itself is plain `ws://`. Fine on your home LAN; away from home, go over
  Tailscale/WireGuard rather than exposing port 8765 to the internet.
- Whoever has the token controls your mouse and keyboard. Keep the token file private
  (it is created `chmod 600`). Delete it and restart to rotate.
- Firewall: open TCP 8765 to your LAN only, e.g. `sudo ufw allow from 192.168.0.0/16 to any port 8765`.
