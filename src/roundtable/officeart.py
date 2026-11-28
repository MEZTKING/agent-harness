"""The office's pixel art: the quote, the sample sheet, then the rest, never past $10 (wave 9).

A stub with its frozen signatures: Helper w9-office fills it. Every piece is in ``ui/static/office/manifest.json``
(its prompt, Retro Diffusion style, size and options), made by Retro Diffusion, never drawn in code. The quote
uses ``check_cost`` (it spends nothing); the sample sheet waits for the owner's yes, and only then the rest.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

CAP_USD = 10.0
SAMPLE_CAP_USD = 1.5
MANIFEST = Path(__file__).parent / "ui" / "static" / "office" / "manifest.json"


def manifest() -> list[dict[str, Any]]:
    """Every piece: ``{id, file, style, width, height, prompt, options, stage: "sample" | "rest"}`` (stub: none)."""
    return []


def quote(provider) -> dict[str, Any]:
    """``{"pieces": [{id, usd}], "sample_usd", "total_usd", "cap": 10.0}``; spends nothing (stub: nothing to make)."""
    return {"pieces": [], "sample_usd": 0.0, "total_usd": 0.0, "cap": CAP_USD}


def make(provider, stage: str, out, spent_file) -> dict[str, Any]:
    """Make the pieces of ``stage`` ("sample" or "rest") into ``out``, each reserved then settled in
    ``spent_file`` (stub: nothing is made or spent)."""
    return {"made": [], "usd": 0.0, "stage": stage, "words": "The office art isn't set up yet."}
