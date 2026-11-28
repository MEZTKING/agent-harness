"""Answer several (wave 8, p1-board: MD-42): the recommended answer for the ticked cards, each with its own stamp.
Cards whose recommended answer spends money or can't be undone, and commands, are left to be answered alone.

Made-up projects in tmp_path, scripted models.
"""

from roundtable import asks
from roundtable.ui import boardapi

from .test_board import board_orch, set_status


def blocked(tmp_path):
    o = board_orch(tmp_path)
    set_status(o, T3="failed", T4="failed")
    meta = o.project.meta()
    meta["status"] = "blocked"
    o.project.save_meta(meta)
    return o


def test_the_recommended_answer_for_each_ticked_card(tmp_path):
    o = blocked(tmp_path)
    cards = [a for a in asks.open_asks(o) if a["kind"] == "failed"]
    assert {a["id"] for a in cards} == {"task:T3", "task:T4"}
    r = boardapi.answer_several(o, [{"id": a["id"], "stamp": a["stamp"]} for a in cards])
    assert [a["id"] for a in r["answered"]] == ["task:T3", "task:T4"] and not r["left"]
    assert {t.id: t.status for t in o.project.tasks()}["T3"] == "pending"  # retried, as its recommended answer says
    assert r["then"]["then"] == "run" and r["reply"] == "2 answered with the recommended answer."


def test_a_changed_question_is_refused_as_when_answered_alone(tmp_path):
    o = blocked(tmp_path)
    cards = {a["id"]: a for a in asks.open_asks(o)}
    r = boardapi.answer_several(o, [{"id": "task:T3", "stamp": "not-the-same"},
                                    {"id": "task:T4", "stamp": cards["task:T4"]["stamp"]}])
    assert [a["id"] for a in r["answered"]] == ["task:T4"]
    assert r["left"] == [{"id": "task:T3", "why": "That question changed since you saw it. Look at it again, then answer."}]
    assert {t.id: t.status for t in o.project.tasks()}["T3"] == "failed"
    r = boardapi.answer_several(o, [{"id": "task:T3"}])  # no stamp at all: never guessed
    assert r["left"][0]["why"].startswith("It was sent without the question")


def test_cards_that_need_a_yes_and_commands_are_left_alone(tmp_path, monkeypatch):
    o = blocked(tmp_path)
    real = asks.open_asks
    spend = asks._ask("money", "money", "Money", "Carry on?", [
        {"id": "more", "label": "Carry on with $2.00 more", "confirm": "This spends up to $2.00 more. Carry on?"},
        {"id": "stop", "label": "Stop here"}], recommended="more")
    command = asks._ask("command:abc", "command", "Command", "Run rm -rf build?", [
        {"id": "allow", "label": "Allow once"}, {"id": "deny", "label": "Don't allow"}], recommended="allow")
    monkeypatch.setattr(asks, "open_asks", lambda orch, answered=False: real(orch, answered) + [spend, command])
    applied = []
    monkeypatch.setitem(asks.APPLY, "money", lambda *a: applied.append(a) or {"reply": "x", "then": None})
    monkeypatch.setitem(asks.APPLY, "command", lambda *a: applied.append(a) or {"reply": "x", "then": None})
    t3 = next(a for a in asks.open_asks(o) if a["id"] == "task:T3")
    r = boardapi.answer_several(o, [{"id": "money", "stamp": spend["stamp"]}, {"id": "command:abc", "stamp": command["stamp"]},
                                    {"id": "task:T3", "stamp": t3["stamp"]}])
    assert applied == [] and [a["id"] for a in r["answered"]] == ["task:T3"]
    why = {x["id"]: x["why"] for x in r["left"]}
    assert why["money"].startswith("Its recommended answer spends money") and why["command:abc"].startswith("A command")
    assert r["reply"] == "1 answered with the recommended answer; 2 left for you to answer on their own."


def test_needs_alone_words():
    assert boardapi.needs_alone({"kind": "decision", "recommended": None, "options": []}) == "It has no recommended answer."
    assert boardapi.needs_alone({"kind": "decision", "recommended": "a", "options": [{"id": "a"}]}) == ""
