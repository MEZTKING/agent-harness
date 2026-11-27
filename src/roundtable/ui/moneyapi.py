"""Costs also in pounds (money.py).

    GET  /api/rates   -> {currency: "GBP", per_usd, at, source: ecb | saved | typed | none, stale, show, setting,
                          words}
    POST /api/rates   {show?: "usd" | "usd+gbp", rate?: "auto" | <pounds for one dollar>} -> the same

The rate is read on the PC (once a day, the European Central Bank's public file) and the phone gets it from the
PC, so the phone asks no outside service.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import money


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/rates"): lambda q: view(app),
        ("POST", "/api/rates"): lambda body: change(app, body or {}),
    }


def _home(app) -> Path | None:
    fn = getattr(app, "_backup_home", None)
    return Path(fn()) if callable(fn) else None


def _section(app) -> dict[str, Any]:
    try:
        cfg = app.cfg()
    except Exception:  # noqa: BLE001 - no settings yet: the defaults
        return {}
    sections = getattr(cfg, "sections", None) or {}
    sec = sections.get("money") if isinstance(sections, dict) else None
    return sec if isinstance(sec, dict) else {}


def view(app) -> dict[str, Any]:
    return money.rate(_home(app), _section(app))


def change(app, body: dict) -> dict[str, Any]:
    home = _home(app)
    if home is None:
        from .server import ApiError

        raise ApiError("Roundtable can't find its own folder to keep this in.", 500)
    try:
        money.save(home, {k: body[k] for k in ("show", "rate") if k in body})
    except ValueError as e:
        from .server import ApiError

        raise ApiError(str(e)) from None
    return view(app)
