"""The circuit breaker: a guard on one agent loop (one task's attempt).

It watches five signals:

* the same tool call (name and arguments) made ``repeats`` times in a row;
* ``errors`` tool errors in a row;
* runaway output: one tool result or one model reply longer than ``max_output_chars``;
* the task's tokens (input + output + cache writes; cache reads left out, since the context is
  re-read on every call) past ``max_tokens_per_task``;
* ``no_progress_minutes`` without progress. Progress is a file changed, or a tool call never made
  before in this conversation. Time spent inside a long command (``quiet_tools``) is not counted.

Each time a signal trips, the breaker goes one level up – never more than one level in a step:
first it **steers** (a short note to the model saying what it is doing wrong), then it **refuses**
the model's next tool calls (all but the tool that finishes the task), then it **stops** the
loop, which ``run_agent`` returns as ``stop="breaker"`` with the plain reason. A changed file
lowers the level by one again.

The policy follows Munder Difflin's circuit breaker (``src/main/breaker.ts``, MIT,
Copyright (c) 2026 Chaitanya Giri): the steer → constrain → stop ladder, one level at a time,
defaults of 8 identical calls and 5 errors, and the call key as a hash of its arguments with each
long string capped. It is rewritten here for a single loop instead of a periodic beat.

No side effects: ``run_agent`` feeds it what happened and does what it says.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import section

LEVELS = ("ok", "steer", "refuse", "stop")


@dataclass
class BreakerSettings:
    """``breaker:`` in harness.yaml. 0 switches a single check off."""

    enabled: bool = True
    repeats: int = 8  # identical tool calls in a row
    errors: int = 5  # tool errors in a row
    max_output_chars: int = 100_000  # one tool result or one model reply
    max_tokens_per_task: int = 3_000_000  # input + output + cache writes in one attempt
    no_progress_minutes: float = 5.0
    quiet_tools: tuple[str, ...] = ("run_command", "run_game")  # their running time isn't "no progress"

    @classmethod
    def from_config(cls, cfg: Any) -> "BreakerSettings":
        raw = section(cfg, "breaker")
        out = cls()
        for key in ("enabled",):
            if key in raw:
                setattr(out, key, bool(raw[key]))
        for key in ("repeats", "errors", "max_output_chars", "max_tokens_per_task"):
            if key in raw and raw[key] is not None:
                setattr(out, key, max(0, int(raw[key])))
        if raw.get("no_progress_minutes") is not None:
            out.no_progress_minutes = max(0.0, float(raw["no_progress_minutes"]))
        if isinstance(raw.get("quiet_tools"), (list, tuple)):
            out.quiet_tools = tuple(str(t) for t in raw["quiet_tools"])
        return out


@dataclass
class Trip:
    signal: str  # repeats | errors | output | tokens | no_progress
    reason: str  # plain words, for the owner and the orchestrator
    hint: str  # what the model should do instead


@dataclass
class Breaker:
    settings: BreakerSettings = field(default_factory=BreakerSettings)
    clock: Callable[[], float] = time.monotonic
    level: int = 0
    trips: list[dict[str, Any]] = field(default_factory=list)  # every escalation, for the final event

    def __post_init__(self) -> None:
        self._repeat_key: str | None = None
        self._repeat_count = 0
        self._errors = 0
        self._seen: set[str] = set()
        self._last_progress = self.clock()
        self._pending: Trip | None = None  # the first trip of this step
        self._refusing = False
        self._tool_started = 0.0

    @property
    def on(self) -> bool:
        return self.settings.enabled

    @property
    def stopped(self) -> bool:
        return self.level >= 3

    @property
    def reason(self) -> str:
        return self.trips[-1]["reason"] if self.trips else ""

    # -- what happened ----------------------------------------------------------------------
    def after_reply(self, text: str, work_tokens: int) -> None:
        """A model reply came back; ``work_tokens`` is the attempt's total so far."""
        s = self.settings
        if not self.on:
            return
        if s.max_output_chars and len(text or "") > s.max_output_chars:
            self._trip("output", f"a reply of {len(text):,} characters, over the {s.max_output_chars:,} limit",
                       "Keep replies short; put large content in files with the tools.")
        if s.max_tokens_per_task and work_tokens >= s.max_tokens_per_task:
            self._trip("tokens", f"{work_tokens:,} tokens used, over the {s.max_tokens_per_task:,} for one task",
                       "Stop exploring. Finish the task now with what you have.")
        self._check_progress()

    def refuses(self, name: str, terminal: bool) -> bool:
        """Whether this tool call is refused (the step after a "refuse"). The finishing tool never is."""
        return self.on and self._refusing and not terminal

    def tools_done(self) -> None:
        """A batch of tool calls was handled: a refusal lasts one batch."""
        self._refusing = False

    def tool_started(self, name: str) -> None:
        self._tool_started = self.clock()

    def after_tool(self, name: str, args: dict[str, Any], out: str, is_err: bool, changed: bool) -> str:
        """A tool call ran. Returns its output, cut down when it ran away."""
        s = self.settings
        now = self.clock()
        if name in s.quiet_tools:  # a long build or test run is work: its time isn't counted
            self._last_progress += max(0.0, now - self._tool_started)
        if not self.on:
            return out
        key = call_key(name, args)
        if changed or key not in self._seen:
            self._last_progress = now
        self._seen.add(key)
        if changed:
            self._repeat_key, self._repeat_count = None, 0
            if self.level and not self._pending:
                self.level -= 1  # real work again: one level back down
        if key == self._repeat_key:
            self._repeat_count += 1
        else:
            self._repeat_key, self._repeat_count = key, 1
        self._errors = self._errors + 1 if is_err else 0
        if s.repeats and self._repeat_count >= s.repeats:
            self._trip("repeats", f"the same {name} call {self._repeat_count} times in a row",
                       "That call keeps giving the same answer. Try something different, or finish.")
        if s.errors and self._errors >= s.errors:
            self._trip("errors", f"{self._errors} tool errors in a row",
                       "Read the last error carefully and change approach instead of retrying.")
        if s.max_output_chars and len(out) > s.max_output_chars:
            self._trip("output", f"a {name} result of {len(out):,} characters, over the {s.max_output_chars:,} limit",
                       "Ask for less: a line range, a search, or output piped through head or tail.")
            out = out[: s.max_output_chars] + f"\n... [cut by Roundtable: {len(out) - s.max_output_chars:,} more characters]"
        self._check_progress()
        return out

    # -- what to do -------------------------------------------------------------------------
    def end_step(self) -> str | None:
        """Close the step: go one level up if anything tripped. Returns ``"steer"``, ``"refuse"``,
        ``"stop"`` or None; a ``"refuse"`` arms the refusal of the next batch of tool calls."""
        trip, self._pending = self._pending, None
        if trip is None:
            return None
        self.level = min(self.level + 1, 3)
        action = LEVELS[self.level]
        self._refusing = self._refusing or action == "refuse"
        self.trips.append({"action": action, "signal": trip.signal, "reason": trip.reason, "hint": trip.hint})
        return action

    def note(self, action: str) -> str:
        """The message for the model after ``action``."""
        trip = self.trips[-1]
        hint = trip["hint"]
        if action == "steer":
            return f"Roundtable's safety check: {trip['reason']}. {hint}"
        if action == "refuse":
            return (f"Roundtable's safety check, second warning: {trip['reason']}. Your next tool calls will be "
                    f"refused (all but the one that finishes). {hint} Next time the task is stopped.")
        return f"Roundtable stopped this task: {trip['reason']}."

    def refusal(self) -> str:
        return (f"Refused by Roundtable's safety check ({self.reason}). Think about what went wrong, "
                "then carry on differently or finish the task.")

    # -- inside -----------------------------------------------------------------------------
    def _trip(self, signal: str, reason: str, hint: str) -> None:
        if self._pending is None:
            self._pending = Trip(signal, reason, hint)
            # the same evidence never trips twice: the count starts again
            if signal == "repeats":
                self._repeat_count = 0
            elif signal == "errors":
                self._errors = 0
            elif signal == "no_progress":
                self._last_progress = self.clock()

    def _check_progress(self) -> None:
        mins = self.settings.no_progress_minutes
        if mins and self.clock() - self._last_progress >= mins * 60:
            self._trip("no_progress", f"{mins:g} minutes without changing a file or trying anything new",
                       "Change a file towards the goal, or finish the task and say what blocks it.")


def call_key(name: str, args: Any) -> str:
    """One tool call as a short key: its name and a hash of its arguments, each long string capped
    (after Munder Difflin's ``toolKey``: a hash, not a prefix, so calls sharing a long start differ)."""
    def cap(v: Any) -> Any:
        if isinstance(v, str):
            return v[:4096]
        if isinstance(v, dict):
            return {k: cap(x) for k, x in v.items()}
        if isinstance(v, list):
            return [cap(x) for x in v]
        return v
    try:
        body = json.dumps(cap(args), sort_keys=True, default=str)
    except (TypeError, ValueError):
        body = str(args)
    return f"{name}:{hashlib.sha256(body.encode('utf-8', 'replace')).hexdigest()[:24]}"


def work_tokens(usage: Any) -> int:
    """Tokens that count towards the cap: cache reads are left out (re-read on every call)."""
    return int(usage.input_tokens + usage.output_tokens + usage.cache_write_tokens)
