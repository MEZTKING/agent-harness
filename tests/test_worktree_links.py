"""Linked dependencies (worktrees.py ``link_deps``): a new task worktree shares the project's node_modules, .venv…
instead of installing them again – only when the lockfiles match and git ignores the link – and removing the lane
takes the link away without ever following it. Made-up projects in tmp_path, no network."""

import json
import os
import sys

import pytest

from roundtable.harness import perms
from roundtable.harness.gate import Gate
from roundtable.harness.worktrees import LINKS_FILE, Worktrees, _is_link, linked_folders

from .test_parallel import THREE, ParallelBrain, raw
from .test_harness import make
from .test_repository import git

LOCK = '{"name": "app", "lockfileVersion": 3, "packages": {"": {"dependencies": {"left-pad": "1.3.0"}}}}\n'


def deps(root):
    """A made-up node_modules with nested files, as an install would leave it."""
    nm = root / "node_modules"
    (nm / "left-pad" / "lib").mkdir(parents=True)
    (nm / "left-pad" / "package.json").write_text('{"name": "left-pad"}\n')
    (nm / "left-pad" / "lib" / "index.js").write_text("module.exports = (s) => s;\n")
    (nm / ".package-lock.json").write_text(LOCK)
    return {p.relative_to(nm).as_posix(): p.read_bytes() for p in nm.rglob("*") if p.is_file()}


def repo(tmp_path, ignore="node_modules\n.harness/\n", lock=True, name="proj"):
    root = tmp_path / name
    root.mkdir()
    git(root, "init", "-q")
    git(root, "checkout", "-q", "-b", "main")
    (root / ".gitignore").write_text(ignore)
    (root / "index.js").write_text("console.log('hi')\n")
    if lock:
        (root / "package-lock.json").write_text(LOCK)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "first")
    return root


def lane(root, task="T1"):
    trees = Worktrees(root)
    path, _ = trees.add(task, git(root, "rev-parse", "HEAD"))
    return trees, path


def files_of(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


# -- when a folder is linked ----------------------------------------------------------------------------------------
def test_links_are_made_when_the_lockfiles_match(tmp_path):
    root = repo(tmp_path)
    deps(root)
    trees, path = lane(root)
    out = trees.link_deps("T1")
    assert out == {"linked": ["node_modules"], "skipped": [], "complete": True}
    assert _is_link(path / "node_modules") and (path / "node_modules" / "left-pad" / "lib" / "index.js").is_file()
    assert os.path.realpath(path / "node_modules") == os.path.realpath(root / "node_modules")
    assert json.loads((root / LINKS_FILE).read_text()) == {"T1": {"node_modules": str(trees.root / "node_modules")}}
    assert linked_folders(root) == ["node_modules"]
    assert git(path, "status", "--porcelain", "--untracked-files=all") == ""  # git never sees it


def test_a_different_lockfile_means_the_lane_installs_its_own(tmp_path):
    root = repo(tmp_path)
    deps(root)
    trees, path = lane(root)
    (path / "package-lock.json").write_text(LOCK.replace("1.3.0", "1.4.0"))
    out = trees.link_deps("T1")
    assert out["linked"] == [] and out["complete"] is False
    assert out["skipped"] == [{"folder": "node_modules", "why": "package-lock.json differs from the project's"}]
    assert not os.path.lexists(path / "node_modules")


def test_no_lockfile_means_no_link(tmp_path):
    root = repo(tmp_path, lock=False)
    deps(root)
    trees, path = lane(root)
    assert trees.link_deps("T1")["skipped"][0]["why"].startswith("there's no lockfile")
    assert not os.path.lexists(path / "node_modules")


def test_a_folder_git_doesnt_ignore_is_never_linked(tmp_path):
    root = repo(tmp_path, ignore=".harness/\n")
    deps(root)
    trees, path = lane(root)
    assert trees.link_deps("T1")["skipped"] == [
        {"folder": "node_modules", "why": "git doesn't ignore it here, so it could be committed"}]
    assert not os.path.lexists(path / "node_modules")


def test_a_folder_only_pattern_is_covered_by_the_repositorys_own_exclude(tmp_path):
    root = repo(tmp_path, ignore="node_modules/\n.harness/\n")  # the usual way: it ignores folders, not links
    deps(root)
    trees, path = lane(root)
    assert trees.link_deps("T1")["linked"] == ["node_modules"]
    exclude = (root / ".git" / "info" / "exclude").read_text()
    assert "/node_modules" in exclude.splitlines() and git(root, "status", "--porcelain") == ""
    assert git(path, "status", "--porcelain", "--untracked-files=all") == ""
    trees2, path2 = lane(root, "T2")
    trees2.link_deps("T2")
    assert (root / ".git" / "info" / "exclude").read_text().count("/node_modules") == 1


def test_the_settings_choose_the_folders_and_never_reach_outside(tmp_path):
    root = repo(tmp_path, ignore="node_modules\n.venv\n.harness/\n")
    deps(root)
    (root / ".venv").mkdir()
    (root / "requirements.txt").write_text("requests==2.0\n")
    git(root, "add", "requirements.txt")
    git(root, "commit", "-q", "-m", "reqs")
    trees = Worktrees(root)
    assert trees.link_candidates() == ["node_modules", ".venv"]  # the defaults that are there
    assert trees.link_candidates({"link": False}) == [] and trees.link_candidates({"link": []}) == []
    assert trees.link_candidates({"link": ["../elsewhere", "/etc", ".git", ".harness/x", "a/../b", "C:/x", "vendor"]}) \
        == ["vendor"]
    _, path = lane(root)
    out = trees.link_deps(path, {"link": [".venv"]})
    assert out["linked"] == [".venv"] and not os.path.lexists(path / "node_modules")


def test_a_lane_that_has_its_own_folder_keeps_it(tmp_path):
    root = repo(tmp_path)
    deps(root)
    trees, path = lane(root)
    (path / "node_modules").mkdir()
    (path / "node_modules" / "mine.txt").write_text("lane's own")
    assert trees.link_deps("T1")["skipped"] == [{"folder": "node_modules", "why": "the lane has its own already"}]
    assert (path / "node_modules" / "mine.txt").read_text() == "lane's own"


# -- never committed -------------------------------------------------------------------------------------------------
def test_a_linked_folder_never_appears_in_a_commit(tmp_path):
    root = repo(tmp_path)
    deps(root)
    trees, path = lane(root)
    trees.link_deps("T1")
    (path / "feature.js").write_text("export const x = 1;\n")
    (path / ".gitignore").write_text(".harness/\n")  # a builder stops ignoring it: the link still stays out
    assert trees.commit("T1", "[T1] feature")
    names = git(path, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert "feature.js" in names and not any(n.startswith("node_modules") for n in names)
    assert "node_modules" not in git(path, "ls-files")


# -- removing a lane ---------------------------------------------------------------------------------------------------
def test_removing_a_lane_leaves_the_original_folder_and_every_file_in_it(tmp_path):
    root = repo(tmp_path)
    before = deps(root)
    trees, path = lane(root)
    assert trees.link_deps("T1")["linked"] == ["node_modules"]
    (path / "feature.js").write_text("export const x = 1;\n")
    assert trees.commit("T1", "[T1] feature")
    assert trees.merge_into_project("T1", "bring it in").ok
    removed, why = trees.remove("T1")
    assert removed, why
    assert not path.exists()
    assert (root / "node_modules").is_dir() and not _is_link(root / "node_modules")
    assert files_of(root / "node_modules") == before  # every file, byte for byte
    assert linked_folders(root) == []


def test_a_link_that_cant_be_taken_away_keeps_the_lane(tmp_path, monkeypatch):
    from roundtable.harness import worktrees as wt

    root = repo(tmp_path)
    before = deps(root)
    trees, path = lane(root)
    trees.link_deps("T1")
    monkeypatch.setattr(wt, "_unlink", lambda p: False)
    removed, why = trees.remove("T1")
    assert not removed and "couldn't be taken away" in why and path.exists()
    assert files_of(root / "node_modules") == before


def test_a_lane_whose_own_folder_replaced_the_link_is_removed_as_its_own(tmp_path):
    root = repo(tmp_path)
    before = deps(root)
    trees, path = lane(root)
    trees.link_deps("T1")
    os.unlink(path / "node_modules")  # a builder made its own install in the lane
    (path / "node_modules").mkdir()
    (path / "node_modules" / "x.js").write_text("lane\n")
    removed, why = trees.remove("T1")
    assert removed, why
    assert files_of(root / "node_modules") == before


@pytest.mark.skipif(os.name != "nt", reason="directory junctions are Windows'")
def test_on_windows_a_junction_is_made_and_removing_the_lane_leaves_the_folder(tmp_path):
    root = repo(tmp_path)
    before = deps(root)
    trees, path = lane(root)
    assert trees.link_deps("T1")["linked"] == ["node_modules"]
    assert _is_link(path / "node_modules") and not os.path.islink(path / "node_modules")  # a junction, not a symlink
    removed, why = trees.remove("T1")
    assert removed, why
    assert files_of(root / "node_modules") == before


# -- a whole run, several tasks at once -----------------------------------------------------------------------------
def test_a_parallel_run_links_skips_setup_and_leaves_node_modules(tmp_path):
    root = repo(tmp_path)
    before = deps(root)
    (root / ".harness").mkdir()
    (root / ".harness" / "project.yaml").write_text(
        "setup: " + (sys.executable.replace("\\", "/") + " -c \"open('SETUP_RAN','w').write('x')\"") + "\n")
    orch, *_ = make(tmp_path, raw=raw(2), brain=ParallelBrain(THREE[:2]))
    orch.start("two files")
    assert orch.run() == "done"
    evs = [json.loads(ln) for ln in (orch.project.root / ".harness" / "events.jsonl").read_text().splitlines()]
    linked = [e for e in evs if e["event"] == "deps_linked"]
    assert sorted(e["task"] for e in linked) == ["T1", "T2"] and all(e["linked"] == ["node_modules"] for e in linked)
    assert not any(e["event"] == "worktree_setup" for e in evs)  # nothing installed again
    assert not Worktrees(root).exists("T1") and not Worktrees(root).exists("T2")
    assert files_of(root / "node_modules") == before
    assert "node_modules" not in git(root, "ls-files")


def test_deleting_the_shared_folder_from_a_lane_waits_for_the_owner(tmp_path):
    root = repo(tmp_path)
    deps(root)
    trees, path = lane(root)
    trees.link_deps("T1")
    guard = perms.guard(root, None, "coder", Gate(root, poll=0.01, timeout=0.05))
    assert guard("run_command", {"command": "rm -rf node_modules/left-pad"}).startswith("Nobody answered")


def test_an_unrecorded_link_is_taken_away_only_when_it_points_at_the_projects_folder(tmp_path):
    root = repo(tmp_path)
    before = deps(root)
    trees, path = lane(root)
    trees.link_deps("T1")
    (root / LINKS_FILE).unlink()  # the record lost (a crash): the link is still found and taken away
    other = tmp_path / "elsewhere"
    other.mkdir()
    (path / ".venv").symlink_to(other, target_is_directory=True) if os.name != "nt" else None
    assert trees.unlink_deps("T1") == []
    assert not os.path.lexists(path / "node_modules")
    if os.name != "nt":
        assert _is_link(path / ".venv")  # not ours: left alone
    assert files_of(root / "node_modules") == before
