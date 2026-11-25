"""Workspace tools offered to every chat model, whatever its provider.

All paths are confined to the project directory. ``run_command`` runs a
real shell in the project directory with a timeout - it is NOT a security
sandbox; disable it with ``workspace.allow_shell: false`` if you don't
trust the models you route to.
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..providers.base import ToolSpec

MAX_OUTPUT = 12_000
SKIP_DIRS = {".git", ".harness", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".pytest_cache"}


class ToolError(Exception):
    pass


def _truncate(s: str, limit: int = MAX_OUTPUT) -> str:
    if len(s) <= limit:
        return s
    half = limit // 2
    return f"{s[:half]}\n... [{len(s) - limit} chars truncated] ...\n{s[-half:]}"


@dataclass
class Tool:
    spec: ToolSpec
    fn: Callable[[dict[str, Any]], str]
    terminal: bool = False  # calling it ends the agent loop (e.g. submit_plan)


@dataclass
class Toolbox:
    tools: dict[str, Tool] = field(default_factory=dict)
    captured: dict[str, Any] = field(default_factory=dict)  # args of terminal tools

    def add(self, tool: Tool) -> None:
        self.tools[tool.spec.name] = tool

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self.tools.values()]

    def call(self, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        tool = self.tools.get(name)
        if not tool:
            return f"unknown tool {name!r}; available: {sorted(self.tools)}", True
        if "_invalid_json" in args:
            return "your tool arguments were not valid JSON; try again", True
        try:
            out = tool.fn(args)
            if tool.terminal:
                self.captured[name] = args
            return out, False
        except ToolError as e:
            return str(e), True
        except Exception as e:  # tool bugs shouldn't kill the run
            return f"{type(e).__name__}: {e}", True

    def done(self) -> bool:
        return any(self.tools[n].terminal for n in self.captured if n in self.tools)


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


class Workspace:
    def __init__(self, root: str | Path, allow_shell: bool = True, command_timeout: int = 120):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.allow_shell = allow_shell
        self.command_timeout = command_timeout
        self.changed: set[str] = set()

    def path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise ToolError(f"path {rel!r} is outside the project")
        if ".harness" in p.relative_to(self.root).parts:
            raise ToolError("the .harness directory is managed by the harness")
        return p

    # -- tool implementations --------------------------------------------
    def read_file(self, a: dict) -> str:
        p = self.path(a["path"])
        if not p.is_file():
            raise ToolError(f"no such file: {a['path']}")
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        start = max(int(a.get("start_line") or 1), 1)
        end = int(a.get("end_line") or len(lines))
        body = "\n".join(f"{i}\t{line}" for i, line in enumerate(lines[start - 1 : end], start))
        return _truncate(body or "(empty file)", 40_000)

    def write_file(self, a: dict) -> str:
        p = self.path(a["path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(a["content"], encoding="utf-8")
        self.changed.add(str(p.relative_to(self.root)))
        return f"wrote {a['path']} ({len(a['content'])} chars)"

    def edit_file(self, a: dict) -> str:
        p = self.path(a["path"])
        if not p.is_file():
            raise ToolError(f"no such file: {a['path']}")
        text = p.read_text(encoding="utf-8")
        old, new = a["old_text"], a["new_text"]
        n = text.count(old)
        if n == 0:
            raise ToolError("old_text not found; read the file and copy the text exactly")
        if n > 1 and not a.get("replace_all"):
            raise ToolError(f"old_text occurs {n} times; include more context or set replace_all")
        p.write_text(text.replace(old, new) if a.get("replace_all") else text.replace(old, new, 1), encoding="utf-8")
        self.changed.add(str(p.relative_to(self.root)))
        return f"edited {a['path']} ({n if a.get('replace_all') else 1} replacement(s))"

    def list_files(self, a: dict) -> str:
        base = self.path(a.get("path") or ".")
        pattern = a.get("pattern") or "*"
        out = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for f in sorted(filenames):
                rel = os.path.relpath(os.path.join(dirpath, f), self.root)
                if fnmatch.fnmatch(f, pattern) or fnmatch.fnmatch(rel, pattern):
                    out.append(rel)
                if len(out) >= 500:
                    return "\n".join(out) + "\n... (truncated at 500)"
        return "\n".join(out) or "(no files)"

    def search(self, a: dict) -> str:
        try:
            rx = re.compile(a["pattern"])
        except re.error as e:
            raise ToolError(f"bad regex: {e}")
        glob = a.get("glob") or "*"
        hits = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for f in filenames:
                if not fnmatch.fnmatch(f, glob):
                    continue
                fp = Path(dirpath) / f
                try:
                    for i, line in enumerate(fp.read_text(encoding="utf-8").splitlines(), 1):
                        if rx.search(line):
                            hits.append(f"{fp.relative_to(self.root)}:{i}: {line.strip()[:200]}")
                            if len(hits) >= 200:
                                return "\n".join(hits) + "\n... (truncated)"
                except (UnicodeDecodeError, OSError):
                    continue
        return "\n".join(hits) or "(no matches)"

    def run_command(self, a: dict) -> str:
        if not self.allow_shell:
            raise ToolError("shell commands are disabled in this harness config")
        timeout = min(int(a.get("timeout") or self.command_timeout), self.command_timeout * 5)
        try:
            res = subprocess.run(
                a["command"], shell=True, cwd=self.root, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            raise ToolError(f"command timed out after {timeout}s")
        out = f"exit code: {res.returncode}\n--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}"
        return _truncate(out)

    # -- toolbox builders --------------------------------------------------
    def toolbox(self, names: list[str] | None = None) -> Toolbox:
        all_tools = {
            "read_file": Tool(
                ToolSpec("read_file", "Read a text file from the project (with line numbers).", _obj(
                    {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}},
                    ["path"],
                )),
                self.read_file,
            ),
            "write_file": Tool(
                ToolSpec("write_file", "Create or overwrite a file in the project with the full content.", _obj(
                    {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]
                )),
                self.write_file,
            ),
            "edit_file": Tool(
                ToolSpec("edit_file", "Replace exact text in a file. old_text must match exactly (and be unique unless replace_all).", _obj(
                    {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"},
                     "replace_all": {"type": "boolean"}},
                    ["path", "old_text", "new_text"],
                )),
                self.edit_file,
            ),
            "list_files": Tool(
                ToolSpec("list_files", "List project files, optionally under a path and matching a glob pattern.", _obj(
                    {"path": {"type": "string"}, "pattern": {"type": "string"}}, []
                )),
                self.list_files,
            ),
            "search": Tool(
                ToolSpec("search", "Regex search across project files. Returns file:line: text.", _obj(
                    {"pattern": {"type": "string"}, "glob": {"type": "string", "description": "file-name glob, e.g. *.py"}},
                    ["pattern"],
                )),
                self.search,
            ),
            "run_command": Tool(
                ToolSpec("run_command", "Run a shell command in the project directory (e.g. tests, builds). Returns exit code and output.", _obj(
                    {"command": {"type": "string"}, "timeout": {"type": "integer", "description": "seconds"}}, ["command"]
                )),
                self.run_command,
            ),
        }
        if not self.allow_shell:
            all_tools.pop("run_command")
        box = Toolbox()
        for name, tool in all_tools.items():
            if names is None or name in names:
                box.add(tool)
        return box

    def tree(self, limit: int = 200) -> str:
        listing = self.list_files({}).splitlines()
        if len(listing) > limit:
            listing = listing[:limit] + [f"... ({len(listing) - limit} more)"]
        return "\n".join(listing)


READ_ONLY = ["read_file", "list_files", "search"]
REVIEW_TOOLS = READ_ONLY + ["run_command"]
