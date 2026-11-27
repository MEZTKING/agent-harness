"""Learning's own weekly money (improve/wallet.py), as an API.

    GET  /api/learning/wallet     {allowance, spent, spent_here, spent_elsewhere, left, week, lines: [{at, what,
                                   proposal, usd, machine}], by_what, next_run, on, choices, words, day_limit}
    POST /api/learning/allowance  {usd, confirm?} -> without confirm: {confirm: true, question, usd} (nothing
                                  changed); with confirm the figure is kept in custom.yaml and the same as GET.
                                  On the PC only: the phone's server never routes it (phone.PHONE_ROUTES).

Numbers only: never a prompt, a task or a project's name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..brand import NAME


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/learning/wallet"): lambda q: view(app),
        ("POST", "/api/learning/allowance"): lambda body: set_allowance(app, body or {}),
    }


def _cfg(app):
    try:
        return app.cfg()
    except Exception:  # noqa: BLE001 - no settings yet
        return None


def _lab(cfg):
    if cfg is None or not getattr(cfg, "lab_dir", None):
        return None
    from ..improve.lab import Lab

    return Lab(cfg.lab_dir)


def view(app) -> dict[str, Any]:
    from ..improve import wallet

    cfg = _cfg(app)
    if cfg is None:
        return {"allowance": 0.0, "spent": 0.0, "left": 0.0, "week": wallet.week_of(), "lines": [], "next_run": None,
                "on": False, "choices": list(wallet.CHOICES), "words": "Learning by itself is off",
                "by_what": {}, "spent_here": 0.0, "spent_elsewhere": 0.0, "day_limit": 0.0}
    return wallet.view(cfg, _lab(cfg))


def question(usd: float) -> str:
    from ..improve.wallet import money

    if usd <= 0:
        return f"Switch learning by itself off? {NAME} stops spending on learning; what it learned stays."
    return (f"Let {NAME} spend up to {money(usd)} a week on learning by itself? It tests ideas for better "
            "model choices and applies the safe ones; anything bigger waits for you. Unused money doesn't "
            "carry over, and it counts inside your daily limit.")


def set_allowance(app, body: dict[str, Any]) -> dict[str, Any]:
    from ..improve import wallet
    from .server import ApiError

    try:
        usd = wallet.clean_allowance(body.get("usd"))
    except ValueError as e:
        raise ApiError(f"Nothing was changed: {e}.") from None
    if not body.get("confirm"):
        return {"confirm": True, "question": question(usd), "usd": usd}
    cfg = _cfg(app)
    p = getattr(cfg, "path", None) or getattr(app, "harness_config_path", None)
    path = Path(p) if p else None
    if not path or not path.is_file():
        raise ApiError("The harness's settings aren't set up on this computer yet. Run the set-up in Settings first.",
                       503)
    wallet.save_allowance(path, usd)
    return view(app)
