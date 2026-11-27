"""The "What's new in X" card, shown once after the app updates, for the desktop and the phone in PC mode.

    GET  /api/whatsnew           {version, show, title, items: [{title, text}], source}
                                 show: true once after an update, until it is marked seen
         ?all=1                  the notes of this version whether seen or not (Settings → Updates)
    POST /api/whatsnew/seen      {version?} -> {ok, seen}; never shown again for that version

The notes come from the README's "What's new in X" sections (updater.whats_new). What was seen is this
computer's (``whatsnew.json`` in the app's own folder); the phone keeps its own. A new install shows nothing:
there's nothing "new" to someone who has just started.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import updater

STATE = "whatsnew.json"


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/whatsnew"): lambda q: get(app, q),
        ("POST", "/api/whatsnew/seen"): lambda body: seen(app, body),
    }


def _home(app) -> Path | None:
    try:
        return Path(app._backup_home())
    except Exception:
        return None


def _version() -> str:
    from .. import __version__

    return __version__


def _first(q: dict, key: str) -> str:
    v = (q or {}).get(key) or [""]
    return str(v[0] if isinstance(v, list) else v)


def _read(home: Path | None) -> dict[str, Any] | None:
    if not home:
        return None
    try:
        return json.loads((home / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(home: Path | None, data: dict[str, Any]) -> None:
    if not home:
        return
    try:
        home.mkdir(parents=True, exist_ok=True)
        (home / STATE).write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def _used_before(home: Path) -> bool:
    """Signs this computer had Roundtable before this version (an update, not a new install)."""
    return any((home / p).exists() for p in ("config/app.json", "config/harness.yaml", "config/hub.yaml",
                                              "notify-seen.json", "backup-state.json"))


def should_show(home: Path | None, version: str) -> bool:
    """True once for each version the app updated to; records a new install's version as already seen."""
    state = _read(home)
    if state is None:
        if home and _used_before(home):
            return True  # updated from a version that didn't know about this card yet
        _write(home, {"seen": version})
        return False
    last = str(state.get("seen") or "")
    if not last:
        return True
    return updater._parse_version(version) > updater._parse_version(last)


def card(version: str, show: bool) -> dict[str, Any]:
    notes = updater.whats_new(version)
    items = notes["items"]
    return {"version": version, "show": bool(show and items), "title": f"What's new in {version}",
            "items": items, "source": notes["source"]}


def get(app, q) -> dict[str, Any]:
    version = _version()
    home = _home(app)
    show = should_show(home, version)
    out = card(version, show)
    if show and not out["items"]:  # nothing written for this version: don't keep asking
        _write(home, {"seen": version})
    if _first(q, "all") in ("1", "true", "yes"):
        out["show"] = False
    return out


def seen(app, body) -> dict[str, Any]:
    version = str((body or {}).get("version") or _version()).lstrip("vV")
    home = _home(app)
    last = str((_read(home) or {}).get("seen") or "")
    if not last or updater._parse_version(version) >= updater._parse_version(last):
        _write(home, {"seen": version})
        last = version
    return {"ok": True, "seen": last}
