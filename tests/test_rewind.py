"""Undo a task, go back to before it, put it back, try another way (harness/rewind.py, ui/rewindapi.py).

Every project is made up, in tmp_path; the models are scripted (the three-task bakery run of test_harness)."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from roundtable.harness import rewind
from roundtable.harness.rewind import RewindError

from .test_harness import make


def _git(root, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@localhost", *args], cwd=root,
                          capture_output=True, text=True, check=True).stdout.strip()


def _tasks(root):
    return {t["id"]: t for t in json.loads((root / ".harness/tasks.json").read_text(encoding="utf-8"))}


def _files(root):
    return sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*")
                  if p.is_file() and ".git" not in p.parts and ".harness" not in p.parts)


@pytest.fixture
def proj(tmp_path):
    orch, *_ = make(tmp_path)
    orch.start("build a bakery site")
    assert orch.run() == "done"
    return orch.project.root


def test_history_has_one_row_per_finished_task_with_its_files(proj):
    rows = rewind.history(proj)
    assert [r["id"] for r in rows] == ["T1", "T2", "T3"]
    by = {r["id"]: r for r in rows}
    assert by["T1"]["files"] == [{"path": "hello.py", "change": "added"}]
    assert by["T2"]["files"] == [{"path": "assets/logo.png", "change": "added"}]
    assert by["T3"]["words"] == "Changed 1 file." and not by["T3"]["pushed"] and by["T3"]["can_undo"]


def test_undo_task_reverts_only_that_task_and_keeps_later_work(proj):
    pv = rewind.preview(proj, "T2", "undo_task")
    assert not pv["blocked"] and pv["back_to_todo"] == ["T2"]
    assert [(f["path"], f["change"]) for f in pv["files"]] == [("assets/logo.png", "removed")]
    res = rewind.apply(proj, "T2", "undo_task", pv["stamp"])
    assert res["ok"] and res["ref"].startswith(rewind.REF_PREFIX)
    assert not (proj / "assets/logo.png").exists() and (proj / "test_hello.py").exists()
    t = _tasks(proj)
    assert t["T2"]["status"] == "pending" and t["T2"]["attempts"] == [] and len(t["T2"]["previous_attempts"]) == 1
    assert t["T3"]["status"] == "done"
    assert json.loads((proj / ".harness/project.json").read_text(encoding="utf-8"))["status"] == "paused"
    assert _git(proj, "log", "-1", "--format=%s").startswith("Undo [T2]")
    row = next(r for r in rewind.history(proj) if r["id"] == "T2")
    assert row["undone"] and row["words"] == "Undone." and not row["can_undo"]
    assert rewind.preview(proj, "T2", "undo_task")["blocked"] == "This task has already been undone."


def test_back_to_before_restores_files_and_task_list(proj):
    before_t2 = _tasks(proj)["T2"]["base_commit"]
    pv = rewind.preview(proj, "T2", "back_to_before")
    assert not pv["blocked"] and pv["back_to_todo"] == ["T2", "T3"]
    assert sorted(f["path"] for f in pv["files"]) == ["assets/logo.png", "test_hello.py"]
    rewind.apply(proj, "T2", "back_to_before", pv["stamp"])
    assert _git(proj, "rev-parse", "HEAD") == before_t2
    assert _files(proj) == [".gitignore", "hello.py"]
    t = _tasks(proj)
    assert t["T1"]["status"] == "done" and t["T2"]["status"] == t["T3"]["status"] == "pending"
    assert t["T3"]["previous_attempts"] and t["T3"]["base_commit"] is None


@pytest.mark.parametrize("mode", rewind.MODES)
def test_the_preview_is_exactly_what_apply_does(proj, mode):
    before = {p: (proj / p).read_bytes() for p in _files(proj)}
    pv = rewind.preview(proj, "T1", mode) if mode == "back_to_before" else rewind.preview(proj, "T3", mode)
    assert _files(proj) == sorted(before) and rewind.stamp(proj) == pv["stamp"]  # the preview changed nothing
    rewind.apply(proj, pv["task"], mode, pv["stamp"])
    after = {p: (proj / p).read_bytes() for p in _files(proj)}
    differ = {p for p in set(before) | set(after) if before.get(p) != after.get(p)}
    assert differ == {f["path"] for f in pv["files"]} and differ
    for f in pv["files"]:
        assert (f["path"] in after) == (f["change"] != "removed")
    assert sorted(t for t, v in _tasks(proj).items() if v["status"] == "pending") == sorted(pv["back_to_todo"])


def test_a_stale_stamp_is_refused_and_nothing_changes(proj):
    pv = rewind.preview(proj, "T2", "undo_task")
    (proj / "hello.py").write_text("print('changed by hand')\n", encoding="utf-8")
    head = _git(proj, "rev-parse", "HEAD")
    with pytest.raises(RewindError, match="changed since you looked"):
        rewind.apply(proj, "T2", "undo_task", pv["stamp"])
    with pytest.raises(RewindError):
        rewind.apply(proj, "T2", "undo_task", "")
    assert _git(proj, "rev-parse", "HEAD") == head and not rewind.entries(proj)
    assert (proj / "assets/logo.png").exists()


def test_pushed_work_refuses_back_to_before_and_offers_undo(proj, tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    _git(proj, "remote", "add", "origin", str(bare))
    _git(proj, "push", "-q", "origin", "HEAD:refs/heads/main")
    _git(proj, "fetch", "-q", "origin")
    pv = rewind.preview(proj, "T2", "back_to_before")
    assert "sent to GitHub" in pv["blocked"] and pv["offer"] == "undo_task"
    with pytest.raises(RewindError, match="sent to GitHub"):
        rewind.apply(proj, "T2", "back_to_before", pv["stamp"])
    assert all(r["pushed"] for r in rewind.history(proj))
    ok = rewind.preview(proj, "T2", "undo_task")  # undoing it alone adds a commit: fine after a push
    assert not ok["blocked"]
    rewind.apply(proj, "T2", "undo_task", ok["stamp"])
    assert not (proj / "assets/logo.png").exists()


def test_a_hand_edit_survives_both_ways(proj):
    (proj / "hello.py").write_text("print('hi')  # my own note\n", encoding="utf-8")
    (proj / "notes.txt").write_text("my own new file\n", encoding="utf-8")
    pv = rewind.preview(proj, "T3", "undo_task")
    assert {f["path"] for f in pv["hand_edits"]} == {"hello.py", "notes.txt"}
    rewind.apply(proj, "T3", "undo_task", pv["stamp"])
    assert "my own note" in (proj / "hello.py").read_text(encoding="utf-8") and (proj / "notes.txt").exists()
    assert not (proj / "test_hello.py").exists()
    assert sorted(_git(proj, "status", "--porcelain").splitlines()) == [" M hello.py", "?? notes.txt"]  # still yours
    # going back to before T2: the edits still fit (T2 and T3 didn't touch them), so they stay, uncommitted
    pv = rewind.preview(proj, "T2", "back_to_before")
    assert pv["hand_edits_kept"] is True
    rewind.apply(proj, "T2", "back_to_before", pv["stamp"])
    assert (proj / "notes.txt").read_text(encoding="utf-8") == "my own new file\n"


def test_an_edit_that_doesnt_fit_is_kept_safe_and_comes_back(proj):
    (proj / "test_hello.py").write_text("# my own test\n", encoding="utf-8")  # a file T3 made
    pv = rewind.preview(proj, "T3", "back_to_before")
    assert pv["hand_edits_kept"] is False and "kept safe" in pv["words"]
    rewind.apply(proj, "T3", "back_to_before", pv["stamp"])
    assert not (proj / "test_hello.py").exists()
    rewind.undo_last(proj)
    assert (proj / "test_hello.py").read_text(encoding="utf-8") == "# my own test\n"


def test_undo_last_restores_everything(proj):
    head = _git(proj, "rev-parse", "HEAD")
    tasks_before = (proj / ".harness/tasks.json").read_text(encoding="utf-8")
    meta_before = (proj / ".harness/project.json").read_text(encoding="utf-8")
    (proj / "notes.txt").write_text("mine\n", encoding="utf-8")
    files_before = {p: (proj / p).read_bytes() for p in _files(proj)}
    pv = rewind.preview(proj, "T1", "back_to_before")
    rewind.apply(proj, "T1", "back_to_before", pv["stamp"])
    assert not (proj / "hello.py").exists()
    last = rewind.last_rewind(proj)
    assert last["can_put_back"] and last["mode"] == "back_to_before"
    res = rewind.undo_last(proj)
    assert res["ok"] and _git(proj, "rev-parse", "HEAD") == head
    assert {p: (proj / p).read_bytes() for p in _files(proj)} == files_before
    assert _git(proj, "status", "--porcelain") == "?? notes.txt"  # still the owner's uncommitted file
    assert (proj / ".harness/tasks.json").read_text(encoding="utf-8") == tasks_before
    assert (proj / ".harness/project.json").read_text(encoding="utf-8") == meta_before
    assert rewind.last_rewind(proj) is None
    with pytest.raises(RewindError, match="nothing to put back"):
        rewind.undo_last(proj)
    # every state on the way is kept: the rewind's and the put-back's
    assert len(rewind.refs(proj)) == 2


def test_put_back_after_undo_task(proj):
    head = _git(proj, "rev-parse", "HEAD")
    pv = rewind.preview(proj, "T2", "undo_task")
    rewind.apply(proj, "T2", "undo_task", pv["stamp"])
    rewind.undo_last(proj)
    assert _git(proj, "rev-parse", "HEAD") == head and (proj / "assets/logo.png").exists()
    assert _tasks(proj)["T2"]["status"] == "done"


def test_put_back_refuses_once_work_has_carried_on(proj):
    pv = rewind.preview(proj, "T3", "undo_task")
    rewind.apply(proj, "T3", "undo_task", pv["stamp"])
    (proj / "more.txt").write_text("x\n", encoding="utf-8")
    _git(proj, "add", "-A")
    _git(proj, "commit", "-q", "-m", "later work")
    assert rewind.last_rewind(proj)["can_put_back"] is False
    with pytest.raises(RewindError, match="carried on"):
        rewind.undo_last(proj)


def test_a_clash_blocks_undo_task_with_nothing_changed(proj):
    (proj / "hello.py").write_text("print('rewritten later')\n", encoding="utf-8")
    _git(proj, "add", "-A")
    _git(proj, "commit", "-q", "-m", "[T9] later rewrite")
    head = _git(proj, "rev-parse", "HEAD")
    pv = rewind.preview(proj, "T1", "undo_task")
    assert "can't be undone on its own" in pv["blocked"] and pv["offer"] == "back_to_before"
    assert _git(proj, "rev-parse", "HEAD") == head and _git(proj, "status", "--porcelain") == ""
    assert _git(proj, "worktree", "list").count("\n") == 0  # the scratch worktree is gone


@pytest.mark.parametrize("mode", rewind.MODES)
def test_both_refuse_while_a_job_runs_or_another_machine_builds(proj, mode):
    pv = rewind.preview(proj, "T2", mode, busy=True)
    assert "working on this project" in pv["blocked"]
    with pytest.raises(RewindError, match="working on this project"):
        rewind.apply(proj, "T2", mode, pv["stamp"], busy=True)
    with pytest.raises(RewindError, match="Laptop"):
        rewind.apply(proj, "T2", mode, pv["stamp"], elsewhere="This project is being built on Laptop right now.")
    with pytest.raises(RewindError, match="working on this project"):
        rewind.undo_last(proj, busy=True)
    assert not rewind.entries(proj)


def test_unsaved_work_in_a_kept_worktree_refuses(proj):
    from roundtable.harness.worktrees import Worktrees

    trees = Worktrees(proj)
    p, _ = trees.add("T7", _git(proj, "rev-parse", "HEAD"))
    (p / "half.txt").write_text("half done\n", encoding="utf-8")
    assert "Unsaved work" in rewind.preview(proj, "T2", "undo_task")["blocked"]


def test_fork_has_the_right_commit_zero_spend_and_no_event_log(proj, tmp_path):
    t2 = next(r for r in rewind.history(proj) if r["id"] == "T2")
    out = rewind.fork(proj, "T2", "Bakery other way", tmp_path / "projects")
    fork = tmp_path / "projects" / "Bakery-other-way"
    assert out["path"] == str(fork) and out["commit"] == t2["commit"]
    assert _git(fork, "rev-parse", "HEAD") == t2["commit"] and _git(fork, "remote") == ""
    assert (fork / "assets/logo.png").exists() and not (fork / "test_hello.py").exists()
    meta = json.loads((fork / ".harness/project.json").read_text(encoding="utf-8"))
    assert meta["spent_usd"] == 0 and meta["status"] == "paused" and meta["goals"] == ["build a bakery site"]
    assert meta["forked_from"]["task"] == "T2" and meta["forked_from"]["commit"] == t2["commit"]
    assert not (fork / ".harness/events.jsonl").exists() and not (fork / ".harness/metrics.jsonl").exists()
    assert (fork / ".harness/plan.json").exists() and (fork / ".harness/project.yaml").exists()
    t = _tasks(fork)
    assert [t[i]["status"] for i in ("T1", "T2", "T3")] == ["done", "done", "pending"]
    assert all(v["attempts"] == [] for v in t.values())
    assert _tasks(proj)["T3"]["status"] == "done"  # the original is untouched
    with pytest.raises(RewindError, match="already a folder"):
        rewind.fork(proj, "T2", "Bakery other way", tmp_path / "projects")


def test_expired_refs_and_drop_ref(proj):
    pv = rewind.preview(proj, "T3", "undo_task")
    rewind.apply(proj, "T3", "undo_task", pv["stamp"])
    [ref] = [r["ref"] for r in rewind.refs(proj)]
    assert rewind.expired_refs(proj, 30) == []
    later = datetime.now(timezone.utc) + timedelta(days=31)
    assert rewind.expired_refs(proj, 30, now=later) == [ref]
    with pytest.raises(RewindError):
        rewind.drop_ref(proj, "refs/heads/master")
    assert rewind.drop_ref(proj, ref) and rewind.refs(proj) == []


def test_no_git_says_so(tmp_path):
    root = tmp_path / "plain"
    (root / ".harness").mkdir(parents=True)
    (root / ".harness/tasks.json").write_text(json.dumps([{"id": "T1", "title": "x", "status": "done"}]),
                                              encoding="utf-8")
    assert rewind.history(root)[0]["can_undo"] is False
    assert "isn't kept in git" in rewind.preview(root, "T1", "undo_task")["blocked"]
