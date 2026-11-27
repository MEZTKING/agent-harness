"""The command line (terminal.py) and a running task's command, live (harness/livecmd.py).

The command line (desktop only, and only while the app is local-only; never a phone route):

    POST /api/terminal/open    {path?: <project>, folder?, fresh?} -> {id, folder, running, line, next, project,
                               history}; the project's own command line comes back while it is still open
    POST /api/terminal/run     {id, line} -> the same: runs one line (``cd`` is kept between lines)
    POST /api/terminal/input   {id, text} -> the same: a line typed into the program that is running
    POST /api/terminal/stop    {id} -> the same: ends what is running and everything it started
    GET  /api/terminal/read    ?id=&since=&wait= -> {id, text, next, cut, running, line, folder, closed};
                               waits up to 20 seconds for new output
    POST /api/terminal/close   {id} -> {closed: true}

A task's command (the phone may use these two):

    GET  /api/terminal/task       ?path=&task=&since=&n= -> {task, n, command, text, next, skipped, running,
                                  ended, words, commands}: what the task's newest command has printed
    POST /api/terminal/task/stop  {path, task, n?} -> {stopped, words}: stops that one command
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import terminal
from ..harness import livecmd

LOCAL_ONLY_WORDS = ("The command line only works in the app's own window on this computer. It's switched off "
                    "while the app is opened to other computers.")


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("POST", "/api/terminal/open"): lambda body: open_line(app, body or {}),
        ("POST", "/api/terminal/run"): lambda body: _do(app, body, lambda s, b: s.run(str(b.get("line", "")))),
        ("POST", "/api/terminal/input"): lambda body: _do(app, body, lambda s, b: s.input(str(b.get("text", "")))),
        ("POST", "/api/terminal/stop"): lambda body: _do(app, body, lambda s, b: s.stop()),
        ("GET", "/api/terminal/read"): lambda q: read(app, q),
        ("POST", "/api/terminal/close"): lambda body: close(app, body or {}),
        ("GET", "/api/terminal/task"): lambda q: task_tail(app, q),
        ("POST", "/api/terminal/task/stop"): lambda body: task_stop(app, body or {}),
    }


def _first(q: dict, key: str, default: str = "") -> str:
    v = q.get(key, default)
    if isinstance(v, list):
        v = v[0] if v else default
    return str(v if v is not None else default)


def _error(text: str, status: int = 400):
    from .server import ApiError

    return ApiError(text, status)


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def terminals(app) -> terminal.Terminals:
    t = getattr(app, "_terminals", None)
    if t is None:
        t = terminal.Terminals()
        app._terminals = t
    return t


def _local(app) -> None:
    if not getattr(app, "local_only", True):
        raise _error(LOCAL_ONLY_WORDS, 403)


def _project_root(app, path: str) -> Path:
    cfg = app.cfg()
    if not cfg:
        raise _error("Roundtable has no settings yet, so it can't find that project.", 404)
    return Path(app.project(cfg, path).root)


def open_line(app, body: dict) -> dict[str, Any]:
    _local(app)
    path = str(body.get("path") or "")
    if path:
        folder, project = _project_root(app, path), path
    else:
        folder, project = Path(str(body.get("folder") or Path.home())), ""
    try:
        return terminals(app).open(folder, project, fresh=bool(body.get("fresh"))).view()
    except terminal.TerminalError as e:
        raise _error(str(e)) from None


def _do(app, body, fn) -> dict[str, Any]:
    _local(app)
    body = body or {}
    try:
        return fn(terminals(app).get(str(body.get("id", ""))), body)
    except terminal.TerminalError as e:
        raise _error(str(e)) from None


def read(app, q: dict) -> dict[str, Any]:
    _local(app)
    try:
        s = terminals(app).get(_first(q, "id"))
    except terminal.TerminalError as e:
        raise _error(str(e), 404) from None
    wait = min(float(_int(_first(q, "wait", "0"))), terminal.WAIT_MAX)
    return s.read(_int(_first(q, "since", "0")), wait)


def close(app, body: dict) -> dict[str, Any]:
    _local(app)
    terminals(app).close(str(body.get("id", "")))
    return {"closed": True}


# -- a task's command, live ---------------------------------------------------------------------------
def _task(value: str) -> str:
    task = str(value or "")
    if not task or livecmd.safe_task(task) != task:
        raise _error("Which task? That name isn't one of this project's tasks.")
    return task


def task_tail(app, q: dict) -> dict[str, Any]:
    root = _project_root(app, _first(q, "path"))
    n = _first(q, "n")
    return livecmd.tail(root, _task(_first(q, "task")), _int(_first(q, "since", "0")), _int(n) if n else None)


def task_stop(app, body: dict) -> dict[str, Any]:
    root = _project_root(app, str(body.get("path") or ""))
    n = body.get("n")
    done = livecmd.stop(root, _task(str(body.get("task") or "")), _int(n) if n not in (None, "") else None)
    return {"stopped": done, "words": "Stopped. The task carries on without it." if done
            else "Nothing was running in that task."}
