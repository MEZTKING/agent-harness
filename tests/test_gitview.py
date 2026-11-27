"""A project's git history for the app (harness/gitview.py): log, one commit, one file's diff, branches, compare,
the guarded switch of branch, and hand edits put back. Every repository is made up, in tmp_path."""

from __future__ import annotations

import subprocess

import pytest

from roundtable.harness import gitview, rewind
from roundtable.harness.gitview import GitViewError


def _git(root, *args):
    return subprocess.run(["git", "-c", "user.name=Tester", "-c", "user.email=t@localhost", "-c",
                           "commit.gpgsign=false", *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "kite-shop"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "app.py").write_text("print('one')\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "First words")
    (root / "app.py").write_text("print('one')\nprint('two')\n", encoding="utf-8")
    (root / "notes.md").write_text("# Notes\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "[T1] Add a second line and notes")
    _git(root, "branch", "kites")
    (root / "app.py").write_text("print('two')\n", encoding="utf-8")
    _git(root, "commit", "-q", "-am", "Take the first line out")
    _git(root, "checkout", "-q", "kites")
    (root / "kites.txt").write_text("red\nblue\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "Kites list")
    _git(root, "checkout", "-q", "main")
    return root


def test_log_lists_newest_first_with_kinds(repo):
    d = gitview.log(repo)
    assert d["branch"] == "main" and not d["more"]
    assert [c["subject"] for c in d["commits"]] == ["Take the first line out", "[T1] Add a second line and notes",
                                                   "First words"]
    assert d["commits"][1]["kind"] == "task" and d["commits"][1]["task"] == "T1"
    assert d["commits"][0]["author"] == "Tester" and len(d["commits"][0]["short"]) == 7
    two = gitview.log(repo, limit=2)
    assert len(two["commits"]) == 2 and two["more"]
    assert [c["subject"] for c in gitview.log(repo, "kites")["commits"]][0] == "Kites list"


def test_one_commit_has_its_files_with_lines_added_and_removed(repo):
    sha = gitview.log(repo)["commits"][1]["sha"]
    c = gitview.commit(repo, sha)
    by = {f["path"]: f for f in c["files"]}
    assert by["app.py"]["change"] == "changed" and by["app.py"]["added"] == 1 and by["app.py"]["removed"] == 0
    assert by["notes.md"]["change"] == "added" and c["added"] == 2
    first = gitview.log(repo)["commits"][-1]["sha"]
    assert [f["path"] for f in gitview.commit(repo, first)["files"]] == ["app.py"]  # the first commit too


def test_a_files_diff_is_lines_marked_added_removed_or_kept(repo):
    sha = gitview.log(repo)["commits"][0]["sha"]
    d = gitview.diff(repo, sha, "app.py")
    kinds = [(x["kind"], x["text"]) for x in d["lines"] if x["kind"] != "hunk"]
    assert kinds == [("del", "print('one')"), ("same", "print('two')")]
    first = gitview.log(repo)["commits"][-1]["sha"]
    assert [x["kind"] for x in gitview.diff(repo, first, "app.py")["lines"]] == ["hunk", "add"]


def test_branches_and_compare(repo):
    b = gitview.branches(repo)
    assert b["current"] == "main" and {x["name"] for x in b["branches"]} == {"main", "kites"}
    c = gitview.compare(repo, "main", "kites")
    assert c["only_a"] == 1 and c["only_b"] == 1
    assert {f["path"] for f in c["files"]} == {"app.py", "kites.txt"}


@pytest.mark.parametrize("bad", ["main; rm -rf /", "$(whoami)", "-x", "a..b", "../main", "a b", "x`y`", "",
                                 "main.lock", "@{1}", "feature/", "a|b"])
def test_a_branch_name_with_shell_characters_is_refused_before_git_runs(repo, bad, monkeypatch):
    called = []
    monkeypatch.setattr(gitview.subprocess, "run", lambda *a, **k: called.append(a) or None)
    with pytest.raises(GitViewError):
        gitview.check_branch(bad)
    with pytest.raises(GitViewError):
        gitview.compare(repo, "main", bad) if bad else gitview.checkout_preview(repo, bad)
    assert called == []  # git never ran


@pytest.mark.parametrize("bad", ["HEAD", "zzzz", "1234; ls", "--all", "abc"])
def test_a_bad_sha_is_refused(repo, bad):
    with pytest.raises(GitViewError):
        gitview.commit(repo, bad)


def test_a_file_outside_is_refused_for_a_diff(repo):
    sha = gitview.log(repo)["commits"][0]["sha"]
    for bad in ("../x", "/etc/passwd", ".git/config", "C:/x"):
        with pytest.raises(GitViewError):
            gitview.diff(repo, sha, bad)


def test_checkout_needs_a_clean_tree_and_the_preview_stamp_and_keeps_a_snapshot(repo):
    (repo / "app.py").write_text("changed by hand\n", encoding="utf-8")
    pv = gitview.checkout_preview(repo, "kites")
    assert pv["blocked"] and "not kept yet" in pv["blocked"] and pv["stamp"] == ""
    with pytest.raises(GitViewError):
        gitview.checkout(repo, "kites", "anything")
    _git(repo, "checkout", "--", "app.py")
    pv = gitview.checkout_preview(repo, "kites")
    assert not pv["blocked"] and {f["path"] for f in pv["files"]} == {"app.py", "kites.txt"}
    with pytest.raises(GitViewError):
        gitview.checkout(repo, "kites", "stale")
    res = gitview.checkout(repo, "kites", pv["stamp"])
    assert res["ok"] and gitview.current_branch(repo) == "kites" and (repo / "kites.txt").is_file()
    assert res["kept"].startswith(rewind.REF_PREFIX) and _git(repo, "rev-parse", res["kept"])
    assert gitview.checkout_preview(repo, "kites")["blocked"] == "The project is on that branch already."


def test_commit_file_commits_that_file_alone_and_undo_puts_it_back(repo):
    (repo / "notes.md").write_text("# Notes\nmore\n", encoding="utf-8")  # the owner's other unsaved change
    (repo / "app.py").write_text("print('three')\n", encoding="utf-8")
    sha = gitview.commit_file(repo, "app.py")
    assert sha and _git(repo, "log", "-1", "--format=%s") == "Edited by hand: app.py"
    assert _git(repo, "show", "--name-only", "--format=", sha) == "app.py"
    assert gitview.dirty(repo) == ["notes.md"]  # still the owner's, not swept in
    assert gitview.commit_file(repo, "app.py") == ""  # nothing new
    rows = gitview.hand_edits(repo)
    assert rows[0]["file"] == "app.py" and not rows[0]["undone"]
    res = gitview.undo_edit(repo, sha)
    assert res["ok"] and (repo / "app.py").read_text(encoding="utf-8") == "print('two')\n"
    assert gitview.hand_edits(repo)[0]["undone"]
    assert gitview.log(repo)["commits"][0]["kind"] == "put_back"
    with pytest.raises(GitViewError):
        gitview.undo_edit(repo, sha)


def test_undo_is_refused_when_the_file_changed_since(repo):
    (repo / "app.py").write_text("print('three')\n", encoding="utf-8")
    sha = gitview.commit_file(repo, "app.py")
    (repo / "app.py").write_text("print('four')\n", encoding="utf-8")
    with pytest.raises(GitViewError) as e:
        gitview.undo_edit(repo, sha)
    assert "changed since" in str(e.value)
    task = gitview.log(repo)["commits"][2]["sha"]
    with pytest.raises(GitViewError):
        gitview.undo_edit(repo, task)  # only hand edits


def test_not_a_repository_says_so(tmp_path):
    with pytest.raises(GitViewError) as e:
        gitview.log(tmp_path)
    assert "isn't kept in git" in str(e.value)
