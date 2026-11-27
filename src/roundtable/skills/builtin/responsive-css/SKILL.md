---
name: Responsive pages with CSS
when: Laying out or styling pages that must work on phones and big screens.
tags: [css, styling, layout, html]
---
- Start with the phone layout, then widen with `@media (min-width: ...)`; include `<meta name="viewport" content="width=device-width, initial-scale=1">`.
- Use CSS custom properties (`--color-text`, `--space-2`) for colours and spacing so they change in one place.
- Flexbox for a row or a column of things; grid for two-dimensional layouts (`grid-template-columns: repeat(auto-fill, minmax(240px, 1fr))`).
- Sizes in `rem` for text, `%`, `fr` or `min()`/`clamp()` for widths; avoid fixed pixel widths on containers.
- Images: `max-width: 100%; height: auto;` and give them width and height attributes so the page doesn't jump.
- Keep a readable line length (about 60 to 80 characters: `max-width: 70ch`).
- Respect `prefers-reduced-motion` and `prefers-color-scheme` where the project has motion or a dark look.
- No horizontal scrolling at 320 pixels wide: check it.
