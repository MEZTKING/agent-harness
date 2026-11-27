"""Stages and parts: a working slice first, then the rest; several parts in their own folders; who changes which file.

The plan document carries ``doc["stages"] = [{id: "M1", title, shows}]`` (``shows``: what the owner can try at
the end of it) and, only when the idea truly has more than one, ``doc["parts"] = [{id, name, folder, kind?}]``.
Each task says its ``stage``, ``part`` and ``files`` (paths or globs from the project's top folder).

While it runs (``StagesStage._stage_ready``):

- only tasks of the earliest unfinished stage are ready (a task added mid-run without a stage is never held);
- a ready task whose files overlap a running one's (or one picked before it) waits;
- once a stage is all done, the between-stages step runs once: a journal note "Stage 1 is ready to try: …",
  a light re-plan of the later stages only when the stage left lessons (failed attempts, help from another
  task, files changed outside the plan), and a mark in ``.harness/stages.json`` so it never runs twice. It only
  stops for the owner when the project setting ``stage_stop`` is ``each``.

A plan without stages runs exactly as before. Every step here is a help: a failure is written down, never a
reason to stop the run (money is the only exception: ``BudgetExceeded`` from the re-plan passes through).
"""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from ..brand import NAME
from ..core.models import utcnow
from .agent import BudgetExceeded

RECORD = "stages.json"
STAGE_STOPS = ("off", "each")
SIZES = ("small", "medium", "large")
MAX_STAGES = 4
FINISHED = ("done", "skipped")
IGNORED = (".harness/", ".gitignore")  # the harness's own files never count as a task's
_ID = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,40}")


# -- the plan's stages and parts, tidied ---------------------------------------------------------------------
def _text(v: Any, limit: int = 300) -> str:
    return " ".join(str(v or "").split())[:limit]


def clean_stages(raw: Any) -> list[dict[str, str]]:
    """The planner's stages, tidied: ids M1, M2… when missing or repeated, at most four, never empty titles."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for i, s in enumerate(raw if isinstance(raw, list) else []):
        if isinstance(s, str):
            s = {"title": s}
        if not isinstance(s, dict):
            continue
        sid = _text(s.get("id"), 40)
        if not _ID.fullmatch(sid) or sid in seen:
            sid = f"M{len(out) + 1}"
            while sid in seen:
                sid += "b"
        title = _text(s.get("title")) or f"Stage {len(out) + 1}"
        seen.add(sid)
        out.append({"id": sid, "title": title, "shows": _text(s.get("shows"))})
        if len(out) == MAX_STAGES:
            break
    return out


def clean_folder(v: Any) -> str:
    """A part's folder, relative to the project and inside it ("." for the top folder)."""
    s = str(v or "").strip().replace("\\", "/")
    if s.startswith("/"):
        return "."  # never outside the project
    s = s.strip("/")
    while s.startswith("./"):
        s = s[2:]
    p = PurePosixPath(s) if s else PurePosixPath(".")
    if not s or s == "." or p.is_absolute() or ".." in p.parts or re.match(r"^[A-Za-z]:", s):
        return "."
    return str(p)


def clean_parts(raw: Any) -> list[dict[str, str]]:
    """The planner's parts, tidied. One part in the top folder is no parts at all (the project itself)."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for s in raw if isinstance(raw, list) else []:
        if not isinstance(s, dict):
            continue
        pid = _text(s.get("id") or s.get("name"), 40).lower().replace(" ", "-")
        if not _ID.fullmatch(pid) or pid in seen:
            pid = f"part{len(out) + 1}"
        seen.add(pid)
        part = {"id": pid, "name": _text(s.get("name"), 80) or pid, "folder": clean_folder(s.get("folder") or pid)}
        if _text(s.get("kind"), 60):
            part["kind"] = _text(s.get("kind"), 60)
        out.append(part)
    if len(out) == 1 and out[0]["folder"] == ".":
        return []
    return out


def _ids(items: list[dict[str, Any]] | None) -> list[str]:
    return [x["id"] for x in items or [] if isinstance(x, dict) and x.get("id")]


def stage_of(task: Any, stages: list[dict[str, Any]] | None, goal_index: int | None = None) -> str:
    """The stage a task really belongs to. An unknown or missing stage is the last one (a sloppy plan is
    repaired, not refused); a task added mid-run without one, or of another goal, belongs to none ("")."""
    ids = _ids(stages)
    if not ids or (goal_index is not None and getattr(task, "goal_index", 0) != goal_index):
        return ""
    if task.stage in ids:
        return task.stage
    return "" if getattr(task, "added_by", "") else ids[-1]


def part_of(task: Any, parts: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    for p in parts or []:
        if p.get("id") == task.part:
            return p
    return None


def files_of(task: Any, parts: list[dict[str, Any]] | None) -> list[str]:
    """The task's files, each in its part's folder: a bare path of a part's task goes into that part's folder
    (unless it is already in another part's)."""
    part = part_of(task, parts)
    folder = (part or {}).get("folder", ".")
    folders = [p["folder"] for p in parts or [] if p.get("folder", ".") != "."]
    out = []
    for f in task.files or []:
        f = str(f).strip().replace("\\", "/")
        while f.startswith("./"):
            f = f[2:]
        if not f:
            continue
        if folder != "." and not any(f == d or f.startswith(d + "/") for d in folders):
            f = f"{folder}/{f}"
        if f not in out:
            out.append(f)
    return out


def _is_dir(p: str) -> bool:
    return p.endswith("/")


def _match(path: str, pattern: str) -> bool:
    """A file against one planned path: the same file, inside a planned folder, or matched by a glob."""
    if path == pattern:
        return True
    if _is_dir(pattern) or "*" not in pattern and "?" not in pattern and "[" not in pattern:
        d = pattern.rstrip("/")
        if path.startswith(d + "/"):
            return True
    return fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(path, pattern.rstrip("/") + "/*")


def patterns_overlap(a: str, b: str) -> bool:
    """Whether two planned paths (files, folders or globs) may name the same file."""
    a, b = a.strip(), b.strip()
    if not a or not b:
        return False
    return a == b or _match(a, b) or _match(b, a)


def shared(a: list[str], b: list[str]) -> list[str]:
    """The planned paths of ``a`` that overlap one of ``b``'s."""
    return [x for x in a if any(patterns_overlap(x, y) for y in b)]


def _ordered(tasks: list[Any]) -> set[tuple[str, str]]:
    """Every (earlier, later) pair already put in order by the tasks' dependencies."""
    deps = {t.id: list(t.depends_on) for t in tasks}
    out: set[tuple[str, str]] = set()
    for tid, first in deps.items():
        seen, todo = set(), list(first)
        while todo:
            d = todo.pop()
            if d in seen:
                continue
            seen.add(d)
            out.add((d, tid))
            todo += deps.get(d, [])
    return out


def overlaps(tasks: list[Any], stages: list[dict[str, Any]] | None = None,
             parts: list[dict[str, Any]] | None = None, goal_index: int | None = None) -> list[dict[str, Any]]:
    """Warnings for the plan: two tasks still to do, free to run at once, that change the same file.
    "T4 and T7 both change game.js: they'll run one after the other". Tasks in different stages, or already put
    in order by their dependencies, never run together and get no warning."""
    todo = [t for t in tasks if t.status not in FINISHED and t.files]
    order = _ordered(tasks)
    out = []
    for i, a in enumerate(todo):
        for b in todo[i + 1:]:
            if stages and stage_of(a, stages, goal_index) != stage_of(b, stages, goal_index):
                continue
            if (a.id, b.id) in order or (b.id, a.id) in order:
                continue
            both = shared(files_of(a, parts), files_of(b, parts))
            if not both:
                continue
            names = ", ".join(both[:3]) + (f" and {len(both) - 3} more" if len(both) > 3 else "")
            out.append({"id": f"overlap:{a.id}:{b.id}", "by": "stages", "kind": "overlap", "tasks": [a.id, b.id],
                        "files": both, "text": f"{a.id} and {b.id} both change {names}: they'll run one after the other"})
    return out


def size_warnings(sizes: dict[str, str], tasks: list[Any]) -> list[dict[str, Any]]:
    open_ids = {t.id for t in tasks if t.status not in FINISHED}
    return [{"id": f"size:{tid}", "by": "stages", "kind": "size", "tasks": [tid],
             "text": f"{tid} is planned as a large task: it may be split into smaller ones if it runs out of steps"}
            for tid, s in sizes.items() if s == "large" and tid in open_ids]


def outside_plan(planned: list[str], changed: list[str]) -> list[str]:
    """The changed files the plan didn't name (the harness's own files never count)."""
    return [f for f in changed if not f.startswith(IGNORED) and not any(_match(f, p) for p in planned)]


# -- where each stage stands -----------------------------------------------------------------------------------
def progress(doc: dict[str, Any] | None, tasks: list[Any]) -> list[dict[str, Any]]:
    """Each stage with how many of its tasks are done and its state: done, now (being built), stuck (being built,
    something failed) or waiting."""
    doc = doc or {}
    stages = doc.get("stages") or []
    gi = doc.get("goal_index")
    rows, current = [], None
    for s in stages:
        mine = [t for t in tasks if stage_of(t, stages, gi) == s["id"]]
        done = sum(t.status in FINISHED for t in mine)
        finished = done == len(mine)
        if finished:
            state = "done"
        elif current is None:
            current = s["id"]
            state = "stuck" if any(t.status == "failed" for t in mine) else "now"
        else:
            state = "waiting"
        rows.append({"id": s["id"], "title": s.get("title", ""), "shows": s.get("shows", ""), "done": done,
                     "total": len(mine), "state": state, "tasks": [t.id for t in mine]})
    return rows


def current_stage(doc: dict[str, Any] | None, tasks: list[Any]) -> str:
    """The earliest stage not finished yet ("" when there are no stages or all are finished)."""
    return next((r["id"] for r in progress(doc, tasks) if r["state"] != "done"), "")


def markdown(doc: dict[str, Any], tasks: list[Any] | None) -> list[str]:
    """The plan's task list as markdown lines, under a heading per stage when the plan has stages (the same
    "## Tasks" list as before when it has none)."""
    tasks = list(tasks or [])
    if not tasks:
        return []
    # the part goes before the role, so "- [T1] done Title (role)" still reads the same in every parser
    line = lambda t, part="": f"- [{t.id}] {t.status} {t.title}{part} ({t.role})"
    stages = doc.get("stages") or []
    if not stages:
        return ["## Tasks"] + [line(t) for t in tasks] + [""]
    gi = doc.get("goal_index")
    parts = doc.get("parts") or []
    pname = {p["id"]: p.get("name") or p["id"] for p in parts}
    L = ["## Tasks"]
    if parts:
        L.append("Parts: " + "; ".join(f"{p.get('name') or p['id']} (in {p.get('folder', '.')}/)" for p in parts))
    for n, s in enumerate(progress(doc, tasks), 1):
        L.append(f"### Stage {n}: {s['title']} [{s['id']}]")
        if s.get("shows"):
            L.append(f"At the end you can try: {s['shows']}")
        for t in tasks:
            if t.id in s["tasks"]:
                L.append(line(t, f" · {pname[t.part]}" if t.part in pname else ""))
    free = [t for t in tasks if not stage_of(t, stages, gi)]
    if free:
        L.append("### Added along the way")
        L += [line(t) for t in free]
    return L + [""]


# -- the record in .harness/stages.json ---------------------------------------------------------------------------
def path(root: str | Path) -> Path:
    return Path(root) / ".harness" / RECORD


def read(root: str | Path) -> dict[str, Any]:
    p = path(root)
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("boundaries", {})
    data.setdefault("strayed", {})
    data.setdefault("sizes", {})
    return data


def write(root: str | Path, data: dict[str, Any]) -> None:
    p = path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{RECORD}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(p)


def changed_files(root: str | Path, task_id: str) -> list[str] | None:
    """The files the task's own commit changed ("[T3] …", a merge when tasks ran at once); None when there's no
    such commit or no git. Read only."""
    root = Path(root)
    if not (root / ".git").exists():
        return None
    from .safeenv import clean_env

    def git(*a: str) -> str | None:
        r = subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, env=clean_env(), check=False)
        return r.stdout if r.returncode == 0 else None

    sha = (git("log", "-1", "--format=%H", "--fixed-strings", f"--grep=[{task_id}] ") or "").strip()
    if not sha:
        return None
    parents = (git("rev-list", "--parents", "-n", "1", sha) or "").split()
    if len(parents) > 1:
        out = git("diff", "--name-only", parents[1], sha)
    else:
        out = git("show", "--name-only", "--format=", sha)
    return [ln.strip() for ln in (out or "").splitlines() if ln.strip()]


def strayed(root: str | Path, task: Any, parts: list[dict[str, Any]] | None = None) -> list[str]:
    """The files the task's commit changed that its plan didn't name (shown, never a failure). Nothing when the
    task named no files or there's no commit to look at."""
    planned = files_of(task, parts)
    if not planned:
        return []
    return outside_plan(planned, changed_files(root, task.id) or [])


# -- what the apps show (GET /api/stages) ------------------------------------------------------------------------
def view(root: str | Path) -> dict[str, Any]:
    from .orchestrator import Project

    project = Project(root)
    doc = project.plan_doc() or {}
    gi = doc.get("goal_index", 0)
    tasks = [t for t in project.tasks() if t.goal_index == gi]
    rec = read(project.root)
    rows = progress(doc, tasks)
    for r in rows:
        b = rec["boundaries"].get(r["id"]) or {}
        r["ready_at"] = b.get("at", "")
    strays = [{"task": tid, "files": v.get("files", [])} for tid, v in rec["strayed"].items()
              if any(t.id == tid for t in tasks)]
    now = next((r for r in rows if r["state"] != "done"), None)
    if not rows:
        words = ""
    elif now is None:
        words = "Every stage is built."
    else:
        n = rows.index(now) + 1
        words = (f"Stage {n} of {len(rows)}: {now['title']}" + (f" – then you can try {now['shows']}" if now["shows"] else "")
                 + (". Something in it didn't pass." if now["state"] == "stuck" else "."))
    return {"stages": rows, "parts": doc.get("parts") or [], "words": words,
            "warnings": [w for w in doc.get("warnings") or [] if isinstance(w, dict)], "strayed": strays,
            "files": {t.id: files_of(t, doc.get("parts")) for t in tasks if t.files}}


# -- the Orchestrator's side ------------------------------------------------------------------------------------
PLAN_WORDS = (
    "\n\n# Stages, parts and files\n"
    "- Split the work into 2 to 4 stages in submit_plan's `stages` (id M1, M2…, a short title, and `shows`: what "
    "the owner can try at the end of it, in plain words). Stage M1 is a working slice: the smallest version that "
    "starts and shows something real (a page that opens, a game you can move in). Later stages grow it. Give every "
    "task its `stage`.\n"
    "- Only when the idea truly has more than one part (a game and its web page, an app and its server), list them "
    "in `parts` (id, name, folder, kind) and give every task its `part`. Each part lives in its own folder.\n"
    "- Give every task `files`: the paths from the project's top folder (or globs such as src/*.js) it creates or "
    "changes, and `size` (small, medium or large). Two tasks of a stage that change the same file run one after the "
    "other. Split a large task into smaller ones.\n"
)
SKELETON_WORDS = "- This kind always starts with a working slice: stage M1 is the folder layout and a first version that starts.\n"


class StagesStage:
    """The stages' mixin for the Orchestrator (hooks named in Orchestrator.PLAN_PARTS, SCHEMA_PARTS, DOC_PARTS,
    WORKER_PARTS and ``_stage_ready``)."""

    # -- planning ------------------------------------------------------------------------------------------------
    def _stages_plan_part(self) -> str:
        words = PLAN_WORDS
        try:
            kind = self._kind()
            if kind and (kind.plan or {}).get("skeleton_first"):
                words += SKELETON_WORDS
        except Exception as e:  # noqa: BLE001 - the kind is a help here
            self.emit("stage_error", {"stage": "_stages_plan_part", "error": str(e)[:300]})
        return words

    def _stages_schema(self, schema: dict[str, Any]) -> None:
        s = {"type": "string"}
        props = schema.setdefault("properties", {})
        props["stages"] = {
            "type": "array", "description": "2 to 4 stages; M1 is a working slice that starts and shows something",
            "items": {"type": "object", "properties": {
                "id": {**s, "description": "M1, M2…"}, "title": {**s, "description": "a few plain words"},
                "shows": {**s, "description": "what the owner can try at the end of this stage, in plain words"}},
                "required": ["id", "title", "shows"]}}
        props["parts"] = {
            "type": "array", "description": "only when the idea truly has more than one part (a game and its web page)",
            "items": {"type": "object", "properties": {
                "id": {**s, "description": "short, like game or site"}, "name": s,
                "folder": {**s, "description": "its own folder, relative to the project, like game/"},
                "kind": {**s, "description": "optional: what kind of thing it is, like website or godot-game"}},
                "required": ["id", "name", "folder"]}}
        task = ((props.get("tasks") or {}).get("items") or {}).setdefault("properties", {})
        task["files"] = {"type": "array", "items": s,
                         "description": "the files (paths from the top folder, or globs) this task creates or changes"}
        task["stage"] = {**s, "description": "the id of its stage, like M1"}
        task["part"] = {**s, "description": "the id of its part (only when there are parts)"}
        task["size"] = {**s, "enum": list(SIZES), "description": "a rough size: small, medium or large"}

    def _stages_doc(self, doc: dict[str, Any], args: dict[str, Any]) -> None:
        """The stages and parts in the plan document, every task checked against them (repaired, never refused),
        and the overlap warnings."""
        stages = clean_stages(args.get("stages")) or doc.get("stages") or []
        parts = clean_parts(args.get("parts")) if args.get("parts") else (doc.get("parts") or [])
        if stages:
            doc["stages"] = stages
        if parts:
            doc["parts"] = parts
        raw = [t for t in args.get("tasks") or [] if isinstance(t, dict)]
        rec = read(self.project.root)
        for t in raw:
            size = str(t.get("size") or "").lower()
            if size in SIZES and t.get("id"):
                rec["sizes"][str(t["id"])] = size
        write(self.project.root, rec)
        self._stages_repair(doc)
        from .orchestrator import Task

        gi = doc.get("goal_index", 0)
        named = {str(t.get("id")) for t in raw}
        mine = [Task.from_dict({**t, "goal_index": gi}) for t in raw if t.get("id")]
        mine += [t for t in self.project.tasks() if t.goal_index == gi and t.id not in named and t.status == "running"]
        warn = overlaps(mine, stages, parts, gi) + size_warnings(rec["sizes"], mine)
        kept = [w for w in doc.get("warnings") or [] if not (isinstance(w, dict) and w.get("by") == "stages")]
        doc["warnings"] = kept + warn
        if not doc["warnings"]:
            doc.pop("warnings")

    def _stages_repair(self, doc: dict[str, Any]) -> list[str]:
        """The saved tasks of the plan's goal put right: an unknown stage becomes the last one, an unknown part
        none, files inside their part's folder. Returns the ids changed."""
        stages, parts = doc.get("stages") or [], doc.get("parts") or []
        if not stages and not parts:
            return []
        tasks = self.project.tasks()
        changed = self._stages_fix(tasks, doc)
        if changed:
            self.project.save_tasks(tasks)
        return changed

    def _stages_fix(self, tasks: list[Any], doc: dict[str, Any]) -> list[str]:
        stages, parts = doc.get("stages") or [], doc.get("parts") or []
        gi = doc.get("goal_index", 0)
        pids = set(_ids(parts))
        changed = []
        for t in tasks:
            if t.goal_index != gi or t.status in FINISHED:
                continue
            before = (t.stage, t.part, list(t.files))
            s = stage_of(t, stages, gi)
            if s:
                t.stage = s
            if t.part and t.part not in pids:
                t.part = ""
            if parts:
                t.files = files_of(t, parts)
            if (t.stage, t.part, t.files) != before:
                changed.append(t.id)
        return changed

    # -- building ------------------------------------------------------------------------------------------------
    def _stages_worker_part(self, task: Any) -> str:
        doc = self.project.plan_doc() or {}
        stages, parts = doc.get("stages") or [], doc.get("parts") or []
        lines = []
        sid = stage_of(task, stages, doc.get("goal_index"))
        if sid:
            n = _ids(stages).index(sid) + 1
            s = stages[n - 1]
            lines.append(f"This task is in stage {sid} of {len(stages)}, “{s.get('title', '')}”."
                         + (f" At the end of this stage the owner can try: {s['shows']}." if s.get("shows") else ""))
            if n == 1:
                lines.append("Stage 1 is a working slice: keep it small, and make sure it starts and shows something.")
        part = part_of(task, parts)
        if part:
            lines.append(f"Part: {part.get('name') or part['id']}, in the folder {part.get('folder', '.')}/. "
                         "Keep its files there.")
        files = files_of(task, parts)
        if files:
            lines.append(f"Your files: {', '.join(files[:20])}. Change other files only if you must, and say which "
                         "in your summary.")
        return ("# Your stage, part and files\n" + "\n".join(lines)) if lines else ""

    def _stage_ready(self, ready: list[Any], tasks: list[Any], running_ids: set[str]) -> list[Any]:
        """Which of the ready tasks may start now: those of the earliest unfinished stage, never two that change
        the same file at once. Runs the between-stages step once at each boundary."""
        doc = self.project.plan_doc() or {}
        stages, parts = doc.get("stages") or [], doc.get("parts") or []
        gi = doc.get("goal_index", 0)
        if stages:
            self._stages_fix(tasks, doc)  # a revision's tasks put right (the caller saves them with its next save)
            if not running_ids:
                fresh = self._stage_boundary(doc, tasks)
                if fresh == "stop":
                    return []
                if fresh == "replanned":  # the later stages changed: the caller's list follows, ready again
                    doc = self.project.plan_doc() or doc
                    stages, parts = doc.get("stages") or stages, doc.get("parts") or parts
                    tasks[:] = self.project.tasks()
                    self._stages_fix(tasks, doc)
                    by_id = {t.id: t for t in tasks}
                    ready = [t for t in tasks if t.status == "pending" and t.id not in running_ids
                             and all(by_id[d].status == "done" for d in t.depends_on if d in by_id)]
            now = current_stage(doc, tasks)
            ready = [t for t in ready if not stage_of(t, stages, gi) or stage_of(t, stages, gi) == now]
        busy = [files_of(t, parts) for t in tasks if t.id in running_ids and t.files]
        picked: list[Any] = []
        for t in ready:
            mine = files_of(t, parts)
            if mine and any(shared(mine, other) for other in busy):
                continue  # it changes a file a running (or earlier picked) task changes: it waits its turn
            picked.append(t)
            if mine:
                busy.append(mine)
        if len(picked) < len(ready):
            held = [t.id for t in ready if t not in picked]
            key = tuple(held)
            if getattr(self, "_stages_held", None) != key:
                self._stages_held = key
                self.emit("files_wait", {"tasks": held, "words": "they change the same files as a task already "
                                                                 "running: they run after it"})
        return picked

    def _stage_boundary(self, doc: dict[str, Any], tasks: list[Any]) -> str | None:
        """Stage N is all done and N+1 waits: once per boundary, say it's ready to try, re-plan the later stages
        when N left lessons, and mark it. "stop" when the owner asked to stop after each stage, "replanned" when
        the later stages changed, else None."""
        rows = progress(doc, tasks)
        rec = read(self.project.root)
        for i, r in enumerate(rows[:-1]):
            if r["state"] != "done" or rows[i + 1]["state"] == "done":
                continue
            mark = rec["boundaries"].get(r["id"])
            if mark:
                if mark.get("stopped") and not mark.get("resumed"):
                    mark["resumed"] = utcnow()  # the owner carried on: never stop at this one again
                    write(self.project.root, rec)
                    self._resolved("stage", note="carried on to the next stage")
                continue
            return self._stage_step(doc, tasks, rows, i, rec)
        return None

    def _stage_step(self, doc, tasks, rows, i, rec) -> str | None:
        r, nxt = rows[i], rows[i + 1]
        n, total = i + 1, len(rows)
        words = f"Stage {n} is ready to try: {r['shows'] or r['title']}."
        mark = {"at": utcnow(), "next": nxt["id"], "replanned": False}
        rec["boundaries"][r["id"]] = mark
        write(self.project.root, rec)  # marked first: whatever happens next, this boundary never runs twice
        self.emit("stage_done", {"stage": r["id"], "index": n, "total": total, "shows": r["shows"]})
        self._journal("note", words, details=f"Next: stage {n + 1} of {total}, {nxt['title']}.")
        got = None
        lessons = self._stage_lessons(doc, tasks, r, rec)
        if lessons:
            later = ", ".join(x["id"] for x in rows[i + 1:])
            try:
                res = self.revise_plan(
                    f"Stage {r['id']} ({r['title']}) is finished. What it taught us:\n"
                    + "\n".join(f"- {x}" for x in lessons)
                    + f"\nAdjust the tasks of the later stages ({later}) to fit what is really there now. Keep every "
                    "task that still fits exactly as it is, keep each task's stage, part and files, and keep the "
                    "stages themselves.", by="harness")
                mark.update(replanned=True, summary=res.get("summary", ""))
                self.emit("stage_replanned", {"stage": r["id"], "summary": res.get("summary", "")})
                got = "replanned"
            except BudgetExceeded:
                raise  # money stops the run: the run's own handler pauses it
            except Exception as e:  # noqa: BLE001 - a help: the later stages stay as they were
                mark["replan_error"] = str(e)[:300]
                self.emit("stage_error", {"stage": "_stage_boundary", "error": str(e)[:300]})
            rec = read(self.project.root)
            rec["boundaries"][r["id"]] = mark
            write(self.project.root, rec)
        if self._stage_stop_setting() == "each":
            mark["stopped"] = True
            rec = read(self.project.root)
            rec["boundaries"][r["id"]] = mark
            write(self.project.root, rec)
            self._stages_stop = "paused"
            self._attention("stage", f"{words} Try it, then carry on when you're ready.",
                            details=f"The next stage is {nxt['title']}. Run the project again to carry on.")
            return "stop"
        return got

    def _stage_lessons(self, doc, tasks, row, rec) -> list[str]:
        """What a finished stage taught: tasks that needed another go, help from another task, files changed
        outside the plan."""
        ids = set(row["tasks"])
        out = []
        for t in tasks:
            if t.id in ids:
                tries = [a for a in t.attempts if a.get("outcome") != "approved"]
                if tries:
                    out.append(f"{t.id} ({t.title}) needed {len(tries) + 1} goes: "
                               + "; ".join(str(a.get("review") or a.get("error") or a.get("outcome") or "")[:160] for a in tries[-2:]))
                if t.status == "skipped":
                    out.append(f"{t.id} ({t.title}) was skipped")
                if t.parked:
                    out.append(f"{t.id} ({t.title}) was put aside: {t.parked[:200]}")
            elif t.handoff_from in ids or t.fix_of in ids:
                out.append(f"{t.id} ({t.title}) was added to help with {t.handoff_from or t.fix_of}")
        for tid, v in rec.get("strayed", {}).items():
            if tid in ids and v.get("files"):
                out.append(f"{tid} changed files the plan didn't name: {', '.join(v['files'][:6])}")
        return out

    def _stage_stop_setting(self) -> str:
        """The project setting ``stage_stop`` (off, each); off when it isn't set or the harness doesn't know it."""
        from . import projectsettings

        try:
            v = projectsettings.load(self.project.root).values.get("stage_stop")
            if v is None:
                raw, _ = projectsettings._read_raw(self.project.root / projectsettings.PROJECT_FILE)
                v = raw.get("stage_stop")
        except Exception:  # noqa: BLE001
            return "off"
        v = str(v or "off").strip().lower()
        return v if v in STAGE_STOPS else "off"

    def _stage_stop(self) -> str | None:
        """The status to stop with when the between-stages step asked to wait for the owner (once)."""
        stop, self._stages_stop = getattr(self, "_stages_stop", None), None
        if stop:
            self._set_status("paused", pause="stage")
        return stop

    def _stage_after_task(self, task: Any) -> list[str]:
        """After a task passed: the files it changed that its plan didn't name, written down and shown."""
        if task.status != "done" or not task.files:
            return []
        doc = self.project.plan_doc() or {}
        try:
            extra = strayed(self.project.root, task, doc.get("parts"))
        except (OSError, subprocess.SubprocessError):
            return []
        if extra:
            rec = read(self.project.root)
            rec["strayed"][task.id] = {"at": utcnow(), "files": extra[:50]}
            write(self.project.root, rec)
            self.emit("files_strayed", {"task": task.id, "files": extra[:50],
                                        "words": f"{task.id} also changed {len(extra)} file{'s' * (len(extra) != 1)} "
                                                 f"its plan didn't name. {NAME} only notes it."})
        return extra
