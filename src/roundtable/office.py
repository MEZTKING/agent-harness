"""The office: a second view of the Hall where each agent can be seen at work (wave 9).

A stub with its frozen signature: Helper w9-office fills it. No model is asked: where each agent stands comes
from what the harness already knows (a task building, a command running, a question waiting, a quiet task),
and nothing here invents activity.
"""

from __future__ import annotations

from typing import Any


def scene(app) -> dict[str, Any]:
    """``{"rooms": [...], "actors": [{"id", "name", "at", "doing", "bubble", "project"}], "art": bool}``.
    Stub: an empty office with no art, so the app keeps the Ring."""
    return {"rooms": [], "actors": [], "art": False}
