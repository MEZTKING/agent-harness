import asyncio
import json

from agentharness.hub.mcp_server import build_server

from .test_hub import make_hub


def _text(result) -> str:
    # call_tool may return a list of content blocks or a (content, structured) tuple
    if isinstance(result, tuple):
        result = result[0]
    if hasattr(result, "content"):
        result = result.content
    return result[0].text


def test_mcp_tools_roundtrip(tmp_path):
    hub = make_hub(tmp_path)
    fe = build_server(hub, "frontend")
    be = build_server(hub, "backend")

    async def go():
        names = {t.name for t in await fe.list_tools()}
        assert {"hub_inbox", "hub_send", "hub_read_card", "hub_update_card", "hub_reply"} <= names

        sent = json.loads(_text(await fe.call_tool("hub_send", {
            "to": ["backend"], "subject": "q", "body": "what port?"})))
        msg_id = sent["sent"][0]["id"]

        inbox = json.loads(_text(await be.call_tool("hub_inbox", {})))
        assert inbox[0]["id"] == msg_id

        await be.call_tool("hub_reply", {"message_id": msg_id, "body": "8080"})
        await be.call_tool("hub_update_card", {"status": "serving on 8080", "change_note": "port 8080"})
        card = json.loads(_text(await fe.call_tool("hub_read_card", {"agent_id": "backend"})))
        assert card["status"] == "serving on 8080"

    asyncio.run(go())
