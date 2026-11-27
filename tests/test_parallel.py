"""Several tasks at once (worktrees.py): each in its own git worktree, merged back in task order.

Every project here is made up, in tmp_path; the models are scripted.
"""

import json
import subprocess
import threading

from roundtable.harness import checks as checkslib
from roundtable.harness.worktrees import Worktrees, safe_name
from roundtable.providers.scripted import reply

from .test_harness import RAW, make
from .test_repository import git, make_repo

THREE = [
    {"id": "T1", "title": "one", "role": "coder", "description": "write one.txt", "acceptance": "exists",
     "depends_on": []},
    {"id": "T2", "title": "two", "role": "coder", "description": "write two.txt", "acceptance": "exists",
     "depends_on": []},
    {"id": "T3", "title": "three", "role": "coder", "description": "write three.txt", "acceptance": "exists",
     "depends_on": []},
]


def raw(width=3, **limits):
    r = json.loads(json.dumps(RAW))
    r["limits"].update(max_parallel=width, **limits)
    return r


def tid_of(messages):
    prompt = messages[0]["content"]
    for marker in ("# Your task [", "# Task ["):
        if marker in prompt:
            return prompt.split(marker, 1)[1].split("]", 1)[0]
    return ""


class ParallelBrain:
    """Workers write ``files[task]`` (default ``<task>.txt``); ``meet`` makes the first worker turns wait for
    each other, which only passes when the tasks really run at the same time."""

    def __init__(self, plan, files=None, meet=0, on_second_turn=None, reject=()):
        self.plan = plan
        self.files = files or {}
        self.meet = threading.Barrier(meet) if meet else None
        self.met = []
        self.on_second_turn = on_second_turn
        self.reject = set(reject)
        self.prompts = {}
        self.lock = threading.Lock()

    def __call__(self, model, system, messages, tools):
        names = {t.name for t in tools}
        last = messages[-1]
        tid = tid_of(messages)
        if "submit_plan" in names:
            return reply("planned") if last["role"] == "tool" else reply(calls=[("submit_plan", {"tasks": self.plan})])
        if "submit_review" in names:
            if last["role"] == "tool":
                return reply("ok")
            ok = tid not in self.reject
            return reply(calls=[("submit_review", {"approved": ok, "feedback": "fine" if ok else "not yet"})])
        if "finish_task" in names:
            if last["role"] == "user":
                with self.lock:
                    self.prompts[tid] = messages[0]["content"]
                with self.lock:
                    meet = self.meet is not None and len(self.met) < self.meet.parties and tid not in self.met
                    if meet:
                        self.met.append(tid)
                if meet:
                    self.meet.wait(timeout=10)
                path, content = self.files.get(tid, (f"{tid.lower()}.txt", f"{tid}\n"))
                return reply(calls=[("write_file", {"path": path, "content": content})])
            if self.on_second_turn:
                self.on_second_turn(tid)
            return reply(calls=[("finish_task", {"summary": f"{tid} done"})])
        return reply("Final report: all done.")


def events_of(orch):
    rows = (orch.project.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(r) for r in rows if r.strip()]


def log(root):
    return subprocess.run(["git", "log", "--format=%s"], cwd=root, capture_output=True, text=True).stdout


def test_three_independent_tasks_run_at_once_and_all_merge(tmp_path):
    brain = ParallelBrain(THREE, meet=3)
    orch, *_ = make(tmp_path, raw=raw(3), brain=brain)
    orch.start("three files")
    assert orch.run() == "done"
    assert sorted(brain.met) == ["T1", "T2", "T3"]  # all three were in their first turn together
    root = orch.project.root
    for n in ("t1", "t2", "t3"):
        assert (root / f"{n}.txt").is_file()
    assert {t.status for t in orch.project.tasks()} == {"done"}
    subjects = log(root)
    assert "[T1] one" in subjects and "[T2] two" in subjects and "[T3] three" in subjects
    ev = events_of(orch)
    assert [e["task"] for e in ev if e["event"] == "merged"] == ["T1", "T2", "T3"]  # in task order
    # cleaned up: no worktree folders, no task branches
    assert not any((root / ".harness" / "worktrees").glob("*"))
    assert "roundtable-task/" not in git(root, "branch", "--list")
    assert sum(1 for e in ev if e["event"] == "worktree_removed") == 3
    # every event of a task's conversation says which task it is
    for e in ev:
        if e["event"] in ("attempt", "review", "task_start", "task_end", "worktree") or (
                e["event"] in ("model_turn", "tool_call") and e.get("role") in ("coder", "reviewer")):
            assert e.get("task") in {"T1", "T2", "T3"}, e
    # the tools wrote in the task's own worktree, not the project's folder
    starts = {e["task"]: e["worktree"] for e in ev if e["event"] == "task_start"}
    assert starts["T2"].replace("\\", "/").endswith(".harness/worktrees/T2")


def test_depends_on_waits_for_the_merge(tmp_path):
    plan = [dict(THREE[0]), dict(THREE[1]), {**THREE[2], "depends_on": ["T1"]}]
    brain = ParallelBrain(plan)
    orch, *_ = make(tmp_path, raw=raw(3), brain=brain)
    orch.start("three files")
    assert orch.run() == "done"
    ev = events_of(orch)
    order = [(e["event"], e.get("task")) for e in ev if e["event"] in ("merged", "task_start")]
    assert order.index(("merged", "T1")) < order.index(("task_start", "T3"))
    # T3's worktree started from the project with T1's work in it, and it saw T1's summary
    assert "t1.txt" in brain.prompts["T3"] and "T1 done" in brain.prompts["T3"]


def test_a_clash_becomes_a_fix_up_task_and_is_never_overwritten(tmp_path):
    plan = [dict(THREE[0]), dict(THREE[1]), {**THREE[2], "depends_on": ["T2"]}]
    files = {"T1": ("shared.txt", "from one\n"), "T2": ("shared.txt", "from two\n"),
             "T2-merge": ("shared.txt", "from one\nfrom two\n")}
    brain = ParallelBrain(plan, files=files, meet=2)

    orch, *_ = make(tmp_path, raw=raw(2), brain=brain)
    orch.start("two writers")
    assert orch.run() == "done"
    root = orch.project.root
    ev = events_of(orch)
    clash = next(e for e in ev if e["event"] == "merge_conflict")
    assert clash["task"] == "T2" and clash["files"] == ["shared.txt"] and clash["fixup"] == "T2-merge"
    tasks = {t.id: t for t in orch.project.tasks()}
    fix = tasks["T2-merge"]
    assert fix.merge_of == "T2" and fix.role == "coder"
    assert "shared.txt" in fix.description and "T1 done" in fix.description and "T2 done" in fix.description
    assert "T2-merge" in tasks["T3"].depends_on  # what needed T2 waited for its changes to land
    # the fix-up's worktree started with both sides and git's markers in the file
    assert "<<<<<<<" in brain.prompts["T2-merge"] or "shared.txt" in brain.prompts["T2-merge"]
    assert (root / "shared.txt").read_text(encoding="utf-8") == "from one\nfrom two\n"
    assert all(t.status == "done" for t in tasks.values())
    assert not any((root / ".harness" / "worktrees").glob("*"))  # both worktrees went once it landed


def test_the_money_limit_stops_all_three_and_they_resume(tmp_path):
    holder = {}

    def spend_it_all(tid):
        if tid == "T1":  # every task is past its first turn: the run's money is gone
            holder["orch"].budget.limit_usd = holder["orch"].budget.spent_usd

    brain = ParallelBrain(THREE, meet=3, on_second_turn=spend_it_all)
    orch, *_ = make(tmp_path, raw=raw(3), brain=brain)
    holder["orch"] = orch
    orch.start("three files")
    assert orch.run() == "paused_budget"
    root = orch.project.root
    assert {t.status for t in orch.project.tasks()} == {"pending"}
    trees = Worktrees(root)
    for tid in ("T1", "T2", "T3"):
        assert trees.exists(tid) and (trees.path(tid) / f"{tid.lower()}.txt").is_file()  # the work is kept
    ev = events_of(orch)
    assert {e["task"] for e in ev if e["event"] == "worktree_kept"} == {"T1", "T2", "T3"}
    assert not (root / "t1.txt").exists()  # nothing half-done landed in the project

    brain.meet, brain.on_second_turn = None, None
    orch.raise_budget(20)
    assert orch.run() == "done"
    assert all((root / f"t{n}.txt").is_file() for n in (1, 2, 3))
    reused = [e for e in events_of(orch) if e["event"] == "worktree" and e.get("reused")]
    assert {e["task"] for e in reused} == {"T1", "T2", "T3"}  # carried on where they stopped


def test_a_stop_from_outside_stops_every_task(tmp_path):
    holder = {}

    def stop(tid):
        if tid == "T2":
            holder["orch"].stop_all("breaker", "a helper kept doing the same thing")

    brain = ParallelBrain(THREE, meet=3, on_second_turn=stop)
    orch, *_ = make(tmp_path, raw=raw(3), brain=brain)
    holder["orch"] = orch
    orch.start("three files")
    assert orch.run() == "paused"
    meta = orch.project.meta()
    assert meta["status"] == "paused" and meta["pause"] == "breaker"
    assert {t.status for t in orch.project.tasks()} == {"pending"}


def test_one_at_a_time_is_unchanged(tmp_path):
    orch, *_ = make(tmp_path, raw=raw(1), brain=ParallelBrain(THREE))
    orch.start("three files")
    assert orch._parallel_width() == 1
    assert orch.run() == "done"
    ev = events_of(orch)
    assert not any(e["event"] in ("worktree", "merged", "parallel") for e in ev)
    assert not (orch.project.root / ".harness" / "worktrees").exists()
    # the task's own events still say which task they belong to
    assert all(e.get("task") for e in ev if e["event"] in ("model_turn", "tool_call") and e.get("role") == "coder")


def test_a_project_without_git_stays_one_at_a_time(tmp_path):
    r = raw(3)
    r["workspace"] = {"git": False}
    orch, *_ = make(tmp_path, raw=r, brain=ParallelBrain(THREE))
    orch.start("three files")
    assert orch._parallel_width() == 1
    assert orch.run() == "done"


def test_repository_mode_keeps_its_branch(tmp_path):
    root = make_repo(tmp_path)
    main_before = git(root, "rev-parse", "main")
    orch, *_ = make(tmp_path, raw=raw(3), brain=ParallelBrain(THREE))
    orch.start("Add three files")
    branch = orch.project.meta()["repository"]["branch"]
    assert orch.run() == "done"
    assert git(root, "rev-parse", "main") == main_before  # nothing landed on main
    assert git(root, "symbolic-ref", "--short", "HEAD") == branch
    subjects = git(root, "log", "--format=%s", branch)
    assert "[T1] one" in subjects and "[T3] three" in subjects
    assert "roundtable-task/" not in git(root, "branch", "--list")
    assert ".harness" not in git(root, "ls-files")


def test_a_failed_task_keeps_its_worktree_and_says_why(tmp_path):
    brain = ParallelBrain(THREE, reject={"T2"})
    orch, *_ = make(tmp_path, raw=raw(3, max_attempts_per_task=1, split_stuck_tasks=False), brain=brain)
    orch.start("three files")
    assert orch.run() == "blocked"
    tasks = {t.id: t for t in orch.project.tasks()}
    assert tasks["T1"].status == "done" and tasks["T3"].status == "done" and tasks["T2"].status == "failed"
    kept = [e for e in events_of(orch) if e["event"] == "worktree_kept"]
    assert [e["task"] for e in kept] == ["T2"] and "retry" in kept[0]["why"]
    assert Worktrees(orch.project.root).exists("T2")

    # the owner accepts it as it is: its work comes in and the worktree goes
    orch.accept("T2")
    assert (orch.project.root / "t2.txt").is_file()
    assert not Worktrees(orch.project.root).exists("T2")


def test_a_dirty_worktree_is_never_removed(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    (root / ".gitignore").write_text(".harness/\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "first")
    trees = Worktrees(root)
    path, reused = trees.add("A b/c", git(root, "rev-parse", "HEAD"))
    assert not reused and path.name == safe_name("A b/c") == "A-b-c"
    (path / "work.txt").write_text("unsaved\n", encoding="utf-8")
    removed, why = trees.remove("A b/c")
    assert not removed and "never committed" in why and (path / "work.txt").is_file()
    assert trees.commit("A b/c", "save it")
    assert trees.merge_into_project("A b/c", "bring it in").ok
    removed, _ = trees.remove("A b/c")
    assert removed and not path.exists()


def test_a_worktree_baseline_is_the_repositorys_only_from_the_same_commit(tmp_path):
    (tmp_path / "ok.py").write_text("print('FAILED tests/test_x.py::test_old - boom')\nraise SystemExit(1)\n",
                                    encoding="utf-8")
    import sys

    values = {"test": f'"{sys.executable}" ok.py', "setup": "", "env": {}, "timeout": 60}
    repo = {"command": values["test"], "commit": "abc", "passed": True, "failing": []}
    same = checkslib.prepare_worktree(tmp_path, values, "abc", repo)
    assert same["baseline"] is repo
    moved = checkslib.prepare_worktree(tmp_path, values, "def", repo)
    assert moved["baseline"]["failing"] == ["tests/test_x.py::test_old"] and moved["baseline"]["worktree"]


def test_the_breaker_stops_one_task_and_the_others_carry_on(tmp_path, monkeypatch):
    from roundtable.harness import orchestrator as orchmod
    from roundtable.harness.agent import AgentResult
    from roundtable.providers.base import Usage

    real = orchmod.run_agent
    tripped = []

    def run_agent(cfg, ref, system, prompt, box, budget, **kw):
        if "# Your task [T2]" in prompt and not tripped:
            tripped.append(1)
            return AgentResult(text="", steps=3, usage=Usage(), cost_usd=0.0, model=str(ref), stop="breaker",
                               breaker_reason="it kept reading the same file")
        return real(cfg, ref, system, prompt, box, budget, **kw)

    monkeypatch.setattr(orchmod, "run_agent", run_agent)
    brain = ParallelBrain(THREE)
    orch, *_ = make(tmp_path, raw=raw(3), brain=brain)
    orch.start("three files")
    assert orch.run() == "done"
    tasks = {t.id: t for t in orch.project.tasks()}
    assert [a["outcome"] for a in tasks["T2"].attempts] == ["breaker", "approved"]
    assert len(tasks["T1"].attempts) == 1 and len(tasks["T3"].attempts) == 1  # not stopped with it
    assert "stopped by the safety check: it kept reading the same file." in brain.prompts["T2"]


def test_every_task_gets_a_gate_keyed_to_the_project(tmp_path, monkeypatch):
    from roundtable.harness import orchestrator as orchmod

    seen = {}
    real = orchmod.Orchestrator._run_task

    def spy(self, task, tasks):
        gate = self.ws.gate
        seen[task.id] = (self.ws.root, gate.root, gate.context(), gate.timeout)
        return real(self, task, tasks)

    monkeypatch.setattr(orchmod.Orchestrator, "_run_task", spy)
    orch, *_ = make(tmp_path, raw=raw(3), brain=ParallelBrain(THREE))
    orch.ws.gate.timeout = 0  # as the lab's replays do
    orch.start("three files")
    assert orch.run() == "done"
    root = orch.project.root
    for tid in ("T1", "T2", "T3"):
        ws_root, gate_root, ctx, timeout = seen[tid]
        assert ws_root == Worktrees(root).path(tid) and gate_root == root  # cards in one place
        assert ctx["id"] == tid and timeout == 0
