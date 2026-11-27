"""Rival plans, one merged plan (harness/council.py, wave 6).

Made-up projects in tmp_path; scripted planners from three makers (the maker is the provider id: a, b, c).
"""

import json
import threading

from roundtable.harness import council, dial, plandoc
from roundtable.harness import projectsettings as ps
from roundtable.harness.config import parse_config
from roundtable.harness.council import CouncilStage
from roundtable.harness.orchestrator import Orchestrator
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider, reply

from .test_stage_hooks import Seam

PRICE = {"input": 1, "output": 1}
RAW = {
    "providers": {"a": {"type": "scripted"}, "b": {"type": "scripted"}, "c": {"type": "scripted"},
                  "img": {"type": "scripted_images"}},
    "roles": {
        "orchestrator": {"model": "a/planner"},
        "critic": {"model": "b/critic"},
        "coder": {"model": "a/coder"},
        "reviewer": {"model": "a/reviewer"},
    },
    "profiles": {"quality": {"roles": {"orchestrator": {"model": "c/planner3"}}}},
    "pricing": {m: PRICE for m in ("a/planner", "b/critic", "c/planner3", "a/coder", "a/reviewer")},
    "limits": {"max_cost_usd": 5, "max_attempts_per_task": 3},
    # the estimate's sizes set to what a scripted reply uses, so the estimate can be compared with the spend
    "council": {"plan_tokens": [100, 20], "critique_tokens": [100, 20]},
}


def task(tid, title):
    return {"id": tid, "title": title, "role": "coder", "description": f"write {tid}.txt", "acceptance": "exists",
            "depends_on": []}


class Planners:
    """Each maker plans its own way; the chair merges; every critique says A is best."""

    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, model, system, messages, tools):
        names = {t.name for t in tools}
        last = messages[-1]
        prompt = messages[0]["content"]
        if last["role"] == "tool":
            return reply("ok")
        with self.lock:
            self.calls.append((model, "chair" if "as the chair" in prompt else
                               "plan" if "submit_plan" in names else
                               "critique" if "submit_critique" in names else "other"))
        if "submit_plan" in names and "as the chair" in prompt:
            return reply(calls=[("submit_plan", {
                "title": "Merged plan", "summary": "the chair's plan",
                "tasks": [task("T1", "merged one"), task("T2", "merged two")],
                "decisions": [{"question": "Which store?", "options": [{"label": "Files"}, {"label": "A database"}],
                               "recommended": "o1", "why": "simpler"}],
                "disagreements": [
                    {"topic": "How to save", "options": [{"who": "A", "says": "files"}, {"who": "B", "says": "a database"}],
                     "chosen": "files", "why": "simpler"},
                    {"topic": "Tests first", "options": [{"who": "C", "says": "yes"}], "chosen": "yes"}]})])
        if "submit_plan" in names:
            return reply(calls=[("submit_plan", {"summary": f"plan by {model}", "tasks": [task("T1", f"one by {model}")]})])
        if "submit_critique" in names:
            if "verdict" in json.dumps([t.parameters for t in tools if t.name == "submit_critique"]):
                return reply(calls=[("submit_critique", {"verdict": "good", "points": []})])
            return reply(calls=[("submit_critique", {"best": "A", "points": [{"about": "B", "text": "too big"}]})])
        if "submit_review" in names:
            return reply(calls=[("submit_review", {"approved": True, "feedback": "fine"})])
        if "finish_task" in names:
            if last["role"] == "user":
                return reply(calls=[("write_file", {"path": "out.txt", "content": "x\n"})])
            return reply(calls=[("finish_task", {"summary": "done"})])
        return reply("done")

    def kinds(self):
        return [k for _, k in self.calls]


class O(CouncilStage, Seam):
    pass


def build(tmp_path, raw=RAW, planners=3, cls=O, monkeypatch=None):
    cfg = parse_config(json.loads(json.dumps(raw)))
    brain = Planners()
    for name in ("a", "b", "c"):
        cfg.register(name, ScriptedProvider(name, brain))
    cfg.register("img", ScriptedImages())
    events = []
    orch = cls(cfg, tmp_path / "proj", on_event=lambda k, d: events.append((k, d)))
    if monkeypatch is not None:
        monkeypatch.setattr(dial, "for_plan", lambda o: {"planners": planners})
    return orch, brain, events


def plan(orch):
    orch.start("a made-up notes app")
    return orch.plan()


def test_three_planners_and_a_chair_make_one_plan(tmp_path, monkeypatch):
    orch, brain, events = build(tmp_path, monkeypatch=monkeypatch)
    new = plan(orch)
    assert [t.title for t in new] == ["merged one", "merged two"]  # the chair's plan
    assert brain.kinds().count("plan") == 3 and brain.kinds().count("critique") == 3 and brain.kinds().count("chair") == 1
    planners = {m for m, k in brain.calls if k == "plan"}
    assert planners == {"planner", "critic", "planner3"}  # one per maker: the planner, the critic, the Quality planner
    doc = orch.project.plan_doc()
    c = doc["council"]
    assert [p["label"] for p in c["planners"]] == ["A", "B", "C"]
    assert [p["maker"] for p in c["planners"]] == ["a", "b", "c"]
    assert c["merged"] and c["chair"] == "a/planner" and len(c["disagreements"]) == 2
    assert c["planners"][0]["votes"] == 3
    assert "disagreements" not in json.dumps(doc["decisions"])  # not a part of the plan's own fields
    assert doc["decisions"][0]["question"] == "Which store?"  # the owner's choice: an ordinary decision
    assert doc["critique"] is None  # the chair weighed the plans: no second opinion
    assert doc["title"] == "Merged plan" and doc["summary"] == "the chair's plan"
    assert council.words(c) == "Three planners agreed on most of it; they differed on 2 things"
    md = plandoc.render_markdown(doc, new) + "\n".join(council.markdown(doc))
    assert council.HEADING in md and "How to save" in md
    assert orch.project.meta()["spent_usd"] > 0 and c["cost_usd"] > 0
    assert any(k == "council" for k, _ in events)
    row = json.loads((orch.project.root / dial.LEDGER).read_text().splitlines()[-1])
    assert row["what"] == "council" and row["usd"] == round(c["cost_usd"], 6)


def test_the_plan_has_every_part_a_single_plan_has(tmp_path, monkeypatch):
    class Parts(O):
        def _done_doc(self, doc, args):
            doc["done_list"] = {"items": [{"id": "D1", "text": "it opens"}]}

        def _stages_doc(self, doc, args):
            doc["stages"] = [{"id": "G1", "title": "slice"}]

    orch, brain, _ = build(tmp_path, cls=Parts, monkeypatch=monkeypatch)
    plan(orch)
    doc = orch.project.plan_doc()
    assert doc["done_list"]["items"] and doc["stages"] and doc["council"]["merged"]
    assert doc.get("estimate") is not None


def test_the_disagreements_survive_a_revision(tmp_path, monkeypatch):
    orch, brain, _ = build(tmp_path, monkeypatch=monkeypatch)
    plan(orch)
    before = len(brain.calls)
    orch.revise_plan("make it smaller")
    doc = orch.project.plan_doc()
    assert doc["version"] == 2 and len(doc["council"]["disagreements"]) == 2
    assert [k for _, k in brain.calls[before:]] == ["plan"]  # a revision is one planner, no council


def test_the_cap_stops_it_after_round_one_and_the_best_plan_is_used(tmp_path, monkeypatch):
    raw = json.loads(json.dumps(RAW))
    raw["council"]["max_usd"] = 0.0003  # a scripted planning call costs 0.00012: reached by the third plan
    orch, brain, _ = build(tmp_path, raw=raw, monkeypatch=monkeypatch)
    new = plan(orch)
    assert brain.kinds() == ["plan", "plan", "plan"]  # no critiques, no chair
    assert [t.title for t in new] == ["one by planner"]  # the owner's planner's plan (nobody voted)
    c = orch.project.plan_doc()["council"]
    assert not c["merged"] and c["best"] == "A" and c["stopped"] == "cap"
    assert "the one the others liked best (A)" in council.words(c)


def test_one_maker_only_is_the_usual_plan_and_critique(tmp_path, monkeypatch):
    raw = json.loads(json.dumps(RAW))
    raw["roles"]["critic"] = {"model": "a/critic"}
    raw["profiles"] = {"quality": {"roles": {"orchestrator": {"model": "a/planner"}}}}
    raw["pricing"]["a/critic"] = PRICE
    orch, brain, _ = build(tmp_path, raw=raw, monkeypatch=monkeypatch)
    plan(orch)
    doc = orch.project.plan_doc()
    assert "council" not in doc and doc["critique"]["verdict"] == "good"
    assert brain.kinds() == ["plan", "critique"]


def test_council_never_uses_a_model_the_project_does_not_allow(tmp_path, monkeypatch):
    orch, brain, _ = build(tmp_path, monkeypatch=monkeypatch)
    orch.start("a made-up notes app")
    ps.update(orch.project.root, {"makers_allowed": ["a", "c"]})
    orch.plan()
    asked = {m for m, _ in brain.calls}
    assert "critic" not in asked  # b's model is never asked anything
    c = orch.project.plan_doc()["council"]
    assert [p["maker"] for p in c["planners"]] == ["a", "c"]
    assert council.words(c).startswith("Two planners")


def test_lean_and_balanced_make_no_extra_planning_calls(tmp_path, monkeypatch):
    table = {"lean": 1, "balanced": 1, "maximum": 3}  # the dial's table for the plan
    for level in ("lean", "balanced"):
        orch, brain, _ = build(tmp_path / level)
        monkeypatch.setattr(dial, "for_plan", lambda o: {"planners": table[dial.level(o)]})
        orch.cfg.sections["tandem"] = {"default": level}
        plan(orch)
        assert brain.kinds() == ["plan", "critique"], level  # one planner and today's critique
        assert "council" not in orch.project.plan_doc()
    orch, brain, _ = build(tmp_path / "max")
    orch.cfg.sections["tandem"] = {"default": "maximum"}
    plan(orch)  # the level is set before the dial is asked, so a new plan's Maximum counts
    assert orch.project.plan_doc()["council"]["merged"]


def test_the_stub_dial_runs_no_council(tmp_path):
    orch, brain, _ = build(tmp_path)
    plan(orch)
    assert "council" not in orch.project.plan_doc()


def test_the_estimate_is_within_ten_percent_of_the_planning_spend(tmp_path, monkeypatch):
    orch, brain, _ = build(tmp_path, monkeypatch=monkeypatch)
    refs = orch._council_planners(3)
    est = council.estimate(orch.cfg, 3, refs)
    plan(orch)
    spent = orch.project.plan_doc()["council"]["cost_usd"]
    assert est and abs(est - spent) <= 0.1 * spent, (est, spent)
    assert council.estimate(orch.cfg, 1) == 0.0


def test_a_dial_that_says_no_room_runs_the_usual_plan(tmp_path, monkeypatch):
    orch, brain, _ = build(tmp_path, monkeypatch=monkeypatch)
    monkeypatch.setattr(dial, "allow", lambda o, what, usd: what != "council")
    plan(orch)
    assert "council" not in orch.project.plan_doc() and brain.kinds()[0] == "plan"


def test_a_failed_chair_uses_the_best_plan_so_far(tmp_path, monkeypatch):
    orch, brain, _ = build(tmp_path, monkeypatch=monkeypatch)
    real = orch._council_chair_job
    monkeypatch.setattr(orch, "_council_chair_job", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    new = plan(orch)
    c = orch.project.plan_doc()["council"]
    assert not c["merged"] and c["best"] == "A" and [t.title for t in new] == ["one by planner"]
    assert real  # the real one is untouched


class Full(CouncilStage, Orchestrator):
    def _kind_proof(self):
        return []


def test_a_scripted_maximum_project_on_the_full_orchestrator_plans_and_runs(tmp_path, monkeypatch):
    orch, brain, events = build(tmp_path, cls=Full, monkeypatch=monkeypatch)
    plan(orch)
    doc = orch.project.plan_doc()
    assert doc["council"]["merged"] and not doc.get("critique")
    assert any(k == "council_start" and d["estimate_usd"] for k, d in events)  # the spend was known before it ran
    assert not [d for k, d in events if k == "stage_error"]
    orch.approve()
    assert orch.run() == "done"


def test_the_api_reads_the_council(tmp_path, monkeypatch):
    from roundtable.ui import councilapi

    orch, _, _ = build(tmp_path, monkeypatch=monkeypatch)
    plan(orch)

    class App:
        def need_cfg(self):
            return orch.cfg

        def project(self, cfg, path):
            return orch.project

    got = councilapi.routes(App())[("GET", "/api/tandem/council")]({"path": [str(orch.project.root)]})
    assert got["found"] and got["words"].startswith("Three planners") and len(got["disagreements"]) == 2


def test_the_view_and_the_words():
    assert council.view({}) == {"found": False}
    v = council.view({"council": {"planners": [{}, {}], "disagreements": [], "merged": True}})
    assert v["found"] and v["words"] == "Two planners agreed on the whole plan"
    assert council.markdown({}) == []
