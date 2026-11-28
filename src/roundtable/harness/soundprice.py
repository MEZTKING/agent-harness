"""Sound money: the cap a project may spend on sound, decided in one place (wave 9).

A stub with its frozen signatures: Helper w9-sound fills it. The design (plans, wave 9):

* ``sound.max_per_project_usd`` (default :data:`CAP_DEFAULT`); a project's own setting may lower it, and only
  the owner's tap raises it, never above the figure in the app's settings;
* :func:`reserve` before every call, for the quoted price, under one lock, as an append-only line in
  ``.harness/sound-spend.jsonl``; :func:`settle` with the real charge after; :func:`release` when the call
  failed. Money reserved and not yet settled counts as spent, so two sounds at once can't slip past the cap;
* :func:`per_sound` prices one sound for the estimate without reaching the network (None: "unpriced").

Learning may never change any of it (improve/charter.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

CAP_DEFAULT = 2.0
SPEND_FILE = Path(".harness") / "sound-spend.jsonl"


class SoundCapReached(Exception):
    """A sound would take the project past its sound cap: nothing was asked of the service."""


def cap(cfg, root) -> float:
    """``sound.max_per_project_usd``, never above the owner's figure (stub: the default)."""
    return CAP_DEFAULT


def spent(root) -> float:
    """What sound has cost this project so far, reserved money included (stub: nothing)."""
    return 0.0


def reserve(root, cfg, usd: float) -> str:
    """Hold ``usd`` against the cap under one lock; raises :class:`SoundCapReached`; returns a token."""
    raise SoundCapReached("Sound isn't set up yet.")


def settle(root, token: str, real_usd: float, row: dict) -> None:
    """The call was made: record its real charge (``row`` is the sound's own line)."""
    return None


def release(root, token: str) -> None:
    """The call failed: nothing was charged, so the money held is let go."""
    return None


def per_sound(cfg, model, kind: str, seconds: float, charges: dict[str, Any] | None = None) -> float | None:
    """The price of one sound of ``kind`` and ``seconds`` from ``model``: what the service really charged
    before, else the adapter's quote, else None ("unpriced"). Stub: None."""
    return None
