"""Working, resting, waiting or gone quiet: what a project is doing, at a glance.

``state(root, now)`` reads the project's status, the time of its newest event and the commands
``livecmd`` lists as running:

* ``working`` – a run is on and something happened lately (or a command is running: a long build or test
  is work, as the breaker counts it);
* ``waiting`` – it waits for the owner (a plan to approve, a stuck task, money, a command to allow);
* ``resting`` – nothing to do (done, paused, not started);
* ``quiet``  – a run is on but nothing has happened for longer than the breaker's no-progress limit plus
  ``MARGIN_MINUTES``.

A quiet run raises one Needs-you card ("Still going? Wait, or Stop it") through the asks
(``quiet_ask`` / ``apply_quiet``, wired into ``asks.py`` by the coordinator). It never stops a run by
itself. "Wait" settles the card for this quiet spell only (``.harness/quiet.json``); "Stop it" stops the
project's running commands and asks the run to pause before its next task (``boardstage.request_stop``).
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

MARGIN_MINUTES = 5.0
QUIET_FILE = "quiet.json"
WORDS = {"working": "Working", "resting": "Resting", "waiting": "Waiting for you", "quiet": "Gone quiet"}
OWNER_PAUSES = {"money", "money_nothing_done", "money_day", "budget", "allowance", "agreed"}


def _ts(text: str | None) -> float | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def last_event_at(root: str | Path) -> str:
    """The ``at`` of the newest event in ``.harness/events.jsonl`` ("" when there is none)."""
    p = Path(root) / ".harness" / "events.jsonl"
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 65536))
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    for line in reversed(tail.splitlines()):
        try:
            at = json.loads(line).get("at")
        except (ValueError, AttributeError):
            continue
        if at:
            return str(at)
    return ""


def _limit_minutes(cfg: Any = None) -> float:
    from .breaker import BreakerSettings

    try:
        mins = BreakerSettings.from_config(cfg).no_progress_minutes if cfg is not None else BreakerSettings().no_progress_minutes
    except Exception:  # noqa: BLE001 - a bad setting: the default
        mins = BreakerSettings().no_progress_minutes
    return (mins or BreakerSettings().no_progress_minutes) + MARGIN_MINUTES


def _minutes(seconds: float) -> str:
    m = max(1, int(seconds // 60))
    if m >= 120:
        return f"{m // 60} hours"
    return f"{m} minute{'s' if m != 1 else ''}"


def state(root: str | Path, now: float | None = None, cfg: Any = None, busy: bool | None = None,
          waiting: bool | None = None) -> dict[str, Any]:
    """{state, word, line, last_at, quiet_for}. ``busy``: whether this computer has a job on the project
    (None: not known); ``waiting``: whether a card waits for the owner (None: worked out from the status)."""
    from . import livecmd

    root = Path(root)
    now = time.time() if now is None else now
    try:
        meta = json.loads((root / ".harness" / "project.json").read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        meta = {}
    status = str(meta.get("status") or "")
    last_at = last_event_at(root)
    last = _ts(last_at)
    since = max(0.0, now - last) if last is not None else None
    commands = [c for c in livecmd.running(root) if float(c.get("until") or 0) > now]

    def out(s: str, line: str) -> dict[str, Any]:
        return {"state": s, "word": WORDS[s], "line": line, "last_at": last_at,
                "quiet_for": round(since) if since is not None else None}

    if waiting is None:
        waiting = status in ("awaiting_approval", "blocked", "paused_budget") or (
            status == "paused" and str(meta.get("pause") or "") in OWNER_PAUSES)
        if not waiting:
            from ..asks import command_asks

            try:
                waiting = bool(command_asks(root))
            except Exception:  # noqa: BLE001 - can't tell: not waiting
                waiting = False
    run_on = busy is True or commands or status in ("running",) or (status == "planning" and busy is True)
    if commands:
        return out("working", "Running a command")
    if waiting and not (status == "running" and busy):
        return out("waiting", "Waiting for your answer")
    if not run_on:
        return out("resting", "Finished" if status == "done" else "Nothing to do now")
    if since is not None and since > _limit_minutes(cfg) * 60:
        line = f"Nothing has happened for {_minutes(since)}"
        if busy is False:
            line += ": it may have stopped"
        return out("quiet", line)
    return out("working", "Working on it")


# -- the one card for a quiet run ----------------------------------------------------------------------
def _waited(root: Path) -> str:
    try:
        return str(json.loads((root / ".harness" / QUIET_FILE).read_text(encoding="utf-8")).get("waited") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def quiet_ask(orch, meta: dict[str, Any] | None = None, now: float | None = None, busy: bool | None = None) -> dict[str, Any] | None:
    """The card for a quiet run, or None. One per project; "Wait" settles it until the next event, so a
    new quiet spell asks again."""
    from ..asks import _ask

    root = Path(orch.project.root)
    st = state(root, now, cfg=getattr(orch, "cfg", None), busy=busy)
    if st["state"] != "quiet" or (st["last_at"] and _waited(root) == st["last_at"]):
        return None
    opts = [{"id": "wait", "label": "Wait", "description": "Leave it going. You're asked again if it stays quiet."},
            {"id": "stop", "label": "Stop it", "description": "Stop what it's running and pause before the next task. "
                                                              "Carry on starts it again."}]
    return _ask("quiet", "quiet", "Quiet", f"{root.name} has gone quiet. {st['line']}. Still going?", opts,
                recommended="wait", other_hint="Or tell it what to do", source={"last_at": st["last_at"]})


def apply_quiet(orch, ask, picked, other):
    from . import boardstage, livecmd

    root = Path(orch.project.root)
    if other:
        orch.steer(other)
    if (picked[0] if picked else "wait") == "stop":
        stopped = livecmd.stop_strays(root)
        boardstage.request_stop(root)
        meta = orch.project.meta()
        if meta.get("status") == "running":  # if its process is gone, this is what lets Carry on start it
            meta.update(status="paused", pause="owner_stop")
            orch.project.save_meta(meta)
        return {"reply": "Stopping it" + (f": {stopped} running command{'s' if stopped != 1 else ''} ended" if stopped else "")
                         + ". It pauses before its next task; Carry on starts it again.", "then": None}
    (root / ".harness").mkdir(parents=True, exist_ok=True)
    (root / ".harness" / QUIET_FILE).write_text(json.dumps({"waited": ask["source"].get("last_at", "")}) + "\n",
                                                encoding="utf-8")
    return {"reply": "Leaving it going. You're asked again if it stays quiet.", "then": None}
