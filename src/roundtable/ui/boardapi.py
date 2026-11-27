"""The board, what every project is doing, answering several cards, and the task worktrees.

    GET  /api/board?path=            {columns: [{id, title, cards: [{id, number, title, line, column, moves, more}]}],
                                      earlier: {count, title, cards}, can_move, why_not, state: {state, word, line}}
    POST /api/board/move             {path, task, to, confirmed?} -> {reply, column}; to is a column id, "up" or "down".
                                      A refused move answers 400 with one plain sentence; a move that needs a
                                      yes answers 409 with an error starting "Are you sure?"
    GET  /api/board/states           {states: {path: {state, word, line, last_at, quiet_for}}, order: [seat ids]}
    POST /api/board/order            {order: [seat ids]} -> {order}; the Hall's order by hand, kept on this computer
    POST /api/board/answer-several   {items: [{path, id, stamp}]} -> {answered: [...], left: [{id, why}], reply, jobs}
                                      each card's recommended answer; cards whose answer needs a yes, and commands,
                                      are left for the owner to answer alone
    GET  /api/worktrees?path=        {items: [{task, title, branch, unsaved: "yes" | "no" | "can't tell", why, tidy}]}
    GET  /api/worktrees/files?path=&task=   {files: [{path, change}]} what the task's copy changed (never deletes)

The phone may read ``GET /api/board`` only: everything else here changes something or is the desktop's own.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from ..harness import boardstage, quiet
from ..harness.orchestrator import HarnessError

ORDER_FILE = "hall-order.json"


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/board"): lambda q: board(app, _one(q, "path")),
        ("POST", "/api/board/move"): lambda body: move(app, body or {}),
        ("GET", "/api/board/states"): lambda q: states(app),
        ("POST", "/api/board/order"): lambda body: set_order(app, body or {}),
        ("POST", "/api/board/answer-several"): lambda body: answer_several_route(app, body or {}),
        ("GET", "/api/worktrees"): lambda q: worktrees(app, _one(q, "path")),
        ("GET", "/api/worktrees/files"): lambda q: worktree_files(app, _one(q, "path"), _one(q, "task")),
    }


def _one(q: Any, key: str) -> str:
    v = (q or {}).get(key, "")
    return str(v[0] if isinstance(v, list) and v else v or "")


def _error(message: str, status: int = 400):
    from .server import ApiError

    return ApiError(message, status)


# -- the orchestrator with the board stage, before and after the coordinator's hook-up --------------------
def board_class():
    from ..harness.orchestrator import Orchestrator

    if issubclass(Orchestrator, boardstage.BoardStage):
        return Orchestrator
    return type("BoardOrchestrator", (boardstage.BoardStage, Orchestrator), {})


def _orch(app, path: str):
    cfg = app.need_cfg()
    proj = app.project(cfg, path)
    return board_class()(cfg, proj.root)


def other_claim(app, root: Path) -> dict[str, Any] | None:
    """Another machine's fresh claim on this project (it is building it right now), or None."""
    hub = getattr(app, "hub", None)
    if not hub:
        return None
    try:
        from ..sync import claim_fresh, read_claims, this_machine

        me = this_machine()["id"]
        try:
            hub_name = json.loads((root / ".harness" / "project.json").read_text(encoding="utf-8")).get("hub_name")
        except (OSError, ValueError):
            hub_name = None
        for c in read_claims(hub).values():
            ours = c.get("folder") == root.name or (hub_name and c.get("hub_name") == hub_name)
            if ours and claim_fresh(c) and c.get("machine") != me:
                return c
    except Exception:  # noqa: BLE001 - the hub can't be read: nothing shows it is taken
        return None
    return None


def _asks(orch) -> list[dict[str, Any]]:
    from ..asks import open_asks

    try:
        return open_asks(orch)
    except Exception:  # noqa: BLE001 - the board still shows without them
        return []


# -- the board ----------------------------------------------------------------------------------------------
def board(app, path: str) -> dict[str, Any]:
    orch = _orch(app, path)
    root = orch.project.root
    claim = other_claim(app, root)
    why = (boardstage.REFUSE["elsewhere"].format(machine=claim.get("machine_name") or "another computer")
           if claim else "")
    busy = app._busy(root)
    view = orch.board(_asks(orch), can_move=not claim, why_not=why)
    view["busy"] = busy
    view["state"] = quiet.state(root, cfg=orch.cfg, busy=busy)
    return view


def move(app, body: dict[str, Any]) -> dict[str, Any]:
    orch = _orch(app, str(body.get("path", "")))
    root = orch.project.root
    try:
        return orch.move_task(str(body.get("task", "")), str(body.get("to", "")), confirmed=bool(body.get("confirmed")),
                              claim=other_claim(app, root), busy=app._busy(root), asks=_asks(orch))
    except HarnessError as e:
        text = str(e)
        if text.startswith("Are you sure?"):
            raise _error(text, 409)  # the app asks "Are you sure?" and sends confirmed
        raise _error(text)


# -- what every project is doing, and the Hall's order -------------------------------------------------------
def _home(app) -> Path:
    return Path(app._backup_home())


def read_order(home: Path) -> list[str]:
    try:
        raw = json.loads((home / ORDER_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [str(x) for x in raw.get("order") or []] if isinstance(raw, dict) else []


def save_order(home: Path, order: list[str]) -> list[str]:
    clean = list(dict.fromkeys(str(x) for x in order if str(x).strip()))[:500]
    home.mkdir(parents=True, exist_ok=True)
    tmp = home / f".{ORDER_FILE}.tmp"
    tmp.write_text(json.dumps({"order": clean}) + "\n", encoding="utf-8")
    tmp.replace(home / ORDER_FILE)
    return clean


def states(app) -> dict[str, Any]:
    out: dict[str, Any] = {}
    cfg = app.cfg()
    roots: list[Path] = []
    if cfg:
        try:
            roots = [Path(p) for p in app.lab(cfg).projects()]
        except Exception:  # noqa: BLE001 - no lab yet: no projects
            roots = []
    for root in roots:
        try:
            out[str(root)] = quiet.state(root, cfg=cfg, busy=app._busy(root))
        except Exception:  # noqa: BLE001 - one project never hides the others
            continue
    return {"states": out, "order": read_order(_home(app))}


def set_order(app, body: dict[str, Any]) -> dict[str, Any]:
    order = body.get("order")
    if not isinstance(order, list):
        raise _error("Send the projects in the order you want them.")
    return {"order": save_order(_home(app), order)}


# -- answering several cards at once ---------------------------------------------------------------------------
def needs_alone(ask: dict[str, Any]) -> str:
    """Why a card can't be answered with the others ("" when it can)."""
    if ask.get("kind") == "command":
        return "A command is always answered on its own."
    rec = ask.get("recommended")
    if not rec:
        return "It has no recommended answer."
    opt = next((o for o in ask.get("options") or [] if o.get("id") == rec), None)
    if not opt:
        return "It has no recommended answer."
    if opt.get("confirm"):
        return "Its recommended answer spends money or can't be undone, so it's answered on its own."
    return ""


def answer_several(orch, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Give each card (by id and the stamp the owner saw) its recommended answer, in order, on one project.

    A card that needs answering alone is left. A card whose question changed since the owner saw it (its
    stamp differs) is refused, as when it is answered alone. The first answer that starts long work (a run,
    a plan update) is kept as ``then``; a later card wanting different long work is left for after it."""
    from ..asks import answer_ask, find_ask

    answered, left, then = [], [], None
    for it in items:
        aid, stamp = str(it.get("id", "")), it.get("stamp") or None
        try:
            ask = find_ask(orch, aid)
        except HarnessError as e:
            left.append({"id": aid, "why": str(e)})
            continue
        why = needs_alone(ask)
        if why:
            left.append({"id": aid, "why": why})
            continue
        if not stamp:
            left.append({"id": aid, "why": "It was sent without the question it answers. Look at it again."})
            continue
        if then and then.get("then") != "run":
            left.append({"id": aid, "why": "It waits until the plan update just started has finished."})
            continue
        try:
            r = answer_ask(orch, aid, [ask["recommended"]], stamp=stamp)
        except HarnessError as e:
            left.append({"id": aid, "why": str(e)})
            continue
        answered.append({"id": aid, "reply": r.get("reply", "")})
        if r.get("then") and not then:
            then = r  # the first long step wins; a run picks up what later answers set
    n = len(answered)
    reply = (f"{n} answered with the recommended answer" if n else "Nothing answered") + (
        f"; {len(left)} left for you to answer on their own." if left else ".")
    return {"answered": answered, "left": left, "then": then, "reply": reply}


def answer_several_route(app, body: dict[str, Any]) -> dict[str, Any]:
    items = body.get("items")
    if not isinstance(items, list) or not items:
        raise _error("Tick the cards to answer first.")
    cfg = app.need_cfg()
    by_path: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        if isinstance(it, dict):
            by_path.setdefault(str(it.get("path", "")), []).append(it)
    answered, left, jobs = [], [], []
    for path, its in by_path.items():
        try:
            proj = app.project(cfg, path)
        except Exception as e:  # noqa: BLE001 - one project never stops the others
            left += [{"id": str(i.get("id", "")), "path": path, "why": str(e)} for i in its]
            continue
        if app._busy(proj.root):
            left += [{"id": str(i.get("id", "")), "path": path,
                      "why": "Something is running on this project: answer it once that finishes."} for i in its]
            continue
        from ..harness.orchestrator import Orchestrator

        r = answer_several(Orchestrator(cfg, proj.root), its)
        answered += [{**a, "path": path} for a in r["answered"]]
        left += [{**x, "path": path} for x in r["left"]]
        if r["then"]:
            jobs.append(app.start_answer_job(cfg, proj.root, r["then"], why="answers to several cards").view())
    n = len(answered)
    reply = (f"{n} answered with the recommended answer" if n else "Nothing answered") + (
        f"; {len(left)} left for you to answer on their own." if left else ".")
    return {"answered": answered, "left": left, "jobs": jobs, "reply": reply}


# -- the task worktrees (MD-73): what each kept copy is, and why it stays ---------------------------------------
def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess | None:
    from ..harness.safeenv import clean_env

    try:
        return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=clean_env(),
                              encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None


def _kept_reasons(root: Path) -> dict[str, str]:
    from ..harness.eventlog import read_events

    out: dict[str, str] = {}
    try:
        for e in read_events(root, include_archives=False):
            if e.get("event") == "worktree_kept" and e.get("task"):
                out[str(e["task"])] = str(e.get("why") or "")
            elif e.get("event") == "worktree_removed" and e.get("task"):
                out.pop(str(e["task"]), None)
    except Exception:  # noqa: BLE001 - no reasons: the panel still lists them
        pass
    return out


def worktree_rows(root: Path) -> list[dict[str, Any]]:
    """Every task worktree of the project, read only. ``tidy`` says what the daily tidy-up does with it, by
    the tidy-up's own rule (retention.py): removed once its task is done, its branch is merged and it holds
    nothing unsaved; kept otherwise."""
    from .. import retention
    from ..harness.orchestrator import Project
    from ..harness.worktrees import BRANCH_PREFIX, Worktrees, safe_name

    root = Path(root)
    trees_dir = root / ".harness" / "worktrees"
    if not trees_dir.is_dir() or trees_dir.is_symlink():
        return []
    tasks = {safe_name(t.id): t for t in Project(root).tasks()}
    reasons = _kept_reasons(root)
    merged = retention._merged_branches(root)
    trees = Worktrees(root)
    rows = []
    for d in sorted(trees_dir.iterdir()):
        if not d.is_dir() or d.is_symlink():
            continue
        t = tasks.get(d.name)
        tid = t.id if t else d.name
        dirty = trees.dirty(tid) if (d / ".git").exists() else None
        unsaved = "can't tell" if dirty is None else "yes" if dirty else "no"
        if not t:
            tidy = "Kept: its task is no longer on the board."
        elif t.status != "done":
            tidy = "Kept: its task isn't finished, so a retry carries on from here."
        elif merged is None:
            tidy = "Kept: git couldn't say whether its work was brought in."
        elif f"{BRANCH_PREFIX}{d.name}" not in merged:
            tidy = "Kept: its work hasn't been brought into the project yet."
        else:
            why = retention._unsaved(d)
            tidy = f"Kept: {why}." if why else "The daily tidy-up removes it: its work is in the project."
        rows.append({"task": tid, "title": t.title if t else "", "branch": f"{BRANCH_PREFIX}{d.name}",
                     "unsaved": unsaved, "why": reasons.get(tid, ""), "tidy": tidy, "folder": str(d)})
    return rows


def worktrees(app, path: str) -> dict[str, Any]:
    cfg = app.need_cfg()
    proj = app.project(cfg, path)
    return {"items": worktree_rows(proj.root)}


def worktree_files(app, path: str, task: str) -> dict[str, Any]:
    from ..harness.worktrees import Worktrees

    cfg = app.need_cfg()
    proj = app.project(cfg, path)
    trees = Worktrees(proj.root)
    if not task or not trees.exists(task):
        raise _error("That task has no copy of the project any more. Look at the list again.", 404)
    files: dict[str, str] = {}
    res = _git(proj.root, "diff", "--name-status", f"HEAD...{trees.branch(task)}")
    for line in (res.stdout if res and res.returncode == 0 else "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            files[parts[-1]] = {"A": "added", "D": "removed"}.get(parts[0][:1], "changed")
    res = _git(trees.path(task), "status", "--porcelain")
    for line in (res.stdout if res and res.returncode == 0 else "").splitlines():
        if len(line) > 3:
            files[line[3:].strip().strip('"')] = "not saved yet" if line[:2] != "??" else "new, not saved yet"
    return {"files": [{"path": p, "change": c} for p, c in sorted(files.items())][:500]}
