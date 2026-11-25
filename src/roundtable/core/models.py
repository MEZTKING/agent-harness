"""Data models shared by the hub and (later) the harness.

Plain dataclasses serialised to JSON, so the on-disk format stays
human-readable and diff-friendly in git.
"""

from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import Any

MAX_RECENT_CHANGES = 20


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    """Sortable, collision-resistant id: UTC timestamp + random suffix."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{ts}-{secrets.token_hex(3)}"


def _from_dict(cls, data: dict[str, Any]):
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ProjectCard:
    """What one agent / repo is, what it is doing, and what it exposes."""

    agent: str
    repo: str = ""
    summary: str = ""
    goal: str = ""
    status: str = ""
    # Public contracts other repos rely on: APIs, schemas, events, CLI flags...
    interfaces: str = ""
    # Agent ids whose work this agent depends on. Updates to those cards
    # are pushed to this agent's inbox automatically.
    depends_on: list[str] = field(default_factory=list)
    notes: str = ""
    recent_changes: list[dict[str, str]] = field(default_factory=list)
    recent_commits: list[str] = field(default_factory=list)
    updated_at: str = ""
    updated_by: str = ""

    EDITABLE = ("repo", "summary", "goal", "status", "interfaces", "depends_on", "notes")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectCard":
        return _from_dict(cls, data)

    def add_change(self, note: str, by: str) -> None:
        self.recent_changes.insert(0, {"at": utcnow(), "by": by, "note": note})
        del self.recent_changes[MAX_RECENT_CHANGES:]


MESSAGE_KINDS = ("ask", "notify", "request", "reply")


@dataclass
class Message:
    id: str
    sender: str
    recipient: str
    kind: str
    subject: str
    body: str
    created_at: str
    in_reply_to: str | None = None
    thread_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        return _from_dict(cls, data)
