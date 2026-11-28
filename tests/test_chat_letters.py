"""Letters folded into the chat (1.5.0): old letters read-only under Earlier messages in the chat they belong to,
``inbox/`` byte for byte unchanged; a ``roundtable:`` command as one plain line with its reply; an agent's
letter to the owner a chat message, agent to agent a folded grey line. Made-up hub and projects."""

from __future__ import annotations

import hashlib
import json

import pytest

from roundtable import chat, chatstore

from .chatworld import World


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def inbox_digest(world) -> str:
    h = hashlib.sha256()
    for p in sorted((world.tmp / "hubdata" / "inbox").rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(world.tmp)).encode() + p.read_bytes())
    return h.hexdigest()


def letters(world):
    hub = world.hub
    cmd = hub.send("me", ["harness"], "roundtable: approve",
                   json.dumps({"action": "approve", "project_folder": "proj"}), kind="request")[0]
    hub.mark_read("harness", [cmd["id"]])
    rep = hub.reply("harness", cmd["id"], "Approved and started. The run ended as: done.")
    hub.mark_read("me", [rep["id"]])
    talk = hub.send("me", ["website"], "Colours", "Use the bakery's gold, please.", kind="ask")[0]
    hub.mark_read("website", [talk["id"]])
    told = hub.send("website", ["harness"], "API moved", "The prices API is at /v2 now.", kind="notify")[0]
    new = hub.send("website", ["me"], "Done", "The page is live.", kind="notify")[0]
    return cmd, rep, talk, told, new


def test_old_letters_sit_under_earlier_in_the_right_chat_and_inbox_is_untouched(world):
    cmd, rep, talk, told, new = letters(world)
    before = inbox_digest(world)
    proj = world.read()["earlier"]
    site = world.read(chatstore.chat_id("website"))["earlier"]
    assert all(x["earlier"] for x in proj) and world.read(since="1970")["lines"] == []
    assert inbox_digest(world) == before  # nothing in inbox/ is written; read marks live in state/
    assert {x["id"] for x in proj if x["id"].startswith("earlier-")} == {
        "earlier-" + cmd["id"], "earlier-" + rep["id"], "earlier-" + told["id"]}
    by = {x["id"]: x for x in proj}
    c = by["earlier-" + cmd["id"]]
    assert c["who"] == "owner" and c["text"] == "You asked it to approve and build · done"
    r = by["earlier-" + rep["id"]]
    assert r["who"] == "project" and r["text"] == "Approved and started. The run ended as: done."
    g = by["earlier-" + told["id"]]
    assert g["who"] == "agent" and g["from"] == "website" and g["to"] == "harness" and "/v2" in g["text"]
    assert "earlier-" + talk["id"] in {x["id"] for x in site} and "earlier-" + told["id"] in {x["id"] for x in site}
    # the old letters are only shown: a reader can't answer or tap them
    assert all("card" not in x for x in proj if x["id"].startswith("earlier-"))


def test_an_unread_letter_to_the_owner_becomes_a_chat_message_once(world):
    *_, new = letters(world)
    site = chatstore.chat_id("website")
    got = world.read(site)
    lines = got["lines"]
    assert not any(x["id"] == "earlier-" + new["id"] for x in got["earlier"])
    msg = [x for x in lines if x["id"] == "letter-" + new["id"]]
    assert len(msg) == 1 and msg[0]["who"] == "project" and "The page is live." in msg[0]["text"]
    assert world.hub.inbox("me", unread_only=True) == []  # counted read
    r = world.read(site)
    again = r["lines"] + r["earlier"]
    assert sum(1 for x in again if x["id"].endswith(new["id"])) == 1  # not twice, and not under Earlier too
    chats = {c["id"]: c for c in world.app.dispatch("GET", "/api/chats", {}, {})["chats"]}
    assert list(chats)[0] == "hall" and site in chats and world.chat in chats
    assert chats[site]["unread"] == 0  # read just now: the count drops
    chatstore.append(world.home, world.hub, site, {"who": "project", "seat": "", "text": "One more thing."})
    chats = {c["id"]: c for c in world.app.dispatch("GET", "/api/chats", {}, {})["chats"]}
    assert chats[site]["unread"] == 1
    world.read(site)
    assert {c["id"]: c for c in world.app.dispatch("GET", "/api/chats", {}, {})["chats"]}[site]["unread"] == 0


def test_a_reply_to_a_command_sent_from_the_chat_lands_in_the_chat(world):
    """remote.process's hook-up: a request carrying chat_turn is answered with chat.command_done."""
    shop_line = chatstore.append(world.home, world.hub, world.chat, {"who": "chat", "seat": chatstore.me()["id"],
                                                                     "text": "ok", "answers": "o1", "card": {
        "id": "c1", "title": "Build", "line": "About $1.", "command": "/run", "state": "queued",
        "buttons": [{"id": "cancel", "words": "Cancel"}]}})
    cmd = {"action": "run", "chat": world.chat, "chat_turn": "o1", "chat_card": "c1"}
    assert chat.command_done(world.hub, world.tmp / "pc2", cmd, "The run ended as: done.")
    got = world.read()["lines"]
    said = next(x for x in got if x["who"] == "project")
    assert said["text"] == "The run ended as: done." and said["answers"] == "o1"
    assert next(x for x in got if x["id"] == shop_line["id"])["card"]["state"] == "done"
    assert world.hub.inbox("me", unread_only=False) == []  # no letter


def test_wrote_to_you_counts_a_projects_new_message_until_the_chat_is_read(world):
    *_, new = letters(world)
    chatstore.bring_in_letters(world.home, world.hub)
    rows = chat.wrote_to_you(world.app)
    assert [(r["chat"], r["text"]) for r in rows] == [(chatstore.chat_id("website"), "Website wrote to you")]
    world.read(chatstore.chat_id("website"))
    assert chat.wrote_to_you(world.app) == []
