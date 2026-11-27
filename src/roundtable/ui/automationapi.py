"""The Automations page's API (automation.py): work that starts by itself. Registered through FEATURE_APIS.

    GET  /api/automations
         {enabled, automations: [{id, name, kind, on, what, when_words, money, last_run, last_result, last_ok,
          next_run (UTC), made: [{at, text, project, link, status}], waiting: [{key, what, text, at}], spent_usd,
          cap_usd, start_by_itself, editable, when?, do?, repo?, label?, make?, branch?, project?}],
          projects: [{path, name}], github: {set, which}, machine: {id, name}}
    POST /api/automations
         {action: "add", automation: {...}}               -> the same as GET, plus done
         {action: "edit", id, changes: {...}}
         {action: "on" | "off" | "remove", id}
         {action: "run", id}                              Run now (a build still waits for the owner's OK)
         {action: "start", id, key} | {action: "dismiss", id, key}   something that waited for the owner
         {action: "parse", text, zone?}                   plain words -> {when, words}
         {action: "github_key", key}                      the owner's GitHub key, kept in the key store
"""

from __future__ import annotations

from typing import Any

WHICH = {"ROUNDTABLE_GITHUB_TOKEN": "your GitHub key", "ROUNDTABLE_HUB_TOKEN": "the phone's hub key"}


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/automations"): lambda q: listing(app),
        ("POST", "/api/automations"): lambda body: post(app, body),
    }


def listing(app) -> dict[str, Any]:
    from .. import automation as au
    from ..core import secrets as vault
    from ..remote import project_dirs

    ctx = au.app_context(app)
    state = au.load_state(ctx.home, ctx.machine)
    s = au.settings(ctx.cfg)
    which = next((n for n in (au.TOKEN_KEY, *au.TOKEN_FALLBACKS) if vault.get(n)), "")
    out: dict[str, Any] = {
        "enabled": s["enabled"],
        "automations": [au.view(a, state.get(a["id"]) or {}) | ({"on": False} if (state.get(a["id"]) or {}).get("off")
                                                               else {})
                        for a in au.every(ctx.cfg, ctx.home)],
        "projects": [{"path": str(p), "name": p.name} for p in (project_dirs(ctx.cfg) if ctx.cfg else [])],
        "github": {"set": bool(which), "which": WHICH.get(which, "a key on this computer") if which else ""},
        "machine": {"id": ctx.machine["id"], "name": ctx.machine["name"]},
    }
    if not s["enabled"]:
        out["message"] = "Automations are switched off in Roundtable's settings (automation: enabled: false)."
    return out


def post(app, body: dict[str, Any]) -> dict[str, Any]:
    from .. import automation as au
    from .server import ApiError

    ctx = au.app_context(app)
    action, aid = body.get("action"), str(body.get("id") or "")
    try:
        if action == "parse":
            when = au.parse_schedule(str(body.get("text") or ""), body.get("zone") or None)
            return {"when": when, "words": au.when_words(when)}
        if action == "github_key":
            key = str(body.get("key") or "").strip()
            if not app.desktop:
                raise ApiError("This copy reads keys from the computer's own settings. Open the Roundtable Hold app "
                               "to save your GitHub key here.")
            app.desktop["keys"].set(au.TOKEN_KEY, key)  # the key store, and the in-memory vault; never a file here
            done = "Your GitHub key is saved." if key else "Your GitHub key is removed."
        elif action == "add":
            a = au.add(ctx.home, dict(body.get("automation") or {}))
            done = f"Added “{a['name']}”."
        elif action == "edit":
            a = au.edit(ctx.home, aid, dict(body.get("changes") or {}))
            done = f"Saved “{a['name']}”."
        elif action in ("on", "off"):
            a = au.switch(ctx.home, aid, action == "on", ctx.cfg)
            done = f"“{a['name']}” is {action}."
        elif action == "remove":
            au.remove(ctx.home, aid)
            done = "Removed."
        elif action == "run":
            if not ctx.cfg:
                raise ApiError("Roundtable's settings file is missing or has a problem. Open Settings to fix it.", 503)
            done = au.run_now(ctx, aid)["text"]
        elif action == "start":
            done = au.start_waiting(ctx, aid, str(body.get("key") or ""))["text"]
        elif action == "dismiss":
            au.dismiss(ctx.home, aid, str(body.get("key") or ""), ctx.machine)
            done = "Put away."
        else:
            raise ApiError("Say what to do: add, edit, on, off, remove, run, start or dismiss.")
    except au.AutomationError as e:
        raise ApiError(str(e)) from None
    return {**listing(app), "done": done}
