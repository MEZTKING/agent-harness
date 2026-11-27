"""The Tools page's API (prereq.py): what this computer has, installs, and the MCP tool servers.

    GET  /api/tools                       {os, tools: [{id, name, group, why, state: found|missing|old|broken,
                                           words, version, where, detail, also, extras, min_version,
                                           install: {can, via, shown, text, admin, reboot, needs, blocked, note,
                                           size}}], groups, servers: [{name, where, enabled, from, removable,
                                           roles, jobs}], jobs: [{role, name, servers}], known: [{id, name, about,
                                           steps, needs, prepare?, added}], servers_error}
                                          (?fresh=1 looks again instead of using the last look; the phone reads it)
    POST /api/tools/check                 {} -> the same as GET, looked at again
    POST /api/tools/install               {tool, confirm?} -> {confirm: words} when it needs a yes first, else the
                                          background job (kind "install"); never runs without the owner's press
    POST /api/tools/servers/add           {known} or {name, command, args, env, cwd, url, timeout} -> {added, ...}
    POST /api/tools/servers/remove        {name}
    POST /api/tools/servers/test          {name} -> {name, ok, words, tools, error}
    POST /api/tools/servers/give          {name, roles: [job ids]} -> {name, roles, jobs}
    POST /api/tools/servers/prepare       {known} -> the background job (MCP for Blender: its add-on put in place)

``needs(app)`` gives the Needs-you cards for projects missing a tool (kind "tool"), for the Hall to show.
"""

from __future__ import annotations

from typing import Any

from .. import prereq


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/tools"): lambda q: view(app, fresh=_first(q, "fresh") in ("1", "true")),
        ("POST", "/api/tools/check"): lambda body: view(app, fresh=True),
        ("POST", "/api/tools/install"): lambda body: install(app, body),
        ("POST", "/api/tools/servers/add"): lambda body: server_add(app, body),
        ("POST", "/api/tools/servers/remove"): lambda body: _wrap(prereq.remove_server, app, str(body.get("name") or "")),
        ("POST", "/api/tools/servers/test"): lambda body: _wrap(prereq.test_server, app, str(body.get("name") or "")),
        ("POST", "/api/tools/servers/give"): lambda body: _wrap(prereq.give_server, app, str(body.get("name") or ""),
                                                               list(body.get("roles") or [])),
        ("POST", "/api/tools/servers/prepare"): lambda body: prepare(app, body),
    }


def _first(q: dict, key: str, default: str = "") -> str:
    v = q.get(key) or [default]
    return str(v[0] if isinstance(v, list) else v)


def _godot_path(app) -> str | None:
    cfg = app.cfg()
    return getattr(getattr(cfg, "godot", None), "path", None) if cfg else None


def _wrap(fn, app, *args):
    from .server import ApiError

    try:
        return fn(app.harness_config_path, *args)
    except FileNotFoundError as e:
        raise ApiError(str(e), 503) from None
    except ValueError as e:
        raise ApiError(str(e)) from None


def view(app, fresh: bool = False) -> dict[str, Any]:
    s = prereq.System.here()
    rows = prereq.status(godot_path=_godot_path(app), fresh=fresh)
    if getattr(app, "desktop", None):  # this computer's memory learns what it can build with (memory.py)
        try:
            from .. import memory

            memory.refresh_machine(app.desktop["paths"].home, rows=rows, os_name=s.os)
        except Exception:  # memory is a help: the Tools page shows all the same
            pass
    out: dict[str, Any] = {"os": s.os, "tools": rows, "groups": prereq.GROUPS, "servers": [], "jobs": [],
                           "servers_error": ""}
    try:
        out.update(prereq.servers_view(app.harness_config_path))
    except (FileNotFoundError, ValueError) as e:
        out["servers_error"] = str(e)
    names = {r["name"] for r in out["servers"]}
    out["known"] = [{k: v for k, v in x.items() if k != "spec"} | {"added": x["id"] in names}
                    for x in prereq.known_servers(s.os)]
    return out


def install(app, body) -> dict[str, Any]:
    from .server import ApiError

    tid = str(body.get("tool") or "")
    tool = prereq.BY_ID.get(tid)
    if not tool:
        raise ApiError("Roundtable doesn't know that tool. Refresh the page and try again.")
    s = prereq.System.here()
    plan = prereq.install_plan(tool, s.os)
    if not plan["can"]:
        raise ApiError(f"{tool.name} can't be installed from the app on this computer. {plan['text']}".strip())
    words = prereq.confirm_words(tool, s.os)
    if words and not body.get("confirm"):
        return {"confirm": words, "tool": tid, "title": f"Install {tool.name}?"}

    def run(job):
        return prereq.run_install(tid, job.line)

    return app.jobs.start("install", f"install {tool.name}", run, target=f"install:{tid}").view()


def server_add(app, body) -> dict[str, Any]:
    spec = {k: body[k] for k in ("command", "args", "env", "cwd", "url", "headers", "timeout", "tools") if k in body}
    out = _wrap(lambda path: prereq.add_server(path, name=str(body.get("name") or ""), spec=spec,
                                               known=str(body.get("known") or "")), app)
    return {"added": out["name"], **out}


def prepare(app, body) -> dict[str, Any]:
    from .server import ApiError

    known = str(body.get("known") or "")
    if not any(k["id"] == known and k.get("prepare") for k in prereq.known_servers(prereq.System.here().os)):
        raise ApiError("That server needs nothing put in place first.")
    return app.jobs.start("install", f"set up {known} for its tool server",
                          lambda job: prereq.prepare_server(known, job.line), target=f"prepare:{known}").view()


def needs(app) -> list[dict[str, Any]]:
    """Needs-you cards: a project on this computer needs a tool that isn't here (presence only, no programs run)."""
    try:
        projects = app._lab_projects()
        if not projects:
            return []
        rows = prereq.status(versions=False, godot_path=_godot_path(app))
        return prereq.needs_cards(projects, rows)
    except Exception:  # a look at the tools must never take the Hall down
        return []
