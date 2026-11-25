import io
import json
import subprocess

import pytest
import yaml

from roundtable.connect import (add_agent_to_yaml, agent_id_for, connect, main as connect_main, repo_slug,
                                run_hook, transcript_summary, write_claude_settings)
from roundtable.core.config import find_config
from roundtable.hub.service import Hub
from roundtable.core.config import load_config

HUB_YAML = """\
# my hub (comments must survive)
storage:
  type: git
  path: .
  branch: main

agents:
  me:
    description: My own notes
  other:
    description: Another repo   # trailing comment

# rules are checked in order
rules:
  - {from: "*", to: "*", allow: [read_card, message]}
"""


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A hub repo (git, with a bare remote) and a project repo next to it."""
    monkeypatch.setenv("ROUNDTABLE_HOME", str(tmp_path / "apphome"))
    monkeypatch.delenv("HUB_CONFIG", raising=False)
    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    hub_dir = tmp_path / "agent-hub-data"
    _git("clone", str(remote), str(hub_dir), cwd=tmp_path)
    (hub_dir / "hub.yaml").write_text(HUB_YAML)
    _git("add", "hub.yaml", cwd=hub_dir)
    _git("commit", "-m", "hub", cwd=hub_dir)
    _git("push", "origin", "HEAD:main", cwd=hub_dir)
    repo = tmp_path / "My Game"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)
    _git("remote", "add", "origin", "https://github.com/someone/my-game.git", cwd=repo)
    (repo / "src").mkdir()
    return tmp_path, hub_dir, repo, remote


def test_agent_ids_and_repo_slugs(tmp_path):
    assert agent_id_for("My Game!") == "my-game"
    assert agent_id_for("agent-harness") == "agent-harness"
    with pytest.raises(ValueError):
        agent_id_for("!!!")
    _git("init", cwd=tmp_path)
    for url, slug in [("git@github.com:o/r.git", "o/r"), ("https://github.com/o/r", "o/r"),
                      ("http://local_proxy@127.0.0.1:1234/git/O/r-x", "O/r-x")]:
        subprocess.run(["git", "remote", "remove", "origin"], cwd=tmp_path, capture_output=True)
        _git("remote", "add", "origin", url, cwd=tmp_path)
        assert repo_slug(tmp_path) == slug


def test_adding_an_agent_keeps_comments_and_layout():
    new = add_agent_to_yaml(HUB_YAML, "my-game", "someone/my-game", 'a "quoted" game')
    assert "# my hub (comments must survive)" in new and "# trailing comment" in new
    raw = yaml.safe_load(new)
    assert raw["agents"]["my-game"] == {"repo": "someone/my-game", "description": 'a "quoted" game'}
    assert list(raw["agents"]) == ["me", "other", "my-game"]
    assert new.index("my-game:") < new.index("# rules are checked in order")
    assert yaml.safe_load(add_agent_to_yaml("storage: {type: file}\nagents: {}\n", "x"))["agents"]["x"]
    assert "x" in yaml.safe_load(add_agent_to_yaml("storage: {type: file}\n", "x"))["agents"]


def test_connect_registers_pushes_and_writes_claude_files(world, monkeypatch):
    tmp_path, hub_dir, repo, remote = world
    monkeypatch.chdir(repo / "src")  # anywhere inside the repo; the hub is found next to it
    r = connect()
    assert r["agent"] == "my-game" and r["added_to_hub"] and r["repo"] == str(repo)
    assert r["hub_config"] == str(hub_dir / "hub.yaml")
    # pushed: a fresh clone sees the new project
    fresh = tmp_path / "fresh"
    _git("clone", str(remote), str(fresh), cwd=tmp_path)
    assert yaml.safe_load((fresh / "hub.yaml").read_text())["agents"]["my-game"]["repo"] == "someone/my-game"
    mcp = json.loads((repo / ".mcp.json").read_text())["mcpServers"]["roundtable"]
    assert mcp["command"] == "roundtable" and mcp["args"] == ["mcp", "--agent", "my-game"] and "env" not in mcp
    s = json.loads((repo / ".claude" / "settings.json").read_text())
    assert s["enabledMcpjsonServers"] == ["roundtable"] and "mcp__roundtable" in s["permissions"]["allow"]
    assert [g["hooks"][0]["command"] for g in s["hooks"]["SessionStart"]] == [
        "roundtable hook session-start --agent my-game"]
    # elsewhere on this computer, the hub connect used is found again without HUB_CONFIG
    monkeypatch.chdir(tmp_path)
    assert find_config() == hub_dir / "hub.yaml"
    # connecting again changes nothing in the hub and doesn't duplicate anything
    monkeypatch.chdir(repo)
    assert connect()["added_to_hub"] is False
    s2 = json.loads((repo / ".claude" / "settings.json").read_text())
    assert s2 == s


def test_settings_merge_keeps_other_hooks_and_settings(tmp_path):
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"model": "x", "permissions": {"allow": ["Bash(ls)"]}, "hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": "say done"},
                            {"type": "command", "command": "roundtable hook stop --agent old"}]}],
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "check"}]}]}}))
    write_claude_settings(tmp_path, "new")
    s = json.loads(path.read_text())
    assert s["model"] == "x" and s["permissions"]["allow"] == ["Bash(ls)", "mcp__roundtable"]
    assert s["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "check"
    stop = [h["command"] for g in s["hooks"]["Stop"] for h in g["hooks"]]
    assert stop == ["say done", "roundtable hook stop --agent new"]
    write_claude_settings(tmp_path, "new", hooks=False)  # --no-hooks removes ours only
    s = json.loads(path.read_text())
    assert [h["command"] for g in s["hooks"]["Stop"] for h in g["hooks"]] == ["say done"]
    assert "SessionStart" not in s["hooks"]


def _transcript(path, edits=(), tools=()):
    lines = []
    for fp in edits:
        lines.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": fp}}]}})
    for t in tools:
        lines.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": t, "input": {}}]}})
    lines.append({"type": "user", "message": {"content": "plain text"}})
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
    return str(path)


def test_hooks_brief_remind_once_and_log_forgotten_handoffs(world, monkeypatch, capsys):
    tmp_path, hub_dir, repo, remote = world
    monkeypatch.chdir(repo)
    connect()
    hub = Hub(load_config(str(hub_dir / "hub.yaml")))
    hub.journal.session_end("my-game", "made the title screen", ["add sound"])
    hub.send("other", ["my-game"], "API?", "what does /score return?")

    run_hook("session-start", "my-game", {})
    out = capsys.readouterr().out
    assert "project `my-game`" in out and "made the title screen" in out and "add sound" in out
    assert "Unread messages (1)" in out and "from other: API?" in out
    assert len(hub.inbox("my-game")) == 1  # the briefing doesn't mark anything read

    # no changes yet: Claude may stop
    t = _transcript(tmp_path / "t.jsonl")
    run_hook("stop", "my-game", {"session_id": "s1", "transcript_path": t})
    assert capsys.readouterr().out == ""
    # changed files and no handoff: reminded once, never twice, never while already continuing
    t = _transcript(tmp_path / "t.jsonl", edits=[str(repo / "src" / "a.py")])
    run_hook("stop", "my-game", {"session_id": "s1", "transcript_path": t, "stop_hook_active": True})
    assert capsys.readouterr().out == ""
    run_hook("stop", "my-game", {"session_id": "s1", "transcript_path": t})
    decision = json.loads(capsys.readouterr().out)
    assert decision["decision"] == "block" and "hub_session_end" in decision["reason"]
    run_hook("stop", "my-game", {"session_id": "s1", "transcript_path": t})
    assert capsys.readouterr().out == ""

    # session ends without a handoff: a note with the changed files is logged for it
    run_hook("session-end", "my-game", {"session_id": "s1", "transcript_path": t, "cwd": str(repo)})
    hub2 = Hub(load_config(str(hub_dir / "hub.yaml")))
    last = hub2.journal.brief("my-game", "my-game")["last_session"]
    assert "auto-logged" in last["text"] and "src/a.py" in last["text"].replace("\\", "/")
    # ... but not when Claude did log one
    t2 = _transcript(tmp_path / "t2.jsonl", edits=["x.py"], tools=["mcp__roundtable__hub_session_end"])
    assert transcript_summary(t2)["changed"] == ["x.py"]
    run_hook("stop", "my-game", {"session_id": "s2", "transcript_path": t2})
    run_hook("session-end", "my-game", {"session_id": "s2", "transcript_path": t2, "cwd": str(repo)})
    assert capsys.readouterr().out == ""
    assert Hub(load_config(str(hub_dir / "hub.yaml"))).journal.brief("my-game", "my-game")["last_session"] == last


def test_hooks_never_break_a_session(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ROUNDTABLE_HOME", str(tmp_path / "apphome"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("HUB_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    assert run_hook("session-start", "x", {}) == 0
    assert "hub unavailable" in capsys.readouterr().out
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))
    with pytest.raises(SystemExit) as e:
        connect_main("hook", ["session-end", "--agent", "x"])
    assert e.value.code == 0


def test_cli_and_cloud_script(world, monkeypatch, capsys):
    from roundtable.main import main

    tmp_path, hub_dir, repo, remote = world
    monkeypatch.chdir(tmp_path)  # never near a real agent-hub-data checkout
    main(["connect", "--cloud-script"])
    assert "pip install" in capsys.readouterr().out
    main(["connect", str(repo), "--config", str(hub_dir / "hub.yaml"), "--agent", "game2", "--description", "second game", "--no-hooks"])
    out = capsys.readouterr().out
    assert "as project 'game2' (new in the hub)" in out
    assert "hooks" not in json.loads((repo / ".claude" / "settings.json").read_text())
    assert yaml.safe_load((hub_dir / "hub.yaml").read_text())["agents"]["game2"]["description"] == "second game"
