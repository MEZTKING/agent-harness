"""Questions as cards to tap (asks.py): what waits, in what order, and that every answer goes through
the orchestrator's own actions. Made-up projects, scripted models, no network."""

import json

import pytest

from roundtable import asks as asklib
from roundtable.harness import plandoc
from roundtable.harness.orchestrator import HarnessError, Orchestrator
from roundtable.providers.scripted import reply

from .test_harness import PLAN, RAW, Brain, make, tool_names
from .test_look import direction
from .test_plan import DOC, PlanBrain

QUESTIONS = [{"id": "Q1", "header": "Bakery's name", "text": "What is the bakery called?", "why": "for the logo",
              "options": [{"id": "a", "label": "Crumbs & Co", "detail": "short and warm"},
                          {"id": "b", "label": "The Oven Door", "detail": "a little old-fashioned"}],
              "recommended": "a"},
             {"id": "Q2", "text": "Which pages matter most?", "multi": True,
              "options": [{"id": "a", "label": "Menu"}, {"id": "b", "label": "Opening hours"}, {"id": "c", "label": "Map"}]}]


def with_profiles(raw=RAW):
    raw = json.loads(json.dumps(raw))
    raw["profiles"] = {"budget": {"description": "cheapest", "roles": {"coder": {"model": "a/coder"}}},
                       "balanced": {"roles": {"coder": {"model": "a/coder", "fallback": ["b/coder2"]}}},
                       "quality": {"description": "strongest", "roles": {"coder": {"model": "b/coder2"}}}}
    return raw


class CardBrain(PlanBrain):
    """The planner's questions come with answers to tap."""

    def __init__(self, questions=QUESTIONS, **kw):
        super().__init__(**kw)
        self.questions = questions

    def __call__(self, model, system, messages, tools):
        resp = super().__call__(model, system, messages, tools)
        if "submit_plan" in tool_names(tools) and resp.tool_calls:
            resp.tool_calls[0].arguments["questions"] = json.loads(json.dumps(self.questions))
        return resp


class RejectBrain(Brain):
    """The reviewer never passes the coder's work: the task fails."""

    def __call__(self, model, system, messages, tools):
        if "submit_review" in tool_names(tools) and messages[-1]["role"] != "tool":
            return reply(calls=[("submit_review", {"approved": False, "feedback": "the greeting is missing"})])
        return super().__call__(model, system, messages, tools)


def planned(tmp_path, raw=None, brain=None, confirm_kind=True):
    orch, *_ = make(tmp_path, raw=raw or with_profiles(), brain=brain or CardBrain())
    orch.start("bakery site", require_approval=True)
    if confirm_kind:  # as the wizard does; the kind card has its own tests
        orch.set_kind("website", by="owner", replan=False)
    assert orch.run() == "awaiting_approval"
    return orch


def add_looks(orch):
    doc = orch.project.plan_doc()
    doc["look"] = {"directions": [direction(i) for i in range(3)], "chosen": None, "pictures": {}}
    orch.project.save_plan_doc(doc)


def ids(orch):
    return [a["id"] for a in asklib.open_asks(orch)]


def test_a_waiting_plan_becomes_cards_in_order(tmp_path):
    orch = planned(tmp_path)
    add_looks(orch)
    asks = asklib.open_asks(orch)
    assert [a["id"] for a in asks] == ["choose:C1", "answer:Q1", "answer:Q2", "look", "profile", "idea:I1", "approve"]
    for a in asks:
        assert len(a["header"]) <= 12 and a["allow_other"] and a["stamp"] and a["answer"] is None
        assert a["project"] == "proj" and a["path"] == str(orch.project.root)
        if a["recommended"]:
            assert a["options"][0]["id"] == a["recommended"]  # the recommendation comes first
    c1, q1, q2, look, prof, idea, appr = asks
    assert c1["kind"] == "decision" and [o["label"] for o in c1["options"]] == ["Pixel art", "Watercolour"]
    assert c1["options"][0]["description"] == "matches the site · cheap" and "pixel-art" in c1["detail"]
    assert q1["header"] == "Bakery's nam" and q1["options"][0]["label"] == "Crumbs & Co" and not q1["multi"]
    assert q2["multi"] and q2["header"] == "Question" and len(q2["options"]) == 3
    assert [o["id"] for o in look["options"]] == ["A", "B", "C"] and look["options"][0]["picture"] == "A"
    assert prof["recommended"] == "balanced" and {o["id"] for o in prof["options"]} == {"budget", "balanced", "quality"}
    assert prof["options"][0]["description"].startswith("About $")
    assert [o["label"] for o in idea["options"]] == ["Yes, add it", "No thanks"]
    assert appr["options"][0]["label"] == "Approve and start" and "About $" in appr["options"][0]["description"]
    # the planner's ready answers are in the plan (and its markdown, for the phone and the hub)
    md = (orch.project.dir / "plan.md").read_text(encoding="utf-8")
    assert "Answers: Crumbs & Co (recommended) {a}; The Oven Door {b}" in md and "Answers (any of)" in md


def test_answering_each_plan_card_uses_the_plan_actions(tmp_path):
    orch = planned(tmp_path)
    add_looks(orch)
    r = asklib.answer_ask(orch, "choose:C1", ["b"])
    assert r["then"] is None and "Watercolour" in r["reply"]
    asklib.answer_ask(orch, "answer:Q1", [], other="Bun Voyage")  # typed: goes where typed answers went
    asklib.answer_ask(orch, "answer:Q2", ["a", "c"], other="and a contact form")
    asklib.answer_ask(orch, "idea:I1", ["no"])
    asklib.answer_ask(orch, "look", ["B"], other="warmer colours")
    asklib.answer_ask(orch, "profile", ["budget"])
    doc = orch.project.plan_doc()
    assert doc["decisions"][0]["chosen"] == "b"
    q1, q2 = doc["questions"]
    assert q1["answer"] == "Bun Voyage" and q1["chosen"] == []
    assert q2["answer"] == "Menu; Map; and a contact form" and q2["chosen"] == ["a", "c"]
    shown = {a["id"]: a["answer"] for a in asklib.open_asks(orch, answered=True)}
    assert shown["answer:Q2"] == {"chosen": ["a", "c"], "other": "and a contact form"}
    assert shown["idea:I1"] == {"chosen": ["no"], "other": ""} and shown["look"] == {"chosen": ["B"], "other": "warmer colours"}
    assert shown["profile"] == {"chosen": ["budget"], "other": ""}
    assert doc["ideas"][0]["state"] == "rejected"
    assert doc["look"]["chosen"] == "B" and doc["look"]["note"] == "warmer colours"
    assert orch.project.meta()["profile"] == "budget"
    assert ids(orch) == ["approve"]
    appr = asklib.open_asks(orch)[0]
    assert appr["options"][0]["id"] == "revise" and "5 changes" in appr["question"]
    assert asklib.answer_ask(orch, "approve", ["revise"])["then"] == "revise"
    assert "Plan v2" in asklib.finish(orch, {"then": "revise"})
    assert asklib.answer_ask(orch, "approve", ["approve"]) == {"reply": "Approved: building has started.", "then": "run"}
    assert orch.project.meta()["plan_approved"] and ids(orch) == []


def test_wrong_or_stale_answers_are_refused(tmp_path):
    orch = planned(tmp_path)
    with pytest.raises(HarnessError, match="Pick an answer"):
        asklib.answer_ask(orch, "choose:C1", [])
    with pytest.raises(HarnessError, match="isn't one of"):
        asklib.answer_ask(orch, "choose:C1", ["z"])
    with pytest.raises(HarnessError, match="Pick one"):
        asklib.answer_ask(orch, "choose:C1", ["a", "b"])
    with pytest.raises(HarnessError, match="changed since"):
        asklib.answer_ask(orch, "choose:C1", ["a"], stamp="0000000000")
    asklib.answer_ask(orch, "choose:C1", "a")  # a comma list works too (the hub sends text)
    assert "choose:C1" not in ids(orch)
    [c1] = [a for a in asklib.open_asks(orch, answered=True) if a["id"] == "choose:C1"]
    assert c1["answer"] == {"chosen": ["a"], "other": ""}
    asklib.answer_ask(orch, "choose:C1", ["b"])  # changed before approving: fine
    assert orch.project.plan_doc()["decisions"][0]["chosen"] == "b"
    orch.revise_plan()
    orch.approve()
    with pytest.raises(HarnessError, match="answered already"):  # building: the plan's cards are settled
        asklib.answer_ask(orch, "choose:C1", ["a"])


def test_other_alone_and_skipping(tmp_path):
    orch = planned(tmp_path)
    asklib.answer_ask(orch, "choose:C1", [], other="hand-drawn, please")
    doc = orch.project.plan_doc()
    assert doc["decisions"][0]["chosen"] is None and "hand-drawn, please" in doc["pending"][-1]["text"]
    r = asklib.answer_ask(orch, "idea:I1", [], other="only on the home page")  # "Yes, but…"
    assert r["reply"] == "Idea added." and orch.project.plan_doc()["ideas"][0]["state"] == "accepted"
    asklib.answer_ask(orch, "answer:Q1", skip=True)
    assert "answer:Q1" not in ids(orch)
    r = asklib.answer_ask(orch, "approve", [], other="no map page")
    assert r["then"] == "revise" and "no map page" in orch.project.plan_doc()["pending"][-1]["text"]
    add_looks(orch)
    assert asklib.answer_ask(orch, "look", [], other="like a night bus") == {
        "reply": "Making three new looks from your note…", "then": "looks", "text": "like a night bus"}


def test_old_plans_without_ready_answers_still_work(tmp_path):
    old = [{"id": "Q1", "text": "What is the bakery called?", "why": "for the logo"}, "Who is it for?"]
    orch = planned(tmp_path, brain=CardBrain(questions=old))
    doc = orch.project.plan_doc()
    assert [q["options"] for q in doc["questions"]] == [[], []] and doc["questions"][1]["id"] == "Q2"
    q = asklib.open_asks(orch)[1]
    assert q["id"] == "answer:Q1" and q["options"] == [] and q["other_hint"] == "Type your answer"
    asklib.answer_ask(orch, "answer:Q1", other="Crumbs & Co")
    assert orch.project.plan_doc()["questions"][0]["answer"] == "Crumbs & Co"
    # a plan saved before questions had options at all
    doc = orch.project.plan_doc()
    for q in doc["questions"]:
        for k in ("options", "recommended", "multi", "header", "chosen"):
            q.pop(k, None)
    orch.project.save_plan_doc(doc)
    assert "answer:Q2" in ids(orch)
    assert plandoc.render_markdown(doc)  # still renders


def test_a_failed_task_card(tmp_path):
    raw = with_profiles()
    raw["roles"]["coder"]["fallback"] = []
    orch, *_ = make(tmp_path, raw=raw, brain=RejectBrain(plan=[DOC_TASK]))
    orch.start("bakery site")
    assert orch.run() == "blocked"
    [a] = asklib.open_asks(orch)
    assert a["id"] == "task:T1" and a["header"] == "Task failed" and "greeting is missing" in a["detail"]
    assert [o["id"] for o in a["options"]] == ["retry", "stronger", "accept", "skip"]
    assert "b/coder2" in a["options"][1]["description"] and a["options"][1]["confirm"]
    with pytest.raises(HarnessError, match="Are you sure"):
        asklib.answer_ask(orch, "task:T1", ["stronger"])
    r = asklib.answer_ask(orch, "task:T1", ["stronger"], other="print hi", confirmed=True)
    assert r["then"] == "run" and orch.project.tasks()[0].stronger
    assert orch.project.meta()["guidance"][-1]["text"] == "About task T1: print hi"  # typed: steer
    orch.cfg.limits.max_attempts_per_task = 1
    orch.run()
    assert orch.project.tasks()[0].attempts[-1]["model"] == "b/coder2"  # the Quality setting's model
    asklib.answer_ask(orch, "task:T1", ["accept"], other="good enough")
    t = orch.project.tasks()[0]
    assert t.status == "done" and "good enough" in t.summary


DOC_TASK = {"id": "T1", "title": "hello module", "role": "coder", "description": "create hello.py",
            "acceptance": "hello.py prints hi", "depends_on": []}


def test_a_money_pause_card(tmp_path):
    raw = with_profiles()
    raw["limits"]["max_cost_usd"] = 0.0001
    orch, *_ = make(tmp_path, raw=raw, brain=Brain(plan=[DOC_TASK]))
    orch.start("bakery site")
    assert orch.run() == "paused_budget"
    [a] = asklib.open_asks(orch)
    assert a["id"] == "money" and a["header"] == "Money"
    assert [o["id"] for o in a["options"]] == ["more", "stop", "budget"]
    assert a["options"][0]["label"].startswith("Carry on with $") and a["options"][0]["confirm"]
    with pytest.raises(HarnessError, match="Are you sure"):
        asklib.answer_ask(orch, "money", ["more"])
    assert asklib.answer_ask(orch, "money", ["stop"])["then"] is None
    assert ids(orch) == []  # stopped: not asked again until it pauses again
    meta = orch.project.meta()
    meta["asks_dismissed"] = {}
    orch.project.save_meta(meta)
    r = asklib.answer_ask(orch, "money", ["more"], confirmed=True)
    assert r["then"] == "run" and orch.project.meta()["budget_extra_usd"] >= 1
    assert Orchestrator(orch.base_cfg, orch.project.root).budget.limit_usd > 1
    assert asklib.finish(orch, r) == "The run ended as: done."


def test_wizard_cards_and_project(tmp_path):
    orch, *_ = make(tmp_path, raw=with_profiles())
    asks = asklib.wizard_asks(orch.base_cfg)
    assert [a["id"] for a in asks] == ["kind", "idea", "like", "profile", "look"]
    assert asks[0]["options"][0]["label"] == "Web app" and asks[1]["required"] and asks[1]["options"] == []
    assert asks[3]["options"][0]["id"] == "balanced" and asks[4]["options"][0]["label"] == "Yes, show me three looks"
    (tmp_path / "projects" / "bakery-site-opening-hours").mkdir(parents=True)
    w = asklib.wizard_project({"kind": {"chosen": ["game"]}, "idea": {"other": "A bakery site with opening hours"},
                               "like": {"other": "https://made-up.example\n\nsomething cosy"},
                               "profile": {"chosen": ["quality"]}, "look": {"chosen": ["no"]}}, tmp_path / "projects")
    assert w["dir"].name == "bakery-site-opening-hours-2" and w["goal"] == "Game: A bakery site with opening hours"
    assert w["references"] == ["https://made-up.example", "something cosy"]
    assert w["profile"] == "quality" and w["look"] is False
    with pytest.raises(HarnessError, match="idea"):
        asklib.wizard_project({"kind": {"chosen": ["web"]}}, tmp_path)


# -- through the app's server, the hub and the table --------------------------------------------------
@pytest.fixture
def ui(tmp_path):
    from roundtable.ui.server import UIApp

    orch, *_ = make(tmp_path, raw=with_profiles(), brain=CardBrain())
    cfg = orch.base_cfg
    cfg.lab_dir = tmp_path / "lab"
    app = UIApp(hub_config=str(tmp_path / "none.yaml"), harness_config=str(tmp_path / "missing.yaml"),
                projects_dir=str(tmp_path / "projects"))
    app.cfg = lambda: cfg
    return app


def test_server_asks_and_wizard(ui, tmp_path):
    from roundtable.ui.server import ApiError

    from .test_ui import call, wait_job

    r = call(ui, "GET", "/api/asks", wizard="1")
    assert r["asks"][0]["id"] == "kind"
    r = call(ui, "POST", "/api/asks", {"wizard": {"kind": {"chosen": ["web"]}, "idea": {"other": "Bakery site"},
                                                  "like": {"other": "https://made-up.example"},
                                                  "profile": {"chosen": ["budget"]}, "look": {"chosen": ["no"]}}})
    assert r["path"].endswith("bakery-site")
    assert wait_job(ui, r["job"]["id"])["result"]["status"] == "awaiting_approval"
    path = r["path"]
    meta = json.loads((tmp_path / "projects/bakery-site/.harness/project.json").read_text(encoding="utf-8"))
    assert meta["profile"] == "budget" and meta["look_step"] is False and meta["goals"] == ["Web app: Bakery site"]
    assert meta["references"][0]["input"] == "https://made-up.example"
    all_asks = call(ui, "GET", "/api/asks")["asks"]
    assert all_asks[0]["id"] == "choose:C1" and all_asks[0]["project"] == "bakery-site"
    assert "profile" not in [a["id"] for a in all_asks]  # chosen in the wizard
    one = call(ui, "GET", "/api/asks", path=path)["asks"]
    assert [a["id"] for a in one] == [a["id"] for a in all_asks]
    r = call(ui, "POST", "/api/asks", {"path": path, "id": "choose:C1", "chosen": ["b"], "stamp": one[0]["stamp"]})
    assert "Watercolour" in r["reply"] and "job" not in r
    with pytest.raises(ApiError, match="isn't one of"):
        call(ui, "POST", "/api/asks", {"path": path, "id": "choose:C1", "chosen": ["zz"]})
    done = {a["id"]: a for a in call(ui, "GET", "/api/asks", path=path, answered="1")["asks"]}
    assert done["choose:C1"]["answer"] == {"chosen": ["b"], "other": ""}
    assert done["kind"]["answer"] == {"chosen": ["web-app"], "other": ""}  # the wizard's "Web app", confirmed
    r = call(ui, "POST", "/api/asks", {"path": path, "id": "approve", "chosen": ["revise"]})
    assert wait_job(ui, r["job"]["id"])["status"] == "done"
    r = call(ui, "POST", "/api/asks", {"path": path, "id": "approve", "chosen": ["approve"]})
    assert r["job"]["kind"] == "run" and wait_job(ui, r["job"]["id"])["result"]["reply"] == "The run ended as: done."

    # the table's Needs you shows the next card of each waiting project
    from roundtable.ui.roundtable import build

    r = call(ui, "POST", "/api/asks", {"wizard": {"idea": {"other": "Second shop"}}})
    wait_job(ui, r["job"]["id"])
    needs = build(ui)["needs_you"]
    [n] = [n for n in needs if n["project"] == "second-shop"]
    assert n["ask"]["id"] == "choose:C1" and n["asks"] >= 3


def test_phone_may_use_the_cards():
    from roundtable.phone import phone_allowed

    assert phone_allowed("GET", "/api/asks") and phone_allowed("POST", "/api/asks")


def test_remote_answer_action(tmp_path):
    from roundtable import remote

    orch = planned(tmp_path)
    text = remote.execute(orch.cfg, orch.project.root, {"action": "answer", "id": "choose:C1", "chosen": ["b"]})
    assert text.startswith("Noted: Watercolour")
    text = remote.execute(orch.cfg, orch.project.root, {"action": "answer", "id": "answer:Q2", "chosen": "a,b"})
    assert orch.project.plan_doc()["questions"][1]["chosen"] == ["a", "b"] and "Answer saved" in text
    with pytest.raises(HarnessError):
        remote.execute(orch.cfg, orch.project.root, {"action": "answer", "id": "nope", "chosen": ["a"]})
    text = remote.execute(orch.cfg, orch.project.root, {"action": "answer", "id": "approve", "chosen": ["revise"]})
    assert "Updating the plan" in text and "Plan v2" in text
    text = remote.execute(orch.cfg, orch.project.root, {"action": "answer", "id": "approve", "chosen": ["approve"]})
    assert text == "Approved: building has started. The run ended as: done."
    assert "answer" in remote.LONG


def test_remote_answer_by_question(tmp_path):
    """The phone's cards built from the plan answer a question with {question, text}, not a card id."""
    from roundtable import remote

    orch = planned(tmp_path)
    text = remote.execute(orch.cfg, orch.project.root, {"action": "answer", "question": "Q1", "text": "Crumbs & Co"})
    assert orch.project.plan_doc()["questions"][0]["answer"] == "Crumbs & Co"
    assert text.startswith("Answer saved.") and "Update plan" in text and "revise" not in text


def test_the_hub_gets_the_cards_next_to_the_plan(tmp_path):
    import yaml

    from .test_hub import RAW as HUB_RAW

    hub_raw = json.loads(json.dumps(HUB_RAW))
    hub_raw["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
    (tmp_path / "hub.yaml").write_text(yaml.safe_dump(hub_raw), encoding="utf-8")
    raw = with_profiles()
    raw["hub"] = {"config": str(tmp_path / "hub.yaml"), "agent": "backend"}
    orch = planned(tmp_path, raw=raw)
    data = json.loads((tmp_path / "hubdata/plans/backend--proj.asks.json").read_text(encoding="utf-8"))
    assert data["project"] == "proj" and data["asks"][0]["id"] == "choose:C1"


def test_approve_can_wait_for_the_cheaper_hours(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from roundtable import asks as asks_mod
    from roundtable.harness import orchestrator as orch_mod

    orch, *_ = make(tmp_path, brain=Brain(plan=PLAN[:1]))
    orch.start("goal", require_approval=True)
    orch.plan()
    later = datetime(2030, 1, 1, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(orch_mod.Orchestrator, "cheap_start_at", lambda self: later)
    card = next(a for a in asks_mod.open_asks(orch) if a["kind"] == "approve")
    assert any(o["id"] == "approve_cheap" and "10:00" in o["label"] for o in card["options"])
    r = asks_mod.answer_ask(orch, card["id"], ["approve_cheap"], "")
    assert "10:00 UTC" in r["reply"] and orch.project.meta()["status"] == "waiting_cheap"
    assert orch.run() == "waiting_cheap"  # not before its time


def test_the_kind_card_comes_first_and_changing_it_updates_the_plan(tmp_path):
    orch = planned(tmp_path, confirm_kind=False)
    asks = asklib.open_asks(orch)
    kind = asks[0]
    assert kind["id"] == "kind" and kind["recommended"] == "website" and kind["question"].startswith("This looks like a Website")
    assert kind["options"][-1]["id"] == "other"
    r = asklib.answer_ask(orch, "kind", ["website"])
    assert r == {"reply": "Kept as a Website.", "then": None} and "kind" not in ids(orch)
    shown = {a["id"]: a for a in asklib.open_asks(orch, answered=True)}
    assert shown["kind"]["answer"] == {"chosen": ["website"], "other": ""}
    r = asklib.answer_ask(orch, "kind", [], other="a game to play in the browser")  # in the owner's words
    assert r["then"] == "revise" and "Browser game" in orch.project.plan_doc()["pending"][-1]["text"]
    assert orch.project.meta()["kind"]["id"] == "browser-game"


def test_no_kind_card_for_a_guess_of_something_else(tmp_path):
    orch, *_ = make(tmp_path, raw=with_profiles(), brain=CardBrain())
    orch.start("renames my photos", require_approval=True)
    assert orch.run() == "awaiting_approval"
    assert orch.project.meta()["kind"]["id"] == "other" and "kind" not in ids(orch)


def test_the_wizard_offers_the_kinds_and_greys_the_coming_ones(tmp_path):
    orch, *_ = make(tmp_path, raw=with_profiles())
    make_ = asklib.wizard_asks(orch.base_cfg)[0]
    by = {o["id"]: o for o in make_["options"]}
    assert make_["recommended"] == "web-app" and by["java-mod"]["disabled"] and by["java-mod"]["tip"]
    assert by["other"]["label"] == "Something else"
    w = asklib.wizard_project({"kind": {"chosen": ["web-app"]}, "idea": {"other": "a timer"}, "extras": ["apk", "nope"]},
                              tmp_path / "projects")
    assert (w["kind"], w["extras"], w["kind_by"]) == ("web-app", ["apk"], "owner") and w["goal"] == "Web app: a timer"
