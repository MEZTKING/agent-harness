"""The provider-agnostic tool-use loop.

One call to ``run_agent`` = one model working on one job until it stops
calling tools, calls a terminal tool (e.g. ``submit_review``), runs out of
steps, or the budget is exhausted.
"""

from __future__ import annotations

import inspect
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Callable

from .. import otel
from ..providers.base import Provider, ProviderError, Usage
from .breaker import Breaker, BreakerSettings, work_tokens
from .config import HarnessConfig, ModelRef
from .saver import TokenSaver
from .tools import Toolbox


class BudgetExceeded(RuntimeError):
    pass


class OutOfCredit(BudgetExceeded):
    """A provider said the account has no money left; the run pauses until the owner tops up."""


@dataclass
class Budget:
    """The run's money. ``charge`` is safe from several threads (its own lock).

    ``on_charge(cost)``: for spend logs. ``on_use(ref, usage, cost, role)``: who spent it (a model ref,
    its token ``Usage``, the role), called after ``on_charge`` for every charge, even an unpriced one.
    """
    limit_usd: float
    spent_usd: float = 0.0
    unpriced_calls: int = 0
    on_charge: Any = field(default=None, repr=False, compare=False)  # callback(cost) for spend logs
    on_use: Any = field(default=None, repr=False, compare=False)  # callback(ref, usage, cost, role)
    _lock: Any = field(default_factory=threading.RLock, init=False, repr=False, compare=False)

    def charge(self, cost: float | None, *, ref: Any = None, usage: Any = None, role: str | None = None) -> None:
        with self._lock:
            if cost is None:
                self.unpriced_calls += 1
            else:
                self.spent_usd += cost
            try:
                if self.on_charge and cost:
                    self.on_charge(cost)
            finally:  # who spent it is written even when the spend log stops the run
                if self.on_use:
                    self.on_use(ref, usage, cost, role)

    def check(self) -> None:
        if self.spent_usd >= self.limit_usd:
            raise BudgetExceeded(f"budget exhausted: ${self.spent_usd:.4f} of ${self.limit_usd:.2f}")


@dataclass
class AgentResult:
    text: str
    steps: int
    usage: Usage
    cost_usd: float
    model: str
    stop: str  # done | terminal | max_steps | refusal | max_tokens | breaker
    captured: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    seconds: float = 0.0
    saved_tokens_est: int = 0  # tokens the token saver kept out of this conversation (estimate)
    breaker_reason: str = ""  # with stop == "breaker": why, in plain words
    model_ms: int = 0  # time spent waiting for the model
    tool_ms: int = 0  # time spent inside tool calls
    other_ms: int = 0  # the rest: plugins, saving, everything between


def _delta_kw(provider: Any, on_delta: Callable[[str, str], None] | None) -> dict[str, Any]:
    """``{"on_delta": on_delta}`` when there is one and the provider's ``chat`` takes it, else nothing: with no
    ``on_delta`` the call is the one made before streaming existed, and an older provider still works."""
    if on_delta is None:
        return {}
    try:
        params = inspect.signature(provider.chat).parameters
    except (TypeError, ValueError):
        return {}
    takes = "on_delta" in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    return {"on_delta": on_delta} if takes else {}


def run_agent(
    cfg: HarnessConfig,
    ref: ModelRef,
    system: str,
    prompt: str,
    toolbox: Toolbox,
    budget: Budget,
    max_steps: int = 40,
    max_tokens: int = 16000,
    options: dict[str, Any] | None = None,
    require_terminal: str | None = None,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
    saver: TokenSaver | None = None,
    role: str | None = None,
    project_root: Path | None = None,
    breaker: Breaker | None = None,
    on_delta: Callable[[str, str], None] | None = None,
) -> AgentResult:
    """Drive one model through a tool loop.

    ``require_terminal``: name of a tool the model must call before it is
    done (e.g. ``submit_plan``). If it answers in prose instead, it gets
    nudged (forced tool_choice isn't available on every model).

    ``saver``: a ``TokenSaver`` for this conversation. Each tool result goes through it
    once, as it enters ``messages``; earlier messages are never rewritten (prompt cache).
    The model also gets its ``expand_output`` tool.

    Plugins (``cfg.plugin_host()``; the token saver is the first, built in) see each model
    call before and after it, each tool result as it enters, and may add tools. ``role`` and
    ``project_root`` are what they are told about this conversation.

    ``breaker``: the guard against loops, error storms, runaway output, the token cap and no
    progress (``breaker.py``); by default one from ``breaker:`` in harness.yaml. When it stops the
    loop, ``stop`` is ``"breaker"`` and ``breaker_reason`` says why.

    Every ``model_turn`` and ``tool_call`` event carries ``ms`` (how long it took); the closing
    ``agent_done`` event carries the totals (``model_ms``, ``tool_ms``, ``other_ms``).

    ``on_delta`` (wave 8): told each piece of every reply as it is written (``"text"`` or ``"thinking"``, then the
    piece), when the provider can stream. ``None`` (the default) makes exactly the call made before it existed;
    so does a provider that doesn't take it. A coding CLI's own loop doesn't use it.
    """
    provider = cfg.provider(ref.provider)
    from ..providers.cli_engine import CliEngine, run_cli_agent

    if isinstance(provider, CliEngine):  # a coding CLI drives its own loop (cli_engine.py)
        return run_cli_agent(cfg, ref, system, prompt, toolbox, budget, max_steps=max_steps, max_tokens=max_tokens,
                             options=options, require_terminal=require_terminal, on_event=on_event, saver=saver,
                             role=role, project_root=project_root, breaker=breaker)
    if not isinstance(provider, Provider):
        raise ProviderError(f"{ref} is not a chat provider")
    emit = on_event or (lambda *_: None)
    if saver is not None and saver.cfg.enabled:
        saver.on_event = saver.on_event or emit
    root = project_root if project_root is not None else (saver.project_root if saver is not None else None)
    plugins = cfg.plugin_host().conversation(Path(root) if root else None, role, emit,
                                             shared={"token_saver": saver, "emit": emit})
    for tool in plugins.tools():
        if tool.spec.name not in toolbox.tools:  # a plugin never replaces a workspace tool
            toolbox.add(tool)
    saver = plugins.shared.get("token_saver")
    saved_at_start = saver.stats.tokens_saved if saver else 0
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    total = Usage()
    cost = 0.0
    nudges = 0
    brk = breaker if breaker is not None else Breaker(BreakerSettings.from_config(cfg))
    clock = brk.clock
    t0 = clock()
    model_s = tool_s = 0.0
    waited_ms = 0  # time the commands waited for the owner (Ask me first)
    stop = "max_steps"
    text = ""
    step = 0

    for step in range(1, max_steps + 1):
        cost += plugins.compact(messages, str(ref), lambda c: budget.charge(c, ref=ref, role=role), toolbox, step)  # long tasks: older steps summed up
        budget.check()
        sys_sent, msgs_sent = plugins.before_model_call(str(ref), system, messages)
        m0 = clock()
        with otel.span(otel.here(), "model", model=str(ref), role=role or "", step=step) as _sp:  # run timeline
            resp = provider.chat(ref.model, sys_sent, msgs_sent, toolbox.specs(), max_tokens=max_tokens,
                                 options=options, **_delta_kw(provider, on_delta))
            if _sp:
                _sp.set("input_tokens", resp.usage.input_tokens)
                _sp.set("output_tokens", resp.usage.output_tokens)
        took = clock() - m0
        model_s += took
        plugins.after_model_call(str(ref), resp, resp.usage)
        c = cfg.cost(ref, resp.usage)
        budget.charge(c, ref=ref, usage=resp.usage, role=role)
        cost += c or 0.0
        total = total + resp.usage
        messages.append(resp.as_message())
        text = resp.text or text
        emit("model_turn", {"model": str(ref), "step": step, "text": resp.text[:500], "role": role,
                            "tools": [tc.name for tc in resp.tool_calls], "cost": c, "ms": _ms(took),
                            "input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens,
                            "cache_read_tokens": resp.usage.cache_read_tokens,
                            "cache_write_tokens": resp.usage.cache_write_tokens})

        if resp.stop_reason == "refusal":
            stop = "refusal"
            break

        finishing = any(getattr(toolbox.tools.get(tc.name), "terminal", False) for tc in resp.tool_calls)
        if not finishing:  # a reply that finishes the task is never stopped
            brk.after_reply(resp.text or "", work_tokens(total))
        action = brk.end_step()
        if action and _tripped(emit, brk, action, role, step) == "stop":
            stop = "breaker"
            break
        note = brk.note(action) if action else ""

        if resp.tool_calls:
            for tc in resp.tool_calls:
                tool = toolbox.tools.get(tc.name)
                if brk.refuses(tc.name, bool(tool and tool.terminal)):
                    out, is_err = brk.refusal(), True
                    emit("tool_call", {**_tool_event(tc.name, tc.arguments, out, is_err, None), "refused": True, "ms": 0})
                else:
                    brk.tool_started(tc.name)
                    a0 = clock()
                    with otel.span(otel.here(), "tool", tool=tc.name) as _tsp:
                        out, is_err = toolbox.call(tc.name, tc.arguments)
                        if _tsp and is_err:
                            _tsp.error("the tool reported a problem")
                    took = clock() - a0
                    tool_s += took
                    change = toolbox.take_change()
                    waited = toolbox.take_waited()
                    waited_ms += waited
                    emit("tool_call", {**_tool_event(tc.name, tc.arguments, out, is_err, change), "ms": _ms(took),
                                       **({"waited_ms": waited} if waited else {})})
                    out = brk.after_tool(tc.name, tc.arguments, out, is_err, bool(change))
                out = plugins.on_tool_result(tc.name, tc.arguments, out, is_err)
                messages.append({"role": "tool", "tool_call_id": tc.id, "name": tc.name, "content": out, "is_error": is_err})
            brk.tools_done()
            if toolbox.done():
                stop = "terminal"
                break
            if not action:  # a step goes up one level at most
                action = brk.end_step()
                if action and _tripped(emit, brk, action, role, step) == "stop":
                    stop = "breaker"
                    break
                note = brk.note(action) if action else ""
            if note:  # the note rides on the last tool result: no extra turn, nothing rewritten
                messages[-1]["content"] = f"{messages[-1]['content']}\n\n{note}"
            continue

        if resp.stop_reason == "max_tokens":
            messages.append({"role": "user", "content": _join(note, "Your reply was cut off. Continue, using tools for large file contents.")})
            continue

        if require_terminal and require_terminal not in toolbox.captured and nudges < 2:
            nudges += 1
            messages.append({"role": "user", "content": _join(note, f"You must finish by calling the `{require_terminal}` tool.")})
            continue
        stop = "done"
        break

    seconds = clock() - t0
    other_s = max(0.0, seconds - model_s - tool_s)
    emit("agent_done", {"model": str(ref), "role": role, "stop": stop, "steps": step,
                        "model_ms": _ms(model_s), "tool_ms": _ms(tool_s), "other_ms": _ms(other_s),
                        "ms": _ms(seconds), **({"waited_ms": waited_ms} if waited_ms else {}),
                        **({"breaker": brk.reason} if stop == "breaker" else {}),
                        **({"breaker_trips": brk.trips} if brk.trips else {})})
    return AgentResult(
        text=text,
        steps=step,
        usage=total,
        cost_usd=cost,
        model=str(ref),
        stop=stop,
        captured=dict(toolbox.captured),
        messages=messages,
        seconds=round(seconds, 2),
        saved_tokens_est=(saver.stats.tokens_saved - saved_at_start) if saver else 0,
        breaker_reason=brk.reason if stop == "breaker" else "",
        model_ms=_ms(model_s),
        tool_ms=_ms(tool_s),
        other_ms=_ms(other_s),
    )


def _ms(seconds: float) -> int:
    return round(seconds * 1000)


def _join(note: str, msg: str) -> str:
    return f"{note}\n\n{msg}" if note else msg


def _tripped(emit: Callable[[str, dict[str, Any]], None], brk: Breaker, action: str, role: str | None, step: int) -> str:
    """Tell the event log the breaker went up a level; returns the action."""
    trip = brk.trips[-1]
    emit("breaker", {"action": action, "signal": trip["signal"], "reason": trip["reason"], "role": role,
                     "step": step})
    return action


def _tool_event(name: str, args: dict[str, Any], out: str, is_err: bool, change: dict[str, Any] | None) -> dict[str, Any]:
    """What a tool call leaves in events.jsonl: short arguments, the start of the result, and for the
    Session view the diff of a write or edit and the end of a command's output."""
    row: dict[str, Any] = {"tool": name, "args": _short(args), "error": is_err, "result": out[:300]}
    if change:
        row["change"] = change
    if name == "run_command":
        row["output"] = out if len(out) <= 3000 else out[:1000] + "\n...\n" + out[-2000:]
    return row


def _short(args: dict[str, Any]) -> dict[str, Any]:
    return {k: (v[:120] + "..." if isinstance(v, str) and len(v) > 120 else v) for k, v in args.items()}
