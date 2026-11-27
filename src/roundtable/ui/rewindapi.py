"""Undo a task, go back to before it, put it back, and try another way (harness/rewind.py), for the desktop
and the phone.

    GET  /api/rewind          ?path=<project> -> {rows: [history rows], last: {id, at, mode, task, title, words,
                              can_put_back, why_not, files} | null, can_change, why_not}
    GET  /api/rewind/preview  ?path=&task=&mode=undo_task|back_to_before -> {mode, task, title, words, files:
                              [{path, change, words}], back_to_todo, hand_edits, hand_edits_kept, blocked, offer,
                              stamp}; nothing changes
    POST /api/rewind          {path, task, mode, stamp} -> {ok, id, files, back_to_todo, words}; 409 when the stamp is
                              stale or something blocks it (the words say what to do)
    POST /api/rewind/undo     {path} -> {ok, words}: Put it back (the last rewind)
    POST /api/rewind/fork     {path, task, name} -> {ok, path, name, commit, words}: a copy from that task, added to
                              the projects list; it costs nothing until it is run

Nothing changes while a job runs on the project (``app._busy``) or another machine builds it (its claim in the
hub, sync.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..harness import rewind


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/rewind"): lambda q: overview(app, q),
        ("GET", "/api/rewind/preview"): lambda q: preview(app, q),
        ("POST", "/api/rewind"): lambda body: do(app, body),
        ("POST", "/api/rewind/undo"): lambda body: put_back(app, body),
        ("POST", "/api/rewind/fork"): lambda body: fork(app, body),
    }


def _first(q: dict, key: str, default: str = "") -> str:
    v = (q or {}).get(key, default)
    if isinstance(v, list):
        v = v[0] if v else default
    return str(v if v is not None else default)


def _error(text: str, status: int = 400):
    from .server import ApiError

    return ApiError(text, status)


def _root(app, q: dict) -> Path:
    cfg = app.cfg()
    if not cfg:
        raise _error("Roundtable isn't set up on this computer yet. Finish the set-up in Settings first.", 503)
    path = _first(q, "path")
    if not path:
        raise _error("Choose a project first.")
    return app.project(cfg, path).root  # only registered projects (404 otherwise)


def _busy(app, root: Path) -> bool:
    try:
        return bool(app._busy(root))
    except Exception:  # noqa: BLE001 - can't tell: say busy rather than risk it
        return True


def elsewhere(app, root: Path) -> str:
    """The refusal when another machine is building this project right now ("" when none is)."""
    hub = getattr(app, "hub", None)
    if hub is None:
        return ""
    try:
        from .. import sync

        where = sync.where_is(hub, root.name)
        if where and where.get("building") and where.get("machine") != sync.this_machine()["id"]:
            who = where.get("machine_name") or "another computer"
            return (f"This project is being built on {who} right now. Wait for it to finish or pause there, "
                    "then try again.")
    except Exception:  # noqa: BLE001 - the hub can't be read: nothing to say about it
        return ""
    return ""


def _guards(app, root: Path) -> tuple[bool, str]:
    return _busy(app, root), elsewhere(app, root)


def overview(app, q) -> dict[str, Any]:
    root = _root(app, q)
    busy, other = _guards(app, root)
    why = rewind.guard(root, busy, other)
    return {"rows": rewind.history(root), "last": rewind.last_rewind(root), "can_change": not why, "why_not": why}


def preview(app, q) -> dict[str, Any]:
    root = _root(app, q)
    busy, other = _guards(app, root)
    try:
        return rewind.preview(root, _first(q, "task"), _first(q, "mode", "undo_task"), busy, other)
    except rewind.RewindError as e:
        raise _error(str(e)) from None


def do(app, body) -> dict[str, Any]:
    body = body or {}
    root = _root(app, body)
    busy, other = _guards(app, root)
    try:
        return rewind.apply(root, str(body.get("task") or ""), str(body.get("mode") or ""), str(body.get("stamp") or ""),
                            busy, other)
    except rewind.RewindError as e:
        raise _error(str(e), 409) from None


def put_back(app, body) -> dict[str, Any]:
    root = _root(app, body or {})
    busy, other = _guards(app, root)
    try:
        return rewind.undo_last(root, busy, other)
    except rewind.RewindError as e:
        raise _error(str(e), 409) from None


def fork(app, body) -> dict[str, Any]:
    body = body or {}
    root = _root(app, body)
    cfg = app.cfg()
    projects = Path(getattr(app, "projects_dir", "") or root.parent)
    name = str(body.get("name") or "").strip() or f"{root.name}-another-way"
    try:
        out = rewind.fork(root, str(body.get("task") or ""), name, projects)
    except rewind.RewindError as e:
        raise _error(str(e), 409) from None
    app.lab(cfg).register_project(out["path"])
    return out
