"""Search everything, and the memory files (search.py, memory.py).

    GET  /api/search?q=words[&kinds=plan,task,...][&limit=40]
                                    {query, hits: [{kind, kind_words, title, where, snippet, at, open}], total, words}
    GET  /api/search/peek?path=<project>&file=<relative>[&line=N]
                                    {file, from, line, lines: [...], words}: lines around a hit, only inside the project
    GET  /api/memory?path=<project> | ?machine=1 [&archive=1]
                                    {markdown, counts, archived, words, exists, where} (archive=1: the archive's text)
    POST /api/memory                {path | machine, markdown}: the owner's edit -> {saved, moved, ...the view}
    POST /api/memory/note           {path | machine, text, as: note|fact|rule} -> {added, ...the view}
    POST /api/memory/machine/check  {} -> this computer's memory with "Tools found" looked at again

Only projects registered on this computer can be read or written (``app.project``); the machine memory is the
app home's ``memory.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import memory
from .. import search as finder


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/search"): lambda q: run_search(app, q),
        ("GET", "/api/search/peek"): lambda q: peek(app, q),
        ("GET", "/api/memory"): lambda q: memory_get(app, q),
        ("POST", "/api/memory"): lambda body: memory_save(app, body),
        ("POST", "/api/memory/note"): lambda body: memory_note(app, body),
        ("POST", "/api/memory/machine/check"): lambda body: machine_check(app),
    }


def _first(q: dict, key: str, default: str = "") -> str:
    v = q.get(key)
    if v is None:
        return default
    return str(v[0] if isinstance(v, list) else v)


def _home(app) -> Path | None:
    try:
        from ..desktop import app_home

        return app_home()
    except Exception:
        return None


def _names(app) -> dict[str, str]:
    hub = app.hub
    if not hub:
        return {}
    from .hall import NOTES_NAME, friendly

    return {a: (NOTES_NAME if a == app.agent and not s.repo else friendly(a, s)) for a, s in hub.config.agents.items()}


def run_search(app, q) -> dict[str, Any]:
    from .server import ApiError

    words = _first(q, "q").strip()
    if len(words) > 200:
        raise ApiError("That's a lot of words to look for. Try a few.")
    kinds = [k for k in _first(q, "kinds").split(",") if k in finder.KINDS] or None
    try:
        limit = min(200, max(1, int(_first(q, "limit", "40"))))
    except ValueError:
        limit = 40
    projects = app._lab_projects()
    with app.hub_lock:
        return finder.search(words, projects=projects, hub=app.hub, me=app.agent, home=_home(app), limit=limit,
                             kinds=kinds, names=_names(app))


def _root(app, path: str) -> Path:
    cfg = app.need_cfg()
    return app.project(cfg, path).root


def peek(app, q) -> dict[str, Any]:
    from .server import ApiError

    root = _root(app, _first(q, "path"))
    try:
        line = int(_first(q, "line", "0") or 0)
    except ValueError:
        line = 0
    try:
        return finder.peek_file(root, _first(q, "file"), line)
    except ValueError as e:
        raise ApiError(str(e), 404) from None


def _target(app, src: dict) -> tuple[Path, str]:
    """(the memory file, where in words) for {machine} or {path} (a registered project)."""
    from .server import ApiError

    machine = src.get("machine")
    if isinstance(machine, list):
        machine = machine[0] if machine else ""
    if machine and str(machine).lower() not in ("0", "false", ""):
        home = _home(app)
        if not home:
            raise ApiError("This computer has no folder for Roundtable's own files yet. Run the set-up in Settings.", 503)
        return memory.machine_path(home), "This computer"
    path = src.get("path")
    if isinstance(path, list):
        path = path[0] if path else ""
    root = _root(app, str(path or ""))
    return memory.project_path(root), finder.project_name(root)


def _view(app, path: Path, where: str) -> dict[str, Any]:
    return {**memory.view(path), "where": where}


def memory_get(app, q) -> dict[str, Any]:
    path, where = _target(app, q)
    if _first(q, "archive") in ("1", "true"):
        arch = memory.archive_of(path)
        text = arch.read_text(encoding="utf-8") if arch.is_file() else ""
        return {"markdown": text, "where": where, "archive": True,
                "words": "Older lines, word for word." if text else "Nothing has been moved here yet."}
    return _view(app, path, where)


def memory_save(app, body) -> dict[str, Any]:
    from .server import ApiError

    path, where = _target(app, body)
    try:
        out = memory.save_text(path, str(body.get("markdown") or ""), app.cfg())
    except (ValueError, OSError) as e:
        raise ApiError(str(e) if isinstance(e, ValueError) else "Couldn't save it: the file couldn't be written. "
                       "Check the project folder still exists and try again.") from None
    return {**out, **_view(app, path, where)}


AS = {"note": memory.RECENT, "fact": memory.PINNED, "pin": memory.PINNED, "rule": memory.RULES}


def memory_note(app, body) -> dict[str, Any]:
    from .server import ApiError

    text = str(body.get("text") or "").strip()
    if not text:
        raise ApiError("Write what to remember first.")
    kind = str(body.get("as") or "note")
    if kind not in AS:
        raise ApiError("Choose a note, a fact or a rule.")
    path, where = _target(app, body)
    fn = {memory.RECENT: memory.add_note, memory.PINNED: memory.pin, memory.RULES: memory.add_rule}[AS[kind]]
    added = fn(path, text, app.cfg())
    return {"added": added, **_view(app, path, where)}


def machine_check(app) -> dict[str, Any]:
    from .server import ApiError

    home = _home(app)
    if not home:
        raise ApiError("This computer has no folder for Roundtable's own files yet. Run the set-up in Settings.", 503)
    path = memory.refresh_machine(home)
    return _view(app, path, "This computer")
