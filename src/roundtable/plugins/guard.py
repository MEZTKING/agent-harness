"""The plugin box's rules, and the Python audit hook that holds a boxed plugin to them.

This is layer 2 of the box (``sandbox.py`` has the whole picture). It is imported by the box's
child process before the plugin's code, as a module on its own: it imports nothing from the rest
of the harness, only the standard library.

``Rules.decide(event, args)`` is pure apart from looking at the file system (resolving links,
telling folders from files): it says whether one audit event is allowed and, if not, why, in
words the owner reads ("go on the internet (connect to 1.2.3.4)"). ``install(rules, report)``
adds the audit hook; Python has no way to take an audit hook away again.

Two kinds of refusal:

* a refused **action** (a socket, a file outside the plugin's places, a program) raises
  ``PermissionError`` and is *reported*: the parent switches the plugin off for the run even if
  the plugin caught the error;
* a refused **import** (``ctypes``, ``cffi``, the registry, the rest of the harness) raises
  ``ImportError`` and is not reported, because libraries often try such imports and carry on
  without them.

The honest limit: this runs inside the plugin's own Python, so it stops a plugin that tries, not
one written on purpose to break out (by rewriting this hook's state through frames, say). The
operating system layers in ``sandbox.py`` (bwrap or unshare on Linux, a Job Object on Windows)
are what a deliberate attempt meets.
"""

from __future__ import annotations

import os
import re
import sys
import threading
import types
from typing import Any, Callable, Iterable

# The same rule as roundtable.search.SECRET_NAME (a test keeps the two equal): files a plugin
# that may read the project still never sees.
SECRET_NAME = re.compile(r"^(\.env(\..*)?|.*\.(pem|key|p12|pfx|jks|keystore)|id_(rsa|ed25519|ecdsa)(\.pub)?|"
                         r"\.npmrc|\.pypirc|\.netrc|credentials(\.json)?)$", re.IGNORECASE)
PRIVATE_DIRS = {".git", ".harness"}  # a project's history (remote links can hold tokens) and the harness's own

COMPILED = (".pyd", ".so", ".dll", ".dylib", ".exe")
SCAN_SKIP = {".git", "__pycache__", "node_modules", ".venv", "venv"}  # never on the plugin's import path

AF_UNIX = 1  # the same number on Linux, macOS and Windows

# Imports refused unless the plugin may run programs: native code the audit hook can't see into.
NATIVE_IMPORTS = {"ctypes", "_ctypes", "cffi", "_cffi_backend", "_posixsubprocess"}
REGISTRY_IMPORTS = {"winreg", "_winreg"}  # Windows' registry: refused unless the plugin may use files

PROCESS_EVENTS = {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork",
                  "os.forkpty", "os.startfile", "pty.spawn", "os.killpg", "os.add_dll_directory",
                  "_winapi.CreateProcess", "_winapi.OpenProcess", "_winapi.TerminateProcess", "webbrowser.open"}
NET_EVENTS = {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo",
              "socket.sethostname", "urllib.Request", "http.client.connect", "ftplib.connect", "smtplib.connect",
              "poplib.connect", "imaplib.open", "nntplib.connect", "telnetlib.Telnet.open"}
SOCKET_ADDRESS_EVENTS = {"socket.connect", "socket.bind", "socket.sendto", "socket.sendmsg"}
# Ways into the box's own state (and into the guard): never allowed, whatever the permissions.
# (code.__new__ can't be on the list: asyncio's types.coroutine makes code objects as it loads.)
INTROSPECTION_EVENTS = {"gc.get_objects", "gc.get_referrers", "gc.get_referents", "sys._current_frames",
                        "sys._current_exceptions", "sys.settrace", "sys.setprofile",
                        "sys.monitoring.register_callback", "sys.remote_exec", "cpython.remote_debugger_script"}
READ_EVENTS = {"os.listdir": (0,), "os.scandir": (0,), "os.listxattr": (0,), "os.getxattr": (0,)}
WRITE_EVENTS = {"os.remove": (0,), "os.rmdir": (0,), "os.mkdir": (0,), "os.rename": (0, 1), "os.chmod": (0,),
                "os.chown": (0,), "os.chflags": (0,), "os.lchflags": (0,), "os.lchmod": (0,), "os.utime": (0,),
                "os.truncate": (0,), "os.setxattr": (0,), "os.removexattr": (0,), "os.mkfifo": (0,),
                "os.mknod": (0,)}
LINK_EVENTS = {"os.link", "os.symlink", "_winapi.CreateJunction"}
DRIVE_EVENTS = {"os.listdrives", "os.listvolumes", "os.listmounts"}

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_GENERIC_WRITE = 0x40000000 | 0x10000000  # GENERIC_WRITE | GENERIC_ALL
_OPEN_EXISTING = 3


class BoxImportRefused(ImportError):
    """An import the box doesn't allow (a library may catch it and carry on)."""


def is_compiled(name: str) -> bool:
    n = name.lower()
    return n.endswith(COMPILED) or ".so." in n


def compiled_files(folder: Any, most: int = 20) -> list[str]:
    """Compiled files (``.pyd``, ``.so``, ``.dll``, ``.dylib``, ``.exe``) in a plugin's folder, ``.deps``
    included: code the audit hook can't watch. Paths relative to the folder, at most ``most``."""
    root = os.fspath(folder)
    found: list[str] = []
    if not os.path.isdir(root):
        return found
    for here, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SCAN_SKIP)
        for f in sorted(files):
            if is_compiled(f):
                found.append(os.path.relpath(os.path.join(here, f), root).replace(os.sep, "/"))
                if len(found) >= most:
                    return found
    return found


def _norm(p: str) -> str:
    return os.path.normcase(p)


def real(path: Any, cwd: str | None = None) -> str:
    """The real, absolute path (links resolved), compared case-blind where the system is."""
    p = os.fsdecode(os.fspath(path))
    if not os.path.isabs(p):
        p = os.path.join(cwd or os.getcwd(), p)
    return _norm(os.path.realpath(p))


def inside(p: str, root: str) -> bool:
    return p == root or p.startswith(root.rstrip(os.sep) + os.sep)


class Rules:
    """What one boxed plugin may touch. ``granted``: its permissions (network, files, shell,
    project:read, secrets:<host>). Places: its data folder (read and write), the read-only roots
    (its code, the standard library) and, with project:read, the projects it is helping with."""

    def __init__(self, data_dir: Any, read_roots: Iterable[Any] = (), granted: Iterable[str] = (),
                 read_files: Iterable[Any] = ()):
        self.granted = frozenset(granted)
        self.net = "network" in self.granted
        self.files = "files" in self.granted
        self.shell = "shell" in self.granted
        self.project_read = "project:read" in self.granted
        self.data = real(data_dir)
        self.read_roots = tuple(dict.fromkeys(real(p) for p in read_roots if p))
        extra = [os.devnull, "/dev/urandom", "/dev/random", "/etc/localtime", "/etc/timezone", "/etc/os-release",
                 "/usr/lib/os-release"]
        self.read_files = frozenset(real(p) for p in [*read_files, *extra] if p)
        self.devnull = real(os.devnull)
        self.projects: tuple[str, ...] = ()

    def allow_project(self, path: Any) -> None:
        """The project a call is helping with (only with project:read)."""
        if self.project_read and path:
            p = real(path)
            if p not in self.projects:
                self.projects = (*self.projects, p)

    # -- places -------------------------------------------------------------------------
    def _project_part(self, p: str) -> str | None:
        """None when ``p`` is readable project content; else why not ("" = not in a project)."""
        for root in self.projects:
            if inside(p, root):
                parts = [x for x in p[len(root):].split(os.sep) if x]
                if any(x in PRIVATE_DIRS for x in parts) or (parts and SECRET_NAME.match(parts[-1])):
                    return "read a private file in the project (" + "/".join(parts) + ")"
                return None
        return ""

    def may_read(self, path: Any) -> str | None:
        if self.files:
            return None
        p = real(path)
        if p in self.read_files or inside(p, self.data) or any(inside(p, r) for r in self.read_roots):
            return None
        why = self._project_part(p)
        if why is None:
            return None
        return why or f"read a file outside its own folder ({_show(path)})"

    def may_write(self, path: Any) -> str | None:
        p = real(path)
        if not self.shell and is_compiled(p):
            return f"write a compiled file ({_show(path)})"
        if self.files or p == self.devnull or inside(p, self.data):
            return None
        return f"change a file outside its own folder ({_show(path)})"

    # -- one event --------------------------------------------------------------------------
    def decide(self, event: str, args: tuple) -> tuple[str, bool] | None:
        """None if allowed; else (what it tried to do, soft). Soft: an import, not reported."""
        if event == "import":
            name = str(args[0]) if args else ""
            top = name.split(".")[0]
            if top == "roundtable":
                return f"use the rest of the harness ({name})", True
            if top in NATIVE_IMPORTS and not self.shell:
                return f"run compiled code ({name})", True
            if top in REGISTRY_IMPORTS and not self.files:
                return f"read Windows' registry ({name})", True
            return None
        if event == "open":
            return self._open(args)
        if event in READ_EVENTS:
            return self._paths(args, READ_EVENTS[event], self.may_read)
        if event in WRITE_EVENTS:
            return self._paths(args, WRITE_EVENTS[event], self.may_write)
        if event == "os.chdir":
            return self._chdir(args)
        if event in LINK_EVENTS:
            return None if self.files else (f"make a link between files ({_show(args[0]) if args else ''})", False)
        if event in DRIVE_EVENTS:
            return None if self.files else ("list the computer's drives", False)
        if event == "sqlite3.connect":
            return self._sqlite(args)
        if event == "_winapi.CreateFile":
            return self._winfile(args)
        if event.startswith("winreg."):
            return None if self.files else ("read Windows' registry", False)
        if event == "socket.__new__":
            family = args[1] if len(args) > 1 else -1
            if self.net or family == AF_UNIX:
                return None
            return "go on the internet (open a network socket)", False
        if event in SOCKET_ADDRESS_EVENTS:
            return self._address(event, args)
        if event in NET_EVENTS:
            return None if self.net else (f"go on the internet ({event.split('.')[0]})", False)
        if event == "os.kill":
            if self.shell or (args and args[0] == os.getpid()):
                return None
            return "stop or signal another program", False
        if event in PROCESS_EVENTS:
            return None if self.shell else (f"run another program ({_program(event, args)})", False)
        if event.startswith(("ctypes.", "cffi.")):
            return None if self.shell else ("run compiled code (ctypes)", False)
        if event in INTROSPECTION_EVENTS:
            return f"look inside the box itself ({event})", False
        return None

    def _open(self, args: tuple) -> tuple[str, bool] | None:
        path = args[0] if args else None
        if path is None or isinstance(path, int):
            return None  # a file it already has open
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else 0
        writing = any(c in mode for c in "wax+") if isinstance(mode, str) else bool((flags or 0) & _WRITE_FLAGS)
        why = self.may_write(path) if writing else self.may_read(path)
        if why is None and not self.files:
            p = real(path)
            if os.path.isdir(p) and not inside(p, self.data):
                why = f"open a folder outside its own folder ({_show(path)})"
        return (why, False) if why else None

    def _paths(self, args: tuple, which: tuple[int, ...], check: Callable[[Any], str | None]):
        for i in which:
            if i < len(args) and args[i] is not None and not isinstance(args[i], int):
                why = check(args[i])
                if why:
                    return why, False
        return None

    def _chdir(self, args: tuple):
        if self.files:
            return None
        path = args[0] if args else None
        if isinstance(path, int) or path is None:
            return "change its working folder", False
        return None if inside(real(path), self.data) else (f"move out of its own folder ({_show(path)})", False)

    def _sqlite(self, args: tuple):
        db = os.fsdecode(args[0]) if args and args[0] is not None else ""
        if db in ("", ":memory:"):
            return None
        if db.startswith("file:"):
            db = db[5:].split("?", 1)[0]
            if db in ("", ":memory:"):
                return None
        why = self.may_write(db)
        return (why, False) if why else None

    def _winfile(self, args: tuple):
        name = args[0] if args else None
        if name is None:
            return None
        access = args[1] if len(args) > 1 else 0
        disposition = args[3] if len(args) > 3 else _OPEN_EXISTING
        s = os.fsdecode(name)
        if s.lower().startswith("\\\\.\\pipe\\"):
            # only its own process's pipes (asyncio and multiprocessing put the pid in the name),
            # never another program's (a database's, a container engine's)
            return None if f"-{os.getpid()}-" in s else ("talk to another program (a named pipe)", False)
        writing = bool((access or 0) & _GENERIC_WRITE) or disposition != _OPEN_EXISTING
        why = self.may_write(s) if writing else self.may_read(s)
        return (why, False) if why else None

    def _address(self, event: str, args: tuple):
        if self.net:
            return None
        address = args[1] if len(args) > 1 else None
        if isinstance(address, (str, bytes)):
            text = os.fsdecode(address)
            if not text or text.startswith("\0"):
                return "talk to another program (a hidden local socket)", False
            if event == "socket.bind":
                why = self.may_write(text)
            else:
                p = real(text)
                why = None if inside(p, self.data) else f"talk to another program ({_show(text)})"
            return (why, False) if why else None
        if event in ("socket.sendto", "socket.sendmsg") and address is None:
            return None  # a connected local pair (asyncio's own wake-up socket)
        return f"go on the internet ({_show_address(address)})", False


def _show(path: Any) -> str:
    try:
        return os.fsdecode(os.fspath(path))[-160:]
    except TypeError:
        return str(path)[-160:]


def _show_address(address: Any) -> str:
    if isinstance(address, tuple) and address:
        return "connect to " + ":".join(str(a) for a in address[:2])
    return "connect somewhere"


def _program(event: str, args: tuple) -> str:
    first = args[0] if args else ""
    if event == "subprocess.Popen" and len(args) > 1 and args[1]:
        first = args[1][0] if isinstance(args[1], (list, tuple)) and args[1] else args[1]
    text = os.fsdecode(first) if isinstance(first, (str, bytes)) else ""
    return (os.path.basename(text) or event)[:80]


# -- installing ---------------------------------------------------------------------------
def install(rules: Rules, report: Callable[[str], None]) -> None:
    """Hold this Python to ``rules`` from now on. ``report(what)`` hears each refused action."""
    busy = threading.local()

    def refuse(what: str) -> None:
        try:
            report(what)
        except Exception:  # noqa: BLE001 - reporting must never let the action through
            pass
        raise PermissionError(f"Not allowed in the plugin box: {what}.")

    def hook(event: str, args: tuple) -> None:
        if getattr(busy, "on", False):
            return
        busy.on = True
        try:
            verdict = rules.decide(event, args)
        finally:
            busy.on = False
        if verdict is None:
            return
        what, soft = verdict
        if soft:
            raise BoxImportRefused(f"Not allowed in the plugin box: {what}.")
        refuse(what)

    if not rules.shell:
        # starting programs through _posixsubprocess (multiprocessing does) raises no audit event:
        # a stand-in that refuses takes its place before any plugin code runs
        stub = types.ModuleType("_posixsubprocess")

        def fork_exec(*_a: Any, **_k: Any) -> Any:
            refuse("run another program (fork_exec)")

        stub.fork_exec = fork_exec  # type: ignore[attr-defined]
        sys.modules["_posixsubprocess"] = stub
    sys.addaudithook(hook)
