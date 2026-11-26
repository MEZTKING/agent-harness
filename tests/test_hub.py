import subprocess
from pathlib import Path

import pytest

from roundtable.core.config import parse_config
from roundtable.core.policy import Policy, PolicyError
from roundtable.core.store import FileStore, GitStore
from roundtable.hub.service import Hub, HubError

RAW = {
    "storage": {"type": "file", "path": "data"},
    "default_policy": "deny",
    "agents": {
        "backend": {"repo": "me/api", "description": "API"},
        "frontend": {"repo": "me/web"},
        "secret": {"repo": "me/secret"},
    },
    "rules": [
        {"from": "*", "to": "*", "allow": ["read_card"]},
        {"from": "*", "to": "secret", "deny": ["read_card"]},
        {"from": "backend", "to": "frontend", "allow": ["message"]},
        {"from": "frontend", "to": "backend", "allow": ["message"]},
    ],
}


def make_hub(tmp_path: Path, store=None, raw=RAW) -> Hub:
    cfg = parse_config(raw, tmp_path / "hub.yaml")
    return Hub(cfg, store=store or FileStore(tmp_path / "data"))


def test_policy_last_match_wins():
    pol = Policy.from_config(RAW["rules"], "deny")
    assert pol.allowed("backend", "frontend", "read_card")
    assert not pol.allowed("backend", "secret", "read_card")
    assert pol.allowed("backend", "frontend", "message")
    assert not pol.allowed("backend", "secret", "message")
    assert pol.allowed("secret", "secret", "message")  # self always allowed


def test_policy_rejects_unknown_action():
    with pytest.raises(ValueError):
        Policy.from_config([{"from": "*", "to": "*", "allow": ["teleport"]}])


def test_invalid_agent_id(tmp_path):
    with pytest.raises(ValueError):
        parse_config({"agents": {"Bad Name": {}}}, tmp_path / "hub.yaml")


def test_card_defaults_and_update(tmp_path):
    hub = make_hub(tmp_path)
    card = hub.get_card("frontend", "backend")
    assert card["repo"] == "me/api" and card["summary"] == "API"
    hub.update_card("backend", change_note="added /orders", status="building", interfaces="GET /orders")
    card = hub.get_card("frontend", "backend")
    assert card["status"] == "building"
    assert card["recent_changes"][0]["note"] == "added /orders"
    with pytest.raises(PolicyError):
        hub.get_card("backend", "secret")
    with pytest.raises(HubError):
        hub.update_card("backend", agent="frontend")  # not editable


def test_list_cards_respects_policy(tmp_path):
    hub = make_hub(tmp_path)
    ids = [c["agent"] for c in hub.list_cards("backend")]
    assert ids == ["backend", "frontend"]


def test_messaging_reply_and_thread(tmp_path):
    hub = make_hub(tmp_path)
    [m] = hub.send("frontend", "backend", "orders shape?", "what fields on /orders?")
    with pytest.raises(PolicyError):
        hub.send("frontend", "secret", "hi", "hi")
    with pytest.raises(HubError):
        hub.send("frontend", "nobody", "hi", "hi")

    inbox = hub.inbox("backend", mark_read=True)
    assert [x["id"] for x in inbox] == [m["id"]]
    assert hub.inbox("backend") == []  # now read
    assert len(hub.inbox("backend", unread_only=False)) == 1

    r = hub.reply("backend", m["id"], "id, total_cents, items[]")
    assert r["recipient"] == "frontend" and r["subject"] == "Re: orders shape?"
    assert r["thread_id"] == m["thread_id"]
    thread = hub.thread("frontend", m["thread_id"])
    assert [t["sender"] for t in thread] == ["frontend", "backend"]
    with pytest.raises(HubError):
        hub.reply("backend", "../../etc", "x")


def test_change_notes_reach_subscribers_and_dependents(tmp_path):
    hub = make_hub(tmp_path)
    hub.update_card("frontend", depends_on=["backend"])
    hub.subscribe("secret", "backend")
    res = hub.update_card("backend", change_note="renamed total -> total_cents")
    assert res["notified"] == ["frontend", "secret"]
    [note] = hub.inbox("frontend")
    assert note["kind"] == "notify" and "total_cents" in note["body"]
    # updates without a change note notify nobody
    assert hub.update_card("backend", status="done")["notified"] == []


def test_subscribe_requires_read_permission(tmp_path):
    hub = make_hub(tmp_path)
    with pytest.raises(PolicyError):
        hub.subscribe("backend", "secret")


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_git_store_shares_state_between_clones(tmp_path):
    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)

    hub_a = make_hub(tmp_path, store=GitStore(tmp_path / "clone_a", remote=str(remote), sync_interval=0))
    hub_b = make_hub(tmp_path, store=GitStore(tmp_path / "clone_b", remote=str(remote), sync_interval=0))

    hub_a.update_card("backend", change_note="v1 api", status="live")
    [m] = hub_a.send("backend", "frontend", "heads up", "v1 is live")

    # clone B sees A's writes after its automatic pull
    assert hub_b.get_card("frontend", "backend")["status"] == "live"
    assert [x["id"] for x in hub_b.inbox("frontend")] == [m["id"]]

    # concurrent writes from both sides merge cleanly
    hub_b.reply("frontend", m["id"], "thanks")
    hub_a.send("backend", "frontend", "another", "msg")
    assert len(hub_a.inbox("backend")) == 1
    assert len(hub_b.inbox("frontend", unread_only=False)) == 2


def test_cli_agent_flag_either_position(tmp_path, monkeypatch, capsys):
    import yaml
    from roundtable.cli import main

    cfg = tmp_path / "hub.yaml"
    cfg.write_text(yaml.safe_dump(RAW), encoding="utf-8")
    monkeypatch.setenv("HUB_CONFIG", str(cfg))
    main(["--agent", "backend", "cards"])
    main(["cards", "--agent", "backend"])
    main(["card", "show", "frontend", "--agent", "backend"])
    out = capsys.readouterr().out
    assert out.count('"agent": "backend"') == 2


def test_git_store_works_with_clone_of_initially_empty_repo(tmp_path):
    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    _git("clone", "-q", str(remote), str(tmp_path / "early"), cwd=tmp_path)  # cloned while empty
    seed = tmp_path / "seed"
    _git("clone", "-q", str(remote), str(seed), cwd=tmp_path)
    (seed / "hub.yaml").write_text("x: 1\n", encoding="utf-8")
    _git("-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "add", ".", cwd=seed)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-qm", "init", cwd=seed)
    _git("push", "-q", "origin", "HEAD:main", cwd=seed)

    hub = make_hub(tmp_path, store=GitStore(tmp_path / "early", remote=str(remote)))
    hub.update_card("backend", status="ok")
    assert (tmp_path / "early/hub.yaml").exists()  # picked up the remote's history
    log = subprocess.run(["git", "log", "--oneline", "main"], cwd=remote, capture_output=True, text=True).stdout
    assert "card(backend)" in log and "init" in log


def test_unified_roundtable_command_routes_to_hub_and_harness(tmp_path, monkeypatch, capsys):
    import yaml

    from roundtable.main import _command, main

    assert _command(["--agent", "me", "where"]) == "where"
    assert _command(["--config", "x.yaml", "-v", "new", "d", "g"]) == "new"
    cfg = tmp_path / "hub.yaml"
    cfg.write_text(yaml.safe_dump(RAW), encoding="utf-8")
    monkeypatch.setenv("HUB_CONFIG", str(cfg))
    main(["--agent", "backend", "log", "todo", "routed through roundtable"])
    main(["where", "--agent", "backend"])
    assert "routed through roundtable" in capsys.readouterr().out
    monkeypatch.chdir(tmp_path / "data")
    main(["init"])
    assert (tmp_path / "data/hub.yaml").exists() and (tmp_path / "data/harness.yaml").exists()
    main([])
    assert "roundtable where" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["frobnicate"])


def test_reads_reuse_a_recent_sync_but_writes_always_sync(tmp_path):
    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    a = make_hub(tmp_path, store=GitStore(tmp_path / "a", remote=str(remote), sync_interval=0))
    b_store = GitStore(tmp_path / "b", remote=str(remote), sync_interval=3600)
    b = make_hub(tmp_path, store=b_store)
    a.update_card("backend", status="v1")
    b.store.sync(force=True)
    assert b.get_card("frontend", "backend")["status"] == "v1"
    a.update_card("backend", status="v2")
    assert b.get_card("frontend", "backend")["status"] == "v1"  # read within the window: local copy, no network
    b.update_card("frontend", status="writing")  # a write always pulls first...
    assert b.get_card("frontend", "backend")["status"] == "v2"  # ...so it sees the latest state
    log = subprocess.run(["git", "log", "--oneline", "main"], cwd=remote, capture_output=True, text=True).stdout
    assert log.count("card(") == 3  # nothing lost


def test_offline_reads_fall_back_to_local_copy(tmp_path):
    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    hub = make_hub(tmp_path, store=GitStore(tmp_path / "c", remote=str(remote), sync_interval=0))
    hub.update_card("backend", status="cached")
    # go "offline": point the remote at a location that doesn't exist (deleting the bare repo
    # would fail on Windows, where git marks its object files read-only)
    _git("remote", "set-url", "origin", str(tmp_path / "unreachable.git"), cwd=tmp_path / "c")
    assert hub.get_card("frontend", "backend")["status"] == "cached"
    assert hub.store.last_sync_error


def test_ids_made_one_after_another_sort_in_order(monkeypatch):
    from datetime import datetime, timezone

    from roundtable.core import models

    frozen = datetime(2026, 11, 26, 15, 0, 0, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen  # a clock that doesn't move between calls, like Windows' within a tick

    monkeypatch.setattr(models, "datetime", Clock)
    ids = [models.new_id() for _ in range(50)]
    assert ids == sorted(ids) and len(set(i.split("-")[0] for i in ids)) == 50
