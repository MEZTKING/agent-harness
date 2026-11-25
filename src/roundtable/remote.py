"""Commands through the hub: drive projects from the phone (or anywhere) without reaching the PC.

The phone writes a message to a project's hub inbox: kind ``request``, subject starting with
``roundtable:``, body a JSON object such as ``{"action": "choose", "decision": "C1", "option": "b"}``.
Whichever Roundtable Hold runs that project (the desktop app's auto-sync, or ``roundtable remote
--watch``) picks it up, does it, replies in the same thread and marks it read.

Only messages from the owner's identities (``remote.owners`` in harness.yaml, default ``[me]``)
are obeyed. Anyone who can write to the hub repository could already change everything in it, so
this adds no new access; it only makes the owner's intent actionable.

Actions: the plan edits (choose, answer, dont_add, dont_remove, idea, section, scope_add,
scope_remove, note), revise, approve (then run), run, retry, skip, steer, ask.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable

PREFIX = "roundtable:"
LONG = {"revise", "approve", "run", "retry", "skip", "ask"}
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
    if action in orch.PLAN_ACTIONS:
        r = orch.plan_update(action, **kw)
        return f"Done. {r['pending']} change(s) waiting: send 'revise' (Update plan) to apply them."
    if action == "revise":
        r = orch.revise_plan(kw.get("text", ""))
        return r["summary"] + ". The new plan is in plans/ in the hub."
    if action == "approve":
        orch.approve()
        status = orch.run()
        return f"Approved and started. The run ended as: {status}."
    if action in ("retry", "skip"):
        getattr(orch, action)(kw.get("task", ""))
        return f"{action} {kw.get('task')}: done. The run ended as: {orch.run()}."
    if action == "run":
        return f"The run ended as: {orch.run()}."
    if action == "steer":
        return orch.steer(kw.get("text", ""))["reply"]
    if action == "ask":
        return orch.ask(kw.get("text", ""))["reply"]
    return f"Unknown action {action!r}."


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
                    hub.reply(agent, msg["id"], text)
                except Exception as e:
                    log(f"remote: couldn't reply: {e}")

            if background and cmd.get("action") in LONG:
                threading.Thread(target=work, daemon=True, name=f"remote-{agent}").start()
            else:
                work()
            done += 1
    return done
