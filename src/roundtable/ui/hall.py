"""Who sits at the Hall's table, and what the owner reads about them.

One seat per project the owner works on:

* a hub project with a repository (hub.yaml ``agents``), shown by its friendly name (``title:`` in hub.yaml,
  else its id made readable; Roundtable's own repository is "Roundtable Hold (this app)");
* a project Roundtable builds (``roundtable new``), on this computer (the lab) or on another one. Those
  report to the hub through one shared agent (``harness``, harness.yaml ``hub.agent``) unless the hub has a
  project of the same name: their plan is ``plans/<agent>--<folder>.md`` with ``.asks.json`` next to it, and
  their journal entries start "<folder>: ". Here they get a seat of their own, named after the folder.

Not seats: the owner's own notes (the app's identity, ``me``: "My notes", a small entry beside the table)
and the shared agent itself (its entries go to the projects they name). Old journals are read as they are:
nothing is moved or rewritten.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

OWN_REPOS = ("agent-harness", "roundtable-hold")
THIS_APP = "Roundtable Hold (this app)"
NOTES_NAME = "My notes"
SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,120}$")

# A to-do written as an instruction to a programmer (a command, a file, a setting in code) is for the
# sessions working on the project, not the owner: it stays in the project's list, out of Needs you.
TECHNICAL = re.compile(
    r"`|\b(pip|npm|pnpm|gradle|gradlew|git|clone|commit|rebase|cherry-pick|venv|cli|sdk|mcp|ci)\b|~/|\$[A-Z_]{3,}"
    r"|\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b|\.(py|json|ya?ml|toml|kt|ts|js|sh|ps1|cmd|md)\b|\b\w+\(\)|-->|->|=>|"
    r"\bsettings\s*>\s*environments\b",
    re.I,
)
PLAN_READY = re.compile(r"\bplan is ready\b", re.I)


def friendly(agent_id: str, spec: Any = None) -> str:
    """The name the owner reads for a project."""
    title = getattr(spec, "title", "") if spec is not None else ""
    if title:
        return title
    repo = (getattr(spec, "repo", "") or "").lower().rstrip("/")
    if agent_id in OWN_REPOS or repo.split("/")[-1] in OWN_REPOS:
        return THIS_APP
    words = re.split(r"[-_.\s]+", agent_id.strip())
    return " ".join(w[:1].upper() + w[1:] for w in words if w) or agent_id


def for_owner(entry: dict[str, Any]) -> bool:
    """A to-do meant for the owner (the Hall's Needs you) rather than for a programmer."""
    tags = {str(t).lower() for t in entry.get("tags") or []}
    if "owner" in tags:
        return True
    if tags & {"dev", "tech", "code"}:
        return False
    if entry.get("source") == "harness":  # Roundtable writes the owner's to-dos in plain words
        return True
    return not TECHNICAL.search(entry.get("text") or "")


def split_prefix(text: str, names: set[str]) -> tuple[str | None, str]:
    """"mse: The plan is ready" -> ("mse", "The plan is ready") when ``mse`` is a known project."""
    head, sep, rest = (text or "").partition(": ")
    if sep and head in names:
        return head, rest
    return None, text


# -- the hub's plans (projects Roundtable builds, wherever they run) --------------------------------
STATUS_LINE = re.compile(r"^_Plan status: (?P<state>[^·_]+?)\s*·\s*(?P<summary>.*?)\s*·\s*updated (?P<at>\S+)")
GOAL_LINE = re.compile(r"^# Plan v\d+:\s*(?P<goal>.*)$", re.M)


def hub_root(hub) -> Path | None:
    root = getattr(getattr(hub, "store", None), "root", None)
    return Path(root) if root else None


def hub_plans(hub) -> dict[str, dict[str, Any]]:
    """Every plan in the hub: {hub name: {name, agent, folder, state, summary, at, goal, asks, shot}}.

    ``harness--mse`` is folder ``mse`` reported by the agent ``harness``; ``mse`` alone is a hub project's own."""
    root = hub_root(hub)
    plans_dir = root / "plans" if root else None
    if not plans_dir or not plans_dir.is_dir():
        return {}
    agents = set(hub.config.agents)
    out: dict[str, dict[str, Any]] = {}
    for md in sorted(plans_dir.glob("*.md")):
        name = md.stem
        if not SAFE_NAME.match(name):
            continue
        agent, sep, folder = name.partition("--")
        if not sep:
            agent, folder = (name if name in agents else ""), name
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        m = STATUS_LINE.match(text.strip().splitlines()[0] if text.strip() else "")
        g = GOAL_LINE.search(text)
        out[name] = {
            "name": name, "agent": agent, "folder": folder,
            "state": (m.group("state").strip() if m else ""), "summary": (m.group("summary") if m else ""),
            "at": (m.group("at") if m else ""), "goal": (g.group("goal").strip() if g else ""),
            "asks": read_hub_asks(root, name), "shot": _hub_shot(root, name),
        }
    return out


def read_hub_asks(root: Path, name: str) -> list[dict[str, Any]]:
    try:
        data = json.loads((root / "plans" / f"{name}.asks.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    asks = data.get("asks") if isinstance(data, dict) else None
    return [a for a in asks or [] if isinstance(a, dict) and a.get("id") and a.get("answer") is None]


def _hub_shot(root: Path, name: str) -> dict[str, str] | None:
    from urllib.parse import urlencode

    try:
        rec = json.loads((root / "plans" / "shots" / name / "latest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pic = (rec.get("pictures") or {}).get("desktop")
    if not pic:
        return None
    return {"url": "/raw/hubshot?" + urlencode({"name": name, "file": pic}), "task": rec.get("task", ""),
            "at": rec.get("at", "")}


def hub_shot_file(hub, name: str, file: str) -> Path:
    """A picture a project published to the hub (plans/shots/<name>/<file>), only from that folder."""
    root = hub_root(hub)
    if not root or not SAFE_NAME.match(name or "") or not re.match(r"^[\w.-]+\.(png|jpe?g|webp)$", file or ""):
        raise ValueError("no such picture")
    p = (root / "plans" / "shots" / name / file).resolve()
    if (root / "plans" / "shots").resolve() not in p.parents or not p.is_file():
        raise ValueError("no such picture")
    return p


def plan_state(state: str) -> tuple[str, str]:
    """The plan's published state as (seat status, words)."""
    s = (state or "").lower()
    if "waiting" in s:
        return "waiting", "Waiting for you: the plan is ready"
    if "building" in s:
        return "running", "Building"
    if s.startswith("done"):
        return "done", "Finished"
    return "idle", "Planned"


# -- journals: split the shared agent's entries by the project they name -------------------------------
def split_brief(brief: dict[str, Any], names: set[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """The shared agent's brief as one brief per project it names, and what's left for nobody in particular."""
    per: dict[str, dict[str, Any]] = {}
    rest = {k: (list(v) if isinstance(v, list) else v) for k, v in brief.items()}
    for key in ("open_todos", "open_plans", "recent_done", "recent_decisions"):
        rest[key] = []
        for e in brief.get(key) or []:
            who, text = split_prefix(e.get("text", ""), names)
            if who is None:
                rest[key].append(e)
                continue
            b = per.setdefault(who, _empty_brief(brief, who))
            b[key].append({**e, "text": text})
            if (e.get("created_at") or "") > (b["last_activity"] or ""):
                b["last_activity"] = e["created_at"]
    s = brief.get("last_session")
    if s:
        who, text = split_prefix(s.get("text", ""), names)
        if who:
            per.setdefault(who, _empty_brief(brief, who))["last_session"] = {**s, "text": text}
            rest["last_session"] = None
    return per, rest


def _empty_brief(brief: dict[str, Any], who: str) -> dict[str, Any]:
    return {"agent": brief["agent"], "repo": "", "description": "", "last_activity": "", "last_ts": 0.0,
            "last_session": None, "open_todos": [], "open_plans": [], "recent_done": [], "recent_decisions": [],
            "for": who}
