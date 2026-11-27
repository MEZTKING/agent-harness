"""The charter: what the lab may never change by itself (wave 7, Helper 4 fills this in).

Anything that applies, shares, re-applies or offers a learned change asks ``check`` and ``may_auto``
here, never a copy of the rules. The signatures below are frozen: the helper that owns this file fills
the bodies and keeps them as they are.
"""

from __future__ import annotations

from typing import Any


class CharterError(ValueError):
    """A change the charter refuses. ``needs_owner``: the owner may still allow it with one tap."""

    needs_owner: bool = False


def check(cfg: Any, proposal: Any, lab: Any = None, by_owner: bool = False) -> None:
    """Raise CharterError when ``proposal`` would change something protected. Stub: passes."""
    return None


def may_auto(proposal: Any) -> bool:
    """Whether the lab may apply ``proposal`` without the owner's tap. Stub: the three first kinds."""
    return getattr(proposal, "kind", "") in ("routing", "options", "prompt")


def may_touch(path: str) -> bool:
    """Whether a fix the harness makes to its own code may change ``path``. Stub: True."""
    return True


def fixed_block(prompt_name: str) -> str:
    """The lines no learned prompt can drop, added to every system prompt of that name. Stub: none."""
    return ""


def scrub(text: str, lab: Any = None) -> str:
    """``text`` with project names, paths and key-like text taken out. Stub: unchanged."""
    return text


def diff(old: str, new: str) -> list[dict[str, Any]]:
    """Line by line: [{"op": "same" | "gone" | "new", "text": ...}]. Stub: []."""
    return []
