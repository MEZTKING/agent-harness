"""The watch: after a change is applied, the next tasks are compared with before, and a clear drop undoes
it (wave 7, Helper 3 fills this in). The signatures below are frozen.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def start(lab: Any, proposal: Any, version: int) -> None:
    """Start watching a change that was just applied. Stub: nothing."""
    return None


def check(cfg: Any, lab: Any, now: datetime | None = None) -> list[dict[str, Any]]:
    """Look at the changes being watched; returns the ones undone just now. Stub: []."""
    return []
