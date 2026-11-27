"""What the harness learned, in plain words, with an undo on each line (improve/ledger.py).

    GET  /api/learned        -> ledger.view: {lines, waiting, not_here, never, wallet, counts, share}
    POST /api/learned        {action: undo | put_back | apply | turn_down, id} -> {ok, ..., the view again}
    POST /api/learned/undo   {id} -> the same as action undo (the one change the phone may make)

The phone may only undo: a body the phone server marks ``_via: "phone"`` is refused anything else, and the
phone's route list need only allow ``/api/learned/undo``.
"""

from __future__ import annotations

from typing import Any


def routes(app) -> dict[tuple[str, str], Any]:
    return {("GET", "/api/learned"): lambda q: listing(app, q),
            ("POST", "/api/learned"): lambda body: action(app, body),
            ("POST", "/api/learned/undo"): lambda body: action(app, {**(body or {}), "action": "undo"})}


def _lab(app):
    cfg = app.need_cfg()
    return cfg, app.lab(cfg)


def listing(app, q=None) -> dict[str, Any]:
    from ..improve import ledger

    cfg, lab = _lab(app)
    return ledger.view(cfg, lab)


def action(app, body: dict[str, Any]) -> dict[str, Any]:
    from ..improve import ledger

    body = dict(body or {})
    via = "phone" if str(body.pop("_via", "") or "") == "phone" else "pc"
    cfg, lab = _lab(app)
    lock = getattr(app, "hub_lock", None)
    if lock is None:
        return ledger.act(cfg, lab, body, via=via)
    with lock:  # sharing (share.tick) rebuilds the same files under this lock
        return ledger.act(cfg, lab, body, via=via)
