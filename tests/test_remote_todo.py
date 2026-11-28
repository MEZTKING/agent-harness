import json

import pytest
import yaml

from roundtable.remote import execute, is_trouble, process

from .test_harness import RAW, make
from .test_hub import RAW as HUB_RAW
from .test_plan import PlanBrain


def _orch(tmp_path):
    raw = json.loads(json.dumps(HUB_RAW))
    raw["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
    raw["agents"].update({"proj": {}, "harness": {}, "me": {}})
    raw["rules"].append({"from": "*", "to": "*", "allow": ["message"]})
    (tmp_path / "hub.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    hraw = json.loads(json.dumps(RAW))
    hraw["hub"] = {"config": str(tmp_path / "hub.yaml"), "agent": "harness"}
    orch, *_ = make(tmp_path, raw=hraw, brain=PlanBrain())
    orch.cfg.lab_dir = tmp_path / "lab"
    orch.start("bakery site", require_approval=True)  # a made-up project, so remote finds it
    return orch


def test_todo_done_from_the_phone(tmp_path):
    orch = _orch(tmp_path)
    hub = orch._hub()
    agent = orch._hub_agent()
    todo = hub.journal.add(agent, "todo", "Draw the shop sign", priority="high")
    hub.send("me", agent, "roundtable: command", json.dumps({"action": "todo_done", "id": todo["id"]}), kind="request")
    assert process(orch.cfg, hub, log=lambda s: None) == 1
    closed = next(e for e in hub.journal.entries(agent, agent) if e["id"] == todo["id"])
    assert closed["status"] == "done" and "owner" in closed["closed_note"]
    replies = hub.inbox("me", unread_only=False)
    assert any('"Draw the shop sign" is ticked off' in r["body"] for r in replies)
    assert hub.inbox("me", unread_only=True) == []  # a receipt: arrives already read
    # closing it again, or an id that isn't there, says what to do in plain words
    again = execute(orch.cfg, orch.project.root, {"action": "todo_done", "id": todo["id"]})
    missing = execute(orch.cfg, orch.project.root, {"action": "todo_done", "id": "abc123"})
    empty = execute(orch.cfg, orch.project.root, {"action": "todo_done"})
    for text in (missing, empty):
        assert text.startswith("Couldn't mark it done") and is_trouble(text)
    assert "refresh" in missing.lower() and "refresh" in empty.lower()
    assert again  # closing a closed to-do is harmless: it replies either way


def test_the_owners_own_machines_may_send_commands(tmp_path):
    """A command from the phone's own Roundtable (a seat registered as role: machine) counts as the owner's;
    any other project's seat still doesn't."""
    orch = _orch(tmp_path)
    hub = orch._hub()
    agent = orch._hub_agent()
    hub_yaml = tmp_path / "hub.yaml"
    raw = yaml.safe_load(hub_yaml.read_text(encoding="utf-8"))
    raw["agents"]["phone-abc123"] = {"title": "Phone (Test)", "role": "machine"}
    raw["agents"]["stranger"] = {}
    hub_yaml.write_text(yaml.safe_dump(raw), encoding="utf-8")
    hub = orch._hub()
    hub.refresh_config() if hasattr(hub, "refresh_config") else None
    one = hub.journal.add(agent, "todo", "Water the plants")
    two = hub.journal.add(agent, "todo", "Feed the cat")
    hub.send("stranger", agent, "roundtable: command", json.dumps({"action": "todo_done", "id": two["id"]}), kind="request")
    hub.send("phone-abc123", agent, "roundtable: command", json.dumps({"action": "todo_done", "id": one["id"]}), kind="request")
    assert process(orch.cfg, hub, log=lambda s: None) == 1
    status = {e["id"]: e["status"] for e in hub.journal.entries(agent, agent)}
    assert status[one["id"]] == "done" and status[two["id"]] == "open"


# -- requests the chat sent (1.5.0): chat, chat_turn and chat_card ride along -------------------------------------------
def _chat_request(hub, agent, body):
    hub.send("me", agent, "roundtable: command", json.dumps(body), kind="request")


def test_a_chat_request_whose_card_was_cancelled_is_skipped(tmp_path, monkeypatch):
    from roundtable import chat as chatmod
    from roundtable.harness.orchestrator import Orchestrator

    orch = _orch(tmp_path)
    hub, agent = orch._hub(), orch._hub_agent()
    todo = hub.journal.add(agent, "todo", "Draw the shop sign", priority="high")
    seen = []
    monkeypatch.setattr(chatmod, "cancelled", lambda h, home, cmd: seen.append(cmd) or True)
    monkeypatch.setattr(Orchestrator, "plan_update", lambda self, *a, **k: pytest.fail("a cancelled card ran"))
    _chat_request(hub, agent, {"action": "todo_done", "id": todo["id"], "chat": "bakery", "chat_turn": "t1",
                               "chat_card": "c1"})
    process(orch.cfg, hub, log=lambda s: None)
    assert seen and seen[0]["chat_card"] == "c1"
    still = next(e for e in hub.journal.entries(agent, agent) if e["id"] == todo["id"])
    assert still["status"] != "done"  # never run
    assert hub.inbox(agent, unread_only=True) == []  # and taken off the list, so it isn't tried again
    assert hub.inbox("me", unread_only=False) == []  # no letter back


def test_a_chat_request_answers_in_its_chat_not_in_a_letter(tmp_path, monkeypatch):
    from roundtable import chat as chatmod

    orch = _orch(tmp_path)
    hub, agent = orch._hub(), orch._hub_agent()
    todo = hub.journal.add(agent, "todo", "Draw the shop sign", priority="high")
    done = []
    monkeypatch.setattr(chatmod, "cancelled", lambda h, home, cmd: False)
    monkeypatch.setattr(chatmod, "command_done", lambda h, home, cmd, text, ok=True: done.append((cmd, text, ok)) or True)
    _chat_request(hub, agent, {"action": "todo_done", "id": todo["id"], "chat": "bakery", "chat_turn": "t1"})
    assert process(orch.cfg, hub, log=lambda s: None) == 1
    assert done and '"Draw the shop sign" is ticked off' in done[0][1] and done[0][2] is True
    assert hub.inbox("me", unread_only=False) == []  # the answer went into the chat


def test_a_chat_request_s_extra_keys_never_reach_the_action_and_at_most_caps_it(tmp_path, monkeypatch):
    from roundtable.harness import slash
    from roundtable.harness.orchestrator import Orchestrator

    orch = _orch(tmp_path)
    got, caps = {}, []
    monkeypatch.setattr(Orchestrator, "plan_update", lambda self, action, **kw: got.update(kw) or {"pending": []})
    real = slash.cap_budget
    monkeypatch.setattr(slash, "cap_budget", lambda o, cap: caps.append(cap) or real(o, cap))
    execute(orch.cfg, orch.project.root, {"action": "choose", "decision": "D1", "option": "b", "chat": "bakery",
                                          "chat_turn": "t1", "chat_card": "c1", "max_cost_usd": 2})
    assert got == {"decision": "D1", "option": "b"} and caps == [2.0]
    built = []
    monkeypatch.setattr(slash, "build_project", lambda o, goal="", cap=None: built.append(goal) or "done")
    text = execute(orch.cfg, orch.project.root, {"action": "build", "goal": "a shop page"})
    assert text == "The run ended as: done." and built == ["a shop page"]
