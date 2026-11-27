"""Tools from MCP servers (Unreal Engine's editor, community servers...) for the roles that ask for them.

``harness.yaml``::

    mcp_servers:
      unreal: {url: "http://127.0.0.1:8000/mcp", timeout: 300}       # streamable HTTP
      blender: {command: uvx, args: [blender-mcp], tools: ["get_*"]}  # a program run over stdio
    roles:
      unreal_builder: {model: ..., mcp: [unreal]}

A role sees a server's tools only when it lists the server under ``mcp``. Each tool is offered as
``mcp__<server>__<tool>``. The harness loop is synchronous, so every server's client lives in a
background thread with its own event loop for the whole run (started on first use, closed by
``MCPPool.close``); calls to one server go one at a time (Unreal runs them on its game thread).
A server that can't start or list its tools never stops the run: an ``mcp_error`` event says what
to do, and the role carries on without those tools.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import re
import tempfile
import threading
from collections.abc import Callable
from typing import Any

from ..providers.base import ToolSpec
from .tools import Tool, ToolError, _truncate
from .safeenv import clean_env

PREFIX = "mcp__"
DEFAULT_TIMEOUT = 120.0
START_TIMEOUT = 60.0  # starting a server and listing its tools
CLOSE_TIMEOUT = 15.0

Emit = Callable[[str, dict[str, Any]], None]


def tool_name(server: str, tool: str) -> str:
    """``mcp__<server>__<tool>``, only [a-zA-Z0-9_-], at most 64 characters (what every maker accepts)."""
    clean = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{PREFIX}{server}__{tool}")
    return clean[:64]


def _size(n_bytes: int) -> str:
    return f"{max(1, round(n_bytes / 1024))} KB"


def result_text(result: Any) -> str:
    """One MCP tool result as text: text joined, pictures and files as a short line each."""
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        kind = getattr(block, "type", "")
        if kind == "text":
            parts.append(block.text)
        elif kind in ("image", "audio"):
            parts.append(f"[{kind} {block.mime_type}, {_size(len(block.data or '') * 3 // 4)}]")
        elif kind == "resource":
            res = block.resource
            text = getattr(res, "text", None)
            if text is not None:
                parts.append(f"[file {res.uri}]\n{text}")
            else:
                mime = getattr(res, "mime_type", None) or "data"
                parts.append(f"[file {res.uri}, {mime}, {_size(len(getattr(res, 'blob', '') or '') * 3 // 4)}]")
        elif kind == "resource_link":
            parts.append(f"[link {getattr(block, 'name', '')} {block.uri}]".replace("  ", " "))
        else:
            parts.append(f"[{kind or 'unknown'} content]")
    structured = getattr(result, "structured_content", None)
    if not parts and structured is not None:
        parts.append(json.dumps(structured, ensure_ascii=False, indent=2))
    return _truncate("\n".join(parts))


def _plain_error(e: BaseException) -> str:
    """The innermost real error of an exception group, as 'Type: message'."""
    while getattr(e, "exceptions", None):  # an exception group (anyio's task groups raise them)
        e = e.exceptions[0]
    text = str(e).strip()
    return f"{type(e).__name__}: {text}" if text else type(e).__name__


class MCPServerClient:
    """One MCP server, kept open in a background thread, with blocking ``list_tools`` and ``call_tool``."""

    def __init__(self, name: str, spec: dict[str, Any]):
        self.name = name
        self.spec = spec
        self.timeout = float(spec.get("timeout") or DEFAULT_TIMEOUT)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop: asyncio.Event | None = None
        self._client: Any = None
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._lock = threading.Lock()  # one call at a time per server
        self._errlog: Any = None

    # -- life ----------------------------------------------------------------
    def where(self) -> str:
        return self.spec.get("url") or " ".join([self.spec.get("command", "")] + list(self.spec.get("args") or []))

    def start(self) -> None:
        """Start the server (or connect to it) and wait until it answers; raises ToolError if it doesn't."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._thread_main, name=f"mcp-{self.name}", daemon=True)
            self._thread.start()
        if not self._ready.wait(min(START_TIMEOUT, self.timeout) if self.timeout else START_TIMEOUT):
            raise ToolError(self._help(f"it didn't answer within {int(START_TIMEOUT)} seconds"))
        if self._error is not None:
            raise ToolError(self._help(_plain_error(self._error)))

    def _help(self, why: str) -> str:
        if "url" in self.spec:
            return (f"MCP server '{self.name}' isn't answering at {self.spec['url']} ({why}). Open the program "
                    "it belongs to (for Unreal: the editor, with its MCP plugin turned on), check the address and "
                    "port in harness.yaml, then try again.")
        tail = self._stderr_tail()
        return (f"MCP server '{self.name}' couldn't be started with `{self.where()}` ({why})."
                + (f" It said: {tail}" if tail else "")
                + " Check that the program is installed and the command under mcp_servers in harness.yaml is "
                  "right, then try again.")

    def _stderr_tail(self) -> str:
        try:
            self._errlog.flush()
            self._errlog.seek(0)
            return " ".join(self._errlog.read()[-400:].split())
        except Exception:
            return ""

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()  # the Proactor loop on Windows, which can run programs
        self._loop = loop
        try:
            loop.run_until_complete(self._serve())
        except BaseException as e:  # noqa: BLE001 - reported through start()
            self._error = self._error or e
        finally:
            self._ready.set()
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()

    def _transport(self):
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared._httpx_utils import create_mcp_http_client

        if "url" in self.spec:
            http = create_mcp_http_client(headers=dict(self.spec.get("headers") or {}) or None)
            return streamable_http_client(self.spec["url"], http_client=http), http
        self._errlog = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
        params = StdioServerParameters(command=self.spec["command"], args=list(self.spec.get("args") or []),
                                       env=clean_env(self.spec.get("env")), cwd=self.spec.get("cwd"))
        return stdio_client(params, errlog=self._errlog), None

    async def _serve(self) -> None:
        from mcp import Client
        from mcp_types import Implementation

        self._stop = asyncio.Event()
        transport, http = self._transport()
        try:
            async with Client(transport, read_timeout_seconds=self.timeout,
                              client_info=Implementation(name="roundtable", version="1")) as client:
                self._client = client
                self._ready.set()
                await self._stop.wait()
        finally:
            self._client = None
            if http is not None:
                await http.aclose()

    def _run(self, coro, timeout: float):
        if self._loop is None or self._client is None:
            coro.close()
            raise ToolError(f"MCP server '{self.name}' isn't connected any more; run the task again.")
        fut = asyncio.run_coroutine_threadsafe(asyncio.wait_for(coro, timeout), self._loop)
        try:
            return fut.result(timeout + 5)
        except (TimeoutError, asyncio.TimeoutError):
            fut.cancel()
            raise ToolError(f"MCP server '{self.name}' took longer than {int(timeout)} seconds to answer. "
                            "If it is busy (a big build or import), raise its timeout under mcp_servers in "
                            "harness.yaml and try again.") from None

    def close(self) -> None:
        loop, stop = self._loop, self._stop
        if loop is not None and stop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(stop.set)
            except RuntimeError:
                pass  # the loop has just finished
        if self._thread is not None:
            self._thread.join(CLOSE_TIMEOUT)
        if self._errlog is not None:
            try:
                self._errlog.close()
            except Exception:
                pass
            self._errlog = None

    # -- calls ---------------------------------------------------------------
    def list_tools(self) -> list[Any]:
        """Every tool the server offers (all pages)."""
        self.start()
        out: list[Any] = []
        cursor = None
        with self._lock:
            for _ in range(100):
                page = self._run(self._client.list_tools(cursor=cursor), self.timeout)
                out += list(page.tools)
                cursor = page.next_cursor
                if not cursor:
                    break
        return out

    def call_tool(self, name: str, args: dict[str, Any]) -> str:
        """The tool's result as text; raises ToolError when the server reports an error."""
        self.start()
        with self._lock:
            try:
                result = self._run(self._client.call_tool(name, args), self.timeout)
            except ToolError:
                raise
            except Exception as e:
                raise ToolError(f"MCP server '{self.name}' couldn't run {name}: {_plain_error(e)}") from e
        text = result_text(result)
        if getattr(result, "is_error", False):
            raise ToolError(text or f"{name} reported an error (no details given)")
        return text or "(no output)"


def _wanted(tool: str, allow: list[str] | None) -> bool:
    return not allow or any(fnmatch.fnmatchcase(tool, pat) for pat in allow)


def _decode_nested(args: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Some models send a nested object as a JSON string; decode it where the schema wants an object or list."""
    props = (schema or {}).get("properties") or {}
    out = dict(args)
    for key, value in args.items():
        want = (props.get(key) or {}).get("type")
        if isinstance(value, str) and want in ("object", "array"):
            try:
                decoded = json.loads(value)
            except ValueError:
                continue
            if isinstance(decoded, dict if want == "object" else list):
                out[key] = decoded
    return out


class MCPPool:
    """The MCP servers of one run: started on first use, each listed once, all closed by ``close``."""

    def __init__(self, servers: dict[str, dict[str, Any]], emit: Emit | None = None,
                 factory: Callable[[str, dict[str, Any]], MCPServerClient] = MCPServerClient):
        self.servers = servers
        self.emit = emit or (lambda *_: None)
        self._factory = factory
        self._clients: dict[str, MCPServerClient] = {}
        self._tools: dict[str, list[Tool]] = {}
        self._failed: dict[str, str] = {}
        self._lock = threading.Lock()

    def tools_for(self, names: list[str] | None) -> list[Tool]:
        """The tools of these servers (servers that are off or failed give none)."""
        out: list[Tool] = []
        for name in names or []:
            out += self._server_tools(name)
        return out

    def failed(self) -> dict[str, str]:
        return dict(self._failed)

    def _server_tools(self, name: str) -> list[Tool]:
        with self._lock:
            if name in self._tools:
                return self._tools[name]
            if name in self._failed:
                return []
            spec = self.servers.get(name)
            if not spec or not spec.get("enabled", True):
                self._tools[name] = []
                return []
            client = self._clients.get(name) or self._factory(name, spec)
            self._clients[name] = client
            try:
                listed = client.list_tools()
            except Exception as e:  # never stops the run
                message = str(e) if isinstance(e, ToolError) else client._help(_plain_error(e))
                self._failed[name] = message
                self.emit("mcp_error", {"server": name, "error": message})
                return []
            tools = [self._wrap(client, t) for t in listed if _wanted(t.name, spec.get("tools"))]
            self._tools[name] = tools
            self.emit("mcp_tools", {"server": name, "tools": [t.spec.name for t in tools]})
            return tools

    def _wrap(self, client: MCPServerClient, t: Any) -> Tool:
        schema = dict(getattr(t, "input_schema", None) or {})
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        desc = (getattr(t, "description", None) or getattr(t, "title", None) or t.name).strip()
        notes = getattr(t, "annotations", None)
        if notes is not None and getattr(notes, "read_only_hint", None):
            desc += " (read-only)"
        original = t.name

        def call(args: dict[str, Any]) -> str:
            return client.call_tool(original, _decode_nested(args, schema))

        return Tool(ToolSpec(tool_name(client.name, original), f"[MCP server {client.name}] {desc}", schema), call)

    def close(self) -> None:
        for client in list(self._clients.values()):
            try:
                client.close()
            except Exception:
                pass
        self._clients.clear()
        self._tools.clear()


def check_servers(servers: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """For ``roundtable mcp list``: each server, whether it answers, and its tool names."""
    rows = []
    for name, spec in servers.items():
        row: dict[str, Any] = {"server": name, "where": spec.get("url") or " ".join(
            [spec.get("command", "")] + list(spec.get("args") or [])), "enabled": spec.get("enabled", True)}
        if not row["enabled"]:
            rows.append({**row, "ok": None, "tools": []})
            continue
        pool = MCPPool({name: spec})
        try:
            tools = pool.tools_for([name])
            err = pool.failed().get(name)
            rows.append({**row, "ok": err is None, "error": err,
                         "tools": [t.spec.name for t in tools]})
        finally:
            pool.close()
    return rows
