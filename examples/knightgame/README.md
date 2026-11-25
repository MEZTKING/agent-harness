# Knight Coin Run

A tiny browser game in a single 960x480 HTML5 canvas. A pixel-art knight walks
left and right along a tiled grass floor, jumps with the space bar, and collects
5 spinning coins. The current score is drawn in the top-left corner, and
`All coins collected!` appears when every coin has been picked up.

The whole game is plain HTML plus vanilla JavaScript in a single IIFE — there is
no CSS at all and **no libraries, no frameworks, no build step, no `npm
install`**. There are exactly three image files, and pixel art is drawn with
image smoothing turned off so it stays crisp when scaled.

## How to run

You need a modern browser (Chrome, Firefox, Edge, Safari). No tooling required.

### Option 1: open the file directly

Double-click `index.html`, or drag it into a browser window. That is it.

If a browser blocks local `file://` image loads and the canvas stays blank,
open the DevTools console — the game logs
`Game failed to start because an asset could not be loaded: ...` — and use
Option 2 instead.

### Option 2: serve the folder (recommended)

From the project root:

```sh
python3 -m http.server 8000
```

Then visit <http://localhost:8000> in your browser. The game loads
`index.html`, which pulls in `game.js` and the three PNGs from `assets/`.

Any static server works equally well, for example `npx serve .`.

There is no build, test, or install command — the source files are the app.

## Controls

| Input | Action |
| --- | --- |
| `ArrowLeft` | Walk left (the knight sprite flips to face left) |
| `ArrowRight` | Walk right |
| `Space` | Jump — only when the knight is standing on the ground |

Tips:

- Hold an arrow key to walk continuously; the knight stops when the key is released.
- The knight cannot leave the canvas horizontally, so you cannot fall off the edge.
- Coins are placed at different heights, so a few of them require a jump to reach.
- Collect all 5 coins to see the win message. There is no timer and no way to lose.

## File structure

```
project-root/
├── index.html          # Page shell: the 960x480 <canvas id="gameCanvas"> + <script src="game.js">
├── game.js             # All game logic: asset loading, input, physics, collision, rendering
├── README.md           # This file
└── assets/
    ├── knight.png      # Knight sprite, 64x64, transparent background, side view
    ├── coin.png        # Coin sprite, 32x32, transparent background
    └── tile.png        # Seamless grass ground tile, 32x32
```

- `index.html` — nothing but the canvas element and the script tag; the canvas is
  `width="960" height="480"` and has the id `gameCanvas`.
- `game.js` — one self-contained IIFE (`'use strict'`), no globals, no modules.
- `assets/*.png` — the only three images the game uses, referenced by relative
  paths from `game.js` as `assets/knight.png`, `assets/coin.png`, and
  `assets/tile.png`. All three are pixel art with transparent backgrounds and are
  drawn 1:1 at their native size (knight 64x64, coin 32x32, tile 32x32).

## How it works

Everything is in `game.js`, in this order:

1. **Canvas setup** — grabs `#gameCanvas`, gets the 2D context, and sets
   `ctx.imageSmoothingEnabled = false` once. It is never re-enabled, so every
   sprite stays pixel-sharp.
2. **Asset loading** — `loadImage()` wraps each `new Image()` in a Promise.
   `Promise.all([...])` waits for the knight, coin, and tile images before the
   game starts; if any fails, a clear error is logged to the console and the
   loop never begins (no half-drawn frames).
3. **Input** — `keydown` / `keyup` listeners on `window` track the left and right
   arrow keys and queue a jump on `Space` (auto-repeat is ignored, and the
   browser's default scrolling is prevented).
4. **Update (delta time)** — the knight moves at `MOVE_SPEED = 220` px/s and is
   clamped between `x = 0` and `x = 960 - 64`. Jumping uses
   `JUMP_VELOCITY = -520` px/s with `GRAVITY = 1400` px/s², and the knight lands
   exactly on the ground top at `y = 416`. Frame deltas are clamped to 0.05 s so a
   background tab cannot teleport the player.
5. **Collection** — each coin is a 32x32 rectangle; an axis-aligned rectangle
   overlap test against the knight removes the coin and increments `score`.
6. **Rendering** (every frame) — a flat sky-blue fill above the ground, the
   32x32 grass tile repeated to fill `y = 416..480`, coins spinning via
   `Math.abs(Math.cos(elapsedTime * 4))` as a horizontal scale about their center,
   the knight (flipped with `ctx.scale(-1, 1)` when facing left), then
   `Score: N` and the win message.

The loop is `requestAnimationFrame`-driven and frame-rate independent.

## Tuning

The gameplay constants sit together near the top of `game.js` if you want to
change the feel:

| Constant | Value | Meaning |
| --- | --- | --- |
| `CANVAS_WIDTH` / `CANVAS_HEIGHT` | 960 / 480 | Canvas size (also set on the `<canvas>` element) |
| `TILE_SIZE` | 32 | Ground tile size in pixels |
| `GROUND_TOP` | 416 | Y coordinate where the grass surface starts |
| `MOVE_SPEED` | 220 | Walking speed in px/s |
| `JUMP_VELOCITY` | -520 | Initial upward jump velocity in px/s |
| `GRAVITY` | 1400 | Downward acceleration in px/s² |

Coin layout lives in the `positions` array inside `createCoins()` (5 entries, each
`{ x, y }` for the coin's top-left corner).

## Notes and limitations

- Only keyboard input is supported; there are no touch or gamepad controls.
- There is no sound, no high-score persistence, and no restart — reload the page
  to play again.
- The game is designed for the fixed 960x480 canvas and does not scale itself to
  the window; the browser page simply scrolls on smaller screens.
- The three sprites were generated as pixel art; they are plain PNGs, so you can
  swap in replacements as long as you keep the file names and dimensions
  (or update `KNIGHT_WIDTH`/`KNIGHT_HEIGHT` and `COIN_SIZE` in `game.js`).
