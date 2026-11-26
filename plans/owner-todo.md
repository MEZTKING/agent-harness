# Waiting for the owner

Newest first. Each item says what to do and where.

## Now

- **The music player build** (the yardstick): task 1 is done; task 2 is being run on its
  own to measure the real cost per task against the DeepSeek balance. Then: carry on,
  or change the plan, once the true total is known.
- **Try Roundtable Mobile on your phone** (`RoundtableMobile-test.apk`, sent 25
  November): say what's unclear or missing. It works in Hub mode with a fine-grained
  GitHub token (only `agent-hub-data`, Contents read and write).

## When you're at your PC

- **Two cloud environments** need the setup lines pasted by hand (Settings → the
  environment → Setup script): "Magnum" and "mse studio". `roundtable connect --cloud-script`
  prints them (README, "Connect Claude Code sessions"). Far Worlds is left out for now.
- **Add a `critic` role** in the desktop app (Settings → Roles), for example DeepSeek V4
  Pro with Opus as the fallback, so every plan gets a second opinion.
- **DeepSeek prices**: check the current prices (including the cache-hit price) on
  DeepSeek's site, so Roundtable's counts match your bill.
- **GitHub:** set `main` as the default branch of `agent-harness`.

## Before the phone app is released

- **A release signing key** for the Android app, kept as a repository secret (not in
  git). Without it the app can't be updated over the installed test version.
- **Try PC mode** with the desktop app on the same Wi-Fi (pairing by QR code).

## Decided for you

- Answers to a plan's questions can be sent from chat or the phone; nothing is built
  until you approve.
- The music player: under 1 GB of music, all up-to-date browsers, the planner's
  recommendations, the storage meter, the up-next queue, crossfade and sortable
  columns; Next and Back work like a real player; the queue starts fresh each visit.
