"""Watch: where a task's time went, how full its context is, the files it changed, and several tasks at once.

Every log here is made up."""

import json

from roundtable.harness import session as S


def ev(event, **kw):
    return {"at": kw.pop("at", "2026-11-27T10:00:00Z"), "event": event, **kw}


def turn(task, ms=None, **kw):
    row = ev("model_turn", task=task, model=kw.pop("model", "deepseek/deepseek-chat"), role=kw.pop("role", "coder"),
             text=kw.pop("text", ""), cost=kw.pop("cost", 0.001), **kw)
    if ms is not None:
        row["ms"] = ms
    return row


def tool(task, name="read_file", ms=None, **kw):
    row = ev("tool_call", task=task, tool=name, args=kw.pop("args", {"path": "a.py"}), error=kw.pop("error", False),
             result=kw.pop("result", "ok"), **kw)
    if ms is not None:
        row["ms"] = ms
    return row


def parts(t):
    return {p["key"]: p["ms"] for p in (t["time"] or {}).get("parts", [])}


def test_the_split_of_one_task():
    rows = [ev("task_start", task="T1", title="Make the page", role="coder"),
            turn("T1", ms=3000, first_ms=1200),
            tool("T1", "read_file", ms=40),
            turn("T1", ms=2000, first_ms=500),
            tool("T1", "run_command", ms=65_000, waited_ms=60_000, args={"command": "npm test"},
                 output="exit code: 0\nok"),
            ev("agent_done", task="T1", model="deepseek/deepseek-chat", role="coder", model_ms=5000, tool_ms=65_040,
               other_ms=300),
            ev("task_end", task="T1", status="done")]
    (t,) = S.tasks_from_events(rows)
    assert parts(t) == {"first": 1700, "writing": 3300, "tools": 5040, "you": 60_000, "other": 300}
    assert [p["key"] for p in t["time"]["parts"]] == ["first", "writing", "tools", "you", "other"]
    assert t["time"]["total_ms"] == 70_340
    assert t["time"]["unrecorded"] == 0


def test_without_first_word_the_model_is_one_part():
    rows = [ev("task_start", task="T1", title="x"), turn("T1", ms=4000), tool("T1", ms=100)]
    (t,) = S.tasks_from_events(rows)
    assert parts(t) == {"model": 4000, "tools": 100}


def test_wait_only_in_agent_done_moves_out_of_tools():
    rows = [ev("task_start", task="T1", title="x"), turn("T1", ms=1000),
            tool("T1", "run_command", ms=30_000, args={"command": "rm -rf build"}, output="exit code: 0"),
            ev("agent_done", task="T1", model_ms=1000, tool_ms=30_000, other_ms=0, waited_ms=25_000)]
    (t,) = S.tasks_from_events(rows)
    assert parts(t) == {"model": 1000, "tools": 5000, "you": 25_000}


def test_old_logs_without_times_have_no_bar():
    rows = [ev("task_start", task="T1", title="Old one"), turn("T1", text="Looking"), tool("T1"),
            ev("task_end", task="T1", status="done")]
    (t,) = S.tasks_from_events(rows)
    assert t["time"] is None  # never a bar of zeros
    assert t["context"] is None
    assert t["steps"][0]["kind"] == "say"
    assert t["status"] == "done"


def test_untimed_events_are_left_out_not_zero():
    rows = [ev("task_start", task="T1", title="x"), turn("T1"), turn("T1", ms=2000), tool("T1")]
    (t,) = S.tasks_from_events(rows)
    assert parts(t) == {"model": 2000}
    assert t["time"]["unrecorded"] == 2


def test_context_and_cache():
    rows = [ev("task_start", task="T1", title="x"),
            turn("T1", ms=10, input_tokens=1000, cache_read_tokens=0, cache_write_tokens=0, output_tokens=200),
            turn("T1", ms=10, input_tokens=400, cache_read_tokens=3600, output_tokens=100),
            turn("T1", ms=10, role="reviewer", model="anthropic/claude-x", input_tokens=9000, output_tokens=50)]
    (t,) = S.tasks_from_events(rows)
    c = t["context"]
    assert c["used"] == 400 + 3600 + 100  # the worker's newest call, not the reviewer's
    assert c["window"] == 128_000
    assert c["share"] == round(4100 / 128_000, 3)
    assert c["cache_hit"] == round(3600 / (1000 + 4000 + 9000), 3)


def test_context_window_from_the_event_or_unknown():
    rows = [ev("task_start", task="T1", title="x"),
            turn("T1", model="custom/house-model", input_tokens=5000, output_tokens=10, context_window=10_000)]
    assert S.tasks_from_events(rows)[0]["context"]["share"] == 0.501
    rows[1].pop("context_window")
    c = S.tasks_from_events(rows)[0]["context"]
    assert c["window"] is None and c["share"] is None and c["used"] == 5010


def test_changed_files_folded_into_one_list():
    rows = [ev("task_start", task="T1", title="x"),
            tool("T1", "write_file", args={"path": "a.py"}, change={"diff": "+x", "added": 3, "removed": 0}),
            tool("T1", "edit_file", args={"path": "a.py"}, change={"diff": "-x\n+y", "added": 1, "removed": 1}),
            tool("T1", "edit_file", args={"path": "b.py"}, change={"diff": "", "added": 2, "removed": 5}),
            tool("T1", "edit_file", args={"path": "c.py"}, error=True, result="no such text")]
    (t,) = S.tasks_from_events(rows)
    assert t["changes"] == [{"path": "a.py", "added": 4, "removed": 1, "new": True},
                            {"path": "b.py", "added": 2, "removed": 5, "new": False}]


def test_overlapping_tasks_group_by_id():
    rows = [ev("task_start", task="T1", title="Menu"),
            ev("task_start", task="T2", title="Sounds"),
            turn("T1", ms=1000, text="Making the menu"),
            turn("T2", ms=3000, text="Adding sounds"),
            tool("T1", "write_file", ms=20, args={"path": "menu.js"}, change={"diff": "+a", "added": 1, "removed": 0}),
            tool("T2", "write_file", ms=30, args={"path": "sfx.js"}, change={"diff": "+b", "added": 2, "removed": 0}),
            ev("task_end", task="T1", status="done"),
            turn("T2", ms=500, text="Still on the sounds"),
            ev("task_start", task="T3", title="Help page")]
    tasks = S.tasks_from_events(rows)
    by = {t["id"]: t for t in tasks}
    assert [s["text"] for s in by["T1"]["steps"] if s["kind"] == "say"] == ["Making the menu"]
    assert [s["text"] for s in by["T2"]["steps"] if s["kind"] == "say"] == ["Adding sounds", "Still on the sounds"]
    assert [c["path"] for c in by["T1"]["changes"]] == ["menu.js"]
    assert [c["path"] for c in by["T2"]["changes"]] == ["sfx.js"]
    assert parts(by["T1"]) == {"model": 1000, "tools": 20}
    assert parts(by["T2"]) == {"model": 3500, "tools": 30}
    assert by["T1"]["status"] == "done" and by["T2"]["status"] == "running"
    assert S.running(tasks) == ["T2", "T3"]
    assert by["T2"]["now"] == "Still on the sounds"
    assert by["T3"]["now"] == "Starting"


def test_a_task_run_again_counts_only_its_newest_run():
    rows = [ev("task_start", task="T1", title="x"), turn("T1", ms=100),
            ev("task_end", task="T1", status="paused"),
            ev("task_start", task="T1", title="x"), turn("T1", ms=700)]
    tasks = S.tasks_from_events(rows)
    assert [parts(t) for t in tasks] == [{"model": 100}, {"model": 700}]
    assert S.running(tasks) == ["T1"]


def test_events_without_a_task_id_go_to_the_latest_task():
    rows = [{"event": "task_start", "task": "T1", "title": "x", "at": "a"},
            {"event": "model_turn", "text": "hello", "role": "coder", "at": "b"},
            {"event": "task_end", "task": "T1", "status": "done", "at": "c"},
            {"event": "model_turn", "text": "after the end", "role": "coder", "at": "d"}]
    (t,) = S.tasks_from_events(rows)
    assert [s["text"] for s in t["steps"]] == ["hello"]


def _project(tmp_path, rows):
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "events.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return tmp_path


def test_session_and_phone_show_every_running_task(tmp_path):
    rows = [ev("task_start", task="T1", title="Menu"), ev("task_start", task="T2", title="Sounds"),
            turn("T1", ms=1000, text="menu", input_tokens=100, output_tokens=5),
            turn("T2", ms=2000, text="sounds")]
    root = _project(tmp_path, rows)
    v = S.session(root)
    assert v["running"] == ["T1", "T2"]
    assert v["tasks"][0]["time"]["parts"][0]["ms"] == 1000
    h = S.hub_session(root, "made-up")
    assert [t["id"] for t in h["tasks"]] == ["T1", "T2"]
    assert h["task"]["id"] == "T2"  # older phones: the latest started
    assert h["tasks"][0]["context"]["used"] == 105
    assert h["tasks"][1]["now"] == "sounds"


def test_phone_with_nothing_running_gets_the_latest(tmp_path):
    root = _project(tmp_path, [ev("task_start", task="T1", title="Menu"), ev("task_end", task="T1", status="done")])
    h = S.hub_session(root, "made-up")
    assert [t["id"] for t in h["tasks"]] == ["T1"] and h["task"]["status"] == "done"
