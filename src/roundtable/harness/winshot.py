"""A picture of a running program's window (wave 8, stub: p1-proof fills it).

``window_picture(pid, out)`` finds the top-level window of the process (or a child), waits up to ``wait``
seconds for it and saves its picture to ``out``: ``{"ok", "file", "why"}``. ``find`` and ``grab`` are passed
in by tests. Windows only; elsewhere the answer is "not checked" with the reason, never a failure. The
signature is frozen.
"""

from pathlib import Path


def window_picture(pid: int, out: Path, wait: float = 8.0, grab=None, find=None) -> dict:
    """Stub: not checked yet."""
    return {"ok": False, "file": None, "why": "Not checked: pictures of a program's window aren't built yet."}
