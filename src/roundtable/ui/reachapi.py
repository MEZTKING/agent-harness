"""Reach's API (wave 8, p1-reach): who is listening, one list of services, the MCP catalogue, CI on a project,
local hooks, moving the data, engines that install themselves, the stand-up. Registered through FEATURE_APIS.

    GET  /api/listening                   {machine, at, minutes, words}       (the phone reads it)
    GET  /api/integrations                {rows: [...], groups, counts, words} (no key text, ever; the phone reads it)
    POST /api/integrations/test           {id} -> {id, ok, words, at}
    GET  /api/mcp/catalogue               {servers: [{id, name, group, about, can, writes, needs, needs_missing,
                                           command, added}], checked}
    POST /api/mcp/catalogue/add           {id} -> {added, test: {ok, words, tools}}    (a tick: add, then Test)
    GET  /api/ci?path=                    {state, words, repo, branch, failing, runs, link} (the phone reads it)
    POST /api/hooks/new                   {name?, make?, project?} -> {id, path, header, secret, words}: a local hook;
                                          the secret is in this answer only and never saved
    POST /api/hooks/secret                {id} -> a new secret for that hook (the old one stops working)
    GET  /api/datamove                    {hub: {folder}, projects: {folder}, moves, busy}
    POST /api/datamove                    {action: "move", what: hub|projects, to} -> the job;
                                          {action: "back", id?} -> switched back
    GET  /api/engines/offer?engine=       the "Install it and carry on" card's words
    POST /api/engines/install             {engine, path?} -> the job: install (checked download only), then carry on
    POST /api/standup                     {} -> the stand-up now (no model, no cost)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..brand import NAME


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/listening"): lambda q: listening(app),
        ("GET", "/api/integrations"): lambda q: integrations(app),
        ("POST", "/api/integrations/test"): lambda body: integrations_test(app, body),
        ("GET", "/api/mcp/catalogue"): lambda q: catalogue(app),
        ("POST", "/api/mcp/catalogue/add"): lambda body: catalogue_add(app, body),
        ("GET", "/api/ci"): lambda q: ci_status(app, q),
        ("POST", "/api/hooks/new"): lambda body: hook_new(app, body),
        ("POST", "/api/hooks/secret"): lambda body: hook_secret(app, body),
        ("GET", "/api/datamove"): lambda q: datamove_view(app),
        ("POST", "/api/datamove"): lambda body: datamove_post(app, body),
        ("GET", "/api/engines/offer"): lambda q: engine_offer(app, q),
        ("POST", "/api/engines/install"): lambda body: engine_install(app, body),
        ("POST", "/api/standup"): lambda body: standup_now(app),
    }


def _first(q: dict, key: str, default: str = "") -> str:
    v = q.get(key) or [default]
    return str(v[0] if isinstance(v, list) else v)


def _err(msg: str, status: int = 400):
    from .server import ApiError

    return ApiError(msg, status)


# -- listening ----------------------------------------------------------------------------------------------
def listening(app) -> dict[str, Any]:
    from .. import reach

    return reach.listening(getattr(app, "hub", None))


# -- one list of services -------------------------------------------------------------------------------------
def integrations(app) -> dict[str, Any]:
    from .. import integrations as ig

    return ig.listing(app.cfg(), app.harness_config_path)


def integrations_test(app, body: dict[str, Any]) -> dict[str, Any]:
    from .. import integrations as ig

    try:
        return ig.test(app.cfg(), str(body.get("id") or ""), app.harness_config_path)
    except (ValueError, FileNotFoundError) as e:
        raise _err(str(e)) from None


# -- the MCP catalogue -------------------------------------------------------------------------------------
def catalogue(app) -> dict[str, Any]:
    from .. import prereq

    s = prereq.System.here()
    rows = {r["id"]: r for r in prereq.status(versions=False)}
    try:
        names = {r["name"] for r in prereq.servers_view(app.harness_config_path)["servers"]}
    except (FileNotFoundError, ValueError):
        names = set()
    out = []
    for x in prereq.catalogue_servers(s.os):
        spec = x["spec"]
        out.append({k: x.get(k) for k in ("id", "name", "group", "about", "can", "writes", "needs", "project_folder")}
                   | {"command": " ".join([spec.get("command", "")] + list(spec.get("args") or [])),
                      "needs_missing": [prereq.BY_ID[n].name for n in x.get("needs") or []
                                        if n in rows and rows[n].get("state") == "missing"],
                      "added": x["id"] in names})
    return {"servers": out, "checked": prereq.catalogue().get("checked", "")}


def catalogue_add(app, body: dict[str, Any]) -> dict[str, Any]:
    from .. import prereq
    from .toolsapi import server_add

    sid = str(body.get("id") or "")
    if not any(x["id"] == sid for x in prereq.catalogue_servers(prereq.System.here().os)):
        raise _err("That server isn't on the list. Refresh the page and try again.")
    added = server_add(app, {"known": sid})
    try:
        test = prereq.test_server(app.harness_config_path, added["added"])
    except Exception as e:  # noqa: BLE001 - added all the same; the Test button tries again
        test = {"ok": False, "words": f"Added, but the test couldn't run: {e}", "tools": []}
    return {**added, "test": test}


# -- CI on a project ----------------------------------------------------------------------------------------
def ci_status(app, q: dict) -> dict[str, Any]:
    from .. import ci

    cfg = app.need_cfg()
    proj = app.project(cfg, _first(q, "path"))
    from ..automation import _load_token

    _load_token(app)
    return ci.status(proj.root, fresh=_first(q, "fresh") in ("1", "true"))


# -- local hooks -----------------------------------------------------------------------------------------------
def _hook_answer(a: dict[str, Any], secret: str, words: str) -> dict[str, Any]:
    from .. import reach

    return {"id": a["id"], "name": a["name"], "path": f"/hooks/{a['id']}", "header": reach.SECRET_HEADER,
            "secret": secret, "max_kb": reach.MAX_BODY // 1024, "words": words,
            "note": "Copy the secret now: it is shown only once. Programs on this computer send a POST with it in "
                    f"the {reach.SECRET_HEADER} header; nothing outside this computer can reach it."}


def hook_new(app, body: dict[str, Any]) -> dict[str, Any]:
    from .. import automation as au
    from .. import reach

    ctx = au.app_context(app)
    secret = reach.new_secret()
    raw = {"kind": "local", "name": str(body.get("name") or ""), "make": body.get("make") or "idea",
           "project": body.get("project") or None, "hook": {"secret": secret},
           "start_by_itself": bool(body.get("start_by_itself")), "cap_usd": body.get("cap_usd") or 0}
    try:
        a = au.add(ctx.home, {k: v for k, v in raw.items() if v is not None})
    except au.AutomationError as e:
        raise _err(str(e)) from None
    return _hook_answer(a, secret, f"Added “{a['name']}”.")


def hook_secret(app, body: dict[str, Any]) -> dict[str, Any]:
    from .. import automation as au
    from .. import reach

    ctx = au.app_context(app)
    aid = str(body.get("id") or "")
    cur = next((x for x in au.saved(ctx.home) if x.get("id") == aid and x.get("kind") == "local"), None)
    if not cur:
        raise _err("That hook isn't there any more. Refresh the page.")
    secret = reach.new_secret()
    try:
        a = au.edit(ctx.home, aid, {"hook": {"secret": secret}})
    except au.AutomationError as e:
        raise _err(str(e)) from None
    return _hook_answer(a, secret, "A new secret is made. The old one no longer works.")


# -- moving the data -------------------------------------------------------------------------------------------
def _busy(app) -> bool:
    if any(j.status == "running" and j.kind in ("run", "plan", "install", "move")
           for j in app.jobs.jobs.values()):
        return True
    from ..harness.orchestrator import Project

    for p in app._lab_projects():
        try:
            if Project(p).meta().get("status") in ("running", "planning"):
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _homes(app) -> dict[str, Any]:
    d = getattr(app, "desktop", None)
    if not d:
        raise _err(f"Moving your data works in the {NAME} app on your PC.", 409)
    paths = d["paths"]
    return {"home": paths.home, "hub_yaml": paths.hub_yaml, "settings": paths.settings}


def datamove_view(app) -> dict[str, Any]:
    from .. import datamove

    h = _homes(app)
    hub = datamove.hub_folder(h["hub_yaml"])
    return {"hub": {"folder": str(hub) if hub else ""}, "projects": {"folder": str(app.projects_dir)},
            "moves": [{k: v for k, v in m.items() if k != "pointers"} for m in reversed(datamove.moves(h["home"]))][:5],
            "busy": _busy(app)}


def datamove_post(app, body: dict[str, Any]) -> dict[str, Any]:
    import json

    from .. import datamove
    from ..core.config import saved_hub_pointer

    h = _homes(app)
    action = body.get("action")
    if action == "back":
        try:
            res = datamove.switch_back(h["home"], str(body.get("id") or ""), busy=_busy(app))
        except datamove.MoveError as e:
            raise _err(str(e)) from None
        _reload(app)
        return res
    if action != "move":
        raise _err("Say what to do: move or back.")
    what, to = str(body.get("what") or ""), str(body.get("to") or "").strip()
    if what not in datamove.WHATS or not to:
        raise _err("Pick what to move (the hub or the projects) and the new folder.")
    if _busy(app):
        raise _err("Something is building. Wait for it to finish (or stop it), then move your data.", 409)
    if what == "hub":
        src = datamove.hub_folder(h["hub_yaml"])
        if not src:
            raise _err("The hub isn't set up on this computer yet.")
        ptrs = datamove.pointers_for("hub", hub_yaml=h["hub_yaml"], hub_pointer=saved_hub_pointer())
    else:
        src = app.projects_dir
        settings = {}
        try:
            settings = json.loads(Path(h["settings"]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        if not settings.get("projects_dir"):  # the default folder: written down, so it can be pointed elsewhere
            settings["projects_dir"] = str(src)
            Path(h["settings"]).write_text(json.dumps(settings, indent=2), encoding="utf-8")
        cfg = app.cfg()
        ptrs = datamove.pointers_for("projects", settings_file=h["settings"],
                                     lab_dir=getattr(cfg, "lab_dir", None) if cfg else None)
    try:
        datamove.check(Path(src), Path(to))
    except datamove.MoveError as e:
        raise _err(str(e)) from None

    def run(job):
        res = datamove.move(h["home"], what, Path(src), Path(to), ptrs, busy=_busy_but(app, job), line=job.line)
        _reload(app)
        return res

    return app.jobs.start("move", f"move the {'hub' if what == 'hub' else 'projects'}", run, target="datamove").view()


def _busy_but(app, job) -> bool:
    return any(j is not job and j.status == "running" and j.kind in ("run", "plan", "install")
               for j in app.jobs.jobs.values())


def _reload(app) -> None:
    """After a switch: the app reads its pointers again."""
    import json

    try:
        settings = json.loads(Path(app.desktop["paths"].settings).read_text(encoding="utf-8"))
        if settings.get("projects_dir"):
            app.projects_dir = Path(settings["projects_dir"]).expanduser().resolve()
    except Exception:  # noqa: BLE001
        pass
    for name in ("reload_hub", "_load_hub", "reload"):
        fn = getattr(app, name, None)
        if callable(fn):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass
            break


# -- engines that install themselves ----------------------------------------------------------------------------
def engine_offer(app, q: dict) -> dict[str, Any]:
    from .. import prereq

    try:
        return prereq.engine_offer(_first(q, "engine"))
    except ValueError as e:
        raise _err(str(e)) from None


def engine_install(app, body: dict[str, Any]) -> dict[str, Any]:
    from .. import prereq

    engine = str(body.get("engine") or "")
    try:
        offer = prereq.engine_offer(engine)
    except ValueError as e:
        raise _err(str(e)) from None
    if not offer["auto"]:
        raise _err(offer["words"])
    root = None
    if body.get("path"):
        cfg = app.need_cfg()
        root = app.project(cfg, str(body["path"])).root

    def carry_on():
        if root is not None:
            app.start_run_job(app.need_cfg(), root, f"after installing {offer['name']}")

    return app.jobs.start("install", f"install {offer['name']} and carry on",
                          lambda job: prereq.install_and_carry_on(engine, job.line, carry_on),
                          target=f"install:{offer['tool']}").view()


# -- the stand-up -------------------------------------------------------------------------------------------------
def standup_now(app) -> dict[str, Any]:
    from .. import automation as au
    from .. import reach

    ctx = au.app_context(app)
    if not ctx.cfg:
        raise _err("The harness's settings file is missing or has a problem. Open Settings to fix it.", 503)
    res = reach.standup(ctx)
    return {k: v for k, v in res.items() if k != "projects"} | {
        "projects": [{k: r[k] for k in ("name", "state", "done", "total", "stuck", "spent", "agreed")}
                     for r in res.get("projects") or []]}
