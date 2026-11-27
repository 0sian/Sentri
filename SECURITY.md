# Security

Sentri lets a phone move your mouse, press keys and, if you enable the AI companion, act on your PC. That is a lot of
power, so this page says plainly what protects it and what doesn't.

## What it protects against

- **Someone on your network who doesn't know the token.** Pairing uses an HMAC challenge-response over a one-time
  nonce. The token itself never crosses the network.
- **A leaked chat or screen.** The Anthropic API key lives only in `~/.config/companion/ai.toml` on the PC (the daemon
  refuses to read it unless it is mode 600). It is never sent to the phone and never logged. The daemon's logs hold
  message types and lengths, never what you typed or said.
- **The AI doing something you didn't approve.** Anything risky (typing, key presses, closing windows, opening links,
  screenshots, reading the clipboard, running a saved command) needs an Allow tap on the phone, and no answer means no.
  Raw shell, `sudo`, writing or deleting files, and arbitrary network requests are never offered to the model.
- **A runaway bill.** Replies and tool rounds are capped, and `daily_token_cap` bounds spend.

## What it does not protect against

- **Anyone who has the token.** They control your mouse and keyboard. The token file is created mode 600; delete it and
  restart the daemon to rotate it.
- **Traffic being read or changed on the wire.** The link is plain `ws://`, not TLS. On a home LAN that is a reasonable
  trade-off. Away from home, run it over Tailscale or WireGuard. **Never expose port 8765 to the internet**, and allow
  it from your LAN only in the firewall.
- **A hostile phone app or an unlocked phone.** Sentri has no lock screen of its own by design: anyone holding your
  unlocked phone could equally sit at your keyboard.
- **Screenshots sent to the AI.** When you approve a screenshot, it goes to the API provider.

Not done yet, and listed in the README: TLS or pinned-certificate pairing and QR-code pairing.

## Input device permissions

The daemon needs `/dev/uinput`. Use the dedicated `uinput` group described in `daemon/README.md`. Do **not** add yourself
to the `input` group: that would let every process you run read your physical keyboard.

## Reporting a problem

Please report vulnerabilities privately rather than in a public issue. Either:

- use this repository's **Security** tab ("Report a vulnerability"), or
- email **git@osianj.com**.

Include what you did, what happened and what version you ran. Please don't post working exploit details in a public issue
or discussion before there's a fix.
