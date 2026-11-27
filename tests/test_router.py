"""The router (wave 6): each task goes to the model that wins its kind of work; a capped share of easy tasks
tries a model not yet tried; the strength map in the lab and the app.

Every project is made up, in tmp_path; the models are scripted (the maker is the provider id); the history is
written by hand into metrics.jsonl.
"""

import json
import math

import pytest

from roundtable.harness import dial, router as routerlib
from roundtable.harness import projectsettings as ps
from roundtable.harness.config import ModelRef, parse_config
from roundtable.harness.orchestrator import Orchestrator
from roundtable.harness.router import RouterStage
from roundtable.improve import analysis
from roundtable.providers.base import ProviderError
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider

from .test_harness import RAW, Brain


class O(RouterStage, Orchestrator):
    def _kind_proof(self):
        return []  # the kind guessed for a made-up project would bring its own checks


def _task(tid, tags=(), **kw):
    return {"id": tid, "title": f"task {tid}", "role": "coder", "description": f"do {tid}", "acceptance": "done",
            "depends_on": [], "tags": list(tags), **kw}


def _raw(**router):
    raw = json.loads(json.dumps(RAW))
    raw["providers"]["c"] = {"type": "scripted"}
    raw["pricing"]["c/newbie"] = {"input": 1, "output": 1}
    raw["limits"]["max_cost_usd"] = 50
    if router:
        raw["router"] = router
    return raw


def build(tmp_path, plan, raw=None, c_brain=None):
    cfg = parse_config(raw or _raw())
    brain = Brain(plan=plan)
    for name in ("a", "b"):
        cfg.register(name, ScriptedProvider(name, brain))
    cfg.register("c", ScriptedProvider("c", c_brain or brain))
    cfg.register("img", ScriptedImages())
    events = []
    orch = O(cfg, tmp_path / "proj", on_event=lambda k, d: events.append((k, d)))
    return orch, events


def history(orch, rows):
    """Past metrics rows: (model, tag, approved, rejected)."""
    p = orch.project.dir / "metrics.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("a", encoding="utf-8") as f:
        for model, tag, ok, bad in rows:
            for outcome, k in (("approved", ok), ("rejected", bad)):
                for _ in range(k):
                    n += 1
                    f.write(json.dumps({"task": f"old{n}", "role": "coder", "model": model, "outcome": outcome,
                                        "tags": [tag], "cost_usd": 0.01}) + "\n")


def first_models(orch):
    return {t.id: t.attempts[0]["model"] for t in orch.project.tasks()}


def planned(tmp_path, plan, **kw):
    orch, events = build(tmp_path, plan, **kw)
    orch.start("a made-up game")
    orch.plan()
    return orch, events


# -- routing by strength -----------------------------------------------------------------------------------
def test_a_shader_task_goes_to_the_shader_winner_and_a_layout_task_to_the_other(tmp_path):
    orch, events = build(tmp_path, [_task("T1", ["shaders"]), _task("T2", ["layout"])])
    orch.start("a made-up game")
    history(orch, [("b/coder2", "shaders", 9, 1), ("a/coder", "shaders", 2, 8),
                   ("a/coder", "layout", 9, 1), ("b/coder2", "layout", 3, 7)])
    orch.plan()
    assert dial.level(orch) == "balanced"
    assert orch.run() == "done"
    assert first_models(orch) == {"T1": "b/coder2", "T2": "a/coder"}
    t1 = next(t for t in orch.project.tasks() if t.id == "T1")
    assert t1.attempts[0]["routed"] == {"from": "a/coder", "why": "wins 9 of 10 shader tasks"}
    assert "routed" not in next(t for t in orch.project.tasks() if t.id == "T2").attempts[0]
    routed = [d for k, d in events if k == "routed"]
    assert [(d["task"], d["model"]) for d in routed] == [("T1", "b/coder2")]
    assert not [d for k, d in events if k == "stage_error"]


def test_the_chain_is_kept_behind_the_winner(tmp_path):
    orch, _ = planned(tmp_path, [_task("T1", ["shaders"])])
    history(orch, [("b/coder2", "shaders", 9, 1)])
    task = orch.project.tasks()[0]
    role = orch.cfg.roles["coder"]
    got = orch._route_models(task, role, list(role.models))
    assert [str(m) for m in got] == ["b/coder2", "a/coder"]


def test_too_little_history_leaves_the_order_alone(tmp_path):
    orch, events = build(tmp_path, [_task("T1", ["shaders"])])
    orch.start("a made-up game")
    history(orch, [("b/coder2", "shaders", 4, 0)])  # 4 judged tries: below min_samples (5)
    orch.plan()
    assert orch.run() == "done"
    assert first_models(orch) == {"T1": "a/coder"}
    assert not [d for k, d in events if k == "routed"]


def test_a_small_lead_is_not_enough(tmp_path):
    orch, _ = planned(tmp_path, [_task("T1", ["shaders"])])
    history(orch, [("b/coder2", "shaders", 8, 2), ("a/coder", "shaders", 7, 3)])  # 0.75 against 0.67
    task, role = orch.project.tasks()[0], orch.cfg.roles["coder"]
    assert orch._route_models(task, role, list(role.models)) is None


def test_a_tie_goes_to_the_cheaper_model_per_finished_task(tmp_path):
    raw = _raw(pool={"coder": ["c/newbie"]})
    orch, _ = planned(tmp_path, [_task("T1", ["shaders"])], raw=raw)
    p = orch.project.dir / "metrics.jsonl"
    with p.open("a", encoding="utf-8") as f:
        for i in range(10):
            for model, cost in (("b/coder2", 0.05), ("c/newbie", 0.01)):
                f.write(json.dumps({"task": f"o{i}{model}", "role": "coder", "model": model, "outcome": "approved",
                                    "tags": ["shaders"], "cost_usd": cost}) + "\n")
    task, role = orch.project.tasks()[0], orch.cfg.roles["coder"]
    assert str(orch._route_models(task, role, list(role.models))[0]) == "c/newbie"


def test_nothing_is_routed_at_lean(tmp_path):
    orch, _ = planned(tmp_path, [_task("T1", ["shaders"])])
    history(orch, [("b/coder2", "shaders", 9, 1)])
    meta = orch.project.meta()
    meta["checking"] = "lean"
    orch.project.save_meta(meta)
    task, role = orch.project.tasks()[0], orch.cfg.roles["coder"]
    assert orch._route_models(task, role, list(role.models)) is None
    assert orch._tags_metric(task, role.models[0]) == {}


def test_router_never_uses_a_model_the_project_does_not_allow(tmp_path):
    raw = _raw(pool={"coder": ["c/newbie"]})
    orch, events = build(tmp_path, [_task("T1", ["shaders"]), _task("T2", ["layout"])], raw=raw)
    orch.start("a made-up game")
    history(orch, [("c/newbie", "shaders", 10, 0), ("b/coder2", "layout", 10, 0)])
    ps.update(orch.project.root, {"providers_allowed": ["a", "b"]})
    orch.plan()
    task, role = orch.project.tasks()[0], orch.cfg.roles["coder"]
    assert orch._route_models(task, role, list(role.models)) is None  # the winner comes through c: never
    ps.update(orch.project.root, {"providers_allowed": [], "makers_allowed": ["a"]})
    t2 = orch.project.tasks()[1]
    assert orch._route_models(t2, role, list(role.models)) is None  # b's model: its maker isn't allowed
    assert orch.run() == "done"
    assert all(a["model"].startswith("a/") for t in orch.project.tasks() for a in t.attempts)


def test_a_pool_model_from_a_service_not_set_up_is_never_a_candidate(tmp_path):
    raw = _raw(pool={"coder": ["nowhere/model-x"]})
    orch, _ = planned(tmp_path, [_task("T1", ["shaders"])], raw=raw)
    history(orch, [("nowhere/model-x", "shaders", 10, 0)])
    task, role = orch.project.tasks()[0], orch.cfg.roles["coder"]
    assert orch._route_models(task, role, list(role.models)) is None


def test_history_from_the_labs_other_projects_counts(tmp_path):
    from roundtable.improve.lab import Lab

    other, _ = planned(tmp_path / "other", [_task("X1", ["shaders"])])
    history(other, [("b/coder2", "shaders", 9, 1)])
    raw = _raw()
    orch, _ = planned(tmp_path / "mine", [_task("T1", ["shaders"])], raw=raw)
    orch.cfg.lab_dir = tmp_path / "lab"
    Lab(orch.cfg.lab_dir).register_project(other.project.root)
    task, role = orch.project.tasks()[0], orch.cfg.roles["coder"]
    assert str(orch._route_models(task, role, list(role.models))[0]) == "b/coder2"


# -- tags in the plan and the metrics ----------------------------------------------------------------------------
def test_tags_reach_metrics_jsonl(tmp_path):
    orch, _ = planned(tmp_path, [_task("T1", ["Game Logic", "tests"], files=["src/main.gd", "shade.gdshader"],
                                       risky=True)])
    assert orch.run() == "done"
    rows = [json.loads(x) for x in (orch.project.dir / "metrics.jsonl").read_text().splitlines()]
    assert rows[-1]["tags"][:4] == ["game-logic", "tests", "gdscript", "shaders"]
    assert rows[-1]["risky"] is True and rows[-1]["hard"] is False


def test_the_planner_is_asked_for_tags_unless_lean(tmp_path):
    orch, _ = build(tmp_path, [_task("T1")])
    orch.start("a made-up game")
    assert "game-logic" in orch._tags_plan_part() and "risky" in orch._tags_plan_part()
    orch.cfg.sections["tandem"] = {"default": "lean"}
    assert dial.level_for_new_plan(orch) == "lean" and orch._tags_plan_part() == ""


def test_an_over_marked_plan_is_trimmed(tmp_path):
    plan = [_task(f"T{i}", hard=True, why_hard="tricky") for i in range(1, 9)]
    plan[7]["risky"] = True
    orch, _ = build(tmp_path, plan)
    orch.start("a made-up game")
    orch.plan()  # without the hook-up in plan(): the document part trims the saved tasks
    doc = {"goal_index": 0}
    orch._tags_doc(doc, {})
    tasks = orch.project.tasks()
    assert [t.id for t in tasks if t.hard] == ["T1", "T2"]  # a quarter of 8
    assert tasks[2].why_hard == "" and tasks[7].why_hard == "tricky"  # a risky task keeps its reason
    (warn,) = doc["warnings"]
    assert warn["by"] == "tags" and warn["tasks"] == [f"T{i}" for i in range(3, 9)]
    assert "8 tasks as hard" in warn["text"]
    again = {"goal_index": 0, "warnings": [warn]}
    orch._tags_doc(again, {})
    assert "warnings" not in again  # nothing more to trim: the old warning goes


def test_the_trim_hook_on_new_tasks(tmp_path):
    from roundtable.harness.orchestrator import Task

    orch, _ = build(tmp_path, [_task("T1")])
    new = [Task(id=f"T{i}", title="t", role="coder", description="d", hard=True) for i in range(4)]
    orch._tags_trim(new)
    assert [t.hard for t in new] == [True, False, False, False]
    doc = {}
    orch._tags_doc(doc, {})
    assert doc["warnings"][0]["id"] == "hard:trimmed"


# -- trying untried models -----------------------------------------------------------------------------------------
@pytest.fixture
def explore(monkeypatch):
    monkeypatch.setattr(dial, "for_task", lambda orch, task: {"rivals": 1, "panel": 1, "explore": True, "why": ""})


def _explored(orch):
    return [t.id for t in orch.project.tasks() if t.attempts and t.attempts[0]["model"] == "c/newbie"]


def test_exploring_keeps_to_the_money_cap(tmp_path, explore):
    raw = _raw(pool={"coder": ["c/newbie"]}, explore={"share": 1.0, "max_usd_per_goal": 0.2})
    orch, _ = planned(tmp_path, [_task(f"T{i}", ["logic"]) for i in range(1, 9)], raw=raw)
    assert orch.run() == "done"
    est = 68_000 / 1_000_000 * 1.4  # one typical try at $1 a million tokens, with the allowance
    assert len(_explored(orch)) == math.floor(0.2 / est) == 2
    t = next(t for t in orch.project.tasks() if t.id in _explored(orch))
    assert t.attempts[0]["routed"]["explore"] is True and t.attempts[0]["routed"]["from"] == "a/coder"
    ledger = [json.loads(x) for x in (orch.project.root / dial.LEDGER).read_text().splitlines()]
    assert [r["what"] for r in ledger] == ["router", "router"]


def test_exploring_keeps_to_the_share(tmp_path, explore):
    raw = _raw(pool={"coder": ["c/newbie"]}, explore={"share": 0.25, "max_usd_per_goal": 50})
    plan = [_task(f"T{i}", ["logic"]) for i in range(1, 13)]
    orch, _ = planned(tmp_path, plan, raw=raw)
    goal = orch.project.meta()["goals"][0]
    hashed = [p["id"] for p in plan if routerlib._hash(goal, 0, p["id"]) < 0.25]
    assert orch.run() == "done"
    assert hashed  # the made-up ids give the test something to cap
    assert len(_explored(orch)) == min(3, len(hashed)) <= 3  # a quarter of 12
    assert set(_explored(orch)) <= set(hashed)


def test_never_explores_on_hard_or_risky_tasks(tmp_path, explore):
    raw = _raw(pool={"coder": ["c/newbie"]}, explore={"share": 1.0, "max_usd_per_goal": 50})
    plan = [_task("T1", ["logic"], hard=True, why_hard="x"), _task("T2", ["logic"], risky=True),
            _task("T3", ["logic"]), _task("T4", ["logic"])]
    orch, _ = planned(tmp_path, plan, raw=raw)
    assert orch.run() == "done"
    assert set(_explored(orch)) == {"T3", "T4"}


def test_a_failed_try_falls_back_and_the_task_still_passes(tmp_path, explore):
    def broken(model, system, messages, tools):
        raise ProviderError("the newer model is down")

    raw = _raw(pool={"coder": ["c/newbie"]}, explore={"share": 1.0, "max_usd_per_goal": 50})
    orch, _ = planned(tmp_path, [_task("T1", ["logic"])], raw=raw, c_brain=broken)
    assert orch.run() == "done"
    (t,) = orch.project.tasks()
    assert [(a["model"], a["outcome"]) for a in t.attempts] == [("c/newbie", "error"), ("a/coder", "approved")]
    assert t.status == "done"


def test_no_untried_maker_in_a_restricted_project_or_a_repository(tmp_path, explore, monkeypatch):
    raw = _raw(pool={"coder": ["c/newbie"]}, explore={"share": 1.0, "max_usd_per_goal": 50})
    orch, _ = planned(tmp_path, [_task("T1", ["logic"])], raw=raw)
    ps.update(orch.project.root, {"makers_allowed": ["a", "b", "c"]})  # c is allowed, but not in the job lists
    task, role = orch.project.tasks()[0], orch.cfg.roles["coder"]
    assert orch._route_models(task, role, list(role.models)) is None
    ps.update(orch.project.root, {"makers_allowed": []})
    monkeypatch.setattr(O, "_repo_mode", lambda self: True)
    assert orch._route_models(task, role, list(role.models)) is None
    monkeypatch.setattr(O, "_repo_mode", lambda self: False)
    assert str(orch._route_models(task, role, list(role.models))[0]) == "c/newbie"


def test_a_dear_or_unpriced_model_is_never_tried(tmp_path, explore):
    raw = _raw(pool={"coder": ["c/newbie"]}, explore={"share": 1.0, "max_usd_per_goal": 50})
    raw["pricing"]["c/newbie"] = {"input": 2, "output": 2}  # twice the usual
    orch, _ = planned(tmp_path, [_task("T1", ["logic"])], raw=raw)
    task, role = orch.project.tasks()[0], orch.cfg.roles["coder"]
    assert orch._route_models(task, role, list(role.models)) is None
    del orch.cfg.pricing["c/newbie"]
    assert orch._route_models(task, role, list(role.models)) is None


def test_exploring_needs_the_dial(tmp_path):
    raw = _raw(pool={"coder": ["c/newbie"]}, explore={"share": 1.0, "max_usd_per_goal": 50})
    orch, _ = planned(tmp_path, [_task("T1", ["logic"])], raw=raw)  # the stub dial never explores
    assert orch.run() == "done" and _explored(orch) == []


def test_the_estimate_line_for_trying_newer_models(tmp_path, explore):
    raw = _raw(pool={"coder": ["c/newbie"]}, explore={"share": 1.0, "max_usd_per_goal": 0.2})
    orch, _ = planned(tmp_path, [_task(f"T{i}", ["logic"]) for i in range(1, 5)], raw=raw)
    got = orch._router_estimate(orch.project.tasks())
    assert got["id"] == "router" and got["usd"] == 0.2
    assert got["words"] == "trying newer models on 4 small tasks: up to about $0.20"
    assert orch._router_estimate([t for t in orch.project.tasks() if False]) is None


# -- the lab's numbers ----------------------------------------------------------------------------------------------
def _ds(rows):
    ds = analysis.Dataset()
    firsts = set()
    for row in rows:
        key = (row["role"], row["model"])
        analysis.count_row(ds.stats.setdefault(key, analysis.ModelStats(*key)), row, firsts, ())
    return ds


def test_rival_lost_rows_are_not_failures():
    rows = [{"task": "T1", "role": "coder", "model": "a/x", "outcome": "rival_lost", "cost_usd": 0.1},
            {"task": "T1", "role": "coder", "model": "a/x", "outcome": "approved", "rival": "r1"},
            {"task": "T2", "role": "coder", "model": "a/x", "outcome": "approved"}]
    s = _ds(rows).stats[("coder", "a/x")]
    assert (s.attempts, s.approved, s.rejected, s.other_fail, s.errors) == (2, 2, 0, 0, 0)
    assert (s.rival_wins, s.rival_losses, s.quality) == (1, 1, 1.0)


def test_strengths_and_the_table_by_tag(tmp_path):
    f = tmp_path / "metrics.jsonl"
    f.write_text("".join(json.dumps({"task": f"t{i}", "role": "coder", "model": m, "outcome": o,
                                     "tags": ["game-logic"], "cost_usd": 0.02}) + "\n"
                         for i, (m, o) in enumerate([("a/x", "approved")] * 9 + [("a/x", "rejected")]
                                                    + [("b/y", "approved")] * 2)), encoding="utf-8")
    st = analysis.tag_stats([f])
    got = analysis.strengths(st, min_n=5)
    assert got == {"coder": {"game-logic": [{"model": "a/x", "quality": 0.9, "approved": 9, "n": 10,
                                             "cost_per_success": round(0.2 / 9, 6)}]}}
    ds = analysis.Dataset(by_tag=st)
    table = analysis.stats_table(ds, by_tag=True)
    assert "game-logic" in table and "90%" in table and table.splitlines()[0].split()[2] == "tag"


def test_the_strengths_api(tmp_path, monkeypatch):
    import yaml

    from roundtable.ui import server
    from roundtable.ui.server import UIApp

    from .test_hub import RAW as HUB_RAW

    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "strengthsapi"))
    h = json.loads(json.dumps(HUB_RAW))
    h["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
    (tmp_path / "hub.yaml").write_text(yaml.safe_dump(h), encoding="utf-8")
    orch, _ = planned(tmp_path, [_task("T1", ["shaders"])])
    history(orch, [("b/coder2", "shaders", 9, 1), ("b/coder2", "layout", 2, 3), ("a/coder", "layout", 6, 0)])
    cfg = orch.cfg
    cfg.lab_dir = tmp_path / "lab"
    orch._register_with_lab()
    app = UIApp(str(tmp_path / "hub.yaml"), "missing.yaml", agent="backend")
    app.cfg = lambda: cfg
    got = app.dispatch("GET", "/api/strengths", {"path": [str(orch.project.root)]}, {})
    assert [(x["model"], x["words"]) for x in got["lines"]] == [("a/coder", "Best at layout: 6 of 6"),
                                                                ("b/coder2", "Best at shader: 9 of 10")]
    assert {r["tag"] for r in got["table"]} == {"shaders", "layout"} and got["min_samples"] == 5
    assert got["roles"]["coder"]["layout"][0]["model"] == "a/coder"


def test_the_count_cap_holds_even_when_every_task_hashes_in(tmp_path, explore, monkeypatch):
    monkeypatch.setattr(routerlib, "_hash", lambda *parts: 0.0)
    raw = _raw(pool={"coder": ["c/newbie"]}, explore={"share": 0.25, "max_usd_per_goal": 50})
    orch, _ = planned(tmp_path, [_task(f"T{i}", ["logic"]) for i in range(1, 9)], raw=raw)
    assert orch.run() == "done"
    assert _explored(orch) == ["T1", "T2"]  # a quarter of 8, in turn
    state = json.loads((orch.project.root / routerlib.STATE).read_text())
    assert [r["task"] for r in state["explored"]] == ["T1", "T2"]


def test_the_full_orchestrator_with_the_router_at_lean_runs_as_before(tmp_path):
    from .test_tandem_seam import NoKind, _run, _shape

    class Routed(RouterStage, NoKind):
        pass

    bare, _, _ = _run(tmp_path / "bare", NoKind, level="lean")
    full, events, _ = _run(tmp_path / "full", Routed, level="lean")
    assert _shape(full) == _shape(bare)
    assert not [k for k, _ in events if k in ("stage_error", "routed")]
