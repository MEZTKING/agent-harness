"""Project runner: plan -> route tasks to roles -> review -> retry / fall back.

State lives in ``<project>/.harness/`` so a run can stop (budget, approval,
failure, Ctrl-C) and resume exactly where it left off:

    project.json   goal(s), status, spend
    tasks.json     the task board
    events.jsonl   everything that happened (human-readable audit log)
    metrics.jsonl  one row per task attempt: role, model, outcome, cost, tokens
                   -> input for the Phase 3 self-improvement loop
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..core.models import utcnow
from ..providers.base import ImageProvider, ProviderError
from .agent import AgentResult, Budget, BudgetExceeded, run_agent
from .config import HarnessConfig, ModelRef, RoleSpec
from ..providers.base import ToolSpec
from .tools import READ_ONLY, REVIEW_TOOLS, Tool, Toolbox, Workspace, _obj

TASK_STATES = ("pending", "running", "done", "failed", "skipped")
MAX_DIFF = 20_000


@dataclass
class Task:
    id: str
    title: str
    role: str
    description: str
    acceptance: str = ""
    depends_on: list[str] = field(default_factory=list)
    output_path: str = ""
    image_options: dict[str, Any] = field(default_factory=dict)  # per-task style/size for image roles
    status: str = "pending"
    summary: str = ""
    attempts: list[dict[str, Any]] = field(default_factory=list)
    goal_index: int = 0
    base_commit: str | None = None  # project state the task started from (for replays)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Task":
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in known})


class HarnessError(RuntimeError):
    pass


class Project:
    """Persistent state of one project directory."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.dir = self.root / ".harness"

    @property
    def exists(self) -> bool:
        return (self.dir / "project.json").is_file()

    def _read(self, name: str, default):
        p = self.dir / name
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default

    def _write(self, name: str, data) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / f".{name}.tmp"
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.dir / name)

    def meta(self) -> dict[str, Any]:
        return self._read("project.json", {})

    def save_meta(self, meta: dict[str, Any]) -> None:
        self._write("project.json", meta)

    def tasks(self) -> list[Task]:
        return [Task.from_dict(t) for t in self._read("tasks.json", [])]

    def save_tasks(self, tasks: list[Task]) -> None:
        self._write("tasks.json", [asdict(t) for t in tasks])

    def append(self, name: str, row: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / name, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _validate_plan(raw_tasks: Any, roles: dict[str, RoleSpec], existing: list[Task]) -> list[Task]:
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise ValueError("tasks must be a non-empty list")
    known = {t.id for t in existing}
    new: list[Task] = []
    for i, t in enumerate(raw_tasks):
        if not isinstance(t, dict):
            raise ValueError(f"task #{i} is not an object")
        tid = str(t.get("id") or "").strip()
        if not tid:
            raise ValueError(f"task #{i} has no id")
        if tid in known:
            raise ValueError(f"duplicate task id {tid!r}")
        if t.get("role") not in roles:
            raise ValueError(f"task {tid}: unknown role {t.get('role')!r}; available: {sorted(roles)}")
        known.add(tid)
        new.append(
            Task(
                id=tid,
                title=str(t.get("title") or tid),
                role=t["role"],
                description=str(t.get("description") or ""),
                acceptance=str(t.get("acceptance") or ""),
                depends_on=[str(d) for d in t.get("depends_on") or []],
                output_path=str(t.get("output_path") or ""),
                image_options=dict(t.get("image_options") or {}),
            )
        )
    for t in new:
        for d in t.depends_on:
            if d not in known:
                raise ValueError(f"task {t.id} depends on unknown task {d!r}")
    # cycle check
    graph = {t.id: t.depends_on for t in existing + new}
    state: dict[str, int] = {}

    def visit(n: str) -> None:
        if state.get(n) == 1:
            raise ValueError(f"dependency cycle involving {n!r}")
        if state.get(n) == 2:
            return
        state[n] = 1
        for d in graph.get(n, []):
            visit(d)
        state[n] = 2

    for n in graph:
        visit(n)
    return new


class Orchestrator:
    def __init__(
        self,
        cfg: HarnessConfig,
        project_dir: str | Path,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ):
        self.cfg = cfg
        self.project = Project(project_dir)
        self.ws = Workspace(self.project.root, allow_shell=cfg.allow_shell, command_timeout=cfg.limits.command_timeout)
        self._listener = on_event
        meta = self.project.meta()
        self.budget = Budget(limit_usd=cfg.limits.max_cost_usd, spent_usd=meta.get("spent_usd", 0.0))
        # every charge (plans, tasks, reviews, reports, images) is logged, so "spent today" is exact
        self.budget.on_charge = lambda cost: self.project.append(
            "spend.jsonl", {"at": utcnow(), "cost_usd": round(cost, 6)})

    # -- logging -------------------------------------------------------------
    def emit(self, kind: str, data: dict[str, Any]) -> None:
        row = {"at": utcnow(), "event": kind, **data}
        self.project.append("events.jsonl", row)
        if self._listener:
            self._listener(kind, data)

    def _save_spend(self) -> None:
        meta = self.project.meta()
        meta["spent_usd"] = round(self.budget.spent_usd, 6)
        meta["unpriced_calls"] = self.budget.unpriced_calls
        self.project.save_meta(meta)

    def _set_status(self, status: str, **extra: Any) -> None:
        meta = self.project.meta()
        meta.update(status=status, updated_at=utcnow(), **extra)
        self.project.save_meta(meta)
        self.emit("status", {"status": status, **extra})

    # -- git -------------------------------------------------------------------
    def _git(self, *args: str, check: bool = True) -> str:
        res = subprocess.run(
            ["git", "-c", "user.name=agent-harness", "-c", "user.email=harness@localhost",
             "-c", "commit.gpgsign=false", *args],
            cwd=self.project.root, capture_output=True, text=True,
        )
        if check and res.returncode != 0:
            raise HarnessError(f"git {' '.join(args)}: {res.stderr.strip()}")
        return res.stdout

    def _git_init(self) -> None:
        if not self.cfg.git:
            return
        if not (self.project.root / ".git").exists():
            self._git("init", "-q")
        gi = self.project.root / ".gitignore"
        lines = gi.read_text().splitlines() if gi.exists() else []
        if ".harness/" not in lines:
            gi.write_text("\n".join(lines + [".harness/"]) + "\n")

    def _git_commit(self, message: str) -> None:
        if not self.cfg.git:
            return
        self._git("add", "-A")
        if self._git("status", "--porcelain").strip():
            self._git("commit", "-q", "-m", message)

    def _head(self) -> str | None:
        if not self.cfg.git or not (self.project.root / ".git").exists():
            return None
        res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.project.root, capture_output=True, text=True)
        return res.stdout.strip() if res.returncode == 0 else None

    def _diff(self) -> str:
        if not self.cfg.git or not (self.project.root / ".git").exists():
            return "(git disabled - inspect files directly)"
        self._git("add", "-A", check=False)
        has_head = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=self.project.root,
                                  capture_output=True).returncode == 0
        diff = self._git("diff", "--cached", *(["HEAD"] if has_head else []), check=False)
        self._git("reset", "-q", check=False)
        if len(diff) > MAX_DIFF:
            diff = diff[:MAX_DIFF] + f"\n... [diff truncated, {len(diff) - MAX_DIFF} more chars - read files directly]"
        return diff or "(no changes)"

    # -- hub -------------------------------------------------------------------
    _hub_cache: Any = None

    def _hub(self):
        if not self.cfg.hub:
            return None
        if self._hub_cache is None:
            from ..core.config import load_config as load_hub_config
            from ..hub.service import Hub

            self._hub_cache = Hub(load_hub_config(self.cfg.hub.get("config")))
        return self._hub_cache

    def _hub_update(self, status: str, note: str | None = None) -> None:
        try:
            hub = self._hub()
            if hub:
                hub.update_card(self.cfg.hub["agent"], change_note=note, status=status)
        except Exception as e:  # the hub is optional; never fail a run over it
            self.emit("hub_error", {"error": str(e)})

    # journal: the project's history in the hub ("where was I")
    def _journal(self, kind: str, text: str, **kw: Any) -> str | None:
        try:
            hub = self._hub()
            if not hub:
                return None
            return hub.journal.add(self.cfg.hub["agent"], kind, f"{self.project.root.name}: {text}",
                                   source="harness", **kw)["id"]
        except Exception as e:
            self.emit("hub_error", {"error": str(e)})
            return None

    def _journal_close(self, entry_id: str | None, note: str = "") -> None:
        if not entry_id:
            return
        try:
            hub = self._hub()
            if hub:
                hub.journal.close(self.cfg.hub["agent"], entry_id, note=note)
        except Exception as e:
            self.emit("hub_error", {"error": str(e)})

    def _attention(self, key: str, text: str) -> None:
        """Open a high-priority todo for the owner once per issue (no duplicates across reruns)."""
        meta = self.project.meta()
        open_ = meta.setdefault("journal_todos", {})
        if key in open_:
            return
        entry = self._journal("todo", text, priority="high")
        if entry:
            open_[key] = entry
            self.project.save_meta(meta)

    def _resolved(self, *keys: str, note: str = "") -> None:
        meta = self.project.meta()
        open_ = meta.get("journal_todos", {})
        changed = False
        for k in keys:
            if k in open_:
                self._journal_close(open_.pop(k), note)
                changed = True
        if changed:
            self.project.save_meta(meta)

    # -- context ---------------------------------------------------------------
    def _roles_text(self) -> str:
        lines = []
        for r in self.cfg.roles.values():
            if r.name == self.cfg.planner_role or r.name == self.cfg.reviewer_role:
                continue
            kind = (" (image generation: description = the visual prompt; set output_path, and image_options "
                    "for style/size when the role description lists choices)") if r.kind == "image" else ""
            lines.append(f"- {r.name}{kind}: {r.description or 'general work'}")
        return "\n".join(lines)

    def _project_context(self, tasks: list[Task], upto: Task | None = None) -> str:
        meta = self.project.meta()
        goals = "\n".join(f"{i + 1}. {g}" for i, g in enumerate(meta.get("goals", [])))
        done = [f"- [{t.id}] {t.title} ({t.role}): {t.summary}" for t in tasks if t.status == "done"]
        board = "\n".join(f"- [{t.id}] {t.status:8} {t.title} ({t.role})" for t in tasks)
        parts = [f"# Project goals\n{goals}", f"# Task board\n{board}"]
        if done:
            parts.append("# Completed work\n" + "\n".join(done))
        guidance = self._guidance_text()
        if guidance:
            parts.append(guidance)
        parts.append(f"# Files\n{self.ws.tree()}")
        return "\n\n".join(parts)

    # -- owner steering & chat ----------------------------------------------------
    def _guidance_text(self) -> str:
        notes = self.project.meta().get("guidance", [])
        if not notes:
            return ""
        lines = "\n".join(f"- {g['text']}" for g in notes)
        return ("# Owner's instructions (from the project owner; follow them; later ones win on conflict)\n"
                + lines)

    def steer(self, text: str) -> dict[str, Any]:
        """Record an instruction from the owner; every later plan, task and review sees it."""
        text = (text or "").strip()
        if not text:
            raise HarnessError("empty instruction")
        meta = self.project.meta()
        meta.setdefault("guidance", []).append({"at": utcnow(), "text": text[:2000]})
        self.project.save_meta(meta)
        remaining = [t.id for t in self.project.tasks() if t.status in ("pending", "running", "failed")]
        reply = ("Noted. This instruction now goes to every remaining task"
                 + (f" ({', '.join(remaining)})" if remaining else "") + " and to future plans and reviews.")
        self.project.append("chat.jsonl", {"at": utcnow(), "who": "owner", "text": text, "steer": True})
        self.project.append("chat.jsonl", {"at": utcnow(), "who": "orchestrator", "text": reply, "steer": True})
        self.emit("steer", {"text": text[:300]})
        return {"reply": reply, "guidance": len(meta["guidance"])}

    def chat_history(self, limit: int = 50) -> list[dict[str, Any]]:
        p = self.project.dir / "chat.jsonl"
        rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.is_file() else []
        return rows[-limit:]

    def ask(self, question: str) -> dict[str, Any]:
        """Ask the project's orchestrator (the planner role) about the project. Read-only."""
        question = (question or "").strip()
        if not question:
            raise HarnessError("empty question")
        tasks = self.project.tasks()
        detail = []
        for t in tasks:
            line = f"[{t.id}] {t.status} {t.title} ({t.role})"
            for a in t.attempts[-3:]:
                line += f"\n    attempt: {a.get('model')} -> {a.get('outcome')}"
                if a.get("review"):
                    line += f"; review: {a['review'][:300]}"
                if a.get("error"):
                    line += f"; error: {a['error'][:200]}"
            detail.append(line)
        ev = self.project.dir / "events.jsonl"
        recent = []
        if ev.is_file():
            for raw in ev.read_text(encoding="utf-8").splitlines()[-40:]:
                try:
                    d = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if d.get("event") in ("task_start", "task_end", "review", "provider_error", "status", "plan"):
                    recent.append(f"{d.get('at', '')[11:19]} {d['event']}: "
                                  + json.dumps({k: v for k, v in d.items() if k not in ('at', 'event')})[:240])
        history = "\n".join(f"{c['who']}: {c['text']}" for c in self.chat_history(10))
        prompt = (f"{self._project_context(tasks)}\n\n# Task details\n" + "\n".join(detail)
                  + (f"\n\n# Recent events\n" + "\n".join(recent) if recent else "")
                  + (f"\n\n# Conversation so far\n{history}" if history else "")
                  + f"\n\n# The owner asks\n{question}\n\nAnswer briefly and concretely. You may read project "
                    "files with your tools. Do not change anything.")
        role = self.cfg.roles[self.cfg.planner_role]
        res = self._run_with_fallback(
            role, "You are the orchestrator of this software project, answering its owner's questions about "
                  "progress, problems and next steps. Be direct and specific; cite task ids.",
            prompt, self.ws.toolbox(READ_ONLY))
        answer = res.text.strip() or "(no answer)"
        self.project.append("chat.jsonl", {"at": utcnow(), "who": "owner", "text": question, "steer": False})
        self.project.append("chat.jsonl", {"at": utcnow(), "who": "orchestrator", "text": answer, "steer": False,
                                           "model": res.model, "cost_usd": round(res.cost_usd, 6)})
        return {"reply": answer, "model": res.model, "cost_usd": res.cost_usd}

    # -- planning --------------------------------------------------------------
    def start(self, goal: str, require_approval: bool = False) -> None:
        if self.project.exists:
            raise HarnessError(f"{self.project.root} already has a project; use `roundtable extend` to add a goal")
        self._git_init()
        self.project.save_meta({
            "goals": [goal], "status": "planning", "created_at": utcnow(),
            "require_approval": require_approval, "plan_approved": not require_approval, "spent_usd": 0.0,
        })
        self.project.save_tasks([])
        self.emit("goal", {"goal": goal})
        self._register_with_lab()

    def _register_with_lab(self) -> None:
        if self.cfg.lab_dir:
            from ..improve.lab import Lab

            Lab(self.cfg.lab_dir).register_project(self.project.root)

    def extend(self, goal: str) -> None:
        if not self.project.exists:
            raise HarnessError("no project here yet; use `roundtable new`")
        meta = self.project.meta()
        meta["goals"].append(goal)
        meta["status"] = "planning"
        meta["plan_approved"] = not meta.get("require_approval", False)
        self.project.save_meta(meta)
        self.emit("goal", {"goal": goal})

    def plan(self) -> list[Task]:
        meta = self.project.meta()
        existing = self.project.tasks()
        goal_index = len(meta["goals"]) - 1
        role = self.cfg.roles[self.cfg.planner_role]
        captured: dict[str, Any] = {}
        roles = self.cfg.roles
        last_error: list[str] = []

        def submit_plan(args: dict) -> str:
            try:
                new = _validate_plan(args.get("tasks"), roles, existing)
            except ValueError as e:
                last_error.append(str(e))
                raise Exception(f"plan rejected: {e}. Fix it and call submit_plan again.")
            captured["tasks"] = new
            captured["notes"] = args.get("notes", "")
            return f"plan accepted with {len(new)} tasks"

        box = self.ws.toolbox(READ_ONLY)
        task_schema = _obj(
            {
                "id": {"type": "string", "description": "short unique id like T1, T2"},
                "title": {"type": "string"},
                "role": {"type": "string", "enum": sorted(r for r in roles if r not in (self.cfg.planner_role,))},
                "description": {"type": "string", "description": "complete, self-contained instructions"},
                "acceptance": {"type": "string", "description": "how to verify it is done (tests to pass, files to exist...)"},
                "depends_on": {"type": "array", "items": {"type": "string"}},
                "output_path": {"type": "string", "description": "for image tasks: where to save the file"},
                "image_options": {
                    "type": "object",
                    "description": "image tasks only: e.g. {style, width, height, remove_bg, tile_x, tile_y}",
                    "properties": {
                        "style": {"type": "string"}, "width": {"type": "integer"}, "height": {"type": "integer"},
                        "remove_bg": {"type": "boolean"}, "tile_x": {"type": "boolean"}, "tile_y": {"type": "boolean"},
                        "seed": {"type": "integer"},
                    },
                    "additionalProperties": False,
                },
            },
            ["id", "title", "role", "description", "acceptance", "depends_on"],
        )
        task_schema["required"] = ["id", "title", "role", "description", "acceptance", "depends_on"]
        box.add(Tool(
            ToolSpec("submit_plan", "Submit the task plan. Call exactly once when the plan is complete.",
                     _obj({"tasks": {"type": "array", "items": task_schema}, "notes": {"type": "string"}}, ["tasks"])),
            submit_plan, terminal=True,  # only counts once validation passes
        ))

        prompt = (
            f"{self._project_context(existing)}\n\n"
            f"# Roles you can assign\n{self._roles_text()}\n\n"
            f"# Your job\nPlan the work for goal #{goal_index + 1}: {meta['goals'][-1]}\n"
            + (f"Existing task ids (don't reuse; you may depend on them): {', '.join(t.id for t in existing)}\n" if existing else "")
            + "Inspect the existing files if useful, then call submit_plan."
        )
        self.emit("planning", {"model": str(role.models[0])})
        result = self._run_with_fallback(
            role, self.cfg.prompt_text(role.prompt), prompt, box, require="submit_plan",
            done=lambda: "tasks" in captured,
        )
        if "tasks" not in captured:
            raise HarnessError(f"planner did not produce a valid plan ({'; '.join(last_error[-1:]) or result.stop})")
        new = captured["tasks"]
        for t in new:
            t.goal_index = goal_index
        self.project.save_tasks(existing + new)
        self.emit("plan", {"tasks": [f"{t.id} [{t.role}] {t.title}" for t in new], "notes": captured.get("notes", "")})
        meta = self.project.meta()
        status = "awaiting_approval" if not meta.get("plan_approved") else "running"
        self._set_status(status)
        self._hub_update("planned", f"new plan: {len(new)} tasks for goal: {meta['goals'][-1][:200]}")
        plan_id = self._journal("plan", f"goal: {meta['goals'][-1][:300]}",
                                details="\n".join(f"[{t.id}] ({t.role}) {t.title}" for t in new))
        if plan_id:
            meta = self.project.meta()
            meta.setdefault("journal_plans", []).append(plan_id)
            self.project.save_meta(meta)
        return new

    def approve(self) -> None:
        meta = self.project.meta()
        meta["plan_approved"] = True
        if meta.get("status") == "awaiting_approval":
            meta["status"] = "running"
        self.project.save_meta(meta)
        self.emit("approved", {})

    # -- execution ---------------------------------------------------------------
    def _run_with_fallback(
        self, role: RoleSpec, system: str, prompt: str, box: Toolbox,
        require: str | None = None, done: Callable[[], bool] | None = None,
    ) -> AgentResult:
        """Run a one-shot role job (planning / summary), trying fallback models on provider errors."""
        last: Exception | None = None
        for ref in role.models:
            try:
                res = run_agent(self.cfg, ref, system, prompt, box, self.budget,
                                max_steps=self.cfg.limits.max_steps_per_task, max_tokens=role.max_tokens,
                                options=role.options, require_terminal=require, on_event=self.emit)
                self._save_spend()
                if done is None or done() or res.stop != "refusal":
                    return res
            except ProviderError as e:
                last = e
                self.emit("provider_error", {"model": str(ref), "error": str(e)})
        raise HarnessError(f"all models for role {role.name!r} failed: {last}")

    def _worker_prompt(self, task: Task, tasks: list[Task], feedback: list[str]) -> str:
        deps = [t for t in tasks if t.id in task.depends_on]
        parts = [
            self._project_context(tasks, task),
            f"# Your task [{task.id}] {task.title}\n{task.description}",
            f"# Acceptance criteria\n{task.acceptance or '(use judgement)'}",
        ]
        if deps:
            parts.append("# Results of tasks this depends on\n" + "\n".join(f"- [{d.id}] {d.summary}" for d in deps))
        if feedback:
            parts.append("# Feedback on your previous attempt(s) - address all of it\n" + "\n\n".join(feedback))
        parts.append("Work in the project files using your tools. When finished, call finish_task with a concise summary "
                     "of what you did and anything the next person must know.")
        return "\n\n".join(parts)

    def _review(self, task: Task, worker_summary: str) -> tuple[bool, str, AgentResult | None]:
        reviewer = self.cfg.roles.get(self.cfg.reviewer_role or "")
        role = self.cfg.roles[task.role]
        if not reviewer or not role.review:
            return True, "(review skipped)", None
        verdict: dict[str, Any] = {}

        def submit_review(args: dict) -> str:
            verdict.update(args)
            return "review recorded"

        box = self.ws.toolbox(REVIEW_TOOLS)
        box.add(Tool(
            ToolSpec("submit_review", "Record your verdict. approved=true only if every acceptance criterion is met.",
                     _obj({"approved": {"type": "boolean"}, "feedback": {"type": "string",
                           "description": "what is wrong and exactly how to fix it (or brief confirmation)"}},
                          ["approved", "feedback"])),
            submit_review, terminal=True,
        ))
        prompt = (
            f"# Task [{task.id}] {task.title}\n{task.description}\n\n"
            f"# Acceptance criteria\n{task.acceptance or '(use judgement)'}\n\n"
            f"# Worker's summary\n{worker_summary}\n\n"
            + (f"{self._guidance_text()}\n\n" if self._guidance_text() else "") +
            f"# Changes since last commit\n```diff\n{self._diff()}\n```\n\n"
            "Verify the work (read files, run tests if relevant), then call submit_review."
        )
        res = self._run_with_fallback(reviewer, self.cfg.prompt_text(reviewer.prompt), prompt, box,
                                      require="submit_review", done=lambda: bool(verdict))
        if not verdict:
            return False, f"reviewer gave no verdict ({res.stop}): {res.text[:500]}", res
        return bool(verdict.get("approved")), str(verdict.get("feedback", "")), res

    def _metric(self, task: Task, ref: ModelRef, outcome: str, res: AgentResult | None, review_cost: float = 0.0) -> None:
        self.project.append("metrics.jsonl", {
            "at": utcnow(), "task": task.id, "role": task.role, "model": str(ref), "outcome": outcome,
            "steps": res.steps if res else 0, "seconds": res.seconds if res else 0,
            "input_tokens": res.usage.input_tokens if res else 0,
            "output_tokens": res.usage.output_tokens if res else 0,
            "cost_usd": round((res.cost_usd if res else 0) + review_cost, 6),
        })

    def _run_image_task(self, task: Task, role: RoleSpec) -> bool:
        rel = task.output_path or f"assets/{task.id.lower()}.png"
        last = None
        for ref in role.models:
            provider = self.cfg.provider(ref.provider)
            if not isinstance(provider, ImageProvider):
                raise HarnessError(f"{ref} is not an image provider")
            t0 = time.monotonic()
            try:
                self.budget.check()
                data, ext, usage = provider.generate(ref.model, task.description,
                                                     {**role.options, **task.image_options})
            except ProviderError as e:
                last = e
                self.emit("provider_error", {"model": str(ref), "error": str(e)})
                self._metric(task, ref, "error", None)
                continue
            cost = self.cfg.cost(ref, usage)
            self.budget.charge(cost)
            self._save_spend()
            if "." not in Path(rel).name:
                rel = f"{rel}.{ext}"
            elif Path(rel).suffix.lower() in (".png", ".gif") and Path(rel).suffix.lower() != f".{ext}":
                rel = str(Path(rel).with_suffix(f".{ext}"))  # e.g. an animation came back as GIF
            path = self.ws.path(rel)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            style = task.image_options.get("style") or role.options.get("style")
            task.summary = f"generated image {rel} with {ref}" + (f" (style {style})" if style else "")
            task.attempts.append({"model": str(ref), "outcome": "approved", "cost_usd": cost})
            self.project.append("metrics.jsonl", {
                "at": utcnow(), "task": task.id, "role": task.role, "model": str(ref), "outcome": "approved",
                "steps": 1, "seconds": round(time.monotonic() - t0, 2), "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens, "cost_usd": cost or 0,
            })
            return True
        task.summary = f"image generation failed: {last}"
        return False

    def _run_task(self, task: Task, tasks: list[Task]) -> bool:
        role = self.cfg.roles.get(task.role)
        if not role:
            raise HarnessError(f"task {task.id}: role {task.role!r} no longer exists in config")
        if role.kind == "image":
            return self._run_image_task(task, role)

        feedback: list[str] = []
        model_idx = 0
        rejections_on_model = 0
        for attempt in range(1, self.cfg.limits.max_attempts_per_task + 1):
            if model_idx >= len(role.models):
                break
            ref = role.models[model_idx]
            self.emit("attempt", {"task": task.id, "attempt": attempt, "model": str(ref)})
            summary: dict[str, Any] = {}

            def finish_task(args: dict) -> str:
                summary["summary"] = args.get("summary", "")
                return "recorded"

            box = self.ws.toolbox(role.tools)
            box.add(Tool(ToolSpec("finish_task", "Call when the task is complete.",
                                  _obj({"summary": {"type": "string"}}, ["summary"])), finish_task, terminal=True))
            try:
                res = run_agent(self.cfg, ref, self.cfg.prompt_text(role.prompt), self._worker_prompt(task, tasks, feedback),
                                box, self.budget, max_steps=self.cfg.limits.max_steps_per_task,
                                max_tokens=role.max_tokens, options=role.options, require_terminal="finish_task",
                                on_event=self.emit)
                self._save_spend()
            except ProviderError as e:
                self.emit("provider_error", {"task": task.id, "model": str(ref), "error": str(e)})
                task.attempts.append({"model": str(ref), "outcome": "error", "error": str(e)})
                self._metric(task, ref, "error", None)
                model_idx += 1
                rejections_on_model = 0
                continue

            if res.stop in ("refusal", "max_steps") and not summary:
                task.attempts.append({"model": str(ref), "outcome": res.stop, "cost_usd": res.cost_usd})
                self._metric(task, ref, res.stop, res)
                feedback.append(f"Previous attempt ended with {res.stop}. Work more efficiently and call finish_task.")
                model_idx += 1
                continue

            worker_summary = summary.get("summary") or res.text or "(no summary)"
            approved, fb, rev = self._review(task, worker_summary)
            review_cost = rev.cost_usd if rev else 0.0
            outcome = "approved" if approved else "rejected"
            task.attempts.append({"model": str(ref), "outcome": outcome, "summary": worker_summary[:1000],
                                  "review": fb[:2000], "cost_usd": round(res.cost_usd + review_cost, 6)})
            self._metric(task, ref, outcome, res, review_cost)
            self.emit("review", {"task": task.id, "approved": approved, "feedback": fb[:500]})
            if approved:
                task.summary = worker_summary
                return True
            feedback.append(f"Attempt {attempt} ({ref}) was rejected by the reviewer:\n{fb}")
            rejections_on_model += 1
            if rejections_on_model >= 2 and model_idx + 1 < len(role.models):
                model_idx += 1  # this model keeps missing; let the fallback try
                rejections_on_model = 0
        task.summary = f"failed after {len(task.attempts)} attempt(s)"
        return False

    def run(self, max_tasks: int | None = None) -> str:
        """Run until done, blocked, out of budget, awaiting approval, or max_tasks executed."""
        if not self.project.exists:
            raise HarnessError("no project here; use `roundtable new`")
        meta = self.project.meta()
        self._register_with_lab()
        try:
            if meta.get("status") == "planning":
                self.plan()
                meta = self.project.meta()
            if not meta.get("plan_approved"):
                self._set_status("awaiting_approval")
                self._attention("approval", f"review the plan, then: roundtable approve {self.project.root} "
                                            f"&& roundtable run {self.project.root}")
                return "awaiting_approval"
            self._resolved("approval", "budget", note="run resumed")
            self._set_status("running")

            executed = 0
            while True:
                tasks = self.project.tasks()
                by_id = {t.id: t for t in tasks}
                for t in tasks:  # resume after a crash mid-task
                    if t.status == "running":
                        t.status = "pending"
                ready = [t for t in tasks if t.status == "pending"
                         and all(by_id[d].status == "done" for d in t.depends_on)]
                if not ready:
                    if any(t.status == "failed" for t in tasks):
                        self._set_status("blocked")
                        for t in tasks:
                            if t.status == "failed":
                                self._attention(f"failed:{t.id}", f"task {t.id} '{t.title}' failed; check "
                                                f"`roundtable status {self.project.root}`, then retry or skip it")
                        return "blocked"
                    if all(t.status == "done" for t in tasks):
                        self._finish(tasks)
                        return "done"
                    self._set_status("blocked")
                    return "blocked"
                if max_tasks is not None and executed >= max_tasks:
                    self._set_status("paused")
                    return "paused"

                task = ready[0]
                task.status = "running"
                if not task.base_commit:
                    self._git_commit("harness: snapshot before task")  # capture any manual edits
                    task.base_commit = self._head() or ""
                self.project.save_tasks(tasks)
                self.emit("task_start", {"task": task.id, "title": task.title, "role": task.role})
                ok = self._run_task(task, tasks)
                task.status = "done" if ok else "failed"
                self.project.save_tasks(tasks)
                self.emit("task_end", {"task": task.id, "status": task.status, "summary": task.summary[:500]})
                if ok:
                    self._git_commit(f"[{task.id}] {task.title}")
                    self._journal("done", f"[{task.id}] {task.title}", details=task.summary[:2000])
                    self._resolved(f"failed:{task.id}", note="task completed")
                executed += 1
        except BudgetExceeded as e:
            tasks = self.project.tasks()
            for t in tasks:
                if t.status == "running":
                    t.status = "pending"
            self.project.save_tasks(tasks)
            self._save_spend()
            self._set_status("paused_budget", reason=str(e))
            self._attention("budget", f"paused at the budget limit ({e}); raise limits.max_cost_usd, then "
                                      f"roundtable run {self.project.root}")
            return "paused_budget"

    def _finish(self, tasks: list[Task]) -> None:
        role = self.cfg.roles[self.cfg.planner_role]
        meta = self.project.meta()
        summary = ""
        try:
            res = self._run_with_fallback(
                role, "You write concise project completion reports.",
                f"{self._project_context(tasks)}\n\nWrite a short report for the project owner: what was built, "
                "how to run/use it, and known limitations or next steps. Plain markdown, no tool calls needed.",
                self.ws.toolbox(READ_ONLY),
            )
            summary = res.text
        except (HarnessError, BudgetExceeded) as e:
            summary = f"(summary unavailable: {e})"
        (self.project.dir / "summary.md").write_text(summary + "\n", encoding="utf-8")
        self._set_status("done")
        self._hub_update("done", f"completed goal: {meta['goals'][-1][:200]}")
        for plan_id in meta.get("journal_plans", []):
            self._journal_close(plan_id, "completed by the harness")
        if meta.get("journal_plans"):
            meta = self.project.meta()
            meta["journal_plans"] = []
            self.project.save_meta(meta)
        first = next((ln.strip("# ").strip() for ln in summary.splitlines() if ln.strip()), "")
        self._journal("session", f"harness finished goal '{meta['goals'][-1][:150]}' ({len(tasks)} tasks, "
                                 f"${self.budget.spent_usd:.2f}). {first[:200]}",
                      next_steps=[f"review the result and report: {self.project.dir / 'summary.md'}",
                                  f"rate tasks: roundtable feedback {self.project.root} TASK --good/--bad"])

    def retry(self, task_id: str) -> None:
        tasks = self.project.tasks()
        for t in tasks:
            if t.id == task_id:
                if t.status not in ("failed", "skipped", "done"):
                    raise HarnessError(f"task {task_id} is {t.status}; only failed/skipped/done tasks can be retried")
                t.status = "pending"
                self.project.save_tasks(tasks)
                self.emit("retry", {"task": task_id})
                return
        raise HarnessError(f"no task {task_id!r}")

    def skip(self, task_id: str) -> None:
        tasks = self.project.tasks()
        for t in tasks:
            if t.id == task_id:
                t.status = "done"
                t.summary = t.summary or "(skipped by owner)"
                self.project.save_tasks(tasks)
                self.emit("skip", {"task": task_id})
                return
        raise HarnessError(f"no task {task_id!r}")
