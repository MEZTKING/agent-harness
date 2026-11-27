"""Retention: the one place that deletes old data, so the disk stays tidy and nothing else ever has to.

What it removes (and nothing else), each with a limit in ``retention:`` in harness.yaml:

* the app's old log files (``<home>/logs``): files older than ``logs_days``; ``app.log`` cut to its newest
  half once it is bigger than ``app_log_mb``
* nothing of a project's event log: once ``.harness/events.jsonl`` is bigger than ``events_mb`` its older half
  moves into a compressed archive beside it (harness/eventlog.py; the Session view still reads it all)
* the token saver's spill files (``.harness/spill/``) older than ``spill_days``
* a task's live command output (``.harness/live/*.log``) older than ``logs_days``
* the ways back that rewind keeps (``refs/roundtable/undo/…``) older than ``rewind_days``: "Put it back" is
  offered that long; the copies in ``.harness/rewinds/`` and ``rewinds.jsonl`` stay
* old pictures (``.harness/shots/<task>/``): only the newest ``shots_keep`` folders stay (and the latest one)
* the runs kept in the hub (``sessions/<project>/<run>.jsonl``): only the newest ``hub_sessions_keep`` per project
* task worktrees (``.harness/worktrees/``) of tasks that are done, whose branch is merged, and which hold no
  uncommitted, untracked or ignored files that matter (build caches like node_modules don't count) –
  removed the way the run itself does it (``worktrees.json`` updated, a ``worktree_removed`` event);
  ``worktrees_merged``; never while ``parallel.keep_worktrees`` is on
* plug-in drafts from "Make one" (``<home>/plugin-drafts/``) older than ``drafts_days`` that no plug-in entry
  points at (adding one copies it, so a draft is only ever a starting point)

Never: a project's own files, anything the owner sent (attachments), anything touched in the last
``min_age_minutes``, a project that is running or paused – every path is checked to be inside one of the
folders above; symbolic links are removed as links, never followed.

The owner's switch "Tidy up old files automatically" (Settings → Advanced, ``ui/tidyapi.py``) is kept in
``<home>/tidy.json``; off, the daily sweep doesn't run (``roundtable tidy`` still works). Every sweep writes what it removed and how much space it freed to
``<home>/logs/retention.jsonl``. ``dry_run`` says what it would remove and removes nothing.

Run once a day by the desktop app's auto-sync (``run_daily``) and by hand with ``roundtable tidy``.

The idea of one sweep that is the only thing allowed to delete, with a reason beside every limit, is from
Munder Difflin's ``src/shared/retention.ts`` and ``src/main/retention.ts`` (MIT); no code was copied.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from .brand import NAME

# Each limit and why it is that number.
DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "logs_days": 30,  # a month of app logs is enough to find out what went wrong last time
    "app_log_mb": 20,  # the running app's log: cut in half beyond this (about a month of busy use)
    "events_mb": 20,  # a project's event log: its older half is archived (compressed) beyond this
    "spill_days": 14,  # spill files are only read back during the task that made them
    "rewind_days": 30,  # "Put it back" after an undo stays offered a month (the owner's question 2, 27 Nov 2026)
    "shots_keep": 30,  # picture folders per project: enough to compare a month of tasks
    "hub_sessions_keep": 20,  # runs per project in the hub: the phone's list shows the last few
    "worktrees_merged": True,  # a merged task's copy of the project is no longer needed
    "drafts_days": 14,  # a plug-in draft not added in a fortnight is never going to be: make it again if wanted
    "min_age_minutes": 60,  # a safety floor: never touch what was written in the last hour
}
LOG_NAME = "retention.jsonl"
LOG_KEEP = 2000  # lines of the sweep's own log
SWITCH = "tidy.json"  # the owner's switch: {"auto": true|false}
# Ignored files that never stop a worktree being removed: things any build makes again.
CACHE_NAMES = {"node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
               "dist", "build", ".godot", ".gradle", "target", ".next", ".cache", ".parcel-cache", ".turbo",
               ".tox", ".eggs"}
MB = 1024 * 1024


@dataclass
class Removed:
    what: str  # logs, app_log, events (archived), spill, live, rewind, shots, hub_sessions, worktrees, plugin_drafts
    path: str
    bytes: int
    note: str = ""


@dataclass
class Result:
    dry_run: bool = False
    removed: list[Removed] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    at: str = ""

    @property
    def freed(self) -> int:
        return sum(r.bytes for r in self.removed)

    def message(self) -> str:
        n = len(self.removed)
        if not n:
            text = "Nothing old to tidy up."
        else:
            verb = "Would remove" if self.dry_run else "Tidied up:"
            things = "1 old thing" if n == 1 else f"{n} old things"
            text = f"{verb} {things}, {size_text(self.freed)} {'would be ' if self.dry_run else ''}freed."
        if self.errors:
            text += f" {len(self.errors)} couldn't be removed (see the log)."
        return text

    def to_dict(self) -> dict[str, Any]:
        groups: dict[str, dict[str, int]] = {}
        for r in self.removed:
            g = groups.setdefault(r.what, {"count": 0, "bytes": 0})
            g["count"] += 1
            g["bytes"] += r.bytes
        return {"at": self.at, "dry_run": self.dry_run, "message": self.message(), "freed": self.freed,
                "groups": groups, "removed": [r.__dict__ for r in self.removed], "errors": self.errors,
                "skipped": self.skipped}


def size_text(n: int) -> str:
    if n >= 1024 * MB:
        return f"{n / (1024 * MB):.1f} GB"
    if n >= MB:
        return f"{n / MB:.0f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} bytes"


def settings(cfg: Any = None) -> dict[str, Any]:
    """The limits: ``retention:`` in harness.yaml over the defaults (a bad value keeps the default)."""
    out = dict(DEFAULTS)
    try:
        from .harness.config import section

        given = section(cfg, "retention") if cfg is not None else {}
    except Exception:  # noqa: BLE001
        given = {}
    for k, v in given.items():
        if k not in DEFAULTS:
            continue
        d = DEFAULTS[k]
        try:
            out[k] = (str(v).lower() not in ("0", "false", "off", "no")) if isinstance(d, bool) else type(d)(v)
        except (TypeError, ValueError):
            continue
    for k in ("logs_days", "app_log_mb", "events_mb", "spill_days", "rewind_days", "min_age_minutes"):
        out[k] = max(out[k], 0)
    for k in ("shots_keep", "hub_sessions_keep"):
        out[k] = max(out[k], 1)  # always keep the newest
    return out


# -- the safety checks --------------------------------------------------------------------------
def _inside(path: Path, root: Path) -> bool:
    """``path`` is strictly inside ``root`` (by its real location, without following ``path`` itself)."""
    try:
        parent = Path(os.path.realpath(path.parent))
        real_root = Path(os.path.realpath(root))
    except OSError:
        return False
    return parent == real_root or real_root in parent.parents


def _size(p: Path) -> int:
    try:
        if p.is_symlink() or p.is_file():
            return p.lstat().st_size
        total = 0
        for dirpath, _dirs, files in os.walk(p):
            for f in files:
                try:
                    total += os.lstat(os.path.join(dirpath, f)).st_size
                except OSError:
                    pass
        return total
    except OSError:
        return 0


def _newest_mtime(p: Path) -> float:
    try:
        newest = p.lstat().st_mtime
        if p.is_dir() and not p.is_symlink():
            for dirpath, _dirs, files in os.walk(p):
                for f in files:
                    try:
                        newest = max(newest, os.lstat(os.path.join(dirpath, f)).st_mtime)
                    except OSError:
                        pass
        return newest
    except OSError:
        return time.time()


class Sweep:
    """One tidy-up. Every removal goes through ``remove``, which checks the path is inside ``allowed``."""

    def __init__(self, limits: dict[str, Any], dry_run: bool = False, now: float | None = None):
        self.limits = limits
        self.dry_run = dry_run
        self.now = now if now is not None else time.time()
        self.result = Result(dry_run=dry_run, at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def fresh(self, p: Path) -> bool:
        return self.now - _newest_mtime(p) < self.limits["min_age_minutes"] * 60

    def older_than(self, p: Path, days: float) -> bool:
        return self.now - _newest_mtime(p) > days * 86400

    def remove(self, what: str, p: Path, allowed: Path, note: str = "") -> bool:
        if not _inside(p, allowed) or Path(os.path.realpath(allowed)) == Path(os.path.realpath(p)):
            self.result.skipped.append(f"{p}: outside the folders the harness tidies")
            return False
        if self.fresh(p):
            return False
        size = _size(p)
        if not self.dry_run:
            try:
                if p.is_symlink() or p.is_file():
                    p.unlink()
                else:
                    shutil.rmtree(p)
            except OSError as e:
                self.result.errors.append(f"{p}: {e}")
                return False
        self.result.removed.append(Removed(what, str(p), size, note))
        return True

    def trim(self, what: str, p: Path, allowed: Path, max_bytes: int) -> None:
        """Cut a growing log to its newest half (at a line break), in place, once it is over ``max_bytes``."""
        try:
            if not p.is_file() or p.is_symlink() or not _inside(p, allowed):
                return
            size = p.stat().st_size
        except OSError:
            return
        if size <= max_bytes or max_bytes <= 0:
            return
        keep = max_bytes // 2
        try:
            with open(p, "rb") as f:
                f.seek(size - keep)
                tail = f.read()
            cut = tail.find(b"\n")
            tail = tail[cut + 1:] if cut >= 0 else b""
            if not self.dry_run:
                with open(p, "r+b") as f:  # in place: the app may hold it open (Windows can't replace it)
                    f.seek(0)
                    f.write(tail)
                    f.truncate()
        except OSError as e:
            self.result.errors.append(f"{p}: {e}")
            return
        self.result.removed.append(Removed(what, str(p), size - len(tail), "cut to its newest part"))

    # -- the stores ---------------------------------------------------------------------------------
    def app_logs(self, home: Path) -> None:
        logs = Path(home) / "logs"
        if not logs.is_dir():
            return
        self.trim("app_log", logs / "app.log", logs, self.limits["app_log_mb"] * MB)
        for f in sorted(logs.iterdir()):
            if f.name in ("app.log", LOG_NAME) or not (f.is_file() or f.is_symlink()):
                continue
            if self.older_than(f, self.limits["logs_days"]):
                self.remove("logs", f, logs)

    def plugin_drafts(self, home: Path, cfg: Any = None) -> None:
        drafts = Path(home) / "plugin-drafts"
        if not drafts.is_dir():
            return
        used = ""
        path = getattr(cfg, "path", None)
        if path:
            custom = Path(path).parent / "custom.yaml"
            used = custom.read_text(encoding="utf-8", errors="replace") if custom.is_file() else ""
        for d in sorted(drafts.iterdir()):
            if d.is_dir() and not d.is_symlink() and d.name not in used \
                    and self.older_than(d, self.limits["drafts_days"]):
                self.remove("plugin_drafts", d, drafts, "a plug-in draft that was never added")

    def project(self, root: Path, cfg: Any = None) -> None:
        root = Path(root)
        hdir = root / ".harness"
        if not hdir.is_dir() or hdir.is_symlink():
            return
        meta = _meta(hdir)
        status = str(meta.get("status") or "")
        if status == "running" or status.startswith("paused"):
            self.result.skipped.append(f"{root.name}: {status}, left alone")
            return
        self.archive_events(root)
        spill = hdir / "spill"
        if spill.is_dir() and not spill.is_symlink():
            for f in sorted(spill.iterdir()):
                if self.older_than(f, self.limits["spill_days"]):
                    self.remove("spill", f, spill)
        live = hdir / "live"
        if live.is_dir() and not live.is_symlink():
            for f in sorted(live.glob("*.log")):
                if self.older_than(f, self.limits["logs_days"]):
                    self.remove("live", f, live)
        self.rewind_refs(root)
        self.shots(hdir / "shots")
        self.goal_dirs(hdir / "play")  # play-test pictures (harness/playtest.py), like the app's pictures
        self.goal_dirs(hdir / "journeys")  # the finishing step's pictures (harness/finishstage.py)
        if self.limits["worktrees_merged"]:
            self.worktrees(root, cfg)

    def rewind_refs(self, root: Path) -> None:
        """Ways back older than ``rewind_days`` (harness/rewind.py); only refs under refs/roundtable/undo/."""
        if not (root / ".git").exists():
            return
        from .harness import rewind

        try:
            old = rewind.expired_refs(root, int(self.limits["rewind_days"]), now=datetime.fromtimestamp(self.now, timezone.utc))
        except Exception as e:  # git missing or broken: nothing is removed
            self.result.errors.append(f"{root.name}: ways back: {e}"[:300])
            return
        for ref in old:
            if self.dry_run or rewind.drop_ref(root, ref):
                self.result.removed.append(Removed("rewind", f"{root}:{ref}", 0, "a way back older than "
                                                   f"{self.limits['rewind_days']} days"))
            else:
                self.result.errors.append(f"{root.name}: couldn't remove {ref}")

    def archive_events(self, root: Path) -> None:
        from .harness import eventlog

        live = root / ".harness" / eventlog.LIVE
        if not live.is_file() or self.fresh(live):
            return
        try:
            done = eventlog.archive_older_half(root, self.limits["events_mb"] * MB, dry_run=self.dry_run,
                                               now=self.now)
        except OSError as e:
            self.result.errors.append(f"{live}: {e}")
            return
        if done:
            self.result.removed.append(Removed("events", str(live), done["saved"],
                                               f"older part kept in {Path(done['archive']).name}"))

    def goal_dirs(self, top: Path) -> None:
        """Folders of pictures kept per goal (``play/goal-1/<item>``, ``journeys/g1/<part>``): the newest
        ``shots_keep`` in each goal's folder, as for the app's pictures."""
        if top.is_dir() and not top.is_symlink():
            for goal in sorted(d for d in top.iterdir() if d.is_dir() and not d.is_symlink()):
                self.shots(goal)

    def shots(self, shots: Path) -> None:
        if not shots.is_dir() or shots.is_symlink():
            return
        latest = ""
        try:
            latest = str(json.loads((shots / "latest.json").read_text(encoding="utf-8")).get("dir") or "")
        except (OSError, ValueError, AttributeError):
            pass
        dirs = sorted((d for d in shots.iterdir() if d.is_dir() and not d.is_symlink()),
                      key=_newest_mtime, reverse=True)
        for d in dirs[self.limits["shots_keep"]:]:
            if d.name != Path(latest).name:
                self.remove("shots", d, shots)

    def worktrees(self, root: Path, cfg: Any = None) -> None:
        trees_dir = root / ".harness" / "worktrees"
        if not trees_dir.is_dir() or trees_dir.is_symlink():
            return
        try:
            from .harness.config import section

            if cfg is not None and section(cfg, "parallel").get("keep_worktrees"):
                return
        except Exception:  # noqa: BLE001
            pass
        from .harness.worktrees import BRANCH_PREFIX, Worktrees, safe_name

        merged = _merged_branches(root)
        if merged is None:
            return
        done = {safe_name(t.get("id", "")): t.get("id", "") for t in _tasks(root / ".harness")
                if t.get("status") == "done" and t.get("id")}
        trees = Worktrees(root)
        for d in sorted(trees_dir.iterdir()):
            if not d.is_dir() or d.is_symlink() or not _inside(d, trees_dir) or self.fresh(d):
                continue
            task_id = done.get(d.name)
            if not task_id:
                continue  # not done: a retry carries on from here
            if f"{BRANCH_PREFIX}{d.name}" not in merged:
                continue
            why = _unsaved(d)
            if why:
                self.result.skipped.append(f"{d}: {why}")
                continue
            size = _size(d)
            if self.dry_run:
                self.result.removed.append(Removed("worktrees", str(d), size, f"task {task_id} is done"))
                continue
            ok, why = trees.remove(task_id)
            if not ok:
                self.result.skipped.append(f"{d}: {why}")
                continue
            _forget_worktree(root, task_id)
            self.result.removed.append(Removed("worktrees", str(d), size, f"task {task_id} is done"))

    def hub_sessions(self, hub: Any, lock: Any = None) -> None:
        root = getattr(getattr(hub, "store", None), "root", None)
        if not root:
            return
        base = Path(root) / "sessions"
        if not base.is_dir():
            return
        gone: list[str] = []
        for proj in sorted(p for p in base.iterdir() if p.is_dir() and not p.is_symlink()):
            runs = sorted(proj.glob("*.jsonl"), key=lambda f: f.name, reverse=True)
            for f in runs[self.limits["hub_sessions_keep"]:]:
                if not _inside(f, base) or self.fresh(f):
                    continue
                self.result.removed.append(Removed("hub_sessions", f"sessions/{proj.name}/{f.name}", _size(f)))
                gone.append(f"sessions/{proj.name}/{f.name}")
        if gone and not self.dry_run:
            try:
                if lock is not None:
                    with lock:
                        hub.store.write_json(dict.fromkeys(gone), f"tidy: {len(gone)} old runs")
                else:
                    hub.store.write_json(dict.fromkeys(gone), f"tidy: {len(gone)} old runs")
            except Exception as e:  # noqa: BLE001 - offline: try again tomorrow
                n = len(gone)
                self.result.removed = [r for r in self.result.removed if r.path not in gone]
                self.result.errors.append(f"the hub's {n} old runs: {e}"[:300])


def _meta(hdir: Path) -> dict[str, Any]:
    try:
        return json.loads((hdir / "project.json").read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def _tasks(hdir: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads((hdir / "tasks.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [t for t in data if isinstance(t, dict)] if isinstance(data, list) else []


def _unsaved(tree: Path) -> str:
    """Why a worktree must stay: changes, untracked files, or ignored files that aren't a build cache; else ""."""
    from .harness.safeenv import clean_env

    try:
        res = subprocess.run(["git", "status", "--porcelain", "--ignored", "--untracked-files=all"],
                             cwd=str(tree), capture_output=True, text=True, env=clean_env(), encoding="utf-8",
                             errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return f"git couldn't look at it ({e}), so it was kept"
    if res.returncode != 0:
        return "git couldn't say whether it holds unsaved work, so it was kept"
    for line in res.stdout.splitlines():
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:].strip().strip('"')
        if code == "!!" and set(Path(path.rstrip("/")).parts) & CACHE_NAMES:
            continue
        what = {"!!": "files git ignores", "??": "files never committed"}.get(code, "changes never committed")
        return f"it holds {what} ({path}), so it was kept"
    return ""


def _forget_worktree(root: Path, task_id: str) -> None:
    """What the run does when it removes a worktree itself: drop its record and say so in the events."""
    from .core.models import utcnow
    from .harness.orchestrator import _IO_LOCK, Project

    project = Project(root)
    with _IO_LOCK:
        records = project._read("worktrees.json", {})
        if isinstance(records, dict) and records.pop(task_id, None) is not None:
            project._write("worktrees.json", records)
        project.append("events.jsonl", {"at": utcnow(), "event": "worktree_removed", "task": task_id,
                                        "by": "tidy"})


def _merged_branches(root: Path) -> set[str] | None:
    from .harness.safeenv import clean_env

    try:
        res = subprocess.run(["git", "branch", "--merged", "HEAD", "--format=%(refname:short)"], cwd=str(root),
                             capture_output=True, text=True, env=clean_env(), encoding="utf-8", errors="replace",
                             timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    return {ln.strip() for ln in res.stdout.splitlines() if ln.strip()}


def _projects(cfg: Any) -> list[Path]:
    lab = getattr(cfg, "lab_dir", None)
    if not lab:
        return []
    try:
        from .improve.lab import Lab

        return Lab(lab).projects()
    except Exception:  # noqa: BLE001
        return []


def write_log(home: Path, result: Result) -> None:
    logs = Path(home) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    p = logs / LOG_NAME
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
        if len(lines) > LOG_KEEP:
            p.write_text("\n".join(lines[-LOG_KEEP:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def entries(home: Path, limit: int = 20) -> list[dict[str, Any]]:
    """The newest sweeps from the log, newest first."""
    out = []
    try:
        lines = (Path(home) / "logs" / LOG_NAME).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for ln in reversed(lines[-limit:]):
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def tidy(cfg: Any = None, home: Path | None = None, hub: Any = None, hub_lock: Any = None,
         projects: list[Path] | None = None, dry_run: bool = False, now: float | None = None) -> Result:
    """One sweep of everything above; writes the log (a dry run too, marked as one). Never raises."""
    from .desktop import app_home

    home = Path(home) if home else app_home()
    limits = settings(cfg)
    sweep = Sweep(limits, dry_run=dry_run, now=now)
    if not limits["enabled"]:
        sweep.result.skipped.append("retention is off (retention.enabled: false)")
        return sweep.result
    steps: list[tuple[str, Callable[[], None]]] = [("the app's logs", lambda: sweep.app_logs(home)),
                                                   ("plug-in drafts", lambda: sweep.plugin_drafts(home, cfg))]
    for root in (projects if projects is not None else _projects(cfg)):
        steps.append((str(root), lambda root=root: sweep.project(Path(root), cfg)))
    if hub is not None:
        steps.append(("the hub", lambda: sweep.hub_sessions(hub, hub_lock)))
    for name, step in steps:
        try:
            step()
        except Exception as e:  # noqa: BLE001 - one bad folder never stops the rest
            sweep.result.errors.append(f"{name}: {e}"[:300])
    try:
        write_log(home, sweep.result)
    except OSError as e:
        sweep.result.errors.append(f"couldn't write the log: {e}")
    return sweep.result


def auto_on(home: Path) -> bool:
    """The owner's switch "Tidy up old files automatically" (on unless turned off)."""
    try:
        return bool(json.loads((Path(home) / SWITCH).read_text(encoding="utf-8")).get("auto", True))
    except (OSError, ValueError, AttributeError):
        return True


def set_auto(home: Path, on: bool) -> bool:
    Path(home).mkdir(parents=True, exist_ok=True)
    (Path(home) / SWITCH).write_text(json.dumps({"auto": bool(on)}), encoding="utf-8")
    return bool(on)


GROUP_NAMES = {"logs": "Old app logs", "app_log": "The app's log, shortened", "events": "Old history, packed away",
               "spill": "Spill files", "shots": "Old pictures", "hub_sessions": "Old runs in the hub",
               "worktrees": "Working copies of finished tasks", "plugin_drafts": "Plug-in drafts never added"}


def details(groups: dict[str, Any]) -> list[str]:
    """One plain line per kind of thing removed, for "More"."""
    return [f"{GROUP_NAMES.get(k, k)}: {g.get('count', 0)} ({size_text(int(g.get('bytes', 0)))})"
            for k, g in (groups or {}).items()]


def activity_items(home: Path, limit: int = 10) -> list[dict[str, Any]]:
    """One line for the Activity feed per real sweep that removed something; the list is behind More."""
    out = []
    for e in entries(home, limit=200):
        if e.get("dry_run") or not e.get("removed"):
            continue
        out.append({"at": e.get("at", ""), "seq": 0, "project": "", "kind": "tidy", "who": NAME,
                    "task": "", "role": "", "model": "", "text": e.get("message", ""),
                    "details": details(e.get("groups") or {})})
        if len(out) >= limit:
            break
    return out


def _state_path(home: Path) -> Path:
    return Path(home) / "retention-state.json"


def run_daily(cfg: Any = None, home: Path | None = None, hub: Any = None, hub_lock: Any = None,
              busy: bool = False, now: datetime | None = None) -> Result | None:
    """At most once a day, never while a run or plan job is going (then it tries again on a later tick)."""
    from .desktop import app_home

    home = Path(home) if home else app_home()
    today = (now or datetime.now()).strftime("%Y-%m-%d")
    try:
        state = json.loads(_state_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if busy or state.get("last_day") == today or not auto_on(home):
        return None
    try:
        home.mkdir(parents=True, exist_ok=True)
        _state_path(home).write_text(json.dumps({"last_day": today}), encoding="utf-8")
    except OSError:
        return None
    return tidy(cfg, home=home, hub=hub, hub_lock=hub_lock)


# -- roundtable tidy ----------------------------------------------------------------------------------
def main(argv: list[str]) -> None:
    import argparse

    p = argparse.ArgumentParser(prog="roundtable tidy", description="Remove old logs, pictures, spill files, "
                                "merged worktrees and old runs in the hub (never your project's own files).")
    p.add_argument("--dry-run", action="store_true", help="say what would be removed, remove nothing")
    p.add_argument("--config", help="harness.yaml (default $HARNESS_CONFIG or ./harness.yaml)")
    p.add_argument("--hub-config", help="hub.yaml, to tidy the runs kept in the hub too")
    p.add_argument("--no-hub", action="store_true", help="leave the hub alone")
    p.add_argument("--log", action="store_true", help="show the last tidy-ups instead")
    args = p.parse_args(argv)
    from .desktop import app_home

    if args.log:
        for e in entries(app_home()):
            print(f"{e.get('at', '')}  {e.get('message', '')}")
        return
    cfg = None
    try:
        from .harness.config import load_config

        cfg = load_config(args.config)
    except Exception as e:  # noqa: BLE001
        print(f"No harness.yaml found ({e}); only the app's logs are tidied.", file=sys.stderr)
    hub = None
    if not args.no_hub:
        try:
            from .core.config import load_config as load_hub
            from .hub.service import Hub

            hub = Hub(load_hub(args.hub_config))
        except Exception:  # noqa: BLE001 - no hub: fine
            hub = None
    result = tidy(cfg, hub=hub, dry_run=args.dry_run)
    for r in result.removed:
        print(f"{'would remove' if args.dry_run else 'removed'}  {r.what:12} {size_text(r.bytes):>8}  {r.path}")
    for e in result.errors:
        print(f"couldn't: {e}", file=sys.stderr)
    print(result.message())


# -- attempts not chosen (wave 6: rivals.py) ---------------------------------------------------------------------
# When two or three models built a task side by side, the ones not chosen keep their branch
# (roundtable-task/<task>-r<n>) and a patch (.harness/rivals/<task>/<rN>.patch). Nothing clears them by itself:
# the Tidy page lists them with their size, and only the owner's Clear removes them.
NOT_CHOSEN_BRANCH = re.compile(r"^roundtable-task/(?P<task>.+)-(?P<rival>r\d+)$")


def _git_out(root: Path, *args: str) -> tuple[int, str]:
    from .harness.safeenv import clean_env

    try:
        res = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, env=clean_env(),
                             encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return res.returncode, res.stdout


def not_chosen(root: Path) -> list[dict[str, Any]]:
    """One project's attempts not chosen: [{task, rival, model, why, branch, patch, size, bytes}], oldest first."""
    root = Path(root)
    hdir = root / ".harness"
    try:
        records = json.loads((hdir / "rivals.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        records = {}
    info: dict[tuple[str, str], dict[str, Any]] = {}
    for task, rounds in (records.items() if isinstance(records, dict) else []):
        for rnd in rounds if isinstance(rounds, list) else []:
            for r in (rnd or {}).get("rivals") or []:
                if isinstance(r, dict) and not r.get("picked"):
                    info[(str(task), str(r.get("id", "")))] = {"model": r.get("model", ""), "why": rnd.get("why", "")
                                                                or r.get("why", "")}
    items: dict[tuple[str, str], dict[str, Any]] = {}
    code, out = _git_out(root, "branch", "--list", "roundtable-task/*", "--format=%(refname:short)")
    merged = _merged_branches(root) or set()
    if code == 0:
        for b in (ln.strip() for ln in out.splitlines()):
            m = NOT_CHOSEN_BRANCH.match(b)
            if m and b not in merged:
                items[(m["task"], m["rival"])] = {"task": m["task"], "rival": m["rival"], "branch": b, "patch": ""}
    pdir = hdir / "rivals"
    if pdir.is_dir():
        for p in sorted(pdir.glob("*/*.patch")):
            key = (p.parent.name, p.stem)
            items.setdefault(key, {"task": key[0], "rival": key[1], "branch": ""})["patch"] = \
                str(p.relative_to(root)).replace("\\", "/")
    rows = []
    for key, it in sorted(items.items()):
        size = 0
        if it.get("patch"):
            size += _size(root / it["patch"])
        rows.append({**it, **info.get(key, {"model": "", "why": ""}), "bytes": size, "size": size_text(size)})
    return rows


def not_chosen_words(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No attempts waiting: every task's chosen attempt is in its project."
    tasks = len({(r.get("project", ""), r["task"]) for r in rows})
    n = len(rows)
    return (f"{n} attempt{'s' * (n != 1)} not chosen, on {tasks} task{'s' * (tasks != 1)}. Each is kept as a branch "
            "and a small patch until you clear it.")


def clear_not_chosen(root: Path, task: str = "", rival: str = "") -> dict[str, Any]:
    """The owner's Clear: removes the branches and patches of attempts not chosen (one, one task's, or all).
    Never called by the sweep. A branch that has been merged since is left alone."""
    root = Path(root)
    cleared, kept = [], []
    for it in not_chosen(root):
        if (task and it["task"] != task) or (rival and it["rival"] != rival):
            continue
        ok = True
        if it.get("branch"):
            code, _ = _git_out(root, "branch", "-D", it["branch"])  # not merged (listed only then): -D is needed
            ok = code == 0
        if it.get("patch"):
            p = root / it["patch"]
            if _inside(p, root / ".harness" / "rivals"):
                try:
                    p.unlink()
                    if p.parent.is_dir() and not any(p.parent.iterdir()):
                        p.parent.rmdir()
                except OSError:
                    ok = False
        (cleared if ok else kept).append(f"{it['task']} {it['rival']}")
    return {"cleared": cleared, "kept": kept,
            "reply": (f"Cleared {len(cleared)} attempt{'s' * (len(cleared) != 1)} not chosen."
                      if cleared else "Nothing to clear.") + (f" {len(kept)} couldn't be cleared." if kept else "")}
