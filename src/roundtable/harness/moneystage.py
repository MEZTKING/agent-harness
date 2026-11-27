"""Money: a run never quietly costs more than the owner agreed to (wave 5, d2-money).

The owner: "Money is the owner's … stop and ask when a run goes well past it."

* ``_money_agreed`` (at approval, and again when the owner says Carry on): ``meta["agreed"]`` =
  {usd, at, version, by, spent_before}: the estimate the owner saw, and what was already spent then.
* ``_money_gate`` (before each task): what was spent since the agreement plus the estimate of what's still
  to do, against the agreed amount plus some room (``money.over_estimate``, 25 %, never less than
  ``money.over_estimate_min_usd``, $0.50). Past it the run pauses (``pause: over_estimate``) with one card:
  ``over_estimate_ask``. Nothing happens for an old project with no agreement, or while the estimate has
  models without a price (the count would be wrong; the project's own limit still holds).
* Autopilot's allowance: a run autopilot starts carries ``meta["run_allowance"]`` (autopilot.allow). While
  that autopilot session is on (or it switched itself off at its limit), the run stops at it:
  ``_money_charge`` raises :class:`AllowanceReached` inside a task, ``_money_gate`` pauses between tasks.
  ``_money_charge`` also re-reads what every project spent since autopilot was switched on, at most once a
  minute, so several projects started together can't jointly pass autopilot's limit.

Autopilot never answers these cards (they're money: asks' kind "money").
"""

from __future__ import annotations

import time
from typing import Any

from ..brand import NAME
from ..core.models import utcnow
from .agent import BudgetExceeded
from .config import section

OVER = 0.25  # how far past the agreed amount a run may go before it asks
OVER_MIN_USD = 0.50  # but always at least this much room
PAUSES = ("over_estimate", "allowance")


class AllowanceReached(BudgetExceeded):
    """Autopilot's spending limit is reached: the run waits for the owner."""


def _usd(x: float | None) -> str:
    return f"${(x or 0):.2f}"


def room(cfg, agreed_usd: float) -> float:
    """How much past ``agreed_usd`` a run may go before it stops and asks."""
    s = section(cfg, "money")
    try:
        over = float(s.get("over_estimate", OVER))
        least = float(s.get("over_estimate_min_usd", OVER_MIN_USD))
    except (TypeError, ValueError):
        over, least = OVER, OVER_MIN_USD
    return max(agreed_usd * max(over, 0.0), max(least, 0.0))


class MoneyStage:
    """A mixin for Orchestrator: the agreed amount and autopilot's allowance."""

    ALLOWANCE_CHECK_SECONDS = 60  # how often a run re-reads what every project spent under autopilot

    # -- what the owner agreed to -----------------------------------------------------------------------
    def _money_agreed(self, again: bool = False, by: str = "") -> dict[str, Any]:
        """Write down what the owner agreed to spend. At approval: the estimate they saw. ``again`` (Carry on
        on the card): the new figure, counted from the same starting point."""
        meta = self.project.meta()
        doc = self.project.plan_doc() or {}
        if not doc or not self.project.tasks():
            return {}  # approved before there was a plan: no estimate was seen, so nothing was agreed
        spent = float(self.budget.spent_usd or 0)
        old = meta.get("agreed") or {}
        if again and old:
            now = self._money_projection()
            usd = None if now is None else now["now_usd"]
            before = float(old.get("spent_before") or 0)
        else:
            est = doc.get("estimate") or self._estimate(self.project.tasks(), doc.get("has_ui"))
            usd = None if est.get("unpriced") or est.get("cost_usd") is None else float(est["cost_usd"])
            before = spent
        agreed = {"usd": None if usd is None else round(usd, 4), "at": utcnow(), "version": doc.get("version", 1),
                  "by": by or getattr(self, "money_by", "") or "owner", "spent_before": round(before, 6)}
        meta = self.project.meta()
        meta["agreed"] = agreed
        self.project.save_meta(meta)
        self.emit("money_agreed", {"usd": agreed["usd"], "again": bool(again)})
        return agreed

    def _money_projection(self) -> dict[str, Any] | None:
        """{now_usd, agreed_usd, limit_usd, spent_usd, left_usd}: what this goal will now cost, or None when
        it can't be told (no agreement, or a model without a price)."""
        agreed = self.project.meta().get("agreed") or {}
        if agreed.get("usd") is None:
            return None
        doc = self.project.plan_doc() or {}
        est = self._estimate(self.project.tasks(), doc.get("has_ui"))
        if est.get("unpriced") or est.get("cost_usd") is None:
            return None
        spent = max(0.0, float(self.budget.spent_usd or 0) - float(agreed.get("spent_before") or 0))
        now = spent + float(est["cost_usd"])
        usd = float(agreed["usd"])
        return {"now_usd": round(now, 4), "agreed_usd": usd, "limit_usd": round(usd + room(self.cfg, usd), 4),
                "spent_usd": round(spent, 4), "left_usd": round(float(est["cost_usd"]), 4)}

    # -- autopilot's allowance --------------------------------------------------------------------------
    def _allowance(self) -> dict[str, Any] | None:
        """The allowance autopilot gave this run, while it holds (that autopilot session is still on, or
        stopped itself at its limit). None otherwise."""
        allow = self.project.meta().get("run_allowance")
        if not isinstance(allow, dict) or not allow.get("session"):
            return None
        from .. import autopilot

        try:
            state = autopilot.load(allow.get("home") or None)
        except Exception:  # can't read autopilot's settings: the project's own limits still hold
            return None
        if state.get("started_at") != allow["session"] or not (state.get("on") or state.get("capped")):
            return None
        return {**allow, "state": state}

    def _allowance_used(self, allow: dict[str, Any]) -> float:
        return max(0.0, float(self.budget.spent_usd or 0) - float(allow.get("spent_before") or 0))

    def _allowance_stop(self) -> str | None:
        """Why this run must stop for autopilot's limit, in plain words, or None."""
        allow = self._allowance()
        if not allow:
            return None
        used = self._allowance_used(allow)
        if used >= float(allow.get("usd") or 0):
            return (f"autopilot's spending limit is reached: this run spent {_usd(used)} of the "
                    f"{_usd(allow.get('usd'))} it had left")
        cap = float(allow.get("cap_usd") or allow["state"].get("spend_cap_usd") or 0)
        with self._lock:
            mark = getattr(self, "_ap_seen", None)  # (when, every project's spend then, counted since)
            if mark is None or time.time() - mark[0] >= self.ALLOWANCE_CHECK_SECONDS:
                from .. import autopilot

                try:
                    total = autopilot.counted(self.cfg, allow["state"])
                except Exception:
                    total = 0.0
                real = float(allow["state"].get("real_usd") or 0)
                mark = self._ap_seen = (time.time(), max(total, real), 0.0)
            together = mark[1] + mark[2]
        if cap and together >= cap:
            return (f"autopilot's spending limit of {_usd(cap)} is reached across your projects "
                    f"({_usd(together)} spent while it was on)")
        return None

    # -- the hooks ----------------------------------------------------------------------------------------
    def _money_charge(self, cost: float) -> None:
        """Every charge (spend.jsonl already has it): inside a task, autopilot's limit stops the run."""
        with self._lock:
            mark = getattr(self, "_ap_seen", None)
            if mark is not None:
                self._ap_seen = (mark[0], mark[1], mark[2] + float(cost or 0))
        why = self._allowance_stop()
        if why:
            raise AllowanceReached(why)

    def _money_gate(self) -> str | None:
        """Before each task. Returns "paused" when the run must wait for the owner."""
        why = self._allowance_stop()
        if why:
            self._set_status("paused", pause="allowance", reason=why)
            self._attention("money", "Autopilot's spending limit is reached: this run waits for you")
            return "paused"
        p = self._money_projection()
        if not p or p["now_usd"] <= p["limit_usd"]:
            return None
        self._set_status("paused", pause="over_estimate", over_estimate=p)
        self._attention("money", f"This will now cost about {_usd(p['now_usd'])}. You agreed to about "
                                 f"{_usd(p['agreed_usd'])}: it waits for you",
                        details=f"spent since you agreed {_usd(p['spent_usd'])}, still to do about "
                                f"{_usd(p['left_usd'])}, allowed up to {_usd(p['limit_usd'])}")
        self._journal("note", f"{NAME} paused: this goal would now cost about {_usd(p['now_usd'])}, well past "
                              f"the {_usd(p['agreed_usd'])} you agreed to.")
        return "paused"


# -- the card ------------------------------------------------------------------------------------------------
def over_estimate_ask(orch) -> dict[str, Any] | None:
    """The card for a run paused past the agreed amount or at autopilot's limit, as plain data:
    {question, options, recommended, source}. asks.py wraps it as a money card. None: not paused for money."""
    meta = orch.project.meta()
    why = meta.get("pause")
    if meta.get("status") != "paused" or why not in PAUSES:
        return None
    if why == "allowance":
        allow = meta.get("run_allowance") or {}
        q = (f"Autopilot's spending limit is reached ({_usd(allow.get('usd'))} for this run). It waits for you. "
             "Carry on?")
        opts = [{"id": "more", "label": "Carry on",
                 "description": "Carries on without autopilot's limit; the project's own limits still hold.",
                 "confirm": "This lets the run spend past autopilot's limit. Carry on?"},
                {"id": "stop", "label": "Stop here", "description": "Nothing more is spent. You can carry on later."}]
        return {"question": q, "options": opts, "recommended": None,
                "source": {"pause": why, "at": meta.get("updated_at", ""), "extra": 0.0,
                           "allowance": allow.get("usd")}}
    p = meta.get("over_estimate") or {}
    now, agreed = p.get("now_usd"), p.get("agreed_usd")
    q = f"This will now cost about {_usd(now)}. You agreed to about {_usd(agreed)}. Carry on?"
    opts = [{"id": "more", "label": f"Carry on (about {_usd(now)})",
             "description": "Agrees the new amount and carries on, fixes included.",
             "confirm": f"This agrees about {_usd(now)} of your credit for this goal. Carry on?"},
            {"id": "finish", "label": "Finish with what's there",
             "description": "Does the tasks already planned, then stops: no more automatic fixes or extra tasks."},
            {"id": "stop", "label": "Stop here", "description": "Nothing more is spent. You can carry on later."}]
    return {"question": q, "options": opts, "recommended": None,
            "source": {"pause": why, "at": meta.get("updated_at", ""), "extra": 0.0, "now_usd": now,
                       "agreed_usd": agreed}}


def apply_answer(orch, pause: str, choice: str) -> dict[str, Any]:
    """The owner's answer on that card ("stop" is asks.py's own): {"reply", "then"}."""
    meta = orch.project.meta()
    if pause == "allowance":
        meta.pop("run_allowance", None)  # the owner's say-so: this run no longer stops at autopilot's limit
        orch.project.save_meta(meta)
        return {"reply": "Carrying on without autopilot's limit.", "then": "run"}
    if choice == "finish":
        meta["no_auto_tasks"] = True  # add_tasks refuses from now on: only what's planned is done
        orch.project.save_meta(meta)
        orch._money_agreed(again=True)
        return {"reply": "Finishing the tasks already planned, with no extra ones.", "then": "run"}
    a = orch._money_agreed(again=True)
    return {"reply": f"Agreed: about {_usd(a.get('usd'))}. Carrying on.", "then": "run"}
