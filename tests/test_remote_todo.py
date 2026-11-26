import json

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
