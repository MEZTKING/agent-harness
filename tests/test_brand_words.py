"""The owner never reads the old name: no "Roundtable" in a string the desktop app serves.

The app is Darkness Harness from 1.0.0 (`roundtable.brand`). Names machines read keep the old
words on purpose (the `roundtable` command, `%APPDATA%\\RoundtableHold`, the backups folder, the
phone's readiness line, the `roundtable:` hub prefix, which is lower case and so never matches),
so they sit in ALLOWED below with the reason. Comments and docstrings aren't served, so they're
not checked. A string still waiting on another helper's file sits in PENDING: once that file is
renamed, its line here must go (the test says so).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from roundtable import brand

SRC = Path(__file__).resolve().parents[1] / "src" / "roundtable"
STATIC = SRC / "ui" / "static"
OLD = "Roundtable"

# (file relative to src/roundtable, a piece of the string): kept on purpose.
ALLOWED = {
    ("brand.py", brand.LEGACY_NAME): "what installed copies were called: the legacy name itself",
    ("brand.py", brand.LEGACY_EXE): "the old app file, removed by the installer",
    ("brand.py", brand.LEGACY_SWITCHED): "journal entries written before 1.0.0 are still read",
    ("desktop.py", "RoundtableHold"): "the data folder %APPDATA%\\RoundtableHold is never moved",
    ("desktop.py", "Roundtable Hold"): "the key store's old service name, read as a fallback",
    ("desktop.py", "Roundtable Projects"): "an existing projects folder stays where it is",
    ("backup.py", "Roundtable backups"): "the folder the backups already live in",
    ("onphone.py", "Roundtable is ready on"): "the line the phone app waits for (its readiness prefix)",
    ("phone.py", "Roundtable Hold on "): "the pinned TLS certificate's name; the phone pins it, so it's never remade",
    ("money.py", "Roundtable"): "a User-Agent: read by a web server, not the owner",
    ("harness/scout.py", "RoundtableHold/1"): "a User-Agent",
    ("harness/websearch.py", "RoundtableHold/1"): "a User-Agent",
    ("hub/mcp_server.py", "formerly Roundtable Hold"): "agents in other repositories knew the old name",
    ("ui/static/core.js", brand.LEGACY_NAME): "BRAND.legacy, the legacy name itself",
}

# Strings in files another helper of the 1.0.0 rename owns. Remove each line once its file is done.
PENDING: dict = {
}


def _py_strings(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docs.add(id(first.value))
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def _js_strings(text: str) -> list[tuple[int, str]]:
    """The string and template literals of a JS file, with comments and regex literals skipped."""
    out, i, n, line = [], 0, len(text), 1
    prev = ""  # the last significant character, to tell a regex from a division
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            line += text.count("\n", i, j)
            i = n if j < 0 else j + 2
            continue
        if c in "\"'`":
            j, start = i + 1, line
            while j < n and text[j] != c:
                if text[j] == "\\":
                    j += 1
                elif text[j] == "\n":
                    line += 1
                j += 1
            out.append((start, text[i + 1:j]))
            i, prev = j + 1, c
            continue
        if c == "/" and (prev in "(,=:[!&|?{};+-*%<>~^" or prev == ""):
            j = i + 1
            while j < n and text[j] not in "/\n":
                if text[j] == "\\":
                    j += 1
                elif text[j] == "[":  # a class can hold a slash
                    while j < n and text[j] != "]":
                        j += 2 if text[j] == "\\" else 1
                j += 1
            i, prev = j + 1, "/"
            continue
        if not c.isspace():
            prev = c
        i += 1
    return out


def _html_text(text: str) -> list[tuple[int, str]]:
    return [(text.count("\n", 0, m.start()) + 1, m.group(0)) for m in re.finditer(r"[^<>\"]*" + OLD + r"[^<>\"]*", text)]


def _found() -> list[tuple[str, int, str]]:
    found = []
    for p in sorted(SRC.rglob("*.py")):
        found += [(p.relative_to(SRC).as_posix(), ln, s) for ln, s in _py_strings(p) if OLD in s]
    for p in sorted(STATIC.glob("*.js")):
        found += [(p.relative_to(SRC).as_posix(), ln, s) for ln, s in _js_strings(p.read_text(encoding="utf-8")) if OLD in s]
    for p in sorted(STATIC.glob("*.html")):
        found += [(p.relative_to(SRC).as_posix(), ln, s) for ln, s in _html_text(p.read_text(encoding="utf-8"))]
    return found


def _kept(f: str, s: str) -> bool:
    return any(f == kf and piece in s for (kf, piece) in (*ALLOWED, *PENDING))


def test_no_old_name_in_anything_the_app_serves():
    bad = [f"{f}:{ln}: {s[:120]!r}" for f, ln, s in _found() if not _kept(f, s)]
    assert not bad, ("The owner would read the old name here. Use brand.NAME / BRAND.name, or \"the harness\" "
                     "in a running sentence; if a machine reads it, add it to ALLOWED with the reason:\n  "
                     + "\n  ".join(bad))


def test_every_kept_line_is_still_needed():
    """An ALLOWED or PENDING line nothing matches any more is out of date: take it out."""
    found = _found()
    stale = [f"{k} ({why})" for k, why in {**ALLOWED, **PENDING}.items()
             if not any(f == k[0] and k[1] in s for f, _, s in found)]
    assert not stale, "No longer needed, remove from tests/test_brand_words.py:\n  " + "\n  ".join(stale)


def test_the_js_reader_finds_strings_and_skips_comments():
    src = ('// Roundtable in a comment\nconst a = "one", b = \'two\';\n/* Roundtable */ const r = /"[^/]"/g;\n'
           "const t = `three ${a}`; x = 4 / 2; y = \"after\";\n")
    assert [s for _, s in _js_strings(src)] == ["one", "two", "three ${a}", "after"]


def test_the_name_comes_from_one_place():
    core = (STATIC / "core.js").read_text(encoding="utf-8")
    assert f'name: "{brand.NAME}"' in core and f'short: "{brand.SHORT}"' in core and f'legacy: "{brand.LEGACY_NAME}"' in core


def test_old_and_new_journal_signatures_both_read_as_the_harness_choosing():
    assert brand.is_switched("Switched by Roundtable: DeepSeek V4 Pro was replaced. Why: the owner said so.")
    assert brand.is_switched(f"{brand.SWITCHED} the recommended setup. Why: the owner chose it.")
    assert not brand.is_switched("The owner switched the planner.")
