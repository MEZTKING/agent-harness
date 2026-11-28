"""What you use most, counted on this computer only (wave 9, MD-91).

The owner's answer (27 November 2026): counted here and shown to the owner, never sent anywhere.

* :func:`count` adds one to a *family* for today, in one small file in the app's own folder
  (``<home>/counts.json``). A family is what :func:`family` makes from a route: ``see.<screen>`` for a screen
  opened (a GET) and ``do.<button>`` for a button family pressed (a POST), at most three words of the route,
  lower-case letters only. Anything else is refused, so no project name, no text and no id can be counted: a
  route that carries a name in its path (``/api/journal/<project>``) is cut to its first word.
* A screen that refreshes itself is one look, not hundreds: a ``see.`` family counts at most once every
  ``LOOK_S`` seconds.
* :func:`view` gives the owner their own numbers (Settings → What you use most); :func:`clear` empties the file;
  :func:`set_on` stops or restarts counting. Days older than ``KEEP_DAYS`` are dropped when the file is written.

Nothing here opens a connection: ``tests/test_localcounts.py`` reads this file and fails on any network module.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

FILE = "counts.json"
KEEP_DAYS = 90
LOOK_S = 600  # a screen open and refreshing counts once in ten minutes
# routes whose second word is a name or an id (the rest of the path is never kept)
PARAMETRISED = {"journal", "inbox", "jobs", "cards", "plugins"}
# routes nobody presses: the app's own background checks
QUIET = {"features", "changes", "ping", "health", "counts", "pair"}
_WORD = re.compile(r"[a-z][a-z_-]{0,23}")
_FAMILY = re.compile(r"(?:see|do)(?:\.[a-z][a-z_-]{0,23}){1,3}")

_LOCK = threading.Lock()
_LOOKED: dict[tuple[str, str], float] = {}  # (home, family) -> when it was last counted

# plain names for the commonest families; anything else is shown as its route words
NAMES = {
    "see.roundtable": "Home", "see.asks": "Needs you", "see.projects": "Projects", "see.project": "A project",
    "see.plan": "A plan", "see.activity": "Activity", "see.chat": "Chat", "see.gallery": "Gallery",
    "see.files": "Files", "see.board": "The board", "see.usage": "What's been used", "see.agents": "Agents",
    "see.tools": "Tools", "see.search": "Search", "see.journal": "The journal", "see.inbox": "Earlier messages",
    "do.plan": "Plan buttons", "do.asks": "Answering cards", "do.chat": "Sending a message",
    "do.send": "Sending a letter", "do.project": "Project buttons", "do.projects": "Making a project",
    "do.attach.send": "Sending with files", "do.board.answer-several": "Answer these",
    "do.queue": "The queue", "do.rewind": "Undo a task", "do.app.start": "Starting an app",
}


def family(method: str, path: str) -> str | None:
    """``see.<words>`` or ``do.<words>`` for an API route, or None when it isn't counted."""
    parts = [p for p in str(path or "").split("?")[0].strip("/").split("/") if p]
    if len(parts) < 2 or parts[0] != "api":
        return None
    parts = parts[1:]
    if parts[0] in PARAMETRISED:
        parts = parts[:1]
    words: list[str] = []
    for p in parts[:3]:
        if not _WORD.fullmatch(p):
            break
        words.append(p)
    if not words or words[0] in QUIET:
        return None
    verb = "see" if str(method).upper() == "GET" else "do"
    return ".".join([verb, *words])


def _path(home) -> Path:
    if home is None:
        from .desktop import app_home

        home = app_home()
    return Path(home) / FILE


def _load(p: Path) -> dict[str, Any]:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"days": {}}
    if not isinstance(data, dict):
        return {"days": {}}
    days = data.get("days")
    data["days"] = days if isinstance(days, dict) else {}
    return data


def _save(p: Path, data: dict[str, Any]) -> None:
    cut = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
    data["days"] = {d: v for d, v in data["days"].items() if str(d) >= cut}
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def is_on(home) -> bool:
    return not _load(_path(home)).get("off")


def count(home, what: str) -> None:
    """Add one to ``what`` (a family from :func:`family`) for today. Anything that isn't a family is ignored."""
    what = str(what or "")
    if not _FAMILY.fullmatch(what) or what.split(".")[1] in QUIET:
        return None
    p = _path(home)
    now = time.monotonic()
    with _LOCK:
        if what.startswith("see."):
            key = (str(p), what)
            if now - _LOOKED.get(key, -LOOK_S - 1) < LOOK_S:
                return None
            _LOOKED[key] = now
        try:
            data = _load(p)
            if data.get("off"):
                return None
            day = data["days"].setdefault(date.today().isoformat(), {})
            day[what] = int(day.get(what) or 0) + 1
            _save(p, data)
        except OSError:  # counting is never worth an error
            return None
    return None


def name_of(fam: str) -> str:
    if fam in NAMES:
        return NAMES[fam]
    verb, _, rest = fam.partition(".")
    words = rest.replace(".", " ").replace("_", " ").replace("-", " ")
    return (f"{words.capitalize()} (opened)" if verb == "see" else f"{words.capitalize()} (pressed)")


def view(home, days: int = 30) -> dict[str, Any]:
    """{on, top: [{family, name, count}], screens, buttons, days, since, words}: the last ``days`` days."""
    data = _load(_path(home))
    cut = (date.today() - timedelta(days=max(1, days) - 1)).isoformat()
    sums: dict[str, int] = {}
    seen_days = sorted(d for d in data["days"] if str(d) >= cut)
    for d in seen_days:
        for fam, n in (data["days"].get(d) or {}).items():
            if _FAMILY.fullmatch(str(fam)):
                sums[fam] = sums.get(fam, 0) + int(n or 0)
    rows = sorted(({"family": f, "name": name_of(f), "count": n} for f, n in sums.items()),
                  key=lambda r: (-r["count"], r["family"]))
    on = not data.get("off")
    if not on:
        words = "Counting is off. Nothing new is counted until you turn it back on."
    elif not rows:
        words = "Nothing counted yet. Use the app for a while and your most-used parts show here."
    else:
        words = f"Most used in the last {days} days: {rows[0]['name']}."
    return {"on": on, "top": rows[:10], "screens": [r for r in rows if r["family"].startswith("see.")],
            "buttons": [r for r in rows if r["family"].startswith("do.")], "days": len(seen_days),
            "since": seen_days[0] if seen_days else "", "words": words,
            "note": "Counted on this computer only and never sent anywhere. No project names, no text."}


def clear(home) -> dict[str, Any]:
    p = _path(home)
    with _LOCK:
        data = _load(p)
        data["days"] = {}
        data["cleared_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        _save(p, data)
        for k in [k for k in _LOOKED if k[0] == str(p)]:
            _LOOKED.pop(k, None)
    return view(home)


def set_on(home, on: bool) -> dict[str, Any]:
    p = _path(home)
    with _LOCK:
        data = _load(p)
        if on:
            data.pop("off", None)
        else:
            data["off"] = True
        _save(p, data)
    return view(home)
