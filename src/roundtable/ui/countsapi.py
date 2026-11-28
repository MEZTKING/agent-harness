"""What you use most (localcounts.py), as an API. On the PC only: the phone never sees or clears these.

    GET  /api/counts                      ?days=30 -> {on, top, screens, buttons, days, since, words, note}
    POST /api/counts {action: "clear"}    -> the same, empty
    POST /api/counts {action: "on"|"off"} -> the same; off stops counting until it is turned back on

The counting itself happens in the desktop's ``dispatch`` (one line: ``localcounts.count(home, family(...))``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import localcounts


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/counts"): lambda q: view(app, q or {}),
        ("POST", "/api/counts"): lambda body: change(app, body or {}),
    }


def home_of(app) -> Path | None:
    fn = getattr(app, "_backup_home", None)
    try:
        return Path(fn()) if callable(fn) else None
    except Exception:  # noqa: BLE001 - the default home then
        return None


def _days(q) -> int:
    v = q.get("days", 30)
    if isinstance(v, list):
        v = v[0] if v else 30
    try:
        return max(1, min(localcounts.KEEP_DAYS, int(v)))
    except (TypeError, ValueError):
        return 30


def view(app, q) -> dict[str, Any]:
    return localcounts.view(home_of(app), _days(q))


def change(app, body: dict[str, Any]) -> dict[str, Any]:
    action = str(body.get("action") or "")
    if action == "clear":
        return localcounts.clear(home_of(app))
    if action in ("on", "off"):
        return localcounts.set_on(home_of(app), action == "on")
    raise ValueError("Choose clear, on or off.")
