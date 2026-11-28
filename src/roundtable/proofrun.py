"""The proof run: one idea, one small game, built end to end for a known, capped price (wave 9).

A stub with its frozen signatures: Helper w9-proof fills it. The run goes through the ordinary commands (new,
plan, approve, run), so it proves the harness and not a script; the caps are the harness's own limits.
"""

from __future__ import annotations

from typing import Any


def prepare(lab, idea: str, caps: dict[str, Any]) -> dict[str, Any]:
    """Make the lab folder and a made-up hub for ``idea`` under ``caps`` (stub: nothing is made)."""
    raise NotImplementedError("The proof run isn't built yet.")


def report(lab) -> dict[str, Any]:
    """The estimate, the harness's own count and the real fall in the balance, side by side (stub: none yet)."""
    return {"ready": False, "words": "No proof run yet."}
