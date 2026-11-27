"""The done list and the done stage (wave 5, d2-done): what "finished" means, written from the idea, and a run
that can't be called done while an item on that list fails.

Every project here is made up, in tmp_path; the models are scripted. Until the coordinator hooks the stage
up, it is tested as ``class O(DoneStage, Orchestrator)``.
"""

import json

import pytest

from roundtable import asks
from roundtable.harness import donelist, donestage, plandoc
from roundtable.harness.donestage import DoneStage
from roundtable.harness.orchestrator import Orchestrator
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider

from .test_harness import RAW, Brain
from .test_parallel import ParallelBrain, raw as parallel_raw

ONE = [{"id": "T1", "title": "one", "role": "coder", "description": "write one.txt", "acceptance": "exists",
        "depends_on": []}]
TWO = ONE + [dict(ONE[0], id="T2", title="two", description="write two.txt")]
ITEMS = [
    {"text": "You can start a game, lose and start again", "how": "journey", "serves": ["T1"],
     "steps": [{"open": "/"}, {"click": "Start"}, {"expect_text": "Game over"}, {"click": "Play again"}]},
    {"text": "It opens with no errors", "how": "page_opens"},
    {"text": "The high score is kept", "how": "journey", "steps": [{"teleport": "moon"}]},  # can't be run: look
    {"text": "It feels fun", "how": "play", "must": False},
]


# before the hook-up the stage is laid over a bare Orchestrator; after it, Orchestrator has it already
BASES = (Orchestrator,) if issubclass(Orchestrator, DoneStage) else (DoneStage, Orchestrator)


class O(*BASES):
    """The done stage over a bare Orchestrator; ``_finish`` adds the report note as the hook-up line will."""

    def _kind_proof(self):
        return []  # the kind guessed for a made-up project would add its checks; a test asks for them itself

    def _finish(self, tasks):
        super()._finish(tasks)
        p = self.project.dir / "summary.md"
        p.write_text(p.read_text(encoding="utf-8") + self._hook("_done_report_note", default=""), encoding="utf-8")


def with_done(brain, items):
    """The scripted planner also gives a done list (``items`` may be a function: a new list each plan)."""

    def call(model, system, messages, tools):
        r = brain(model, system, messages, tools)
        for c in r.tool_calls:
            if c.name == "submit_plan":
                c.arguments = {**c.arguments, "done_list": items() if callable(items) else items}
        return r

    return call


def build(tmp_path, cls=O, raw=RAW, brain=None):
    cfg = parse(raw)
    brain = brain or with_done(Brain(plan=ONE), ITEMS)
    for name in ("a", "b"):
        cfg.register(name, ScriptedProvider(name, brain))
    cfg.register("img", ScriptedImages())
    events = []
    orch = cls(cfg, tmp_path / "proj", on_event=lambda k, d: events.append((k, d)))
    return orch, events


def parse(raw):
    from roundtable.harness.config import parse_config

    return parse_config(json.loads(json.dumps(raw)))


# -- the module -----------------------------------------------------------------------------------------------------
def test_journey_steps_use_the_fixed_words_only():
    assert donelist.clean_steps([{"open": "/"}, {"do": "click", "what": "Start"}, {"type": "Ada", "into": "Name"},
                                 {"wait": "5"}, {"wait": "Ready"}, {"expect_no_errors": "yes"}]) == [
        {"open": "/"}, {"click": "Start"}, {"type": "Ada", "into": "Name"}, {"wait": 5.0}, {"wait": "Ready"},
        {"expect_no_errors": True}]
    for bad in ([{"teleport": "x"}], [{"click": ""}], [{"click": "a", "press": "b"}], [{"click": "a", "x": 1}], [], "x"):
        assert donelist.clean_steps(bad) is None
    assert donelist.clean_item({"text": "x", "how": "journey", "steps": [{"fly": 1}]})["how"] == "look"
    assert donelist.clean_item({"text": "x", "how": "file_exists"})["how"] == "look"  # no path: a person looks
    assert donelist.clean_item({"text": "  "}) is None and donelist.clean_item(7) is None


def test_kind_items_merge_without_duplicates():
    kind = donelist.from_kind([
        {"id": "opens", "how": "page_opens", "words": "The page opens without errors", "status": "trial"},
        {"id": "pic", "how": "picture", "words": "There is a picture of it", "optional": True},
        {"id": "zip", "how": "file_exists", "words": "There is a zip", "path": "dist/*.zip"},
        {"id": "later", "how": "play", "words": "Someone plays it", "status": "not_yet"},
    ])
    assert [(k["how"], k["must"], k["by"]) for k in kind] == [("page_opens", True, "kind"), ("look", False, "kind"),
                                                             ("file_exists", True, "kind"), ("play", False, "kind")]
    planner = [donelist.clean_item(i) for i in ITEMS]
    first = donelist.merge(planner, kind, [])
    texts = [i["text"] for i in first]
    assert "The page opens without errors" not in texts  # the planner's page_opens item covers it
    assert next(i for i in first if i["how"] == "page_opens")["kind_id"] == "opens"
    assert texts.count("There is a zip") == 1
    assert [i["id"] for i in first] == [f"D{n}" for n in range(1, len(first) + 1)]
    again = donelist.merge(planner, kind, first)  # merging twice adds nothing
    assert [(i["id"], i["text"]) for i in again] == [(i["id"], i["text"]) for i in first]


def test_unchecked_items_never_read_as_passed(tmp_path):
    root = tmp_path / "p"
    donelist.write_list(root, 0, donelist.merge([donelist.clean_item(i) for i in ITEMS], [], []))
    s = donelist.summary(root)
    assert (s["passed"], s["unchecked"]) == (0, 4) and "✓" not in s["words"] and "none checked" in s["words"]
    donelist.record(root, "D1", True, "it worked")
    donelist.record(root, "D2", None, "no browser here")
    s = donelist.summary(root, finished=True)
    assert (s["passed"], s["unchecked"], s["checked"]) == (1, 3, 1)
    assert s["words"] == "Finished: 1 of 4 checked, 3 couldn’t be checked here"
    assert donelist.MARK["unchecked"] != donelist.MARK["passed"] and donelist.MARK["open"] != donelist.MARK["passed"]
    assert donelist.verdict(root)["done"] is False  # unchecked is never "done"…
    assert donelist.verdict(root)["failed"] == []  # …but never a failure either
    donelist.record(root, "D2", False, "a red error")
    assert donelist.summary(root)["words"] == "Done when: 1 of 4 ✓ · 1 doesn’t work yet"


def test_markdown_context_and_proof_lines(tmp_path):
    root = tmp_path / "p"
    items = donelist.merge([donelist.clean_item(i) for i in ITEMS],
                           donelist.from_kind([{"id": "opens", "how": "page_opens", "words": "Opens"}]), [])
    donelist.write_list(root, 0, items)
    doc = {"done_list": [donelist.public(i) for i in items]}
    md = "\n".join(donelist.markdown(doc))
    assert md.startswith("## Done when") and "{D1}" in md and "(nice to have)" in md
    assert "state" not in doc["done_list"][0]
    assert "[D1] You can start a game" in donelist.context(doc)
    assert donelist.markdown({}) == [] and donelist.context(None) == ""
    assert donelist.proof_lines(root) is None  # nothing checked yet: the kind stage's own look still counts
    donelist.record(root, "D2", True, "opened")
    assert donelist.proof_lines(root) == [{"id": "opens", "words": "It opens with no errors", "optional": False,
                                           "status": "trial", "passed": True}]


def test_evidence_pictures_stay_inside_the_project(tmp_path):
    root = tmp_path / "p"
    (root / ".harness" / "shots").mkdir(parents=True)
    png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000")
    (root / ".harness" / "shots" / "a.png").write_bytes(png)
    (tmp_path / "secret.png").write_bytes(png)
    donelist.add_item(root, {"text": "It opens", "how": "page_opens"})
    donelist.record(root, "D1", True, "opened", {"pictures": [".harness/shots/a.png", "../secret.png",
                                                              str(tmp_path / "secret.png")], "log": "ok"})
    ev = donelist.evidence(root, "D1")
    assert [p["name"] for p in ev["pictures"]] == ["a.png"] and ev["pictures"][0]["data"].startswith("data:image/png")
    assert ev["texts"] == {"log": "ok"} and donelist.evidence(root, "D9") is None


# -- the stage: planning ------------------------------------------------------------------------------------------------
def test_a_bare_project_with_no_done_list_runs_as_before(tmp_path, monkeypatch):
    # with a kind guessed, only its checks are listed; nobody checks them here, so nothing stops
    class WithKind(O):
        _kind_proof = Orchestrator._kind_proof

    orch, events = build(tmp_path, cls=WithKind, brain=Brain(plan=ONE))
    orch.start("a made-up tool")
    assert orch.run() == "done"
    assert {i["by"] for i in donelist.read(orch.project.root)["items"]} <= {"kind"}
    assert not {"not_finished", "stage_error"} & {k for k, _ in events}
    # no kind and no list from the planner: nothing is written at all
    orch, events = build(tmp_path / "b", brain=Brain(plan=ONE))
    orch.start("a made-up tool")
    assert orch.run() == "done"
    assert not donelist.path(orch.project.root).exists() and "done_list" not in orch.project.plan_doc()


def test_the_plan_gets_a_done_list_and_tasks_hear_about_it(tmp_path):
    seen = []
    inner = with_done(Brain(plan=ONE), ITEMS)

    def spy(model, system, messages, tools):
        seen.append(([t.name for t in tools], messages[0]["content"], tools))
        return inner(model, system, messages, tools)

    orch, _ = build(tmp_path, brain=spy)
    orch.start("a made-up game")
    orch.run()
    doc = orch.project.plan_doc()
    assert [i["id"] for i in doc["done_list"]] == ["D1", "D2", "D3", "D4"]
    assert doc["done_list"][2]["how"] == "look" and doc["done_list"][3]["must"] is False
    data = donelist.read(orch.project.root)
    assert [i["state"] for i in data["items"]] == ["open"] * 4
    plan_prompt = next(p for names, p, _ in seen if "submit_plan" in names)
    assert "# Done when" in plan_prompt and "expect_text" in plan_prompt
    tool = next(t for names, _, tools in seen if "submit_plan" in names for t in tools if t.name == "submit_plan")
    assert "done_list" in tool.parameters["properties"]
    worker = next(p for names, p, _ in seen if "finish_task" in names and "# Your task [T1]" in p)
    assert "# What finished means" in worker and "[D1] You can start a game" in worker


def test_the_done_list_survives_a_revision_with_the_owners_items_kept(tmp_path):
    lists = iter([ITEMS, [{"text": "You can pause the game", "how": "journey",
                           "steps": [{"open": "/"}, {"press": "Escape"}, {"expect_text": "Paused"}]}]])
    orch, _ = build(tmp_path, brain=with_done(Brain(plan=ONE), lambda: next(lists)))
    orch.start("a made-up game", require_approval=True)
    orch.plan()
    doc = orch.project.plan_doc()
    notes = []
    mine = donelist.owner_add(orch.project.root, doc, {"text": "My little brother can win  once"},
                              lambda text, key: notes.append((key, text)))
    gone = donelist.owner_remove(orch.project.root, doc, {"id": "D2"}, lambda text, key: notes.append((key, text)))
    orch.project.save_plan_doc(doc)
    assert mine["by"] == "owner" and mine["how"] == "owner" and mine["text"] == "My little brother can win once"
    assert gone["text"] == "It opens with no errors" and len(notes) == 2
    orch.revise_plan("add a pause")
    doc = orch.project.plan_doc()
    texts = [i["text"] for i in doc["done_list"]]
    assert texts[0] == "My little brother can win once"  # the owner's own, word for word, on top
    assert "You can pause the game" in texts and "It opens with no errors" not in texts
    assert doc["done_removed"][0]["id"] == "D2"
    assert {i["id"] for i in doc["done_list"]} == {i["id"] for i in donelist.read(orch.project.root)["items"]}
    # a revision where the planner gives no list keeps the one there
    orch2, _ = build(tmp_path / "b", brain=with_done(Brain(plan=ONE), lambda: []))
    orch2.start("a made-up game", require_approval=True)
    orch2.project.save_plan_doc({**plandoc.doc_from_submission({}, "a made-up game", 0),
                                 "done_list": [donelist.public(i) for i in donelist.merge(
                                     [donelist.clean_item(x) for x in ITEMS], [], [])]})
    orch2.revise_plan("smaller")
    assert len(orch2.project.plan_doc()["done_list"]) == 4


def test_the_kinds_checks_join_the_list(tmp_path, monkeypatch):
    monkeypatch.setattr(O, "_kind_proof", lambda self: [
        {"id": "opens", "how": "page_opens", "words": "The page opens", "status": "trial"},
        {"id": "zip", "how": "file_exists", "words": "There is a download", "path": "dist/game.zip"}])
    orch, _ = build(tmp_path)
    orch.start("a made-up game", require_approval=True)
    orch.plan()
    items = orch.project.plan_doc()["done_list"]
    assert [i["by"] for i in items].count("kind") == 1  # "The page opens" is the planner's page_opens item
    assert next(i for i in items if i["by"] == "kind")["text"] == "There is a download"
    orch.revise_plan("again")
    assert len(orch.project.plan_doc()["done_list"]) == len(items)


# -- the stage: the gate ------------------------------------------------------------------------------------------------
class Checks(O):
    """A made-up finish stage: D1 fails until a fix task ran, everything else couldn't be checked here."""

    def _attention(self, key, text, details=""):
        self.cards = getattr(self, "cards", []) + [key]
        super()._attention(key, text, details)

    def _finish_step(self, tasks):
        root = self.project.root
        fixed = any(t.fix_of == "D1" and t.status == "done" for t in tasks)
        for i in donelist.read(root)["items"]:
            if i["id"] == "D1":
                donelist.record(root, "D1", fixed, "it works now" if fixed else "Play again does nothing", by="finish")
            elif i["state"] == "open":
                donelist.record(root, i["id"], None, "no browser here", by="finish")


def test_a_failed_must_item_stops_the_run_with_one_card(tmp_path):
    orch, events = build(tmp_path, cls=Checks, raw=dict(RAW, limits={"max_cost_usd": 5, "max_attempts_per_task": 1}))
    orch.start("a made-up game")
    assert orch.run() == "blocked"
    meta = orch.project.meta()
    assert (meta["status"], meta["pause"]) == ("blocked", "not_finished")
    assert set(meta.get("journal_todos") or {}) <= {"not_finished"}
    assert orch.cards == ["not_finished"]  # one card, not one a task or an item
    assert not (orch.project.dir / "summary.md").exists()
    assert ("not_finished", {"failed": ["D1"]}) in events
    card = donestage.not_finished_ask(orch)
    assert card["kind"] == "not_finished" and [o["id"] for o in card["options"]] == ["fix", "accept", "stop"]
    assert card["options"][0]["label"].startswith("Try fixing again (about $")
    assert card["options"][1]["confirm"] and "fix" == card["recommended"]
    assert asks._failed_asks(orch, meta, orch.project.tasks()) == []  # no per-task cards: every task is done


def test_try_fixing_again_adds_fixes_and_finishes_once_they_work(tmp_path):
    orch, events = build(tmp_path, cls=Checks)
    orch.start("a made-up game")
    assert orch.run() == "blocked"
    card = donestage.not_finished_ask(orch)
    assert donestage.decide_not_finished(orch, card, {"spend_cap_usd": 5, "spent_usd": 0})[0] == ["fix"]
    r = donestage.apply_not_finished(orch, card, ["fix"], "the button is hidden")
    assert r["then"] == "run"
    fix = next(t for t in orch.project.tasks() if t.added_by == "done")
    assert (fix.id, fix.fix_of) == ("X1", "D1") and "the button is hidden" in fix.description
    assert donelist.read(orch.project.root)["items"][0]["state"] == "open"
    assert orch.project.meta()["done_fix_rounds"] == 1
    assert orch.run() == "done"
    assert "not_finished" not in orch.project.meta().get("journal_todos", {})
    assert "done_fix_rounds" not in orch.project.meta()
    s = donelist.summary(orch.project.root, finished=True)
    assert s["words"] == "Finished: 1 of 4 checked, 3 couldn’t be checked here"


def test_accept_lets_it_finish_once_and_the_report_says_so(tmp_path):
    orch, events = build(tmp_path, cls=Checks)
    orch.start("a made-up game")
    assert orch.run() == "blocked"
    card = donestage.not_finished_ask(orch)
    assert donestage.decide_not_finished(orch, card, {"spend_cap_usd": 5})[0] == ["fix"]  # autopilot never accepts
    r = donestage.apply_not_finished(orch, card, ["accept"], "")
    assert r["then"] == "run"
    assert orch.run() == "done"
    summary = (orch.project.dir / "summary.md").read_text(encoding="utf-8")
    assert "## Accepted as it is" in summary and "You can start a game, lose and start again" in summary
    meta = orch.project.meta()
    assert "accepted_unfinished" not in meta and ("done_accepted", {"failed": ["D1"]}) in events
    assert "accepted it as it is" in donelist.context(orch.project.plan_doc())
    # once: the next time it fails it stops again
    assert orch._done_gate(orch.project.tasks()) == "blocked"


def test_autopilot_tries_fixing_at_most_once_and_within_its_money(tmp_path):
    orch, _ = build(tmp_path, cls=Checks)
    orch.start("a made-up game")
    orch.run()
    card = donestage.not_finished_ask(orch)
    assert donestage.decide_not_finished(orch, card, {"spend_cap_usd": 0.0000001})[0] is None
    assert donestage.decide_not_finished(orch, {**card, "source": {**card["source"], "fixes": 1}},
                                         {"spend_cap_usd": 5})[0] is None
    assert donestage.decide_not_finished(orch, {**card, "source": {**card["source"], "cost": None}},
                                         {"spend_cap_usd": 5})[0] is None
    stop = donestage.apply_not_finished(orch, card, ["stop"], "")
    assert stop["then"] is None and orch.project.meta()["asks_dismissed"]["not_finished"] == card["stamp"]


class ParallelChecks(Checks):
    pass


def test_the_parallel_path_stops_at_the_done_gate_too(tmp_path):
    orch, events = build(tmp_path, cls=ParallelChecks, raw=parallel_raw(2),
                         brain=with_done(ParallelBrain(TWO), ITEMS))
    orch.start("a made-up game")
    assert orch.run() == "blocked"
    assert "parallel" in {k for k, _ in events}
    assert orch.project.meta()["pause"] == "not_finished"
    assert set(orch.project.meta().get("journal_todos") or {}) <= {"not_finished"}


def test_a_gate_error_never_crashes_a_run(tmp_path, monkeypatch):
    def broken(root):
        raise OSError("disk went away")

    orch, events = build(tmp_path)
    orch.start("a made-up game")
    monkeypatch.setattr(donelist, "verdict", broken)
    assert orch.run() == "done"
    assert any(k == "stage_error" and d["stage"] == "_done_gate" for k, d in events)


# -- the API ------------------------------------------------------------------------------------------------------------
def test_the_api_gives_the_list_and_one_items_evidence(tmp_path, monkeypatch):
    import yaml

    from roundtable.ui import server
    from roundtable.ui.server import ApiError, UIApp

    from .test_hub import RAW as HUB_RAW

    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "doneapi"))
    h = json.loads(json.dumps(HUB_RAW))
    h["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
    (tmp_path / "hub.yaml").write_text(yaml.safe_dump(h), encoding="utf-8")
    orch, _ = build(tmp_path, cls=Checks)
    cfg = orch.cfg
    cfg.lab_dir = tmp_path / "lab"
    orch.start("a made-up game")
    orch._register_with_lab()
    orch.run()
    app = UIApp(str(tmp_path / "hub.yaml"), "missing.yaml", agent="backend")
    app.cfg = lambda: cfg
    path = str(orch.project.root)
    got = app.dispatch("GET", "/api/done", {"path": [path]}, {})
    assert {"items", "checked", "passed", "failed", "unchecked", "words", "rounds"} <= set(got)
    assert (got["failed"], got["unchecked"], got["finished"]) == (1, 3, False)
    assert got["words"] == "Done when: 0 of 4 ✓ · 1 doesn’t work yet"
    ev = app.dispatch("GET", "/api/done/evidence", {"path": [path], "item": ["D1"]}, {})
    assert ev["found"] and ev["state"] == "failed" and ev["words"] == "Play again does nothing"
    assert app.dispatch("GET", "/api/done/evidence", {"path": [path], "item": ["D9"]}, {})["found"] is False
    with pytest.raises(ApiError):
        app.dispatch("GET", "/api/done/evidence", {"path": [path], "item": ["../x"]}, {})
    with pytest.raises(ApiError):
        app.dispatch("GET", "/api/done", {"path": [str(tmp_path / "elsewhere")]}, {})
    assert "/api/done" in app.dispatch("GET", "/api/features", {}, {})["routes"]
