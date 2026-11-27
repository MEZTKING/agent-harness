"""Kinds and the Gallery as an API (kinds/, harness/kindstage.py), for the desktop's kinds.js and gallery.js and
the phone's Gallery screen.

    GET  /api/kinds                   {groups: [{group, kinds: [card]}], extras: [...], problems: [...]}
    GET  /api/kinds/one?id=K[&extras=a,b] | ?path=P     one kind's card (with More), or a project's kind card
    POST /api/kinds/propose {goal}    {choices: [{id, name, score, why}], extras: [...]}   free: no model call
    POST /api/kinds/set {path, id, extras?}   confirm or change a project's kind before approval; with a plan,
                                       a change re-plans in a job -> {kind, reply, job?}
    POST /api/kinds/newest {path}     "Use the newest recipe" for a project already frozen
    GET  /api/kinds/export?id=K       {name: "K.rtkind", data: base64}          (PC only)
    POST /api/kinds/import {data, confirm}   what it would switch on; installs only with confirm (PC only)

    GET  /api/gallery[?hidden=1]      {entries: [tile], words}
    GET  /api/gallery/one?project&goal    the record with its pictures (data URLs) and proof lines
    POST /api/gallery/hide {project, goal, hidden?}   never deletes
    POST /api/gallery/star {project, goal, starred?}
    POST /api/gallery/again {project, goal}           the wizard filled in: kind, extras, model set
"""

from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import Any

from .. import kinds as kindlib
from ..kinds import gallery as gallerylib


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/kinds"): lambda q: _wrap(lambda: catalog(app)),
        ("GET", "/api/kinds/one"): lambda q: _wrap(lambda: one_kind(app, q)),
        ("POST", "/api/kinds/propose"): lambda b: _wrap(lambda: propose(app, b)),
        ("POST", "/api/kinds/set"): lambda b: _wrap(lambda: set_kind(app, b)),
        ("POST", "/api/kinds/newest"): lambda b: _wrap(lambda: _orch(app, b.get("path")).kind_use_newest()),
        ("GET", "/api/kinds/export"): lambda q: _wrap(lambda: export(app, q)),
        ("POST", "/api/kinds/import"): lambda b: _wrap(lambda: import_kind(app, b)),
        ("GET", "/api/gallery"): lambda q: _wrap(lambda: gallery(app, q)),
        ("GET", "/api/gallery/one"): lambda q: _wrap(lambda: gallerylib.one(_home(app), _first(q, "project"),
                                                                           _first(q, "goal"))),
        ("POST", "/api/gallery/hide"): lambda b: _wrap(lambda: gallerylib.hide(
            _home(app), str(b.get("project") or ""), str(b.get("goal") or ""), b.get("hidden", True) is not False)),
        ("POST", "/api/gallery/star"): lambda b: _wrap(lambda: gallerylib.star(
            _home(app), str(b.get("project") or ""), str(b.get("goal") or ""), b.get("starred", True) is not False)),
        ("POST", "/api/gallery/again"): lambda b: _wrap(lambda: gallerylib.again(
            _home(app), str(b.get("project") or ""), str(b.get("goal") or ""))),
    }


def _first(q: dict, key: str) -> str:
    v = q.get(key) or [""]
    return str(v[0] if isinstance(v, list) else v)


def _wrap(fn):
    from ..harness.orchestrator import HarnessError
    from .server import ApiError

    try:
        return fn()
    except (kindlib.KindError, gallerylib.GalleryError, HarnessError) as e:
        raise ApiError(str(e)) from None


def _home(app) -> Path:
    return Path(app._backup_home())


def tools() -> tuple[dict[str, str], set[str]]:
    """The tools' names and the ones missing on this computer (prereq.py; cached there)."""
    try:
        from .. import prereq

        rows = prereq.status(versions=False)
        return {r["id"]: r["name"] for r in rows}, {r["id"] for r in rows if r.get("state") not in ("found", "old")}
    except Exception:  # noqa: BLE001 - without the check nothing is shown as missing
        return {}, set()


def _card(k: kindlib.Kind, state, names, missing) -> dict[str, Any]:
    return kindlib.card(k, state, sorted(missing), names)


def catalog(app) -> dict[str, Any]:
    home = _home(app)
    cat = kindlib.load_all(home)
    state = kindlib.read_state(home)
    names, missing = tools()
    groups: dict[str, list] = {}
    order = {g: i for i, g in enumerate(kindlib.model.GROUPS)}
    for k in sorted(cat.kinds.values(), key=lambda k: (order.get(k.group, 99), not k.usable, k.name)):
        try:
            rk = kindlib.resolve(k.id, catalog=cat)
        except kindlib.KindError:
            continue
        groups.setdefault(k.group, []).append(_card(rk, state, names, missing))
    return {"groups": [{"group": g, "kinds": ks} for g, ks in groups.items()],
            "extras": [kindlib.model.extra_card(e) for e in cat.extras.values()],
            "problems": cat.problems,
            "words": "What the harness can make. “On trial” means nothing built with it has passed its proof yet."}


def one_kind(app, q: dict) -> dict[str, Any]:
    if _first(q, "path"):
        orch = _orch(app, _first(q, "path"))
        doc = orch._kind_doc()
        if not doc:
            return {"kind": None, "reply": "This project has no kind yet."}
        return {"kind": doc}
    home = _home(app)
    extras = [x for x in _first(q, "extras").split(",") if x]
    from ..improve import toolkind  # with the learned kind tweak on top, as a project sees it

    k = toolkind.resolve_with_tweaks(_first(q, "id"), extras, home=home)
    names, missing = tools()
    return _card(k, kindlib.read_state(home), names, missing)


def propose(app, b: dict[str, Any]) -> dict[str, Any]:
    goal = str(b.get("goal") or "").strip()
    if not goal:
        return {"choices": [], "extras": []}
    cat = kindlib.load_all(_home(app))
    choices = kindlib.propose(goal, cat)
    top = choices[0][0] if choices else "other"
    return {"choices": [{"id": i, "name": cat.kinds[i].name if i != "other" else "Something else", "score": s,
                         "why": w} for i, s, w in choices[:4]],
            "extras": kindlib.propose_extras(goal, top, cat)}


def _orch(app, path):
    from ..harness.orchestrator import HarnessError, Orchestrator

    proj = app.project(app.need_cfg(), str(path or ""))
    if not proj.exists:
        raise HarnessError("There's no project there.")
    return Orchestrator(app.need_cfg(), proj.root)


def set_kind(app, b: dict[str, Any]) -> dict[str, Any]:
    from .server import ApiError

    path, kid = str(b.get("path") or ""), str(b.get("id") or "")
    extras = b.get("extras")
    extras = [str(x) for x in extras] if isinstance(extras, list) else None
    orch = _orch(app, path)
    old = (orch.project.meta() or {}).get("kind") or {}
    changed = old.get("id") != kid or (extras is not None and sorted(extras) != sorted(old.get("extras") or []))
    if not (orch.project.plan_doc() and changed):
        return orch.set_kind(kid, extras, by=str(b.get("by") or "owner"))
    if app._busy(orch.project.root):
        raise ApiError("Wait for the job running on this project to finish, then try again.", 409)
    orch.set_kind(kid, extras, by=str(b.get("by") or "owner"), replan=False)  # checks it first, quickly
    cfg = app.need_cfg()

    def run(job):
        o = app._orch(cfg, orch.project.root, job)
        o.revise_plan(f"The owner says this is a {o._kind().name}. Re-plan it as one: follow "
                      "'What this project is' below.", by="owner")
        doc = o.project.plan_doc()
        if doc:
            doc["kind"] = o._kind_doc()
            o.project.save_plan_doc(doc)
            o._publish_plan()
        return {"kind": o._kind_doc()}

    job = app.jobs.start("plan", f"re-plan {orch.project.root.name}", run, target=str(orch.project.root)).view()
    return {"kind": orch._kind_doc(), "job": job, "reply": "Changed. The planner is making the plan again for it."}


def export(app, q: dict) -> dict[str, Any]:
    cat = kindlib.load_all(_home(app))
    kid = _first(q, "id")
    k = cat.kinds.get(kid) or cat.extras.get(kid)
    if not k:
        raise kindlib.KindError(f"there's no kind called {kid!r}")
    return {"name": f"{k.id}.rtkind", "data": base64.b64encode(kindlib.export(k)).decode()}


def import_kind(app, b: dict[str, Any]) -> dict[str, Any]:
    try:
        data = base64.b64decode(str(b.get("data") or ""), validate=True)
    except (binascii.Error, ValueError):
        raise kindlib.KindError("That file couldn't be read. Choose a .rtkind file again.") from None
    if len(data) > kindlib.model.MAX_TOTAL:
        raise kindlib.KindError("That file is too big for a kind (over 20 MB).")
    return kindlib.import_file(data, _home(app), confirm=b.get("confirm") is True)


def gallery(app, q: dict) -> dict[str, Any]:
    home = _home(app)
    rows = [gallerylib.summary(e) for e in gallerylib.entries(home, hidden=_first(q, "hidden") == "1")]
    return {"entries": rows,
            "words": "Everything finished, newest first." if rows else "Nothing finished yet. Finished projects show here."}
