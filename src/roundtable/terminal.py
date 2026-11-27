"""The desktop app's command line: type commands in a project's folder (the owner's own tool, on their own PC).

Not a full terminal. Each line runs through the platform's shell (``cmd`` on Windows, ``sh`` elsewhere) with
pipes, so programs that take over the whole screen (editors, ``top``) don't work, and the page says so. ``cd``
is Roundtable's own: the folder is kept between lines. Output goes to a ring buffer (512 KB); a line typed
while a program runs is sent to that program; Stop ends the whole process tree. The environment is
``clean_env()``: the owner's keys stay out even here.

At most four command lines are open at once; one nobody has looked at for 30 minutes is closed (and whatever
it was running is stopped). The API (``ui/terminalapi.py``) refuses unless the app is local-only, and none of
it is a phone route.
"""

from __future__ import annotations

import locale
import os
import re
import secrets
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from .harness.livecmd import kill_tree
from .harness.safeenv import clean_env

BUFFER_MAX = 512 * 1024
MAX_SESSIONS = 4
IDLE_SECONDS = 30 * 60
WAIT_MAX = 20.0  # a read waits at most this long for new output
_CD = re.compile(r"^\s*(?:cd|chdir)(?:\s+/d)?(?:\s+(?P<to>.*?))?\s*$", re.IGNORECASE)
_CHAINS = ("&&", "||", ";", "|", "&", "\n")


class TerminalError(Exception):
    pass


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode(locale.getpreferredencoding(False) or "utf-8", errors="replace")


def _cut_utf8(data: bytes) -> bytes:
    from .harness.livecmd import _cut_utf8 as cut

    return cut(data)


class Session:
    def __init__(self, folder: Path, project: str = ""):
        self.id = secrets.token_hex(6)
        self.start = self.folder = folder
        self.project = project
        self.buf = bytearray()
        self.base = 0  # the offset of buf[0] in everything this session ever printed
        self.proc: subprocess.Popen | None = None
        self.line = ""  # what is running now
        self.used = time.monotonic()
        self.closed = False
        self.cond = threading.Condition()
        self.history: list[str] = []

    # -- output ---------------------------------------------------------------------------------------
    @property
    def end(self) -> int:
        return self.base + len(self.buf)

    def write(self, data: bytes) -> None:
        with self.cond:
            self.buf += data
            extra = len(self.buf) - BUFFER_MAX
            if extra > 0:
                del self.buf[:extra]
                self.base += extra
            self.cond.notify_all()

    def say(self, text: str) -> None:
        self.write(text.encode("utf-8"))

    def read(self, since: int = 0, wait: float = 0.0) -> dict[str, Any]:
        self.used = time.monotonic()
        wait = max(0.0, min(float(wait or 0), WAIT_MAX))
        with self.cond:
            if wait and since >= self.end and not self.closed:
                state = self.proc is not None
                self.cond.wait_for(lambda: self.end > since or self.closed or (self.proc is not None) != state, wait)
            cut = since < self.base
            since = min(max(since, self.base), self.end)
            chunk = _cut_utf8(bytes(self.buf[since - self.base:]))
            return {"id": self.id, "text": _decode(chunk), "next": since + len(chunk), "cut": cut,
                    "running": self.proc is not None, "line": self.line, "folder": str(self.folder),
                    "closed": self.closed}

    # -- one line -------------------------------------------------------------------------------------
    def run(self, line: str) -> dict[str, Any]:
        self.used = time.monotonic()
        line = str(line or "").rstrip("\r\n")
        if self.closed:
            raise TerminalError("This command line was closed. Open a new one.")
        if self.proc is not None:
            raise TerminalError("Something is still running. Type into it, or press Stop first.")
        self.say(f"{self.folder}> {line}\n")
        if line.strip():
            self.history = [*self.history[-99:], line]
        if not line.strip():
            return self.view()
        m = _CD.match(line)
        if m and not any(c in line for c in _CHAINS):
            self._cd(m.group("to"))
            return self.view()
        kw: dict[str, Any] = {}
        if os.name != "nt":
            kw["start_new_session"] = True  # its own group, so Stop ends everything it started
        env = clean_env({"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
        try:
            proc = subprocess.Popen(line, shell=True, cwd=str(self.folder), env=env, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)
        except OSError as e:
            self.say(f"It couldn't start: {e}\n")
            return self.view()
        with self.cond:
            self.proc, self.line = proc, line
            self.cond.notify_all()
        threading.Thread(target=self._pump, args=(proc,), daemon=True).start()
        return self.view()

    def _cd(self, to: str | None) -> None:
        to = (to or "").strip()
        if len(to) >= 2 and to[0] == to[-1] and to[0] in "\"'":
            to = to[1:-1]
        elif to and os.name != "nt":
            try:
                to = " ".join(shlex.split(to))
            except ValueError:
                pass
        if not to:
            target = self.start  # back to where this command line began
        else:
            p = Path(os.path.expanduser(to))
            target = (p if p.is_absolute() else self.folder / p).resolve()
        if not target.is_dir():
            self.say(f"There's no folder called {to}.\n")
            return
        self.folder = target

    def _pump(self, proc: subprocess.Popen) -> None:
        fd = proc.stdout.fileno()
        while True:
            try:
                data = os.read(fd, 65536)
            except OSError:
                break
            if not data:
                break
            self.write(data)
        code = proc.wait()
        try:
            proc.stdout.close()
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        with self.cond:
            stopped = getattr(proc, "_rt_stopped", False)
            self.proc, self.line = None, ""
            if self.buf and not self.buf.endswith(b"\n"):
                self.buf += b"\n"
            note = "(stopped)\n" if stopped else (f"(exit code {code})\n" if code else "")
            self.buf += note.encode()
            self.cond.notify_all()

    def input(self, text: str) -> dict[str, Any]:
        self.used = time.monotonic()
        proc = self.proc
        if proc is None or proc.stdin is None:
            raise TerminalError("Nothing is running to type into. Type a command instead.")
        try:
            proc.stdin.write((str(text).rstrip("\r\n") + "\n").encode("utf-8"))
            proc.stdin.flush()
        except (OSError, ValueError):
            raise TerminalError("That program isn't reading any more.") from None
        self.say(str(text).rstrip("\r\n") + "\n")
        return self.view()

    def stop(self) -> dict[str, Any]:
        self.used = time.monotonic()
        proc = self.proc
        if proc is not None:
            proc._rt_stopped = True  # type: ignore[attr-defined]
            kill_tree(proc.pid)
        return self.view()

    def close(self) -> None:
        self.stop()
        with self.cond:
            self.closed = True
            self.cond.notify_all()

    def view(self) -> dict[str, Any]:
        return {"id": self.id, "folder": str(self.folder), "running": self.proc is not None, "line": self.line,
                "next": self.end, "project": self.project, "history": self.history[-50:]}


class Terminals:
    """The open command lines of one app."""

    def __init__(self):
        self.sessions: dict[str, Session] = {}
        self.lock = threading.Lock()

    def reap(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self.lock:
            for sid, s in list(self.sessions.items()):
                if s.closed or now - s.used > IDLE_SECONDS:
                    s.close()
                    self.sessions.pop(sid, None)

    def open(self, folder: str | Path, project: str = "", fresh: bool = False) -> Session:
        self.reap()
        folder = Path(folder).expanduser().resolve()
        if not folder.is_dir():
            raise TerminalError("That folder isn't there any more.")
        with self.lock:
            if not fresh:
                for s in self.sessions.values():
                    if s.project == project and s.start == folder and not s.closed:
                        s.used = time.monotonic()
                        return s
            if len(self.sessions) >= MAX_SESSIONS:
                raise TerminalError(f"{MAX_SESSIONS} command lines are open already. Close one to open another.")
            s = Session(folder, project)
            self.sessions[s.id] = s
            return s

    def get(self, sid: str) -> Session:
        self.reap()
        s = self.sessions.get(str(sid or ""))
        if s is None:
            raise TerminalError("That command line has closed (nobody looked at it for 30 minutes, or the app "
                                "restarted). Open a new one.")
        return s

    def close(self, sid: str) -> None:
        with self.lock:
            s = self.sessions.pop(str(sid or ""), None)
        if s:
            s.close()

    def close_all(self) -> None:
        for sid in list(self.sessions):
            self.close(sid)
