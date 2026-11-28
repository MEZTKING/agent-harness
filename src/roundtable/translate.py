"""What models and the harness write as they go, read in the owner's language (wave 9).

A stub with its frozen signatures: Helper w9-words fills it. One model call (the project's cheapest allowed
model, ``makers.allowed`` obeyed), priced first, kept by the hash of the text in ``.harness/translations/`` so
it is paid for once. Until it is filled nothing is translated and nothing is spent.
"""

from __future__ import annotations

from typing import Any


def price(cfg, text: str, lang: str) -> float | None:
    """What translating ``text`` into ``lang`` would cost, in dollars, without spending (stub: None)."""
    return None


def words(cfg, root, text: str, lang: str, why: str) -> dict[str, Any]:
    """``{"text", "cached": bool, "usd"}``: ``text`` in ``lang`` (stub: the text as it is, nothing spent)."""
    return {"text": text, "cached": False, "usd": 0.0}
