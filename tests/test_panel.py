"""The panel of checkers (wave 6, "checking each other"): work is checked by a model from another maker,
hard and risky tasks get two checkers and a third on a split, and a rejection must quote the line it breaks.

Every project is made up, in tmp_path; the models are scripted and each provider is its own maker.
"""

import json

import pytest

from roundtable.harness import dial, panel
from roundtable.harness import projectsettings as ps
from roundtable.harness.config import parse_config
from roundtable.harness.panel import PanelStage
from roundtable.providers.base import ProviderError
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider

from .test_harness import reply, tool_names
from .test_stage_hooks import Seam

DESC = "write one.txt holding the word hello"
ACC = "one.txt exists and holds hello"
PLAN = [{"id": "T1", "title": "one", "role": "coder", "description": DESC, "acceptance": ACC, "depends_on": []}]
QUOTE = "holding the WORD   hello"  # case and spacing differ from the task: still a quote


def raw(reviewers=("a/rev-a", "b/rev-b", "c/rev-c", "d/rev-d"), critic=None):
    models = ["a/planner", "a/coder", *reviewers] + ([critic] if critic else [])
    r = {
        "providers": {p: {"type": "scripted"} for p in "abcd"} | {"img": {"type": "scripted_images"}},
        "roles": {
            "orchestrator": {"model": "a/planner"},
            "coder": {"model": "a/coder", "description": "writes code"},
            "reviewer": {"model": reviewers[0], "fallback": list(reviewers[1:])},
        },
        "pricing": {m: {"input": 1, "output": 1} for m in models},
        "limits": {"max_cost_usd": 50, "max_attempts_per_task": 3},
    }
    if critic:
        r["roles"]["critic"] = {"model": critic}
    return r


class Brain:
    """Plans PLAN, builds one.txt, and gives each checker's verdicts in turn (``verdicts[model]``); a checker
    with none left approves. ``calls``: the checker models asked, in order; ``prompts``: what each was told."""

    def __init__(self, verdicts=None, broken=()):
        self.verdicts = {k: list(v) for k, v in (verdicts or {}).items()}
        self.broken = set(broken)
        self.calls, self.prompts = [], []

    def __call__(self, model, system, messages, tools):
        names = tool_names(tools)
        last = messages[-1]
        if "submit_plan" in names:
            return reply("planned") if last["role"] == "tool" else reply(calls=[("submit_plan", {"tasks": PLAN})])
        if "submit_review" in names:
            if last["role"] == "tool":
                return reply("ok")
            if model in self.broken:
                return ProviderError(f"{model}: out of service")
            self.calls.append(model)
            self.prompts.append(messages[0]["content"])
            queue = self.verdicts.get(model) or []
            v = queue.pop(0) if queue else {"approved": True, "feedback": f"fine by {model}"}
            return reply(calls=[("submit_review", v)])
        if "finish_task" in names:
            if last["role"] == "user":
                return reply(calls=[("write_file", {"path": "one.txt", "content": "hello\n"})])
            return reply(calls=[("finish_task", {"summary": f"done by {model}"})])
        return reply("Final report: all done.")


def no(feedback="it is wrong", breaks=None):
    v = {"approved": False, "feedback": feedback}
    if breaks is not None:
        v["breaks"] = breaks
    return v


YES = {"approved": True, "feedback": "it works"}


# the Orchestrator without its stages, plus this one (once hooked up, the coordinator lists it in STAGES)
P = Seam if issubclass(Seam, PanelStage) else type("P", (PanelStage, Seam), {})


def setup(tmp_path, monkeypatch, brain, n=1, level=None, r=None, allow=True):
    cfg = parse_config(json.loads(json.dumps(r or raw())))
    for p in "abcd":
        cfg.register(p, ScriptedProvider(p, brain))
    cfg.register("img", ScriptedImages())
    events = []
    orch = P(cfg, tmp_path / "proj", on_event=lambda k, d: events.append((k, d)))
    monkeypatch.setattr(dial, "for_task", lambda o, t: {"rivals": 1, "panel": n, "explore": False,
                                                         "why": "hard" if n > 1 else ""})
    if allow is not True:
        monkeypatch.setattr(dial, "allow", allow)
    orch.start("a made-up tool")
    orch.plan()
    if level:
        meta = orch.project.meta()
        meta["checking"] = level
        orch.project.save_meta(meta)
    brain.calls.clear()
    return orch, events


def run(orch):
    assert orch.run() == "done"
    return orch.project.tasks()[0]


def rows(orch):
    p = orch.project.root / ".harness" / panel.LEDGER
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


# -- who checks ------------------------------------------------------------------------------------------------
def test_the_builders_maker_is_never_picked_when_another_exists(tmp_path, monkeypatch):
    brain = Brain()
    orch, _ = setup(tmp_path, monkeypatch, brain)
    t = run(orch)
    assert brain.calls == ["rev-b"]  # the builder is a/coder: a/rev-a, first in the chain, is passed over
    a = t.attempts[-1]
    assert a["outcome"] == "approved" and a["same_maker"] is False and a["disagreed"] is False
    assert [(r["model"], r["maker"], r["approved"], r["counted"]) for r in a["reviews"]] == [
        ("b/rev-b", "b", True, True)]


def test_the_critics_chain_is_used_when_the_reviewers_are_all_the_builders_maker(tmp_path, monkeypatch):
    brain = Brain()
    orch, _ = setup(tmp_path, monkeypatch, brain, r=raw(reviewers=("a/rev-a",), critic="c/crit"))
    run(orch)
    assert brain.calls == ["crit"]


def test_with_one_maker_only_the_run_works_and_is_marked(tmp_path, monkeypatch):
    brain = Brain()
    orch, events = setup(tmp_path, monkeypatch, brain, n=2, r=raw(reviewers=("a/rev-a",)))
    t = run(orch)
    assert brain.calls == ["rev-a"]  # nobody else to ask: the first reviewer, as today
    assert t.attempts[-1]["same_maker"] is True and t.status == "done"
    assert "stage_error" not in [k for k, _ in events]
    assert panel.same_maker_warnings(orch.cfg) == [panel.SAME_MAKER]
    other = parse_config(json.loads(json.dumps(raw())))
    assert panel.same_maker_warnings(other) == []


def test_panel_never_uses_a_model_the_project_does_not_allow(tmp_path, monkeypatch):
    brain = Brain(verdicts={"rev-c": [YES], "rev-d": [no(breaks=QUOTE)]})
    orch, _ = setup(tmp_path, monkeypatch, brain, n=3)
    ps.update(orch.project.root, {"providers_allowed": ["a", "c", "d"], "makers_allowed": ["a", "c"]})
    run(orch)
    assert "rev-b" not in brain.calls and "rev-d" not in brain.calls
    # c is the only other maker allowed; the second seat goes to the reviewer left (the builder's maker)
    assert brain.calls == ["rev-c", "rev-a"]
    assert not orch._may_use(parse_config(raw()).roles["reviewer"].models[1])


def test_a_checker_that_cannot_be_reached_is_passed_over(tmp_path, monkeypatch):
    brain = Brain(broken={"rev-b"})
    orch, events = setup(tmp_path, monkeypatch, brain)
    t = run(orch)
    assert brain.calls == ["rev-c"] and t.attempts[-1]["reviews"][0]["model"] == "c/rev-c"
    assert "panel_skip" in [k for k, _ in events]


# -- the quote rule --------------------------------------------------------------------------------------------
def test_a_rejection_quoting_a_real_line_counts(tmp_path, monkeypatch):
    brain = Brain(verdicts={"rev-b": [no("one.txt is empty", breaks=QUOTE)]})
    orch, _ = setup(tmp_path, monkeypatch, brain)
    t = run(orch)
    first = t.attempts[0]
    assert first["outcome"] == "rejected" and brain.calls == ["rev-b", "rev-b"]  # no re-ask; then the 2nd build
    assert first["reviews"][0]["counted"] is True and first["reviews"][0]["breaks"] == QUOTE
    assert "one.txt is empty" in first["review"] and QUOTE in first["review"]
    assert t.attempts[1]["outcome"] == "approved"


def test_reviews_can_no_longer_reject_for_the_wrong_reasons(tmp_path, monkeypatch):
    """gaps.md: "a rejection should quote the line of the task it breaks or not count". An unquoted rejection
    is asked once more for its quote, then another maker decides."""
    brain = Brain(verdicts={"rev-b": [no("I prefer tabs"), no("still tabs", breaks="use tabs everywhere")]})
    orch, _ = setup(tmp_path, monkeypatch, brain)
    t = run(orch)
    assert brain.calls == ["rev-b", "rev-b", "rev-c"]
    assert panel.REASK in brain.prompts[1] and "I prefer tabs" in brain.prompts[1]
    a = t.attempts[0]
    assert a["outcome"] == "approved" and len(t.attempts) == 1
    assert [(r["model"], r["counted"]) for r in a["reviews"]] == [
        ("b/rev-b", False), ("b/rev-b", False), ("c/rev-c", True)]
    assert a["reviews"][1]["reasked"] is True


def test_a_reasked_checker_that_quotes_counts(tmp_path, monkeypatch):
    brain = Brain(verdicts={"rev-b": [no("wrong"), no("wrong", breaks=f"“{ACC.upper()}.”")]})
    orch, _ = setup(tmp_path, monkeypatch, brain)
    t = run(orch)
    assert t.attempts[0]["outcome"] == "rejected" and brain.calls[:2] == ["rev-b", "rev-b"]
    assert t.attempts[0]["reviews"][-1]["counted"] is True and "rev-c" not in brain.calls[:3]


def test_an_unquoted_rejection_with_nobody_else_counts_and_is_marked(tmp_path, monkeypatch):
    brain = Brain(verdicts={"rev-a": [no("bad"), no("bad")]})
    orch, _ = setup(tmp_path, monkeypatch, brain, r=raw(reviewers=("a/rev-a",)))
    t = run(orch)
    first = t.attempts[0]
    assert first["outcome"] == "rejected"  # never turned into a pass by itself
    assert first["reviews"][-1]["counted"] == "unquoted" and "did not quote" in first["review"]
    assert t.attempts[1]["outcome"] == "approved"


def test_the_quote_match():
    texts = [DESC, "Short line", "Traceback ...\nAssertionError: expected 3 got 4"]
    assert panel.quoted("  Holding The  Word hello. ", texts)
    assert panel.quoted("“expected 3 got 4”", texts)
    assert panel.quoted("short line", texts)  # a whole short line counts
    assert not panel.quoted("short", texts)  # too short, and not a whole line
    assert not panel.quoted("tabs not spaces everywhere", texts)
    assert panel.quoted("write one.txt ... the word hello", texts)
    assert not panel.quoted("write one.txt ... the word goodbye", texts)
    assert not panel.quoted("", texts) and not panel.quoted(None, texts)


def test_the_plan_s_donts_the_done_list_and_failing_tests_can_be_quoted(tmp_path, monkeypatch):
    orch, _ = setup(tmp_path, monkeypatch, Brain())
    doc = orch.project.plan_doc()
    doc["dont"] = [{"id": "D1", "text": "never add a login screen", "by": "owner"}]
    doc["done_list"] = [{"id": "W1", "text": "a person can save their work"}]
    orch.project.save_plan_doc(doc)
    task = orch.project.tasks()[0]
    checks = {"verdict": "new", "text": "", "new": ["test_saves_the_file"], "now": {"tail": "E  KeyError: 'name'"}}
    texts = panel.sources(orch, task, checks)
    for q in ("never add a login screen", "can save their work", "test_saves_the_file", "keyerror: 'name'"):
        assert panel.quoted(q, texts), q
    assert not panel.quoted("test_saves_the_file", panel.sources(orch, task, None))


# -- the verdict -----------------------------------------------------------------------------------------------
def test_two_that_agree_need_no_third(tmp_path, monkeypatch):
    brain = Brain()
    orch, _ = setup(tmp_path, monkeypatch, brain, n=2)
    t = run(orch)
    assert brain.calls == ["rev-b", "rev-c"]
    a = t.attempts[-1]
    assert a["disagreed"] is False and [r["maker"] for r in a["reviews"]] == ["b", "c"]
    spent = [json.loads(x) for x in (orch.project.root / dial.LEDGER).read_text().splitlines()]
    assert [(s["what"], s["task"]) for s in spent] == [("panel", "T1")]  # the second checker is extra


def test_three_checkers_stop_as_soon_as_two_agree(tmp_path, monkeypatch):
    brain = Brain()
    orch, _ = setup(tmp_path, monkeypatch, brain, n=3)
    run(orch)
    assert brain.calls == ["rev-b", "rev-c"]


@pytest.mark.parametrize("third,outcome", [(YES, "approved"), (no("off by one", breaks=ACC), "rejected")])
def test_a_split_goes_to_a_third_maker_who_decides(tmp_path, monkeypatch, third, outcome):
    brain = Brain(verdicts={"rev-c": [no("it is empty", breaks=QUOTE)], "rev-d": [third]})
    orch, _ = setup(tmp_path, monkeypatch, brain, n=2)
    orch.run()
    t = orch.project.tasks()[0]
    a = t.attempts[0]
    assert brain.calls[:3] == ["rev-b", "rev-c", "rev-d"]
    assert a["outcome"] == outcome and a["disagreed"] is True
    assert [r["model"] for r in a["reviews"]] == ["b/rev-b", "c/rev-c", "d/rev-d"]
    if outcome == "rejected":  # the worker hears every rejecting checker, each with its quote
        assert "it is empty" in a["review"] and QUOTE in a["review"] and "off by one" in a["review"]
    got = [r for r in rows(orch) if r["kind"] == "decision"][0]
    assert got["disagreed"] is True and got["checkers"] == 3 and got["approved"] is (outcome == "approved")
    assert len([r for r in rows(orch) if r["kind"] == "verdict"]) >= 3


def test_a_split_with_no_third_maker_goes_to_the_strongest_reviewer_left(tmp_path, monkeypatch):
    brain = Brain(verdicts={"rev-c": [no("it is empty", breaks=QUOTE)]})
    orch, _ = setup(tmp_path, monkeypatch, brain, n=2, r=raw(reviewers=("a/rev-a", "b/rev-b", "c/rev-c")))
    t = run(orch)
    assert brain.calls[:3] == ["rev-b", "rev-c", "rev-a"]  # no third maker: a reviewer left decides
    assert t.attempts[0]["disagreed"] is True and t.attempts[0]["same_maker"] is True


def test_the_costs_are_added_up_into_one_result(tmp_path, monkeypatch):
    brain = Brain(verdicts={"rev-c": [no("it is empty", breaks=QUOTE)]})
    orch, _ = setup(tmp_path, monkeypatch, brain, n=2)
    task = orch.project.tasks()[0]
    ok, fb, res = orch._panel_review(task, "done", None, False, parse_config(raw()).roles["coder"].models[0])
    assert ok and res.model.count(",") == 2 and res.steps >= 3
    assert res.cost_usd > 0 and orch._panel_attempt(task, "a/coder")["disagreed"] is True
    assert orch._panel_attempt(task, "a/coder") is None  # taken once, by the attempt it belongs to


# -- lean and money --------------------------------------------------------------------------------------------
def test_at_lean_there_is_exactly_one_review_call_as_today(tmp_path, monkeypatch):
    brain = Brain(verdicts={"rev-a": [no("bad")]})
    orch, _ = setup(tmp_path, monkeypatch, brain, n=3, level="lean")
    t = run(orch)
    # today's reviewer, even of the builder's maker, then the next one after a rejection; no re-ask, no panel
    assert brain.calls == ["rev-a", "rev-b"]
    assert t.attempts[0]["outcome"] == "rejected" and "reviews" not in t.attempts[0]
    assert rows(orch) == []


def test_the_allowance_refusing_extra_checkers_leaves_one_checker(tmp_path, monkeypatch):
    brain = Brain(verdicts={"rev-b": [no("bad")]})
    orch, _ = setup(tmp_path, monkeypatch, brain, n=3, allow=lambda o, what, usd: False)
    t = run(orch)
    assert brain.calls[0] == "rev-b" and brain.calls[1] == "rev-b"  # first review, then the next build's
    first = t.attempts[0]
    assert first["outcome"] == "rejected" and first["reviews"][-1]["counted"] == "unquoted"
    assert len(first["reviews"]) == 1  # no re-ask, no second maker, no second seat
    assert not (orch.project.root / dial.LEDGER).exists()
