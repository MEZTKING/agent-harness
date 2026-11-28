"""The words the owner reads, in their language (wave 9).

One table for both apps: the key is the British English sentence itself, with ``{name}`` holes for values, so a
missing translation shows English and nothing ever shows a code. ``ui/static/lang/<code>.json`` is
``{"English sentence": "translated"}``; the phone reads the same files. A value may also be a set of plural forms
(``{"one": "…", "few": "…", "other": "…"}``, the language's own categories), chosen by the value ``n`` (or
``count``). Keys that start with ``@`` are about the file, never sentences: ``"@meta"`` says who made it
(``{"by": "model" | "person", "model", "made", "name", "own_name", "rtl", "locale"}``).

Where a table comes from, later winning: the one shipped with the app, one the owner added (made in the app's data
folder, ``<home>/lang/<code>.json``), then the owner's own fixes (``<home>/language.json``, ``fixes``). British
English (``en-GB``) is the default and the tests' language: with it nothing is looked up at all.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

DEFAULT = "en-GB"

# code -> {name (in English), own_name (in itself), rtl}: the languages the app knows how to show
LANGS: dict[str, dict[str, Any]] = {
    "en-GB": {"name": "English (UK)", "own_name": "English (UK)", "rtl": False},
    "ar": {"name": "Arabic", "own_name": "العربية", "rtl": True},
    "zh-Hans": {"name": "Chinese (Simplified)", "own_name": "简体中文", "rtl": False},
    "es": {"name": "Spanish", "own_name": "Español", "rtl": False},
    "fr": {"name": "French", "own_name": "Français", "rtl": False},
    "de": {"name": "German", "own_name": "Deutsch", "rtl": False},
    "pt": {"name": "Portuguese", "own_name": "Português", "rtl": False},
    "ja": {"name": "Japanese", "own_name": "日本語", "rtl": False},
    "ko": {"name": "Korean", "own_name": "한국어", "rtl": False},
    "hi": {"name": "Hindi", "own_name": "हिन्दी", "rtl": False},
    "ru": {"name": "Russian", "own_name": "Русский", "rtl": False},
    "tr": {"name": "Turkish", "own_name": "Türkçe", "rtl": False},
    "he": {"name": "Hebrew", "own_name": "עברית", "rtl": True},
    "fa": {"name": "Persian", "own_name": "فارسی", "rtl": True},
    "ur": {"name": "Urdu", "own_name": "اردو", "rtl": True},
}

# The eleven the owner allowed for 1.5.0 (28 November 2026), each made by a model and labelled so.
SHIPPED = ("ar", "zh-Hans", "es", "fr", "de", "pt", "ja", "ko", "hi", "ru", "tr")

# Never translated, whatever a table says: the app's own name and the names of things machines read.
KEEP = ("Darkness Harness", "Darkness")

LABEL = "Translated by a model; some words may be off. Tell me and I'll fix them."

STATIC_LANG = Path(__file__).resolve().parent / "ui" / "static" / "lang"
_HOLE = re.compile(r"\{(\w+)\}")
_LOCK = threading.Lock()
_CACHE: dict[tuple[str, float, float, float], dict[str, Any]] = {}


# -- where things live -------------------------------------------------------------------------------------------
def _home() -> Path:
    from .desktop import app_home

    return app_home()


def settings_path() -> Path:
    return _home() / "language.json"


def data_lang_dir() -> Path:
    return _home() / "lang"


def load_settings() -> dict[str, Any]:
    """``{lang, fixes: {code: {english: text}}, auto_reasons: bool, allowance_usd}`` (missing parts: defaults)."""
    try:
        raw = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    fixes = raw.get("fixes") if isinstance(raw.get("fixes"), dict) else {}
    try:
        allowance = max(0.0, min(5.0, float(raw.get("allowance_usd", 0.10))))
    except (TypeError, ValueError):
        allowance = 0.10
    return {"lang": str(raw.get("lang") or DEFAULT),
            "fixes": {str(k): {str(a): str(b) for a, b in v.items()} for k, v in fixes.items() if isinstance(v, dict)},
            "auto_reasons": bool(raw.get("auto_reasons", False)), "allowance_usd": allowance}


def save_settings(**changes: Any) -> dict[str, Any]:
    with _LOCK:
        s = load_settings()
        s.update({k: v for k, v in changes.items() if k in s})
        p = settings_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(p)
    return s


def fix(lang: str, english: str, text: str) -> dict[str, Any]:
    """The owner's own wording for one sentence (``text`` empty: back to the table's)."""
    s = load_settings()
    mine = dict(s["fixes"].get(lang) or {})
    if str(text).strip():
        mine[english] = str(text)
    else:
        mine.pop(english, None)
    fixes = {**s["fixes"], lang: mine}
    if not mine:
        fixes.pop(lang, None)
    return save_settings(fixes=fixes)


# -- tables ----------------------------------------------------------------------------------------------------
def _read(path: Path) -> dict[str, Any]:
    try:
        st = path.stat()
    except OSError:
        return {}
    key = (str(path), st.st_mtime, float(st.st_size), 0.0)
    got = _CACHE.get(key)
    if got is None:
        try:
            got = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            got = {}
        got = got if isinstance(got, dict) else {}
        _CACHE[key] = got
    return got


def files(lang: str) -> list[Path]:
    """The table files for ``lang``, the shipped one first."""
    return [p for p in (STATIC_LANG / f"{lang}.json", data_lang_dir() / f"{lang}.json") if p.is_file()]


def meta(lang: str) -> dict[str, Any]:
    out: dict[str, Any] = dict(LANGS.get(lang) or {"name": lang, "own_name": lang, "rtl": False})
    for p in files(lang):
        m = _read(p).get("@meta")
        if isinstance(m, dict):
            out.update({k: v for k, v in m.items() if k in ("by", "model", "made", "name", "own_name", "rtl",
                                                             "locale")})
    out.setdefault("by", "model" if lang != DEFAULT else "person")
    return out


def _sentences(raw: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in raw.items() if not k.startswith("@") and isinstance(v, (str, dict)) and v}


def catalogue(lang: str) -> dict[str, Any]:
    """``{"English sentence": "translated"}`` for ``lang``: the shipped table, one added in the app, then the
    owner's fixes. British English has none (the key is the sentence)."""
    if not lang or lang == DEFAULT:
        return {}
    out: dict[str, Any] = {}
    for p in files(lang):
        out.update(_sentences(_read(p)))
    out.update(load_settings()["fixes"].get(lang) or {})
    return out


def available() -> list[str]:
    """British English, then every language with a table (shipped or added), in LANGS' order."""
    found = {p.stem for d in (STATIC_LANG, data_lang_dir()) if d.is_dir() for p in d.glob("*.json")}
    found.discard(DEFAULT)
    known = [c for c in LANGS if c in found]
    return [DEFAULT, *known, *sorted(found - set(known))]


def language(app) -> str:
    """The language the owner chose for the app; British English when nothing (or nothing usable) is chosen."""
    lang = load_settings()["lang"]
    return lang if lang == DEFAULT or lang in available() else DEFAULT


def rtl(lang: str) -> bool:
    """Whether ``lang`` is written right to left (Arabic, Hebrew, Persian, Urdu)."""
    known = LANGS.get(lang) or LANGS.get(str(lang).split("-")[0])
    if known is not None:
        return bool(known.get("rtl"))
    return bool(meta(lang).get("rtl")) if lang else False


def locale(lang: str) -> str:
    """The locale dates and numbers are written in (an added language may name its own)."""
    return str(meta(lang).get("locale") or lang) if lang in LANGS or lang == DEFAULT else str(
        meta(lang).get("locale") or DEFAULT)


# -- plurals (CLDR's categories for the languages shipped; the browser uses Intl.PluralRules) -------------------
def plural_category(lang: str, n: Any) -> str:
    try:
        x = float(n)
    except (TypeError, ValueError):
        return "other"
    whole = x.is_integer()
    i = int(abs(x)) if whole else None
    base = str(lang or DEFAULT).split("-")[0]
    if base in ("ja", "zh", "ko"):
        return "other"
    if base == "ar":
        if not whole:
            return "other"
        if i == 0:
            return "zero"
        if i == 1:
            return "one"
        if i == 2:
            return "two"
        if 3 <= i % 100 <= 10:
            return "few"
        if 11 <= i % 100 <= 99:
            return "many"
        return "other"
    if base == "ru":
        if not whole:
            return "other"
        if i % 10 == 1 and i % 100 != 11:
            return "one"
        if 2 <= i % 10 <= 4 and not 12 <= i % 100 <= 14:
            return "few"
        return "many"
    if base == "he":
        return "one" if x == 1 else "two" if x == 2 else "other"
    if base == "fr":
        return "one" if 0 <= abs(x) < 2 else "other"
    if base in ("pt", "hi", "fa"):
        return "one" if abs(x) in (0, 1) or (base != "pt" and 0 < abs(x) < 1) else "other"
    return "one" if x == 1 else "other"


def _fill(text: str, vals: dict[str, Any]) -> str:
    if not vals:
        return text
    return _HOLE.sub(lambda m: str(vals[m.group(1)]) if m.group(1) in vals else m.group(0), text)


def _pick(value: Any, lang: str, vals: dict[str, Any], english: str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        n = vals.get("n", vals.get("count"))
        cat = plural_category(lang, n) if n is not None else "other"
        got = value.get(cat) or value.get("other")
        if isinstance(got, str) and got:
            return got
    return english


def t(text: str, lang: str | None = None, **vals) -> str:
    """``text`` in ``lang`` (default: the chosen language) with its ``{holes}`` filled from ``vals``.
    A sentence the table doesn't have stays English; a hole with no value is left as it is."""
    text = str(text)
    if lang is None:
        lang = language(None)
    if lang and lang != DEFAULT:
        table = catalogue(lang)
        value = table.get(text)
        if value is not None:
            text = _pick(value, lang, vals, text)
        else:
            core = text.strip()
            if core != text and core in table:  # the spaces around it are kept
                at = text.index(core)
                text = text[:at] + _pick(table[core], lang, vals, core) + text[at + len(core):]
    return _fill(text, vals)


def plural(n: Any, one: str, other: str, lang: str | None = None, **vals) -> str:
    """``one`` or ``other`` (English forms, ``{n}`` for the number), in the chosen language. The table's key is
    the ``other`` form; its value may carry the language's own forms."""
    lang = language(None) if lang is None else lang
    vals = {"n": n, **vals}
    if lang and lang != DEFAULT and other in catalogue(lang):
        return t(other, lang, **vals)
    return _fill(one if plural_category(DEFAULT, n) == "one" else other, vals)


# -- checking a table --------------------------------------------------------------------------------------------
def holes(text: str) -> set[str]:
    return set(_HOLE.findall(str(text)))


def problems(table: dict[str, Any]) -> list[str]:
    """What is wrong with a translated table, in plain words ([] when it is fine): a lost or made-up ``{hole}``, an
    empty sentence, the app's name translated."""
    out = []
    for key, value in ((k, v) for k, v in table.items() if not str(k).startswith("@")):
        forms = value.values() if isinstance(value, dict) else [value]
        for v in forms:
            if not isinstance(v, str) or not v.strip():
                out.append(f"empty: {key!r}")
                continue
            if holes(v) != holes(key) and not (isinstance(value, dict) and holes(v) <= holes(key)):
                out.append(f"holes changed: {key!r} -> {v!r}")
            for name in KEEP[:1]:
                if name in key and name not in v:
                    out.append(f"the app's name was translated: {key!r} -> {v!r}")
    return out


def view(lang: str | None = None) -> dict[str, Any]:
    """Everything the desktop and the phone need to show the chosen language (``GET /api/words``)."""
    s = load_settings()
    lang = language(None) if lang is None else lang
    langs = []
    for code in available():
        m = meta(code)
        langs.append({"code": code, "name": m.get("name", code), "own_name": m.get("own_name", code),
                      "rtl": rtl(code), "by_model": code != DEFAULT and m.get("by") == "model"})
    m = meta(lang)
    by_model = lang != DEFAULT and m.get("by") == "model"
    return {"lang": lang, "dir": "rtl" if rtl(lang) else "ltr", "locale": locale(lang), "table": catalogue(lang),
            "langs": langs, "label": t(LABEL, lang) if by_model else "", "by_model": by_model,
            "fixes": len(s["fixes"].get(lang) or {}), "auto_reasons": s["auto_reasons"],
            "allowance_usd": s["allowance_usd"]}


def owner_line(lang: str | None = None) -> str:
    """The house style's one line for the chosen language ("" for British English): plans and replies arrive in it
    without a second call; the builders' briefs and the code stay in English."""
    lang = language(None) if lang is None else lang
    if not lang or lang == DEFAULT:
        return ""
    name = meta(lang).get("name", lang)
    return (f"Write to the owner in {name}: plans, questions, summaries and replies. Briefs for the builders, code, "
            f"file names and commit messages stay in English. Never translate the name {KEEP[0]}.")
