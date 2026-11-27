"""The plug-in and skill list, making a plug-in, and skills, as an API (plugins/market.py, plugins/make.py,
skills.py), for the desktop's market.js. PC only: the phone reads GET /api/market and nothing else.

    GET  /api/market      {plugins: [...], skills: [...], updates: [...], words, from, updated, refreshed_at}
    POST /api/market      {"action": ...}
        install {id, confirmed: [permissions] | true}   a reply {ok: false, needs_ok: {...}} means: show it, ask,
                                                         and send it again with "confirmed"
        remove {id}                                      moved aside, never deleted
        refresh                                          reads the newer list (only shown)
        make {idea}                                      {ok, price}: the price first
        make {idea, go: true}                            {ok, job}: the plug-in is made in a job (the job's result is
                                                         make.draft's dict)
        add_made {folder, confirmed: [permissions]}      "Add it" for a made plug-in that passed
        skill_add {file | text, name}                    {ok: false, needs_ok: {skill: {..., text}, digest}}
        skill_add {file | text, name, digest}            adds it, only if the text is still the one shown
        skill_switch {id, on}
        skill_remove {id}
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any

from .. import skills as skilllib
from ..plugins import make, market
from ..plugins.api import PluginError

MAKE_MOST_USD = 1.0  # the made plug-in's own cap when its model has no price


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/market"): lambda q: _wrap(lambda: market.view(_harness(app))),
        ("POST", "/api/market"): lambda b: _wrap(lambda: action(app, b or {})),
    }


def _harness(app) -> Any:
    return getattr(app, "harness_config_path", None)


def _wrap(fn):
    from .server import ApiError

    try:
        return fn()
    except (PluginError, skilllib.SkillError, ValueError, FileNotFoundError) as e:
        raise ApiError(str(e)) from None


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def action(app, body: dict[str, Any]) -> dict[str, Any]:
    from ..plugins import manage
    from ..plugins.manage import NeedsOk

    act, eid = body.get("action"), str(body.get("id") or "")
    confirmed = body.get("confirmed")
    asked: dict[str, Any] = {}

    def ok(thing: Any) -> bool:
        if isinstance(thing, skilllib.Skill):
            asked["skill"] = thing
            return confirmed is True or body.get("digest") == _digest(thing.text)
        perms = set(getattr(thing, "permissions", []) or [])
        return confirmed is True and not perms or isinstance(confirmed, list) and perms <= set(confirmed)

    try:
        if act == "install":
            return {"ok": True, **market.install(eid, ok, harness_path=_harness(app))}
        if act == "remove":
            return {"ok": True, **market.remove(eid, harness_path=_harness(app))}
        if act == "refresh":
            got = market.refresh()
            return {"ok": True, "entries": len(got["entries"]), "words": "The list is up to date. Nothing was added."}
        if act == "make":
            return _make(app, body)
        if act == "add_made":
            folder = str(body.get("folder") or "")
            if not make.is_draft(folder):
                raise PluginError("Only a plug-in made here can be added this way.")
            probs = make.check(Path(folder))
            if probs:
                raise PluginError("It can't be added: " + " ".join(probs[:3]))
            return {"ok": True, "added": manage.add_plugin(_harness(app), folder, ok)}
        if act == "skill_add":
            with tempfile.TemporaryDirectory(prefix="skill-") as t:
                src = _skill_source(body, Path(t))
                s = skilllib.preview(src)
                if body.get("digest") != _digest(s.text):
                    return {"ok": False, "needs_ok": {"skill": s.view(full=True), "digest": _digest(s.text)},
                            "message": f"Read {s.name} first: this is everything it would add."}
                return {"ok": True, "added": skilllib.add(src, ok).view()}
        if act == "skill_switch":
            return {"ok": True, **skilllib.switch(eid, body.get("on", True) is not False)}
        if act == "skill_remove":
            return {"ok": True, **market.remove(eid, harness_path=_harness(app))}
    except NeedsOk as e:
        return {"ok": False, "needs_ok": e.manifest.view(),
                "message": f"{e.manifest.name} asks for: " + (", ".join(
                    p["words"] for p in e.manifest.view()["permissions"]) or "nothing special")}
    except skilllib.SkillError:
        if "skill" in asked:
            s = asked["skill"]
            return {"ok": False, "needs_ok": {"skill": s.view(full=True), "digest": _digest(s.text)},
                    "message": f"Read {s.name} first: this is everything it would add."}
        raise
    raise PluginError("action must be install, remove, refresh, make, add_made, skill_add, skill_switch or "
                      "skill_remove")


def _skill_source(body: dict[str, Any], tmp: Path) -> str:
    """A skill file on this computer: its path (``file``), or the text of a file the owner chose in the app
    (``text``, with the file's ``name``). Never a web link."""
    if body.get("text") is not None:
        text = str(body["text"])
        if len(text) > skilllib.MAX_CHARS * 4:
            raise skilllib.SkillError(f"That file is too big for a skill (up to {skilllib.MAX_CHARS:,} characters).")
        stem = Path(str(body.get("name") or "")).stem.lower()
        folder = tmp / (stem if skilllib.ID_RE.match(stem) and stem != "skill" else "_")  # "_": the id comes from its name
        folder.mkdir()
        (folder / skilllib.SKILL_FILE).write_text(text, encoding="utf-8")
        return str(folder)
    return str(body.get("file") or "")


def _make(app, body: dict[str, Any]) -> dict[str, Any]:
    from ..harness.agent import Budget

    cfg = app.need_cfg()
    idea = " ".join(str(body.get("idea") or "").split())
    if len(idea) < 8:
        raise PluginError("Say in a sentence what the tool should do.")
    price = make.estimate(cfg)
    if not body.get("go"):
        return {"ok": True, "price": price}
    # the owner's own tap: their money, capped at twice the price shown (the run stops there)
    limit = max(0.05, 2 * price["usd"]) if price["usd"] else MAKE_MOST_USD

    def run(job):
        def on_event(kind, data):
            if kind == "make_plugin":
                job.line({"writing": "Writing the plug-in…", "testing": "Running its tests in the box…",
                          "done": "Finished."}.get(data.get("step"), str(data.get("step"))))

        return make.draft(cfg, idea, Budget(limit_usd=limit), on_event=on_event)

    job = app.jobs.start("make-plugin", f"Making a plug-in: {idea[:60]}", run)
    return {"ok": True, "price": price, "job": job.view()}
