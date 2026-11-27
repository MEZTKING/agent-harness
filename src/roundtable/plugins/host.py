"""The plugin host: finds the plugins that are switched on, loads them and calls their hooks.

One host per harness config (``HarnessConfig.plugin_host()``). Each model conversation
(``run_agent``) gets a ``Conversation`` from it; events of a whole run go through
``notify``. A plugin that goes wrong is switched off until ``begin_run`` (the next run), its
error is logged in its folder and the owner gets a ``plugin_error`` event in plain words.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .api import QUIET_EVENTS, PluginContext, PluginError
from .builtin import BUILTINS
from .loader import load_object
from .manifest import Manifest, check_api, find_manifest

Emit = Callable[[str, dict[str, Any]], None]


def plugins_home() -> Path:
    """<app home>/plugins: each plugin's own data folder is in here."""
    from ..desktop import app_home

    return app_home() / "plugins"


def code_home() -> Path:
    """<app home>/plugin-code: where installed plugins' code is kept."""
    from ..desktop import app_home

    return app_home() / "plugin-code"


@dataclass
class Loaded:
    """One plugin the host knows about, loaded or not."""

    manifest: Manifest
    builtin: bool
    enabled: bool
    settings: dict[str, Any]
    obj: Any = None
    status: str = "off"  # on | off | broken | needs_ok
    problem: str = ""  # why it isn't on, in plain words
    path: str = ""

    @property
    def id(self) -> str:
        return self.manifest.id

    def has(self, hook: str) -> bool:
        return self.status == "on" and hook in self.manifest.hooks


def _instance(obj: Any) -> Any:
    return obj() if isinstance(obj, type) else obj


def import_paths(code: Path) -> list[Path]:
    return [p for p in (code, code / "src", code / ".deps") if p.is_dir()]


def load_installed(pid: str, spec: dict[str, Any]) -> Loaded:
    """An installed plugin from its state in custom.yaml: checked, and imported when it's on."""
    path = Path(str(spec.get("path") or ""))
    try:
        manifest = find_manifest(path)
    except PluginError as e:
        return Loaded(Manifest(pid, pid, "?", "", "?:?"), False, False, {}, status="broken", problem=str(e), path=str(path))
    item = Loaded(manifest, False, bool(spec.get("enabled", True)), {**manifest.defaults(),
                  **_safe_settings(manifest, spec.get("settings") or {})}, path=str(path))
    if manifest.id != pid:
        return _broken(item, f"the folder holds plugin {manifest.id!r}, not {pid!r}; add it again")
    if not item.enabled:
        return item
    asked = sorted(set(manifest.permissions) - set(spec.get("permissions") or []))
    if asked:
        item.status = "needs_ok"
        item.problem = (f"{manifest.name} now asks for more: {', '.join(asked)}. Switch it on again to "
                        "say yes, or remove it.")
        return item
    try:
        check_api(manifest)
        item.obj = _instance(load_object(manifest.entry, import_paths=import_paths(path)))
        _check_hooks(item)
    except Exception as e:  # a broken plugin never stops the app
        return _broken(item, f"{manifest.name} could not start ({type(e).__name__}: {e})")
    item.status = "on"
    return item


def _safe_settings(manifest: Manifest, values: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in values.items():
        if k in manifest.settings:
            try:
                out[k] = manifest.settings[k].coerce(v)
            except ValueError:
                pass  # a bad saved value: the default is used
    return out


def _broken(item: Loaded, problem: str) -> Loaded:
    item.status, item.problem, item.obj = "broken", problem, None
    return item


def _check_hooks(item: Loaded) -> None:
    missing = [h for h in item.manifest.hooks if not callable(getattr(item.obj, h, None))]
    if missing:
        raise PluginError(f"it says it uses {', '.join(missing)} but has no such method")


def load_builtin(make: Callable[[Any], tuple[Manifest, Any, bool, dict[str, Any]]], cfg: Any) -> Loaded:
    manifest, obj, enabled, settings = make(cfg)
    item = Loaded(manifest, True, enabled, settings, obj=obj, path="(built in)")
    item.status = "on" if enabled else "off"
    return item


class PluginHost:
    def __init__(self, plugins: list[Loaded], cfg: Any = None):
        self.plugins = plugins  # in calling order: the token saver first
        self.cfg = cfg
        self.off_this_run: dict[str, str] = {}  # id -> the plain message
        self.run_state: dict[str, dict[str, Any]] = {}

    @classmethod
    def from_config(cls, cfg: Any) -> "PluginHost":
        state = getattr(cfg, "plugins", None) or {}
        items = [load_builtin(make, cfg) for make in BUILTINS]
        known = {i.id for i in items}
        for pid, spec in state.items():
            if pid not in known and (spec or {}).get("path"):
                items.append(load_installed(pid, spec))
        return cls(items, cfg)

    def get(self, pid: str) -> Loaded | None:
        return next((p for p in self.plugins if p.id == pid), None)

    def begin_run(self) -> None:
        """A new run: plugins switched off by an error get another chance."""
        self.off_this_run.clear()
        self.run_state.clear()

    def active(self, hook: str) -> list[Loaded]:
        return [p for p in self.plugins if p.has(hook) and p.id not in self.off_this_run]

    # -- contexts -----------------------------------------------------------------
    def context(self, p: Loaded, project_root: Path | None = None, role: str | None = None,
                emit: Emit | None = None, state: dict[str, Any] | None = None,
                shared: dict[str, Any] | None = None) -> PluginContext:
        return PluginContext(p.id, dict(p.settings), plugins_home() / p.id, project_root=project_root, role=role,
                             state=state if state is not None else {},
                             shared=shared if shared is not None else {}, _emit=emit,
                             _cost=self._cost)

    def _cost(self, model: str, usage: Any) -> float | None:
        if self.cfg is None:
            return None
        from ..harness.config import ModelRef

        return self.cfg.cost(ModelRef.parse(model), usage)

    def conversation(self, project_root: Path | None = None, role: str | None = None, emit: Emit | None = None,
                     shared: dict[str, Any] | None = None) -> "Conversation":
        return Conversation(self, project_root, role, emit or (lambda *_: None), shared if shared is not None else {})

    # -- errors -------------------------------------------------------------------
    def fail(self, p: Loaded, hook: str, error: BaseException, emit: Emit | None) -> None:
        """Switch a plugin off for the rest of this run and tell the owner, plainly."""
        message = (f"The plugin \"{p.manifest.name}\" went wrong ({hook}: {type(error).__name__}: {error}). "
                   "It's switched off until this run ends; the run carries on without it. If it keeps "
                   f"happening, switch it off in Settings > Plugins or with `roundtable plugin disable {p.id}`.")
        self.off_this_run[p.id] = message
        _write_error_log(p.id, hook, error)
        if emit:
            try:
                emit("plugin_error", {"plugin": p.id, "hook": hook, "message": message})
            except Exception:
                pass

    def call(self, p: Loaded, hook: str, ctx: PluginContext | None, *args: Any, emit: Emit | None = None,
             check: Callable[[Any], bool] | None = None, want: str = "") -> tuple[bool, Any]:
        """(ok, result) of one hook; on any error the plugin is switched off and ok is False.

        ``ctx`` None: the hook takes no context (``commands`` and ``routes``).
        """
        try:
            fn = getattr(p.obj, hook)
            result = fn(*args) if ctx is None else fn(ctx, *args)
            if check is not None and not check(result):
                raise PluginError(f"it must return {want}, not {type(result).__name__}")
            return True, result
        except Exception as e:
            self.fail(p, hook, e, emit)
            return False, None

    # -- run events ---------------------------------------------------------------
    def notify(self, kind: str, data: dict[str, Any], project_root: Path | None = None,
               emit: Emit | None = None) -> None:
        """Hand a run event to every plugin with on_event (read-only copies; never raises)."""
        if kind in QUIET_EVENTS:
            return
        for p in self.active("on_event"):
            ctx = self.context(p, project_root, emit=emit, state=self.run_state.setdefault(p.id, {}))
            self.call(p, "on_event", ctx, kind, _copy(data), emit=emit)

    # -- commands and routes --------------------------------------------------------
    def commands(self, pid: str) -> dict[str, Callable[..., Any]]:
        p = self.get(pid)
        if not p or not p.has("commands"):
            return {}
        ok, found = self.call(p, "commands", None, check=lambda r: isinstance(r, dict), want="a dict")
        return found if ok else {}

    def route(self, method: str, pid: str, path: str, query: dict[str, Any] | None = None,
              body: Any = None) -> tuple[int, Any]:
        """Answer /api/plugins/<pid>/<path>: (HTTP status, JSON-able reply)."""
        p = self.get(pid)
        if not p or not p.has("routes"):
            return 404, {"error": f"no plugin {pid!r} with routes is switched on"}
        ok, table = self.call(p, "routes", None, check=lambda r: isinstance(r, dict), want="a dict")
        handler = table.get(f"{method.upper()} {path.strip('/')}") if ok else None
        if handler is None:
            return 404, {"error": f"{p.manifest.name} has no {method.upper()} {path.strip('/') or '(root)'}"}
        try:
            out = handler(self.context(p), dict(query or {}), body)
        except Exception as e:
            _write_error_log(p.id, f"route {path}", e)
            return 500, {"error": f"{p.manifest.name} went wrong: {type(e).__name__}: {e}"}
        return out if isinstance(out, tuple) else (200, out)


def _copy(data: dict[str, Any]) -> dict[str, Any]:
    import copy

    try:
        return copy.deepcopy(data)
    except Exception:
        return dict(data)


def _write_error_log(pid: str, hook: str, error: BaseException) -> None:
    try:
        d = plugins_home() / pid
        d.mkdir(parents=True, exist_ok=True)
        with (d / "errors.log").open("a", encoding="utf-8") as f:
            f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} {hook}\n")
            f.write("".join(traceback.format_exception(type(error), error, error.__traceback__)))
    except OSError:
        pass


@dataclass
class Conversation:
    """The plugins' view of one model conversation (one ``run_agent`` call)."""

    host: PluginHost
    project_root: Path | None
    role: str | None
    emit: Emit
    shared: dict[str, Any]
    _ctx: dict[str, PluginContext] = field(default_factory=dict)
    last_usage: Any = None  # the last model call's usage: how big the conversation was then
    _sent: int = 0  # how many messages that call was sent

    def ctx(self, p: Loaded) -> PluginContext:
        if p.id not in self._ctx:
            self._ctx[p.id] = self.host.context(p, self.project_root, self.role, self.emit, shared=self.shared)
        return self._ctx[p.id]

    def _call(self, p: Loaded, hook: str, *args: Any, **kw: Any) -> tuple[bool, Any]:
        return self.host.call(p, hook, self.ctx(p), *args, emit=self.emit, **kw)

    def tools(self) -> list[Any]:
        from ..harness.tools import Tool

        out = []
        for p in self.host.active("tools"):
            ok, found = self._call(p, "tools", check=lambda r: isinstance(r, (list, tuple))
                                   and all(isinstance(t, Tool) for t in r), want="a list of Tool")
            out += list(found or []) if ok else []
        return out

    def on_tool_result(self, tool: str, args: dict[str, Any], text: str, is_error: bool) -> str:
        for p in self.host.active("on_tool_result"):
            ok, new = self._call(p, "on_tool_result", tool, args, text, is_error,
                                 check=lambda r: isinstance(r, str), want="text (a string)")
            if ok:
                text = new
        return text

    def before_model_call(self, model: str, system: str, messages: list[dict[str, Any]]):
        """The request as the plugins want it sent; the conversation itself isn't changed."""
        self._sent = len(messages)
        for p in self.host.active("before_model_call"):
            ok, new = self._call(p, "before_model_call", self.role, model, system, list(messages),
                                 check=_is_request, want="(system text, list of messages)")
            if ok:
                system, messages = new[0], list(new[1])
        return system, messages

    def after_model_call(self, model: str, response: Any, usage: Any) -> None:
        self.last_usage = usage
        for p in self.host.active("after_model_call"):
            self._call(p, "after_model_call", self.role, model, response, usage)


    def compact(self, messages: list[dict[str, Any]], model: str, charge: Callable[[float | None], None],
                toolbox: Any = None, step: int = 0) -> float:
        """Let the ``compact`` plugins shorten ``messages`` (in place); returns what that cost.

        Called by the agent loop before each model call, when every tool call has its result. A
        model call a plugin makes is paid through ``charge`` (the task's budget). Each change is a
        ``compacted`` event: tokens before and after (after is an estimate), messages, cost.
        """
        active = self.host.active("compact")
        if not active or self.last_usage is None or not messages:
            return 0.0
        spent = [0.0]

        def pay(cost: float | None) -> None:
            charge(cost)
            spent[0] += cost or 0.0

        # the last call's size, plus what came in since (its reply is in its output tokens)
        tokens = context_tokens(self.last_usage) + estimate_tokens(messages[self._sent + 1:])
        source = getattr(toolbox, "source", None)
        changed = sorted(str(c).replace("\\", "/") for c in (getattr(source, "changed", None) or ()))
        for p in active:
            paid = spent[0]
            info = {"tokens": tokens, "model": model, "role": self.role, "step": step,
                    "task": messages[0].get("content", ""), "changed": list(changed), "charge": pay,
                    "cfg": self.host.cfg}
            old = list(messages)
            ok, new = self._call(p, "compact", list(messages), info,
                                 check=lambda r: r is None or valid_compaction(old, r),
                                 want="None or a shorter list of messages that starts with the task and keeps "
                                      "each tool call with its result")
            if not ok or new is None:
                continue
            after = max(0, tokens - estimate_tokens(old) + estimate_tokens(new))
            messages[:] = new
            self.emit("compacted", {"plugin": p.id, "role": self.role, "step": step, "tokens_before": tokens,
                                    "tokens_after": after, "messages_before": len(old), "messages_after": len(new),
                                    "cost": round(spent[0] - paid, 6)})
            tokens = after
        return spent[0]


def context_tokens(usage: Any) -> int:
    """How many tokens the conversation was at the last call: what was read plus what was written."""
    return sum(int(getattr(usage, k, 0) or 0) for k in
               ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens"))


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """A rough count (about four characters a token) of what messages hold."""
    import json

    chars = 0
    for m in messages:
        chars += len(str(m.get("content") or ""))
        if m.get("tool_calls"):
            chars += len(json.dumps(m["tool_calls"], default=str))
    return chars // 4


def valid_compaction(old: list[dict[str, Any]], new: Any) -> bool:
    """A compacted conversation: shorter, the task still first, and no tool call parted from its result."""
    if not isinstance(new, list) or not new or not all(isinstance(m, dict) for m in new):
        return False
    if new[0] != old[0] or len(new) >= len(old):
        return False
    pending: set[str] = set()
    for m in new:
        role = m.get("role")
        if role == "tool":
            if m.get("tool_call_id") not in pending:
                return False  # a result whose call was taken away
            pending.discard(m.get("tool_call_id"))
            continue
        if pending:
            return False  # a call whose result was taken away
        if role == "assistant":
            pending = {str(c.get("id")) for c in (m.get("tool_calls") or []) if isinstance(c, dict)}
    return not pending


def _is_request(r: Any) -> bool:
    return (isinstance(r, (tuple, list)) and len(r) == 2 and isinstance(r[0], str) and isinstance(r[1], list)
            and all(isinstance(m, dict) for m in r[1]))


def notify(cfg: Any, kind: str, data: dict[str, Any], project_root: Path | None = None,
           emit: Emit | None = None) -> None:
    """For the orchestrator's ``emit``: give the event to plugins. Never raises."""
    try:
        cfg.plugin_host().notify(kind, data, project_root, emit)
    except Exception:
        pass


def begin_run(cfg: Any) -> None:
    """For the start of ``Orchestrator.run``: plugins switched off last run get another chance."""
    try:
        cfg.plugin_host().begin_run()
    except Exception:
        pass
