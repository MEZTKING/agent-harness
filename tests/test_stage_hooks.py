"""Step 0 of wave 5: the stages' seam (Orchestrator._hook and the ordered names, add_tasks, the done list).

A bare Orchestrator has none of the hooks, so it must run exactly as before; a stage is a mixin that adds
them. Every project here is made up, in tmp_path; the models are scripted.
"""

import json

import pytest

from roundtable.harness import donelist, plandoc
from roundtable.harness.agent import BudgetExceeded
from roundtable.harness.config import FEATURE_SECTIONS, parse_config
from roundtable.harness.orchestrator import HarnessError, Orchestrator
from roundtable.kinds import model as kindmodel
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider

from .test_harness import RAW, Brain
from .test_parallel import ParallelBrain, raw as parallel_raw

ONE = [{"id": "T1", "title": "one", "role": "coder", "description": "write one.txt", "acceptance": "exists",
        "depends_on": []}]
EXTRA = {"id": "F1", "title": "fix", "role": "coder", "description": "write f1.txt", "acceptance": "exists",
         "depends_on": [], "files": ["f1.txt"], "stage": "slice", "part": "game"}

HOOKS = (*Orchestrator.PLAN_PARTS, *Orchestrator.SCHEMA_PARTS, *Orchestrator.DOC_PARTS, *Orchestrator.WORKER_PARTS,
         *Orchestrator.ESTIMATE_PARTS, *Orchestrator.END_STEPS, "_stage_ready", "_unstick_task", "_unstick_end",
         "_money_agreed", "_money_gate", "_money_charge")


def build(tmp_path, cls=Orchestrator, raw=RAW, brain=None):
    cfg = parse_config(json.loads(json.dumps(raw)))
    brain = brain or Brain()
    for name in ("a", "b"):
        cfg.register(name, ScriptedProvider(name, brain))
    cfg.register("img", ScriptedImages())
    events = []
    orch = cls(cfg, tmp_path / "proj", on_event=lambda k, d: events.append((k, d)))
    return orch, events, brain


def kinds(events):
    return [k for k, _ in events]


# -- a bare Orchestrator is as before ---------------------------------------------------------------------------
def test_a_bare_orchestrator_has_none_of_the_stage_hooks():
    for name in HOOKS:
        assert not callable(getattr(Orchestrator, name, None)), name


def test_a_bare_orchestrator_runs_exactly_as_before(tmp_path):
    orch, events, brain = build(tmp_path, brain=Brain(plan=ONE))
    orch.start("a made-up tool")
    assert orch.run() == "done"
    assert [t.status for t in orch.project.tasks()] == ["done"]
    t = orch.project.tasks()[0]
    assert (t.files, t.stage, t.part, t.added_by, t.fix_of, t.handoff_from, t.parked) == ([], "", "", "", "", "", "")
    assert not {"stage_error", "tasks_added"} & set(kinds(events))
    doc = orch.project.plan_doc()
    assert doc["estimate"]["extras"] == []
    for k in ("done_list", "stages", "parts", "prep", "warnings"):
        assert k not in doc
    assert not donelist.path(orch.project.root).exists()
    # the plan's schema is the plain one: the task schema offers the new fields, nothing else changed
    schema = plandoc.submission_schema(orch._task_schema())
    props = schema["properties"]["tasks"]["items"]["properties"]
    assert {"files", "stage", "part"} <= set(props)
    assert "files" not in schema["properties"]["tasks"]["items"]["required"]
    assert orch._end_steps(orch.project.tasks()) is None


def test_the_planner_can_give_files_stage_and_part(tmp_path):
    plan = [dict(ONE[0], files=["one.txt", " "], stage="slice", part="game")]
    orch, _, _ = build(tmp_path, brain=Brain(plan=plan))
    orch.start("a made-up tool")
    orch.plan()
    t = orch.project.tasks()[0]
    assert (t.files, t.stage, t.part) == (["one.txt"], "slice", "game")


# -- _hook ------------------------------------------------------------------------------------------------------
class Hooks(Orchestrator):
    def _done_plan_part(self):
        raise ValueError("the done list broke")

    def _prep_plan_part(self):
        return None

    def _money_gate(self):
        raise BudgetExceeded("allowance")

    def _done_gate(self, tasks):
        raise HarnessError("refused")


def test_a_stage_error_is_written_down_never_raised(tmp_path):
    orch, events, _ = build(tmp_path, cls=Hooks)
    assert orch._hook("_done_plan_part", default="") == ""
    assert ("stage_error", {"stage": "_done_plan_part", "error": "the done list broke"}) in events
    assert orch._hook("_prep_plan_part", default="x") == "x"  # None: the default
    assert orch._hook("_no_such_hook", 1, 2, default=7) == 7
    with pytest.raises(BudgetExceeded):
        orch._hook("_money_gate")
    with pytest.raises(HarnessError):
        orch._hook("_done_gate", [])


# -- every call site --------------------------------------------------------------------------------------------
class AllStages(Orchestrator):
    calls: list

    def _prep_plan_part(self):
        return "\n# PREP PART\n"

    def _done_plan_part(self):
        return "\n# DONE PART\n"

    def _done_schema(self, schema):
        schema["properties"]["done_list"] = {"type": "array", "items": {"type": "string"}}

    def _done_doc(self, doc, args):
        doc["done_list"] = list(args.get("done_list") or ["You can open it"])

    def _stages_worker_part(self, task):
        return f"# STAGE PART for {task.id}"

    def _finish_estimate(self, tasks):
        return {"id": "finish", "usd": 0.5, "minutes": 3, "words": "start it and use it"}

    def _money_agreed(self):
        self.calls.append("agreed")

    def _money_charge(self, cost):
        self.calls.append(("charge", cost))

    def _money_gate(self):
        self.calls.append("gate")

    def _stage_ready(self, ready, tasks, running):
        self.calls.append(("ready", [t.id for t in ready], sorted(running)))

    def _finish_step(self, tasks):
        if not any(t.added_by for t in tasks):
            self.add_tasks([dict(EXTRA)], by="finish", why="it didn't start", fix_of="D1")
            return "again"
        return None

    def _done_gate(self, tasks):
        self.calls.append(("gate_end", sorted(t.id for t in tasks)))


def test_every_hook_is_called_where_it_belongs(tmp_path):
    AllStages.calls = []
    orch, events, brain = build(tmp_path, cls=AllStages, raw=dict(RAW, limits={"max_cost_usd": 5}),
                                brain=Brain(plan=ONE))
    orch.start("a made-up tool", require_approval=True)
    orch.plan()
    doc = orch.project.plan_doc()
    assert doc["done_list"] == ["You can open it"]
    assert doc["estimate"]["extras"] == [{"id": "finish", "usd": 0.5, "minutes": 3.0, "words": "start it and use it"}]
    assert doc["estimate"]["cost_usd"] >= 0.5
    orch.approve()
    assert "agreed" in AllStages.calls
    assert orch.run() == "done"
    tasks = {t.id: t for t in orch.project.tasks()}
    assert tasks["F1"].status == "done" and tasks["F1"].added_by == "finish" and tasks["F1"].fix_of == "D1"
    assert (tasks["F1"].files, tasks["F1"].stage, tasks["F1"].part) == (["f1.txt"], "slice", "game")
    assert "gate" in AllStages.calls
    assert any(c[0] == "charge" for c in AllStages.calls if isinstance(c, tuple))
    assert ("ready", ["T1"], []) in AllStages.calls and ("ready", ["F1"], []) in AllStages.calls
    assert ("gate_end", ["F1", "T1"]) in AllStages.calls  # the done gate ran once the added task was done
    assert ("gate_end", ["T1"]) not in AllStages.calls  # an "again" stops the later steps that round
    assert "tasks_added" in kinds(events)


def test_the_plan_and_worker_parts_reach_the_models(tmp_path):
    AllStages.calls = []
    seen = []
    brain = Brain(plan=ONE)

    def spy(model, system, messages, tools):
        seen.append((sorted(t.name for t in tools), messages[0]["content"], tools))
        return brain(model, system, messages, tools)

    orch, _, _ = build(tmp_path, cls=AllStages, brain=spy)
    orch.start("a made-up tool")
    orch.run()
    plan_prompt = next(p for names, p, _ in seen if "submit_plan" in names)
    assert plan_prompt.index("# PREP PART") < plan_prompt.index("# DONE PART")
    tool = next(t for names, _, tools in seen if "submit_plan" in names for t in tools if t.name == "submit_plan")
    assert "done_list" in tool.parameters["properties"]
    worker = next(p for names, p, _ in seen if "finish_task" in names and "# Your task [T1]" in p)
    assert "# STAGE PART for T1" in worker


def test_the_doc_parts_run_after_a_revision_too(tmp_path):
    AllStages.calls = []
    orch, _, _ = build(tmp_path, cls=AllStages, brain=Brain(plan=ONE))
    orch.start("a made-up tool", require_approval=True)
    orch.plan()
    r = orch.revise_plan("make it smaller")
    assert r["version"] == 2 and orch.project.plan_doc()["done_list"] == ["You can open it"]


class Stops(Orchestrator):
    def _done_gate(self, tasks):
        return "not_done"


def test_an_end_step_can_stop_the_run_with_its_own_status(tmp_path):
    orch, _, _ = build(tmp_path, cls=Stops, brain=Brain(plan=ONE))
    orch.start("a made-up tool")
    assert orch.run() == "not_done"
    assert not (orch.project.dir / "summary.md").exists()  # not finished: no report


class Loops(Orchestrator):
    def _finish_step(self, tasks):
        return "again"  # without adding work: must not go round for ever


def test_again_without_new_work_does_not_go_round_for_ever(tmp_path):
    orch, events, _ = build(tmp_path, cls=Loops, brain=Brain(plan=ONE))
    orch.start("a made-up tool")
    assert orch.run() == "done"
    assert any(k == "stage_error" and d["stage"] == "_finish_step" for k, d in events)


class Gated(Orchestrator):
    def _money_gate(self):
        self._set_status("paused", pause="over_estimate")
        return "paused"


def test_the_money_gate_stops_a_run(tmp_path):
    orch, _, _ = build(tmp_path, cls=Gated, brain=Brain(plan=ONE))
    orch.start("a made-up tool")
    assert orch.run() == "paused"
    assert orch.project.tasks()[0].status == "pending"


class Unstick(Orchestrator):
    def _unstick_task(self, task, tasks):
        self.unstuck = getattr(self, "unstuck", []) + [task.id]
        return False

    def _unstick_end(self, tasks):
        return True

    def _attention(self, key, text, details=""):
        self.cards = getattr(self, "cards", []) + [key]
        super()._attention(key, text, details)


def test_unstick_is_asked_after_a_failure_and_at_the_end(tmp_path):
    orch, events, _ = build(tmp_path, cls=Unstick, raw=dict(RAW, limits={"max_cost_usd": 5, "max_attempts_per_task": 1}),
                            brain=Brain(plan=ONE, reject_first=True))
    orch.start("a made-up tool")
    assert orch.run() == "blocked"
    assert orch.unstuck == ["T1"]
    assert "failed:T1" not in getattr(orch, "cards", [])  # the stage gives one card, not one a task


# -- the parallel path ------------------------------------------------------------------------------------------
class ParallelStages(AllStages):
    pass


def test_the_parallel_path_calls_the_same_hooks(tmp_path):
    ParallelStages.calls = []
    plan = [dict(ONE[0]), dict(ONE[0], id="T2", title="two", description="write two.txt")]
    orch, events, _ = build(tmp_path, cls=ParallelStages, raw=parallel_raw(2), brain=ParallelBrain(plan))
    orch.start("a made-up tool")
    assert orch.run() == "done"
    tasks = {t.id: t for t in orch.project.tasks()}
    assert tasks["F1"].status == "done" and tasks["F1"].added_by == "finish"
    assert ("gate_end", ["F1", "T1", "T2"]) in ParallelStages.calls
    assert any(c[0] == "ready" and "F1" in c[1] for c in ParallelStages.calls if isinstance(c, tuple))
    assert "gate" in ParallelStages.calls
    assert "parallel" in kinds(events)


def test_the_money_gate_stops_the_parallel_path(tmp_path):
    calls = []

    class G(Orchestrator):
        def _money_gate(self):
            calls.append(1)
            if len(calls) > 1:  # the first look is before the run; the second is before a task starts
                self._set_status("paused", pause="over_estimate")
                return "paused"

    plan = [dict(ONE[0]), dict(ONE[0], id="T2", title="two", description="write two.txt")]
    orch, _, _ = build(tmp_path, cls=G, raw=parallel_raw(2), brain=ParallelBrain(plan))
    orch.start("a made-up tool")
    assert orch.run() == "paused"
    assert orch.project.meta().get("pause") == "over_estimate"


# -- add_tasks --------------------------------------------------------------------------------------------------
def planned(tmp_path, **limits):
    raw = dict(RAW, limits={"max_cost_usd": 5, **limits})
    orch, events, _ = build(tmp_path, raw=raw, brain=Brain(plan=ONE))
    orch.start("a made-up tool", require_approval=True)
    orch.plan()
    return orch, events


def test_add_tasks_checks_saves_and_tells(tmp_path):
    orch, events = planned(tmp_path)
    new = orch.add_tasks([dict(EXTRA, depends_on=["T1"])], by="ship", why="the build needs an icon", fix_of="D2")
    assert [t.id for t in new] == ["F1"] and new[0].added_by == "ship" and new[0].fix_of == "D2"
    saved = {t.id: t for t in orch.project.tasks()}
    assert saved["F1"].depends_on == ["T1"] and saved["F1"].goal_index == 0
    doc = orch.project.plan_doc()
    assert doc["history"][-1]["by"] == "ship" and doc["history"][-1]["diff"]["added"] == ["F1"]
    assert doc["estimate"]["tasks"] == 2
    assert ("tasks_added", {"by": "ship", "why": "the build needs an icon", "fix_of": "D2", "tasks": ["F1"]}) in events
    assert "F1" in (orch.project.dir / "plan.md").read_text(encoding="utf-8")


def test_add_tasks_refuses_bad_tasks(tmp_path):
    orch, _ = planned(tmp_path)
    with pytest.raises(HarnessError, match="aren't right"):
        orch.add_tasks([dict(EXTRA, role="nobody")], by="ship", why="x")
    with pytest.raises(HarnessError, match="aren't right"):
        orch.add_tasks([dict(EXTRA, id="T1")], by="ship", why="x")  # an id already used
    with pytest.raises(HarnessError):
        orch.add_tasks([], by="ship", why="x")
    assert [t.id for t in orch.project.tasks()] == ["T1"]


def test_add_tasks_stops_at_the_limit(tmp_path):
    orch, _ = planned(tmp_path, max_auto_tasks=2)
    assert orch.cfg.limits.max_auto_tasks == 2
    orch.add_tasks([dict(EXTRA, id="F1"), dict(EXTRA, id="F2")], by="finish", why="two fixes")
    with pytest.raises(HarnessError, match="more than 2"):
        orch.add_tasks([dict(EXTRA, id="F3")], by="finish", why="one more")
    assert len(orch.project.tasks()) == 3


def test_add_tasks_refuses_when_the_owner_said_finish_with_whats_there(tmp_path):
    orch, _ = planned(tmp_path)
    meta = orch.project.meta()
    meta["no_auto_tasks"] = True
    orch.project.save_meta(meta)
    with pytest.raises(HarnessError, match="finish with what's there"):
        orch.add_tasks([dict(EXTRA)], by="finish", why="x")


def test_the_default_limit_is_eight():
    assert parse_config(json.loads(json.dumps(RAW))).limits.max_auto_tasks == 8
    assert {"prep", "finish", "unstick", "stages", "playtest", "ship"} <= set(FEATURE_SECTIONS)


# -- plandoc ----------------------------------------------------------------------------------------------------
def test_carry_over_keeps_the_stages_parts():
    old = {"decisions": [], "questions": [], "dont": [], "ideas": [], "version": 1, "history": [],
           "done_list": [{"id": "D1"}], "stages": [{"id": "S1"}], "parts": ["game"], "prep": {"brief": "b"},
           "warnings": ["w"]}
    new = {"decisions": [], "questions": [], "dont": [], "ideas": [], "stages": [{"id": "S9"}]}
    out = plandoc.carry_over(new, old)
    assert out["done_list"] == [{"id": "D1"}] and out["parts"] == ["game"] and out["prep"] == {"brief": "b"}
    assert out["warnings"] == ["w"] and out["stages"] == [{"id": "S9"}]  # the planner's new ones win


def test_estimate_adds_the_extras():
    cfg = parse_config(json.loads(json.dumps(RAW)))
    base = plandoc.estimate(cfg, [])
    assert base["extras"] == [] and base["cost_usd"] == 0
    got = plandoc.estimate(cfg, [], extras=[{"id": "play", "usd": 0.25, "minutes": 2, "words": "a person plays"},
                                            {"id": "bad", "usd": "lots"}, "nonsense"])
    assert got["cost_usd"] == 0.25 and got["minutes"] == 2
    assert got["extras"] == [{"id": "play", "usd": 0.25, "minutes": 2.0, "words": "a person plays"}]


# -- kinds ------------------------------------------------------------------------------------------------------
def test_a_kind_may_say_how_to_start_and_ship_it():
    # the shapes d2-ship made strict (ship: build + artefact; start: command, port, ready; tests/test_ship.py)
    kind = {"schema": "kind@1", "id": "web-app", "name": "Web app",
            "start": {"command": "npm start", "port": 3000, "ready": "/"},
            "ship": {"build": "npm run build", "artefact": "dist/*.zip"}}
    data, probs = kindmodel.validate(kind, known_needs=set())
    assert probs == [] and data["start"]["command"] == "npm start"
    extra = {"schema": "extra@1", "id": "installer", "name": "Installer",
             "ship": {"build": "make installer", "artefact": "dist/*.exe"}}
    assert kindmodel.validate(extra, is_extra=True, known_needs=set())[1] == []
    for bad in ({"command": ["npm", "start"]}, "npm start", {"command": "x" * 600}, {"url": "http://localhost"}):
        _, probs = kindmodel.validate(dict(kind, start=bad), known_needs=set())
        assert probs and "start" in probs[0]
    _, probs = kindmodel.validate(dict(extra, start={"command": "x"}), is_extra=True, known_needs=set())
    assert probs  # an extra has no start of its own


# -- the done list ----------------------------------------------------------------------------------------------
def test_the_done_list_keeps_items_and_results(tmp_path):
    root = tmp_path / "proj"
    assert donelist.read(root) == {"goal_index": 0, "items": [], "rounds": []}
    assert donelist.verdict(root) == {"done": True, "failed": [], "unchecked": []}  # nothing listed: no stop
    d1 = donelist.add_item(root, {"text": "You can start a game,  lose and start again", "how": "journey",
                                  "must": True, "by": "planner", "steps": [{"open": "/"}]})
    d2 = donelist.add_item(root, {"text": "It has a picture", "how": "teleport", "by": "nobody", "must": False})
    assert donelist.path(root) == root / ".harness" / "done.json" and donelist.path(root).is_file()
    assert (d1["id"], d1["state"], d1["text"], d1["steps"]) == ("D1", "open", "You can start a game, lose and start again",
                                                               [{"open": "/"}])
    assert (d2["id"], d2["how"], d2["by"]) == ("D2", "look", "planner")
    assert donelist.verdict(root) == {"done": False, "failed": [], "unchecked": ["D1"]}  # D2 isn't a must
    donelist.record(root, "D1", False, "the restart button does nothing", {"shot": "a.png"}, by="finish")
    assert donelist.verdict(root) == {"done": False, "failed": ["D1"], "unchecked": []}
    item = donelist.record(root, "D1", True, "works now", by="finish")
    assert item["state"] == "passed" and item["checked_by"] == "finish"
    assert donelist.verdict(root)["done"] is True
    donelist.record(root, "D1", None, "couldn't tell")
    assert donelist.verdict(root)["unchecked"] == ["D1"]
    data = donelist.read(root)
    assert [r["passed"] for r in data["rounds"]] == [False, True, None]
    again = donelist.add_item(root, {"id": "D1", "text": "Reworded", "how": "command", "command": "pytest"})
    assert again["state"] == "open" and [i["id"] for i in donelist.read(root)["items"]] == ["D2", "D1"]
    with pytest.raises(KeyError):
        donelist.record(root, "D9", True, "")
    with pytest.raises(ValueError):
        donelist.add_item(root, {"text": "  "})


def test_a_broken_done_list_reads_as_empty(tmp_path):
    root = tmp_path / "proj"
    donelist.path(root).parent.mkdir(parents=True)
    donelist.path(root).write_text("{not json", encoding="utf-8")
    assert donelist.read(root)["items"] == []
    assert donelist.add_item(root, {"text": "It opens"})["id"] == "D1"
