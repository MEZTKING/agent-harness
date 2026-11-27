"""Undo a task, put the project back to before it, try another way from any task, and the history.

What each finished task changed comes from git (the commit whose subject starts ``[<task id>]``, on the
project's branch, first parents only, so a task that ran in its own worktree counts once, as its merge) and
from ``.harness/tasks.json`` (``base_commit``: where the task started).

Two ways back, both shown first (``preview``) and done only with the preview's ``stamp`` (``apply``):

- ``undo_task``: a ``git revert`` of that task's commit. Later work stays. A clash means it is refused and
  nothing changes. The task goes back to "to do".
- ``back_to_before``: the project as it was before the task started (its ``base_commit``). The task and every
  later one go back to "to do"; their attempts move to ``previous_attempts``. Refused when a commit it would
  drop has been pushed (``git branch -r --contains``): undoing the task alone is offered instead.

Nothing is ever deleted:

- before any change, the project as it is now (the owner's own edits too, as a snapshot commit made with a
  separate index, so nothing is touched to make it) is kept under ``refs/roundtable/undo/<utc>``;
- copies of ``tasks.json`` and ``project.json`` go in ``.harness/rewinds/<id>/``;
- a line goes in ``.harness/rewinds.jsonl``;
- ``undo_last`` ("Put it back") restores the last one from those, and keeps the state it replaces the same way.
  Your own edits made after a task survive ``back_to_before`` when they still fit; when they don't, they are
  in the kept snapshot and come back with Put it back.

Refused while a job runs on the project (``busy``), while another machine builds it (``elsewhere``), while a
kept task worktree has unsaved work, or while git is in the middle of a merge or revert.

``fork`` starts a copy of the project at any task's commit (``git clone --local --no-hardlinks``) with the
plan, the task list trimmed to that point and the project's settings; its spend starts at 0, it records
``forked_from`` and costs nothing until it is run.

``expired_refs`` / ``drop_ref`` are for the tidy-up (retention.py): the kept ways back are 30 days old
before they are offered for tidying; only refs under ``refs/roundtable/undo/`` are ever dropped.
Every git call runs with ``clean_env()``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .safeenv import clean_env
from .worktrees import WORKTREES, Worktrees

REF_PREFIX = "refs/roundtable/undo/"
LOG_FILE = "rewinds.jsonl"
COPIES_DIR = "rewinds"
MODES = ("undo_task", "back_to_before")
SNAPSHOT_MESSAGE = "harness: snapshot before undo"
KEEP_DAYS = 30
_SUBJECT = re.compile(r"^\[([^\]]+)\] ")
_REVERTS = re.compile(r"This reverts commit ([0-9a-f]{40})")
_CHANGE = {"A": "added", "M": "changed", "D": "removed", "R": "renamed", "C": "copied", "T": "changed"}
# the project's settings worth copying into a fork (spend, status and the hub's records start afresh)
FORK_META_KEYS = ("goals", "title", "require_approval", "plan_approved", "references", "profile", "guidance")
FORK_FILES = ("plan.json", "plan.md", "project.yaml")


class RewindError(RuntimeError):
    """A rewind refused, in words for the owner."""


# -- git -----------------------------------------------------------------------------------------
def _git(root: Path, *args: str, env: dict[str, str] | None = None, check: bool = False) -> subprocess.CompletedProcess:
    res = subprocess.run(
        ["git", "-c", "user.name=agent-harness", "-c", "user.email=harness@localhost", "-c", "commit.gpgsign=false",
         *args],
        cwd=str(root), capture_output=True, text=True, env=env or clean_env(), encoding="utf-8", errors="replace")
    if check and res.returncode != 0:
        raise RewindError(f"git {args[0]} didn't work: {(res.stderr or res.stdout).strip()[:400]}")
    return res


def _out(root: Path, *args: str) -> str:
    res = _git(root, *args)
    return res.stdout.strip() if res.returncode == 0 else ""


def is_repo(root: Path) -> bool:
    return (Path(root) / ".git").exists() and bool(_out(Path(root), "rev-parse", "--verify", "-q", "HEAD"))


def _head(root: Path) -> str:
    return _out(root, "rev-parse", "HEAD")


def _tree(root: Path, rev: str) -> str:
    return _out(root, "rev-parse", f"{rev}^{{tree}}")


def _is_ancestor(root: Path, a: str, b: str) -> bool:
    return _git(root, "merge-base", "--is-ancestor", a, b).returncode == 0


def _short(sha: str) -> str:
    return sha[:7]


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ref_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def snapshot_commit(root: Path, message: str = SNAPSHOT_MESSAGE) -> str:
    """A commit of the files as they are now (the owner's edits and new files too, ignored ones not), made
    through a separate index so neither the files nor git's own index are touched. HEAD when nothing differs."""
    head = _head(root)
    fd, idx = tempfile.mkstemp(prefix="rt-undo-index-")
    os.close(fd)
    try:
        env = {**clean_env(), "GIT_INDEX_FILE": idx}
        _git(root, "read-tree", head, env=env, check=True)
        _git(root, "add", "-A", env=env, check=True)
        tree = _git(root, "write-tree", env=env, check=True).stdout.strip()
    finally:
        try:
            os.unlink(idx)
        except OSError:
            pass
    if tree == _tree(root, head):
        return head
    return _git(root, "commit-tree", tree, "-p", head, "-m", message, check=True).stdout.strip()


def _changes(root: Path, a: str, b: str) -> list[dict[str, str]]:
    """The files that differ from ``a`` to ``b``: [{path, change}] (added, changed, removed, renamed)."""
    res = _git(root, "diff", "--name-status", "-M", "--no-color", a, b)
    return _parse_status(res.stdout if res.returncode == 0 else "")


def _parse_status(text: str) -> list[dict[str, str]]:
    out = []
    for ln in text.splitlines():
        parts = ln.split("\t")
        if len(parts) < 2:
            continue
        kind = _CHANGE.get(parts[0][:1], "changed")
        row = {"path": parts[-1], "change": kind}
        if kind in ("renamed", "copied") and len(parts) >= 3:
            row["from"] = parts[1]
        out.append(row)
    return out


def _commit_files(root: Path, sha: str) -> list[dict[str, str]]:
    parent = _out(root, "rev-parse", "--verify", "-q", f"{sha}^1")
    if parent:
        return _changes(root, parent, sha)
    res = _git(root, "diff-tree", "--root", "-r", "--no-commit-id", "--name-status", sha)
    return _parse_status(res.stdout)


def _pushed(root: Path, sha: str) -> bool:
    return bool(_out(root, "branch", "-r", "--contains", sha))


def _pushed_in(root: Path, base: str, head: str) -> list[str]:
    """Commits after ``base`` up to ``head`` that some remote branch already has."""
    all_ = _out(root, "rev-list", f"{base}..{head}").split()
    if not all_:
        return []
    local = set(_out(root, "rev-list", f"{base}..{head}", "--not", "--remotes").split())
    return [c for c in all_ if c not in local]


# -- the project's records -------------------------------------------------------------------------
def _hdir(root: Path) -> Path:
    return Path(root) / ".harness"


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default
    except (OSError, ValueError):
        return default


def _write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(p)


def _tasks(root: Path) -> list[dict[str, Any]]:
    return _read_json(_hdir(root) / "tasks.json", [])


def _tasks_bytes(root: Path) -> bytes:
    p = _hdir(root) / "tasks.json"
    try:
        return p.read_bytes()
    except OSError:
        return b""


def entries(root: Path) -> list[dict[str, Any]]:
    """Every line of ``.harness/rewinds.jsonl``, oldest first."""
    p = _hdir(root) / LOG_FILE
    if not p.is_file():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def _log(root: Path, row: dict[str, Any]) -> None:
    p = _hdir(root) / LOG_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def stamp(root: Path) -> str:
    """What the project is right now: HEAD, the task list and the files' state. A preview carries it, and
    ``apply`` refuses when it has changed since."""
    root = Path(root)
    h = hashlib.sha256()
    h.update(_head(root).encode())
    h.update(b"\0")
    h.update(_tasks_bytes(root))
    h.update(b"\0")
    h.update(_out(root, "status", "--porcelain", "-uall").encode())
    return h.hexdigest()[:20]


# -- history ---------------------------------------------------------------------------------------
@dataclass
class _Commit:
    sha: str
    subject: str
    at: str
    body: str


def _first_parent_log(root: Path) -> list[_Commit]:
    res = _git(root, "log", "--first-parent", "--format=%H%x1f%s%x1f%cI%x1f%b%x1e", "HEAD")
    out = []
    for rec in res.stdout.split("\x1e") if res.returncode == 0 else []:
        rec = rec.strip("\n")
        if not rec:
            continue
        parts = rec.split("\x1f")
        if len(parts) >= 3:
            out.append(_Commit(parts[0].strip(), parts[1], parts[2], parts[3] if len(parts) > 3 else ""))
    return out


def _task_commits(root: Path) -> tuple[dict[str, list[_Commit]], set[str]]:
    """Each task's commits on the branch, newest first, and the commits undone by a later revert."""
    by_task: dict[str, list[_Commit]] = {}
    reverted: set[str] = set()
    for c in _first_parent_log(root):
        reverted.update(_REVERTS.findall(c.body))
        m = _SUBJECT.match(c.subject)
        if m:
            by_task.setdefault(m.group(1), []).append(c)
    return by_task, reverted


def _live_commit(by_task, reverted, task_id: str) -> _Commit | None:
    return next((c for c in by_task.get(task_id, []) if c.sha not in reverted), None)


def _words(row: dict[str, Any]) -> str:
    n = len(row["files"])
    if row["undone"]:
        return "Undone."
    if not row["commit"]:
        return "Changed no files."
    files = f"Changed {n} file{'s' if n != 1 else ''}" if n else "Changed no files"
    return files + (" (already sent to GitHub)." if row["pushed"] else ".")


def history(root: str | Path) -> list[dict[str, Any]]:
    """One row per finished task, in the task list's order: what it changed, and whether it was pushed."""
    root = Path(root)
    tasks = _tasks(root)
    git = is_repo(root)
    by_task, reverted = _task_commits(root) if git else ({}, set())
    rows = []
    for t in tasks:
        tid = str(t.get("id") or "")
        mine = by_task.get(tid, [])
        if t.get("status") != "done" and not mine:
            continue
        live = _live_commit(by_task, reverted, tid)
        shown = live or (mine[0] if mine else None)
        row = {
            "id": tid, "title": t.get("title") or tid, "role": t.get("role", ""), "status": t.get("status", ""),
            "summary": str(t.get("summary") or "")[:400],
            "commit": shown.sha if shown else "", "short": _short(shown.sha) if shown else "",
            "at": shown.at if shown else "",
            "files": _commit_files(root, shown.sha) if shown else [],
            "pushed": bool(live and _pushed(root, live.sha)),
            "undone": bool(mine) and live is None,
            "can_undo": bool(live), "can_go_back": bool(t.get("base_commit")) and git,
        }
        row["words"] = _words(row)
        rows.append(row)
    return rows


def last_rewind(root: str | Path) -> dict[str, Any] | None:
    """The newest rewind not yet put back, with whether Put it back can be done now."""
    root = Path(root)
    rows = entries(root)
    put_back = {r.get("of") for r in rows if r.get("kind") == "put_back"}
    last = next((r for r in reversed(rows) if r.get("kind") == "rewind" and r.get("id") not in put_back), None)
    if last is None:
        return None
    why = ""
    if is_repo(root) and _head(root) != last.get("head_after"):
        why = "Work has carried on since, so it can't simply be put back. Everything is still kept safe."
    if last is not rows[-1] and not why:
        why = "Something else has been put back since."
    return {"id": last.get("id"), "at": last.get("at"), "mode": last.get("mode"), "task": last.get("task"),
            "title": last.get("title", ""), "words": _rewind_words(last), "can_put_back": not why, "why_not": why,
            "files": last.get("files", [])}


def _rewind_words(r: dict[str, Any]) -> str:
    title = r.get("title") or r.get("task")
    if r.get("mode") == "undo_task":
        return f"Undid “{title}”."
    return f"Went back to before “{title}”."


# -- guards ----------------------------------------------------------------------------------------
def _unsaved_worktrees(root: Path) -> list[str]:
    d = root / WORKTREES
    if not d.is_dir():
        return []
    trees = Worktrees(root)
    out = []
    for p in sorted(d.iterdir()):
        if p.is_dir() and trees.exists(p.name) and trees.dirty(p.name) is not False:
            out.append(p.name)
    return out


def _in_the_middle(root: Path) -> bool:
    g = root / ".git"
    return g.is_dir() and any((g / n).exists() for n in ("MERGE_HEAD", "REVERT_HEAD", "CHERRY_PICK_HEAD",
                                                         "rebase-merge", "rebase-apply"))


def guard(root: Path, busy: bool = False, elsewhere: str = "") -> str:
    """Why nothing may change the project right now ("" when it may)."""
    if busy:
        return "Roundtable is working on this project right now. Wait for it to finish or stop it, then try again."
    if elsewhere:
        return elsewhere
    if not is_repo(root):
        return "This project isn't kept in git, so there's no way back to an earlier state."
    if _in_the_middle(root):
        return "Git is in the middle of a merge in this project. Finish or cancel it first."
    left = _unsaved_worktrees(root)
    if left:
        return (f"Unsaved work is waiting in the copy for task {', '.join(left[:3])}. Run the project or finish "
                "that task first, so nothing is lost.")
    return ""


# -- preview and apply ---------------------------------------------------------------------------------
def _find(tasks: list[dict[str, Any]], task_id: str) -> dict[str, Any]:
    t = next((t for t in tasks if str(t.get("id")) == str(task_id)), None)
    if t is None:
        raise RewindError("That task isn't in this project's list.")
    return t


def _dropped(root: Path, base: str, head: str) -> set[str]:
    return set(_out(root, "rev-list", f"{base}..{head}").split())


def _back_to_todo(root: Path, tasks, target: dict[str, Any], mode: str, base: str) -> list[str]:
    """The tasks that go back to "to do" (ids, in list order)."""
    if mode == "undo_task":
        return [str(target["id"])]
    dropped = _dropped(root, base, _head(root))
    by_task, _ = _task_commits(root)
    out = []
    for t in tasks:
        tid = str(t.get("id"))
        if tid == str(target["id"]):
            out.append(tid)
        elif t.get("status") == "pending" and not t.get("attempts"):
            continue
        elif any(c.sha in dropped for c in by_task.get(tid, [])) or (t.get("base_commit") or "") in dropped:
            out.append(tid)
    return out


class _Scratch:
    """A throwaway worktree outside the project (detached), to try a change without touching anything."""

    def __init__(self, root: Path, rev: str):
        self.root, self.rev = root, rev
        self.path = Path(tempfile.mkdtemp(prefix="rt-undo-try-")) / "w"

    def __enter__(self) -> Path:
        _git(self.root, "worktree", "add", "-q", "--detach", str(self.path), self.rev, check=True)
        return self.path

    def __exit__(self, *exc) -> None:
        _git(self.root, "worktree", "remove", "--force", str(self.path))
        shutil.rmtree(self.path.parent, ignore_errors=True)
        _git(self.root, "worktree", "prune")


def _conflicts(p: Path) -> list[str]:
    return [ln for ln in _out(p, "diff", "--name-only", "--diff-filter=U").splitlines() if ln.strip()]


def _revert_args(root: Path, sha: str) -> list[str]:
    parents = _out(root, "rev-list", "--parents", "-n", "1", sha).split()[1:]
    return ["-m", "1"] if len(parents) > 1 else []


def _try_revert(root: Path, rev: str, commit: str) -> tuple[str, list[str]]:
    """The tree a revert of ``commit`` on top of ``rev`` leaves, or ("", clashing files)."""
    with _Scratch(root, rev) as w:
        res = _git(w, "revert", "--no-commit", *_revert_args(root, commit), commit)
        clash = _conflicts(w)
        if res.returncode != 0 or clash:
            return "", clash or ["(git refused)"]
        return _git(w, "write-tree", check=True).stdout.strip(), []


def _simulate(root: Path, mode: str, snap: str, head: str, commit: str, base: str) -> dict[str, Any]:
    """What the change would leave, worked out in scratch worktrees: {ok, conflicts, tree (the files after),
    commit_tree (what is committed: the files without the owner's own edits), hand_edits_kept}."""
    if mode == "undo_task":
        committed, clash = _try_revert(root, head, commit)
        if not committed:
            return {"ok": False, "conflicts": clash, "tree": "", "commit_tree": "", "hand_edits_kept": True}
        if snap == head:
            return {"ok": True, "conflicts": [], "tree": committed, "commit_tree": committed, "hand_edits_kept": True}
        files, clash = _try_revert(root, snap, commit)
        if not files:
            return {"ok": False, "conflicts": clash, "tree": "", "commit_tree": "", "hand_edits_kept": True,
                    "own_edits": True}
        return {"ok": True, "conflicts": [], "tree": files, "commit_tree": committed, "hand_edits_kept": True}
    # back_to_before: the base, with the owner's own edits on top when they still fit
    base_tree = _tree(root, base)
    if snap == head:
        return {"ok": True, "conflicts": [], "tree": base_tree, "commit_tree": base_tree, "hand_edits_kept": True}
    with _Scratch(root, base) as w:
        res = _git(w, "cherry-pick", "--no-commit", snap)
        if res.returncode != 0 or _conflicts(w):
            return {"ok": True, "conflicts": [], "tree": base_tree, "commit_tree": base_tree, "hand_edits_kept": False}
        tree = _git(w, "write-tree", check=True).stdout.strip()
        return {"ok": True, "conflicts": [], "tree": tree, "commit_tree": base_tree, "hand_edits_kept": True}


def _tree_changes(root: Path, a: str, tree: str) -> list[dict[str, str]]:
    res = _git(root, "diff-tree", "-r", "-M", "--name-status", "--no-commit-id", a, tree)
    return _parse_status(res.stdout if res.returncode == 0 else "")


def _undo_words(changes: list[dict[str, str]]) -> list[dict[str, str]]:
    """The same list, each with a plain word of what happens to it."""
    say = {"added": "comes back", "removed": "goes", "changed": "goes back to how it was",
           "renamed": "gets its old name back", "copied": "comes back"}
    return [{**c, "words": say.get(c["change"], "changes")} for c in changes]


def preview(root: str | Path, task_id: str, mode: str, busy: bool = False, elsewhere: str = "") -> dict[str, Any]:
    out = _preview(root, task_id, mode, busy, elsewhere)
    out.pop("_sim", None)
    return out


def _preview(root: str | Path, task_id: str, mode: str, busy: bool = False, elsewhere: str = "") -> dict[str, Any]:
    """What ``apply`` would do, without changing anything: {mode, task, title, files, back_to_todo, blocked,
    offer, stamp, hand_edits, hand_edits_kept, words}. ``blocked`` says why it can't be done ("" when it can)."""
    root = Path(root)
    if mode not in MODES:
        raise RewindError("Choose Undo this task or Go back to before it.")
    tasks = _tasks(root)
    t = _find(tasks, task_id)
    out: dict[str, Any] = {"mode": mode, "task": str(t["id"]), "title": t.get("title") or str(t["id"]),
                           "files": [], "back_to_todo": [], "blocked": "", "offer": "", "stamp": stamp(root),
                           "hand_edits": [], "hand_edits_kept": True}
    why = guard(root, busy, elsewhere)
    if why:
        out["blocked"] = why
        return _finish(out)
    head = _head(root)
    by_task, reverted = _task_commits(root)
    live = _live_commit(by_task, reverted, str(t["id"]))
    base = str(t.get("base_commit") or "")
    if mode == "undo_task":
        if live is None:
            out["blocked"] = ("This task has already been undone." if by_task.get(str(t["id"]))
                              else "This task changed no files, so there's nothing to undo.")
            return _finish(out)
        commit = live.sha
    else:
        if not base or not _out(root, "rev-parse", "--verify", "-q", f"{base}^{{commit}}"):
            out["blocked"] = "Roundtable didn't note where this task started, so it can't go back to before it."
            return _finish(out)
        if not _is_ancestor(root, base, head):
            out["blocked"] = "The project has moved on another way since this task started, so it can't go back there."
            return _finish(out)
        pushed = _pushed_in(root, base, head)
        if pushed:
            out["blocked"] = ("Some of this work has already been sent to GitHub, so going back would lose it there. "
                              "Undo this task on its own instead: later work stays.")
            out["offer"] = "undo_task" if live else ""
            return _finish(out)
        commit = live.sha if live else ""
    snap = snapshot_commit(root)
    out["hand_edits"] = _changes(root, head, snap) if snap != head else []
    sim = _simulate(root, mode, snap, head, commit, base)
    if not sim["ok"]:
        out["blocked"] = (("Your own edits since change the same lines this task did. Save them elsewhere or put them "
                           "back first, then try again. Nothing was changed.") if sim.get("own_edits") else
                          ("Later work changed the same lines, so this task can't be undone on its own. Nothing was "
                           "changed. Go back to before it instead, or ask for a fix-up task."))
        out["conflicts"] = sim["conflicts"]
        out["offer"] = "back_to_before" if base and not _pushed_in(root, base, head) else ""
        return _finish(out)
    out["files"] = _undo_words(_tree_changes(root, snap, sim["tree"]))
    out["hand_edits_kept"] = sim["hand_edits_kept"]
    out["back_to_todo"] = _back_to_todo(root, tasks, t, mode, base)
    out["_sim"] = sim
    return _finish(out)


def _finish(out: dict[str, Any]) -> dict[str, Any]:
    n = len(out["files"])
    if out["blocked"]:
        out["words"] = out["blocked"]
    elif out["mode"] == "undo_task":
        out["words"] = (f"Undo “{out['title']}”: {n} file{'s' if n != 1 else ''} change back. "
                        "Later work stays. You can put it back afterwards.")
    else:
        k = len(out["back_to_todo"])
        out["words"] = (f"Go back to before “{out['title']}”: {n} file{'s' if n != 1 else ''} change and "
                        f"{k} task{'s' if k != 1 else ''} go back to to-do. You can put it back afterwards.")
        if out["hand_edits"] and not out["hand_edits_kept"]:
            out["words"] += " Your own edits since don't fit there: they're kept safe and come back with Put it back."
    return out


def _new_id() -> str:
    return _ref_stamp()


def _keep(root: Path, rid: str, snap: str) -> tuple[str, dict[str, str]]:
    """The safety ref and the copies of the records, before anything changes."""
    ref = REF_PREFIX + rid
    _git(root, "update-ref", ref, snap, check=True)
    d = _hdir(root) / COPIES_DIR / rid
    d.mkdir(parents=True, exist_ok=True)
    copies = {}
    for name in ("tasks.json", "project.json"):
        src = _hdir(root) / name
        if src.is_file():
            shutil.copy2(src, d / name)
            copies[name] = str(Path(".harness") / COPIES_DIR / rid / name)
    return ref, copies


def _restore_exact(root: Path, snap: str, head: str) -> None:
    """The files exactly as in ``snap`` with the branch at ``head`` (the owner's edits uncommitted again)."""
    _git(root, "reset", "-q", "--hard", snap, check=True)
    if snap != head:
        _git(root, "reset", "-q", "--mixed", head, check=True)


def apply(root: str | Path, task_id: str, mode: str, stamp_: str, busy: bool = False,
          elsewhere: str = "") -> dict[str, Any]:
    """Do what ``preview`` showed. Refused (RewindError) when the stamp has changed or it is blocked."""
    root = Path(root)
    if not stamp_ or stamp_ != stamp(root):
        raise RewindError("The project has changed since you looked. Look at the list of files again, then try again.")
    pv = _preview(root, task_id, mode, busy, elsewhere)
    if pv["blocked"]:
        raise RewindError(pv["blocked"])
    tasks = _tasks(root)
    t = _find(tasks, task_id)
    head = _head(root)
    snap = snapshot_commit(root)
    rid = _new_id()
    ref, copies = _keep(root, rid, snap)  # nothing changes before this is kept
    sim = pv.pop("_sim")
    kept = sim["hand_edits_kept"]
    try:
        if mode == "undo_task":
            by_task, reverted = _task_commits(root)
            live = _live_commit(by_task, reverted, str(t["id"]))
            msg = f"Undo [{t['id']}] {t.get('title') or ''}".rstrip() + f"\n\nThis reverts commit {live.sha}.\n"
            parent = head
        else:
            msg, parent = "", str(t["base_commit"])
        new_head = (_git(root, "commit-tree", sim["commit_tree"], "-p", parent, "-m", msg, check=True).stdout.strip()
                    if msg else parent)
        files = new_head
        if sim["tree"] != sim["commit_tree"]:  # the owner's edits on top, left uncommitted as they were
            files = _git(root, "commit-tree", sim["tree"], "-p", new_head, "-m", SNAPSHOT_MESSAGE,
                         check=True).stdout.strip()
        if snap != head:
            _git(root, "reset", "-q", "--hard", snap, check=True)  # the owner's new files become tracked, so they move too
        _restore_exact(root, files, new_head)
    except Exception:
        _restore_exact(root, snap, head)
        raise
    back = pv["back_to_todo"]
    for task in tasks:
        if str(task.get("id")) in back:
            task["previous_attempts"] = list(task.get("previous_attempts") or []) + list(task.get("attempts") or [])
            task.update(status="pending", attempts=[], summary="", base_commit=None)
    _write_json(_hdir(root) / "tasks.json", tasks)
    meta_p = _hdir(root) / "project.json"
    meta = _read_json(meta_p, {})
    if meta:
        meta.pop("pause", None)
        meta.update(status="paused", updated_at=_utc(), rewound_at=_utc())
        _write_json(meta_p, meta)
    row = {"kind": "rewind", "id": rid, "at": _utc(), "mode": mode, "task": str(t["id"]),
           "title": t.get("title") or str(t["id"]), "ref": ref, "head_before": head, "snapshot": snap,
           "head_after": _head(root), "files": pv["files"], "back_to_todo": back, "hand_edits_kept": kept,
           "copies": copies}
    _log(root, row)
    return {"ok": True, "id": rid, "ref": ref, "files": pv["files"], "back_to_todo": back, "hand_edits_kept": kept,
            "words": _rewind_words(row) + " Put it back any time from the history."}


def undo_last(root: str | Path, busy: bool = False, elsewhere: str = "") -> dict[str, Any]:
    """Put it back: the project and its task list as they were before the last rewind. What it replaces is kept
    the same way (its own safety ref and copies), so this can be undone too."""
    root = Path(root)
    why = guard(root, busy, elsewhere)
    if why:
        raise RewindError(why)
    last = last_rewind(root)
    if last is None:
        raise RewindError("There's nothing to put back.")
    if not last["can_put_back"]:
        raise RewindError(last["why_not"])
    row = next(r for r in entries(root) if r.get("id") == last["id"])
    head = _head(root)
    snap = snapshot_commit(root)
    rid = _new_id()
    ref, copies = _keep(root, rid, snap)
    try:
        if snap != head:
            _git(root, "reset", "-q", "--hard", snap, check=True)
        _restore_exact(root, row["snapshot"], row["head_before"])
    except Exception:
        _restore_exact(root, snap, head)
        raise
    for name, rel in (row.get("copies") or {}).items():
        src = root / rel
        if src.is_file():
            shutil.copy2(src, _hdir(root) / name)
    _log(root, {"kind": "put_back", "id": rid, "of": row["id"], "at": _utc(), "ref": ref, "head_before": head,
                "snapshot": snap, "head_after": _head(root), "copies": copies})
    return {"ok": True, "id": rid, "ref": ref,
            "words": f"Put back: the project is as it was before “{row.get('title') or row.get('task')}” was undone."}


# -- try another way -------------------------------------------------------------------------------------
def _fork_tasks(root: Path, tasks: list[dict[str, Any]], commit: str) -> list[dict[str, Any]]:
    by_task, reverted = _task_commits(root)
    out = []
    for t in tasks:
        t = dict(t)
        live = _live_commit(by_task, reverted, str(t.get("id")))
        kept = t.get("status") == "done" and live is not None and _is_ancestor(root, live.sha, commit)
        if not kept:
            t.update(status="pending", summary="", base_commit=None)
        t["attempts"] = []
        t.pop("previous_attempts", None)
        out.append(t)
    return out


def safe_folder(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._ -]+", "", str(name or "")).strip().replace(" ", "-").strip(".-")
    return s[:60]


def fork(root: str | Path, task_id: str, name: str, projects_dir: str | Path) -> dict[str, Any]:
    """A copy of the project as it was when ``task_id`` was done, in ``projects_dir/<name>``, to try another
    way. The plan, the task list (later tasks back to to-do) and the project's settings come along; spend
    starts at 0, the event log starts empty, and nothing runs until the owner says so."""
    root = Path(root)
    if not is_repo(root):
        raise RewindError("This project isn't kept in git, so it can't be copied from a task.")
    folder = safe_folder(name)
    if not folder:
        raise RewindError("Give the copy a name (letters and numbers).")
    target = Path(projects_dir) / folder
    if target.exists():
        raise RewindError(f"There's already a folder called {folder}. Choose another name.")
    tasks = _tasks(root)
    t = _find(tasks, task_id)
    by_task, reverted = _task_commits(root)
    live = _live_commit(by_task, reverted, str(t["id"]))
    commit = live.sha if live else ""
    if not commit:
        raise RewindError("This task has no saved state of its own to start from. Choose a finished task.")
    target.parent.mkdir(parents=True, exist_ok=True)
    res = _git(target.parent, "clone", "-q", "--local", "--no-hardlinks", str(root), str(target))
    if res.returncode != 0:
        raise RewindError(f"Couldn't make the copy: {(res.stderr or res.stdout).strip()[:300]}")
    _git(target, "reset", "-q", "--hard", commit, check=True)
    _git(target, "remote", "remove", "origin")  # the copy is a project of its own, not a way to push into this one
    hd = _hdir(target)
    hd.mkdir(parents=True, exist_ok=True)
    for name_ in FORK_FILES:
        src = _hdir(root) / name_
        if src.is_file():
            shutil.copy2(src, hd / name_)
    _write_json(hd / "tasks.json", _fork_tasks(root, tasks, commit))
    meta = _read_json(_hdir(root) / "project.json", {})
    new_meta = {k: meta[k] for k in FORK_META_KEYS if k in meta}
    new_meta.update(status="paused", created_at=_utc(), updated_at=_utc(), spent_usd=0.0,
                    forked_from={"path": str(root), "name": root.name, "task": str(t["id"]),
                                 "title": t.get("title") or str(t["id"]), "commit": commit, "at": _utc()})
    _write_json(hd / "project.json", new_meta)
    return {"ok": True, "path": str(target), "name": folder, "commit": commit,
            "words": (f"Made “{folder}”: a copy as it was after “{t.get('title') or t['id']}”. "
                      "It costs nothing until you run it.")}


# -- the tidy-up -------------------------------------------------------------------------------------------
def refs(root: str | Path) -> list[dict[str, Any]]:
    """Every kept way back: [{ref, at (UTC datetime)}], oldest first."""
    res = _git(Path(root), "for-each-ref", "--format=%(refname)", REF_PREFIX)
    out = []
    for ref in res.stdout.split() if res.returncode == 0 else []:
        name = ref[len(REF_PREFIX):]
        try:
            at = datetime.strptime(name, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        out.append({"ref": ref, "at": at})
    return sorted(out, key=lambda r: r["at"])


def expired_refs(root: str | Path, days: int = KEEP_DAYS, now: datetime | None = None) -> list[str]:
    """The kept ways back older than ``days`` (for the tidy-up to offer; nothing is removed here)."""
    cut = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    return [r["ref"] for r in refs(root) if r["at"] < cut]


def drop_ref(root: str | Path, ref: str) -> bool:
    """Remove one kept way back (only ever a ref under ``refs/roundtable/undo/``)."""
    if not str(ref).startswith(REF_PREFIX) or ".." in str(ref):
        raise RewindError("Only Roundtable's own ways back can be tidied.")
    return _git(Path(root), "update-ref", "-d", ref).returncode == 0
