"""The proof run in the app (proofrun.py): one card, "Prove it", that plans a small game, shows its price and
builds it only after a yes.

    GET  /api/proofrun           -> the report (proofrun.report) of the app's own lab, plus {about, busy, lab}
    POST /api/proofrun/start     {confirm?, art?, sound?} -> without confirm: {confirm: true, question} (nothing
                                 made); with confirm: a background job that makes the lab, prices the pictures
                                 and sound, plans it and stops at the estimate (spends a few cents of planning)
    POST /api/proofrun/build     {confirm?} -> without confirm: {confirm: true, question} with the estimate; with
                                 confirm: a background job that builds it (spends, at most the caps)
    POST /api/proofrun/new       {confirm?} -> put the last proof run aside (renamed, never deleted) for a new one

On the PC only: these spend the owner's money, so the phone's server never routes the POSTs (phone.PHONE_ROUTES
may list the GET: it reads numbers and plain sentences only).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .. import proofrun

JOB_KIND = "proofrun"


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/proofrun"): lambda q: view(app),
        ("POST", "/api/proofrun/start"): lambda body: start(app, body or {}),
        ("POST", "/api/proofrun/build"): lambda body: build(app, body or {}),
        ("POST", "/api/proofrun/new"): lambda body: fresh(app, body or {}),
    }


def lab_of(app) -> Path:
    """The app's own proof-run folder (a test may set ``app.proofrun_lab``)."""
    return Path(getattr(app, "proofrun_lab", None) or proofrun.default_lab())


def _busy(app) -> bool:
    lab = str(lab_of(app))
    return any(j.target == lab and j.status == "running" for j in app.jobs.jobs.values())


def _real_cfg(app):
    try:
        return app.cfg()
    except Exception:  # noqa: BLE001 - no settings of its own: no journal line
        return None


def view(app) -> dict[str, Any]:
    lab = lab_of(app)
    rep = proofrun.report(lab)
    return {**rep, "about": proofrun.ABOUT, "busy": _busy(app), "lab": str(lab)}


def _printer(job):
    from .server import harness_event_line

    def ev(kind: str, data: dict[str, Any]) -> None:
        line = harness_event_line(kind, data)
        if line:
            job.line(line)
    return ev


def start(app, body: dict[str, Any]) -> dict[str, Any]:
    from .server import ApiError

    if _busy(app):
        raise ApiError("The proof run is already going. Wait for it to finish (Activity → Background work).", 409)
    lab = lab_of(app)
    state = proofrun.read_state(lab)
    if state and state.get("phase") != "prepared":
        raise ApiError("There's already a proof run. Read its report, or put it aside to start a new one.", 409)
    art, sound = body.get("art", True) is not False, body.get("sound", True) is not False
    caps = proofrun.checked_caps(state.get("caps") if state else proofrun.caps_for(art=art, sound=sound))
    if not body.get("confirm"):
        return {"confirm": True, "question": (
            f"Plan a small game from one idea? Planning costs a few cents. You'll see the price before anything is "
            f"built; building is about $1 and stops at {proofrun._usd(caps['total_usd'])}.")}

    def run(job):
        if not proofrun.read_state(lab):
            proofrun.prepare(lab, proofrun.default_idea(), caps)
        job.line("Pricing the pictures and the sound, then planning…")
        got = proofrun.plan_phase(lab, on_event=_printer(job))
        job.line(got["words"])
        return {"go": got["go"], "words": got["words"]}

    return {"job": app.jobs.start(JOB_KIND, "the proof run: plan", run, target=str(lab)).view()}


def build(app, body: dict[str, Any]) -> dict[str, Any]:
    from .server import ApiError

    if _busy(app):
        raise ApiError("The proof run is already going. Wait for it to finish (Activity → Background work).", 409)
    lab = lab_of(app)
    state = proofrun.read_state(lab)
    if state.get("phase") != "estimated":
        raise ApiError("There's no priced plan waiting. Press Start first.", 409)
    est = state.get("estimate") or {}
    caps = state.get("caps") or {}
    if not body.get("confirm"):
        return {"confirm": True, "question": (
            f"Build it now? The plan is about {proofrun._usd(est.get('total_usd'))}; it stops at "
            f"{proofrun._usd(caps.get('total_usd'))} whatever happens.")}
    real = _real_cfg(app)

    def run(job):
        job.line("Building: autopilot approves the plan and runs it…")
        rep = proofrun.build_phase(lab, on_event=_printer(job), real_hub=real)
        job.line(rep.get("words", ""))
        return {"words": rep.get("words", "")}

    return {"job": app.jobs.start(JOB_KIND, "the proof run: build", run, target=str(lab)).view()}


def fresh(app, body: dict[str, Any]) -> dict[str, Any]:
    from .server import ApiError

    if _busy(app):
        raise ApiError("The proof run is still going. Wait for it to finish first.", 409)
    lab = lab_of(app)
    if not lab.exists():
        return {"reply": "There's no proof run to put aside."}
    if not body.get("confirm"):
        return {"confirm": True, "question": "Put the last proof run aside and start a new one? Its folder is kept, "
                                             "renamed with today's date."}
    aside = lab.with_name(f"{lab.name}-{time.strftime('%Y%m%d-%H%M%S')}")
    lab.rename(aside)
    return {"reply": f"Put aside in {aside.name}.", "aside": str(aside)}
