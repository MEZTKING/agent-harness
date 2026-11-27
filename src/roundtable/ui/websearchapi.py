"""Web search for builders (harness/websearch.py) as an API, for the desktop's Tools page. Stays on the PC.

    GET  /api/websearch        {enabled, engine, active: {id, name, best_effort}, engines: [{id, name, ready,
                                best_effort, key, key_name, words}], roles, max_searches_per_task,
                                max_reads_per_task, max_searches_per_day, searxng_url, today: {searches, reads},
                                words}
    POST /api/websearch        {enabled?, engine?, roles?, max_searches_per_task?, max_reads_per_task?,
                                max_searches_per_day?, searxng_url?} -> the same as GET (kept in custom.yaml;
                                harness.yaml is never rewritten)
    POST /api/websearch/test   {query?} -> {ok, engine, best_effort, results: [{title, url, snippet}], words}

Keys are never sent or shown here: only whether one is set. They are added through the app's key form.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from ..harness import websearch as ws

ENGINE_WORDS = {
    "auto": "The best one that's set up: Brave or Tavily with a key, then your own SearXNG, else DuckDuckGo.",
    "brave": "Brave Search: steady and fast. Needs a Brave Search key.",
    "tavily": "Tavily: made for AI helpers. Needs a Tavily key.",
    "searxng": "SearXNG: a search you run yourself. Needs its address.",
    "duckduckgo": "DuckDuckGo: no key needed, best effort (it may give fewer results or refuse at times).",
}


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/websearch"): lambda q: view(app),
        ("POST", "/api/websearch"): lambda body: save(app, body or {}),
        ("POST", "/api/websearch/test"): lambda body: test(app, body or {}),
    }


def _cfg(app):
    try:
        return app.cfg()
    except Exception:
        return None


def _path(app) -> Path | None:
    cfg = _cfg(app)
    p = getattr(cfg, "path", None) or getattr(app, "harness_config_path", None)
    return Path(p) if p else None


def _projects(app) -> list[Path]:
    try:
        return list(app._lab_projects())
    except Exception:
        return []


def today(app) -> dict[str, int]:
    out = {"searches": 0, "reads": 0}
    for root in _projects(app):
        c = ws.today_counts(root)
        out["searches"] += int(c.get("searches") or 0)
        out["reads"] += int(c.get("reads") or 0)
    tried = getattr(app, "_websearch_tried", None)
    if tried and tried[0] == date.today().isoformat():
        out["searches"] += tried[1]
    return out


def view(app) -> dict[str, Any]:
    s = ws.settings(_cfg(app))
    first = ws.active(s)
    engines = [{"id": e.id, "name": e.name, "ready": e.ready(s), "best_effort": e.best_effort, "key": bool(e.key),
                "key_name": ws.KEY_NAMES.get(e.key or "", ""), "words": ENGINE_WORDS[e.id]} for e in ws.ALL.values()]
    if not s["enabled"]:
        words = "Builders don't search the web."
    else:
        words = f"Builders can look things up with {first.name}" + (" (best effort)." if first.best_effort else ".")
    return {**s, "active": {"id": first.id, "name": first.name, "best_effort": first.best_effort},
            "engines": engines, "engine_words": ENGINE_WORDS, "today": today(app), "words": words}


def save(app, body: dict[str, Any]) -> dict[str, Any]:
    from ..harness.config import load_custom, save_custom
    from .server import ApiError

    path = _path(app)
    if not path or not path.is_file():
        raise ApiError("Roundtable's settings aren't set up on this computer yet. Run the set-up in Settings first.",
                       503)
    custom = load_custom(path)
    mine = dict(custom.get("websearch") or {})
    changes = {k: v for k, v in body.items() if k in ws.DEFAULTS}
    try:
        ws.clean_settings({**mine, **changes})
    except ValueError as e:
        raise ApiError(f"Nothing was changed: {e}.") from None
    mine.update(changes)
    custom["websearch"] = mine
    save_custom(path, custom)
    return view(app)


def test(app, body: dict[str, Any]) -> dict[str, Any]:
    from ..harness.tools import ToolError
    from .server import ApiError

    s = ws.settings(_cfg(app))
    try:
        query = ws.guard_query(body.get("query") or "python list sort documentation")
    except ToolError as e:
        raise ApiError(f"{e}.") from None
    try:
        engine, hits, tried = ws.search(query, 3, s, getattr(app, "_websearch_opener", None))
    except ws.SearchError as e:
        return {"ok": False, "engine": "", "best_effort": False, "results": [],
                "words": f"The search didn't work: {e}. Check the key in Settings → Keys, or choose another engine."}
    day = date.today().isoformat()
    t = getattr(app, "_websearch_tried", None)
    app._websearch_tried = (day, (t[1] if t and t[0] == day else 0) + 1)
    words = f"{engine.name} answered with {len(hits)} result{'s' if len(hits) != 1 else ''}."
    if tried:
        words += f" (Tried first: {'; '.join(tried)}.)"
    return {"ok": True, "engine": engine.name, "best_effort": engine.best_effort, "results": hits, "words": words}
