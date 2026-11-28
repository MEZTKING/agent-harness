"""The chat's wave 8 parts as an API (stream.js, slash.js, queue.js, voice.js, asks.js; the phone's chat).

Words as they are written (harness/streamlog.py):

    GET  /api/stream?path=&task=&since=   {text, thinking, at, done, skipped}; key-shaped text hidden

``/`` commands (harness/slash.py); each one does what a button does, and one that spends or deletes answers
``{confirm}`` first (send it again with ``confirmed: true``); slow ones come back at once with a ``job``:

    GET  /api/commands?path=              {commands: [{name, words, args, confirm, slow, pc_only, kind}]}
    POST /api/commands     {path, line, confirmed?}  -> {reply, job?, confirm?, open?, results?}  (the phone too:
                           the PC-only commands, which run programs on the PC, are refused here)
    POST /api/commands/pc  the same with every command, for the PC's own app (never offered to the phone)

A follow-up to one task (harness/followstage.py):

    GET  /api/follow?path=&task=          {items: [{at, question, answer | change, model, cost_usd}]}
    POST /api/follow  {path, task, text, mode: ask | change, confirmed?}
                      -> {confirm, estimate} (an ask, before anything is spent) | {job} (an ask, confirmed) |
                         {reply, task} (a change: a new task) | {reply, delivered: "steer"} (the task builds now)

The queue (messages for the next task: the "Next task" notes no task has read yet):

    GET  /api/queue?path=                 {items: [{id, at, text, now?}], running}
    POST /api/queue   {path, action: change | remove | send_now, id, text?}  -> the queue, with {reply}

Timers on questions (asktimer.py):

    POST /api/asktimer {path, id, stamp, minutes, on_expire} | {path, id, hold: true} | {path, id, clear: true}

Talking to the planner (voice.js): the words the browser heard, sent as a question, never as an instruction:

    POST /api/chat/talk {path, text}      -> {reply, action: {line, words, confirm, card, chat} | null}
                          (1.5.0: a message in the project's chat, chat.reply; the action is the answer's card)
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .. import asktimer
from ..harness import slash, streamlog
from ..harness.followstage import FollowError, FollowStage, follow_ups


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/stream"): lambda q: stream(app, q),
        ("GET", "/api/commands"): lambda q: {"commands": slash.table(app, _first(q, "path"))},
        ("POST", "/api/commands"): lambda b: command(app, b or {}, pc=False),
        ("POST", "/api/commands/pc"): lambda b: command(app, b or {}, pc=True),
        ("GET", "/api/follow"): lambda q: {"items": follow_ups(_root(app, _first(q, "path")), _first(q, "task"))},
        ("POST", "/api/follow"): lambda b: follow(app, b or {}),
        ("GET", "/api/queue"): lambda q: queue(app, _first(q, "path")),
        ("POST", "/api/queue"): lambda b: queue_change(app, b or {}),
        ("POST", "/api/asktimer"): lambda b: timer(app, b or {}),
        ("POST", "/api/chat/talk"): lambda b: talk(app, b or {}),
    }


def _first(q: dict, key: str, default: str = "") -> str:
    v = (q or {}).get(key, default)
    if isinstance(v, list):
        v = v[0] if v else default
    return str(v if v is not None else default)


def _error(text: str, status: int = 400):
    from .server import ApiError

    return ApiError(text, status)


def _root(app, path: str) -> Path:
    if not path:
        raise _error("Choose a project first.")
    return app.project(app.need_cfg(), path).root


def _orch(app, root: Path):
    """The project's orchestrator with the follow-up stage (the coordinator adds it to the bases)."""
    from ..harness.orchestrator import Orchestrator

    cls = Orchestrator if issubclass(Orchestrator, FollowStage) else type("FollowOrchestrator", (FollowStage, Orchestrator), {})
    return cls(app.need_cfg(), root)


# -- words as they are written ------------------------------------------------------------------------------
def stream(app, q: dict) -> dict[str, Any]:
    root = _root(app, _first(q, "path"))
    task = _first(q, "task")
    if not task or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", task):
        raise _error("Which task? That name isn't one of this project's tasks.")
    try:
        since = int(_first(q, "since", "0") or 0)
    except ValueError:
        since = 0
    t = next((x for x in app.project(app.need_cfg(), str(root)).tasks() if x.id == task), None)
    done = None if t is not None and t.status == "running" else True
    return streamlog.read(root, task, since, done=done)


# -- / commands ----------------------------------------------------------------------------------------------
def command(app, b: dict[str, Any], pc: bool) -> dict[str, Any]:
    from ..harness.orchestrator import HarnessError

    try:
        return slash.run(app, str(b.get("path") or ""), str(b.get("line") or ""), bool(b.get("confirmed")), pc=pc)
    except (slash.SlashError, HarnessError, FollowError) as e:
        raise _error(str(e)) from None


# -- a follow-up -------------------------------------------------------------------------------------------
def follow(app, b: dict[str, Any]) -> dict[str, Any]:
    root = _root(app, str(b.get("path") or ""))
    task, text, mode = str(b.get("task") or ""), str(b.get("text") or ""), str(b.get("mode") or "ask")
    orch = _orch(app, root)
    try:
        if mode == "ask" and b.get("confirmed"):
            t = orch._follow_task(task)
            if t.status != "running":
                orch.follow_up(task, text, "ask", confirmed=False)  # the same checks first, nothing spent
                if app._busy(root):
                    raise _error("Wait for the job running on this project to finish, then ask again.", 409)

                def work(job):
                    job.line(f"asking the model that built {t.id}")
                    return _orch(app, root).follow_up(task, text, "ask", confirmed=True)

                return {"job": app.jobs.start("follow", f"a question about {t.id}", work, target=str(root)).view(),
                        "reply": f"Asking the model that built {t.id}. The answer shows under the task."}
        return orch.follow_up(task, text, mode, confirmed=False)
    except FollowError as e:
        raise _error(str(e)) from None


# -- the queue ---------------------------------------------------------------------------------------------
def _note_id(g: dict[str, Any]) -> str:
    return hashlib.sha1(f"{g.get('at', '')}\n{g.get('text', '')}".encode()).hexdigest()[:8]


def _last_start(root: Path) -> str:
    from ..harness import eventlog

    try:
        rows = eventlog.read_events(root, include_archives=False)
    except Exception:  # noqa: BLE001
        return ""
    return max((r.get("at", "") for r in rows if r.get("event") == "task_start"), default="")


def waiting(root: Path, meta: dict[str, Any]) -> list[dict[str, Any]]:
    """The notes no task has started after yet (and not already sent to the task working now)."""
    since = _last_start(root)
    out = []
    for g in meta.get("guidance") or []:
        if g.get("at", "") >= since and not g.get("sent_now"):  # the same second: not read yet, to be safe
            out.append({"id": _note_id(g), "at": g.get("at", ""), "text": g.get("text", "")})
    return out


def queue(app, path: str) -> dict[str, Any]:
    root = _root(app, path)
    proj = app.project(app.need_cfg(), str(root))
    return {"items": waiting(root, proj.meta()), "running": bool(app._busy(root))}


def queue_change(app, b: dict[str, Any]) -> dict[str, Any]:
    from .. import attachments as att

    root = _root(app, str(b.get("path") or ""))
    proj = app.project(app.need_cfg(), str(root))
    action, nid = str(b.get("action") or ""), str(b.get("id") or "")
    meta = proj.meta()
    notes = meta.get("guidance") or []
    ids = {w["id"] for w in waiting(root, meta)}
    i = next((k for k, g in enumerate(notes) if _note_id(g) == nid), None)
    if i is None or nid not in ids:
        raise _error("That message isn't waiting any more: a task has read it. Look at the queue again.", 409)
    if action == "change":
        text = str(b.get("text") or "").strip()[:2000]
        if not text:
            raise _error("Write the new words first, or remove the message.")
        notes[i] = {**notes[i], "text": text}
        reply = "Changed. The next task reads the new words."
    elif action == "remove":
        notes.pop(i)
        reply = "Removed. No task will read it."
    elif action == "send_now":
        if not app._busy(root):
            return {**queue(app, str(root)), "reply": "Nothing is working right now, so it goes to the next task anyway."}
        att.steer_now(root, notes[i]["text"])
        notes[i] = {**notes[i], "sent_now": True}
        reply = "Sent to the task working now: it reads it at its next step."
    else:
        raise _error("Say change, remove or send_now.")
    meta["guidance"] = notes
    proj.save_meta(meta)
    return {**queue(app, str(root)), "reply": reply}


# -- timers on questions -----------------------------------------------------------------------------------
def timer(app, b: dict[str, Any]) -> dict[str, Any]:
    from ..asks import open_asks

    root = _root(app, str(b.get("path") or ""))
    aid = str(b.get("id") or "")
    if b.get("hold"):
        return {"timer": asktimer.hold(root, aid)}
    if b.get("clear"):
        return {"cleared": asktimer.clear_timer(root, aid)}
    ask = next((a for a in open_asks(_orch(app, root)) if a["id"] == aid), None)
    if ask is None or (b.get("stamp") and b["stamp"] != ask["stamp"]):
        raise _error("That question has changed or been answered. Look again for what's waiting.", 409)
    try:
        minutes = float(b.get("minutes") or 0)
        t = asktimer.set_timer(root, ask, minutes * 60, str(b.get("on_expire") or "recommended"))
    except (TypeError, ValueError) as e:
        raise _error(str(e) if isinstance(e, asktimer.TimerError) else "Say how many minutes.") from None
    return {"timer": t}


# -- talking -----------------------------------------------------------------------------------------------
ACTION = re.compile(r"^\s*Action:\s*(/\S.*)$", re.M)
TALK_COMMANDS = ("run", "next", "retry", "skip", "goal", "plan", "stop", "model", "board", "search")


def talk(app, b: dict[str, Any]) -> dict[str, Any]:
    """The words the browser heard, as a chat message (chat.reply): an answer to read aloud, and the card it
    offers as an action (a tap still runs it). Voice never offers undoing or leaving out a task."""
    from .. import chat as chatmod

    path = str(b.get("path") or "")
    _root(app, path)
    text = str(b.get("text") or "").strip()[:2000]
    if not text:
        raise _error("Nothing was heard. Try again, a little closer to the microphone.")
    chat = chatmod.chat_for_path(app, path)
    try:
        line = chatmod.reply(app, chat, text, aloud=True)
    except chatmod.ChatError as e:
        raise _error(str(e)) from None
    card = line.get("card") if line.get("who") == "chat" else None
    action = None
    if card and card.get("state") == "open":
        name, _ = slash.parse(card["command"])
        if name in TALK_COMMANDS:
            action = {"line": card["command"], "words": slash.COMMANDS[name][0],
                      "confirm": bool(slash.COMMANDS[name][2]), "card": card["id"], "chat": chat}
    return {"reply": line.get("text", ""), "action": action, "cost_usd": line.get("cost_usd", 0) or 0}
