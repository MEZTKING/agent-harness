"""Starting the thing built: an app that starts with a command, run for as long as it is looked at.

``Running`` is a context manager. It runs the app's start command in its folder with a free port passed as
``PORT`` (and ``{port}`` in the command filled in), waits for the port to answer, and always ends the whole
process tree when it is done – after an error too::

    with Running(folder, "npm start", ws=self.ws) as app:
        if app.ok:
            ...  # app.url is http://127.0.0.1:<port>/
        else:
            ...  # app.error says why in plain words; nothing was raised

The command goes the way every command of the harness goes: the gate ("Ask me first") is asked first, the
environment is the clean one (no keys, no git login: safeenv.py), and the output is written to the live log
(``.harness/live/<task>-<n>.log``, listed in ``running.json``), so the app's Stop and ``livecmd.stop_strays``
reach it. It doesn't go through ``Workspace.run_command`` itself only because that waits for the command to
end, and a web server never does.

``start_recipe`` says what to start: the kind's ``start: {command, port?, ready?}`` first, else the folder's own
``package.json`` start (``showit.start_command``). ``needs_start`` says whether the static page alone would be
the wrong picture of the app (it needs building, or there is no page without the command).
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from . import livecmd
from .safeenv import clean_env

START_SECONDS = 60  # finish.start_seconds: how long an app may take to open its port
LIFETIME = 4 * 3600  # how long the live list may treat a started app as ours
TAIL_MAX = 4000  # characters of the app's output kept for the evidence
_URL = re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]):(\d{2,5})")
# a page that needs building first: a bundler in package.json, or a page that loads source files directly
_BUNDLERS = ("vite", "next", "react-scripts", "webpack", "parcel", "@angular/cli", "nuxt", "astro", "svelte-kit",
             "@sveltejs/kit", "remix", "gatsby", "esbuild", "rollup", "snowpack")
_SOURCE_SCRIPT = re.compile(r"<script[^>]+src=[\"'][^\"']*\.(?:ts|tsx|jsx|vue|svelte)[\"']", re.I)


class StartFailed(Exception):
    """The app couldn't be started (the gate said no, commands are off, the command ended at once…)."""


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


# -- what to start -------------------------------------------------------------------------------------------
def _clean_recipe(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not str(raw.get("command") or "").strip():
        return None
    out: dict[str, Any] = {"command": str(raw["command"]).strip()}
    try:
        if raw.get("port") not in (None, ""):
            p = int(raw["port"])
            if 0 < p < 65536:
                out["port"] = p
    except (TypeError, ValueError):
        pass
    ready = str(raw.get("ready") or "").strip()
    if ready:
        out["ready"] = ready if ready.startswith("/") else "/" + ready
    return out


def start_recipe(folder: Path, kind_start: Any = None) -> dict[str, Any] | None:
    """{command, port?, ready?, from} for the folder, or None when nothing says how to start it.
    ``from`` is ``kind`` (the kind's own recipe) or ``package.json``."""
    got = _clean_recipe(kind_start)
    if got:
        return {**got, "from": "kind"}
    from .showit import start_command

    cmd = start_command(folder)
    return {"command": cmd, "from": "package.json"} if cmd else None


def needs_start(folder: Path, recipe: dict[str, Any] | None) -> bool:
    """True when the app should be started with its command to be seen as it really is: the kind says how,
    there is no plain page, the page loads source files a browser can't read, or a bundler builds it."""
    if not recipe:
        return False
    if recipe.get("from") == "kind":
        return True
    from .showit import entry_page

    folder = Path(folder)
    entry = entry_page(folder)
    if not entry:
        return True
    try:
        if _SOURCE_SCRIPT.search((folder / entry).read_text(encoding="utf-8", errors="replace")):
            return True
    except OSError:
        pass
    try:
        pkg = json.loads((folder / "package.json").read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return False
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    return any(b in deps for b in _BUNDLERS)


# -- running it ----------------------------------------------------------------------------------------------
class Running:
    """One app, started for as long as the ``with`` lasts. Never raises from ``__enter__``: ``ok`` and
    ``error`` say how it went; ``__exit__`` ends everything it started, whatever happened."""

    def __init__(self, folder: Path, command: str, ws: Any = None, port: int | None = None, ready: str = "",
                 seconds: float = START_SECONDS, live: tuple[Path, str] | None = None,
                 ask: Callable[[str], str | None] | None = None, env: dict[str, str] | None = None):
        self.folder = Path(folder)
        self.command = str(command or "").strip()
        self.ws = ws
        self.port = int(port) if port else 0
        self.ready = ready or ""
        self.seconds = float(seconds or START_SECONDS)
        self.live = live
        self.ask = ask
        self.env = env
        self.proc: subprocess.Popen | None = None
        self.ok = False
        self.error = ""
        self.refused = False  # the gate said no or commands are off: not the app's fault
        self.url = ""
        self.started_at = 0.0
        self._out: list[bytes] = []
        self._log = None
        self._registry: Path | None = None
        self._lock = threading.Lock()

    # the gate, the way Workspace.run_command asks it
    def _refused(self) -> str | None:
        if not self.command:
            return "there is no start command"
        if self.ws is not None and not getattr(self.ws, "allow_shell", True):
            return "commands are switched off for this project, so the app can't be started"
        if self.ask is not None:
            return self.ask(self.command)
        gate = getattr(self.ws, "gate", None) if self.ws is not None else None
        return gate.check(self.command) if gate is not None else None

    def __enter__(self) -> "Running":
        try:
            self._start()
        except StartFailed as e:
            self.error = str(e)
            self._end()
        except Exception as e:  # noqa: BLE001 - starting it is a help: written down, never raised
            self.error = f"the app couldn't be started: {str(e)[:300]}"
            self._end()
        return self

    def __exit__(self, *exc) -> None:
        self._end()

    def _start(self) -> None:
        refused = self._refused()
        if refused:
            self.refused = True
            raise StartFailed(refused)
        port = self.port or free_port()
        env = dict(self.env) if self.env is not None else clean_env()
        env.update({"PORT": str(port), "HOST": "127.0.0.1", "BROWSER": "none", "CI": "1"})
        command = self.command.replace("{port}", str(port))
        kw: dict[str, Any] = {}
        if os.name == "nt":
            kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kw["start_new_session"] = True  # its own group, so ending it ends everything it started
        live_root, live_task = self.live or ((self.ws.live if self.ws is not None and getattr(self.ws, "live", None)
                                              else (self.folder, "app")))
        slot = livecmd.slot(live_root, live_task)
        try:
            self._log = open(slot.log, "ab", buffering=0)
            self._log.write(("$ " + command.replace("\n", " ") + "\n").encode("utf-8", errors="replace"))
        except OSError:
            self._log = None
        self.started_at = time.time()
        self.proc = subprocess.Popen(command, shell=True, cwd=self.folder, env=env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)
        self._registry = slot.registry
        entry = {"pid": self.proc.pid, "task": slot.task, "n": slot.n, "command": command[:500],
                 "started": self.started_at, "until": self.started_at + LIFETIME, "log": slot.log.name}
        with livecmd._lock:
            livecmd._running[self.proc.pid] = {"proc": self.proc, "root": str(live_root), "task": slot.task,
                                               "n": slot.n, "stopped": False}
            livecmd._write_registry(slot.registry, [*livecmd._read_registry(slot.registry), entry])
        threading.Thread(target=self._pump, daemon=True).start()
        self._wait(port)

    def _pump(self) -> None:
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        fd = proc.stdout.fileno()
        while True:
            try:
                data = os.read(fd, 65536)
            except OSError:
                break
            if not data:
                break
            with self._lock:
                self._out.append(data)
                if sum(len(x) for x in self._out) > 200_000:
                    self._out = self._out[-20:]
            if self._log is not None:
                try:
                    self._log.write(data)
                except (OSError, ValueError):
                    self._log = None

    def output(self) -> str:
        with self._lock:
            text = b"".join(self._out).decode("utf-8", errors="replace")
        return text[-TAIL_MAX:]

    def _wait(self, port: int) -> None:
        deadline = time.time() + self.seconds
        while time.time() < deadline:
            if port_open(port):
                return self._answered(port)
            seen = _URL.findall(self.output())  # a dev server that picked its own port and said so
            for p in reversed(seen):
                if int(p) != port and port_open(int(p)):
                    return self._answered(int(p))
            if self.proc is not None and self.proc.poll() is not None:
                tail = self.output().strip().splitlines()[-3:]
                raise StartFailed(f"the start command ended at once (exit code {self.proc.returncode})"
                                  + (f": {' / '.join(tail)[:300]}" if tail else ""))
            time.sleep(0.15)
        raise StartFailed(f"the app didn't open its address within {self.seconds:g} seconds "
                          f"(it was given port {port} in PORT)")

    def _answered(self, port: int) -> None:
        self.port = port
        self.url = f"http://127.0.0.1:{port}/"
        if self.ready:
            deadline = time.time() + max(5.0, self.seconds / 2)
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen(self.url.rstrip("/") + self.ready, timeout=2) as r:
                        if r.status < 500:
                            break
                except urllib.error.HTTPError as e:
                    if e.code < 500:
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(0.3)
            else:
                raise StartFailed(f"the app opened port {port} but {self.ready} never answered")
        self.ok = True

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _end(self) -> None:
        proc, self.proc = self.proc, None
        if proc is not None:
            if proc.poll() is None:
                livecmd.kill_tree(proc.pid)
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    proc.wait(2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            try:
                if proc.stdout is not None:
                    proc.stdout.close()
            except OSError:
                pass
            with livecmd._lock:
                livecmd._running.pop(proc.pid, None)
            if self._registry is not None:
                livecmd._drop(self._registry, lambda c: c.get("pid") == proc.pid)
        if self._log is not None:
            try:
                self._log.write(b"\n[stopped: the harness ended the app]\n")
                self._log.close()
            except (OSError, ValueError):
                pass
            self._log = None
