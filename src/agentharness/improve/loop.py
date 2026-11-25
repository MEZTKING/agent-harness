"""One improvement cycle: analyze -> (test) -> apply what the policy allows.

Auto-apply policy (``improve.auto_apply`` in harness.yaml):
    none    (default) nothing is applied without you
    low     low-risk changes that passed a replay test, plus rule-based
            routing changes (they are backed by production metrics)
    medium  same, up to medium risk

LLM-proposed changes are only ever auto-applied after passing a replay test.
Run it after projects finish, or on a schedule (cron) to keep improving.
"""

from __future__ import annotations

from typing import Any, Callable

from ..harness.agent import BudgetExceeded
from ..harness.config import HarnessConfig
from .analysis import analyze
from .evaluate import EvalError, evaluate
from .lab import Lab, Proposal

RISK_RANK = {"low": 1, "medium": 2, "high": 3}
POLICY_RANK = {"none": 0, "low": 1, "medium": 2}


def auto_apply_allowed(p: Proposal, policy: str) -> bool:
    if RISK_RANK.get(p.risk, 3) > POLICY_RANK.get(policy, 0):
        return False
    if p.test and p.test.get("passed"):
        return True
    return p.source == "rules" and p.kind == "routing" and not p.test  # data-backed, untested is OK


def cycle(
    cfg: HarnessConfig,
    lab: Lab,
    use_llm: bool = False,
    test: bool = False,
    max_cost: float = 2.0,
    samples: int = 3,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    emit = on_event or (lambda *_: None)
    policy = cfg.improve.get("auto_apply", "none")
    ds, new, analyst_cost = analyze(cfg, lab, use_llm=use_llm, max_cost=max_cost, on_event=on_event)
    report: dict[str, Any] = {"new": [p.id for p in new], "tested": [], "applied": [], "skipped": [],
                              "projects": len(ds.projects), "analyst_cost_usd": analyst_cost}
    remaining = max(max_cost - analyst_cost, 0)
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
        if policy != "none" and auto_apply_allowed(p, policy):
            version = lab.apply(p, cfg, reason=f"auto ({policy} policy)")
            lab.apply_learned(cfg)  # later proposals in this cycle see the new state
            report["applied"].append({"id": p.id, "version": version, "summary": p.summary()})
            emit("applied", {"id": p.id, "version": version})
    return report
