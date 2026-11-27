"""A task's command shown as it prints, with a Stop for that one command ("Every task must be easy to see").

``run_streaming`` runs a worker's shell command the way ``tools.run_command`` always has (the same shell, folder,
environment and timeout, and the same text back), but writes the output to ``.harness/live/<task>-<n>.log`` as it
arrives and keeps the running commands in ``.harness/live/running.json``, so the app (and the phone, read only) can
follow it and stop it:

    .harness/live/<task>-<n>.log   "$ <command>\\n", the output as it came (stdout and stderr in arrival order),
                                   then one closing line: "[exit code 0]", "[stopped]" or "[timed out after 60s]"
    .harness/live/running.json     {"commands": [{pid, task, n, command, started, until, log}]}

``stop(root, task)`` ends one task's running command and everything it started (the process group, or
``taskkill /T /F`` on Windows); the worker is told the owner stopped it. ``stop_strays(root)`` ends whatever is
still listed after a run (a crash, the app's Stop). Nothing here decides what may run: the gate ("Ask me first")
has already said yes, and the environment is the one handed in (``clean_env()``: no keys).
"""

from __future__ import annotations

import json
import locale
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .safeenv import clean_env

LIVE = Path(".harness") / "live"
REGISTRY = "running.json"
LOG_MAX = 4_000_000  # bytes of one command's output kept on disk; the worker's own copy is not cut here
TAIL_MAX = 64_000  # bytes sent the first time a log is read; later reads send what is new
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")

_lock = threading.RLock()
_running: dict[int, dict[str, Any]] = {}  # pid -> {proc, root, task, n, stopped}: this process's own commands


class Stopped(Exception):
    """The owner pressed Stop on this command."""


@dataclass
class Slot:
    log: Path
    registry: Path
    task: str
    n: int


def live_dir(root: str | Path) -> Path:
    return Path(root) / LIVE


def safe_task(task: str) -> str:
    return _SAFE.sub("-", str(task or "run")).strip("-.")[:80] or "run"


def _logs(root: str | Path, task: str) -> list[tuple[int, Path]]:
    d = live_dir(root)
    if not d.is_dir():
        return []
    pat = re.compile(re.escape(safe_task(task)) + r"-(\d+)\.log$")
    out = [(int(m.group(1)), p) for p in d.iterdir() if (m := pat.match(p.name))]
    return sorted(out)


def slot(root: str | Path, task: str) -> Slot:
    """Where the next command of ``task`` writes: the next free ``<task>-<n>.log`` (made empty now)."""
    with _lock:
        d = live_dir(root)
        d.mkdir(parents=True, exist_ok=True)
        logs = _logs(root, task)
        n = (logs[-1][0] + 1) if logs else 1
        log = d / f"{safe_task(task)}-{n}.log"
        log.write_bytes(b"")
        return Slot(log, d / REGISTRY, safe_task(task), n)


# -- the registry -------------------------------------------------------------------------------------
def _read_registry(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [c for c in data.get("commands", []) if isinstance(c, dict)]
    except (OSError, ValueError, AttributeError):
        return []


def _write_registry(path: Path, commands: list[dict[str, Any]]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"commands": commands}, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass  # the live view is a help, never a reason for a command to fail


def running(root: str | Path) -> list[dict[str, Any]]:
    """The commands listed as running in this project (any process's)."""
    return _read_registry(live_dir(root) / REGISTRY)


# -- stopping a whole process tree ---------------------------------------------------------------------
def kill_tree(pid: int) -> None:
    """End ``pid`` and everything it started: Roundtable's own command, never anything a worker wrote."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, env=clean_env())
        else:
            os.killpg(pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass


def _still_ours(rec: dict[str, Any]) -> bool:
    """A command listed by another (perhaps crashed) process: only stopped while it can still be the same one."""
    pid = int(rec.get("pid") or 0)
    if pid <= 0 or time.time() > float(rec.get("until") or 0):
        return False  # past its own timeout: the number may belong to something else by now
    if os.name != "nt":
        try:
            return os.getpgid(pid) == pid  # it was started as the head of its own group
        except (OSError, ProcessLookupError):
            return False
    return True


def stop(root: str | Path, task: str, n: int | None = None) -> int:
    """Stop the running command(s) of one task (or only its ``n``th). Returns how many were stopped."""
    task = safe_task(task)
    done = 0
    with _lock:
        mine = [(pid, r) for pid, r in _running.items()
                if Path(r["root"]) == Path(root) and r["task"] == task and (n is None or r["n"] == n)]
        for pid, r in mine:
            r["stopped"] = True
            kill_tree(pid)
            done += 1
        if done:
            return done
        for rec in running(root):
            if rec.get("task") == task and (n is None or rec.get("n") == n) and _still_ours(rec):
                kill_tree(int(rec["pid"]))
                done += 1
        if done:
            _drop(live_dir(root) / REGISTRY, lambda c: c.get("task") == task and (n is None or c.get("n") == n))
    return done


def stop_strays(root: str | Path) -> int:
    """After a run (or the app's Stop): end every command still listed for this project and empty the list."""
    done = 0
    with _lock:
        for pid, r in list(_running.items()):
            if Path(r["root"]) == Path(root):
                r["stopped"] = True
                kill_tree(pid)
                done += 1
        for rec in running(root):
            if int(rec.get("pid") or 0) not in _running and _still_ours(rec):
                kill_tree(int(rec["pid"]))
                done += 1
        reg = live_dir(root) / REGISTRY
        if reg.exists():
            _write_registry(reg, [c for c in _read_registry(reg) if int(c.get("pid") or 0) in _running])
    return done


def _drop(reg: Path, gone) -> None:
    with _lock:
        _write_registry(reg, [c for c in _read_registry(reg) if not gone(c)])


# -- running one command ------------------------------------------------------------------------------
def _text_encoding() -> str:
    """The encoding ``subprocess.run(text=True)`` decodes with, so the text the worker gets stays the same."""
    fn = getattr(subprocess, "_text_encoding", None)
    return fn() if callable(fn) else locale.getpreferredencoding(False)


def _text(data: bytes, encoding: str) -> str:
    # exactly what subprocess does in text mode: decode, then universal newlines
    return data.decode(encoding).replace("\r\n", "\n").replace("\r", "\n")


def run_streaming(command: str, cwd: str | Path, env: dict[str, str], timeout: float,
                  log: Path | Slot | None = None, registry: Path | None = None, *, root: str | Path | None = None,
                  task: str = "run", n: int = 0) -> subprocess.CompletedProcess:
    """Run ``command`` in the shell like ``subprocess.run(shell=True, capture_output=True, text=True)``, writing
    its output to ``log`` as it arrives. Raises ``subprocess.TimeoutExpired`` (after ending the whole tree) and
    ``Stopped`` when the owner stopped it."""
    if isinstance(log, Slot):
        registry, task, n, log = log.registry, log.task, log.n, log.log
    root = Path(root) if root is not None else (registry.parent.parent.parent if registry else Path(cwd))
    kw: dict[str, Any] = {}
    if os.name != "nt":
        kw["start_new_session"] = True  # its own group, so Stop and a timeout end everything it started
    proc = subprocess.Popen(command, shell=True, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)
    started = time.time()
    out_chunks: list[bytes] = []
    err_chunks: list[bytes] = []
    write_lock = threading.Lock()
    fh = None
    written = [0]
    if log is not None:
        try:
            fh = open(log, "ab", buffering=0)
            fh.write(("$ " + command.replace("\n", " ") + "\n").encode("utf-8", errors="replace"))
        except OSError:
            fh = None

    def to_log(data: bytes) -> None:
        nonlocal fh
        if fh is None:
            return
        with write_lock:
            try:
                room = LOG_MAX - written[0]
                if room > 0:
                    fh.write(data[:room])
                    written[0] += min(len(data), room)
                    if len(data) > room:
                        fh.write(b"\n... (more output, not kept here) ...\n")
            except OSError:
                fh = None

    def pump(stream, into: list[bytes]) -> None:
        fd = stream.fileno()
        while True:
            try:
                data = os.read(fd, 65536)
            except OSError:
                break
            if not data:
                break
            into.append(data)
            to_log(data)

    readers = [threading.Thread(target=pump, args=(proc.stdout, out_chunks), daemon=True),
               threading.Thread(target=pump, args=(proc.stderr, err_chunks), daemon=True)]
    for t in readers:
        t.start()
    entry = {"pid": proc.pid, "task": task, "n": n, "command": command[:500], "started": started,
             "until": started + float(timeout) + 60, "log": log.name if log is not None else ""}
    with _lock:
        _running[proc.pid] = {"proc": proc, "root": str(root), "task": task, "n": n, "stopped": False}
        if registry is not None:
            _write_registry(registry, [*_read_registry(registry), entry])

    end_line = ""
    try:
        deadline = started + float(timeout)
        try:
            proc.wait(timeout=max(0.0, deadline - time.time()))
            for t in readers:  # like communicate(): the output is whole once both pipes close
                t.join(max(0.0, deadline - time.time()))
            if any(t.is_alive() for t in readers):
                raise subprocess.TimeoutExpired(command, timeout)
        except subprocess.TimeoutExpired:
            kill_tree(proc.pid)
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
            for t in readers:
                t.join(2)
            with _lock:
                stopped = _running.get(proc.pid, {}).get("stopped")
            end_line = "[stopped]" if stopped else f"[timed out after {timeout:g}s]"
            if stopped:
                raise Stopped() from None
            raise subprocess.TimeoutExpired(command, timeout) from None
        with _lock:
            stopped = _running.get(proc.pid, {}).get("stopped")
        if stopped:
            end_line = "[stopped]"
            raise Stopped()
        end_line = f"[exit code {proc.returncode}]"
        enc = _text_encoding()
        return subprocess.CompletedProcess(command, proc.returncode, _text(b"".join(out_chunks), enc),
                                           _text(b"".join(err_chunks), enc))
    finally:
        for s in (proc.stdout, proc.stderr):
            try:
                s.close()
            except OSError:
                pass
        with _lock:
            _running.pop(proc.pid, None)
            if registry is not None:
                _drop(registry, lambda c: c.get("pid") == proc.pid)
        if fh is not None:
            try:
                with write_lock:
                    fh.write(("\n" + (end_line or "[ended]") + "\n").encode("utf-8"))
                    fh.close()
            except OSError:
                pass


# -- reading a task's output -----------------------------------------------------------------------------
def _cut_utf8(data: bytes) -> bytes:
    """Hold back a character split at the end, so the next read starts on a whole one."""
    for back in range(1, min(4, len(data)) + 1):
        b = data[-back]
        if b & 0xC0 == 0x80:
            continue  # a continuation byte: look further back
        if b & 0x80 == 0:
            return data
        need = 2 if b & 0xE0 == 0xC0 else 3 if b & 0xF0 == 0xE0 else 4
        return data if back >= need else data[:-back]
    return data


def tail(root: str | Path, task: str, since: int = 0, n: int | None = None) -> dict[str, Any]:
    """What one task's newest command printed since byte ``since`` (``n``: the command the reader had)."""
    logs = _logs(root, task)
    if not logs:
        return {"task": safe_task(task), "n": 0, "command": "", "text": "", "next": 0, "running": False,
                "ended": "", "words": "No command has run in this task yet."}
    latest, path = logs[-1]
    if n is not None and n != latest:
        since = 0  # a new command started: begin again
    try:
        data = path.read_bytes()
    except OSError:
        data = b""
    first_nl = data.find(b"\n")
    command = data[2:first_nl].decode("utf-8", errors="replace") if data.startswith(b"$ ") and first_nl > 0 else ""
    body_start = first_nl + 1 if command else 0
    since = max(int(since or 0), body_start)
    skipped = 0
    if since == body_start and len(data) - since > TAIL_MAX:
        skipped = len(data) - TAIL_MAX - since
        since = len(data) - TAIL_MAX
    chunk = _cut_utf8(data[since:]) if since < len(data) else b""
    is_running = any(c.get("task") == safe_task(task) and c.get("n") == latest for c in running(root))
    text = chunk.decode("utf-8", errors="replace")
    ended = ""
    m = re.search(r"\n(\[(?:exit code -?\d+|stopped|timed out after [\d.]+s|ended)\])\n$", data.decode("utf-8", "replace"))
    if m and not is_running:
        ended = m.group(1)
    words = ("Running now." if is_running else
             "The owner stopped it." if ended == "[stopped]" else
             "It ran out of time and was stopped." if ended.startswith("[timed out") else
             "Finished." if ended == "[exit code 0]" else
             f"Finished with a problem ({ended.strip('[]')})." if ended else "Finished.")
    return {"task": safe_task(task), "n": latest, "command": command, "text": text, "next": since + len(chunk),
            "skipped": skipped, "running": is_running, "ended": ended, "words": words, "commands": len(logs)}
