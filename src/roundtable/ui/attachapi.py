"""The message box (attachments.py) as an API, for the desktop's compose.js and the phone's Composer.

Drafts (one per message box, by ``key``; kept in the app's own folder, so they survive closing the app):

    GET  /api/attach/draft?key=K              {key, text, mode, saved_at, items: [{id, name, kind, size_words, preview?}]}
    POST /api/attach/draft   {key, text, mode?}  -> the draft (mode: queue | steer)
    POST /api/attach/upload  {key, name, data (base64), upload_id?, last?}
         a file in parts of at most about 1.4 MB: {upload_id} until ``last``, then {item, draft}
    POST /api/attach/remove  {key, id}        -> the draft
    POST /api/attach/clear   {key}            -> {}

The project's files for @ (``project`` is a registered project's path):

    GET  /api/attach/files?project=P&q=text   {files: ["src/app.py", …]}
    GET  /api/attach/list?project=P           {items: [...]} what's attached to the project

Sending a draft:

    POST /api/attach/start {key, wizard}      a new project from the wizard's answers (as POST /api/asks
         {wizard}), its draft's files attached to the idea before the planner starts
    POST /api/attach/start {key, dir, goal?, approve, references}   the same, typed (as POST /api/projects);
         the goal is the draft's text when not given
    POST /api/attach/send  {key, path, as, mode?, text?}
         as "chat": a question to the planner (the files go with this question only)
         as "note": "Tell the planner" – mode "queue" (default): from the next task on; "steer": also into
                    the task working now, at its next step (only while it runs; otherwise it is queued)
         as "goal": a new goal for the project (like Build more), the files with it
         -> {reply, items, delivered: "queue" | "steer" | "chat" | "goal", job?}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import attachments as att


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/attach/draft"): lambda q: _wrap(lambda: _draft(app, _first(q, "key")).view()),
        ("POST", "/api/attach/draft"): lambda b: _wrap(lambda: _draft(app, b.get("key")).save_text(
            str(b.get("text") or ""), b.get("mode"))),
        ("POST", "/api/attach/upload"): lambda b: _wrap(lambda: upload(app, b)),
        ("POST", "/api/attach/remove"): lambda b: _wrap(lambda: _removed(app, b)),
        ("POST", "/api/attach/clear"): lambda b: _wrap(lambda: (_draft(app, b.get("key")).clear(), {})[1]),
        ("GET", "/api/attach/files"): lambda q: _wrap(lambda: {"files": att.project_files(
            _project(app, _first(q, "project")).root, _first(q, "q"))}),
        ("GET", "/api/attach/list"): lambda q: _wrap(lambda: {"items": [att.public(x) for x in att.project_items(
            _project(app, _first(q, "project")).root)]}),
        ("POST", "/api/attach/start"): lambda b: _wrap(lambda: start(app, b)),
        ("POST", "/api/attach/send"): lambda b: _wrap(lambda: send(app, b)),
    }


def _first(q: dict, key: str) -> str:
    v = q.get(key) or [""]
    return str(v[0] if isinstance(v, list) else v)


def _wrap(fn):
    from .server import ApiError

    try:
        return fn()
    except att.AttachmentError as e:
        raise ApiError(str(e)) from None


def _home(app) -> Path:
    return Path(app._backup_home())


def _draft(app, key) -> att.Draft:
    return att.Draft(_home(app), str(key or ""))


def _settings(app) -> att.Settings:
    return att.Settings.from_config(app.cfg())


def _project(app, path: str):
    return app.project(app.need_cfg(), path)


def upload(app, b: dict[str, Any]) -> dict[str, Any]:
    return att.upload_part(_home(app), str(b.get("key") or ""), str(b.get("name") or "file"), str(b.get("data") or ""),
                           upload_id=str(b.get("upload_id") or ""), last=b.get("last", True) is not False,
                           settings=_settings(app))


def _removed(app, b: dict[str, Any]) -> dict[str, Any]:
    d = _draft(app, b.get("key"))
    d.remove(str(b.get("id") or ""))
    return d.view()


def _text(d: att.Draft, b: dict[str, Any]) -> str:
    return str(b.get("text") if b.get("text") is not None else d.meta().get("text") or "").strip()


def start(app, b: dict[str, Any]) -> dict[str, Any]:
    """A new project, with the draft's files attached to the idea first (so the planner's very first call has
    them): from the wizard's answers ({wizard}) or typed ({dir, goal, approve, references}). The same steps as
    the server's own starts (POST /api/asks {wizard}, POST /api/projects)."""
    from ..asks import wizard_project
    from ..harness.orchestrator import HarnessError
    from .server import ApiError, _lines

    cfg = app.need_cfg()
    d = _draft(app, b.get("key"))
    if isinstance(b.get("wizard"), dict):
        try:
            w = wizard_project(b["wizard"], app.projects_dir)
            if w["profile"] and w["profile"] not in cfg.profiles:
                raise HarnessError(f"there's no {w['profile']} setting; choose another")
        except HarnessError as e:
            raise ApiError(str(e))
        path, approve = Path(w["dir"]).resolve(), True
    else:
        goal, name = _text(d, {"text": b.get("goal")}), str(b.get("dir") or "").strip()
        if not goal or not name:
            raise ApiError("Give the project a folder name and say what to build, then start it.")
        path = Path(name).expanduser()
        path = (path if path.is_absolute() else app.projects_dir / path).resolve()
        if (path / ".harness/project.json").exists():
            raise ApiError(f"{path} already has a project. Open it and add a new goal there instead.")
        w = {"goal": goal, "references": _lines(b.get("references")), "profile": None, "look": None}
        approve = bool(b.get("approve", True))
    items = att.claim(d, path, "goal", _settings(app), goal_index=0)
    goal = w["goal"] + (f"\n(The owner attached: {att.names_line(items)}.)" if items else "")

    def run(job):
        orch = app._orch(cfg, path, job)
        orch.start(goal, require_approval=approve, references=w["references"])
        if w["profile"]:
            orch.set_profile(w["profile"])
        if w["look"] is not None:
            meta = orch.project.meta()
            meta.update(look_step=w["look"], look_brief=w["look_note"])
            orch.project.save_meta(meta)
        return {"status": orch.run(max_tasks=b.get("max_tasks")), "path": str(path)}

    job = app.jobs.start("run", f"new project {path.name}", run, target=str(path)).view()
    d.clear()
    with_files = f" with {len(items)} attached" if items else ""
    return {"reply": f"Started {path.name}{with_files}: the planner is drawing up the plan.", "job": job,
            "path": str(path), "target": str(path), "items": [att.public(x) for x in items]}


def send(app, b: dict[str, Any]) -> dict[str, Any]:
    from .server import ApiError

    cfg = app.need_cfg()
    proj = _project(app, str(b.get("path") or ""))
    d = _draft(app, b.get("key"))
    text = _text(d, b)
    kind = str(b.get("as") or "note")
    mode = b.get("mode") if b.get("mode") in att.MODES else (d.meta().get("mode") or "queue")
    if kind not in ("chat", "note", "goal"):
        raise ApiError("Say chat, note or goal.")
    if not text:
        raise ApiError("Write something first." if kind != "goal" else "Say what to build next first.")
    if kind == "goal" and app._busy(proj.root):
        raise ApiError("Wait for the job running on this project to finish, then try again.", 409)
    s = _settings(app)
    before = {x["id"] for x in att.project_items(proj.root)}
    try:
        return _send(app, cfg, proj, d, text, kind, mode, s)
    except Exception:  # nothing went: the files leave the project again, the draft keeps them
        folder = att.project_folder(proj.root)
        for x in folder.items():
            if x["id"] not in before:
                folder.remove(x["id"])
        raise


def _send(app, cfg, proj, d: att.Draft, text: str, kind: str, mode: str, s: att.Settings) -> dict[str, Any]:
    from ..harness.orchestrator import HarnessError, Orchestrator
    from .server import ApiError

    try:
        if kind == "chat":
            items = att.claim(d, proj.root, "chat", s, pending=True)
            try:
                said = text + (f"\n(The owner attached: {att.names_line(items)}.)" if items else "")
                r = Orchestrator(cfg, proj.root).ask(said)
            finally:
                att.finish_chat(proj.root, [x["id"] for x in items])
            d.clear()
            return {**r, "items": [att.public(x) for x in items], "delivered": "chat"}
        if kind == "goal":
            goals = len((proj.meta() or {}).get("goals") or [])
            items = att.claim(d, proj.root, "goal", s, goal_index=goals)
            goal = text + (f"\n(The owner attached: {att.names_line(items)}.)" if items else "")
            job = app.project_action({"path": str(proj.root), "action": "extend", "goal": goal})
            d.clear()
            return {"reply": "Sent: the planner plans it next.", "job": job, "items": [att.public(x) for x in items],
                    "delivered": "goal"}
        items = att.claim(d, proj.root, "note", s)
        note = text + (f"\n(The owner attached: {att.names_line(items)}.)" if items else "")
        r = Orchestrator(cfg, proj.root).steer(note)
        d.clear()
        delivered = "queue"
        if mode == "steer" and app._busy(proj.root):
            att.steer_now(proj.root, note)
            delivered = "steer"
            r["reply"] = "Sent to the task working now: it reads it at its next step. Later tasks get it too."
        elif mode == "steer":
            r["reply"] = "Nothing is working right now, so it waits for the next task. " + r["reply"]
        return {**r, "items": [att.public(x) for x in items], "delivered": delivered}
    except HarnessError as e:
        raise ApiError(str(e))
