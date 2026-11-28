import json

import pytest

from roundtable.harness import plandoc
from roundtable.harness.orchestrator import HarnessError
from roundtable.providers.scripted import reply

from .test_harness import PLAN, RAW, Brain, make, tool_names

DOC = {
    "summary": "A small bakery site: a Python greeter, a logo and tests.",
    "in_scope": ["greeting page", "logo"], "out_of_scope": ["online orders"],
    "dont": [{"text": "add a database", "why": "nothing needs storing yet"}],
    "spec": [{"id": "S1", "title": "Stack", "text": "Python 3, no frameworks"},
             {"id": "S2", "title": "Art style", "text": "warm pixel art"}],
    "decisions": [{"id": "C1", "question": "Which logo style?", "options": [
        {"id": "a", "label": "Pixel art", "detail": "matches the site", "cost": "cheap"},
        {"id": "b", "label": "Watercolour", "detail": "softer", "cost": "needs another provider"}],
        "recommended": "a", "why": "the image role is a pixel-art model", "section": "S2"}],
    "questions": [{"id": "Q1", "text": "What is the bakery called?", "why": "for the logo"}],
    "ideas": [{"id": "I1", "text": "an opening-hours widget", "why": "customers ask"}],
}


class PlanBrain(Brain):
    """Planner submits a full plan document; revisions follow the owner's changes; a critic can object."""

    def __init__(self, critic_verdict="good"):
        super().__init__(plan=[dict(t, section="S1" if t["role"] == "coder" else "S2") for t in PLAN])
        self.critic_verdict = critic_verdict
        self.prompts = []

    def __call__(self, model, system, messages, tools):
        names = tool_names(tools)
        last = messages[-1]
        if "submit_plan" in names and last["role"] == "user":
            prompt = messages[0]["content"]
            self.prompts.append(prompt)
            tasks = [dict(t) for t in self.plan]
            doc = json.loads(json.dumps(DOC))
            if "Revise the plan" in prompt:
                done = prompt.split("Already done or in progress, don't repeat (you may depend on them): ", 1)
                done = done[1].split(".", 1)[0].split(", ") if len(done) > 1 else []
                tasks = [t for t in tasks if t["id"] not in done]
                if "Watercolour" in prompt:  # the owner's choice changes only the logo task
                    t2 = next(t for t in tasks if t["id"] == "T2")
                    t2["description"] = "a watercolour bakery logo"
                if "Crumbs" in prompt:
                    doc["questions"] = []  # answered
                if "critiqued" in prompt:
                    tasks.append({"id": "T4", "title": "README", "role": "coder", "description": "how to run",
                                  "acceptance": "README.md exists", "depends_on": [], "section": "S1"})
                    tasks = [t for t in self.plan] + [tasks[-1]]
            return reply(calls=[("submit_plan", {**doc, "tasks": tasks})])
        if "submit_critique" in names:
            if last["role"] == "tool":
                return reply("ok")
            pts = [{"severity": "high", "text": "no README: the owner can't run it", "suggestion": "add one"}] \
                if self.critic_verdict == "revise" else [{"severity": "low", "text": "fine"}]
            return reply(calls=[("submit_critique", {"verdict": self.critic_verdict, "points": pts})])
        return super().__call__(model, system, messages, tools)


def raw_with_critic():
    raw = json.loads(json.dumps(RAW))
    raw["roles"]["critic"] = {"model": "b/critic"}
    return raw


def test_first_plan_is_a_document_with_estimate_and_critique(tmp_path):
    brain = PlanBrain()
    orch, *_ = make(tmp_path, raw=raw_with_critic(), brain=brain)
    orch.start("bakery site", require_approval=True)
    assert orch.run() == "awaiting_approval"
    doc = orch.project.plan_doc()
    assert doc["summary"].startswith("A small bakery") and doc["version"] == 1
    assert doc["decisions"][0]["recommended"] == "a" and doc["decisions"][0]["chosen"] is None
    assert doc["questions"][0]["answer"] == "" and doc["ideas"][0]["state"] == "open"
    assert doc["critique"]["verdict"] == "good" and doc["critique"]["model"] == "b/critic"
    est = doc["estimate"]
    assert est["tasks"] == 3 and est["cost_usd"] > 0 and est["minutes"] > 0
    assert est["unpriced"] == ["img/pic"]  # the image model has no price: shown, not guessed
    assert {t.section for t in orch.project.tasks()} == {"S1", "S2"}
    md = (orch.project.dir / "plan.md").read_text(encoding="utf-8")
    assert "## Decisions" in md and "Pixel art (recommended)" in md and "## Don't" in md
    # the critic isn't a role tasks can be given to
    assert "critic" not in orch._roles_text()
    line = plandoc.summary_line(doc)
    assert line.startswith("plan ready: 1 choice, 1 question (about $")


def test_serious_critique_revises_the_plan_once(tmp_path):
    brain = PlanBrain(critic_verdict="revise")
    orch, *_ = make(tmp_path, raw=raw_with_critic(), brain=brain)
    orch.start("bakery site", require_approval=True)
    orch.run()
    doc = orch.project.plan_doc()
    assert doc["version"] == 2 and doc["history"][-1]["by"] == "critic"
    assert doc["history"][-1]["diff"]["added"] == ["T4"]
    assert "no README" in brain.prompts[-1]
    assert [t.id for t in orch.project.tasks()] == ["T1", "T2", "T3", "T4"]
    assert doc["critique"]["verdict"] == "revise"  # kept for the owner to read


def test_owner_edits_wait_then_revise_changes_only_affected_tasks(tmp_path):
    brain = PlanBrain()
    orch, *_ = make(tmp_path, brain=brain)  # no critic configured: no critique
    orch.start("bakery site", require_approval=True)
    orch.run()
    assert orch.project.plan_doc()["critique"] is None
    orch.plan_update("choose", decision="C1", option="b")
    orch.plan_update("answer", question="Q1", text="Crumbs & Co")
    orch.plan_update("dont_add", text="use any paid fonts")
    orch.plan_update("idea", id="I1", accept=True)
    orch.plan_update("choose", decision="C1", option="b")  # same edit twice: one pending change
    doc = orch.project.plan_doc()
    assert len(doc["pending"]) == 4 and plandoc.open_items(doc)["choices"] == 0
    with pytest.raises(HarnessError):
        orch.approve()  # changes not applied yet
    with pytest.raises(HarnessError):
        orch.plan_update("choose", decision="C9", option="a")

    # pretend T1 already ran: it must survive the revision untouched
    tasks = orch.project.tasks()
    tasks[0].status, tasks[0].summary = "done", "hello.py written"
    orch.project.save_tasks(tasks)
    r = orch.revise_plan()
    prompt = brain.prompts[-1]
    assert "the owner chose: Watercolour" in prompt and "Crumbs & Co" in prompt and "paid fonts" in prompt
    assert "Already done or in progress" in prompt and "T1" in prompt
    assert r["changed"] == ["T2"] and r["added"] == [] and r["removed"] == [] and r["unchanged"] == 1
    doc = orch.project.plan_doc()
    assert doc["version"] == 2 and doc["pending"] == []
    assert doc["decisions"][0]["chosen"] == "b"  # the owner's choice survives the revision
    assert any(d["text"] == "use any paid fonts" and d["by"] == "owner" for d in doc["dont"])
    assert doc["ideas"][0]["state"] == "accepted" and [q["answer"] for q in doc["questions"]] == ["Crumbs & Co"]  # kept as a record
    by_id = {t.id: t for t in orch.project.tasks()}
    assert by_id["T1"].status == "done" and by_id["T2"].description == "a watercolour bakery logo"
    assert doc["estimate"]["tasks"] == 2  # only what's left
    assert "Plan v2: 1 changed (T2)" in orch.chat_history()[-1]["text"]
    with pytest.raises(HarnessError):
        orch.revise_plan()  # nothing to change

    # every later task is told the plan, including the owner's choices and don'ts
    orch.approve()
    assert orch.run() == "done"
    ctx = orch._project_context(orch.project.tasks())
    assert "# The plan" in ctx and "Watercolour (owner's choice)" in ctx and "Don't: add a database; use any paid fonts" in ctx


def test_plan_api_and_needs_you_line(tmp_path):
    from roundtable.ui.server import UIApp

    brain = PlanBrain()
    orch, *_ = make(tmp_path, brain=brain)
    cfg = orch.cfg
    cfg.lab_dir = tmp_path / "lab"
    app = UIApp(None, "missing.yaml")
    app.cfg = lambda: cfg
    orch._register_with_lab()
    orch.start("bakery site", require_approval=True)
    orch.run()
    path = str(orch.project.root)
    got = app.dispatch("GET", "/api/plan", {"path": [path]}, {})
    assert got["doc"]["decisions"][0]["id"] == "C1" and len(got["tasks"]) == 3 and not got["approved"]
    assert got["open"] == {"choices": 1, "questions": 1, "ideas": 1, "pending": 0}
    r = app.dispatch("POST", "/api/plan", {}, {"path": path, "action": "choose", "decision": "C1", "option": "b"})
    assert r["pending"] == 1
    from roundtable.ui.roundtable import build

    seat = next(s for s in build(app)["seats"] if s["id"] == "proj")
    assert seat["detail"].startswith("plan ready: 1 question, 1 change to apply")
    with pytest.raises(Exception):
        app.dispatch("POST", "/api/plan", {}, {"path": path, "action": "approve"})  # pending change
    job = app.dispatch("POST", "/api/plan", {}, {"path": path, "action": "revise", "text": "keep it small"})
    import time

    for _ in range(200):
        j = app.dispatch("GET", f"/api/jobs/{job['id']}", {}, {})
        if j["status"] != "running":
            break
        time.sleep(0.05)
    assert j["status"] == "done", (j.get("error"), j.get("lines"))
    assert j["result"]["version"] == 2
    assert "keep it small" in brain.prompts[-1]


def test_estimate_uses_history_when_there_is_some(tmp_path):
    from roundtable.harness.orchestrator import Task

    orch, *_ = make(tmp_path)
    f = tmp_path / "m.jsonl"
    f.write_text("\n".join(json.dumps({"task": f"T{i}", "role": "coder", "cost_usd": 0.5, "seconds": 120,
                                       "at": "2026-11-20T10:00:00Z"}) for i in range(4)), encoding="utf-8")
    hist = plandoc.history_by_role([f])
    assert hist["coder"]["cost"] == 0.5 and hist["coder"]["minutes"] == 2.0
    est = plandoc.estimate(orch.cfg, [Task("X", "x", "coder", "d")], hist)
    assert est["by_role"]["coder"]["basis"] == "history" and est["cost_usd"] == 0.5


def test_plan_published_to_the_projects_own_hub_page(tmp_path):
    import yaml

    from .test_hub import RAW as HUB_RAW

    raw = json.loads(json.dumps(HUB_RAW))
    raw["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
    raw["agents"]["proj"] = {"description": "the project folder's own hub project"}
    raw["agents"]["harness"] = {"description": "shared"}
    (tmp_path / "hub.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    hraw = json.loads(json.dumps(RAW))
    hraw["hub"] = {"config": str(tmp_path / "hub.yaml"), "agent": "harness"}
    orch, *_ = make(tmp_path, raw=hraw, brain=PlanBrain())
    orch.start("bakery site", require_approval=True)
    orch.run()
    page = (tmp_path / "hubdata" / "plans" / "proj.md").read_text(encoding="utf-8")
    assert page.startswith("_Plan status: waiting for the owner · plan ready: 1 choice, 1 question")
    assert "## Decisions" in page and "[T1]" in page
    hub = orch._hub()
    todo = hub.journal.entries("proj", "proj")
    assert any(e["kind"] == "plan" and e["text"].startswith("goal: bakery site") for e in todo)  # no name prefix
    orch.plan_update("choose", decision="C1", option="b")
    assert "Watercolour (chosen)" in (tmp_path / "hubdata" / "plans" / "proj.md").read_text(encoding="utf-8")


def test_commands_through_the_hub(tmp_path):
    import yaml

    from roundtable.remote import process

    from .test_hub import RAW as HUB_RAW

    raw = json.loads(json.dumps(HUB_RAW))
    raw["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
    raw["agents"].update({"proj": {}, "harness": {}, "me": {}, "stranger": {}})
    raw["rules"].append({"from": "*", "to": "*", "allow": ["message"]})
    (tmp_path / "hub.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    hraw = json.loads(json.dumps(RAW))
    hraw["hub"] = {"config": str(tmp_path / "hub.yaml"), "agent": "harness"}
    brain = PlanBrain()
    orch, *_ = make(tmp_path, raw=hraw, brain=brain)
    orch.cfg.lab_dir = tmp_path / "lab"
    orch.start("bakery site", require_approval=True)
    orch.run()
    hub = orch._hub()
    send = lambda who, body, subject="roundtable: command": hub.send(who, "proj", subject, body, kind="request")  # noqa: E731
    send("me", json.dumps({"action": "choose", "decision": "C1", "option": "b"}))
    send("stranger", json.dumps({"action": "approve"}))  # not the owner: ignored
    send("me", "not json")
    hub.send("me", "proj", "hello", "just a note")  # a plain letter: answered, and on Needs you
    assert process(orch.cfg, hub, log=lambda s: None) == 3
    assert orch.project.plan_doc()["decisions"][0]["chosen"] == "b"
    assert not orch.project.meta()["plan_approved"]
    replies = hub.inbox("me", unread_only=False)
    assert len(replies) == 3 and any("1 change waits for you to press Update plan" in r["body"] for r in replies)
    assert any("isn't valid JSON" in r["body"] for r in replies)
    # the receipt arrives read; the refusal and the answer to the letter wait for the owner
    unread = [r["body"] for r in hub.inbox("me", unread_only=True)]
    assert unread[0] == "Couldn't do that: the command isn't valid JSON." and "Needs you" in unread[1]
    left = {m["subject"] for m in hub.inbox("proj", unread_only=True)}
    assert left == {"roundtable: command"}  # only the stranger's command
    send("me", json.dumps({"action": "revise"}))
    send("me", json.dumps({"action": "approve"}))
    assert process(orch.cfg, hub, log=lambda s: None) == 2
    assert orch.project.meta()["status"] == "done"
    assert any("The run ended as: done" in r["body"] for r in hub.inbox("me", unread_only=False))
    assert process(orch.cfg, hub, log=lambda s: None) == 0  # each command runs once


def test_revisions_carry_answers_by_wording_not_id():
    old = plandoc.doc_from_submission(DOC, "g", 0)
    old["ideas"][0]["state"] = "accepted"
    old["decisions"][0]["chosen"] = "b"
    old["questions"][0]["answer"] = "Crumbs & Co"
    sub = json.loads(json.dumps(DOC))
    sub["ideas"] = [{"id": "I1", "text": "a loyalty card"}]  # same id, different idea
    sub["decisions"][0]["options"] = [{"id": "x", "label": "Watercolour"}, {"id": "y", "label": "Pixel art"}]
    new = plandoc.carry_over(plandoc.doc_from_submission(sub, "g", 0), old)
    assert new["ideas"][0]["state"] == "open"
    assert new["decisions"][0]["chosen"] == "x"  # the owner's Watercolour, under its new id
    assert new["questions"][0]["answer"] == "Crumbs & Co"


def test_settled_items_stay_and_turned_down_ideas_dont_come_back():
    old = plandoc.doc_from_submission(DOC, "g", 0)
    old["ideas"] = [{"id": "I1", "text": "Add a waveform or peak preview in the seek bar.", "state": "rejected"},
                    {"id": "I2", "text": "Add a play queue with history.", "state": "accepted"}]
    old["decisions"][0]["chosen"] = "b"
    old["questions"][0]["answer"] = "Crumbs & Co"
    sub = json.loads(json.dumps(DOC))
    sub["decisions"], sub["questions"] = [], []  # the planner drops what's settled
    sub["ideas"] = [{"id": "I1", "text": "Add a mini peak/waveform preview in the seek bar."},  # reworded
                    {"id": "I2", "text": "Add crossfade between tracks."}]
    new = plandoc.carry_over(plandoc.doc_from_submission(sub, "g", 0), old)
    texts = {i["text"]: i["state"] for i in new["ideas"]}
    assert "Add a mini peak/waveform preview in the seek bar." not in texts
    assert texts["Add crossfade between tracks."] == "open"
    assert texts["Add a waveform or peak preview in the seek bar."] == "rejected"
    assert texts["Add a play queue with history."] == "accepted"
    assert len({i["id"] for i in new["ideas"]}) == len(new["ideas"])
    assert new["decisions"][0]["chosen"] == "b" and new["questions"][0]["answer"] == "Crumbs & Co"
    ctx = plandoc.context_text(new)
    assert "doesn't want: Add a waveform" in ctx and "owner's choice" in ctx


def test_profiles_change_the_models_and_show_each_estimate(tmp_path):
    from roundtable.harness.config import parse_config
    from roundtable.harness.orchestrator import Orchestrator
    from roundtable.providers.scripted import ScriptedProvider

    raw = {
        "providers": {"a": {"type": "scripted"}, "b": {"type": "scripted"}},
        "roles": {"orchestrator": {"model": "a/planner"}, "coder": {"model": "a/cheap"}},
        "pricing": {"a/planner": {"input": 1, "output": 1}, "a/cheap": {"input": 1, "output": 1},
                    "b/strong": {"input": 20, "output": 20}},
        "profiles": {"budget": {"roles": {"coder": {"model": "a/cheap"}}},
                     "quality": {"description": "best", "roles": {"coder": {"model": "b/strong", "fallback": ["a/cheap"]}}}},
        "default_profile": "budget",
    }
    cfg = parse_config(raw)
    brain = Brain(plan=[PLAN[0]])
    cfg.register("a", ScriptedProvider("a", brain))
    cfg.register("b", ScriptedProvider("b", brain))
    orch = Orchestrator(cfg, tmp_path / "p")
    orch.start("goal")
    orch.plan()
    assert orch.profile() == "budget" and str(orch.cfg.roles["coder"].models[0]) == "a/cheap"
    doc = orch.project.plan_doc()
    assert doc["estimates"]["quality"]["cost_usd"] > doc["estimates"]["budget"]["cost_usd"] * 10
    assert "Settings: budget (chosen)" in plandoc.render_markdown(doc)
    orch.set_profile("quality")
    again = Orchestrator(cfg, tmp_path / "p")
    assert again.profile() == "quality" and [str(m) for m in again.cfg.roles["coder"].models] == ["b/strong", "a/cheap"]
    assert str(cfg.roles["coder"].models[0]) == "a/cheap"  # the base config is untouched
    with pytest.raises(HarnessError):
        orch.set_profile("nope")
    with pytest.raises(ValueError):
        parse_config({**raw, "profiles": {"x": {"roles": {"coder": {"model": "zz/m"}}}}})


def test_past_work_is_repriced_for_another_model():
    from roundtable.harness.config import ModelRef, parse_config

    cfg = parse_config({"providers": {"a": {"type": "scripted"}}, "roles": {"orchestrator": {"model": "a/x"}},
                        "pricing": {"a/x": {"input": 1, "output": 1}, "a/y": {"input": 3, "output": 3}}})
    h = {"model": "a/x", "input": 1000, "output": 1000, "cost": 0.5}
    assert plandoc._reprice(cfg, 0.5, h, ModelRef.parse("a/y")) == pytest.approx(1.5)
    assert plandoc._reprice(cfg, 0.5, h, ModelRef.parse("a/x")) == 0.5


def test_learned_order_still_applies_inside_a_profile():
    from roundtable.harness.config import parse_config

    cfg = parse_config({
        "providers": {"a": {"type": "scripted"}},
        "roles": {"orchestrator": {"model": "a/p"}, "coder": {"model": "a/cheap"}},
        "profiles": {"balanced": {"roles": {"coder": {"model": "a/cheap", "fallback": ["a/strong"]}}},
                     "other": {"roles": {"coder": {"model": "a/third"}}}},
    })
    cfg.learned = {"roles": {"coder": {"model": "a/strong", "fallback": ["a/cheap"]}}}
    assert [str(m) for m in cfg.for_profile("balanced").roles["coder"].models] == ["a/strong", "a/cheap"]
    assert [str(m) for m in cfg.for_profile("other").roles["coder"].models] == ["a/third"]  # different models: the profile wins


def test_questions_for_the_owner_are_asked_in_plain_words():
    """The planner is told, in its prompt and in submit_plan itself, to write for someone who isn't a programmer."""
    from pathlib import Path

    import roundtable

    schema = plandoc.submission_schema({"type": "object"})["properties"]
    for part, field in (("decisions", "question"), ("questions", "text"), ("ideas", "text")):
        assert "isn't a programmer" in schema[part]["items"]["properties"][field]["description"]
    prompt = (Path(roundtable.__file__).parent / "prompts" / "orchestrator.md").read_text(encoding="utf-8")
    assert "isn't a programmer" in prompt and "no tool names or jargon" in prompt


def test_receipts_and_trouble():
    from roundtable.remote import is_trouble

    assert not is_trouble("Done. 1 change waits for you to press Update plan.")
    assert not is_trouble("Plan v3: 3 tasks added. The new plan is ready to look at.")
    for t in ("Couldn't do 'run': no plan", "Unknown action 'x'.", "The run ended as: failed.", "Are you sure? It costs more"):
        assert is_trouble(t)


def test_a_planner_cannot_say_the_owner_settled_a_choice():
    from roundtable.harness.plandoc import doc_from_submission
    doc = doc_from_submission({"decisions": [{"id": "C1", "question": "Cards first?", "recommended": "a",
                                              "why": "Settled by the owner. Only the deck-opening path changes.",
                                              "options": [{"id": "a", "label": "Yes"}, {"id": "b", "label": "No"}]}]},
                              "goal", 1)
    d = doc["decisions"][0]
    assert d["why"] == "Only the deck-opening path changes." and d["chosen"] is None


def test_a_plan_leads_with_a_short_title_and_where_it_stands(tmp_path):
    """Short first: the owner reads a title and one sentence; the builders' brief is folded further down."""
    import yaml

    from .test_hub import RAW as HUB_RAW

    raw = json.loads(json.dumps(HUB_RAW))
    raw["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
    raw["agents"]["proj"] = {"description": "a made-up project"}
    (tmp_path / "hub.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    hraw = json.loads(json.dumps(RAW))
    hraw["hub"] = {"config": str(tmp_path / "hub.yaml"), "agent": "harness"}
    orch, *_ = make(tmp_path, raw=hraw, brain=PlanBrain())
    long_goal = ("Also ship the bakery site as an Android app (APK) and a Windows app (EXE). One code base: both wrap "
                 "the same index.html, css and js.")
    orch.start(long_goal, require_approval=True)
    orch.run()
    page = (tmp_path / "hubdata" / "plans" / "proj.md").read_text(encoding="utf-8")
    heading = next(ln for ln in page.splitlines() if ln.startswith("# "))
    assert heading == "# Small bakery site"  # from the summary's first sentence, not the goal
    assert "## The builders' brief (version 1)" in page and long_goal in page
    assert "Estimate: about $" in page and "## Sets of models" not in page.split("## The builders' brief")[0]
    words = json.loads((tmp_path / "hubdata" / "plans" / "proj.asks.json").read_text(encoding="utf-8"))
    assert words["title"] == "Small bakery site" and words["summary"].startswith("A small bakery site")
    assert words["state"] == "Waiting for you: 1 choice, 1 question" and words["waiting"] == ["1 choice", "1 question"]
    assert words["estimate"].startswith("about $") and " and " in words["estimate"]
    orch.approve()
    assert orch.run() == "done"
    page = (tmp_path / "hubdata" / "plans" / "proj.md").read_text(encoding="utf-8")
    assert "Estimate:" not in page  # only while it waits for approval
    words = json.loads((tmp_path / "hubdata" / "plans" / "proj.asks.json").read_text(encoding="utf-8"))
    assert words["state"] == "Finished – 3 tasks" and words["waiting"] == [] and words["estimate"] == ""


def test_the_planners_title_wins_and_survives_a_revision():
    doc = plandoc.doc_from_submission({**DOC, "title": "Bakery site with a logo", "tasks": []}, "a goal", 0)
    assert plandoc.plan_title(doc) == "Bakery site with a logo"
    new = plandoc.doc_from_submission({**DOC, "tasks": []}, "a goal", 0)
    assert plandoc.carry_over(new, doc)["title"] == "Bakery site with a logo"
    long = plandoc.doc_from_submission({**DOC, "title": "one two three four five six seven eight nine ten", "tasks": []}, "g", 0)
    assert plandoc.plan_title(long) == "one two three four five six seven eight"


def test_an_old_plan_gets_a_title_made_for_it():
    t = plandoc.short_title
    assert t("", "", "Also ship the player as an Android app (APK) and a Windows app (EXE). One code base: both wrap "
                     "the same index.html, css, js") == "Also ship the player as an Android app and a Windows app"
    assert t("", "", "Build a lantern timer web app with index.html and app.js") == "Build a lantern timer web app"
    assert t("", "", "Plan v3: a shop for kites") == "Shop for kites"
    assert len(t("", "word " * 40, "")) <= 60 and t("", "", "") == "The plan"
    assert "summary" not in plandoc.submission_schema({})["required"]
    assert "title" in plandoc.submission_schema({})["properties"]


def test_the_state_sentence():
    from roundtable.harness.orchestrator import Task

    done = [Task(f"T{i}", "x", "coder", "d", status="done") for i in range(16)]
    assert plandoc.state_sentence({}, done, {"status": "done", "spent_usd": 5.01, "plan_approved": True}) == \
        "Finished – 16 tasks, $5.01"
    mixed = done[:2] + [Task("T9", "x", "coder", "d", status="running")] + [Task("T10", "x", "coder", "d")] * 4
    assert plandoc.state_sentence({}, mixed, {"status": "running", "plan_approved": True}) == "Building task 3 of 7"
    assert plandoc.state_sentence(plandoc.doc_from_submission({**DOC, "tasks": []}, "g", 0), [], {}) == \
        "Waiting for you: 1 choice, 1 question"
    assert plandoc.estimate_line({"cost_usd": 3.449, "minutes": 45}) == "about $3.45 and 45 minutes"
