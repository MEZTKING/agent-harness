"""One message to every agent (hub/service.py ``to="everyone"``, MD-12): each other agent once, never the sender,
all in one thread; replies go back to the sender only; the hop cap still stops a conversation going round."""

import json

import pytest

from roundtable.core.config import parse_config
from roundtable.core.store import FileStore
from roundtable.hub.service import EVERYONE, HOP_CAP, Hub, HubError

RAW = {"storage": {"type": "file", "path": "data"}, "default_policy": "deny",
       "agents": {"lead": {}, "api": {}, "web": {}, "app": {}, "private": {}},
       "rules": [{"from": "*", "to": "*", "allow": ["read_card", "message"]},
                 {"from": "lead", "to": "private", "deny": ["message"]}]}


def make_hub(tmp_path, raw=RAW):
    return Hub(parse_config(raw, tmp_path / "hub.yaml"), store=FileStore(tmp_path / "data"))


def test_everyone_reaches_each_other_agent_once_in_one_thread(tmp_path):
    hub = make_hub(tmp_path)
    sent = hub.send("lead", EVERYONE, "Release on Friday", "Please finish what you're on.", kind="notify")
    to = sorted(m["recipient"] for m in sent)
    assert to == ["api", "app", "web"]  # never the sender; not the one the rules say lead may not message
    assert len({m["thread_id"] for m in sent}) == 1
    for agent in ("api", "app", "web"):
        assert len(hub.inbox(agent)) == 1
    assert hub.inbox("lead") == [] and hub.inbox("private") == []
    # a name listed as well is not sent twice
    again = hub.send("lead", ["api", EVERYONE], "Again", "x")
    assert sorted(m["recipient"] for m in again) == ["api", "app", "web"]


def test_replies_go_to_the_sender_only_in_the_same_thread(tmp_path):
    hub = make_hub(tmp_path)
    sent = hub.send("lead", [EVERYONE], "Who is free?", "Say if you can take a task.")
    thread = sent[0]["thread_id"]
    api_msg = hub.inbox("api")[0]
    r = hub.reply("api", api_msg["id"], "I can.")
    assert r["recipient"] == "lead" and r["thread_id"] == thread
    assert len(hub.inbox("lead")) == 1 and len(hub.inbox("web")) == 1  # web hears nothing of api's answer
    assert len(hub.thread("lead", thread)) == 4


def test_everyone_bounces_past_the_hop_cap(tmp_path):
    hub = make_hub(tmp_path)
    first = hub.send("lead", "api", "ping", "0")[0]
    # api answers with a message to everyone, deep in a long conversation
    hub.store.write_json({f"inbox/api/{first['id']}.json": {**first, "hops": HOP_CAP}}, "deep")
    out = hub.send("api", EVERYONE, "Re: ping", "again", in_reply_to=first["id"])
    assert len(out) == 1 and out[0]["bounced"] and out[0]["recipient"] == "api"
    assert sorted(out[0]["bounced_to"]) == ["app", "lead", "private", "web"]
    assert hub.inbox("web") == []


def test_everyone_with_nobody_to_send_to_says_so(tmp_path):
    raw = {**RAW, "agents": {"solo": {}}}
    with pytest.raises(HubError, match="nobody to send to"):
        make_hub(tmp_path, raw).send("solo", EVERYONE, "x", "y")
    clash = {**RAW, "agents": {"everyone": {}, "lead": {}}}
    with pytest.raises(HubError, match="ambiguous"):
        make_hub(tmp_path, clash).send("lead", EVERYONE, "x", "y")


def test_hub_send_tool_takes_everyone(tmp_path):
    pytest.importorskip("mcp")
    import asyncio

    from roundtable.hub.mcp_server import build_server

    hub = make_hub(tmp_path)
    server = build_server(hub, "lead")

    from .test_mcp import _text

    async def go():
        return json.loads(_text(await server.call_tool("hub_send", {"to": ["everyone"], "subject": "Hello", "body": "all"})))

    out = asyncio.run(go())
    assert sorted(m["to"] for m in out["sent"]) == ["api", "app", "web"] and out["thread_id"]
