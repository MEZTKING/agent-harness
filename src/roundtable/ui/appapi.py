"""The App tab's Start: an app that starts with a command, started on this PC and shown in a frame.

    GET  /api/app?path=        -> {static, command, from, state, running, url, error, started_at, words}
    POST /api/app/start {path} -> the same; starts it (this PC only, while the app is local-only)
    POST /api/app/stop  {path} -> the same; ends it and everything it started

``state`` is ``off``, ``starting``, ``running`` or ``failed``. A started app is ended after ``IDLE_MINUTES``
without anyone looking (each GET counts as a look) and when the desktop app closes (``stop_all``). The phone
never starts anything: these aren't phone routes, and start and stop are refused while the app is opened to
other computers, as the command line is. Pressing Start is the owner's own yes, with the command shown on the
card, so it doesn't wait at the gate; the environment is still the clean one (no keys).
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from ..harness import appserver, showit

IDLE_MINUTES = 30
# what the desktop page's frame-src must allow for the App tab's frame (an app started here, on any local port)
FRAME_SRC = "http://127.0.0.1:*"
LOCAL_ONLY_WORDS = ("Starting an app only works in the app's own window on this computer. It's switched off "
                    "while the app is opened to other computers.")

_lock = threading.RLock()
_apps: dict[str, dict[str, Any]] = {}  # project folder -> {run, state, error, started_at, seen}
_reaper: threading.Thread | None = None


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/app"): lambda q: view(app, q),
        ("POST", "/api/app/start"): lambda body: start(app, body or {}),
        ("POST", "/api/app/stop"): lambda body: stop(app, body or {}),
    }


def _error(text: str, status: int = 400):
    from .server import ApiError

    return ApiError(text, status)


def _first(q: dict, key: str) -> str:
    v = q.get(key, "")
    if isinstance(v, list):
        v = v[0] if v else ""
    return str(v or "")


def _local(app) -> None:
    if not getattr(app, "local_only", True):
        raise _error(LOCAL_ONLY_WORDS, 403)


def _root(app, path: str) -> Path:
    cfg = app.cfg()
    if not cfg:
        raise _error("The harness has no settings yet, so it can't find that project.", 404)
    return Path(app.project(cfg, path).root).resolve()


def _kind_start(root: Path) -> Any:
    """The project's kind's ``start:`` recipe, from the copy frozen when the plan was approved."""
    from ..harness.kindstage import FROZEN

    try:
        kind = json.loads((root / ".harness" / FROZEN).read_text(encoding="utf-8")).get("kind") or {}
        return (kind.get("spec") or {}).get("start")
    except (OSError, ValueError, AttributeError):
        return None


def recipe_for(root: Path) -> dict[str, Any] | None:
    return appserver.start_recipe(root, _kind_start(root))


def _state(root: Path) -> dict[str, Any]:
    with _lock:
        rec = _apps.get(str(root))
        if rec is None:
            return {"state": "off", "running": False, "url": "", "error": "", "started_at": 0}
        run = rec["run"]
        state = rec["state"]
        if state == "running" and not run.alive():  # it stopped by itself
            state = rec["state"] = "failed"
            rec["error"] = "the app stopped by itself: " + (run.output().strip().splitlines() or ["no output"])[-1][:200]
        return {"state": state, "running": state == "running", "url": run.url if state == "running" else "",
                "error": rec.get("error", ""), "started_at": rec.get("started_at", 0)}


def _words(info: dict[str, Any]) -> str:
    if info["state"] == "running":
        return f"Running on this PC at {info['url']}. It stops by itself after {IDLE_MINUTES} minutes nobody looks."
    if info["state"] == "starting":
        return "Starting it… this can take up to a minute."
    if info["state"] == "failed":
        return f"It didn't start: {info['error']}"
    if info.get("command"):
        return "This app starts with a command. Start it to use it here."
    return "This app opens as a page: its pictures are below." if info.get("static") else "There's nothing to start yet."


def view_of(root: Path) -> dict[str, Any]:
    recipe = recipe_for(root)
    info: dict[str, Any] = {"static": showit.entry_page(root), "command": (recipe or {}).get("command"),
                            "from": (recipe or {}).get("from"), **_state(root)}
    info["words"] = _words(info)
    with _lock:
        if str(root) in _apps:
            _apps[str(root)]["seen"] = time.time()
    return info


def view(app, q: dict) -> dict[str, Any]:
    return view_of(_root(app, _first(q, "path")))


def start_folder(root: Path, seconds: float = appserver.START_SECONDS) -> dict[str, Any]:
    """Start the project's app in the background (the call returns at once; GET follows it)."""
    recipe = recipe_for(root)
    if not recipe:
        raise _error("This app has no start command, so there's nothing to start. Its pictures are in the App tab.")
    with _lock:
        rec = _apps.get(str(root))
        if rec and rec["state"] in ("starting", "running") and (rec["state"] == "starting" or rec["run"].alive()):
            return view_of(root)
        if rec:
            rec["run"].__exit__(None, None, None)
        run = appserver.Running(root, recipe["command"], port=recipe.get("port"), ready=recipe.get("ready", ""),
                                seconds=seconds, live=(root, "app"), ask=lambda c: None)  # the owner's own Start
        _apps[str(root)] = {"run": run, "state": "starting", "error": "", "started_at": time.time(), "seen": time.time()}

    def go() -> None:
        run.__enter__()
        with _lock:
            rec = _apps.get(str(root))
            if rec is None or rec["run"] is not run:  # stopped while it started
                run.__exit__(None, None, None)
                return
            rec["state"] = "running" if run.ok else "failed"
            rec["error"] = run.error
            rec["seen"] = time.time()

    threading.Thread(target=go, daemon=True, name="app-start").start()
    _start_reaper()
    return view_of(root)


def stop_folder(root: Path) -> dict[str, Any]:
    with _lock:
        rec = _apps.pop(str(root), None)
    if rec:
        rec["run"].__exit__(None, None, None)
    return view_of(root)


def start(app, body: dict) -> dict[str, Any]:
    _local(app)
    return start_folder(_root(app, str(body.get("path") or "")))


def stop(app, body: dict) -> dict[str, Any]:
    _local(app)
    return stop_folder(_root(app, str(body.get("path") or "")))


def reap(now: float | None = None) -> int:
    """End apps nobody has looked at for IDLE_MINUTES. Returns how many were ended."""
    now = time.time() if now is None else now
    with _lock:
        idle = [k for k, r in _apps.items() if now - float(r.get("seen") or 0) > IDLE_MINUTES * 60]
        recs = [_apps.pop(k) for k in idle]
    for r in recs:
        r["run"].__exit__(None, None, None)
    return len(recs)


def _start_reaper() -> None:
    global _reaper
    with _lock:
        if _reaper is not None and _reaper.is_alive():
            return

        def loop() -> None:
            while True:
                time.sleep(60)
                reap()
                with _lock:
                    if not _apps:
                        return

        _reaper = threading.Thread(target=loop, daemon=True, name="app-reaper")
        _reaper.start()


def stop_all() -> int:
    """At exit: end every app started from the App tab."""
    with _lock:
        recs = list(_apps.values())
        _apps.clear()
    for r in recs:
        r["run"].__exit__(None, None, None)
    return len(recs)
