"""Project runner: plan -> route tasks to roles -> review -> retry / fall back.

State lives in ``<project>/.harness/`` so a run can stop (budget, approval,
failure, Ctrl-C) and resume exactly where it left off:

    project.json   goal(s), status, spend
    tasks.json     the task board
    events.jsonl   everything that happened (human-readable audit log)
    metrics.jsonl  one row per task attempt: role, model, outcome, cost, tokens,
                   saved_tokens_est -> input for the Phase 3 self-improvement loop
    spill/         originals of tool results the token saver slimmed (saver.py)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..core.models import utcnow
from ..providers.base import ImageProvider, ProviderError
from .agent import AgentResult, Budget, BudgetExceeded, OutOfCredit, run_agent
from . import plandoc
from .lookstage import LookStage
from .refstage import ReferenceStage, new_reference
from .saver import TokenSaver
from .showstage import ShowStage
from ..plugins.host import begin_run as plugins_begin_run, notify as plugins_notify
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
    section: str = ""  # the plan's spec section (or decision) this task belongs to
    stronger: bool = False  # the owner asked to retry it with the Quality setting's model

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

    def plan_doc(self) -> dict[str, Any] | None:
        return self._read("plan.json", None)

    def save_plan_doc(self, doc: dict[str, Any], tasks: list[Task] | None = None) -> None:
        self._write("plan.json", doc)
        goal_tasks = [t for t in (tasks if tasks is not None else self.tasks()) if t.goal_index == doc.get("goal_index", 0)]
        (self.dir / "plan.md").write_text(plandoc.render_markdown(doc, goal_tasks) + "\n", encoding="utf-8")

    def append(self, name: str, row: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / name, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def saved_tokens_est(self) -> int:
        """Tokens the token saver kept out of the task conversations so far (an estimate)."""
        p = self.dir / "metrics.jsonl"
        if not p.is_file():
            return 0
        rows = (json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip())
        return sum(int(r.get("saved_tokens_est") or 0) for r in rows)


def due_cheap_runs(cfg) -> list[Path]:
    """Lab projects that were approved to start when it's cheaper and whose time has come."""
    from ..remote import project_dirs

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for root in project_dirs(cfg):
        meta = Project(root).meta()
        if meta.get("status") == "waiting_cheap" and (meta.get("start_after") or "") <= now:
            out.append(root)
    return out


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
                section=str(t.get("section") or ""),
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


class Orchestrator(LookStage, ReferenceStage, ShowStage):
    def __init__(
        self,
        cfg: HarnessConfig,
        project_dir: str | Path,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ):
        self.base_cfg = cfg
        self.project = Project(project_dir)
        self.cfg = cfg.for_profile(self.profile())
        self.ws = Workspace(self.project.root, allow_shell=cfg.allow_shell, command_timeout=cfg.limits.command_timeout)
        self._listener = on_event
        meta = self.project.meta()
        # the owner can let one project spend more than the limit ("Carry on with $X more")
        limit = cfg.limits.max_cost_usd + float(meta.get("budget_extra_usd") or 0)
        self.budget = Budget(limit_usd=limit, spent_usd=meta.get("spent_usd", 0.0))
        # every charge (plans, tasks, reviews, reports, images) is logged, so "spent today" is exact
        self.budget.on_charge = self._on_charge
        self._broke: set[str] = set()  # providers that said "out of credit" during this run
        self._last_real_check = 0.0
        self._mcp = None  # the MCP servers' clients for this run (mcp_tools.MCPPool), started on first use
        self.mcp_allowed = True  # off for the lab's replays: they must not drive the owner's open editor

    # -- MCP servers -----------------------------------------------------------
    def _add_mcp_tools(self, box: Toolbox, role: RoleSpec) -> None:
        """The tools of the MCP servers this role lists under `mcp` (none for a role without it)."""
        if not role.mcp or not self.cfg.mcp_servers or not self.mcp_allowed:
            return
        if self._mcp is None:
            from .mcp_tools import MCPPool

            self._mcp = MCPPool(self.cfg.mcp_servers, self.emit)
        for tool in self._mcp.tools_for(role.mcp):
            if tool.spec.name not in box.tools:
                box.add(tool)

    def _close_mcp(self) -> None:
        pool, self._mcp = self._mcp, None
        if pool is not None:
            pool.close()

    # -- logging -------------------------------------------------------------
    def emit(self, kind: str, data: dict[str, Any]) -> None:
        row = {"at": utcnow(), "event": kind, **data}
        self.project.append("events.jsonl", row)
        plugins_notify(self.cfg, kind, data, self.project.root, self.emit)
        if self._listener:
            self._listener(kind, data)

    def _save_spend(self) -> None:
        meta = self.project.meta()
        meta["spent_usd"] = round(self.budget.spent_usd, 6)
        meta["unpriced_calls"] = self.budget.unpriced_calls
        self.project.save_meta(meta)

    def _set_status(self, status: str, **extra: Any) -> None:
        meta = self.project.meta()
        if not status.startswith("paused"):
            meta.pop("pause", None)  # why it last paused: only while it is paused
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
        lines = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
        if ".harness/" not in lines:
            gi.write_text("\n".join(lines + [".harness/"]) + "\n", encoding="utf-8")

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

    def _hub_agent(self) -> str:
        """The project's own hub project if there is one with its folder name, else the shared harness agent."""
        hub = self._hub()
        name = self.project.root.name
        if hub and name in hub.config.agents:
            return name
        return self.cfg.hub["agent"]

    def _publish_plan(self) -> None:
        """Put the readable plan in the hub (plans/<project>.md), so the phone and other sessions see it."""
        try:
            hub = self._hub()
            doc = self.project.plan_doc()
            if not hub or not doc:
                return
            from ..core.store import BinaryFile, TextFile

            name = self._hub_name()
            meta = self.project.meta()
            state = ("approved, building" if meta.get("plan_approved") and meta.get("status") != "done"
                     else "done" if meta.get("status") == "done" else "waiting for the owner")
            gi = doc.get("goal_index", 0)
            md = (f"_Plan status: {state} · {plandoc.summary_line(doc)} · updated {utcnow()} by Roundtable Hold_\n\n"
                  + plandoc.render_markdown(doc, [t for t in self.project.tasks() if t.goal_index == gi],
                                            image_base=f"looks/{name}/"))
            files: dict[str, Any] = {f"plans/{name}.md": TextFile(md + "\n"),
                                     f"plans/{name}.asks.json": TextFile(self._asks_json())}
            files.update({f"plans/looks/{name}/{f}": BinaryFile(b) for f, b in self._look_pictures().items()})
            hub.store.write_json(files, f"plan({name}): v{doc.get('version', 1)} {state}")
        except Exception as e:  # the hub is optional; never fail a run over it
            self.emit("hub_error", {"error": str(e)})

    def _asks_json(self) -> str:
        """What waits for the owner, as cards for the phone (Hub mode reads it next to the plan)."""
        from ..asks import open_asks

        try:
            asks = open_asks(self)
        except Exception as e:  # the cards are a help: never fail a publish over them
            self.emit("hub_error", {"error": f"asks: {e}"})
            asks = []
        return json.dumps({"project": self.project.root.name, "at": utcnow(), "asks": asks}, indent=1,
                          ensure_ascii=False) + "\n"

    def _hub_update(self, status: str, note: str | None = None) -> None:
        try:
            hub = self._hub()
            if hub:
                hub.update_card(self._hub_agent(), change_note=note, status=status)
        except Exception as e:  # the hub is optional; never fail a run over it
            self.emit("hub_error", {"error": str(e)})

    # journal: the project's history in the hub ("where was I")
    def _journal(self, kind: str, text: str, **kw: Any) -> str | None:
        try:
            hub = self._hub()
            if not hub:
                return None
            agent = self._hub_agent()
            prefix = "" if agent == self.project.root.name else f"{self.project.root.name}: "
            return hub.journal.add(agent, kind, f"{prefix}{text}", source="harness", **kw)["id"]
        except Exception as e:
            self.emit("hub_error", {"error": str(e)})
            return None

    def _journal_close(self, entry_id: str | None, note: str = "") -> None:
        if not entry_id:
            return
        try:
            hub = self._hub()
            if hub:
                hub.journal.close(self._hub_agent(), entry_id, note=note)
        except Exception as e:
            self.emit("hub_error", {"error": str(e)})

    def _attention(self, key: str, text: str, details: str = "") -> None:
        """Open a high-priority todo for the owner once per issue (no duplicates across reruns).

        ``text`` is what the owner reads (the app, the phone): a plain sentence, no file paths or commands;
        those go in ``details``."""
        meta = self.project.meta()
        open_ = meta.setdefault("journal_todos", {})
        if key in open_:
            return
        entry = self._journal("todo", text, priority="high", **({"details": details} if details else {}))
        if entry:
            open_[key] = entry
            self.project.save_meta(meta)
        self._publish_plan()  # the phone's cards (plans/<project>.asks.json) show it too

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
            if r.name in self._not_for_tasks() or r.name == self.cfg.reviewer_role:
                continue
            kind = (" (image generation: description = the visual prompt; set output_path, and image_options "
                    "for style/size when the role description lists choices)") if r.kind == "image" else ""
            lines.append(f"- {r.name}{kind}: {r.description or 'general work'}")
        return "\n".join(lines)

    def _not_for_tasks(self) -> set[str]:
        """Roles that plan, critique or design looks: never given a task."""
        return {r for r in (self.cfg.planner_role, self.cfg.critic_role, self.cfg.design_role, self.cfg.scout_role) if r}

    def _project_context(self, tasks: list[Task], upto: Task | None = None) -> str:
        meta = self.project.meta()
        goals = "\n".join(f"{i + 1}. {g}" for i, g in enumerate(meta.get("goals", [])))
        done = [f"- [{t.id}] {t.title} ({t.role}): {t.summary}" for t in tasks if t.status == "done"]
        board = "\n".join(f"- [{t.id}] {t.status:8} {t.title} ({t.role})" for t in tasks)
        parts = [f"# Project goals\n{goals}"]
        plan_text = plandoc.context_text(self.project.plan_doc())
        if plan_text:
            parts.append(plan_text)
        design = self._design_context()
        if design:
            parts.append(design)
        parts.append(f"# Task board\n{board}")
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
    def start(self, goal: str, require_approval: bool = False, references: list[str] | None = None) -> None:
        """A new project. ``references``: links, GitHub repositories or descriptions to make it like."""
        if self.project.exists:
            raise HarnessError(f"{self.project.root} already has a project; use `roundtable extend` to add a goal")
        refs: list[dict[str, Any]] = []
        for text in references or []:
            if str(text).strip():
                refs.append(new_reference(text, refs))
        self._git_init()
        self.project.save_meta({
            "goals": [goal], "status": "planning", "created_at": utcnow(),
            "require_approval": require_approval, "plan_approved": not require_approval, "spent_usd": 0.0,
            "references": refs,
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

    def _task_schema(self) -> dict[str, Any]:
        roles = self.cfg.roles
        schema = _obj(
            {
                "id": {"type": "string", "description": "short unique id like T1, T2"},
                "title": {"type": "string"},
                "role": {"type": "string", "enum": sorted(r for r in roles if r not in self._not_for_tasks())},
                "description": {"type": "string", "description": "complete, self-contained instructions"},
                "acceptance": {"type": "string", "description": "how to verify it is done (tests to pass, files to exist...)"},
                "depends_on": {"type": "array", "items": {"type": "string"}},
                "section": {"type": "string", "description": "id of the spec section (or decision) this task belongs to"},
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
        schema["required"] = ["id", "title", "role", "description", "acceptance", "depends_on"]
        return schema

    def _plan_call(self, job: str, reserved: list[Task]) -> tuple[list[Task], dict[str, Any]]:
        """Ask the planner for a plan document + tasks; returns the validated tasks and the raw submission."""
        role = self.cfg.roles[self.cfg.planner_role]
        captured: dict[str, Any] = {}
        roles = self.cfg.roles
        last_error: list[str] = []

        def submit_plan(args: dict) -> str:
            try:
                new = _validate_plan(args.get("tasks"), roles, reserved)
            except ValueError as e:
                last_error.append(str(e))
                raise Exception(f"plan rejected: {e}. Fix it and call submit_plan again.")
            captured["tasks"] = new
            captured["args"] = args
            return f"plan accepted with {len(new)} tasks"

        box = self.ws.toolbox(READ_ONLY)
        box.add(Tool(
            ToolSpec("submit_plan", "Submit the plan: the plan document and its tasks. Call exactly once when complete.",
                     plandoc.submission_schema(self._task_schema())),
            submit_plan, terminal=True,  # only counts once validation passes
        ))
        prompt = f"{self._project_context(self.project.tasks())}\n\n# Roles you can assign\n{self._roles_text()}\n\n{job}"
        self.emit("planning", {"model": str(role.models[0])})
        result = self._run_with_fallback(
            role, self.cfg.prompt_text(role.prompt), prompt, box, require="submit_plan",
            done=lambda: "tasks" in captured,
        )
        if "tasks" not in captured:
            raise HarnessError(f"planner did not produce a valid plan ({'; '.join(last_error[-1:]) or result.stop})")
        return captured["tasks"], captured["args"]

    # -- running when it's cheaper (providers with off-peak prices, e.g. DeepSeek) -------
    def cheap_start_at(self) -> datetime | None:
        """When the run would be cheaper: the next off-peak moment for the models doing the tasks,
        or None when it's already off-peak or none of them has off-peak prices."""
        from .config import DEFAULT_PRICING, next_offpeak

        windows: list[str] = []
        for t in self.project.tasks():
            role = self.cfg.roles.get(t.role)
            if t.status != "pending" or not role:
                continue
            for ref in role.models[:1] + ([self.cfg.roles[self.cfg.reviewer_role].models[0]]
                                          if self.cfg.reviewer_role in self.cfg.roles else []):
                price = self.cfg.pricing.get(str(ref)) or self.cfg.pricing.get(ref.model) or DEFAULT_PRICING.get(ref.model) or {}
                windows += [w for w in price.get("peak_utc", []) if w not in windows]
        if not windows:
            return None
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        at = next_offpeak(windows, now)
        return at if at > now else None

    def start_when_cheap(self) -> str | None:
        """Approve the plan to start at the next off-peak moment; returns that time (UTC, HH:MM) or None."""
        at = self.cheap_start_at()
        meta = self.project.meta()
        meta["start_after"] = at.strftime("%Y-%m-%dT%H:%M:%SZ") if at else None
        self.project.save_meta(meta)
        if at:
            self._set_status("waiting_cheap")
            self.emit("waiting_cheap", {"start_after": meta["start_after"]})
        return at.strftime("%H:%M") if at else None

    # -- profiles: budget / balanced / quality ---------------------------------------
    def profile(self) -> str | None:
        """The project's chosen set of models, else the config's default (None: the roles as written)."""
        chosen = self.project.meta().get("profile") if self.project.exists else None
        return chosen if chosen in self.base_cfg.profiles else self.base_cfg.default_profile

    def set_profile(self, name: str) -> dict[str, Any]:
        if name not in self.base_cfg.profiles:
            raise HarnessError(f"no profile {name!r}; choose from {', '.join(self.base_cfg.profiles) or 'none set up'}")
        meta = self.project.meta()
        meta["profile"] = name
        self.project.save_meta(meta)
        self.cfg = self.base_cfg.for_profile(name)
        doc = self.project.plan_doc()
        if doc:
            doc["profile"] = name
            doc["estimate"] = self._estimate(self.project.tasks())
            doc["estimates"] = self.profile_estimates()
            self.project.save_plan_doc(doc)
            self._publish_plan()
        self.emit("profile", {"profile": name})
        return {"profile": name, "estimates": self.profile_estimates()}

    def profile_estimates(self) -> dict[str, dict[str, Any]]:
        """The plan's estimate under every profile, so the owner sees what each would cost."""
        out, keep = {}, self.cfg
        try:
            for name in self.base_cfg.profiles:
                self.cfg = self.base_cfg.for_profile(name)
                e = self._estimate(self.project.tasks())
                out[name] = {"cost_usd": e.get("cost_usd"), "minutes": e.get("minutes"), "unpriced": e.get("unpriced", [])}
        finally:
            self.cfg = keep
        return out

    def _estimate(self, tasks: list[Task]) -> dict[str, Any]:
        files = [self.project.dir / "metrics.jsonl"]
        if self.cfg.lab_dir:
            try:
                from ..improve.lab import Lab

                files += [p / ".harness" / "metrics.jsonl" for p in Lab(self.cfg.lab_dir).projects()]
            except Exception:  # the estimate must never stop planning
                pass
        seen, uniq = set(), []
        for f in files:
            if f.resolve() not in seen and f.is_file():
                seen.add(f.resolve())
                uniq.append(f)
        return plandoc.estimate(self.cfg, [t for t in tasks if t.status == "pending"], plandoc.history_by_role(uniq))

    def plan(self) -> list[Task]:
        meta = self.project.meta()
        existing = self.project.tasks()
        goal_index = len(meta["goals"]) - 1
        goal = meta["goals"][-1]
        refs = self._scout_pending()
        like = self._references_text()
        job = (
            (f"{like}\n\n" if like else "")
            + f"# Your job\nPlan the work for goal #{goal_index + 1}: {goal}\n"
            + (f"Existing task ids (don't reuse; you may depend on them): {', '.join(t.id for t in existing)}\n" if existing else "")
            + "Inspect the existing files if useful, then call submit_plan with the plan document (summary, scope, "
              "don't-do list, a short spec, the real decisions with your recommendation, questions only you can't "
              "answer, worthwhile ideas), has_ui (true when people will look at its screens) and the tasks, each "
              "linked to its spec section."
        )
        new, args = self._plan_call(job, existing)
        for t in new:
            t.goal_index = goal_index
        tasks = existing + new
        self.project.save_tasks(tasks)
        doc = plandoc.doc_from_submission(args, goal, goal_index)
        doc["references"] = refs
        doc["estimate"] = self._estimate(new)
        if self.base_cfg.profiles:
            doc["estimates"] = self.profile_estimates()
            doc["profile"] = self.profile()
        self.project.save_plan_doc(doc, tasks)
        self.emit("plan", {"tasks": [f"{t.id} [{t.role}] {t.title}" for t in new], "notes": doc["summary"][:500]})
        self._critique()
        self._look_stage()
        doc = self.project.plan_doc() or doc
        new = [t for t in self.project.tasks() if t.goal_index == goal_index]
        meta = self.project.meta()
        status = "awaiting_approval" if not meta.get("plan_approved") else "running"
        self._set_status(status)
        self._publish_plan()
        self._hub_update("planned", f"new plan: {len(new)} tasks for goal: {goal[:200]}")
        plan_id = self._journal("plan", f"goal: {goal[:300]}",
                                details="\n".join(f"[{t.id}] ({t.role}) {t.title}" for t in new))
        if plan_id:
            meta = self.project.meta()
            meta.setdefault("journal_plans", []).append(plan_id)
            self.project.save_meta(meta)
        return new

    def _critique(self) -> dict[str, Any] | None:
        """A second model (ideally another maker's) reviews the plan; a serious problem gets one revision."""
        role = self.cfg.roles.get(self.cfg.critic_role or "")
        doc = self.project.plan_doc()
        if not role or not doc:
            return None
        verdict: dict[str, Any] = {}

        def submit_critique(args: dict) -> str:
            verdict.update(args)
            return "critique recorded"

        box = self.ws.toolbox(READ_ONLY)
        point = {"type": "object", "properties": {
            "severity": {"type": "string", "enum": ["high", "medium", "low"]},
            "text": {"type": "string", "description": "the problem, concretely"},
            "suggestion": {"type": "string"}}, "required": ["severity", "text"]}
        box.add(Tool(ToolSpec("submit_critique", "Record your critique of the plan.",
                              _obj({"verdict": {"type": "string", "enum": ["good", "revise"]},
                                    "points": {"type": "array", "items": point}}, ["verdict", "points"])),
                     submit_critique, terminal=True))
        goal_tasks = [t for t in self.project.tasks() if t.goal_index == doc["goal_index"]]
        prompt = (f"{plandoc.render_markdown(doc, goal_tasks)}\n\n# Task details\n"
                  + "\n".join(f"[{t.id}] ({t.role}) {t.title}: {t.description[:600]} | done when: {t.acceptance[:300]}"
                               + (f" | after {', '.join(t.depends_on)}" if t.depends_on else "") for t in goal_tasks)
                  + "\n\nCritique this plan before any work starts. Look for: missing pieces, wrong order, tasks too big "
                    "or vague to verify, risky or over-engineered choices, choices the owner should make that are "
                    "hidden, and a better recommendation where you'd pick differently. Severity high = the plan "
                    "would fail or waste most of the budget. Be brief; call submit_critique.")
        self.emit("critique_start", {"model": str(role.models[0])})
        try:
            res = self._run_with_fallback(
                role, "You are a senior engineer critiquing another team's project plan. Be specific and fair.",
                prompt, box, require="submit_critique", done=lambda: bool(verdict))
        except HarnessError as e:
            self.emit("critique", {"error": str(e)[:300]})
            return None
        if not verdict:
            return None
        points = [p for p in verdict.get("points") or [] if isinstance(p, dict) and p.get("text")]
        doc = self.project.plan_doc() or doc
        doc["critique"] = {"model": res.model or str(role.models[0]), "verdict": verdict.get("verdict", "good"),
                           "points": points, "at": utcnow(), "version": doc.get("version", 1)}
        self.project.save_plan_doc(doc)
        self.emit("critique", {"verdict": doc["critique"]["verdict"], "points": len(points),
                               "high": sum(p.get("severity") == "high" for p in points)})
        if doc["critique"]["verdict"] == "revise" and any(p.get("severity") == "high" for p in points):
            notes = "\n".join(f"- [{p['severity']}] {p['text']}" + (f" (suggestion: {p['suggestion']})" if p.get("suggestion") else "")
                              for p in points)
            self.revise_plan(f"A second model critiqued the plan. Address the points you agree with, especially the "
                             f"high-severity ones; say in the summary which you didn't take and why:\n{notes}",
                             by="critic", critique_again=False)
        return doc["critique"]

    def revise_plan(self, instruction: str = "", by: str = "owner", critique_again: bool = False) -> dict[str, Any]:
        """Re-plan the current goal with the owner's pending changes (and/or an instruction).

        Done and running tasks stay; the planner returns the full updated document and the tasks still
        to do, keeping unchanged tasks as they were. Returns what changed.
        """
        doc = self.project.plan_doc()
        if not doc:
            raise HarnessError("this project has no plan document yet")
        pending = doc.get("pending", [])
        instruction = (instruction or "").strip()
        if not pending and not instruction:
            raise HarnessError("nothing to change: choose, answer, edit or write what you want changed first")
        if any(r.get("status") == "new" for r in doc.get("references", [])):
            self._scout_pending()  # a reference added since: read it before re-planning
            doc = self.project.plan_doc()
        like = self._references_text()
        meta = self.project.meta()
        gi = doc["goal_index"]
        tasks = self.project.tasks()
        keep = [t for t in tasks if t.goal_index != gi or t.status in ("done", "running")]
        old_open = {t.id: t for t in tasks if t.goal_index == gi and t.status not in ("done", "running")}
        changes = "\n".join(f"- {c['text']}" for c in pending)
        job = (
            f"# Current plan (version {doc.get('version', 1)})\n{plandoc.render_markdown(doc, [t for t in tasks if t.goal_index == gi])}\n\n"
            + (f"{like}\n\n" if like else "")
            + (f"# The owner's changes to apply\n{changes}\n\n" if changes else "")
            + (f"# {'The owner says' if by == 'owner' else 'Also'}\n{instruction}\n\n" if instruction else "")
            + f"# Your job\nRevise the plan for goal #{gi + 1}: {meta['goals'][gi]}\n"
            "Call submit_plan with the complete updated plan document and the complete list of tasks still to do. "
            + (f"Already done or in progress, don't repeat (you may depend on them): {', '.join(t.id for t in keep if t.goal_index == gi)}. " if any(t.goal_index == gi for t in keep) else "")
            + "Keep the same id, role and wording for tasks these changes don't affect. Respect the owner's choices, "
            "answers and don't-do list; drop questions that are now answered and decisions that are now settled "
            "(keep a settled decision only if it's still useful to show)."
        )
        new, args = self._plan_call(job, keep)
        for t in new:
            t.goal_index = gi
            old = old_open.get(t.id)
            if old and old.status == "failed" and (old.description, old.role) == (t.description, t.role):
                t.attempts = old.attempts  # same task: keep its history (it stays to-do)
        new_doc = plandoc.carry_over(plandoc.doc_from_submission(args, meta["goals"][gi], gi), doc)
        added = [t.id for t in new if t.id not in old_open]
        removed = [i for i in old_open if i not in {t.id for t in new}]
        changed = [t.id for t in new if t.id in old_open and (t.title, t.role, t.description, t.acceptance)
                   != (old_open[t.id].title, old_open[t.id].role, old_open[t.id].description, old_open[t.id].acceptance)]
        diff = {"added": added, "removed": removed, "changed": changed,
                "unchanged": len(new) - len(added) - len(changed)}
        summary = (f"Plan v{new_doc['version']}: " + ", ".join(
            f"{len(v)} {k} ({', '.join(v[:8])})" for k, v in (("added", added), ("changed", changed), ("removed", removed)) if v)
            or f"Plan v{new_doc['version']}: tasks unchanged")
        new_doc["history"].append({"at": utcnow(), "version": new_doc["version"], "by": by,
                                   "change": (instruction[:300] or changes[:300]), "diff": diff})
        new_doc["pending"] = []
        all_tasks = keep + new
        self.project.save_tasks(all_tasks)
        new_doc["estimate"] = self._estimate(new)
        if self.base_cfg.profiles:
            new_doc["estimates"] = self.profile_estimates()
            new_doc["profile"] = self.profile()
        self.project.save_plan_doc(new_doc, all_tasks)
        self.emit("plan_revised", {"version": new_doc["version"], "by": by, **diff})
        if by != "critic":  # the first plan publishes after its critique
            self._publish_plan()
        if self._look_changed(new_doc):
            self.apply_look()
        if by == "owner":
            self.project.append("chat.jsonl", {"at": utcnow(), "who": "orchestrator", "text": summary, "steer": False})
        if critique_again:
            self._critique()
        return {"version": new_doc["version"], "summary": summary, **diff}

    PLAN_ACTIONS = ("choose", "answer", "dont_add", "dont_remove", "idea", "section", "scope_add", "scope_remove", "note",
                    "look", "reference_add", "reference_remove")

    def plan_update(self, action: str, **kw: Any) -> dict[str, Any]:
        """The owner edits the plan. Edits wait in `pending` until revise_plan applies them (one model call)."""
        doc = self.project.plan_doc()
        if not doc:
            raise HarnessError("this project has no plan document yet")
        pend = doc.setdefault("pending", [])

        def note(text: str, key: str) -> None:
            pend[:] = [p for p in pend if p.get("key") != key]  # a later edit of the same thing replaces it
            pend.append({"at": utcnow(), "key": key, "text": text})

        def find(items: list[dict[str, Any]], iid: str) -> dict[str, Any]:
            for x in items:
                if x.get("id") == iid:
                    return x
            raise HarnessError(f"no item {iid!r} in the plan")

        if action == "choose":
            d = find(doc["decisions"], kw.get("decision", ""))
            opt = find(d["options"], kw.get("option", ""))
            d["chosen"] = opt["id"]
            note(f"For '{d['question']}' the owner chose: {opt['label']}", f"choose:{d['id']}")
        elif action == "answer":
            q = find(doc["questions"], kw.get("question", ""))
            q["answer"] = str(kw.get("text", "")).strip()[:2000]
            if not q["answer"]:
                raise HarnessError("write an answer, or pick one")
            ids = {o.get("id") for o in q.get("options") or []}
            q["chosen"] = [c for c in kw.get("chosen") or [] if c in ids]  # which ready answers were tapped
            note(f"Answer to '{q['text']}': {q['answer']}", f"answer:{q['id']}")
        elif action == "dont_add":
            text = str(kw.get("text", "")).strip()[:500]
            if not text:
                raise HarnessError("write what not to do")
            iid = f"D{len(doc['dont']) + 1}o{len(doc.get('history', []))}"
            doc["dont"].append({"id": iid, "text": text, "why": "", "by": "owner"})
            note(f"Don't: {text}", f"dont:{iid}")
        elif action == "dont_remove":
            x = find(doc["dont"], kw.get("id", ""))
            doc["dont"].remove(x)
            note(f"The owner removed the rule 'don't {x['text']}': it is allowed again", f"dont:{x['id']}")
        elif action == "idea":
            i = find(doc["ideas"], kw.get("id", ""))
            i["state"] = "accepted" if kw.get("accept") else "rejected"
            if i["state"] == "accepted":
                note(f"The owner wants this idea too: {i['text']}", f"idea:{i['id']}")
            else:  # tell the planner too, or it may suggest the same thing again
                note(f"The owner doesn't want this idea, don't suggest it again: {i['text']}", f"idea:{i['id']}")
        elif action == "section":
            sec = find(doc["spec"], kw.get("id", ""))
            sec["text"] = str(kw.get("text", "")).strip()[:8000]
            note(f"The owner rewrote spec section {sec['id']} '{sec['title']}' to:\n{sec['text']}", f"section:{sec['id']}")
        elif action in ("scope_add", "scope_remove"):
            key = "out_of_scope" if kw.get("out") else "in_scope"
            text = str(kw.get("text", "")).strip()[:500]
            if not text:
                raise HarnessError("write the scope item")
            if action == "scope_add":
                doc[key].append(text)
                note(f"{'Out of' if kw.get('out') else 'In'} scope (owner): {text}", f"{key}:{text[:40]}")
            else:
                if text not in doc[key]:
                    raise HarnessError("no such scope item")
                doc[key].remove(text)
                note(f"No longer {'out of' if kw.get('out') else 'in'} scope: {text}", f"{key}:{text[:40]}")
        elif action == "look":
            self._choose_look(doc, kw, note)
        elif action == "reference_add":
            self._add_reference(doc, kw, note)
        elif action == "reference_remove":
            self._remove_reference(doc, kw, note)
        elif action == "note":
            text = str(kw.get("text", "")).strip()[:2000]
            if not text:
                raise HarnessError("write the change you want")
            note(text, f"note:{len(pend)}:{text[:20]}")
        else:
            raise HarnessError(f"action must be one of {', '.join(self.PLAN_ACTIONS)}, revise or approve")
        self.project.save_plan_doc(doc)
        self.emit("plan_edit", {"action": action, "pending": len(pend)})
        self._publish_plan()
        return {"pending": len(pend), "open": plandoc.open_items(doc)}

    def approve(self) -> None:
        doc = self.project.plan_doc()
        if doc and doc.get("pending"):
            raise HarnessError(f"{len(doc['pending'])} change(s) to the plan aren't applied yet: update the plan first "
                               "(or undo them)")
        meta = self.project.meta()
        meta["plan_approved"] = True
        if meta.get("status") == "awaiting_approval":
            meta["status"] = "running"
        self.project.save_meta(meta)
        self.emit("approved", {})
        self._publish_plan()

    # -- execution ---------------------------------------------------------------
    def _run_with_fallback(
        self, role: RoleSpec, system: str, prompt: str, box: Toolbox,
        require: str | None = None, done: Callable[[], bool] | None = None, max_steps: int | None = None,
    ) -> AgentResult:
        """Run a one-shot role job (planning / summary), trying fallback models on provider errors."""
        last: Exception | None = None
        for ref in role.models:
            try:
                res = run_agent(self.cfg, ref, system, prompt, box, self.budget,
                                max_steps=max_steps or self.cfg.limits.max_steps_per_task, max_tokens=role.max_tokens,
                                options=role.options, require_terminal=require, on_event=self.emit,
                                saver=self._saver(), role=role.name)
                self._save_spend()
                if done is None or done() or res.stop != "refusal":
                    return res
            except ProviderError as e:
                last = e
                self.emit("provider_error", {"model": str(ref), "error": str(e)})
        raise HarnessError(f"all models for role {role.name!r} failed: {last}")

    def _saver(self) -> TokenSaver:
        """A fresh token saver for one conversation; originals spill into .harness/spill."""
        return TokenSaver(self.cfg.token_saver, self.project.root, on_event=self.emit)

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
        parts.append("Work in the project files using your tools. Throwaway scripts you write only to check your work "
                     "go in .harness/scratch/ (never committed or reviewed), or delete them before you finish. When "
                     "finished, call finish_task with a concise summary of what you did and anything the next person "
                     "must know.")
        return "\n\n".join(parts)

    def _review(self, task: Task, worker_summary: str, stronger: bool = False) -> tuple[bool, str, AgentResult | None]:
        reviewer = self.cfg.roles.get(self.cfg.reviewer_role or "")
        role = self.cfg.roles[task.role]
        if not reviewer or not role.review:
            return True, "(review skipped)", None
        if stronger and len(reviewer.models) > 1:
            from dataclasses import replace as _replace

            reviewer = _replace(reviewer, models=reviewer.models[1:] + reviewer.models[:1])
        verdict: dict[str, Any] = {}

        def submit_review(args: dict) -> str:
            verdict.update(args)
            return "review recorded"

        box = self.ws.toolbox(REVIEW_TOOLS)
        self._add_mcp_tools(box, reviewer)
        game = self._game_tool()
        if game is not None:
            box.add(game)
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
            + (f"{self._guidance_text()}\n\n" if self._guidance_text() else "")
            + (f"{plandoc.context_text(self.project.plan_doc())}\n\n" if self.project.plan_doc() else "")
            + "".join(f"{x}\n\n" for x in (self._design_context(), self._design_findings()) if x) +
            f"# Changes since last commit\n```diff\n{self._diff()}\n```\n\n"
            + self._later_tasks_text(task) +
            ("This project is a Godot game: call run_game to start it and see its script errors.\n\n"
               if game is not None else "") +
            "Verify the work (read files, run tests if relevant), then call submit_review. Judge THIS task "
            "against its own acceptance criteria: the plan, the design file and later tasks are context, so don't "
            "reject for work a later task will do, or for small harmless changes the criteria don't forbid."
        )
        res = self._run_with_fallback(reviewer, self.cfg.prompt_text(reviewer.prompt), prompt, box,
                                      require="submit_review", done=lambda: bool(verdict))
        if not verdict:
            return False, f"reviewer gave no verdict ({res.stop}): {res.text[:500]}", res
        return bool(verdict.get("approved")), str(verdict.get("feedback", "")), res

    def _later_tasks_text(self, task: Task) -> str:
        """The tasks still to come, so a reviewer doesn't ask this one to do their work."""
        later = [t for t in self.project.tasks() if t.id != task.id and t.status == "pending"]
        if not later:
            return ""
        return "# Still to come (not this task's job)\n" + "".join(f"- [{t.id}] {t.title}\n" for t in later[:20]) + "\n"

    def _metric(self, task: Task, ref: ModelRef, outcome: str, res: AgentResult | None, review_cost: float = 0.0,
                review_saved: int = 0) -> None:
        self.project.append("metrics.jsonl", {
            "at": utcnow(), "task": task.id, "role": task.role, "model": str(ref), "outcome": outcome,
            "steps": res.steps if res else 0, "seconds": res.seconds if res else 0,
            "input_tokens": res.usage.input_tokens if res else 0,
            "output_tokens": res.usage.output_tokens if res else 0,
            "cost_usd": round((res.cost_usd if res else 0) + review_cost, 6),
            "saved_tokens_est": (res.saved_tokens_est if res else 0) + review_saved,
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
        ran_out_once = False
        models = (self.stronger_models(task) if task.stronger else []) or role.models
        for attempt in range(1, self.cfg.limits.max_attempts_per_task + 1):
            while model_idx < len(models) and models[model_idx].provider in self._broke:
                model_idx += 1  # that account is empty: no point trying it again this run
            if model_idx >= len(models):
                if all(m.provider in self._broke for m in models):
                    raise OutOfCredit("no credit left with " + ", ".join(sorted({m.provider for m in models})))
                break
            ref = models[model_idx]
            self.emit("attempt", {"task": task.id, "attempt": attempt, "model": str(ref)})
            summary: dict[str, Any] = {}

            def finish_task(args: dict) -> str:
                summary["summary"] = args.get("summary", "")
                return "recorded"

            box = self.ws.toolbox(role.tools)
            self._add_mcp_tools(box, role)
            if "write_file" in box.tools or "edit_file" in box.tools or "run_game" in (role.tools or []):
                game = self._game_tool()  # a Godot game: the coder can start it and see its errors
                if game is not None:
                    box.add(game)
            box.add(Tool(ToolSpec("finish_task", "Call when the task is complete.",
                                  _obj({"summary": {"type": "string"}}, ["summary"])), finish_task, terminal=True))
            try:
                res = run_agent(self.cfg, ref, self.cfg.prompt_text(role.prompt), self._worker_prompt(task, tasks, feedback),
                                box, self.budget, max_steps=self.cfg.limits.max_steps_per_task,
                                max_tokens=role.max_tokens, options=role.options, require_terminal="finish_task",
                                on_event=self.emit, saver=self._saver(), role=task.role)
                self._save_spend()
            except ProviderError as e:
                if getattr(e, "out_of_credit", False):
                    self._broke.add(ref.provider)
                self.emit("provider_error", {"task": task.id, "model": str(ref), "error": str(e)})
                task.attempts.append({"model": str(ref), "outcome": "error", "error": str(e)})
                self._metric(task, ref, "error", None)
                model_idx += 1
                rejections_on_model = 0
                continue

            if res.stop in ("refusal", "max_steps") and not summary:
                task.attempts.append({"model": str(ref), "outcome": res.stop, "cost_usd": res.cost_usd})
                self._metric(task, ref, res.stop, res)
                if res.stop == "max_steps" and model_idx + 1 >= len(models) and not ran_out_once:
                    # no fallback model: the files it wrote are still there, so let it carry on once
                    ran_out_once = True
                    feedback.append("Your previous attempt ran out of steps before finishing. Its changes are still "
                                    "in the files: check what's there, finish the rest, and call finish_task.")
                    continue
                feedback.append(f"Previous attempt ended with {res.stop}. Work more efficiently and call finish_task.")
                model_idx += 1
                continue

            worker_summary = summary.get("summary") or res.text or "(no summary)"
            # after a rejection, the next verdict comes from the next (stronger) reviewer model
            approved, fb, rev = self._review(task, worker_summary,
                                             stronger=any(a.get("outcome") == "rejected" for a in task.attempts))
            review_cost = rev.cost_usd if rev else 0.0
            outcome = "approved" if approved else "rejected"
            task.attempts.append({"model": str(ref), "outcome": outcome, "summary": worker_summary[:1000],
                                  "review": fb[:2000], "cost_usd": round(res.cost_usd + review_cost, 6)})
            self._metric(task, ref, outcome, res, review_cost, rev.saved_tokens_est if rev else 0)
            self.emit("review", {"task": task.id, "approved": approved, "feedback": fb[:500]})
            if approved:
                task.summary = worker_summary
                return True
            feedback.append(f"Attempt {attempt} ({ref}) was rejected by the reviewer:\n{fb}")
            rejections_on_model += 1
            if rejections_on_model >= 2 and model_idx + 1 < len(models):
                model_idx += 1  # this model keeps missing; let the fallback try
                rejections_on_model = 0
        task.summary = f"failed after {len(task.attempts)} attempt(s)"
        return False

    def run(self, max_tasks: int | None = None) -> str:
        """Run until done, blocked, out of budget, awaiting approval, or max_tasks executed."""
        plugins_begin_run(self.cfg)
        start = self._note_balance("start")
        self._balance_start = start
        self._last_real_check = time.time()
        try:
            status = self._run(max_tasks)
        finally:
            self._close_mcp()
            if start:
                self._note_balance("end", start)
        if status != "awaiting_approval":
            self._learn_after_run()
        return status

    def _learn_after_run(self) -> None:
        """improve.after_each_run: look at what the runs showed and apply what the policy allows.

        Rules only (no model calls, no replay tests, no probes), so it costs nothing; what changed goes
        into the journal as a decision, so the owner can read later what was switched and why.
        """
        if not self.base_cfg.improve.get("after_each_run") or not self.base_cfg.lab_dir:
            return
        try:
            from ..improve.lab import Lab
            from ..improve.loop import cycle

            lab = Lab(self.base_cfg.lab_dir)
            report = cycle(self.base_cfg.variant(), lab, use_llm=False, test=False, probe=False)
        except Exception as e:  # learning is a bonus; never fail a run over it
            self.emit("learn_failed", {"error": str(e)[:300]})
            return
        for a in report.get("applied", []):
            p = next((x for x in lab.proposals() if x.id == a["id"]), None)
            why = p.rationale if p else ""
            self.emit("improved", {"id": a["id"], "version": a["version"], "summary": a["summary"]})
            self._journal("decision", f"Switched by Roundtable: {a['summary']}. Why: {why}",
                          details=f"undo: roundtable improve rollback {a['version']}")

    REAL_CHECK_SECONDS = 60  # how often a long task looks at the real balance

    def _on_charge(self, cost: float) -> None:
        self.project.append("spend.jsonl", {"at": utcnow(), "cost_usd": round(cost, 6)})
        # the real-money limit is also checked inside a long task, at most once a minute
        limit = self.cfg.limits.max_real_usd_per_run
        self._counted_since_check = getattr(self, "_counted_since_check", 0.0) + cost
        # look at the real balance once a minute, or sooner when a dear model is spending fast
        # (a tenth of the limit counted since the last look)
        if limit and (time.time() - self._last_real_check >= self.REAL_CHECK_SECONDS
                      or self._counted_since_check >= limit * 0.1):
            self._last_real_check, self._counted_since_check = time.time(), 0.0
            if self._real_spend_over_limit():
                raise BudgetExceeded(f"this run reached its real-money limit of "
                                     f"${self.cfg.limits.max_real_usd_per_run:.2f}")

    def _real_spent(self) -> float | None:
        """Real money spent since the run started, from the providers' balances (None: can't tell)."""
        start = getattr(self, "_balance_start", None)
        if not start:
            return None
        try:
            from ..providers.balance import balances

            now = balances(self.cfg, list(start["balances"]))
        except Exception:
            return None
        return sum(start["balances"][p]["amount"] - b["amount"] for p, b in now.items() if p in start["balances"])

    def _real_spend_over_limit(self, fraction: float = 1.0) -> bool:
        """True when the run's real spend reached `fraction` of limits.max_real_usd_per_run."""
        limit = self.cfg.limits.max_real_usd_per_run
        spent = self._real_spent() if limit else None
        return spent is not None and spent >= limit * fraction

    def _note_balance(self, phase: str, start: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Note the providers' real balances, so the cost count can be checked against the bill."""
        if not self.project.exists or os.environ.get("ROUNDTABLE_NO_BALANCE"):
            return None
        try:
            from ..providers.balance import balances

            used = sorted({m.provider for r in self.cfg.roles.values() for m in r.models})
            now = balances(self.cfg, used)
        except Exception:
            return None
        if not now:
            return None
        row: dict[str, Any] = {"at": utcnow(), "phase": phase, "balances": now,
                               "counted_usd": round(self.project.meta().get("spent_usd", 0.0), 6)}
        if start:
            real = sum(start["balances"][p]["amount"] - b["amount"] for p, b in now.items() if p in start["balances"])
            counted = row["counted_usd"] - start["counted_usd"]
            row.update(real_usd=round(real, 4), counted_since_start_usd=round(counted, 4))
            self.emit("real_cost", {"real_usd": row["real_usd"], "counted_usd": row["counted_since_start_usd"]})
        with (self.project.root / ".harness" / "balance.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        return row

    def _split_if_too_big(self, task: Task) -> bool:
        """A task that kept running out of steps is too big: ask the planner to split it, once."""
        outcomes = [a.get("outcome") for a in task.attempts]
        record = self.project.root / ".harness" / "split.json"
        split = json.loads(record.read_text(encoding="utf-8")) if record.is_file() else []
        if (not self.cfg.limits.split_stuck_tasks or not outcomes or task.id in split
                or any(o != "max_steps" for o in outcomes) or not self.project.plan_doc()):
            return False
        record.write_text(json.dumps(split + [task.id]), encoding="utf-8")
        try:
            r = self.revise_plan(
                f"Task {task.id} '{task.title}' ran out of steps {len(outcomes)} times: it is too big for one "
                "attempt. Its partial work is already in the files. Replace it with 2 to 4 smaller tasks that "
                "finish it, each small enough to do in about 30 steps, with clear 'done when' checks. Keep "
                "every other task as it is.", by="harness")
        except Exception as e:  # splitting is a help, not a must: the task stays failed for the owner
            self.emit("split_failed", {"task": task.id, "error": str(e)[:300]})
            return False
        self.emit("task_split", {"task": task.id, "summary": r["summary"]})
        self._journal("note", f"[{task.id}] was too big for one attempt; split: {r['summary']}")
        return True

    def _run(self, max_tasks: int | None = None) -> str:
        if not self.project.exists:
            raise HarnessError("no project here; use `roundtable new`")
        meta = self.project.meta()
        after = meta.get("start_after")
        if after and after > datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"):
            return "waiting_cheap"  # approved to start when it's cheaper; the desktop app starts it then
        if after:
            meta["start_after"] = None
            self.project.save_meta(meta)
        self._register_with_lab()
        try:
            if meta.get("status") == "planning":
                self.plan()
                meta = self.project.meta()
            if not meta.get("plan_approved"):
                self._set_status("awaiting_approval")
                self._attention("approval", "The plan is ready: look at it, then approve it to start building",
                                details=f"roundtable approve {self.project.root} && roundtable run {self.project.root}")
                return "awaiting_approval"
            self._resolved("approval", "budget", "money", note="run resumed")
            self._set_status("running")

            executed = finished_this_run = 0
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
                                self._attention(f"failed:{t.id}", f"Task {t.id} “{t.title}” didn't pass: try it "
                                                "again or skip it", details=f"roundtable status {self.project.root}")
                        return "blocked"
                    if all(t.status == "done" for t in tasks):
                        self._finish(tasks)
                        return "done"
                    self._set_status("blocked")
                    return "blocked"
                if not finished_this_run and executed and self._real_spend_over_limit(0.5):
                    # half the money gone and nothing passed: stop and let the owner look, don't spend the rest
                    self._set_status("paused", pause="money_nothing_done")
                    self._attention("money", "this run has spent half its real-money limit and finished nothing; "
                                             "look at the failed attempts before running again")
                    return "paused"
                if self._real_spend_over_limit():
                    self._set_status("paused", pause="money")
                    self._attention("money", f"this run has spent ${self.cfg.limits.max_real_usd_per_run:.2f} of real "
                                             "credit, the limit you set; run again to carry on")
                    return "paused"
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
                    finished_this_run += 1
                    self._git_commit(f"[{task.id}] {task.title}")
                    self._journal("done", f"[{task.id}] {task.title}", details=task.summary[:2000])
                    self._resolved(f"failed:{task.id}", note="task completed")
                self._after_task(task, ok)
                if not ok and self._split_if_too_big(task):
                    continue  # the planner replaced it with smaller tasks; carry on with those
                executed += 1
        except BudgetExceeded as e:
            tasks = self.project.tasks()
            for t in tasks:
                if t.status == "running":
                    t.status = "pending"
                    if isinstance(e, OutOfCredit):  # the money ran out, the task didn't fail
                        t.attempts = [a for a in t.attempts if a.get("outcome") != "error"]
            self.project.save_tasks(tasks)
            self._save_spend()
            if isinstance(e, OutOfCredit):
                self._set_status("paused", reason=str(e), pause="credit")
                self._attention("money", f"{e}: top up that account, then run the project again")
                return "paused"
            self._set_status("paused_budget", reason=str(e), pause="budget")
            self._attention("budget", "Paused at this project's spending limit: choose Carry on to give it more",
                            details=f"{e}; raise limits.max_cost_usd, then roundtable run {self.project.root}")
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
        self._resolved("approval", "budget", "money", note="the run finished")
        self._publish_plan()
        self._hub_update("done", f"completed goal: {meta['goals'][-1][:200]}")
        self._close_goal_plans(meta["goals"])
        meta = self.project.meta()
        first = next((ln.strip("# ").strip() for ln in summary.splitlines() if ln.strip()), "")
        # the owner reads the next steps on the phone and in the app: plain sentences; the paths and
        # commands go in the details
        self._journal("session", f"harness finished goal '{meta['goals'][-1][:150]}' ({len(tasks)} tasks, "
                                 f"${self.budget.spent_usd:.2f}). {first[:200]}",
                      next_steps=["Look at what was built and say what you think",
                                  "Rate the tasks in the app (good or bad), so Roundtable learns"],
                      details=f"Report: {self.project.dir / 'summary.md'}\n"
                              f"Rate tasks: roundtable feedback {self.project.root} TASK --good/--bad")

    def _close_goal_plans(self, goals: list[str]) -> None:
        """Close the journal's "Future plans" entries of finished goals.

        The ids kept in ``journal_plans`` are closed in the journal they were written to: the project's own
        hub project, or the shared harness agent before the project had one (``_hub_agent`` can change
        between planning and finishing, and closing in the wrong journal used to leave the entry open for
        good). Open plan entries that read "goal: <a finished goal>" are closed too, so one whose id was lost
        (or written by another session) doesn't stay under Future plans."""
        hub = self._hub()
        if not hub:
            return
        agents = list(dict.fromkeys(a for a in (self._hub_agent(), (self.cfg.hub or {}).get("agent")) if a
                                    and a in hub.config.agents))
        name = self.project.root.name
        wanted = {" ".join(f"goal: {g[:300]}".split()) for g in goals}
        left: list[str] = []
        try:
            for plan_id in self.project.meta().get("journal_plans", []):
                if not any(self._close_in(hub, agent, plan_id) for agent in agents):
                    left.append(plan_id)
            for agent in agents:
                prefix = "" if agent == name else f"{name}: "
                for e in hub.journal.entries(agent, agent, kinds=["plan"], status="open"):
                    text = e["text"]
                    if prefix and not text.startswith(prefix):
                        continue
                    if " ".join(text[len(prefix):].split()) in wanted:
                        self._close_in(hub, agent, e["id"])
        except Exception as e:  # the hub is optional; never fail a run over it
            self.emit("hub_error", {"error": str(e)})
        meta = self.project.meta()
        if meta.get("journal_plans") or left:
            meta["journal_plans"] = []  # one that can't be found anywhere is gone already
            self.project.save_meta(meta)

    def _close_in(self, hub, agent: str, entry_id: str) -> bool:
        """Close one plan entry in one agent's journal; False when it isn't there (or is closed already)."""
        from ..hub.journal import JournalError

        try:
            data = hub.store.read_json(f"journal/{agent}/{entry_id}.json")
            if not data:
                return False
            if data.get("status") == "open":
                hub.journal.close(agent, entry_id, note="completed by the harness")
            return True
        except JournalError:
            return False

    def retry(self, task_id: str, stronger: bool = False) -> None:
        """Try a task again; ``stronger``: with the Quality setting's model for its role."""
        tasks = self.project.tasks()
        for t in tasks:
            if t.id == task_id:
                if t.status not in ("failed", "skipped", "done"):
                    raise HarnessError(f"task {task_id} is {t.status}; only failed/skipped/done tasks can be retried")
                if stronger and not self.stronger_models(t):
                    raise HarnessError("there's no stronger model set up for this task (the Quality setting has the "
                                       "same one)")
                t.status, t.stronger = "pending", stronger
                self.project.save_tasks(tasks)
                self.emit("retry", {"task": task_id, "stronger": stronger})
                return
        raise HarnessError(f"no task {task_id!r}")

    def stronger_models(self, task: Task) -> list[ModelRef]:
        """The Quality setting's models for the task's role, when they differ from the ones in use."""
        quality = next((n for n in self.base_cfg.profiles if n.lower() == "quality"), None)
        role = self.cfg.roles.get(task.role)
        if not quality or not role:
            return []
        strong = self.base_cfg.for_profile(quality).roles.get(task.role)
        if not strong or [str(m) for m in strong.models] == [str(m) for m in role.models]:
            return []
        return list(strong.models)

    def raise_budget(self, extra_usd: float) -> float:
        """Let this project spend ``extra_usd`` more than its limit; returns the new limit."""
        extra = round(float(extra_usd), 2)
        if not 0 < extra <= 10_000:
            raise HarnessError("the extra must be between $0.01 and $10,000")
        meta = self.project.meta()
        meta["budget_extra_usd"] = round(float(meta.get("budget_extra_usd") or 0) + extra, 2)
        self.project.save_meta(meta)
        self.budget.limit_usd = self.cfg.limits.max_cost_usd + meta["budget_extra_usd"]
        self.emit("budget_raised", {"extra_usd": extra, "limit_usd": self.budget.limit_usd})
        return self.budget.limit_usd

    def accept(self, task_id: str, note: str = "") -> None:
        """The owner accepts a task's work as it is in the files (e.g. a reviewer rejected it for the wrong
        reason): it's committed and counts as done."""
        tasks = self.project.tasks()
        t = next((x for x in tasks if x.id == task_id), None)
        if not t:
            raise HarnessError(f"no task {task_id!r}")
        if t.status in ("done", "running"):
            raise HarnessError(f"task {task_id} is {t.status}; only a failed or waiting task can be accepted")
        t.status = "done"
        t.summary = f"Accepted by the owner{': ' + note if note else ''}. " + (t.summary or "")
        self.project.save_tasks(tasks)
        self._git_commit(f"[{t.id}] {t.title} (accepted by the owner)")
        self._journal("done", f"[{t.id}] {t.title} – accepted by the owner", details=note)
        self._resolved(f"failed:{t.id}", note="accepted by the owner")
        self.emit("accept", {"task": task_id, "note": note})

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
