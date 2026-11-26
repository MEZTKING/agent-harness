"""The Session view: each task's work as steps, like watching a Claude Code session.

``session(project_root)`` reads ``.harness/events.jsonl`` and turns every task into steps: the
model's words, each tool call as one line (Read, Edit with its diff, Run with its output), the
reviewer's verdict, the pictures, and the cost of each model turn. ``outputs`` lists the pictures
and files the project made, by task. ``hub_session`` is the short version for the phone in Hub
mode: one line per step, no file contents. Everything shown goes through ``redact`` first.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from ..backup import SECRET_PATTERNS, SETTING_PATTERN

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
FILE_EXT = {".apk", ".aab", ".zip", ".exe", ".msi", ".jar", ".dmg", ".appimage", ".pdf", ".mp3", ".wav", ".ogg",
            ".mp4", ".webm", ".gz", ".tgz", ".7z"}
SKIP_DIRS = {".git", ".harness", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache"}
MAX_TASKS = 30
HIDDEN = "[hidden: looks like a key]"
_KEYS = [re.compile(p.pattern.decode()) for p, _ in SECRET_PATTERNS]
_SETTING = re.compile(SETTING_PATTERN.pattern.decode())


def redact(text: Any) -> str:
    """The text with anything shaped like a key or a password replaced."""
    s = str(text or "")
    for p in _KEYS:
        s = p.sub(HIDDEN, s)
    return _SETTING.sub(lambda m: m.group(0).replace(m.group(1), HIDDEN), s)


def _redact_all(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_redact_all(v) for v in value]
    if isinstance(value, dict):
        return {k: _redact_all(v) for k, v in value.items()}
    return value


# -- one tool call as a line --------------------------------------------------------------------
def _exit_code(text: str) -> int | None:
    m = re.match(r"exit code: (-?\d+)", text or "")
    return int(m.group(1)) if m else None


def _diff_from_args(a: dict[str, Any], name: str) -> dict[str, Any] | None:
    """For older events (before the diff was kept): a diff made from the (shortened) arguments."""
    from .tools import file_change

    path = str(a.get("path", ""))
    if name == "edit_file" and ("old_text" in a or "new_text" in a):
        return file_change(path, str(a.get("old_text", "")), str(a.get("new_text", "")))
    if name == "write_file" and "content" in a:
        return file_change(path, "", str(a.get("content", "")))
    return None


def tool_step(d: dict[str, Any]) -> dict[str, Any]:
    """A tool_call event as a step: {kind: tool, tool, label, detail, error, diff | output | lines}."""
    name, a, result = d.get("tool", ""), d.get("args") or {}, str(d.get("result") or "")
    step: dict[str, Any] = {"kind": "tool", "tool": name, "error": bool(d.get("error")), "at": d.get("at", "")}
    path = str(a.get("path") or "")
    if name == "read_file":
        lo, hi = a.get("start_line"), a.get("end_line")
        step.update(label=f"Read {path}", detail=f"lines {lo or 1}–{hi or 'end'}" if lo or hi else "",
                    output=result)
    elif name in ("write_file", "edit_file"):
        change = d.get("change") or _diff_from_args(a, name)
        verb = "Write" if name == "write_file" else "Edit"
        step.update(label=f"{verb} {path}", path=path, diff=(change or {}).get("diff", ""),
                    detail=f"+{change['added']} −{change['removed']}" if change else "")
    elif name == "run_command":
        code = _exit_code(d.get("output") or result)
        step.update(label=f"Run `{str(a.get('command', ''))[:160]}`", output=d.get("output") or result,
                    detail="passed" if code == 0 else f"failed (exit {code})" if code is not None else "")
        step["error"] = step["error"] or bool(code)
    elif name == "list_files":
        step.update(label=f"List {path or 'the project'}", detail=str(a.get("pattern") or ""), output=result)
    elif name == "search":
        step.update(label=f"Search `{str(a.get('pattern', ''))[:120]}`", output=result)
    elif name == "finish_task":
        step.update(kind="finish", label="Finished", text=str(a.get("summary") or ""))
    elif name == "submit_review":
        step.update(kind="hidden")
    else:
        step.update(label=name.replace("_", " ").capitalize(), output=result)
    if step["error"] and name != "run_command":
        step["detail"] = "didn't work: " + result[:200]
    return step


# -- events into tasks ----------------------------------------------------------------------------
def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _new_task(d: dict[str, Any]) -> dict[str, Any]:
    return {"id": d.get("task", ""), "title": d.get("title", ""), "role": d.get("role", ""), "status": "running",
            "started": d.get("at", ""), "ended": "", "cost": 0.0, "steps": [], "summary": ""}


def _add(task: dict[str, Any], d: dict[str, Any], reviewer: str | None, pending_cost: list[float]) -> None:
    ev = d.get("event")
    steps = task["steps"]
    who = "reviewer" if reviewer and d.get("role") == reviewer else "worker"
    if ev == "model_turn":
        cost = float(d.get("cost") or 0)
        task["cost"] += cost
        if (d.get("text") or "").strip():
            steps.append({"kind": "say", "who": who, "model": d.get("model", ""), "text": d["text"], "cost": cost,
                          "at": d.get("at", "")})
        else:
            pending_cost[0] += cost  # shown with the tool line it led to
    elif ev == "tool_call":
        step = tool_step(d)
        if step["kind"] != "hidden":
            step["who"] = who
            if pending_cost[0]:
                step["cost"], pending_cost[0] = pending_cost[0], 0.0
            steps.append(step)
    elif ev == "attempt":
        steps.append({"kind": "attempt", "text": f"Attempt {d.get('attempt')} on {d.get('model')}",
                      "model": d.get("model", ""), "at": d.get("at", "")})
    elif ev == "review":
        steps.append({"kind": "review", "approved": bool(d.get("approved")), "text": d.get("feedback", ""),
                      "at": d.get("at", "")})
    elif ev == "shots":
        steps.append({"kind": "shots", "task": d.get("task"), "dir": d.get("dir", ""), "pictures": d.get("pictures", []),
                      "errors": d.get("errors", 0), "note": d.get("note", ""), "at": d.get("at", "")})
    elif ev == "provider_error":
        steps.append({"kind": "error", "text": f"{d.get('model')}: {d.get('error', '')}"[:400], "at": d.get("at", "")})


def tasks_from_events(rows: list[dict[str, Any]], reviewer: str | None = "reviewer") -> list[dict[str, Any]]:
    """Each run of a task (task_start to task_end) with its steps, oldest first."""
    tasks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    pending_cost = [0.0]
    for d in rows:
        ev = d.get("event")
        if ev == "task_start":
            current = _new_task(d)
            tasks.append(current)
            pending_cost = [0.0]
        elif current is None:
            continue
        elif ev == "task_end" and d.get("task") == current["id"]:
            current.update(status=d.get("status", ""), ended=d.get("at", ""), summary=d.get("summary", ""))
        elif ev == "shots" and d.get("task") == current["id"]:
            _add(current, d, reviewer, pending_cost)
        elif not current["ended"]:
            _add(current, d, reviewer, pending_cost)
    for t in tasks:
        t["cost"] = round(t["cost"], 6)
    return tasks


# -- what the project made -------------------------------------------------------------------------
def _mtime_iso(p: Path) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def outputs(root: Path, tasks: list[dict[str, Any]] | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """Pictures and files (apk, zip, exe ...) in the project, newest first, each with the task that made it
    (the last task that wrote it, else the task whose run was going on when the file last changed)."""
    root = Path(root)
    written = {s["path"]: t["id"] for t in tasks or [] for s in t["steps"] if s.get("path") and not s.get("error")}
    found: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for f in filenames:
            p = Path(dirpath) / f
            ext = p.suffix.lower()
            if f.startswith(".") or (ext not in IMAGE_EXT and ext not in FILE_EXT):
                continue
            at, rel = _mtime_iso(p), p.relative_to(root).as_posix()
            task = written.get(rel) or next((t["id"] for t in reversed(tasks or [])
                                             if t["started"] <= at and (not t["ended"] or at <= t["ended"])), None)
            found.append({"path": rel, "kind": "image" if ext in IMAGE_EXT else "file",
                          "size": p.stat().st_size, "at": at, "task": task})
            if len(found) >= limit:
                break
    return sorted(found, key=lambda o: o["at"], reverse=True)


# -- the whole view -------------------------------------------------------------------------------
def cursor(project_root: Path) -> int:
    """A cheap 'has anything happened' number: the size of the event log."""
    try:
        return (Path(project_root) / ".harness" / "events.jsonl").stat().st_size
    except OSError:
        return 0


def session(project_root: Path, reviewer: str | None = "reviewer", max_tasks: int = MAX_TASKS) -> dict[str, Any]:
    root = Path(project_root)
    tasks = tasks_from_events(_rows(root / ".harness" / "events.jsonl"), reviewer)
    made = outputs(root, tasks)
    for i, t in enumerate(tasks):  # a task run more than once: its outputs go with its newest run
        again = any(u["id"] == t["id"] for u in tasks[i + 1:])
        t["outputs"] = [] if again else [o for o in made if o["task"] == t["id"]]
    return _redact_all({"cursor": cursor(root), "tasks": tasks[-max_tasks:], "outputs": made})


def step_line(s: dict[str, Any]) -> str:
    """One step as one short line (for the phone)."""
    kind = s.get("kind")
    if kind == "tool":
        return f"● {s.get('label', '')}" + (f" · {s['detail']}" if s.get("detail") else "")
    if kind == "say":
        return ("Reviewer: " if s.get("who") == "reviewer" else "") + " ".join(str(s.get("text", "")).split())[:200]
    if kind == "review":
        return ("✓ Approved: " if s.get("approved") else "✗ Sent back: ") + str(s.get("text", ""))[:200]
    if kind == "shots":
        n = len(s.get("pictures") or [])
        return f"Pictures taken ({n})" if n else f"No pictures: {s.get('note', '')}"[:200]
    if kind == "finish":
        return f"Finished: {s.get('text', '')}"[:220]
    return str(s.get("text", ""))[:200]


def hub_session(project_root: Path, project: str, reviewer: str | None = "reviewer", max_steps: int = 40) -> dict[str, Any]:
    """The latest task's last steps as one-line summaries: no file contents, no diffs, keys hidden."""
    from ..core.models import utcnow

    tasks = tasks_from_events(_rows(Path(project_root) / ".harness" / "events.jsonl"), reviewer)
    t = tasks[-1] if tasks else None
    out: dict[str, Any] = {"project": project, "at": utcnow(), "task": None}
    if t:
        out["task"] = {"id": t["id"], "title": t["title"], "role": t["role"], "status": t["status"],
                       "cost": t["cost"], "summary": t["summary"][:300],
                       "steps": [{"kind": s.get("kind"), "line": step_line(s), "error": bool(s.get("error"))}
                                 for s in t["steps"][-max_steps:]]}
    return _redact_all(out)
