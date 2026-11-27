"""Plugins in their own box: a separate process with no keys, no internet, no other programs and only
its own folder (wave 7, Helper 1 fills this in). The signatures below are frozen.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .api import PluginError


class SandboxError(PluginError):
    """A boxed plugin couldn't start, broke a rule or didn't answer (the message is for the owner)."""


class Box:
    """A running box. ``call(hook, payload, timeout)`` returns the hook's answer; ``stop()`` ends it."""

    def call(self, hook: str, payload: Any, timeout: float) -> Any:
        raise SandboxError("Plugins can't run in their own box yet.")

    def stop(self) -> None:
        return None


def supported() -> dict[str, Any]:
    """What the box can enforce on this computer. Stub: only the guard inside Python."""
    return {"guard": True, "os_net": False, "os_proc": False,
            "words": "Plugins can't run in their own box yet."}


def start(code: Path, manifest: Any, granted: list[str], data_dir: Path) -> Box:
    """Start a plugin in a box. Stub: refuses."""
    raise SandboxError("Plugins can't run in their own box yet.")


def trial(code: Path, command: list[str], timeout: float = 60) -> dict[str, Any]:
    """Run a plugin's own tests inside the box: {"ok", "output"}. Stub: refuses."""
    return {"ok": False, "output": "Plugins can't run in their own box yet."}
