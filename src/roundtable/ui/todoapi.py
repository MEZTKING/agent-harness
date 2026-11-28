"""To-dos as actions, hub seats, a repository's declared set-up and the backups folder picker (wave 9, w9-gaps).
Registered through FEATURE_APIS ("todoapi").

    GET  /api/todo/actions            {todos: [{agent, id, project, text, action}], with, without}
    POST /api/todo/act                {agent, id, confirm?} -> {confirm, label} (asks first) | {open: "#/..."} |
                                      {ok, reply, result}; the route comes from todoactions' table, never the page
    POST /api/todo/handoff            {agent, id, to?} -> {ok, reply}: the to-do as a letter to the session that does it
    POST /api/todo/github             {repo, branch, confirm} -> {ok, reply}: the default branch, with the app's GitHub key
    POST /api/todo/backup             {folder?} -> backup.turn_on's {ok, destination, words}
    POST /api/backup/browse           {start?} -> {folder} (None: cancelled); the desktop window's own dialog
    GET  /api/hub/seats               {seats, listening}: every hub project as a seat, and who last listened
    POST /api/hub/send-once           {agent, folder, action, fields?} -> {sent, reply, listening}
    GET  /api/setup/declared?path=    setupdecl.check: what this computer still needs for that project
    POST /api/setup/declared          {path, yes} -> the answer remembered (the run does the work)

Only ``GET /api/todo/actions``, ``GET /api/hub/seats`` and ``GET /api/setup/declared`` read without changing
anything; the rest spend, write files or change settings and stay on the PC.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable

GITHUB_API = "https://api.github.com/repos/"
# (method, url, body, token) -> (status, json); a stand-in in the tests, urllib otherwise
GitHubCall = Callable[[str, str, dict[str, Any], str], tuple[int, dict[str, Any]]]
github_call: GitHubCall | None = None


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/todo/actions"): lambda q: actions(app),
        ("POST", "/api/todo/act"): lambda body: act(app, body),
        ("POST", "/api/todo/handoff"): lambda body: handoff(app, body),
        ("POST", "/api/todo/github"): lambda body: github(app, body),
        ("POST", "/api/todo/backup"): lambda body: backup_on(app, body),
        ("POST", "/api/backup/browse"): lambda body: browse(app, body),
        ("GET", "/api/hub/seats"): lambda q: hub_seats(app),
        ("POST", "/api/hub/send-once"): lambda body: send_once(app, body),
        ("GET", "/api/setup/declared"): lambda q: declared_get(app, q),
        ("POST", "/api/setup/declared"): lambda body: declared_post(app, body),
    }


def _err(msg: str, status: int = 400):
    from .server import ApiError

    return ApiError(msg, status)


def _first(q: dict, key: str, default: str = "") -> str:
    v = q.get(key) or [default]
    return str(v[0] if isinstance(v, list) else v)


# -- the to-dos ------------------------------------------------------------------------------------------------
def _todo_needs(app) -> list[dict[str, Any]]:
    from .roundtable import build

    return [n for n in build(app).get("needs_you") or [] if n.get("kind") == "todo"]


def _entry(app, agent: str, tid: str) -> dict[str, Any] | None:
    hub = getattr(app, "hub", None)
    if not hub or agent not in hub.config.agents:
        return None
    with app.hub_lock:
        for e in hub.journal.entries(agent, agent):
            if e.get("id") == tid:
                return e
    return None


def _find(app, body: dict[str, Any]) -> dict[str, Any]:
    """The to-do the card shows (the Hall's own Needs-you item, with its project), from {agent, id}."""
    agent, tid = str(body.get("agent") or ""), str(body.get("id") or "")
    if not tid:
        raise _err("Say which to-do. Refresh the page and try again.")
    for n in _todo_needs(app):
        if n.get("id") == tid and (not agent or n.get("agent") == agent or n.get("project") == agent):
            e = _entry(app, n.get("agent") or n["project"], tid) or {}
            return {**e, **n}
    e = _entry(app, agent, tid)
    if not e:
        raise _err("That to-do isn't on the list any more. Refresh the page.", 404)
    return {**e, "agent": agent, "project": agent}


def actions(app) -> dict[str, Any]:
    from .. import todoactions

    out, counts = [], {"with": 0, "without": 0}
    for n in _todo_needs(app):
        a = todoactions.action_for(n, app)
        counts["with" if a else "without"] += 1
        out.append({"agent": n.get("agent"), "id": n.get("id"), "project": n.get("project"), "text": n.get("text"),
                    "action": a})
    return {"todos": out, **counts}


def _close(app, todo: dict[str, Any], note: str) -> None:
    hub = getattr(app, "hub", None)
    if not hub:
        return
    try:
        with app.hub_lock:
            hub.journal.close(todo.get("agent") or todo["project"], todo["id"], note=note)
    except Exception:  # noqa: BLE001 - done is done; the list catches up on the next sync
        pass


def act(app, body: dict[str, Any]) -> dict[str, Any]:
    """Do the to-do's own action, from the server's table (todoactions), never a route the page sends."""
    from .. import hubseats, todoactions

    todo = _find(app, body)
    a = todoactions.action_for(todo, app)
    if not a:
        raise _err("This to-do has no button: tick it off with Done once it's done.")
    if a["route"].startswith("#/"):
        return {"open": a["route"], "label": a["label"]}
    if a.get("confirm") and body.get("confirm") is not True:
        return {"confirm": a["confirm"], "label": a["label"]}
    if a["kind"] == "hub":
        b = a["body"]
        got = hubseats.send_once(app, b["agent"], b.get("folder") or "", b["action"], b.get("fields"))
        result, reply = got, got["reply"]
    elif a["kind"] == "handover":
        result = handoff(app, {**a["body"], "_todo": todo})
        return result
    else:
        result = app.dispatch("POST", a["route"], {}, {**a["body"], **({"confirm": True} if a.get("confirm") else {})})
        if isinstance(result, dict) and result.get("confirm") and not result.get("id"):
            return {"confirm": result["confirm"], "label": a["label"]}  # the route's own "Are you sure?"
        if isinstance(result, dict) and result.get("ok") is False:
            return {"ok": False, "reply": result.get("words") or result.get("reply") or "It couldn't be done yet.",
                    "result": result}
        reply = (result.get("words") or result.get("reply") if isinstance(result, dict) else "") or \
            ("Started: it shows in Activity." if isinstance(result, dict) and result.get("id") else "Done.")
    if a.get("close"):
        _close(app, todo, f"done from the app: {a['label']}")
    return {"ok": True, "reply": reply, "result": result}


def handoff(app, body: dict[str, Any]) -> dict[str, Any]:
    """The to-do as a letter to the session that does it (a cloud session, the project's own agent); off the
    owner's list once it's sent."""
    hub = getattr(app, "hub", None)
    if not hub:
        raise _err("There's no hub to send it through. Connect the hub in Settings → Hub first.")
    todo = body.get("_todo") or _find(app, body)
    to = str(body.get("to") or todo.get("agent") or todo.get("project") or "")
    if to not in hub.config.agents:
        raise _err("The session that does this isn't in the hub. Refresh the Hall and try again.", 404)
    if not getattr(app, "agent", ""):
        raise _err("This computer has no name in the hub yet. Connect the hub in Settings first.")
    text = str(todo.get("text") or "")
    details = str(todo.get("details") or "")
    letter = (f"The owner handed you this to-do from the app, so they don't have to do it by hand:\n\n{text}\n"
              + (f"\nDetails:\n{details}\n" if details else "")
              + "\nDo it with your own tools (the GitHub tools, the cloud environment tools, Remote Control on the "
                "owner's PC), then reply in one plain sentence. If only the owner can do it, say why and make it a "
                "one-tap card in the app instead.")
    try:
        with app.hub_lock:
            hub.send(app.agent, [to], "A to-do handed to you", letter, kind="request")
    except (PermissionError, ValueError) as e:
        raise _err(f"The hub didn't take it: {e}. Check the hub's rules let you message this project.") from None
    _close(app, todo, f"handed to {to}")
    from .hall import friendly

    return {"ok": True, "reply": f"Handed to {friendly(to, hub.config.agents.get(to))}: its answer comes back in its chat."}


# -- GitHub settings through the app's own key ------------------------------------------------------------------
def _github(method: str, url: str, body: dict[str, Any], token: str) -> tuple[int, dict[str, Any]]:
    if github_call is not None:
        return github_call(method, url, body, token)
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method=method, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "darkness-harness",
        "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, OSError) as e:
        raise _err(f"GitHub couldn't be reached ({getattr(e, 'reason', e)}). Try again when you're online.") from None


def _full_repo(app, repo: str) -> str:
    repo = (repo or "").strip().strip("`").removesuffix(".git")
    if "/" in repo:
        return repo
    hub = getattr(app, "hub", None)
    for spec in (hub.config.agents.values() if hub else []):
        r = (getattr(spec, "repo", "") or "").strip().rstrip("/")
        if r.split("/")[-1].lower() == repo.lower() and "/" in r:
            return "/".join(r.split("/")[-2:])
    raise _err(f"Which repository is {repo or 'it'}? Say it as owner/name.")


def github(app, body: dict[str, Any]) -> dict[str, Any]:
    from ..automation import github_token

    repo = _full_repo(app, str(body.get("repo") or ""))
    branch = str(body.get("branch") or "main").strip()
    if body.get("confirm") is not True:
        return {"confirm": f"Make {branch} the default branch of {repo} on GitHub?"}
    token = github_token()
    if not token:
        raise _err("The app has no GitHub key yet. Add one on the Automations page (GitHub key), then try again.")
    status, data = _github("PATCH", GITHUB_API + repo, {"default_branch": branch}, token)
    if status == 200 and data.get("default_branch") == branch:
        return {"ok": True, "reply": f"Done: {branch} is now the default branch of {repo}."}
    if status in (401, 403):
        raise _err("Your GitHub key isn't allowed to change this repository's settings. It needs "
                   "Administration: read and write; add a key with that on the Automations page.")
    if status == 404:
        raise _err(f"GitHub can't find {repo} with your key. Check the name, or give the key that repository.")
    if status == 422:
        raise _err(f"GitHub says there's no branch {branch} in {repo} yet.")
    raise _err(f"GitHub said no (HTTP {status}). Try again later.")


# -- backups --------------------------------------------------------------------------------------------------
def backup_on(app, body: dict[str, Any]) -> dict[str, Any]:
    from .. import backup as bk

    try:
        return bk.turn_on(app._backup_home(), str(body.get("folder") or "") or None)
    except bk.BackupError as e:
        raise _err(str(e)) from None


def browse(app, body: dict[str, Any]) -> dict[str, Any]:
    from .. import backup as bk

    try:
        return {"folder": bk.pick_folder(str(body.get("start") or "") or None)}
    except bk.BackupError as e:
        raise _err(str(e)) from None


# -- hub seats ------------------------------------------------------------------------------------------------
def hub_seats(app) -> dict[str, Any]:
    from .. import hubseats

    beat = hubseats.listening(app)
    return {"seats": hubseats.seats(app, beat), "listening": beat}


def send_once(app, body: dict[str, Any]) -> dict[str, Any]:
    from .. import hubseats

    agent = str(body.get("agent") or "")
    hub = getattr(app, "hub", None)
    if not hub or agent not in hub.config.agents:
        raise _err("That project isn't in the hub. Refresh the Hall and try again.", 404)
    return hubseats.send_once(app, agent, str(body.get("folder") or ""), str(body.get("action") or ""),
                              body.get("fields") or {})


# -- a repository's declared set-up -----------------------------------------------------------------------------
def _project_root(app, path: str):
    cfg = app.need_cfg()
    return app.project(cfg, path).root


def declared_get(app, q: dict) -> dict[str, Any]:
    from ..harness import setupdecl

    return setupdecl.check(_project_root(app, _first(q, "path")))


def declared_post(app, body: dict[str, Any]) -> dict[str, Any]:
    from ..harness import setupdecl

    root = _project_root(app, str(body.get("path") or ""))
    got = setupdecl.answer(root, bool(body.get("yes")))
    return {**got, "reply": "Fetched and installed when the run starts." if got["yes"] else
            "Left for now: nothing is fetched or installed."}
