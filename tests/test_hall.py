"""The Hall's seats: every project the owner works on, with a friendly name; the hub's own hub.yaml read
again on every sync; Needs you ranked like the phone; commands through the hub for projects elsewhere.
Made-up projects only."""

import json

import yaml

from roundtable.core.config import load_config
from roundtable.remote import process
from roundtable.ui import hall
from roundtable.ui.roundtable import activity, build
from roundtable.ui.server import UIApp

from .test_remote_todo import _orch


def _hub_repo(tmp_path, agents):
    """A hub repository clone (its own hub.yaml) and the app's hub.yaml pointing at it, as connect writes."""
    repo = tmp_path / "hub-repo"
    repo.mkdir()
    (repo / "hub.yaml").write_text(yaml.safe_dump({
        "storage": {"type": "file", "path": "."}, "default_policy": "deny", "agents": agents,
        "rules": [{"from": "*", "to": "*", "allow": ["read_card", "message"]}]}), encoding="utf-8")
    app_yaml = tmp_path / "app-hub.yaml"
    app_yaml.write_text(yaml.safe_dump({"storage": {"type": "file", "path": str(repo)}, "default_policy": "deny",
                                        "agents": {"me": {}}}), encoding="utf-8")
    return repo, app_yaml


def test_the_hub_repository_lists_the_projects_and_new_ones_arrive(tmp_path):
    repo, app_yaml = _hub_repo(tmp_path, {"me": {}, "bakery": {"repo": "someone/bakery"}})
    assert set(load_config(str(app_yaml)).agents) == {"me", "bakery"}  # not the copy made at connect time
    app = UIApp(str(app_yaml), "missing.yaml", agent="me")
    raw = yaml.safe_load((repo / "hub.yaml").read_text(encoding="utf-8"))
    raw["agents"]["tide-clock"] = {"repo": "someone/tide-clock", "title": "Tide clock"}
    (repo / "hub.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")  # another computer added a project
    data = build(app)
    names = {s["id"]: s["name"] for s in data["seats"]}
    assert names == {"bakery": "Bakery", "tide-clock": "Tide clock"}
    assert data["notes"]["name"] == "My notes"  # the owner's own notes sit beside the table


def test_projects_roundtable_builds_elsewhere_get_their_own_seat(tmp_path):
    repo, app_yaml = _hub_repo(tmp_path, {
        "me": {}, "harness": {"description": "the project runner"},
        "agent-harness": {"repo": "someone/agent-harness"}, "pond-game": {"repo": "someone/pond-game"}})
    app = UIApp(str(app_yaml), "missing.yaml", agent="me")
    hub = app.hub
    plans = repo / "plans"
    plans.mkdir()
    (plans / "harness--kite-shop.md").write_text(
        "_Plan status: waiting for the owner · 1 choice · about $0.40 · updated 2026-11-26T10:00:00Z by Roundtable "
        "Hold_\n\n# Plan v1: a shop for kites\n", encoding="utf-8")
    ask = {"id": "approve", "kind": "approve", "header": "Plan", "question": "Is the plan right? Start building?",
           "options": [{"id": "approve", "label": "Approve and start"}], "stamp": "abc", "answer": None}
    (plans / "harness--kite-shop.asks.json").write_text(json.dumps({"asks": [ask]}), encoding="utf-8")
    hub.journal.add("harness", "todo", "kite-shop: The plan is ready: look at it, then approve it", priority="high",
                    source="harness")
    hub.journal.add("pond-game", "todo", "On each PC run pip install roundtable and clone the data", priority="high")
    hub.journal.add("pond-game", "todo", "Pick the frog's colour", priority="high")

    data = build(app)
    seats = {s["id"]: s for s in data["seats"]}
    assert set(seats) == {"kite-shop", "agent-harness", "pond-game"}  # no "me", no "harness"
    assert seats["agent-harness"]["name"] == hall.THIS_APP
    kite = seats["kite-shop"]
    assert kite["status"] == "waiting" and kite["where"] == "elsewhere" and kite["hub_agent"] == "harness"
    assert kite["brief"]["open_todos"][0]["text"].startswith("The plan is ready")  # the shared journal, split
    needs = data["needs_you"]
    assert needs[0]["kind"] == "ask" and needs[0]["project"] == "kite-shop" and needs[0]["via"] == "hub"
    assert not any(n["kind"] == "todo" and "plan is ready" in n["text"] for n in needs)  # the card stands for it
    todos = [n["text"] for n in needs if n["kind"] == "todo"]
    assert todos == ["Pick the frog's colour"]  # an instruction for a programmer stays out of Needs you
    assert any(f["project"] == "kite-shop" for f in activity(app))

    # Approve from the desktop: a command through the hub, for that project only
    r = app.hub_command({"agent": "harness", "folder": "kite-shop", "action": "approve"})
    assert r["reply"].startswith("Sent")
    msg = hub.inbox("harness", unread_only=True)[0]
    assert msg["subject"] == "roundtable: approve" and json.loads(msg["body"])["project_folder"] == "kite-shop"
    plan = app.hub_plan({"name": ["harness--kite-shop"]})
    assert plan["title"] == "Kite Shop" and "a shop for kites" in plan["markdown"] and plan["asks"]


def test_a_command_for_another_folder_is_left_for_it(tmp_path):
    orch = _orch(tmp_path)
    hub, agent = orch._hub(), orch._hub_agent()
    hub.send("me", agent, "roundtable: run", json.dumps({"action": "todo_done", "id": "x",
                                                        "project_folder": "someone-else"}), kind="request")
    assert process(orch.cfg, hub, log=lambda s: None) == 0
    assert len(hub.inbox(agent, unread_only=True)) == 1  # still waiting for the project it names


def test_owner_todos_and_friendly_names():
    assert hall.for_owner({"text": "Choose the shop's opening hours"})
    assert not hall.for_owner({"text": "Add the key to harness.yaml"})
    assert not hall.for_owner({"text": "Run `make` again"})
    assert hall.for_owner({"text": "Run `make` again", "tags": ["owner"]})
    assert hall.friendly("tide-clock") == "Tide Clock"


def test_a_plan_waiting_elsewhere_without_cards_offers_open_and_approve(tmp_path):
    repo, app_yaml = _hub_repo(tmp_path, {"me": {}, "harness": {}})
    (repo / "plans").mkdir()
    (repo / "plans" / "harness--rain-garden.md").write_text(
        "_Plan status: waiting for the owner · 2 questions · updated 2026-11-26T09:00:00Z by Roundtable Hold_\n\n"
        "# Plan v2: pick plants for wet soil\n", encoding="utf-8")
    app = UIApp(str(app_yaml), "missing.yaml", agent="me")
    data = build(app)
    need = data["needs_you"][0]
    assert need["kind"] == "plan" and need["actions"] == ["open_plan", "approve"] and need["hub_name"] == \
        "harness--rain-garden"
    s = data["seats"][0]
    assert s["id"] == "rain-garden" and s["state"].startswith("Waiting for you") and s["goal"] == "pick plants for wet soil"
