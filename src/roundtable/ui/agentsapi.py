"""Named agents as an API (agents.py), for the desktop's agents.js and the phone.

    GET  /api/agents                    {agents: [card], jobs: [{job, name, words}], words}
    GET  /api/agents/one?id=A           one card with its notes, what it learned and its face's details
    POST /api/agents {id?, name, job, about, notes, traits, hire?}   make, change, rename or hire one
    POST /api/agents/remove {id}        moved to agents/.removed, never deleted
    POST /api/agents/face {id, confirm} the price first; with confirm the picture job makes it (PC only)
    GET  /api/agents/export?id=A[&memory=1][&preview=1]   {name, data: base64, files, memory} (PC only)
    POST /api/agents/import {data, confirm}   everything shown first; joins only with confirm (PC only)
"""

from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import Any

from .. import agents as agentlib

IMPORT_MAX = 1024 * 1024


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/agents"): lambda q: _wrap(lambda: listing(app)),
        ("GET", "/api/agents/one"): lambda q: _wrap(lambda: agentlib.card(
            _home(app), agentlib.get(_home(app), _first(q, "id")), full=True)),
        ("POST", "/api/agents"): lambda b: _wrap(lambda: save(app, b)),
        ("POST", "/api/agents/remove"): lambda b: _wrap(lambda: agentlib.remove(_home(app), str(b.get("id") or ""))),
        ("POST", "/api/agents/face"): lambda b: _wrap(lambda: face(app, b)),
        ("GET", "/api/agents/export"): lambda q: _wrap(lambda: export(app, q)),
        ("POST", "/api/agents/import"): lambda b: _wrap(lambda: import_agent(app, b)),
    }


def _first(q: dict, key: str) -> str:
    v = q.get(key) or [""]
    return str(v[0] if isinstance(v, list) else v)


def _wrap(fn):
    from .server import ApiError

    try:
        return fn()
    except agentlib.AgentError as e:
        raise ApiError(str(e)) from None


def _home(app) -> Path:
    return Path(app._backup_home())


def listing(app) -> dict[str, Any]:
    home = _home(app)
    rows = [agentlib.card(home, a) for a in agentlib.load_all(home)]
    hired = {r["job"] for r in rows if r["hired"]}
    jobs = [{"job": j, "name": n, "words": w, "hired": j in hired} for j, (n, w) in agentlib.JOBS.items()]
    return {"agents": rows, "jobs": jobs,
            "words": "Your team: one agent per job. Each keeps your notes and what it learns."}


def save(app, b: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "name", "job", "about", "notes", "traits", "hire")
    a = agentlib.save(_home(app), {k: b[k] for k in keys if k in b})
    return {"agent": agentlib.card(_home(app), a), "reply": f"Saved {a.name}."}


def face(app, b: dict[str, Any]) -> dict[str, Any]:
    home = _home(app)
    a = agentlib.get(home, str(b.get("id") or ""))
    cfg = app.need_cfg()
    price = agentlib.face_price(cfg, home)
    if b.get("confirm") is not True or not price["ok"]:
        return {"made": False, "price": price, "reply": price["words"]}
    jobs = getattr(app, "jobs", None)
    if jobs is None:  # no background jobs (tests, a bare app): make it now
        return {"made": True, **agentlib.make_face(cfg, a, home)}
    job = jobs.start("face", f"a face for {a.name}", lambda j: agentlib.make_face(cfg, a, home)).view()
    return {"made": False, "job": job, "reply": f"Making {a.name}'s face. It takes about a minute."}


def export(app, q: dict) -> dict[str, Any]:
    home = _home(app)
    a = agentlib.get(home, _first(q, "id"))
    with_memory = _first(q, "memory") == "1"
    look = agentlib.export_preview(home, a, with_memory)
    out = {"name": f"{a.id}{agentlib.FILE_SUFFIX}", "files": look["files"], "memory": look["memory"]}
    if _first(q, "preview") != "1":
        out["data"] = base64.b64encode(agentlib.export(home, a, with_memory)).decode()
    return out


def import_agent(app, b: dict[str, Any]) -> dict[str, Any]:
    try:
        data = base64.b64decode(str(b.get("data") or ""), validate=True)
    except (binascii.Error, ValueError):
        raise agentlib.AgentError("That file couldn't be read. Choose a .rtagent file again.") from None
    if len(data) > IMPORT_MAX:
        raise agentlib.AgentError("That file is too big for an agent (over 1 MB).")
    return agentlib.import_file(data, _home(app), confirm=b.get("confirm") is True)
