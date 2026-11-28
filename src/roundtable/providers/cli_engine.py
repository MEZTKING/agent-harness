"""Coding CLIs as workers: Claude Code and Codex, signed in with the owner's own subscriptions.

A role picks one by naming it in its model chain: ``cli/claude-code`` or ``cli/codex`` (a model
for the CLI after ``@``: ``cli/claude-code@opus``, ``cli/codex@gpt-6-astra``). It is off until a
role names it.

Unlike the other providers, a CLI runs a whole task by itself: ``run_cli_agent`` starts it in the
task's folder (the task's own worktree when several tasks run at once), gives it the task on its
standard input, and turns its streamed steps into Roundtable's events (``model_turn``,
``tool_call``, ``agent_done``, each with ``ms``). Afterwards the files it changed are found with
git (or, outside git, by their times and sizes) and shown as ``tool_call`` events with a diff.

* **Claude Code**: ``claude -p --output-format stream-json --verbose --permission-mode acceptEdits``
  with an allowed-tools list (file tools and test/build commands; no web, no ``curl``, no pushes,
  no ``rm -rf``). A retry resumes the same conversation with ``--resume <session>``.
* **Codex**: ``codex exec --json --sandbox workspace-write --skip-git-repo-check -`` (its own
  sandbox: it can write only inside the folder and has no network). A retry resumes with
  ``codex exec resume <session>``.

Safety: the process gets ``harness/safeenv.clean_env()`` (no API keys, no hub token, no git login)
but keeps HOME, USERPROFILE and APPDATA, so the CLI finds its own sign-in. Its time is capped
(``workers: cli_time_limit_minutes``, default 30), the breaker's token cap and repeat check stop it,
the run's money limit is checked before it starts, and a stop kills its whole process tree.
"Ask me first" can't see inside a CLI: with the gate on "all" Claude Code gets no shell at all.

Money: with ``bill: subscription`` (the default) the CLI's own reported cost is shown but not
charged, since the owner's subscription pays; ``bill: api`` charges it to the run's budget.

The engine table (command, resume, install) follows Munder Difflin's agent provider table
(``src/shared/agentProvider.ts``, MIT, Copyright (c) 2026 Chaitanya Giri): Codex resumes through a
``resume`` subcommand rather than a flag, keeps its sandbox when approvals are off, and a missing
CLI points at its install command. The headless stream reading is Roundtable's own.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .base import ChatResponse, Provider, ProviderError, Usage

PROVIDER_NAME = "cli"
DEFAULT_TIME_LIMIT_MIN = 30.0
SESSIONS_FILE = "cli-sessions.json"  # in <workspace>/.harness/: task id -> {engine, session}
_TASK_ID = re.compile(r"^# Your task \[([^\]\n]+)\]", re.M)
_FEEDBACK = "# Feedback on your previous attempt(s)"
MAX_DIFF_FILE = 200_000  # bytes: bigger files are listed, not diffed
_SCAN_SKIP = {".git", ".harness", "node_modules", "__pycache__", ".venv", "venv", ".godot", "build", "dist"}

# Claude Code: what it may do without asking. Edits are accepted by the permission mode; these
# commands are the usual tests and builds. Anything else is denied (nobody can answer a prompt).
CLAUDE_ALLOWED = (
    "Read", "Edit", "MultiEdit", "Write", "Glob", "Grep", "LS", "NotebookEdit", "TodoWrite",
    "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)", "Bash(git add:*)",
    "Bash(ls:*)", "Bash(cat:*)", "Bash(mkdir:*)", "Bash(python -m pytest:*)", "Bash(pytest:*)",
    "Bash(python -m unittest:*)", "Bash(npm test:*)", "Bash(npm run test:*)", "Bash(npm run build:*)",
    "Bash(npm run lint:*)", "Bash(npx tsc:*)", "Bash(cargo test:*)", "Bash(cargo build:*)",
    "Bash(go test:*)", "Bash(go build:*)", "Bash(dotnet build:*)", "Bash(dotnet test:*)",
    "Bash(./gradlew test:*)", "Bash(./gradlew build:*)", "Bash(godot --headless:*)",
)
CLAUDE_DENIED = (
    "WebFetch", "WebSearch", "Bash(curl:*)", "Bash(wget:*)", "Bash(ssh:*)", "Bash(scp:*)",
    "Bash(git push:*)", "Bash(git remote:*)", "Bash(git reset --hard:*)", "Bash(git clean:*)",
    "Bash(rm -rf:*)", "Bash(rm -fr:*)", "Bash(sudo:*)", "Bash(npm publish:*)", "Bash(npm install -g:*)",
    "Bash(pip install:*)", "Bash(Invoke-WebRequest:*)", "Bash(iwr:*)",
)
CLAUDE_FILE_ONLY = ("Read", "Edit", "MultiEdit", "Write", "Glob", "Grep", "LS", "NotebookEdit", "TodoWrite")

# Claude Code's tool names -> Roundtable's, so Watch shows them the same way
_CLAUDE_TOOLS = {"Bash": "run_command", "Read": "read_file", "Write": "write_file", "Edit": "edit_file",
                 "MultiEdit": "edit_file", "Glob": "list_files", "Grep": "search", "LS": "list_files"}


@dataclass(frozen=True)
class Engine:
    id: str  # what follows cli/ in a model ref
    name: str  # what the owner reads
    command: str  # the program
    tool: str  # its id on the Tools page (prereq.py), for the Install button
    install: str  # the install command, for the docs and the error
    resume: str  # how a retry continues: "flag" (--resume <id>) or "subcommand" (resume <id>)


ENGINES: dict[str, Engine] = {
    "claude-code": Engine("claude-code", "Claude Code", "claude", "claude",
                          "npm install -g @anthropic-ai/claude-code", "flag"),
    "codex": Engine("codex", "Codex", "codex", "codex", "npm install -g @openai/codex", "subcommand"),
}
ALIASES = {"claude": "claude-code", "claudecode": "claude-code", "claude_code": "claude-code",
           "openai-codex": "codex"}


def engine_for(model: str) -> tuple[Engine, str]:
    """``claude-code@opus`` -> (Claude Code, "opus"); an unknown engine is a plain error."""
    eid, _, sub = (model or "").partition("@")
    eid = ALIASES.get(eid.strip().lower(), eid.strip().lower())
    if eid not in ENGINES:
        raise ProviderError(f"There's no coding helper called {model!r}. Use cli/claude-code or cli/codex.")
    return ENGINES[eid], sub.strip()


class CliMissing(ProviderError):
    """The CLI isn't installed: the app shows an Install card for ``tool`` (the Tools page)."""

    def __init__(self, engine: Engine):
        super().__init__(f"{engine.name} isn't installed on this computer. Install it from the Tools page "
                         f"(Settings → Tools → {engine.name} → Install), sign in to it once, then try again.")
        self.tool = engine.tool
        self.install = engine.install


# -- running processes, so a stop can kill them -------------------------------------------------
_RUNNING: set[subprocess.Popen] = set()
_STOPPED: set[int] = set()  # pids stopped by stop_all, so their run reads as stopped, not failed
_RUNNING_LOCK = threading.Lock()


def kill_tree(proc: subprocess.Popen) -> None:
    """Stop the CLI and everything it started (its builds, its test runs)."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=15)
        else:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            try:
                proc.wait(timeout=3)
                return
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
    except Exception:  # noqa: BLE001 - the kill below is the last resort
        pass
    try:
        proc.kill()
    except Exception:  # noqa: BLE001
        pass


def stop_all() -> int:
    """Kill every running CLI worker (the app's Stop). Returns how many were stopped."""
    with _RUNNING_LOCK:
        procs = list(_RUNNING)
    for p in procs:
        with _RUNNING_LOCK:
            _STOPPED.add(p.pid)
        kill_tree(p)
    return len(procs)


def running() -> int:
    with _RUNNING_LOCK:
        return sum(1 for p in _RUNNING if p.poll() is None)


# -- the provider ------------------------------------------------------------------------------
class CliEngine(Provider):
    """``providers: cli: {type: cli}`` in harness.yaml. Options:

    * ``commands``: {engine id: program or [program, args...]} instead of finding it on this computer;
    * ``bill``: ``subscription`` (default: shown, not charged) or ``api`` (charged to the budget);
    * ``allowed_tools`` / ``disallowed_tools``: Claude Code's lists, replacing the defaults;
    * ``extra_args``: {engine id: [args...]} added to the command line;
    * ``time_limit_minutes``: per task (also ``workers: cli_time_limit_minutes``).
    """

    name = PROVIDER_NAME

    def __init__(self, name: str = PROVIDER_NAME, commands: dict[str, Any] | None = None, bill: str = "subscription",
                 allowed_tools: list[str] | None = None, disallowed_tools: list[str] | None = None,
                 extra_args: dict[str, list[str]] | None = None, time_limit_minutes: float | None = None,
                 **_ignored: Any):
        self.name = name
        self.commands = dict(commands or {})
        self.bill = "api" if str(bill).lower() == "api" else "subscription"
        self.allowed_tools = tuple(allowed_tools) if allowed_tools else None
        self.disallowed_tools = tuple(disallowed_tools) if disallowed_tools else None
        self.extra_args = {k: [str(a) for a in v] for k, v in (extra_args or {}).items()}
        self.time_limit_minutes = time_limit_minutes

    def chat(self, model, system, messages, tools=None, max_tokens=16000, options=None, *,
             on_delta=None) -> ChatResponse:  # on_delta unused: a coding CLI streams its own steps
        raise ProviderError("A coding helper (cli/…) works on a whole task by itself; it can't answer one "
                            "message. Use it for building roles only.")

    def list_models(self) -> list[str]:
        return list(ENGINES)

    # -- finding the program ----------------------------------------------------------------------
    def command(self, engine: Engine, env: dict[str, str] | None = None) -> list[str]:
        given = self.commands.get(engine.id)
        if given:
            argv = [str(a) for a in given] if isinstance(given, (list, tuple)) else [str(given)]
            if not (shutil.which(argv[0], path=(env or os.environ).get("PATH")) or Path(argv[0]).exists()):
                raise CliMissing(engine)
            return argv
        found = shutil.which(engine.command, path=(env or os.environ).get("PATH"))
        if not found:
            try:  # the Tools page also looks where npm and the installers put it
                from ..prereq import find

                row = find(engine.tool, versions=False)
                found = row.get("where") if row.get("state") in ("found", "old") else None
            except Exception:  # noqa: BLE001 - finding it is best effort
                found = None
        if not found:
            raise CliMissing(engine)
        return [found]

    def argv(self, engine: Engine, sub_model: str, resume: str | None, file_only: bool,
             env: dict[str, str] | None = None) -> list[str]:
        base = self.command(engine, env)
        extra = self.extra_args.get(engine.id, [])
        if engine.id == "claude-code":
            allowed = CLAUDE_FILE_ONLY if file_only else (self.allowed_tools or CLAUDE_ALLOWED)
            denied = self.disallowed_tools or CLAUDE_DENIED
            argv = [*base, "-p", "--output-format", "stream-json", "--verbose",
                    "--permission-mode", "acceptEdits",
                    "--allowedTools", ",".join(allowed), "--disallowedTools", ",".join(denied)]
            if sub_model:
                argv += ["--model", sub_model]
            if resume:
                argv += ["--resume", resume]
            return argv + extra
        # codex: exec's options first, then the resume subcommand, then "-" (the prompt on stdin)
        argv = [*base, "exec", "--json", "--sandbox", "workspace-write", "--skip-git-repo-check"]
        if sub_model:
            argv += ["--model", sub_model]
        argv += extra
        if resume:
            argv += ["resume", resume]
        return argv + ["-"]


# -- reading the streams -----------------------------------------------------------------------
@dataclass
class Step:
    kind: str  # text | tool_start | tool_end
    text: str = ""
    tool: str = ""
    call_id: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    output: str = ""
    error: bool = False


@dataclass
class StreamState:
    session: str = ""
    model: str = ""
    usage: Usage = field(default_factory=Usage)
    reported_usd: float | None = None
    final: str = ""
    last_text: str = ""
    error: str = ""
    done: bool = False
    turns: int = 0
    denied: list[str] = field(default_factory=list)
    done_steps: int = 0  # steps seen in the stream (text or tool calls)


def read_claude(obj: dict[str, Any], st: StreamState) -> list[Step]:
    """One line of ``claude -p --output-format stream-json --verbose``."""
    t = obj.get("type")
    out: list[Step] = []
    if obj.get("session_id"):
        st.session = str(obj["session_id"])
    if t == "system" and obj.get("subtype") == "init":
        st.model = str(obj.get("model") or st.model)
    elif t == "assistant":
        msg = obj.get("message") or {}
        for block in msg.get("content") or []:
            if block.get("type") == "text" and block.get("text"):
                st.last_text = block["text"]
                out.append(Step("text", text=block["text"]))
            elif block.get("type") == "tool_use":
                name = str(block.get("name") or "tool")
                out.append(Step("tool_start", tool=name, call_id=str(block.get("id") or ""),
                                args=block.get("input") if isinstance(block.get("input"), dict) else {}))
        st.turns += 1
    elif t == "user":
        msg = obj.get("message") or {}
        content = msg.get("content")
        for block in content if isinstance(content, list) else []:
            if block.get("type") == "tool_result":
                body = block.get("content")
                if isinstance(body, list):
                    body = "\n".join(str(b.get("text", "")) for b in body if isinstance(b, dict))
                out.append(Step("tool_end", call_id=str(block.get("tool_use_id") or ""), output=str(body or ""),
                                error=bool(block.get("is_error"))))
    elif t == "result":
        st.done = True
        u = obj.get("usage") or {}
        st.usage = Usage(int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0),
                         int(u.get("cache_read_input_tokens") or 0), int(u.get("cache_creation_input_tokens") or 0))
        if obj.get("total_cost_usd") is not None:
            st.reported_usd = float(obj["total_cost_usd"])
        st.final = str(obj.get("result") or "")
        st.turns = int(obj.get("num_turns") or st.turns)
        st.denied = [str(d.get("tool_name", "")) for d in obj.get("permission_denials") or [] if isinstance(d, dict)]
        if obj.get("is_error") or (obj.get("subtype") not in (None, "success")):
            st.error = st.final or str(obj.get("subtype") or "error")
    return out


def read_codex(obj: dict[str, Any], st: StreamState) -> list[Step]:
    """One line of ``codex exec --json``."""
    t = str(obj.get("type") or "")
    out: list[Step] = []
    if t in ("thread.started", "session.created") and (obj.get("thread_id") or obj.get("session_id")):
        st.session = str(obj.get("thread_id") or obj.get("session_id"))
    elif t in ("item.started", "item.completed"):
        item = obj.get("item") or {}
        kind = item.get("type") or item.get("item_type")
        iid = str(item.get("id") or "")
        if kind in ("agent_message", "assistant_message") and t == "item.completed":
            text = str(item.get("text") or "")
            if text:
                st.last_text = text
                out.append(Step("text", text=text))
        elif kind == "command_execution":
            if t == "item.started":
                out.append(Step("tool_start", tool="run_command", call_id=iid,
                                args={"command": str(item.get("command") or "")}))
            else:
                code = item.get("exit_code")
                out.append(Step("tool_end", call_id=iid, output=str(item.get("aggregated_output") or ""),
                                error=bool(code) or item.get("status") == "failed"))
        elif kind == "file_change" and t == "item.completed":
            paths = [str(c.get("path", "")) for c in item.get("changes") or [] if isinstance(c, dict)]
            out.append(Step("tool_start", tool="edit_file", call_id=iid, args={"paths": paths}))
            out.append(Step("tool_end", call_id=iid, output="changed " + ", ".join(paths),
                            error=item.get("status") == "failed"))
        elif kind in ("mcp_tool_call", "web_search") and t == "item.completed":
            name = str(item.get("tool") or kind)
            out.append(Step("tool_start", tool=name, call_id=iid, args={}))
            out.append(Step("tool_end", call_id=iid, output="", error=item.get("status") == "failed"))
    elif t == "turn.completed":
        u = obj.get("usage") or {}
        cached = int(u.get("cached_input_tokens") or 0)
        st.usage = st.usage + Usage(max(0, int(u.get("input_tokens") or 0) - cached),
                                    int(u.get("output_tokens") or 0), cached, 0)
        st.turns += 1
        st.done = True
    elif t == "turn.failed":
        st.error = str((obj.get("error") or {}).get("message") or "the turn failed")
        st.done = True
    elif t == "error":
        st.error = str(obj.get("message") or "error")
    return out


READERS: dict[str, Callable[[dict[str, Any], StreamState], list[Step]]] = {
    "claude-code": read_claude, "codex": read_codex}


# -- what changed in the folder ----------------------------------------------------------------
def _git(root: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=60,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _is_git(root: Path) -> bool:
    return (_git(root, "rev-parse", "--is-inside-work-tree") or "").strip() == "true"


def _status(root: Path) -> list[str]:
    out = _git(root, "status", "--porcelain", "-uall", "-z") or ""
    paths: list[str] = []
    parts = out.split("\0")
    i = 0
    while i < len(parts):
        row = parts[i]
        i += 1
        if len(row) < 4:
            continue
        code, path = row[:2], row[3:]
        if code[0] in "RC":  # renamed: the old name follows
            i += 1
        if not path.startswith(".harness/"):
            paths.append(path)
    return paths


def _read(p: Path) -> str | None:
    try:
        if p.stat().st_size > MAX_DIFF_FILE:
            return None
        data = p.read_bytes()
    except OSError:
        return ""
    if b"\0" in data[:8000]:
        return None
    return data.decode("utf-8", errors="replace")


def _digest(p: Path) -> str:
    try:
        return hashlib.sha1(p.read_bytes()).hexdigest()
    except OSError:
        return ""


def _scan(root: Path, limit: int = 20000) -> dict[str, tuple[int, int]]:
    seen: dict[str, tuple[int, int]] = {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SCAN_SKIP]
        for f in files:
            p = Path(dirpath) / f
            try:
                s = p.stat()
            except OSError:
                continue
            seen[p.relative_to(root).as_posix()] = (s.st_mtime_ns, s.st_size)
            if len(seen) >= limit:
                return seen
    return seen


class Snapshot:
    """The folder before the CLI ran, to find what it changed afterwards."""

    def __init__(self, root: Path):
        self.root = root
        self.git = _is_git(root)
        self.dirty: dict[str, tuple[str, str | None]] = {}
        self.files: dict[str, tuple[int, int]] = {}
        if self.git:
            for rel in _status(root):
                p = root / rel
                self.dirty[rel] = (_digest(p), _read(p))
        else:
            self.files = _scan(root)

    def changes(self) -> list[tuple[str, str | None, str | None]]:
        """[(path, old text or None, new text or None)] for every file the CLI changed."""
        out: list[tuple[str, str | None, str | None]] = []
        if self.git:
            for rel in _status(self.root):
                p = self.root / rel
                if rel in self.dirty:
                    digest, old = self.dirty[rel]
                    if _digest(p) == digest:
                        continue  # dirty before, untouched by the CLI
                else:
                    old = _git(self.root, "show", f"HEAD:{rel}")
                    old = old if old is not None else ""
                out.append((rel, old, _read(p) if p.exists() else ""))
            for rel in self.dirty:  # dirty before and now back as committed: still a change
                if rel not in {c[0] for c in out} and rel not in _status(self.root):
                    out.append((rel, self.dirty[rel][1], _read(self.root / rel)))
        else:
            now = _scan(self.root)
            for rel, sig in now.items():
                if self.files.get(rel) != sig:
                    out.append((rel, None, None))
            for rel in self.files:
                if rel not in now:
                    out.append((rel, None, ""))
        return out


# -- sessions, so a retry carries on the same conversation ---------------------------------------
def task_key(prompt: str) -> str:
    """The task's id and a hash of its heading: a new plan reusing the id never resumes the old talk."""
    m = _TASK_ID.search(prompt or "")
    if not m:
        return ""
    line = prompt[m.start():].split("\n", 1)[0]
    return f"{m.group(1).strip()}:{hashlib.sha1(line.encode('utf-8')).hexdigest()[:10]}"


def _sessions_path(root: Path) -> Path:
    """In the project's own .harness (also for a task's worktree, which lives in .harness/worktrees/)."""
    for parent in root.parents:
        if parent.name == ".harness" and (parent / "worktrees") in [root, *root.parents]:
            return parent / SESSIONS_FILE
    return root / ".harness" / SESSIONS_FILE


def load_session(root: Path, key: str, engine: Engine) -> str:
    if not key:
        return ""
    try:
        data = json.loads(_sessions_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    row = data.get(key) or {}
    return str(row.get("session") or "") if row.get("engine") == engine.id else ""


def save_session(root: Path, key: str, engine: Engine, session: str) -> None:
    if not key or not session:
        return
    path = _sessions_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        data = {}
    data[key] = {"engine": engine.id, "session": session}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def resume_prompt(prompt: str) -> str:
    """On a resumed conversation the CLI already has the task: send only the feedback and the ending."""
    i = prompt.find(_FEEDBACK)
    if i < 0:
        return "Carry on with the task: check what's done, finish the rest.\n\n" + _ENDING
    return prompt[i:] + "\n\n" + _ENDING


_ENDING = ("You are working through a coding tool, not the harness's own tools: there is no finish_task "
           "here. Don't touch the .harness folder. When you are done, end with a short summary of what you "
           "did and anything the next person must know.")


def _prompt(system: str, prompt: str, engine: Engine) -> str:
    body = prompt.replace("call finish_task with", "end with").replace("call finish_task", "finish")
    if system:  # on stdin, not a flag: Codex has none, and a long flag breaks through Windows' claude.cmd
        body = f"{system}\n\n{body}"
    return f"{body}\n\n{_ENDING}"


# -- one task --------------------------------------------------------------------------------
def _ms(seconds: float) -> int:
    return round(seconds * 1000)


def _login_problem(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in ("not logged in", "please log in", "/login", "login required", "unauthorized",
                                  "authentication", "sign in", "invalid api key"))


def _plain_failure(engine: Engine, text: str) -> str:
    tail = text.strip()[-600:]
    if _login_problem(tail):
        return (f"{engine.name} isn't signed in on this computer. Open it once from the Tools page and sign in "
                f"with your subscription, then try again. ({tail[-200:]})")
    return f"{engine.name} stopped with an error: {tail or 'no message'}"


def run_cli_agent(
    cfg: Any,
    ref: Any,
    system: str,
    prompt: str,
    toolbox: Any,
    budget: Any,
    max_steps: int = 40,
    max_tokens: int = 16000,
    options: dict[str, Any] | None = None,
    require_terminal: str | None = None,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
    saver: Any = None,
    role: str | None = None,
    project_root: Path | None = None,
    breaker: Any = None,
    stop_event: threading.Event | None = None,
    engine_provider: CliEngine | None = None,
) -> Any:
    """``run_agent`` for a coding CLI: same arguments, same ``AgentResult``.

    Works in the toolbox's folder (``toolbox.source.root``: the task's worktree when tasks run at
    once). The CLI's final summary goes to the task's finishing tool, so the orchestrator reviews it
    as any other attempt. ``options``: ``resume`` (a session id), ``fresh`` (don't resume).
    """
    from ..harness.agent import AgentResult
    from ..harness.breaker import Breaker, BreakerSettings, call_key, work_tokens
    from ..harness.config import section
    from ..harness.safeenv import clean_env
    from ..harness.tools import file_change

    provider = engine_provider or cfg.provider(ref.provider)
    if not isinstance(provider, CliEngine):
        raise ProviderError(f"{ref} is not a coding helper")
    engine, sub_model = engine_for(ref.model)
    emit = on_event or (lambda *_: None)
    opts = dict(options or {})

    terminals = [n for n, t in toolbox.tools.items() if getattr(t, "terminal", False)]
    finisher = "finish_task" if "finish_task" in terminals else ""
    if terminals and not finisher or not any(n in toolbox.tools for n in ("write_file", "edit_file")):
        raise ProviderError(f"{engine.name} can only build (write code for a task); it can't plan, review or "
                            "only look. Give this role a chat model, or put the helper after one in its chain.")
    ws = getattr(toolbox, "source", None)
    root = Path(getattr(ws, "root", None) or project_root or Path.cwd()).resolve()

    budget.check()  # the run's money limit still applies
    brk = breaker if breaker is not None else Breaker(BreakerSettings.from_config(cfg))
    workers = section(cfg, "workers")
    limit_min = float(opts.get("time_limit_minutes") or provider.time_limit_minutes
                      or workers.get("cli_time_limit_minutes") or DEFAULT_TIME_LIMIT_MIN)
    gate_mode = "off"
    gate = getattr(ws, "gate", None)
    if gate is not None:
        try:
            from ..harness.gate import mode_for

            gate_mode = mode_for(root, cfg)
        except Exception:  # noqa: BLE001
            gate_mode = "off"
    file_only = gate_mode == "all" and engine.id == "claude-code"

    key = task_key(prompt)
    resume = "" if opts.get("fresh") else str(opts.get("resume") or load_session(root, key, engine))
    env = clean_env()  # no keys, no hub token, no git login; HOME/USERPROFILE/APPDATA stay (the CLI's sign-in)
    # the helper's own telemetry (if the owner sends it to 127.0.0.1) says the harness drove it (otel.py)
    env["OTEL_RESOURCE_ATTRIBUTES"] = ",".join(x for x in (env.get("OTEL_RESOURCE_ATTRIBUTES", ""),
                                                           "roundtable.driven=true") if x)

    snap = Snapshot(root)
    t0 = time.monotonic()
    tool_s = 0.0
    step = 0
    st = StreamState()
    stop = "done"
    reason = ""
    for attempt in (1, 2):  # the second only when a resumed session can't be found
        text_in = resume_prompt(prompt) if resume else _prompt(system, prompt, engine)
        argv = provider.argv(engine, sub_model, resume or None, file_only, env)
        emit("cli_start", {"engine": engine.id, "name": engine.name, "role": role, "resume": bool(resume),
                           "folder": str(root), "ask_me_first": gate_mode,
                           "note": ("Ask me first can't see inside a coding helper: "
                                    + ("it gets no commands, only file edits." if file_only
                                       else "it runs its own allowed commands without asking."))
                           if gate_mode != "off" else ""})
        st = StreamState()
        try:
            stop, reason, step, tool_s = _drive(argv, root, env, text_in, engine, st, emit, brk, budget, provider,
                                                limit_min, max_steps, stop_event, role, ref, call_key, work_tokens,
                                                t0, tool_s, step)
        finally:
            if st.session:  # even when stopped: a retry carries on the same conversation
                save_session(root, key, engine, st.session)
        if attempt == 1 and resume and st.error and not st.done_steps:
            emit("cli_note", {"engine": engine.id, "note": "The earlier conversation couldn't be found; starting afresh."})
            resume = ""
            continue
        break

    # the files it changed, as tool_call events with a diff (Watch's Session view)
    changed: list[str] = []
    for rel, old, new in snap.changes():
        changed.append(rel)
        if ws is not None and hasattr(ws, "changed"):
            ws.changed.add(rel)
        change = file_change(rel, old, new) if old is not None and new is not None else None
        row = {"tool": "file_changed", "args": {"path": rel}, "error": False, "ms": 0,
               "result": f"changed by {engine.name}", "engine": engine.id}
        if change:
            row["change"] = change
        emit("tool_call", row)

    usage = st.usage
    reported = st.reported_usd
    cost = reported if (provider.bill == "api" and reported is not None) else 0.0
    budget.charge(cost, ref=ref, usage=usage, role=role)
    seconds = time.monotonic() - t0
    text = st.final or st.last_text

    if stop == "done" and st.error:  # its files stay; the next attempt or model carries on from them
        emit("agent_done", {"model": str(ref), "role": role, "stop": "error", "steps": step, "ms": _ms(seconds),
                            "engine": engine.id})
        raise ProviderError(_plain_failure(engine, st.error))
    if stop == "done" and finisher:
        toolbox.call(finisher, {"summary": text or f"{engine.name} finished; files changed: {', '.join(changed) or 'none'}"})
        stop = "terminal"
    model_s = max(0.0, seconds - tool_s)
    emit("agent_done", {"model": str(ref), "role": role, "stop": stop, "steps": step,
                        "model_ms": _ms(model_s), "tool_ms": _ms(tool_s), "other_ms": 0, "ms": _ms(seconds),
                        "engine": engine.id, "session": st.session, "files": changed[:50],
                        "reported_usd": reported, "billed": provider.bill,
                        **({"breaker": reason} if stop == "breaker" else {}),
                        **({"denied": st.denied[:20]} if st.denied else {})})
    return AgentResult(
        text=text, steps=step, usage=usage, cost_usd=cost, model=str(ref), stop=stop,
        captured=dict(toolbox.captured), messages=[{"role": "user", "content": prompt},
                                                   {"role": "assistant", "content": text}],
        seconds=round(seconds, 2), breaker_reason=reason if stop == "breaker" else "",
        model_ms=_ms(model_s), tool_ms=_ms(tool_s), other_ms=0,
    )


def _drive(argv, root, env, text_in, engine, st, emit, brk, budget, provider, limit_min, max_steps, stop_event,
           role, ref, call_key, work_tokens, t0, tool_s, step):
    """Start the CLI, read its stream until it ends, is stopped, or runs over a limit."""
    popen_kw: dict[str, Any] = {}
    if os.name == "nt":
        popen_kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "CREATE_NO_WINDOW", 0)
    else:
        popen_kw["start_new_session"] = True  # its own process group: a stop kills its children too
    try:
        proc = subprocess.Popen(argv, cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, **popen_kw)
    except FileNotFoundError as e:
        raise CliMissing(engine) from e
    with _RUNNING_LOCK:
        _RUNNING.add(proc)
    lines: queue.Queue = queue.Queue()
    err_tail: list[str] = []

    def pump_out() -> None:
        for raw in iter(proc.stdout.readline, b""):
            lines.put(raw)
        lines.put(None)

    def pump_err() -> None:
        for raw in iter(proc.stderr.readline, b""):
            err_tail.append(raw.decode("utf-8", errors="replace"))
            del err_tail[:-40]

    threading.Thread(target=pump_out, daemon=True).start()
    threading.Thread(target=pump_err, daemon=True).start()

    def feed() -> None:
        try:
            proc.stdin.write(text_in.encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass

    threading.Thread(target=feed, daemon=True).start()

    read = READERS[engine.id]
    deadline = t0 + limit_min * 60
    started: dict[str, tuple[float, Step]] = {}
    last = time.monotonic()
    repeat_key, repeats = "", 0
    stop, reason = "done", ""
    halted: BaseException | None = None
    checked = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            if stop_event is not None and stop_event.is_set():
                stop, reason = "stopped", "stopped by the owner"
                break
            if now - checked >= 0.5:  # the run's Stop and money limit reach a CLI too (budget.check raises)
                checked = now
                try:
                    budget.check()
                except Exception as e:  # noqa: BLE001 - re-raised once the CLI is killed
                    halted, stop, reason = e, "stopped", str(e)
                    break
            if now > deadline:
                stop, reason = "breaker", f"{engine.name} ran past its {limit_min:g}-minute limit for one task"
                break
            try:
                raw = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if raw is None:
                break
            try:
                obj = json.loads(raw.decode("utf-8", errors="replace"))
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue
            for s in read(obj, st):
                now = time.monotonic()
                if s.kind == "text":
                    step += 1
                    st.done_steps += 1
                    emit("model_turn", {"model": str(ref), "step": step, "text": s.text[:500], "role": role,
                                        "tools": [], "cost": None, "ms": _ms(now - last), "engine": engine.id})
                    last = now
                elif s.kind == "tool_start":
                    started[s.call_id] = (now, s)
                    st.done_steps += 1
                    k = call_key(s.tool, s.args)
                    repeats = repeats + 1 if k == repeat_key else 1
                    repeat_key = k
                elif s.kind == "tool_end":
                    t_start, begun = started.pop(s.call_id, (now, Step("tool_start", tool="tool")))
                    took = now - t_start
                    tool_s += took
                    name = _CLAUDE_TOOLS.get(begun.tool, begun.tool) if engine.id == "claude-code" else begun.tool
                    row = {"tool": name, "args": _short(begun.args), "error": s.error, "result": s.output[:300],
                           "ms": _ms(took), "engine": engine.id, "engine_tool": begun.tool}
                    if name == "run_command":
                        out = s.output
                        row["output"] = out if len(out) <= 3000 else out[:1000] + "\n...\n" + out[-2000:]
                    emit("tool_call", row)
                    last = now
            s_cfg = brk.settings
            if s_cfg.enabled and s_cfg.max_tokens_per_task and work_tokens(st.usage) >= s_cfg.max_tokens_per_task:
                stop, reason = "breaker", (f"{work_tokens(st.usage):,} tokens used, over the "
                                           f"{s_cfg.max_tokens_per_task:,} for one task")
                break
            if s_cfg.enabled and s_cfg.repeats and repeats >= s_cfg.repeats:
                stop, reason = "breaker", f"the same step {repeats} times in a row"
                break
            if max_steps and st.turns > max_steps * 3:  # a CLI turn is smaller than a Roundtable step
                stop, reason = "breaker", f"more than {max_steps * 3} turns for one task"
                break
            if provider.bill == "api" and st.reported_usd is not None and \
                    budget.spent_usd + st.reported_usd >= budget.limit_usd:
                stop, reason = "breaker", "the run's money limit was reached"
                break
    finally:
        if proc.poll() is None and stop != "done":
            kill_tree(proc)
        try:
            proc.wait(timeout=30 if stop == "done" else 10)
        except subprocess.TimeoutExpired:
            kill_tree(proc)
        with _RUNNING_LOCK:
            _RUNNING.discard(proc)
            if proc.pid in _STOPPED:
                _STOPPED.discard(proc.pid)
                if stop == "done":
                    stop, reason = "stopped", "stopped by the owner"
    if halted is not None:
        raise halted
    if stop == "breaker":
        brk.trips.append({"signal": "cli", "reason": reason})
        emit("breaker", {"action": "stop", "signal": "cli", "reason": reason, "role": role, "step": step})
    if stop == "stopped":
        stop = "breaker"
    if stop == "done" and not st.done and proc.returncode not in (0, None):
        st.error = st.error or "".join(err_tail) or f"exit code {proc.returncode}"
    elif stop == "done" and not st.done and not st.last_text:
        st.error = st.error or "".join(err_tail) or "it ended without a result"
    return stop, reason, step, tool_s


def _short(args: dict[str, Any]) -> dict[str, Any]:
    return {k: (v[:120] + "..." if isinstance(v, str) and len(v) > 120 else v) for k, v in (args or {}).items()}

