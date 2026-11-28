"""``/`` commands in the message box (wave 8, DS-16, DS-83).

A table, not a second way of doing things: each command does what one of the app's buttons already does,
through the same function the button's route calls, so a command never has more power than a button, and one
that spends money or deletes work asks the same "Are you sure?" first (``confirm``; the box sends the line again
with ``confirmed``).

Slow commands (``/compact``, ``/test``, a plug-in's command) start a background job and come back at once with
it; the box follows the job (``GET /api/jobs/<id>``) for as long as it takes, so nothing times out after 30
seconds the way the forks' boxes used to.

Besides the table: an installed plug-in's own commands (``/<plug-in> <command> …``, its ``commands`` hook, as
``roundtable <plug-in> <command>`` runs them) and skills by name (``/<skill>`` asks the next tasks to use it).

``table(app, path)`` lists them for the menu; ``run(app, path, line, confirmed, pc)`` does one. ``pc`` is False
for the phone: commands that run programs on the PC (``/test``, plug-ins) are the PC's own.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any, Callable

# name: (what it does, what may follow, confirm when it spends or deletes ("" for none), slow, PC only)
COMMANDS: dict[str, tuple[str, str, str, bool, bool]] = {
    "plan": ("Update the plan (say what to change after it)", "[what to change]",
             "The planner updates the plan. That is one model call from your accounts.", False, False),
    "run": ("Build: carry on with the plan's tasks", "", "spend", False, False),
    "next": ("Build only the next task, then stop", "", "spend", False, False),
    "stop": ("Stop what a task is running now (a command, the app it started)", "", "", False, False),
    "retry": ("Try a task again", "[task id]", "", False, False),
    "skip": ("Leave a task out and carry on", "<task id>", "", False, False),
    "undo": ("Undo the newest finished task's changes", "[task id]", "undo", False, False),
    "goal": ("Add something new to build", "<what to build next>",
             "The planner plans it next, which is a model call; building it is asked for after.", False, False),
    "compact": ("Sum up this chat in a few lines, so the planner reads less each time", "",
                "The planner sums up the chat. That is one model call from your accounts.", True, False),
    "model": ("Which set of models does the work (Budget, Balanced, Quality)", "[setting]", "", False, False),
    "test": ("Run the project's own tests", "", "", True, True),
    "search": ("Look for something in every project and the journal", "<words>", "", False, False),
    "board": ("Open the board of tasks", "", "", False, False),
    "help": ("List these commands", "", "", False, False),
    # 1.5.0: what the phone's letters could do and the box couldn't (the chat's cards run them too)
    "approve": ("Approve the plan and build (say “at most $N” to set the limit)", "[at most $N]", "spend", False,
                False),
    "build": ("Build the accepted ideas, or something new (say “at most $N” to set the limit)",
              "[accepted | what to build] [at most $N]", "spend", False, False),
    "answer": ("Answer one of the plan's questions", "<question id> <answer>", "", False, False),
    "choose": ("Choose one of a decision's options", "<decision id> <option id>", "", False, False),
    "looks": ("Make new looks to choose from", "[a starting point]",
              "The designer makes new looks. That is one model call from your accounts.", False, False),
    "accept": ("Accept a stopped task as it is and carry on building", "<task id> [note]", "spend", False, False),
    "autopilot": ("Autopilot for every project: on (until a time, at most $N), off, or how it is",
                  "on [until HH:MM] [at most $N] | off | status", "autopilot", False, False),
    "pictures": ("Take pictures of the app as it is now", "", "", False, False),
    "note": ("Tell the planner something: the next tasks and plans read it", "<words>", "", False, False),
    "todo": ("Tick off one of the project's to-dos", "done <to-do id>", "", False, False),
    "recall": ("Look through every project for the answer to a question", "<question>", "recall", False, False),
    "new": ("Start a new project: the planner writes its plan, building waits for your yes", "<what to build>",
            "The planner writes a plan for it. That is one model call from your accounts.", False, False),
}
NO_PROJECT = ("help", "search", "recall", "new", "autopilot")  # commands that work in Hall, without a project
SPEND = "It starts building, which spends from your model accounts{est}. You can stop a command any time."


class SlashError(ValueError):
    """A command that can't be done, in words the owner reads (what to do instead)."""


def parse(line: str) -> tuple[str, str]:
    """``"/goal a shop page"`` -> ``("goal", "a shop page")``. Not a command -> ``("", line)``."""
    s = str(line or "").strip()
    if not s.startswith("/") or s.startswith("//"):
        return "", s
    head, _, rest = s[1:].partition(" ")
    return head.strip().lower(), rest.strip()


def _plugins(app) -> dict[str, dict[str, Callable]]:
    try:
        cfg = app.cfg()
        host = cfg.plugin_host() if cfg else None
    except Exception:  # noqa: BLE001 - a broken plug-in never hides the table
        return {}
    if host is None:
        return {}
    out: dict[str, dict[str, Callable]] = {}
    try:
        for p in host.active("commands"):
            cmds = host.commands(p.id)
            if cmds:
                out[p.id] = cmds
    except Exception:  # noqa: BLE001
        return out
    return out


def _skills() -> dict[str, Any]:
    try:
        from .. import skills

        return {s.id: s for s in skills.list_skills() if s.enabled}
    except Exception:  # noqa: BLE001
        return {}


def table(app, path: str = "") -> list[dict[str, Any]]:
    """Every command the box offers, in the menu's order: the table, then plug-ins, then skills."""
    out = [{"name": n, "words": w, "args": a, "confirm": bool(c), "slow": slow, "pc_only": pc, "kind": "command"}
           for n, (w, a, c, slow, pc) in COMMANDS.items()]
    for pid, cmds in sorted(_plugins(app).items()):
        if pid in COMMANDS:
            continue  # the app's own commands win
        out.append({"name": pid, "words": f"A plug-in's commands: {', '.join(sorted(cmds))}", "args": "<command> …",
                    "confirm": True, "slow": True, "pc_only": True, "kind": "plugin"})
    for sid, s in sorted(_skills().items()):
        if sid in COMMANDS or any(o["name"] == sid for o in out):
            continue
        out.append({"name": sid, "words": f"Ask the next tasks to use the skill “{s.name}”", "args": "[anything to add]",
                    "confirm": False, "slow": False, "pc_only": False, "kind": "skill"})
    return out


def help_text(app) -> str:
    return "\n".join(f"/{c['name']}{(' ' + c['args']) if c['args'] else ''} – {c['words']}" for c in table(app))


# -- doing one ----------------------------------------------------------------------------------------------
def run(app, path: str, line: str, confirmed: bool = False, pc: bool = True) -> dict[str, Any]:
    """Do one command line. Returns ``{"reply"}`` and, as it fits, ``"job"`` (follow it: slow work),
    ``"confirm"`` (nothing was done: ask "Are you sure?" with these words, then send it again with
    ``confirmed``), ``"open"`` (a page for the app to show: ``"board"``) or ``"results"``."""
    name, rest = parse(line)
    if not name:
        raise SlashError("A command starts with /. Type / to see them all.")
    if name in COMMANDS:
        words, args, confirm, slow, pc_only = COMMANDS[name]
        if not path and name not in NO_PROJECT:
            raise SlashError("Open a project first: commands work on the project you're looking at.")
        if pc_only and not pc:
            raise SlashError("That one runs programs on the PC, so it's only in the PC's own app.")
        need = _confirm_words(app, path, name, confirm, rest)
        if need and not confirmed:
            return {"reply": need, "confirm": need, "command": line}
        return DO[name](app, path, rest)
    plugins = _plugins(app)
    if name in plugins:
        if not pc:
            raise SlashError("A plug-in's commands run on the PC, so they're only in the PC's own app.")
        if not confirmed:
            need = "A plug-in's command can change things in your projects. Run it?"
            return {"reply": need, "confirm": need, "command": line}
        return _plugin(app, name, plugins[name], rest)
    skills = _skills()
    if name in skills:
        return _skill(app, path, skills[name], rest)
    raise SlashError(f"There's no /{name}. Type / to see the commands.")


def _confirm_words(app, path: str, name: str, confirm: str, rest: str) -> str:
    if confirm == "spend":
        return SPEND.format(est=_estimate(app, path))
    if confirm == "undo":
        return _undo_preview(app, path, rest)["confirm"]
    if confirm == "autopilot":
        return "Autopilot answers what waits and builds on its own, which spends from your model accounts." \
            if (rest.split() or [""])[0].lower() == "on" else ""
    if confirm == "recall":
        return _recall_price(app, rest)
    return confirm


def _estimate(app, path: str) -> str:
    try:
        from . import plandoc

        proj = _project(app, path)
        doc, meta = proj.plan_doc() or {}, proj.meta()
        line = plandoc.estimate_line(doc.get("estimate"), meta.get("agreed")) if doc.get("estimate") else ""
        return f" ({line})" if line else ""
    except Exception:  # noqa: BLE001 - the words are a help
        return ""


def _project(app, path: str):
    if not path:
        raise SlashError("Open a project first: commands work on the project you're looking at.")
    return app.project(app.need_cfg(), path)


def _job(view: Any, reply: str) -> dict[str, Any]:
    return {"reply": reply, "job": view}


def _plan(app, path, rest):
    return _job(app.plan_post({"path": path, "action": "revise", "text": rest}),
                "The planner is updating the plan. It shows on the Plan page when it's ready.")


def _run(app, path, rest, max_tasks=None):
    body = {"path": path, "action": "run", **({"max_tasks": max_tasks} if max_tasks else {})}
    return _job(app.project_action(body), "Building the next task, then it stops." if max_tasks
                else "Building. Watch shows each task as it goes.")


def _stop(app, path, rest):
    from . import livecmd

    root = _project(app, path).root
    stopped = sum(livecmd.stop(root, c["task"], c.get("n")) for c in livecmd.running(root) if c.get("task"))
    app_stopped = False
    try:
        from ..ui import appapi

        app_stopped = str(root) in getattr(appapi, "_apps", {})
        if app_stopped:
            appapi.stop_folder(root)
    except Exception:  # noqa: BLE001 - no app running is the usual case
        pass
    if not stopped and not app_stopped:
        return {"reply": "Nothing was running a command or an app just now."}
    parts = ([f"{stopped} command{'s' if stopped != 1 else ''}"] if stopped else []) + (["the app"] if app_stopped else [])
    return {"reply": f"Stopped {' and '.join(parts)}. The task carries on and is told you stopped it."}


def _task_id(app, path: str, rest: str, want: tuple[str, ...], what: str) -> str:
    tasks = _project(app, path).tasks()
    if rest:
        tid = rest.split()[0].upper()
        if not any(t.id == tid for t in tasks):
            raise SlashError(f"There's no task {tid} in this project. The task ids are on the cards (T1, T2…).")
        return tid
    found = [t.id for t in tasks if t.status in want]
    if not found:
        raise SlashError(f"No task {what} right now. Say which one, like /{'retry' if 'failed' in want else 'undo'} T3.")
    return found[0] if "failed" in want else found[-1]


def _retry(app, path, rest):
    tid = _task_id(app, path, rest, ("failed",), "has stopped")
    app.project_action({"path": path, "action": "retry", "task": tid})
    return {"reply": f"{tid} will be tried again. Use /run to start."}


def _skip(app, path, rest):
    if not rest:
        raise SlashError("Say which task to leave out, like /skip T3.")
    tid = _task_id(app, path, rest, (), "")
    app.project_action({"path": path, "action": "skip", "task": tid})
    return {"reply": f"{tid} is left out. Use /run to carry on."}


def _undo_preview(app, path, rest) -> dict[str, Any]:
    from ..ui import rewindapi

    tid = _task_id(app, path, rest, ("done",), "has finished")
    pv = rewindapi.preview(app, {"path": [path], "task": [tid], "mode": ["undo_task"]})
    if pv.get("blocked"):
        raise SlashError(str(pv["blocked"]))
    words = pv.get("words") or f"Undo {tid}'s changes."
    return {"task": tid, "stamp": pv.get("stamp", ""),
            "confirm": f"{words} Its changes are taken out (Put it back on the History page brings them back)."}


def _undo(app, path, rest):
    from ..ui import rewindapi

    pv = _undo_preview(app, path, rest)
    res = rewindapi.do(app, {"path": path, "task": pv["task"], "mode": "undo_task", "stamp": pv["stamp"]})
    return {"reply": res.get("words") or f"{pv['task']} is undone. It goes back to the to-do list."}


def _goal(app, path, rest):
    if not rest:
        raise SlashError("Say what to build next, like /goal a page for prices.")
    return _job(app.project_action({"path": path, "action": "extend", "goal": rest}),
                "Sent: the planner plans it next, then it is built.")


def _compact(app, path, rest):
    proj = _project(app, path)
    cfg = app.need_cfg()

    def work(job):
        return compact_chat(cfg, proj.root, job.line)

    return _job(app.jobs.start("chat", f"sum up the chat of {proj.root.name}", work, target=str(proj.root)).view(),
                "Summing up the chat. It can take a minute; the box shows when it's done.")


def compact_chat(cfg, root: Path, line: Callable[[str], None] = lambda s: None) -> dict[str, Any]:
    """Sum the planner chat up in a few lines (one planner call, charged like any question) and keep only that
    and the newest four messages; the older ones go to ``chat-old.jsonl`` beside it, nothing is deleted."""
    from .orchestrator import Orchestrator

    orch = Orchestrator(cfg, root)
    rows = orch.chat_history(10_000)
    if len(rows) < 6:
        return {"reply": "The chat is short already: nothing to sum up."}
    line("asking the planner to sum up the chat")
    r = orch.ask("Sum up our conversation so far in at most 10 short lines: what was asked, what was decided, "
                 "what is still open. Only the summary, no greeting.")
    p = orch.project.dir / "chat.jsonl"
    every = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    keep = every[-6:-2]  # the newest four before the summary's own question and answer
    old = every[:-6]
    with (orch.project.dir / "chat-old.jsonl").open("a", encoding="utf-8") as f:
        for row in old:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {"at": every[-1].get("at", ""), "who": "orchestrator", "steer": False, "summary": True,
               "text": "Summary of the chat so far:\n" + r["reply"]}
    p.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in [summary, *keep]), encoding="utf-8")
    return {"reply": "The chat is summed up. The older messages are kept in the project's chat-old file.",
            "cost_usd": r.get("cost_usd", 0)}


def _model(app, path, rest):
    proj = _project(app, path)
    if not rest:
        from .orchestrator import Orchestrator

        orch = Orchestrator(app.need_cfg(), proj.root)
        names = ", ".join(sorted(orch.base_cfg.profiles)) or "none"
        return {"reply": f"This project uses {orch.profile() or 'the default'} setting. The settings: {names}. "
                         "Say /model and a name to change it."}
    r = app.plan_post({"path": path, "action": "profile", "name": rest.split()[0].lower()})
    return {"reply": f"This project now uses the {r.get('profile', rest)} setting."}


def _test(app, path, rest):
    from ..ui import filesapi

    return _job(filesapi.run_tests(app, {"path": path}), "Running the project's tests. The box shows how they ended.")


def _search(app, path, rest):
    if not rest:
        raise SlashError("Say what to look for, like /search logo.")
    from ..ui import searchapi

    r = searchapi.run_search(app, {"q": [rest], "limit": ["8"]})
    hits = r.get("results") or r.get("hits") or []
    if not hits:
        return {"reply": f"Nothing found for “{rest}”.", "results": []}
    lines = [f"- {h.get('title') or h.get('text') or h.get('path') or ''}"[:160] for h in hits[:8]]
    return {"reply": f"Found {len(hits)}:\n" + "\n".join(lines), "results": hits[:8]}


def _board(app, path, rest):
    return {"reply": "Opening the board.", "open": "board"}


def _help(app, path, rest):
    return {"reply": help_text(app)}


def _plugin(app, pid: str, cmds: dict[str, Callable], rest: str) -> dict[str, Any]:
    argv = shlex.split(rest) if rest else []
    if not argv or argv[0] not in cmds:
        raise SlashError(f"Say which of its commands: {', '.join(sorted(cmds))}. Like /{pid} {sorted(cmds)[0]}.")
    cfg = app.need_cfg()
    host = cfg.plugin_host()

    def work(job):
        p = host.get(pid)
        out = cmds[argv[0]](host.context(p), argv[1:])
        return {"reply": str(out) if out not in (None, 0, True) else "Done."}

    return _job(app.jobs.start("plugin", f"{pid} {argv[0]}", work).view(), f"Running {pid} {argv[0]}.")


def _skill(app, path, skill, rest):
    from .orchestrator import HarnessError, Orchestrator

    proj = _project(app, path)
    text = f"Use the skill “{skill.name}” for the tasks it suits." + (f" {rest}" if rest else "")
    try:
        Orchestrator(app.need_cfg(), proj.root).steer(text)
    except HarnessError as e:
        raise SlashError(str(e)) from None
    return {"reply": f"Noted: the next tasks use the skill “{skill.name}”."}


# -- 1.5.0: the commands the chat's cards run ---------------------------------------------------------------
_CAP = re.compile(r"(?i)\b(?:at most|no more than|up to|max(?:imum)?|stops? at|cap(?:ped)? at)\s*(?:of\s*)?"
                  r"(?:US)?\$\s*(\d{1,4}(?:\.\d{1,4})?)\b|\$\s*(\d{1,4}(?:\.\d{1,4})?)\s*(?:at most|max(?:imum)?)\b")


def split_cap(rest: str) -> tuple[str, float | None]:
    """``"accepted at most $2"`` -> ``("accepted", 2.0)``: the run's own limit, said in words."""
    m = _CAP.search(rest or "")
    if not m:
        return (rest or "").strip(), None
    cap = float(m.group(1) or m.group(2))
    return (rest[:m.start()] + rest[m.end():]).strip(" ,.;"), cap if cap > 0 else None


def cap_budget(orch, cap: float | None) -> None:
    """``at most $N``: this run stops once it has spent N more (the project's own limit still holds)."""
    if cap:
        orch.budget.limit_usd = min(orch.budget.limit_usd, orch.budget.spent_usd + float(cap))


def build_project(orch, goal: str = "", cap: float | None = None) -> str:
    """Build the accepted ideas (the plan's waiting changes applied first) or a new goal, approved, within
    ``cap``. The same steps as Update plan, Approve and Build; remote.py's ``build`` does the same."""
    from .orchestrator import HarnessError

    cap_budget(orch, cap)
    goal = (goal or "").strip()
    if goal and goal.lower() != "accepted":
        orch.extend(goal)
    else:
        doc = orch.project.plan_doc() or {}
        if doc.get("pending"):
            orch.revise_plan("")
    meta = orch.project.meta()
    if not meta.get("plan_approved") or meta.get("status") == "awaiting_approval":
        try:
            orch.approve()
        except HarnessError:
            raise
    return orch.run()


def _busy_check(app, root) -> None:
    if app._busy(root):
        raise SlashError("Wait for the job running on this project to finish, then try again.")


def _approve(app, path, rest):
    _rest, cap = split_cap(rest)
    root = _project(app, path).root
    cfg = app.need_cfg()
    _busy_check(app, root)

    def work(job):
        orch = app._orch(cfg, root, job)
        orch.approve()
        cap_budget(orch, cap)
        return {"status": orch.run()}

    return _job(app.jobs.start("run", f"run {root.name}", work, target=str(root)).view(),
                "Approved. Building now" + (f"; it stops at ${cap:.2f}." if cap else "."))


def _build(app, path, rest):
    goal, cap = split_cap(rest)
    if goal.lower() in ("accepted", "the accepted ideas", "accepted ideas", "ideas"):
        goal = ""
    root = _project(app, path).root
    cfg = app.need_cfg()
    _busy_check(app, root)

    def work(job):
        return {"status": build_project(app._orch(cfg, root, job), goal, cap)}

    what = "the new goal" if goal else "the accepted ideas"
    return _job(app.jobs.start("run", f"build {root.name}", work, target=str(root)).view(),
                f"Building {what}" + (f"; it stops at ${cap:.2f}." if cap else "."))


def _plan_edit(app, path, action, **kw):
    from .orchestrator import HarnessError

    try:
        r = app.plan_post({"path": path, "action": action, **kw})
    except HarnessError as e:
        raise SlashError(str(e)) from None
    n = int((r or {}).get("pending") or 0)
    return {"reply": f"Saved. {n} change{'s' if n != 1 else ''} wait{'s' if n == 1 else ''} for the plan to be "
                     "updated (/build does that and builds)."}


def _answer(app, path, rest):
    qid, _, text = rest.partition(" ")
    if not qid or not text.strip():
        raise SlashError("Say which question and the answer, like /answer Q1 blue and gold.")
    return _plan_edit(app, path, "answer", question=qid, text=text.strip())


def _choose(app, path, rest):
    parts = rest.split()
    if len(parts) < 2:
        raise SlashError("Say which decision and which option, like /choose D1 b.")
    return _plan_edit(app, path, "choose", decision=parts[0], option=parts[1])


def _looks(app, path, rest):
    return _job(app.plan_post({"path": path, "action": "looks", "text": rest}),
                "Making new looks. They show on the Plan page to choose from.")


def _accept(app, path, rest):
    parts = rest.split(None, 1)
    if not parts:
        raise SlashError("Say which task to accept, like /accept T3.")
    tid = _task_id(app, path, parts[0], (), "")
    note, cap = split_cap(parts[1] if len(parts) > 1 else "")
    root = _project(app, path).root
    cfg = app.need_cfg()
    _busy_check(app, root)

    def work(job):
        orch = app._orch(cfg, root, job)
        orch.accept(tid, note)
        cap_budget(orch, cap)
        return {"status": orch.run()}

    return _job(app.jobs.start("run", f"accept {tid} in {root.name}", work, target=str(root)).view(),
                f"{tid} is accepted as it is. Building carries on.")


def _autopilot(app, path, rest):
    from ..remote import autopilot_command

    words, cap = split_cap(rest)
    parts = words.split()
    state = parts[0].lower() if parts else "status"
    if state not in ("on", "off", "status"):
        raise SlashError("Say on, off or status, like /autopilot on until 08:00 at most $2.")
    kw: dict[str, Any] = {"state": state}
    until = next((p for p in parts[1:] if re.fullmatch(r"\d{1,2}:\d\d", p)), "")
    if until:
        kw["until"] = until
    if cap:
        kw["cap"] = cap
    return {"reply": autopilot_command(app.need_cfg(), kw)}


def _pictures(app, path, rest):
    return _job(app.project_action({"path": path, "action": "show_it"}),
                "Taking pictures of the app. They show on the Live tab.")


def _note(app, path, rest):
    from .orchestrator import HarnessError, Orchestrator

    if not rest:
        raise SlashError("Say what to tell the planner, like /note use British spelling.")
    try:
        return {"reply": Orchestrator(app.need_cfg(), _project(app, path).root).steer(rest)["reply"]}
    except HarnessError as e:
        raise SlashError(str(e)) from None


def _todo(app, path, rest):
    from ..remote import todo_done
    from .orchestrator import Orchestrator

    parts = rest.split()
    if len(parts) < 2 or parts[0].lower() != "done":
        raise SlashError("Say which to-do is done, like /todo done 20261128-ab12.")
    return {"reply": todo_done(Orchestrator(app.need_cfg(), _project(app, path).root), {"id": parts[1]})}


def _recall_price(app, rest) -> str:
    try:
        from ..ui import recallapi

        r = recallapi.ask(app, {"question": rest, "confirm": False})
        usd = float(r.get("price_usd") or 0)
        return f"It asks one model, with only the pieces it may see: about ${usd:.3f}."
    except Exception:  # noqa: BLE001 - the words are a help
        return "It asks one model, with only the pieces it may see. That is one model call from your accounts."


def _recall(app, path, rest):
    from ..ui import recallapi

    if not rest:
        raise SlashError("Say what you want to know, like /recall which projects use a login page?")
    r = recallapi.ask(app, {"question": rest, "confirm": True})
    return {"reply": str(r.get("answer") or r.get("words") or "Nothing was found."), "cost_usd": r.get("cost_usd", 0)}


def _new(app, path, rest):
    import re as _re

    if not rest:
        raise SlashError("Say what to build, like /new a recipe app for my family.")
    name = _re.sub(r"[^a-z0-9]+", "-", rest.lower()).strip("-")[:40].strip("-") or "new-project"
    base = name
    i = 2
    while (app.projects_dir / name).exists():
        name = f"{base}-{i}"
        i += 1
    return _job(app.project_new({"goal": rest, "dir": name, "approve": True}),
                f"The planner is writing a plan for “{rest[:80]}”. It shows in the Hall; building waits for your yes.")


DO: dict[str, Callable[[Any, str, str], dict[str, Any]]] = {
    "plan": _plan, "run": _run, "next": lambda app, path, rest: _run(app, path, rest, max_tasks=1), "stop": _stop,
    "retry": _retry, "skip": _skip, "undo": _undo, "goal": _goal, "compact": _compact, "model": _model, "test": _test,
    "search": _search, "board": _board, "help": _help,
    "approve": _approve, "build": _build, "answer": _answer, "choose": _choose, "looks": _looks, "accept": _accept,
    "autopilot": _autopilot, "pictures": _pictures, "note": _note, "todo": _todo, "recall": _recall, "new": _new,
}
