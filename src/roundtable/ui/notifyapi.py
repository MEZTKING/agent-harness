"""The news for the owner (notify.py) as an API, for the desktop's pop-ups and bell, and the phone in PC mode.

    GET  /api/notifications?since=<next or an ISO time>
         {news: [{n, key, kind, project, name, title, text, at, group, quiet, buttons: [{id, label}], ask,
          via, path, hub_agent}], next, at, settings: {kinds: {finished, needs_you, failed, money, idle}, popups},
          kinds: [{id, name, hint}]}
    GET  /api/notifications/settings     {kinds: {...}, popups}
    POST /api/notifications/settings     {kinds?: {kind: bool}, popups?: bool} -> the same

The news is worked out from the Hall's data at most every few seconds, whoever asks. The switches are
this computer's (a file in the app's own folder); the phone keeps its own.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .. import notify
from ..brand import NAME

REFRESH_S = 10.0


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/notifications"): lambda q: news(app, q),
        ("GET", "/api/notifications/settings"): lambda q: settings_get(app),
        ("POST", "/api/notifications/settings"): lambda body: settings_post(app, body),
    }


def _home(app) -> Path | None:
    try:
        return Path(app._backup_home())
    except Exception:
        return None


def _feed(app) -> notify.Feed:
    feed = getattr(app, "_notify_feed", None)
    if feed is None:
        home = _home(app)
        feed = app._notify_feed = notify.Feed(home / "notify-seen.json" if home else None)
        app._notify_checked = 0.0
    return feed


def refresh(app, force: bool = False) -> list[dict[str, Any]]:
    """Look at the Hall's data again (not more often than every REFRESH_S) and add what's new."""
    feed = _feed(app)
    if not force and time.monotonic() - getattr(app, "_notify_checked", 0.0) < REFRESH_S:
        return []
    app._notify_checked = time.monotonic()
    from .roundtable import build

    return feed.update(notify.snapshot(build(app)))


def _first(q: dict, key: str) -> str:
    v = q.get(key) or [""]
    return str(v[0] if isinstance(v, list) else v)


def news(app, q) -> dict[str, Any]:
    feed = _feed(app)
    try:
        refresh(app)
    except Exception as e:  # the hub offline etc.: say what we have
        app.auto_sync_error = getattr(app, "auto_sync_error", "") or f"notifications: {e}"[:300]
    items = feed.since(_first(q, "since") or None)
    return {"news": items, "next": feed.n, "at": notify.now_iso(), "settings": settings_get(app),
            "kinds": [{"id": k, "name": notify.KIND_NAMES[k], "hint": notify.KIND_HINTS[k]} for k in notify.KINDS]}


def _settings_path(app) -> Path | None:
    home = _home(app)
    return home / "notifications.json" if home else None


def settings_get(app) -> dict[str, Any]:
    p = _settings_path(app)
    return notify.load_settings(p) if p else notify.default_settings()


def settings_post(app, body: dict[str, Any]) -> dict[str, Any]:
    from .server import ApiError

    p = _settings_path(app)
    if not p:
        raise ApiError(f"This computer has nowhere to keep the switches. Open {NAME}'s settings first.")
    return notify.save_settings(p, body or {})
