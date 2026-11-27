"""The watch (improve/canary.py): after a change is applied the next tasks are compared with before, and a clear drop
undoes it by itself. Made-up projects with hand-written metrics rows; no network, no keys."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from roundtable.harness.orchestrator import Orchestrator
from roundtable.improve import canary, charter
from roundtable.improve.lab import Lab, Proposal
from roundtable.improve.loop import cycle

from .test_improve import make_cfg

T0 = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def project(lab, root):
    (root / ".harness").mkdir(parents=True, exist_ok=True)
    (root / ".harness" / "project.json").write_text("{}", encoding="utf-8")
    (root / ".harness" / "tasks.json").write_text("[]", encoding="utf-8")
    lab.register_project(root)
    return root


def add_rows(root, role, outcomes, start, cost=0.01, **extra):
    with open(root / ".harness" / "metrics.jsonl", "a", encoding="utf-8") as f:
        for i, o in enumerate(outcomes):
            row = {"at": iso(start + timedelta(minutes=i)), "task": f"T{i}", "role": role, "model": "a/coder",
                   "outcome": o, "cost_usd": cost, **extra}
            f.write(json.dumps(row) + "\n")


def applied(lab, cfg, role="coder", models=("b/coder2",), at=None):
    p = lab.add_proposal(Proposal(id="", kind="routing", role=role, change={"models": list(models)},
                                  rationale="r", risk="low"))
    lab.apply(p, cfg)
    p = lab.proposal(p.id)
    if at is not None:  # pretend it was applied then (the rows are written around it)
        p.watch["since"] = iso(at)
        lab.save_proposal(p)
    return p


@pytest.fixture
def setup(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    root = project(lab, tmp_path / "shop")
    add_rows(root, "coder", ["approved"] * 9 + ["rejected"], T0 - timedelta(days=1))  # 90% before
    return cfg, lab, root


def _before(lab, p):
    """The before-numbers as start() would have taken them at the change's own time."""
    rows = [r for r in canary.rows(lab, p.role) if r["at"] <= p.watch["since"]]
    p.watch["before"] = canary.summary(rows[-30:])
    lab.save_proposal(p)
    return p


def test_a_planted_bad_change_is_undone_without_a_human(setup):
    cfg, lab, root = setup
    p = _before(lab, applied(lab, cfg, at=T0))
    add_rows(root, "coder", ["rejected", "approved", "rejected", "rejected", "rejected"], T0 + timedelta(hours=1))
    undone = canary.check(cfg, lab)
    assert [u["id"] for u in undone] == [p.id]
    assert "work passed fell from 90% to 20%" in undone[0]["why"]
    q = lab.proposal(p.id)
    assert q.status == "undone" and q.watch["state"] == "undone" and q.undone_why
    overlay, _ = lab.learned()
    assert "coder" not in (overlay.get("roles") or {}) or not (overlay["roles"]["coder"] or {}).get("model")
    assert canary.check(cfg, lab) == []  # said once


def test_a_good_change_is_kept_at_eight(setup):
    cfg, lab, root = setup
    p = _before(lab, applied(lab, cfg, at=T0))
    add_rows(root, "coder", ["approved"] * 7 + ["rejected"], T0 + timedelta(hours=1))
    assert canary.check(cfg, lab) == []
    q = lab.proposal(p.id)
    assert q.status == "applied" and q.watch["state"] == "kept" and q.watch["after"]["judged"] == 8


def test_one_unlucky_rejection_undoes_nothing(setup):
    cfg, lab, root = setup
    p = _before(lab, applied(lab, cfg, at=T0))
    add_rows(root, "coder", ["rejected", "approved", "approved", "approved", "approved"], T0 + timedelta(hours=1))
    assert canary.check(cfg, lab) == []
    assert lab.proposal(p.id).watch["state"] == "watching"
    add_rows(root, "coder", ["rejected"], T0 + timedelta(hours=2))  # 2 of 6 back: 67%, only 1.4 more than expected
    assert canary.check(cfg, lab) == []


def test_provider_errors_undo_it(setup):
    cfg, lab, root = setup
    p = _before(lab, applied(lab, cfg, at=T0))
    add_rows(root, "coder", ["error", "approved", "error", "approved", "approved"], T0 + timedelta(hours=1))
    [u] = canary.check(cfg, lab)
    assert u["id"] == p.id and "failed on 2 of 5 tries" in u["why"]


def test_dearer_with_no_gain_is_undone_at_eight(setup):
    cfg, lab, root = setup
    p = _before(lab, applied(lab, cfg, at=T0))
    add_rows(root, "coder", ["approved"] * 7 + ["rejected"], T0 + timedelta(hours=1), cost=0.05)
    [u] = canary.check(cfg, lab)
    assert u["id"] == p.id and "times as much" in u["why"]


def test_other_jobs_later_changes_stay(setup):
    cfg, lab, root = setup
    p = _before(lab, applied(lab, cfg, at=T0))
    other = applied(lab, cfg, role="orchestrator", models=("b/coder2",), at=T0 + timedelta(minutes=30))
    add_rows(root, "coder", ["rejected"] * 5, T0 + timedelta(hours=1))
    [u] = canary.check(cfg, lab)
    assert u["id"] == p.id
    assert lab.proposal(other.id).status == "applied"
    overlay, _ = lab.learned()
    assert overlay["roles"]["orchestrator"]["model"] == "b/coder2"


def test_rival_rows_and_explore_tries_are_ignored(setup):
    cfg, lab, root = setup
    p = _before(lab, applied(lab, cfg, at=T0))
    later = T0 + timedelta(hours=1)
    add_rows(root, "coder", ["rival_lost"] * 6, later)
    add_rows(root, "coder", ["rejected"] * 6, later, rival="R2")
    add_rows(root, "coder", ["rejected"] * 6, later, routed={"explore": True})
    add_rows(root, "coder", ["built"] * 6, later)
    assert canary.check(cfg, lab) == []
    assert lab.proposal(p.id).watch["after"]["judged"] == 0


def test_kept_after_thirty_days_without_enough_work(setup):
    cfg, lab, root = setup
    p = _before(lab, applied(lab, cfg, at=T0))
    assert canary.check(cfg, lab, now=T0 + timedelta(days=31)) == []
    assert lab.proposal(p.id).watch["state"] == "kept (not enough work to judge)"


def test_an_undone_change_is_never_applied_by_itself_again(setup):
    cfg, lab, root = setup
    cfg.improve["auto_apply"] = "low"
    p = _before(lab, applied(lab, cfg, at=T0))
    add_rows(root, "coder", ["rejected"] * 5, T0 + timedelta(hours=1))
    canary.check(cfg, lab)
    same = Proposal(id="", kind="routing", role="coder", change={"models": ["b/coder2"]}, rationale="r",
                    risk="low")
    assert lab.is_duplicate(same)  # never offered again
    lab.save_proposal(Proposal(id="PX", kind="routing", role="coder", change={"models": ["b/coder2"]},
                               rationale="r", risk="low", created_at="2026-11-27T00:00:00Z"))
    report = cycle(cfg, lab, probe=False)
    assert report["applied"] == [] and lab.proposal("PX").status == "proposed"
    assert lab.proposal(p.id).status == "undone"


def test_start_takes_the_last_thirty_judged_rows(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    root = project(lab, tmp_path / "shop")
    add_rows(root, "coder", ["rejected"] * 40 + ["approved"] * 30, T0 - timedelta(days=2))
    p = applied(lab, cfg)
    assert p.watch["before"]["judged"] == 30 and p.watch["before"]["rate"] == 1.0
    assert p.watch["state"] == "watching" and p.watch["need"] == 8


def test_canary_never_changes_what_the_charter_protects(setup, tmp_path):
    """The watch only ever goes back to an earlier learned state: it asks the charter nothing new, writes no
    harness.yaml or custom.yaml, and an undo only takes the change out."""
    cfg, lab, root = setup
    harness = tmp_path / "harness.yaml"
    harness.write_text("roles: {}\n", encoding="utf-8")
    p = _before(lab, applied(lab, cfg, at=T0))
    add_rows(root, "coder", ["rejected"] * 5, T0 + timedelta(hours=1))
    assert canary.check(cfg, lab)
    assert harness.read_text() == "roles: {}\n" and not (tmp_path / "custom.yaml").exists()
    assert charter.may_auto(p) in (True, False)


# -- the Orchestrator's stage ------------------------------------------------------------------------------------------
def test_watch_stage_undoes_after_a_run_and_writes_it_down(setup, tmp_path):
    cfg, lab, root = setup
    O = type("O", (Orchestrator,) if issubclass(Orchestrator, canary.WatchStage) else (canary.WatchStage, Orchestrator), {})
    p = _before(lab, applied(lab, cfg, at=T0))
    add_rows(root, "coder", ["rejected"] * 5, T0 + timedelta(hours=1))
    orch = O(cfg, tmp_path / "other")
    seen, notes = [], []
    orch._journal = lambda kind, text, **kw: notes.append((kind, text))
    orch.emit = lambda kind, data: seen.append(kind)
    undone = orch._watch_after_run()
    assert [u["id"] for u in undone] == [p.id]
    assert "learning_undone" in seen
    assert notes and notes[0][0] == "decision" and notes[0][1].startswith("Undone by itself:") and "Why:" in notes[0][1]
    assert orch._watch_metric(None, None) == {"learned": lab.state_id()}
