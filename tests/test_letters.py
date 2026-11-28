"""Letters from the phone throughout (wave 9): plain letters get an answer, built files reach the hub, each project
says who reads its letters, a session's end hands its projects over, and a run that ends always republishes its
plan. Made-up projects only; no network, no keys."""

import json
import os
from datetime import UTC, datetime, timedelta

from roundtable import connect, reach
from roundtable.remote import HUB_MAX_BYTES, built_files, process

from .test_remote_todo import _orch

PC = {"id": "pc-desk", "name": "PC (DESK)", "kind": "pc"}
NO_SESSION = {}


def _letter(hub, agent, body, subject="note"):
    return hub.send("me", agent, subject, body, kind="ask")[0]


def test_send_me_the_apk_puts_the_newest_build_in_the_hub_and_replies(tmp_path, monkeypatch):
    orch = _orch(tmp_path)
    hub, agent = orch._hub(), orch._hub_agent()
    dist = orch.project.root / "dist"
    (dist / "electron").mkdir(parents=True)
    (dist / "Bakery-debug.apk").write_bytes(b"PK-apk")
    (dist / "Bakery-windows-x64.zip").write_bytes(b"PK-zip")
    old = dist / "Bakery-old.apk"
    old.write_bytes(b"PK-old")
    os.utime(old, (1_000_000, 1_000_000))
    letter = _letter(hub, agent, "send me the apk", "apk")
    assert process(orch.cfg, hub, log=lambda s: None) == 1
    assert [p.name for p in built_files(orch.project.root, (".apk",))] == ["Bakery-debug.apk"]  # newest only
    name = orch._hub_name()
    latest = hub.store.read_json(f"plans/builds/{name}/latest.json")
    assert [f["name"] for f in latest["files"]] == ["Bakery-debug.apk"] and latest["files"][0]["in_hub"]
    root = hub.store.root
    assert (root / "plans" / "builds" / name / "Bakery-debug.apk").read_bytes() == b"PK-apk"
    reply = next(m for m in hub.inbox("me", unread_only=False) if m.get("in_reply_to") == letter["id"])
    assert "Bakery-debug.apk" in reply["body"] and f"[hub:plans/builds/{name}/Bakery-debug.apk]" in reply["body"]
    assert any(m["id"] == reply["id"] for m in hub.inbox("me"))  # the owner asked: the answer arrives unread
    assert hub.inbox(agent) == []  # the letter itself is read
    assert process(orch.cfg, hub, log=lambda s: None) == 0  # answered once


def test_a_build_too_big_for_the_hub_is_named_not_copied(tmp_path, monkeypatch):
    import roundtable.remote as remote

    monkeypatch.setattr(remote, "HUB_MAX_BYTES", 3)
    orch = _orch(tmp_path)
    hub, agent = orch._hub(), orch._hub_agent()
    (orch.project.root / "dist").mkdir()
    (orch.project.root / "dist" / "Bakery-windows-x64.zip").write_bytes(b"PK-zip")
    letter = _letter(hub, agent, "Send me the Windows build please")
    process(orch.cfg, hub, log=lambda s: None)
    latest = hub.store.read_json(f"plans/builds/{orch._hub_name()}/latest.json")
    assert latest["files"][0]["in_hub"] is False and latest["files"][0]["path"] == ""
    reply = next(m for m in hub.inbox("me", unread_only=False) if m.get("in_reply_to") == letter["id"])
    assert "too big to send" in reply["body"]
    assert HUB_MAX_BYTES > 3  # the real limit is untouched


def test_any_other_plain_letter_goes_on_needs_you_and_is_answered(tmp_path):
    orch = _orch(tmp_path)
    hub, agent = orch._hub(), orch._hub_agent()
    letter = _letter(hub, agent, "Could the shop sign be blue?")
    assert process(orch.cfg, hub, log=lambda s: None) == 1
    reply = next(m for m in hub.inbox("me", unread_only=False) if m.get("in_reply_to") == letter["id"])
    assert "Needs you" in reply["body"]
    todos = [e for e in hub.journal.entries(agent, agent) if e["kind"] == "todo" and e["status"] == "open"]
    assert any("shop sign be blue" in e["text"] and e.get("priority") == "high" for e in todos)
    # asking for a build where nothing is built yet: said plainly, and on Needs you too
    letter = _letter(hub, agent, "send me the apk")
    process(orch.cfg, hub, log=lambda s: None)
    reply = next(m for m in hub.inbox("me", unread_only=False) if m.get("in_reply_to") == letter["id"])
    assert "no built app" in reply["body"]


def test_a_stranger_s_plain_letter_is_left_alone(tmp_path):
    orch = _orch(tmp_path)
    hub, agent = orch._hub(), orch._hub_agent()
    hub.send("harness", agent, "hello", "send me the apk", kind="ask")
    assert process(orch.cfg, hub, log=lambda s: None) == 0
    assert len(hub.inbox(agent)) == 1


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
    assert one["reading"] and one["offers"] == [] and "reads this project's letters" in one["words"]
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
    assert one["words"].startswith(reach.NOBODY) and "A cloud session last read them" in one["words"]
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


def test_the_same_command_sent_twice_is_done_once(tmp_path):
    orch = _orch(tmp_path)
    orch.run()
    hub, agent = orch._hub(), orch._hub_agent()
    body = json.dumps({"action": "note", "text": "Make the sign bigger"})
    first = hub.send("me", agent, "roundtable: note", body, kind="request")[0]
    again = hub.send("me", agent, "roundtable: note", body, kind="request")[0]
    assert process(orch.cfg, hub, log=lambda s: None) == 2
    pending = orch.project.plan_doc()["pending"]
    assert sum("sign bigger" in p["text"] for p in pending) == 1
    replies = {m["in_reply_to"]: m["body"] for m in hub.inbox("me", unread_only=False)}
    assert replies[again["id"]].startswith("Done once already") and first["id"] in replies
