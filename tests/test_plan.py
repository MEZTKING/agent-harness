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
    md = (orch.project.dir / "plan.md").read_text()
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
    assert doc["ideas"][0]["state"] == "accepted" and doc["questions"] == []
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
                                       "at": "2026-11-20T10:00:00Z"}) for i in range(4)))
    hist = plandoc.history_by_role([f])
    assert hist["coder"]["cost"] == 0.5 and hist["coder"]["minutes"] == 2.0
    est = plandoc.estimate(orch.cfg, [Task("X", "x", "coder", "d")], hist)
    assert est["by_role"]["coder"]["basis"] == "history" and est["cost_usd"] == 0.5
