"""What's news for the owner: one classifier for the desktop and the phone.

Five kinds, each with its own switch (and its own channel on the phone):

    finished   a run is done
    needs_you  a question, a plan to approve, a command waiting, a to-do or letters
    failed     a task stopped and waits for a decision
    money      a spending limit was reached, or an account ran out of credit
    idle       a run paused part-way with nothing happening for a long while

``snapshot(rt, at)`` turns the Hall's data (``GET /api/roundtable``) into a small, plain state;
``classify(old, new, open_project=None)`` compares two of them and returns the news, each with a ``key``
so the same news never comes twice, a ``group`` (the project) and ``quiet`` when that project is the one
on screen. ``buttons(ask)`` are the answers safe to give straight from a notification. The phone's twin
(``mobile/.../notify/Classifier.kt``) follows the same rules; both run the cases in
``mobile/app/src/test/resources/notify_cases.json``.

``Feed`` keeps the news for ``GET /api/notifications?since=`` (ui/notifyapi.py): the newest 200, the keys
already given out remembered in a file so a restart doesn't repeat them.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

KINDS = ("finished", "needs_you", "failed", "money", "idle")
KIND_NAMES = {"finished": "Finished", "needs_you": "Needs you", "failed": "Something stopped",
              "money": "Money", "idle": "Paused for a while"}
KIND_HINTS = {
    "finished": "A project has built everything in its plan.",
    "needs_you": "A question, a plan to approve, a command to allow, a to-do or letters.",
    "failed": "A task didn't work and waits for you to say what to do.",
    "money": "A spending limit was reached, or an account ran out of credit.",
    "idle": "A run stopped part-way and nothing has happened for a while.",
}
IDLE_AFTER_S = 30 * 60
BUTTON_KINDS = ("approve", "command", "decision", "question", "idea")
SHORT_QUESTION = 160
SHORT_LABEL = 30


@dataclass
class News:
    key: str
    kind: str
    project: str
    name: str
    title: str
    text: str = ""
    at: str = ""
    group: str = ""
    quiet: bool = False
    buttons: list[dict[str, str]] = field(default_factory=list)
    ask: dict[str, Any] | None = None
    # how the desktop answers it: here (POST /api/asks with path) or through the hub (hub_agent)
    via: str = ""
    path: str = ""
    hub_agent: str = ""

    def view(self) -> dict[str, Any]:
        return asdict(self)


# -- the state, from the Hall's data ---------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _secs(ts: str) -> float | None:
    s = str(ts or "").strip()
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def need_kind(ask_kind: str, actions: list[str] | tuple[str, ...]) -> str:
    """Which kind of news a waiting card is: money and failures have their own, the rest need you."""
    if ask_kind == "money" or "budget" in actions:
        return "money"
    if ask_kind == "failed" or "retry" in actions:
        return "failed"
    return "needs_you"


def need_key(n: dict[str, Any]) -> str:
    a = n.get("ask")
    if a:
        return f"ask:{n['project']}:{a.get('id', '')}:{a.get('stamp', '')}"
    return f"{n['kind']}:{n['project']}:{n.get('id') or n.get('task') or n.get('text', '')}"


def snapshot(rt: dict[str, Any], at: str | None = None) -> dict[str, Any]:
    """The few facts the classifier needs, from ``GET /api/roundtable``."""
    names = {s["id"]: s.get("name") or s["id"] for s in rt.get("seats") or []}
    projects = []
    for s in rt.get("seats") or []:
        prog = s.get("progress") or {}
        projects.append({
            "id": s["id"], "name": names[s["id"]], "status": s.get("status", "idle"), "state": s.get("state", ""),
            "done": int(prog.get("done") or 0), "total": int(prog.get("total") or 0),
            "last_activity": s.get("last_activity") or "",
            "paused": s.get("status") == "idle" and ("resume" in (s.get("actions") or [])
                                                      or "part-way" in (s.get("state") or "")),
        })
    needs = []
    for n in rt.get("needs_you") or []:
        ask = n.get("ask") or None
        needs.append({
            "key": need_key(n), "project": n["project"], "name": n.get("name") or names.get(n["project"], n["project"]),
            "kind": need_kind((ask or {}).get("kind", ""), n.get("actions") or []),
            "text": (ask or {}).get("question") or n.get("text", ""), "ask": ask,
            "via": n.get("via", ""), "path": (ask or {}).get("path") or n.get("path", ""),
            "hub_agent": n.get("hub_agent", ""),
        })
    return {"at": at or now_iso(), "projects": projects, "needs": needs}


# -- the rules ---------------------------------------------------------------------------------------
def buttons(ask: dict[str, Any] | None) -> list[dict[str, str]]:
    """Answers safe to give from the notification itself: never one that spends money, needs an "Are you
    sure?", takes several picks or a picture; only short cards."""
    if not ask or ask.get("multi") or ask.get("kind") not in BUTTON_KINDS:
        return []
    opts = ask.get("options") or []
    if any(o.get("confirm") or o.get("picture") for o in opts):
        return []
    if ask["kind"] == "approve":
        return [{"id": "approve", "label": "Approve plan"}] if any(o.get("id") == "approve" for o in opts) else []
    if len(opts) != 2 or len(ask.get("question") or "") > SHORT_QUESTION \
            or any(len(o.get("label") or "") > SHORT_LABEL for o in opts):
        return []
    return [{"id": str(o["id"]), "label": str(o["label"])} for o in opts]


def _need_words(n: dict[str, Any]) -> tuple[str, str]:
    name, ask = n["name"], n.get("ask") or {}
    text = n.get("text", "")
    if n["kind"] == "money":
        if "credit" in text and "ran out" in text:
            return f"{name}: an account is out of credit", text
        return f"{name} reached its money limit", text
    if n["kind"] == "failed":
        return f"{name}: a task stopped", text
    if ask.get("kind") == "approve":
        return f"{name}: the plan is ready", "Look at it, then approve it to start building."
    if ask.get("kind") == "command":
        return f"{name} wants to run a command", text
    return f"{name} needs you", text


def _idle_since(p: dict[str, Any], at: str) -> float | None:
    """How long a paused run has been quiet, when it counts as idle news."""
    if not p.get("paused"):
        return None
    then, now = _secs(p.get("last_activity", "")), _secs(at)
    if then is None or now is None or now - then < IDLE_AFTER_S:
        return None
    return now - then


def _for_a_while(secs: float) -> str:
    mins = int(secs // 60)
    if mins < 120:
        return f"{mins} minutes"
    hours = mins // 60
    return f"{hours} hours" if hours < 48 else f"{hours // 24} days"


def classify(old: dict[str, Any] | None, new: dict[str, Any], open_project: str | None = None) -> list[News]:
    """The news between two snapshots. With no old one (the first look), only what waits now is news."""
    at = new.get("at") or now_iso()
    out: list[News] = []
    before = {p["id"]: p for p in (old or {}).get("projects") or []}
    had = {n["key"] for n in (old or {}).get("needs") or []}

    for p in new.get("projects") or []:
        was = before.get(p["id"])
        if was is not None and was.get("status") != "done" and p.get("status") == "done":
            total = p.get("total") or 0
            out.append(News(f"finished:{p['id']}:{p.get('last_activity', '')}", "finished", p["id"], p["name"],
                            f"{p['name']} is finished",
                            f"All {total} tasks done. Open it to try it." if total else "Everything is done. Open it to try it."))
        quiet_for = _idle_since(p, at)
        if quiet_for is not None and was is not None and _idle_since(was, (old or {}).get("at", "")) is None:
            out.append(News(f"idle:{p['id']}:{p.get('last_activity', '')}", "idle", p["id"], p["name"],
                            f"{p['name']} has been paused a while",
                            f"Nothing has happened for {_for_a_while(quiet_for)}. Open it to carry on."))
    seen: set[str] = set()
    for n in new.get("needs") or []:
        if n["key"] in had or n["key"] in seen:
            continue
        seen.add(n["key"])
        title, text = _need_words(n)
        out.append(News(f"{n['kind']}:{n['key']}", n["kind"], n["project"], n["name"], title, text,
                        buttons=buttons(n.get("ask")), ask=n.get("ask"), via=n.get("via", ""),
                        path=n.get("path", ""), hub_agent=n.get("hub_agent", "")))
    for x in out:
        x.at, x.group = at, x.project
        x.quiet = bool(open_project) and x.project == open_project
    return out


# -- the desktop's list (GET /api/notifications) ------------------------------------------------------
class Feed:
    """The news so far: classify each new snapshot against the last, never the same key twice."""

    KEEP = 200
    KEYS = 1000

    def __init__(self, path: Path | None = None):
        self.path = path
        self.lock = threading.Lock()
        self.last: dict[str, Any] | None = None
        self.items: list[dict[str, Any]] = []
        self.n = 0
        self.keys: list[str] = []
        if path and path.is_file():
            try:
                self.keys = list(json.loads(path.read_text(encoding="utf-8")).get("keys") or [])[-self.KEYS:]
            except (OSError, ValueError):
                self.keys = []

    def update(self, snap: dict[str, Any]) -> list[dict[str, Any]]:
        with self.lock:
            fresh = [x for x in classify(self.last, snap) if x.key not in self.keys]
            self.last = snap
            added = []
            for x in fresh:
                self.n += 1
                added.append({"n": self.n, **x.view()})
                self.keys.append(x.key)
            if added:
                self.items = (self.items + added)[-self.KEEP:]
                self.keys = self.keys[-self.KEYS:]
                self._save()
            return added

    def since(self, since: str | int | None) -> list[dict[str, Any]]:
        """News after ``since``: the ``next`` number an earlier answer gave, or a time (ISO)."""
        with self.lock:
            if since in (None, ""):
                return list(self.items)
            try:
                n = int(since)
            except (TypeError, ValueError):
                t = _secs(str(since))
                return [x for x in self.items if t is None or (_secs(x["at"]) or 0) > t]
            return [x for x in self.items if x["n"] > n]

    def _save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"keys": self.keys}), encoding="utf-8")
        except OSError:
            pass  # remembered for this session at least


# -- switches per kind (per machine) -----------------------------------------------------------------
def default_settings() -> dict[str, Any]:
    return {"kinds": {k: True for k in KINDS}, "popups": True}


def load_settings(path: Path) -> dict[str, Any]:
    out = default_settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    for k, v in (data.get("kinds") or {}).items():
        if k in KINDS:
            out["kinds"][k] = bool(v)
    if "popups" in data:
        out["popups"] = bool(data["popups"])
    return out


def save_settings(path: Path, changes: dict[str, Any]) -> dict[str, Any]:
    cur = load_settings(path)
    for k, v in (changes.get("kinds") or {}).items():
        if k in KINDS:
            cur["kinds"][k] = bool(v)
    if "popups" in changes:
        cur["popups"] = bool(changes["popups"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    return cur
