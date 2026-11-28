"""Wave 9, step 0: the six routes wave 8's Part B left for the phone, each narrowed to its safe part.

``phone.PHONE_NARROW`` runs after ``phone_allowed`` and before the desktop's dispatch: a body it doesn't accept
is answered 403 with a plain sentence, and nothing reaches the route.
"""

import json

import pytest

from roundtable import agents as agentlib
from roundtable import phone
from roundtable.phone import PC_ONLY, PHONE_NARROW, NarrowRefused, phone_allowed

from .conformance.test_phone_calls import _call, paired  # noqa: F401  (fixture)
from .test_roundtable import setup  # noqa: F401  (fixture)

NEW = [("POST", "/api/asktimer"), ("POST", "/api/board/answer-several"), ("GET", "/api/plan/looks"),
       ("GET", "/api/documents"), ("POST", "/api/agents"), ("POST", "/api/chat/talk")]


@pytest.mark.parametrize("route", NEW)
def test_each_new_route_is_allowed_for_a_phone(route):
    assert phone_allowed(*route)


def test_what_stays_on_the_pc_is_still_refused():
    assert not phone_allowed("POST", "/api/documents")  # adding or removing a folder
    assert not phone_allowed("POST", "/api/agents/remove") and not phone_allowed("POST", "/api/agents/face")
    assert not phone_allowed("POST", "/api/agents/import") and not phone_allowed("GET", "/api/agents/export")
    assert not phone_allowed("POST", "/api/board/move")


def test_every_narrowed_route_is_an_allowed_one():
    assert all(phone_allowed(*k) for k in PHONE_NARROW)


# -- the narrowings, one by one -----------------------------------------------------------------------------
def _refused(route, body, words=PC_ONLY):
    with pytest.raises(NarrowRefused) as e:
        PHONE_NARROW[route](body)
    assert str(e.value) == words
    return e


def test_a_timer_may_only_be_held_from_the_phone():
    t = ("POST", "/api/asktimer")
    assert PHONE_NARROW[t]({"path": "/p", "id": "a1", "hold": True}) == {"path": "/p", "id": "a1", "hold": True}
    _refused(t, {"path": "/p", "id": "a1", "stamp": "s", "minutes": 10, "on_expire": "recommended"})  # set
    _refused(t, {"path": "/p", "id": "a1", "clear": True})
    _refused(t, {"path": "/p", "id": "a1", "hold": True, "minutes": 5})  # a hold carrying a new time
    _refused(t, {"path": "/p", "id": "a1", "hold": "yes"})
    _refused(t, {"path": "/p", "hold": True})  # no card named


def test_only_a_hire_of_an_agent_that_exists_passes():
    a = ("POST", "/api/agents")
    assert PHONE_NARROW[a]({"id": "maelin", "job": "planner", "hire": True}) == {
        "id": "maelin", "job": "planner", "hire": True}
    _refused(a, {"name": "New one", "job": "builder"})  # making one
    _refused(a, {"name": "New one", "job": "builder", "hire": True})  # making one and hiring it
    _refused(a, {"id": "maelin", "name": "Renamed", "job": "planner", "hire": True})  # renaming
    for extra in ("about", "notes", "traits"):
        _refused(a, {"id": "maelin", "job": "planner", "hire": True, extra: "x"})
    _refused(a, {"id": "maelin", "job": "planner"})  # a change of job without the hire


def test_answer_these_takes_plain_items_and_never_a_pc_only_card():
    r = ("POST", "/api/board/answer-several")
    ok = {"items": [{"path": "/p", "id": "plan-q1", "stamp": "s1"}, {"path": "/p", "id": "look", "stamp": "s2"}]}
    assert PHONE_NARROW[r](ok) == ok
    _refused(r, {"items": [{"path": "/p", "id": "shipoffer-1", "stamp": "s"}]},
             "One of the ticked cards can only be answered on the PC itself.")
    _refused(r, {"items": [{"path": "/p", "id": "q1", "stamp": "s", "chosen": "delete everything"}]})
    _refused(r, {"items": [{"path": "/p", "id": "q1"}], "confirm": True})
    _refused(r, {"items": ["q1"]})
    _refused(r, {"items": "q1"}, "Tick the cards to answer first.")


def test_talk_takes_only_the_words_heard():
    t = ("POST", "/api/chat/talk")
    assert PHONE_NARROW[t]({"path": "/p", "text": "how is it going?"}) == {"path": "/p", "text": "how is it going?"}
    _refused(t, {"path": "/p", "text": "run it", "confirmed": True})
    _refused(t, {"path": "/p", "text": "x" * (phone.TALK_MAX + 1)},
             "That's too long to send from the phone: say it in under 2,000 characters.")
    assert PHONE_NARROW[t]({"path": "/p", "text": "x" * phone.TALK_MAX})["text"] == "x" * phone.TALK_MAX


# -- through the real phone server ----------------------------------------------------------------------------
def test_the_phone_server_refuses_with_the_plain_sentence_and_lets_the_safe_part_through(paired):  # noqa: F811
    app, orch, p, token, tmp = paired
    orch._register_with_lab()
    orch.start("bakery site", require_approval=True)
    orch.run()
    path = str(orch.project.root)
    called = []
    real = app.dispatch

    def spy(method, route, q, body):
        called.append((method, route, json.dumps(body, sort_keys=True)))
        return real(method, route, q, body)

    app.dispatch = spy

    def post(route, body):
        status, text = _call(p.port, "POST", route, body, token)
        return status, json.loads(text or "{}")

    refused = [
        ("/api/asktimer", {"path": path, "id": "plan-q1", "stamp": "s", "minutes": 10}),  # a timer set
        ("/api/asktimer", {"path": path, "id": "plan-q1", "clear": True}),
        ("/api/agents", {"name": "Made-up", "job": "builder"}),  # an agent made
        ("/api/agents", {"id": "maelin", "name": "Renamed", "job": "planner", "hire": True}),  # renamed
        ("/api/board/answer-several", {"items": [{"path": path, "id": "shipoffer", "stamp": "s"}]}),  # PC only
    ]
    for route, body in refused:
        status, data = post(route, body)
        assert status == 403 and data["error"].endswith("on the PC itself."), (route, body, data)
    assert called == []  # nothing refused reached the desktop's routes
    status, _ = _call(p.port, "POST", "/api/documents", {"folder": str(tmp)}, token)
    assert status == 403

    status, data = post("/api/asktimer", {"path": path, "id": "plan-q1", "hold": True})
    assert status == 200 and "timer" in data
    status, data = post("/api/agents", {"id": "maelin", "job": "planner", "hire": True})
    assert status == 200 and data["agent"]["id"] == "maelin"
    assert agentlib.get(app._backup_home(), "maelin").name == "Maelin"  # nothing but the hire changed
    status, data = post("/api/board/answer-several", {"items": [{"path": path, "id": "no-such-card", "stamp": "s"}]})
    assert status == 200 and "left" in data
    status, _ = _call(p.port, "GET", "/api/documents", None, token)
    assert status == 200
    assert [c[1] for c in called] == ["/api/asktimer", "/api/agents", "/api/board/answer-several", "/api/documents"]
