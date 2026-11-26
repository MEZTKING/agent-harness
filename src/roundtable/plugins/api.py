"""The plugin API: what a Roundtable Hold plugin can hook into (version 1).

A plugin is any object (an instance, a class with no arguments, or a module) with some of
these methods. Subclassing ``Plugin`` is optional; it gives a do-nothing default for each.
Only the hooks named in the plugin's manifest (``hooks = [...]``) are called.

=====================  =================================================  ==================
hook                   called                                             returns
=====================  =================================================  ==================
on_tool_result         as each tool result enters a model's conversation  the text to keep
before_model_call      just before each model call                        (system, messages)
after_model_call       after each model call                              nothing
tools                  once per conversation                              list of ``Tool``
on_event               for each run event (task_start, plan, ...)         nothing (read-only)
commands               when ``roundtable <plugin-id> ...`` runs           {name: fn(ctx, argv)}
routes                 when the app calls ``/api/plugins/<id>/<path>``    {"GET path": fn}
=====================  =================================================  ==================

``ctx`` (a ``PluginContext``) gives the plugin its settings, a data folder of its own, a
logger, the project folder (read it, don't write it), the role, ``emit`` and ``state`` (a
dict that lasts one conversation).

Safety: a hook that raises, or returns the wrong type, is caught; the plugin is switched off
until the run ends and the owner sees a plain message. Nothing stops a plugin's code doing
anything Python can do: installing one means trusting it (see docs/plugins.md).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..harness.tools import Tool, ToolError, _obj  # noqa: F401  (re-exported for plugins)
from ..providers.base import ToolSpec  # noqa: F401  (re-exported for plugins)

API_VERSION = 1

HOOKS = ("on_tool_result", "before_model_call", "after_model_call", "tools", "on_event", "commands", "routes")

# What each permission means, in the words the owner reads before installing.
PERMISSIONS = {
    "network": "Can go on the internet",
    "files": "Can read and change files on this computer outside its own folder",
    "shell": "Can run programs on this computer",
}
SECRET_PERMISSION = "secrets:"  # secrets:<host> - may use your saved key for that host

# Events a plugin never receives through on_event (its own messages; avoids loops).
QUIET_EVENTS = frozenset({"plugin", "plugin_error"})


def permission_words(perm: str) -> str:
    if perm.startswith(SECRET_PERMISSION):
        return f"Can use your saved key for {perm[len(SECRET_PERMISSION):]}"
    return PERMISSIONS.get(perm, perm)


class PluginError(RuntimeError):
    """A plugin can't be read, installed or loaded (the message is for the owner)."""


@dataclass
class PluginContext:
    """What a hook gets as ``ctx``."""

    plugin_id: str
    settings: dict[str, Any]
    home: Path  # <app home>/plugins/<id>/ (made when first used)
    project_root: Path | None = None
    role: str | None = None
    state: dict[str, Any] = field(default_factory=dict)  # lasts one conversation (or one run for on_event)
    shared: dict[str, Any] = field(default_factory=dict)  # what the harness hands every plugin (e.g. token_saver)
    _emit: Callable[[str, dict[str, Any]], None] | None = field(default=None, repr=False)
    _cost: Callable[[str, Any], float | None] | None = field(default=None, repr=False)

    @property
    def data_dir(self) -> Path:
        self.home.mkdir(parents=True, exist_ok=True)
        return self.home

    @property
    def log(self) -> logging.Logger:
        return logging.getLogger(f"roundtable.plugins.{self.plugin_id}")

    def emit(self, kind: str, data: dict[str, Any] | None = None) -> None:
        """Tell the run's activity feed something (shows as a ``plugin`` event)."""
        if self._emit:
            self._emit("plugin", {"plugin": self.plugin_id, "kind": kind, **(data or {})})

    def cost_of(self, model: str, usage: Any) -> float | None:
        """What a call cost in US dollars (``model`` is ``provider/model``); None when unpriced."""
        return self._cost(model, usage) if self._cost else None


class Plugin:
    """Optional base class: every hook does nothing until you override it."""

    def on_tool_result(self, ctx: PluginContext, tool: str, args: dict[str, Any], text: str, is_error: bool) -> str:
        return text

    def before_model_call(self, ctx: PluginContext, role: str | None, model: str, system: str,
                          messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        return system, messages

    def after_model_call(self, ctx: PluginContext, role: str | None, model: str, response: Any, usage: Any) -> None:
        return None

    def tools(self, ctx: PluginContext) -> list[Tool]:
        return []

    def on_event(self, ctx: PluginContext, kind: str, data: dict[str, Any]) -> None:
        return None

    def commands(self) -> dict[str, Callable[[PluginContext, list[str]], Any]]:
        return {}

    def routes(self) -> dict[str, Callable[[PluginContext, dict[str, Any], Any], Any]]:
        return {}
