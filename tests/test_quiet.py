"""Working, resting, waiting or gone quiet (wave 8, p1-board: MD-18, MD-19), and the one card for a quiet run.

Made-up event logs in tmp_path; nothing runs a model.
"""

import json
import time
from datetime import datetime, timezone

from roundtable.harness import boardstage, livecmd, quiet
from roundtable.harness.orchestrator import Project

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc).timestamp()


def at(minutes_ago: float) -> str:
    return datetime.fromtimestamp(NOW - minutes_ago * 60, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def project(tmp_path, status="running", last_minutes_ago=1.0, **meta):
    root = tmp_path / "proj"
    p = Project(root)
    p.save_meta({"goals": ["a made-up shop"], "status": status, **meta})
    p.save_tasks([])
    if last_minutes_ago is not None:
        p.append("events.jsonl", {"at": at(last_minutes_ago + 5), "event": "goal"})
        p.append("events.jsonl", {"at": at(last_minutes_ago), "event": "tool_call", "task": "T1"})
    return root


def test_working_resting_waiting_and_quiet(tmp_path):
    assert quiet.state(project(tmp_path / "a"), NOW)["state"] == "working"
    assert quiet.state(project(tmp_path / "b", status="done"), NOW) == {
        "state": "resting", "word": "Resting", "line": "Finished", "last_at": at(1.0), "quiet_for": 60}
    assert quiet.state(project(tmp_path / "c", status="awaiting_approval"), NOW)["state"] == "waiting"
    assert quiet.state(project(tmp_path / "d", status="blocked"), NOW)["word"] == "Waiting for you"
    assert quiet.state(project(tmp_path / "e", status="paused", pause="money"), NOW)["state"] == "waiting"
    assert quiet.state(project(tmp_path / "f", status="paused", pause="elsewhere"), NOW)["state"] == "resting"
    q = quiet.state(project(tmp_path / "g", last_minutes_ago=30), NOW)
    assert q["state"] == "quiet" and q["line"] == "Nothing has happened for 30 minutes"
    assert quiet.state(project(tmp_path / "h", last_minutes_ago=30), NOW, busy=False)["line"].endswith("it may have stopped")


def test_quiet_waits_past_the_breakers_limit_plus_a_margin(tmp_path):
    limit = 5.0 + quiet.MARGIN_MINUTES  # the breaker's no-progress default plus the margin
    assert quiet.state(project(tmp_path / "a", last_minutes_ago=limit - 0.5), NOW)["state"] == "working"
    assert quiet.state(project(tmp_path / "b", last_minutes_ago=limit + 0.5), NOW)["state"] == "quiet"


def test_a_running_command_is_working_not_quiet(tmp_path):
    root = project(tmp_path, last_minutes_ago=60)
    reg = livecmd.live_dir(root)
    reg.mkdir(parents=True, exist_ok=True)
    (reg / livecmd.REGISTRY).write_text(json.dumps({"commands": [{"task": "T1", "pid": 1, "until": NOW + 600}]}), encoding="utf-8")
    assert livecmd.running(root)
    assert quiet.state(root, NOW)["state"] == "working"
    assert quiet.state(root, NOW + 3600)["state"] == "quiet"  # past its own timeout: not counted


def test_no_events_at_all(tmp_path):
    assert quiet.state(project(tmp_path, status="", last_minutes_ago=None), NOW)["state"] == "resting"


class Orch:
    def __init__(self, root):
        self.project = Project(root)
        self.cfg = None
        self.steered = []

    def steer(self, text):
        self.steered.append(text)


def test_one_card_for_a_quiet_run_and_wait_settles_this_spell_only(tmp_path):
    root = project(tmp_path, last_minutes_ago=30)
    o = Orch(root)
    card = quiet.quiet_ask(o, now=NOW)
    assert card["id"] == "quiet" and card["recommended"] == "wait" and [x["id"] for x in card["options"]] == ["wait", "stop"]
    assert not any(x.get("confirm") for x in card["options"])
    assert quiet.quiet_ask(o, now=NOW)["stamp"] == card["stamp"]  # the same spell: the same one card
    r = quiet.apply_quiet(o, card, ["wait"], "")
    assert r["then"] is None and "asked again" in r["reply"]
    assert quiet.quiet_ask(o, now=NOW) is None
    o.project.append("events.jsonl", {"at": at(0), "event": "tool_call"})  # it moved, then went quiet again
    again = quiet.quiet_ask(o, now=NOW + 40 * 60)
    assert again and again["stamp"] != card["stamp"]


def test_stop_it_pauses_before_the_next_task_and_never_by_itself(tmp_path):
    root = project(tmp_path, last_minutes_ago=30)
    o = Orch(root)
    assert quiet.quiet_ask(o, now=NOW)  # asking changes nothing
    assert o.project.meta()["status"] == "running" and not (root / ".harness" / boardstage.STOP_REQUEST).exists()
    r = quiet.apply_quiet(o, quiet.quiet_ask(o, now=NOW), ["stop"], "")
    assert "pauses before its next task" in r["reply"]
    assert (root / ".harness" / boardstage.STOP_REQUEST).is_file()
    assert o.project.meta()["status"] == "paused" and o.project.meta()["pause"] == "owner_stop"


def test_no_card_when_not_quiet(tmp_path):
    assert quiet.quiet_ask(Orch(project(tmp_path)), now=NOW) is None
    assert quiet.quiet_ask(Orch(project(tmp_path / "x", status="done", last_minutes_ago=300)), now=NOW) is None


def test_last_event_reads_only_the_end_of_a_long_log(tmp_path):
    root = project(tmp_path, last_minutes_ago=2)
    with open(root / ".harness" / "events.jsonl", "a", encoding="utf-8") as f:
        f.write("not json\n")
    assert quiet.last_event_at(root) == at(2)
    assert quiet.last_event_at(tmp_path / "nowhere") == ""
    assert time.time()  # (the clock is passed in; nothing here depends on it)
