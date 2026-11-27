"""Replay past tasks to test a proposal before it is applied.

For each sampled task: check out the project exactly as it was when the task
started (its ``base_commit``), run the task once with the CURRENT setup and
once with the CANDIDATE setup, and let the same reviewer judge both. Only the
proposal differs between the two runs.

Small samples are noisy; the report says how many tasks were compared so a
1-vs-0 result is not mistaken for proof.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from ..core.models import utcnow
from ..harness.agent import Budget, BudgetExceeded
from ..harness import makers
from ..harness import projectsettings as ps
from ..harness.config import HarnessConfig
from ..harness.orchestrator import Orchestrator, Project, Task
from ..harness.safeenv import clean_env
from .lab import Lab, Proposal
from ..core.files import remove_tree


class EvalError(RuntimeError):
    pass


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=clean_env())


def find_base_commit(project: Path, task: dict[str, Any]) -> str | None:
    """The commit a task started from. Older runs didn't record it, so fall
    back to the parent of the task's own "[ID] title" commit."""
    if task.get("base_commit"):
        return task["base_commit"]
    if not (project / ".git").exists():
        return None
    log = _git(project, "log", "--format=%H %s").stdout.splitlines()
    for line in log:
        sha, _, subject = line.partition(" ")
        if subject.startswith(f"[{task['id']}] "):
            parent = _git(project, "rev-parse", f"{sha}^")
            return parent.stdout.strip() if parent.returncode == 0 else ""
    return None


def _kept_out(proj: Path, role: str, cfgs: tuple[HarnessConfig, ...]) -> bool:
    """Does the project's own allowed list leave ``role`` (or the judging reviewer) with no model in one of
    ``cfgs``? Such a project is never replayed: its work may only be seen by the models it allows."""
    if not cfgs:
        return False
    values = ps.load(proj).values
    if not (values.get("providers_allowed") or values.get("makers_allowed")):
        return False
    for c in cfgs:
        for name in {role, c.reviewer_role} - {None, ""}:
            spec = c.roles.get(name)
            if spec is None or not any(makers.allowed(values, m) for m in spec.models):
                return True
    return False


def benchmark_tasks(lab: Lab, role: str, limit: int,
                    cfgs: tuple[HarnessConfig, ...] = ()) -> list[tuple[Path, dict[str, Any], dict[str, Any], list[dict]]]:
    """Recent past tasks for ``role`` that can be replayed: (project, meta, task, all tasks).

    ``cfgs``: the set-ups the replay will use (current and candidate). A project whose allowed lists
    (``providers_allowed``, ``makers_allowed``) leave the role or the reviewer with no model in any of
    them is left out."""
    found = []
    for proj in lab.projects():
        if _kept_out(proj, role, cfgs):
            continue
        meta = json.loads((proj / ".harness/project.json").read_text(encoding="utf-8"))
        tasks = json.loads((proj / ".harness/tasks.json").read_text(encoding="utf-8"))
        for t in tasks:
            if t["role"] != role or t["status"] not in ("done", "failed") or not t.get("attempts"):
                continue
            base = find_base_commit(proj, t)
            if base is None:
                continue
            found.append((proj, meta, {**t, "base_commit": base}, tasks))
    # newest projects last in registry; prefer recent work
    return list(reversed(found))[:limit]


def _prepare(project: Path, meta: dict, task: dict, all_tasks: list[dict]) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="harness-replay-"))
    work = tmp / "project"
    if task["base_commit"]:
        res = _git(tmp, "clone", "-q", "--no-checkout", str(project), str(work))
        if res.returncode != 0:
            raise EvalError(f"could not clone {project}: {res.stderr.strip()}")
        res = _git(work, "checkout", "-q", task["base_commit"])
        if res.returncode != 0:
            raise EvalError(f"could not check out {task['base_commit']}: {res.stderr.strip()}")
    else:
        work.mkdir(parents=True)
        _git(work, "init", "-q")
    # the project's own settings (git-ignored, so not in the clone): its allowed lists hold in the replay too
    src = project / ps.PROJECT_FILE
    if src.is_file():
        dst = work / ps.PROJECT_FILE
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)

    # minimal task board: the task's (transitive) dependencies as done, the task itself pending
    by_id = {t["id"]: t for t in all_tasks}
    needed, stack = set(), list(task.get("depends_on", []))
    while stack:
        d = stack.pop()
        if d in by_id and d not in needed:
            needed.add(d)
            stack.extend(by_id[d].get("depends_on", []))
    board = []
    for t in all_tasks:
        if t["id"] in needed:
            board.append({**t, "status": "done", "attempts": []})
        elif t["id"] == task["id"]:
            board.append({**t, "status": "pending", "attempts": [], "summary": ""})
    proj = Project(work)
    proj.save_meta({"goals": meta.get("goals", []), "status": "running", "plan_approved": True,
                    "created_at": utcnow(), "replay_of": str(project)})
    proj.save_tasks([Task.from_dict(t) for t in board])
    return tmp


def _replay_once(cfg: HarnessConfig, project: Path, meta: dict, task: dict, all_tasks: list[dict],
                 budget: Budget, on_event: Callable | None) -> dict[str, Any]:
    tmp = _prepare(project, meta, task, all_tasks)
    try:
        orch = Orchestrator(cfg, tmp / "project", on_event=on_event)
        orch.budget = budget
        orch.mcp_allowed = False  # a replay must not change things in a real editor (Unreal...) through MCP
        gate = getattr(orch.ws, "gate", None)
        if gate is not None:
            gate.timeout = 0  # a replay never waits for the owner: a command that would ask is refused
        tasks = orch.project.tasks()
        target = next(t for t in tasks if t.id == task["id"])
        spent0, t0 = budget.spent_usd, time.monotonic()
        ok = orch._run_task(target, tasks)
        last = target.attempts[-1] if target.attempts else {}
        return {"task": task["id"], "approved": ok, "cost_usd": round(budget.spent_usd - spent0, 6),
                "seconds": round(time.monotonic() - t0, 1), "outcome": last.get("outcome"),
                "model": last.get("model"), "review": (last.get("review") or "")[:400]}
    finally:
        remove_tree(tmp)


def evaluate(cfg: HarnessConfig, lab: Lab, proposal: Proposal, samples: int = 3, max_cost: float = 2.0,
             on_event: Callable | None = None) -> dict[str, Any]:
    proposal.validate(cfg)
    role = cfg.roles[proposal.role]
    if role.kind != "chat":
        raise EvalError("only chat roles can be replay-tested (image output has no automatic judge)")
    if proposal.role == cfg.reviewer_role:
        raise EvalError("the reviewer is the judge, so it can't test changes to itself; apply manually if you trust it")
    if not cfg.reviewer_role:
        raise EvalError("replay tests need a reviewer_role to judge results")

    def variant(c: HarnessConfig) -> HarnessConfig:
        v = c.variant()
        v.limits.max_attempts_per_task = 1  # measure first-try quality
        v.hub, v.lab_dir, v.git = None, None, True
        return v

    current, candidate = variant(cfg), variant(lab.candidate_config(cfg, proposal))
    bench = benchmark_tasks(lab, proposal.role, samples, (current, candidate))
    if not bench:
        raise EvalError(f"no replayable past tasks for role {proposal.role!r} yet; run some projects first")

    budget = Budget(max_cost)
    runs: dict[str, list[dict[str, Any]]] = {"current": [], "candidate": []}
    note = ""
    try:
        for project, meta, task, all_tasks in bench:
            for label, c in (("current", current), ("candidate", candidate)):
                if on_event:
                    on_event("replay", {"task": task["id"], "variant": label, "project": project.name})
                runs[label].append(_replay_once(c, project, meta, task, all_tasks, budget, on_event))
    except BudgetExceeded as e:
        note = f"stopped early: {e}"

    n = min(len(runs["current"]), len(runs["candidate"]))
    cur, cand = runs["current"][:n], runs["candidate"][:n]
    cur_ok, cand_ok = sum(r["approved"] for r in cur), sum(r["approved"] for r in cand)
    cur_cost, cand_cost = sum(r["cost_usd"] for r in cur), sum(r["cost_usd"] for r in cand)
    priced = cur_cost > 0 and cand_cost > 0
    if n == 0:
        verdict, passed = "inconclusive", False
    elif cand_ok > cur_ok:
        verdict, passed = "better", True
    elif cand_ok < cur_ok:
        verdict, passed = "worse", False
    elif priced and cand_cost <= 0.8 * cur_cost:
        verdict, passed = "cheaper", True
    elif priced and cand_cost > 1.25 * cur_cost:
        verdict, passed = "costlier", False
    else:
        verdict, passed = "equal", proposal.kind != "prompt"  # a prompt rewrite must earn its place
    result = {
        "at": utcnow(), "tasks_compared": n, "verdict": verdict, "passed": passed,
        "current": {"approved": cur_ok, "cost_usd": round(cur_cost, 6), "runs": cur},
        "candidate": {"approved": cand_ok, "cost_usd": round(cand_cost, 6), "runs": cand},
        "eval_cost_usd": round(budget.spent_usd, 6), "unpriced_calls": budget.unpriced_calls, "note": note,
    }
    proposal.test = result
    if proposal.status == "proposed":
        proposal.status = "tested"
    lab.save_proposal(proposal)
    return result
