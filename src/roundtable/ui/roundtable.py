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

from .hall import PLAN_READY as PLAN_READY_RE
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
    meta = json.loads((hdir / "project.json").read_text(encoding="utf-8"))
    tasks = json.loads((hdir / "tasks.json").read_text(encoding="utf-8") or "[]")
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
            detail = "making the plan…"
    elif st == "awaiting_approval":
        from ..harness.plandoc import summary_line

        doc = None
        try:
            doc = json.loads((hdir / "plan.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        line = summary_line(doc) if doc else "plan ready"
        status, detail, actions = "waiting", f"{line}: look at it, then approve it to start", ["approve"]
    elif st == "blocked" and failed:
        t = failed[0]
        status, detail, actions = "waiting", f"{t['id']} {t['title']} didn't work: try again or skip it", ["retry", "skip"]
    elif st == "paused_budget":
        status, detail, actions = "waiting", "stopped at the spending limit: raise it to go on", ["budget"]
    elif st == "done":
        status, detail = "done", "all tasks done"
    elif st in ("paused", "running", "planning"):
        status, detail, actions = "idle", "stopped part-way: resume when ready", ["resume"]
    return {
        "id": path.name, "path": str(path), "kind": "run", "status": status, "detail": detail, "actions": actions,
        "state": _run_words(status, st, tasks, running_task, failed),
        "shot": _seat_shot(path),
        "failed_task": failed[0]["id"] if failed else None,
        "progress": {"done": done, "total": len(tasks)}, "goal": (meta.get("goals") or [""])[-1],
        "spent_usd": meta.get("spent_usd", 0), "last_activity": last_at,
    }


def _run_words(status: str, st: str | None, tasks: list[dict[str, Any]], running: dict[str, Any] | None,
               failed: list[dict[str, Any]]) -> str:
    """A run's state as the owner reads it on the seat."""
    if status == "running":
        if running:
            n = next((i for i, t in enumerate(tasks, 1) if t is running), 0)
            return f"Building {running['id']} of {len(tasks)}" if running["id"].startswith("T") and n else \
                f"Building task {n} of {len(tasks)}"
        return "Planning…"
    if st == "awaiting_approval":
        return "Waiting for you: the plan is ready"
    if st == "blocked" and failed:
        return f"Stopped: {failed[0]['id']} needs you"
    if st == "paused_budget":
        return "Stopped at the spending limit"
    if status == "done":
        return "Finished"
    if st in ("paused", "running", "planning"):
        return "Paused part-way"
    return "Idle"


def _seat_shot(path: Path) -> dict[str, str] | None:
    """The newest desktop picture of the project's app, for the seat's thumbnail."""
    from urllib.parse import urlencode

    from ..harness.showit import latest

    rec = latest(path)
    if not rec or "desktop" not in (rec.get("pictures") or {}):
        return None
    d = rec.get("dir") or rec.get("task", "")
    pic = "desktop.jpg" if (path / ".harness" / "shots" / d / "desktop.jpg").is_file() else "desktop.png"
    return {"url": "/raw/shot?" + urlencode({"path": str(path), "task": d, "name": pic}),
            "task": rec.get("task", ""), "at": rec.get("at", "")}


ASK_STATES = ("awaiting_approval", "blocked", "paused", "paused_budget")


def _asks(cfg, path: Path) -> list[dict[str, Any]]:
    """The project's open cards (asks.py), only when it is waiting for the owner; never breaks the table."""
    try:
        meta = json.loads((path / ".harness" / "project.json").read_text(encoding="utf-8"))
        if meta.get("status") not in ASK_STATES:
            return []
        from ..asks import open_asks
        from ..harness.orchestrator import Orchestrator

        return open_asks(Orchestrator(cfg, path))
    except Exception:
        return []


ASK_RANK = {"money": 1, "failed": 1}  # questions and decisions first, then money and stopped runs
NEED_KINDS = {"ask": 0, "plan": 0, "run": 1, "todo": 2, "messages": 3}


def _need_rank(n: dict[str, Any]) -> int:
    if n.get("ask"):
        return ASK_RANK.get(n["ask"].get("kind"), 0)
    if n["kind"] == "run":
        return 0 if "approve" in (n.get("actions") or []) else 1
    return NEED_KINDS.get(n["kind"], 4)


def _runner_ids(app, cfg, plans: dict[str, dict[str, Any]]) -> set[str]:
    """The hub agents Roundtable's projects report through (``harness``): plumbing, not projects."""
    agents = set(app.hub.config.agents) if app.hub else set()
    ids = {p["agent"] for p in plans.values() if p["agent"] and p["folder"] != p["agent"]}
    hub_agent = ((cfg.hub or {}) if cfg else {}).get("agent")
    if hub_agent:
        ids.add(hub_agent)
    return ids & agents


def _hub_status(seat: dict[str, Any]) -> None:
    """A hub project's state in words, from its journal."""
    if seat.get("owner_high"):
        n = seat["owner_high"]
        seat.update(status="waiting", state=f"Waiting for you: {n} thing{'s' if n > 1 else ''} to do")
    elif seat.get("last_activity"):
        seat.update(status="idle", state="Idle")
    else:
        seat.update(status="idle", state="No news yet")


def build(app) -> dict[str, Any]:
    """Every project as a seat, what waits for the owner (ranked like the phone) and the table's figures.

    See hall.py for who sits at the table. Each seat has ``name`` (what the owner reads), ``state`` (its
    state in words), ``where`` (here: run on this computer; elsewhere: another computer or a session) and
    ``hub_agent``/``hub_name`` when commands go through the hub."""
    from . import hall

    seats: dict[str, dict[str, Any]] = {}
    needs: list[dict[str, Any]] = []
    cfg = app.cfg()
    notes: dict[str, Any] | None = None
    plans: dict[str, dict[str, Any]] = {}

    # hub projects (journal)
    if app.hub:
        with app.hub_lock:
            app.hub.store.sync()
            app.hub.refresh_config()  # projects added to the hub since the app started
            agents = dict(app.hub.config.agents)
            briefs = {a: app.hub.journal.brief(a, a) for a in agents}
            unread = {a: len(app.hub.inbox(a, unread_only=True, limit=200)) for a in agents}
            plans = hall.hub_plans(app.hub)
        runners = _runner_ids(app, cfg, plans)
        lab_names = set()
        if cfg and cfg.lab_dir:
            try:
                lab_names = {p.name for p in app.lab(cfg).projects()}
            except Exception:
                lab_names = set()
        folders = {p["folder"] for p in plans.values() if p["agent"] in runners} | lab_names
        split: dict[str, dict[str, Any]] = {}
        for r in sorted(runners):
            per, rest = hall.split_brief(briefs[r], folders - set(agents))
            for who, b in per.items():
                split[who] = b
            briefs[r] = rest
        for a, b in briefs.items():
            spec = agents[a]
            if spec.role == "machine" and a not in runners:  # a PC or a phone: in the machines, not a project
                continue
            if a == app.agent and not spec.repo:  # the owner's own notes: beside the table, not at it
                notes = {"id": a, "name": hall.NOTES_NAME, "open_todos": len(b["open_todos"]),
                         "unread": unread.get(a, 0), "last_activity": b["last_activity"], "brief": b}
                continue
            if a in runners:  # plumbing: its projects sit down on their own below
                if b["open_todos"] or b["open_plans"]:
                    notes = notes or {"id": app.agent, "name": hall.NOTES_NAME, "open_todos": 0, "unread": 0,
                                      "last_activity": "", "brief": None}
                    notes["runner"] = {"id": a, "name": "Roundtable's own list", "brief": b}
                continue
            seats[a] = _hub_seat(a, hall.friendly(a, spec), b, unread.get(a, 0))
        for who, b in split.items():  # Roundtable-built projects named in the shared journal
            seats.setdefault(who, _hub_seat(who, hall.friendly(who), b, 0, kind="remote"))
            if seats[who]["kind"] == "remote":
                seats[who]["brief"] = b
        # plans in the hub: Roundtable-built projects wherever they run
        for p in plans.values():
            sid = p["folder"]
            seat = seats.get(sid)
            if seat is None:
                if p["agent"] not in runners and p["agent"] != sid:
                    continue
                seat = seats[sid] = _hub_seat(sid, hall.friendly(sid), _blank_brief(p["agent"] or sid), 0,
                                              kind="remote")
            seat.update(hub_name=p["name"], hub_agent=p["agent"] or sid, goal=p["goal"] or seat.get("goal", ""))
            if sid in lab_names:
                continue  # this computer runs it: its live state comes from the lab below
            status, words = hall.plan_state(p["state"])
            if status == "running" and _age_s(p["at"]) > 2 * 3600:
                status, words = "idle", "Building elsewhere: no news for a while"
            elif status == "running":
                words = "Building on another computer"
            seat.update(status=status, state=words, detail=p["summary"], shot=p["shot"],
                        last_activity=max(seat.get("last_activity") or "", p["at"] or ""), where="elsewhere")
            if p["asks"]:
                a0 = p["asks"][0]
                needs.append({"kind": "ask", "project": sid, "name": seat["name"], "text": a0.get("question", ""),
                              "actions": [], "at": p["at"], "ask": a0, "asks": len(p["asks"]), "via": "hub",
                              "hub_agent": seat["hub_agent"], "hub_name": p["name"]})
            elif status == "waiting":
                needs.append({"kind": "plan", "project": sid, "name": seat["name"], "via": "hub",
                              "text": "The plan is ready: look at it, then approve it to start building.",
                              "actions": ["open_plan", "approve"], "at": p["at"],
                              "hub_agent": seat["hub_agent"], "hub_name": p["name"]})
        # the owner's to-dos (high priority, meant for them), and their letters
        for sid, seat in seats.items():
            b = seat.get("brief") or {}
            for e in b.get("open_todos") or []:
                if e.get("priority") != "high" or not hall.for_owner(e):
                    continue
                if hall.PLAN_READY.search(e.get("text", "")) and (seat.get("hub_name") or sid in lab_names):
                    continue  # the plan's own card (or Approve) stands for it
                needs.append({"kind": "todo", "project": sid, "name": seat["name"], "text": e["text"], "id": e["id"],
                              "agent": b.get("agent") or sid, "actions": ["done"], "at": e["created_at"]})
        if notes and notes["unread"]:
            needs.append({"kind": "messages", "project": notes["id"], "name": hall.NOTES_NAME,
                          "text": f"{notes['unread']} unread letter{'s' if notes['unread'] > 1 else ''}",
                          "actions": ["read"], "at": ""})
        elif app.agent in unread and unread[app.agent] and app.agent in seats:
            needs.append({"kind": "messages", "project": app.agent, "name": seats[app.agent]["name"],
                          "text": f"{unread[app.agent]} unread message(s)", "actions": ["read"], "at": ""})

    # harness runs on this computer: merged into the seat with the same name, else a seat of their own
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
                from .hall import friendly

                seat = seats[run["id"]] = {**run, "name": friendly(run["id"]), "open_todos": 0, "high": 0,
                                           "owner_high": 0, "unread": 0, "repo": "", "description": ""}
            seat["where"] = "here"
            asks = _asks(cfg, path) if run["status"] != "running" else []
            # a plan-ready to-do is answered by the plan's card: drop it from Needs you
            if run["status"] == "waiting" or asks:
                needs[:] = [n for n in needs if not (n["project"] == run["id"] and n["kind"] in ("ask", "plan"))]
                needs.append({"kind": "run", "project": run["id"], "name": seat["name"], "path": run["path"],
                              "text": run["detail"], "actions": run["actions"], "task": run["failed_task"],
                              "at": run["last_activity"], "via": "here",
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

    from .hall import for_owner

    for b in [s.get("brief") for s in seats.values()] + [(notes or {}).get("brief"),
                                                         ((notes or {}).get("runner") or {}).get("brief")]:
        for e in (b or {}).get("open_todos") or []:
            e["for_owner"] = for_owner(e)  # False: an instruction for a programmer, kept out of Needs you
            e["plan_ready"] = bool(PLAN_READY_RE.search(e.get("text", "")))
    pilot = _autopilot(app)
    for s in seats.values():
        s["autopilot"] = bool(pilot.get("on") and s.get("path") and s["id"] not in pilot.get("never", []))
        s.setdefault("where", "elsewhere")
        s["waiting_for_you"] = sum(1 for n in needs if n["project"] == s["id"])
    for i, n in enumerate(needs):
        n["rank"] = _need_rank(n)
        n["order"] = i
    # questions and decisions first, then money and stopped runs, then to-dos, then letters
    needs.sort(key=lambda n: (n["rank"], n["order"]))
    order = {"running": 0, "waiting": 1, "idle": 2, "done": 3}
    # running first, then waiting, idle, done; most recently active first within each group
    seat_list = sorted(seats.values(), key=lambda s: (order.get(s["status"], 9), _age_s(s.get("last_activity") or "")))
    machines, claims = _machines(app)
    from ..sync import claim_fresh, this_machine

    me = this_machine()
    for s in seat_list:  # which machine has it, and which builds it now (one at a time)
        mine = [c for c in claims.values() if (s.get("hub_name") and c.get("hub_name") == s["hub_name"])
                or c.get("folder") == s["id"]]
        c = next((c for c in mine if claim_fresh(c)), None)
        if c:
            s["building_on"] = {"machine": c.get("machine"), "name": c.get("machine_name"), "since": c.get("since")}
        held = c or (mine[0] if mine else None)
        if s.get("where") == "here":
            s["machine"], s["machine_name"] = me["id"], me["name"]
        elif held:
            s["machine"], s["machine_name"] = held.get("machine"), held.get("machine_name")
        elif s.get("hub_name"):
            m = _published_by(app, s["hub_name"])
            if m:
                s["machine"], s["machine_name"] = m
    return {
        "machines": machines,
        "seats": seat_list, "needs_you": needs, "health": sorted(health, key=lambda h: h["model"]),
        "notes": notes,
        # agent: this machine's seat (sync.py); hub_agent: who this app is in the hub's letters ("me")
        "spend_today": round(spend_today, 6), "synced_at": app.last_auto_sync, "agent": me["id"],
        "hub_agent": app.agent, "machine": me,
        "running_jobs": sum(j.status == "running" for j in app.jobs.jobs.values()),
        "autopilot": pilot,
    }


def _published_by(app, hub_name: str) -> tuple[str, str] | None:
    """The machine that published a plan (plans/<name>.asks.json), for a project no machine has claimed yet."""
    from .hall import hub_root

    root = hub_root(app.hub) if app.hub else None
    try:
        data = json.loads((root / "plans" / f"{hub_name}.asks.json").read_text(encoding="utf-8")) if root else {}
    except (OSError, ValueError):
        return None
    return (data["machine"], data.get("machine_name") or data["machine"]) if data.get("machine") else None


def _machines(app) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Every machine seat and every claim; never breaks the table."""
    if not app.hub:
        return [], {}
    try:
        from ..sync import machines, read_claims

        with app.hub_lock:
            return machines(app.hub), read_claims(app.hub)
    except Exception:
        return [], {}


def _blank_brief(agent: str) -> dict[str, Any]:
    return {"agent": agent, "repo": "", "description": "", "last_activity": "", "last_ts": 0.0, "last_session": None,
            "open_todos": [], "open_plans": [], "recent_done": [], "recent_decisions": []}


def _hub_seat(sid: str, name: str, b: dict[str, Any], unread: int, kind: str = "hub") -> dict[str, Any]:
    from .hall import for_owner

    high = [e for e in b["open_todos"] if e["priority"] == "high"]
    seat = {
        "id": sid, "name": name, "kind": kind, "status": "idle", "state": "", "detail": "", "actions": [],
        "repo": b.get("repo", ""), "description": b.get("description", ""), "last_activity": b["last_activity"],
        "open_todos": len(b["open_todos"]), "high": len(high),
        "owner_high": sum(1 for e in high if for_owner(e)), "unread": unread,
        "last_session": b.get("last_session"), "brief": b,
    }
    _hub_status(seat)
    return seat


def _autopilot(app) -> dict[str, Any]:
    """Autopilot's switch for the header and the seats; never breaks the table."""
    try:
        from ..autopilot import status

        return status(app._backup_home())
    except Exception:
        return {"on": False, "never": []}


JOURNAL_WORDS = {"todo": "to do", "done": "done", "plan": "plan", "decision": "decided", "note": "note",
                 "session": "session"}
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
        from . import hall

        with app.hub_lock:
            plans = hall.hub_plans(app.hub)
            runners = _runner_ids(app, cfg, plans)
            folders = {p["folder"] for p in plans.values()}
            if cfg and cfg.lab_dir:
                folders |= {p.name for p in app.lab(cfg).projects()}
            for agent, spec in app.hub.config.agents.items():
                for e in app.hub.journal.entries(agent, agent, limit=15):
                    project, text = agent, e["text"]
                    if agent in runners:  # "mse: plan ready" in the shared journal is the project mse's
                        who, rest = hall.split_prefix(text, folders)
                        if who:
                            project, text = who, rest
                    items.append({"at": e["created_at"], "seq": e.get("ts", 0), "project": project,
                                  "kind": f"journal:{e['kind']}", "who": JOURNAL_WORDS.get(e["kind"], ""),
                                  "text": text[:220]})
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
        self.sync_hub()
        self.autopilot()

    def autopilot(self) -> None:
        """After the other jobs: answer what waits with the recommendations while autopilot is on."""
        try:
            self.app.autopilot_tick()
        except Exception as e:  # never let the tick fail
            self.app.auto_sync_error = f"autopilot: {e}"[:300]

    def sync_hub(self) -> None:
        if not self.app.hub:
            return
        try:
            with self.app.hub_lock:
                self.app.hub.store.sync(force=True)
                self.app.hub.refresh_config()  # projects another computer added to the hub's hub.yaml
            self.app.last_auto_sync = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            self.app.auto_sync_error = ""
            cfg = self.app.cfg()
            listening = bool(cfg and cfg.lab_dir and (cfg.remote or {}).get("enabled", True))
            from ..sync import tick as sync_tick

            done = sync_tick(self.app, listening=listening)  # this machine's seat, heartbeat, shared settings
            if done.get("error"):
                self.app.auto_sync_error = done["error"]
            if listening:
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
