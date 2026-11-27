"""Best of several (rivals.py): two or three models build a hard task side by side, the tests and one checker
pick the best, only that work goes in, and the others are kept as branches with the reason.

Every project here is made up, in tmp_path; the models are scripted (the maker is the provider id: ``a``, ``b``
and ``c``). The dial's stub always says one builder, so each test sets how many it gives a hard task.
"""

import json
import subprocess
import sys
import threading

import pytest

from roundtable.harness import dial
from roundtable.harness.agent import BudgetExceeded
from roundtable.harness.config import parse_config
from roundtable.harness.orchestrator import Orchestrator
from roundtable.harness.rivals import RivalsStage
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider, reply

from .test_harness import RAW

PRICE = 0.00012  # one scripted call: 100 tokens in and 20 out at $1 a million each

HARD = {"id": "T1", "title": "the answer", "role": "coder", "description": "write out.txt with the answer",
        "acceptance": "out.txt holds the answer", "depends_on": [], "hard": True}
EASY = {"id": "T2", "title": "notes", "role": "coder", "description": "write notes.txt", "acceptance": "exists",
        "depends_on": []}


class O(RivalsStage, Orchestrator):
    def _kind_proof(self):
        return []  # the kind guessed for a made-up project would bring its own checks


def raw(**over):
    r = json.loads(json.dumps(RAW))
    r["providers"]["c"] = {"type": "scripted"}
    r["roles"]["reviewer"] = {"model": "c/rev", "fallback": ["a/reviewer"]}
    r["pricing"]["c/rev"] = {"input": 1, "output": 1}
    for k, v in over.items():
        if isinstance(v, dict):
            r.setdefault(k, {}).update(v)
        else:
            r[k] = v
    return r


class Brain:
    """``coder`` (maker a) writes A's answer, ``coder2`` (maker b) writes B's; the checker picks ``pick``."""

    def __init__(self, plan, pick="B", reject_first=False, before_first=None):
        self.plan = plan
        self.pick = pick
        self.reject_first = reject_first
        self.before_first = before_first or {}  # model -> callable run before its first worker turn
        self.picks, self.reviews, self.worker = [], [], []
        self.lock = threading.Lock()

    def __call__(self, model, system, messages, tools):
        names = {t.name for t in tools}
        last = messages[-1]
        prompt = messages[0]["content"]
        if "submit_plan" in names:
            return reply("planned") if last["role"] == "tool" else reply(calls=[("submit_plan", {"tasks": self.plan})])
        if "pick_best" in names:
            if last["role"] == "tool":
                return reply("ok")
            with self.lock:
                self.picks.append((model, prompt))
            return reply(calls=[("pick_best", {"best": self.pick, "why": f"{self.pick} reads more clearly",
                                               "problems": "the other one is wordy"})])
        if "submit_review" in names:
            if last["role"] == "tool":
                return reply("ok")
            with self.lock:
                self.reviews.append(model)
                ok = not (self.reject_first and len(self.reviews) == 1)
            return reply(calls=[("submit_review", {"approved": ok, "feedback": "fine" if ok else "add a newline"})])
        if "finish_task" in names:
            tid = prompt.split("# Your task [", 1)[1].split("]", 1)[0]
            if last["role"] == "user":
                hook = self.before_first.pop(model, None)
                if hook:
                    hook()
                with self.lock:
                    self.worker.append((model, tid))
                name = "out.txt" if tid == "T1" else f"{tid.lower()}.txt"
                text = {"coder": "A\n", "coder2": "B\n"}.get(model, "?\n")
                return reply(calls=[("write_file", {"path": name, "content": text})])
            return reply(calls=[("finish_task", {"summary": f"{tid} done"})])
        return reply("Final report: all done.")


def build(tmp_path, brain, raw_cfg=None, settings=""):
    cfg = parse_config(raw_cfg or raw())
    for name in ("a", "b", "c"):
        cfg.register(name, ScriptedProvider(name, brain))
    cfg.register("img", ScriptedImages())
    events = []
    orch = O(cfg, tmp_path / "proj", on_event=lambda k, d: events.append((k, d)))
    if settings:
        (orch.project.root / ".harness").mkdir(parents=True, exist_ok=True)
        (orch.project.root / ".harness" / "project.yaml").write_text(settings, encoding="utf-8")
    return orch, events


@pytest.fixture
def rivals(monkeypatch):
    """The dial gives a hard task ``n`` builders (2 unless a test says otherwise)."""
    state = {"n": 2}

    def for_task(orch, task):
        return {"rivals": state["n"] if task.hard else 1, "panel": 1, "explore": False,
                "why": "hard" if task.hard else ""}

    monkeypatch.setattr(dial, "for_task", for_task)
    return state


def start(orch):
    orch.start("a made-up answer file")
    orch.plan()
    orch.approve()


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True).stdout


def events_of(events, kind):
    return [d for k, d in events if k == kind]


def check_script(root, bad="B"):
    """A test command that fails once out.txt holds ``bad`` (it passes before anything is built)."""
    (root / "check.py").parent.mkdir(parents=True, exist_ok=True)
    (root / "check.py").write_text(
        "import pathlib, sys\np = pathlib.Path('out.txt')\n"
        f"sys.exit(1 if p.exists() and p.read_text().strip() == {bad!r} else 0)\n", encoding="utf-8")
    return f'test: \'"{sys.executable}" check.py\'\n'


def no_leftovers(root):
    wt = root / ".harness" / "worktrees"
    assert not wt.exists() or not any(wt.iterdir())


# -- picking ---------------------------------------------------------------------------------------------------
def test_one_rival_breaks_a_test_and_the_other_wins_with_no_pick_call(tmp_path, rivals):
    brain = Brain([HARD])
    orch, events = build(tmp_path, brain, settings=check_script(tmp_path / "proj", bad="B"))
    start(orch)
    assert orch.run() == "done"
    root = orch.project.root
    assert (root / "out.txt").read_text() == "A\n"
    assert brain.picks == []  # the tests decided: no pick call
    assert sorted(m for m, _ in brain.worker) == ["coder", "coder2"]
    (t,) = orch.project.tasks()
    (att,) = t.attempts
    assert att["outcome"] == "approved" and att["rival"] == "r1"
    by_id = {r["id"]: r for r in att["rivals"]}
    assert by_id["r1"]["picked"] and by_id["r1"]["tests"] == "passed"
    assert not by_id["r2"]["picked"] and by_id["r2"]["why"] == "broke a test that passed before"
    assert by_id["r2"]["branch"] == "roundtable-task/T1-r2"
    no_leftovers(root)


def test_both_pass_and_the_checker_picks_b(tmp_path, rivals):
    brain = Brain([HARD], pick="B")
    orch, events = build(tmp_path, brain, settings=check_script(tmp_path / "proj", bad="nothing"))
    start(orch)
    assert orch.run() == "done"
    root = orch.project.root
    assert (root / "out.txt").read_text() == "B\n"  # B's work is in the project
    # A's is only on its branch, with a patch beside it
    assert "roundtable-task/T1-r1" in git(root, "branch", "--list")
    assert git(root, "show", "roundtable-task/T1-r1:out.txt") == "A\n"
    patch = root / ".harness" / "rivals" / "T1" / "r1.patch"
    assert patch.is_file() and "+A" in patch.read_text()
    # the winner's own branch went once it was in; no folder is left behind
    assert "roundtable-task/T1-r2" not in git(root, "branch", "--list")
    no_leftovers(root)
    # one pick call, by the maker that built neither (c), seeing letters and no model names
    ((picker, prompt),) = brain.picks
    assert picker == "rev"
    assert "# Attempt A" in prompt and "# Attempt B" in prompt and "coder2" not in prompt and "+B" in prompt
    # the reason is shown: the event, the record and the kept branch's note
    (picked,) = events_of(events, "rivals_picked")
    assert picked["winner"] == "r2" and picked["why"] == "B reads more clearly" and "same_maker" not in picked
    (kept,) = events_of(events, "rival_kept")
    assert kept["rival"] == "r1" and kept["why"] == "another model's attempt was chosen: B reads more clearly"
    rec = json.loads((root / ".harness" / "rivals.json").read_text())["T1"][-1]
    assert rec["winner"] == "r2" and rec["problems"] == "the other one is wordy"
    # the winner was checked the normal way, by the reviewer
    assert brain.reviews == ["rev"]
    (att,) = orch.project.tasks()[0].attempts
    assert att["model"] == "b/coder2" and att["outcome"] == "approved" and att["rival"] == "r2"
    # the metrics: the winner's row carries rival and rivals: 2, the loser has a rival_lost row
    rows = [json.loads(x) for x in (root / ".harness" / "metrics.jsonl").read_text().splitlines()]
    win = next(r for r in rows if r["outcome"] == "approved")
    lost = next(r for r in rows if r["outcome"] == "rival_lost")
    assert (win["model"], win["rival"], win["rivals"]) == ("b/coder2", "r2", 2)
    assert (lost["model"], lost["rival"]) == ("a/coder", "r1") and lost["cost_usd"] == pytest.approx(2 * PRICE)
    # every event of a rival's conversation says which rival it is
    assert {d.get("rival") for k, d in events if k == "attempt" and d.get("task") == "T1"} == {"r1", "r2"}


def test_the_spend_counted_is_the_sum_of_the_rivals_charges(tmp_path, rivals):
    brain = Brain([HARD], pick="A")
    orch, _ = build(tmp_path, brain)
    start(orch)
    before = orch.budget.spent_usd
    assert orch.run() == "done"
    root = orch.project.root
    rec = json.loads((root / ".harness" / "rivals.json").read_text())["T1"][-1]
    builds = sum(r["cost_usd"] for r in rec["rivals"])
    assert builds == pytest.approx(4 * PRICE)  # two calls each: write, finish
    assert rec["pick_cost_usd"] == pytest.approx(PRICE)
    ledger = [json.loads(x) for x in (root / dial.LEDGER).read_text().splitlines()]
    assert [(r["what"], r["task"]) for r in ledger] == [("rivals", "T1")]
    loser = next(r for r in rec["rivals"] if not r["picked"])
    assert ledger[0]["usd"] == pytest.approx(loser["cost_usd"] + rec["pick_cost_usd"])
    # everything the round spent went through the run's one budget: builds, pick, review, the final report
    review = 1 * PRICE
    report = 1 * PRICE
    assert orch.budget.spent_usd - before == pytest.approx(builds + rec["pick_cost_usd"] + review + report)


def test_a_winner_rejected_by_review_carries_on_in_the_usual_loop(tmp_path, rivals):
    brain = Brain([HARD], pick="B", reject_first=True)
    orch, events = build(tmp_path, brain)
    start(orch)
    assert orch.run() == "done"
    (t,) = orch.project.tasks()
    assert [a["outcome"] for a in t.attempts] == ["rejected", "approved"]
    assert t.attempts[0]["rival"] == "r2" and "rival" not in t.attempts[1]
    assert t.attempts[1]["model"] == "b/coder2"  # the winner carries on first
    # it carried on from the winner's work, told what the reviewer said
    assert (orch.project.root / "out.txt").read_text() == "B\n"


def test_when_no_rival_passes_the_usual_loop_has_the_remaining_tries(tmp_path, rivals):
    brain = Brain([HARD])
    orch, events = build(tmp_path, brain, settings=check_script(tmp_path / "proj", bad="A"))

    real = brain.__call__

    def both_break(model, system, messages, tools):
        resp = real(model, system, messages, tools)
        for c in resp.tool_calls:  # both rivals write a broken answer; the usual loop writes a good one
            if c.name == "write_file" and getattr(threading.current_thread(), "name", "").startswith(
                    "roundtable-rival"):
                c.arguments["content"] = "A\n"
            elif c.name == "write_file":
                c.arguments["content"] = "C\n"
        return resp

    for name in ("a", "b", "c"):
        orch.cfg.provider(name).script = both_break
    start(orch)
    assert orch.run() == "done"
    (t,) = orch.project.tasks()
    assert t.attempts[0]["outcome"] == "rivals_failed" and t.attempts[-1]["outcome"] == "approved"
    assert len(t.attempts) <= orch.cfg.limits.max_attempts_per_task
    assert (orch.project.root / "out.txt").read_text() == "C\n"
    assert len(events_of(events, "rival_kept")) == 2 and brain.picks == []


# -- when it runs ----------------------------------------------------------------------------------------------
def test_inside_a_parallel_lane(tmp_path, rivals):
    brain = Brain([HARD, EASY], pick="B")
    orch, events = build(tmp_path, brain, raw_cfg=raw(limits={"max_parallel": 2}))
    start(orch)
    assert orch.run() == "done"
    assert events_of(events, "parallel")
    root = orch.project.root
    assert (root / "out.txt").read_text() == "B\n" and (root / "t2.txt").is_file()
    assert [m for m, tid in brain.worker if tid == "T2"] == ["coder"]  # the easy task: one builder
    assert "roundtable-task/T1-r1" in git(root, "branch", "--list")
    assert "roundtable-task/T1-r2" not in git(root, "branch", "--list")
    no_leftovers(root)
    (start_ev,) = events_of(events, "rivals_start")
    assert start_ev["task"] == "T1"


def test_a_money_stop_mid_rival_pauses_the_run_and_leaves_the_task_pending(tmp_path, rivals):
    b_raised = threading.Event()

    def b_stops():
        b_raised.set()
        raise BudgetExceeded("budget exhausted: made-up limit")

    brain = Brain([HARD], before_first={"coder2": b_stops, "coder": lambda: b_raised.wait(5)})
    orch, events = build(tmp_path, brain)
    start(orch)
    assert orch.run() == "paused_budget"
    (t,) = orch.project.tasks()
    assert t.status == "pending"
    assert orch.budget.__dict__.get("check") is None and orch._halt is None  # disarmed after the round
    no_leftovers(orch.project.root)
    assert not (orch.project.root / "out.txt").exists()  # nothing went in
    assert len(events_of(events, "rival_kept")) == 2


def test_a_project_with_no_git_runs_the_usual_way(tmp_path, rivals):
    brain = Brain([HARD])
    orch, events = build(tmp_path, brain, raw_cfg=raw(workspace={"git": False}))
    start(orch)
    assert orch.run() == "done"
    assert [m for m, _ in brain.worker] == ["coder"] and not events_of(events, "rivals_start")


def test_a_model_the_project_does_not_allow_is_never_a_rival(tmp_path, rivals):
    brain = Brain([HARD])
    orch, events = build(tmp_path, brain, settings="makers_allowed: [a, c]\n")
    start(orch)
    assert orch.run() == "done"
    assert all(m != "coder2" for m, _ in brain.worker)
    assert not events_of(events, "rivals_start")
    assert events_of(events, "rivals_skipped")[0]["why"] == "fewer than two models this project may use"


def test_rivals_never_uses_a_model_the_project_does_not_allow(tmp_path, rivals):
    rivals["n"] = 3
    r = raw()
    r["providers"]["d"] = {"type": "scripted"}
    r["roles"]["coder"]["fallback"] = ["b/coder2", "d/coder3"]
    r["pricing"]["d/coder3"] = {"input": 1, "output": 1}
    brain = Brain([HARD], pick="A")
    cfg_orch, events = build(tmp_path, brain, raw_cfg=r, settings="providers_allowed: [a, b, c]\n")
    cfg_orch.cfg.register("d", ScriptedProvider("d", brain))
    start(cfg_orch)
    assert cfg_orch.run() == "done"
    (s,) = events_of(events, "rivals_start")
    assert [x["model"] for x in s["rivals"]] == ["a/coder", "b/coder2"]
    assert all(m != "coder3" for m, _ in brain.worker)


def test_lean_or_an_easy_task_is_the_usual_way(tmp_path):
    brain = Brain([HARD])  # the dial's stub: one builder for everything
    orch, events = build(tmp_path, brain)
    start(orch)
    assert orch.run() == "done"
    assert [m for m, _ in brain.worker] == ["coder"] and not events_of(events, "rivals_start")
    rows = [json.loads(x) for x in (orch.project.root / ".harness" / "metrics.jsonl").read_text().splitlines()]
    assert all("rival" not in r for r in rows)


def test_the_extra_checking_allowance_saying_no_builds_the_usual_way(tmp_path, rivals, monkeypatch):
    seen = []
    monkeypatch.setattr(dial, "allow", lambda orch, what, usd: seen.append((what, usd)) or False)
    brain = Brain([HARD])
    orch, events = build(tmp_path, brain)
    start(orch)
    assert orch.run() == "done"
    assert seen == [("rivals", None)]  # no builds yet to price it from
    assert [m for m, _ in brain.worker] == ["coder"]


def test_a_second_round_never_reuses_an_old_rivals_branch(tmp_path, rivals):
    brain = Brain([HARD], pick="B")
    orch, events = build(tmp_path, brain)
    start(orch)
    assert orch.run() == "done"
    orch.retry("T1")
    brain.pick = "A"
    assert orch.run() == "done"
    (s1, s2) = events_of(events, "rivals_start")
    assert [x["id"] for x in s1["rivals"]] == ["r1", "r2"]
    assert [x["id"] for x in s2["rivals"]] == ["r3", "r4"]
    root = orch.project.root
    assert git(root, "show", "roundtable-task/T1-r1:out.txt") == "A\n"  # the first round's loser is still there
    assert len(json.loads((root / ".harness" / "rivals.json").read_text())["T1"]) == 2
