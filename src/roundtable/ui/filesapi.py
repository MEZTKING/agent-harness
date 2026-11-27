"""Files in the app: a project's folder to browse, its files to open, and the commands its tasks ran.

    GET  /api/files              ?path=<project>&dir=<folder in it>   (or ?name=<hub name> for one elsewhere)
                                 -> {here: true, path, dir, crumbs: [{name, dir}], items: [{name, path, folder,
                                     size, kind}], more: n, test_command}
                                 or {here: false, words, machine_name} when the files are on another machine
    GET  /api/files/open         ?path=&file=&copy=1 -> {file, name, size, kind, mime, data}: Save a copy (the phone)
    GET  /api/files/open         ?path=&file=&inline=1 -> {file, name, size, kind, lang, text | rows | data,
                                 too_big, words}; kind: text, code, markdown, csv, json, image, pdf, other
                                 (``data``: base64, for pictures and PDFs, with inline=1 and under INLINE_MAX)
    GET  /api/files/log          ?path=&task= -> {commands: [{at, task, task_title, who, kind, command,
                                 exit_code, passed, timed_out, words, output}] newest first, test_command,
                                 can_run, why_not}
    POST /api/files/run_tests    {path} -> the background job (kind "tests") running the project's own test command
    /raw/pfile                   ?path=&file=&download=1: the file itself, for pictures, the PDF viewer, video and
                                 sound, and Save a copy (``raw_file``; wired in ``UIApp.raw``). A ``Range`` request
                                 (passed in as ``_range``) gets only those bytes, so a video can be wound on.

A file with a richer view (a notebook, an archive, a Word, Excel or PowerPoint file, video or sound) carries
``preview`` (``preview.kind``): the desktop asks ``/api/files/preview`` (ui/editapi.py) for it. ``kind`` stays as it
was, so the phone shows what it always has.

Safety (the same rules as ``showit.safe_path``, which every file goes through): no ``..`` or absolute paths, nothing
hidden (``.git``, ``.harness``, ``.env`` and every other dot-file), no link that leads out of the project, and no file
that looks like a key or password store (``SECRET_NAME``). Big files say so instead of loading. The command log is
read from the project's own records on purpose (``.harness/events.jsonl``, ``project.json``, ``test-runs.jsonl``);
the rest of ``.harness`` is never served.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

from ..harness import showit
from ..brand import NAME

TEXT_MAX = 1_000_000  # bytes of text shown in the app; bigger says so
INLINE_MAX = 10_000_000  # pictures and PDFs sent inside the answer (the phone)
RAW_MAX = 200_000_000  # Save a copy
LIST_MAX = 500  # entries shown in one folder
CSV_ROWS, CSV_COLS = 500, 60
LOG_MAX = 300  # commands in the log
OUTPUT_MAX = 20_000  # characters of one command's output kept in the log
EVENTS_MAX = 20_000_000  # the newest part of events.jsonl that is read
RUNS_FILE = "test-runs.jsonl"  # under .harness/: the owner's own "Run the tests"

HIDE_DIRS = {"__pycache__"}  # never worth opening; node_modules is shown (it is only a folder until opened)
SECRET_NAME = re.compile(
    r"(?i)^(?:id_(?:rsa|dsa|ecdsa|ed25519)(?:\.pub)?|.*\.(?:pem|key|p12|pfx|jks|keystore|kdbx|ppk|secret|env)"
    r"|credentials(?:\..*)?|client_secret.*\.json|service[-_]account.*\.json|secrets?(?:\..*)?"
    r"|keystore\.properties|signing\.properties|local\.properties|\.?netrc|auth\.json)$")
SECRET_DIRS = re.compile(r"(?i)^(?:secrets?|signing|keys)$")

IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".avif", ".svg"}
MARKDOWN = {".md", ".markdown", ".mdown"}
CSVS = {".csv": ",", ".tsv": "\t"}
JSONS = {".json", ".webmanifest", ".map", ".geojson"}
LANGS = {
    ".py": "python", ".pyw": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript", ".kt": "kotlin", ".kts": "kotlin",
    ".java": "java", ".gd": "gdscript", ".cs": "csharp", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
    ".rs": "rust", ".go": "go", ".rb": "ruby", ".php": "php", ".swift": "swift", ".lua": "lua",
    ".sh": "shell", ".bash": "shell", ".ps1": "powershell", ".bat": "batch", ".cmd": "batch",
    ".html": "html", ".htm": "html", ".xml": "xml", ".svg": "xml", ".css": "css", ".scss": "css",
    ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".ini": "ini", ".cfg": "ini", ".sql": "sql",
    ".gradle": "groovy", ".tscn": "ini", ".tres": "ini", ".godot": "ini", ".vue": "html", ".svelte": "html",
    ".jsonl": "json", ".dockerfile": "shell",
}
TEXT_NAMES = {"dockerfile", "makefile", "license", "licence", "readme", "procfile", "gemfile", "changelog"}


# -- routes ---------------------------------------------------------------------------------------
def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/files"): lambda q: listing(app, q),
        ("GET", "/api/files/open"): lambda q: open_file(app, q),
        ("GET", "/api/files/log"): lambda q: command_log_view(app, q),
        ("POST", "/api/files/run_tests"): lambda body: run_tests(app, body),
    }


def _first(q: dict, key: str, default: str = "") -> str:
    v = q.get(key, default)
    if isinstance(v, list):
        v = v[0] if v else default
    return str(v if v is not None else default)


def _error(text: str, status: int = 400):
    from .server import ApiError

    return ApiError(text, status)


# -- where the project is -------------------------------------------------------------------------
def _local_root(app, q: dict) -> Path | None:
    """The project's folder when it is on this computer (only registered projects), else None."""
    path = _first(q, "path")
    if not path:
        return None
    cfg = app.cfg()
    if not cfg:
        return None
    from .server import ApiError

    try:
        return app.project(cfg, path).root
    except ApiError:
        return None


def elsewhere(app, q: dict) -> dict[str, Any]:
    """Where the files are when they aren't on this computer, in words."""
    name = _first(q, "name") or PurePosixPath(_first(q, "path").replace("\\", "/")).name
    where = None
    try:
        from .. import sync

        hub = app.hub if getattr(app, "hub", None) is not None else None
        where = sync.where_is(hub, name) if hub is not None and name else None
    except Exception:  # the hub can't be read: say what we can
        where = None
    machine = (where or {}).get("machine_name") or ""
    if machine:
        words = (f"This project's files are on {machine}. Open {NAME} there to see them, or connect to it "
                 "from here when it's on.")
    else:
        words = f"This project's files aren't on this computer. Open {NAME} on the computer that builds it."
    return {"here": False, "name": name, "machine_name": machine, "words": words}


def _root_or_elsewhere(app, q: dict) -> tuple[Path | None, dict[str, Any] | None]:
    root = _local_root(app, q)
    return (root, None) if root is not None else (None, elsewhere(app, q))


# -- the rules ------------------------------------------------------------------------------------
def _parts(rel: str) -> tuple[str, ...] | None:
    """The folder parts of ``rel`` under the same rules as showit.safe_path (None when refused); "" is the top."""
    if "\x00" in rel:
        return None
    rel = rel.replace("\\", "/").strip("/") if not rel.startswith(("/", "\\")) else None
    if rel is None or re.match(r"^[A-Za-z]:", rel):
        return None
    if not rel:
        return ()
    parts = PurePosixPath(rel).parts
    if any(p in ("..", "") or p.startswith(".") for p in parts):
        return None
    return parts


def is_secret(name: str, folder: bool = False) -> bool:
    """A file or folder that may hold a key or password (never shown, never served)."""
    return bool(SECRET_DIRS.match(name) if folder else SECRET_NAME.match(name))


def safe_dir(root: Path, rel: str) -> Path | None:
    """The folder ``rel`` inside ``root`` (or root itself for ""), or None when it is outside, hidden, secret, a link
    out, or missing."""
    parts = _parts(rel)
    if parts is None or any(is_secret(p, True) for p in parts):
        return None
    base = Path(root).resolve()
    full = (base / Path(*parts)).resolve() if parts else base
    if (full != base and base not in full.parents) or not full.is_dir():
        return None
    return full


def safe_file(root: Path, rel: str) -> Path | None:
    """The file ``rel`` (showit.safe_path's rules, and never a secret or inside a secret folder)."""
    parts = _parts(rel)
    if not parts or is_secret(parts[-1]) or any(is_secret(p, True) for p in parts[:-1]):
        return None
    return showit.safe_path(root, "/".join(parts))


def _inside(base: Path, p: Path) -> bool:
    try:
        r = p.resolve()
    except OSError:
        return False
    return r == base or base in r.parents


def kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in IMAGES:
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext in MARKDOWN:
        return "markdown"
    if ext in CSVS:
        return "csv"
    if ext in JSONS:
        return "json"
    if ext in LANGS:
        return "code"
    if ext in (".txt", ".log", ".text", ".rst", "") or path.name.lower() in TEXT_NAMES:
        return "text"
    return "other"


# -- listing a folder -----------------------------------------------------------------------------
def list_dir(root: Path, rel: str = "") -> dict[str, Any]:
    """One folder of the project: folders first, then files, by name; nothing hidden, secret or leading out."""
    base = Path(root).resolve()
    d = safe_dir(base, rel)
    if d is None:
        raise _error("That folder can't be opened: it isn't in the project, or it's one the harness keeps private.", 404)
    items: list[dict[str, Any]] = []
    try:
        entries = list(os.scandir(d))
    except OSError as e:
        raise _error(f"That folder can't be read ({e.strerror or e}). Try again, or look on the computer itself.") from None
    for e in entries:
        name = e.name
        if name.startswith(".") or name in HIDE_DIRS:
            continue
        try:
            folder = e.is_dir()
            if e.is_symlink() and not _inside(base, Path(e.path)):
                continue  # a link that leads out of the project
            if not folder and not e.is_file():
                continue
            if is_secret(name, folder):
                continue
            size = 0 if folder else e.stat().st_size
        except OSError:
            continue
        relp = (PurePosixPath(*_parts(rel)) / name).as_posix() if _parts(rel) else name
        items.append({"name": name, "path": relp, "folder": folder, "size": size,
                      "kind": "folder" if folder else kind_of(Path(name)), "preview": "" if folder else rich(name)})
    items.sort(key=lambda x: (not x["folder"], x["name"].lower()))
    parts = _parts(rel) or ()
    crumbs = [{"name": "Project", "dir": ""}] + [
        {"name": p, "dir": "/".join(parts[: i + 1])} for i, p in enumerate(parts)]
    return {"dir": "/".join(parts), "crumbs": crumbs, "items": items[:LIST_MAX],
            "more": max(0, len(items) - LIST_MAX)}


def listing(app, q: dict) -> dict[str, Any]:
    root, other = _root_or_elsewhere(app, q)
    if other:
        return other
    out = list_dir(root, _first(q, "dir"))
    return {"here": True, "path": str(root), "name": root.name, **out, "test_command": test_command(root)}


# -- opening a file -------------------------------------------------------------------------------
def _looks_binary(head: bytes) -> bool:
    return b"\x00" in head[:8192]


def read_file(root: Path, rel: str, inline: bool = False) -> dict[str, Any]:
    """What the app shows for one file. Text comes as text (never run, never as a page), a CSV as rows, pictures and
    PDFs as base64 only when ``inline`` (the phone; the desktop uses /raw/pfile)."""
    f = safe_file(Path(root), rel)
    if f is None:
        raise _error("That file can't be opened: it isn't in the project, or it's one the harness keeps private "
                     "(keys, passwords and its own records).", 404)
    size = f.stat().st_size
    kind = kind_of(f)
    out: dict[str, Any] = {"file": rel.replace("\\", "/").strip("/"), "name": f.name, "size": size, "kind": kind,
                           "lang": LANGS.get(f.suffix.lower(), ""), "too_big": False, "words": "",
                           "preview": rich(f.name)}
    if kind in ("image", "pdf"):
        if inline:
            if size > INLINE_MAX:
                out.update(too_big=True, words=f"This file is {_size(size)}: too big to show here. Save a copy to open it.")
            else:
                out["data"] = base64.b64encode(f.read_bytes()).decode("ascii")
        return out
    if size > TEXT_MAX:
        out.update(too_big=True, words=f"This file is {_size(size)}: too big to show here. Save a copy to open it.")
        return out
    raw = f.read_bytes()
    if kind == "other" and (_looks_binary(raw) or not _utf8(raw)):
        out["words"] = "The harness can't show this kind of file. Save a copy to open it with another app."
        return out
    if kind == "other":
        out["kind"] = kind = "text"
    text = raw.decode("utf-8", errors="replace")
    if kind == "csv":
        rows, cut = csv_rows(text, CSVS.get(f.suffix.lower(), ","))
        out["rows"] = rows
        if cut:
            out["words"] = f"Only the first {CSV_ROWS} rows and {CSV_COLS} columns are shown."
        return out
    if kind == "json":
        try:
            json.loads(text)
        except ValueError as e:
            out["words"] = f"This JSON has a mistake ({e}), so it's shown as plain text."
            out["kind"] = "code"
            out["lang"] = "json"
    out["text"] = text
    return out


def _utf8(raw: bytes) -> bool:
    try:
        raw.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def csv_rows(text: str, delimiter: str = ",") -> tuple[list[list[str]], bool]:
    rows: list[list[str]] = []
    cut = False
    try:
        for i, row in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter)):
            if i >= CSV_ROWS:
                cut = True
                break
            if len(row) > CSV_COLS:
                cut = True
            rows.append(row[:CSV_COLS])
    except csv.Error:
        pass
    return rows, cut


def _size(n: int) -> str:
    v = float(n)
    for unit in ("bytes", "KB", "MB", "GB"):
        if v < 1024 or unit == "GB":
            return f"{int(v)} bytes" if unit == "bytes" else f"{v:.1f} {unit}"
        v /= 1024
    return f"{n} bytes"


def open_file(app, q: dict) -> dict[str, Any]:
    root, other = _root_or_elsewhere(app, q)
    if other:
        return other
    if _first(q, "copy") in ("1", "true"):
        return {"here": True, **copy_of(root, _first(q, "file"))}
    return {"here": True, **read_file(root, _first(q, "file"), inline=_first(q, "inline") in ("1", "true"))}


def copy_of(root: Path, rel: str) -> dict[str, Any]:
    """Save a copy on the phone: the whole file as base64 (up to INLINE_MAX), whatever its kind."""
    f = safe_file(Path(root), rel)
    if f is None:
        raise _error("That file can't be saved: it isn't in the project, or it's one the harness keeps private.", 404)
    size = f.stat().st_size
    if size > INLINE_MAX:
        raise _error(f"This file is {_size(size)}: too big to send to the phone. Open it on the computer instead.", 413)
    return {"file": rel.replace("\\", "/").strip("/"), "name": f.name, "size": size, "kind": kind_of(f),
            "mime": showit.content_type(f).split(";")[0], "data": base64.b64encode(f.read_bytes()).decode("ascii")}


def raw_file(app, q: dict) -> tuple[bytes, str, dict[str, str]]:
    """The file itself (/raw/pfile): pictures and PDFs shown, anything else (or ?download=1) saved, never run as a
    page of Roundtable's own."""
    root = _local_root(app, q)
    if root is None:
        raise FileNotFoundError("that project's files aren't on this computer")
    f = safe_file(root, _first(q, "file"))
    if f is None:
        raise FileNotFoundError("that file isn't there, or the harness keeps it private")
    if f.stat().st_size > RAW_MAX:
        raise ValueError("that file is too big to send through the app")
    return raw_answer(f, download=_first(q, "download") in ("1", "true"), range_header=_first(q, "_range"))


def rich(name: str) -> str:
    """The richer view a file has (notebook, archive, office, video, audio) or ""."""
    from .. import preview

    return preview.kind(name)


def byte_range(header: str, size: int) -> tuple[int, int] | None:
    """The bytes a ``Range: bytes=a-b`` header asks for, as (first, last) inclusive; None for the whole file
    (no header, several ranges, or one that can't be met: the whole file is the safe answer)."""
    m = re.fullmatch(r"\s*bytes=(\d*)-(\d*)\s*", header or "")
    if not m or size <= 0 or (not m.group(1) and not m.group(2)):
        return None
    if not m.group(1):  # the last n bytes
        n = int(m.group(2))
        return (max(0, size - n), size - 1) if n else None
    a = int(m.group(1))
    b = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
    return (a, b) if a <= b and a < size else None


def _read_range(f: Path, span: tuple[int, int] | None) -> bytes:
    if span is None:
        return f.read_bytes()
    with open(f, "rb") as fh:
        fh.seek(span[0])
        return fh.read(span[1] - span[0] + 1)


def raw_answer(f: Path, download: bool = False, range_header: str = "") -> tuple[bytes, str, dict[str, str]]:
    """The file's bytes, its type and headers. With ``range_header`` only those bytes, and the headers carry
    ``_status: 206`` and ``Content-Range`` (the server sends that status)."""
    from .. import preview

    sandbox = {"Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'"}
    name = f.name.replace('"', "")
    kind = kind_of(f)
    size = f.stat().st_size
    span = byte_range(range_header, size)
    ranged = {"Accept-Ranges": "bytes"}
    if span is not None:
        ranged.update({"_status": "206", "Content-Range": f"bytes {span[0]}-{span[1]}/{size}"})
    media = preview.media_type(f.name)
    if download or (kind not in ("image", "pdf") and not media):
        return _read_range(f, span), "application/octet-stream", {
            **sandbox, **ranged, "Content-Disposition": f'attachment; filename="{name}"'}
    if kind == "pdf":  # the browser's own PDF viewer (a sandbox would stop it)
        return _read_range(f, span), "application/pdf", {**ranged, "Content-Disposition": f'inline; filename="{name}"',
                                                         "X-Frame-Options": "SAMEORIGIN"}
    if media:  # the browser's own player
        return _read_range(f, span), media, {**sandbox, **ranged}
    return _read_range(f, span), showit.content_type(f), {**sandbox, **ranged}


# -- the command log ------------------------------------------------------------------------------
def _exit_code(text: str) -> int | None:
    m = re.match(r"\s*exit code: (-?\d+)", text or "")
    return int(m.group(1)) if m else None


def _rows(path: Path, limit: int = EVENTS_MAX) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with open(path, "rb") as fh:
        size = fh.seek(0, 2)
        fh.seek(max(0, size - limit))
        data = fh.read()
    lines = data.decode("utf-8", errors="replace").splitlines()
    if size > limit:
        lines = lines[1:]  # the first may be cut
    out = []
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def _words(passed: bool | None, code: int | None, timed_out: bool = False) -> str:
    if timed_out:
        return "took too long and was stopped"
    if passed:
        return "worked"
    if code is not None:
        return f"failed (exit code {code})"
    return "failed" if passed is False else "no exit code recorded"


def command_log(root: Path, task: str = "", tasks: dict[str, str] | None = None, reviewer: str | None = None,
                meta: dict[str, Any] | None = None, test_cmd: str = "") -> list[dict[str, Any]]:
    """Every command the project's tasks ran (run_command), its checks (setup, the starting point, after each task)
    and the owner's own Run the tests, newest first. Built from the project's own records only."""
    root = Path(root)
    hdir = root / ".harness"
    tasks = tasks or {}
    meta = meta or {}
    out: list[dict[str, Any]] = []

    def add(row: dict[str, Any]) -> None:
        if task and row.get("task") != task:
            return
        row.setdefault("task_title", tasks.get(row.get("task") or "", ""))
        row["output"] = _cut(row.get("output") or "")
        out.append(row)

    for d in _rows(hdir / "events.jsonl"):
        ev = d.get("event")
        if ev == "tool_call" and d.get("tool") == "run_command":
            args = d.get("args") or {}
            text = str(d.get("output") or d.get("result") or "")
            code = _exit_code(text)
            refused = bool(d.get("refused"))
            err = bool(d.get("error"))
            passed = (code == 0) if code is not None else (False if err else None)
            words = ("wasn't run: " + text[:200]) if refused else (
                ("didn't run: " + text[:200]) if err and code is None else _words(passed, code))
            who = "reviewer" if reviewer and d.get("role") == reviewer else (d.get("role") or "worker")
            add({"at": d.get("at", ""), "task": d.get("task", ""), "who": who, "kind": "task",
                 "command": str(args.get("command") or ""), "exit_code": code, "passed": passed,
                 "timed_out": "timed out" in text[:200], "refused": refused, "words": words, "output": text})
        elif ev == "checks":
            verdict = d.get("verdict")
            passed = verdict == "pass"
            new = d.get("new") or []
            text = ("These tests fail now:\n" + "\n".join(f"- {n}" for n in new)) if new else ""
            words = {"pass": "the checks passed", "old_only": "still fails, but only on tests that failed before",
                     "unknown": "fails, as it did before the run", "new": "the checks found a problem"}.get(verdict, str(verdict))
            add({"at": d.get("at", ""), "task": d.get("task", ""), "who": "checks", "kind": "checks",
                 "command": test_cmd or (meta.get("baseline") or {}).get("command", ""), "exit_code": None,
                 "passed": passed, "timed_out": False, "words": words, "output": text})
        elif ev in ("baseline", "setup"):
            m = meta.get(ev) or {}
            same = m.get("command") == d.get("command")
            label = "the starting point, before any task" if ev == "baseline" else "the project's set-up"
            add({"at": d.get("at", ""), "task": d.get("task", ""), "who": "checks", "kind": ev,
                 "command": str(d.get("command") or ""), "exit_code": m.get("exit_code") if same else None,
                 "passed": bool(d.get("passed")), "timed_out": bool(m.get("timed_out")) if same else False,
                 "words": f"{label}: " + ("worked" if d.get("passed") else "failed"),
                 "output": (m.get("tail") or "") if same else ""})
    for d in _rows(hdir / RUNS_FILE):
        add({"at": d.get("at", ""), "task": "", "who": "you", "kind": "tests", "command": d.get("command", ""),
             "exit_code": d.get("exit_code"), "passed": d.get("passed"), "timed_out": bool(d.get("timed_out")),
             "words": "you ran the tests: " + _words(d.get("passed"), d.get("exit_code"), bool(d.get("timed_out"))),
             "output": d.get("output", ""), "seconds": d.get("seconds")})
    out.sort(key=lambda r: r.get("at") or "", reverse=True)
    return out[:LOG_MAX]


def _cut(text: str) -> str:
    head = OUTPUT_MAX // 5  # the start (the command's first words) and most of the end (where errors are)
    return text if len(text) <= OUTPUT_MAX else text[:head] + "\n...\n" + text[-(OUTPUT_MAX - head):]


def test_command(root: Path) -> str:
    from ..harness import projectsettings as ps

    try:
        return str(ps.load(root).values.get("test") or "")
    except Exception:  # a settings file with a mistake: no button, the Settings tab says what's wrong
        return ""


def command_log_view(app, q: dict) -> dict[str, Any]:
    root, other = _root_or_elsewhere(app, q)
    if other:
        return other
    from ..harness.orchestrator import Project

    proj = Project(root)
    cfg = app.cfg()
    tasks = {t.id: t.title for t in proj.tasks()}
    test = test_command(root)
    rows = command_log(root, _first(q, "task"), tasks, getattr(cfg, "reviewer_role", None), proj.meta(), test)
    busy = app._busy(root)
    why = "" if test else "This project has no test command yet: add one in the project's Settings (Checks)."
    if test and busy:
        why = "The harness is working on this project now: run the tests when it has finished."
    return {"here": True, "path": str(root), "commands": rows, "test_command": test, "can_run": bool(test) and not busy,
            "why_not": why}


# -- Run the tests ----------------------------------------------------------------------------------
def run_tests(app, body: dict) -> dict[str, Any]:
    """The owner's "Run the tests": the project's own test command as a background job (no free shell)."""
    from ..core.models import utcnow
    from ..harness import checks
    from ..harness import projectsettings as ps

    root = _local_root(app, body)
    if root is None:
        raise _error(elsewhere(app, body)["words"], 404)
    st = ps.load(root)
    if st.errors:
        raise _error("This project's settings file has a mistake, so the tests can't run. Open its Settings to fix it.")
    test = str(st.values.get("test") or "")
    if not test:
        raise _error("This project has no test command yet: add one in the project's Settings (Checks).")
    if app._busy(root):
        raise _error("The harness is working on this project now: run the tests when it has finished.", 409)
    env, timeout = st.values.get("env") or {}, int(st.values.get("timeout") or 900)

    def run(job) -> dict[str, Any]:
        job.line(f"$ {test}")
        res = checks.run(root, test, env, timeout)
        passed = res["exit_code"] == 0 and not res["timed_out"]
        row = {"at": utcnow(), "command": test, "exit_code": res["exit_code"], "passed": passed,
               "timed_out": res["timed_out"], "seconds": res["seconds"], "output": _cut(res["output"])}
        hdir = root / ".harness"
        hdir.mkdir(parents=True, exist_ok=True)
        with open(hdir / RUNS_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        for line in res["output"].splitlines()[-40:]:
            job.line(line)
        words = ("The tests passed." if passed else "The tests took too long and were stopped." if res["timed_out"]
                 else f"The tests failed (exit code {res['exit_code']}). The command log has the output.")
        return {"ok": passed, "words": words, **{k: row[k] for k in ("exit_code", "passed", "timed_out", "seconds")}}

    return app.jobs.start("tests", f"run the tests of {root.name}", run, target=str(root)).view()
