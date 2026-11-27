"""The Session view: each task's work as steps, like watching a Claude Code session.

``session(project_root)`` reads ``.harness/events.jsonl`` and turns every task into steps: the
model's words, each tool call as one line (Read, Edit with its diff, Run with its output), the
reviewer's verdict, the pictures, and the cost of each model turn. Several tasks can run at once: events
are grouped by their ``task`` id, and each task carries where its time went (``time``), how full its
context is (``context``) and the files it changed (``changes``). ``outputs`` lists the pictures
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
    elif name in ("web_search", "web_read"):  # "Searched the web for …", "Read a page: …" (websearch.py)
        from .websearch import step as web_step

        step.update(web_step(name, a, result))
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


# -- where the time went, how full the context is -------------------------------------------------
# The parts of a task's time, in the order the bar shows them. Only time that was recorded is counted:
# an event without ``ms`` (an older log) adds nothing, and a part with nothing in it is left out.
TIME_PARTS = (
    ("first", "Waiting for the first word"),
    ("writing", "The model writing"),
    ("model", "The model thinking and writing"),
    ("tools", "Tools"),
    ("you", "Waiting for you"),
    ("other", "Roundtable's own work"),
)
# A model's context window when its event doesn't say: only families whose window is well known.
# Anything else shows the tokens without a gauge.
CONTEXT_WINDOWS = (("claude-", 200_000), ("deepseek", 128_000))


def context_window(model: str) -> int | None:
    """The context window of a model ("provider/model"), when it is known; else None."""
    name = str(model or "").lower().rsplit("/", 1)[-1]
    return next((n for prefix, n in CONTEXT_WINDOWS if prefix in name), None)


def _num(d: dict[str, Any], key: str) -> int | None:
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return max(0, int(v))


class _Clock:
    """What one task's events say about its time and tokens (see ``time`` and ``context``)."""

    def __init__(self) -> None:
        self.ms = dict.fromkeys(k for k, _ in TIME_PARTS)  # None: nothing recorded
        self.unrecorded = 0  # model turns and tool calls without a time
        self.conv_wait = 0  # waiting for you counted from this conversation's tool calls
        self.last: dict[str, Any] | None = None  # the newest model turn with tokens (the worker's first)
        self.last_who = ""
        self.prompt = self.cached = 0
        self.turns_with_tokens = 0

    def add(self, key: str, ms: int) -> None:
        if ms > 0:
            self.ms[key] = (self.ms[key] or 0) + ms

    def turn(self, d: dict[str, Any], who: str) -> None:
        ms, first = _num(d, "ms"), _num(d, "first_ms")
        if ms is None:
            self.unrecorded += 1
        elif first is not None:
            self.add("first", min(first, ms))
            self.add("writing", ms - min(first, ms))
        else:
            self.add("model", ms)
        tok = {k: _num(d, k) for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")}
        if any(v is not None for v in tok.values()):
            t = {k: v or 0 for k, v in tok.items()}
            self.turns_with_tokens += 1
            self.prompt += t["input_tokens"] + t["cache_read_tokens"] + t["cache_write_tokens"]
            self.cached += t["cache_read_tokens"]
            if who == "worker" or self.last_who != "worker":
                self.last, self.last_who = {**t, "model": d.get("model", ""), "window": _num(d, "context_window")}, who

    def tool(self, d: dict[str, Any]) -> None:
        ms, waited = _num(d, "ms"), _num(d, "waited_ms") or 0
        if ms is None:
            self.unrecorded += 1
            self.add("you", waited)
        else:
            waited = min(waited, ms)
            self.add("tools", ms - waited)
            self.add("you", waited)
        self.conv_wait += waited

    def done(self, d: dict[str, Any]) -> None:
        """agent_done: Roundtable's own time, and waiting the tool calls didn't carry themselves."""
        self.add("other", _num(d, "other_ms") or 0)
        extra = (_num(d, "waited_ms") or 0) - self.conv_wait
        if extra > 0:
            moved = min(extra, self.ms["tools"] or 0)  # that wait was inside the tool time
            if moved:
                self.ms["tools"] = (self.ms["tools"] or 0) - moved or None
            self.add("you", extra)
        self.conv_wait = 0

    def time(self) -> dict[str, Any] | None:
        parts = [{"key": k, "label": label, "ms": self.ms[k]} for k, label in TIME_PARTS if self.ms[k]]
        if not parts:
            return None
        return {"parts": parts, "total_ms": sum(p["ms"] for p in parts), "unrecorded": self.unrecorded}

    def context(self) -> dict[str, Any] | None:
        if not self.last:
            return None
        t = self.last
        used = t["input_tokens"] + t["cache_read_tokens"] + t["cache_write_tokens"] + t["output_tokens"]
        window = t["window"] or context_window(t["model"])
        return {"used": used, "window": window, "share": round(min(used / window, 1.0), 3) if window else None,
                "model": t["model"], "who": self.last_who,
                "cache_hit": round(self.cached / self.prompt, 3) if self.prompt else None,
                "turns": self.turns_with_tokens}


def changes(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The files a task changed (its writes and edits that worked), each once, with lines added and removed."""
    out: dict[str, dict[str, Any]] = {}
    for s in steps:
        if s.get("kind") != "tool" or not s.get("path") or s.get("error"):
            continue
        c = out.setdefault(s["path"], {"path": s["path"], "added": 0, "removed": 0, "new": s.get("tool") == "write_file"})
        m = re.match(r"\+(\d+) −(\d+)", s.get("detail") or "")
        if m:
            c["added"] += int(m.group(1))
            c["removed"] += int(m.group(2))
    return list(out.values())


def progress(task: dict[str, Any]) -> str:
    """What the task is doing now, in one short line (its newest step); a finished task: its summary."""
    if task["status"] != "running":
        return " ".join(str(task.get("summary") or "").split())[:140]
    for s in reversed(task["steps"]):
        if s.get("kind") == "attempt":
            return "Starting"
        if s.get("kind") == "say" and s.get("who") == "reviewer":
            return "The reviewer is checking it"
        if s.get("kind") in ("tool", "say", "review", "finish", "shots", "error"):
            return step_line(s).lstrip("● ")[:140]
    return "Starting"


def _add(task: dict[str, Any], d: dict[str, Any], reviewer: str | None, pending_cost: list[float],
         clock: _Clock | None = None) -> None:
    ev = d.get("event")
    steps = task["steps"]
    who = "reviewer" if reviewer and d.get("role") == reviewer else "worker"
    clock = clock or _Clock()
    if ev == "model_turn":
        clock.turn(d, who)
        cost = float(d.get("cost") or 0)
        task["cost"] += cost
        if (d.get("text") or "").strip():
            steps.append({"kind": "say", "who": who, "model": d.get("model", ""), "text": d["text"], "cost": cost,
                          "at": d.get("at", "")})
        else:
            pending_cost[0] += cost  # shown with the tool line it led to
    elif ev == "tool_call":
        clock.tool(d)
        step = tool_step(d)
        if step["kind"] != "hidden":
            step["who"] = who
            if pending_cost[0]:
                step["cost"], pending_cost[0] = pending_cost[0], 0.0
            steps.append(step)
    elif ev == "agent_done":
        clock.done(d)
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
    """Each run of a task (task_start to task_end) with its steps, in the order they started.

    Several tasks can run at once: an event carrying a ``task`` id goes to that task's newest run; an
    event without one (an older log) goes to the task started last. Each task also gets ``time`` (where
    its time went, or None when nothing was timed), ``context`` (tokens of its newest model call against
    the model's window, and the cache-hit rate; None without token counts), ``changes`` (the files it
    changed) and ``now`` (what it is doing, in one line)."""
    tasks: list[dict[str, Any]] = []
    newest: dict[str, dict[str, Any]] = {}  # task id -> its newest run
    clocks: dict[int, _Clock] = {}
    pending: dict[int, list[float]] = {}
    current: dict[str, Any] | None = None
    for d in rows:
        ev = d.get("event")
        if ev == "task_start":
            current = _new_task(d)
            tasks.append(current)
            newest[current["id"]] = current
            clocks[id(current)], pending[id(current)] = _Clock(), [0.0]
            continue
        tid = d.get("task")
        t = newest.get(tid) if tid else current
        if t is None:
            continue
        if ev == "task_end":
            if tid == t["id"]:
                t.update(status=d.get("status", ""), ended=d.get("at", ""), summary=d.get("summary", ""))
        elif ev == "shots" and tid == t["id"]:
            _add(t, d, reviewer, pending[id(t)], clocks[id(t)])
        elif not t["ended"]:
            _add(t, d, reviewer, pending[id(t)], clocks[id(t)])
    for t in tasks:
        t["cost"] = round(t["cost"], 6)
        c = clocks[id(t)]
        t.update(time=c.time(), context=c.context(), changes=changes(t["steps"]), now=progress(t))
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
    from .eventlog import read_events

    root = Path(project_root)
    tasks = tasks_from_events(read_events(root), reviewer)  # the archives too: the tidy-up moves old events there
    made = outputs(root, tasks)
    for i, t in enumerate(tasks):  # a task run more than once: its outputs go with its newest run
        again = any(u["id"] == t["id"] for u in tasks[i + 1:])
        t["outputs"] = [] if again else [o for o in made if o["task"] == t["id"]]
    shown = tasks[-max_tasks:]
    return _redact_all({"cursor": cursor(root), "tasks": shown, "outputs": made, "running": running(shown)})


def running(tasks: list[dict[str, Any]]) -> list[str]:
    """The ids of the tasks still going (each task's newest run), in the order they started."""
    last = {t["id"]: t for t in tasks}
    return [t["id"] for t in tasks if last[t["id"]] is t and t["status"] == "running"]


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


def compact_task(t: dict[str, Any], max_steps: int = 40) -> dict[str, Any]:
    """A task for the phone: its steps as one-line summaries, where its time went, its context and the
    files it changed (paths and counts only)."""
    return {"id": t["id"], "title": t["title"], "role": t["role"], "status": t["status"],
            "cost": t["cost"], "summary": t["summary"][:300], "now": t.get("now", ""),
            "time": t.get("time"), "context": t.get("context"), "changes": t.get("changes") or [],
            "steps": [{"kind": s.get("kind"), "line": step_line(s), "error": bool(s.get("error"))}
                      for s in t["steps"][-max_steps:]]}


def hub_session(project_root: Path, project: str, reviewer: str | None = "reviewer", max_steps: int = 40) -> dict[str, Any]:
    """The latest task's last steps as one-line summaries: no file contents, no diffs, keys hidden.

    ``tasks`` holds every task still running (several run at once), each the same shape as ``task``;
    with none running it holds the latest task alone. ``task`` (the latest started) stays for older
    phones."""
    from ..core.models import utcnow

    tasks = tasks_from_events(_rows(Path(project_root) / ".harness" / "events.jsonl"), reviewer)
    t = tasks[-1] if tasks else None
    out: dict[str, Any] = {"project": project, "at": utcnow(), "task": None, "tasks": []}
    if t:
        out["task"] = compact_task(t, max_steps)
        last = {u["id"]: u for u in tasks}
        live = [last[i] for i in running(tasks)]
        per = max(10, max_steps // max(1, len(live)))
        out["tasks"] = [compact_task(u, per) for u in live] if live else [out["task"]]
    return _redact_all(out)
