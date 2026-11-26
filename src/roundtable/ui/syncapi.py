"""The API of the phone and the PC as one Roundtable (sync.py), for the desktop and the phone's PC and
This-phone modes. Registered in server.py's routes with one line.

    GET  /api/hub/session?name=<hub name or folder>&run=<run id>&since=<lines already held>
         {name, key, live, runs: [{run_id, machine, machine_name, started, ended, status, cost_usd, task,
          lines}], run: {...one of runs, since, events: [lines]}, claim: {machine, machine_name, state, since,
          heartbeat, run_id, fresh}}
    GET  /api/machines
         {this: {id, name, kind}, machines: [{id, name, kind, this, online, listening, last_seen, version,
          building: [{key, hub_name, folder, since, run_id}], state}]}
    GET  /api/settings/shared    {settings: {limits, autopilot, default_profile, roles, changed_by,
                                  changed_by_name, changed_at} | null, this: {...}}
    POST /api/settings/shared    {changes: {limits: {max_cost_usd, max_real_usd_per_run, max_usd_per_day},
                                  autopilot: {on, until, cap}, default_profile, roles: {role: {model,
                                  fallback}}}} -> {settings, changed}
    POST /api/hub/carry_on       {name: hub name} -> {reply, machine, sent, here}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/hub/session"): lambda q: hub_session(app, q),
        ("GET", "/api/machines"): lambda q: machines(app, q),
        ("GET", "/api/settings/shared"): lambda q: shared_get(app, q),
        ("POST", "/api/settings/shared"): lambda body: shared_post(app, body),
        ("POST", "/api/hub/carry_on"): lambda body: carry_on(app, body),
    }


def _first(q: dict, key: str, default: str = "") -> str:
    v = q.get(key) or [default]
    return str(v[0] if isinstance(v, list) else v)


def hub_session(app, q) -> dict[str, Any]:
    from .. import sync
    from .server import ApiError

    hub = app.need_hub()
    name = _first(q, "name")
    if not name:
        raise ApiError("Say which project: name=<its name in the hub>.")
    try:
        since = int(_first(q, "since", "0") or 0)
    except ValueError:
        since = 0
    with app.hub_lock:
        hub.store.sync()
        out = sync.sessions(hub, name, _first(q, "run"), since)
    if not out["runs"]:
        out["message"] = "No build of this project has been watched yet: it shows here once one starts."
    return out


def machines(app, q=None) -> dict[str, Any]:
    from .. import sync

    me = sync.this_machine()
    if not app.hub:
        return {"this": me, "machines": [], "message": "Connect the hub in Settings to see your other machines."}
    with app.hub_lock:
        app.hub.store.sync()
        app.hub.refresh_config()
        return {"this": me, "machines": sync.machines(app.hub, me)}


def _paths(app) -> tuple[Path | None, Path]:
    harness = Path(app.harness_config_path) if app.harness_config_path else None
    return harness, app._backup_home()


def shared_get(app, q=None) -> dict[str, Any]:
    from .. import sync

    hub = app.need_hub()
    harness, home = _paths(app)
    with app.hub_lock:
        hub.store.sync()
        settings = sync.read_shared(hub)
    return {"settings": settings, "this": sync.local_snapshot(harness, home), "machine": sync.this_machine()}


def shared_post(app, body) -> dict[str, Any]:
    from .. import sync
    from .server import ApiError

    hub = app.need_hub()
    changes = body.get("changes")
    if not isinstance(changes, dict) or not changes:
        raise ApiError("Send the settings to change as changes: {limits: {...}, autopilot: {...}, ...}.")
    harness, home = _paths(app)
    try:
        with app.hub_lock:
            return sync.change_shared(hub, changes, harness, home, app.cfg())
    except (TypeError, ValueError) as e:
        raise ApiError(f"Nothing was changed: {e}.") from None


def carry_on(app, body) -> dict[str, Any]:
    """Carry on a paused or stopped run: here when this machine holds the project, else on the machine that
    does (through the hub, addressed to that machine only)."""
    from .. import sync
    from ..remote import FOLDER, MACHINE, PREFIX
    from . import hall
    from .server import ApiError

    hub = app.need_hub()
    name = str(body.get("name") or "")
    with app.hub_lock:
        hub.store.sync()
        hub.refresh_config()  # projects and machines another computer added
        plans = hall.hub_plans(hub)
        where = sync.where_is(hub, name)
        everyone = {m["id"]: m for m in sync.machines(hub)}
    p = plans.get(name)
    if not p:
        raise ApiError("That project isn't in the hub any more. Go back to the Hall and refresh.", 404)
    me = sync.this_machine()
    local = {x.name: x for x in app._lab_projects()}
    if p["folder"] in local and (not where or where["machine"] == me["id"]):
        if where and where.get("building"):
            return {"reply": "It's already building here.", "machine": me, "sent": False, "here": True}
        cfg = app.need_cfg()
        job = app.start_run_job(cfg, local[p["folder"]], why="you asked to carry on")
        return {"reply": "It's on this machine: carrying on now.", "machine": me, "sent": False, "here": True,
                "job": job.view() if job else None}
    if not where:
        raise ApiError("Roundtable doesn't know which machine has this project's files yet. Open it on the machine "
                       "that made it and press Carry on there.", 404)
    if where.get("building"):
        return {"reply": f"It's still building on {where['machine_name']}: nothing to carry on yet.",
                "machine": where, "sent": False, "here": False}
    agent = p["agent"] or p["folder"]
    if agent not in hub.config.agents:
        raise ApiError("That project isn't in the hub. Refresh the Hall and try again.", 404)
    sender = "me" if "me" in hub.config.agents else app.agent
    if not sender:
        raise ApiError("This machine has no name in the hub yet. Connect the hub in Settings first.")
    cmd: dict[str, Any] = {"action": "carry_on", MACHINE: where["machine"]}
    if p["folder"] != agent:
        cmd[FOLDER] = p["folder"]
    try:
        with app.hub_lock:
            hub.send(sender, [agent], f"{PREFIX} carry_on", json.dumps(cmd), kind="request")
    except (PermissionError, ValueError) as e:
        raise ApiError(f"The hub didn't take it: {e}. Check the hub's rules let you message this project.") from None
    m = everyone.get(where["machine"]) or {"kind": "phone" if str(where["machine"]).startswith("phone-") else "pc",
                                           "online": False, "listening": False}
    kind = sync.words_for(m.get("kind", "pc"))
    reply = f"It's on your {kind}: asked it to carry on."
    if not m.get("online"):
        reply += f" Your {kind} is off – it'll pick this up when it's on."
    elif not m.get("listening"):
        reply += f" Your {kind} isn't listening for commands: open Roundtable Hold there."
    return {"reply": reply, "machine": where, "sent": True, "here": False}
