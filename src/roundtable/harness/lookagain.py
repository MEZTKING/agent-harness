"""The critic looks again (wave 9, w9-gaps).

A plan's critique is about the version it read. When a revision changes more than a third of the tasks (added,
changed or removed, counted against the tasks still to do before it), the critique is marked "about an earlier
version" and one new look is offered as a card, priced first. Autopilot answers the card by its own rules (the
"yes" carries no "Are you sure?", so it may pick it while the price fits its allowance); otherwise it waits for
the owner. Nothing here calls a model: ``apply`` asks the orchestrator's own ``_critique`` once.

The offer lives in ``.harness/look-again.json`` so it survives a restart and is made once per version.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SHARE = 1 / 3
OFFER_FILE = "look-again.json"
CRITIQUE_TOKENS = (25_000, 2_500)  # council.py's critique_tokens: what one look is priced at


def changed_share(diff: dict[str, Any], before: int) -> float:
    """How much of the plan a revision changed: (added + changed + removed) / the tasks to do before it."""
    moved = len(diff.get("added") or []) + len(diff.get("changed") or []) + len(diff.get("removed") or [])
    base = max(1, before)
    return moved / base


def price(cfg) -> float | None:
    """What one more look by the critic costs, or None when its model isn't priced."""
    from ..providers.base import Usage

    role = cfg.roles.get(getattr(cfg, "critic_role", "") or "")
    if not role:
        return None
    try:
        return cfg.cost(role.models[0], Usage(*CRITIQUE_TOKENS))
    except (ValueError, AttributeError):
        return None


def _offer_path(root: Path | str) -> Path:
    return Path(root) / ".harness" / OFFER_FILE


def read_offer(root: Path | str) -> dict[str, Any] | None:
    try:
        d = json.loads(_offer_path(root).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def mark(root: Path | str, doc: dict[str, Any], diff: dict[str, Any], before: int, cfg=None) -> bool:
    """After a revision: True (and the critique marked, the offer written) when a third or more changed.

    ``doc`` is the new plan document (saved by the caller); a plan with no critique, or one whose critique is
    already about this version, is left alone."""
    crit = doc.get("critique")
    if not isinstance(crit, dict) or changed_share(diff, before) <= SHARE - 1e-9:
        return False
    now = int(doc.get("version") or 1)
    then = int(crit.get("version") or 1)
    if then >= now:
        return False
    crit["stale"] = True
    crit["stale_words"] = f"About an earlier version (v{then}); the plan has changed a lot since."
    usd = price(cfg) if cfg is not None else None
    offer = {"version": now, "about": then, "usd": usd, "share": round(changed_share(diff, before), 3)}
    p = _offer_path(root)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(offer, indent=2), encoding="utf-8")
    except OSError:
        pass
    return True


def ask(orch) -> dict[str, Any] | None:
    """The card: "The plan changed a lot since its critique. Have it looked at again?" (priced), or None."""
    from ..asks import _ask

    offer = read_offer(orch.project.root)
    doc = orch.project.plan_doc() or {}
    if not offer or int(offer.get("version") or 0) != int(doc.get("version") or 0):
        return None
    crit = doc.get("critique") or {}
    if int(crit.get("version") or 0) >= int(offer["version"]):
        return None  # it has looked again since
    usd = offer.get("usd")
    cost = f"about ${usd:.2f}" if isinstance(usd, (int, float)) else "a few cents (its price isn't known)"
    opts = [{"id": "yes", "label": "Look again", "description": f"A second model reads the new plan: {cost}."},
            {"id": "no", "label": "Not needed", "description": "The old critique stays, marked as about an earlier version."}]
    a = _ask("lookagain", "look_again", "Critique",
             "The plan has changed a lot since it was critiqued. Have it looked at again?", opts,
             recommended="yes", detail=f"The critique was about version {offer.get('about')}; this is version "
                                       f"{offer['version']}.", source={"look_again": offer["version"]},
             usd=usd)
    a["allow_other"] = False
    return a


def apply(orch, ask_: dict[str, Any], picked: list[str] | None, other: str = "") -> dict[str, Any]:
    """The card's answer: yes asks the critic once (the orchestrator's own ``_critique``); either way the offer goes."""
    try:
        _offer_path(orch.project.root).unlink()
    except OSError:
        pass
    if (picked or ["no"])[0] != "yes":
        return {"reply": "The old critique stays, marked as about an earlier version.", "then": None}
    got = orch._critique()
    if not got:
        return {"reply": "The critic couldn't look this time; the old critique stays.", "then": None}
    return {"reply": f"Looked at again: {'it needs changes' if got.get('verdict') == 'revise' else 'it looks right'}.",
            "then": None}
