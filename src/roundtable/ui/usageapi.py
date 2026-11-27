"""What each service and job may use, what's left, and who has seen a project (harness/usage.py), as an API.

    GET  /api/usage           ?balance=1 also asks the services that report one for the real balance (kept
                              five minutes) -> {services: [{id, name, used, caps, left, subscription, balance,
                              reached, words, balance_words, unpriced_words}], jobs: [{role, name, caps}], words,
                              note, fields}
    POST /api/usage/limits    {services?: {id: {usd_per_day?, usd_per_month?, tokens_per_day?}},
                               jobs?: {role: {tokens_per_project?, usd_per_project?}}} -> the same as GET.
                              0 takes a limit away. Kept in custom.yaml (harness.yaml is never rewritten).
                              On the PC only: the phone's server never routes it (phone.PHONE_ROUTES).
    GET  /api/usage/seen      ?path=<project> -> {makers: [{maker, maker_name, service, service_name, first,
                              last, calls}], words, note}

Only numbers and names leave here: never what was sent to a model, never a key.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..harness import usage

BALANCE_KEEP_S = 300


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/usage"): lambda q: view(app, q or {}),
        ("POST", "/api/usage/limits"): lambda body: change(app, body or {}),
        ("GET", "/api/usage/seen"): lambda q: seen(app, q or {}),
    }


def _arg(q, name: str) -> str:
    v = q.get(name)
    if isinstance(v, list):
        v = v[0] if v else ""
    return str(v or "")


def _cfg(app):
    try:
        return app.cfg()
    except Exception:  # noqa: BLE001 - no settings yet
        return None


def _home(app) -> Path | None:
    fn = getattr(app, "_backup_home", None)
    try:
        return Path(fn()) if callable(fn) else None
    except Exception:  # noqa: BLE001 - the default home then
        return None


def _balances(app, cfg) -> dict[str, Any]:
    have = getattr(app, "_usage_balances", None)
    if have and time.time() - have[0] < BALANCE_KEEP_S:
        return have[1]
    from ..providers import balance

    try:
        got = balance.balances(cfg) if cfg is not None else {}
    except Exception:  # noqa: BLE001 - a service that can't be asked just shows no balance
        got = {}
    app._usage_balances = (time.time(), got)
    return got


def view(app, q) -> dict[str, Any]:
    cfg = _cfg(app)
    bal = _balances(app, cfg) if _arg(q, "balance") in ("1", "true", "yes") else None
    out = usage.view(cfg, _home(app), bal)
    out["fields"] = {"services": list(usage.SERVICE_FIELDS), "jobs": list(usage.JOB_FIELDS)}
    return out


def change(app, body: dict[str, Any]) -> dict[str, Any]:
    from .server import ApiError

    cfg = _cfg(app)
    p = getattr(cfg, "path", None) or getattr(app, "harness_config_path", None)
    path = Path(p) if p else None
    if not path or not path.is_file():
        raise ApiError("The harness's settings aren't set up on this computer yet. Run the set-up in Settings first.",
                       503)
    body = {k: body[k] for k in ("services", "jobs") if k in body}
    try:
        usage.save_limits(path, body)
    except ValueError as e:
        raise ApiError(f"Nothing was changed: {e}.") from None
    return view(app, {})


def seen(app, q) -> dict[str, Any]:
    proj = app.project(app.need_cfg(), _arg(q, "path"))
    return usage.seen_view(proj.root, _home(app))
