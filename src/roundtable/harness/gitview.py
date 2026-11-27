"""A project's git history for the app to read (MD-70), and the two guarded writes the editor needs.

Reading only:

* ``log(root, branch, limit, skip)`` – the newest commits first: who, when, the subject, and what kind of
  change it was (a task's ``[T3] ...``, a hand edit, a put-back, a merge or anything else);
* ``commit(root, sha)`` – one commit with every file it changed and the lines added and removed;
* ``diff(root, sha, file)`` – one file's change in that commit, as lines marked added, removed or kept;
* ``branches(root)`` and ``compare(root, a, b)`` – the branches, and how two of them differ.

Two writes, both refused unless it is safe:

* ``commit_file`` – the editor's save: the file written, then one commit of that file only ("Edited by hand:
  <file>"), made through a separate index so nothing else the owner has changed is swept in, and moved onto
  the branch only if nobody moved it meanwhile. ``undo_edit`` takes one back the same way (its body says
  "This reverts commit <sha>." as ``git revert`` would, so the rewind history counts it as undone).
* ``checkout`` – switch to another branch, only with a clean tree; a snapshot of where it was is kept under
  ``rewind.REF_PREFIX`` first. ``checkout_preview`` shows the files that will change and gives the ``stamp``
  the switch must carry. The app adds its own checks (no run here, no other machine building it).

Every git call is a fixed argument list (never a shell), runs with ``safeenv.clean_env()``, and a sha or a
branch name is checked against a strict pattern before git sees it.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from .safeenv import clean_env

SHA = re.compile(r"^[0-9a-f]{4,40}$")
BRANCH = re.compile(r"^(?![-./])(?!.*\.\.)(?!.*//)(?!.*@\{)(?!.*\.lock$)[A-Za-z0-9._/+-]{1,200}(?<![./])$")
HAND_PREFIX = "Edited by hand: "
PUT_BACK_PREFIX = "Put back by hand: "
_TASK = re.compile(r"^\[([^\]]+)\] ")
_REVERTS = re.compile(r"This reverts commit ([0-9a-f]{40})")
LOG_MAX = 200
DIFF_MAX = 400_000  # characters of one file's diff shown
FILES_MAX = 1000  # files listed for one commit
TIMEOUT = 30
_CHANGE = {"A": "added", "M": "changed", "D": "removed", "R": "renamed", "C": "copied", "T": "changed"}


class GitViewError(ValueError):
    """Refused, in words for the owner."""


# -- git ------------------------------------------------------------------------------------------
def _git(root: Path, *args: str, env: dict[str, str] | None = None, data: bytes | None = None,
         check: bool = False) -> subprocess.CompletedProcess:
    argv = ["git", "--no-pager", "-c", "core.quotepath=off", "-c", "user.name=agent-harness",
            "-c", "user.email=harness@localhost", "-c", "commit.gpgsign=false", *args]
    try:
        res = subprocess.run(argv, cwd=str(root), capture_output=True, input=data, env=env or clean_env(),
                             timeout=TIMEOUT)
    except FileNotFoundError:
        raise GitViewError("Git isn't installed on this computer. The Tools page can install it.") from None
    except subprocess.TimeoutExpired:
        raise GitViewError("Git took too long to answer. Try again in a moment.") from None
    if check and res.returncode != 0:
        err = (res.stderr or res.stdout).decode("utf-8", "replace").strip()
        raise GitViewError(f"Git said no: {err[:300]}")
    return res


def _text(res: subprocess.CompletedProcess) -> str:
    return res.stdout.decode("utf-8", "replace") if res.returncode == 0 else ""


def _out(root: Path, *args: str) -> str:
    return _text(_git(root, *args)).strip()


def is_repo(root: Path) -> bool:
    return (Path(root) / ".git").exists() and bool(_out(Path(root), "rev-parse", "--verify", "-q", "HEAD"))


def check_sha(sha: str) -> str:
    sha = str(sha or "").strip().lower()
    if not SHA.match(sha):
        raise GitViewError("That isn't a commit the harness knows. Go back to the history and pick one there.")
    return sha


def check_branch(name: str) -> str:
    name = str(name or "").strip()
    if not BRANCH.match(name):
        raise GitViewError("That branch name can't be used. Pick a branch from the list.")
    return name


def check_file(rel: str) -> str:
    """A file path inside the project as git writes it (no ``..``, nothing absolute, no NUL)."""
    rel = str(rel or "").replace("\\", "/")
    if rel.startswith("/"):
        raise GitViewError("That file isn't in the project.")
    rel = rel.strip("/")
    parts = PurePosixPath(rel).parts if rel else ()
    if (not parts or "\x00" in rel or re.match(r"^[A-Za-z]:", rel) or any(p in ("..", "") for p in parts)
            or parts[0] == ".git"):
        raise GitViewError("That file isn't in the project.")
    return "/".join(parts)


def _need_repo(root: Path) -> None:
    if not is_repo(root):
        raise GitViewError("This project isn't kept in git yet, so it has no history to show.")


def _resolve(root: Path, rev: str) -> str:
    full = _out(root, "rev-parse", "--verify", "-q", rev + "^{commit}")
    if not full:
        raise GitViewError("That commit isn't in this project's history.")
    return full


# -- reading ----------------------------------------------------------------------------------------
def kind_of(subject: str, body: str = "") -> tuple[str, str]:
    """(kind, task id): task, hand, put_back, undo, merge or other."""
    m = _TASK.match(subject)
    if m:
        return "task", m.group(1)
    if subject.startswith(HAND_PREFIX):
        return "hand", ""
    if subject.startswith(PUT_BACK_PREFIX):
        return "put_back", ""
    if subject.startswith("Revert ") or _REVERTS.search(body or ""):
        return "undo", ""
    if subject.startswith("Merge "):
        return "merge", ""
    return "other", ""


def log(root: str | Path, branch: str = "", limit: int = 50, skip: int = 0) -> dict[str, Any]:
    """The newest commits first (of ``branch``, or of where the project is now)."""
    root = Path(root)
    rev = check_branch(branch) if branch else "HEAD"
    _need_repo(root)
    if branch:
        _resolve(root, f"refs/heads/{rev}")
        rev = f"refs/heads/{rev}"
    limit = max(1, min(int(limit or 50), LOG_MAX))
    skip = max(0, int(skip or 0))
    res = _git(root, "log", f"--max-count={limit + 1}", f"--skip={skip}",
               "--format=%H%x1f%P%x1f%an%x1f%cI%x1f%s%x1f%b%x1e", rev, "--")
    rows: list[dict[str, Any]] = []
    for rec in _text(res).split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        p = rec.split("\x1f")
        if len(p) < 5:
            continue
        kind, task = kind_of(p[4], p[5] if len(p) > 5 else "")
        rows.append({"sha": p[0], "short": p[0][:7], "parents": p[1].split(), "author": p[2], "at": p[3],
                     "subject": p[4], "kind": kind, "task": task})
    more = len(rows) > limit
    return {"branch": branch or current_branch(root), "commits": rows[:limit], "more": more, "skip": skip}


def current_branch(root: Path) -> str:
    return _out(Path(root), "symbolic-ref", "--short", "-q", "HEAD")


def _numstat(root: Path, *rev: str) -> dict[str, tuple[int | None, int | None]]:
    res = _git(root, *rev)
    out: dict[str, tuple[int | None, int | None]] = {}
    for line in _text(res).splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        a, d, path = parts[0], parts[1], parts[-1]
        out[path] = (None if a == "-" else int(a), None if d == "-" else int(d))
    return out


def _status(root: Path, *rev: str) -> list[dict[str, str]]:
    res = _git(root, *rev)
    rows = []
    for line in _text(res).splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not parts[0]:
            continue
        code = parts[0][0]
        row = {"path": parts[-1], "change": _CHANGE.get(code, "changed")}
        if code in "RC" and len(parts) >= 3:
            row["from"] = parts[1]
        rows.append(row)
    return rows


def _files(root: Path, base: list[str]) -> list[dict[str, Any]]:
    counts = _numstat(root, *base[:1], "--numstat", *base[1:])
    rows = _status(root, *base[:1], "--name-status", *base[1:])
    for r in rows:
        a, d = counts.get(r["path"], (0, 0))
        r["binary"] = a is None
        r["added"], r["removed"] = a or 0, d or 0
    return rows[:FILES_MAX]


def commit(root: str | Path, sha: str) -> dict[str, Any]:
    """One commit: who, when, its message, and each file it changed with the lines added and removed."""
    root = Path(root)
    sha = check_sha(sha)
    _need_repo(root)
    full = _resolve(root, sha)
    head = _text(_git(root, "show", "-s", "--format=%H%x1f%P%x1f%an%x1f%cI%x1f%s%x1f%b", full)).rstrip("\n")
    p = head.split("\x1f")
    parents = p[1].split() if len(p) > 1 else []
    kind, task = kind_of(p[4] if len(p) > 4 else "", p[5] if len(p) > 5 else "")
    base = ["diff-tree", "-r", "--root", "--no-commit-id", "-M", full] if len(parents) <= 1 else \
        ["diff", "-M", parents[0], full]
    files = _files(root, base)
    return {"sha": full, "short": full[:7], "parents": parents, "author": p[2] if len(p) > 2 else "",
            "at": p[3] if len(p) > 3 else "", "subject": p[4] if len(p) > 4 else "",
            "body": (p[5] if len(p) > 5 else "").strip(), "kind": kind, "task": task, "files": files,
            "added": sum(f["added"] for f in files), "removed": sum(f["removed"] for f in files)}


def parse_diff(text: str) -> list[dict[str, Any]]:
    """Unified diff text as lines: {kind: add | del | same | hunk, text, old, new} (line numbers where known)."""
    out: list[dict[str, Any]] = []
    old = new = 0
    started = False
    for line in text.splitlines():
        if line.startswith("@@"):
            m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)", line)
            if m:
                old, new = int(m.group(1)), int(m.group(2))
            out.append({"kind": "hunk", "text": line})
            started = True
            continue
        if not started:
            continue  # the header lines (diff --git, index, ---, +++)
        if line.startswith("+"):
            out.append({"kind": "add", "text": line[1:], "new": new})
            new += 1
        elif line.startswith("-"):
            out.append({"kind": "del", "text": line[1:], "old": old})
            old += 1
        elif line.startswith("\\"):
            continue  # "\ No newline at end of file"
        else:
            out.append({"kind": "same", "text": line[1:], "old": old, "new": new})
            old += 1
            new += 1
    return out


def diff(root: str | Path, sha: str, file: str) -> dict[str, Any]:
    """One file's change in one commit, as lines."""
    root = Path(root)
    sha, rel = check_sha(sha), check_file(file)
    _need_repo(root)
    full = _resolve(root, sha)
    parents = _out(root, "show", "-s", "--format=%P", full).split()
    if parents:
        res = _git(root, "diff", "-M", "--no-color", "--no-ext-diff", parents[0], full, "--", rel)
    else:
        res = _git(root, "show", "--format=", "--no-color", "--no-ext-diff", full, "--", rel)
    text = _text(res)
    binary = "Binary files" in text[:2000] and "@@" not in text[:2000]
    too_big = len(text) > DIFF_MAX
    return {"sha": full, "file": rel, "binary": binary, "too_big": too_big,
            "lines": [] if binary else parse_diff(text[:DIFF_MAX])}


def branches(root: str | Path) -> dict[str, Any]:
    root = Path(root)
    _need_repo(root)
    res = _git(root, "for-each-ref", "--sort=-committerdate",
               "--format=%(refname:short)%1f%(objectname)%1f%(committerdate:iso-strict)%1f%(subject)", "refs/heads/")
    cur = current_branch(root)
    rows = []
    for line in _text(res).splitlines():
        p = line.split("\x1f")
        if len(p) >= 4:
            rows.append({"name": p[0], "sha": p[1], "short": p[1][:7], "at": p[2], "subject": p[3],
                         "current": p[0] == cur})
    return {"current": cur, "branches": rows}


def compare(root: str | Path, a: str, b: str) -> dict[str, Any]:
    """How branch ``b`` differs from branch ``a``: commits only on each side, and the files that differ."""
    root = Path(root)
    a, b = check_branch(a), check_branch(b)
    _need_repo(root)
    ra, rb = _resolve(root, f"refs/heads/{a}"), _resolve(root, f"refs/heads/{b}")
    counts = _out(root, "rev-list", "--left-right", "--count", f"{ra}...{rb}").split()
    only_a, only_b = (int(counts[0]), int(counts[1])) if len(counts) == 2 else (0, 0)
    return {"a": a, "b": b, "only_a": only_a, "only_b": only_b, "files": _files(root, ["diff", "-M", ra, rb])}


# -- the tree as it is now --------------------------------------------------------------------------------
def dirty(root: Path) -> list[str]:
    """Tracked files changed and not committed (untracked files don't count: git keeps those safe itself)."""
    res = _git(Path(root), "status", "--porcelain=v1", "--untracked-files=no")
    return [line[3:] for line in _text(res).splitlines() if line.strip()]


def _in_the_middle(root: Path) -> bool:
    g = Path(root) / ".git"
    return g.is_dir() and any((g / n).exists() for n in ("MERGE_HEAD", "REVERT_HEAD", "CHERRY_PICK_HEAD",
                                                         "rebase-merge", "rebase-apply"))


def ignored(root: Path, rel: str) -> bool:
    return _git(Path(root), "check-ignore", "-q", "--", rel).returncode == 0


def tracked(root: Path, rel: str) -> bool:
    """The file is in the last commit (a hand edit of it can be put back from the history)."""
    head = _out(Path(root), "rev-parse", "--verify", "-q", "HEAD")
    return bool(head) and bool(_blob_of(Path(root), head, check_file(rel)))


def _blob_of(root: Path, rev: str, rel: str) -> str:
    return _out(root, "rev-parse", "--verify", "-q", f"{rev}:{rel}")


def _mode_of(root: Path, rev: str, rel: str) -> str:
    line = _out(root, "ls-tree", rev, "--", rel)
    return line.split(" ", 1)[0] if line else "100644"


def _commit_blob(root: Path, rel: str, blob: str, mode: str, message: str, head: str) -> str:
    """A commit on top of ``head`` that changes only ``rel`` (to ``blob``), moved onto the branch only if the
    branch is still at ``head``; the real index entry for ``rel`` follows."""
    fd, idx = tempfile.mkstemp(prefix="rt-edit-index-")
    os.close(fd)
    try:
        env = {**clean_env(), "GIT_INDEX_FILE": idx}
        _git(root, "read-tree", head, env=env, check=True)
        _git(root, "update-index", "--add", "--cacheinfo", f"{mode},{blob},{rel}", env=env, check=True)
        tree = _git(root, "write-tree", env=env, check=True).stdout.decode().strip()
    finally:
        try:
            os.unlink(idx)
        except OSError:
            pass
    new = _git(root, "commit-tree", tree, "-p", head, data=message.encode("utf-8"), check=True).stdout.decode().strip()
    res = _git(root, "update-ref", "-m", message.splitlines()[0], "HEAD", new, head)
    if res.returncode != 0:
        raise GitViewError("The project moved on while this was being saved. The file is saved; press Save again "
                           "to keep it in the history.")
    _git(root, "update-index", "--cacheinfo", f"{mode},{blob},{rel}")  # the real index agrees for this file only
    return new


def commit_file(root: str | Path, rel: str, message: str = "") -> str:
    """One commit of ``rel`` exactly as it is on disk now ("Edited by hand: <file>"); "" when it didn't change."""
    root = Path(root)
    rel = check_file(rel)
    head = _out(root, "rev-parse", "--verify", "-q", "HEAD")
    if not head:
        raise GitViewError("This project's git history is empty, so the edit can't be kept there.")
    blob = _git(root, "hash-object", "-w", "--", rel, check=True).stdout.decode().strip()
    if blob == _blob_of(root, head, rel):
        return ""
    return _commit_blob(root, rel, blob, _mode_of(root, head, rel), message or HAND_PREFIX + rel, head)


def hand_edits(root: str | Path, limit: int = 30) -> list[dict[str, Any]]:
    """The newest hand edits first, with whether each has been put back."""
    root = Path(root)
    if not is_repo(root):
        return []
    res = _git(root, "log", "--first-parent", "--max-count=400", "--format=%H%x1f%cI%x1f%s%x1f%b%x1e", "HEAD")
    rows, undone = [], set()
    for rec in _text(res).split("\x1e"):
        rec = rec.strip("\n")
        p = rec.split("\x1f")
        if len(p) < 3:
            continue
        undone.update(_REVERTS.findall(p[3] if len(p) > 3 else ""))
        if p[2].startswith(HAND_PREFIX):
            rows.append({"sha": p[0], "short": p[0][:7], "at": p[1], "file": p[2][len(HAND_PREFIX):]})
    for r in rows:
        r["undone"] = r["sha"] in undone
    return rows[:limit]


def undo_edit(root: str | Path, sha: str) -> dict[str, Any]:
    """Put a file back as it was before one hand edit, if the file hasn't changed since that edit."""
    root = Path(root)
    sha = check_sha(sha)
    _need_repo(root)
    full = _resolve(root, sha)
    subject = _out(root, "show", "-s", "--format=%s", full)
    if not subject.startswith(HAND_PREFIX):
        raise GitViewError("Only an edit made by hand can be put back here. Task changes are undone on the "
                           "History of tasks (Undo).")
    rel = check_file(subject[len(HAND_PREFIX):])
    parent = _out(root, "rev-parse", "--verify", "-q", full + "^")
    old_blob, new_blob = _blob_of(root, parent, rel), _blob_of(root, full, rel)
    if not old_blob:
        raise GitViewError("This file didn't exist before that edit, so there's nothing to put back.")
    now_blob = _git(root, "hash-object", "--", rel).stdout.decode().strip() if (root / rel).is_file() else ""
    if now_blob != new_blob:
        raise GitViewError("This file has changed since that edit, so putting it back would lose the newer "
                           "changes. Open the file and change it by hand instead.")
    if {r["sha"] for r in hand_edits(root) if r["undone"]} & {full}:
        raise GitViewError("That edit has already been put back.")
    head = _out(root, "rev-parse", "HEAD")
    data = _git(root, "cat-file", "--filters", f"{parent}:{rel}", check=True).stdout  # line endings as checked out
    target = root / rel
    target.write_bytes(data)
    message = f"{PUT_BACK_PREFIX}{rel}\n\nThis reverts commit {full}.\n"
    new = _commit_blob(root, rel, old_blob, _mode_of(root, head, rel), message, head)
    return {"ok": True, "commit": new, "file": rel, "words": f"{rel} is back as it was before that edit."}


# -- switching branch ------------------------------------------------------------------------------------
def _stamp(root: Path, branch: str) -> str:
    head = _out(root, "rev-parse", "HEAD")
    target = _out(root, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")
    return hashlib.sha256(f"{head}|{branch}|{target}".encode()).hexdigest()[:16]


def _checkout_block(root: Path, branch: str) -> str:
    if _in_the_middle(root):
        return "Git is in the middle of a merge in this project. Finish or cancel it first."
    left = dirty(root)
    if left:
        return (f"{len(left)} file{'s are' if len(left) != 1 else ' is'} changed and not kept yet "
                f"({', '.join(left[:3])}). Save or undo those changes first, so nothing is lost.")
    if branch == current_branch(root):
        return "The project is on that branch already."
    return ""


def checkout_preview(root: str | Path, branch: str) -> dict[str, Any]:
    """What switching to ``branch`` would change, and whether it can be done now; nothing changes."""
    root = Path(root)
    branch = check_branch(branch)
    _need_repo(root)
    target = _resolve(root, f"refs/heads/{branch}")
    files = _files(root, ["diff", "-M", "HEAD", target])
    block = _checkout_block(root, branch)
    n = len(files)
    words = (f"Switching to {branch} changes {n} file{'s' if n != 1 else ''}. Where it is now is kept, so you "
             "can come back.") if n else f"Switching to {branch} changes no files."
    return {"branch": branch, "from": current_branch(root), "files": files, "blocked": block,
            "words": block or words, "stamp": "" if block else _stamp(root, branch)}


def checkout(root: str | Path, branch: str, stamp: str) -> dict[str, Any]:
    """Switch to ``branch``, only with the preview's ``stamp`` and a clean tree; a snapshot is kept first."""
    from . import rewind

    root = Path(root)
    branch = check_branch(branch)
    _need_repo(root)
    _resolve(root, f"refs/heads/{branch}")
    block = _checkout_block(root, branch)
    if block:
        raise GitViewError(block)
    if not stamp or stamp != _stamp(root, branch):
        raise GitViewError("The project changed since you looked. Look at what will change again, then switch.")
    snap = rewind.snapshot_commit(root, "harness: snapshot before switching branch")
    ref = rewind.REF_PREFIX + rewind._ref_stamp()
    _git(root, "update-ref", ref, snap, check=True)
    res = _git(root, "checkout", "-q", branch, "--")
    if res.returncode != 0:
        err = (res.stderr or res.stdout).decode("utf-8", "replace").strip()
        raise GitViewError(f"Git couldn't switch branch: {err[:300]}")
    return {"ok": True, "branch": branch, "kept": ref, "words": f"The project is on {branch} now."}


__all__ = ["GitViewError", "branches", "check_branch", "check_file", "check_sha", "checkout", "checkout_preview",
           "commit", "commit_file", "compare", "current_branch", "diff", "dirty", "hand_edits", "ignored", "is_repo",
           "kind_of", "log", "tracked", "parse_diff", "undo_edit"]
