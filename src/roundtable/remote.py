"""Commands through the hub: drive projects from the phone (or anywhere) without reaching the PC.

The phone writes a message to a project's hub inbox: kind ``request``, subject starting with
``roundtable:``, body a JSON object such as ``{"action": "choose", "decision": "C1", "option": "b"}``.
Whichever Roundtable Hold runs that project (the desktop app's auto-sync, or ``roundtable remote
--watch``) picks it up, does it, replies in the same thread and marks it read.

Only messages from the owner's identities (``remote.owners`` in harness.yaml, default ``[me]``)
are obeyed. Anyone who can write to the hub repository could already change everything in it, so
this adds no new access; it only makes the owner's intent actionable.

Actions: the plan edits (choose, answer, dont_add, dont_remove, idea, section, scope_add,
scope_remove, note, look: choose a look by its id, with an optional note, reference_add: ``text`` is a
link, a GitHub repository or a description to make it like, reference_remove: ``id`` such as R1), revise, approve (then
run), run, retry, skip, steer, ask, looks (make new looks to choose from; ``text`` is the owner's
starting point), answer (a tapped card: ``id`` of the ask, ``chosen`` option ids, ``other`` typed
text, ``confirmed`` after "Are you sure?", ``stamp`` so an old card can't answer a changed question;
see asks.py; the phone reads the cards from plans/<project>.asks.json), autopilot (one switch for every
project: ``state`` on / off / status, ``until``, ``cap``; or ``project`` with ``never``; see autopilot.py).
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Callable

PREFIX = "roundtable:"
LONG = {"revise", "approve", "run", "retry", "skip", "accept", "ask", "looks", "answer"}
_busy: set[str] = set()
_busy_lock = threading.Lock()


def project_dirs(cfg) -> list[Path]:
    if not cfg.lab_dir:
        return []
    from .improve.lab import Lab

    return [p for p in Lab(cfg.lab_dir).projects() if (p / ".harness" / "project.json").is_file()]


def parse(msg: dict[str, Any]) -> dict[str, Any] | None:
    if msg.get("kind") != "request" or not str(msg.get("subject", "")).startswith(PREFIX):
        return None
    try:
        body = json.loads(msg.get("body") or "{}")
    except ValueError:
        return {"action": "_invalid", "error": "the command isn't valid JSON"}
    return body if isinstance(body, dict) and body.get("action") else {"action": "_invalid",
                                                                         "error": "no action in the command"}


def execute(cfg, project: Path, cmd: dict[str, Any], log: Callable[[str], None] = lambda s: None) -> str:
    """Do one command on one project; returns the reply text."""
    from .harness.orchestrator import Orchestrator

    orch = Orchestrator(cfg, project, on_event=lambda k, d: None)
    action = cmd.get("action")
    kw = {k: v for k, v in cmd.items() if k != "action"}
    if action == "_invalid":
        return f"Couldn't do that: {cmd.get('error')}."
    if action == "answer" and "id" not in kw and "question" in kw:  # the plan's own answer: {question, text}
        r = orch.plan_update("answer", **kw)
        return f"Answer saved. {_waiting(r['pending'])}"
    if action == "answer":
        return _answer(orch, kw)
    if action == "autopilot":
        return autopilot_command(cfg, kw)
    if action == "todo_done":
        return todo_done(orch, kw)
    if action == "looks":
        r = orch.look(kw.get("text", ""))
        names = ", ".join(f"{x['id']} {x['name']}" for x in r["looks"])
        return f"New looks to choose from: {names}. Pick the one you like in the plan."
    if action in orch.PLAN_ACTIONS:
        r = orch.plan_update(action, **kw)
        return f"Done. {_waiting(r['pending'])}"
    if action == "revise":
        r = orch.revise_plan(kw.get("text", ""))
        return r["summary"] + ". The new plan is ready to look at."
    if action == "approve":
        orch.approve()
        status = orch.run()
        return f"Approved and started. The run ended as: {status}."
    if action == "accept":
        orch.accept(kw.get("task", ""), kw.get("text", ""))
        return f"{kw.get('task')} accepted as it is. The run ended as: {orch.run()}."
    if action in ("retry", "skip"):
        getattr(orch, action)(kw.get("task", ""))
        return f"{action} {kw.get('task')}: done. The run ended as: {orch.run()}."
    if action == "run":
        return f"The run ended as: {orch.run()}."
    if action == "profile":
        r = orch.set_profile(str(kw.get("name", "")))
        costs = ", ".join(f"{n} about ${e.get('cost_usd') or 0:.2f}" for n, e in r["estimates"].items())
        return f"This project now uses the {r['profile']} setting. Estimates: {costs}."
    if action == "steer":
        return orch.steer(kw.get("text", ""))["reply"]
    if action == "ask":
        return orch.ask(kw.get("text", ""))["reply"]
    return f"Unknown action {action!r}."


TROUBLE = re.compile(r"\b(couldn'?t|could not|can'?t|cannot|refused|failed|blocked|unknown action|isn't|not allowed|"
                     r"error|are you sure)\b", re.I)


def is_trouble(text: str) -> bool:
    """A reply that reports a refusal or a failure: the owner must see it. Anything else is a receipt."""
    return bool(TROUBLE.search(text or ""))


def _waiting(pending: int) -> str:
    """What the owner reads after a plan change: how many wait, and the one button that applies them."""
    return (f"{pending} change{'s' if pending != 1 else ''} wait{'s' if pending == 1 else ''} for you to press "
            "Update plan.")


def autopilot_command(cfg, kw: dict[str, Any]) -> str:
    """Autopilot from the phone: {"state": "on" | "off" | "status", "until": "08:00", "cap": 2,
    "project": name, "never": true} (or {"on": true/false}). It's one switch for every project."""
    from . import autopilot

    mode = kw.get("state") or ({True: "on", False: "off"}.get(kw.get("on")) if "on" in kw else "status")
    if kw.get("project") and "never" in kw:
        autopilot.set_never(str(kw["project"]), bool(kw["never"]))
        return f"{kw['project']} is {'never' if kw['never'] else 'again'} on autopilot."
    if mode == "on":
        return f"Autopilot on, {autopilot.turn_on(kw.get('until'), kw.get('cap'), cfg=cfg)['label']}."
    if mode == "off":
        autopilot.turn_off("you turned it off from the phone.", cfg=cfg)
        return "Autopilot off."
    st = autopilot.status()
    return f"Autopilot: {st['label']}."


def todo_done(orch, kw: dict[str, Any]) -> str:
    """A to-do ticked off from the phone: closed in the project's own journal, noting it was the owner."""
    from .hub.journal import JournalError

    hub = orch._hub()
    if hub is None:
        return "Couldn't mark it done: this project isn't on the hub. Mark it done on the PC instead."
    entry = str(kw.get("id") or "").strip()
    if not entry:
        return "Couldn't mark it done: the to-do's id is missing. Refresh the Table and try again."
    try:
        e = hub.journal.close(orch._hub_agent(), entry, note=str(kw.get("note") or "Marked done by the owner from the phone."))
    except JournalError as err:
        return f"Couldn't mark it done: {err}. It may already be closed: refresh the Table."
    return f"Done: \"{e['text'][:80]}\" is ticked off."


def _answer(orch, kw: dict[str, Any]) -> str:
    """A card answered from the phone or another machine: the same as tapping it on the PC."""
    from .asks import answer_ask, finish

    r = answer_ask(orch, str(kw.get("id", "")), kw.get("chosen"), str(kw.get("other") or ""),
                   confirmed=bool(kw.get("confirmed")), stamp=kw.get("stamp") or None, skip=bool(kw.get("skip")))
    return " ".join(x for x in (r["reply"], finish(orch, r)) if x)


def process(cfg, hub, background: bool = False, log: Callable[[str], None] = print) -> int:
    """One pass: find owner commands for the projects this Roundtable runs, do them, reply."""
    from .harness.orchestrator import Orchestrator

    allowed = set((getattr(cfg, "remote", None) or {}).get("owners") or ["me"])
    done = 0
    hub.store.sync()
    for project in project_dirs(cfg):
        agent = Orchestrator(cfg, project)._hub_agent() if cfg.hub else project.name
        if agent not in hub.config.agents:
            continue
        for msg in hub.inbox(agent, unread_only=True, limit=50):
            cmd = parse(msg)
            if cmd is None or msg.get("sender") not in allowed:
                continue
            key = f"{project}:{msg['id']}"
            with _busy_lock:
                if key in _busy:
                    continue
                _busy.add(key)
            hub.mark_read(agent, [msg["id"]])  # claim it before working, so it runs once

            def work(msg=msg, cmd=cmd, agent=agent, key=key, project=project):
                try:
                    log(f"remote: {agent}: {cmd.get('action')}")
                    text = execute(cfg, project, cmd, log)
                except Exception as e:  # every failure goes back to the owner as a reply
                    text = f"Couldn't do '{cmd.get('action')}': {e}"
                finally:
                    with _busy_lock:
                        _busy.discard(key)
                try:
                    sent = hub.reply(agent, msg["id"], text)
                    if not is_trouble(text):  # a receipt: it doesn't need the owner, so it arrives already read
                        hub.mark_read(msg["sender"], [sent["id"]])
                except Exception as e:
                    log(f"remote: couldn't reply: {e}")

            if background and cmd.get("action") in LONG:
                threading.Thread(target=work, daemon=True, name=f"remote-{agent}").start()
            else:
                work()
            done += 1
    return done
