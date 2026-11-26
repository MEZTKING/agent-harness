"""Data for the Roundtable main screen: every project at the table with its live
status, what needs the owner, a live activity feed, model health and spend.

Kept separate from server.py so it can be tested without HTTP.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .server import harness_event_line

FEED_EVENTS = ("task_start", "attempt", "tool_call", "review", "task_end", "plan", "planning", "status", "steer",
               "provider_error", "goal")
RECENTLY_ACTIVE_S = 120  # a run with events this recent counts as running even if another process drives it


def _read_jsonl(path: Path, tail: int | None = None) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    if tail:
        lines = lines[-tail:]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def _age_s(ts: str) -> float:
    try:
        then = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return 1e12
    return (datetime.now(timezone.utc) - then).total_seconds()


def run_seat(app, path: Path) -> dict[str, Any]:
    """Status of one harness project as a seat at the table."""
    hdir = path / ".harness"
    meta = json.loads((hdir / "project.json").read_text())
    tasks = json.loads((hdir / "tasks.json").read_text() or "[]")
    events = _read_jsonl(hdir / "events.jsonl", tail=60)
    done = sum(t["status"] == "done" for t in tasks)
    failed = [t for t in tasks if t["status"] == "failed"]
    running_task = next((t for t in tasks if t["status"] == "running"), None)
    job = next((j for j in app.jobs.jobs.values() if j.target == str(path) and j.status == "running"), None)
    last_at = events[-1]["at"] if events else (meta.get("updated_at") or meta.get("created_at", ""))
    status, detail, actions = "idle", "", []
    st = meta.get("status")
    if job or (running_task and _age_s(last_at) < RECENTLY_ACTIVE_S) or (st == "planning" and job):
        status = "running"
        last_attempt = next((e for e in reversed(events) if e.get("event") == "attempt"), None)
        if running_task:
            detail = f"{running_task['id']} {running_task['title']}"
            if last_attempt and last_attempt.get("task") == running_task["id"]:
                detail += f" · {running_task['role']} on {last_attempt.get('model')}"
        else:
            detail = "planning…"
    elif st == "awaiting_approval":
        from ..harness.plandoc import summary_line

        doc = None
        try:
            doc = json.loads((hdir / "plan.json").read_text())
        except (OSError, ValueError):
            pass
        line = summary_line(doc) if doc else "plan ready"
        status, detail, actions = "waiting", f"{line}: review and approve it to start", ["approve"]
    elif st == "blocked" and failed:
        t = failed[0]
        status, detail, actions = "waiting", f"{t['id']} {t['title']} failed", ["retry", "skip"]
    elif st == "paused_budget":
        status, detail, actions = "waiting", "paused at the budget limit", ["budget"]
    elif st == "done":
        status, detail = "done", "all tasks done"
    elif st in ("paused", "running", "planning"):
        status, detail, actions = "idle", "stopped part-way: resume when ready", ["resume"]
    return {
        "id": path.name, "path": str(path), "kind": "run", "status": status, "detail": detail, "actions": actions,
        "failed_task": failed[0]["id"] if failed else None,
        "progress": {"done": done, "total": len(tasks)}, "goal": (meta.get("goals") or [""])[-1],
        "spent_usd": meta.get("spent_usd", 0), "last_activity": last_at,
    }


ASK_STATES = ("awaiting_approval", "blocked", "paused", "paused_budget")


def _asks(cfg, path: Path) -> list[dict[str, Any]]:
    """The project's open cards (asks.py), only when it is waiting for the owner; never breaks the table."""
    try:
        meta = json.loads((path / ".harness" / "project.json").read_text())
        if meta.get("status") not in ASK_STATES:
            return []
        from ..asks import open_asks
        from ..harness.orchestrator import Orchestrator

        return open_asks(Orchestrator(cfg, path))
    except Exception:
        return []


def build(app) -> dict[str, Any]:
    seats: dict[str, dict[str, Any]] = {}
    needs: list[dict[str, Any]] = []

    # hub projects (journal)
    if app.hub:
        with app.hub_lock:
            app.hub.store.sync()
            briefs = [app.hub.journal.brief(a, a) for a in app.hub.config.agents]
            unread = {a: len(app.hub.inbox(a, unread_only=True, limit=200)) for a in app.hub.config.agents}
        for b in briefs:
            high = [e for e in b["open_todos"] if e["priority"] == "high"]
            seats[b["agent"]] = {
                "id": b["agent"], "kind": "hub", "status": "idle", "detail": "", "actions": [],
                "repo": b["repo"], "description": b["description"], "last_activity": b["last_activity"],
                "open_todos": len(b["open_todos"]), "high": len(high), "unread": unread.get(b["agent"], 0),
                "last_session": b["last_session"], "brief": b,
            }
            for e in high[:3]:
                needs.append({"kind": "todo", "project": b["agent"], "text": e["text"], "id": e["id"],
                              "actions": ["done"], "at": e["created_at"]})
        for agent, n in unread.items():
            if n and agent == app.agent:
                needs.append({"kind": "messages", "project": agent, "text": f"{n} unread message(s)",
                              "actions": ["read"], "at": ""})

    # harness runs: merged into the hub seat with the same name, else a seat of their own
    cfg = app.cfg()
    spend_today = 0.0
    health: list[dict[str, Any]] = []
    if cfg and cfg.lab_dir:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for path in app.lab(cfg).projects():
            try:
                run = run_seat(app, path)
            except (OSError, json.JSONDecodeError):
                continue
            for m in _read_jsonl(path / ".harness" / "spend.jsonl"):
                if str(m.get("at", "")).startswith(today):
                    spend_today += m.get("cost_usd") or 0
            seat = seats.get(run["id"])
            if seat:
                seat.update({k: v for k, v in run.items() if k not in ("id",)})
                seat["kind"] = "both"
                seat["last_activity"] = max(seat.get("last_activity") or "", run["last_activity"] or "")
            else:
                seats[run["id"]] = {**run, "open_todos": 0, "high": 0, "unread": 0, "repo": "", "description": ""}
            asks = _asks(cfg, path) if run["status"] != "running" else []
            if run["status"] == "waiting" or asks:
                needs.insert(0, {"kind": "run", "project": run["id"], "path": run["path"], "text": run["detail"],
                                 "actions": run["actions"], "task": run["failed_task"], "at": run["last_activity"],
                                 # the next card to tap, and how many more wait on the plan page
                                 "ask": asks[0] if asks else None, "asks": len(asks)})
        # model health: latest probe run per model
        latest: dict[str, dict[str, Any]] = {}
        for r in _read_jsonl(cfg.lab_dir / "probes.jsonl"):
            cur = latest.setdefault(r["model"], {"model": r["model"], "run": r["run"], "at": r["at"], "passed": 0,
                                                 "total": 0})
            if r["run"] != cur["run"]:
                if r["at"] < cur["at"]:
                    continue
                cur.update(run=r["run"], at=r["at"], passed=0, total=0)
            cur["passed"] += bool(r["passed"])
            cur["total"] += 1
        for h in latest.values():
            h["state"] = "ok" if h["passed"] == h["total"] else ("warn" if h["passed"] >= h["total"] - 1 else "bad")
            health.append(h)

    order = {"running": 0, "waiting": 1, "idle": 2, "done": 3}
    # running first, then waiting, idle, done; most recently active first within each group
    seat_list = sorted(seats.values(), key=lambda s: (order.get(s["status"], 9), _age_s(s.get("last_activity") or "")))
    return {
        "seats": seat_list, "needs_you": needs, "health": sorted(health, key=lambda h: h["model"]),
        "spend_today": round(spend_today, 6), "synced_at": app.last_auto_sync, "agent": app.agent,
        "running_jobs": sum(j.status == "running" for j in app.jobs.jobs.values()),
    }


TOOL_MAIN_ARG = ("path", "command", "pattern", "query", "summary", "approved")


def _tool_text(d: dict[str, Any]) -> str:
    args = d.get("args") or {}
    main = next((args[k] for k in TOOL_MAIN_ARG if k in args), "")
    if d.get("tool") == "submit_review":
        main = "approved" if args.get("approved") else "rejected"
    text = f"{d.get('tool')} {main}".strip()
    return text + (" (failed)" if d.get("error") else "")


def activity(app, limit: int = 120) -> list[dict[str, Any]]:
    """Newest-first feed across harness runs (agent steps) and the hub journal.

    Each step carries who did it: the task, the role and the model, tracked from
    the task_start / attempt events that precede it.
    """
    items: list[dict[str, Any]] = []
    cfg = app.cfg()
    if cfg and cfg.lab_dir:
        for path in app.lab(cfg).projects():
            ctx = {"task": "", "role": "", "model": ""}
            for seq, d in enumerate(_read_jsonl(path / ".harness" / "events.jsonl", tail=400)):
                ev = d.get("event")
                if ev == "task_start":
                    ctx = {"task": d.get("task", ""), "role": d.get("role", ""), "model": ""}
                elif ev == "attempt":
                    ctx["model"] = d.get("model", "")
                elif ev == "planning":
                    ctx = {"task": "", "role": "orchestrator", "model": d.get("model", "")}
                elif ev == "model_turn" and d.get("model"):
                    ctx["model"] = d["model"]
                if ev not in FEED_EVENTS:
                    continue
                if ev == "steer":
                    text = f"owner instruction: {d.get('text', '')}"
                elif ev == "goal":
                    text = f"new goal: {d.get('goal', '')[:160]}"
                elif ev == "tool_call":
                    text = _tool_text(d)
                else:
                    text = harness_event_line(ev, d)
                if not text:
                    continue
                role = "reviewer" if ev == "review" or d.get("tool") == "submit_review" else ctx["role"]
                who = " ".join(x for x in (ctx["task"], role) if x)
                if ctx["model"] and ev in ("tool_call", "attempt", "planning", "review"):
                    who += f" ({ctx['model'].split('/', 1)[-1]})"
                items.append({"at": d.get("at", ""), "seq": seq, "project": path.name, "kind": ev, "who": who.strip(),
                              "task": ctx["task"], "role": role, "model": ctx["model"],
                              "text": text.strip().lstrip("▶✓✗-> ").split("\n")[0][:220]})
    if app.hub:
        with app.hub_lock:
            for agent in app.hub.config.agents:
                for e in app.hub.journal.entries(agent, agent, limit=15):
                    items.append({"at": e["created_at"], "seq": e.get("ts", 0), "project": agent,
                                  "kind": f"journal:{e['kind']}",
                                  "text": f"{e['kind']}: {e['text']}"[:220]})
    if getattr(app, "desktop", None):
        from ..backup import feed_items

        items += feed_items(app.desktop["paths"].home)[:3]
    # newest first; "seq" keeps steps logged within the same second in their real order
    items.sort(key=lambda i: (i["at"], i["seq"]), reverse=True)
    return items[:limit]


class AutoSync:
    """Background hub sync while the app is open, so other sessions' changes show up."""

    def __init__(self, app, every_s: float = 60.0):
        import threading

        self.app, self.every = app, every_s
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True, name="hub-auto-sync")

    def start(self) -> "AutoSync":
        self.thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.every):
            self.tick()

    def tick(self) -> None:
        self.daily_backup()
        self.start_cheap_runs()
        if not self.app.hub:
            return
        try:
            with self.app.hub_lock:
                self.app.hub.store.sync(force=True)
            self.app.last_auto_sync = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            self.app.auto_sync_error = ""
            cfg = self.app.cfg()
            if cfg and cfg.lab_dir and (cfg.remote or {}).get("enabled", True):
                from ..remote import process

                process(cfg, self.app.hub, background=True, log=lambda s: None)  # commands from the phone
        except Exception as e:  # offline etc.: keep the app working on its local copy
            self.app.auto_sync_error = str(e)[:300]
        time.sleep(0)

    def start_cheap_runs(self) -> None:
        """Projects approved to start when it's cheaper (off-peak) are started once their time comes."""
        try:
            cfg = self.app.cfg()
            if not cfg or not cfg.lab_dir:
                return
            from ..harness.orchestrator import due_cheap_runs

            for root in due_cheap_runs(cfg):
                self.app.start_run_job(cfg, root, why="its off-peak time came")
        except Exception as e:  # never let the tick fail
            self.app.auto_sync_error = f"couldn't start a waiting run: {e}"[:300]

    def daily_backup(self) -> None:
        """Once a day while the desktop app is open, never while a project job runs."""
        if not getattr(self.app, "desktop", None):
            return
        from ..backup import find_sources, run_daily

        app = self.app
        busy = any(j.status == "running" and j.kind in ("run", "plan", "backup")
                   for j in app.jobs.jobs.values())
        msg = run_daily(app.desktop["paths"].home, busy=busy,
                        sources=lambda: find_sources(app.harness_config_path, app.hub_config_path,
                                                     app.desktop["paths"].home))
        if msg:
            app.backup_message = msg
