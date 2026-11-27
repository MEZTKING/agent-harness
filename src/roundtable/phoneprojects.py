"""Projects on the phone (DS-55, "This phone" only): clone a repository, import a folder or a zip picked with the
phone's file picker, and share a project as a zip through the phone's share sheet.

Three routes, served by ``onphone.LocalAccess.local_api`` (hook-up: ``routes``):

- ``POST /api/projects/clone`` ``{url, name?, use_key?}``: ``git clone`` an https address into the projects folder.
  A private repository uses the phone's own project key (``PROJECT_GIT_KEY``, saved through the phone's key form),
  never the hub's token; the key travels to git through the environment only (``onphone.git_auth_env``).
- ``POST /api/projects/import``: a zip in parts (the phone server takes at most 2 MB a request).
  ``{upload, index, data}`` adds part ``index`` (base64); ``{upload, name, done: true}`` unpacks it as a new
  project. A folder picked on the phone is zipped by the app first, so both come the same way. Refused: a name
  with ``..`` or an absolute path, a link, more than ``MAX_FILES`` files, more than ``MAX_BYTES`` unpacked, and a
  name that is already a project (never over an existing one).
- ``GET /api/projects/share?name=``: zips the project (without ``.harness``, ``.git`` and anything
  ``filesapi.is_secret`` catches) and answers ``{id, size, parts}``; ``?id=&index=`` answers ``{data}`` for one part.
"""

from __future__ import annotations

import base64
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import urlparse

from .ui.filesapi import is_secret

PROJECT_GIT_KEY = "ROUNDTABLE_PROJECT_GIT_TOKEN"
PART = 1_000_000  # bytes per part before base64 (the phone server's body limit is 2 MB)
MAX_BYTES = 500 * 1024 * 1024  # unpacked, per import
MAX_UPLOAD = 300 * 1024 * 1024  # the zip itself
MAX_FILES = 20_000
NEVER_SHARED = {".harness", ".git"}
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}$")
_ID = re.compile(r"^[a-f0-9]{16,64}$")


class ProjectError(ValueError):
    """A refusal, in plain words for the owner (the phone shows it as it is)."""


def project_name(name: str) -> str:
    """A project folder name the owner typed or a repository gave: letters, digits, spaces, dots, dashes."""
    n = " ".join(str(name or "").split()).strip().removesuffix(".git").removesuffix(".zip")
    if not _NAME.match(n) or n in (".", "..") or ".." in n:
        raise ProjectError("Give the project a short name with letters and numbers only.")
    return n


def _target(projects: Path, name: str) -> Path:
    n = project_name(name)
    target = Path(projects) / n
    if target.exists():
        raise ProjectError(f"There's already a project called {n}. Pick another name.")
    return target


# -- clone ----------------------------------------------------------------------------------------------------
def clone(projects: Path, url: str, name: str = "", token: str = "", run: Callable = subprocess.run) -> dict[str, Any]:
    """Clone ``url`` (https only) as a new project. ``token`` is the phone's project key, or empty for a public one."""
    from .onphone import git_auth_env

    url = (url or "").strip()
    u = urlparse(url)
    if u.scheme != "https" or not u.hostname or u.username or u.password:
        raise ProjectError("Paste the repository's https address, for example https://github.com/you/game.")
    target = _target(projects, name or PurePosixPath(u.path).name)
    Path(projects).mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **(git_auth_env(url, token) if token else {"GIT_TERMINAL_PROMPT": "0"})}
    res = run(["git", "clone", "--", url, str(target)], capture_output=True, text=True, timeout=900, env=env)
    if res.returncode != 0:
        shutil.rmtree(target, ignore_errors=True)
        private = "authentication" in (res.stderr or "").lower() or "could not read" in (res.stderr or "").lower()
        raise ProjectError("Couldn't get it: the repository is private. Save a project key in Settings, Keys, then try again."
                           if private and not token else
                           "Couldn't get the repository. Check the address" + (" and that the key can read it." if token else "."))
    return {"name": target.name, "path": str(target)}


# -- import ---------------------------------------------------------------------------------------------------
def _uploads(home: Path) -> Path:
    d = Path(home) / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def add_part(home: Path, upload: str, index: int, data: str) -> dict[str, Any]:
    """Part ``index`` of an upload, in order (a part sent again replaces nothing: it must be the next one)."""
    if not _ID.match(str(upload or "")):
        raise ProjectError("That upload isn't known. Start the import again.")
    raw = base64.b64decode(data or "", validate=True)
    if len(raw) > PART:
        raise ProjectError("That part is too big. Start the import again.")
    f = _uploads(home) / f"{upload}.zip"
    size = f.stat().st_size if f.exists() else 0
    if size % PART != 0 or int(index) != size // PART:  # every part before this one full, and in order
        raise ProjectError("A part went missing. Start the import again.")
    if size + len(raw) > MAX_UPLOAD:
        f.unlink(missing_ok=True)
        raise ProjectError(f"That's too big to import (more than {MAX_UPLOAD // (1024 * 1024)} MB).")
    with f.open("ab") as out:
        out.write(raw)
    return {"upload": upload, "size": size + len(raw)}


def new_upload() -> str:
    return secrets.token_hex(16)


def unpack(projects: Path, name: str, zip_path: Path, max_bytes: int = MAX_BYTES, max_files: int = MAX_FILES) -> dict[str, Any]:
    """Unpack ``zip_path`` as the new project ``name``, checking every entry first; nothing is written on a refusal."""
    target = _target(projects, name)
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError):
        raise ProjectError("That file isn't a zip the phone can open.") from None
    with zf:
        infos = zf.infolist()
        if len(infos) > max_files:
            raise ProjectError(f"That has too many files (more than {max_files}).")
        total = 0
        names = []
        for i in infos:
            p = PurePosixPath(i.filename.replace("\\", "/"))
            if i.filename.startswith(("/", "\\")) or p.is_absolute() or ".." in p.parts or (p.parts and ":" in p.parts[0]):
                raise ProjectError("That zip has a file that points outside the project, so it wasn't used.")
            if stat.S_ISLNK(i.external_attr >> 16):
                raise ProjectError("That zip has a link in it, so it wasn't used.")
            total += i.file_size
            if total > max_bytes:
                raise ProjectError(f"That's too big to import (more than {max_bytes // (1024 * 1024)} MB unpacked).")
            names.append(p)
        # One folder holding everything (how a zipped folder usually looks): its contents become the project.
        tops = {n.parts[0] for n in names if n.parts}
        strip = 1 if len(tops) == 1 and all(len(n.parts) > 1 or i.is_dir() for n, i in zip(names, infos)) else 0
        Path(projects).mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".import-", dir=projects))
        try:
            for n, i in zip(names, infos):
                parts = n.parts[strip:]
                if not parts:
                    continue
                out = staging.joinpath(*parts)
                if i.is_dir():
                    out.mkdir(parents=True, exist_ok=True)
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(i) as src, out.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            if target.exists():  # made meanwhile
                raise ProjectError(f"There's already a project called {target.name}. Pick another name.")
            staging.rename(target)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    return {"name": target.name, "path": str(target), "files": sum(1 for i in infos if not i.is_dir())}


def finish_import(home: Path, projects: Path, upload: str, name: str) -> dict[str, Any]:
    if not _ID.match(str(upload or "")):
        raise ProjectError("That upload isn't known. Start the import again.")
    f = _uploads(home) / f"{upload}.zip"
    if not f.exists():
        raise ProjectError("Nothing arrived for that import. Start it again.")
    try:
        return unpack(projects, name, f)
    finally:
        f.unlink(missing_ok=True)


# -- share ----------------------------------------------------------------------------------------------------
def shared_files(root: Path) -> list[Path]:
    """The files a shared zip holds: never ``.harness``, ``.git``, a link or a secret-named file or folder."""
    root = Path(root)
    out = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in NEVER_SHARED and not is_secret(d, True)
                             and not (Path(dirpath) / d).is_symlink())
        for f in sorted(filenames):
            p = Path(dirpath) / f
            if not is_secret(f) and not p.is_symlink() and p.is_file():
                out.append(p)
    return out


def share_zip(projects: Path, name: str, out: Path) -> Path:
    root = Path(projects) / project_name(name)
    if not root.is_dir():
        raise ProjectError("That project isn't on this phone.")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in shared_files(root):
            zf.write(p, f"{root.name}/{p.relative_to(root).as_posix()}")
    return out


def start_share(home: Path, projects: Path, name: str) -> dict[str, Any]:
    sid = new_upload()
    f = share_zip(projects, name, _uploads(home) / f"share-{sid}.zip")
    size = f.stat().st_size
    return {"id": sid, "name": project_name(name), "size": size, "parts": max(1, (size + PART - 1) // PART)}


def share_part(home: Path, sid: str, index: int) -> dict[str, Any]:
    if not _ID.match(str(sid or "")):
        raise ProjectError("That share isn't known. Share the project again.")
    f = _uploads(home) / f"share-{sid}.zip"
    if not f.exists():
        raise ProjectError("That share has gone. Share the project again.")
    size = f.stat().st_size
    parts = max(1, (size + PART - 1) // PART)
    index = int(index)
    if not 0 <= index < parts:
        raise ProjectError("That part isn't there. Share the project again.")
    with f.open("rb") as src:
        src.seek(index * PART)
        data = src.read(PART)
    if index == parts - 1:
        f.unlink(missing_ok=True)  # the last part read: nothing stays behind
    return {"index": index, "parts": parts, "data": base64.b64encode(data).decode()}


# -- the routes -----------------------------------------------------------------------------------------------
def routes(home: Path, projects: Path, key: Callable[[str], str | None], method: str, path: str, q: dict,
           body: dict, run: Callable = subprocess.run) -> tuple[bool, Any]:
    """``(handled, answer)`` for the three project routes; ``key(name)`` reads the phone's key store."""
    def one(k: str) -> str:
        v = q.get(k) or [""]
        return v[0] if isinstance(v, list) else str(v)

    if (method, path) == ("POST", "/api/projects/clone"):
        token = (key(PROJECT_GIT_KEY) or "") if body.get("use_key") else ""
        return True, clone(projects, str(body.get("url") or ""), str(body.get("name") or ""), token, run=run)
    if (method, path) == ("POST", "/api/projects/import"):
        if body.get("done"):
            return True, finish_import(home, projects, str(body.get("upload") or ""), str(body.get("name") or ""))
        if not body.get("upload"):
            return True, {"upload": new_upload(), "part": PART}
        return True, add_part(home, str(body.get("upload")), int(body.get("index") or 0), str(body.get("data") or ""))
    if (method, path) == ("GET", "/api/projects/share"):
        if one("id"):
            return True, share_part(home, one("id"), int(one("index") or 0))
        return True, start_share(home, projects, one("name"))
    return False, None
