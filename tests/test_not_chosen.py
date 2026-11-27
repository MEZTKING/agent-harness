"""The Tidy page's "attempts not chosen" (retention.py): rival attempts kept as a branch and a patch, listed with
their size and cleared only by the owner's button. A made-up project in tmp_path."""

import json
import subprocess

from roundtable import retention


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout


def made_up(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "user.name", "t")
    (root / "a.txt").write_text("a\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "base")
    for rid, text in (("r1", "A\n"), ("r2", "B\n")):
        git(root, "checkout", "-qb", f"roundtable-task/T1-{rid}", "main")
        (root / "out.txt").write_text(text)
        git(root, "add", ".")
        git(root, "commit", "-qm", f"[T1] the answer ({rid})")
    git(root, "checkout", "-q", "main")
    git(root, "merge", "-q", "--ff-only", "roundtable-task/T1-r2")  # r2 won and went in
    patches = root / ".harness" / "rivals" / "T1"
    patches.mkdir(parents=True)
    (patches / "r1.patch").write_text("+A\n" * 50)
    (root / ".harness" / "rivals.json").write_text(json.dumps({"T1": [{"winner": "r2", "why": "B reads more clearly",
        "rivals": [{"id": "r1", "model": "a/coder", "picked": False}, {"id": "r2", "model": "b/coder2", "picked": True}]}]}))
    return root


def test_attempts_not_chosen_are_listed_and_only_cleared_by_the_owner(tmp_path):
    root = made_up(tmp_path)
    rows = retention.not_chosen(root)
    assert [(r["task"], r["rival"], r["branch"], r["model"]) for r in rows] == [
        ("T1", "r1", "roundtable-task/T1-r1", "a/coder")]  # the merged winner is not listed
    assert rows[0]["patch"] == ".harness/rivals/T1/r1.patch" and rows[0]["bytes"] > 0
    assert rows[0]["why"] == "B reads more clearly"
    assert "1 attempt not chosen, on 1 task" in retention.not_chosen_words(rows)
    # the daily sweep never touches them
    retention.tidy(None, home=tmp_path / "home")
    assert retention.not_chosen(root) == rows
    out = retention.clear_not_chosen(root)
    assert out["cleared"] == ["T1 r1"] and not out["kept"]
    assert retention.not_chosen(root) == []
    assert "roundtable-task/T1-r1" not in git(root, "branch", "--list")
    assert (root / "out.txt").read_text() == "B\n"  # the chosen work stays
