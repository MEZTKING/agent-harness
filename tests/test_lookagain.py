"""The critic looks again (wave 9): a revision that changes a third of the tasks marks the critique as about an
earlier version and offers one new look, priced, as a card. Made-up plans; no model is called."""

from types import SimpleNamespace

from roundtable.harness import lookagain


class Cfg:
    critic_role = "critic"
    roles = {"critic": SimpleNamespace(models=["deepseek/deepseek-chat"])}

    def cost(self, model, usage):
        return round(usage.input_tokens * 1e-6 + usage.output_tokens * 2e-6, 6)


def _orch(tmp_path, doc):
    calls = []

    def critique():
        calls.append(1)
        doc["critique"] = {"verdict": "good", "points": [], "version": doc["version"]}
        return doc["critique"]

    orch = SimpleNamespace(project=SimpleNamespace(root=tmp_path, plan_doc=lambda: doc), _critique=critique)
    return orch, calls


def test_a_third_of_the_tasks_changed_marks_the_critique_and_offers_a_priced_look(tmp_path):
    doc = {"version": 2, "critique": {"verdict": "good", "points": [], "version": 1}}
    diff = {"added": ["T7"], "changed": ["T2"], "removed": [], "unchanged": 4}
    assert lookagain.changed_share(diff, 6) == 2 / 6
    assert lookagain.mark(tmp_path, doc, diff, 6, cfg=Cfg()) is True
    assert doc["critique"]["stale"] and "earlier version (v1)" in doc["critique"]["stale_words"]
    orch, calls = _orch(tmp_path, doc)
    card = lookagain.ask(orch)
    assert card["kind"] == "look_again" and card["recommended"] == "yes"
    assert "$0.03" in card["options"][0]["description"]  # priced first: 25,000 in and 2,500 out
    assert not any(o.get("confirm") for o in card["options"])  # autopilot may answer it within its allowance
    got = lookagain.apply(orch, card, ["yes"])
    assert calls == [1] and "looks right" in got["reply"]
    assert lookagain.ask(orch) is None  # asked once


def test_a_small_revision_or_no_critique_is_left_alone(tmp_path):
    doc = {"version": 2, "critique": {"verdict": "good", "points": [], "version": 1}}
    assert lookagain.mark(tmp_path, doc, {"added": [], "changed": ["T2"], "removed": []}, 6) is False
    assert "stale" not in doc["critique"]
    assert lookagain.mark(tmp_path, {"version": 2}, {"added": ["T1", "T2", "T3"]}, 3) is False
    same = {"version": 2, "critique": {"version": 2}}
    assert lookagain.mark(tmp_path, same, {"changed": ["T1", "T2"]}, 3) is False  # already about this version
    orch, calls = _orch(tmp_path, doc)
    assert lookagain.ask(orch) is None


def test_saying_no_keeps_the_old_critique(tmp_path):
    doc = {"version": 3, "critique": {"verdict": "revise", "points": [], "version": 1}}
    lookagain.mark(tmp_path, doc, {"removed": ["T1", "T2"]}, 4)
    orch, calls = _orch(tmp_path, doc)
    card = lookagain.ask(orch)
    assert "isn't known" in card["options"][0]["description"]  # no price known: said, never invented
    assert "earlier version" in lookagain.apply(orch, card, ["no"])["reply"] and calls == []
    assert lookagain.ask(orch) is None
