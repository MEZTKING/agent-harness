---
name: Canvas browser games
when: Writing a 2D game that runs in a browser canvas.
tags: [game-logic, graphics, javascript, kind:browser-game]
---
- One loop with `requestAnimationFrame`; move things by the time passed (`dt` in seconds), capped (say at 0.05) so a slow frame doesn't make objects jump through walls.
- Keep the game's state in plain objects, separate from drawing: `update(state, dt, input)` then `draw(ctx, state)`. That makes the rules testable without a canvas.
- Read keys into a set on `keydown`/`keyup`; read it in `update`, not in the event handler.
- Scale the canvas for sharp pictures: set its width and height to the CSS size times `devicePixelRatio`, then `ctx.scale`.
- Load every picture and sound before the first frame; show a simple "Loading" until then.
- Collisions: axis-aligned boxes are enough for most games; resolve one axis at a time.
- Pause when the tab is hidden (`visibilitychange`) and give the player a key to pause.
- Sounds start only after the first click or key press (browsers block them before).
- Keep a fixed playable size and letterbox it, rather than letting the play area change with the window.
