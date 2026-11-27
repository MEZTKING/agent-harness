# Your phone and your PC: what's kept, where it goes

Short version: the phone talks only to your own PC, GitHub and (if you use it) the harness on the
phone itself. Everything secret is locked on the phone. If you lose the phone, remove it on the PC
in **Settings → Your phone** and it can't get in any more.

## What the phone keeps

| What | Where | How it's kept |
|---|---|---|
| Your PC's name, addresses, port and certificate fingerprint | Phone, app's own storage | Locked with a key in Android's keystore |
| The phone's own pass for your PC (a random token) | Phone, app's own storage | Locked the same way; the PC keeps only a scrambled copy (its hash) |
| Your GitHub token, if you use the hub without the PC | Phone, app's own storage | Locked the same way |
| A copy of the last Hall screen, which messages you've been told about | Phone, app's own storage | Locked the same way |
| Drafts and pictures you're about to send | Phone, app's own folder (`drafts`) | Only this app can read it; cleared once sent |
| The harness on this phone (if you set it up): its files and API keys | Phone, app's own folder (`runtime`) | Only this app can read it; keys stay with it |

Nothing is backed up to Google: backups are switched off for this app. Uninstalling the app
deletes all of it.

## What the phone connects to

- **Your PC**, on your Wi-Fi or through Tailscale, port 8766 by default. Always encrypted (HTTPS).
  The phone trusts exactly one certificate: the one your PC made, whose fingerprint came in the
  pairing QR code. Anything else on the network – someone posing as your PC – is refused.
- **Looking for your PC on the Wi-Fi** (only when you press **Look for my PC**): the phone asks
  "is Roundtable here?" on the Wi-Fi, port 8767. Your PC answers with its name, port and
  fingerprint – never the pairing code, and only to devices on a home or office network.
  - A PC you already paired: the phone only takes a new address from an answer with *the same*
    fingerprint, and the encrypted connection checks it again.
  - Pairing without the QR code: you type the 8-letter code shown on the PC. Its last two letters
    are worked out from the PC's certificate, so the phone checks the code against the PC that
    answered *before* sending it. A stand-in on the same Wi-Fi fails the check and never sees
    your code. (One stand-in in about a thousand could pass the check by luck; the QR code has no
    such gap, so use it when you can.)
- **GitHub** (api.github.com): the hub, if you use it without the PC, and checking for app updates.
- **The harness on this phone** (127.0.0.1, the phone itself): the only place the app talks to
  without encryption, because it never leaves the phone.

The PC's phone server lets a phone do only what's on its list: the Hall, projects, chat,
messages, files to read, the hub. Settings, API keys, providers and updates stay on the PC.

## Pairing

1. On the PC: **Settings → Your phone → Pair a phone**. A code shows for 5 minutes; five wrong
   tries end it.
2. On the phone: scan the QR code (best), or press **Look for my PC** and type the code.
3. The PC gives the phone its own pass and keeps only a scrambled copy of it.

## If you lose the phone

On the PC: **Settings → Your phone**, then **Remove** next to it. The phone's pass stops working
straight away. If you also gave the phone a GitHub token, delete that token on GitHub too.

Turning off phone access on the PC stops the phone server and the Wi-Fi answer at once.
