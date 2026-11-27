"""The Eclipse look reads well in all three themes (Eclipse, Pitch, Ash).

style.css keeps every colour in one token block (between the "tokens: start" and "tokens: end" markers): `:root` is
Eclipse, `:root[data-theme="pitch"]` and `:root[data-theme="ash"]` override it. These tests read that block and check
WCAG AA: text at 4.5:1 on every background it sits on, control borders at 3:1, and text over the backdrop art on its
scrim. They also check that no colour is written anywhere else in the file.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "roundtable" / "ui" / "static"
CSS = (STATIC / "style.css").read_text(encoding="utf-8")
START, END = "/* ===== tokens: start", "/* ===== tokens: end ===== */"
THEMES = ("eclipse", "pitch", "ash")


def _block() -> str:
    a, b = CSS.index(START), CSS.index(END)
    return CSS[a:b]


def _rules(block: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for sel, body in re.findall(r"(:root[^{]*)\{([^}]*)\}", block):
        decls = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body))
        out.setdefault(sel.strip(), {}).update({k: v.strip() for k, v in decls.items()})
    return out


def tokens(theme: str) -> dict[str, str]:
    rules = _rules(_block())
    t = dict(rules[":root"])
    if theme != "eclipse":
        t.update(rules[f':root[data-theme="{theme}"]'])
    return t


def colour(t: dict[str, str], name: str) -> tuple[float, float, float, float]:
    v = t[name]
    for _ in range(5):  # follow aliases: var(--x)
        m = re.fullmatch(r"var\((--[\w-]+)\)", v)
        if not m:
            break
        v = t[m.group(1)]
    m = re.fullmatch(r"#([0-9a-fA-F]{6})([0-9a-fA-F]{2})?", v)
    assert m, f"{name} is not a plain colour: {v}"
    rgb = [int(m.group(1)[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    a = int(m.group(2), 16) / 255 if m.group(2) else 1.0
    return rgb[0], rgb[1], rgb[2], a


def over(top, bottom):
    a = top[3]
    return tuple(top[i] * a + bottom[i] * (1 - a) for i in range(3)) + (1.0,)


def lum(c) -> float:
    def ch(x):
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def ratio(a, b) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


PLAIN = ("--color-background", "--color-surface", "--color-sunken", "--color-raised")
TEXT = [  # (text token, the backgrounds it sits on)
    ("--color-text", PLAIN), ("--color-muted", PLAIN), ("--color-accent", PLAIN),
    ("--color-flare", ("--color-background", "--color-surface")),
    ("--color-good", ("--color-background", "--color-surface", "--color-good-soft")),
    ("--color-bad", ("--color-background", "--color-surface", "--color-bad-soft")),
    ("--color-warn", ("--color-background", "--color-surface", "--color-warn-soft")),
    ("--color-accent", ("--color-accent-soft",)),
    ("--color-flare", ("--color-flare-soft",)),
    ("--color-accent-text", ("--color-accent", "--color-bad")),  # main buttons, the solid danger button, error toasts
    ("--color-background", ("--color-text",)),                   # toasts
    ("--term-text", ("--term-bg",)), ("--term-muted", ("--term-bg",)), ("--term-accent", ("--term-bg",)),
    ("--term-add", ("--term-bg", "--term-add-bg")), ("--term-del", ("--term-bg", "--term-del-bg")),
]


@pytest.mark.parametrize("theme", THEMES)
def test_text_reads_at_aa(theme):
    t = tokens(theme)
    bad = []
    for fg, bgs in TEXT:
        for bg in bgs:
            r = ratio(colour(t, fg), colour(t, bg))
            if r < 4.5:
                bad.append(f"{fg} on {bg}: {r:.2f}")
    assert not bad, f"{theme}: " + "; ".join(bad)


@pytest.mark.parametrize("theme", THEMES)
def test_control_borders_reach_three_to_one(theme):
    t = tokens(theme)
    for bg in ("--color-background", "--color-surface", "--color-sunken"):
        r = ratio(colour(t, "--color-line-strong"), colour(t, bg))
        assert r >= 3.0, f"{theme}: --color-line-strong on {bg}: {r:.2f}"


@pytest.mark.parametrize("theme", THEMES)
def test_text_over_the_backdrop_reads_on_its_scrim(theme):
    t = tokens(theme)
    under = over(colour(t, "--color-scrim"), colour(t, "--color-backdrop-peak"))  # the worst place: the brightest art
    for fg in ("--color-text", "--color-muted"):
        r = ratio(colour(t, fg), under)
        assert r >= 4.5, f"{theme}: {fg} over the backdrop's scrim: {r:.2f}"


def test_backdrop_art_is_no_brighter_than_the_peak_where_text_sits():
    art = STATIC / "eclipse.webp"
    if not art.exists():
        pytest.skip("the backdrop art isn't in yet")
    image = pytest.importorskip("PIL.Image")
    with image.open(art) as im:
        w, h = im.size
        mid = im.convert("RGB").crop((int(w * .4), int(h * .42), int(w * .6), int(h * .58)))  # the ring's middle, where the words sit
        px = sorted(lum(tuple(v / 255 for v in p) + (1.0,)) for p in mid.get_flattened_data())
    peak = lum(colour(tokens("eclipse"), "--color-backdrop-peak"))
    assert px[int(len(px) * .95)] <= peak, "the backdrop is brighter than --color-backdrop-peak where the ring's words sit"


def test_every_theme_sets_the_same_core_tokens():
    base = tokens("eclipse")
    for name in ("--color-background", "--color-surface", "--color-text", "--color-muted", "--color-accent", "--color-accent-text",
                 "--color-flare", "--color-good", "--color-bad", "--color-warn", "--color-line", "--color-line-strong",
                 "--color-scrim", "--color-backdrop-peak"):
        assert name in base, name
    for theme in THEMES:
        t = tokens(theme)
        for name in base:
            if name.startswith("--color-") and "var(" not in base[name]:
                colour(t, name)


def test_no_colour_outside_the_token_block():
    rest = CSS[:CSS.index(START)] + CSS[CSS.index(END):]
    rest = re.sub(r"/\*.*?\*/", "", rest, flags=re.S)
    found = re.findall(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(", rest)
    assert not found, found
    for f in [p.name for p in sorted(STATIC.glob("*.js"))] + ["index.html"]:
        text = (STATIC / f).read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{6}\b|\brgba?\(", text), f


def test_old_candle_and_oak_names_are_gone():
    for f in ("style.css", "hall.js", "index.html", "theme.js"):
        body = (STATIC / f).read_text(encoding="utf-8")
        for old in ("candle", "oak", "flame", "chair", "cdl", "table-top", "seat-", "hall.webp", "table.webp", "fraunces", "nunito"):
            assert old not in body.lower(), (f, old)


def test_old_token_names_are_gone_everywhere():
    old = re.compile(r"--color-(oak-line|candle-glow|ember|gold|ok)(?![\w-])|--color-ok-soft")
    for f in sorted(STATIC.glob("*.js")) + [STATIC / "style.css", STATIC / "index.html"]:
        assert not old.search(f.read_text(encoding="utf-8")), f.name


def test_motion_stops_when_asked():
    assert "@media (prefers-reduced-motion: reduce)" in CSS
    assert re.search(r"--breathe:\s*6s", _block()) and re.search(r"--flare-in:\s*400ms", _block())


def test_fonts_are_bundled():
    for name in ("space-grotesk.woff2", "inter.woff2", "inter-italic.woff2", "jetbrains-mono.woff2"):
        assert (STATIC / name).stat().st_size > 10_000, name
        assert f"url({name})" in CSS, name
