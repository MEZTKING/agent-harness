"""The checking dial (harness/dial.py): one level per project, its price before anything runs, its own share of
the money, and who built, who checked and who disagreed (ui/tandemapi.py).

The "within 10 % at every level" test runs on the full Orchestrator with the real stages (rivals, panel, council,
router, agents, usage); the other tests use scripted stand-ins that ask the dial and write the attempt keys
documented in dial.py. Every project is made up,
in tmp_path; the models are scripted (the maker is the provider id).
"""

import json
from pathlib import Path

import pytest

from roundtable.harness import dial, makers, plandoc
from roundtable.harness.config import parse_config
from roundtable.harness.orchestrator import Orchestrator, Task
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider

from .test_harness import Brain
from .test_stage_hooks import Seam

PRICE = {"input": 100, "output": 100}
RAW = {
    "providers": {"a": {"type": "scripted"}, "b": {"type": "scripted"}, "c": {"type": "scripted"},
                  "img": {"type": "scripted_images"}},
    "roles": {
        "orchestrator": {"model": "a/planner"},
        "coder": {"model": "a/coder", "fallback": ["b/coder2", "c/coder3"], "description": "writes code"},
        "reviewer": {"model": "a/reviewer", "fallback": ["b/reviewer2", "c/reviewer3"]},
    },
    "pricing": {m: PRICE for m in ("a/planner", "a/coder", "b/coder2", "c/coder3", "a/reviewer", "b/reviewer2",
                                   "c/reviewer3")},
    "limits": {"max_cost_usd": 50, "max_attempts_per_task": 3},
}


def plan_of(*kinds):
    out = []
    for i, k in enumerate(kinds, 1):
        out.append({"id": f"T{i}", "title": f"part {i}", "role": "coder", "description": f"write part {i}",
                    "acceptance": "exists", "depends_on": [], "hard": k == "hard", "risky": k == "risky"})
    return out


# -- scripted stand-ins for the rival and panel stages (they ask the dial and write its attempt keys) -----------
class StandIns:
    def _usage_use(self, ref, usage, cost, role):  # every charge, by job: the planner's are left out of a run's spend
        self.__dict__.setdefault("charges", []).append((str(ref), role, cost or 0.0))

    def _rivals_run(self, task, tasks):
        d = dial.for_task(self, task)
        if d["rivals"] < 2:
            return None
        role = self.cfg.roles[task.role]
        pool = [m for m in makers.distinct(role.models) if self._may_use(m)]
        others = pool[1:d["rivals"]]
        if not others or not dial.allow(self, "rivals", dial.task_cost(self, task, "rivals")):
            return None
        before = self.budget.spent_usd
        rows = [{"id": "r1", "model": str(pool[0]), "maker": makers.maker(pool[0]), "picked": True,
                 "why": "the checker liked it best", "tests": "passed"}]
        for i, ref in enumerate(others, 2):
            self._tl.rival = f"r{i}"
            try:
                self._attempt_loop(task, tasks, [ref], review=False)
            finally:
                self._tl.rival = None
            rows.append({"id": f"r{i}", "model": str(ref), "maker": makers.maker(ref), "picked": False,
                         "why": "", "tests": "passed"})
        reviewer = self.cfg.roles[self.cfg.reviewer_role]
        built = {makers.maker(m) for m in [pool[0], *others]}
        picker = [m for m in reviewer.models if makers.maker(m) not in built] or reviewer.models
        self._review_once(task, task.summary or "", None, picker[:1])  # the pick call
        dial.spent(self, "rivals", self.budget.spent_usd - before, task.id)
        self.__dict__.setdefault("rival_rows", {})[task.id] = rows
        return self._attempt_loop(task, tasks, pool[:1])

    def _rivals_attempt(self, task, ref):
        rows = getattr(self, "rival_rows", {}).get(task.id)
        if getattr(self._tl, "rival", None):
            return {"rival": self._tl.rival}
        return {"rival": "r1", "rivals": rows} if rows else None

    def _rivals_metric(self, task, ref):
        return {"rival": "r1"} if getattr(self, "rival_rows", {}).get(task.id) else None

    def _panel_review(self, task, summary, checks, stronger, built_by):
        d = dial.for_task(self, task)
        if d["panel"] < 2:
            return None
        reviewer = self.cfg.roles[self.cfg.reviewer_role]
        pool = makers.distinct([m for m in reviewer.models if self._may_use(m)],
                               not_maker=makers.maker(built_by) if built_by else "")
        ok, fb, res, _ = self._review_once(task, summary, checks, pool[:1])
        reviews = [{"model": str(pool[0]), "maker": makers.maker(pool[0]), "approved": ok, "feedback": fb,
                    "breaks": "", "counted": True}]
        one = (dial.task_cost(self, task, "panel") or 0) / (1 + dial.third_share(self.cfg, dial.level(self)))
        if len(pool) > 1 and dial.allow(self, "panel", one):
            ok2, fb2, res2, _ = self._review_once(task, summary, checks, pool[1:2])
            reviews.append({"model": str(pool[1]), "maker": makers.maker(pool[1]), "approved": ok2, "feedback": fb2,
                            "breaks": "", "counted": True})
            dial.spent(self, "panel", res2.cost_usd if res2 else 0, task.id)
            if res and res2:
                res.cost_usd += res2.cost_usd
            ok = ok and ok2
        self.__dict__.setdefault("panel_rows", {})[task.id] = {"reviews": reviews, "disagreed": False,
                                                                "same_maker": False}
        return ok, fb, res

    def _panel_attempt(self, task, ref):
        return getattr(self, "panel_rows", {}).pop(task.id, None)


class Approving:
    """Orchestrator.approve calls the hook itself now (after _money_agreed); kept so the classes read as before."""


class Dialled(Approving, StandIns, dial.DialStage, Seam):
    pass


class NoKind(Orchestrator):
    def _kind_proof(self):
        return []


class FullDialled(Approving, *((NoKind,) if issubclass(NoKind, dial.DialStage) else (dial.DialStage, NoKind))):
    pass


def build(tmp_path, cls=Dialled, plan=None, raw=RAW, name="proj", tandem=None):
    raw = json.loads(json.dumps(raw))
    if tandem:
        raw["tandem"] = tandem
    cfg = parse_config(raw)
    brain = Brain(plan=plan or plan_of("ordinary"))
    for p in ("a", "b", "c"):
        cfg.register(p, ScriptedProvider(p, brain))
    cfg.register("img", ScriptedImages())
    events = []
    orch = cls(cfg, tmp_path / name, on_event=lambda k, d: events.append((k, d)))
    return orch, events


def history(tmp_path, plan):
    """A lean run of the same made-up plan first: the past the estimate reads."""
    orch, _ = build(tmp_path, plan=plan, name="before", tandem={"default": "lean"})
    orch.start("a made-up tool")
    orch.plan()
    orch.approve()
    assert orch.run() == "done"
    return (orch.project.dir / "metrics.jsonl").read_text(encoding="utf-8")


def run_spend(orch):
    return sum(c for _, role, c in getattr(orch, "charges", []) if role != orch.cfg.planner_role)


# -- the level ----------------------------------------------------------------------------------------------
def test_a_project_planned_before_the_dial_is_lean_and_its_estimate_is_unchanged(tmp_path):
    plan = plan_of("hard", "risky", "ordinary")
    plain, _ = build(tmp_path, cls=Seam, plan=plan, name="plain")
    plain.start("a made-up tool")
    plain.plan()
    orch, _ = build(tmp_path, plan=plan)
    orch.start("a made-up tool")
    orch.plan()
    meta = orch.project.meta()
    del meta["checking"]  # made before 1.2.0
    orch.project.save_meta(meta)
    assert dial.level(orch) == "lean"
    t = orch.project.tasks()[0]
    assert t.hard and dial.for_task(orch, t) == {"rivals": 1, "panel": 1, "explore": False, "why": ""}
    assert not dial.allow(orch, "panel", 0.01)
    old = plain._estimate(plain.project.tasks())
    new = orch._estimate(orch.project.tasks())
    assert new["cost_usd"] == old["cost_usd"] and new["extras"] == old["extras"] == []
    assert dial.words(orch) == "Checking: Lean"


def test_a_new_plan_is_balanced_and_only_hard_and_risky_tasks_carry_extras(tmp_path):
    orch, _ = build(tmp_path, plan=plan_of("ordinary", "hard", "risky", "ordinary"))
    orch.start("a made-up tool")
    orch.plan()
    doc = orch.project.plan_doc()
    assert orch.project.meta()["checking"] == "balanced" == doc["checking"]
    tasks = {t.id: t for t in orch.project.tasks()}
    assert dial.for_task(orch, tasks["T1"]) == {"rivals": 1, "panel": 1, "explore": True, "why": ""}
    assert dial.for_task(orch, tasks["T2"]) == {"rivals": 2, "panel": 2, "explore": False, "why": "hard"}
    assert dial.for_task(orch, tasks["T3"]) == {"rivals": 1, "panel": 2, "explore": False, "why": "risky"}
    line = next(e for e in doc["estimate"]["extras"] if e["id"] == "dial")
    assert line["words"].startswith("extra checking on 2 hard or risky tasks: about $")
    assert dial.words(orch) == f"Checking: Balanced (about ${line['usd']:.2f} of this)"
    # the plan card's three prices, before approval: Maximum the dearest and its planners counted
    est = doc["checking_estimates"]
    assert set(est) == set(dial.LEVELS)
    assert est["lean"]["cost_usd"] < est["balanced"]["cost_usd"] < est["maximum"]["cost_usd"]
    assert est["lean"]["extra_usd"] == 0 and est["maximum"]["planning_usd"] > 0
    assert est["balanced"]["cost_usd"] == doc["estimate"]["cost_usd"]
    p = dial.price(orch.cfg, list(tasks.values()), "balanced")
    assert p["tasks"] == 2 and p["parts"]["rivals"] > 0 and p["parts"]["panel"] > 0


def test_the_table_takes_overrides_and_lean_cannot_be_switched_on(tmp_path):
    orch, _ = build(tmp_path, plan=plan_of("hard"), tandem={
        "default": "maximum", "maximum": {"hard": {"rivals": 2}, "planners": 2},
        "lean": {"hard": {"rivals": 3}}})
    orch.start("a made-up tool")
    assert dial.for_plan(orch) == {"planners": 2}
    orch.plan()
    t = orch.project.tasks()[0]
    assert dial.for_task(orch, t) == {"rivals": 2, "panel": 3, "explore": False, "why": "hard"}
    assert dial.table(orch.cfg, "lean")["hard"]["rivals"] == 1


def test_the_project_setting_wins_then_the_owners_choice_then_the_default(tmp_path, monkeypatch):
    orch, _ = build(tmp_path, tandem={"default": "maximum"})
    orch.start("a made-up tool")
    assert dial.level_for_new_plan(orch) == "maximum"
    meta = orch.project.meta()
    meta["checking_chosen"] = "lean"
    orch.project.save_meta(meta)
    assert dial.level_for_new_plan(orch) == "lean"

    class S:
        values = {"checking": "balanced"}

    monkeypatch.setattr(orch, "project_settings", lambda: S())
    assert dial.level_for_new_plan(orch) == "balanced"


# -- the price against a scripted run ------------------------------------------------------------------------
def test_history_leaves_out_rival_rows(tmp_path):
    f = tmp_path / "m.jsonl"
    rows = [{"task": f"T{i}", "role": "coder", "cost_usd": 0.5, "seconds": 60, "at": "2026-11-20T10:00:00Z"}
            for i in range(3)]
    rows += [{"task": "T9", "role": "coder", "cost_usd": 9.0, "seconds": 600, "rival": "r1", "at": "2026-11-20"},
             {"task": "T9", "role": "coder", "cost_usd": 9.0, "seconds": 600, "outcome": "rival_lost",
              "at": "2026-11-20"}]
    f.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    h = plandoc.history_by_role([f])
    assert h["coder"]["samples"] == 3 and h["coder"]["cost"] == 0.5


# -- its own share of the money ----------------------------------------------------------------------------
def test_the_allowance_stops_the_extras_and_the_run_still_finishes(tmp_path):
    plan = plan_of("hard", "hard", "hard")
    past = history(tmp_path, plan)
    orch, events = build(tmp_path, plan=plan, tandem={"allowance_over": 0.6, "allowance_least_usd": 0})
    orch.start("a made-up tool")
    (orch.project.dir / "metrics.jsonl").write_text(past, encoding="utf-8")
    orch.plan()
    orch.approve()
    a = dial.read_allowance(orch.project.root)
    line = next(e for e in orch.project.plan_doc()["estimate"]["extras"] if e["id"] == "dial")
    assert a["usd"] == round(line["usd"] * 0.6, 4) and a["level"] == "balanced"
    assert orch.run() == "done"
    t1, _, t3 = orch.project.tasks()
    assert [x["outcome"] for x in t1.attempts] == ["built", "approved"] and len(t1.attempts[-1]["reviews"]) == 2
    assert [x["outcome"] for x in t3.attempts] == ["approved"] and "reviews" not in t3.attempts[0]
    assert all(t.status == "done" for t in orch.project.tasks())
    assert dial.spent_since(orch.project.root, a) <= a["usd"] + 1e-9
    assert [k for k, _ in events].count("tandem_allowance") == 1
    assert dial.read_allowance(orch.project.root)["used_up"]
    assert dial.for_task(orch, t3)["rivals"] == 1 and not dial.allow(orch, "panel", 0.0)


def test_the_allowance_is_never_less_than_a_quarter_dollar_and_planning_is_not_held_back(tmp_path):
    orch, _ = build(tmp_path, plan=plan_of("ordinary"))
    orch.start("a made-up tool")
    orch.plan()
    assert dial.allow(orch, "council", 5.0)  # before approval there is no allowance yet: the money gate holds
    orch.approve()
    assert dial.read_allowance(orch.project.root)["usd"] == 0.25
    assert dial.allow(orch, "panel", 0.2) and not dial.allow(orch, "panel", 0.3)


def test_maximum_after_approval_meets_the_money_card(tmp_path):
    raw = json.loads(json.dumps(RAW))
    raw["pricing"] = {m: {"input": 1, "output": 1} for m in raw["pricing"]}
    raw["money"] = {"over_estimate": 0.0, "over_estimate_min_usd": 0.0}
    orch, events = build(tmp_path, cls=FullDialled, plan=plan_of("ordinary", "hard"), raw=raw)
    orch.start("a made-up tool")
    orch.plan()
    orch.approve()
    agreed = orch.project.meta()["agreed"]["usd"]
    ask = dial.confirm(orch, "maximum")
    assert ask["ask"] and ask["to_usd"] > ask["from_usd"] and ask["planning_usd"] > 0
    assert "instead of about" in ask["words"] and "Three planners" in ask["words"]
    assert not dial.confirm(orch, "lean")["ask"]
    got = dial.set_checking(orch, "maximum")
    assert got["level"] == "maximum" and orch.project.meta()["checking_chosen"] == "maximum"
    doc = orch.project.plan_doc()
    assert doc["checking"] == "maximum" and doc["estimate"]["cost_usd"] > agreed
    assert dial.read_allowance(orch.project.root)["level"] == "maximum"
    assert orch.run() == "paused"
    meta = orch.project.meta()
    assert meta.get("pause") == "over_estimate"


def test_set_checking_refuses_a_level_it_does_not_know(tmp_path):
    from roundtable.harness.orchestrator import HarnessError

    orch, _ = build(tmp_path)
    orch.start("a made-up tool")
    orch.plan()
    with pytest.raises(HarnessError):
        dial.set_checking(orch, "huge")


def test_autopilot_never_changes_the_level():
    src = Path(__file__).resolve().parents[1] / "src" / "roundtable" / "autopilot.py"
    text = src.read_text(encoding="utf-8")
    assert "set_checking" not in text and "checking_chosen" not in text


# -- the API --------------------------------------------------------------------------------------------------
class FakeApp:
    def __init__(self, project):
        self._p = project

    def need_cfg(self):
        return None

    def project(self, cfg, path):
        return self._p


def test_the_api_says_who_built_who_checked_and_who_disagreed(tmp_path):
    from roundtable.ui import tandemapi

    orch, _ = build(tmp_path, plan=plan_of("hard", "ordinary"))
    orch.start("a made-up tool")
    orch.plan()
    tasks = orch.project.tasks()
    tasks[0].attempts = [
        {"model": "b/coder2", "outcome": "built", "rival": "r2"},
        {"model": "anthropic/claude-opus-5-5", "outcome": "approved", "rival": "r1", "agent": "ada",
         "rivals": [{"id": "r1", "model": "anthropic/claude-opus-5-5", "picked": True, "why": "smaller and tested"},
                    {"id": "r2", "model": "b/coder2", "picked": False, "why": ""}],
         "reviews": [{"model": "openai/gpt-6", "maker": "openai", "approved": True, "feedback": "fine"},
                     {"model": "google/gemini-3-pro", "maker": "google", "approved": False, "feedback": "x",
                      "breaks": "the score must show", "counted": True}],
         "disagreed": True, "same_maker": False}]
    orch.project.save_tasks(tasks)
    v = tandemapi.view(FakeApp(orch.project), {"path": [str(orch.project.root)]})
    assert set(v) == {"level", "label", "words", "allowance", "estimates", "tasks"}
    assert v["level"] == "balanced" and v["label"] == "Checking: Balanced"
    assert v["allowance"] == {"usd": None, "spent": 0.0, "used_up": False}
    assert set(v["estimates"]) == set(dial.LEVELS)
    t = v["tasks"]["T1"]
    assert list(v["tasks"]) == ["T1"]  # T2 has not been built
    assert t["built_by"] == "anthropic/claude-opus-5-5" and t["agent"] == "ada" and t["disagreed"]
    assert t["line"] == ("Built by Claude Opus 5.5 (ada) · best of 2 · checked by GPT 6 and Gemini 3 Pro · "
                         "they disagreed")
    assert any("“the score must show”" in x for x in t["fold"])
    assert any(x.startswith("Rival r1 Claude Opus 5.5: chosen: smaller and tested") for x in t["fold"])
    assert t["fold"][0].startswith("Try 1 (rival r2):")


def test_the_api_route_is_listed():
    from roundtable.ui import tandemapi

    assert ("GET", "/api/tandem") in tandemapi.routes(FakeApp(None))


def test_never_uses_a_model_the_project_does_not_allow():
    """The dial picks no models itself: it only prices the stages' extras and gives them their share."""
    src = (Path(__file__).resolve().parents[1] / "src" / "roundtable" / "harness" / "dial.py").read_text()
    assert "providers_allowed" not in src and "makers_allowed" not in src and "run_agent" not in src


# -- the same price against the real stages (wave 6 merged: rivals, panel, council, router, agents, usage) --------
class RealStages(NoKind):
    """The full Orchestrator: every real stage, nothing stood in for."""


def _tap_charges(orch):
    before = orch.budget.on_use

    def tap(ref, usage, cost, role):
        orch.__dict__.setdefault("charges", []).append((str(ref), role, cost or 0.0))
        if before:
            before(ref, usage, cost, role)

    orch.budget.on_use = tap


@pytest.mark.parametrize("level", dial.LEVELS)
def test_the_estimate_is_within_ten_percent_with_the_real_stages(tmp_path, level):
    plan = plan_of("ordinary", "hard", "risky", "ordinary")
    before, _ = build(tmp_path, cls=RealStages, plan=plan, name="before", tandem={"default": "lean"})
    before.start("a made-up tool")
    before.plan()
    before.approve()
    assert before.run() == "done"
    past = (before.project.dir / "metrics.jsonl").read_text(encoding="utf-8")
    orch, events = build(tmp_path, cls=RealStages, plan=plan, tandem={"default": level})
    _tap_charges(orch)
    orch.start("a made-up tool")
    (orch.project.dir / "metrics.jsonl").write_text(past, encoding="utf-8")
    orch.plan()
    est = orch.project.plan_doc()["estimate"]
    orch.approve()
    assert orch.run() == "done"
    spend = run_spend(orch)
    # the unsticking allowance (wave 5) is money kept for a task that gets stuck; a clean run never spends it
    spare = sum(e.get("usd") or 0 for e in est.get("extras") or [] if e.get("id") == "unstick")
    want = est["cost_usd"] - spare
    assert spend > 0
    assert abs(want - spend) <= 0.10 * spend, (level, want, spend, est.get("extras"))
    tasks = {t.id: t for t in orch.project.tasks()}
    if level == "lean":
        assert all("rival" not in a and "reviews" not in a for t in tasks.values() for a in t.attempts)
    elif level == "balanced":
        assert tasks["T2"].attempts[-1].get("rival") and len(tasks["T2"].attempts[-1]["rivals"]) == 2
        assert len([r for r in tasks["T3"].attempts[-1]["reviews"] if r["counted"] is True]) == 2
    assert not {"stage_error"} & {k for k, _ in events}
    print(f"\n10% check, real stages, {level}: estimate ${want:.4f} (+${spare:.2f} kept for stuck tasks), "
          f"spend ${spend:.4f}, {(want - spend) / spend:+.1%}")
