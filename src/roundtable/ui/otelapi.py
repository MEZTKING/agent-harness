"""The run timelines and the coding helpers' telemetry (otel.py), as an API. On the PC only.

    GET  /api/otel                 -> {traces, receiver: {on, running, port, endpoint, error}, collector,
                                       warning, helpers, words}
    POST /api/otel {traces?, receiver?, receiver_port?, collector?, collector_warned?} -> the same.
                                      A collector's address needs ``collector_warned: true`` (the owner ticked
                                      "task names and timings will go to that address"); "" takes it away.
    GET  /api/otel/traces ?path=   -> {traces: [{id, name, task, start_ms, ms, spans, ok}], words}
    GET  /api/otel/trace ?id=      -> {id, ms, spans: [{id, parent, name, offset_ms, ms, depth, ok, error, attrs}]}

The receiver is started by :func:`start` (a hook-up line at the app's start) and whenever it is switched on.
"""

from __future__ import annotations

from typing import Any

from .. import otel
from .countsapi import home_of


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/otel"): lambda q: view(app),
        ("POST", "/api/otel"): lambda body: change(app, body or {}),
        ("GET", "/api/otel/traces"): lambda q: list_traces(app, q or {}),
        ("GET", "/api/otel/trace"): lambda q: one(app, q or {}),
    }


def _arg(q, name: str) -> str:
    v = q.get(name, "")
    if isinstance(v, list):
        v = v[0] if v else ""
    return str(v or "")


def receiver(app) -> otel.Receiver:
    r = getattr(app, "_otel_receiver", None)
    if r is None:
        r = app._otel_receiver = otel.Receiver(home_of(app))
    return r


def start(app) -> None:
    """At the app's start: the receiver listens if the owner turned it on. Never fails the start."""
    try:
        receiver(app).start()
    except Exception:  # noqa: BLE001
        pass


def view(app) -> dict[str, Any]:
    home = home_of(app)
    s = otel.settings(home)
    r = receiver(app)
    st = r.status()
    words = ("A timeline of each run is kept on this computer." if s["traces"]
             else "Timelines are off. Turn them on to see how long each step of a run took.")
    return {"traces": s["traces"], "collector": s["collector"], "warning": otel.WARNING,
            "receiver": {"on": s["receiver"], **st, "wanted_port": s["receiver_port"]},
            "helpers": otel.helper_settings(st["port"] or s["receiver_port"]), "words": words,
            "note": "Nothing leaves this computer unless you type a collector's address below."}


def change(app, body: dict[str, Any]) -> dict[str, Any]:
    home = home_of(app)
    kw: dict[str, Any] = {}
    for k in ("traces", "receiver"):
        if k in body:
            kw[k] = bool(body[k])
    if "receiver_port" in body:
        try:
            kw["receiver_port"] = int(body["receiver_port"])
        except (TypeError, ValueError):
            raise ValueError("Choose a port between 1024 and 65535.") from None
    if "collector" in body:
        kw["collector"] = str(body.get("collector") or "")
        kw["collector_warned"] = bool(body.get("collector_warned"))
    s = otel.save(home, **kw)
    r = receiver(app)
    if not s["receiver"] or ("receiver_port" in kw and r.port != kw["receiver_port"]):
        r.stop()
    if s["receiver"]:
        r.start()
    return view(app)


def list_traces(app, q) -> dict[str, Any]:
    pid = ""
    path = _arg(q, "path")
    if path:
        from ..harness.usage import project_id

        cfg = app.cfg()
        pid = project_id(app.project(cfg, path).root) if cfg else ""
    rows = otel.traces(home_of(app), project=pid)
    return {"traces": rows, "words": (f"{len(rows)} recent run{'s' if len(rows) != 1 else ''}." if rows
                                      else "No timelines yet." if otel.enabled(home_of(app))
                                      else "Timelines are off (Settings → Advanced).")}


def one(app, q) -> dict[str, Any]:
    tid = _arg(q, "id")
    if not tid:
        raise ValueError("Choose a run first.")
    return otel.trace(home_of(app), tid)
