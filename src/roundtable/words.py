"""The words the owner reads, in their language (wave 9).

A stub with its frozen signatures: Helper w9-words fills it. One table for both apps: the key is the British
English sentence itself, with ``{name}`` holes for values, so a missing translation shows English and nothing
ever shows a code. ``ui/static/lang/<code>.json`` is ``{"English sentence": "translated"}``; the phone reads
the same files. British English (``en-GB``) is the default and the tests' language.

Until it is filled every function answers in British English: :func:`t` returns the English with its holes
filled, and nothing else changes.
"""

from __future__ import annotations

import re
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

_HOLE = re.compile(r"\{(\w+)\}")


def language(app) -> str:
    """The language the owner chose for the app (stub: always British English)."""
    return DEFAULT


def catalogue(lang: str) -> dict[str, str]:
    """``{"English sentence": "translated"}`` for ``lang`` (stub: empty, so everything stays English)."""
    return {}


def rtl(lang: str) -> bool:
    """Whether ``lang`` is written right to left (Arabic, Hebrew, Persian, Urdu)."""
    return bool((LANGS.get(lang) or LANGS.get(str(lang).split("-")[0]) or {}).get("rtl"))


def t(text: str, lang: str | None = None, **vals) -> str:
    """``text`` in ``lang`` (default: the chosen language) with its ``{holes}`` filled from ``vals``.
    Stub: the English, holes filled; a hole with no value is left as it is."""
    if not vals:
        return text
    return _HOLE.sub(lambda m: str(vals[m.group(1)]) if m.group(1) in vals else m.group(0), text)
