import json
import subprocess

import pytest
import yaml

from roundtable.core.store import GitStore
from roundtable.providers.base import ProviderError
from roundtable.providers.scripted import reply
from roundtable.ui.roundtable import AutoSync, activity, build
from roundtable.ui.server import UIApp

from .test_harness import RAW as HARNESS_RAW, Brain, make as make_harness, tool_names
from .test_hub import RAW as HUB_RAW


class Recorder(Brain):
    """Brain that remembers every worker prompt, and answers 'ask' questions."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.worker_prompts = []

    def __call__(self, model, system, messages, tools):
        names = tool_names(tools)
        if "finish_task" in names and messages[-1]["role"] == "user":
            self.worker_prompts.append(messages[0]["content"])
        if not names - {"read_file", "list_files", "search"} and "orchestrator of this software project" in system:
            return reply("T1 failed because the provider was down; T3 waits on it.")
        return super().__call__(model, system, messages, tools)


@pytest.fixture
def setup(tmp_path):
    hub_raw = json.loads(json.dumps(HUB_RAW))
    hub_raw["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
    hub_raw["agents"]["proj"] = {"description": "the harness project"}  # same name as the run folder below
    hub_raw["rules"].append({"from": "*", "to": "*", "allow": ["read_card", "message"]})
    (tmp_path / "hub.yaml").write_text(yaml.safe_dump(hub_raw))
    brain = Recorder()
    orch, *_ = make_harness(tmp_path, brain=brain)  # project folder: tmp_path/"proj"
    cfg = orch.cfg
    cfg.lab_dir = tmp_path / "lab"
    app = UIApp(str(tmp_path / "hub.yaml"), "missing.yaml", agent="backend")
    app.cfg = lambda: cfg
    return app, orch, brain, cfg


def seat(data, sid):
    return next(s for s in data["seats"] if s["id"] == sid)


def test_runs_and_hub_projects_merge_into_seats_with_live_status(setup):
    app, orch, brain, cfg = setup
    app.hub.journal.add("proj", "todo", "check the logo colours", priority="high")
    app.hub.journal.add("frontend", "session", "navbar done")
    orch._register_with_lab()
    orch.start("bakery site", require_approval=True)
    assert orch.run() == "awaiting_approval"

    data = build(app)
    s = seat(data, "proj")
    assert s["kind"] == "both" and s["status"] == "waiting" and s["actions"] == ["approve"]
    assert s["open_todos"] == 1 and s["high"] == 1
    assert data["needs_you"][0]["kind"] == "run" and data["needs_you"][0]["actions"] == ["approve"]
    assert any(n["kind"] == "todo" and "logo" in n["text"] for n in data["needs_you"])
    assert seat(data, "frontend")["status"] == "idle"
    assert [x["status"] for x in data["seats"]][0] == "waiting"  # attention first (nothing running)

    orch.approve()
    assert orch.run() == "done"
    data = build(app)
    s = seat(data, "proj")
    assert s["status"] == "done" and s["progress"] == {"done": 3, "total": 3}
    assert not [n for n in data["needs_you"] if n["kind"] == "run"]


def test_failed_task_needs_you_with_retry(setup, tmp_path):
    app, orch, brain, cfg = setup
    broken = {"on": True}

    def flaky(model, system, messages, tools):
        if model in ("coder", "coder2") and broken["on"]:
            raise ProviderError("down")
        return brain(model, system, messages, tools)

    cfg._instances["a"].script = flaky
    cfg._instances["b"].script = flaky
    orch._register_with_lab()
    orch.start("goal")
    assert orch.run() == "blocked"
    s = seat(build(app), "proj")
    assert s["status"] == "waiting" and s["actions"] == ["retry", "skip"] and s["failed_task"] == "T1"


def test_activity_feed_is_newest_first_across_runs_and_journal(setup):
    app, orch, brain, cfg = setup
    orch._register_with_lab()
    orch.start("goal")
    orch.run()
    app.hub.journal.add("frontend", "done", "footer shipped")
    feed = activity(app)
    assert feed == sorted(feed, key=lambda i: i["at"], reverse=True)
    kinds = {i["kind"] for i in feed}
    assert {"task_start", "review", "task_end", "journal:done"} <= kinds
    assert any("proj" == i["project"] and "write_file" in i["text"] for i in feed)


def test_steering_reaches_every_later_task_and_is_in_chat(setup):
    app, orch, brain, cfg = setup
    orch._register_with_lab()
    orch.start("goal", require_approval=True)
    orch.run()
    r = app.dispatch("POST", "/api/chat", {}, {"path": str(orch.project.root), "steer": True,
                                               "message": "Use 32x32 sprites from now on"})
    assert "every remaining task" in r["reply"]
    orch.approve()
    orch.run()
    assert brain.worker_prompts and all("Use 32x32 sprites from now on" in p for p in brain.worker_prompts)
    history = app.dispatch("GET", "/api/chat", {"path": [str(orch.project.root)]}, {})
    assert [(c["who"], c["steer"]) for c in history] == [("owner", True), ("orchestrator", True)]


def test_ask_the_orchestrator(setup):
    app, orch, brain, cfg = setup
    orch._register_with_lab()
    orch.start("goal")
    r = app.dispatch("POST", "/api/chat", {}, {"path": str(orch.project.root), "message": "why did T1 fail?"})
    assert "provider was down" in r["reply"]
    history = orch.chat_history()
    assert history[-2]["text"] == "why did T1 fail?" and history[-1]["who"] == "orchestrator"
    with pytest.raises(Exception):
        app.dispatch("POST", "/api/chat", {}, {"path": "/not/a/project", "message": "hi"})


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_auto_sync_picks_up_other_sessions(tmp_path):
    from .test_hub import make_hub

    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    other = make_hub(tmp_path, store=GitStore(tmp_path / "other", remote=str(remote), sync_interval=0))
    other.update_card("backend", status="v1")
    hub_raw = json.loads(json.dumps(HUB_RAW))
    hub_raw["storage"] = {"type": "git", "path": str(tmp_path / "mine"), "remote": str(remote),
                          "sync_interval": 3600}
    (tmp_path / "hub.yaml").write_text(yaml.safe_dump(hub_raw))
    app = UIApp(str(tmp_path / "hub.yaml"), "missing.yaml", agent="backend")
    app.hub.store.sync(force=True)
    other.update_card("backend", status="v2")  # another session writes
    assert app.hub.get_card("frontend", "backend")["status"] == "v1"  # read window still open
    AutoSync(app).tick()  # the background sync fires
    assert app.hub.get_card("frontend", "backend")["status"] == "v2" and app.last_auto_sync
    _git("remote", "set-url", "origin", str(tmp_path / "gone.git"), cwd=tmp_path / "mine")
    AutoSync(app).tick()  # offline: recorded, nothing breaks
    assert app.auto_sync_error
