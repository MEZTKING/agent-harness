"""Replay past tasks to test a proposal before it is applied.

For each sampled task: check out the project exactly as it was when the task
started (its ``base_commit``), run the task once with the CURRENT setup and
once with the CANDIDATE setup, and let the same reviewer judge both. Only the
proposal differs between the two runs.

Small samples are noisy; the report says how many tasks were compared so a
1-vs-0 result is not mistaken for proof.

Since wave 7 the yardstick (``yardstick.py``: small made-up tasks with objective checks) is tried too. An
empty lab tests on the yardstick alone, and a change to the reviewer is tested on the reviewer's yardstick
(it can't judge itself on replays). A change passes only when it is not worse on either, and better on one
or at least a fifth cheaper at equal results; a reviewer that lets one more planted fault through is vetoed;
a prompt change needs at least six yardstick tasks.
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
from ..harness import usage
from ..harness import projectsettings as ps
from ..harness.config import HarnessConfig
from ..harness.orchestrator import Orchestrator, Project, Task
from ..harness.safeenv import clean_env
from . import yardstick
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
    ``cfgs``? Such a project is never replayed: its work may only be seen by the models it allows.

    A project in one of the owner's own repositories is also left out when a model of ``role`` or the
    reviewer in any of ``cfgs`` comes from a maker that has never received it (``usage.seen``): a replay
    never introduces a new maker to private code."""
    if not cfgs:
        return False
    if _private_repo(proj):
        try:
            seen = {str(r.get("maker") or "").lower() for r in usage.seen(proj)}
        except Exception:  # noqa: BLE001 - no record of who has seen it: nobody new may
            seen = set()
        for c in cfgs:
            for name in {role, c.reviewer_role} - {None, ""}:
                spec = c.roles.get(name)
                if spec is not None and any(makers.maker(m) not in seen for m in spec.models):
                    return True
    values = ps.load(proj).values
    if not (values.get("providers_allowed") or values.get("makers_allowed")):
        return False
    for c in cfgs:
        for name in {role, c.reviewer_role} - {None, ""}:
            spec = c.roles.get(name)
            if spec is None or not any(makers.allowed(values, m) for m in spec.models):
                return True
    return False


def _private_repo(proj: Path) -> bool:
    """Is this project one of the owner's own apps in a git repository (repository mode)?"""
    try:
        meta = json.loads((proj / ".harness/project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True  # can't tell: treat it as private
    return bool(meta.get("repository"))


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


def _combine(proposal: Proposal, replay: dict[str, Any] | None, yard: dict[str, Any] | None
             ) -> tuple[str, bool, str]:
    """(verdict, passed, note) from the replay comparison and the yardstick's."""
    if yard and yard.get("veto"):
        return "vetoed", False, yard["veto"]
    yn = int((yard or {}).get("n") or 0)
    if proposal.kind == "prompt" and yn < yardstick.MIN_FOR_PROMPT:
        return "inconclusive", False, (f"A prompt change is compared on at least {yardstick.MIN_FOR_PROMPT} "
                                       f"yardstick tasks; {yn} were.")
    sides = [s for s in ((replay or {}).get("verdict"), (yard or {}).get("verdict") if yn else None)
             if s and s != "inconclusive"]
    if not sides:
        return "inconclusive", False, ""
    for bad in ("worse", "costlier"):
        if bad in sides:
            return bad, False, ""
    if "better" in sides:
        return "better", True, ""
    cur = float((replay or {}).get("cur_cost") or 0) + (float(yard["current"]["cost_usd"]) if yn else 0)
    cand = float((replay or {}).get("cand_cost") or 0) + (float(yard["candidate"]["cost_usd"]) if yn else 0)
    if cur > 0 and cand > 0 and cand <= 0.8 * cur:
        return "cheaper", True, ""
    return "equal", False, "Not better and not a fifth cheaper, so it is not worth changing."


def evaluate(cfg: HarnessConfig, lab: Lab, proposal: Proposal, samples: int = 3, max_cost: float = 2.0,
             on_event: Callable | None = None, budget: Budget | None = None, yard: bool = True) -> dict[str, Any]:
    """Test ``proposal``: replays of past tasks and (``yard``) the yardstick. ``budget``: the money it may
    spend (the learning allowance's, when it runs by itself); else ``max_cost``."""
    proposal.validate(cfg)
    role = cfg.roles[proposal.role]
    if role.kind != "chat":
        raise EvalError("only chat roles can be replay-tested (image output has no automatic judge)")
    is_reviewer = proposal.role == cfg.reviewer_role
    has_yard = yard and yardstick.available(cfg, proposal.role) > 0
    if is_reviewer and not has_yard:
        raise EvalError("the reviewer is the judge, so replays can't test changes to it; the yardstick can "
                        "(test it with the yardstick on), or apply it by hand if you trust it")
    if not cfg.reviewer_role and not has_yard:
        raise EvalError("replay tests need a reviewer_role to judge results")

    def variant(c: HarnessConfig) -> HarnessConfig:
        v = c.variant()
        v.limits.max_attempts_per_task = 1  # measure first-try quality
        v.hub, v.lab_dir, v.git = None, None, True
        return v

    current, candidate = variant(cfg), variant(lab.candidate_config(cfg, proposal))
    bench = [] if is_reviewer or not cfg.reviewer_role else benchmark_tasks(
        lab, proposal.role, samples, (current, candidate))
    if not bench and not has_yard:
        raise EvalError(f"no replayable past tasks for role {proposal.role!r} yet; run some projects first")

    budget = budget if budget is not None else Budget(max_cost)
    spent0 = budget.spent_usd
    runs: dict[str, list[dict[str, Any]]] = {"current": [], "candidate": []}
    notes: list[str] = []
    yres: dict[str, Any] | None = None
    if has_yard:  # first: objective, and the only evidence a prompt change can pass on
        yres = yardstick.run(cfg, lab, proposal, budget, runs=int(cfg.improve.get("yardstick_runs", 2) or 2),
                             on_event=on_event)
        if yres and yres.get("note"):
            notes.append(f"yardstick: {yres['note']}")
    try:
        for project, meta, task, all_tasks in bench:
            for label, c in (("current", current), ("candidate", candidate)):
                if on_event:
                    on_event("replay", {"task": task["id"], "variant": label, "project": project.name})
                runs[label].append(_replay_once(c, project, meta, task, all_tasks, budget, on_event))
    except BudgetExceeded as e:
        notes.append(f"stopped early: {e}")

    n = min(len(runs["current"]), len(runs["candidate"]))
    cur, cand = runs["current"][:n], runs["candidate"][:n]
    cur_ok, cand_ok = sum(r["approved"] for r in cur), sum(r["approved"] for r in cand)
    cur_cost, cand_cost = sum(r["cost_usd"] for r in cur), sum(r["cost_usd"] for r in cand)
    replay = {"verdict": yardstick.compare(cur_ok, cand_ok, cur_cost, cand_cost), "cur_cost": cur_cost,
              "cand_cost": cand_cost} if n else None
    verdict, passed, why = _combine(proposal, replay, yres)
    if why:
        notes.append(why)
    result = {
        "at": utcnow(), "tasks_compared": n, "verdict": verdict, "passed": passed,
        "current": {"approved": cur_ok, "cost_usd": round(cur_cost, 6), "runs": cur},
        "candidate": {"approved": cand_ok, "cost_usd": round(cand_cost, 6), "runs": cand},
        "replay_verdict": replay["verdict"] if replay else None,
        "yardstick": yres, "yardstick_compared": int((yres or {}).get("n") or 0),
        "eval_cost_usd": round(budget.spent_usd - spent0, 6), "unpriced_calls": budget.unpriced_calls,
        "note": "; ".join(notes),
    }
    proposal.test = result
    if proposal.status == "proposed":
        proposal.status = "tested"
    lab.save_proposal(proposal)
    return result
