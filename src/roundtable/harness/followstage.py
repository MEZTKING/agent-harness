"""A follow-up to one task (wave 8, DS-31): ask the builder of a finished task about it, or ask for a change.

``FollowStage.follow_up(task_id, text, mode, confirmed)``:

- the task is building now: today's "Now" steering, unchanged (``steer`` plus ``attachments.steer_now``);
- the task has finished or stopped, ``mode="ask"``: a fresh conversation for that task's model, given its
  handover (handoff.py), the files it changed and its last review, with read-only tools. Priced first (nothing
  is spent until ``confirmed``), charged to the project's budget like any call, so the usage ledger counts it.
  A model the project's "who may see it" list doesn't allow (makers.py) is refused. The answer is kept under
  the task in ``.harness/follow/<task>.jsonl`` (``follow_ups``);
- ``mode="change"``: a small new task that depends on that one, built and reviewed like any other.

A stage is a help: a follow-up that fails says so and changes nothing else.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..core.models import utcnow
from ..providers.base import ProviderError, Usage
from . import handoff
from .agent import run_agent
from .config import ModelRef
from .tools import READ_ONLY

DIR = Path(".harness") / "follow"
ASK_STEPS = 12
OUT_TOKENS_EST = 1500  # a short answer, for the price shown first
SYSTEM = ("You built a task in this software project earlier. Its owner has a question about it. Answer briefly and "
          "concretely, in plain words for someone who isn't a programmer; name the files you mean. You may read the "
          "project's files with your tools. Do not change anything.")


class FollowError(ValueError):
    """A follow-up that can't be done, in the owner's words."""


def _safe(task_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(task_id))[:80] or "task"


def follow_ups(root, task_id: str) -> list[dict[str, Any]]:
    """The questions asked of one task and their answers, oldest first."""
    p = Path(root) / DIR / f"{_safe(task_id)}.jsonl"
    try:
        rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict)]


def _keep(root, task_id: str, row: dict[str, Any]) -> None:
    p = Path(root) / DIR / f"{_safe(task_id)}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


class FollowStage:
    """Mixed into the Orchestrator (the coordinator adds it to the bases)."""

    def _follow_task(self, task_id: str):
        task = next((t for t in self.project.tasks() if t.id == str(task_id or "").strip().upper()), None)
        if task is None:
            raise FollowError("That task isn't in the plan any more. Look at the tasks again.")
        return task

    def _follow_model(self, task) -> ModelRef:
        """The model that last built it (the approved attempt first), else its role's first model."""
        tried = [a.get("model") for a in reversed(task.attempts) if a.get("outcome") == "approved"] + \
                [a.get("model") for a in reversed(task.attempts)]
        for m in tried:
            if m and "/" in str(m):
                return ModelRef.parse(str(m))
        role = self.cfg.roles.get(task.role)
        if not role or not role.models:
            raise FollowError("No model is set for that task's job, so there's nobody to ask.")
        return role.models[0]

    def _follow_prompt(self, task, text: str) -> str:
        last_review = next((a.get("review") for a in reversed(task.attempts) if a.get("review")), "")
        parts = [f"# The task\n[{task.id}] {task.title}\n{task.description}",
                 f"# What it ended as\n{task.status}" + (f": {task.summary}" if task.summary else "")]
        hand = handoff.read(self.project.root, task.id)
        if hand:
            parts.append(f"# Its handover\n{hand}")
        changed = handoff.files_changed(self.project.root, task)
        if changed:
            parts.append(f"# The files it changed\n{changed}")
        if last_review:
            parts.append(f"# Its last review\n{str(last_review)[:2000]}")
        parts.append(f"# The owner asks\n{text}")
        return "\n\n".join(parts)

    def follow_estimate(self, task_id: str, text: str) -> dict[str, Any]:
        """What asking would cost about (input read once or twice, a short answer), before anything is spent."""
        task = self._follow_task(task_id)
        ref = self._follow_model(task)
        prompt = self._follow_prompt(task, text)
        tokens_in = (len(prompt) + len(SYSTEM)) // 4 * 2  # the question, and once more after a file is read
        cost = self.cfg.cost(ref, Usage(input_tokens=tokens_in, output_tokens=OUT_TOKENS_EST))
        return {"task": task.id, "model": str(ref), "cost_usd": round(cost, 4) if cost is not None else None}

    def follow_up(self, task_id: str, text: str, mode: str = "ask", confirmed: bool = False) -> dict[str, Any]:
        text = str(text or "").strip()[:2000]
        if not text:
            raise FollowError("Write your question or the change first.")
        task = self._follow_task(task_id)
        if task.status == "running":
            from .. import attachments

            r = self.steer(text)
            attachments.steer_now(self.project.root, text)
            return {"reply": "Sent to the task working now: it reads it at its next step. Later tasks get it too.",
                    "delivered": "steer", "guidance": r.get("guidance")}
        if mode == "change":
            return self._follow_change(task, text)
        if mode != "ask":
            raise FollowError("Say ask (a question) or change (a small new task).")
        if task.status not in ("done", "failed"):
            raise FollowError("That task hasn't been built yet, so there's nothing to ask it. Ask the planner instead.")
        ref = self._follow_model(task)
        if not self._may_use(ref):
            raise FollowError(f"This project's “who may see it” list doesn't allow {ref.provider}, the maker that "
                              "built this task. Allow it in the project's settings, or ask the planner instead.")
        est = self.follow_estimate(task.id, text)
        if not confirmed:
            price = f"about ${est['cost_usd']:.2f}" if est["cost_usd"] is not None else "a little (its price isn't known)"
            return {"confirm": f"Asking the model that built {task.id} costs {price}. Ask it?", "estimate": est}
        box = self.ws.toolbox(READ_ONLY)
        role = self.cfg.roles.get(task.role)
        try:
            res = run_agent(self.cfg, ref, self._system(SYSTEM, ""), self._follow_prompt(task, text), box, self.budget,
                            max_steps=ASK_STEPS, max_tokens=getattr(role, "max_tokens", 16000) if role else 16000,
                            options=getattr(role, "options", None) if role else None, on_event=self.emit,
                            role=task.role, project_root=self.project.root)
        except ProviderError as e:
            raise FollowError(f"The model didn't answer ({e}). Try again in a moment.") from None
        self._save_spend()
        answer = res.text.strip() or "(no answer)"
        row = {"at": utcnow(), "task": task.id, "question": text, "answer": answer, "model": res.model,
               "cost_usd": round(res.cost_usd, 6)}
        _keep(self.project.root, task.id, row)
        self.emit("follow_up", {"task": task.id, "model": res.model, "cost": res.cost_usd})
        return {"reply": answer, "model": res.model, "cost_usd": res.cost_usd, "delivered": "ask"}

    def _follow_change(self, task, text: str) -> dict[str, Any]:
        from .orchestrator import HarnessError

        raw = [{"id": f"F{task.id}", "title": f"Change to {task.id}: {text[:60]}", "role": task.role,
                "description": f"A change the owner asked for to task {task.id} “{task.title}”: {text}",
                "acceptance": "The owner's change is made and nothing else in the task breaks.",
                "depends_on": [task.id]}]
        existing = {t.id for t in self.project.tasks()}
        n = 1
        while raw[0]["id"] in existing:
            n += 1
            raw[0]["id"] = f"F{task.id}-{n}"
        try:
            new = self.add_tasks(raw, by="owner", why=f"follow-up to {task.id}: {text}", fix_of=task.id)
        except HarnessError as e:
            raise FollowError(str(e)) from None
        _keep(self.project.root, task.id, {"at": utcnow(), "task": task.id, "question": text, "change": new[0].id})
        meta = self.project.meta()
        if meta.get("status") == "done":  # a finished project picks the new task up on its next run
            meta["status"] = "paused"
            self.project.save_meta(meta)
        return {"reply": f"Added {new[0].id}: it is built and checked like any task. Use /run (or Build) to start it.",
                "task": new[0].id, "delivered": "change"}


__all__ = ["FollowStage", "FollowError", "follow_ups"]
