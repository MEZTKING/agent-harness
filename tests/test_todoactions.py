"""To-dos become actions (wave 9): each kind of to-do the harness writes gets its one-tap button, no to-do the
harness's own code writes tells the owner to go somewhere, paste, type or run something without one, and the
server does the action from its own table. Made-up projects and hubs; GitHub is a stand-in; no network."""

import ast
import json
from pathlib import Path

import pytest

from roundtable import todoactions as ta
from roundtable.ui import todoapi
from roundtable.ui.roundtable import build
from roundtable.ui.server import ApiError, UIApp

from .test_hall import _hub_repo

SRC = Path(__file__).resolve().parents[1] / "src" / "roundtable"


def _a(text, **kw):
    return ta.action_for({"text": text, "id": "t1", "agent": "harness", "project": "kite-shop", **kw}, None)


# -- each kind ------------------------------------------------------------------------------------------------
def test_each_kind_of_todo_gets_the_right_action():
    a = _a("The plan is ready: look at it, then approve it to start building")
    assert a["kind"] == "hub" and a["route"] == "/api/hub/command" and a["body"] == {
        "agent": "harness", "folder": "kite-shop", "action": "approve"} and a["confirm"]
    a = _a("The plan is ready: approve it", path="/lab/kite-shop")  # on this computer: the project's own route
    assert a["route"] == "/api/project" and a["body"] == {"path": "/lab/kite-shop", "action": "approve"}
    a = _a("Task T3 “the menu” didn't pass: try it again or skip it", path="/lab/kite-shop")
    assert a["body"] == {"path": "/lab/kite-shop", "action": "retry", "task": "T3"} and a["label"] == "Try it again"
    a = _a("DeepSeek is out of credit: top up that account, then run the project again")
    assert a["label"] == "I've topped up: carry on" and a["body"]["action"] == "carry_on"
    a = _a("Paused at this project's spending limit: choose Carry on to give it more")
    assert a["label"] == "Carry on" and a["confirm"]
    assert _a("The first slice is ready. Try it, then carry on when you're ready.")["label"] == "Carry on"
    assert _a("the project's setup command (make) stopped with code 2; fix it in the project's settings or by hand, "
              "then run again")["route"] == "#/p/kite-shop/settings"
    assert _a("Not finished yet: 2 things on the done list don’t work. Choose Try fixing again, or Accept as it is"
              )["route"] == "#/p/kite-shop"
    assert _a("Add a critic role in the desktop app")["route"] == "/api/setup/recommended"
    assert _a("Add the OpenRouter key so the checkers can work")["route"] == "#/settings/keys"
    a = _a("Set main as the default branch of someone/kite-shop")
    assert a["route"] == "/api/todo/github" and a["body"] == {"repo": "someone/kite-shop", "branch": "main"}
    assert _a("Turn on daily backups")["route"] == "/api/todo/backup"
    a = _a("Two cloud environments need the setup lines pasted by hand")
    assert a["kind"] == "handover" and a["route"] == "/api/todo/handoff"
    a = _a("This game needs Godot: install it")
    assert a["route"] == "/api/tools/install" and a["body"] == {"tool": "godot"} and a["close"] is False
    assert _a("Check DeepSeek's current prices so the counts match the bill")["kind"] == "handover"
    assert _a("this run has spent $2.00 of real credit, the limit you set; run again to carry on")["confirm"]
    assert _a("Today's spending limit ($3.00) is reached: this run carries on tomorrow, or raise the limit in "
              "Settings")["route"] == "#/settings/spending"
    assert _a("kite-shop: the task “menu” is stuck.")["route"] == "#/p/kite-shop"
    assert _a("Pick the frog's colour") is None  # a real choice: only Done
    assert ta.counts([{"text": "Pick the frog's colour"}, {"text": "Turn on backups"}], None) == {"with": 1, "without": 1}


def test_the_six_waiting_at_the_pc_each_get_an_action_or_go_to_an_agent():
    """plans/owner-todo.md's "When you're at your PC" (made-up wording of the same six)."""
    six = {
        "Backups: install Google Drive for desktop, sign in, then in Settings → Backups tick Back up every day":
            "backups",
        "Openference: top the balance up to over $1 so Claude works through it": "page",
        "Two cloud environments need the setup lines pasted by hand (Settings → the environment → Setup script)":
            "handover",
        "Add a critic role in the desktop app (Settings → Roles)": "job",
        "DeepSeek prices: check the current prices on DeepSeek's site": "handover",
        "GitHub: set main as the default branch of agent-harness": "github",
    }
    for text, kind in six.items():
        a = ta.action_for({"text": text, "id": "x", "agent": "me"}, None)
        assert a and a["kind"] == kind, text


# -- nothing the harness writes sends the owner out without a button ------------------------------------------
def _strings(node):
    """Every text a to-do's expression can be: constants, f-strings (values as X), both sides of an if."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return ["".join(v.value if isinstance(v, ast.Constant) else "X" for v in node.values)]
    if isinstance(node, ast.IfExp):
        return _strings(node.body) + _strings(node.orelse)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return [a + b for a in _strings(node.left) or ["X"] for b in _strings(node.right) or ["X"]]
    return []


def _todo_texts():
    found = []
    for p in SRC.rglob("*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
                continue
            if n.func.attr == "_attention" and len(n.args) >= 2:
                found += [(p.name, s) for s in _strings(n.args[1])]
            if (n.func.attr == "add" and len(n.args) >= 3 and isinstance(n.args[1], ast.Constant)
                    and n.args[1].value == "todo"):
                found += [(p.name, s) for s in _strings(n.args[2])]
    return found


def test_no_todo_the_harness_writes_says_go_to_paste_type_or_run_without_an_action():
    texts = _todo_texts()
    assert len(texts) >= 15  # the scan really finds them
    bad = [(f, t) for f, t in texts if ta.needs_action(t)
           and not ta.action_for({"text": t, "id": "x", "agent": "harness", "project": "p"}, None)]
    assert bad == []
    assert ta.needs_action("Go to GitHub and paste this") and not ta.needs_action("this run has spent half")


# -- the server does it, from its own table --------------------------------------------------------------------
@pytest.fixture
def hub_app(tmp_path, monkeypatch):
    from roundtable.ui import server

    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "todoapi"))
    repo, app_yaml = _hub_repo(tmp_path, {"me": {}, "harness": {}, "kite-shop": {"repo": "someone/kite-shop"},
                                          "cloud-shop": {"repo": "someone/cloud-shop"}})
    app = UIApp(str(app_yaml), "missing.yaml", agent="me")
    monkeypatch.setattr(app, "_backup_home", lambda: tmp_path / "home")
    return app


def _need(app, text):
    for n in build(app)["needs_you"]:
        if n["kind"] == "todo" and n["text"] == text:
            return n
    raise AssertionError(text)


def test_the_github_setting_is_done_with_the_apps_key(hub_app, monkeypatch):
    calls = []
    monkeypatch.setattr(todoapi, "github_call", lambda m, url, body, tok: (calls.append((m, url, body, tok)) or
                                                                           (200, {"default_branch": body["default_branch"]})))
    monkeypatch.setattr("roundtable.automation.github_token", lambda: "proxy-injected")
    hub_app.hub.journal.add("kite-shop", "todo", "Set main as the default branch of kite-shop", priority="high",
                            source="harness")
    n = _need(hub_app, "Set main as the default branch of kite-shop")
    first = hub_app.dispatch("POST", "/api/todo/act", {}, {"agent": n["agent"], "id": n["id"]})
    assert first["confirm"].startswith("Make main the default branch of kite-shop") and calls == []
    done = hub_app.dispatch("POST", "/api/todo/act", {}, {"agent": n["agent"], "id": n["id"], "confirm": True})
    assert done["ok"] and "is now the default branch" in done["reply"]
    assert calls == [("PATCH", "https://api.github.com/repos/someone/kite-shop", {"default_branch": "main"},
                      "proxy-injected")]
    assert not any(x["kind"] == "todo" for x in build(hub_app)["needs_you"])  # off the list
    # a key without the right says what to do next
    monkeypatch.setattr(todoapi, "github_call", lambda *a: (403, {}))
    with pytest.raises(ApiError, match="Administration"):
        todoapi.github(hub_app, {"repo": "someone/kite-shop", "confirm": True})


def test_a_cloud_set_up_is_handed_to_its_session_not_the_owner(hub_app):
    hub_app.hub.journal.add("cloud-shop", "todo", "The cloud environment needs its setup script set", priority="high",
                            source="harness", details="pip install -e .")
    n = _need(hub_app, "The cloud environment needs its setup script set")
    got = hub_app.dispatch("POST", "/api/todo/act", {}, {"agent": n["agent"], "id": n["id"]})
    assert got["ok"] and got["reply"].startswith("Handed to Cloud Shop")
    letter = hub_app.hub.inbox("cloud-shop", unread_only=True)[0]
    assert letter["subject"] == "A to-do handed to you" and "pip install -e ." in letter["body"]
    assert "one-tap card" in letter["body"]
    assert not any(x["kind"] == "todo" for x in build(hub_app)["needs_you"])


def test_backups_and_pages_and_counts(hub_app, monkeypatch, tmp_path):
    from roundtable import backup as bk

    monkeypatch.setattr(bk, "find_drive_folders", lambda *a, **k: [])
    hub_app.hub.journal.add("kite-shop", "todo", "Turn on daily backups", priority="high", source="harness")
    hub_app.hub.journal.add("kite-shop", "todo", "Add the OpenRouter key", priority="high", source="harness")
    hub_app.hub.journal.add("kite-shop", "todo", "Pick the frog's colour", priority="high", source="harness")
    listing = hub_app.dispatch("GET", "/api/todo/actions", {}, {})
    assert (listing["with"], listing["without"]) == (2, 1)
    n = _need(hub_app, "Turn on daily backups")
    got = hub_app.dispatch("POST", "/api/todo/act", {}, {"agent": n["agent"], "id": n["id"]})
    assert got["ok"] is False and "Browse" in got["reply"]  # no Drive folder: it stays on the list, and says why
    monkeypatch.setattr(bk, "find_drive_folders", lambda *a, **k: [tmp_path])
    assert hub_app.dispatch("POST", "/api/todo/act", {}, {"agent": n["agent"], "id": n["id"]})["ok"]
    key = _need(hub_app, "Add the OpenRouter key")
    assert hub_app.dispatch("POST", "/api/todo/act", {}, {"agent": key["agent"], "id": key["id"]}) == {
        "open": "#/settings/keys", "label": "Add the key"}
    frog = _need(hub_app, "Pick the frog's colour")
    with pytest.raises(ApiError, match="tick it off with Done"):
        hub_app.dispatch("POST", "/api/todo/act", {}, {"agent": frog["agent"], "id": frog["id"]})
    with pytest.raises(ApiError, match="only opens in the desktop app's own window"):
        hub_app.dispatch("POST", "/api/backup/browse", {}, {})
