"""d2-unstick: a stuck task is worked out by a model from another maker, not handed straight to the owner.

Every project here is made up, in tmp_path; the models are scripted (no network, no keys).
"""

import json

from roundtable.harness import handoff
from roundtable.harness import unstick
from roundtable.harness.orchestrator import Orchestrator
from roundtable.harness.unstick import UnstickStage, maker
from roundtable.harness.config import parse_config
from roundtable.providers.base import ProviderError
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider, reply

from .test_harness import RAW, Brain, tool_names
from .test_parallel import ParallelBrain, raw as parallel_raw


class O(UnstickStage, Orchestrator):
    """With the cards it raised kept (there's no hub here for _attention to write to)."""

    def _attention(self, key, text, details=""):
        self.__dict__.setdefault("cards", {}).setdefault(key, text)
        super()._attention(key, text, details)

    def _resolved(self, *keys, note=""):
        for k in keys:
            self.__dict__.setdefault("cards", {}).pop(k, None)
        super()._resolved(*keys, note=note)


def task(tid, title, deps=(), desc=None):
    return {"id": tid, "title": title, "role": "coder", "description": desc or f"write {tid.lower()}.py",
            "acceptance": f"{tid} works", "depends_on": list(deps)}


# T2 always fails; T3 doesn't need it; T4 waits for it
PLAN4 = [task("T1", "start"), task("T2", "the stuck one"), task("T3", "unrelated"), task("T4", "after two", ["T2"])]
CAUSE = "The test needs a data file that isn't there."


class Stuck(Brain):
    def __init__(self, action="park", plan=None, fixable=False, replan=None, fail_diagnosis=False, slow=False):
        super().__init__(plan=plan or PLAN4)
        self.action, self.fixable, self.replan, self.fail_diagnosis = action, fixable, replan, fail_diagnosis
        self.slow = slow
        self.diagnosed, self.prompts, self.fixed, self.replans = [], {}, False, []

    def __call__(self, model, system, messages, tools):
        names = tool_names(tools)
        last, first = messages[-1], messages[0]["content"]
        if "diagnose" in names:
            if last["role"] == "tool":
                return reply("ok")
            if self.fail_diagnosis:
                raise ProviderError("the diagnoser's service is down")
            if self.slow:  # looks around first (and never gets to answer under a tiny cap)
                return reply(calls=[("list_files", {"path": "."})])
            self.diagnosed.append(model)
            args = {"cause": CAUSE, "action": self.action, "advice": "Create data.txt before the test."}
            if self.action == "needs_owner":
                args["owner_question"] = "Which file should it read?"
            return reply(calls=[("diagnose", args)])
        if "submit_plan" in names and self.replan is not None and "# Your job\nRevise" in first:
            if last["role"] == "tool":
                return reply("planned")
            self.replans.append(first)
            return reply(calls=[("submit_plan", {"tasks": self.replan})])
        if "finish_task" in names and last["role"] == "user":
            tid = first.split("# Your task [", 1)[1].split("]", 1)[0]
            self.prompts.setdefault(tid, []).append(first)
            if tid == "T2" and self.fixable and "handover" in first.lower():
                self.fixed = True
        if ("submit_review" in names and last["role"] != "tool" and "# Task [T2]" in first
                and not self.fixed):
            return reply(calls=[("submit_review", {"approved": False, "feedback": "T2's test still fails"})])
        return super().__call__(model, system, messages, tools)


def raw(reviewer=("a/reviewer",), coder_fallback=False, **unstick_cfg):
    r = json.loads(json.dumps(RAW))
    if not coder_fallback:
        r["roles"]["coder"].pop("fallback")
    r["roles"]["reviewer"] = {"model": reviewer[0], **({"fallback": list(reviewer[1:])} if len(reviewer) > 1 else {})}
    for m in reviewer:
        r["pricing"].setdefault(m, {"input": 1, "output": 1})
    r["limits"]["max_attempts_per_task"] = 2
    if unstick_cfg:
        r["unstick"] = unstick_cfg
    return r


def build(tmp_path, brain, cfg_raw=None, cls=None):
    cfg = parse_config(json.loads(json.dumps(cfg_raw or raw())))
    a, b = ScriptedProvider("a", brain), ScriptedProvider("b", brain)
    for name, p in (("a", a), ("b", b), ("img", ScriptedImages())):
        cfg.register(name, p)
    events = []
    orch = (cls or O)(cfg, tmp_path / "proj", on_event=lambda k, d: events.append((k, d)))
    return orch, a, b, events


def todos(orch):
    return dict(orch.__dict__.get("cards") or {})


def by_id(orch):
    return {t.id: t for t in orch.project.tasks()}


# -- who diagnoses -------------------------------------------------------------------------------------------
def test_maker_reads_routers_and_model_names():
    assert maker("openrouter/anthropic/claude-x") == "anthropic"
    assert maker("deepseek/deepseek-v4-flash") == "deepseek"
    assert maker("myproxy/claude-opus") == "anthropic"
    assert maker("a/coder") == "a"


def test_the_diagnoser_is_from_another_maker_when_there_is_one(tmp_path):
    brain = Stuck("park")
    orch, a, b, _ = build(tmp_path, brain, raw(reviewer=("a/reviewer", "b/second")))
    orch.start("a made-up tool")
    orch.approve()
    assert orch.run() == "blocked"
    assert brain.diagnosed == ["second"]  # the coder is a's model: b's diagnoses
    d = unstick.diagnoses(orch.project.root)["T2"]
    assert d["model"] == "b/second" and d["same_maker"] is False


def test_the_same_maker_is_used_and_said_when_no_other_exists(tmp_path):
    brain = Stuck("park")
    orch, *_ = build(tmp_path, brain)
    orch.start("a made-up tool")
    orch.approve()
    orch.run()
    assert brain.diagnosed == ["reviewer"]
    assert unstick.diagnoses(orch.project.root)["T2"]["same_maker"] is True


# -- the five actions ---------------------------------------------------------------------------------------
def test_park_carries_on_with_the_rest_then_asks_once(tmp_path):
    brain = Stuck("park")
    orch, _, _, events = build(tmp_path, brain)
    orch.start("a made-up tool")
    orch.approve()
    assert orch.run() == "blocked"
    t = by_id(orch)
    assert (t["T1"].status, t["T2"].status, t["T3"].status, t["T4"].status) == ("done", "failed", "done", "pending")
    assert t["T2"].parked == CAUSE
    keys = set(todos(orch))
    assert "stuck" in keys and not any(k.startswith("failed:") for k in keys)  # one card, no per-task cards
    ask = unstick.stuck_ask(orch, orch.project.tasks())
    assert ask["kind"] == "stuck" and ask["question"].startswith("1 of 4 tasks couldn't be finished")
    assert CAUSE in ask["detail"]
    ids = [o["id"] for o in ask["options"]]
    assert ids == ["retry", "without", "stop"]  # no Quality setting here: no stronger model to offer
    without = next(o for o in ask["options"] if o["id"] == "without")
    assert "T2 “the stuck one”" in without["description"] and "1 task that needed them still runs" in without["description"]
    assert ("unstick", {"task": "T2", "action": "park", "cause": CAUSE, "model": "a/reviewer",
                        "same_maker": True}) in events
    assert handoff.read(orch.project.root, "T2").startswith("# Handover: [T2]")


def test_needs_owner_parks_it_and_the_card_carries_the_question(tmp_path):
    brain = Stuck("needs_owner")
    orch, *_ = build(tmp_path, brain)
    orch.start("a made-up tool")
    orch.approve()
    assert orch.run() == "blocked"
    assert by_id(orch)["T2"].parked == CAUSE
    ask = unstick.stuck_ask(orch, orch.project.tasks())
    assert "Which file should it read?" in ask["detail"]
    assert ask["tasks"][0]["owner_question"] == "Which file should it read?"


def test_retry_with_advice_puts_the_handover_in_the_next_attempt(tmp_path):
    brain = Stuck("retry_with_advice", fixable=True)
    orch, *_ = build(tmp_path, brain)
    orch.start("a made-up tool")
    orch.approve()
    assert orch.run() == "done"
    t2 = by_id(orch)["T2"]
    assert t2.status == "done" and not t2.parked
    retry_prompt = brain.prompts["T2"][-1]
    assert "A handover from the earlier try at this task" in retry_prompt
    assert "Create data.txt before the test." in retry_prompt and CAUSE in retry_prompt
    assert "T2's test still fails" in retry_prompt  # the last review is in it


def test_split_hands_over_to_the_new_tasks(tmp_path):
    replan = [task("T3", "unrelated"), task("T2a", "first half"), task("T2b", "second half", ["T2a"]),
              task("T4", "after two", ["T2b"])]
    brain = Stuck("split", replan=replan)
    orch, _, _, events = build(tmp_path, brain)
    orch.start("a made-up tool")
    orch.approve()
    assert orch.run() == "done"
    t = by_id(orch)
    assert "T2" not in t and t["T2a"].handoff_from == "T2" and t["T2b"].handoff_from == "T2"
    assert "Replace it with 2 to 4 smaller tasks" in brain.replans[0]
    assert "A handover from task T2" in brain.prompts["T2a"][0]
    dropped = unstick.dropped(orch.project.root)
    assert [r["task"] for r in dropped] == ["T2"] and dropped[0]["attempts"]  # nothing is lost
    assert "task_split" in [k for k, _ in events]


def test_replan_around_keeps_done_tasks_and_writes_the_dropped_one(tmp_path):
    replan = [task("T3", "unrelated"), task("T5", "another way"), task("T4", "after two", ["T5"])]
    brain = Stuck("replan_around", replan=replan)
    orch, *_ = build(tmp_path, brain)
    orch.start("a made-up tool")
    orch.approve()
    assert orch.run() == "done"
    t = by_id(orch)
    assert t["T1"].status == "done" and "T2" not in t
    assert t["T5"].handoff_from == "T2" and "A handover from task T2" in brain.prompts["T5"][0]
    assert "without task T2" in brain.replans[0]
    rows = unstick.dropped(orch.project.root)
    assert rows[0]["task"] == "T2" and rows[0]["why"] == "replan_around" and len(rows[0]["attempts"]) == 2
    assert unstick.wasted(orch.project.tasks(), orch.project.root) > 0  # T2's tries bought nothing


def test_a_replan_that_fails_parks_the_task(tmp_path):
    brain = Stuck("split")  # no replan given: the planner answers with the first plan, which re-adds T1 (done)
    orch, *_ = build(tmp_path, brain)
    orch.start("a made-up tool")
    orch.approve()

    def broken(*a, **kw):
        raise RuntimeError("the planner is down")
    orch.revise_plan = broken
    assert orch.run() == "blocked"
    assert by_id(orch)["T2"].parked == CAUSE and "stuck" in todos(orch)


# -- the caps ------------------------------------------------------------------------------------------------
def test_once_per_task(tmp_path):
    brain = Stuck("retry_with_advice")  # the advice doesn't help: it fails again
    orch, *_ = build(tmp_path, brain)
    orch.start("a made-up tool")
    orch.approve()
    assert orch.run() == "blocked"
    assert brain.diagnosed == ["reviewer"]  # not a second time
    assert "failed:T2" in todos(orch)  # nothing left to work out: its own card, as before


def test_at_most_max_per_run(tmp_path):
    plan = [task("T1", "x"), task("T2", "y"), task("T3", "z")]

    class AllFail(Stuck):
        def __call__(self, model, system, messages, tools):
            names = tool_names(tools)
            if "submit_review" in names and messages[-1]["role"] != "tool":
                return reply(calls=[("submit_review", {"approved": False, "feedback": "no"})])
            return super().__call__(model, system, messages, tools)

    brain = AllFail("park", plan=plan)
    orch, *_ = build(tmp_path, brain, raw(max_per_run=2))
    orch.start("a made-up tool")
    orch.approve()
    assert orch.run() == "blocked"
    assert len(brain.diagnosed) == 2
    assert set(unstick.diagnoses(orch.project.root)) == {"T1", "T2"}


def test_a_diagnosis_stops_at_its_money_cap(tmp_path):
    brain = Stuck("park", slow=True)
    orch, *_ = build(tmp_path, brain, raw(max_usd_per_task=0.000001))
    orch.start("a made-up tool")
    orch.approve()
    assert orch.run() == "blocked"
    d = unstick.diagnoses(orch.project.root)["T2"]
    assert "action" not in d and d["cost_usd"] > 0  # its first turn cost more than the cap: no second
    assert "failed:T2" in todos(orch) and "stuck" not in todos(orch)


def test_the_money_gate_stops_the_diagnosis(tmp_path):
    class Gated(O):
        def _money_gate(self):
            return "paused" if any(t.status == "failed" for t in self.project.tasks()) else None

    brain = Stuck("park")
    o, *_ = build(tmp_path, brain, cls=Gated)
    o.start("a made-up tool")
    o.approve()
    o.run()
    assert brain.diagnosed == []


def test_a_provider_error_in_the_diagnosis_leaves_todays_behaviour(tmp_path):
    brain = Stuck("park", fail_diagnosis=True)
    orch, _, _, events = build(tmp_path, brain)
    orch.start("a made-up tool")
    orch.approve()
    assert orch.run() == "blocked"
    assert not by_id(orch)["T2"].parked
    assert "failed:T2" in todos(orch) and "stuck" not in todos(orch)
    assert "unstick_error" in [k for k, _ in events]
    assert by_id(orch)["T3"].status == "done"


def test_off_in_settings(tmp_path):
    brain = Stuck("park")
    orch, *_ = build(tmp_path, brain, raw(enabled=False))
    orch.start("a made-up tool")
    orch.approve()
    orch.run()
    assert brain.diagnosed == [] and "failed:T2" in todos(orch)


# -- the card's answers -------------------------------------------------------------------------------------
def _stuck(tmp_path):
    orch, *_ = build(tmp_path, Stuck("park"))
    orch.start("a made-up tool")
    orch.approve()
    orch.run()
    return orch, unstick.stuck_ask(orch, orch.project.tasks())


def test_carry_on_without_them_skips_them_and_closes_the_card(tmp_path):
    orch, ask = _stuck(tmp_path)
    r = unstick.apply_stuck(orch, ask, ["without"], "")
    assert r["then"] == "run" and "T2" in r["reply"]
    t2 = by_id(orch)["T2"]
    assert t2.status == "done" and not t2.parked and "stuck" not in todos(orch)


def test_try_again_and_typed_words(tmp_path):
    orch, ask = _stuck(tmp_path)
    r = unstick.apply_stuck(orch, ask, [], "Use the sample file in data/.")
    assert r["then"] == "run"
    t2 = by_id(orch)["T2"]
    assert t2.status == "pending" and not t2.parked
    assert any("Use the sample file" in json.dumps(x) for x in orch.chat_history())


def test_stop_leaves_it(tmp_path):
    orch, ask = _stuck(tmp_path)
    r = unstick.apply_stuck(orch, ask, ["stop"], "")
    assert r["then"] is None and by_id(orch)["T2"].status == "failed"


def test_the_stronger_model_is_offered_with_a_confirm(tmp_path):
    r = raw()
    r["profiles"] = {"quality": {"roles": {"coder": {"model": "b/coder2"}}}}
    r["pricing"]["b/coder2"] = {"input": 1, "output": 1}
    orch, *_ = build(tmp_path, Stuck("park"), r)
    orch.start("a made-up tool")
    orch.approve()
    orch.run()
    ask = unstick.stuck_ask(orch, orch.project.tasks())
    first = ask["options"][0]
    assert first["id"] == "stronger" and first["confirm"] and ask["recommended"] == "stronger"
    unstick.apply_stuck(orch, ask, ["stronger"], "")
    t2 = by_id(orch)["T2"]
    assert t2.status == "pending" and t2.stronger


# -- the estimate and the report ----------------------------------------------------------------------------
def test_the_estimate_counts_a_small_allowance(tmp_path):
    orch, *_ = build(tmp_path, Stuck("park"))
    orch.start("a made-up tool")
    orch.plan()
    extras = orch.project.plan_doc()["estimate"]["extras"]
    e = next(x for x in extras if x["id"] == "unstick")
    assert 0 < e["usd"] <= 0.15 and "1 stuck task" in e["words"]


def test_wasted_counts_failed_and_skipped_work():
    class T:
        def __init__(self, tid, status, cost, summary=""):
            self.id, self.status, self.summary = tid, status, summary
            self.attempts = [{"cost_usd": cost}]

    tasks = [T("A", "done", 1.0), T("B", "failed", 0.25), T("C", "done", 0.5, "(skipped by owner)")]
    assert unstick.wasted(tasks) == 0.75
    assert "spent with nothing finished: $0.75 (on B, C)" in unstick.wasted_words(tasks)
    assert unstick.wasted_words(tasks[:1]) == ""


def test_wasted_counts_dropped_tasks(tmp_path):
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness/dropped-tasks.jsonl").write_text(json.dumps({"task": "Z", "cost_usd": 0.5}) + "\n")
    assert unstick.wasted([], tmp_path) == 0.5
    assert "$0.50 (on Z)" in unstick.wasted_words([], tmp_path)


# -- the parallel path ---------------------------------------------------------------------------------------
def test_parallel_a_parked_task_lets_the_rest_finish_then_one_card(tmp_path):
    plan = [task("T1", "one"), task("T2", "two"), task("T3", "three", ["T2"])]

    class PB(ParallelBrain):
        diagnosed: list = []

        def __call__(self, model, system, messages, tools):
            if "diagnose" in {t.name for t in tools}:
                if messages[-1]["role"] == "tool":
                    return reply("ok")
                self.diagnosed.append(model)
                return reply(calls=[("diagnose", {"cause": CAUSE, "action": "park", "advice": "later"})])
            return super().__call__(model, system, messages, tools)

    brain = PB(plan, reject={"T2"})
    r = parallel_raw(2)
    r["limits"]["max_attempts_per_task"] = 1
    orch, *_ = build(tmp_path, brain, r)
    orch.start("a made-up tool")
    orch.approve()
    assert orch.run() == "blocked"
    t = by_id(orch)
    assert (t["T1"].status, t["T2"].status, t["T3"].status) == ("done", "failed", "pending")
    assert t["T2"].parked == CAUSE and brain.diagnosed == ["reviewer"]
    keys = set(todos(orch))
    assert "stuck" in keys and "failed:T2" not in keys


# -- the exit: a planted always-failing task asks once, at the end --------------------------------------------
def test_an_always_failing_task_waits_until_everything_else_is_built(tmp_path):
    plan = [task("T1", "a"), task("T2", "the stuck one"), task("T3", "b"), task("T4", "c", ["T3"]),
            task("T5", "d")]
    brain = Stuck("park", plan=plan)
    orch, _, _, events = build(tmp_path, brain)
    orch.start("a made-up tool")
    orch.approve()
    assert orch.run() == "blocked"
    assert [t.status for t in orch.project.tasks()] == ["done", "failed", "done", "done", "done"]
    stuck_at = next(i for i, (k, d) in enumerate(events) if k == "unstick")
    last_end = max(i for i, (k, d) in enumerate(events) if k == "task_end")
    assert stuck_at < last_end  # worked out mid-run, the rest built after it
    assert [k for k in todos(orch)] == ["stuck"]


# -- the coordinator's hook-ups, tried here before they're made ----------------------------------------------
def test_the_card_answers_through_asks_with_its_confirm(tmp_path, monkeypatch):
    import pytest

    from roundtable import asks
    from roundtable.harness.orchestrator import HarnessError

    r = raw()
    r["profiles"] = {"quality": {"roles": {"coder": {"model": "b/coder2"}}}}
    orch, *_ = build(tmp_path, Stuck("park"), r)
    orch.start("a made-up tool")
    orch.approve()
    orch.run()
    monkeypatch.setattr(asks, "APPLY", {**asks.APPLY, "stuck": unstick.apply_stuck})
    monkeypatch.setattr(asks, "_failed_asks", lambda o, meta, tasks: (
        [c] if (c := unstick.stuck_ask(o, tasks)) and meta.get("status") == "blocked" else []))
    cards = asks.open_asks(orch)
    assert [c["id"] for c in cards] == ["stuck"]
    with pytest.raises(HarnessError, match="Are you sure"):
        asks.answer_ask(orch, "stuck", ["stronger"])
    got = asks.answer_ask(orch, "stuck", ["stronger"], confirmed=True)
    assert got["then"] == "run" and by_id(orch)["T2"].stronger


def test_a_too_big_split_hands_over_too(tmp_path):
    orch, *_ = build(tmp_path, Stuck("park", plan=[task("T1", "big"), task("T2", "next")]))
    orch.start("a made-up tool")
    orch.plan()
    t1 = by_id(orch)["T1"]
    orch._handoff_split(t1, ["T2"])
    assert "too big for one attempt" in handoff.read(orch.project.root, "T1")
    assert by_id(orch)["T2"].handoff_from == "T1"
    assert "A handover from task T1" in orch._worker_prompt(by_id(orch)["T2"], orch.project.tasks(), [])
