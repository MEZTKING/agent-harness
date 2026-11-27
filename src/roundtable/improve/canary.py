"""The watch: after a change is applied, the next tasks are compared with before, and a clear drop undoes
it by itself (wave 7). Always on, even while learning's money is off: it only ever goes back to the earlier
state, and it never spends anything.

``start(lab, p, version)`` (from ``Lab.apply``) writes ``p.watch``::

    {since, need: 8, state: "watching", version, before: {judged, approved, rejected, errors, tries, rate,
     cost_usd, finished, cost_per_finished}}

from the last 30 judged rows of that job before the change. ``check(cfg, lab)`` reads the job's rows after
``since`` in every project of the lab (rival rows – ``rival``, ``rival_lost``, ``built`` – and explore tries
left out) and, for each change still watched:

* undoes it when the approval rate fell by a fifth (0.20) or more **and** there are at least 2.5 more
  rejections than the earlier rate predicts (from 5 judged tasks on), or provider errors reach 30% over at
  least 5 tries, or the cost per finished task is 1.5 times higher with no gain in approvals (at 8);
* keeps it at 8 judged tasks with no drop ("kept"), or after 30 days without enough work ("kept (not enough
  work to judge)").

An undone change is ``Lab.undo(p.id, why, by="watch")`` (status ``undone``), never applied by itself again.
``WatchStage`` is the Orchestrator's mixin: ``_watch_after_run`` runs ``check`` after a run and writes a
decision in the journal for each change undone; ``_watch_metric`` adds ``{"learned": state_id}`` to every
metrics row (read once per run). The signatures of ``start`` and ``check`` are frozen.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

NEED = 8  # judged tasks before a change is kept
FIRST_LOOK = 5  # judged tasks (or tries) before anything can be undone
BEFORE_ROWS = 30  # rows of the job before the change that make the "before"
RATE_DROP = 0.20  # a fall of a fifth in work passed
EXTRA_REJECTIONS = 2.5  # and this many more rejections than the earlier rate predicts
ERROR_SHARE = 0.30  # provider errors over the tries
COST_TIMES = 1.5  # the cost per finished task, with no gain
GIVE_UP_DAYS = 30
SKIP_OUTCOMES = ("rival_lost", "built", "owner_feedback")
JUDGED = ("approved", "rejected")


def _now(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(text: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


# -- the rows -----------------------------------------------------------------------------------------------
def _counts(row: dict[str, Any]) -> bool:
    """A row the watch reads: not a rival's extra build, not an explore try, not the owner's own rating."""
    if row.get("rival") or row.get("outcome") in SKIP_OUTCOMES:
        return False
    routed = row.get("routed")
    if row.get("explore") or (isinstance(routed, dict) and routed.get("explore")):
        return False
    return bool(row.get("outcome"))


def rows(lab: Any, role: str = "") -> list[dict[str, Any]]:
    """Every counted metrics row of the job (every job when ``role`` is empty) in every project of the lab,
    oldest first."""
    out = []
    try:
        roots = list(lab.projects())
    except Exception:  # noqa: BLE001
        return []
    for root in roots:
        try:
            raw = (Path(root) / ".harness" / "metrics.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for ln in raw:
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if isinstance(d, dict) and (not role or d.get("role") == role) and _counts(d):
                out.append(d)
    out.sort(key=lambda d: str(d.get("at") or ""))
    return out


def summary(rs: list[dict[str, Any]]) -> dict[str, Any]:
    """Numbers only: judged, approved, rejected, errors, tries, rate, cost, cost per finished task."""
    approved = sum(1 for r in rs if r.get("outcome") == "approved")
    rejected = sum(1 for r in rs if r.get("outcome") == "rejected")
    errors = sum(1 for r in rs if r.get("outcome") == "error")
    judged = approved + rejected
    cost = round(sum(float(r.get("cost_usd") or 0) for r in rs), 6)
    return {"judged": judged, "approved": approved, "rejected": rejected, "errors": errors,
            "tries": judged + errors, "rate": round(approved / judged, 4) if judged else None,
            "cost_usd": cost, "finished": approved,
            "cost_per_finished": round(cost / approved, 6) if approved else None}


# -- start ------------------------------------------------------------------------------------------------------
def start(lab: Any, proposal: Any, version: int) -> None:
    """Start watching a change that was just applied: the job's last 30 judged rows are the "before"."""
    since = _now()
    before = [r for r in rows(lab, getattr(proposal, "role", "") or "") if str(r.get("at") or "") <= _iso(since)]
    judged = [r for r in before if r.get("outcome") in JUDGED]
    keep = judged[-BEFORE_ROWS:]
    first = str(keep[0].get("at") or "") if keep else ""
    window = [r for r in before if str(r.get("at") or "") >= first] if first else []
    proposal.watch = {"since": _iso(since), "need": NEED, "state": "watching", "version": version,
                      "before": summary(window), "after": summary([])}
    lab.save_proposal(proposal)


# -- judging --------------------------------------------------------------------------------------------------------
def judge(before: dict[str, Any], after: dict[str, Any]) -> tuple[str, str]:
    """("undo", why) / ("keep", "") / ("watch", "") from the numbers before and after a change."""
    n = after["judged"]
    rate0 = before.get("rate")
    if n >= FIRST_LOOK and rate0 is not None and after["rate"] is not None:
        expected = n * (1 - rate0)
        extra = after["rejected"] - expected
        if rate0 - after["rate"] >= RATE_DROP - 1e-9 and extra >= EXTRA_REJECTIONS - 1e-9:
            return "undo", (f"work passed fell from {round(rate0 * 100)}% to {round(after['rate'] * 100)}% "
                            f"over {n} tasks ({after['rejected']} sent back, about {round(expected, 1)} expected)")
    if after["tries"] >= FIRST_LOOK and after["errors"] / after["tries"] >= ERROR_SHARE - 1e-9:
        return "undo", (f"the service failed on {after['errors']} of {after['tries']} tries "
                        f"({round(100 * after['errors'] / after['tries'])}%)")
    if n >= NEED:
        c0, c1 = before.get("cost_per_finished"), after.get("cost_per_finished")
        gain = rate0 is None or (after["rate"] or 0) > rate0
        if c0 and c1 and c1 >= COST_TIMES * c0 - 1e-12 and not gain:
            return "undo", (f"each finished task cost {c1 / c0:.1f} times as much (${c1:.4f} against ${c0:.4f}) "
                            "with no more work passed")
        return "keep", ""
    return "watch", ""


def watched(lab: Any, role: str = "") -> list[Any]:
    """Applied changes still being watched (of one job when asked)."""
    return [p for p in lab.proposals("applied")
            if (p.watch or {}).get("state") == "watching" and (not role or p.role == role)]


def check(cfg: Any, lab: Any, now: datetime | None = None) -> list[dict[str, Any]]:
    """Look at the changes being watched; returns the ones undone just now:
    [{id, role, kind, summary, why, version}]."""
    now = _now(now)
    out: list[dict[str, Any]] = []
    try:
        candidates = watched(lab)
    except Exception:  # noqa: BLE001 - an empty or unreadable lab watches nothing
        return []
    for p in sorted(candidates, key=lambda q: q.applied_version or 0):
        try:
            p = lab.proposal(p.id)  # an undo earlier in this loop may have rewritten it
        except KeyError:
            continue
        w = dict(p.watch or {})
        if p.status != "applied" or w.get("state") != "watching":
            continue
        since = str(w.get("since") or "")
        after_rows = [r for r in rows(lab, p.role or "") if str(r.get("at") or "") > since]
        after = summary(after_rows)
        w["after"] = after
        verdict, why = judge(w.get("before") or summary([]), after)
        if verdict == "undo":
            try:
                version = lab.undo(p.id, why=why, by="watch", cfg=cfg)
            except Exception as e:  # noqa: BLE001 - a change that can't be undone stays watched; said once
                w["error"] = str(e)[:300]
                p.watch = w
                lab.save_proposal(p)
                continue
            p = lab.proposal(p.id)
            w["state"], w["undone_at"] = "undone", _iso(now)
            p.watch = w
            lab.save_proposal(p)
            out.append({"id": p.id, "role": p.role, "kind": p.kind, "summary": p.summary().strip(), "why": why,
                        "version": version})
            continue
        if verdict == "keep":
            w["state"], w["kept_at"] = "kept", _iso(now)
        else:
            t0 = _parse(since)
            if t0 and now - t0 >= timedelta(days=GIVE_UP_DAYS):
                w["state"], w["kept_at"] = "kept (not enough work to judge)", _iso(now)
        p.watch = w
        lab.save_proposal(p)
    return out


def words(u: dict[str, Any]) -> str:
    """The journal's line for a change undone by itself."""
    return f"Undone by itself: {u.get('summary', '')}. Why: {u.get('why', '')}"


# -- the Orchestrator's mixin ----------------------------------------------------------------------------------------
class WatchStage:
    """After every run: the watch; on every metrics row: which learned state it was made with."""

    def _watch_lab(self):
        lab_dir = getattr(getattr(self, "base_cfg", None), "lab_dir", None)
        if not lab_dir or not Path(lab_dir).is_dir():
            return None
        from .lab import Lab

        return Lab(lab_dir)

    def _watch_after_run(self) -> list[dict[str, Any]]:
        lab = self._watch_lab()
        if lab is None:
            return []
        undone = check(self.base_cfg, lab)
        for u in undone:
            self.emit("learning_undone", {"id": u["id"], "summary": u["summary"], "why": u["why"]})
            self._journal("decision", words(u), details=f"put back: roundtable improve rollback {u['version']}")
        return undone  # the next run reads the learned state afresh

    def _watch_metric(self, task: Any, ref: Any) -> dict[str, Any]:
        sid = getattr(self, "_watch_state_id", None)
        if sid is None:
            lab = self._watch_lab()
            sid = lab.state_id() if lab is not None and (lab.root / "learned.yaml").is_file() else ""
            self._watch_state_id = sid
        return {"learned": sid} if sid else {}
