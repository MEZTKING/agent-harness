"""The house style and the charter as an API (Settings → How agents write; the Learning page).

    GET  /api/style     {on, text, default_text, max_chars, words}
    POST /api/style     {on?, text?, reset?} -> the same as GET (kept in custom.yaml)
    GET  /api/charter   {never: [{id, title, words}], words, fixed_rules, protected_lines, settings_it_may_change}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..harness import housestyle
from ..improve import charter


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/style"): lambda q: view(app),
        ("POST", "/api/style"): lambda body: save(app, body or {}),
        ("GET", "/api/charter"): lambda q: charter.view(),
    }


def _cfg(app):
    try:
        return app.cfg()
    except Exception:
        return None


def _path(app) -> Path | None:
    cfg = _cfg(app)
    p = getattr(cfg, "path", None) or getattr(app, "harness_config_path", None)
    return Path(p) if p else None


def _out(s: dict[str, Any]) -> dict[str, Any]:
    if not s["on"]:
        words = "Agents write in their own way."
    elif s["text"] == housestyle.DEFAULT_TEXT:
        words = "Agents write for you in the usual house style."
    else:
        words = "Agents write for you in your own house style."
    return {"on": s["on"], "text": s["text"], "default_text": housestyle.DEFAULT_TEXT,
            "max_chars": housestyle.MAX_CHARS, "words": words}


def view(app) -> dict[str, Any]:
    return _out(housestyle.settings(_cfg(app)))


def save(app, body: dict[str, Any]) -> dict[str, Any]:
    from .server import ApiError

    path = _path(app)
    if not path or not path.is_file():
        raise ApiError("The harness's settings aren't set up on this computer yet. Run the set-up in Settings first.",
                       503)
    try:
        housestyle.save(path, body)
    except ValueError as e:
        raise ApiError(f"Nothing was changed: {e}.") from None
    return view(app)  # app.cfg() reads the settings afresh, so the next model call uses it
