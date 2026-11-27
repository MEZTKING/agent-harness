"""The learning allowance: the only money unattended learning may spend (wave 7, Helper 3 fills this in).

``improve.allowance_usd_per_week`` in harness.yaml or the app's settings; 0 (the default) means off, so
nothing paid happens by itself. The signatures below are frozen.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..harness.agent import Budget, BudgetExceeded


class AllowanceUsed(BudgetExceeded):
    """This week's learning allowance is spent (or it is off)."""

    pause = "learning"


def allowance(cfg: Any) -> float:
    """The weekly allowance in dollars; 0 means off (the default)."""
    raw = (getattr(cfg, "improve", None) or {}).get("allowance_usd_per_week") or 0
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 0.0


def left(cfg: Any, lab: Any, now: datetime | None = None) -> float:
    """What is left of this week's allowance. Stub: the whole allowance."""
    return allowance(cfg)


def budget(cfg: Any, lab: Any, what: str, most: float | None = None) -> Budget:
    """A Budget for one unattended learning step, at most ``most`` and never past what is left.
    Raises AllowanceUsed when nothing is left (always, while the allowance is 0)."""
    room = left(cfg, lab)
    if most is not None:
        room = min(room, float(most))
    if room <= 0:
        raise AllowanceUsed("Learning by itself is off, or this week's allowance is used.")
    return Budget(limit_usd=room)


def spent_today(lab: Any) -> float:
    """What learning spent today on this machine. Stub: 0."""
    return 0.0
