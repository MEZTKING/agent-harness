"""The office (office.py) and its art (officeart.py) as an API, for the desktop's office.js.

    GET  /api/office            the scene: {rooms, actors, art, more, words}; read only, no model (rides the Hall's refresh)
    GET  /api/office/art        {art, pieces: {id: {url, kind, sheet, draw}}, room, props, spots, actor, agents, bubbles}
    GET  /api/office/status     {spent, cap, approved, stopped, sample: {...} | null, ask: card | null, words}
    POST /api/office/quote      {} -> the quote (Retro Diffusion's price check: spends nothing)
    POST /api/office/answer     {choice: "rest" | "again" | "stop", confirm} -> the sample card's answer; the paid
                                choices need confirm: true and run as a background job (PC only)
    POST /api/office/remake     {id, confirm} -> one piece made again: the price first, made with confirm (PC only)

None of these is offered to the phone: the paid ones spend, and the office on the phone is later work.
"""

from __future__ import annotations

from typing import Any

from .. import office, officeart


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/office"): lambda q: office.scene(app),
        ("GET", "/api/office/art"): lambda q: officeart.pictures(app),
        ("GET", "/api/office/status"): lambda q: status(app),
        ("POST", "/api/office/quote"): lambda b: quote(app),
        ("POST", "/api/office/answer"): lambda b: answer(app, b or {}),
        ("POST", "/api/office/remake"): lambda b: remake(app, b or {}),
    }


def _provider(app):
    from .server import ApiError

    p = officeart.provider_for(app.need_cfg())
    if p is None:
        raise ApiError("Retro Diffusion isn't set up yet, so the office art can't be made. Add its key in Models, "
                       "then try again.", 503)
    return p


def status(app) -> dict[str, Any]:
    out, spent_file = officeart.paths(app)
    st = officeart.state(spent_file)
    spent = officeart.spent(spent_file)
    sample = st.get("sample") or None
    if st.get("approved") and st.get("rest"):
        words = f"The office art is made. ${spent:.2f} of ${officeart.CAP_USD:.2f} spent."
    elif st.get("approved"):
        words = "You said yes to the sample: the rest is being made, or waits to be."
    elif st.get("stopped"):
        words = "You stopped after the sample. Nothing more is made."
    elif sample:
        words = "The sample sheet is ready for you to look at."
    else:
        words = "No office art yet: the Ring stays on Home."
    return {"spent": spent, "cap": officeart.CAP_USD, "approved": bool(st.get("approved")),
            "stopped": bool(st.get("stopped")), "sample": sample, "ask": officeart.sample_ask(app), "words": words,
            "art": officeart.ready(app)}


def quote(app) -> dict[str, Any]:
    return officeart.quote(_provider(app))


def _job(app, kind: str, title: str, fn):
    jobs = getattr(app, "jobs", None)
    if jobs is None:  # a bare app (tests): now
        return {"done": True, **fn(None)}
    return {"done": False, "job": jobs.start(kind, title, fn).view()}


def answer(app, body: dict[str, Any]) -> dict[str, Any]:
    from .server import ApiError

    choice = str(body.get("choice") or "")
    out, spent_file = officeart.paths(app)
    if choice == "stop":
        officeart.stop(spent_file)
        return {"reply": "Stopped. Nothing more is made; the Ring stays on Home."}
    if choice not in ("rest", "again"):
        raise ApiError('Say what to do: "rest", "again" or "stop".')
    if body.get("confirm") is not True:  # it spends: only with the owner's confirmed tap
        ask = officeart.sample_ask(app)
        return {"done": False, "ask": ask, "reply": "This spends Retro Diffusion credit: confirm it first."}
    provider = _provider(app)
    try:
        if choice == "rest":
            officeart.approve(spent_file)
    except officeart.OfficeArtError as e:
        raise ApiError(str(e)) from e
    stage = "rest" if choice == "rest" else "sample"

    def run(job):
        res = officeart.make(provider, stage, out, spent_file)
        if job is not None:
            job.line(res["words"])
        return res

    try:
        return {**_job(app, "office_art", "the office art" if stage == "rest" else "the office's sample again", run),
                "reply": "Making the rest of the office. It takes a few minutes." if stage == "rest"
                else "Making the sample again. It takes a minute or two."}
    except officeart.OfficeArtError as e:
        raise ApiError(str(e)) from e


def remake(app, body: dict[str, Any]) -> dict[str, Any]:
    from .server import ApiError

    out, spent_file = officeart.paths(app)
    pid = str(body.get("id") or "")
    provider = _provider(app)
    try:
        if body.get("confirm") is not True:
            return officeart.remake(provider, pid, out, spent_file, confirm=False)
        return _job(app, "office_art", f"the office piece {pid} again",
                    lambda job: officeart.remake(provider, pid, out, spent_file, confirm=True))
    except officeart.OfficeArtError as e:
        raise ApiError(str(e)) from e
