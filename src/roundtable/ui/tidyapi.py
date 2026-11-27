"""Tidying up old files (retention.py) from Settings → Advanced.

    GET  /api/tidy           {auto, last: {at, message, freed, details} | null}
    POST /api/tidy           {auto: bool} -> the same (the switch "Tidy up old files automatically")
    POST /api/tidy/preview   {} -> {message, freed, details: [...], items: [{what, path, size}]}
                             what would be removed right now; nothing is removed
    GET  /api/tidy/not-chosen          {words, items: [{project, path, task, rival, model, why, branch, patch, size}]}
                                       attempts other models built side by side that weren't chosen (rivals.py)
    POST /api/tidy/not-chosen/clear    {path, task?, rival?} -> {cleared, kept, reply}; only the owner's button

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
        ("GET", "/api/tidy/not-chosen"): lambda q: not_chosen(app),
        ("POST", "/api/tidy/not-chosen/clear"): lambda body: clear_not_chosen(app, body or {}),
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


def _project_roots(app) -> list[Path]:
    try:
        return [Path(p) for p in retention._projects(app.cfg())]
    except Exception:  # noqa: BLE001 - no settings yet: no projects
        return []


def not_chosen(app) -> dict[str, Any]:
    rows = []
    for root in _project_roots(app):
        try:
            rows += [{**r, "project": root.name, "path": str(root)} for r in retention.not_chosen(root)]
        except Exception:  # noqa: BLE001 - one project's git failing never hides the others
            continue
    return {"words": retention.not_chosen_words(rows), "items": rows}


def clear_not_chosen(app, body: dict[str, Any]) -> dict[str, Any]:
    from .server import ApiError

    path = str(body.get("path") or "")
    roots = {str(r): r for r in _project_roots(app)}
    if path not in roots:  # only a project the app knows: nothing else is ever touched
        raise ApiError("That project isn't one of yours on this computer. Open the Tidy page again and retry.")
    out = retention.clear_not_chosen(roots[path], str(body.get("task") or ""), str(body.get("rival") or ""))
    return {**out, **not_chosen(app)}
