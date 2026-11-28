"""Right to left on the desktop: Arabic, Hebrew, Persian and Urdu turn the page round; what can't turn by itself
is in rtl.css; the turn from left and right to logical properties leaves nothing physical but what must stay."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from roundtable import words as W

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/roundtable/ui/static"
PHYSICAL = re.compile(r"(?<![-\w])(left|right)\s*:|(margin|padding|border)-(left|right)\b|text-align:\s*(left|right)")

sys.path.insert(0, str(ROOT / "tools"))
import words_sweep as SW  # noqa: E402


def test_which_languages_run_right_to_left():
    assert [c for c in W.LANGS if W.rtl(c)] == ["ar", "he", "fa", "ur"]
    assert not W.rtl("en-GB") and not W.rtl("ja") and W.rtl("ar-EG")


def test_the_new_desktop_files_use_logical_properties_only():
    for name in ("rtl.css", "language.js", "words.js"):
        text = (STATIC / name).read_text(encoding="utf-8")
        assert not PHYSICAL.search(text), name


def test_rtl_css_holds_only_what_logical_properties_cannot_do():
    css = (STATIC / "rtl.css").read_text(encoding="utf-8")
    assert ':root[dir="rtl"] .ring > .ring-card' in css  # the ring's centring turns round
    assert "direction: ltr" in css and "unicode-bidi: isolate" in css  # code, paths, money stay left to right
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(", css)  # no colours of its own: the tokens' only
    assert "url(" not in css  # no pictures drawn or loaded here


def test_after_the_turn_style_css_has_nothing_physical_but_the_ring_s_centre_and_a_tick():
    out, n = SW.logical_css((STATIC / "style.css").read_text(encoding="utf-8"))
    left = [m.group(0) for line in out.splitlines() if PHYSICAL.search(line)
            for m in [PHYSICAL.search(line)] if not any(k in line for k in SW.KEEP_PHYSICAL)]
    assert left == [] and n >= 30


def test_the_modules_own_styles_turn_too():
    rest = []
    for p in sorted(STATIC.glob("*.js")):
        out, _ = SW.logical_js(p.read_text(encoding="utf-8"))
        for tk in SW.X.tokens(out):
            raw = out[tk.start:tk.end]
            if tk.kind in ("str", "tpl") and "{" in raw and ";" in raw and PHYSICAL.search(raw):
                rest.append((p.name, PHYSICAL.search(raw).group(0)))
    assert rest == []
