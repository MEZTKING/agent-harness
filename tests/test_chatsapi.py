"""The chat's routes (ui/chatsapi.py, 1.5.0): the frozen shapes filled in, the phone's narrower tap, Stop, the
files, and no route ever hands out a key. Scripted models, a made-up hub and project."""

from __future__ import annotations

import base64
import json
import threading

import pytest

from roundtable import chatstore, phone
from roundtable.ui import chatsapi
from roundtable.ui.server import ApiError

from .chatworld import World

SECRET = "sk-" + "Zq9" * 9


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def test_the_routes_in_their_shapes(world):
    world.model.answers = ["All three tasks are done."]
    got = world.say("how is it?")
    assert set(got) == {"line", "turn"} and got["line"]["who"] == "owner"
    r = world.read()
    assert set(r) == {"lines", "at", "answering", "can", "seat", "earlier"} and r["can"] == {"answer": True, "why": ""}
    assert r["seat"] == chatstore.me()["id"] and "earlier" not in world.read(since=r["at"])
    assert r["lines"][-1]["id"] == got["turn"] and r["lines"][-1]["text"] == "All three tasks are done."
    assert world.read(since=r["at"])["lines"] == []
    chats = world.app.dispatch("GET", "/api/chats", {}, {})["chats"]
    assert chats[0]["id"] == "hall" and {"id", "name", "last", "unread", "waiting"} == set(chats[0])
    mine = next(c for c in chats if c["id"] == world.chat)
    assert mine["name"] == "Proj" and mine["unread"] == 0 and mine["last"] == "All three tasks are done."
    with pytest.raises(ApiError):
        world.app.dispatch("POST", "/api/chats/say", {}, {"chat": world.chat, "text": ""})
    with pytest.raises(ApiError):
        world.app.dispatch("POST", "/api/chats/say", {}, {"chat": "no-such-chat", "text": "hi"})


def test_stop_ends_the_answer_and_keeps_what_was_written(world):
    go, hold = threading.Event(), threading.Event()

    def slow(model, system, messages, tools):
        go.set()
        hold.wait(5)
        return "never seen"

    world.model.answers = [slow]
    world.deepseek.chunks = [[("text", "Half an "), ("text", "answer and more")]]
    got = world.app.dispatch("POST", "/api/chats/say", {}, {"chat": world.chat, "text": "long one"})
    go.wait(5)
    assert world.app.dispatch("POST", "/api/chats/stop", {}, {"chat": world.chat, "turn": got["turn"]}) == {
        "stopped": True}
    hold.set()
    assert chatsapi.wait(world.chat)
    last = world.last()
    assert last["id"] == got["turn"] and "You stopped it here" in last["text"]
    assert world.app.dispatch("POST", "/api/chats/stop", {}, {"chat": world.chat, "turn": got["turn"]}) == {
        "stopped": False}


def test_a_picture_goes_in_with_the_paper_clip_and_comes_back(world):
    from roundtable import attachments as att

    from .test_chatstore import _jpeg_with_location

    att.Draft(world.home, "chat:pc").add("shot.jpg", _jpeg_with_location(300))
    world.say("look", key="chat:pc")
    f = world.last("owner")["files"][0]
    assert f["kind"] == "picture" and att.Draft(world.home, "chat:pc").empty
    got = world.app.dispatch("GET", "/api/chats/file", {"chat": [world.chat], "name": [f"{f['sha']}.{f['ext']}"]}, {})
    assert got["type"] == "image/jpeg" and base64.b64decode(got["data"].split(",", 1)[1])[:2] == b"\xff\xd8"
    by_name = world.app.dispatch("GET", "/api/chats/file", {"chat": [world.chat], "name": ["shot.jpg"]}, {})
    assert by_name["data"] == got["data"]
    for bad in ("../../hub.yaml", "x"):
        with pytest.raises(ApiError):
            world.app.dispatch("GET", "/api/chats/file", {"chat": [world.chat], "name": [bad]}, {})


def test_no_route_ever_returns_a_key(world):
    world.model.answers = [f"Your key {SECRET} works.", f"Again {SECRET}"]
    got = world.say(f"is my key {SECRET} right?")
    outs = [got, world.read(), world.app.dispatch("GET", "/api/chats", {}, {})]
    assert all(SECRET not in json.dumps(o) for o in outs)
    texts = [x["text"] for x in world.read()["lines"]]
    assert any("hid something that looked like a key" in t for t in texts)
    for p in list((world.tmp / "hubdata").rglob("*.jsonl")) + list(world.home.rglob("*.jsonl")):
        assert SECRET not in p.read_text(encoding="utf-8")
    assert SECRET not in json.dumps(world.model.sent)  # nor sent to the model


def test_the_phones_tap_refuses_a_pc_only_command(world):
    world.model.answers = ["Running them.\nAction: /test"]
    world.say("run the tests")
    card = world.last()["card"]
    narrow = phone.PHONE_NARROW[("POST", "/api/chats/tap")]
    body = narrow({"chat": world.chat, "card": card["id"]})
    with pytest.raises(ApiError, match="only in the PC's own app"):
        world.app.dispatch("POST", "/api/chats/tap", {}, body)
    assert world.last()["card"]["state"] == "open"


def test_hall_streams_under_the_apps_folder(world):
    world.model.answers = ["Nothing waits for you."]
    world.say("anything?", chat="hall")
    assert (world.home / "chat-live").is_dir()
    assert "chat-live" not in chatstore.chat_dirs(world.home, world.hub)
