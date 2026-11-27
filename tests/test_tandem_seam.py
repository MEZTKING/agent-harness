"""Step 0 of wave 6 (models in tandem): the seam the tandem stages hook into.

A bare ``Seam`` (the Orchestrator without its stage mixins) and the full Orchestrator at "lean" behave
exactly as before; each new hook is used only when a stage defines it. Also: privacy in one place
(makers.py), the budget's lock and its "who spent it", the dial's stub. Every project is made up, in
tmp_path; the models are scripted (the maker is the provider id).
"""

import json
import threading

import pytest

from roundtable.harness import dial, makers, plandoc
from roundtable.harness import projectsettings as ps
from roundtable.harness.agent import Budget, BudgetExceeded
from roundtable.harness.config import FEATURE_SECTIONS, ModelRef
from roundtable.harness.orchestrator import HarnessError, Orchestrator, _validate_plan

from .test_harness import Brain
from .test_stage_hooks import ONE, STAGES, Seam, build, kinds

NEW_HOOKS = ("_tags_plan_part", "_council_schema", "_council_doc", "_dial_doc", "_agent_worker_part",
             "_router_estimate", "_dial_estimate", *Orchestrator.ATTEMPT_PARTS, *Orchestrator.METRIC_PARTS,
             "_rivals_run", "_route_models", "_panel_review", "_council_plan", "_usage_blocked", "_usage_use")
OLD_ATTEMPT = {"model", "outcome", "summary", "review", "cost_usd"}
OLD_METRIC = {"at", "task", "role", "model", "outcome", "steps", "seconds", "input_tokens", "output_tokens",
              "cost_usd", "saved_tokens_est"}


class NoKind(Orchestrator):
    def _kind_proof(self):
        return []  # the kind guessed for a made-up project would bring its own checks


def _run(tmp_path, cls, brain=None, level=None):
    orch, events, brain = build(tmp_path, cls=cls, brain=brain or Brain(plan=ONE))
    orch.start("a made-up tool")
    orch.plan()
    if level:
        meta = orch.project.meta()
        meta["checking"] = level
        orch.project.save_meta(meta)
    assert orch.run() == "done"
    return orch, events, brain


def _shape(orch):
    """What a run left behind, without times and money."""
    tasks = [(t.id, t.status, [(a["model"], a["outcome"], sorted(a)) for a in t.attempts])
             for t in orch.project.tasks()]
    rows = [json.loads(x) for x in (orch.project.root / ".harness/metrics.jsonl").read_text().splitlines()]
    return tasks, [(r["model"], r["outcome"], sorted(r)) for r in rows]


# -- the new hooks are names only -------------------------------------------------------------------------------
def test_the_new_hooks_are_listed_and_only_the_stages_define_them():
    assert "_tags_plan_part" in Orchestrator.PLAN_PARTS and "_council_schema" in Orchestrator.SCHEMA_PARTS
    assert {"_council_doc", "_dial_doc"} <= set(Orchestrator.DOC_PARTS)
    assert "_agent_worker_part" in Orchestrator.WORKER_PARTS
    assert {"_router_estimate", "_dial_estimate"} <= set(Orchestrator.ESTIMATE_PARTS)
    # wave 6's own, in order; wave 7 adds its names after them (tests/test_learn_seam.py)
    assert Orchestrator.ATTEMPT_PARTS[:4] == ("_router_attempt", "_panel_attempt", "_rivals_attempt", "_agent_attempt")
    assert Orchestrator.METRIC_PARTS[:3] == ("_tags_metric", "_rivals_metric", "_agent_metric")
    for name in NEW_HOOKS:
        assert not callable(getattr(Seam, name, None)), name  # the bare seam has none of them
        assert name not in vars(Orchestrator), name  # the full one has them only from its stages (wave 6)
        owner = next((c for c in Orchestrator.__mro__ if name in vars(c)), None)
        assert owner is None or owner in STAGES, (name, owner)


def test_a_bare_seam_runs_exactly_as_before(tmp_path):
    orch, events, brain = _run(tmp_path, Seam)
    (tid, status, attempts), = _shape(orch)[0]
    assert status == "done" and attempts == [("a/coder", "approved", sorted(OLD_ATTEMPT))]
    assert _shape(orch)[1] == [("a/coder", "approved", sorted(OLD_METRIC))]
    t = orch.project.tasks()[0]
    assert (t.tags, t.hard, t.risky, t.why_hard) == ([], False, False, "")
    assert not {"stage_error"} & set(kinds(events))
    assert all("rival" not in d for _, d in events)
    assert orch.budget.on_use is None
    doc = orch.project.plan_doc()
    assert "council" not in doc and "critique" in doc or orch.cfg.critic_role is None
    assert not (orch.project.root / dial.LEDGER).exists()


def test_the_full_orchestrator_at_lean_runs_exactly_as_the_bare_seam(tmp_path):
    bare, _, _ = _run(tmp_path / "bare", Seam)
    full, events, _ = _run(tmp_path / "full", NoKind, level="lean")
    assert dial.level(full) == "lean"
    assert _shape(full) == _shape(bare)
    assert not {"stage_error"} & set(kinds(events))


def test_a_plan_made_before_1_2_0_is_lean_and_a_new_one_takes_the_setting(tmp_path):
    orch, _, _ = build(tmp_path, brain=Brain(plan=ONE))
    orch.start("a made-up tool")
    assert dial.level(orch) == "lean"  # no meta["checking"]: made before 1.2.0
    orch.plan()
    assert orch.project.meta()["checking"] == "balanced" == dial.level(orch)
    orch.cfg.sections["tandem"] = {"default": "maximum"}
    assert dial.level_for_new_plan(orch) == "maximum"
    # the plan is balanced: an ordinary task gets one builder and one checker, and may try a newer model
    assert dial.for_task(orch, orch.project.tasks()[0]) == {"rivals": 1, "panel": 1, "explore": True, "why": ""}
    # the council asks before a new plan's level is written: the next plan's level (maximum) answers
    assert dial.for_plan(orch) == {"planners": 3} and dial.allow(orch, "panel", 1.0)
    dial.spent(orch, "panel", 0.01, "T1")
    row = json.loads((orch.project.root / dial.LEDGER).read_text().splitlines()[0])
    assert (row["what"], row["usd"], row["task"]) == ("panel", 0.01, "T1")


# -- each hook, once a stage defines it ------------------------------------------------------------------------
class Staged(Seam):
    route = None
    blocked: set = frozenset()

    def _route_models(self, task, role, models):
        return self.route

    def _usage_blocked(self, ref):
        return str(ref) in self.blocked

    def _router_attempt(self, task, ref):
        return {"routed": {"from": "a/coder", "why": "test"}}

    def _tags_metric(self, task, ref):
        return {"tags": list(task.tags)}


def test_attempt_and_metric_parts_are_merged(tmp_path):
    orch, _, _ = _run(tmp_path, Staged)
    t = orch.project.tasks()[0]
    assert t.attempts[-1]["routed"] == {"from": "a/coder", "why": "test"}
    row = json.loads((orch.project.root / ".harness/metrics.jsonl").read_text().splitlines()[-1])
    assert row["tags"] == []


def test_a_routed_model_is_used_only_when_the_project_allows_it(tmp_path):
    orch, _, _ = build(tmp_path, cls=Staged, brain=Brain(plan=ONE))
    orch.start("a made-up tool")
    orch.plan()
    task = orch.project.tasks()[0]
    role = orch.cfg.roles["coder"]
    b = ModelRef("b", "coder2")
    orch.route = [b]
    assert orch._routed(task, role, role.models) == [b]
    ps.update(orch.project.root, {"providers_allowed": ["a"]})
    assert not orch._may_use(b) and orch._may_use(ModelRef("a", "coder"))
    assert orch._routed(task, role, role.models) == role.models  # b is not allowed: the router is ignored
    orch.route = []
    assert orch._routed(task, role, role.models) == role.models
    orch.route = "not a list"
    assert orch._routed(task, role, role.models) == role.models


def test_a_model_whose_limit_is_reached_is_skipped(tmp_path):
    class Blocked(Staged):
        blocked = {"a/coder"}

    orch, _, _ = _run(tmp_path, Blocked)
    assert [a["model"] for a in orch.project.tasks()[0].attempts] == ["b/coder2"]


def test_rivals_run_replaces_the_usual_way(tmp_path):
    class Rivals(Seam):
        def _rivals_run(self, task, tasks):
            task.summary = "picked r1"
            return True

    orch, events, brain = _run(tmp_path, Rivals)
    assert orch.project.tasks()[0].summary == "picked r1"
    assert "attempt" not in kinds(events)


def test_an_attempt_without_review_is_built_with_no_metrics_row(tmp_path):
    orch, events, brain = build(tmp_path, brain=Brain(plan=ONE))
    orch.start("a made-up tool")
    orch.plan()
    tasks = orch.project.tasks()
    task = tasks[0]
    assert orch._attempt_loop(task, tasks, [ModelRef("b", "coder2")], review=False, attempts=1) is True
    assert [(a["model"], a["outcome"]) for a in task.attempts] == [("b/coder2", "built")]
    assert task.summary
    assert not (orch.project.root / ".harness/metrics.jsonl").exists()
    assert "review" not in kinds(events)


def test_the_panel_hook_and_one_review_with_breaks(tmp_path):
    seen = {}

    class Panel(Seam):
        def _panel_review(self, task, summary, checks, stronger, built_by):
            seen["built_by"] = str(built_by)
            ok, fb, res, verdict = self._review_once(task, summary, checks, self.cfg.roles["reviewer"].models,
                                                     note="You are one of two checkers.")
            seen["verdict"] = verdict
            return ok, fb, res

    orch, _, brain = _run(tmp_path, Panel)
    assert seen["built_by"] == "a/coder" and seen["verdict"]["approved"] is True


def test_the_review_tool_offers_breaks(tmp_path):
    captured = {}

    class Spy(Brain):
        def __call__(self, model, system, messages, tools):
            for t in tools:
                if t.name == "submit_review":
                    captured["schema"] = t.input_schema if hasattr(t, "input_schema") else t.parameters
            return super().__call__(model, system, messages, tools)

    _run(tmp_path, Seam, brain=Spy(plan=ONE))
    props = captured["schema"]["properties"]
    assert "breaks" in props and captured["schema"]["required"] == ["approved", "feedback"]


def test_the_council_plans_and_the_critique_is_left_out(tmp_path):
    calls = []

    class Council(Seam):
        def _council_plan(self, job, existing):
            calls.append("council")
            return self._plan_call(job, existing, role=self.cfg.planner_role)

        def _council_doc(self, doc, args):
            doc["council"] = {"planners": ["a/planner"], "chair": "a/planner"}

        def _critique(self):
            calls.append("critique")

    orch, _, _ = build(tmp_path, cls=Council, brain=Brain(plan=ONE))
    orch.start("a made-up tool")
    orch.plan()
    assert calls == ["council"]
    assert orch.project.plan_doc()["council"]["chair"] == "a/planner"


def test_a_stage_money_stop_with_pause_pauses_the_run(tmp_path):
    class CapReached(BudgetExceeded):
        pause = "service_cap"

    class Capped(Seam):
        def _usage_blocked(self, ref):
            if str(ref) == "a/coder":
                raise CapReached("The cap for service a is reached: this run waits for you")
            return False

    orch, events, _ = build(tmp_path, cls=Capped, brain=Brain(plan=ONE))
    orch.start("a made-up tool")
    orch.plan()
    assert orch.run() == "paused"
    meta = orch.project.meta()
    assert meta["status"] == "paused" and meta.get("pause") == "service_cap"


def test_emit_says_which_rival(tmp_path):
    orch, events, _ = build(tmp_path)
    orch._tl.task, orch._tl.rival = "T1", "r2"
    orch.emit("note", {"x": 1})
    assert events[-1] == ("note", {"task": "T1", "x": 1, "rival": "r2"})


def test_the_planner_can_give_tags_and_mark_a_task_hard_or_risky(tmp_path):
    from .test_harness import RAW
    from roundtable.harness.config import parse_config

    roles = parse_config(json.loads(json.dumps(RAW))).roles
    raw = [dict(ONE[0], tags=["UI", "Game Logic", "ui", "a", "b", "c", "d", "e"], hard=True, risky="yes",
                why_hard="many moving parts")]
    t, = _validate_plan(raw, roles, [])
    assert t.tags == ["ui", "game-logic", "a", "b", "c", "d"] and t.hard and not t.risky
    assert t.why_hard == "many moving parts"
    orch, _, _ = build(tmp_path)
    props = plandoc.submission_schema(orch._task_schema())["properties"]["tasks"]["items"]
    assert {"tags", "hard", "risky", "why_hard"} <= set(props["properties"])
    assert not {"tags", "hard", "risky", "why_hard"} & set(props["required"])


def test_plan_call_takes_a_role(tmp_path):
    orch, _, brain = build(tmp_path, brain=Brain(plan=ONE))
    orch.start("x")
    new, args = orch._plan_call("# Your job\nplan it", [], role=orch.cfg.roles[orch.cfg.planner_role])
    assert [t.id for t in new] == ["T1"]
    with pytest.raises(KeyError):
        orch._plan_call("plan", [], role="no-such-role")


# -- privacy in one place -------------------------------------------------------------------------------------
def test_who_made_a_model():
    assert makers.maker("openrouter/anthropic/claude-x") == "anthropic"
    assert makers.maker("deepseek/deepseek-v4-flash") == "deepseek"
    assert makers.maker(ModelRef("custom", "gpt-9")) == "openai"
    assert makers.maker("a/coder") == "a"
    from roundtable.harness import unstick

    assert unstick.maker is makers.maker


def test_allowed_needs_both_lists():
    keep = {"providers_allowed": ["openrouter"], "makers_allowed": ["anthropic"]}
    assert makers.allowed(keep, "openrouter/anthropic/claude-x")
    assert not makers.allowed(keep, "openrouter/openai/gpt-x")  # the right service, the wrong maker
    assert not makers.allowed(keep, "anthropic/claude-x")  # the right maker, the wrong service
    assert makers.allowed({}, "anything/model") and makers.allowed({"makers_allowed": []}, "a/b")
    assert "openai" in makers.why_not(keep, "openrouter/openai/gpt-x")
    assert "providers_allowed" in makers.why_not(keep, "anthropic/claude-x")
    assert makers.why_not(keep, "openrouter/anthropic/claude-x") == ""


def test_distinct_keeps_one_per_maker():
    refs = ["a/one", "b/two", "a/three", "openrouter/anthropic/claude-x", "anthropic/claude-y"]
    assert makers.distinct(refs) == ["a/one", "b/two", "openrouter/anthropic/claude-x"]
    assert makers.distinct(refs, not_maker="a") == ["b/two", "openrouter/anthropic/claude-x"]


def test_makers_allowed_keeps_a_project_to_some_makers(tmp_path):
    assert "makers_allowed" in ps.BY_KEY
    orch, _, _ = build(tmp_path, brain=Brain(plan=ONE))
    ps.update(orch.project.root, {"makers_allowed": ["b"]})
    c = orch._settle_cfg(orch.base_cfg)
    assert [str(m) for m in c.roles["coder"].models] == ["b/coder2"]
    assert c.roles["reviewer"].models == []
    with pytest.raises(HarnessError) as e:
        orch._require_models(c.roles["reviewer"])
    assert "makers_allowed" in str(e.value) and "made by b" in str(e.value)
    assert not orch._may_use(ModelRef("a", "coder")) and orch._may_use(ModelRef("b", "coder2"))


# -- the budget: its own lock, and who spent it ----------------------------------------------------------------
def test_the_budget_says_who_spent_it_and_is_safe_from_threads():
    seen = []
    b = Budget(limit_usd=100)
    b.on_charge = lambda c: seen.append(("charge", c))
    b.on_use = lambda ref, usage, cost, role: seen.append(("use", str(ref), cost, role))
    b.charge(0.5, ref=ModelRef("a", "coder"), role="coder")
    b.charge(None, ref="a/x")
    assert seen == [("charge", 0.5), ("use", "a/coder", 0.5, "coder"), ("use", "a/x", None, None)]
    assert b.unpriced_calls == 1

    b2 = Budget(limit_usd=1e9)

    def many():
        for _ in range(2000):
            b2.charge(0.001)

    threads = [threading.Thread(target=many) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert round(b2.spent_usd, 6) == 16.0


def test_the_full_orchestrator_passes_who_spent_to_a_usage_stage(tmp_path):
    uses = []

    class Usage(Seam):
        def _usage_use(self, ref, usage, cost, role):
            uses.append((str(ref), role))

    orch, _, _ = _run(tmp_path, Usage)
    assert ("a/coder", "coder") in uses and ("a/reviewer", "reviewer") in uses
    assert any(r == "orchestrator" for _, r in uses)


# -- the small ones ---------------------------------------------------------------------------------------------
def test_the_feature_sections_and_carry_over():
    assert {"tandem", "router", "panel", "rivals", "council", "usage", "agents"} <= set(FEATURE_SECTIONS)
    old = {"decisions": [], "questions": [], "dont": [], "ideas": [], "council": {"chair": "x"},
           "checking_estimates": {"lean": 1}}
    new = plandoc.carry_over({"decisions": [], "questions": [], "dont": [], "ideas": []}, old)
    assert new["council"] == {"chair": "x"} and new["checking_estimates"] == {"lean": 1}
