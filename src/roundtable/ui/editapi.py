"""Change a project's files from the app, read its git history, richer previews, and the Browser's addresses.

Editing (desktop only; none of these is a phone route):

    GET  /api/files/edit       ?path=&file= -> {file, name, text, base, eol, git, warn, size}; refused for anything
                               Files wouldn't show, a binary, or a file over ``EDIT_MAX``
    POST /api/files/save       {path, file, text, base, confirm} -> {ok: true, base, commit, kept, words}
                               or {ok: false, conflict: true, theirs, base, words}  (the file changed meanwhile)
                               or {ok: false, needs_confirm: true, words}          (a task is building it)
    GET  /api/files/edits      ?path= -> {edits: [{id, at, file, undone, git}]} the newest hand edits
    POST /api/files/undo_edit  {path, id} -> {ok, words}: the file back as it was before that edit
    GET  /api/files/all        ?path= -> {files: [paths]} every file Files shows (for links in Watch and chat)

Previews and git (reading only; the phone may call log, commit and preview):

    GET  /api/files/preview    ?path=&file= -> {preview, ...}: a notebook, an archive's list, Word, Excel or
                               PowerPoint as text and tables, or {preview: video|audio, src}
    POST /api/files/as_pdf     {path, file} -> the background job making the PDF with LibreOffice;
                               ``/raw/officepdf?path=&file=`` then serves it (``raw_office_pdf``)
    GET  /api/git/log          ?path=&branch=&limit=&skip=
    GET  /api/git/commit       ?path=&sha=
    GET  /api/git/diff         ?path=&sha=&file=
    GET  /api/git/branches     ?path=
    GET  /api/git/compare      ?path=&a=&b=
    GET  /api/git/checkout     ?path=&branch= -> what switching would change, and its ``stamp``
    POST /api/git/checkout     {path, branch, stamp} -> switched, only with a clean tree, nothing running here,
                               no other machine building it, and a snapshot kept first

The Browser (DS-81, the desktop side):

    GET  /api/browser          ?path= -> {local, words, addresses: [{url, frame, from, at}]}: the local web
                               addresses (``localhost``, ``127.0.0.1``) this project's agents and commands printed,
                               newest first, and the App tab's running app. View only: nothing is started and no
                               port is opened; the page shows them in a sandboxed frame.

Saving: only registered projects on this computer, through ``filesapi.safe_file`` (never ``.git``, ``.harness``,
a dot-file or anything that looks like a key); text only, at most ``EDIT_MAX``. ``base`` is the hash of the
text that was opened: when the file changed since, nothing is written and both versions go back. The file's
line endings and byte-order mark are kept. Each save is one commit ("Edited by hand: <file>") of that file
alone (``gitview.commit_file``: a separate index, like ``rewind.snapshot_commit``, but never sweeping in the
owner's other unsaved changes); in a project not kept in git, or a file git ignores, the old text is copied to
``.harness/edits/`` first. Either way the edit can be put back (``undo_edit``), and only while the file is still
as that edit left it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import preview as pv
from ..harness import gitview
from . import filesapi

EDIT_MAX = 1_000_000
ALL_MAX = 5000
EDITS_DIR, EDITS_LOG = "edits", "edits.jsonl"
SKIP_DIRS = {"node_modules", "__pycache__", "build", "dist", "target", "venv"}
URL = re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(?::\d{2,5})?(?:/[^\s\"'<>`)\]]*)?",
                 re.IGNORECASE)
ADDRESSES_MAX = 30
_lock = threading.RLock()


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/files/edit"): lambda q: edit_view(app, q),
        ("POST", "/api/files/save"): lambda body: save(app, body or {}),
        ("GET", "/api/files/edits"): lambda q: edits_view(app, q),
        ("POST", "/api/files/undo_edit"): lambda body: undo(app, body or {}),
        ("GET", "/api/files/all"): lambda q: all_view(app, q),
        ("GET", "/api/files/preview"): lambda q: preview_view(app, q),
        ("POST", "/api/files/as_pdf"): lambda body: as_pdf(app, body or {}),
        ("GET", "/api/git/log"): lambda q: _git(app, q, lambda r: gitview.log(
            r, _first(q, "branch"), _int(q, "limit", 50), _int(q, "skip", 0))),
        ("GET", "/api/git/commit"): lambda q: _git(app, q, lambda r: _mark_private(gitview.commit(r, _first(q, "sha")))),
        ("GET", "/api/git/diff"): lambda q: _git(app, q, lambda r: diff(r, _first(q, "sha"), _first(q, "file"))),
        ("GET", "/api/git/branches"): lambda q: _git(app, q, gitview.branches),
        ("GET", "/api/git/compare"): lambda q: _git(app, q, lambda r: _mark_private(
            gitview.compare(r, _first(q, "a"), _first(q, "b")))),
        ("GET", "/api/git/checkout"): lambda q: _git(app, q, lambda r: _checkout_preview(app, r, _first(q, "branch"))),
        ("POST", "/api/git/checkout"): lambda body: checkout(app, body or {}),
        ("GET", "/api/browser"): lambda q: browser(app, q),
    }


def _first(q: dict, key: str, default: str = "") -> str:
    return filesapi._first(q or {}, key, default)


def _int(q: dict, key: str, default: int) -> int:
    try:
        return int(_first(q, key, str(default)) or default)
    except ValueError:
        return default


def _error(text: str, status: int = 400):
    return filesapi._error(text, status)


def _root(app, q: dict) -> Path:
    root = filesapi._local_root(app, q)
    if root is None:
        raise _error(filesapi.elsewhere(app, q)["words"], 404)
    return Path(root).resolve()


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _busy(app, root: Path) -> bool:
    try:
        return bool(app._busy(root))
    except Exception:  # noqa: BLE001 - can't tell: say busy rather than risk it
        return True


def _elsewhere(app, root: Path) -> str:
    from .rewindapi import elsewhere

    try:
        return elsewhere(app, root)
    except Exception:  # noqa: BLE001
        return ""


# -- opening for editing --------------------------------------------------------------------------------
def _editable(root: Path, rel: str) -> tuple[Path, bytes]:
    f = filesapi.safe_file(root, rel)
    if f is None or not f.is_file():
        raise _error("That file can't be changed: it isn't in the project, or it's one the harness keeps private "
                     "(keys, passwords and its own records).", 404)
    if f.stat().st_size > EDIT_MAX:
        raise _error(f"This file is {filesapi._size(f.stat().st_size)}: too big to change here. Open it with "
                     "another app on this computer.", 413)
    raw = f.read_bytes()
    if filesapi._looks_binary(raw) or not filesapi._utf8(raw):
        raise _error("This file isn't plain text, so it can't be changed here. Open it with another app.", 415)
    return f, raw


def _building(root: Path, rel: str) -> list[str]:
    """Tasks building now that name ``rel`` among the files they change."""
    try:
        from ..harness.orchestrator import Project

        tasks = Project(root).tasks()
    except Exception:  # noqa: BLE001 - no task list: nothing to warn about
        return []
    out = []
    for t in tasks:
        if t.status == "running" and any(str(x).replace("\\", "/").strip("/") == rel for x in (t.files or [])):
            out.append(f"{t.id} {t.title}".strip())
    return out


def _warn(app, root: Path, rel: str) -> str:
    names = _building(root, rel)
    if names:
        return (f"Task {names[0]} is changing this file right now. If you save, it may write over your change, "
                "or yours over its. Save anyway?")
    if _busy(app, root):
        return "The harness is working on this project now. Save anyway? Your change is kept in the history either way."
    return ""


def edit_view(app, q: dict) -> dict[str, Any]:
    root = _root(app, q)
    try:
        rel = gitview.check_file(_first(q, "file"))
    except gitview.GitViewError as e:
        raise _error(str(e), 404) from None
    f, raw = _editable(root, rel)
    text = raw.decode("utf-8")
    return {"file": rel, "name": f.name, "size": len(raw), "base": _hash(raw),
            "text": text[1:] if text.startswith("﻿") else text,
            "eol": "crlf" if b"\r\n" in raw else "lf", "git": _kept_in_git(root, rel), "warn": _warn(app, root, rel),
            "elsewhere": _elsewhere(app, root)}


def _kept_in_git(root: Path, rel: str) -> bool:
    try:
        return gitview.is_repo(root) and not gitview.ignored(root, rel) and gitview.tracked(root, rel)
    except gitview.GitViewError:
        return False


# -- saving -------------------------------------------------------------------------------------------
def _encode(text: str, old: bytes) -> bytes:
    text = text.replace("\r\n", "\n")
    if b"\r\n" in old:
        text = text.replace("\n", "\r\n")
    data = text.encode("utf-8")
    if old.startswith(b"\xef\xbb\xbf") and not data.startswith(b"\xef\xbb\xbf"):
        data = b"\xef\xbb\xbf" + data
    return data


def _write(f: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".rt-save-", dir=str(f.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        try:
            os.chmod(tmp, f.stat().st_mode & 0o7777)
        except OSError:
            pass
        os.replace(tmp, f)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _edits_dir(root: Path) -> Path:
    return root / ".harness" / EDITS_DIR


def _log_rows(root: Path) -> list[dict[str, Any]]:
    p = root / ".harness" / EDITS_LOG
    if not p.is_file():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict):
            rows.append(d)
    return rows


def _log(root: Path, row: dict[str, Any]) -> None:
    p = root / ".harness" / EDITS_LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _keep_copy(root: Path, rel: str, old: bytes, new: bytes) -> str:
    """The old text kept in .harness/edits/ (a project not in git, or a file git ignores); its id."""
    eid = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    d = _edits_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    name = f"{eid}-" + re.sub(r"[^A-Za-z0-9._-]+", "_", rel)[-120:]
    (d / name).write_bytes(old)
    _log(root, {"id": eid, "at": _utc(), "file": rel, "copy": name, "old": _hash(old), "new": _hash(new)})
    return eid


def save(app, body: dict) -> dict[str, Any]:
    root = _root(app, body)
    try:
        rel = gitview.check_file(_first(body, "file"))
    except gitview.GitViewError as e:
        raise _error(str(e), 404) from None
    text = body.get("text")
    if not isinstance(text, str):
        raise _error("Nothing to save: the file's text is missing.")
    if "\x00" in text:
        raise _error("This text has a character that can't go in a text file. Take it out and save again.", 415)
    away = _elsewhere(app, root)
    if away:
        raise _error(away, 409)
    with _lock:
        f, old = _editable(root, rel)
        if _first(body, "base") != _hash(old):
            theirs = old.decode("utf-8")
            return {"ok": False, "conflict": True, "base": _hash(old),
                    "theirs": theirs[1:] if theirs.startswith("﻿") else theirs,
                    "words": "This file changed while you were editing. Both versions are below: keep yours, "
                             "keep the new one, or copy what you need from it."}
        warn = _warn(app, root, rel)
        if warn and not body.get("confirm"):
            return {"ok": False, "needs_confirm": True, "words": warn}
        data = _encode(text, old)
        if len(data) > EDIT_MAX:
            raise _error("This text is too long to save here (over 1 MB). Open the file with another app.", 413)
        if data == old:
            return {"ok": True, "base": _hash(old), "commit": "", "kept": "", "words": "Nothing had changed."}
        git = _kept_in_git(root, rel)
        kept = "" if git else _keep_copy(root, rel, old, data)
        _write(f, data)
        sha = ""
        if git:
            try:
                sha = gitview.commit_file(root, rel)
            except gitview.GitViewError as e:  # the file is saved: keep the old text the other way, and say so
                kept = _keep_copy(root, rel, old, data)
                return {"ok": True, "base": _hash(data), "commit": "", "kept": kept,
                        "words": f"Saved. {e} The old text is kept, so it can still be put back."}
    return {"ok": True, "base": _hash(data), "commit": sha, "kept": kept,
            "words": "Saved. You can put it back from Your edits." if sha or kept else "Saved."}


# -- your edits, and putting one back ------------------------------------------------------------------
def edits(root: Path, limit: int = 30) -> list[dict[str, Any]]:
    rows = [{"id": r["sha"], "at": r["at"], "file": r["file"], "undone": r["undone"], "git": True}
            for r in gitview.hand_edits(root, limit)] if gitview.is_repo(root) else []
    log = _log_rows(root)
    put_back = {r.get("of") for r in log if r.get("kind") == "put_back"}
    for r in log:
        if r.get("kind") == "put_back":
            continue
        rows.append({"id": r.get("id"), "at": r.get("at"), "file": r.get("file"), "undone": r.get("id") in put_back,
                     "git": False})
    rows.sort(key=lambda r: r.get("at") or "", reverse=True)
    return rows[:limit]


def edits_view(app, q: dict) -> dict[str, Any]:
    root = _root(app, q)
    return {"edits": edits(root)}


def undo(app, body: dict) -> dict[str, Any]:
    root = _root(app, body)
    eid = _first(body, "id")
    away = _elsewhere(app, root)
    if away:
        raise _error(away, 409)
    with _lock:
        if gitview.SHA.match(eid.lower()) and gitview.is_repo(root):
            try:
                return gitview.undo_edit(root, eid)
            except gitview.GitViewError as e:
                raise _error(str(e), 409) from None
        row = next((r for r in _log_rows(root) if r.get("id") == eid and r.get("kind") != "put_back"), None)
        if row is None or not re.fullmatch(r"[0-9TZ]+", eid or ""):
            raise _error("That edit isn't in this project's list any more.", 404)
        if any(r.get("kind") == "put_back" and r.get("of") == eid for r in _log_rows(root)):
            raise _error("That edit has already been put back.", 409)
        f = filesapi.safe_file(root, str(row.get("file") or ""))
        copy = _edits_dir(root) / str(row.get("copy") or "")
        if f is None or not copy.is_file() or copy.parent != _edits_dir(root):
            raise _error("The old text of that edit can't be found any more.", 404)
        if not f.is_file() or _hash(f.read_bytes()) != row.get("new"):
            raise _error("This file has changed since that edit, so putting it back would lose the newer changes. "
                         "Open the file and change it by hand instead.", 409)
        _write(f, copy.read_bytes())
        _log(root, {"kind": "put_back", "of": eid, "at": _utc(), "file": row.get("file")})
    return {"ok": True, "file": row.get("file"), "words": f"{row.get('file')} is back as it was before that edit."}


# -- every file, for links -------------------------------------------------------------------------------
def all_files(root: Path) -> list[str]:
    base = Path(root).resolve()
    out: list[str] = []
    for here, dirs, files in os.walk(base, followlinks=False):
        rel_here = Path(here).relative_to(base)
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS
                         and not filesapi.is_secret(d, True))
        for name in sorted(files):
            if name.startswith(".") or filesapi.is_secret(name) or Path(here, name).is_symlink():
                continue
            out.append((rel_here / name).as_posix())
            if len(out) >= ALL_MAX:
                return out
    return out


def all_view(app, q: dict) -> dict[str, Any]:
    root = _root(app, q)
    files = all_files(root)
    return {"files": files, "more": len(files) >= ALL_MAX}


# -- rich previews ----------------------------------------------------------------------------------------
PREVIEW_MAX = 50_000_000  # an office file or notebook bigger than this isn't opened


def preview_view(app, q: dict) -> dict[str, Any]:
    root = _root(app, q)
    rel = _first(q, "file")
    f = filesapi.safe_file(root, rel)
    if f is None or not f.is_file():
        raise _error("That file can't be opened: it isn't in the project, or it's one the harness keeps private.", 404)
    kind = pv.kind(f.name)
    out: dict[str, Any] = {"file": rel.replace("\\", "/").strip("/"), "name": f.name, "size": f.stat().st_size,
                           "preview": kind, "words": ""}
    try:
        if kind in ("video", "audio"):
            out["mime"] = pv.media_type(f.name)
        elif kind == "archive":
            out.update(pv.archive(f))
        elif out["size"] > PREVIEW_MAX:
            out["words"] = f"This file is {filesapi._size(out['size'])}: too big to show here. Save a copy to open it."
        elif kind == "notebook":
            out.update(pv.notebook(f.read_bytes()))
        elif kind == "office":
            out.update(pv.office(f))
            out["can_pdf"] = bool(pv.libreoffice())
            out["pdf_words"] = "" if out["can_pdf"] else (
                "This is a simple view. Install LibreOffice from the Tools page to see the file exactly, as a PDF.")
        else:
            out["words"] = "There's no richer view of this file."
    except pv.PreviewError as e:
        out["words"] = str(e)
        out["failed"] = True
    return out


def _pdf_cache() -> Path:
    return Path(tempfile.gettempdir()) / "rt-officepdf"


def _pdf_for(f: Path) -> Path:
    return _pdf_cache() / (_hash(f.read_bytes()) + ".pdf")


def as_pdf(app, body: dict) -> dict[str, Any]:
    root = _root(app, body)
    rel = _first(body, "file")
    f = filesapi.safe_file(root, rel)
    if f is None or not f.is_file() or pv.kind(f.name) != "office":
        raise _error("Only a Word, Excel or PowerPoint file in the project can be opened as a PDF.", 404)
    soffice = pv.libreoffice()
    if not soffice:
        raise _error("LibreOffice isn't on this computer. Install it from the Tools page, then try again.", 409)

    def run(job) -> dict[str, Any]:
        out = _pdf_for(f)
        if not out.is_file():
            job.line(f"Making a PDF of {f.name} with LibreOffice…")
            pv.to_pdf(f, out, soffice)
        return {"ok": True, "words": "The PDF is ready.", "file": rel}

    return app.jobs.start("pdf", f"open {f.name} as a PDF", run).view()


def raw_office_pdf(app, q: dict) -> tuple[bytes, str, dict[str, str]]:
    """/raw/officepdf: the PDF "Open as PDF" made, for the browser's own viewer."""
    root = filesapi._local_root(app, q)
    f = filesapi.safe_file(root, _first(q, "file")) if root is not None else None
    if f is None or not f.is_file():
        raise FileNotFoundError("that file isn't there, or the harness keeps it private")
    pdf = _pdf_for(f)
    if not pdf.is_file():
        raise FileNotFoundError("the PDF hasn't been made yet: press Open as PDF")
    return filesapi.raw_answer(pdf)


# -- git ----------------------------------------------------------------------------------------------------
def _private(path: str) -> bool:
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    return (not parts or filesapi.is_secret(parts[-1]) or any(filesapi.is_secret(p, True) for p in parts[:-1])
            or any(p in (".harness", ".git") or p.startswith(".env") for p in parts))


def _mark_private(d: dict[str, Any]) -> dict[str, Any]:
    for f in d.get("files") or []:
        f["private"] = _private(f.get("path", ""))
    return d


def diff(root: Path, sha: str, file: str) -> dict[str, Any]:
    if _private(file):
        raise gitview.GitViewError("That file is one the harness keeps private (keys, passwords and its own "
                                   "records), so its changes aren't shown.")
    return gitview.diff(root, sha, file)


def _git(app, q: dict, fn) -> dict[str, Any]:
    root = _root(app, q)
    try:
        return {"path": str(root), **fn(root)}
    except gitview.GitViewError as e:
        raise _error(str(e)) from None


def _checkout_block(app, root: Path) -> str:
    if _busy(app, root):
        return "The harness is working on this project right now. Wait for it to finish or stop it, then switch."
    return _elsewhere(app, root)


def _checkout_preview(app, root: Path, branch: str) -> dict[str, Any]:
    out = _mark_private(gitview.checkout_preview(root, branch))
    block = _checkout_block(app, root)
    if block:
        out.update(blocked=block, words=block, stamp="")
    return out


def checkout(app, body: dict) -> dict[str, Any]:
    root = _root(app, body)
    block = _checkout_block(app, root)
    if block:
        raise _error(block, 409)
    with _lock:
        try:
            return gitview.checkout(root, _first(body, "branch"), _first(body, "stamp"))
        except gitview.GitViewError as e:
            raise _error(str(e), 409) from None


# -- the Browser ----------------------------------------------------------------------------------------------
def frame_url(url: str) -> str:
    """The address the page's frame opens: loopback names become 127.0.0.1 (the only local origin the page may
    show in a frame), anything else ""."""
    m = re.match(r"(?i)^(https?)://(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:\d{2,5})?(/.*)?$", url.strip())
    if not m:
        return ""
    port = m.group(3) or ""
    if port and not (0 < int(port[1:]) < 65536):
        return ""
    return f"{m.group(1).lower()}://127.0.0.1{port}{m.group(4) or '/'}"


def addresses_in(text: str) -> list[str]:
    seen: list[str] = []
    for u in URL.findall(text or ""):
        u = u.rstrip(".,;:!?")
        if u not in seen:
            seen.append(u)
    return seen


def addresses(root: Path, running: str = "") -> list[dict[str, Any]]:
    """Local addresses printed in this project's records, newest first, the running app first of all."""
    found: dict[str, dict[str, Any]] = {}

    def add(url: str, where: str, at: str) -> None:
        frame = frame_url(url)
        if not frame:
            return
        row = found.get(frame)
        if row is None or (at or "") > (row.get("at") or ""):
            found[frame] = {"url": url, "frame": frame, "from": where, "at": at or ""}

    hdir = Path(root) / ".harness"
    for d in filesapi._rows(hdir / "events.jsonl", 5_000_000):
        text = " ".join(str(d.get(k) or "") for k in ("output", "result", "text", "summary", "message"))
        if "http" not in text:
            continue
        who = f"task {d.get('task')}" if d.get("task") else "the harness"
        for u in addresses_in(text):
            add(u, who, str(d.get("at") or ""))
    for d in filesapi._rows(hdir / filesapi.RUNS_FILE):
        for u in addresses_in(str(d.get("output") or "")):
            add(u, "your test run", str(d.get("at") or ""))
    rows = sorted(found.values(), key=lambda r: r["at"], reverse=True)
    if running and frame_url(running):
        rows = [r for r in rows if r["frame"] != frame_url(running)]
        rows.insert(0, {"url": running, "frame": frame_url(running), "from": "the App tab (running now)", "at": ""})
    return rows[:ADDRESSES_MAX]


def browser(app, q: dict) -> dict[str, Any]:
    root = _root(app, q)
    running = ""
    try:
        from . import appapi

        v = appapi._state(root)  # not view_of: a look from the Browser must not keep the app alive
        running = str(v.get("url") or "") if v.get("running") else ""
    except Exception:  # noqa: BLE001 - no App tab: the printed addresses only
        running = ""
    local = bool(getattr(app, "local_only", True))
    words = "" if local else ("These addresses are on the computer the harness runs on, so they can't be opened "
                              "from here. Open them in the app on that computer.")
    return {"local": local, "words": words, "addresses": addresses(root, running)}


__all__ = ["addresses", "addresses_in", "all_files", "browser", "edits", "frame_url", "raw_office_pdf", "routes",
           "save"]
