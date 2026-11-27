"""The charter's part of every system prompt (wave 7): the fixed rules and the owner's house style.

Both are added when a prompt is sent (``Orchestrator._system``, SYSTEM_PARTS) and are never stored in a
learned prompt, so no learned prompt can drop them.
"""

from __future__ import annotations

from ..improve import charter
from . import housestyle


class CharterStage:
    def _charter_system(self, name: str = "") -> str:
        """The lines every agent gets (a constant: it cannot fail and go missing)."""
        return charter.fixed_block(name)

    def _style_system(self, name: str = "") -> str:
        """The owner's house style under "How to write for the owner" ("" when it is off)."""
        return housestyle.block(getattr(self, "cfg", None))
