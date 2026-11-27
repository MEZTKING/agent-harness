"""What each job may do on a project: four presets, one per job.

* **Ask every time** (``ask_all``): every command, and every change to a file outside the task's planned files,
  waits for the owner's tap;
* **Careful** (``careful``, the default; it was "risky"): risky commands wait (``gate.classify``);
* **Free** (``free``; it was "off"): nothing waits; choosing it asks "Are you sure?" (``ui/permsapi.py``);
* **Read only** (``read_only``): no writing and no commands at all: the tools are cut to reading
  (``apply``), and the guard refuses anything else. The natural choice for a checker or the planner.

Under Careful and Ask every time some other tool calls wait too, each as one card through the gate's
machinery (``Gate.ask``: Allow once, Always allow, Don't allow, the time limit; if nobody answers it isn't
done): a file deleted (a tool that deletes, or a file written empty), a tool of an MCP server this project
hasn't allowed yet, and ``web_read`` of a website not seen before. A refusal goes back to the model as a plain
sentence and the task carries on.

Where a job's preset comes from, the first that is set:

1. the project's own setting for that job (``perms: {coder: free}`` in ``.harness/project.yaml`` or
   ``roundtable.yaml``);
2. the project's setting (``ask_first``);
3. this computer's choice: the app's choice for that job (``perms.roles`` in custom.yaml), then
   ``$ROUNDTABLE_GATE`` (the phone's "Ask me first"), then the app's default (``perms.default``);
4. harness.yaml (``perms: {roles: {…}, default: …}``, then ``gate.ask_first``);
5. Careful.

What learning or a project's kind suggests (``cfg.learned["perms"]``, ``cfg.kind_perms``) only ever makes a job
stricter: only the owner's tap loosens one. A project setting that can't be read makes every job at least
Ask every time: a permission check never fails open.

"A box where there is one": under Careful and Ask every time, on Linux with ``bwrap``, a builder's commands
run with the network off when the task says it doesn't need it (``needs_net: false`` from the plan):
``boxed`` puts bwrap in front of the command (``tools.Workspace.run_command`` calls it). On Windows, and where
there is no bwrap, the card says plainly that there is no such box.
"""


import fnmatch
import json
import os
import shlex
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from . import gate as _gate

PRESETS = ("ask_all", "careful", "free", "read_only")
DEFAULT_PRESET = "careful"
STRICTNESS = {"free": 0, "careful": 1, "ask_all": 2, "read_only": 3}
MODE_OF = {"free": "off", "careful": "risky", "ask_all": "all", "read_only": "all"}  # what the gate does with it
_FROM_MODE = {"all": "ask_all", "risky": "careful", "off": "free"}
TITLES = {"ask_all": "Ask every time", "careful": "Careful", "free": "Free", "read_only": "Read only"}
WORDS = {
    "ask_all": "Every command, and every change outside the task's planned files, waits for your tap.",
    "careful": "Only risky commands wait for your tap (deleting outside the project, sending code, installing…).",
    "free": "Nothing waits: commands and changes run straight away.",
    "read_only": "It can only read: no writing and no commands at all.",
}
KINDS = ("mcp", "hosts", "paths", "tools")
STORE = "tools.json"  # in .harness/gate/: the MCP tools, websites and files "Always allow" kept for this project

# the tools a Read only job keeps (plus every tool that ends its job: submit_plan, finish_task…)
READ_TOOLS = ("read_file", "list_files", "search", "web_search", "web_read")
_TERMINAL_NAMES = ("finish_task", "pick_best")
WRITE_TOOLS = ("write_file", "edit_file")
_DELETE_WORDS = ("delete", "remove", "unlink", "rmdir", "erase", "trash")


# -- the preset --------------------------------------------------------------------------------------------
def norm_preset(value: Any) -> str | None:
    """A preset from what a file, the app or the phone says (a preset's name or today's gate mode)."""
    if value is None or value == "":
        return None
    v = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    v = {"ask": "ask_all", "ask_every_time": "ask_all", "every": "ask_all", "readonly": "read_only",
         "read": "read_only", "risky": "careful", "default": None}.get(v, v)
    if v in PRESETS:
        return v
    mode = _gate.norm_mode(value)
    return _FROM_MODE.get(mode) if mode else None


def stricter(a: str, b: str) -> str:
    return a if STRICTNESS.get(a, 3) >= STRICTNESS.get(b, 3) else b


class _Unreadable(Exception):
    pass


def _project_job(root: Path, role: str) -> Any:
    """The project's own setting for this job (``perms`` in the project's files)."""
    from . import projectsettings as ps

    try:
        if "perms" in ps.BY_KEY:  # the project-settings line is in: it validates the value
            st = ps.load(root)
            table = st.values.get("perms") if st.sources.get("perms") != "default" else None
        else:
            table = None
            for name in (ps.REPO_FILE, ps.PROJECT_FILE):  # .harness/project.yaml wins over roundtable.yaml
                raw, _ = ps._read_raw(root / name)
                if "perms" in raw:
                    table = raw["perms"]
    except Exception as e:  # noqa: BLE001
        raise _Unreadable(str(e)) from e
    if table is None:
        return None
    if not isinstance(table, dict):
        raise _Unreadable("perms isn't a list of jobs")
    value = table.get(role)
    if value not in (None, "") and norm_preset(value) is None:
        raise _Unreadable(f"perms: {role}: {value!r} isn't a preset")
    return value


def _project_mode(root: Path) -> Any:
    try:
        value = _gate._project_value(root)
    except Exception as e:  # noqa: BLE001
        raise _Unreadable(str(e)) from e
    if value not in (None, "") and _gate.norm_mode(value) is None:
        raise _Unreadable(f"ask_first: {value!r}")
    return value


def computer_choices(cfg: Any) -> dict[str, Any]:
    """This computer's choices made in the app: custom.yaml's ``perms`` ({default, roles})."""
    path = getattr(cfg, "path", None)
    if not path:
        return {}
    from .config import load_custom

    try:
        mine = load_custom(Path(path)).get("perms")
    except Exception:  # noqa: BLE001 - an unreadable custom.yaml: harness.yaml and the default decide
        return {}
    return mine if isinstance(mine, dict) else {}


def _harness(cfg: Any) -> dict[str, Any]:
    from .config import section

    return section(cfg, "perms") if cfg is not None else {}


def explain(root: str | Path, cfg: Any, role: str) -> dict[str, str]:
    """{preset, source}: the preset for ``role`` and where it came from (for the app)."""
    root = Path(root)
    mine, yaml_ = computer_choices(cfg), _harness(cfg)
    gate_yaml = {}
    try:
        from .config import section

        gate_yaml = section(cfg, "gate") if cfg is not None else {}
    except Exception:  # noqa: BLE001
        pass
    chain: list[tuple[str, Callable[[], Any], Callable[[Any], str | None]]] = [
        ("this project, for this job", lambda: _project_job(root, role), norm_preset),
        ("this project", lambda: _project_mode(root), norm_preset),
        ("this computer, for this job", lambda: (mine.get("roles") or {}).get(role), norm_preset),
        ("this computer (Ask me first)", lambda: os.environ.get(_gate.ENV), norm_preset),
        ("this computer", lambda: mine.get("default"), norm_preset),
        ("harness.yaml, for this job", lambda: (yaml_.get("roles") or {}).get(role), norm_preset),
        ("harness.yaml", lambda: yaml_.get("default"), norm_preset),
        ("harness.yaml (ask_first)", lambda: gate_yaml.get("ask_first"), norm_preset),
    ]
    preset, source, broken = DEFAULT_PRESET, "the default", False
    for name, read, norm in chain:
        try:
            value = read()
        except _Unreadable:
            broken = True
            continue
        except Exception:  # noqa: BLE001 - any other trouble reading a place: the next one decides, see below
            broken = True
            continue
        got = norm(value)
        if got:
            preset, source = got, name
            break
    if broken and STRICTNESS[preset] < STRICTNESS["ask_all"]:
        # a setting that can't be read must never let anything through unseen
        preset, source = "ask_all", "a setting that couldn't be read (so everything waits for you)"
    for name, table in (("what it learned", _learned(cfg)), ("the project's kind", _kind(cfg))):
        got = norm_preset(table.get(role) or table.get("default")) if table else None
        if got and STRICTNESS[got] > STRICTNESS[preset]:  # only ever stricter
            preset, source = got, name
    return {"preset": preset, "source": source}


def _learned(cfg: Any) -> dict[str, Any]:
    t = (getattr(cfg, "learned", None) or {}).get("perms") if cfg is not None else None
    return t if isinstance(t, dict) else {}


def _kind(cfg: Any) -> dict[str, Any]:
    t = getattr(cfg, "kind_perms", None) if cfg is not None else None
    return t if isinstance(t, dict) else {}


def preset_for(root, cfg, role: str) -> str:
    """The preset that applies to ``role`` on the project at ``root`` (see the order above)."""
    try:
        return explain(root, cfg, role)["preset"]
    except Exception:  # noqa: BLE001 - never fail open
        return "ask_all"


# -- the project's "Always allow" for tools -------------------------------------------------------------------
def _store_path(root: Path) -> Path:
    return Path(root) / _gate.GATE_DIR / STORE


def allowed(root: str | Path) -> dict[str, list[str]]:
    try:
        data = json.loads(_store_path(Path(root)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {k: [str(x) for x in (data.get(k) or []) if isinstance(x, str)] for k in KINDS}


def allow(root: str | Path, kind: str, value: str) -> None:
    if kind not in KINDS:
        raise ValueError(kind)
    data = allowed(root)
    if value not in data[kind]:
        data[kind].append(value)
        p = _store_path(Path(root))
        p.parent.mkdir(parents=True, exist_ok=True)
        _gate._write_json(p, data)


def forget(root: str | Path, kind: str, value: str) -> bool:
    data = allowed(root)
    if kind not in data or value not in data[kind]:
        return False
    data[kind].remove(value)
    _gate._write_json(_store_path(Path(root)), data)
    return True


# -- the task doing the work ------------------------------------------------------------------------------------
def _task_info(root: Path, g: Any) -> dict[str, Any] | None:
    """The running task's record from tasks.json (its planned ``files``, ``needs_net``), None when unknown."""
    try:
        tid = (g._task() or {}).get("id") if g is not None else None
    except Exception:  # noqa: BLE001
        tid = None
    if not tid:
        return None
    try:
        tasks = json.loads((Path(root) / ".harness" / "tasks.json").read_text(encoding="utf-8") or "[]")
    except (OSError, ValueError):
        return {"id": tid}
    for t in tasks if isinstance(tasks, list) else []:
        if isinstance(t, dict) and str(t.get("id")) == tid:
            return t
    return {"id": tid}


def _rel(path: str) -> str:
    p = str(path).replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p


def _planned(path: str, files: list[str]) -> bool:
    p = _rel(path)
    if p.startswith("../") or "/../" in p:
        return False
    for f in files:
        f = _rel(f)
        if not f:
            continue
        if p == f.rstrip("/") or p.startswith(f.rstrip("/") + "/") or fnmatch.fnmatch(p, f):
            return True
    return False


# -- the network box ------------------------------------------------------------------------------------------
_BOX = threading.local()
_LAYER: list[str] = []


def _box_layer() -> str:
    """"bwrap" when this computer can cut a command's network, else "" (cached)."""
    if not _LAYER:
        layer = ""
        if sys.platform.startswith("linux"):
            try:
                from ..plugins import sandbox

                info = sandbox.supported()
                layer = "bwrap" if info.get("layer") == "bwrap" and info.get("os_net") else ""
            except Exception:  # noqa: BLE001
                layer = ""
        _LAYER.append(layer)
    return _LAYER[0]


def box_prefix() -> list[str]:
    return ["bwrap", "--dev-bind", "/", "/", "--unshare-net", "--die-with-parent", "--"]


def boxed(command: str) -> str:
    """The command as it runs: with bwrap in front (network off) when this job's check decided so a moment ago
    in this thread, else unchanged. ``tools.Workspace.run_command`` calls it just before running."""
    item = getattr(_BOX, "item", None)
    _BOX.item = None
    if not item or item[0] != command or time.monotonic() - item[1] > _gate.CLEARED_SECONDS:
        return command
    return shlex.join([*box_prefix(), "/bin/sh", "-c", command])


def _box_note(preset: str, task: dict[str, Any] | None) -> tuple[bool, str]:
    """(network off?, the plain line for the card)."""
    if preset not in ("careful", "ask_all"):
        return False, ""
    if os.name == "nt":
        return False, "There's no box on Windows: if you allow it, it runs with this computer's full reach."
    if not _box_layer():
        return False, "There's no box on this computer (bwrap isn't installed): if you allow it, it can use the internet."
    if task is not None and task.get("needs_net") is False:
        return True, "It runs in a box with the internet off (this task doesn't need it)."
    return False, "This task may need the internet, so it runs without a box."


# -- the guard ------------------------------------------------------------------------------------------------
def _is_delete(name: str) -> bool:
    parts = name.lower().replace("-", "_").split("__")[-1].split("_")
    return any(w in parts for w in _DELETE_WORDS)


def _linked_findings(root: Path, command: str) -> list[_gate.Finding]:
    """A command that deletes a folder shared with the main project (worktrees.link_deps)."""
    from .worktrees import linked_folders

    shared = linked_folders(root)
    if not shared:
        return []
    out = []
    for seg in _gate.segments(command):
        name, args = _gate.program(_gate.tokens(seg))
        if name not in _gate.DELETERS and not (name == "find" and "-delete" in args) and not (
                name == "git" and args[:1] == ["clean"]):
            continue
        targets = _gate._paths(name, args) if name not in ("remove-item", "ri") else _gate._ps_paths(args)
        if name == "git":
            targets = ["."]
        for t in targets:
            t = t.strip("\"'").replace("\\", "/").rstrip("/")
            while t.startswith("./"):
                t = t[2:]
            for s in shared:
                if t in (".", "*", "") or t == s or t.startswith(s + "/") or s.startswith(t + "/"):
                    out.append(_gate.Finding(f"it deletes {s}, which is shared with the main project folder "
                                             "(linked, not copied)", _gate.normalise(command), True,
                                             _gate.normalise(seg)))
    return out


def guard(root, cfg, role: str, gate) -> Callable:
    """A ``Toolbox`` guard for ``role``: ``(tool name, arguments) -> refusal sentence or None``. It may wait for
    the owner's tap. ``gate`` is the workspace's gate (its cards, its time limit); without one it makes its own."""
    root = Path(root)
    g = gate if gate is not None else _gate.Gate(root, cfg)
    this_run: set[tuple[str, str]] = set()  # "Allow once" holds for the rest of this job

    def check(name: str, args: dict[str, Any]) -> str | None:
        preset = preset_for(root, cfg, role)
        args = args if isinstance(args, dict) else {}
        if name == "run_command":
            return _command(preset, str(args.get("command", "")))
        if preset == "read_only":
            if name in READ_TOOLS or name in _TERMINAL_NAMES or name.startswith("submit_") \
                    or name in getattr(check, "keep", ()):
                return _web(name, args) if name == "web_read" else None
            return _gate.refusal_read_only(f"use {name}")
        if preset == "free":
            return None
        if name.startswith("mcp__"):
            return _mcp(name, args)
        if name == "web_read":
            return _web(name, args)
        if _is_delete(name):
            return _delete(name, args)
        if name in WRITE_TOOLS:
            return _write(preset, name, args)
        return None

    def _command(preset: str, command: str) -> str | None:
        if preset == "read_only":
            return _gate.refusal_read_only()
        extra = _linked_findings(root, command)
        if preset == "free":
            if extra:
                return ("This command would delete a folder that is shared with the main project folder (it's "
                        "linked into your copy, not copied), so it wasn't run. Delete only what's in your own copy.")
            return _clear_after(command, None, "off")
        task = _task_info(root, g)
        net_off, note = _box_note(preset, task)
        job_mode = MODE_OF[preset]
        try:
            own_mode = g.mode()  # what the workspace's gate would decide by itself
        except Exception:  # noqa: BLE001
            own_mode = None
        if job_mode == own_mode and not extra and not net_off and not note:
            return None  # the same decision the workspace's gate makes: leave it to it (as before)
        refusal = g.check(command, mode=job_mode, extra=extra, note=note)
        if refusal:
            return refusal
        return _clear_after(command, net_off, job_mode)

    def _clear_after(command: str, net_off: bool | None, job_mode: str) -> None:
        if len(command.encode("utf-8", errors="replace")) > _gate.MAX_COMMAND_BYTES:
            return None  # too long to show: the workspace's gate refuses it, whatever the preset
        _gate.clear_once(g.root, command)
        if net_off:
            _BOX.item = (command, time.monotonic())
        return None

    def _delete(name: str, args: dict[str, Any]) -> str | None:
        target = str(args.get("path") or args.get("file") or args.get("name") or "")
        what = f"Delete {target}" if target else f"Use {name}, which deletes something"
        if name in allowed(root)["tools"]:
            return None
        return g.ask(what, ["it deletes something, and that can't be undone"], tool=name,
                     remember=f"{name} in this project", detail=_args_text(args),
                     on_always=lambda: allow(root, "tools", name))

    def _mcp(name: str, args: dict[str, Any]) -> str | None:
        if name in allowed(root)["mcp"] or ("mcp", name) in this_run:
            return None
        server = name[len("mcp__"):].split("__", 1)
        label = f"{server[0]}'s tool {server[1]}" if len(server) == 2 else name
        refusal = g.ask(f"Use {label}", ["this project hasn't used this tool before"], tool=name,
                        remember="this tool in this project", detail=_args_text(args),
                        on_always=lambda: allow(root, "mcp", name))
        if refusal is None:
            this_run.add(("mcp", name))
        return refusal

    def _web(name: str, args: dict[str, Any]) -> str | None:
        url = str(args.get("url") or "").strip()
        try:
            host = (urlsplit(url).hostname or "").lower().rstrip(".")
        except ValueError:
            host = ""
        if not host:
            return "That isn't a web address this job can check, so the page wasn't read. Give the whole address."
        if preset_for(root, cfg, role) == "free" or host in allowed(root)["hosts"] or ("host", host) in this_run:
            return None
        refusal = g.ask(f"Read a page on {host}", ["no job on this project has read this website before"],
                        tool=name, remember=f"{host} in this project", detail=url[:500],
                        on_always=lambda: allow(root, "hosts", host))
        if refusal is None:
            this_run.add(("host", host))
        return refusal

    def _kept_path(path: str) -> bool:
        return _rel(path) in {_rel(x) for x in allowed(root)["paths"]}

    def _write(preset: str, name: str, args: dict[str, Any]) -> str | None:
        path = str(args.get("path") or "")
        if name == "write_file" and args.get("content", None) == "" and path:
            try:
                existing = (Path(g.root) / path).is_file() or (Path(getattr(check, "ws_root", g.root)) / path).is_file()
            except (OSError, ValueError):
                existing = True
            if existing and ("path", path) not in this_run and not _kept_path(path):
                refusal = g.ask(f"Empty the file {path}", ["it wipes what's in a file, like deleting it"], tool=name,
                                remember=f"{path} in this project", on_always=lambda: allow(root, "paths", _rel(path)))
                if refusal is None:
                    this_run.add(("path", path))
                return refusal
        if preset != "ask_all" or not path:
            return None
        task = _task_info(root, g)
        files = [str(f) for f in ((task or {}).get("files") or [])]
        if _planned(path, files) or _kept_path(path) or ("path", path) in this_run:
            return None
        why = ("it isn't one of this task's planned files" if files
               else "this task has no planned files")
        verb = "Change" if name == "edit_file" else "Write"
        refusal = g.ask(f"{verb} {path}", [why], tool=name, remember=f"{path} in this project",
                        on_always=lambda: allow(root, "paths", _rel(path)))
        if refusal is None:
            this_run.add(("path", path))
        return refusal

    check.role = role  # type: ignore[attr-defined]
    return check


def _args_text(args: dict[str, Any]) -> str:
    try:
        text = json.dumps(args, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = str(args)
    return text[:1500]


def apply(box: Any, root, cfg, role: str, gate) -> Any:
    """Fit a ``Toolbox`` to ``role``'s preset once: a Read only job keeps only reading tools (and the tool that
    ends its job), and the guard is added. Safe to call again on the same box (it does nothing the second time)."""
    if getattr(box, "_perms_role", None) == role:
        return box
    preset = preset_for(root, cfg, role)
    keep = [n for n, t in box.tools.items() if getattr(t, "terminal", False)]
    if preset == "read_only":
        for name in list(box.tools):
            if name not in READ_TOOLS and name not in keep:
                box.tools.pop(name)
    g = guard(root, cfg, role, gate)
    g.keep = tuple(keep)  # type: ignore[attr-defined]
    if getattr(box, "source", None) is not None:
        g.ws_root = getattr(box.source, "root", None) or root  # type: ignore[attr-defined]
    box.guards.append(g)
    box._perms_role = role
    return box
