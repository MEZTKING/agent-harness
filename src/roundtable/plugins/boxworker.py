"""The plugin box's child process: one installed plugin, held to its permissions.

Started by ``sandbox.Box`` (never by hand): ``python -I -S -B boxworker.py`` from source, or the app's
own exe with ``--plugin-box`` when frozen. It speaks line-delimited JSON on its own copies of stdin
and stdout; the plugin's prints go to its ``errors.log`` (the process's stderr, opened by the parent).

Order of things, which matters:

1. take the protocol's pipes, point the plugin's stdin at nothing and its stdout at the log;
2. read the one ``init`` line (code folder, entry, data folder, permissions);
3. load what the box itself needs from the standard library (before any rule applies);
4. make ``roundtable.plugins.api`` the stand-alone copy (``boxapi``) and forget the rest of the
   harness, so ``import roundtable.core.secrets`` fails;
5. the import path becomes the standard library plus the plugin's ``code``, ``code/src`` and
   ``code/.deps``;
6. install the guard (``guard.install``): from here on every audit event is checked;
7. only then import the plugin and answer ``hello`` with the hooks it really has.

``--trial`` runs a plugin's own tests the same way (a Python command, no permissions) and exits
with their exit code.
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import types
from collections import OrderedDict
from typing import Any

MAX_CONTEXTS = 256  # conversations whose state a box keeps (oldest forgotten first)


def _parts() -> tuple[Any, Any]:
    if __package__:  # the frozen app: imported as roundtable.plugins.boxworker
        from . import boxapi, guard  # type: ignore[no-redef]
        return boxapi, guard
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    try:
        import boxapi  # type: ignore[no-redef]
        import guard  # type: ignore[no-redef]
    finally:
        sys.path.remove(here)
    return boxapi, guard


class Wire:
    """The protocol's two pipes: one JSON object a line."""

    def __init__(self, rin: Any, wout: Any):
        self.rin, self.wout = rin, wout
        self.lock = threading.Lock()

    def send(self, msg: dict[str, Any]) -> None:
        data = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
        with self.lock:
            self.wout.write(data)
            self.wout.flush()

    def read(self) -> dict[str, Any]:
        line = self.rin.readline()
        if not line:
            _leave(0)
        return json.loads(line)


def _leave(code: int) -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.flush()
        except Exception:  # noqa: BLE001
            pass
    os._exit(code)


def _take_stdio(trial: bool) -> Wire:
    """The protocol keeps copies of stdin/stdout; the plugin gets nothing to read and the log to write."""
    if sys.stderr is None:  # a windowed exe without a console: the parent gave us a file all the same
        try:
            sys.stderr = os.fdopen(2, "w", encoding="utf-8", errors="replace", buffering=1)
        except OSError:
            sys.stderr = open(os.devnull, "w")
    rin = os.fdopen(os.dup(0), "rb")
    null = os.open(os.devnull, os.O_RDWR)
    os.dup2(null, 0)
    sys.stdin = open(os.devnull, "r")
    if trial:
        return Wire(rin, None)
    wout = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return Wire(rin, wout)


def _forget_the_harness(boxapi: Any) -> None:
    """Only ``roundtable.plugins.api`` (the box's copy) is left to import."""
    for name in list(sys.modules):
        if name == "roundtable" or name.startswith("roundtable.") or name in ("guard", "boxapi"):
            del sys.modules[name]
    top = types.ModuleType("roundtable")
    top.__path__ = []  # type: ignore[attr-defined]
    sub = types.ModuleType("roundtable.plugins")
    sub.__path__ = []  # type: ignore[attr-defined]
    top.plugins = sub  # type: ignore[attr-defined]
    sub.api = boxapi  # type: ignore[attr-defined]
    boxapi.__name__ = "roundtable.plugins.api"
    sys.modules.update({"roundtable": top, "roundtable.plugins": sub, "roundtable.plugins.api": boxapi})


def _setup(init: dict[str, Any], start_path: list[str], trial: bool) -> tuple[Any, Any, list[str]]:
    """Steps 3 to 6; returns (boxapi, rules, refusals)."""
    data, code = init["data"], init["code"]
    os.makedirs(os.path.join(data, "tmp"), exist_ok=True)
    os.chdir(data)
    import contextlib  # noqa: F401 - loaded now, while files can still be read
    import importlib  # noqa: F401
    import linecache  # noqa: F401
    import logging
    import mimetypes
    import tempfile
    import traceback  # noqa: F401
    import zoneinfo

    mimetypes.init()  # reads the system's lists now: later it would be a file outside the box
    tempfile.tempdir = os.path.join(data, "tmp")
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s %(message)s")
    boxapi, guard = _parts()
    own = [os.path.abspath(f) for f in (__file__, guard.__file__, boxapi.__file__) if f]
    _forget_the_harness(boxapi)
    reads = [*start_path, code, *zoneinfo.TZPATH]
    if getattr(sys, "_MEIPASS", None):
        reads.append(sys._MEIPASS)  # type: ignore[attr-defined]
    rules = guard.Rules(data, reads, init.get("granted") or [], read_files=[sys.executable, *own])
    mine = [p for p in (code, os.path.join(code, "src"), os.path.join(code, ".deps")) if os.path.isdir(p)]
    sys.path[:] = ([code] if trial else []) + start_path + [p for p in mine if not (trial and p == code)]
    refusals: list[str] = []
    guard.install(rules, refusals.append)
    return boxapi, rules, refusals


def _drain(refusals: list[str]) -> list[str]:
    got = refusals[:]
    del refusals[:len(got)]
    return list(dict.fromkeys(got))


class Child:
    """The plugin and the conversations it has seen."""

    def __init__(self, wire: Wire, boxapi: Any, rules: Any, refusals: list[str], init: dict[str, Any]):
        self.wire, self.api, self.rules, self.refusals = wire, boxapi, rules, refusals
        self.pid = init.get("id") or "plugin"
        self.data = init["data"]
        self.entry = init["entry"]
        self.contexts: OrderedDict[str, list[Any]] = OrderedDict()
        self.tables: dict[str, dict[str, Any]] = {}
        self.obj: Any = None
        self.in_call = False
        self.qid = 0

    # -- asking the parent ------------------------------------------------------------------
    def ask(self, kind: str, args: dict[str, Any], wait: bool = True) -> Any:
        if not wait:
            self.wire.send({"ask": kind, "args": args})
            return None
        if threading.current_thread() is not threading.main_thread() or not self.in_call:
            raise self.api.PluginError(f"ctx.{'http' if kind == 'http' else 'cost_of'} only works while a hook "
                                       "is running, not from a thread of its own")
        self.qid += 1
        qid = self.qid
        self.wire.send({"ask": kind, "qid": qid, "args": args})
        while True:
            msg = self.wire.read()
            if msg.get("op") == "answer" and msg.get("qid") == qid:
                if msg.get("ok"):
                    return msg.get("result")
                raise self.api.PluginError(str(msg.get("error") or "the harness said no"))

    # -- loading ----------------------------------------------------------------------------
    def load(self, hooks: list[str]) -> list[str]:
        import importlib

        modname, objname = self.entry.rsplit(":", 1)
        obj: Any = importlib.import_module(modname.removesuffix(".py"))
        for part in objname.split("."):
            obj = getattr(obj, part)
        self.obj = obj() if isinstance(obj, type) else obj
        return [h for h in hooks if callable(getattr(self.obj, h, None))]

    # -- contexts ---------------------------------------------------------------------------
    def ctx(self, desc: dict[str, Any]) -> list[Any]:
        from pathlib import Path

        key = str(desc.get("key") or "")
        project = desc.get("project")
        if project:
            self.rules.allow_project(project)
        entry = self.contexts.get(key)
        if entry is None:
            ctx = self.api.PluginContext(self.pid, dict(desc.get("settings") or {}), Path(self.data),
                                         project_root=Path(project) if project else None, role=desc.get("role"),
                                         shared=dict(desc.get("shared") or {}), _ask=self.ask)
            entry = self.contexts[key] = [ctx, None]
            while len(self.contexts) > MAX_CONTEXTS:
                self.contexts.popitem(last=False)
        else:
            self.contexts.move_to_end(key)
            ctx = entry[0]
            ctx.settings = dict(desc.get("settings") or {})
            ctx.role = desc.get("role")
            ctx.project_root = Path(project) if project else None
        return entry

    def _tools(self, entry: list[Any]) -> dict[str, Any]:
        found = self.obj.tools(entry[0])
        if not isinstance(found, (list, tuple)) or not all(isinstance(t, self.api.Tool) for t in found):
            raise self.api.PluginError(f"tools must return a list of Tool, not {type(found).__name__}")
        entry[1] = {t.spec.name: t for t in found}
        return entry[1]

    def _table(self, hook: str) -> dict[str, Any]:
        table = getattr(self.obj, hook)()
        if not isinstance(table, dict):
            raise self.api.PluginError(f"{hook} must return a dict, not {type(table).__name__}")
        self.tables[hook] = table
        return table

    # -- one call ---------------------------------------------------------------------------
    def run(self, hook: str, payload: dict[str, Any]) -> Any:
        args = list(payload.get("args") or [])
        if hook in ("commands", "routes"):
            return sorted(str(k) for k in self._table(hook))
        entry = self.ctx(payload.get("ctx") or {})
        ctx = entry[0]
        if hook == "command":
            fn = (self.tables.get("commands") or self._table("commands")).get(payload.get("name"))
            if fn is None:
                raise self.api.PluginError(f"there's no command {payload.get('name')!r}")
            from contextlib import redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf):
                result = fn(ctx, [str(a) for a in payload.get("argv") or []])
            return {"result": result if isinstance(result, (int, str, float, bool, type(None))) else None,
                    "out": buf.getvalue()}
        if hook == "route":
            fn = (self.tables.get("routes") or self._table("routes")).get(payload.get("name"))
            if fn is None:
                raise self.api.PluginError(f"there's no route {payload.get('name')!r}")
            out = fn(ctx, dict(payload.get("query") or {}), payload.get("body"))
            return {"tuple": list(out)} if isinstance(out, tuple) else {"value": out}
        if hook == "tools":
            return [{"name": t.spec.name, "description": t.spec.description, "parameters": t.spec.parameters,
                     "terminal": bool(t.terminal)} for t in self._tools(entry).values()]
        if hook == "tool":
            name = payload.get("name")
            tools = entry[1] if entry[1] is not None and name in entry[1] else self._tools(entry)
            if name not in tools:
                raise self.api.ToolError(f"{name} is no longer one of this plugin's tools")
            out = tools[name].fn(dict(payload.get("toolargs") or {}))
            return out if isinstance(out, str) else str(out)
        if hook == "after_model_call":
            role, model, resp, usage = (args + [None] * 4)[:4]
            resp = resp or {}
            calls = [self.api.ToolCall(str(c.get("id", "")), str(c.get("name", "")), dict(c.get("arguments") or {}))
                     for c in resp.get("tool_calls") or [] if isinstance(c, dict)]
            response = self.api.Response(str(resp.get("text") or ""), calls, str(resp.get("stop") or "end"),
                                         str(resp.get("model") or model or ""))
            known = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "cost_usd")
            used = self.api.Usage(**{k: v for k, v in (usage or {}).items() if k in known})
            return self.obj.after_model_call(ctx, role, model, response, used)
        return getattr(self.obj, hook)(ctx, *args)

    def serve(self) -> None:
        import traceback

        while True:
            msg = self.wire.read()
            op, mid = msg.get("op"), msg.get("id")
            if op == "stop":
                self.wire.send({"id": mid, "ok": True, "result": None, "refused": _drain(self.refusals)})
                _leave(0)
            if op != "call":
                continue
            self.in_call = True
            try:
                result = self.run(str(msg.get("hook")), msg.get("payload") or {})
                reply = {"id": mid, "ok": True, "result": result}
                json.dumps(reply)
            except KeyboardInterrupt:
                raise
            except BaseException as e:  # noqa: BLE001 - every error (sys.exit too) goes back to the parent
                if isinstance(e, TypeError) and "JSON serializable" in str(e):
                    reply = {"id": mid, "ok": False, "kind": "PluginError",
                             "error": "it returned something that can't leave its box (not plain data)"}
                else:
                    traceback.print_exc()
                    reply = {"id": mid, "ok": False, "kind": type(e).__name__, "error": str(e)}
            finally:
                self.in_call = False
            reply["refused"] = _drain(self.refusals)
            self.wire.send(reply)


def _serve(wire: Wire, start_path: list[str]) -> int:
    init = wire.read()
    try:
        boxapi, rules, refusals = _setup(init, start_path, trial=False)
    except BaseException as e:  # noqa: BLE001
        wire.send({"op": "hello", "ok": False, "error": f"its box couldn't be set up ({type(e).__name__}: {e})"})
        return 1
    child = Child(wire, boxapi, rules, refusals, init)
    try:
        hooks = child.load(list(init.get("hooks") or []))
        wire.send({"op": "hello", "ok": True, "hooks": hooks, "refused": _drain(refusals)})
    except BaseException as e:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        wire.send({"op": "hello", "ok": False, "error": f"{type(e).__name__}: {e}", "refused": _drain(refusals)})
        return 1
    child.serve()
    return 0


def _trial(wire: Wire, start_path: list[str]) -> int:
    import runpy
    import traceback

    init = wire.read()
    argv = [str(a) for a in init.get("argv") or []]
    _boxapi, _rules, refusals = _setup(init, start_path, trial=True)
    code = 0
    try:
        if argv[:1] == ["-m"]:
            sys.argv = [argv[1], *argv[2:]]
            runpy.run_module(argv[1], run_name="__main__", alter_sys=True)
        elif argv[:1] == ["-c"]:
            sys.argv = ["-c", *argv[2:]]
            exec(compile(argv[1], "<trial>", "exec"), {"__name__": "__main__"})  # noqa: S102
        else:
            sys.argv = list(argv)
            runpy.run_path(argv[0], run_name="__main__")
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except BaseException:  # noqa: BLE001
        traceback.print_exc()
        code = 1
    stopped = _drain(refusals)
    if stopped:
        print("\nThe box stopped it from: " + "; ".join(stopped), file=sys.stderr)
        code = code or 3
    _leave(code)
    return code


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    start_path = [p for p in sys.path if p]
    trial = "--trial" in argv
    wire = _take_stdio(trial)
    return _trial(wire, start_path) if trial else _serve(wire, start_path)


if __name__ == "__main__":
    raise SystemExit(main())
