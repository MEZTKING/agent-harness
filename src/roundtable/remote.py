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
project: ``state`` on / off / status, ``until``, ``cap``; or ``project`` with ``never``; see autopilot.py),
show_it (pictures of the app now, after its newest finished task, and the hub's live files: "Take pictures now"
on a finished project's Live tab).

Projects Roundtable builds report through one shared hub agent (``harness``) unless the hub has a project of
their own name; a command for one of them carries ``project_folder`` (the project's folder name), so only that
project picks it up. Commands without it go to the first project of that agent, as before.

A command can also carry ``machine`` (a machine's seat, such as ``pc-desk`` or ``phone-1a2b3c``): only that
machine does it, so the PC and the phone never both act on one command. ``carry_on`` continues a paused or
stopped run on the machine that holds the project's files (the same as ``run``).

Plain letters (anything from the owner that isn't a ``roundtable:`` command, such as "send me the apk") are never
left unread and unanswered (``plain_letter``): "send me the apk / the exe / the build" puts the newest built files
from the project's ``dist/`` in the hub (``plans/builds/<project>/``, with ``latest.json``) and the reply says where
to open them; anything else goes on the project's Needs-you list and the reply says so.

Every pass also says who reads each project's letters (``reach.read_beat``: ``plans/readers/<project>.json``), so the
phone can tell the owner when nobody does.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Callable

PREFIX = "roundtable:"
FOLDER = "project_folder"  # which project a command is for, when several share one hub agent (``harness``)
MACHINE = "machine"  # which machine a command is for (sync.this_machine()["id"]); none: whichever runs it
LONG = {"show_it", "revise", "approve", "run", "retry", "skip", "accept", "ask", "looks", "answer", "carry_on"}
BUILDS_DIR = "plans/builds"  # the newest built files of each project, for the phone to download
HUB_MAX_BYTES = 40 * 1024 * 1024  # a built file bigger than this stays on the computer (GitHub refuses 100 MB)
BUILD_KINDS = {".apk": "Android app", ".exe": "Windows app", ".msi": "Windows app", ".appimage": "Linux app",
               ".deb": "Linux app", ".dmg": "Mac app", ".zip": "app", ".gz": "app"}
WANTS = {"apk": (".apk",), "android": (".apk",), "phone": (".apk",), "exe": (".exe", ".msi", ".zip"),
         "windows": (".exe", ".msi", ".zip"), "linux": (".appimage", ".deb", ".gz"), "mac": (".dmg", ".zip")}
SEND = re.compile(r"\b(send|give|share|where|download|get)\b.*\b(apk|exe|build|builds|app|apps|installer|zip|"
                  r"android|windows|linux|mac|files?)\b", re.I | re.S)
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
    kw = {k: v for k, v in cmd.items() if k not in ("action", FOLDER, MACHINE)}
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
    if action == "shared_settings":
        return shared_settings(orch, cfg, kw)
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
    if action in ("run", "carry_on"):
        return f"The run ended as: {orch.run()}."
    if action == "profile":
        r = orch.set_profile(str(kw.get("name", "")))
        costs = ", ".join(f"{n} about ${e.get('cost_usd') or 0:.2f}" for n, e in r["estimates"].items())
        return f"This project now uses the {r['profile']} setting. Estimates: {costs}."
    if action == "show_it":
        return orch.show_it_now()["reply"]
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


def shared_settings(orch, cfg, kw: dict[str, Any]) -> str:
    """{"changes": {limits, autopilot, default_profile, roles}}: the settings every machine shares (sync.py)."""
    from .autopilot import app_home
    from .sync import change_shared

    hub = orch._hub()
    if hub is None:
        return "Couldn't change the shared settings: this machine isn't on the hub."
    changes = kw.get("changes")
    if not isinstance(changes, dict) or not changes:
        return "Couldn't change the shared settings: nothing to change was sent."
    out = change_shared(hub, changes, cfg.path, app_home(), cfg)
    what = ", ".join(out["changed"]) or "nothing new here"
    return f"Shared settings saved for every machine ({what})."


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
    from . import asktimer
    from .asks import finish

    if str(kw.get("id", "")).startswith("shipoffer"):  # a download onto the PC itself: answered there only
        return "That can only be answered on the PC itself."

    r = asktimer.answer(orch, str(kw.get("id", "")), kw.get("chosen"), str(kw.get("other") or ""),
                        confirmed=bool(kw.get("confirmed")), stamp_seen=kw.get("stamp") or None,
                        skip=bool(kw.get("skip")))
    return " ".join(x for x in (r["reply"], finish(orch, r)) if x)


def _size(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB" if n >= 1024 * 1024 else f"{max(1, n // 1024)} KB"


def built_files(project: Path, wants: tuple[str, ...] = ()) -> list[Path]:
    """The newest built file of each kind in the project's ``dist/`` (two folders deep at most), newest first."""
    dist = project / "dist"
    if not dist.is_dir():
        return []
    found: dict[str, Path] = {}
    for p in sorted([*dist.glob("*"), *dist.glob("*/*")], key=lambda p: p.stat().st_mtime, reverse=True):
        ext = p.suffix.lower()
        if not p.is_file() or ext not in BUILD_KINDS or (wants and ext not in wants):
            continue
        kind = BUILD_KINDS[ext] if ext != ".zip" else ("Windows app" if "win" in p.name.lower() else
                                                        "Mac app" if "mac" in p.name.lower() else "app")
        found.setdefault(f"{kind}{ext}", p)
    return sorted(found.values(), key=lambda p: p.stat().st_mtime, reverse=True)


def send_builds(hub, project: Path, hub_name: str, wants: tuple[str, ...] = ()) -> dict[str, Any]:
    """Put the newest built files in the hub (``plans/builds/<hub_name>/``) with ``latest.json``: {project, at,
    files: [{name, kind, size, built_at, in_hub, path}]}. A file over ``HUB_MAX_BYTES`` is listed, not copied."""
    from datetime import datetime, timezone

    from .core.store import BinaryFile

    files = built_files(project, wants)
    writes: dict[str, Any] = {}
    listed = []
    for p in files:
        size = p.stat().st_size
        ext = p.suffix.lower()
        kind = BUILD_KINDS[ext] if ext != ".zip" else ("Windows app" if "win" in p.name.lower() else "app")
        rel = f"{BUILDS_DIR}/{hub_name}/{p.name}"
        fits = size <= HUB_MAX_BYTES
        if fits:
            writes[rel] = BinaryFile(p.read_bytes())
        listed.append({"name": p.name, "kind": kind, "size": size, "in_hub": fits, "path": rel if fits else "",
                       "built_at": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).strftime(
                           "%Y-%m-%dT%H:%M:%SZ")})
    out = {"project": hub_name, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "files": listed}
    if listed:
        writes[f"{BUILDS_DIR}/{hub_name}/latest.json"] = out
        hub.store.write_json(writes, f"builds({hub_name}): {', '.join(f['name'] for f in listed)}"[:200])
    return out


def plain_letter(cfg, project: Path, hub, msg: dict[str, Any]) -> str:
    """The reply to a letter that isn't a command. Never leaves it unanswered."""
    from .harness.orchestrator import Orchestrator

    orch = Orchestrator(cfg, project, on_event=lambda k, d: None)
    text = " ".join(f"{msg.get('subject') or ''} {msg.get('body') or ''}".split())
    if SEND.search(text):
        words = {w.lower() for w in re.findall(r"[A-Za-z]+", text)}
        wants = tuple(dict.fromkeys(x for w in words for x in WANTS.get(w, ())))
        sent = send_builds(hub, project, orch._hub_name(), wants)
        if sent["files"]:
            lines = []
            for f in sent["files"]:
                when = f["built_at"][:10]
                if f["in_hub"]:
                    lines.append(f"- {f['kind']}: {f['name']} ({_size(f['size'])}, built {when}). Open it from the "
                                 f"project's Builds on the phone. [hub:{f['path']}]")
                else:
                    lines.append(f"- {f['kind']}: {f['name']} ({_size(f['size'])}, built {when}) is too big to send "
                                 "through the hub. It stays in the project's dist folder on the computer that built it.")
            return "Here are the newest built files:\n" + "\n".join(lines)
        orch._attention(f"letter-{msg.get('id')}", f"Your letter: \"{text[:160]}\". There's no built app yet",
                        details="Nothing was found in the project's dist folder.")
        return ("There's no built app for this project yet, so there's nothing to send. Your letter is on Needs you; "
                "once the project is built, ask again.")
    orch._attention(f"letter-{msg.get('id')}", f"Your letter: \"{text[:160]}\"",
                    details=f"A plain letter (not a command) sent to {orch._hub_name()}. Turn it into a change to the "
                            "plan, a question or a task.")
    return ("Got your letter. I can't act on a plain letter by myself, so it's on this project's Needs you list. "
            "Tap it there to turn it into a change to the plan, a question or a task.")


def process(cfg, hub, background: bool = False, log: Callable[[str], None] = print) -> int:
    """One pass: find owner commands for the projects this Roundtable runs, do them, reply."""
    from .harness.orchestrator import Orchestrator

    from .sync import this_machine

    allowed = set((getattr(cfg, "remote", None) or {}).get("owners") or ["me"])
    # the owner's own machines (seats registered in the hub as role: machine) speak for the owner too,
    # so a command sent from the phone's own Roundtable reaches the PC
    allowed |= {a for a, spec in hub.config.agents.items() if getattr(spec, "role", None) == "machine"}
    from . import reach

    machine = this_machine()
    me = machine["id"]
    done = 0
    hub.store.sync()
    sent_twice: dict[tuple, str] = {}  # the same command twice in one pass is done once
    answered: set[str] = set()  # plain letters answered this pass (several projects can share one hub agent)
    for project in project_dirs(cfg):
        orch = Orchestrator(cfg, project)
        agent = orch._hub_agent() if cfg.hub else project.name
        if agent not in hub.config.agents:
            continue
        reach.read_beat(hub, orch._hub_name() if cfg.hub else project.name, machine, agent=agent,
                        folder=project.name)  # who reads this project's letters (the phone shows it)
        for msg in hub.inbox(agent, unread_only=True, limit=50):
            if msg.get("sender") not in allowed:
                continue
            cmd = parse(msg)
            if cmd is None:  # a plain letter: answered by the project that owns the hub agent, once
                if msg["id"] in answered:
                    continue
                answered.add(msg["id"])
                hub.mark_read(agent, [msg["id"]])
                try:
                    text = plain_letter(cfg, project, hub, msg)
                except Exception as e:  # noqa: BLE001 - a plain letter still gets a reply
                    text = f"Couldn't answer your letter here: {e}. It stays for the computer that runs the project."
                try:
                    hub.reply(agent, msg["id"], text)
                except Exception as e:  # noqa: BLE001
                    log(f"remote: couldn't reply: {e}")
                done += 1
                continue
            if cmd.get(FOLDER) and cmd[FOLDER] != project.name:
                continue  # for another project that reports through the same hub agent: leave it for that one
            if cmd.get(MACHINE) and cmd[MACHINE] != me:
                continue  # for another machine (the phone or another PC): leave it for that one
            same = (agent, msg.get("sender"), json.dumps(cmd, sort_keys=True))
            if same in sent_twice:  # the owner sent it again because nothing seemed to happen: done once
                hub.mark_read(agent, [msg["id"]])
                try:
                    sent = hub.reply(agent, msg["id"], f"Done once already: this is the same as your letter of "
                                                       f"{sent_twice[same][:16].replace('T', ' ')}.")
                    hub.mark_read(msg["sender"], [sent["id"]])
                except Exception as e:  # noqa: BLE001
                    log(f"remote: couldn't reply: {e}")
                done += 1
                continue
            sent_twice[same] = str(msg.get("created_at") or "")
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
