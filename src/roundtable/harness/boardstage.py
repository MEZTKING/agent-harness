"""The board: every task as a card in a column, and the few moves the owner may make by hand.

Columns, in order: To do, Building, Waiting for you, Stuck, Done, and Left out (shown only when it has
cards). A card is the task's id (like T12), its short title and one line; who built and checked it sits
under ``more``.

A move goes only through actions the orchestrator already has (``retry``, ``skip``, ``accept``) plus one
new one, the order of ready tasks:

* Stuck or Done → To do ("Do it again"; from Done it asks first and says what it will cost);
* To do → Left out (``skip``), and Left out → To do (``retry``);
* Waiting for you → Done only as "Accept as it is" (``accept``, with a confirm), or → To do (``retry``);
* up and down within To do (the order, honoured among tasks whose depends-on are met).

Never into Building by hand, never past an unmet depends-on, never while another machine builds the
project, and never a change of a task's state while this computer's run is going (the order may change
any time: it is read before each pick). A refused move raises ``HarnessError`` with one plain sentence.

The owner's order and "left out" marks live in ``.harness/board.json`` ({"order": [ids], "left_out":
[ids]}), never in ``tasks.json``: the planner rewrites that list, and it keeps ids, so both survive a
rewrite. Hygiene (``archive_earlier``): once a later goal is being built, the earlier goals' finished
tasks move to ``.harness/tasks-archive/goal-<n>.json`` – written and read back before the live list is
shortened, nothing deleted, and a task any remaining task depends on stays in the live list.

Hooks for the run (the coordinator wires them): ``_board_order(ready)`` puts the ready tasks in the
owner's order; ``_board_archive()`` tidies earlier goals at the start of a run; ``_board_stop()`` pauses
the run between tasks when the owner tapped "Stop it" on a quiet run (``quiet.py``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BOARD = "board.json"
ARCHIVE_DIR = "tasks-archive"
STOP_REQUEST = "board-stop.json"
SKIPPED_NOTE = "(skipped by owner)"

COLUMNS = (
    ("todo", "To do"),
    ("building", "Building"),
    ("waiting", "Waiting for you"),
    ("stuck", "Stuck"),
    ("done", "Done"),
    ("left_out", "Left out"),
)
COLUMN_NAMES = dict(COLUMNS)

# the plain sentences a refused move gives (tests read them)
REFUSE = {
    "building": "A task goes into Building by itself when its turn comes: it can't be put there by hand.",
    "running": "{id} is being built right now: wait for it to finish, then move it.",
    "elsewhere": "This project is being built on {machine} right now: move its cards there, or once it stops.",
    "busy": "A run is going on this project: only the order of To do can change until it stops.",
    "unknown": "There's no task {id} on this board any more. Look at the board again.",
    "same": "{id} is already in {column}.",
    "not_allowed": "{id} can't go from {frm} to {to}. {hint}",
    "depends": "{id} can't go above {other}: it needs {other} done first.",
    "edge": "{id} is already at the {end} of To do.",
    "confirm_again": "Are you sure? {id} was finished: doing it again costs {cost}. It's built when the project next runs.",
    "confirm_accept": "Are you sure? {id} didn't pass its check. Accepting it keeps the work as it is in the files and counts it as done.",
    "command": "{id} is waiting for your answer on a command: answer it in Needs you first.",
}
HINTS = {
    "todo": "From To do, a task can only be left out, or moved up and down.",
    "done": "From Done, a task can only be done again.",
    "stuck": "From Stuck, a task can only be done again.",
    "waiting": "From Waiting for you, a task can be accepted as it is or done again.",
    "left_out": "From Left out, a task can only go back to To do.",
}


# -- the board's own file ---------------------------------------------------------------------------------
def _hdir(root: str | Path) -> Path:
    return Path(root) / ".harness"


def read_board(root: str | Path) -> dict[str, list[str]]:
    try:
        raw = json.loads((_hdir(root) / BOARD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    return {"order": [str(x) for x in raw.get("order") or [] if str(x)],
            "left_out": [str(x) for x in raw.get("left_out") or [] if str(x)]}


def save_board(root: str | Path, board: dict[str, list[str]]) -> None:
    from .orchestrator import Project

    Project(root)._write(BOARD, {"order": list(dict.fromkeys(board.get("order") or [])),
                                 "left_out": list(dict.fromkeys(board.get("left_out") or []))})


def ordered(tasks: list[Any], order: list[str]) -> list[Any]:
    """``tasks`` in the owner's order: ordered ids first (in that order), the rest after, as they were."""
    rank = {tid: i for i, tid in enumerate(order)}
    return sorted(tasks, key=lambda t: (0, rank[t.id]) if t.id in rank else (1, 0))  # stable: the rest keep theirs


def left_out(task: Any, board: dict[str, list[str]]) -> bool:
    return task.status == "done" and (task.id in board["left_out"] or (task.summary or "").strip() == SKIPPED_NOTE)


# -- which column ---------------------------------------------------------------------------------------
def waiting_ids(asks: list[dict[str, Any]]) -> dict[str, str]:
    """Task ids an open card waits on, with the card's kind ("failed" or "command")."""
    out: dict[str, str] = {}
    for a in asks or []:
        src = a.get("source") or {}
        task = a.get("task") if isinstance(a.get("task"), dict) else {}
        tid = src.get("task") or task.get("id")
        if tid and a.get("answer") is None:
            out.setdefault(str(tid), str(a.get("kind") or ""))
    return out


def column_of(task: Any, waiting: dict[str, str], board: dict[str, list[str]]) -> str:
    if task.status == "running":
        return "waiting" if waiting.get(task.id) == "command" else "building"
    if task.status == "failed":
        return "waiting" if task.id in waiting else "stuck"
    if task.status == "done":
        return "left_out" if left_out(task, board) else "done"
    if task.status == "skipped":
        return "left_out"
    return "todo"


def _line(task: Any, column: str) -> str:
    last = task.attempts[-1] if task.attempts else {}
    if column == "todo":
        return f"After {', '.join(task.depends_on)}" if task.depends_on else "Ready when its turn comes"
    if column == "building":
        return "Being built now"
    if column == "waiting":
        return "Waiting for your answer in Needs you"
    if column == "stuck":
        why = task.parked or last.get("review") or last.get("error") or ""
        return ("Didn't pass: " + " ".join(str(why).split()))[:140] if why else "Didn't pass its check"
    if column == "left_out":
        return "Left out by you"
    return " ".join(str(task.summary or "Done").split())[:140]


def card(task: Any, column: str) -> dict[str, Any]:
    last = task.attempts[-1] if task.attempts else {}
    more = {"role": task.role, "tries": len(task.attempts)}
    if last.get("model"):
        more["built_by"] = last["model"]
    for key in ("reviewer_model", "reviewer", "checked_by"):
        if last.get(key):
            more["checked_by"] = str(last[key])
            break
    if task.depends_on:
        more["after"] = list(task.depends_on)
    return {"id": task.id, "number": task.id, "title": task.title or task.id, "line": _line(task, column),
            "column": column, "status": task.status, "more": more}


def moves_for(column: str) -> list[dict[str, Any]]:
    """The moves a card in ``column`` offers, as buttons: {to, label, confirm?}."""
    if column == "todo":
        return [{"to": "up", "label": "Move up"}, {"to": "down", "label": "Move down"},
                {"to": "left_out", "label": "Leave it out"}]
    if column == "left_out":
        return [{"to": "todo", "label": "Put it back in To do"}]
    if column == "stuck":
        return [{"to": "todo", "label": "Do it again"}]
    if column == "done":
        return [{"to": "todo", "label": "Do it again", "confirm": True}]
    if column == "waiting":
        return [{"to": "done", "label": "Accept as it is", "confirm": True}, {"to": "todo", "label": "Do it again"}]
    return []


# -- hygiene: earlier goals' finished tasks out of the live list ---------------------------------------
def archive_path(root: str | Path, goal_index: int) -> Path:
    return _hdir(root) / ARCHIVE_DIR / f"goal-{goal_index + 1}.json"


def archived(root: str | Path) -> list[dict[str, Any]]:
    """Every archived task (as saved), oldest goal first."""
    d = _hdir(root) / ARCHIVE_DIR
    out: list[dict[str, Any]] = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob("goal-*.json"), key=lambda p: int(p.stem.split("-")[-1]) if p.stem.split("-")[-1].isdigit() else 0):
        try:
            rows = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out += [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    return out


def archive_earlier(project: Any) -> dict[str, Any]:
    """Move the earlier goals' finished tasks to the archive. Returns {"archived": n, "files": [...]}.

    Only once a later goal exists; only tasks that are done; never one a remaining task depends on. Each
    archive file is written and read back (and must hold every task it should) before ``tasks.json`` is
    shortened. A task already in an archive file is merged, never duplicated."""
    from dataclasses import asdict

    from .orchestrator import HarnessError

    meta = project.meta()
    current = max(0, len(meta.get("goals") or []) - 1)
    if current == 0:
        return {"archived": 0, "files": []}
    tasks = project.tasks()
    candidates = [t for t in tasks if t.goal_index < current and t.status == "done"]
    if not candidates:
        return {"archived": 0, "files": []}
    gone = {t.id for t in candidates}
    while True:  # anything still in the live list that needs one of them keeps it there
        kept = [t for t in tasks if t.id not in gone]
        needed = {d for t in kept for d in t.depends_on} & gone
        if not needed:
            break
        gone -= needed
    if not gone:
        return {"archived": 0, "files": []}
    files = []
    by_goal: dict[int, list[Any]] = {}
    for t in tasks:
        if t.id in gone:
            by_goal.setdefault(t.goal_index, []).append(t)
    for gi, ts in sorted(by_goal.items()):
        p = archive_path(project.root, gi)
        try:
            old = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else []
        except (OSError, ValueError) as e:
            raise HarnessError(f"The archive of goal {gi + 1} can't be read ({e}): nothing was moved.")
        old = [r for r in old if isinstance(r, dict)] if isinstance(old, list) else []
        rows = [r for r in old if r.get("id") not in {t.id for t in ts}] + [asdict(t) for t in ts]
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.tmp")
        tmp.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(p)
        back = json.loads(p.read_text(encoding="utf-8"))  # read back: every task must be there before any goes
        if {r.get("id") for r in back} < {t.id for t in ts}:
            raise HarnessError(f"The archive of goal {gi + 1} didn't hold every task when read back: nothing was moved.")
        files.append(str(p))
    project.save_tasks([t for t in tasks if t.id not in gone])
    return {"archived": len(gone), "files": files}


# -- the board as the app shows it ----------------------------------------------------------------------
def board_view(project: Any, asks: list[dict[str, Any]] | None = None, *, can_move: bool = True,
               why_not: str = "") -> dict[str, Any]:
    """{columns: [{id, title, cards: [...]}], earlier: {count, cards}, can_move, why_not}. Left out is
    listed only when it has cards; To do is in the owner's order."""
    board = read_board(project.root)
    waiting = waiting_ids(asks or [])
    tasks = project.tasks()
    cols: dict[str, list[dict[str, Any]]] = {c: [] for c, _ in COLUMNS}
    todo = [t for t in tasks if column_of(t, waiting, board) == "todo"]
    for t in ordered(todo, board["order"]):
        cols["todo"].append(card(t, "todo"))
    for t in tasks:
        col = column_of(t, waiting, board)
        if col != "todo":
            cols[col].append(card(t, col))
    for col, cards in cols.items():
        for c in cards:
            c["moves"] = moves_for(col) if can_move else []
            if waiting.get(c["id"]) == "command":
                c["moves"] = []
    earlier = archived(project.root)
    return {"columns": [{"id": c, "title": name, "cards": cols[c]} for c, name in COLUMNS
                        if c != "left_out" or cols[c]],
            "earlier": {"count": len(earlier), "title": f"Earlier work ({len(earlier)})",
                        "cards": [{"id": r.get("id", ""), "number": r.get("id", ""), "title": r.get("title") or r.get("id", ""),
                                   "line": " ".join(str(r.get("summary") or "Done").split())[:140],
                                   "goal": int(r.get("goal_index") or 0) + 1} for r in earlier]},
            "can_move": can_move, "why_not": why_not}


# -- the stage ------------------------------------------------------------------------------------------
class BoardStage:
    """Moves by hand on the board, the owner's order of ready tasks, tidying earlier goals and the owner's
    stop of a quiet run. Mixed into the Orchestrator (``self.project``, ``retry``, ``skip``, ``accept``,
    ``emit``, ``_estimate``)."""

    def board(self, asks: list[dict[str, Any]] | None = None, *, can_move: bool = True, why_not: str = "") -> dict[str, Any]:
        return board_view(self.project, asks, can_move=can_move, why_not=why_not)

    def move_task(self, task_id: str, to: str, by: str = "owner", *, confirmed: bool = False,
                  claim: dict[str, Any] | None = None, busy: bool = False,
                  asks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Move one card. ``claim``: another machine's fresh claim on this project (then nothing moves);
        ``busy``: this computer is running the project (then only the order changes); ``asks``: the open
        cards (which tasks wait for the owner). Returns {"reply", "column"}; a refused move raises
        ``HarnessError`` with one plain sentence."""
        from .orchestrator import HarnessError

        to = str(to or "").strip()
        if claim:
            raise HarnessError(REFUSE["elsewhere"].format(machine=claim.get("machine_name") or claim.get("machine")
                                                           or "another computer"))
        board = read_board(self.project.root)
        tasks = self.project.tasks()
        task = next((t for t in tasks if t.id == task_id), None)
        if task is None:
            raise HarnessError(REFUSE["unknown"].format(id=task_id))
        waiting = waiting_ids(asks or [])
        frm = column_of(task, waiting, board)
        if to == "building":
            raise HarnessError(REFUSE["building"])
        if frm == "building":
            raise HarnessError(REFUSE["running"].format(id=task.id))
        if waiting.get(task.id) == "command":
            raise HarnessError(REFUSE["command"].format(id=task.id))
        if to in ("up", "down"):
            if frm != "todo":
                raise HarnessError(REFUSE["not_allowed"].format(id=task.id, frm=COLUMN_NAMES[frm], to="another place in To do",
                                                                hint=HINTS.get(frm, "")).strip())
            return self._board_shift(task, tasks, board, waiting, to)
        if to not in COLUMN_NAMES:
            raise HarnessError(f"There's no column called {to!r} on the board.")
        if to == frm:
            raise HarnessError(REFUSE["same"].format(id=task.id, column=COLUMN_NAMES[to]))
        allowed = {("todo", "left_out"), ("left_out", "todo"), ("stuck", "todo"), ("done", "todo"),
                   ("waiting", "done"), ("waiting", "todo")}
        if (frm, to) not in allowed:
            raise HarnessError(REFUSE["not_allowed"].format(id=task.id, frm=COLUMN_NAMES[frm], to=COLUMN_NAMES[to],
                                                            hint=HINTS.get(frm, "")).strip())
        if busy:
            raise HarnessError(REFUSE["busy"])
        if frm == "done" and not confirmed:
            raise HarnessError(REFUSE["confirm_again"].format(id=task.id, cost=self._board_cost(task)))
        if (frm, to) == ("waiting", "done") and not confirmed:
            raise HarnessError(REFUSE["confirm_accept"].format(id=task.id))
        if to == "left_out":
            self.skip(task.id)
            board["left_out"].append(task.id)
            reply = f"{task.id} is left out. The tasks after it carry on without it."
        elif to == "done":
            self.accept(task.id, "accepted on the board")
            reply = f"{task.id} is accepted as it is."
        else:  # back to To do
            self.retry(task.id)
            board["left_out"] = [x for x in board["left_out"] if x != task.id]
            reply = (f"{task.id} is back in To do." if frm == "left_out"
                     else f"{task.id} is back in To do. It's built when the project next runs.")
        save_board(self.project.root, board)
        self.emit("board_move", {"task": task.id, "from": frm, "to": to, "by": by})
        return {"reply": reply, "column": to}

    def _board_shift(self, task: Any, tasks: list[Any], board: dict[str, list[str]], waiting: dict[str, str],
                     way: str) -> dict[str, Any]:
        from .orchestrator import HarnessError

        todo = ordered([t for t in tasks if column_of(t, waiting, board) == "todo"], board["order"])
        i = next(i for i, t in enumerate(todo) if t.id == task.id)
        j = i - 1 if way == "up" else i + 1
        if j < 0 or j >= len(todo):
            raise HarnessError(REFUSE["edge"].format(id=task.id, end="top" if way == "up" else "bottom"))
        other = todo[j]
        upper, lower = (task, other) if way == "up" else (other, task)  # after the swap, upper sits above lower
        if lower.id in _needs(upper, tasks):  # never above a task it needs done first
            raise HarnessError(REFUSE["depends"].format(id=upper.id, other=lower.id))
        todo[i], todo[j] = todo[j], todo[i]
        board["order"] = [t.id for t in todo]
        save_board(self.project.root, board)
        self.emit("board_move", {"task": task.id, "from": "todo", "to": way, "by": "owner"})
        return {"reply": f"{task.id} moved {way}.", "column": "todo"}

    def _board_cost(self, task: Any) -> str:
        """What doing a finished task again would cost, in words ("about $0.40")."""
        from copy import deepcopy

        try:
            again = deepcopy(task)
            again.status = "pending"
            est = self._estimate([again])
            return f"about ${float(est.get('cost_usd') or 0):.2f}"
        except Exception:  # noqa: BLE001 - no price: say so rather than guess
            return "an amount the harness can't price yet"

    # -- hooks the run calls (wired by the coordinator) -----------------------------------------------
    def _board_order(self, ready: list[Any]) -> list[Any]:
        """The ready tasks in the owner's order (only tasks whose depends-on are met are ever here)."""
        order = read_board(self.project.root)["order"]
        return ordered(list(ready), order) if order else ready

    def _board_archive(self) -> None:
        got = archive_earlier(self.project)
        if got["archived"]:
            self.emit("tasks_archived", got)

    def _board_stop(self) -> str | None:
        """The owner tapped "Stop it" on a quiet run: pause before the next task."""
        p = _hdir(self.project.root) / STOP_REQUEST
        if not p.is_file():
            return None
        try:
            p.unlink()
        except OSError:
            pass
        self._set_status("paused", pause="owner_stop")
        self.emit("board_stop", {})
        return "paused"


def _needs(task: Any, tasks: list[Any]) -> set[str]:
    """Every task ``task`` needs done first, directly or through another."""
    by_id = {t.id: t for t in tasks}
    out: set[str] = set()
    todo = list(task.depends_on)
    while todo:
        d = todo.pop()
        if d in out:
            continue
        out.add(d)
        todo += list(getattr(by_id.get(d), "depends_on", []) or [])
    return out


def request_stop(root: str | Path) -> None:
    """Ask the run to pause before its next task (read by ``BoardStage._board_stop``)."""
    from ..core.models import utcnow

    d = _hdir(root)
    d.mkdir(parents=True, exist_ok=True)
    (d / STOP_REQUEST).write_text(json.dumps({"at": utcnow()}) + "\n", encoding="utf-8")
