"""List every sentence the owner reads into the English table (``ui/static/lang/en-GB.json``), and count what
still reaches the screen without passing the table.

    python tools/words_extract.py            # write en-GB.json and print the counts
    python tools/words_extract.py --check    # write nothing; fail if en-GB.json misses a sentence

Where a sentence is found (desktop pages, ``ui/static/*.js``): the text kids of ``h(…)``, ``fill(…)``, ``card``,
``page``, ``empty``, ``toast``; the attributes the owner reads (``title``, ``tip``, ``placeholder``, ``aria-label``,
``alt``, and a dialog's ``text``, ``yes``, ``no``, ``label``); ``act``'s message; ``new Error(…)``; the key of
``t(…)``; and label tables (an object or list whose strings read like a sentence). On the server: ``ApiError``'s
fixed messages in ``ui/*.py`` and the keys of ``words.t(…)``.

"Not through the table" (the ratchet in tests/test_words_extract.py): a template string with values, or text
joined with ``+``, at one of those places. ``tools/words_sweep.py`` turns the template strings into ``t(…)``.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "roundtable"
STATIC = SRC / "ui" / "static"
TABLE = STATIC / "lang" / "en-GB.json"
SKIP_FILES = {"words.js"}
KEEP = ("Darkness Harness", "Darkness")

KID_CALLS = {"h": 2, "fill": 1, "card": 0, "page": 0, "empty": 0, "toast": 0, "Error": 0, "act": 2}
WORDY_KEYS = {"title", "tip", "placeholder", "aria-label", "alt", "text", "yes", "no", "label"}
REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^") | {"return", "typeof", "case", "in", "of", "new", "delete", "void",
                                             "throw", "=>", "&&", "||", "??", "==", "===", "!=", "!==", "else"}
KEYWORDS = {"if", "for", "while", "switch", "catch", "function", "return", "typeof", "new", "await", "async",
            "with", "else", "do", "try", "finally", "case", "of", "in"}


@dataclass
class Tok:
    kind: str  # str, tpl, ident, punct, regex, num
    start: int
    end: int
    value: str = ""
    parts: list = field(default_factory=list)  # tpl: [(literal, expr_src or None)]


def _skip_string(text: str, i: int) -> int:
    q, j, n = text[i], i + 1, len(text)
    while j < n and text[j] != q:
        j += 2 if text[j] == "\\" else 1
    return j + 1


def _template(text: str, i: int) -> tuple[int, list]:
    """From the opening backtick: (index after the closing one, [(literal, expr)])."""
    j, n, lit, parts = i + 1, len(text), [], []
    while j < n:
        c = text[j]
        if c == "\\":
            lit.append(text[j:j + 2])
            j += 2
            continue
        if c == "`":
            parts.append(("".join(lit), None))
            return j + 1, parts
        if text.startswith("${", j):
            end = _expr_end(text, j + 2)
            parts.append(("".join(lit), text[j + 2:end]))
            lit = []
            j = end + 1
            continue
        lit.append(c)
        j += 1
    parts.append(("".join(lit), None))
    return n, parts


def _expr_end(text: str, i: int) -> int:
    """The index of the ``}`` that closes a template's ``${``."""
    depth, toks = 0, tokens(text, i, stop_at_close=True)
    for t in toks:
        if t.kind == "punct" and t.value == "{":
            depth += 1
        elif t.kind == "punct" and t.value == "}":
            if depth == 0:
                return t.start
            depth -= 1
    return len(text)


def tokens(text: str, i: int = 0, stop_at_close: bool = False) -> list[Tok]:
    out: list[Tok] = []
    n, depth = len(text), 0
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c in "\"'":
            j = _skip_string(text, i)
            out.append(Tok("str", i, j, text[i + 1:j - 1]))
            i = j
            continue
        if c == "`":
            j, parts = _template(text, i)
            out.append(Tok("tpl", i, j, parts=parts))
            i = j
            continue
        if c.isalpha() or c in "_$":
            j = i
            while j < n and (text[j].isalnum() or text[j] in "_$"):
                j += 1
            out.append(Tok("ident", i, j, text[i:j]))
            i = j
            continue
        if c.isdigit():
            j = i
            while j < n and (text[j].isalnum() or text[j] in "._"):
                j += 1
            out.append(Tok("num", i, j, text[i:j]))
            i = j
            continue
        if c == "/":
            prev = out[-1] if out else None
            if prev is None or (prev.kind == "punct" and prev.value in REGEX_AFTER) or (
                    prev.kind == "ident" and prev.value in REGEX_AFTER):
                j, cls = i + 1, False
                while j < n and text[j] != "\n":
                    if text[j] == "\\":
                        j += 2
                        continue
                    if text[j] == "[":
                        cls = True
                    elif text[j] == "]":
                        cls = False
                    elif text[j] == "/" and not cls:
                        break
                    j += 1
                j += 1
                while j < n and text[j].isalpha():
                    j += 1
                out.append(Tok("regex", i, j, text[i:j]))
                i = j
                continue
        for p in ("===", "!==", "...", "=>", "&&", "||", "??", "==", "!=", "?.", "++", "--", "+=", "-="):
            if text.startswith(p, i):
                out.append(Tok("punct", i, i + len(p), p))
                i += len(p)
                break
        else:
            if stop_at_close and c == "{":
                depth += 1
            if stop_at_close and c == "}":
                if depth == 0:
                    out.append(Tok("punct", i, i + 1, c))
                    return out
                depth -= 1
            out.append(Tok("punct", i, i + 1, c))
            i += 1
    return out


@dataclass
class Site:
    tok: Tok
    why: str  # kid, attr, key (a t() key), label (a label table), error
    joined: bool = False  # text joined with + (not through the table)


def _looks_like_words(s: str) -> bool:
    s = s.strip()
    if len(s) < 2 or not re.search(r"[a-z]", s) or not re.match(r"[A-Z]", s):
        return False
    if re.search(r"[/\\<>{}=_#@$|]", s) or re.fullmatch(r"[A-Za-z]+[A-Z][a-z]+\w*", s):
        return False
    return True


def has_letters(s: str) -> bool:
    """Words a person reads: letters, and not a piece of CSS or code."""
    if not re.search(r"[A-Za-z]{2}", s):
        return False
    if re.fullmatch(r"\S+://\S+", s.strip()):
        return False
    return not (re.search(r"\{[^}]*[:;][^}]*\}", s) or s.count(";") >= 2 or re.match(r"\s*[.#@][\w-]", s))


def sites(text: str) -> list[Site]:
    """Every string or template at a place the owner reads, with why."""
    toks = tokens(text)
    stack: list[dict] = []
    out: list[Site] = []

    def joined(k: int) -> bool:
        a = toks[k - 1] if k else None
        b = toks[k + 1] if k + 1 < len(toks) else None
        return any(x is not None and x.kind == "punct" and x.value == "+" for x in (a, b))

    for k, tok in enumerate(toks):
        prev = toks[k - 1] if k else None
        if tok.kind == "punct":
            v = tok.value
            if v == "(":
                callee = None
                if prev is not None and prev.kind == "ident" and prev.value not in KEYWORDS:
                    before = toks[k - 2] if k >= 2 else None
                    if not (before is not None and before.kind == "punct" and before.value in (".", "?.")) or \
                            prev.value == "Error":
                        callee = prev.value
                    if before is not None and before.kind == "ident" and before.value == "function":
                        callee = None
                    if prev.value == "t" and before is not None and before.value == "." and k >= 3 and \
                            toks[k - 3].value == "words":
                        callee = "t"  # words.t(…)
                    if prev.value == "wt":
                        callee = "t"  # t imported as wt where a module has a t of its own
                stack.append({"t": "call", "callee": callee, "arg": 0})
            elif v == "[":
                stack.append({"t": "arr"})
            elif v == "{":
                is_obj = prev is None or (prev.kind == "punct" and prev.value in ("(", ",", ":", "=", "[", "?", "||",
                                                                                     "&&", "??")) or (
                    prev.kind == "ident" and prev.value == "return")
                stack.append({"t": "obj" if is_obj else "block", "key": None})
            elif v in (")", "]", "}"):
                if stack:
                    stack.pop()
            elif v == "," and stack:
                top = stack[-1]
                if top["t"] == "call":
                    top["arg"] += 1
                elif top["t"] == "obj":
                    top["key"] = None
            elif v == ":" and stack and stack[-1]["t"] == "obj" and prev is not None and prev.kind in ("ident", "str"):
                before = toks[k - 2] if k >= 2 else None
                if before is not None and before.kind == "punct" and before.value in ("{", ","):
                    stack[-1]["key"] = prev.value
            continue
        if tok.kind not in ("str", "tpl"):
            continue
        nxt = toks[k + 1] if k + 1 < len(toks) else None
        if tok.kind == "str" and nxt is not None and nxt.kind == "punct" and nxt.value == ":" and stack and \
                stack[-1]["t"] == "obj" and prev is not None and prev.kind == "punct" and prev.value in ("{", ","):
            continue  # a key, not a value
        frame = next((f for f in reversed(stack) if f["t"] in ("call", "obj")), None)
        if frame is None:
            if tok.kind == "str" and stack and stack[-1]["t"] == "arr" and _looks_like_words(tok.value):
                out.append(Site(tok, "label", joined(k)))  # a label table: const TABS = [["id", "Overview", …]]
            continue
        why = None
        if frame["t"] == "call":
            c = frame["callee"]
            if c == "t" and frame["arg"] == 0:
                why = "key"
            elif c in KID_CALLS and frame["arg"] >= KID_CALLS[c] and (c not in ("Error", "act") or
                                                                       frame["arg"] == KID_CALLS[c]):
                why = "error" if c == "Error" else "kid"
        else:
            outer = stack[stack.index(frame) - 1] if stack.index(frame) > 0 else None
            key = frame["key"]
            if key in WORDY_KEYS:
                why = "attr"
            elif key in ("one", "other") and outer and outer["t"] == "call" and outer["callee"] == "t":
                why = "key" if key == "other" else None
            elif tok.kind == "str" and _looks_like_words(tok.value):
                why = "label"
        if why is None and tok.kind == "str" and frame["t"] == "call" and stack and stack[-1]["t"] == "arr" and \
                _looks_like_words(tok.value) and frame["callee"] not in ("t",):
            why = "label"
        if why is None:
            continue
        out.append(Site(tok, why, joined(k) and why != "key"))
    return out


def _cook(lit: str) -> str:
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), lit)


def sentences_of(text: str) -> tuple[set[str], list[Site]]:
    """(the sentences, the places not through the table)."""
    found: set[str] = set()
    left: list[Site] = []
    for s in sites(text):
        if s.tok.kind == "tpl":
            if len(s.tok.parts) == 1:  # no values: a plain sentence
                v = _cook(s.tok.parts[0][0]).strip()
                if has_letters(v):
                    found.add(v)
                    if s.joined:
                        left.append(s)
                continue
            if any(has_letters(lit) for lit, _ in s.tok.parts):
                left.append(s)
            continue
        v = _cook(s.tok.value).strip()
        if not has_letters(v) or v in KEEP:
            continue
        if s.why == "label" and not _looks_like_words(v):
            continue
        found.add(v)
        if s.joined:
            left.append(s)
    return found, left


def py_sentences(path: Path) -> set[str]:
    out: set[str] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return out
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "LABEL" for t in n.targets) and \
                isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
            out.add(n.value.value.strip())  # words.LABEL: the note under a model's translation
            continue
        if not isinstance(n, ast.Call) or not n.args:
            continue
        f = n.func
        name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
        a = n.args[0]
        if name in ("ApiError", "t") and isinstance(a, ast.Constant) and isinstance(a.value, str):
            if name == "t" and not (isinstance(f, ast.Attribute) and getattr(f.value, "id", "") in ("W", "words")):
                continue
            v = a.value.strip()
            if has_letters(v):
                out.add(v)
    return out


def html_sentences(path: Path) -> set[str]:
    """The page's frame (index.html): its text and the titles, placeholders and labels the owner reads."""
    from html.parser import HTMLParser

    out: set[str] = set()

    class P(HTMLParser):
        skip = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "title"):
                self.skip += 1
            for k, v in attrs:
                if k in ("title", "placeholder", "aria-label", "alt") and v and has_letters(v):
                    out.add(v.strip())

        def handle_endtag(self, tag):
            if tag in ("script", "style", "title"):
                self.skip = max(0, self.skip - 1)

        def handle_data(self, data):
            v = data.strip()
            if not self.skip and has_letters(v) and v not in KEEP:
                out.add(v)

    try:
        P().feed(path.read_text(encoding="utf-8"))
    except OSError:
        pass
    return out


def extract(static: Path = STATIC, src: Path = SRC) -> tuple[list[str], dict[str, list[Site]]]:
    """(every sentence, sorted; {file name: places not through the table})."""
    found: set[str] = set()
    left: dict[str, list[Site]] = {}
    for p in sorted(static.glob("*.js")):
        if p.name in SKIP_FILES:
            continue
        f, l = sentences_of(p.read_text(encoding="utf-8"))
        found |= f
        if l:
            left[p.name] = l
    found |= html_sentences(static / "index.html")
    for p in sorted((src / "ui").glob("*.py")):
        found |= py_sentences(p)
    for p in (src / "words.py", src / "translate.py"):
        found |= py_sentences(p)
    return sorted(found), left


def table_text(sentences: list[str]) -> str:
    body = {"@meta": {"by": "person", "name": "English (UK)", "own_name": "English (UK)", "rtl": False}}
    body.update({s: s for s in sentences})
    return json.dumps(body, ensure_ascii=False, indent=1) + "\n"


def not_through(left: dict[str, list[Site]]) -> int:
    return sum(len(v) for v in left.values())


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    sentences, left = extract()
    if "--check" in argv:
        have = set(json.loads(TABLE.read_text(encoding="utf-8"))) if TABLE.exists() else set()
        missing = [s for s in sentences if s not in have]
        print(f"{len(sentences)} sentences; {len(missing)} missing from en-GB.json; "
              f"{not_through(left)} places not through the table")
        return 1 if missing else 0
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    TABLE.write_text(table_text(sentences), encoding="utf-8")
    tpl = sum(1 for v in left.values() for s in v if s.tok.kind == "tpl" and not s.joined)
    print(f"{len(sentences)} sentences in {TABLE.relative_to(ROOT)}; {not_through(left)} places not through the "
          f"table ({tpl} template strings the sweep can turn, {not_through(left) - tpl} joined with +)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
