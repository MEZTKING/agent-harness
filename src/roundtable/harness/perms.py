"""What each job may do on a project (wave 8, stub: p1-perms fills it).

Four presets, one per job: **Ask every time** (``ask_all``), **Careful** (``careful``, the default and today's
"risky"), **Free** (``free``, today's "off") and **Read only** (``read_only``). ``guard`` is a ``Toolbox`` guard
(``harness/tools.py`` ``Toolbox.guards``): asked before any tool runs, a sentence back is the refusal.

Until p1-perms fills it, ``preset_for`` only names today's gate mode and ``guard`` allows everything, so a run
is exactly as before. The signatures are frozen.
"""

from pathlib import Path
from typing import Any, Callable

from . import gate as _gate

PRESETS = ("ask_all", "careful", "free", "read_only")
_FROM_MODE = {"all": "ask_all", "risky": "careful", "off": "free"}


def preset_for(root, cfg, role: str) -> str:
    """The preset that applies to ``role`` on the project at ``root``. Stub: today's gate mode, by its new name."""
    try:
        return _FROM_MODE.get(_gate.mode_for(Path(root), cfg), "careful")
    except Exception:
        return "careful"


def guard(root, cfg, role: str, gate) -> Callable:
    """A ``Toolbox`` guard for ``role``: ``(tool name, arguments) -> refusal sentence or None``. Stub: allows
    everything."""

    def allow(name: str, args: dict[str, Any]) -> None:
        return None

    return allow
