"""Every hub project is a seat (wave 9): a project on a made-up hub appears with its plan and cards, says
whether anything is listening where it lives, and Approve writes the hub command once. No network."""

import json
from datetime import datetime, timedelta, timezone

from roundtable import hubseats, reach
from roundtable.ui.roundtable import build
from roundtable.ui.server import UIApp

from .test_hall import _hub_repo


def _app(tmp_path):
    repo, app_yaml = _hub_repo(tmp_path, {"me": {}, "harness": {}})
    (repo / "plans").mkdir()
    (repo / "plans" / "harness--kite-shop.md").write_text(
        "_Plan status: waiting for the owner · 1 choice · updated 2026-11-26T10:00:00Z by Roundtable Hold_\n\n"
        "# Plan v1: a shop for kites\n", encoding="utf-8")
    ask = {"id": "approve", "kind": "approve", "header": "Plan", "question": "Start building?",
           "options": [{"id": "approve", "label": "Approve and start"}], "stamp": "abc", "answer": None}
    (repo / "plans" / "harness--kite-shop.asks.json").write_text(json.dumps({"asks": [ask]}), encoding="utf-8")
    return repo, UIApp(str(app_yaml), "missing.yaml", agent="me")


def _beat(repo, minutes):
    at = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (repo / "plans" / "listening.json").write_text(json.dumps({"machine": "PC-desk", "at": at}), encoding="utf-8")


def test_a_hub_project_is_a_seat_with_its_plan_cards_and_who_listens(tmp_path):
    repo, app = _app(tmp_path)
    _beat(repo, 4)
    extra = hubseats.seats(app)
    assert [s["id"] for s in extra] == ["kite-shop"]
    s = extra[0]
    assert s["hub_name"] == "harness--kite-shop" and s["hub_agent"] == "harness" and s["status"] == "waiting"
    assert s["asks"] == 1 and s["actions"] == ["open_plan", "approve"]
    assert s["listening"]["words"] == "Your PC last listened 4 minutes ago." and not s["listening"]["stale"]
    seats = hubseats.join(build(app)["seats"], extra)
    kite = next(x for x in seats if x["id"] == "kite-shop")
    assert kite["listening"]["minutes"] == 4  # the table's own seat, now saying who listens
    # a hub seat the table didn't make is added, not lost
    joined = hubseats.join([], extra)
    assert joined[0]["id"] == "kite-shop" and joined[0]["open_todos"] == 0


def test_approve_is_sent_once_and_says_when_nothing_is_listening(tmp_path):
    repo, app = _app(tmp_path)
    _beat(repo, 90)
    got = hubseats.send_once(app, "harness", "kite-shop", "approve")
    assert got["sent"] and got["reply"].startswith("Sent, but nothing is listening there right now.")
    assert "Nothing will start until" in got["reply"]
    again = hubseats.send_once(app, "harness", "kite-shop", "approve")
    assert not again["sent"] and again["reply"].startswith("Already sent")
    msgs = app.hub.inbox("harness", unread_only=True)
    assert len(msgs) == 1 and msgs[0]["subject"] == "roundtable: approve"
    assert json.loads(msgs[0]["body"]) == {"action": "approve", "project_folder": "kite-shop"}
    # after the PC has read it, a new tap sends again
    app.hub.inbox("harness", unread_only=True, mark_read=True)
    _beat(repo, 1)
    third = hubseats.send_once(app, "harness", "kite-shop", "approve")
    assert third["sent"] and "last listened" in third["reply"] and "nothing is listening" not in third["reply"]


def test_no_beat_at_all_says_so(tmp_path):
    repo, app = _app(tmp_path)
    beat = hubseats.listening(app)
    assert beat["stale"] and beat["words"] == reach.listening(None)["words"]
    assert hubseats.seats(type("NoHub", (), {"hub": None})()) == []


def test_the_routes(tmp_path, monkeypatch):
    from roundtable.ui import server

    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "todoapi"))
    repo, app = _app(tmp_path)
    _beat(repo, 2)
    got = app.dispatch("GET", "/api/hub/seats", {}, {})
    assert got["seats"][0]["id"] == "kite-shop" and got["listening"]["minutes"] == 2
    r = app.dispatch("POST", "/api/hub/send-once", {}, {"agent": "harness", "folder": "kite-shop", "action": "approve"})
    assert r["sent"]
    r = app.dispatch("POST", "/api/hub/send-once", {}, {"agent": "harness", "folder": "kite-shop", "action": "approve"})
    assert not r["sent"]
