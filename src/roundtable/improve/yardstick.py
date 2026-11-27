"""The yardstick: small made-up tasks with objective checks that a learned change is tried on (wave 7).

Replays of the owner's own past tasks are judged by the reviewer, so they can't test the reviewer, and an
empty lab has none. The yardstick can: ``yardsticks/<job>/<id>/`` holds about twelve tasks for builders
(each with hidden checks copied in only after the builder has finished), eight for the reviewer (four right
changes and four with a planted fault: the verdict is compared with the truth, and a rejection must quote
the planted line) and six for the planner (checked by the plan's shape only).

- ``run`` tries the current set-up and the candidate on the same tasks, ``runs`` times each. The current
  side's results are kept in ``<lab>/yardstick/results.jsonl`` by task, version and a fingerprint of the
  job's first model, options and prompt, and reused for 14 days, so nothing is paid twice.
- A candidate reviewer that lets through one more planted fault than the current one is vetoed, whatever
  else it does better.
- Everything here is made up, so any configured model may see it. Money comes only from the ``budget``
  given (the owner's own tap, or the learning allowance's ``wallet.budget``).

The signatures of ``available`` and ``run`` are frozen.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from ..core.files import remove_tree
from ..core.models import utcnow
from ..harness.agent import Budget, BudgetExceeded
from ..harness.safeenv import clean_env

ROOT = Path(__file__).parent / "yardsticks"
JOBS = ("builder", "reviewer", "planner")
KEEP_DAYS = 14  # how long a current side's saved result is reused
MIN_FOR_PROMPT = 6  # a prompt change is compared on at least this many tasks
CHECK_TIMEOUT = 120  # seconds for one check command
RESULTS = "yardstick/results.jsonl"

Emit = Callable[[str, dict[str, Any]], None]


# -- the set ------------------------------------------------------------------------------------------------
@dataclass
class YTask:
    id: str
    version: int
    job: str
    title: str
    description: str
    acceptance: str = ""
    tags: list[str] = field(default_factory=list)
    check: list[dict[str, Any]] = field(default_factory=list)
    max_steps: int = 12
    dir: Path = Path()
    extra: dict[str, Any] = field(default_factory=dict)  # summary, truth, planted (reviewer); goal, dont (planner)


_FIELDS = ("id", "version", "job", "title", "description", "acceptance", "tags", "check", "max_steps")


def load(job: str | None = None, root: Path | None = None) -> list[YTask]:
    """Every yardstick task (of ``job``), in id order."""
    base = root or ROOT
    out: list[YTask] = []
    for f in sorted(base.glob("*/*/task.yaml")):
        raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        if job and raw.get("job") != job:
            continue
        out.append(YTask(
            id=str(raw["id"]), version=int(raw.get("version") or 1), job=str(raw["job"]),
            title=str(raw.get("title") or raw["id"]), description=str(raw.get("description") or ""),
            acceptance=str(raw.get("acceptance") or ""), tags=[str(t) for t in raw.get("tags") or []],
            check=list(raw.get("check") or []), max_steps=int(raw.get("max_steps") or 12), dir=f.parent,
            extra={k: v for k, v in raw.items() if k not in _FIELDS}))
    return out


def job_for(cfg: Any, role: str) -> str | None:
    """Which part of the yardstick fits ``role``: the reviewer's, the planner's, or the builders'. None for
    image roles, the critic and the lab's own analyst (nothing objective to measure them on yet)."""
    spec = getattr(cfg, "roles", {}).get(role)
    if spec is None or spec.kind != "chat":
        return None
    if role == cfg.reviewer_role:
        return "reviewer"
    if role == cfg.planner_role:
        return "planner"
    analyst = (getattr(cfg, "improve", None) or {}).get("analyst_role") or "improver"
    if role in (cfg.critic_role, analyst):
        return None
    tools = spec.tools
    if tools is not None and not ({"write_file", "edit_file"} & set(tools)):
        return None  # a role that can't write files can't build
    return "builder"


def available(cfg: Any, role: str) -> int:
    """How many yardstick tasks fit this job (0: none, so it is tested on replays alone)."""
    job = job_for(cfg, role)
    return len(load(job)) if job else 0


def copy_tree(src: Path, dst: Path) -> None:
    """Copy a task's files; ``name.py.txt`` arrives as ``name.py`` (the Windows app keeps no .py data)."""
    if not src.is_dir():
        return
    for f in sorted(src.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(src)
        if rel.name.endswith(".py.txt"):
            rel = rel.with_name(rel.name[:-4])
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, out)


def _command(argv: list[str]) -> list[str]:
    """A check's command; ``python`` or ``{python}`` first is this Python (the app's own when frozen, pyexec)."""
    from ..pyexec import command

    return command([str(a) for a in argv])


def _shown(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv) if sys.platform == "win32" else " ".join(
        a if re.fullmatch(r"[\w./:=+-]+", a) else "'" + a.replace("'", "'\\''") + "'" for a in argv)


def run_checks(root: Path, checks: list[dict[str, Any]], gate: Any = None) -> tuple[bool, list[str]]:
    """A builder task's checks in ``root``: (all passed, what failed). ``gate``: the project's gate, asked
    first (with no wait, so a command that would need the owner is refused)."""
    notes: list[str] = []
    for c in checks:
        if "run" in c:
            argv = _command(list(c["run"]))
            refused = gate.check(_shown(argv)) if gate is not None else None
            if refused:
                notes.append(f"refused: {refused[:200]}")
                continue
            try:
                res = subprocess.run(argv, cwd=root, env=clean_env(), capture_output=True, text=True,
                                     timeout=float(c.get("timeout") or CHECK_TIMEOUT))
            except (OSError, subprocess.TimeoutExpired) as e:
                notes.append(f"{' '.join(c['run'])}: {e}")
                continue
            if res.returncode != 0:
                notes.append(f"{' '.join(c['run'])} exited {res.returncode}: "
                             f"{(res.stdout + res.stderr).strip()[-300:]}")
        elif "file_exists" in c:
            if not (root / c["file_exists"]).is_file():
                notes.append(f"missing {c['file_exists']}")
        elif "contains" in c:
            spec = c["contains"]
            p = root / spec["path"]
            text = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
            for rx in spec.get("text") or []:
                if not re.search(rx, text, re.MULTILINE):
                    notes.append(f"{spec['path']} lacks {rx}")
        else:
            notes.append(f"unknown check {sorted(c)}")
    return not notes, notes


def _norm(text: Any) -> str:
    return " ".join(str(text or "").replace("“", '"').replace("”", '"').replace("’", "'").lower().split())


def plan_shape(t: YTask, tasks: list[Any], args: dict[str, Any]) -> tuple[bool, list[str]]:
    """A planner task's check: the plan's shape, never its taste."""
    notes: list[str] = []
    for c in t.check:
        s = c.get("shape")
        if not isinstance(s, dict):
            continue
        n = len(tasks)
        if n < int(s.get("min_tasks") or 1) or n > int(s.get("max_tasks") or 99):
            notes.append(f"{n} tasks")
        if s.get("acceptance"):
            thin = [x.id for x in tasks if len(str(x.acceptance or "").strip()) < 10]
            if thin:
                notes.append(f"no done-when line on {', '.join(thin)}")
        if s.get("stages") and len(args.get("stages") or []) < 2:
            notes.append("fewer than two stages")
        words = " ".join(f"{x.title} {x.description}" for x in tasks)
        for rx in s.get("forbidden") or []:
            hit = re.search(rx, words, re.IGNORECASE)
            if hit:
                notes.append(f"a task does what the don't list forbids ({hit.group(0)})")
        allwords = words + " " + " ".join(str(x.acceptance) for x in tasks)
        for rx in s.get("must_mention") or []:
            if not re.search(rx, allwords):
                notes.append(f"nothing about {rx}")
    return not notes, notes


# -- running one task -----------------------------------------------------------------------------------------
def variant(c: Any, steps: int | None = None) -> Any:
    """The set-up a yardstick task runs with: one try, no hub, no lab, git on."""
    v = c.variant()
    v.limits.max_attempts_per_task = 1
    if steps:
        v.limits.max_steps_per_task = min(int(steps), int(v.limits.max_steps_per_task or steps))
    v.hub, v.lab_dir, v.git = None, None, True
    return v


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=yardstick", "-c", "user.email=yardstick@localhost", *args], cwd=cwd,
                   capture_output=True, text=True, env=clean_env())


def _project(t: YTask, role: str, goal: str, status: str = "running") -> tuple[Path, Path]:
    from ..harness.orchestrator import Project, Task

    tmp = Path(tempfile.mkdtemp(prefix="harness-yardstick-"))
    work = tmp / "project"
    work.mkdir()
    copy_tree(t.dir / "files", work)
    _git(work, "init", "-q")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "--allow-empty", "-m", "start")
    proj = Project(work)
    proj.save_meta({"goals": [goal], "status": status, "plan_approved": status == "running",
                    "created_at": utcnow(), "yardstick": t.id})
    tasks = [] if t.job == "planner" else [Task.from_dict({
        "id": t.id, "title": t.title, "role": role, "description": t.description, "acceptance": t.acceptance,
        "depends_on": [], "status": "pending", "attempts": [], "tags": list(t.tags)})]
    proj.save_tasks(tasks)
    return tmp, work


def _orch(cfg: Any, work: Path, budget: Budget, on_event: Emit | None, counter: dict[str, int]) -> Any:
    from ..harness.orchestrator import Orchestrator

    def emit(event: str, data: dict[str, Any]) -> None:
        if event == "model_turn":
            counter["steps"] += 1
        if on_event:
            on_event(event, data)

    orch = Orchestrator(cfg, work, on_event=emit)
    orch.budget = budget
    orch.mcp_allowed = False  # nothing outside the folder is touched through MCP
    gate = getattr(orch.ws, "gate", None)
    if gate is not None:
        gate.timeout = 0  # nobody waits for the owner: a command that would ask is refused
    return orch


def _quoted(planted: str, verdict: dict[str, Any], feedback: str) -> bool:
    want = _norm(planted).strip(" .")
    return bool(want) and want in _norm(f"{verdict.get('breaks', '')} {feedback}")


def run_one(cfg: Any, t: YTask, role: str, budget: Budget, on_event: Emit | None = None) -> dict[str, Any]:
    """One try of ``t`` with ``cfg``'s ``role``: {passed, cost_usd, steps, seconds, note} (and
    ``fault_approved`` for the reviewer's planted faults). BudgetExceeded is let through."""
    from ..harness.orchestrator import HarnessError

    c = variant(cfg, t.max_steps)
    spec = c.roles[role]
    counter = {"steps": 0}
    spent0, t0 = budget.spent_usd, time.monotonic()
    row: dict[str, Any] = {"passed": False, "note": ""}
    goal = str(t.extra.get("goal") or t.title)
    tmp, work = _project(t, role, goal, "planning" if t.job == "planner" else "running")
    try:
        orch = _orch(c, work, budget, on_event, counter)
        if t.job == "builder":
            tasks = orch.project.tasks()
            target = next(x for x in tasks if x.id == t.id)
            built = orch._attempt_loop(target, tasks, list(spec.models), review=False)
            last = target.attempts[-1] if target.attempts else {}
            copy_tree(t.dir / "hidden", work)  # only now: the builder could not see or change them
            ok, notes = run_checks(work, t.check, getattr(orch.ws, "gate", None)) if built else (
                False, [f"not finished ({last.get('outcome') or 'no attempt'})"])
            row.update(passed=ok, note="; ".join(notes)[:500], model=last.get("model"))
        elif t.job == "reviewer":
            copy_tree(t.dir / "change", work)  # the change to judge, not committed: it shows in the diff
            task = orch.project.tasks()[0]
            ok, fb, _res, verdict = orch._review_once(task, str(t.extra.get("summary") or "(no summary)"),
                                                      None, list(spec.models))
            truth = str(t.extra.get("truth") or "approve") == "approve"
            right = ok if truth else (not ok and _quoted(str(t.extra.get("planted") or ""), verdict, fb))
            row.update(passed=bool(right), approved=bool(ok), fault_approved=bool(ok and not truth),
                       note="" if right else ("approved a planted fault" if ok and not truth else
                                              "rejected a right change" if truth else
                                              "rejected without quoting the fault"))
        else:  # planner
            job = (f"# Your job\nPlan the work for goal #1: {goal}\n"
                   "Inspect the existing files if useful, then call submit_plan with the plan document (summary, "
                   "scope, don't-do list, a short spec, the real decisions with your recommendation, questions "
                   "only you can't answer, worthwhile ideas), has_ui (true when people will look at its screens) "
                   "and the tasks, each linked to its spec section.")
            try:
                tasks, args = orch._plan_call(job, [], spec)
                ok, notes = plan_shape(t, tasks, args)
            except HarnessError as e:
                ok, notes = False, [str(e)[:300]]
            row.update(passed=ok, note="; ".join(notes)[:500])
    finally:
        remove_tree(tmp)
    row.update(cost_usd=round(budget.spent_usd - spent0, 6), steps=counter["steps"],
               seconds=round(time.monotonic() - t0, 2))
    return row


# -- not paying twice -----------------------------------------------------------------------------------------
def fingerprint(cfg: Any, role: str) -> str:
    """The job's first model, its options and its whole system prompt, as a short hash."""
    from . import charter

    spec = cfg.roles[role]
    blob = json.dumps({"model": str(spec.models[0]) if spec.models else "", "options": spec.options,
                       "prompt": cfg.prompt_text(spec.prompt), "fixed": charter.fixed_block(spec.prompt)},
                      sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _parse(at: str) -> datetime | None:
    try:
        return datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


class Results:
    """``<lab>/yardstick/results.jsonl``: one row per try (numbers and made-up task ids only)."""

    def __init__(self, lab: Any):
        self.path = Path(lab.root) / RESULTS

    def rows(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def recent(self, t: YTask, key: str, most: int, now: datetime | None = None) -> list[dict[str, Any]]:
        """The newest saved tries of ``t`` with set-up ``key``, at most ``most``, none older than 14 days."""
        now = now or datetime.now(timezone.utc)
        since = now - timedelta(days=KEEP_DAYS)
        got = [r for r in self.rows() if r.get("task") == t.id and r.get("version") == t.version
               and r.get("key") == key and (_parse(r.get("at", "")) or since) > since]
        return got[-most:] if most > 0 else []

    def add(self, t: YTask, key: str, row: dict[str, Any], side: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        keep = {k: row[k] for k in ("passed", "cost_usd", "steps", "seconds", "approved", "fault_approved")
                if k in row}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": utcnow(), "task": t.id, "version": t.version, "job": t.job, "key": key,
                                "side": side, **keep}) + "\n")


# -- the verdict ----------------------------------------------------------------------------------------------
def compare(cur_ok: float, cand_ok: float, cur_cost: float, cand_cost: float) -> str:
    """better | worse | cheaper (equal results, at least a fifth cheaper) | costlier (a quarter dearer) | equal."""
    if cand_ok > cur_ok:
        return "better"
    if cand_ok < cur_ok:
        return "worse"
    priced = cur_cost > 0 and cand_cost > 0
    if priced and cand_cost <= 0.8 * cur_cost:
        return "cheaper"
    if priced and cand_cost > 1.25 * cur_cost:
        return "costlier"
    return "equal"


def _side(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"passed": sum(bool(r.get("passed")) for r in rows), "of": len(rows),
            "cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in rows), 6),
            "faults_approved": sum(bool(r.get("fault_approved")) for r in rows)}


def run(cfg: Any, lab: Any, proposal: Any, budget: Any, runs: int = 2,
        on_event: Callable[[str, dict[str, Any]], None] | None = None) -> dict[str, Any] | None:
    """Try ``proposal`` against the current state on the yardstick. None: no yardstick for it.

    {"n", "current": {"passed", "cost_usd"}, "candidate": {"passed", "cost_usd"}, "veto": "", "verdict",
    "passed"} plus the job, each task's row, what was reused and what this call spent.
    """
    role = proposal.role
    job = job_for(cfg, role)
    tasks = load(job) if job else []
    if not tasks:
        return None
    runs = max(1, int(runs or 1))
    from .toolkind import candidate_for  # a tool gets its own plugin host; other kinds as lab.candidate_config

    candidate = candidate_for(lab, cfg, proposal)
    keys = {"current": fingerprint(cfg, role), "candidate": fingerprint(candidate, role)}
    results = Results(lab)
    emit = on_event or (lambda *_: None)
    spent0 = budget.spent_usd
    done: list[dict[str, Any]] = []
    reused, note = 0, ""
    for t in tasks:
        sides: dict[str, list[dict[str, Any]]] = {}
        try:
            for side, c in (("current", cfg), ("candidate", candidate)):
                have = results.recent(t, keys[side], runs) if side == "current" else []
                reused += len(have)
                while len(have) < runs:
                    emit("yardstick", {"task": t.id, "variant": side, "job": job})
                    row = run_one(c, t, role, budget, on_event)
                    results.add(t, keys[side], row, side)
                    have.append(row)
                sides[side] = have
        except BudgetExceeded as e:
            note = f"stopped early: {e}"
            break
        done.append({"task": t.id, "version": t.version, "current": _side(sides["current"]),
                     "candidate": _side(sides["candidate"])})
    cur, cand = ({k: (round(sum(r[side][k] for r in done), 6) if k == "cost_usd" else sum(r[side][k] for r in done))
                  for k in ("passed", "of", "cost_usd", "faults_approved")} for side in ("current", "candidate"))
    n = len(done)
    veto = ""
    if job == "reviewer" and cand["faults_approved"] > cur["faults_approved"]:
        more = cand["faults_approved"] - cur["faults_approved"]
        veto = (f"The new reviewer let through {more} more planted mistake{'s' if more != 1 else ''} than the "
                "current one.")
    if n == 0:
        verdict, passed = "inconclusive", False
    elif veto:
        verdict, passed = "vetoed", False
    else:
        verdict = compare(cur["passed"], cand["passed"], cur["cost_usd"], cand["cost_usd"])
        passed = verdict in ("better", "cheaper")
        if getattr(proposal, "kind", "") == "prompt" and n < MIN_FOR_PROMPT:
            passed = False
            note = (note + "; " if note else "") + (f"a prompt change needs at least {MIN_FOR_PROMPT} tasks; "
                                                   f"{n} compared")
    return {"job": job, "n": n, "runs": runs, "current": cur, "candidate": cand, "veto": veto,
            "verdict": verdict, "passed": passed, "tasks": done, "reused": reused,
            "spent_usd": round(budget.spent_usd - spent0, 6), "note": note}


# -- for the command line ----------------------------------------------------------------------------------------
def baseline(cfg: Any, lab: Any, role: str, budget: Budget, runs: int = 1,
             on_event: Emit | None = None) -> dict[str, Any]:
    """How the current set-up does on ``role``'s part of the yardstick (saved, so a later test reuses it)."""
    job = job_for(cfg, role)
    if not job:
        raise ValueError(f"there's no yardstick for {role!r}")
    key, results = fingerprint(cfg, role), Results(lab)
    out, note, spent0 = [], "", budget.spent_usd
    for t in load(job):
        try:
            have = results.recent(t, key, runs)
            while len(have) < runs:
                row = run_one(cfg, t, role, budget, on_event)
                results.add(t, key, row, "current")
                have.append(row)
        except BudgetExceeded as e:
            note = f"stopped early: {e}"
            break
        out.append({"task": t.id, **_side(have)})
    return {"job": job, "role": role, "tasks": out, "passed": sum(r["passed"] for r in out),
            "of": sum(r["of"] for r in out), "spent_usd": round(budget.spent_usd - spent0, 6), "note": note}


def listing(job: str | None = None) -> str:
    """The set, one line a task."""
    lines = []
    for t in load(job):
        lines.append(f"{t.job:9} {t.id:24} v{t.version}  {t.title}")
    return "\n".join(lines) or "(no yardstick tasks)"


def check_set(root: Path | None = None) -> list[str]:
    """What is wrong with the set itself (no model is called): each builder task fails as it starts and
    passes with its solution; each reviewer task's fault is really in its change. [] when all is well."""
    problems: list[str] = []
    for t in load(root=root):
        if t.job not in JOBS:
            problems.append(f"{t.id}: unknown job {t.job!r}")
            continue
        if t.job == "builder":
            for label, parts, want in (("start", ("files", "hidden"), False),
                                       ("solution", ("files", "solution", "hidden"), True)):
                tmp = Path(tempfile.mkdtemp(prefix="harness-yardstick-check-"))
                try:
                    for part in parts:
                        copy_tree(t.dir / part, tmp)
                    ok, notes = run_checks(tmp, t.check)
                finally:
                    remove_tree(tmp)
                if ok != want:
                    problems.append(f"{t.id}: the {label} {'fails' if want else 'already passes'}"
                                    + (f" ({'; '.join(notes)[:200]})" if notes else ""))
        elif t.job == "reviewer":
            truth = t.extra.get("truth")
            planted = str(t.extra.get("planted") or "")
            if truth not in ("approve", "reject"):
                problems.append(f"{t.id}: truth must be approve or reject")
            changed = " ".join(f.read_text(encoding="utf-8") for f in (t.dir / "change").rglob("*") if f.is_file())
            if truth == "reject" and (not planted or _norm(planted) not in _norm(changed)):
                problems.append(f"{t.id}: the planted line is not in the change")
        elif not any("shape" in c for c in t.check):
            problems.append(f"{t.id}: a planner task needs a shape check")
    return problems
