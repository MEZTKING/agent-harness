"""Who runs each project, and a plan that always says how a run ended (wave 9): each project says who last ran it,
a session's end hands its projects over, and a run that ends always republishes its plan and cards. Made-up
projects only; no network, no keys."""

import json
import os
from datetime import UTC, datetime, timedelta

from roundtable import connect, reach
from roundtable.remote import process

from .test_remote_todo import _orch

PC = {"id": "pc-desk", "name": "PC (DESK)", "kind": "pc"}
NO_SESSION = {}


def test_each_project_says_who_reads_its_letters(tmp_path, monkeypatch):
    for k in reach.SESSION_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ROUNDTABLE_MACHINE", "pc-desk")
    monkeypatch.setenv("ROUNDTABLE_MACHINE_NAME", "PC (DESK)")
    orch = _orch(tmp_path)
    hub = orch._hub()
    process(orch.cfg, hub, log=lambda s: None)
    name = orch._hub_name()
    data = hub.store.read_json(f"plans/readers/{name}.json")
    assert {k: data[k] for k in ("project", "machine", "machine_id", "kind", "state")} == {
        "project": name, "machine": "PC (DESK)", "machine_id": "pc-desk", "kind": "pc", "state": "reading"}
    one = next(r for r in reach.readers(hub) if r["project"] == name)
    assert one["reading"] and one["offers"] == [] and "runs this project" in one["words"]
    later = datetime.now(UTC) + timedelta(minutes=16)
    one = next(r for r in reach.readers(hub, later) if r["project"] == name)
    assert not one["reading"] and one["words"].startswith(reach.NOBODY)
    assert [o["id"] for o in one["offers"]] == ["phone"]  # no other PC is known: only the phone is offered
    assert reach.listening(hub, later)["projects"][0]["project"] == name  # the phone's /api/listening carries it


def test_a_sessions_end_hands_its_projects_over(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    monkeypatch.setenv("ROUNDTABLE_MACHINE", "pc-cloud1")
    orch = _orch(tmp_path)
    hub = orch._hub()
    process(orch.cfg, hub, log=lambda s: None)
    name = orch._hub_name()
    assert hub.store.read_json(f"plans/readers/{name}.json")["kind"] == "session"
    # the owner's PC is a seat in the hub: it's offered once the session has gone
    hub.store.write_json({"machines/pc-home.json": {"id": "pc-home", "name": "PC (HOME)", "kind": "pc",
                                                    "last_seen": reach.iso(reach.utcnow())}}, "pc")
    assert connect.hand_over(hub) == [name]
    one = next(r for r in reach.readers(hub) if r["project"] == name)
    assert not one["reading"] and one["state"] == "no_reader" and "session" in one["note"]
    assert one["words"].startswith(reach.NOBODY) and "A cloud session last ran it" in one["words"]
    assert {(o["id"], o["machine"]) for o in one["offers"]} == {("phone", ""), ("pc", "pc-home")}
    assert connect.hand_over(hub) == []  # already handed over


def test_a_run_that_ends_republishes_its_plan_and_settles_its_questions(tmp_path):
    from roundtable.harness.orchestrator import plan_state

    orch = _orch(tmp_path)
    orch.run()  # plans (scripted): waits for approval
    hub = orch._hub()
    name = orch._hub_name()
    page = (hub.store.root / "plans" / f"{name}.md").read_text(encoding="utf-8")
    assert page.startswith("_Plan status: waiting for the owner")
    meta = orch.project.meta()
    meta.update(plan_approved=True, status="paused_budget")
    orch.project.save_meta(meta)
    orch._publish_plan()
    page = (hub.store.root / "plans" / f"{name}.md").read_text(encoding="utf-8")
    first = page.splitlines()[0]
    assert first.startswith("_Plan status: paused · ") and "tasks done" in first and "question" not in first
    asks = json.loads((hub.store.root / "plans" / f"{name}.asks.json").read_text(encoding="utf-8"))
    assert not any(a.get("kind") == "question" for a in asks["asks"])
    assert [plan_state(m) for m in ({"status": "done"}, {}, {"plan_approved": True, "status": "running"},
                                    {"plan_approved": True, "status": "failed"})] == [
        "done", "waiting for the owner", "approved, building", "stopped"]


def test_run_always_publishes_the_plan_at_the_end(tmp_path, monkeypatch):
    orch = _orch(tmp_path)
    seen = []
    monkeypatch.setattr(type(orch), "_publish_plan", lambda self: seen.append("plan"))
    monkeypatch.setattr(type(orch), "_run", lambda self, max_tasks=None: (_ for _ in ()).throw(RuntimeError("boom")))
    try:
        orch.run()
    except RuntimeError:
        pass
    assert seen == ["plan"]  # even a run that failed says so in the hub
