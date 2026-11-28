"""Turn template strings the owner reads into ``t(…)`` calls, so they pass through the language table.

    python tools/words_sweep.py              # rewrite ui/static/*.js in place, then run words_extract.py
    python tools/words_sweep.py --dry-run    # say what would change, write nothing
    python tools/words_sweep.py a.js b.js    # only these files
    python tools/words_sweep.py --css        # also left/right in style.css and the modules' own styles
                                             # turned into logical properties (right to left)

Mechanical and nothing else: ``h("p", {}, `${n} for you`)`` becomes ``h("p", {}, t("{n} for you", { n }))``. A
value's hole is named after it (``p.name`` → ``{name}``; anything else ``{v1}``, ``{v2}``…). Only template strings
at the places words_extract.py reads are touched; one whose text has its own curly brackets is left as it is.
A module that gets a ``t(…)`` gains ``import { t } from "./words.js";`` (or uses ``words.t`` where it imports
the module whole, or ``wt`` where it already has a ``t`` of its own). Run by the coordinator after the merges,
so no helper's files clash.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import words_extract as X  # noqa: E402

SKIP = {"words.js", "core.js"}  # the table itself; core.js is the seam (its few go by hand)
IMPORT = 'import { t } from "./words.js";'
_IDENT_PATH = re.compile(r"\s*([A-Za-z_$][\w$]*(?:\s*\??\.\s*[A-Za-z_$][\w$]*)*)\s*")


def _name_for(expr: str, used: dict[str, str], counter: list[int]) -> str:
    m = _IDENT_PATH.fullmatch(expr)
    base = re.split(r"\??\.", m.group(1))[-1].strip() if m else ""
    if base and not base.startswith("$"):
        name, i = base, 2
        while name in used and used[name] != expr.strip():
            name, i = f"{base}{i}", i + 1
        return name
    for name, e in used.items():
        if e == expr.strip() and re.fullmatch(r"v\d+", name):
            return name
    counter[0] += 1
    return f"v{counter[0]}"


def rewrite_template(tok: X.Tok, fn: str) -> str | None:
    """The ``t(…)`` call for one template token, or None when it is to be left alone."""
    parts = tok.parts
    if len(parts) < 2 or not any(X.has_letters(lit) for lit, _ in parts):
        return None
    if any("{" in lit or "}" in lit for lit, _ in parts):
        return None
    used: dict[str, str] = {}
    counter = [0]
    text = []
    for lit, expr in parts:
        text.append(X._cook(lit))
        if expr is None:
            continue
        if not expr.strip():
            return None
        name = _name_for(expr, used, counter)
        used.setdefault(name, expr.strip())
        text.append("{" + name + "}")
    vals = ", ".join(name if name == e else f"{name}: {e}" for name, e in used.items())
    return f"{fn}({json.dumps(''.join(text), ensure_ascii=False)}, {{ {vals} }})"


def _fn_name(src: str) -> tuple[str, bool]:
    """(the name to call, whether an import line is needed)."""
    if re.search(r'^import \* as words from "\./words\.js";', src, re.M):
        return "words.t", False
    if re.search(r'^import \{[^}]*\bt\b[^}]*\} from "\./words\.js";', src, re.M):
        return "t", False
    toks = X.tokens(src)
    for i, tk in enumerate(toks):
        if tk.kind == "ident" and tk.value == "t":
            before = toks[i - 1] if i else None
            if not (before is not None and before.kind == "punct" and before.value in (".", "?.")):
                if re.search(r'^import \{[^}]*\bt as wt\b[^}]*\} from "\./words\.js";', src, re.M):
                    return "wt", False
                return "wt", True
    return "t", True


def sweep_text(src: str) -> tuple[str, int]:
    """(the module with its template strings turned into t(…), how many were turned)."""
    fn, need_import = _fn_name(src)
    edits = []
    for s in X.sites(src):
        if s.tok.kind != "tpl" or s.joined or s.why == "key":
            continue
        new = rewrite_template(s.tok, fn)
        if new is not None:
            edits.append((s.tok.start, s.tok.end, new))
    if not edits:
        return src, 0
    out = src
    for start, end, new in sorted(edits, reverse=True):
        out = out[:start] + new + out[end:]
    if need_import:
        line = IMPORT if fn == "t" else 'import { t as wt } from "./words.js";'
        imports = list(re.finditer(r"^import [^\n]*;\n", out, re.M))
        at = imports[-1].end() if imports else 0
        out = out[:at] + line + "\n" + out[at:]
    return out, len(edits)


# -- left and right into logical properties (for right-to-left languages) ------------------------------------------
KEEP_PHYSICAL = (".ring-disc", ".tick.on::after")  # centred by translate(-50%), or a tick drawn inside a box
_RULE = re.compile(r"([^{}]*)\{([^{}]*)\}")
_SWAPS = [
    (re.compile(r"\b(margin|padding)-left\s*:"), r"\1-inline-start:"),
    (re.compile(r"\b(margin|padding)-right\s*:"), r"\1-inline-end:"),
    (re.compile(r"\bborder-left(-color|-width|-style)?\s*:"), r"border-inline-start\1:"),
    (re.compile(r"\bborder-right(-color|-width|-style)?\s*:"), r"border-inline-end\1:"),
    (re.compile(r"(?<![-\w])left\s*:"), "inset-inline-start:"),
    (re.compile(r"(?<![-\w])right\s*:"), "inset-inline-end:"),
    (re.compile(r"text-align:\s*left"), "text-align: start"),
    (re.compile(r"text-align:\s*right"), "text-align: end"),
    (re.compile(r"padding:\s*(\S+) (\S+) \1 (\S+);"), r"padding-block: \1; padding-inline: \3 \2;"),
]


def logical_css(css: str) -> tuple[str, int]:
    """(css with physical left/right turned into logical properties, how many rules changed). A rule whose
    selector is in KEEP_PHYSICAL is left as it is."""
    count = [0]

    def rule(m: re.Match) -> str:
        sel, body = m.group(1), m.group(2)
        if any(k in sel for k in KEEP_PHYSICAL):
            return m.group(0)
        new = body
        for rx, to in _SWAPS:
            new = rx.sub(to, new)
        if new != body:
            count[0] += 1
        return sel + "{" + new + "}"

    return _RULE.sub(rule, css), count[0]


def logical_js(src: str) -> tuple[str, int]:
    """The same for the styles a module carries in its own strings (only strings that read as CSS)."""
    edits, total = [], 0
    for tk in X.tokens(src):
        if tk.kind not in ("str", "tpl"):
            continue
        raw = src[tk.start:tk.end]
        if "{" not in raw or ":" not in raw or ";" not in raw:
            continue
        new, n = logical_css(raw)
        if n:
            edits.append((tk.start, tk.end, new))
            total += n
    for start, end, new in sorted(edits, reverse=True):
        src = src[:start] + new + src[end:]
    return src, total


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    dry = "--dry-run" in argv
    names = [a for a in argv if not a.startswith("--")]
    paths = [Path(a) for a in names] if names else sorted(X.STATIC.glob("*.js"))
    total = 0
    if "--css" in argv:
        rules = 0
        for p in [X.STATIC / "style.css", *paths]:
            if p.name == "words.js":
                continue
            src = p.read_text(encoding="utf-8")
            new, n = (logical_css if p.suffix == ".css" else logical_js)(src)
            if n:
                rules += n
                print(f"{p.name}: {n} rules to logical properties")
                if not dry:
                    p.write_text(new, encoding="utf-8")
        print(f"{rules} rules {'would be' if dry else ''} turned".replace("  ", " "))
    for p in paths:
        if p.name in SKIP:
            continue
        src = p.read_text(encoding="utf-8")
        out, n = sweep_text(src)
        if n:
            total += n
            print(f"{p.name}: {n}")
            if not dry:
                p.write_text(out, encoding="utf-8")
    print(f"{total} template strings {'would be' if dry else ''} turned into t(…)".replace("  ", " "))
    if not dry and total and not names:
        X.main([])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
