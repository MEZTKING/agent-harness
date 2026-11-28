"""A follow-up to one task (wave 8, DS-31): ask its builder (read-only, priced first, charged), or ask for a change
(a new task that depends on it), or steer it while it builds."""

from __future__ import annotations

import json

import pytest

from roundtable.harness.followstage import FollowError, FollowStage, follow_ups
from roundtable.harness.orchestrator import Orchestrator
from roundtable.harness.tools import READ_ONLY

from .test_harness import make
from .test_slash import chat_app, wait  # noqa: F401 - the shared fixture


class O(*((Orchestrator,) if issubclass(Orchestrator, FollowStage) else (FollowStage, Orchestrator))):
    pass


@pytest.fixture
def done(tmp_path, monkeypatch):
    monkeypatch.setenv("ROUNDTABLE_HOME", str(tmp_path / "home"))
    orch, a, b, _img, _ev = make(tmp_path)
    orch.start("build a bakery site")
    assert orch.run() == "done"
    return O(orch.cfg, orch.project.root), a


def test_asking_is_priced_first_and_nothing_is_spent_until_yes(done):
    orch, a = done
    calls = len(a.calls)
    r = orch.follow_up("T1", "why print and not log?", "ask")
    assert r["confirm"].startswith("Asking the model that built T1 costs about $") and r["estimate"]["model"] == "a/coder"
    assert len(a.calls) == calls and follow_ups(orch.project.root, "T1") == []


def test_an_ask_has_no_write_tool_and_is_charged_to_the_ledger(done):
    orch, a = done
    spent = orch.project.meta().get("spent_usd", 0)
    r = orch.follow_up("T1", "why print and not log?", "ask", confirmed=True)
    assert r["reply"] == "Final report: all done." and r["cost_usd"] > 0
    last = a.calls[-1]
    tools = {t.name for t in last["tools"]}
    assert tools <= set(READ_ONLY) | {"expand_output"} and "write_file" not in tools and "run_command" not in tools
    assert "# The task\n[T1] hello module" in last["messages"][0]["content"]
    assert "why print and not log?" in last["messages"][0]["content"] and last["model"] == "coder"
    assert orch.project.meta()["spent_usd"] > spent  # counted like any call
    rows = follow_ups(orch.project.root, "T1")
    assert rows[-1]["question"] == "why print and not log?" and rows[-1]["answer"] == "Final report: all done."


def test_a_project_that_doesnt_allow_the_tasks_maker_refuses(done):
    orch, a = done
    (orch.project.root / ".harness" / "project.yaml").write_text("providers_allowed: [b]\n", encoding="utf-8")
    calls = len(a.calls)
    with pytest.raises(FollowError, match="doesn't allow a"):
        orch.follow_up("T1", "what did you do?", "ask", confirmed=True)
    assert len(a.calls) == calls


def test_a_change_becomes_a_small_task_that_depends_on_it(done):
    orch, _ = done
    r = orch.follow_up("T1", "say hello in French too", "change")
    tasks = {t.id: t for t in orch.project.tasks()}
    new = tasks[r["task"]]
    assert r["task"] == "FT1" and new.depends_on == ["T1"] and new.role == "coder" and new.status == "pending"
    assert new.fix_of == "T1" and new.added_by == "owner" and "French" in new.description
    assert orch.project.meta()["status"] == "paused"  # the next run picks it up
    again = orch.follow_up("T1", "and German", "change")
    assert again["task"] == "FT1-2"


def test_a_task_building_now_is_steered_as_today(done):
    from roundtable import attachments

    orch, _ = done
    tasks = orch.project.tasks()
    tasks[0].status = "running"
    orch.project.save_tasks(tasks)
    r = orch.follow_up("T1", "use bigger letters", "ask")
    assert r["delivered"] == "steer"
    assert attachments.steers(orch.project.root)[-1]["text"] == "use bigger letters"
    assert orch.project.meta()["guidance"][-1]["text"] == "use bigger letters"


def test_wrong_tasks_and_empty_words_say_what_to_do(done):
    orch, _ = done
    with pytest.raises(FollowError, match="isn't in the plan"):
        orch.follow_up("T9", "hi")
    with pytest.raises(FollowError, match="Write your question"):
        orch.follow_up("T1", "  ")
    tasks = orch.project.tasks()
    tasks[0].status = "pending"
    orch.project.save_tasks(tasks)
    with pytest.raises(FollowError, match="hasn't been built yet"):
        orch.follow_up("T1", "how?", "ask")


def test_through_the_app_an_ask_is_a_job_and_the_answer_shows_under_the_task(chat_app):  # noqa: F811
    app, root = chat_app
    p = str(root)
    first = app.dispatch("POST", "/api/follow", {}, {"path": p, "task": "T1", "text": "why?", "mode": "ask"})
    assert first["confirm"]
    r = app.dispatch("POST", "/api/follow", {}, {"path": p, "task": "T1", "text": "why?", "mode": "ask", "confirmed": True})
    assert wait(app, r["job"]).status == "done"
    items = app.dispatch("GET", "/api/follow", {"path": [p], "task": ["T1"]}, {})["items"]
    assert items[-1]["answer"] == "Final report: all done."
    ch = app.dispatch("POST", "/api/follow", {}, {"path": p, "task": "T3", "text": "add a test for French", "mode": "change"})
    assert ch["task"] == "FT3"
    assert json.loads((root / ".harness" / "tasks.json").read_text(encoding="utf-8"))[-1]["id"] == "FT3"
