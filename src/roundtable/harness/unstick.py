"""A stuck task is worked out, not handed to the owner (wave 5, d2-unstick).

When a task fails, a model from another maker reads what was tried and says why, and what to do:

- ``retry_with_advice``: the task goes back to waiting, with the advice in its handover (one more round);
- ``split``: the planner replaces it with smaller tasks (the same words as a task too big for one attempt);
- ``replan_around``: the planner reaches the goal another way; the dropped task's attempts are kept in
  ``.harness/dropped-tasks.jsonl`` (nothing is deleted);
- ``park`` / ``needs_owner``: it is put aside (``task.parked``) and the run carries on with everything that
  doesn't need it.

At the end, the owner gets one card for every task that couldn't be finished (``stuck_ask``), not one card a
task. Each diagnosis happens once per task (``.harness/unstick.json``), at most ``unstick.max_per_run`` a run,
each capped at ``unstick.max_usd_per_task`` and ``unstick.max_steps`` steps with read-only tools. A diagnosis
that can't be had (a provider error, the cap) leaves things as they were: the task's own card.

Whoever picks the work up gets a written handover (``handoff.py``).

Settings (``unstick:`` in harness.yaml): ``enabled`` (true), ``max_per_run`` (4), ``max_usd_per_task`` (0.15),
``max_steps`` (15), ``tasks_per_diagnosis`` (10, for the estimate).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..brand import NAME
from ..core.models import utcnow
from ..providers.base import ProviderError, ToolSpec, Usage
from . import handoff
from .agent import Budget, BudgetExceeded, run_agent
from .config import ModelRef, section
from .makers import maker
from .tools import READ_ONLY, Tool, _obj

ACTIONS = ("retry_with_advice", "split", "replan_around", "park", "needs_owner")
RECORD = Path(".harness") / "unstick.json"
DROPPED = Path(".harness") / "dropped-tasks.jsonl"
DEFAULTS = {"enabled": True, "max_per_run": 4, "max_usd_per_task": 0.15, "max_steps": 15, "tasks_per_diagnosis": 10}
AUTOPILOT_REASON = "only you can drop work or pay for the stronger model"

class _DiagnosisCap(BudgetExceeded):
    """This diagnosis reached its own cap (not the project's limit)."""


@dataclass
class _CappedBudget(Budget):
    """A diagnosis's own small budget: every charge also goes to the project's budget, whose limit still holds."""
    parent: Any = None

    def charge(self, cost: float | None, *, ref: Any = None, usage: Any = None, role: str | None = None) -> None:
        with self._lock:
            if cost is None:
                self.unpriced_calls += 1
            else:
                self.spent_usd += cost
        self.parent.charge(cost, ref=ref, usage=usage, role=role)

    def check(self) -> None:
        self.parent.check()  # the project's own limit: a real stop
        if self.spent_usd >= self.limit_usd:
            raise _DiagnosisCap(f"the diagnosis reached its cap of ${self.limit_usd:.2f}")


def settings(cfg) -> dict[str, Any]:
    out = dict(DEFAULTS)
    out.update({k: v for k, v in section(cfg, "unstick").items() if k in DEFAULTS})
    return out


def _read_record(root) -> dict[str, Any]:
    p = Path(root) / RECORD
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        data = {}
    data.setdefault("tasks", {})
    return data


def _write_record(root, data: dict[str, Any]) -> None:
    p = Path(root) / RECORD
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1), encoding="utf-8")


def diagnoses(root) -> dict[str, dict[str, Any]]:
    """Every task's diagnosis so far: {task id: {at, model, same_maker, cause, action, advice, ...}}."""
    return _read_record(root)["tasks"]


def _cost_of(task) -> float:
    return sum(float(a.get("cost_usd") or 0) for a in (getattr(task, "attempts", None) or []))


def _skipped(task) -> bool:
    return task.status == "done" and str(task.summary or "").startswith("(skipped by owner)")


def dropped(root) -> list[dict[str, Any]]:
    p = Path(root) / DROPPED
    out = []
    try:
        for ln in p.read_text(encoding="utf-8").splitlines() if p.is_file() else []:
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
    except OSError:
        pass
    return out


def wasted(tasks, root=None) -> float:
    """Money spent on work that wasn't finished: failed and skipped tasks, and tasks a re-plan dropped."""
    total = sum(_cost_of(t) for t in tasks if t.status == "failed" or _skipped(t))
    if root is not None:
        ids = {t.id for t in tasks}
        total += sum(float(r.get("cost_usd") or 0) for r in dropped(root) if r.get("task") not in ids)
    return round(total, 4)


def wasted_words(tasks, root=None) -> str:
    """A line for the finished report's prompt: "spent with nothing finished: $X" ("" when nothing was)."""
    x = wasted(tasks, root)
    if x < 0.005:
        return ""
    which = [t.id for t in tasks if (t.status == "failed" or _skipped(t)) and _cost_of(t)]
    if root is not None:
        ids = {t.id for t in tasks}
        which += [str(r.get("task")) for r in dropped(root) if r.get("task") not in ids and r.get("cost_usd")]
    return (f"\n\nAlso say plainly, in one line: spent with nothing finished: ${x:.2f}"
            + (f" (on {', '.join(which[:8])})" if which else "") + ".")


def _depends_on(tasks, ids: set[str]) -> list[Any]:
    """The tasks waiting, directly or not, on any of ``ids``."""
    out, seen = [], set(ids)
    changed = True
    while changed:
        changed = False
        for t in tasks:
            if t.id not in seen and t.status != "done" and any(d in seen for d in t.depends_on):
                seen.add(t.id)
                out.append(t)
                changed = True
    return out


def _sentence(text: str, limit: int = 160) -> str:
    s = " ".join(str(text or "").split())
    first = re.split(r"(?<=[.!?])\s", s, maxsplit=1)[0]
    return (first[:limit - 1] + "…") if len(first) > limit else first


def stuck_ask(orch, tasks) -> dict[str, Any] | None:
    """One card for every task that couldn't be finished, once the rest is built (None: nothing parked)."""
    from ..asks import _ask, _money  # asks imports the orchestrator, which imports this module
    from .plandoc import DEFAULT_TOKENS

    failed = [t for t in tasks if t.status == "failed"]
    if not failed or not any(t.parked for t in failed):
        return None
    record = diagnoses(orch.project.root)
    n, total = len(failed), len(tasks)
    rows = []
    for t in failed:
        d = record.get(t.id) or {}
        rows.append({"id": t.id, "title": t.title, "cause": _sentence(t.parked or d.get("cause") or "it didn't pass"),
                     **({"owner_question": d["owner_question"]} if d.get("owner_question") else {})})
    question = f"{n} of {total} task{'s' * (total != 1)} couldn't be finished. What now?"
    detail = " ".join(f"{r['id']}: {r['cause']}" for r in rows)
    asked = next((r["owner_question"] for r in rows if r.get("owner_question")), "")
    if asked:
        detail = f"It asks: {asked} " + detail
    opts: list[dict[str, Any]] = []
    strong = {t.id: orch.stronger_models(t) for t in failed}
    if any(strong.values()):
        usd = 0.0
        for t in failed:
            ref = (strong[t.id] or orch.cfg.roles[t.role].models)[0] if t.role in orch.cfg.roles else None
            c = orch.cfg.cost(ref, Usage(*DEFAULT_TOKENS["chat"])) if ref else None
            usd += float(c or 0) * 2  # about two tries each
        first = next(v for v in strong.values() if v)[0]
        opts.append({"id": "stronger", "label": "Try them with the stronger model",
                     "description": f"Uses {first} (the Quality setting), about {_money(usd)} more.",
                     "confirm": f"The stronger model costs more: about {_money(usd)} for {n} "
                                f"task{'s' * (n != 1)}. Try them again with it?"})
    else:
        opts.append({"id": "retry", "label": "Try them again",
                     "description": "Each one tries again with what was learned (its handover)."})
    left_out = ", ".join(f"{t.id} “{t.title}”" for t in failed)
    after = _depends_on(tasks, {t.id for t in failed})
    opts.append({"id": "without", "label": "Carry on without them",
                 "description": f"Leaves out: {left_out}." + (
                     f" {len(after)} task{'s' * (len(after) != 1)} that needed them still "
                     f"run{'s' * (len(after) == 1)}." if after else "")})
    opts.append({"id": "stop", "label": "Stop here", "description": "Nothing more is spent. You can carry on later."})
    return _ask("stuck", "stuck", "Stuck", question, opts, recommended=opts[0]["id"], detail=detail,
                other_hint="Tell it what to do, then it tries them again",
                source={"tasks": [t.id for t in failed], "attempts": sum(len(t.attempts) for t in failed)},
                tasks=rows)


def _unpark(orch, ids: list[str]) -> None:
    with orch._lock:
        tasks = orch.project.tasks()
        for t in tasks:
            if t.id in ids:
                t.parked = ""
        orch.project.save_tasks(tasks)


def apply_stuck(orch, ask: dict[str, Any], picked: list[str], other: str) -> dict[str, Any]:
    """The owner's answer to the stuck card (asks.APPLY["stuck"])."""
    from ..asks import _dismiss

    ids = list(ask["source"]["tasks"])
    choice = picked[0] if picked else ("retry" if other else "stop")
    if other:
        orch.steer(f"About the tasks that couldn't be finished ({', '.join(ids)}): {other}")
    if choice == "stop":
        _dismiss(orch, ask)
        return {"reply": "Stopped. Nothing more is spent until you carry on.", "then": None}
    by_id = {t.id: t for t in orch.project.tasks()}
    if choice == "without":
        for tid in ids:
            orch.skip(tid)
        _unpark(orch, ids)
        orch._resolved("stuck", note="carried on without them")
        return {"reply": f"Carrying on without {', '.join(ids)}.", "then": "run"}
    stronger = choice == "stronger"
    for tid in ids:
        t = by_id.get(tid)
        orch.retry(tid, stronger=bool(stronger and t is not None and orch.stronger_models(t)))
    _unpark(orch, ids)
    orch._resolved("stuck", note="trying them again")
    return {"reply": f"Trying {', '.join(ids)} again" + (" with the stronger model." if stronger else "."),
            "then": "run"}


class UnstickStage:
    """The orchestrator's mixin: ``_unstick_task``, ``_unstick_end``, ``_unstick_estimate`` and the handover's
    ``_handoff_worker_part`` and ``_handoff_split``."""

    # -- who diagnoses -----------------------------------------------------------------------------
    def _unstick_diagnoser(self, task) -> tuple[ModelRef, Any, bool] | None:
        """The first model among the reviewer's, critic's and planner's whose maker differs from the one that
        last built the task: (model, its role, same_maker). None: no chat role to ask."""
        built = next((a.get("model") for a in reversed(task.attempts or []) if a.get("model")), None)
        if not built:
            role = self.cfg.roles.get(task.role)
            built = str(role.models[0]) if role and role.models else ""
        theirs = maker(built) if built else ""
        chain: list[tuple[ModelRef, Any]] = []
        for name in (self.cfg.reviewer_role, self.cfg.critic_role, self.cfg.planner_role):
            role = self.cfg.roles.get(name or "")
            if role and role.kind == "chat":
                chain += [(m, role) for m in role.models if m.provider not in self._broke]
        if not chain:
            return None
        for ref, role in chain:
            if maker(ref) != theirs:
                return ref, role, False
        return chain[0][0], chain[0][1], True

    # -- the diagnosis -------------------------------------------------------------------------------
    def _unstick_diagnose(self, task, tasks) -> dict[str, Any] | None:
        """One model works out why the task is stuck. None when it can't (a provider error, its cap)."""
        s = settings(self.cfg)
        pick = self._unstick_diagnoser(task)
        if pick is None:
            return None
        ref, role, same = pick
        root = self.project.root
        got: dict[str, Any] = {}

        def diagnose(args: dict) -> str:
            got.update(args)
            return "recorded"

        box = self.ws.toolbox(READ_ONLY)
        box.add(Tool(ToolSpec(
            "diagnose", "Say why the task is stuck and what to do. Call it once, when you know.",
            _obj({"cause": {"type": "string", "description": "why it didn't pass, in one or two plain sentences"},
                  "action": {"type": "string", "enum": list(ACTIONS)},
                  "advice": {"type": "string", "description": "exactly what whoever carries on should do"},
                  "owner_question": {"type": "string",
                                     "description": "with needs_owner only: the one question only the owner "
                                                    "can answer, in plain words"}},
                 ["cause", "action", "advice"])), diagnose, terminal=True))
        prompt = (
            f"{self._project_context(tasks, task)}\n\n"
            f"# The stuck task [{task.id}] {task.title}\n{task.description}\n\n"
            f"# Its 'done when'\n{task.acceptance or '(use judgement)'}\n\n"
            f"{handoff.text(root, task, 'It did not pass.')}\n\n"
            "# Your job\nThis task didn't pass after every try. Read the files it touched, find out why, and "
            "call diagnose with one action:\n"
            "- retry_with_advice: it can pass with better instructions; give them as advice.\n"
            "- split: it is too much for one task; it should become 2 to 4 smaller ones.\n"
            "- replan_around: the goal can be reached without this task as written; say how in advice.\n"
            "- park: it can't be done now (a missing tool, a service down); the rest can go on without it.\n"
            "- needs_owner: only the owner can decide (a choice about what they want, money, an account); "
            "give owner_question.\n"
            "Prefer the actions that let the build carry on by itself. Don't change any files."
        )
        cap = _CappedBudget(limit_usd=float(s["max_usd_per_task"]), parent=self.budget)
        try:
            res = run_agent(self.cfg, ref, self._with_repo_rules(
                "You work out why a task in a build didn't pass, and what to do about it."), prompt, box, cap,
                max_steps=int(s["max_steps"]), max_tokens=role.max_tokens, options=role.options,
                require_terminal="diagnose", on_event=self.emit, saver=self._saver(), role=role.name)
            cost = res.cost_usd
        except _DiagnosisCap as e:
            self.emit("unstick_error", {"task": task.id, "model": str(ref), "error": str(e)})
            cost = cap.spent_usd
        except ProviderError as e:
            self.emit("unstick_error", {"task": task.id, "model": str(ref), "error": str(e)[:300]})
            cost = cap.spent_usd
        finally:
            self._save_spend()
        if got.get("action") not in ACTIONS or not str(got.get("cause") or "").strip():
            got = {}
        return {"model": str(ref), "same_maker": same, "cost_usd": round(cost or 0, 6), **got}

    # -- the hook after a failed task ------------------------------------------------------------------
    def _unstick_task(self, task, tasks) -> bool:
        """A task failed: work it out. True when it was (retried, split, re-planned or parked)."""
        s = settings(self.cfg)
        if not s["enabled"] or task.status != "failed":
            return False
        root = self.project.root
        record = _read_record(root)
        if task.id in record["tasks"]:
            return False  # once per task
        mark = getattr(self, "_balance_start", None)
        run = getattr(self, "_unstick_run", None)
        if run is None or run[0] is not mark:
            run = self._unstick_run = [mark, 0]
        if run[1] >= int(s["max_per_run"]):
            return False
        if self._hook("_money_gate"):  # past what the owner agreed to: nothing more is spent here
            return False
        run[1] += 1
        d = self._unstick_diagnose(task, tasks)
        if d is None:
            return False
        record = _read_record(root)
        record["tasks"][task.id] = {"at": utcnow(), **{k: d.get(k) for k in (
            "model", "same_maker", "cost_usd", "cause", "action", "advice", "owner_question") if d.get(k) is not None}}
        _write_record(root, record)
        if not d.get("action"):
            return False  # no answer: the task's own card, as before
        cause, advice, action = str(d["cause"]).strip(), str(d.get("advice") or "").strip(), d["action"]
        handoff.write(root, task, cause, advice)
        self.emit("unstick", {"task": task.id, "action": action, "cause": cause[:300], "model": d["model"],
                              "same_maker": d["same_maker"]})
        done = False
        if action == "retry_with_advice":
            done = self._unstick_set(task, status="pending", parked="")
            what = "tried again with advice"
        elif action in ("split", "replan_around"):
            done = self._unstick_replan(task, action, cause, advice)
            what = "split into smaller tasks" if action == "split" else "planned around"
            if not done:
                action = "park"
        if action in ("park", "needs_owner"):
            done = self._unstick_set(task, parked=cause or "it didn't pass")
            what = "put aside; the rest carries on"
        record = _read_record(root)
        record["tasks"][task.id]["outcome"] = action
        _write_record(root, record)
        self._journal("note", f"[{task.id}] didn't pass: {_sentence(cause)} It was {what}.",
                      details=f"Worked out by {d['model']}" + (" (the same maker)" if d["same_maker"] else "")
                              + (f"\nAdvice: {advice[:1000]}" if advice else ""))
        return done

    def _unstick_set(self, task, **fields: Any) -> bool:
        with self._lock:
            tasks = self.project.tasks()
            t = next((x for x in tasks if x.id == task.id), None)
            if t is None:
                return False
            for k, v in fields.items():
                setattr(t, k, v)
                setattr(task, k, v)
            self.project.save_tasks(tasks)
        return True

    def _unstick_replan(self, task, action: str, cause: str, advice: str) -> bool:
        if not self.project.plan_doc() or self._hook("_money_gate"):
            return False
        before = {t.id: t for t in self.project.tasks() if t.status not in ("done", "running")}
        if action == "split":
            words = (f"Task {task.id} '{task.title}' couldn't be finished: {cause} Its partial work is already in "
                     "the files. Replace it with 2 to 4 smaller tasks that finish it, each small enough to do in "
                     "about 30 steps, with clear 'done when' checks. "
                     + (f"Advice: {advice} " if advice else "") + "Keep every other task as it is.")
        else:
            words = (f"Reach the goal without task {task.id} '{task.title}' as written: {advice or cause} Its "
                     "partial work is in the files. Keep every done task, and every other task this doesn't "
                     "affect, as it is.")
        try:
            r = self.revise_plan(words, by="harness")
        except Exception as e:  # noqa: BLE001 - re-planning is a help: the task is put aside instead
            self.emit("unstick_error", {"task": task.id, "error": f"re-plan: {str(e)[:300]}"})
            return False
        p = self.project.root / DROPPED
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            for tid in r.get("removed", []):
                old = before.get(tid)
                if old is None:
                    continue
                f.write(json.dumps({"at": utcnow(), "task": tid, "title": old.title, "role": old.role,
                                    "description": old.description, "why": action, "cause": cause[:500],
                                    "attempts": old.attempts, "cost_usd": round(_cost_of(old), 6)}) + "\n")
        self._handoff_split(task, r.get("added", []))
        self.emit("task_split" if action == "split" else "task_replanned", {"task": task.id, "summary": r["summary"]})
        return True

    # -- the end of a run -----------------------------------------------------------------------------
    def _unstick_end(self, tasks) -> bool:
        """Nothing else can run and some tasks failed: one card for all of them (True), when they were
        worked out; False leaves the per-task cards, as before."""
        failed = [t for t in tasks if t.status == "failed"]
        if not failed or not any(t.parked for t in failed):
            return False
        text = (f"{len(failed)} of {len(tasks)} task{'s' * (len(tasks) != 1)} couldn't be finished: "
                + "; ".join(f"{t.id} {_sentence(t.parked or 'it did not pass', 100)}" for t in failed[:4])
                + (" …" if len(failed) > 4 else ""))
        self._attention("stuck", text, details=f"{NAME} worked out what it could; the rest is built. "
                                               f"Handovers: {self.project.root / handoff.DIR}")
        return True

    # -- the estimate ----------------------------------------------------------------------------------
    def _unstick_estimate(self, tasks) -> dict[str, Any] | None:
        """A small allowance: about one diagnosis for every ten tasks, so the agreed amount already counts it."""
        s = settings(self.cfg)
        chat = [t for t in tasks if t.status not in ("done",)
                and (self.cfg.roles.get(t.role) is not None and self.cfg.roles[t.role].kind == "chat")]
        if not s["enabled"] or not chat:
            return None
        n = min(int(s["max_per_run"]), math.ceil(len(chat) / max(1, int(s["tasks_per_diagnosis"]))))
        pick = self._unstick_diagnoser(chat[0])
        cap = float(s["max_usd_per_task"])
        each = self.cfg.cost(pick[0], Usage(25_000, 2_500)) if pick else None
        each = cap if each is None else min(cap, each)
        return {"id": "unstick", "usd": round(n * each, 4), "minutes": round(n * 1.5, 1),
                "words": f"Working out up to {n} stuck task{'s' * (n != 1)}"}

    # -- the handover -----------------------------------------------------------------------------------
    def _handoff_worker_part(self, task) -> str:
        return handoff.worker_part(self.project.root, task)

    def _handoff_split(self, task, added_ids) -> None:
        """The tasks a split or re-plan made carry on the stuck task's work: they read its handover."""
        root = self.project.root
        if not handoff.read(root, task.id):
            handoff.write(root, task, "It was too big for one attempt, so it was split into smaller tasks.")
        added = set(added_ids or [])
        if not added:
            return
        with self._lock:
            tasks = self.project.tasks()
            for t in tasks:
                if t.id in added and t.id != task.id and not t.handoff_from:
                    t.handoff_from = task.id
            self.project.save_tasks(tasks)
