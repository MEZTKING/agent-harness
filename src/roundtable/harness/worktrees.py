"""Several tasks at once: each in a git worktree of its own, merged back in task order.

``limits.max_parallel`` (1 by default) says how many tasks may run together. Above 1, in a project kept
in git, every task whose depends-on are done gets:

- its own worktree ``.harness/worktrees/<task>`` on its own branch ``roundtable-task/<task>``, made from the
  project's current commit (a paused task's worktree is used again, so it carries on where it stopped);
- its own Workspace (the tools write there), its own token-saver spill and its own checks: setup is run
  in a new worktree, and the test command's baseline is the repository's when the worktree starts from
  the same commit, else one run there before the task changes anything (``checks.prepare_worktree``);
- when the review passes, a commit on its branch, and a merge into the project's branch – in task order,
  so a task never lands before one listed above it that is still running.

A merge that clashes is never forced: it is undone, and a small fix-up task for the same role is added
(``<task>-merge``): its worktree starts with the clash in the files (both sides' summaries in its
description), and the tasks that needed the first one wait for it too.

A worktree is removed only when git says it holds nothing uncommitted (the idea, not the code, is from
Munder Difflin's ``src/shared/worktreeFate.ts``: dirty is kept, and "can't tell" is kept too); every
worktree kept says why in the events (``worktree_kept``).

Stopping: the money limits (per run, per day, the real balance), losing the project's claim (sync.py) and
a stop asked for from outside (``stop_all``, e.g. the app's Stop) stop every task at its next step (the
breaker stops only the task it caught, as one attempt, and the others carry on); the
tasks go back to waiting and their worktrees stay for the next run. Projects without git, or with
``max_parallel: 1``, run one task at a time exactly as before.

Linked dependencies (``link_deps``): a new worktree doesn't reinstall everything. Each folder in
``parallel.link`` (by default those found of ``node_modules``, ``.venv``, ``.gradle``, ``.godot/imported``) is
linked into the lane from the project folder – a directory junction on Windows (no administrator rights
needed), a symbolic link elsewhere – only when the lane's lockfiles (``package-lock.json``,
``requirements*.txt``, ``gradle.lockfile``, ``pyproject.toml``…) are the same as the project's, and only when
git ignores the link (so it is never committed). Otherwise the lane runs its setup as before. When the lane is
removed its links are taken away first, never followed: the project's own folder and every file in it stay.

Settings (``harness.yaml``): ``limits.max_parallel``, ``parallel: {keep_worktrees: true}`` to keep every
worktree after its merge (for looking at later), and ``parallel: {link: [node_modules]}`` (``false``: never link).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agent import BudgetExceeded, OutOfCredit
from . import checks as checkslib
from .config import section
from .safeenv import clean_env

WORKTREES = Path(".harness") / "worktrees"
BRANCH_PREFIX = "roundtable-task/"
MAX_WIDTH = 8  # never more tasks at once than this, whatever the setting says
LINKS_FILE = Path(".harness") / "links.json"  # which folders are linked into which lane
DEFAULT_LINKS = ("node_modules", ".venv", ".gradle", ".godot/imported")
LOCKFILES: dict[str, tuple[str, ...]] = {  # what must be the same in the lane and the project to share a folder
    "node_modules": ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
                     "package.json"),
    ".venv": ("requirements*.txt", "pyproject.toml", "poetry.lock", "uv.lock", "Pipfile.lock"),
    ".gradle": ("gradle.lockfile", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts",
                "gradle/libs.versions.toml"),
    ".godot/imported": ("project.godot",),
}


class RunHalted(BudgetExceeded):
    """Raised inside a task's conversation when the run has been told to stop (another task hit a limit,
    the claim was lost, ``stop_all``): the task goes back to waiting, its worktree stays."""


def safe_name(task_id: str) -> str:
    """A task id as a folder and branch name (letters, digits, dot, dash, underscore)."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", str(task_id)).strip(".-") or "task"
    return name[:60]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.name=agent-harness", "-c", "user.email=harness@localhost", "-c", "commit.gpgsign=false",
         *args],
        cwd=str(root), capture_output=True, text=True, env=clean_env(), encoding="utf-8", errors="replace")


@dataclass
class MergeResult:
    ok: bool
    conflicts: list[str] = field(default_factory=list)
    output: str = ""


# -- linked dependencies ----------------------------------------------------------------------------------------
def _is_link(p: Path) -> bool:
    """A symbolic link or a Windows junction (never its target's own folder)."""
    try:
        if os.path.islink(p):
            return True
        is_junction = getattr(p, "is_junction", None)  # Python 3.12
        if is_junction is not None and is_junction():
            return True
        st = os.lstat(p)
    except OSError:
        return False
    return bool(getattr(st, "st_file_attributes", 0) & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT


def _unlink(p: Path) -> bool:
    """Take a link away without following it. False when it couldn't (or it's no link: then it's left)."""
    if not _is_link(p):
        return False
    try:
        os.unlink(p)  # a symbolic link (and a junction on recent Pythons)
    except OSError:
        try:
            os.rmdir(p)  # a junction or a directory symlink on Windows: removes the link, never what it points at
        except OSError:
            return False
    return not os.path.lexists(p)


def _points_at(link: Path, target: Path) -> bool:
    try:
        return os.path.realpath(link) == os.path.realpath(target)
    except (OSError, ValueError):
        return False


def _make_link(source: Path, dest: Path) -> None:
    if os.name == "nt":
        import _winapi  # type: ignore[import-not-found]

        _winapi.CreateJunction(str(source), str(dest))  # a junction: no administrator rights needed
    else:
        os.symlink(source, dest, target_is_directory=True)


def _clean_rel(rel: Any) -> str | None:
    """A folder in the project as a plain relative path; None for anything outside it or the harness's own."""
    r = str(rel or "").replace("\\", "/").strip()
    if r.startswith("/") or r.startswith("~"):
        return None  # only folders inside the project
    r = r.strip("/")
    while r.startswith("./"):
        r = r[2:]
    parts = r.split("/") if r else []
    if not parts or any(x in ("", ".", "..") for x in parts) or re.match(r"^[A-Za-z]:", r) or \
            parts[0] in (".git", ".harness"):
        return None
    return "/".join(parts)


def _lock_texts(folder: Path, names: tuple[str, ...]) -> dict[str, bytes]:
    out = {}
    for pat in names:
        for f in sorted(folder.glob(pat)) if any(c in pat for c in "*?[") else [folder / pat]:
            try:
                if f.is_file():
                    out[f.relative_to(folder).as_posix()] = f.read_bytes()
            except OSError:
                out[str(pat)] = b"\0unreadable"
    return out


def _locks_match(root: Path, lane: Path, rel: str) -> tuple[bool, str]:
    names = LOCKFILES.get(rel) or tuple(dict.fromkeys(n for v in LOCKFILES.values() for n in v))
    mine, theirs = _lock_texts(root, names), _lock_texts(lane, names)
    if not mine and not theirs:
        return False, "there's no lockfile to say the two need the same things"
    if mine != theirs:
        diff = sorted(set(mine) ^ set(theirs) | {k for k in mine if k in theirs and mine[k] != theirs[k]})
        return False, f"{', '.join(diff[:3])} differ{'s' if len(diff) == 1 else ''} from the project's"
    return True, ""


def _read_links(root: Path) -> dict[str, dict[str, str]]:
    try:
        data = json.loads((root / LINKS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def _write_links(root: Path, data: dict[str, dict[str, str]]) -> None:
    p = root / LINKS_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps({k: v for k, v in data.items() if v}, indent=1), encoding="utf-8")
    os.replace(tmp, p)


_LINKS_LOCK = threading.Lock()
EXCLUDE_MARK = "# Darkness Harness: dependency folders linked into task worktrees (never committed)"


def _exclude_link(lane: Path, rel: str) -> bool:
    """Add ``/rel`` to the repository's own ``info/exclude`` (shared by its worktrees, never committed)."""
    res = _git(lane, "rev-parse", "--git-common-dir")
    if res.returncode != 0 or not res.stdout.strip():
        return False
    common = Path(res.stdout.strip())
    if not common.is_absolute():
        common = (lane / common).resolve()
    f = common / "info" / "exclude"
    line = "/" + rel
    try:
        text = f.read_text(encoding="utf-8") if f.is_file() else ""
        if line in text.splitlines():
            return True
        f.parent.mkdir(parents=True, exist_ok=True)
        add = ("" if not text or text.endswith("\n") else "\n") + (EXCLUDE_MARK + "\n" if EXCLUDE_MARK not in text else "")
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(add + line + "\n")
    except OSError:
        return False
    return True


def linked_folders(root: str | Path) -> list[str]:
    """Every folder linked into some lane of this project (for the guard: deleting one asks)."""
    return sorted({rel for v in _read_links(Path(root).resolve()).values() for rel in v})


class Worktrees:
    """The project's task worktrees (plain git; no Roundtable state)."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def path(self, task_id: str) -> Path:
        return self.root / WORKTREES / safe_name(task_id)

    def branch(self, task_id: str) -> str:
        return BRANCH_PREFIX + safe_name(task_id)

    def exists(self, task_id: str) -> bool:
        p = self.path(task_id)
        return (p / ".git").exists()

    def has_branch(self, task_id: str) -> bool:
        return _git(self.root, "rev-parse", "--verify", "-q", f"refs/heads/{self.branch(task_id)}").returncode == 0

    def head(self, task_id: str) -> str:
        res = _git(self.path(task_id), "rev-parse", "HEAD")
        return res.stdout.strip() if res.returncode == 0 else ""

    def add(self, task_id: str, base: str) -> tuple[Path, bool]:
        """The task's worktree, made from ``base`` (or the one already there). Returns (path, reused)."""
        p = self.path(task_id)
        if self.exists(task_id):
            return p, True
        _git(self.root, "worktree", "prune")
        p.parent.mkdir(parents=True, exist_ok=True)
        if self.has_branch(task_id):  # the folder went but the branch (and its commits) is still there
            res = _git(self.root, "worktree", "add", "-q", str(p), self.branch(task_id))
        else:
            res = _git(self.root, "worktree", "add", "-q", "-b", self.branch(task_id), str(p), base)
        if res.returncode != 0:
            raise RuntimeError(f"couldn't make a worktree for {task_id}: {res.stderr.strip()}")
        return p, False

    # -- linked dependencies -------------------------------------------------------------------------------------
    def link_candidates(self, settings: dict[str, Any] | None = None) -> list[str]:
        """The folders to link: ``parallel.link`` when given (``false`` or [] for none), else the defaults found."""
        settings = settings or {}
        want = settings.get("link", None)
        if want is False or want == []:
            return []
        if want is None or want is True:
            names = [r for r in DEFAULT_LINKS if (self.root / r).is_dir()]
        else:
            names = [want] if isinstance(want, str) else list(want) if isinstance(want, (list, tuple)) else []
        return list(dict.fromkeys(r for r in (_clean_rel(n) for n in names) if r))

    def link_deps(self, lane: str | Path, settings: dict[str, Any] | None = None) -> dict[str, Any]:
        """Link the project's dependency folders into a lane (``lane``: a task id or the worktree's folder).
        Returns {linked: [folders], skipped: [{folder, why}], complete}: complete when every folder found was
        linked (the lane then needn't run its setup)."""
        path = Path(lane) if isinstance(lane, Path) else self.path(lane)
        name = path.name
        out: dict[str, Any] = {"linked": [], "skipped": []}
        for rel in self.link_candidates(settings):
            why = self._link_one(path, rel)
            if why:
                out["skipped"].append({"folder": rel, "why": why})
            else:
                out["linked"].append(rel)
        if out["linked"]:
            with _LINKS_LOCK:
                data = _read_links(self.root)
                data[name] = {**data.get(name, {}), **{r: str(self.root / r) for r in out["linked"]}}
                _write_links(self.root, data)
        out["complete"] = bool(out["linked"]) and not out["skipped"]
        return out

    def _link_one(self, lane: Path, rel: str) -> str:
        """Link one folder; the reason it wasn't, else ""."""
        source, dest = self.root / rel, lane / rel
        if not source.is_dir():
            return "the project has no such folder"
        if os.path.lexists(dest):
            return "the lane has its own already"
        ok, why = _locks_match(self.root, lane, rel)
        if not ok:
            return why
        # ignored as a link, else never. "node_modules/" in .gitignore ignores the folder but not a link of that
        # name: then (only then) the link's own name goes in the repository's info/exclude, which is never committed
        if _git(lane, "check-ignore", "-q", "--", rel).returncode != 0:
            if _git(lane, "check-ignore", "-q", "--", rel + "/").returncode != 0:
                return "git doesn't ignore it here, so it could be committed"
            if not _exclude_link(lane, rel) or _git(lane, "check-ignore", "-q", "--", rel).returncode != 0:
                return "git ignores the folder but not a link to it, so it could be committed"
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            _make_link(source, dest)
        except (OSError, ImportError, AttributeError) as e:
            return f"the link couldn't be made ({type(e).__name__})"
        seen = _git(lane, "status", "--porcelain", "--untracked-files=all", "--", rel)
        if seen.returncode != 0 or seen.stdout.strip():
            _unlink(dest)
            return "git would see the link, so it was taken away again"
        return ""

    def unlink_deps(self, lane: str | Path) -> list[str]:
        """Take every link out of a lane, never following one. Returns the folders whose link is still there
        (then the lane must be kept)."""
        path = Path(lane) if isinstance(lane, Path) else self.path(lane)
        with _LINKS_LOCK:
            data = _read_links(self.root)
            recorded = list(data.get(path.name, {}))
            stuck = []
            for rel in dict.fromkeys([*recorded, *DEFAULT_LINKS]):
                dest = path / rel
                if not _is_link(dest):
                    continue  # gone already, or the lane's own folder now: it goes with the lane
                if rel not in recorded and not _points_at(dest, self.root / rel):
                    continue  # a link that isn't ours (the project may keep one in git): left as it is
                if not _unlink(dest):
                    stuck.append(rel)
            if stuck:
                data[path.name] = {r: v for r, v in data.get(path.name, {}).items() if r in stuck}
            else:
                data.pop(path.name, None)
            _write_links(self.root, data)
        return stuck

    def start_merge(self, task_id: str, other_task: str) -> list[str]:
        """In ``task_id``'s worktree, begin merging ``other_task``'s branch without committing: the clashes
        stay in the files for the fix-up task to settle. Returns the clashing files."""
        p = self.path(task_id)
        _git(p, "merge", "--no-ff", "--no-commit", self.branch(other_task))
        return self._conflicts(p)

    def dirty(self, task_id: str) -> bool | None:
        """Anything uncommitted in the worktree (None: git couldn't tell)."""
        if not self.exists(task_id):
            return False
        p = self.path(task_id)
        res = _git(p, "status", "--porcelain")
        if res.returncode != 0:
            return None
        return bool(res.stdout.strip()) or self._merging(p)

    def _merging(self, p: Path) -> bool:
        res = _git(p, "rev-parse", "-q", "--verify", "MERGE_HEAD")
        return res.returncode == 0

    def commit(self, task_id: str, message: str) -> bool:
        """Commit everything in the worktree (a fix-up's merge included); False when there was nothing."""
        p = self.path(task_id)
        _git(p, "add", "-A")
        self._unstage_links(p)
        if not _git(p, "status", "--porcelain").stdout.strip() and not self._merging(p):
            return False
        res = _git(p, "commit", "-q", "--no-verify", "-m", message)
        if res.returncode != 0:
            raise RuntimeError(f"couldn't commit {task_id}'s work: {res.stderr.strip() or res.stdout.strip()}")
        return True

    def _unstage_links(self, p: Path) -> None:
        """A linked folder never goes in a commit, whatever git was told to ignore since."""
        links = list(_read_links(self.root).get(p.name, {})) + [r for r in DEFAULT_LINKS if _is_link(p / r)]
        staged = _git(p, "diff", "--cached", "--name-only", "--no-renames").stdout.splitlines()
        for rel in dict.fromkeys(links):
            if any(f == rel or f.startswith(rel + "/") for f in staged):
                _git(p, "rm", "-q", "--cached", "-r", "--ignore-unmatch", "--", rel)

    def merge_into_project(self, task_id: str, message: str) -> MergeResult:
        """Merge the task's branch into the branch the project is on. A clash is undone, never forced."""
        res = _git(self.root, "merge", "--no-ff", "--no-edit", "-m", message, self.branch(task_id))
        if res.returncode == 0:
            return MergeResult(True, output=res.stdout)
        conflicts = self._conflicts(self.root)
        _git(self.root, "merge", "--abort")
        return MergeResult(False, conflicts, (res.stdout + res.stderr).strip())

    @staticmethod
    def _conflicts(root: Path) -> list[str]:
        res = _git(root, "diff", "--name-only", "--diff-filter=U")
        return [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]

    def merged_since(self, base: str) -> list[str]:
        """Subjects of the commits on the project's branch since ``base`` (first parents: one per merge)."""
        if not base:
            return []
        res = _git(self.root, "log", "--first-parent", "--format=%s", f"{base}..HEAD")
        return [ln for ln in res.stdout.splitlines() if ln.strip()] if res.returncode == 0 else []

    def remove(self, task_id: str) -> tuple[bool, str]:
        """Remove the worktree and its branch, only when nothing in it is uncommitted.
        Returns (removed, why it was kept)."""
        if not self.exists(task_id):
            _git(self.root, "worktree", "prune")
            self._drop_branch(task_id)
            return True, ""
        state = self.dirty(task_id)
        if state is None:
            return False, "git couldn't say whether it holds unsaved work, so it was kept"
        if state:
            return False, "it holds changes that were never committed, so it was kept"
        stuck = self.unlink_deps(task_id)  # first, so removing the lane can never reach the project's own folders
        if stuck:
            return False, f"the link to {', '.join(stuck)} couldn't be taken away, so it was kept"
        res = _git(self.root, "worktree", "remove", str(self.path(task_id)))
        if res.returncode != 0:
            return False, f"git wouldn't remove it ({res.stderr.strip()[:200]}), so it was kept"
        _git(self.root, "worktree", "prune")
        self._drop_branch(task_id)
        return True, ""

    def _drop_branch(self, task_id: str) -> None:
        _git(self.root, "branch", "-d", self.branch(task_id))  # -d: only once it is merged


class ParallelStage:
    """The Orchestrator's side of several tasks at once (a mixin, like the Look stage)."""

    PARALLEL_POLL = 0.25  # seconds between looks at the running tasks
    DAY_CHECK_SECONDS = 5.0  # how often the day's spending is added up while tasks run
    _halt: Any = None  # why every task must stop now (an exception or a stop record), else None

    # -- settings ----------------------------------------------------------------------------------------------
    def _parallel_width(self) -> int:
        """How many tasks may run at once: 1 unless max_parallel > 1 and the project is kept in git."""
        n = int(getattr(self.cfg.limits, "max_parallel", 1) or 1)
        if n <= 1 or not self.cfg.git or not (self.project.root / ".git").exists():
            return 1
        return min(n, MAX_WIDTH)

    def _parallel_settings(self) -> dict[str, Any]:
        return section(self.cfg, "parallel")

    def stop_all(self, pause: str, text: str = "") -> None:
        """Stop every running task at its next step (e.g. the app's Stop): they wait, worktrees kept."""
        if self._halt is None:
            self._halt = {"pause": pause, "text": text, "halt": True}
        from ..providers import cli_engine

        cli_engine.stop_all()  # a coding CLI is closed at once, with everything it started
        from . import livecmd

        livecmd.stop_strays(self.project.root)  # and a task's running command (tests, a server) with it

    # -- the budget, shared by several threads ----------------------------------------------------------------
    def _arm_budget(self) -> None:
        budget = self.budget
        lock = threading.RLock()
        charge, check = type(budget).charge, type(budget).check

        def locked_charge(cost, *, ref=None, usage=None, role=None):
            with lock:
                charge(budget, cost, ref=ref, usage=usage, role=role)

        def halting_check():
            halt = self._halt
            if halt is not None:
                raise RunHalted(halt.get("text") if isinstance(halt, dict) else str(halt))
            check(budget)

        budget.charge, budget.check = locked_charge, halting_check

    def _disarm_budget(self) -> None:
        for name in ("charge", "check"):
            self.budget.__dict__.pop(name, None)

    # -- one task, in its own thread ----------------------------------------------------------------------------
    def _lane(self, task, tasks, path: Path, fresh: bool) -> tuple[str, BaseException | None]:
        from .gate import Gate
        from .tools import Workspace

        tl = self._tl
        tl.task, tl.root = task.id, path
        tl.ws = Workspace(path, allow_shell=self.cfg.allow_shell, command_timeout=self.cfg.limits.command_timeout)
        # "Ask me first": the cards live in the project's own .harness/gate/, so every task's show in one place,
        # each naming its task; the main gate's timeout (0 in the lab's replays) holds here too
        main = getattr(self._ws, "gate", None)
        tl.ws.gate = Gate(self.project.root, self.cfg, on_change=self._publish_plan,
                          context=lambda: {"id": task.id, "title": task.title},
                          timeout=getattr(main, "timeout", None))
        try:
            linked = self._link_lane(task, path, fresh)
            tl.baseline = self._lane_baseline(task, path, fresh and not linked)
            self._proof_before(task)  # the pictures as the task finds it (proof.py)
            ok = self._run_task(task, tasks)
            return ("ok" if ok else "failed"), None
        except RunHalted as e:
            return "stopped", e
        except BudgetExceeded as e:  # this task hit a money limit: every other task stops too
            if self._halt is None:
                self._halt = e
            return "stopped", e
        except BaseException as e:  # noqa: BLE001 - handed to the main thread, which raises it
            if self._halt is None:
                self._halt = e
            return "error", e
        finally:
            for name in ("task", "root", "ws", "baseline"):
                tl.__dict__.pop(name, None)

    def _link_lane(self, task, path: Path, fresh: bool) -> bool:
        """The project's dependency folders linked into a new lane; True when all were (setup needn't run)."""
        if not fresh:
            return False
        try:
            out = Worktrees(self.project.root).link_deps(path, self._parallel_settings())
        except Exception as e:  # noqa: BLE001 - a help: without links the lane runs its setup as before
            self.emit("stage_error", {"stage": "link_deps", "task": task.id, "error": str(e)[:300]})
            return False
        if out["linked"] or out["skipped"]:
            self.emit("deps_linked", {"task": task.id, "linked": out["linked"], "skipped": out["skipped"]})
        return bool(out["complete"])

    def _lane_baseline(self, task, path: Path, fresh: bool) -> dict[str, Any] | None:
        """Setup in a new worktree, and the checks' starting point for this one (checks.prepare_worktree)."""
        try:
            values = self.project_settings().values
        except Exception:
            return None
        if not values.get("test") and not (fresh and values.get("setup")):
            return None
        record = self.project._read("worktrees.json", {}).get(task.id) or {}
        if not fresh and record.get("baseline") and record["baseline"].get("command") == values.get("test"):
            return record["baseline"]
        out = checkslib.prepare_worktree(path, values, Worktrees(self.project.root).head(task.id),
                                         self.project.meta().get("baseline"), fresh=fresh)
        if out.get("setup"):
            self.emit("worktree_setup", {"task": task.id, "command": out["setup"]["command"],
                                         "passed": out["setup"]["passed"]})
        with self._lock:
            records = self.project._read("worktrees.json", {})
            records[task.id] = {**records.get(task.id, {}), "baseline": out.get("baseline")}
            self.project._write("worktrees.json", records)
        return out.get("baseline")

    # -- the scheduler (main thread) ----------------------------------------------------------------------------
    def _run_parallel(self, max_tasks: int | None) -> str:
        width = self._parallel_width()
        trees = Worktrees(self.project.root)
        state = {"executed": 0, "finished": 0}
        running: dict[str, tuple[Future, Any]] = {}
        passed: list[str] = []
        split_later: list[Any] = []
        stop: dict[str, Any] | None = None
        tasks = self.project.tasks()
        for t in tasks:  # resume after a crash or a pause mid-task
            if t.status == "running":
                t.status = "pending"
        self.project.save_tasks(tasks)
        self._halt = None
        self._arm_budget()
        pool = ThreadPoolExecutor(max_workers=width, thread_name_prefix="roundtable-task")
        self.emit("parallel", {"width": width})
        last_day_check = 0.0
        try:
            while True:
                if not running:
                    self._merge_passed(passed, running, tasks, trees, state)
                    if stop or self._halt is not None:
                        break
                    if split_later:
                        if any([self._split_if_too_big(t) or self._hook("_unstick_task", t, tasks, default=False)
                                for t in split_later]):
                            split_later = []
                            tasks = self.project.tasks()
                            continue
                        split_later = []
                    tasks = self.project.tasks()  # the owner's retries and skips, the planner's splits
                by_id = {t.id: t for t in tasks}
                ready = [t for t in tasks if t.status == "pending" and t.id not in running
                         and all(by_id[d].status == "done" for d in t.depends_on if d in by_id)]
                ready = self._hook("_stage_ready", ready, tasks, set(running), default=ready)  # a working slice first
                if not running and not ready:
                    end = self._parallel_end(tasks)
                    if end == "again":  # the end steps added work: run that too
                        tasks = self.project.tasks()
                        continue
                    return end
                while ready and len(running) < width and stop is None and self._halt is None:
                    stop = self._launch_stop(state, max_tasks)
                    if stop is not None:
                        if stop.get("halt"):
                            self._halt = stop
                        break
                    task = ready.pop(0)
                    running[task.id] = self._launch(pool, task, tasks, trees)
                    state["executed"] += 1
                if not running:
                    continue
                done, _ = wait([f for f, _ in running.values()], timeout=self.PARALLEL_POLL,
                               return_when=FIRST_COMPLETED)
                for tid in [k for k, (f, _) in running.items() if f in done]:
                    fut, task = running.pop(tid)
                    outcome, err = fut.result()
                    self._lane_done(task, tasks, outcome, err, trees, passed, split_later)
                self._merge_passed(passed, running, tasks, trees, state)
                if stop is None and self._halt is None and time.time() - last_day_check >= self.DAY_CHECK_SECONDS:
                    last_day_check = time.time()
                    stop = self._running_stop()
                    if stop is not None:
                        self._halt = stop
        except BaseException as e:
            if self._halt is None:
                self._halt = e  # a crash or Ctrl-C here: the tasks stop too
            raise
        finally:
            pool.shutdown(wait=True)
            self._disarm_budget()
            halt, self._halt = self._halt, None
            if running:  # only after a crash in this loop: put the tasks back as waiting
                for _, task in running.values():
                    if task.status == "running":
                        task.status = "pending"
                self.project.save_tasks(tasks)
        if isinstance(halt, BaseException):
            raise halt  # a money limit: the run's own handler pauses it; anything else is a real error
        stop = stop or halt
        if stop is None:
            end = self._parallel_end(self.project.tasks())
            return self._run_parallel(max_tasks) if end == "again" else end
        return self._apply_stop(stop)

    def _launch(self, pool: ThreadPoolExecutor, task, tasks, trees: Worktrees) -> tuple[Future, Any]:
        task.status = "running"
        self._git_commit("harness: snapshot before task")  # the owner's own edits go in before branching
        head = self._head() or ""
        if not task.base_commit:
            task.base_commit = head
        path, reused = trees.add(task.id, head)
        conflicts: list[str] = []
        if not reused and task.merge_of:
            conflicts = trees.start_merge(task.id, task.merge_of)
        self.project.save_tasks(tasks)
        self.emit("worktree", {"task": task.id, "path": str(path), "branch": trees.branch(task.id), "reused": reused,
                               **({"conflicts": conflicts} if task.merge_of else {})})
        self.emit("task_start", {"task": task.id, "title": task.title, "role": task.role,
                                 "index": next(i for i, t in enumerate(tasks, 1) if t is task), "total": len(tasks),
                                 "worktree": str(path)})
        return pool.submit(self._lane, task, tasks, path, not reused), task

    def _lane_done(self, task, tasks, outcome: str, err, trees: Worktrees, passed: list[str],
                   split_later: list[Any]) -> None:
        if outcome == "ok":
            try:
                trees.commit(task.id, f"[{task.id}] {task.title}")
            except RuntimeError as e:
                task.status = "failed"
                task.summary = f"its work couldn't be saved: {e}"
                self.project.save_tasks(tasks)
                self.emit("task_end", {"task": task.id, "status": "failed", "summary": task.summary[:500]})
                self._keep_note(task.id, trees, "its work couldn't be committed")
                return
            passed.append(task.id)
            self.emit("task_end", {"task": task.id, "status": "done", "summary": task.summary[:500]})
            return
        if outcome == "failed":
            task.status = "failed"
            self.project.save_tasks(tasks)
            self.emit("task_end", {"task": task.id, "status": "failed", "summary": task.summary[:500]})
            self._keep_note(task.id, trees, "the task didn't pass; its work stays here for a retry")
            self._after_task(task, False)
            split_later.append(task)
            return
        # stopped (a limit, the claim, the breaker) or a crash: back to waiting, the worktree stays
        task.status = "pending"
        if isinstance(self._halt, OutOfCredit) or isinstance(err, OutOfCredit):
            task.attempts = [a for a in task.attempts if a.get("outcome") != "error"]  # the money ran out
        self.project.save_tasks(tasks)
        self.emit("task_end", {"task": task.id, "status": "paused", "summary": str(err or "")[:300]})
        self._keep_note(task.id, trees, "the run stopped; the task carries on from here next time")

    def _keep_note(self, task_id: str, trees: Worktrees, why: str) -> None:
        if trees.exists(task_id):
            self.emit("worktree_kept", {"task": task_id, "path": str(trees.path(task_id)), "why": why})

    # -- merging, in task order ------------------------------------------------------------------------------
    def _merge_passed(self, passed: list[str], running: dict[str, Any], tasks, trees: Worktrees,
                      state: dict[str, int]) -> None:
        order = {t.id: i for i, t in enumerate(tasks)}
        for tid in sorted(passed, key=lambda x: order.get(x, 1 << 30)):
            if any(order.get(r, 1 << 30) < order.get(tid, 1 << 30) for r in running):
                break  # one listed above it is still running: it lands first
            passed.remove(tid)
            task = next((t for t in tasks if t.id == tid), None)
            if task is not None:
                self._merge_task(task, tasks, trees, state)

    def _merge_task(self, task, tasks, trees: Worktrees, state: dict[str, int]) -> None:
        from .orchestrator import HarnessError

        self._git_commit("harness: snapshot before task")  # also checks the branch in repository mode
        self._guard_branch()
        res = trees.merge_into_project(task.id, f"[{task.id}] {task.title}")
        if not res.ok and not res.conflicts:
            raise HarnessError(f"couldn't bring task {task.id}'s work into the project: {res.output[:500]}")
        if res.ok:
            task.status = "done"
            self.project.save_tasks(tasks)
            state["finished"] += 1
            self.emit("merged", {"task": task.id, "branch": trees.branch(task.id)})
            self._journal("done", f"[{task.id}] {task.title}", details=task.summary[:2000])
            self._resolved(f"failed:{task.id}", note="task completed")
            self._after_task(task, True)
            self._hook("_stage_after_task", task)  # files changed outside the plan (stages.py)
            chain, seen = [task.id], {task.id}
            while True:  # a fix-up brought in the task it was for (and that one's, and so on)
                prev = next((t for t in tasks if t.id == chain[-1]), None)
                if prev is None or not prev.merge_of or prev.merge_of in seen:
                    break
                chain.append(prev.merge_of)
                seen.add(prev.merge_of)
            for tid in chain:
                self._tidy_worktree(tid, trees)
            return
        fix = self._fixup_task(task, tasks, res.conflicts, trees)
        task.status = "done"
        task.summary = (f"{task.summary} (Its changes clashed with work that landed first; task {fix.id} brings "
                        "them in.)").strip()
        self.project.save_tasks(tasks)
        self.emit("merge_conflict", {"task": task.id, "files": res.conflicts[:50], "fixup": fix.id})
        self._journal("note", f"[{task.id}] clashed with work done alongside it in {len(res.conflicts)} file(s); "
                              f"[{fix.id}] puts the two together", details="\n".join(res.conflicts[:50]))
        self._keep_note(task.id, trees, f"its changes clashed; task {fix.id} brings them in from here")

    def _fixup_task(self, task, tasks, conflicts: list[str], trees: Worktrees):
        from .orchestrator import Task

        ids = {t.id for t in tasks}
        fid, n = f"{task.id}-merge", 2
        while fid in ids:
            fid, n = f"{task.id}-merge{n}", n + 1
        landed = trees.merged_since(task.base_commit or "")
        others = [t for t in tasks if t.id != task.id and t.status == "done"
                  and any(s.startswith(f"[{t.id}] ") for s in landed)]
        files = "".join(f"- {f}\n" for f in conflicts[:40]) or "- (git didn't name them)\n"
        theirs = "".join(f"- [{t.id}] {t.title}: {(t.summary or '')[:600]}\n" for t in others) or "- (not known)\n"
        desc = (f"Task {task.id} “{task.title}” was done alongside other tasks, and its changes clash with theirs in "
                f"these files:\n{files}\nYour folder already has both sides merged, with git's clash markers "
                "(<<<<<<<, =======, >>>>>>>) in those files. Put the two sides together so both kinds of work are "
                f"kept, remove every marker, and make sure the project still works.\n\n"
                f"What {task.id} did: {(task.summary or '')[:1200]}\n\nWhat landed first:\n{theirs}")
        fix = Task(id=fid, title=f"Put {task.id}'s changes together with the work done alongside it", role=task.role,
                   description=desc, acceptance="No clash markers are left; the work of both sides is kept and the "
                   "project's checks pass.", depends_on=[], goal_index=task.goal_index, section=task.section,
                   merge_of=task.id)
        for t in tasks:
            if task.id in t.depends_on and fid not in t.depends_on:
                t.depends_on.append(fid)  # whatever needed the first task needs its changes in the project
        tasks.insert(tasks.index(task) + 1, fix)
        return fix

    def _tidy_worktree(self, task_id: str, trees: Worktrees) -> None:
        if self._parallel_settings().get("keep_worktrees"):
            self._keep_note(task_id, trees, "kept by the setting parallel.keep_worktrees")
            return
        removed, why = trees.remove(task_id)
        if removed:
            self.emit("worktree_removed", {"task": task_id})
            with self._lock:
                records = self.project._read("worktrees.json", {})
                if records.pop(task_id, None) is not None:
                    self.project._write("worktrees.json", records)
        else:
            self.emit("worktree_kept", {"task": task_id, "path": str(trees.path(task_id)), "why": why})

    # -- stopping ---------------------------------------------------------------------------------------------
    def _launch_stop(self, state: dict[str, int], max_tasks: int | None) -> dict[str, Any] | None:
        """Before a task starts: the same limits as one task at a time, in the same order."""
        if not state["finished"] and state["executed"] and self._real_spend_over_limit(0.5):
            return {"pause": "money_nothing_done", "halt": True}
        if self._real_spend_over_limit():
            return {"pause": "money", "halt": True}
        if max_tasks is not None and state["executed"] >= max_tasks:
            return {"pause": "", "halt": False}  # let the running ones finish, start no more
        got = self._hook("_money_gate")  # past what the owner agreed to: the gate has paused it (moneystage.py)
        if got:
            return {"pause": "", "halt": False, "result": got}  # let the running ones finish, start no more
        return self._running_stop()

    def _running_stop(self) -> dict[str, Any] | None:
        if self._taken_elsewhere():
            return {"pause": "elsewhere", "halt": True}
        day = self.cfg.limits.max_usd_per_day
        if day and self._spent_today() >= day:
            return {"pause": "money_day", "halt": True}
        return None

    def _apply_stop(self, stop: dict[str, Any]) -> str:
        if stop.get("result"):
            return stop["result"]  # a stage's gate already set the status and its card
        pause = stop.get("pause") or ""
        if pause == "money_nothing_done":
            self._set_status("paused", pause=pause)
            self._attention("money", "this run has spent half its real-money limit and finished nothing; "
                                     "look at the failed attempts before running again")
        elif pause == "money":
            self._set_status("paused", pause=pause)
            self._attention("money", f"this run has spent ${self.cfg.limits.max_real_usd_per_run:.2f} of real "
                                     "credit, the limit you set; run again to carry on")
        elif pause == "elsewhere":
            self._set_status("paused", pause=pause)
            self._journal("note", "Paused: another machine has taken this project over.")
        elif pause == "money_day":
            day = self.cfg.limits.max_usd_per_day
            self._set_status("paused", pause=pause)
            self._attention("money_day", f"Today's spending limit (${day:.2f}) is reached: this run carries on "
                                         "tomorrow, or raise the limit in Settings")
        elif pause:
            self._set_status("paused", pause=pause, **({"reason": stop["text"]} if stop.get("text") else {}))
        else:
            self._set_status("paused")
        return "paused"

    def _parallel_end(self, tasks) -> str:
        """Nothing running and nothing ready: done, or blocked (the same as one task at a time)."""
        if any(t.status == "failed" for t in tasks):
            self._set_status("blocked")
            if self._hook("_unstick_end", tasks, default=False):  # worked out: one card, not one a task
                return "blocked"
            for t in tasks:
                if t.status == "failed":
                    self._attention(f"failed:{t.id}", f"Task {t.id} “{t.title}” didn't pass: try it "
                                    "again or skip it", details=f"roundtable status {self.project.root}")
            return "blocked"
        if all(t.status == "done" for t in tasks):
            got = self._end_steps(tasks)  # start it, ship it, the done gate
            if got:
                return got  # "again": the caller reloads the tasks and goes round
            self._finish(tasks)
            return "done"
        stop = self._hook("_stage_stop")  # "Stop after each stage" (stages.py)
        if stop:
            return stop
        self._set_status("blocked")
        return "blocked"
