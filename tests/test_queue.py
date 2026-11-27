"""The queue (wave 8, MD-76): the "Next task" notes no task has read yet, listed with Send now, change, remove."""

from __future__ import annotations

import pytest

from roundtable import attachments
from roundtable.harness.orchestrator import Orchestrator
from roundtable.ui import chatapi

from .test_slash import chat_app  # noqa: F401 - the shared fixture


def _notes(app, root, *texts, at="2999-01-01T00:00:00Z"):
    orch = Orchestrator(app.cfg(), root)
    meta = orch.project.meta()
    meta["guidance"] = [{"at": "2000-01-01T00:00:00Z", "text": "an old note every task has read"}] + [
        {"at": at, "text": t} for t in texts]
    orch.project.save_meta(meta)
    return orch


def q(app, root):
    return app.dispatch("GET", "/api/queue", {"path": [str(root)]}, {})


def post(app, root, **b):
    return app.dispatch("POST", "/api/queue", {}, {"path": str(root), **b})


def test_only_notes_no_task_has_read_are_listed(chat_app):  # noqa: F811
    app, root = chat_app
    _notes(app, root, "use bigger buttons", "and a darker header")
    got = q(app, root)
    assert [i["text"] for i in got["items"]] == ["use bigger buttons", "and a darker header"] and not got["running"]


def test_a_note_the_planner_wrote_through_steer_waits_until_the_next_task(chat_app):  # noqa: F811
    app, root = chat_app
    Orchestrator(app.cfg(), root).steer("round corners please")
    assert [i["text"] for i in q(app, root)["items"]] == ["round corners please"]


def test_change_and_remove(chat_app):  # noqa: F811
    app, root = chat_app
    orch = _notes(app, root, "use bigger buttons", "and a darker header")
    first, second = q(app, root)["items"]
    r = post(app, root, action="change", id=first["id"], text="use much bigger buttons")
    assert r["reply"].startswith("Changed") and r["items"][0]["text"] == "use much bigger buttons"
    r = post(app, root, action="remove", id=second["id"])
    assert [i["text"] for i in r["items"]] == ["use much bigger buttons"]
    texts = [g["text"] for g in orch.project.meta()["guidance"]]
    assert texts == ["an old note every task has read", "use much bigger buttons"]  # what the next task reads


def test_send_now_reaches_the_task_working_now(chat_app, monkeypatch):  # noqa: F811
    app, root = chat_app
    _notes(app, root, "stop using tables")
    item = q(app, root)["items"][0]
    r = post(app, root, action="send_now", id=item["id"])
    assert "Nothing is working" in r["reply"] and r["items"]  # nothing running: it simply waits
    monkeypatch.setattr(app, "_busy", lambda path: True)
    r = post(app, root, action="send_now", id=item["id"])
    assert r["reply"].startswith("Sent to the task working now") and r["items"] == []
    assert attachments.steers(root)[-1]["text"] == "stop using tables"


def test_a_note_already_read_cant_be_changed(chat_app):  # noqa: F811
    from roundtable.ui.server import ApiError

    app, root = chat_app
    _notes(app, root)
    old = chatapi._note_id({"at": "2000-01-01T00:00:00Z", "text": "an old note every task has read"})
    with pytest.raises(ApiError) as e:
        post(app, root, action="remove", id=old)
    assert e.value.status == 409
    _notes(app, root, "x")
    nid = q(app, root)["items"][0]["id"]
    with pytest.raises(ApiError, match="new words"):
        post(app, root, action="change", id=nid, text="  ")
    with pytest.raises(ApiError, match="Say change"):
        post(app, root, action="explode", id=nid)
