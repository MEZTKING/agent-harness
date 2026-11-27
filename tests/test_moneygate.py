"""Money (harness/moneystage.py, harness/imageprice.py, autopilot's allowance): a run never quietly costs more
than the owner agreed to. Made-up projects, scripted models, no network, no keys.

The three gaps these close (plans/gaps.md): "A run can start above the estimate the owner saw", "Autopilot
doesn't stop a run at its own limit", "Autopilot can't approve a plan with pictures".
"""

import json
from datetime import datetime, timezone

import pytest

from roundtable import asks as asklib
from roundtable import autopilot
from roundtable.harness import moneystage, plandoc
from roundtable.harness.config import parse_config
from roundtable.harness.imageprice import per_image, reported
from roundtable.harness.moneystage import AllowanceReached, MoneyStage
from roundtable.harness.orchestrator import Orchestrator, Task
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider

from .test_harness import RAW, Brain


# until the coordinator hooks it up, MoneyStage is mixed in here; afterwards it's in Orchestrator already
BASES = (Orchestrator,) if issubclass(Orchestrator, MoneyStage) else (MoneyStage, Orchestrator)


class O(*BASES):
    pass


def task(tid, **kw):
    return {"id": tid, "title": f"part {tid}", "role": "coder", "description": f"write {tid}.txt",
            "acceptance": "exists", "depends_on": [], **kw}


def raw(price=10.0, lab=None, **limits):
    r = json.loads(json.dumps(RAW))
    for m in ("a/planner", "a/coder", "b/coder2", "a/reviewer"):
        r["pricing"][m] = {"input": price, "output": price}
    r["limits"].update({"max_cost_usd": 1000, "max_auto_tasks": 30, **limits})
    if lab:
        r.setdefault("improve", {})["lab_dir"] = str(lab)
    return r


def build(tmp_path, cls=O, r=None, plan=None, name="proj"):
    cfg = parse_config(r or raw())
    brain = Brain(plan=plan or [task("T1")])
    for n in ("a", "b"):
        cfg.register(n, ScriptedProvider(n, brain))
    cfg.register("img", ScriptedImages())
    events = []
    orch = cls(cfg, tmp_path / name, on_event=lambda k, d: events.append((k, d)))
    return orch, events


@pytest.fixture
def no_history(monkeypatch):
    """Past runs' averages would replace the typical sizes with this run's tiny scripted costs; these tests
    are about the gate, so the estimate stays on typical sizes."""
    monkeypatch.setattr(plandoc, "history_by_role", lambda files: {})


def card(orch):
    data = moneystage.over_estimate_ask(orch)
    assert data, "no money card"
    return asklib._ask("money", "money", "Money", data["question"], data["options"],
                       recommended=data["recommended"], source=data["source"])


# -- a run can start above the estimate the owner saw ------------------------------------------------------------
class Grows:
    """An end step that adds work twice (as the done gate and the finish stage do): each round's size given."""

    rounds = (6, 7)

    def _finish_step(self, tasks):
        n = getattr(self, "_round", 0)
        if n >= len(self.rounds):
            return None
        self._round = n + 1
        self.add_tasks([task(f"R{n}x{i}") for i in range(self.rounds[n])], by="harness", why=f"round {n}")
        return "again"


class G(Grows, *BASES):
    pass


def test_a_run_can_start_above_the_estimate_the_owner_saw(tmp_path, no_history):
    orch, events = build(tmp_path, cls=G, plan=[task(f"T{i}") for i in range(1, 6)])
    orch.start("a made-up tool", require_approval=True)
    assert orch.run() == "awaiting_approval"
    est = orch.project.plan_doc()["estimate"]
    assert not est["unpriced"]
    orch.approve()
    agreed = orch.project.meta()["agreed"]
    assert agreed["usd"] == pytest.approx(est["cost_usd"], abs=1e-3) and agreed["by"] == "owner"
    per = (est["cost_usd"] - sum(e["usd"] for e in est.get("extras") or [])) / 5  # a task, without the extra lines
    # round one adds six more tasks (about 1.2 times what was agreed): within the room, it carries on;
    # round two adds seven (about 1.4 times): it stops and asks
    assert orch.run() == "paused"
    meta = orch.project.meta()
    assert meta["status"] == "paused" and meta["pause"] == "over_estimate"
    p = meta["over_estimate"]
    assert p["now_usd"] == pytest.approx(p["left_usd"] + p["spent_usd"], abs=1e-3)
    assert p["left_usd"] >= 7 * per - 1e-3  # round two's seven tasks (and any extra lines) still to come
    assert p["now_usd"] > p["limit_usd"] == pytest.approx(agreed["usd"] * 1.25, abs=1e-3)
    assert sum(1 for t in orch.project.tasks() if t.status == "done") == 11  # round one's tasks did run
    ask = card(orch)
    assert ask["question"] == (f"This will now cost about ${p['now_usd']:.2f}. You agreed to about "
                               f"${agreed['usd']:.2f}. Carry on?")
    assert [o["id"] for o in ask["options"]] == ["more", "finish", "stop"] and ask["options"][0]["confirm"]
    # Carry on agrees the new amount; at the same figure it doesn't ask again
    r = moneystage.apply_answer(orch, "over_estimate", "more")
    assert r["then"] == "run" and orch.project.meta()["agreed"]["usd"] == pytest.approx(p["now_usd"], abs=1e-3)
    assert orch.run() == "done"
    assert all(t.status == "done" for t in orch.project.tasks())
    assert [k for k, d in events if k == "status" and d.get("pause") == "over_estimate"] == ["status"]


def test_within_the_room_it_carries_on(tmp_path, no_history):
    class Small(Grows, *BASES):
        rounds = (6,)

    orch, _ = build(tmp_path, cls=Small, plan=[task(f"T{i}") for i in range(1, 6)])
    orch.start("a made-up tool", require_approval=True)
    orch.run()
    orch.approve()
    assert orch.run() == "done"


def test_the_room_is_never_less_than_fifty_cents(tmp_path):
    cfg = parse_config(raw())
    assert moneystage.room(cfg, 1.0) == 0.5 and moneystage.room(cfg, 4.0) == 1.0
    r = raw()
    r["money"] = {"over_estimate": 0.1, "over_estimate_min_usd": 0.2}
    assert moneystage.room(parse_config(r), 10.0) == 1.0 and moneystage.room(parse_config(r), 1.0) == 0.2


def test_finish_with_whats_there_stops_added_work(tmp_path, no_history):
    orch, _ = build(tmp_path, cls=G, plan=[task(f"T{i}") for i in range(1, 6)])
    orch.start("a made-up tool", require_approval=True)
    orch.run()
    orch.approve()
    assert orch.run() == "paused"
    r = moneystage.apply_answer(orch, "over_estimate", "finish")
    assert r["then"] == "run" and orch.project.meta()["no_auto_tasks"] is True
    with pytest.raises(Exception, match="finish with what's there"):
        orch.add_tasks([task("Z1")], by="harness", why="one more")


def test_no_agreement_or_an_unknown_price_changes_nothing(tmp_path, no_history):
    orch, _ = build(tmp_path, cls=G, plan=[task("T1")])
    orch.start("an old project")  # no approval step: nothing agreed, as for projects made before
    assert orch.run() == "done"
    assert "agreed" not in orch.project.meta()
    # a plan with a picture whose price isn't known: the count would be wrong, so the gate stays out of it
    orch2, _ = build(tmp_path, plan=[task("T1"), {"id": "T2", "title": "logo", "role": "designer",
                                                  "description": "a logo", "acceptance": "png",
                                                  "depends_on": [], "output_path": "logo.png"}], name="p2")
    orch2.start("a made-up site", require_approval=True)
    orch2.run()
    orch2.approve()
    assert orch2.project.meta()["agreed"]["usd"] is None
    assert orch2._money_gate() is None


def test_the_estimate_line_says_what_was_agreed():
    est = {"cost_usd": 1.4, "minutes": 20, "unpriced": []}
    assert plandoc.estimate_line(est) == "about $1.40 and 20 minutes"
    assert plandoc.estimate_line(est, {"usd": 1.0}) == "about $1.40 and 20 minutes (you agreed to about $1.00)"
    assert plandoc.estimate_line(est, 1.4) == "about $1.40 and 20 minutes"


# -- autopilot doesn't stop a run at its own limit ---------------------------------------------------------------
def test_autopilot_stops_a_run_at_its_own_limit(tmp_path):
    home = tmp_path / "home"
    r = raw(price=1000.0)  # every scripted call costs $0.12
    orch, _ = build(tmp_path, r=r, plan=[task("T1")])
    orch.start("a made-up tool")
    autopilot.turn_on(cap=0.30, home=home)
    autopilot.allow(orch, autopilot.load(home), home)
    orch.budget.charge(0.12)
    orch.budget.charge(0.12)
    with pytest.raises(AllowanceReached, match="autopilot's spending limit"):
        orch.budget.charge(0.12)  # a charge reaches the run's hook (_on_charge), inside a task too
    # in a real run: the task waits (not failed) and the run stops there
    orch2, _ = build(tmp_path, r=r, plan=[task("T1")], name="p2")
    orch2.start("a made-up tool")
    autopilot.allow(orch2, autopilot.load(home), home)
    got = orch2.run()
    assert got in ("paused", "paused_budget")  # "paused" once the coordinator's except branch is in
    meta = orch2.project.meta()
    assert "autopilot's spending limit" in meta["reason"]
    assert orch2.project.tasks()[0].status == "pending"
    assert orch2.budget.spent_usd < 0.30 + 0.25  # it stopped at the call that passed it


def test_the_same_run_with_autopilot_off_is_untouched(tmp_path):
    home = tmp_path / "home"
    orch, _ = build(tmp_path, r=raw(price=1000.0), plan=[task("T1")])
    orch.start("a made-up tool")
    autopilot.turn_on(cap=0.30, home=home)
    autopilot.allow(orch, autopilot.load(home), home)
    autopilot.turn_off("you turned it off.", home)  # the owner is back
    assert orch.run() == "done"
    # a new autopilot session doesn't inherit an old run's allowance either
    orch2, _ = build(tmp_path, r=raw(price=1000.0), plan=[task("T1")], name="p2")
    orch2.start("a made-up tool")
    autopilot.turn_on(cap=0.30, home=home, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    autopilot.allow(orch2, autopilot.load(home), home)
    autopilot.turn_on(cap=0.30, home=home)  # switched on again later: another session
    assert orch2.run() == "done"


def test_when_autopilot_turns_itself_off_at_its_limit_the_run_still_stops(tmp_path):
    home = tmp_path / "home"
    orch, _ = build(tmp_path, r=raw(price=1000.0), plan=[task("T1")])
    orch.start("a made-up tool")
    autopilot.turn_on(cap=0.30, home=home)
    autopilot.allow(orch, autopilot.load(home), home)
    autopilot.turn_off("it reached its spend limit.", home, capped=True)
    assert orch.run() in ("paused", "paused_budget")


def test_between_tasks_the_gate_pauses_with_a_card_autopilot_leaves(tmp_path):
    home = tmp_path / "home"
    orch, _ = build(tmp_path, r=raw(price=1000.0), plan=[task("T1")])
    orch.start("a made-up tool")
    autopilot.turn_on(cap=0.30, home=home)
    autopilot.allow(orch, autopilot.load(home), home)
    orch.budget.spent_usd = 0.31  # spent between two tasks
    assert orch._money_gate() == "paused"
    meta = orch.project.meta()
    assert meta["pause"] == "allowance"
    ask = card(orch)
    assert ask["question"].startswith("Autopilot's spending limit is reached ($0.30 for this run)")
    assert [o["id"] for o in ask["options"]] == ["more", "stop"]
    assert autopilot.decide(orch, ask, autopilot.load(home))[0] is None
    r = moneystage.apply_answer(orch, "allowance", "more")  # the owner's say-so: no autopilot limit for it
    assert r["then"] == "run" and "run_allowance" not in orch.project.meta()
    assert orch._money_gate() is None


def test_two_projects_cant_jointly_pass_the_cap(tmp_path):
    home, lab = tmp_path / "home", tmp_path / "lab"
    r = raw(price=1.0, lab=lab)
    a, _ = build(tmp_path, r=r, name="a")
    b, _ = build(tmp_path, r=r, name="b")
    autopilot.turn_on(cap=0.30, home=home)
    for o in (a, b):
        o.start("a made-up tool")
        o._register_with_lab()
        autopilot.allow(o, autopilot.load(home), home)  # each started with all $0.30 left
    for _ in range(2):  # project a spends $0.24 of it
        a.budget.charge(0.12)
    b.budget.charge(0.03)  # b alone is far below its own $0.30, but together they're at $0.27
    b.ALLOWANCE_CHECK_SECONDS = 0  # (a minute later)
    with pytest.raises(AllowanceReached, match="across your projects"):
        b.budget.charge(0.04)
    assert b.budget.spent_usd < 0.30


def test_the_shared_count_is_read_at_most_once_a_minute(tmp_path, monkeypatch):
    home, lab = tmp_path / "home", tmp_path / "lab"
    orch, _ = build(tmp_path, r=raw(price=1.0, lab=lab))
    orch.start("a made-up tool")
    orch._register_with_lab()
    autopilot.turn_on(cap=5.0, home=home)
    autopilot.allow(orch, autopilot.load(home), home)
    reads = []
    real = autopilot.counted
    monkeypatch.setattr(autopilot, "counted", lambda cfg, state: reads.append(1) or real(cfg, state))
    for _ in range(5):
        orch.budget.charge(0.01)
    assert len(reads) == 1


def test_autopilot_writes_the_allowance_before_it_starts_a_run(tmp_path):
    from .test_autopilot import Starts, lab_raw, planned, priced

    home = tmp_path / "home"
    orch = planned(tmp_path)
    autopilot.turn_on(cap=2.0, home=home)
    starts = Starts(do=True)
    autopilot.tick(orch.base_cfg, home=home, start=starts)  # the plan's answers, then the plan is updated
    priced(orch, 0.01)
    autopilot.tick(orch.base_cfg, home=home, start=Starts())
    allow = orch.project.meta()["run_allowance"]
    state = autopilot.load(home)
    assert allow["session"] == state["started_at"] and allow["usd"] == pytest.approx(2.0 - state["spent_usd"])
    assert allow["home"] == str(home)
    # the amount is written down as autopilot's (once MoneyStage is one of Orchestrator's bases)
    assert (orch.project.meta().get("agreed") or {"by": "autopilot"})["by"] == "autopilot"


# -- autopilot can't approve a plan with pictures ------------------------------------------------------------------
def metrics(path, *rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


PICTURE = Task(id="T2", title="logo", role="designer", description="a logo", acceptance="png")


def test_autopilot_can_approve_a_plan_with_pictures(tmp_path):
    cfg = parse_config(raw())
    f = metrics(tmp_path / "m.jsonl",
                {"role": "designer", "model": "img/pic", "outcome": "approved", "cost_usd": 0.04, "task": "T9"},
                {"role": "designer", "model": "img/pic", "outcome": "approved", "cost_usd": 0.06, "task": "T8"})
    assert reported([f]) == {"img/pic": pytest.approx(0.05)}
    est = plandoc.estimate(cfg, [PICTURE], plandoc.history_by_role([f]))
    assert est["unpriced"] == [] and est["cost_usd"] == pytest.approx(0.05)
    assert est["by_role"]["designer"]["cost_usd"] == pytest.approx(0.05)


def test_a_picture_priced_by_the_pricing_table(tmp_path):
    r = raw()
    r["pricing"]["img/pic"] = {"per_image": 0.03}
    cfg = parse_config(r)
    assert per_image(cfg, cfg.roles["designer"].models[0], []) == 0.03
    est = plandoc.estimate(cfg, [PICTURE], {})
    assert est["unpriced"] == [] and est["cost_usd"] == pytest.approx(0.03)


def test_a_picture_with_no_price_stays_unknown_and_autopilot_leaves_it(tmp_path):
    from .test_autopilot import Starts, planned

    cfg = parse_config(raw())
    f = metrics(tmp_path / "m.jsonl",  # a scripted picture model reports no charge: no price is invented
                {"role": "designer", "model": "img/pic", "outcome": "approved", "cost_usd": 0, "task": "T9"})
    est = plandoc.estimate(cfg, [PICTURE], plandoc.history_by_role([f]))
    assert est["unpriced"] == ["img/pic"]
    home = tmp_path / "home"
    orch = planned(tmp_path)
    autopilot.turn_on(home=home)
    autopilot.tick(orch.base_cfg, home=home, start=Starts(do=True))
    ask = next(a for a in asklib.open_asks(orch) if a["kind"] == "approve")
    assert autopilot.decide(orch, ask, autopilot.load(home)) == (None, "the plan's cost isn't known, so it waits for you")


def test_autopilot_never_answers_the_new_card(tmp_path, no_history):
    home = tmp_path / "home"
    orch, _ = build(tmp_path, cls=G, plan=[task(f"T{i}") for i in range(1, 6)])
    orch.start("a made-up tool", require_approval=True)
    orch.run()
    orch.approve()
    assert orch.run() == "paused"
    autopilot.turn_on(home=home)
    ask = card(orch)
    chosen, why = autopilot.decide(orch, ask, autopilot.load(home))
    assert chosen is None and "never raises a limit" in why


# -- once hooked up (MoneyStage among Orchestrator's bases, the asks.py and except branches in) -------------------
hooked = pytest.mark.skipif(not issubclass(Orchestrator, MoneyStage), reason="MoneyStage isn't hooked up yet")


@hooked
def test_hooked_the_card_is_answered_through_asks(tmp_path, no_history):
    class H(Grows, Orchestrator):
        pass

    orch, _ = build(tmp_path, cls=H, plan=[task(f"T{i}") for i in range(1, 6)])
    orch.start("a made-up tool", require_approval=True)
    orch.run()
    orch.approve()
    assert orch.run() == "paused"
    ask = next(a for a in asklib.open_asks(orch) if a["kind"] == "money")
    assert ask["question"].startswith("This will now cost about")
    with pytest.raises(Exception, match="Are you sure"):
        asklib.answer_ask(orch, "money", ["more"])
    r = asklib.answer_ask(orch, "money", ["more"], confirmed=True)
    assert r["then"] == "run" and asklib.finish(orch, r) == "The run ended as: done."


@hooked
def test_hooked_autopilot_stops_a_run_at_its_own_limit_with_one_card(tmp_path):
    home = tmp_path / "home"
    orch, _ = build(tmp_path, cls=Orchestrator, r=raw(price=1000.0), plan=[task("T1")])
    orch.start("a made-up tool")
    autopilot.turn_on(cap=0.30, home=home)
    autopilot.allow(orch, autopilot.load(home), home)
    assert orch.run() == "paused"
    assert orch.project.meta()["pause"] == "allowance"
    ask = next(a for a in asklib.open_asks(orch) if a["kind"] == "money")
    assert autopilot.decide(orch, ask, autopilot.load(home))[0] is None
    asklib.answer_ask(orch, "money", ["stop"])
    assert not [a for a in asklib.open_asks(orch) if a["kind"] == "money"]
