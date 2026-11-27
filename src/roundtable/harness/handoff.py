"""A written handover for a task that didn't finish (parity MD-24).

Whoever picks the work up next - the same task tried again, the smaller tasks a split made, the tasks a
re-plan put in its place - reads what was tried, what the reviewer said, which files changed and what is
left. ``write`` costs nothing: no model is asked, everything comes from the task's own record and git.

Kept in ``<project>/.harness/handoffs/<task>.md``. ``worker_part`` is the piece of the next worker's prompt.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from ..core.models import utcnow
from .safeenv import clean_env

DIR = Path(".harness") / "handoffs"
MAX_ATTEMPTS_SHOWN = 4
MAX_CHARS = 6000  # a handover stays short: the worker reads it in its prompt


def _safe(task_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(task_id))[:80] or "task"


def path(root, task_id: str) -> Path:
    return Path(root) / DIR / f"{_safe(task_id)}.md"


def read(root, task_id: str) -> str:
    """The task's handover, "" when it has none."""
    p = path(root, task_id) if task_id else None
    try:
        return p.read_text(encoding="utf-8") if p and p.is_file() else ""
    except OSError:
        return ""


def _git(cwd: Path, *args: str) -> str:
    """git's own output (read only), "" when it can't say: a handover never fails over git."""
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30,
                           env=clean_env(), encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def files_changed(root, task) -> str:
    """What the task changed since it started: its kept worktree when it ran in one, else the project."""
    root = Path(root)
    where = root
    try:
        from .worktrees import Worktrees

        trees = Worktrees(root)
        if trees.exists(task.id):
            where = trees.path(task.id)
    except Exception:  # noqa: BLE001 - no worktree: the project itself
        where = root
    if not (where / ".git").exists():
        return ""
    base = getattr(task, "base_commit", "") or ""
    stat = _git(where, "diff", "--stat", base) if base else _git(where, "diff", "--stat")
    new = [f for f in _git(where, "ls-files", "--others", "--exclude-standard").splitlines()
           if f and not f.startswith(".harness/")]
    out = stat
    if new:
        out += ("\n" if out else "") + "New files: " + ", ".join(new[:30]) + (" …" if len(new) > 30 else "")
    return out[:2000]


def _short(text: str, limit: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[:limit - 1] + "…"


def _attempts_text(attempts: list[dict[str, Any]]) -> str:
    lines = []
    shown = attempts[-MAX_ATTEMPTS_SHOWN:]
    first = len(attempts) - len(shown) + 1
    for n, a in enumerate(shown, first):
        what = a.get("outcome") or "?"
        line = f"- Attempt {n} ({a.get('model') or 'a model'}): {what}"
        said = (a.get("summary") or a.get("error") or "").strip()
        if said:
            line += f". It said: {_short(said, 300)}"
        review = (a.get("review") or "").strip()
        if review:
            line += f"\n  The reviewer: {_short(review, 400)}"
        lines.append(line)
    return "\n".join(lines) or "- Nothing was tried yet."


def text(root, task, why: str, advice: str = "") -> str:
    """The handover as markdown (also what ``write`` saves)."""
    attempts = list(getattr(task, "attempts", []) or [])
    last_review = next((a.get("review") for a in reversed(attempts) if a.get("review")), "")
    parts = [f"# Handover: [{task.id}] {task.title}", f"Written {utcnow()}.", f"## Why\n{_short(why, 800) or 'It did not pass.'}"]
    if advice.strip():
        parts.append(f"## Advice for whoever carries on\n{_short(advice, 1200)}")
    parts.append(f"## What was tried\n{_attempts_text(attempts)}")
    changed = files_changed(root, task)
    parts.append("## Files it changed\n" + (f"```\n{changed}\n```" if changed else "None that git can see."))
    left = [f"Its 'done when': {task.acceptance.strip()}" if getattr(task, "acceptance", "").strip() else ""]
    if last_review:
        left.append(f"What the last review still wanted: {_short(last_review, 600)}")
    left.append("The changes above are still in the files: check what is there before you start again.")
    parts.append("## What's left\n" + "\n".join(f"- {x}" for x in left if x))
    out = "\n\n".join(parts) + "\n"
    return out if len(out) <= MAX_CHARS else out[:MAX_CHARS - 2] + "…\n"


def write(root, task, why: str, advice: str = "") -> Path:
    """Write (or rewrite) the task's handover. No model call, nothing spent."""
    p = path(root, task.id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text(root, task, why, advice), encoding="utf-8")
    return p


def worker_part(root, task) -> str:
    """For the next worker's prompt: the task's own handover (it's being tried again) and the one of the task
    whose work it carries on (``handoff_from``). "" when there's neither."""
    out = []
    own = read(root, task.id)
    if own:
        out.append("# A handover from the earlier try at this task - read it first\n" + own.strip())
    src = getattr(task, "handoff_from", "") or ""
    if src and src != task.id:
        theirs = read(root, src)
        if theirs:
            out.append(f"# A handover from task {src}, whose work this task carries on - read it first\n"
                       + theirs.strip())
    return "\n\n".join(out)
