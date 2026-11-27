"""Plugins in their own box: a separate process with no keys, no internet, no other programs and
only its own folder, unless the owner granted more.

Who is boxed: every installed plugin (linked folders too), unless the owner marked it Trusted.
Built-in plugins run in the app, as before.

The box, in four layers:

1. **Its own process** (``boxworker.py``), started on first use and kept for the run: a clean
   environment (``safeenv.clean_env`` with the proxy settings taken out too), its data folder as
   the working folder, and an import path of the standard library and the plugin's own folders
   only. ``import roundtable.core.secrets`` (the key vault) fails inside it.
2. **The guard** (``guard.py``), a Python audit hook installed before the plugin is imported:
   sockets, programs, ``ctypes`` and files outside its places are refused; a refusal switches the
   plugin off for the run even if the plugin caught it.
3. **The operating system**, where it can without admin rights: on Linux ``bwrap`` (its own view
   of the files, and no network) or ``unshare -rn`` (no network); on Windows a Job Object (one
   process only, a memory cap, gone when the app goes). The phone: layer 2 only.
4. **No compiled files** (``.pyd``, ``.so``, ``.dll``, ``.dylib``, ``.exe``, ``.deps`` included)
   unless the plugin may run programs: compiled code is not seen by layer 2.

Permissions open their own door: ``network`` sockets, ``files`` any folder, ``shell`` programs and
compiled files, ``project:read`` the project it is helping with (never ``.env``-like files, ``.git``
or ``.harness``), ``secrets:<host>`` web requests to that host through ``ctx.http``, which the
parent sends with the saved key added: the key never enters the box.

Limits: 10 s a hook, 60 s a tool (a manifest's ``tool_timeout`` may ask for up to 300), 8 MB a
message. Over a limit the child is stopped and the owner told plainly; it is started again once
after a crash, then left off until the next run.
"""

from __future__ import annotations

import atexit
import itertools
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .api import PluginError
from .guard import compiled_files  # noqa: F401  (re-exported for host and manage)

HOOK_SECONDS = 10.0
TOOL_SECONDS = 60.0
TOOL_MOST = 300.0
START_SECONDS = 30.0
MESSAGE_BYTES = 8 * 1024 * 1024
TRIAL_OUTPUT = 20_000
ASK_EXTRA_SECONDS = 120.0  # at most this much harness-side waiting (web requests) is added to a limit
MOST_ASKS = 2000  # messages a plugin may send the harness during one call
MEMORY_MB = 1024  # Windows: the Job Object's cap for one box

WORDS = "Runs in its own box: no internet, no other programs, only its own folder"
SOFT = " (the box stops a plugin that tries; it is not proof against one written to break out)"
UNSHARE = (" (Linux itself cuts the internet; for files and programs the box stops a plugin that tries, "
           "but is not proof against one written to break out)")
TRUSTED_WORDS = "Trusted: runs as the app itself, outside a box"
BUILTIN_WORDS = "Comes with the harness: runs as the app itself"


class SandboxError(PluginError):
    """A boxed plugin couldn't start, broke a rule or didn't answer (the message is for the owner)."""


class SandboxRefused(SandboxError):
    """The plugin tried something its box doesn't allow."""


class PluginRaised(PluginError):
    """The plugin's own code raised inside its box; ``kind`` is the error's type name there."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


# -- what this computer can do -----------------------------------------------------------------
_PROBED: dict[str, Any] = {}


def _python() -> str:
    exe = sys.executable
    if os.name == "nt":  # a venv's python.exe starts a second process: use the real one (one process only)
        base = getattr(sys, "_base_executable", "") or ""
        if base and os.path.isfile(base):
            exe = base
    return os.path.realpath(exe)


def worker_command(trial: bool = False) -> list[str]:
    """How the child is started: the app's own exe when frozen, else this Python by file path."""
    extra = ["--trial"] if trial else []
    if getattr(sys, "frozen", False):
        return [sys.executable, "--plugin-box", *extra]
    return [_python(), "-I", "-S", "-B", str(Path(__file__).with_name("boxworker.py")), *extra]


def _run_quiet(cmd: list[str], timeout: float = 10) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _bwrap_binds(granted: list[str], data_dir: Path, code: Path | None, projects: list[str]) -> list[str]:
    if "files" in granted:
        args = ["--bind", "/", "/"]
    else:
        args = []
        system = ["/usr", "/lib", "/lib64", "/lib32", "/bin", "/sbin", "/etc/ld.so.cache", "/etc/ld.so.conf",
                  "/etc/ld.so.conf.d", "/etc/localtime", "/etc/os-release", "/etc/alternatives"]
        if "network" in granted:
            system += ["/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf", "/etc/ssl", "/etc/ca-certificates",
                       "/etc/pki"]
        python = [sys.base_prefix, os.path.dirname(_python()), str(Path(__file__).parent),
                  *[p for p in sys.path if p and p.startswith(sys.base_prefix)]]
        for p in dict.fromkeys([*system, *python]):
            args += ["--ro-bind-try", p, p]
        # bwrap mounts in order: the empty /tmp goes first, or it hides any code, project or data folder
        # that lives under /tmp (a later mount covers an earlier one).
        args += ["--tmpfs", "/tmp"]
        if code is not None:
            args += ["--ro-bind", str(code), str(code)]
        for p in projects:
            args += ["--ro-bind-try", p, p]
    args += ["--proc", "/proc", "--dev", "/dev"]
    if "files" not in granted:
        args += ["--bind", str(data_dir), str(data_dir)]
    return args


def os_prefix(granted: list[str], data_dir: Path, code: Path | None = None, projects: list[str] = (),
              layer: str | None = None) -> list[str]:
    """What goes in front of the child's command on Linux: bwrap, unshare or nothing."""
    layer = os_layer() if layer is None else layer
    if layer == "bwrap":
        net = [] if "network" in granted else ["--unshare-net"]
        return ["bwrap", "--die-with-parent", "--new-session", "--unshare-user-try", "--unshare-ipc",
                "--unshare-pid", "--unshare-uts", "--unshare-cgroup-try", *net,
                *_bwrap_binds(list(granted), data_dir, code, list(projects)), "--chdir", str(data_dir), "--"]
    if layer == "unshare" and "network" not in granted:
        return ["unshare", "-r", "-n", "--"]
    return []


def os_layer() -> str:
    """Which operating-system layer this computer gives the box: bwrap, unshare, job or ""."""
    if "layer" in _PROBED:
        return _PROBED["layer"]
    layer = ""
    if os.environ.get("ROUNDTABLE_BOX_OS") == "off":
        layer = ""
    elif os.name == "nt":
        layer = "job" if _windows_job_works() else ""
    elif sys.platform.startswith("linux") and not os.environ.get("ROUNDTABLE_ON_PHONE"):
        with tempfile.TemporaryDirectory() as t:
            check = [_python(), "-I", "-S", "-c", "import json"]
            if shutil.which("bwrap") and _run_quiet([*os_prefix([], Path(t), layer="bwrap"), *check]):
                layer = "bwrap"
            elif shutil.which("unshare") and _run_quiet(["unshare", "-r", "-n", "--", *check]):
                layer = "unshare"
    _PROBED["layer"] = layer
    return layer


def supported() -> dict[str, Any]:
    """What the box can enforce on this computer, and the sentence the owner reads before adding a plugin."""
    layer = os_layer()
    words = WORDS + ("" if layer == "bwrap" else UNSHARE if layer == "unshare" else SOFT)
    return {"guard": True, "os_net": layer in ("bwrap", "unshare"), "os_proc": layer == "job",
            "os_files": layer == "bwrap", "layer": layer, "words": words}


# -- Windows: a Job Object ---------------------------------------------------------------------
def _windows_job_works() -> bool:
    try:
        job = _windows_job(None, one_process=True)
    except Exception:  # noqa: BLE001
        return False
    if job:
        _close_handle(job)
    return bool(job)


def _windows_job(proc: Any, one_process: bool) -> Any:
    """A Job Object (kill on close, a memory cap, one process unless it may run programs) holding ``proc``."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class Counters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount",
                                                    "OtherOperationCount", "ReadTransferCount",
                                                    "WriteTransferCount", "OtherTransferCount")]

    class Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Counters), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    job = k32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = Extended()
    flags = 0x2000 | 0x100 | 0x400  # kill on job close, process memory, die on unhandled exception
    if one_process:
        flags |= 0x8  # active process limit
        info.BasicLimitInformation.ActiveProcessLimit = 1
    info.BasicLimitInformation.LimitFlags = flags
    info.ProcessMemoryLimit = MEMORY_MB * 1024 * 1024
    ok = k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))  # 9: extended limits
    if ok and proc is not None:
        ok = k32.AssignProcessToJobObject(job, wintypes.HANDLE(int(proc._handle)))
    if not ok:
        _close_handle(job)
        return None
    return job


def _close_handle(handle: Any) -> None:
    if os.name == "nt" and handle:
        import ctypes

        ctypes.WinDLL("kernel32").CloseHandle(handle)


# -- the child's environment ------------------------------------------------------------------
def child_env(data_dir: Path, granted: list[str]) -> dict[str, str]:
    """``safeenv.clean_env`` without proxy or Python settings; temp files in the data folder."""
    from ..harness.safeenv import NO_GIT_LOGIN, clean_env

    env = clean_env()
    for k in list(env):
        up = k.upper()
        if up.endswith("_PROXY") or up.startswith("PYTHON") or (up in NO_GIT_LOGIN and "shell" not in granted):
            env.pop(k)
    if "shell" not in granted:
        env = {k: v for k, v in env.items() if not k.upper().startswith("GIT_CONFIG_")}
    tmp = str(data_dir / "tmp")
    env.update({"TMPDIR": tmp, "TEMP": tmp, "TMP": tmp, "PYTHONDONTWRITEBYTECODE": "1", "ROUNDTABLE_BOX": "1",
                "PYTHONIOENCODING": "utf-8"})
    if os.name != "nt":
        env["HOME"] = str(data_dir)
    return env


# -- one box ------------------------------------------------------------------------------------
_BOXES: "weakref.WeakSet[Box]" = weakref.WeakSet()
_EOF = object()
_BIG = object()


def _kill(holder: dict[str, Any]) -> None:
    proc = holder.get("proc")
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
    if holder.get("job"):
        _close_handle(holder.pop("job"))
    for s in ("stdin", "stdout"):
        try:
            getattr(proc, s).close() if proc is not None and getattr(proc, s) else None
        except Exception:  # noqa: BLE001
            pass
    holder["proc"] = None


@atexit.register
def stop_all() -> None:
    for box in list(_BOXES):
        box.stop()


class Box:
    """A running box. ``call(hook, payload, timeout)`` returns the hook's answer; ``stop()`` ends it."""

    def __init__(self, code: Path, manifest: Any, granted: list[str], data_dir: Path):
        self.code, self.manifest = Path(code), manifest
        self.granted = [str(g) for g in granted]
        self.data_dir = Path(data_dir)
        self.hooks: list[str] = []
        self.projects: list[str] = []
        self.restarts_left = 1
        self.crashed = ""  # why it stopped by itself ("" = it didn't)
        self.layer = os_layer()
        self._h: dict[str, Any] = {"proc": None}
        self._lock = threading.RLock()
        self._q: queue.Queue = queue.Queue()
        self._ids = itertools.count(1)
        self._finalizer = weakref.finalize(self, _kill, self._h)
        _BOXES.add(self)

    @property
    def alive(self) -> bool:
        proc = self._h.get("proc")
        return proc is not None and proc.poll() is None

    @property
    def pid(self) -> int | None:
        proc = self._h.get("proc")
        return proc.pid if proc is not None else None

    # -- starting and stopping ------------------------------------------------------------
    def open(self) -> "Box":
        with self._lock:
            self._open()
        return self

    def _open(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "tmp").mkdir(exist_ok=True)
        log = open(self.data_dir / "errors.log", "ab")
        cmd = [*(os_prefix(self.granted, self.data_dir, self.code, self.projects, self.layer)
                 if self.layer in ("bwrap", "unshare") else []), *worker_command()]
        kw: dict[str, Any] = {}
        if os.name == "nt":
            kw["creationflags"] = 0x08000000  # no console window
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                    cwd=str(self.data_dir), env=child_env(self.data_dir, self.granted), **kw)
        except OSError as e:
            raise SandboxError(f"its box couldn't start ({e})")
        finally:
            log.close()
        self._h["proc"] = proc
        if self.layer == "job":
            self._h["job"] = _windows_job(proc, one_process="shell" not in self.granted)
        self._q = queue.Queue()
        threading.Thread(target=self._reader, args=(proc.stdout, self._q), daemon=True,
                         name=f"box-{self.manifest.id}").start()
        self.crashed = ""
        init = {"op": "init", "id": self.manifest.id, "code": str(self.code), "entry": self.manifest.entry,
                "data": str(self.data_dir), "granted": self.granted, "hooks": list(self.manifest.hooks)}
        self._write(init)
        hello = self._wait(START_SECONDS, None, starting=True)
        if hello.get("refused"):
            self._kill(f"it tried to {hello['refused'][0]} while starting")
            raise SandboxRefused(f"it tried to {'; '.join(hello['refused'])} while starting, which its box "
                                 "doesn't allow")
        if not hello.get("ok"):
            self._kill("it couldn't start")
            raise SandboxError(str(hello.get("error") or "it couldn't start in its box"))
        self.hooks = list(hello.get("hooks") or [])

    @staticmethod
    def _reader(stream: Any, q: queue.Queue) -> None:
        try:
            while True:
                line = stream.readline(MESSAGE_BYTES + 1)
                if not line:
                    break
                if len(line) > MESSAGE_BYTES and not line.endswith(b"\n"):
                    q.put(_BIG)
                    return
                q.put(line)
        except (OSError, ValueError):
            pass
        q.put(_EOF)

    def _write(self, msg: dict[str, Any]) -> None:
        data = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
        if len(data) > MESSAGE_BYTES:
            raise SandboxError("what it was to be given is bigger than its box takes (8 MB)")
        proc = self._h.get("proc")
        try:
            proc.stdin.write(data)
            proc.stdin.flush()
        except (OSError, ValueError, AttributeError):
            self._kill("it stopped unexpectedly")
            raise SandboxError("its box stopped unexpectedly")

    def _kill(self, why: str) -> None:
        self.crashed = why or "it stopped"
        _kill(self._h)

    def stop(self) -> None:
        """End the box on purpose (a new run, the app closing): it starts afresh next time."""
        with self._lock:
            proc = self._h.get("proc")
            if proc is not None and proc.poll() is None:
                try:
                    self._write({"op": "stop", "id": 0})
                    proc.wait(timeout=0.5)
                except Exception:  # noqa: BLE001
                    pass
            _kill(self._h)
            self.crashed = ""
            self.restarts_left = 1

    def _ready(self, project: str | None) -> None:
        if (project and "project:read" in self.granted and self.layer == "bwrap"
                and project not in self.projects):
            self.projects.append(project)  # its own view of the files must show the project: start again
            if self.alive:
                self.stop()
        if self.alive:
            return
        if self.crashed:
            if self.restarts_left <= 0:
                raise SandboxError(f"its box stopped twice ({self.crashed}), so it's off until the next run")
            self.restarts_left -= 1
        self._open()

    # -- calling ------------------------------------------------------------------------
    def call(self, hook: str, payload: Any, timeout: float, on_ask: Callable[[str, Any], Any] | None = None) -> Any:
        with self._lock:
            ctx = payload.get("ctx") if isinstance(payload, dict) else None
            self._ready((ctx or {}).get("project") if isinstance(ctx, dict) else None)
            mid = next(self._ids)
            self._write({"op": "call", "id": mid, "hook": hook, "payload": payload})
            reply = self._wait(timeout, mid, on_ask=on_ask)
            if reply.get("refused"):
                tried = "; ".join(reply["refused"])
                self._kill(f"it tried to {tried}")
                raise SandboxRefused(f"it tried to {tried}, which its box doesn't allow")
            if reply.get("ok"):
                return reply.get("result")
            raise PluginRaised(str(reply.get("kind") or "Error"), str(reply.get("error") or ""))

    def _wait(self, timeout: float, mid: int | None, on_ask: Callable[[str, Any], Any] | None = None,
              starting: bool = False) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        extra, asks = 0.0, 0
        while True:
            left = deadline - time.monotonic()
            try:
                line = self._q.get(timeout=max(0.0, left)) if left > 0 else self._q.get_nowait()
            except queue.Empty:
                self._kill(f"it took longer than {timeout:g} seconds")
                raise SandboxError(f"it took longer than {timeout:g} seconds, so its box was stopped")
            if line is _EOF:
                self._kill("it stopped unexpectedly")
                raise SandboxError("its box stopped unexpectedly" + _log_tail(self.data_dir))
            if line is _BIG:
                self._kill("it sent more than 8 MB at once")
                raise SandboxError("it sent more than its box allows (8 MB at once), so its box was stopped")
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "ask" in msg:
                asks += 1
                if asks > MOST_ASKS:
                    self._kill("it sent the harness too many messages at once")
                    raise SandboxError(f"it sent more than {MOST_ASKS} messages during one call, so its box was "
                                       "stopped")
                began = time.monotonic()
                self._answer(msg, on_ask)
                if msg.get("qid") is not None and extra < ASK_EXTRA_SECONDS:  # it waited on the harness
                    spent = min(time.monotonic() - began, ASK_EXTRA_SECONDS - extra)
                    extra += spent
                    deadline += spent
                continue
            if starting and msg.get("op") == "hello":
                return msg
            if mid is not None and msg.get("id") == mid:
                return msg

    def _answer(self, msg: dict[str, Any], on_ask: Callable[[str, Any], Any] | None) -> None:
        kind, qid = str(msg.get("ask")), msg.get("qid")
        try:
            if on_ask is None:
                raise PluginError("the harness can't do that for it here")
            result, ok, error = on_ask(kind, msg.get("args") or {}), True, ""
        except Exception as e:  # noqa: BLE001
            result, ok, error = None, False, str(e)
        if qid is not None:
            self._write({"op": "answer", "qid": qid, "ok": ok, "result": result, "error": error})


def _log_tail(data_dir: Path) -> str:
    try:
        tail = (data_dir / "errors.log").read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:]
    except OSError:
        return ""
    return (": " + " / ".join(t.strip() for t in tail))[:400] if tail else ""


def start(code: Path, manifest: Any, granted: list[str], data_dir: Path) -> Box:
    """Start a plugin in a box (raises ``SandboxError`` with plain words when it can't)."""
    if manifest is None or not getattr(manifest, "entry", ""):
        raise SandboxError("there's no plugin to start: its manifest is missing")
    if not Path(code).is_dir():
        raise SandboxError(f"its folder is missing ({code}); add the plugin again")
    return Box(code, manifest, granted, data_dir).open()


# -- the plugin as the host sees it ----------------------------------------------------------------
def _plain(value: Any) -> Any:
    """``value`` as plain JSON data, or raise TypeError."""
    return json.loads(json.dumps(value, ensure_ascii=False))


def _loose(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


@dataclass
class BoxedPlugin:
    """An installed plugin in its box, with the hooks of a normal plugin object (``host`` calls them)."""

    box: Box
    manifest: Any
    tool_timeout: float = TOOL_SECONDS
    fault: Callable[[str, BaseException, Any], None] | None = None  # the host's ``fail`` for this plugin
    is_off: Callable[[], bool] = lambda: False

    boxed = True

    # -- helpers -----------------------------------------------------------------------------
    def _desc(self, ctx: Any) -> dict[str, Any]:
        key = getattr(ctx, "_box_key", None)
        if key is None:
            key = uuid.uuid4().hex
            try:
                object.__setattr__(ctx, "_box_key", key)
            except (AttributeError, TypeError):
                pass
        shared = {}
        for k, v in (getattr(ctx, "shared", None) or {}).items():
            try:
                shared[str(k)] = _plain(v)
            except (TypeError, ValueError):
                pass
        project = getattr(ctx, "project_root", None)
        return {"key": key, "settings": _loose(dict(getattr(ctx, "settings", {}) or {})),
                "project": str(Path(project).resolve()) if project else None, "role": getattr(ctx, "role", None),
                "shared": shared}

    @staticmethod
    def _asker(ctx: Any) -> Callable[[str, Any], Any]:
        def on_ask(kind: str, args: dict[str, Any]) -> Any:
            if ctx is None:
                raise PluginError("not available here")
            if kind == "emit":
                ctx.emit(str(args.get("kind") or "note"), dict(args.get("data") or {}))
                return None
            if kind == "cost":
                from ..providers.base import Usage

                u = args.get("usage") or {}
                known = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "cost_usd")
                return ctx.cost_of(str(args.get("model") or ""), Usage(**{k: u[k] for k in known if k in u}))
            if kind == "http":
                return ctx.http(str(args.get("method") or "GET"), str(args.get("url") or ""),
                                headers=args.get("headers") or {}, body=args.get("body"),
                                timeout=float(args.get("timeout") or 30))
            raise PluginError(f"the harness doesn't know {kind!r}")

        return on_ask

    def _call(self, hook: str, ctx: Any, args: list[Any], timeout: float | None = None) -> Any:
        payload: dict[str, Any] = {"args": args}
        if ctx is not None:
            payload["ctx"] = self._desc(ctx)
        return self.box.call(hook, payload, HOOK_SECONDS if timeout is None else timeout, on_ask=self._asker(ctx))

    # -- the hooks ------------------------------------------------------------------------------
    def on_tool_result(self, ctx: Any, tool: str, args: dict[str, Any], text: str, is_error: bool) -> str:
        try:
            sent = [str(tool), _plain(args), text, bool(is_error)]
        except (TypeError, ValueError):
            return text
        return self._call("on_tool_result", ctx, sent)

    def before_model_call(self, ctx: Any, role: str | None, model: str, system: str, messages: list[dict[str, Any]]):
        try:
            sent = [role, model, system, _plain(list(messages))]
        except (TypeError, ValueError):
            return system, messages  # something in the conversation isn't plain data: it stays as it is
        out = self._call("before_model_call", ctx, sent)
        return tuple(out) if isinstance(out, list) else out

    def after_model_call(self, ctx: Any, role: str | None, model: str, response: Any, usage: Any) -> None:
        resp = {"text": str(getattr(response, "text", "") or ""), "stop": str(getattr(response, "stop_reason", "")),
                "model": str(getattr(response, "model", "") or model),
                "tool_calls": _loose([c.to_dict() if hasattr(c, "to_dict") else c
                                      for c in getattr(response, "tool_calls", None) or []])}
        used = {k: getattr(usage, k, 0) for k in ("input_tokens", "output_tokens", "cache_read_tokens",
                                                   "cache_write_tokens", "cost_usd")} if usage is not None else {}
        self._call("after_model_call", ctx, [role, model, resp, _loose(used)])

    def on_event(self, ctx: Any, kind: str, data: dict[str, Any]) -> None:
        self._call("on_event", ctx, [kind, _loose(data)])

    def compact(self, ctx: Any, messages: list[dict[str, Any]], info: dict[str, Any]):
        try:
            sent = [_plain(list(messages)), _loose({k: v for k, v in info.items() if k not in ("cfg", "charge")})]
        except (TypeError, ValueError):
            return None
        return self._call("compact", ctx, sent)

    def tools(self, ctx: Any) -> list[Any]:
        from ..harness.tools import Tool
        from ..providers.base import ToolSpec

        specs = self._call("tools", ctx, [])
        if not isinstance(specs, list):
            raise PluginError("its box sent back something that isn't a list of tools")
        return [Tool(ToolSpec(str(s["name"]), str(s.get("description") or ""), dict(s.get("parameters") or {})),
                     self._tool_fn(ctx, str(s["name"])), terminal=bool(s.get("terminal")))
                for s in specs if isinstance(s, dict) and s.get("name")]

    def _tool_fn(self, ctx: Any, name: str) -> Callable[[dict[str, Any]], str]:
        from ..harness.tools import ToolError

        def run(args: dict[str, Any]) -> str:
            if self.is_off():
                raise ToolError(f"{name} belongs to {self.manifest.name}, which is switched off until this run ends")
            payload = {"ctx": self._desc(ctx), "name": name, "toolargs": args}
            try:
                return self.box.call("tool", payload, self.tool_timeout, on_ask=self._asker(ctx))
            except PluginRaised as e:
                raise ToolError(str(e) if e.kind == "ToolError" else f"{e.kind}: {e}")
            except SandboxError as e:
                if self.fault:
                    self.fault(f"tool {name}", e, getattr(ctx, "_emit", None))
                raise ToolError(f"{self.manifest.name} was stopped: {e}")

        return run

    def commands(self) -> dict[str, Callable[..., Any]]:
        names = self._call("commands", None, [])

        def make(n: str) -> Callable[..., Any]:
            def command(ctx: Any, argv: list[str]) -> Any:
                payload = {"ctx": self._desc(ctx), "name": n, "argv": list(argv)}
                out = self.box.call("command", payload, max(self.tool_timeout, TOOL_SECONDS),
                                    on_ask=self._asker(ctx))
                if out.get("out"):
                    sys.stdout.write(out["out"])
                return out.get("result")

            return command

        return {str(n): make(str(n)) for n in names or []}

    def routes(self) -> dict[str, Callable[..., Any]]:
        names = self._call("routes", None, [])

        def make(n: str) -> Callable[..., Any]:
            def route(ctx: Any, query: dict[str, Any], body: Any) -> Any:
                payload = {"ctx": self._desc(ctx), "name": n, "query": _loose(query), "body": _loose(body)}
                out = self.box.call("route", payload, HOOK_SECONDS, on_ask=self._asker(ctx))
                return tuple(out["tuple"]) if "tuple" in out else out.get("value")

            return route

        return {str(n): make(str(n)) for n in names or []}

    def stop(self) -> None:
        self.box.stop()


def boxed_plugin(code: Path, manifest: Any, granted: list[str], data_dir: Path) -> BoxedPlugin:
    """Start ``manifest``'s plugin in its box; ``missing`` hooks raise ``PluginError`` (plain words)."""
    box = start(code, manifest, granted, data_dir)
    missing = [h for h in manifest.hooks if h not in box.hooks]
    if missing:
        box.stop()
        raise PluginError(f"it says it uses {', '.join(missing)} but has no such method")
    limit = float(getattr(manifest, "tool_timeout", TOOL_SECONDS) or TOOL_SECONDS)
    return BoxedPlugin(box, manifest, tool_timeout=min(max(limit, 1.0), TOOL_MOST))


# -- secrets:<host>: web requests the parent sends with the key ----------------------------------
def key_for_host(cfg: Any, host: str) -> tuple[str, str] | None:
    """(header, value) for a saved key the config uses for ``host``; None if there's none."""
    from urllib.parse import urlparse

    from ..core import secrets as vault

    defaults = {"anthropic": "https://api.anthropic.com", "deepseek": "https://api.deepseek.com",
                "openai": "https://api.openai.com", "openrouter": "https://openrouter.ai"}
    for name, spec in (getattr(cfg, "providers", None) or {}).items():
        spec = spec or {}
        url = spec.get("base_url") or defaults.get(str(spec.get("type") or name)) or defaults.get(str(name)) or ""
        if (urlparse(url).hostname or "").lower() != host:
            continue
        env = spec.get("api_key_env") or ("ANTHROPIC_API_KEY" if spec.get("type") == "anthropic" else None)
        key = vault.get(env) or (os.environ.get(env) if env else None)
        if key:
            if spec.get("type") == "anthropic":
                return "x-api-key", key
            return "Authorization", f"Bearer {key}"
    return None


def secret_request(cfg: Any, granted: list[str], method: str, url: str, headers: dict[str, str] | None = None,
                   body: Any = None, timeout: float = 30, opener: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Send one request for a plugin with ``secrets:<host>``: that host only, https only, no redirects;
    the key is added here and taken out of anything that comes back."""
    import urllib.error
    import urllib.request
    from urllib.parse import urlparse

    u = urlparse(url)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not host:
        raise PluginError("only https:// web addresses can be sent with a saved key")
    if f"secrets:{host}" not in granted:
        raise PluginError(f"it may only use saved keys for: {', '.join(g[8:] for g in granted if g.startswith('secrets:')) or 'no host'}"
                          f" (not {host})")
    found = key_for_host(cfg, host)
    if not found:
        raise PluginError(f"there's no saved key for {host}. Add it in Settings > Keys, then try again.")
    header, value = found
    secret = value.split(" ", 1)[-1]
    clean = {str(k): str(v) for k, v in (headers or {}).items()
             if str(k).lower() not in ("authorization", "x-api-key", "api-key", "cookie", "proxy-authorization")}
    clean[header] = value
    if body is None:
        data = None
    else:
        data = body.encode("utf-8") if isinstance(body, str) else json.dumps(body).encode("utf-8")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a: Any, **k: Any) -> None:
            raise urllib.error.HTTPError(url, 400, "redirects aren't followed for requests with a saved key", None,
                                         None)

    req = urllib.request.Request(url, data=data, headers=clean, method=method.upper())
    open_ = opener or urllib.request.build_opener(NoRedirect).open
    try:
        with open_(req, timeout=min(float(timeout or 30), 60)) as resp:
            status, got, raw = resp.status, dict(resp.headers.items()), resp.read(MESSAGE_BYTES // 2)
    except urllib.error.HTTPError as e:
        status, got, raw = e.code, dict((e.headers or {}).items()), (e.read() if e.fp else b"")[:MESSAGE_BYTES // 2]
    except (urllib.error.URLError, OSError) as e:
        raise PluginError(f"couldn't reach {host} ({e})")

    def scrub(s: str) -> str:
        return s.replace(secret, "[your key]") if secret else s

    return {"status": int(status), "headers": {k: scrub(str(v)) for k, v in got.items()},
            "body": scrub(raw.decode("utf-8", errors="replace"))}


# -- trial: a plugin's own tests in the box -------------------------------------------------------------
_PYTHONS = {"python", "python3", "py", "python.exe", "python3.exe", "py.exe"}


def trial(code: Path, command: list[str], timeout: float = 60) -> dict[str, Any]:
    """Run a plugin's own tests inside the box, on a throwaway copy, with no permissions: {"ok", "output"}.

    ``command`` is a Python command (``["python", "-m", "unittest"]``, ``["python", "tests/run.py"]``,
    ``["python", "-c", "..."]``); anything else is refused.
    """
    argv = [str(c) for c in command]
    if argv and (os.path.basename(argv[0]).lower() in _PYTHONS or argv[0] == sys.executable):
        argv = argv[1:]
    if not argv or not (argv[0] in ("-m", "-c") and len(argv) > 1 or argv[0].endswith(".py")):
        return {"ok": False, "output": "Only a Python command (python -m ..., python file.py or python -c ...) "
                                       "can run in the box."}
    from .manifest import SKIP

    with tempfile.TemporaryDirectory(prefix="plugin-trial-") as t:
        work = Path(t) / "work"
        shutil.copytree(Path(code), work, ignore=shutil.ignore_patterns(*(SKIP - {".deps"})))
        (work / "tmp").mkdir(exist_ok=True)
        cmd = [*os_prefix([], work, work), *worker_command(trial=True)] if os_layer() in ("bwrap", "unshare") \
            else worker_command(trial=True)
        init = json.dumps({"op": "init", "id": "trial", "code": str(work), "entry": "", "data": str(work),
                           "granted": [], "argv": argv}) + "\n"
        kw: dict[str, Any] = {"creationflags": 0x08000000} if os.name == "nt" else {}
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    cwd=str(work), env=child_env(work, []), **kw)
        except OSError as e:
            return {"ok": False, "output": f"The box couldn't start ({e})."}
        holder = {"proc": proc, "job": _windows_job(proc, one_process=True) if os_layer() == "job" else None}
        try:
            out, _ = proc.communicate(init.encode("utf-8"), timeout=timeout)
            text = out.decode("utf-8", errors="replace")
            ok = proc.returncode == 0
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                out, _ = proc.communicate(timeout=10)
            except (subprocess.TimeoutExpired, ValueError, OSError):
                out = b""
            text = (out or b"").decode("utf-8", errors="replace") + f"\nStopped after {timeout:g} seconds."
            ok = False
        finally:
            _kill(holder)
    return {"ok": ok, "output": text[-TRIAL_OUTPUT:]}
