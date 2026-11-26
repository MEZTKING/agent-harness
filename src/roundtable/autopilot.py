"""Autopilot: Roundtable answers the owner's cards by itself while they're away.

The owner (26 November 2026): "Add an autopilot button so you'll automatically make decisions while
I'm off my screen." The spirit is the coordinator's own rule: reversible choices are made freely and
written down; anything important waits for the owner.

One switch for every project, kept in the app's settings (``<app home>/config/app.json``, key
``autopilot``)::

    {on, until (ISO time or null), spend_cap_usd (2.00), started_at, spent_usd, never: [project names]}

``tick`` (called by the desktop app's auto-sync, ``roundtable remote --watch`` and ``roundtable autopilot
--watch``) goes through every project's open cards (asks.open_asks) and answers each with its
recommended option through asks.answer_ask, the same door the owner's taps use. Guard rails:

* plan choices, questions, the look, the setting and ideas: the recommendation (none: left open);
* approving a plan: only when its estimate fits what's left of autopilot's limit and the project's own
  limit; "start at half price" is preferred when it starts before ``until``;
* a failed task: tried again once with the same models (never the stronger model, never "accept" or
  "skip");
* money pauses and empty accounts: left for the owner (no limit is ever raised);
* never an option with ``confirm`` ("Are you sure?"), never anything that deletes, publishes,
  releases or merges;
* it turns itself off when ``until`` passes or the limit is reached.

Every decision goes in the project's journal (a decision) and in the autopilot log the owner reads
when back: ``<app home>/autopilot-log.md`` (newest first) and ``autopilot-log.jsonl`` (for the app).
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

DEFAULT_CAP = 2.00
MAX_REVISES = 3  # plan updates autopilot may ask for per project while it is on (no endless loops)
BALANCE_EVERY_S = 300
LOG_KEEP = 300
FORBIDDEN = re.compile(r"delete|publish|release|merge", re.I)
BUSY_STATES = ("running", "planning", "waiting_cheap")
HUB_FILE = "plans/autopilot.json"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


# -- where it lives --------------------------------------------------------------------------------------
def app_home(home: str | Path | None = None) -> Path:
    if home:
        return Path(home)
    from .desktop import app_home as default_home

    return default_home()


def _settings_file(home: Path) -> Path:
    return home / "config" / "app.json"


def _read_settings(home: Path) -> dict[str, Any]:
    try:
        return json.loads(_settings_file(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load(home: str | Path | None = None) -> dict[str, Any]:
    """Autopilot's state, with defaults filled in."""
    raw = _read_settings(app_home(home)).get("autopilot") or {}
    state = {"on": False, "until": None, "spend_cap_usd": DEFAULT_CAP, "started_at": None, "spent_usd": 0.0,
             "never": [], "left": {}, "balance_start": None, "real_usd": None, "real_checked": 0.0, "stopped": ""}
    state.update({k: v for k, v in raw.items() if k in state})
    return state


def save(state: dict[str, Any], home: str | Path | None = None) -> None:
    home = app_home(home)
    data = _read_settings(home)
    data["autopilot"] = state
    _settings_file(home).parent.mkdir(parents=True, exist_ok=True)
    _settings_file(home).write_text(json.dumps(data, indent=2), encoding="utf-8")


TICK_FIELDS = ("left", "spent_usd", "real_usd", "real_checked")


def _keep(state: dict[str, Any], home: Path) -> bool:
    """Save what a tick learnt without undoing a switch the owner made meanwhile. False when it's off now."""
    fresh = load(home)
    fresh.update({k: state[k] for k in TICK_FIELDS})
    save(fresh, home)
    return bool(fresh["on"]) and fresh.get("started_at") == state.get("started_at")


# -- until -----------------------------------------------------------------------------------------------
def parse_until(text: str | None, now: datetime | None = None) -> str | None:
    """"" / "back" / "off": no end time; "1h", "90m"; "tonight" (until 8am); "08:00" (the next one, local
    time); or an ISO time. Returns an ISO time in UTC, or None."""
    text = str(text or "").strip().lower()
    now = (now or utcnow()).astimezone()  # the computer's own time zone
    if text in ("", "back", "off", "none", "never", "when i'm back"):
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(h|hours?|m|min|minutes?)", text)
    if m:
        n = float(m.group(1))
        return _iso(now + (timedelta(hours=n) if m.group(2).startswith("h") else timedelta(minutes=n)))
    if text == "tonight":
        text = "08:00"
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if m.group(3) == "pm" and hour < 12:
            hour += 12
        if m.group(3) == "am" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            raise ValueError("That time doesn't exist. Try 08:00 or 8am.")
        at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return _iso(at if at > now else at + timedelta(days=1))
    at = _parse_iso(text.upper())
    if not at:
        raise ValueError("Say when to stop as a time (08:00), a length (1h) or 'tonight'.")
    return _iso(at)


def clock(iso: str | None) -> str:
    """'8am', '7:30pm' in the computer's time zone."""
    t = _parse_iso(iso)
    if not t:
        return ""
    t = t.astimezone()
    h = t.hour % 12 or 12
    return f"{h}{':%02d' % t.minute if t.minute else ''}{'am' if t.hour < 12 else 'pm'}"


def label(state: dict[str, Any]) -> str:
    """'until 8am · $0.40 of $2.00' (or 'Off')."""
    if not state.get("on"):
        return "Off"
    when = f"until {clock(state['until'])}" if state.get("until") else "until you're back"
    return f"{when} · ${float(state.get('spent_usd') or 0):.2f} of ${float(state['spend_cap_usd']):.2f}"


# -- the log -----------------------------------------------------------------------------------------------
def entries(home: str | Path | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """The newest entries of the autopilot log first."""
    path = app_home(home) / "autopilot-log.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in reversed(lines):
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
        if len(out) >= limit:
            break
    return out


def _record(home: Path, entry: dict[str, Any]) -> dict[str, Any]:
    entry = {"at": _iso(utcnow()), **entry}
    home.mkdir(parents=True, exist_ok=True)
    with open(home / "autopilot-log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    _write_markdown(home)
    return entry


def _write_markdown(home: Path) -> None:
    lines = ["# What autopilot did", "",
             "Newest first. Every choice autopilot made for you while you were away, and what it left for you.",
             "Answers on a plan can still be changed until the plan is approved.", ""]
    for e in entries(home, LOG_KEEP):
        where = f"**{e['project']}**: " if e.get("project") else ""
        lines.append(f"- {e['at'].replace('T', ' ').rstrip('Z')} UTC · {where}{e['text']}")
    (home / "autopilot-log.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# -- on and off --------------------------------------------------------------------------------------------
def turn_on(until: str | None = None, cap: float | None = None, home: str | Path | None = None, cfg=None,
            now: datetime | None = None) -> dict[str, Any]:
    """Switch autopilot on. ``until``: as parse_until takes it; ``cap``: dollars it may spend."""
    home = app_home(home)
    cap = DEFAULT_CAP if cap in (None, "") else float(cap)
    if not 0 < cap <= 1000:
        raise ValueError("The spend limit must be between $0.01 and $1,000.")
    state = load(home)
    state.update(on=True, until=parse_until(until, now), spend_cap_usd=round(cap, 2),
                 started_at=_iso(now or utcnow()), spent_usd=0.0, left={}, stopped="",
                 balance_start=_balances(cfg), real_usd=None, real_checked=time.time())
    save(state, home)
    text = f"Autopilot on, {label(state)}."
    _record(home, {"kind": "on", "text": text})
    _journal_switch(cfg, text)
    _publish(cfg, home)
    return status(home)


def turn_off(why: str = "", home: str | Path | None = None, cfg=None) -> dict[str, Any]:
    home = app_home(home)
    state = load(home)
    if state["on"]:
        state.update(on=False, stopped=why)
        save(state, home)
        text = f"Autopilot off: {why}" if why else "Autopilot off."
        _record(home, {"kind": "off", "text": text})
        _journal_switch(cfg, text)
        _publish(cfg, home)
    return status(home)


def set_never(project: str, never: bool = True, home: str | Path | None = None) -> dict[str, Any]:
    """Keep one project away from autopilot (or let it back)."""
    home = app_home(home)
    state = load(home)
    names = [n for n in state["never"] if n != project] + ([project] if never else [])
    state["never"] = sorted(names)
    save(state, home)
    return status(home)


def status(home: str | Path | None = None) -> dict[str, Any]:
    state = load(home)
    return {"on": state["on"], "until": state["until"], "until_label": clock(state["until"]),
            "spend_cap_usd": state["spend_cap_usd"], "spent_usd": round(float(state["spent_usd"] or 0), 4),
            "started_at": state["started_at"], "never": state["never"], "label": label(state),
            "stopped": state["stopped"]}


def _journal_switch(cfg, text: str) -> None:
    """On and off go in the journal of the harness's hub project (when there's a hub)."""
    try:
        hub = _hub(cfg)
        agent = (cfg.hub or {}).get("agent") if cfg else None
        if hub and agent in hub.config.agents:
            hub.journal.add(agent, "decision", text, source="autopilot")
    except Exception:  # the hub is optional; never fail a switch over it
        pass


def _hub(cfg):
    if not cfg or not getattr(cfg, "hub", None):
        return None
    from .core.config import load_config as load_hub_config
    from .hub.service import Hub

    return Hub(load_hub_config(cfg.hub.get("config")))


def _publish(cfg, home: Path, hub=None) -> None:
    """The state and the newest log entries in the hub (plans/autopilot.json), for the phone in Hub mode."""
    try:
        hub = hub or _hub(cfg)
        if not hub:
            return
        from .core.store import TextFile

        data = {**status(home), "inbox": (cfg.hub or {}).get("agent"), "log": entries(home, 30)}
        hub.store.write_json({HUB_FILE: TextFile(json.dumps(data, indent=1, ensure_ascii=False) + "\n")},
                             f"autopilot: {label(load(home))}")
    except Exception:
        pass


# -- money -------------------------------------------------------------------------------------------------
def _balances(cfg) -> dict[str, Any] | None:
    """The providers' real balances (where they report one), to measure real money spent."""
    if not cfg or os.environ.get("ROUNDTABLE_NO_BALANCE"):
        return None
    try:
        from .providers.balance import balances

        return balances(cfg) or None
    except Exception:
        return None


def spent(cfg, state: dict[str, Any]) -> float:
    """Money spent since autopilot was switched on: the real balances' drop where providers report it,
    else Roundtable's own count (the larger of the two)."""
    from .remote import project_dirs

    since = state.get("started_at") or ""
    counted = 0.0
    for root in project_dirs(cfg):
        try:
            rows = (root / ".harness" / "spend.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for ln in rows:
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            if str(row.get("at", "")) >= since:
                counted += float(row.get("cost_usd") or 0)
    return max(counted, _real_spent(cfg, state) or 0.0)


def _real_spent(cfg, state: dict[str, Any]) -> float | None:
    start = state.get("balance_start")
    if not start:
        return None
    if time.time() - float(state.get("real_checked") or 0) >= BALANCE_EVERY_S:
        now = _balances(cfg) or {}
        real = sum(start[p]["amount"] - b["amount"] for p, b in now.items() if p in start)
        state.update(real_usd=round(real, 4) if now else state.get("real_usd"), real_checked=time.time())
    return state.get("real_usd")


# -- deciding ----------------------------------------------------------------------------------------------
def _option(ask: dict[str, Any], oid: str | None) -> dict[str, Any] | None:
    return next((o for o in ask["options"] if o["id"] == oid), None)


def _safe(ask: dict[str, Any], oid: str | None) -> bool:
    """An option autopilot may pick: it exists, needs no "Are you sure?", and deletes or publishes nothing."""
    o = _option(ask, oid)
    return bool(o) and not o.get("confirm") and not FORBIDDEN.search(f"{o['id']} {o['label']}")


def _money(x: float | None) -> str:
    return f"${(x or 0):.2f}"


def decide(orch, ask: dict[str, Any], state: dict[str, Any], now: datetime | None = None) -> tuple[list[str] | None, str]:
    """What autopilot answers to one card: (option ids, why) or (None, why it's left for the owner)."""
    kind = ask["kind"]
    if kind in ("decision", "question", "look", "profile", "idea"):
        rec = ask.get("recommended")
        if not rec:
            return None, "there's no recommended answer"
        if not _safe(ask, rec):
            return None, "the recommended answer needs your say-so"
        return [rec], "it's the recommended answer"
    if kind == "approve":
        return _decide_approve(orch, ask, state, now or utcnow())
    if kind == "failed":
        return _decide_failed(orch, ask)
    if kind == "money":
        return None, "money pauses always wait for you: autopilot never raises a limit or spends more"
    return None, "autopilot doesn't answer this kind of question"


def _decide_approve(orch, ask, state, now) -> tuple[list[str] | None, str]:
    ids = [o["id"] for o in ask["options"]]
    if "revise" in ids:
        if _revises(orch, state) >= MAX_REVISES:
            return None, f"the plan was already updated {MAX_REVISES} times on autopilot"
        return ["revise"], "the answers it chose have to go into the plan before it can be approved"
    est = (orch.project.plan_doc() or {}).get("estimate") or {}
    cost = est.get("cost_usd")
    if cost is None or est.get("unpriced"):
        return None, "the plan's cost isn't known, so it waits for you"
    left = float(state["spend_cap_usd"]) - float(state.get("spent_usd") or 0)
    if cost > left:
        return None, f"its estimate ({_money(cost)}) is more than what's left of autopilot's limit ({_money(left)})"
    project_left = orch.budget.limit_usd - orch.budget.spent_usd
    if cost > project_left:
        return None, f"its estimate ({_money(cost)}) is more than this project's own limit allows ({_money(project_left)})"
    if "approve_cheap" in ids and _safe(ask, "approve_cheap"):
        at = orch.cheap_start_at()
        until = _parse_iso(state.get("until"))
        if at and (not until or at <= until):
            return ["approve_cheap"], f"its estimate ({_money(cost)}) fits autopilot's limit, and it's half price later"
    if not _safe(ask, "approve"):
        return None, "approving needs your say-so"
    return ["approve"], f"its estimate ({_money(cost)}) fits what's left of autopilot's limit ({_money(left)})"


def _decide_failed(orch, ask) -> tuple[list[str] | None, str]:
    task = ask["source"]["task"]
    if task in (orch.project.meta().get("autopilot_retried") or []):
        return None, "autopilot already tried it once more; what next is up to you"
    if not _safe(ask, "retry"):
        return None, "trying again needs your say-so"
    return ["retry"], "a failed task is tried once more with the same models"


def _revises(orch, state: dict[str, Any]) -> int:
    """Plan updates autopilot asked for on this project since it was switched on."""
    note = orch.project.meta().get("autopilot") or {}
    return note.get("revises", 0) if note.get("session") == state.get("started_at") else 0


def _before_answer(orch, ask: dict[str, Any], chosen: list[str], state: dict[str, Any]) -> None:
    """Remember what limits autopilot: one retry per task, a few plan updates per session."""
    meta = orch.project.meta()
    if ask["kind"] == "failed":
        meta["autopilot_retried"] = sorted(set(meta.get("autopilot_retried") or []) | {ask["source"]["task"]})
    if chosen == ["revise"]:
        note = meta.get("autopilot") or {}
        if note.get("session") != state.get("started_at"):
            note = {"session": state.get("started_at"), "revises": 0}
        note["revises"] = note.get("revises", 0) + 1
        meta["autopilot"] = note
    orch.project.save_meta(meta)


def _labels(ask: dict[str, Any], chosen: list[str]) -> str:
    return ", ".join(_option(ask, c)["label"] for c in chosen)


# -- the tick ----------------------------------------------------------------------------------------------
Starter = Callable[[Any, Path, dict[str, Any]], Any]


def finish_now(cfg, root: Path, result: dict[str, Any]) -> str:
    """Do the long step an answer started, here and now (the command line)."""
    from .asks import finish
    from .harness.orchestrator import Orchestrator

    return finish(Orchestrator(cfg, root), result)


def tick(cfg, hub=None, home: str | Path | None = None, start: Starter | None = None,
         busy: Callable[[Path], bool] | None = None, now: datetime | None = None) -> list[dict[str, Any]]:
    """One pass over every project's cards. Returns the log entries it wrote."""
    home = app_home(home)
    state = load(home)
    if not state["on"] or not cfg or not cfg.lab_dir:
        return []
    now = now or utcnow()
    out: list[dict[str, Any]] = []
    if _should_stop(cfg, state, home, now):
        return out
    from .remote import project_dirs

    for root in project_dirs(cfg):
        if root.name in state["never"] or (busy and busy(root)):
            continue
        out += _project(cfg, root, state, home, start or finish_now, now)
        if not _keep(state, home) or _should_stop(cfg, state, home, now):
            break
    if out:
        _publish(cfg, home, hub)
    return out


def _should_stop(cfg, state: dict[str, Any], home: Path, now: datetime) -> bool:
    """Turn off when the time's up or the limit is reached. True when it turned off."""
    state["spent_usd"] = round(spent(cfg, state), 6)
    if not _keep(state, home):
        return True
    until = _parse_iso(state.get("until"))
    if until and now >= until:
        turn_off(f"it was on until {clock(state['until'])}, as you asked.", home, cfg)
        return True
    if state["spent_usd"] >= float(state["spend_cap_usd"]):
        turn_off(f"it reached its spend limit ({_money(state['spent_usd'])} of {_money(state['spend_cap_usd'])}). "
                 "Anything still running carries on within its project's own limits.", home, cfg)
        return True
    return False


def _project(cfg, root: Path, state, home: Path, start: Starter, now) -> list[dict[str, Any]]:
    """Answer one project's cards, one at a time (each answer can change the others)."""
    from .asks import answer_ask, open_asks
    from .harness.orchestrator import Orchestrator, Project

    if Project(root).meta().get("status") in BUSY_STATES:
        return []
    orch = Orchestrator(cfg, root)
    out: list[dict[str, Any]] = []
    for _ in range(30):  # a guard: each pass answers one card
        asks = open_asks(orch)
        answered = False
        for ask in asks:
            key = f"{root.name}:{ask['id']}"
            if state["left"].get(key) == ask["stamp"]:
                continue
            chosen, why = decide(orch, ask, state, now)
            if not chosen:
                state["left"][key] = ask["stamp"]
                out.append(_record(home, {"kind": "left", "project": root.name, "path": str(root), "ask": ask["id"],
                                          "text": f"Left for you: “{ask['question']}” – {why}."}))
                continue
            _before_answer(orch, ask, chosen, state)
            r = answer_ask(orch, ask["id"], chosen, stamp=ask["stamp"])
            out.append(_decided(orch, root, home, ask, chosen, why, r))
            if r.get("then"):
                start(cfg, root, r)
                return out  # the project is busy now; the next tick carries on
            answered = True
            break
        if not answered:
            break
    return out


def _decided(orch, root: Path, home: Path, ask, chosen, why, result) -> dict[str, Any]:
    text = f"Autopilot chose “{_labels(ask, chosen)}” for “{ask['question']}” because {why}."
    if chosen == [ask.get("recommended")] and "recommended" not in why:
        text += " It's the recommended answer."
    orch._journal("decision", text)
    orch.emit("autopilot", {"ask": ask["id"], "chosen": chosen})
    return _record(home, {"kind": "chose", "project": root.name, "path": str(root), "ask": ask["id"],
                          "chosen": chosen, "text": f"{text} {result['reply']}"})
