"""The news classifier (notify.py), its feed and the API (ui/notifyapi.py). Made-up projects only."""

import json
from pathlib import Path

import pytest

from roundtable import notify
from roundtable.ui import notifyapi

CASES = Path(__file__).resolve().parents[1] / "mobile" / "app" / "src" / "test" / "resources" / "notify_cases.json"


def _cases():
    return json.loads(CASES.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["name"])
def test_shared_cases(case):
    """The same cases the phone's twin runs (NotifyCasesTest)."""
    got = notify.classify(case["old"], case["new"], open_project=case.get("open"))
    view = [{"key": n.key, "kind": n.kind, "group": n.group, "quiet": n.quiet, "title": n.title, "text": n.text,
             "buttons": [b["id"] for b in n.buttons]} for n in got]
    assert view == case["expect"]
    assert all(n.kind in notify.KINDS and n.at == case["new"]["at"] for n in got)


def _rt(status="running", needs=(), actions=(), state="", last="2026-11-27T10:00:00Z", done=1, total=3):
    return {"seats": [{"id": "kite", "name": "Kite", "status": status, "state": state, "actions": list(actions),
                       "progress": {"done": done, "total": total}, "last_activity": last}],
            "needs_you": list(needs)}


def test_snapshot_from_the_hall():
    ask = {"id": "task:T2", "kind": "failed", "stamp": "x1", "question": "T2 didn't pass. What now?", "path": "/lab/kite",
           "options": [{"id": "retry", "label": "Retry"}]}
    rt = _rt("waiting", needs=[
        {"kind": "run", "project": "kite", "name": "Kite", "text": "stopped", "actions": ["retry", "skip"], "ask": ask,
         "via": "here", "path": "/lab/kite"},
        {"kind": "run", "project": "kite", "name": "Kite", "text": "at the limit", "actions": ["budget"]},
        {"kind": "todo", "project": "kite", "name": "Kite", "text": "Pick a name", "id": "7", "actions": ["done"]},
        {"kind": "ask", "project": "kite", "name": "Kite", "via": "hub", "hub_agent": "harness",
         "ask": {"id": "approve", "kind": "approve", "stamp": "s", "question": "Start?", "options": []}},
    ])
    s = notify.snapshot(rt, at="2026-11-27T10:01:00Z")
    assert s["projects"][0] == {"id": "kite", "name": "Kite", "status": "waiting", "state": "", "done": 1, "total": 3,
                                "last_activity": "2026-11-27T10:00:00Z", "paused": False}
    kinds = [(n["key"], n["kind"]) for n in s["needs"]]
    assert kinds == [("ask:kite:task:T2:x1", "failed"), ("run:kite:at the limit", "money"),
                     ("todo:kite:7", "needs_you"), ("ask:kite:approve:s", "needs_you")]
    assert s["needs"][0]["path"] == "/lab/kite" and s["needs"][0]["text"] == "T2 didn't pass. What now?"
    assert s["needs"][3]["via"] == "hub" and s["needs"][3]["hub_agent"] == "harness"
    paused = notify.snapshot(_rt("idle", actions=["resume"], state="Paused part-way"))
    assert paused["projects"][0]["paused"] is True


def test_the_feed_never_gives_the_same_news_twice_even_after_a_restart(tmp_path):
    path = tmp_path / "seen.json"
    need = {"kind": "todo", "project": "kite", "name": "Kite", "text": "Pick a name", "id": "7", "actions": ["done"]}
    feed = notify.Feed(path)
    first = feed.update(notify.snapshot(_rt(needs=[need]), at="2026-11-27T10:00:00Z"))
    assert [x["key"] for x in first] == ["needs_you:todo:kite:7"] and first[0]["n"] == 1
    assert feed.update(notify.snapshot(_rt(needs=[need]), at="2026-11-27T10:01:00Z")) == []
    done = feed.update(notify.snapshot(_rt("done", needs=[need], last="2026-11-27T10:02:00Z", done=3),
                                       at="2026-11-27T10:02:00Z"))
    assert [x["kind"] for x in done] == ["finished"] and done[0]["text"] == "All 3 tasks done. Open it to try it."
    assert [x["n"] for x in feed.since(1)] == [2] and len(feed.since(None)) == 2
    assert [x["n"] for x in feed.since("2026-11-27T10:01:00Z")] == [2]
    again = notify.Feed(path)  # the app restarted: no old snapshot, but the keys are remembered
    assert again.update(notify.snapshot(_rt(needs=[need]), at="2026-11-27T11:00:00Z")) == []


def test_buttons_only_where_safe():
    two = {"kind": "idea", "question": "Add a dark mode?", "options": [{"id": "yes", "label": "Yes, add it"},
                                                                     {"id": "no", "label": "No thanks"}]}
    assert [b["label"] for b in notify.buttons(two)] == ["Yes, add it", "No thanks"]
    assert notify.buttons({**two, "question": "x" * 200}) == []  # not a short card: open it instead
    assert notify.buttons({**two, "kind": "look"}) == []
    assert notify.buttons({"kind": "approve", "options": [{"id": "revise", "label": "Update the plan"}]}) == []
    assert notify.buttons({"kind": "approve", "options": [{"id": "approve", "label": "Approve and start"},
                                                          {"id": "approve_cheap", "label": "Later"}]}) == \
        [{"id": "approve", "label": "Approve plan"}]
    assert notify.buttons(None) == []


def test_settings_per_kind(tmp_path):
    p = tmp_path / "n.json"
    assert notify.load_settings(p) == notify.default_settings()
    out = notify.save_settings(p, {"kinds": {"idle": False, "nonsense": False}, "popups": False})
    assert out["kinds"]["idle"] is False and out["kinds"]["finished"] is True and "nonsense" not in out["kinds"]
    assert notify.load_settings(p) == out


class FakeApp:
    def __init__(self, home, rt):
        self.home, self.rt, self.auto_sync_error = home, rt, ""

    def _backup_home(self):
        return self.home


def test_the_api_returns_news_since_a_time(tmp_path, monkeypatch):
    from roundtable.ui import roundtable

    app = FakeApp(tmp_path, _rt())
    monkeypatch.setattr(roundtable, "build", lambda a: a.rt)
    assert set(notifyapi.routes(app)) == {("GET", "/api/notifications"), ("GET", "/api/notifications/settings"),
                                          ("POST", "/api/notifications/settings")}
    r = notifyapi.news(app, {})
    assert r["news"] == [] and r["next"] == 0 and [k["id"] for k in r["kinds"]] == list(notify.KINDS)
    app.rt = _rt(needs=[{"kind": "todo", "project": "kite", "name": "Kite", "text": "Pick a name", "id": "7"}])
    assert notifyapi.news(app, {})["news"] == []  # looked at most every few seconds
    notifyapi.refresh(app, force=True)
    r = notifyapi.news(app, {"since": ["0"]})
    assert [(x["kind"], x["title"]) for x in r["news"]] == [("needs_you", "Kite needs you")] and r["next"] == 1
    assert notifyapi.news(app, {"since": [str(r["next"])]})["news"] == []
    assert notifyapi.news(app, {"since": ["2000-01-01T00:00:00Z"]})["news"][0]["key"] == "needs_you:todo:kite:7"
    assert (tmp_path / "notify-seen.json").is_file()
    s = notifyapi.routes(app)[("POST", "/api/notifications/settings")]({"kinds": {"money": False}})
    assert s["kinds"]["money"] is False and notifyapi.settings_get(app)["kinds"]["money"] is False


def test_real_hall_news(setup_hall):
    """End to end over the Hall's own data: a project waiting for its plan's approval is news."""
    app, orch = setup_hall
    notifyapi.refresh(app, force=True)
    news = notifyapi.news(app, {"since": ["0"]})["news"]
    assert any(x["project"] == "proj" and x["kind"] == "needs_you" for x in news), news
    plan = next(x for x in news if x["project"] == "proj" and x["kind"] == "needs_you")
    assert plan["title"] == "Proj: the plan is ready" and [b["id"] for b in plan["buttons"]] == ["approve"]
    assert plan["path"] and plan["ask"]["id"] == "approve"


@pytest.fixture
def setup_hall(tmp_path, monkeypatch):
    import yaml

    from roundtable.ui.server import UIApp

    from .test_harness import make as make_harness
    from .test_hub import RAW as HUB_RAW

    hub_raw = json.loads(json.dumps(HUB_RAW))
    hub_raw["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
    (tmp_path / "hub.yaml").write_text(yaml.safe_dump(hub_raw), encoding="utf-8")
    orch, *_ = make_harness(tmp_path)
    cfg = orch.cfg
    cfg.lab_dir = tmp_path / "lab"
    app = UIApp(str(tmp_path / "hub.yaml"), "missing.yaml", agent="backend")
    app.cfg = lambda: cfg
    monkeypatch.setattr(app, "_backup_home", lambda: tmp_path / "home", raising=False)
    orch._register_with_lab()
    orch.start("bakery site", require_approval=True)
    orch.set_kind("website", by="owner", replan=False)  # as the wizard does: only the approval waits
    assert orch.run() == "awaiting_approval"
    return app, orch


def test_through_the_server_once_listed_in_feature_apis(setup_hall, monkeypatch):
    from roundtable.ui import server

    app, _ = setup_hall
    monkeypatch.setattr(server, "FEATURE_APIS", ("notifyapi",))
    r = app.dispatch("GET", "/api/notifications", {"since": ["0"]}, {})
    assert r["next"] >= 1 and any(x["kind"] == "needs_you" for x in r["news"])
    assert app.dispatch("POST", "/api/notifications/settings", {}, {"popups": False})["popups"] is False
    assert "/api/notifications" in app.dispatch("GET", "/api/features", {}, {})["routes"]
