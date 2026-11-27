import asyncio
import json
import subprocess

import pytest
import yaml

from roundtable.core.policy import PolicyError
from roundtable.core.store import GitStore
from roundtable.hub.journal import Journal, JournalError
from roundtable.hub.mcp_server import build_server

from .test_hub import RAW, make_hub


def test_log_close_and_brief(tmp_path):
    hub = make_hub(tmp_path)
    j = hub.journal
    j.add("backend", "done", "set up FastAPI skeleton")
    t1 = j.add("backend", "todo", "add auth to /orders", priority="high")
    t2 = j.add("backend", "todo", "write API docs", priority="low")
    p = j.add("backend", "plan", "move to Postgres in v2")
    j.add("backend", "decision", "use JWT, not sessions: mobile app needs it")
    j.session_end("backend", "built order endpoints; auth is next", ["implement JWT middleware", "test /orders auth"])

    [b] = j.where("backend", "backend")
    assert b["last_session"]["text"].startswith("built order endpoints")
    assert b["last_session"]["next"] == ["implement JWT middleware", "test /orders auth"]
    assert [e["id"] for e in b["open_todos"]] == [t1["id"], t2["id"]]  # high priority first
    assert [e["id"] for e in b["open_plans"]] == [p["id"]]

    closed = j.close("backend", t1["id"], note="merged")
    assert closed["status"] == "done"
    [b] = j.where("backend", "backend")
    assert [e["id"] for e in b["open_todos"]] == [t2["id"]]
    assert b["recent_done"][-1]["text"] == "add auth to /orders"  # finishing a todo logs it as done
    j.close("backend", p["id"], dropped=True)
    assert j.where("backend", "backend")[0]["open_plans"] == []

    text = Journal.format_brief(b)
    assert "Last session" in text and "next: implement JWT middleware" in text and "write API docs" in text


def test_validation_and_ownership(tmp_path):
    hub = make_hub(tmp_path)
    j = hub.journal
    with pytest.raises(JournalError):
        j.add("backend", "wish", "x")
    with pytest.raises(JournalError):
        j.add("backend", "todo", "   ")
    note = j.add("backend", "note", "fyi")
    with pytest.raises(JournalError):
        j.close("backend", note["id"])  # notes have no lifecycle
    todo = j.add("backend", "todo", "x")
    with pytest.raises(JournalError):
        j.close("frontend", todo["id"])  # can't close another project's todo
    with pytest.raises(JournalError):
        j.close("backend", "../x")


def test_where_all_projects_respects_policy_and_recency(tmp_path):
    hub = make_hub(tmp_path)
    hub.journal.add("frontend", "todo", "fix navbar")
    hub.journal.add("secret", "todo", "classified")
    hub.journal.add("backend", "done", "latest thing")
    briefs = hub.journal.where("backend")
    assert [b["agent"] for b in briefs] == ["backend", "frontend"]  # most recent first, secret hidden
    with pytest.raises(PolicyError):
        hub.journal.where("backend", "secret")
    with pytest.raises(PolicyError):
        hub.journal.entries("frontend", "secret")


def test_status_markdown_is_written(tmp_path):
    hub = make_hub(tmp_path)
    hub.journal.add("backend", "todo", "add auth", priority="high")
    hub.journal.add("backend", "plan", "v2: Postgres")
    hub.journal.session_end("backend", "orders done", ["auth next"])
    md = (tmp_path / "data/status/backend.md").read_text(encoding="utf-8")
    assert md.startswith("# backend (me/api)")
    assert "## Where we left off" in md and "- [ ] auth next" in md
    assert "- [ ] **(high)** add auth" in md and "## Future plans" in md


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_journal_shared_across_sessions_via_git(tmp_path):
    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    laptop = make_hub(tmp_path, store=GitStore(tmp_path / "laptop", remote=str(remote), sync_interval=0))
    cloud = make_hub(tmp_path, store=GitStore(tmp_path / "cloud", remote=str(remote), sync_interval=0))

    laptop.journal.session_end("backend", "half-way through auth", ["finish JWT refresh tokens"])
    t = laptop.journal.add("backend", "todo", "rotate secrets")
    [b] = cloud.journal.where("backend", "backend")  # another session, another machine
    assert b["last_session"]["next"] == ["finish JWT refresh tokens"]
    cloud.journal.close("backend", t["id"])
    assert laptop.journal.where("backend", "backend")[0]["open_todos"] == []
    log = subprocess.run(["git", "log", "--oneline"], cwd=remote, capture_output=True, text=True).stdout
    assert "journal(backend) session" in log


def test_cli_journal_commands(tmp_path, monkeypatch, capsys):
    from roundtable.cli import main

    cfg = tmp_path / "hub.yaml"
    cfg.write_text(yaml.safe_dump(RAW), encoding="utf-8")
    monkeypatch.setenv("HUB_CONFIG", str(cfg))
    monkeypatch.setenv("HUB_AGENT", "backend")
    main(["log", "todo", "ship v1", "--priority", "high"])
    main(["log", "plan", "mobile app"])
    main(["session", "wired up payments", "--next", "test refunds"])
    capsys.readouterr()
    main(["todo", "--plans"])
    out = capsys.readouterr().out
    assert "ship v1" in out and "mobile app" in out
    todo_id = out.split("[", 1)[1].split("]", 1)[0]
    main(["close", todo_id])
    main(["where"])
    out = capsys.readouterr().out
    assert "wired up payments" in out and "next: test refunds" in out and "ship v1" in out  # now in recently done
    main(["history", "--kind", "session"])
    assert "wired up payments" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["close", "nope42"])


def _text(result):
    if isinstance(result, tuple):
        result = result[0]
    if hasattr(result, "content"):
        result = result.content
    return result[0].text


def test_mcp_journal_tools(tmp_path):
    hub = make_hub(tmp_path)
    server = build_server(hub, "backend")

    async def go():
        names = {t.name for t in await server.list_tools()}
        assert {"hub_where", "hub_log", "hub_todos", "hub_close", "hub_session_end"} <= names
        assert "No journal entries" in _text(await server.call_tool("hub_where", {}))
        logged = json.loads(_text(await server.call_tool("hub_log", {"kind": "todo", "text": "add tests"})))
        todos = json.loads(_text(await server.call_tool("hub_todos", {})))
        assert todos[0]["id"] == logged["id"]
        await server.call_tool("hub_close", {"entry_id": logged["id"]})
        await server.call_tool("hub_session_end", {"summary": "added tests", "next_steps": ["deploy"]})
        where = _text(await server.call_tool("hub_where", {}))
        assert "added tests" in where and "next: deploy" in where
        hub.journal.add("frontend", "todo", "navbar")
        assert "frontend" in _text(await server.call_tool("hub_where", {"agent_id": "all"}))

    asyncio.run(go())


def test_harness_writes_project_history(tmp_path):
    from roundtable.harness.orchestrator import Orchestrator
    from roundtable.providers.base import ProviderError

    from .test_harness import RAW as HRAW, Brain, make as make_harness

    hub_cfg = tmp_path / "hub.yaml"
    hub_raw = json.loads(json.dumps(RAW))
    hub_raw["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
    hub_raw["agents"]["harness"] = {"description": "project runner"}
    hub_cfg.write_text(yaml.safe_dump(hub_raw), encoding="utf-8")
    raw = json.loads(json.dumps(HRAW))
    raw["hub"] = {"config": str(hub_cfg), "agent": "harness"}

    brain = Brain()
    broken = {"on": True}

    def flaky(model, system, messages, tools):
        if model in ("coder", "coder2") and broken["on"]:
            raise ProviderError("down")
        return brain(model, system, messages, tools)

    orch, *_ = make_harness(tmp_path, raw=raw, brain=flaky, b_brain=flaky)
    orch.start("bakery site")
    assert orch.run() == "blocked"
    assert orch.run() == "blocked"  # rerun must not duplicate the todo
    hub = orch._hub()
    [b] = hub.journal.where("harness", "harness")
    assert [e["text"] for e in b["open_todos"]] == ["proj: Task T1 “hello module” didn't pass: try it again or skip it"]
    assert b["open_todos"][0]["details"] == f"roundtable status {orch.project.root}"
    assert b["open_plans"][0]["text"] == "proj: goal: bakery site"

    broken["on"] = False
    orch.retry("T1")
    assert orch.run() == "done"
    [b] = hub.journal.where("harness", "harness")
    assert b["open_todos"] == [] and b["open_plans"] == []
    assert "harness finished goal 'bakery site'" in b["last_session"]["text"]
    steps = b["last_session"]["next"]
    assert steps == ["Look at what was built and say what you think",
                     "Rate the tasks in the app (good or bad), so the harness learns"]
    assert not any("/" in s or "roundtable " in s for s in steps)  # no paths or commands for the owner
    assert "roundtable feedback" in b["last_session"]["details"]
    done = [e["text"] for e in hub.journal.entries("harness", kinds=["done"])]
    assert "proj: [T1] hello module" in done and "proj: [T3] tests" in done


def test_finished_goal_leaves_future_plans(tmp_path):
    """The plan entry closes even when the project got its own hub project between planning and finishing
    (it was written to the shared harness journal), and a stray "goal: …" entry for the same goal closes too."""
    from .test_harness import RAW as HRAW, make as make_harness

    hub_cfg = tmp_path / "hub.yaml"
    hub_raw = json.loads(json.dumps(RAW))
    hub_raw["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
    hub_raw["agents"]["harness"] = {"description": "project runner"}
    hub_cfg.write_text(yaml.safe_dump(hub_raw), encoding="utf-8")
    raw = json.loads(json.dumps(HRAW))
    raw["hub"] = {"config": str(hub_cfg), "agent": "harness"}

    orch, *_ = make_harness(tmp_path, raw=raw)
    orch.start("bakery site", require_approval=True)
    assert orch.run() == "awaiting_approval"
    [b] = orch._hub().journal.where("harness", "harness")
    assert b["open_plans"][0]["text"] == "proj: goal: bakery site"

    hub_raw["agents"]["proj"] = {"description": "the bakery"}  # the project joins the hub as itself
    hub_cfg.write_text(yaml.safe_dump(hub_raw), encoding="utf-8")
    orch._hub_cache = None
    hub = orch._hub()
    assert orch._hub_agent() == "proj"
    hub.journal.add("proj", "plan", "goal: bakery site")  # e.g. written by another session
    hub.journal.add("proj", "plan", "a shop later")  # someone else's plan stays

    orch.approve()
    assert orch.run() == "done"
    assert hub.journal.where("harness", "harness")[0]["open_plans"] == []
    assert [e["text"] for e in hub.journal.where("proj", "proj")[0]["open_plans"]] == ["a shop later"]
    assert orch.project.meta()["journal_plans"] == []
