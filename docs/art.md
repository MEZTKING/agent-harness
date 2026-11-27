# Darkness Harness art: the Eclipse look

Every picture here was made by a specialised image model through Roundtable's own picture provider
(`providers/chat_images.py`, `ChatImagesProvider("openrouter_images")`, OpenRouter), then only cut to
size with Pillow (crop, resize, a see-through layer from the glow's brightness). Nothing is drawn by hand
in SVG or CSS; code draws only the chrome (borders, gradients, the lights and the flare on the ring).
Prompts name no artist, game, film or brand. Masters are kept outside the repository.

Made on 2026-11-27. Budget: $15 cap. **Total spent: $0.89** (the real charges OpenRouter
reported for each picture, including one icon try not used).

## The pieces

| File | Size | Made from | Model | Cost |
|---|---|---|---|---|
| `src/roundtable/ui/static/eclipse.webp` | 1280 × 720 | Home backdrop | `openai/gpt-5.4-image-2` (16:9) | $0.132 |
| `src/roundtable/ui/static/ring.webp` | 640 × 640, see-through | cut from the same backdrop | (same picture) | $0 |
| `src/roundtable/ui/static/emblem.png` | 128 × 128 | the app icon | `openai/gpt-5.4-image-2` | $0.230 |
| `src/roundtable/ui/static/icon.png` | 64 × 64 (favicon) | the app icon | (same picture) | $0 |
| `packaging/darkness.ico` | 16, 24, 32, 48, 64, 128, 256 | the app icon (sizes 32 and under cropped closer, so the ring stays readable) | (same picture) | $0 |
| `packaging/darkness.png` | 256 × 256 | the app icon | (same picture) | $0 |
| `mobile/app/src/main/res/mipmap-*/ic_launcher_foreground.png` | 108 to 432 | the app icon on its own black, inside the adaptive icon's safe zone | (same picture) | $0 |
| `src/roundtable/ui/static/wordmark.webp` | 944 × 149, see-through | the wordmark | `openai/gpt-5.4-image-2` | $0.228 |
| `mobile/app/src/main/res/drawable-nodpi/eclipse_phone.webp` | 768 × 1376 | phone backdrop | `google/gemini-3.1-flash-image` (9:16) | $0.067 |
| (not used) | | a first, flatter icon | `openai/gpt-5.4-image-2` | $0.229 |

Notes for the people placing the art:
- `eclipse.webp` already has the ring in it, centred, about 70 % of the picture's height, with calm empty
  space left and right for panels. `ring.webp` is that same ring alone (the colour un-premultiplied, the
  brightness as see-through), for when the ring must move or pulse on its own (the phone, the small ring in
  the heading). Over plain black it looks the same as the backdrop's ring.
- The wordmark is see-through; put it on dark backgrounds only.
- The launcher foreground is opaque (it brings its own black), so the adaptive icon's `@color/ink`
  background no longer shows; the phone helper may still set `ink` to the new background `#0a0a0f`.
- The adaptive icon had no monochrome layer before, so none was added.

## Checks

Each final piece was looked at by eye; the wordmark reads "Darkness Harness", spelled right. The icon was
checked at 16, 48 and 512 px on black and on white, and under round and square launcher masks.
`tests/test_art.py` keeps every file present and under its size cap.

## Prompts

**Home backdrop** (`eclipse.webp`, `ring.webp`), `openai/gpt-5.4-image-2`, aspect 16:9:

> A wide cinematic 16:9 digital painting for the home screen of a dark software app. Near-black deep space background (#0a0a0f, faint indigo haze), very subtle. In the exact centre, a total solar eclipse seen face-on: a perfectly round black disc surrounded by a thin, crisp, glowing violet-white corona ring (lavender #a78bfa fading to white at the rim), with soft wispy corona filaments drifting outward a little. The ring fills about 70% of the image height. Inside the disc: pure empty black. The left third and right third of the image are calm, nearly black empty space with only the faintest dust and two or three very dim distant stars, leaving room for interface panels. One faint, very thin concentric orbit line around the ring. No text, no letters, no logos, no interface, no people, no planets. Elegant, minimal, high contrast, sharp ring edge, photographic quality.

**App icon** (`emblem.png`, `icon.png`, `darkness.ico`, `darkness.png`, launcher icons), `openai/gpt-5.4-image-2`, 1:1:

> A square app icon, 1:1, centred, bold so it stays readable at 16 pixels. Background: solid near-black (#0a0a0f) filling the whole square edge to edge, no border, no tile, no frame. In the centre: a total solar eclipse as a symbol: a perfectly round pure black disc ringed by a bright, crisp white-hot rim that blends into a thick glowing violet corona (lavender #a78bfa), with short soft corona rays fanning outward evenly all around. The whole eclipse is about 72% of the square. At the ring's upper right, one small bright warm orange flare of light (#ff9d4d) breaking out of the rim, with a short soft orange glow. Luminous, premium, high contrast, symmetrical. No text, no letters, no other shapes, no stars.

**Wordmark** (`wordmark.webp`), `openai/gpt-5.4-image-2`:

> A wide horizontal wordmark logo on a solid pure black background (#000000). The exact text, spelled correctly, in one line: "Darkness Harness" (capital D, capital H, two words: D-a-r-k-n-e-s-s H-a-r-n-e-s-s). Lettering: a clean, modern geometric sans-serif in semi-bold weight with slightly tight letter spacing, coloured soft violet-white (#ecebf4) with a faint lavender glow (#a78bfa) at the edges, like light from an eclipse corona. The letter O-like shapes are plain. Centred, generous empty black margins, nothing else in the image: no symbol, no ring, no tagline, no other words, no reflections.

**Phone backdrop** (`eclipse_phone.webp`), `google/gemini-3.1-flash-image`, aspect 9:16:

> A tall 9:16 phone wallpaper for a dark app. Near-black deep space (#0a0a0f, faint indigo haze), very subtle. In the upper third, centred horizontally: a total solar eclipse seen face-on, a perfectly round black disc with a thin, crisp, glowing violet-white corona ring (lavender #a78bfa fading to white at the rim) with soft wispy filaments drifting outward. The ring is about 75% of the image width. The lower half of the image is calm, almost empty black space with only faint dust, leaving room for a list of cards. No text, no letters, no interface, no people, no planets. Minimal, elegant, sharp ring edge.

**Icon try not used**, `openai/gpt-5.4-image-2`, 1:1 (a flat lavender band; clear at 16 px but plainer
than the backdrop):

> A square app icon, 1:1, centred, bold and simple so it stays readable at 16 pixels. Background: solid near-black (#0a0a0f) filling the whole square, no border, no rounded tile, no frame. In the centre: a thick, glowing violet-white ring of light like the corona of a total solar eclipse (lavender #a78bfa with a bright white inner rim), the inside of the ring pure black. The ring's diameter is about 70% of the square and its band is thick. At the ring's upper right, one small bright warm orange point of light (#ff9d4d) sitting on the ring like a flare, with a soft orange glow. Soft violet glow around the ring, but crisp edges. Flat, clean, iconic, symmetrical, high contrast. No text, no letters, no other shapes, no stars.
