"""A reply's words as they are written, kept per task for Watch and the chat (wave 8, stub: p1-chat fills it).

``sink(root, task)`` is what ``run_agent(on_delta=...)`` is given; ``tail(root, task, since)`` is what
``GET /api/stream`` answers: ``{"text", "thinking", "at", "done"}`` (``at``: where the next read starts).
Until p1-chat fills it the sink keeps nothing and writes no file. The signatures are frozen.
"""

from typing import Callable


def sink(root, task: str) -> Callable[[str, str], None]:
    """Where ``task``'s reply pieces go (``("text" | "thinking", piece)``). Stub: does nothing."""

    def keep(kind: str, piece: str) -> None:
        return None

    return keep


def tail(root, task: str, since: int = 0) -> dict:
    """What is new since ``since``. Stub: nothing, and nothing more coming."""
    return {"text": "", "thinking": "", "at": since, "done": True}
