"""Questions with a timer (wave 8, DS-44): expires to the recommended answer, holds while the owner types, never
answers for you when that spends or deletes, and a late answer on a changed question is told so plainly."""

from __future__ import annotations

import time

import pytest

from roundtable import asktimer
from roundtable.asks import open_asks
from roundtable.harness.orchestrator import HarnessError

from .test_harness import make

NOW = 1_800_000_000.0


@pytest.fixture
def waiting(tmp_path, monkeypatch):
    """A made-up plan waiting for approval, with one choice whose recommended answer is free."""
    monkeypatch.setenv("ROUNDTABLE_HOME", str(tmp_path / "home"))
    orch, *_ = make(tmp_path)
    orch.start("build a bakery site", require_approval=True)
    assert orch.run() == "awaiting_approval"
    doc = orch.project.plan_doc()
    doc["decisions"] = [{"id": "D1", "question": "Which colour for the shop?", "recommended": "warm",
                         "options": [{"id": "warm", "label": "Warm browns"}, {"id": "cool", "label": "Cool blues"}]}]
    orch.project.save_plan_doc(doc)
    return orch


def card(orch, aid="choose:D1"):
    return next(a for a in open_asks(orch, answered=True) if a["id"] == aid)


def chosen(orch):
    return orch.project.plan_doc()["decisions"][0].get("chosen")


def test_no_timer_unless_one_is_set(waiting):
    a = asktimer.stamp(card(waiting), waiting.project.root, now=NOW)
    assert "expires_at" not in a
    assert asktimer.sweep(waiting, [card(waiting)], now=NOW + 10 ** 6)[0]["id"] == "choose:D1" and chosen(waiting) is None


def test_it_expires_to_the_recommended_answer(waiting):
    root = waiting.project.root
    asktimer.set_timer(root, card(waiting), 300, "recommended", now=NOW)
    a = asktimer.stamp(card(waiting), root, now=NOW + 10)
    assert a["on_expire"] == "recommended" and a["expires_at"] and not a["held"]
    assert [x["id"] for x in asktimer.sweep(waiting, [card(waiting)], now=NOW + 100)] == ["choose:D1"]  # not yet
    left = asktimer.sweep(waiting, [card(waiting)], now=NOW + 301)
    assert left == [] and chosen(waiting) == "warm"
    assert asktimer.stamp(card(waiting), root)["timed_out"]["did"] == "recommended"


def test_typing_holds_the_clock(waiting):
    root = waiting.project.root
    asktimer.set_timer(root, card(waiting), 120, "recommended", now=NOW)
    asktimer.hold(root, "choose:D1", now=NOW + 100)  # 20 seconds left when they start typing
    assert asktimer.sweep(waiting, [card(waiting)], now=NOW + 150) and chosen(waiting) is None  # held
    asktimer.hold(root, "choose:D1", now=NOW + 180)  # still typing: the 20 seconds are kept, not used up
    assert asktimer.sweep(waiting, [card(waiting)], now=NOW + 180 + asktimer.HOLD_S + 10) and chosen(waiting) is None
    asktimer.sweep(waiting, [card(waiting)], now=NOW + 180 + asktimer.HOLD_S + 21)
    assert chosen(waiting) == "warm"


def test_a_card_that_spends_never_expires_to_its_answer(waiting):
    root = waiting.project.root
    spend = {**card(waiting), "options": [{"id": "warm", "label": "Warm", "confirm": "This spends $5 more."},
                                          {"id": "cool", "label": "Cool"}]}
    with pytest.raises(asktimer.TimerError, match="never answer it for you"):
        asktimer.set_timer(root, spend, 300, "recommended", now=NOW)
    for kind in ("money", "approve", "failed", "command"):
        with pytest.raises(asktimer.TimerError):
            asktimer.set_timer(root, {**card(waiting), "kind": kind}, 300, "recommended", now=NOW)
    approve = card(waiting, "approve")
    asktimer.set_timer(root, approve, 300, "pause", now=NOW)
    out = asktimer.sweep(waiting, [approve], now=NOW + 301)
    assert out[0]["timed_out"]["did"] == "pause" and asktimer.paused(root)["ask"] == "approve"
    assert waiting.project.meta()["status"] == "awaiting_approval"  # nothing was approved, nothing spent


def test_a_card_that_became_one_that_spends_does_nothing_when_it_runs_out(waiting):
    root = waiting.project.root
    asktimer.set_timer(root, card(waiting), 60, "recommended", now=NOW)
    changed = {**card(waiting), "options": [{"id": "warm", "label": "Warm browns", "confirm": "Spends."},
                                            {"id": "cool", "label": "Cool blues"}]}
    out = asktimer.sweep(waiting, [changed], now=NOW + 61)
    assert out[0]["timed_out"]["did"] == "nothing" and chosen(waiting) is None


def test_nothing_leaves_it_waiting(waiting):
    root = waiting.project.root
    asktimer.set_timer(root, card(waiting), 60, "nothing", now=NOW)
    out = asktimer.sweep(waiting, [card(waiting)], now=NOW + 61)
    assert out[0]["timed_out"]["did"] == "nothing" and chosen(waiting) is None


def test_a_late_answer_is_still_applied_when_the_question_is_the_same(waiting):
    root = waiting.project.root
    asktimer.set_timer(root, card(waiting), 60, "recommended", now=NOW)
    seen = card(waiting)["stamp"]
    asktimer.sweep(waiting, [card(waiting)], now=NOW + 61)
    assert chosen(waiting) == "warm"
    asktimer.answer(waiting, "choose:D1", ["cool"], stamp_seen=seen)
    assert chosen(waiting) == "cool"


def test_a_late_answer_on_a_changed_question_is_told_the_moment_passed(waiting):
    root = waiting.project.root
    asktimer.set_timer(root, card(waiting), 60, "recommended", now=NOW)
    seen = card(waiting)["stamp"]
    asktimer.sweep(waiting, [card(waiting)], now=NOW + 61)
    doc = waiting.project.plan_doc()
    doc["decisions"][0]["question"] = "Which colours for the shop and the menu?"  # the plan was revised
    waiting.project.save_plan_doc(doc)
    with pytest.raises(HarnessError, match="The moment has passed") as e:
        asktimer.answer(waiting, "choose:D1", ["cool"], stamp_seen=seen)
    assert "Warm browns" in str(e.value) and "wasn't applied" in str(e.value)


def test_answering_lifts_a_pause(waiting):
    root = waiting.project.root
    asktimer.set_timer(root, card(waiting), 60, "pause", now=NOW)
    asktimer.sweep(waiting, [card(waiting)], now=NOW + 61)
    assert asktimer.paused(root)
    asktimer.answer(waiting, "choose:D1", ["cool"], stamp_seen=card(waiting)["stamp"])
    assert asktimer.paused(root) is None


def test_a_timer_for_an_older_question_doesnt_count(waiting):
    root = waiting.project.root
    asktimer.set_timer(root, {**card(waiting), "stamp": "old"}, 60, "recommended", now=NOW)
    assert "expires_at" not in asktimer.stamp(card(waiting), root, now=NOW)
    asktimer.sweep(waiting, [card(waiting)], now=NOW + 61)
    assert chosen(waiting) is None


def test_a_card_can_bring_its_own_timer(waiting):
    root = waiting.project.root
    a = asktimer.stamp({**card(waiting), "timer": {"minutes": 5, "on_expire": "recommended"}}, root, now=NOW)
    assert a["on_expire"] == "recommended"
    spender = {**card(waiting, "approve"), "timer": {"minutes": 5}}
    assert asktimer.stamp(spender, root, now=NOW)["on_expire"] == "nothing"  # never answers a spending card


def test_limits_on_how_long(waiting):
    root = waiting.project.root
    with pytest.raises(asktimer.TimerError, match="between a minute and a week"):
        asktimer.set_timer(root, card(waiting), 5, "nothing")
    with pytest.raises(asktimer.TimerError):
        asktimer.set_timer(root, card(waiting), 600, "explode")


def test_through_the_app(waiting, tmp_path, monkeypatch):
    from roundtable.ui import server
    from roundtable.ui.server import UIApp

    cfg = waiting.cfg
    cfg.lab_dir = tmp_path / "lab"
    waiting._register_with_lab()
    app = UIApp(str(tmp_path / "missing-hub.yaml"), "missing.yaml")
    app.cfg = lambda: cfg
    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "chatapi"))
    p = str(waiting.project.root)
    c = card(waiting)
    t = app.dispatch("POST", "/api/asktimer", {}, {"path": p, "id": c["id"], "stamp": c["stamp"], "minutes": 10,
                                                  "on_expire": "recommended"})["timer"]
    assert t["on_expire"] == "recommended"
    held = app.dispatch("POST", "/api/asktimer", {}, {"path": p, "id": c["id"], "hold": True})["timer"]
    assert held["held_until"]
    assert app.dispatch("POST", "/api/asktimer", {}, {"path": p, "id": c["id"], "clear": True})["cleared"]
    assert time.time()  # nothing else waits
