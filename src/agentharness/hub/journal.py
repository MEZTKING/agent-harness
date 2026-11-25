"""Project journal: what was done, what needs doing, plans, decisions, and
"where was I" briefings, shared across every session and machine that uses
the hub.

On-disk layout (inside the hub store, next to cards/inbox):

    journal/<agent>/<entry-id>.json   one file per entry (conflict-free in git)
    status/<agent>.md                 human-readable status, rewritten on every
                                      journal write (read it on GitHub)

Entry kinds:
    done      finished work
    todo      something that needs doing      (open -> done / dropped)
    plan      a future idea or milestone       (open -> done / dropped)
    decision  a choice made, and why
    note      anything worth remembering
    session   end-of-session summary + next steps ("where I was")

Agents write only their own journal; reading follows the read_card policy.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ..core.models import utcnow
from ..core.store import TextFile

if TYPE_CHECKING:
    from .service import Hub

KINDS = ("done", "todo", "plan", "decision", "note", "session")
TRACKED = ("todo", "plan")  # kinds with an open/done/dropped lifecycle
PRIORITIES = ("high", "normal", "low")


@dataclass
class Entry:
    id: str
    agent: str
    kind: str
    text: str
    created_at: str
    status: str = ""  # open | done | dropped (todo/plan only)
    priority: str = "normal"
    next: list[str] = field(default_factory=list)  # session: next steps
    details: str = ""
    source: str = ""  # who/what wrote it: a session label, "harness", "cli"...
    tags: list[str] = field(default_factory=list)
    closed_at: str = ""
    closed_note: str = ""
    ts: float = 0.0  # precise creation time, orders entries made within the same second

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Entry":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _ago(ts: str) -> str:
    try:
        then = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return "?"
    secs = int((datetime.now(timezone.utc) - then).total_seconds())
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= size:
            return f"{secs // size}{unit} ago"
    return "just now"


class JournalError(ValueError):
    pass


class Journal:
    def __init__(self, hub: "Hub"):
        self.hub = hub
        self.store = hub.store

    # -- reading ----------------------------------------------------------------
    def _entries(self, agent: str) -> list[Entry]:
        out = [Entry.from_dict(d) for _, d in self._iter(agent)]
        out.sort(key=lambda e: (e.created_at, e.ts))
        return out

    def _iter(self, agent: str):
        from ..core.store import iter_json

        return iter_json(self.store, f"journal/{agent}")

    def entries(self, actor: str, agent: str | None = None, kinds: list[str] | None = None,
                status: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        agent = agent or actor
        self.hub._require_agent(actor)
        self.hub._require_agent(agent)
        self.hub.config.policy.check(actor, agent, "read_card")
        self.store.sync()
        out = [e for e in self._entries(agent)
               if (not kinds or e.kind in kinds) and (status is None or e.status == status)]
        if limit:
            out = out[-limit:]
        return [asdict(e) for e in out]

    # -- writing ------------------------------------------------------------------
    def _writes_with_status(self, agent: str, changed: list[Entry]) -> dict[str, Any]:
        entries = {e.id: e for e in self._entries(agent)}
        for e in changed:
            entries[e.id] = e
        writes: dict[str, Any] = {f"journal/{agent}/{e.id}.json": asdict(e) for e in changed}
        writes[f"status/{agent}.md"] = TextFile(self.render_status(agent, list(entries.values())))
        return writes

    def add(self, actor: str, kind: str, text: str, priority: str = "normal", details: str = "",
            next_steps: list[str] | None = None, source: str = "", tags: list[str] | None = None) -> dict[str, Any]:
        self.hub._require_agent(actor)
        if kind not in KINDS:
            raise JournalError(f"kind must be one of {KINDS}")
        if priority not in PRIORITIES:
            raise JournalError(f"priority must be one of {PRIORITIES}")
        text = (text or "").strip()
        if not text:
            raise JournalError("text is empty")
        self.store.sync()
        e = Entry(
            id=secrets.token_hex(3), agent=actor, kind=kind, text=text, created_at=utcnow(), ts=time.time(),
            status="open" if kind in TRACKED else "", priority=priority, details=details,
            next=[n.strip() for n in next_steps or [] if n and n.strip()], source=source, tags=list(tags or []),
        )
        self.store.write_json(self._writes_with_status(actor, [e]), f"journal({actor}) {kind}: {text[:80]}")
        return asdict(e)

    def close(self, actor: str, entry_id: str, dropped: bool = False, note: str = "") -> dict[str, Any]:
        """Mark one of the actor's todos/plans done (or dropped)."""
        self.hub._require_agent(actor)
        if not entry_id.isalnum():
            raise JournalError("invalid entry id")
        self.store.sync()
        data = self.store.read_json(f"journal/{actor}/{entry_id}.json")
        if not data:
            raise JournalError(f"no entry {entry_id!r} in {actor}'s journal")
        e = Entry.from_dict(data)
        if e.kind not in TRACKED:
            raise JournalError(f"{entry_id} is a {e.kind}; only todo/plan entries can be closed")
        e.status = "dropped" if dropped else "done"
        e.closed_at = utcnow()
        e.closed_note = note
        changed = [e]
        if not dropped and e.kind == "todo":  # finishing a todo also counts as done work
            changed.append(Entry(id=secrets.token_hex(3), agent=actor, kind="done", text=e.text,
                                 created_at=utcnow(), ts=time.time(), details=note, source=f"closed {e.id}"))
        self.store.write_json(self._writes_with_status(actor, changed),
                              f"journal({actor}) {e.status} {e.id}: {e.text[:60]}")
        return asdict(e)

    def session_end(self, actor: str, summary: str, next_steps: list[str] | None = None,
                    source: str = "") -> dict[str, Any]:
        return self.add(actor, "session", summary, next_steps=next_steps, source=source)

    # -- briefings --------------------------------------------------------------------
    def brief(self, actor: str, agent: str) -> dict[str, Any]:
        """Everything needed to pick up where this project left off."""
        es = self._entries(agent)
        sessions = [e for e in es if e.kind == "session"]
        rank = {"high": 0, "normal": 1, "low": 2}
        open_todos = sorted((e for e in es if e.kind == "todo" and e.status == "open"),
                            key=lambda e: (rank.get(e.priority, 1), e.created_at))
        spec = self.hub.config.agents[agent]
        return {
            "agent": agent,
            "repo": spec.repo,
            "description": spec.description,
            "last_activity": es[-1].created_at if es else "",
            "last_ts": es[-1].ts if es else 0.0,
            "last_session": asdict(sessions[-1]) if sessions else None,
            "open_todos": [asdict(e) for e in open_todos],
            "open_plans": [asdict(e) for e in es if e.kind == "plan" and e.status == "open"],
            "recent_done": [asdict(e) for e in es if e.kind == "done"][-5:],
            "recent_decisions": [asdict(e) for e in es if e.kind == "decision"][-3:],
        }

    def where(self, actor: str, agent: str | None = None) -> list[dict[str, Any]]:
        """Briefings for one project, or every project the actor may read (most recent first)."""
        self.hub._require_agent(actor)
        self.store.sync()
        if agent:
            self.hub._require_agent(agent)
            self.hub.config.policy.check(actor, agent, "read_card")
            b = self.brief(actor, agent)
            return [b] if b["last_activity"] else []
        out = [self.brief(actor, a) for a in self.hub.config.agents if self.hub._allowed(actor, a, "read_card")]
        out = [b for b in out if b["last_activity"]]
        out.sort(key=lambda b: (b["last_activity"], b["last_ts"]), reverse=True)
        return out

    # -- rendering ----------------------------------------------------------------------
    @staticmethod
    def format_brief(b: dict[str, Any], compact: bool = False) -> str:
        head = f"== {b['agent']}" + (f" ({b['repo']})" if b["repo"] else "")
        lines = [f"{head}  - last activity {_ago(b['last_activity'])}"]
        s = b["last_session"]
        if s:
            lines.append(f"Last session ({_ago(s['created_at'])}): {s['text']}")
            for n in s["next"]:
                lines.append(f"   next: {n}")
        todos = b["open_todos"]
        if todos:
            lines.append(f"Open todos ({len(todos)}):")
            for e in todos[:5 if compact else None]:
                pri = "!" if e["priority"] == "high" else " "
                lines.append(f"  {pri}[{e['id']}] {e['text']}")
            if compact and len(todos) > 5:
                lines.append(f"   ... {len(todos) - 5} more")
        if b["open_plans"] and not compact:
            lines.append("Plans:")
            lines += [f"   [{e['id']}] {e['text']}" for e in b["open_plans"]]
        elif b["open_plans"]:
            lines.append(f"Plans: {len(b['open_plans'])} open")
        if b["recent_done"]:
            lines.append("Recently done:")
            lines += [f"   - {e['text']} ({_ago(e['created_at'])})" for e in b["recent_done"][-(3 if compact else 5):]]
        if b["recent_decisions"] and not compact:
            lines.append("Decisions:")
            lines += [f"   - {e['text']}" for e in b["recent_decisions"]]
        return "\n".join(lines)

    def render_status(self, agent: str, entries: list[Entry]) -> str:
        entries = sorted(entries, key=lambda e: (e.created_at, e.ts))
        spec = self.hub.config.agents[agent]
        rank = {"high": 0, "normal": 1, "low": 2}
        md = [f"# {agent}" + (f" ({spec.repo})" if spec.repo else ""), ""]
        if spec.description:
            md += [spec.description, ""]
        md += [f"_Updated {utcnow()} - generated by agent-hub, don't edit by hand._", ""]
        sessions = [e for e in entries if e.kind == "session"]
        if sessions:
            s = sessions[-1]
            md += ["## Where we left off", "", f"**{s.created_at}**: {s.text}", ""]
            md += [f"- [ ] {n}" for n in s.next] + ([""] if s.next else [])
        todos = sorted((e for e in entries if e.kind == "todo" and e.status == "open"),
                       key=lambda e: (rank.get(e.priority, 1), e.created_at))
        md += ["## To do", ""] + ([f"- [ ] {'**(high)** ' if e.priority == 'high' else ''}{e.text} `{e.id}`"
                                    for e in todos] or ["_Nothing open._"]) + [""]
        plans = [e for e in entries if e.kind == "plan" and e.status == "open"]
        if plans:
            md += ["## Future plans", ""] + [f"- {e.text} `{e.id}`" for e in plans] + [""]
        decisions = [e for e in entries if e.kind == "decision"]
        if decisions:
            md += ["## Decisions", ""] + [f"- {e.created_at[:10]}: {e.text}" for e in decisions[-15:]] + [""]
        done = [e for e in entries if e.kind == "done"]
        if done:
            md += ["## Done (latest first)", ""] + [f"- {e.created_at[:10]}: {e.text}" for e in reversed(done[-30:])] + [""]
        if len(sessions) > 1:
            md += ["## Session history", ""] + [f"- {e.created_at[:16]}: {e.text}" for e in reversed(sessions[-10:-1])] + [""]
        return "\n".join(md)
