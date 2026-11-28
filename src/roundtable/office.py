"""The office: a second view of the Hall where each agent can be seen at work (wave 9).

No model is asked: where each agent stands comes from what the harness already knows about each project on this
computer (``quiet.state``, the running tasks, the newest events, the commands ``livecmd`` lists), and nothing here
invents activity: an agent with no running task and no recent event isn't in the office.

Where they stand (``at`` is a spot in the manifest's layout; ``bubble`` one of its bubbles):

* building -> a desk, the work loop; reading files or searching -> the shelf; a command running -> the terminal;
* waiting for the owner -> the door, the question bubble, in ember (``tone: "flare"``); money stopped it -> the coin;
* gone quiet -> the desk, the warning bubble; a letter just sent -> the mailbox, the letter bubble;
* a task just passed -> the tick; resting after recent work -> the sofa, asleep.

One room per project with something to show, at most ``MAX_ROOMS`` (``more`` says how many others).
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_ROOMS = 4
RECENT_S = 120  # a tick or a letter shows this long after it happened
REST_SHOW_S = 1800  # a project that finished work this recently shows its agent resting
READING = {"read_file", "list_files", "search"}
LETTERS = ("hub_send", "hub_reply")
MONEY = {"money", "money_nothing_done", "money_day", "budget", "allowance"}
ORDER = {"waiting": 0, "quiet": 1, "working": 2, "resting": 3}


def _ts(text: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _json(p: Path, default: Any) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _events(root: Path, tail: int = 300) -> list[dict[str, Any]]:
    p = root / ".harness" / "events.jsonl"
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 262144))
            lines = f.read().decode("utf-8", "replace").splitlines()[-tail:]
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


class _Team:
    """Who holds each job: the hired agent's name and sprite, else a plain helper figure."""

    def __init__(self, cfg: Any, home: Path | None, figures: set[str]):
        from . import agents

        self.cfg, self.figures, self.jobs = cfg, figures, agents.JOBS
        self.hired: dict[str, Any] = {}
        if home is not None:
            try:
                for a in agents.load_all(home):
                    if a.hired:
                        self.hired.setdefault(a.job, a)
            except Exception:  # noqa: BLE001 - no agents folder: everyone is a helper
                pass
        self._helpers: dict[str, str] = {}

    def job(self, role: str) -> str:
        from . import agents

        try:
            return agents.job_of(self.cfg, role)
        except Exception:  # noqa: BLE001 - no settings: a builder
            return "builder"

    def who(self, job: str) -> dict[str, str]:
        a = self.hired.get(job)
        job_name = self.jobs.get(job, (job.replace("_", " ").title(), ""))[0]
        if a is not None and a.id in self.figures:
            return {"key": a.id, "agent": a.id, "name": a.name, "job": job_name}
        if job not in self._helpers:  # an agent with no face of its own: one of the two plain helpers
            self._helpers[job] = ("helper-a", "helper-b")[len(self._helpers) % 2]
        sprite = self._helpers[job]
        return {"key": a.id if a is not None else f"job-{job}", "agent": sprite,
                "name": a.name if a is not None else job_name, "job": job_name}


def _busy(app, root: Path) -> bool | None:
    jobs = getattr(getattr(app, "jobs", None), "jobs", None)
    if jobs is None:
        return None
    return any(getattr(j, "target", None) == str(root) and getattr(j, "status", "") == "running" for j in jobs.values())


def _task_place(task_id: str, events: list[dict[str, Any]], commands: list[dict[str, Any]], now: float,
                title: str) -> tuple[str, str, str | None]:
    """(spot, doing, bubble) for a task being built, from its newest events."""
    if any(str(c.get("task") or "") == task_id for c in commands):
        return "terminal", "Running a command", None
    for e in reversed(events):
        if e.get("task") != task_id:
            continue
        if e.get("event") != "tool_call":
            break
        tool = str(e.get("tool") or "")
        age = now - (_ts(e.get("at")) or 0)
        if tool.endswith(LETTERS) and age <= RECENT_S:
            return "mailbox", "Sending a letter", "letter"
        if tool in READING:
            return "shelf", "Searching the files" if tool == "search" else "Reading files", None
        break
    return "desk", f"Building: {title}" if title else "Building", None


def _room(app, cfg: Any, team: _Team, root: Path, now: float) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    from .harness import livecmd, quiet

    hdir = root / ".harness"
    meta = _json(hdir / "project.json", {}) or {}
    tasks = [t for t in (_json(hdir / "tasks.json", []) or []) if isinstance(t, dict)]
    events = _events(root)
    try:
        st = quiet.state(root, now, cfg=cfg, busy=_busy(app, root))
    except Exception:  # noqa: BLE001 - a project that can't be read is left out
        return None
    commands = [c for c in livecmd.running(root) if float(c.get("until") or 0) > now]
    last = _ts(st.get("last_at")) if st.get("last_at") else None
    status = str(meta.get("status") or "")
    actors: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(job: str, at: str, doing: str, bubble: str | None, task: dict[str, Any] | None, tone: str = "") -> None:
        w = team.who(job)
        if w["key"] in seen:
            return
        seen.add(w["key"])
        actors.append({"id": f"{root.name}:{w['key']}", "name": w["name"], "job": w["job"], "agent": w["agent"],
                       "at": at, "doing": doing, "bubble": bubble, "project": root.name, "path": str(root),
                       "task": (task or {}).get("id"), "tone": tone})

    running = [t for t in tasks if t.get("status") == "running"]
    by_id = {str(t.get("id")): t for t in tasks}
    if st["state"] == "waiting":
        failed = next((t for t in tasks if t.get("status") == "failed"), None)
        money = status == "paused_budget" or str(meta.get("pause") or "") in MONEY
        if status == "awaiting_approval":
            add("planner", "door", "Waiting for you to approve the plan", "question", None, "flare")
        else:
            t = failed or (running[0] if running else None)
            add(team.job(str((t or {}).get("role") or "")) if t else "builder", "door",
                "Stopped at the spending limit" if money else "Waiting for your answer",
                "coin" if money else "question", t, "flare")
    elif st["state"] in ("working", "quiet"):
        quiet_now = st["state"] == "quiet"
        for t in running:
            at, doing, bubble = _task_place(str(t.get("id")), events, commands, now, str(t.get("title") or ""))
            if quiet_now:
                at, doing, bubble = "desk", st["line"], "warning"
            add(team.job(str(t.get("role") or "")), at, doing, bubble, t)
        if not running and status == "planning":
            add("planner", "whiteboard", st["line"] if quiet_now else "Making the plan", "warning" if quiet_now else None, None)
        if not running and commands:  # a command still running after its task (a long build)
            t = by_id.get(str(commands[0].get("task") or ""))
            add(team.job(str((t or {}).get("role") or "")), "terminal", "Running a command", None, t)
    # a task that passed lately: its agent shows the tick (at its desk if still working, else on the sofa)
    for e in reversed(events):
        if e.get("event") != "task_end" or e.get("status") != "done":
            continue
        age = now - (_ts(e.get("at")) or 0)
        t = by_id.get(str(e.get("task")))
        if t and age <= RECENT_S:
            add(team.job(str(t.get("role") or "")), "desk" if st["state"] == "working" else "sofa", "Finished a task",
                "tick", t)
        elif t and st["state"] == "resting" and age <= REST_SHOW_S and not actors:
            add(team.job(str(t.get("role") or "")), "sofa", "Resting", "asleep", t)
        break
    if not actors:
        return None
    from .ui.hall import friendly

    room = {"id": root.name, "name": friendly(root.name), "path": str(root), "state": st["state"], "word": st["word"],
            "line": st["line"], "last_at": st.get("last_at") or "", "actors": len(actors)}
    room["_rank"] = (ORDER.get(st["state"], 9), -(last or 0))
    return room, actors


def scene(app) -> dict[str, Any]:
    """``{"rooms": [...], "actors": [{"id", "name", "at", "doing", "bubble", "project"}], "art": bool}``.

    Each actor also has ``agent`` (whose figure), ``job``, ``path``, ``task`` and ``tone``; each room ``state`` and
    ``line``. ``more`` counts the rooms not shown; ``words`` is one plain sentence."""
    if app is None:
        return {"rooms": [], "actors": [], "art": False}
    from . import officeart

    cfg = app.cfg() if callable(getattr(app, "cfg", None)) else None
    try:
        home = Path(app._backup_home())
    except Exception:  # noqa: BLE001 - no home folder: helpers only
        home = None
    figures = set((officeart.layout().get("agents") or {}))
    team = _Team(cfg, home, figures)
    lab = getattr(app, "_lab_projects", None)
    projects = lab() if callable(lab) else []
    now = time.time()
    found = []
    for root in projects:
        got = _room(app, cfg, team, Path(root), now)
        if got:
            found.append(got)
    found.sort(key=lambda x: x[0]["_rank"])
    shown = found[:MAX_ROOMS]
    rooms, actors = [], []
    for room, acts in shown:
        room.pop("_rank", None)
        rooms.append(room)
        actors.extend(acts)
    more = len(found) - len(shown)
    n = len(actors)
    words = ("Nobody is working right now." if not n else
             f"{n} at work in {len(rooms)} project{'s' if len(rooms) != 1 else ''}"
             + (f", and {more} more" if more else "") + ".")
    return {"rooms": rooms, "actors": actors, "art": officeart.ready(app), "more": more, "words": words}
