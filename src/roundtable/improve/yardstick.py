"""The yardstick: small made-up tasks a change is tried on (wave 7, Helper 2 fills this in).

The signatures below are frozen.
"""

from __future__ import annotations

from typing import Any, Callable


def available(cfg: Any, role: str) -> int:
    """How many yardstick tasks fit this job. Stub: 0."""
    return 0


def run(cfg: Any, lab: Any, proposal: Any, budget: Any, runs: int = 2,
        on_event: Callable[[str, dict[str, Any]], None] | None = None) -> dict[str, Any] | None:
    """Try ``proposal`` against the current state on the yardstick. None: no yardstick for it.

    {"n", "current": {"passed", "cost_usd"}, "candidate": {"passed", "cost_usd"}, "veto": "", "verdict",
    "passed"}. Stub: None.
    """
    return None
