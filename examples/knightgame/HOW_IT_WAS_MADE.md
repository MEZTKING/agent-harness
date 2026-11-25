# How this example was made

This whole folder was produced by **one command**, with no human edits to the game code or art:

```bash
harness new knightgame "A tiny browser game: index.html + game.js using only the HTML5 canvas (no libraries, no build step). A knight walks left/right with the arrow keys and jumps with space on a ground made of tiles, collecting spinning coins; show the score. Use generated pixel-art assets: a knight sprite (64x64, transparent background, side view), a coin (32x32, transparent), and a seamless grass ground tile (32x32). Draw sprites with image smoothing disabled. Include a README saying how to run it. Generate at most 3 images."
```

## Routing used

| Role | Model |
|---|---|
| orchestrator (planner) | `deepseek/deepseek-v4-pro` |
| coder | `deepseek/deepseek-v4-pro` (fallback `deepseek/deepseek-flash`) |
| manager (README) | `deepseek/deepseek-flash` |
| reviewer | `deepseek/deepseek-flash` |
| designer (pixel art) | `retrodiffusion/rd_lite__default`; the planner chose a style per asset |

## The plan the orchestrator made

| Task | Role | Title | Model / style | Attempts |
|---|---|---|---|---|
| T1 | designer | Generate knight sprite asset | `retrodiffusion/rd_lite__default` / `rd_lite__platformer` | 1 |
| T2 | designer | Generate coin sprite asset | `retrodiffusion/rd_lite__default` / `rd_lite__topdown` | 1 |
| T3 | designer | Generate seamless grass ground tile asset | `retrodiffusion/rd_lite__default` / `rd_tile__single_tile` | 1 |
| T4 | coder | Implement the canvas game | `deepseek/deepseek-v4-pro` | 1 |
| T5 | manager | Write README | `deepseek/deepseek-flash` | 1 |

Every task was approved by the reviewer on its first attempt. Total spend: **$0.16** for the 3 images (Retro Diffusion reports exact prices). The DeepSeek calls weren't priced in that config.

## The harness's own completion report

# Knight Coin Run — Project Report

## What was built
A tiny, dependency-free browser game rendered on an HTML5 canvas:

- **Knight Coin Run** in `index.html` + `game.js` with no libraries and no build step.
- A knight moves left/right with the arrow keys and jumps with the spacebar.
- A seamless grass-tile ground runs along the bottom of the 960×480 canvas.
- Five spinning coins are placed at reachable heights; collecting one increments the score.
- When all coins are collected, the game shows `All coins collected!`.
- Pixel-art assets were generated and are stored under `assets/`:
  - `knight.png` — 64×64 transparent knight sprite
  - `coin.png` — 32×32 transparent coin sprite
  - `tile.png` — 32×32 seamless grass tile
- The game draws sprites with `imageSmoothingEnabled = false` to preserve the pixel-art look.
- Movement is frame-rate independent using delta time, clamped to 0.05 s per frame.

## How to run/use it

Recommended:

```bash
python3 -m http.server 8000
```

Then open `http://localhost:8000`.

Alternatively, open `index.html` directly in a browser. If the assets fail to load from `file://`, use the local-server method above.

### Controls

| Key | Action |
| --- | --- |
| `ArrowLeft` | Walk left (sprite flips) |
| `ArrowRight` | Walk right |
| `Space` | Jump (only when on the ground) |

## Known limitations / next steps

- Keyboard-only input; no touch or on-screen controls.
- Fixed 960×480 canvas with no responsive scaling.
- No audio, persistence, high-score saving, or restart button.
- No fail state — the game is purely a short collection challenge.
- The three generated assets are static; animations are currently limited to flipping the knight and spinning coins via canvas transforms.

Useful next steps could include:

- Adding a restart button or `R` key to reset coins and score.
- Adding simple sound effects and background music.
- Adding more levels, moving platforms, or enemies.
- Adding mobile/touch controls.
- Replacing the static knight with a multi-frame run/jump animation.
