"""Every hub project is a seat (wave 9, w9-gaps).

Most of this has been in the Hall since the rebuild (``ui/roundtable.py`` ``build``: a plan in the hub gets a
seat of its own with its state, its cards and Approve through the hub). What was left, and is here:

* **Is anything listening there?** ``seats`` and ``join`` give every seat that runs elsewhere the hub's
  ``listening`` beat (``reach.listening``): "Your PC last listened 4 minutes ago", or that nothing will start
  until the app is open there again. A tap is never silently lost.
* **A hub project the table didn't seat**: a plan published under a name the Hall's rules skipped (an agent that
  isn't the harness's runner and isn't the folder) still gets a seat, with its plan and cards.
* **Sent once**: ``send_once`` sends Open the plan / Approve (or any hub action) through the hub (``remote``'s
  own commands, the app's ``hub_command``) only when the same command isn't already waiting there unread, and
  the reply says whether anything is listening.

Nothing here calls a model or the network beyond the hub the app already syncs.
"""

from __future__ import annotations

import json
from typing import Any

STALE_MINUTES = 15  # reach.listening says "Nothing will start…" from here


def listening(app) -> dict[str, Any]:
    """{machine, at, minutes, words, stale}: which harness last listened to the hub, and how long ago."""
    from . import reach

    hub = getattr(app, "hub", None)
    got = dict(reach.listening(hub))
    got["stale"] = got.get("minutes") is None or got["minutes"] >= STALE_MINUTES
    return got


def seats(app, beat: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """A seat for every plan in the hub: {id, name, hub_name, hub_agent, where, status, state, goal, asks,
    actions, listening}. Plans run on this computer are left to the table's own seat."""
    hub = getattr(app, "hub", None)
    if not hub:
        return []
    from .ui import hall

    lock = getattr(app, "hub_lock", None)
    try:
        if lock:
            with lock:
                plans = hall.hub_plans(hub)
        else:
            plans = hall.hub_plans(hub)
    except Exception:  # noqa: BLE001 - never breaks the table
        return []
    try:
        here = {p.name for p in app._lab_projects()}
    except Exception:  # noqa: BLE001
        here = set()
    beat = beat if beat is not None else listening(app)
    out = []
    for p in plans.values():
        sid = p["folder"]
        if sid in here:
            continue
        status, words = hall.plan_state(p["state"])
        spec = hub.config.agents.get(sid)
        out.append({
            "id": sid, "name": hall.friendly(sid, spec), "kind": "remote", "hub_name": p["name"],
            "hub_agent": p["agent"] or sid, "where": "elsewhere", "status": status, "state": words,
            "goal": p.get("goal") or "", "detail": p.get("summary") or "", "asks": len(p.get("asks") or []),
            "actions": ["open_plan", "approve"] if status == "waiting" else ["open_plan"],
            "last_activity": p.get("at") or "", "listening": beat,
        })
    return out


def join(seat_list: list[dict[str, Any]], extra: list[dict[str, Any]],
         beat: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The table's seats with the hub's: a seat that runs elsewhere gets ``listening`` (and its plan's actions
    if it had none); a hub seat the table didn't make is added. Order kept; new seats at the end."""
    by_id = {s["id"]: s for s in seat_list}
    if beat is None:
        beat = next((e["listening"] for e in extra if e.get("listening")), None)
    for s in seat_list:
        if s.get("where") == "elsewhere" and beat is not None:
            s.setdefault("listening", beat)
    for e in extra:
        s = by_id.get(e["id"])
        if s is None:
            seat_list.append({**e, "open_todos": 0, "high": 0, "owner_high": 0, "unread": 0, "repo": "",
                              "description": ""})
            by_id[e["id"]] = seat_list[-1]
            continue
        if s.get("where") == "elsewhere":
            s["listening"] = e.get("listening") or s.get("listening")
            s.setdefault("hub_name", e["hub_name"])
            s.setdefault("hub_agent", e["hub_agent"])
            if not s.get("actions"):
                s["actions"] = list(e["actions"])
    return seat_list


def _waiting(hub, agent: str, me: str, subject: str, cmd: dict[str, Any]) -> bool:
    """The same command from this app is already in that project's inbox, unread."""
    try:
        msgs = hub.inbox(agent, unread_only=True, limit=200)
    except Exception:  # noqa: BLE001
        return False
    for m in msgs:
        if (me and m.get("sender") not in (me, None)) or m.get("subject") != subject:
            continue
        try:
            body = json.loads(m.get("body") or "{}")
        except ValueError:
            continue
        if body == cmd:
            return True
    return False


def send_once(app, agent: str, folder: str, action: str, fields: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send a command to a project elsewhere through the hub, once: {sent, reply, listening}.

    Uses the app's own ``hub_command`` (its checks and its wording); a second tap while the first still waits
    unread sends nothing more and says so."""
    from .remote import FOLDER, PREFIX

    hub = getattr(app, "hub", None)
    beat = listening(app)
    cmd = {"action": action, **{k: v for k, v in (fields or {}).items() if k not in ("action", FOLDER)}}
    if folder and folder != agent:
        cmd[FOLDER] = folder
    me = getattr(app, "agent", "") or ""
    if hub and _waiting(hub, agent, me, f"{PREFIX} {action}", cmd):
        return {"sent": False, "listening": beat,
                "reply": "Already sent: it's waiting there. " + beat["words"]}
    got = app.hub_command({"agent": agent, "folder": folder, "action": action, "fields": fields or {}})
    reply = str(got.get("reply") or "Sent.")
    if beat["stale"]:
        reply = "Sent, but nothing is listening there right now. " + beat["words"]
    else:
        reply += " " + beat["words"]
    return {"sent": True, "listening": beat, "reply": reply}
