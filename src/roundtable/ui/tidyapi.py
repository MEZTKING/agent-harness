"""Tidying up old files (retention.py) from Settings → Advanced.

    GET  /api/tidy           {auto, last: {at, message, freed, details} | null}
    POST /api/tidy           {auto: bool} -> the same (the switch "Tidy up old files automatically")
    POST /api/tidy/preview   {} -> {message, freed, details: [...], items: [{what, path, size}]}
                             what would be removed right now; nothing is removed

The switch is this computer's (``tidy.json`` in the app's own folder). The limits stay in harness.yaml
(``retention:``); there are no numbers to tune on screen.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import retention


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/tidy"): lambda q: status(app),
        ("POST", "/api/tidy"): lambda body: switch(app, body),
        ("POST", "/api/tidy/preview"): lambda body: preview(app),
    }


def _home(app) -> Path:
    return Path(app._backup_home())


def status(app) -> dict[str, Any]:
    home = _home(app)
    last = next((e for e in retention.entries(home, limit=50) if not e.get("dry_run")), None)
    return {"auto": retention.auto_on(home),
            "last": ({"at": last.get("at", ""), "message": last.get("message", ""), "freed": last.get("freed", 0),
                      "details": retention.details(last.get("groups") or {})} if last else None)}


def switch(app, body) -> dict[str, Any]:
    retention.set_auto(_home(app), bool((body or {}).get("auto")))
    return status(app)


def preview(app) -> dict[str, Any]:
    cfg = None
    try:
        cfg = app.cfg()
    except Exception:  # noqa: BLE001 - no settings yet: the app's own logs only
        cfg = None
    res = retention.tidy(cfg, home=_home(app), hub=getattr(app, "hub", None), hub_lock=getattr(app, "hub_lock", None),
                         dry_run=True)
    d = res.to_dict()
    return {"message": d["message"], "freed": d["freed"], "details": retention.details(d["groups"]),
            "items": [{"what": retention.GROUP_NAMES.get(r.what, r.what), "path": r.path, "size": retention.size_text(r.bytes)}
                      for r in res.removed][:200]}
