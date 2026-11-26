"""The provider-agnostic tool-use loop.

One call to ``run_agent`` = one model working on one job until it stops
calling tools, calls a terminal tool (e.g. ``submit_review``), runs out of
steps, or the budget is exhausted.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..providers.base import Provider, ProviderError, Usage
from .config import HarnessConfig, ModelRef
from .saver import TokenSaver
from .tools import Toolbox


class BudgetExceeded(RuntimeError):
    pass


class OutOfCredit(BudgetExceeded):
    """A provider said the account has no money left; the run pauses until the owner tops up."""


@dataclass
class Budget:
    limit_usd: float
    spent_usd: float = 0.0
    unpriced_calls: int = 0
    on_charge: Any = field(default=None, repr=False, compare=False)  # callback(cost) for spend logs

    def charge(self, cost: float | None) -> None:
        if cost is None:
            self.unpriced_calls += 1
        else:
            self.spent_usd += cost
            if self.on_charge and cost:
                self.on_charge(cost)

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
    stop: str  # done | terminal | max_steps | refusal | max_tokens
    captured: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    seconds: float = 0.0
    saved_tokens_est: int = 0  # tokens the token saver kept out of this conversation (estimate)


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
) -> AgentResult:
    """Drive one model through a tool loop.

    ``require_terminal``: name of a tool the model must call before it is
    done (e.g. ``submit_plan``). If it answers in prose instead, it gets
    nudged (forced tool_choice isn't available on every model).

    ``saver``: a ``TokenSaver`` for this conversation. Each tool result goes through it
    once, as it enters ``messages``; earlier messages are never rewritten (prompt cache).
    The model also gets its ``expand_output`` tool.
    """
    provider = cfg.provider(ref.provider)
    if not isinstance(provider, Provider):
        raise ProviderError(f"{ref} is not a chat provider")
    emit = on_event or (lambda *_: None)
    if saver is not None and saver.cfg.enabled:
        saver.on_event = saver.on_event or emit
        if "expand_output" not in toolbox.tools:
            toolbox.add(saver.tool())
    saved_at_start = saver.stats.tokens_saved if saver else 0
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    total = Usage()
    cost = 0.0
    nudges = 0
    t0 = time.monotonic()
    stop = "max_steps"
    text = ""

    for step in range(1, max_steps + 1):
        budget.check()
        resp = provider.chat(ref.model, system, messages, toolbox.specs(), max_tokens=max_tokens, options=options)
        c = cfg.cost(ref, resp.usage)
        budget.charge(c)
        cost += c or 0.0
        total = total + resp.usage
        messages.append(resp.as_message())
        text = resp.text or text
        emit("model_turn", {"model": str(ref), "step": step, "text": resp.text[:500],
                            "tools": [tc.name for tc in resp.tool_calls], "cost": c})

        if resp.stop_reason == "refusal":
            stop = "refusal"
            break

        if resp.tool_calls:
            for tc in resp.tool_calls:
                out, is_err = toolbox.call(tc.name, tc.arguments)
                emit("tool_call", {"tool": tc.name, "args": _short(tc.arguments), "error": is_err, "result": out[:300]})
                if saver is not None:
                    out = saver.process(tc.name, tc.arguments, out, is_err)
                messages.append({"role": "tool", "tool_call_id": tc.id, "name": tc.name, "content": out, "is_error": is_err})
            if toolbox.done():
                stop = "terminal"
                break
            continue

        if resp.stop_reason == "max_tokens":
            messages.append({"role": "user", "content": "Your reply was cut off. Continue, using tools for large file contents."})
            continue

        if require_terminal and require_terminal not in toolbox.captured and nudges < 2:
            nudges += 1
            messages.append({"role": "user", "content": f"You must finish by calling the `{require_terminal}` tool."})
            continue
        stop = "done"
        break

    return AgentResult(
        text=text,
        steps=step,
        usage=total,
        cost_usd=cost,
        model=str(ref),
        stop=stop,
        captured=dict(toolbox.captured),
        messages=messages,
        seconds=round(time.monotonic() - t0, 2),
        saved_tokens_est=(saver.stats.tokens_saved - saved_at_start) if saver else 0,
    )


def _short(args: dict[str, Any]) -> dict[str, Any]:
    return {k: (v[:120] + "..." if isinstance(v, str) and len(v) > 120 else v) for k, v in args.items()}
