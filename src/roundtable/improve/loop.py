"""One improvement cycle: analyze -> (test) -> apply what the policy allows.

Auto-apply policy (``improve.auto_apply`` in harness.yaml):
    none    (default) nothing is applied without you
    low     low-risk changes that passed a replay test, plus rule-based
            routing changes (they are backed by production metrics)
    medium  same, up to medium risk

LLM-proposed changes are only ever auto-applied after passing a replay test. Whatever the policy, the
charter (charter.may_auto) has the first word, a job whose last change is still being watched (canary.py)
gets no second change by itself, and a change undone by the watch is never applied by itself again.

``wallet=True`` (the schedule and the after-run step, while the weekly allowance is above 0): every paid step
takes its money from the learning allowance (wallet.py), in this order – the free rules; tests of waiting
proposals, cheapest first; the health check before an apply; the analyst only when 20 new judged tasks have
arrived and enough of the week is left. Running out ends the cycle with one plain line (``report["stopped"]``)
and the proposal being tested stays "proposed". ``wallet=False`` (the command line, the owner's buttons) is as
before: ``max_cost`` is the cap for this call.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

from ..harness.agent import BudgetExceeded
from ..harness.config import HarnessConfig
from . import canary, charter
from .analysis import analyze
from .evaluate import EvalError, evaluate
from .lab import Lab, Proposal

RISK_RANK = {"low": 1, "medium": 2, "high": 3}
POLICY_RANK = {"none": 0, "low": 1, "medium": 2}
TEST_MOST_USD = 0.50  # one test from the wallet costs at most this (improve.max_usd_per_test)
PROBE_MOST_USD = 0.20  # one health check before an apply (improve.max_usd_per_probe)
ANALYST_MOST_USD = 0.50  # one look by the analyst (improve.max_usd_per_analyst)
KIND_ORDER = {"routing": 0, "options": 1, "prompt": 2}


def auto_apply_allowed(p: Proposal, policy: str) -> bool:
    if not charter.may_auto(p):
        return False
    if RISK_RANK.get(p.risk, 3) > POLICY_RANK.get(policy, 0):
        return False
    if p.test and p.test.get("passed"):
        return True
    return p.source == "rules" and p.kind == "routing" and not p.test  # data-backed, untested is OK


def _was_undone(lab: Lab, p: Proposal) -> bool:
    """The same change was undone before (by the watch or the owner): never applied by itself again."""
    return any(q.id != p.id and q.status in ("undone", "rolled_back") and q.kind == p.kind and q.role == p.role
               and q.change == p.change for q in lab.proposals())


def _role_cost(lab: Lab) -> dict[str, float]:
    """Average cost of one try per job, from the lab's metrics (what "cheapest first" sorts by)."""
    sums: dict[str, list[float]] = {}
    for r in canary.rows(lab):
        sums.setdefault(str(r.get("role") or ""), []).append(float(r.get("cost_usd") or 0))
    return {k: sum(v) / len(v) for k, v in sums.items() if v}


def _wants_test(cfg: HarnessConfig, p: Proposal) -> bool:
    """A test is worth its money: not a rules-backed model order (applied on its data), only a chat job's
    change, never the reviewer's own (it is the judge)."""
    if p.source == "rules" and p.kind == "routing":
        return False
    role = cfg.roles.get(p.role)
    return bool(role) and role.kind == "chat" and p.role != cfg.reviewer_role


def _num(cfg: HarnessConfig, key: str, default: float) -> float:
    try:
        return max(0.0, float(cfg.improve.get(key, default)))
    except (TypeError, ValueError):
        return default


def _test_with(cfg: HarnessConfig, lab: Lab, p: Proposal, b: Any, samples: int, on_event) -> dict[str, Any]:
    """Test ``p`` paid by the wallet's budget ``b``, through ``evaluate``: the yardstick when it has tasks for
    the job, and replays of past tasks when there are some; one verdict from both, kept on the proposal.
    Returns {"verdict", "passed", "cost", "note"}."""
    from . import yardstick

    b.what = "yardstick" if yardstick.available(cfg, p.role) > 0 else "replay"
    res = evaluate(cfg, lab, p, samples=samples, budget=b, on_event=on_event, yard=True)
    return {"verdict": res["verdict"], "passed": res["passed"], "cost": res.get("eval_cost_usd"),
            "note": res.get("note", "")}


def cycle(
    cfg: HarnessConfig,
    lab: Lab,
    use_llm: bool = False,
    test: bool = False,
    max_cost: float = 2.0,
    samples: int = 3,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
    probe: bool = True,
    wallet: bool = False,
) -> dict[str, Any]:
    if wallet:
        return _wallet_cycle(cfg, lab, use_llm=use_llm, test=test, samples=samples, on_event=on_event, probe=probe)
    emit = on_event or (lambda *_: None)
    policy = cfg.improve.get("auto_apply", "none")
    ds, new, analyst_cost = analyze(cfg, lab, use_llm=use_llm, max_cost=max_cost, on_event=on_event)
    report: dict[str, Any] = {"new": [p.id for p in new], "tested": [], "applied": [], "skipped": [],
                              "projects": len(ds.projects), "analyst_cost_usd": analyst_cost}
    remaining = max(max_cost - analyst_cost, 0)
    health: dict[str, bool] = {}  # model -> acting up?

    def healthy(p: Proposal) -> bool:
        if not probe or not cfg.improve.get("probe_before_apply", True) or cfg.roles[p.role].kind != "chat":
            return True
        from .probe import check, models_for_proposal

        models = [m for m in models_for_proposal(cfg, p) if str(m) not in health]
        if models:
            for r in check(cfg, lab.root, models):
                health[r.model] = r.bad
        bad = [str(m) for m in models_for_proposal(cfg, p) if health.get(str(m))]
        if bad:
            report["skipped"].append({"id": p.id, "reason": f"held back: {', '.join(bad)} acting up (probe)"})
        return not bad

    for p in lab.proposals():
        if p.status not in ("proposed", "tested"):
            continue
        if test and p.status == "proposed" and remaining > 0:
            try:
                res = evaluate(cfg, lab, p, samples=samples, max_cost=remaining, on_event=on_event)
                remaining -= res["eval_cost_usd"]
                report["tested"].append({"id": p.id, "verdict": res["verdict"], "passed": res["passed"]})
                emit("tested", {"id": p.id, "verdict": res["verdict"]})
            except (EvalError, BudgetExceeded) as e:
                report["skipped"].append({"id": p.id, "reason": str(e)})
        if policy != "none" and auto_apply_allowed(p, policy) and _may_apply_now(lab, p, report) and healthy(p):
            try:
                version = lab.apply(p, cfg, reason=f"auto ({policy} policy)")
            except charter.CharterError as e:  # needs the owner's tap (offered), or never: the cycle carries on
                report["skipped"].append({"id": p.id, "reason": str(e)})
                continue
            lab.apply_learned(cfg)  # later proposals in this cycle see the new state
            report["applied"].append({"id": p.id, "version": version, "summary": p.summary()})
            emit("applied", {"id": p.id, "version": version})
    return report


def _may_apply_now(lab: Lab, p: Proposal, report: dict[str, Any]) -> bool:
    """Not while the same job's last change is still being watched; never a change undone before."""
    if _was_undone(lab, p):
        report["skipped"].append({"id": p.id, "reason": "the same change was undone before, so it waits for you"})
        return False
    if canary.watched(lab, p.role):
        report["skipped"].append({"id": p.id, "reason": "this job's last change is still being watched"})
        return False
    return True


def _wallet_cycle(cfg: HarnessConfig, lab: Lab, use_llm: bool, test: bool, samples: int,
                  on_event: Callable[[str, dict[str, Any]], None] | None, probe: bool) -> dict[str, Any]:
    from . import wallet as w

    emit = on_event or (lambda *_: None)
    policy = cfg.improve.get("auto_apply", "none")
    spent0 = w.spent_week(lab)
    # 1. the free rules
    ds, new, _ = analyze(cfg, lab, use_llm=False)
    report: dict[str, Any] = {"new": [p.id for p in new], "tested": [], "applied": [], "skipped": [],
                              "projects": len(ds.projects), "analyst_cost_usd": 0.0, "stopped": "",
                              "wallet": True}

    def stop(e: BaseException) -> None:
        if not report["stopped"]:
            report["stopped"] = str(e) if isinstance(e, w.AllowanceUsed) else w.stop_words(cfg)
            emit("learning_stopped", {"words": report["stopped"]})

    # 2. tests of waiting proposals, cheapest first
    if test and w.allowance(cfg) > 0:
        costs = _role_cost(lab)
        waiting = [p for p in lab.proposals("proposed") if _wants_test(cfg, p) and not _was_undone(lab, p)]
        waiting.sort(key=lambda p: (costs.get(p.role, 0.0), KIND_ORDER.get(p.kind, 9), p.created_at))
        for p in waiting:
            try:
                b = w.budget(cfg, lab, "replay", most=_num(cfg, "max_usd_per_test", TEST_MOST_USD))
            except w.AllowanceUsed as e:
                stop(e)
                break
            b.proposal = p.id
            try:
                got = _test_with(cfg, lab, p, b, samples, on_event)
            except w.AllowanceUsed as e:
                _back_to_proposed(lab, p)
                stop(e)
                break
            except (EvalError, BudgetExceeded) as e:
                report["skipped"].append({"id": p.id, "reason": str(e)})
                continue
            ran_out = b.spent_usd >= b.limit_usd - 1e-9 and b.cap in ("week", "day")
            cut_short = "stopped early" in str(got.get("note", ""))  # the replays' or the yardstick's (evaluate)
            if ran_out or (w.left(cfg, lab) <= 0 and cut_short):
                _back_to_proposed(lab, p)  # a half-done test proves nothing: it waits for next week
                stop(w.AllowanceUsed(b.words or w.stop_words(cfg)))
                break
            report["tested"].append({"id": p.id, "verdict": got["verdict"], "passed": got["passed"]})
            emit("tested", {"id": p.id, "verdict": got["verdict"]})

    # 3. apply what the policy allows, a health check first (from the wallet)
    health: dict[str, bool] = {}

    def healthy(p: Proposal) -> bool | None:
        """True: fine; False: held back; None: no money left for the check."""
        if not probe or not cfg.improve.get("probe_before_apply", True) or cfg.roles[p.role].kind != "chat":
            return True
        from .probe import check, models_for_proposal

        models = [m for m in models_for_proposal(cfg, p) if str(m) not in health]
        if models:
            try:
                b = w.budget(cfg, lab, "probe", most=_num(cfg, "max_usd_per_probe", PROBE_MOST_USD))
            except w.AllowanceUsed as e:
                stop(e)
                return None
            b.proposal = p.id
            for r in check(cfg, lab.root, models, max_cost=b.limit_usd):
                health[r.model] = r.bad
                try:
                    w.lump(b, float(getattr(r, "cost_usd", 0) or 0), ref=r.model, role=p.role)
                except BudgetExceeded:
                    pass
        bad = [str(m) for m in models_for_proposal(cfg, p) if health.get(str(m))]
        if bad:
            report["skipped"].append({"id": p.id, "reason": f"held back: {', '.join(bad)} acting up (probe)"})
        return not bad

    for p in lab.proposals():
        if p.status not in ("proposed", "tested"):
            continue
        if policy == "none" or not auto_apply_allowed(p, policy) or not _may_apply_now(lab, p, report):
            continue
        ok = healthy(p)
        if ok is None:
            break
        if not ok:
            continue
        try:
            version = lab.apply(p, cfg, reason=f"auto ({policy} policy, learning allowance)")
        except charter.CharterError as e:
            report["skipped"].append({"id": p.id, "reason": str(e)})
            continue
        lab.apply_learned(cfg)
        report["applied"].append({"id": p.id, "version": version, "summary": p.summary()})
        emit("applied", {"id": p.id, "version": version})

    # 4. the analyst, only now and then
    if use_llm and not report["stopped"] and w.allowance(cfg) > 0:
        due, why = w.analyst_due(cfg, lab)
        if not due:
            report["analyst"] = why
        else:
            try:
                b = w.budget(cfg, lab, "analyst", most=_num(cfg, "max_usd_per_analyst", ANALYST_MOST_USD))
            except w.AllowanceUsed as e:
                stop(e)
            else:
                role_name = cfg.improve.get("analyst_role") or ("improver" if "improver" in cfg.roles
                                                                else cfg.planner_role)
                ref = cfg.roles[role_name].models[0] if role_name in cfg.roles and cfg.roles[role_name].models else None
                try:
                    _, more, cost = analyze(cfg, lab, use_llm=True, max_cost=b.limit_usd, on_event=on_event)
                except BudgetExceeded as e:
                    more, cost = [], 0.0
                    report["skipped"].append({"id": "", "reason": f"the analyst stopped: {e}"})
                try:
                    w.lump(b, cost, ref=ref, role=role_name)
                except BudgetExceeded:
                    pass
                w.analyst_ran(lab)
                report["new"] += [p.id for p in more]
                report["analyst_cost_usd"] = round(cost, 6)

    report["spent_usd"] = round(max(0.0, w.spent_week(lab) - spent0), 6)
    report["left_usd"] = w.left(cfg, lab)
    return report


def _back_to_proposed(lab: Lab, p: Proposal) -> None:
    try:
        q = lab.proposal(p.id)
    except KeyError:
        return
    if q.status in ("proposed", "tested"):
        q.status, q.test = "proposed", None
        lab.save_proposal(q)

