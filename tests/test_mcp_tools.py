"""MCP servers' tools for roles (harness/mcp_tools.py): config, listing, calls, failures, shutdown.

The server is a real tiny MCP server run over stdio (tests/fixtures/fake_mcp_server.py); no network.
"""

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from roundtable.harness.config import parse_config
from roundtable.harness.mcp_tools import MCPPool, check_servers, result_text, tool_name
from roundtable.harness.orchestrator import Orchestrator
from roundtable.harness.tools import ToolError
from roundtable.providers.scripted import ScriptedProvider, reply

FAKE = str(Path(__file__).parent / "fixtures" / "fake_mcp_server.py")


def fake(**extra):
    return {"command": sys.executable, "args": [FAKE], **extra}


def base(**extra):
    raw = {"providers": {"a": {"type": "scripted"}},
           "roles": {"orchestrator": {"model": "a/planner"}, "reviewer": {"model": "a/reviewer"}}}
    raw.update(extra)
    return raw


def wait_for(cond, seconds=15.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


# -- config ------------------------------------------------------------------------------------------
def test_config_reads_both_kinds_of_server_and_role_opt_in():
    cfg = parse_config(base(
        mcp_servers={"unreal": {"url": "http://127.0.0.1:8000/mcp", "timeout": 300},
                     "editor": {"command": "uvx", "args": ["some-server", 3], "env": {"MODE": 1},
                                "tools": "get_*", "enabled": False}},
        roles={"orchestrator": {"model": "a/p"}, "unreal_builder": {"model": "a/b", "mcp": ["unreal"]}}))
    assert cfg.mcp_servers["unreal"] == {"enabled": True, "timeout": 300.0, "url": "http://127.0.0.1:8000/mcp",
                                         "headers": {}}
    ed = cfg.mcp_servers["editor"]
    assert ed["args"] == ["some-server", "3"] and ed["env"] == {"MODE": "1"} and ed["tools"] == ["get_*"]
    assert ed["enabled"] is False and ed["timeout"] == 120.0
    assert cfg.roles["unreal_builder"].mcp == ["unreal"]
    assert cfg.roles["orchestrator"].mcp == []
    assert parse_config(base()).mcp_servers == {}


@pytest.mark.parametrize("servers, roles, words", [
    ({"x": {}}, None, "exactly one of command"),
    ({"x": {"command": "a", "url": "http://h/mcp"}}, None, "exactly one of command"),
    ({"x": {"url": "ftp://h"}}, None, "http://"),
    ({"x": {"url": "http://h/mcp", "args": ["a"]}}, None, "only for a server with command"),
    ({"x": {"command": "a", "headers": {"k": "v"}}}, None, "only for a server with url"),
    ({"x": {"command": "a", "timeout": "soon"}}, None, "number of seconds"),
    ({"x": {"command": "a", "timeout": 0}}, None, "more than 0"),
    ({"x": {"command": "a", "enabled": "yes"}}, None, "true or false"),
    ({"x": {"command": "a", "colour": "red"}}, None, "unknown setting"),
    ({"bad name": {"command": "a"}}, None, "letters, digits"),
    (["x"], None, "mapping"),
    ({"x": {"command": "a"}}, {"w": {"model": "a/w", "mcp": ["nope"]}}, "no such server"),
    ({"x": {"command": "a"}}, {"w": {"model": "a/w", "kind": "image", "mcp": ["x"]}}, "only chat roles"),
])
def test_config_errors_are_plain(servers, roles, words):
    raw = base(mcp_servers=servers)
    if roles:
        raw["roles"] = {**raw["roles"], **roles}
    with pytest.raises(ValueError, match=words):
        parse_config(raw)


# -- the pool ----------------------------------------------------------------------------------------
def test_names_are_sanitised_and_short():
    assert tool_name("unreal", "get_blueprint") == "mcp__unreal__get_blueprint"
    assert tool_name("ue", "assets/list.v2") == "mcp__ue__assets_list_v2"
    assert len(tool_name("s", "x" * 200)) == 64


def test_role_without_mcp_sees_no_mcp_tools(tmp_path):
    raw = base(mcp_servers={"editor": fake()})
    orch, _, _ = _orch(tmp_path, raw, lambda *a: reply("hi"))
    box = orch.ws.toolbox(None)
    orch._add_mcp_tools(box, orch.cfg.roles["orchestrator"])
    assert not [n for n in box.tools if n.startswith("mcp__")]
    assert orch._mcp is None  # nothing was started


def test_list_call_error_and_clean_shutdown(tmp_path):
    log = tmp_path / "server.log"
    events = []
    pool = MCPPool({"editor": fake(env={"FAKE_MCP_LOG": str(log)}, tools=["spawn_*", "get_*", "call_tool", "fail",
                                                                            "snapshot"])},
                   lambda k, d: events.append((k, d)))
    try:
        tools = {t.spec.name: t for t in pool.tools_for(["editor"])}
        assert set(tools) == {"mcp__editor__spawn_actor", "mcp__editor__get_blueprint", "mcp__editor__call_tool",
                              "mcp__editor__fail", "mcp__editor__snapshot"}
        spawn = tools["mcp__editor__spawn_actor"]
        assert spawn.spec.description.startswith("[MCP server editor] Put an actor")
        assert spawn.spec.parameters["type"] == "object" and "name" in spawn.spec.parameters["properties"]
        assert tools["mcp__editor__get_blueprint"].spec.description.endswith("(read-only)")
        assert events[0][0] == "mcp_tools"

        assert spawn.fn({"name": "Cube", "x": 2}) == "spawned Cube at (2.0, 0.0)"
        assert "héllo" in tools["mcp__editor__get_blueprint"].fn({"path": "/Game/BP_Door"})
        assert tools["mcp__editor__snapshot"].fn({}).startswith("[image image/png, ")
        # a nested object sent as a JSON string is decoded (some models do that)
        assert tools["mcp__editor__call_tool"].fn({"tool": "t", "arguments": json.dumps({"a": 1})}) \
            == "called t with [('a', 1)]"
        with pytest.raises(ToolError):
            tools["mcp__editor__fail"].fn({})
        # listed once per run
        assert pool.tools_for(["editor"])[0] is pool.tools_for(["editor"])[0]
        assert wait_for(lambda: log.read_text(encoding="utf-8").startswith("started"))
    finally:
        pool.close()
    assert wait_for(lambda: "stopped" in log.read_text(encoding="utf-8")), "the server didn't stop cleanly"
    assert not [t for t in threading.enumerate() if t.name.startswith("mcp-editor")]


def test_allow_list_keeps_only_matching_tools():
    pool = MCPPool({"editor": fake(tools=["get_*"])})
    try:
        assert [t.spec.name for t in pool.tools_for(["editor"])] == ["mcp__editor__get_blueprint"]
    finally:
        pool.close()


def test_server_that_cannot_start_is_reported_and_skipped():
    events = []
    pool = MCPPool({"ghost": {"command": "no-such-program-for-roundtable-tests", "args": []},
                    "off": {**fake(), "enabled": False}}, lambda k, d: events.append((k, d)))
    try:
        assert pool.tools_for(["ghost", "off"]) == []
        assert pool.tools_for(["ghost"]) == []  # tried once per run
    finally:
        pool.close()
    errors = [d for k, d in events if k == "mcp_error"]
    assert len(errors) == 1 and errors[0]["server"] == "ghost"
    assert "couldn't be started" in errors[0]["error"] and "then try again" in errors[0]["error"]


def test_error_result_text_and_other_content():
    class Block:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class Res:
        uri = "file:///level.umap"
        mime_type = "application/octet-stream"
        blob = "A" * 4096

    r = Block(content=[Block(type="text", text="one"), Block(type="resource", resource=Res()),
                       Block(type="audio", mime_type="audio/wav", data="")], structured_content=None)
    assert result_text(r) == "one\n[file file:///level.umap, application/octet-stream, 3 KB]\n[audio audio/wav, 1 KB]"
    assert result_text(Block(content=[], structured_content={"ok": 1})) == '{\n  "ok": 1\n}'


def test_check_servers_for_the_cli():
    rows = {r["server"]: r for r in check_servers({"editor": fake(tools=["get_*"]),
                                                   "ghost": {"command": "no-such-program-for-roundtable-tests"},
                                                   "off": {"command": "x", "enabled": False}})}
    assert rows["editor"]["ok"] is True and rows["editor"]["tools"] == ["mcp__editor__get_blueprint"]
    assert rows["ghost"]["ok"] is False and "couldn't be started" in rows["ghost"]["error"]
    assert rows["off"]["ok"] is None


# -- in a real run -----------------------------------------------------------------------------------
PLAN = [{"id": "T1", "title": "door blueprint", "role": "unreal_builder", "description": "spawn the door",
         "acceptance": "a door is in the level", "depends_on": []}]


def _orch(tmp_path, raw, brain):
    cfg = parse_config(json.loads(json.dumps(raw)))
    a = ScriptedProvider("a", brain)
    cfg.register("a", a)
    events = []
    orch = Orchestrator(cfg, tmp_path / "proj", on_event=lambda k, d: events.append((k, d)))
    return orch, a, events


def test_worker_calls_an_mcp_tool_and_finishes(tmp_path):
    log = tmp_path / "server.log"
    raw = base(mcp_servers={"editor": fake(env={"FAKE_MCP_LOG": str(log)}),
                            "ghost": {"command": "no-such-program-for-roundtable-tests"}})
    raw["roles"]["unreal_builder"] = {"model": "a/builder", "mcp": ["editor", "ghost"]}
    seen = {}

    def brain(model, system, messages, tools):
        names = {t.name for t in tools}
        last = messages[-1]
        if "submit_plan" in names:
            return reply("planned") if last["role"] == "tool" else reply(calls=[("submit_plan", {"tasks": PLAN})])
        if "submit_review" in names:
            seen["review_tools"] = names
            if last["role"] == "tool":
                return reply("ok")
            return reply(calls=[("submit_review", {"approved": True, "feedback": "door is there"})])
        if "finish_task" in names:
            seen["worker_tools"] = names
            if last["role"] == "user":
                return reply(calls=[("mcp__editor__spawn_actor", {"name": "Door", "x": 1})])
            seen["result"] = last["content"]
            return reply(calls=[("finish_task", {"summary": "door spawned"})])
        return reply("Final report: done.")

    orch, _, events = _orch(tmp_path, raw, brain)
    orch.start("a door")
    from roundtable.harness import perms

    # under Careful (the default) a tool server's first use in a project waits for a tap (wave 8): the owner
    # said "Always allow" for this one earlier
    perms.allow(orch.project.root, "mcp", "mcp__editor__spawn_actor")
    assert orch.run() == "done"
    assert seen["result"] == "spawned Door at (1.0, 0.0)"
    assert "mcp__editor__spawn_actor" in seen["worker_tools"]
    assert not [n for n in seen["review_tools"] if n.startswith("mcp__")]  # the reviewer didn't list mcp
    assert any(k == "mcp_error" and d["server"] == "ghost" for k, d in events)
    calls = [d for k, d in events if k == "tool_call" and d["tool"] == "mcp__editor__spawn_actor"]
    assert calls and calls[0]["error"] is False
    assert orch._mcp is None  # closed when the run ended
    assert wait_for(lambda: "stopped" in log.read_text(encoding="utf-8"))


def test_a_server_over_http_like_unreal(tmp_path):
    """The fake editor served over streamable HTTP, the way Unreal's editor serves its tools."""
    import os
    import socket
    import subprocess

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "FAKE_MCP_PORT": str(port), "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen([sys.executable, FAKE], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        def answering():
            with socket.socket() as c:
                return c.connect_ex(("127.0.0.1", port)) == 0
        assert wait_for(answering, 20), "the fake HTTP server didn't start"
        pool = MCPPool({"unreal": {"url": f"http://127.0.0.1:{port}/mcp", "timeout": 30}})
        try:
            tools = {t.spec.name: t for t in pool.tools_for(["unreal"])}
            assert "mcp__unreal__spawn_actor" in tools
            assert tools["mcp__unreal__spawn_actor"].fn({"name": "Door"}) == "spawned Door at (0.0, 0.0)"
            assert "héllo" in tools["mcp__unreal__get_blueprint"].fn({"path": "/Game/BP_Door"})
        finally:
            pool.close()
    finally:
        proc.terminate()
        proc.wait(10)
