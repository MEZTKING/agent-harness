"""The plugin API as a boxed plugin sees it: ``roundtable.plugins.api`` inside the box.

A small stand-alone copy of ``api.py`` (``Plugin``, ``PluginContext``, ``Tool``, ``ToolSpec``,
``ToolError``, ``_obj``) for the box's child process, where the rest of the harness can't be
imported. It imports only the standard library; a test keeps it in step with ``api.py``.

Differences a boxed plugin sees (docs/plugins.md):

* ``ctx.emit``, ``ctx.cost_of`` and ``ctx.http`` go through the parent process;
* ``after_model_call`` gets a ``Response`` (``text``, ``tool_calls``, ``stop_reason``, ``model``)
  and a ``Usage`` (the token counts), copies of the harness's own;
* ``compact``'s ``info`` has no ``cfg`` and no ``charge``: a boxed plugin can't call a model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

API_VERSION = 1

HOOKS = ("on_tool_result", "before_model_call", "after_model_call", "tools", "on_event", "commands", "routes",
         "compact")

PERMISSIONS = {
    "network": "Can go on the internet",
    "files": "Can read and change files on this computer outside its own folder",
    "shell": "Can run programs on this computer",
    "project:read": "Can read the project it is helping with",
}
SECRET_PERMISSION = "secrets:"

BOXED = True  # a plugin can tell it runs in the box


class PluginError(RuntimeError):
    """A plugin can't be read, installed or loaded (the message is for the owner)."""


class ToolError(Exception):
    pass


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class Tool:
    spec: ToolSpec
    fn: Callable[[dict[str, Any]], str]
    terminal: bool = False


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float | None = None


@dataclass
class ToolCall:
    id: str = ""
    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class Response:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end"
    model: str = ""


@dataclass
class PluginContext:
    """What a hook gets as ``ctx`` inside the box."""

    plugin_id: str
    settings: dict[str, Any]
    home: Path
    project_root: Path | None = None
    role: str | None = None
    state: dict[str, Any] = field(default_factory=dict)
    shared: dict[str, Any] = field(default_factory=dict)
    _ask: Callable[..., Any] | None = field(default=None, repr=False)

    @property
    def data_dir(self) -> Path:
        self.home.mkdir(parents=True, exist_ok=True)
        return self.home

    @property
    def log(self) -> logging.Logger:
        return logging.getLogger(f"roundtable.plugins.{self.plugin_id}")

    def emit(self, kind: str, data: dict[str, Any] | None = None) -> None:
        """Tell the run's activity feed something (shows as a ``plugin`` event)."""
        if self._ask:
            self._ask("emit", {"kind": kind, "data": data or {}}, wait=False)

    def cost_of(self, model: str, usage: Any) -> float | None:
        """What a call cost in US dollars (``model`` is ``provider/model``); None when unpriced."""
        if not self._ask:
            return None
        u = usage if isinstance(usage, dict) else {k: getattr(usage, k, 0) for k in
                                                     ("input_tokens", "output_tokens", "cache_read_tokens",
                                                      "cache_write_tokens", "cost_usd")}
        return self._ask("cost", {"model": model, "usage": u})

    def http(self, method: str, url: str, headers: dict[str, str] | None = None, body: str | None = None,
             timeout: float = 30) -> dict[str, Any]:
        """A web request to a host this plugin has ``secrets:<host>`` for, with your saved key added
        by the harness outside the box (the key never enters it): {"status", "headers", "body"}."""
        if not self._ask:
            raise PluginError("web requests through the harness aren't available here")
        return self._ask("http", {"method": method, "url": url, "headers": dict(headers or {}), "body": body,
                                  "timeout": timeout})


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

    def compact(self, ctx: PluginContext, messages: list[dict[str, Any]],
                info: dict[str, Any]) -> list[dict[str, Any]] | None:
        return None

    def commands(self) -> dict[str, Callable[[PluginContext, list[str]], Any]]:
        return {}

    def routes(self) -> dict[str, Callable[[PluginContext, dict[str, Any], Any], Any]]:
        return {}
