"""One dial for how much extra checking a plan gets: lean, balanced or maximum (wave 6).

Every tandem stage (the router, the panel of checkers, rival builders, the planning council, named agents)
asks the dial before it does anything extra, and tells it what it spent. At "lean" a stage does nothing, so
a project planned before 1.2.0 (its meta has no ``checking``) runs exactly as before.

This file is a stub: its signatures are fixed, and every level answers like "lean" until the dial is filled
in (one builder, one checker, one planner, no exploring, no limit on the allowance).

| Level    | Ordinary task                                  | Risky task               | Hard task                | The plan                    |
|----------|------------------------------------------------|--------------------------|--------------------------|-----------------------------|
| lean     | 1 builder, 1 checker                           | the same                 | the same                 | 1 planner, today's critique |
| balanced | 1 builder, 1 checker; may try a newer model    | 2 checkers               | 2 builders, 2 checkers   | 1 planner, today's critique |
| maximum  | 2 builders, 3 checkers                         | 2 builders, 3 checkers   | 3 builders, 3 checkers   | 3 planners and a chair      |

The keys each stage writes into a task's attempt (``task.attempts[i]``), read by the dial and the app:

- ``routed``: ``{"from": <the model the role would have used>, "why": <plain words>}`` (the router);
- ``reviews``: ``[{"model", "maker", "approved", "feedback", "breaks", "counted"}]``, one per checker (the panel);
- ``disagreed``: bool, the checkers did not agree (the panel);
- ``same_maker``: bool, a checker was made by the builder's maker (the panel; warned about, never refused);
- ``rival``: ``"r1"``, which rival attempt this was (rivals);
- ``rivals``: ``[{"id", "model", "maker", "tests", "picked", "why", "branch", "cost_usd"}]`` (rivals);
- ``agent``: the named agent's id who did the work (agents).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.models import utcnow

LEVELS = ("lean", "balanced", "maximum")
DEFAULT_LEVEL = "balanced"
LEDGER = Path(".harness") / "tandem.jsonl"


def _known(value: Any) -> str:
    v = str(value or "").strip().lower()
    return v if v in LEVELS else ""


def level(orch: Any) -> str:
    """The plan's level (``meta["checking"]``); "lean" when absent (plans made before 1.2.0)."""
    try:
        return _known(orch.project.meta().get("checking")) or "lean"
    except Exception:  # noqa: BLE001 - no project yet: the safe answer
        return "lean"


def level_for_new_plan(orch: Any) -> str:
    """The level a new plan starts at: the project's ``checking`` setting, else ``tandem.default`` in
    harness.yaml, else "balanced"."""
    try:
        chosen = _known(orch.project_settings().values.get("checking"))
    except Exception:  # noqa: BLE001 - settings with a mistake never stop a plan here
        chosen = ""
    if chosen:
        return chosen
    try:
        from .config import section

        chosen = _known(section(orch.cfg, "tandem").get("default"))
    except Exception:  # noqa: BLE001
        chosen = ""
    return chosen or DEFAULT_LEVEL


def for_task(orch: Any, task: Any) -> dict[str, Any]:
    """How many builders (``rivals``) and checkers (``panel``) this task gets, whether the router may try a
    newer model (``explore``), and why (``""``, ``"hard"``, ``"risky"`` or ``"maximum"``). Stub: lean."""
    return {"rivals": 1, "panel": 1, "explore": False, "why": ""}


def for_plan(orch: Any) -> dict[str, Any]:
    """How many rival planners this plan gets (1: one planner and today's critique). Stub: lean."""
    return {"planners": 1}


def allow(orch: Any, what: str, usd: float | None) -> bool:
    """Is there room left in the extra-checking allowance for ``what`` (a stage's name) to spend ``usd``?
    Stub: always."""
    return True


def spent(orch: Any, what: str, usd: float, task_id: str = "") -> None:
    """Note money a stage spent on extra checking: one line in ``.harness/tandem.jsonl``."""
    try:
        p = Path(orch.project.root) / LEDGER
        p.parent.mkdir(parents=True, exist_ok=True)
        row = {"at": utcnow(), "what": what, "usd": round(float(usd or 0.0), 6), "task": task_id}
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except (OSError, TypeError, ValueError):  # bookkeeping: never stops a run
        pass
