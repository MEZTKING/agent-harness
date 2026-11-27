"""A tiny made-up MCP server for the tests (stdio), shaped a little like a game editor's.

Run with ``python fake_mcp_server.py``. Its tools: ``spawn_actor``, ``get_blueprint`` (read-only),
``snapshot`` (returns a picture), ``call_tool`` (nested arguments, like a tool-search server's)
and ``fail`` (always an error). With ``FAKE_MCP_LOG`` set it notes when it starts and stops.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Image, MCPServer
from mcp_types import ToolAnnotations

server = MCPServer(name="fake-editor")

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


@server.tool()
def spawn_actor(name: str, x: float = 0.0, y: float = 0.0) -> str:
    """Put an actor in the level."""
    return f"spawned {name} at ({x}, {y})"


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def get_blueprint(path: str) -> str:
    """Read a blueprint's graph."""
    return f"blueprint {path}: Event BeginPlay -> Print String 'héllo'"


@server.tool()
def snapshot() -> Image:
    """A picture of the viewport."""
    return Image(data=PNG, format="png")


@server.tool()
def call_tool(tool: str, arguments: dict[str, Any]) -> str:
    """Call another tool by name with nested arguments."""
    return f"called {tool} with {sorted(arguments.items())}"


@server.tool()
def fail(reason: str = "no level open") -> str:
    """Always fails."""
    raise ValueError(reason)


if __name__ == "__main__":
    # FAKE_MCP_LOG: a file where the server notes "started" and, on a clean shutdown, "stopped"
    log = os.environ.get("FAKE_MCP_LOG")
    if log:
        Path(log).write_text("started\n", encoding="utf-8")
    env_log = os.environ.get("FAKE_MCP_ENV_LOG")  # set: the whole environment it was given, as JSON
    if env_log:
        import json

        Path(env_log).write_text(json.dumps(dict(os.environ)), encoding="utf-8")
    port = os.environ.get("FAKE_MCP_PORT")  # set: serve over HTTP at http://127.0.0.1:<port>/mcp, like Unreal
    if port:
        server.run(transport="streamable-http", host="127.0.0.1", port=int(port))
    else:
        server.run(transport="stdio")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write("stopped\n")
