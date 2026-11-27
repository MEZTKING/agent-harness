"""Prep (wave 5, d2-done; parity MD-08): the owner's idea tidied into a brief before planning.

The owner's words stay the goal, the call is capped, and any trouble means no brief, never a failed plan.
Made-up projects, scripted models.
"""

import json

from roundtable.harness import prep
from roundtable.harness.donestage import DoneStage
from roundtable.harness.orchestrator import Orchestrator
from roundtable.providers.base import ProviderError
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider, reply

from .test_harness import RAW, Brain

ONE = [{"id": "T1", "title": "one", "role": "coder", "description": "write one.txt", "acceptance": "exists",
        "depends_on": []}]
GOAL = "a  little snake game for my phone, like the old Nokia one"
BRIEF = {"what": "A snake game that runs in a phone's browser.", "who": "The owner, playing on their phone.",
         "implied": ["Touch controls for turning", "A high score that's kept"],
         "unclear": ["Should it work without the internet?"]}


# before the hook-up the stage is laid over a bare Orchestrator; after it, Orchestrator has it already
BASES = (Orchestrator,) if issubclass(Orchestrator, DoneStage) else (DoneStage, Orchestrator)


class O(*BASES):
    def _kind_proof(self):
        return []


class PrepBrain(Brain):
    def __init__(self, fail=False, empty=False):
        super().__init__(plan=ONE)
        self.fail, self.empty, self.prep_calls, self.plan_prompts = fail, empty, 0, []

    def __call__(self, model, system, messages, tools):
        names = {t.name for t in tools}
        if "submit_brief" in names:
            self.prep_calls += 1
            if self.fail:
                raise ProviderError("the model is away")
            return reply("hmm") if self.empty else reply(calls=[("submit_brief", BRIEF)])
        if "submit_plan" in names and messages[-1]["role"] == "user":
            self.plan_prompts.append(messages[0]["content"])
            return reply(calls=[("submit_plan", {"tasks": ONE, "in_scope": ["A snake that grows",
                                                                            "A high score that's kept on the phone"]})])
        return super().__call__(model, system, messages, tools)


def build(tmp_path, brain, prep_cfg=None):
    raw = json.loads(json.dumps(RAW))
    raw["prep"] = {"enabled": True, **(prep_cfg or {})}
    from roundtable.harness.config import parse_config

    cfg = parse_config(raw)
    for name in ("a", "b"):
        cfg.register(name, ScriptedProvider(name, brain))
    cfg.register("img", ScriptedImages())
    events = []
    return O(cfg, tmp_path / "proj", on_event=lambda k, d: events.append((k, d))), events


def test_the_brief_keeps_the_owners_words_and_adds_ideas_not_scope(tmp_path):
    brain = PrepBrain()
    orch, events = build(tmp_path, brain)
    orch.start(GOAL, require_approval=True)
    orch.plan()
    doc = orch.project.plan_doc()
    assert doc["goal"] == GOAL and orch.project.meta()["goals"] == [GOAL]  # word for word, double space and all
    assert doc["prep"]["brief"] == BRIEF and doc["prep"]["cost_usd"] > 0
    assert "# The idea, tidied" in brain.plan_prompts[0] and "never as scope" in brain.plan_prompts[0]
    assert brain.plan_prompts[0].index(GOAL) < brain.plan_prompts[0].index("# The idea, tidied")
    ideas = {i["text"]: i for i in doc["ideas"]}
    assert "Touch controls for turning" in ideas and ideas["Touch controls for turning"]["state"] == "open"
    assert "A high score that's kept on the phone" in ideas  # only the brief asked for it: moved to the ideas
    assert doc["in_scope"] == ["A snake that grows"]
    assert ("prep", {"brief": True, "why": "", "cost_usd": doc["prep"]["cost_usd"]}) in events
    saved = json.loads((orch.project.dir / "prep.json").read_text(encoding="utf-8"))
    assert saved["0"]["goal"] == GOAL
    orch.revise_plan("make it faster")  # the same goal: the brief is reused, not paid for again
    assert brain.prep_calls == 1 and orch.project.plan_doc()["prep"]["brief"] == BRIEF


def test_the_cap_is_respected(tmp_path):
    brain = PrepBrain()
    orch, _ = build(tmp_path, brain, {"max_usd": 0.0000001})
    orch.start(GOAL, require_approval=True)
    orch.plan()
    assert brain.prep_calls == 0 and "prep" not in orch.project.plan_doc()
    assert prep.stored(orch, 0, GOAL)["why"] == "too_dear"
    # the spend never passes the cap: one call's real cost is under max_usd
    brain2 = PrepBrain()
    orch2, _ = build(tmp_path / "b", brain2, {"max_usd": 0.05})
    orch2.start(GOAL, require_approval=True)
    orch2.plan()
    assert 0 < orch2.project.plan_doc()["prep"]["cost_usd"] <= 0.05


def test_a_provider_error_means_no_brief_and_the_plan_goes_on(tmp_path):
    for brain in (PrepBrain(fail=True), PrepBrain(empty=True)):
        orch, events = build(tmp_path / str(id(brain)), brain)
        orch.start(GOAL, require_approval=True)
        tasks = orch.plan()
        assert [t.id for t in tasks] == ["T1"] and "prep" not in orch.project.plan_doc()
        assert prep.stored(orch, 0, GOAL)["why"] in ("error", "no_answer")
        assert "# The idea, tidied" not in brain.plan_prompts[0]


def test_off_and_test_models_make_no_call(tmp_path):
    brain = PrepBrain()
    orch, _ = build(tmp_path, brain, {"enabled": False})
    orch.start(GOAL, require_approval=True)
    orch.plan()
    assert brain.prep_calls == 0 and prep.stored(orch, 0, GOAL)["why"] == "off"
    # left out: on, but not for a scripted (test) planner, so every other test's script stays as it was
    raw = json.loads(json.dumps(RAW))
    from roundtable.harness.config import parse_config

    cfg = parse_config(raw)
    b2 = PrepBrain()
    for name in ("a", "b"):
        cfg.register(name, ScriptedProvider(name, b2))
    cfg.register("img", ScriptedImages())
    orch2 = O(cfg, tmp_path / "two")
    orch2.start(GOAL, require_approval=True)
    orch2.plan()
    assert b2.prep_calls == 0 and prep.stored(orch2, 0, GOAL)["why"] == "dry"


def test_what_is_to_hand_has_nothing_from_the_hub(tmp_path):
    orch, _ = build(tmp_path, PrepBrain())
    orch.start(GOAL)
    text = prep.gather(orch)
    assert "journal" not in text.lower() and len(text) <= prep.MAX_CONTEXT
