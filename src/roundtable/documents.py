"""The owner's own documents: files the agents may look up instead of guessing (wave 7, MD-60).

Kept in ``<app home>/documents/``, on this computer only (never synced):

* ``documents.json`` – the list: ``{id, title, name, kind: file|folder, path?, projects: "all" | [project id],
  private, added_at, size}``. A project id is ``usage.project_id(root)`` (a fingerprint of the path).
* ``files/<id>-<name>`` – a copy of each added file. A linked folder is read where it is, never written.
* ``.removed/`` – a removed document is moved here, with its line in ``removed.json``. Nothing is deleted.

``private`` is the "Never leaves this computer" tick: the owner's own search shows it, and it is never given
to a model (``for_models`` leaves it out; ``recall`` checks again).

Reading, with the standard library only: text, Markdown, HTML (tags taken out), CSV, JSON and Word (.docx,
the text of ``word/document.xml``). A PDF is kept and found by its name: ``attachments.py`` only recognises a
PDF, it does not read its text, and no PDF reader is added here.
"""

from __future__ import annotations

import base64
import binascii
import html
import json
import os
import re
import shutil
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

DIR = "documents"
LIST = "documents.json"
REMOVED = "removed.json"
MAX_BYTES = 20 * 1024 * 1024  # one added file
MAX_TEXT = 400 * 1024  # text read from one file
MAX_FOLDER_FILES = 400  # files read from one linked folder
TEXT_TYPES = {".txt": "Text", ".md": "Markdown", ".markdown": "Markdown", ".html": "Web page", ".htm": "Web page",
              ".csv": "Table", ".json": "Data", ".docx": "Word", ".pdf": "PDF"}
UNREAD = {".pdf"}  # kept and found by name; its text isn't read (see the module's notes)
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
_LOCK = threading.RLock()


class DocumentError(ValueError):
    """Plain words for the owner."""


def home_of(home: str | Path | None = None) -> Path:
    if home is None:
        from .desktop import app_home

        home = app_home()
    return Path(home) / DIR


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [d for d in data if isinstance(d, dict) and d.get("id")] if isinstance(data, list) else []


def _save(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def all_documents(home: str | Path | None = None) -> list[dict[str, Any]]:
    return _load(home_of(home) / LIST)


def removed(home: str | Path | None = None) -> list[dict[str, Any]]:
    return _load(home_of(home) / REMOVED)


def get(home: str | Path | None, doc_id: str) -> dict[str, Any]:
    d = next((x for x in all_documents(home) if x["id"] == doc_id), None)
    if d is None:
        raise DocumentError("That document isn't in your list any more. It may have been removed.")
    return d


def safe_name(name: str) -> str:
    base = Path(str(name or "").replace("\\", "/")).name
    base = re.sub(r"[^\w .()+-]", "_", base).strip(" .")[:120]
    return base or "document.txt"


def _title(name: str) -> str:
    stem = Path(name).stem.replace("_", " ").replace("-", " ").strip()
    return (stem[:1].upper() + stem[1:])[:120] if stem else "A document"


def _projects(value: Any) -> str | list[str]:
    if value in (None, "", "all"):
        return "all"
    if isinstance(value, str):
        value = [value]
    out = [str(v).strip() for v in value if re.fullmatch(r"[0-9a-f]{6,64}", str(v).strip())]
    return list(dict.fromkeys(out))


# -- adding, linking, changing, removing --------------------------------------------------------------------
def add_file(home: str | Path | None, name: str, data: bytes, projects: Any = "all", private: bool = False,
             title: str = "") -> dict[str, Any]:
    """Keep a copy of a dropped file. Raises DocumentError with what to do."""
    name = safe_name(name)
    suffix = Path(name).suffix.lower()
    if suffix not in TEXT_TYPES:
        raise DocumentError("That kind of file can't be read here. Use text, Markdown, a web page, a table (CSV), "
                            "data (JSON), a Word file (.docx) or a PDF.")
    if len(data) > MAX_BYTES:
        raise DocumentError("That file is bigger than 20 MB. Split it, or link the folder it's in instead.")
    base = home_of(home)
    doc_id = "d" + uuid.uuid4().hex[:10]
    with _LOCK:
        files = base / "files"
        files.mkdir(parents=True, exist_ok=True)
        (files / f"{doc_id}-{name}").write_bytes(data)
        item = {"id": doc_id, "title": str(title or "").strip()[:120] or _title(name), "name": name, "kind": "file",
                "projects": _projects(projects), "private": bool(private), "added_at": _now(), "size": len(data)}
        items = all_documents(home)
        items.append(item)
        _save(base / LIST, items)
    return item


def add_upload(home: str | Path | None, name: str, data_b64: str, **kw: Any) -> dict[str, Any]:
    try:
        data = base64.b64decode(str(data_b64 or ""), validate=True)
    except (binascii.Error, ValueError):
        raise DocumentError("The file didn't arrive whole. Drop it on the page again.") from None
    return add_file(home, name, data, **kw)


def link_folder(home: str | Path | None, folder: str | Path, projects: Any = "all", private: bool = False,
                title: str = "") -> dict[str, Any]:
    """Link a folder: its readable files are looked up where they are (read only)."""
    p = Path(str(folder or "")).expanduser()
    if not str(folder or "").strip() or not p.is_dir():
        raise DocumentError("That folder couldn't be found. Check the path and try again.")
    p = p.resolve()
    with _LOCK:
        items = all_documents(home)
        if any(d.get("kind") == "folder" and d.get("path") == str(p) for d in items):
            raise DocumentError("That folder is already linked.")
        item = {"id": "d" + uuid.uuid4().hex[:10], "title": str(title or "").strip()[:120] or _title(p.name),
                "name": p.name, "kind": "folder", "path": str(p), "projects": _projects(projects),
                "private": bool(private), "added_at": _now(), "size": 0}
        items.append(item)
        _save(home_of(home) / LIST, items)
    return item


def change(home: str | Path | None, doc_id: str, **fields: Any) -> dict[str, Any]:
    """Change a document's title, its projects ("all" or ids) or its "Never leaves this computer" tick."""
    with _LOCK:
        items = all_documents(home)
        d = next((x for x in items if x["id"] == doc_id), None)
        if d is None:
            raise DocumentError("That document isn't in your list any more. It may have been removed.")
        if "title" in fields and str(fields["title"] or "").strip():
            d["title"] = str(fields["title"]).strip()[:120]
        if "projects" in fields:
            d["projects"] = _projects(fields["projects"])
        if "private" in fields:
            d["private"] = bool(fields["private"])
        _save(home_of(home) / LIST, items)
    return d


def remove(home: str | Path | None, doc_id: str) -> dict[str, Any]:
    """Move a document aside (its copy to ``.removed/``; a linked folder is only unlinked). Nothing is deleted."""
    base = home_of(home)
    with _LOCK:
        items = all_documents(home)
        d = next((x for x in items if x["id"] == doc_id), None)
        if d is None:
            raise DocumentError("That document isn't in your list any more. It may have been removed.")
        if d.get("kind") == "file":
            src = base / "files" / f"{d['id']}-{d['name']}"
            if src.exists():
                (base / ".removed").mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(base / ".removed" / src.name))
        gone = removed(home)
        gone.append({**d, "removed_at": _now()})
        _save(base / REMOVED, gone)
        _save(base / LIST, [x for x in items if x["id"] != doc_id])
    return d


# -- who may use it --------------------------------------------------------------------------------------------
def for_project(doc: dict[str, Any], project_id: str) -> bool:
    p = doc.get("projects", "all")
    return p == "all" or (isinstance(p, list) and project_id in p)


def for_models(home: str | Path | None, project_id: str | None = None, setting: str = "all") -> list[dict[str, Any]]:
    """Documents a model may be given: never a private one; for a project, only those it may use (its
    ``documents`` setting "none" gives none)."""
    if str(setting or "all") == "none":
        return []
    return [d for d in all_documents(home) if not d.get("private")
            and (project_id is None or for_project(d, project_id))]


# -- reading --------------------------------------------------------------------------------------------------
class _Text(HTMLParser):
    SKIP = {"script", "style", "head", "noscript", "svg"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_text(raw: str) -> str:
    p = _Text()
    try:
        p.feed(raw)
        p.close()
    except Exception:  # noqa: BLE001 - a broken page: whatever was read
        pass
    return re.sub(r"\n\s*\n+", "\n\n", "".join(p.out)).strip()


def docx_text(data: bytes | Path) -> str:
    """The words of a Word file: each paragraph (``w:p``) on its own line, tabs and breaks kept."""
    import io

    try:
        z = zipfile.ZipFile(io.BytesIO(data) if isinstance(data, bytes) else data)
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError, OSError):
        return ""
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    xml = re.sub(r"<w:(br|cr)[^>]*/>", "\n", xml)
    paras = []
    for p in re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", xml, flags=re.S):
        words = "".join(re.findall(r"<w:t(?: [^>]*)?>(.*?)</w:t>", p, flags=re.S))
        paras.append(html.unescape(words))
    return "\n".join(paras).strip()


def read_text(path: Path) -> str:
    """The text of one file ("" for a PDF, a file too big or one that can't be read)."""
    suffix = path.suffix.lower()
    if suffix not in TEXT_TYPES or suffix in UNREAD:
        return ""
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            return ""
        if suffix == ".docx":
            return docx_text(path.read_bytes())[:MAX_TEXT]
        raw = path.read_bytes()[:MAX_TEXT]
    except OSError:
        return ""
    if b"\0" in raw[:4096]:
        return ""
    text = raw.decode("utf-8", errors="replace")
    return html_text(text) if suffix in (".html", ".htm") else text


def files_of(home: str | Path | None, doc: dict[str, Any]) -> list[tuple[str, Path]]:
    """(name shown, file) for a document: its copy, or a linked folder's readable files."""
    base = home_of(home)
    if doc.get("kind") == "file":
        p = base / "files" / f"{doc['id']}-{doc['name']}"
        return [(doc["name"], p)] if p.is_file() else []
    root = Path(str(doc.get("path") or ""))
    if not root.is_dir():
        return []
    out: list[tuple[str, Path]] = []
    for here, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for f in sorted(files):
            full = Path(here) / f
            if full.suffix.lower() in TEXT_TYPES and not full.is_symlink() and not f.startswith("."):
                out.append((full.relative_to(root).as_posix(), full))
                if len(out) >= MAX_FOLDER_FILES:
                    return out
    return out


def stamp(home: str | Path | None, doc: dict[str, Any]) -> str:
    """Changes when the document's files change (their dates and sizes) or its settings do."""
    parts = [json.dumps({k: doc.get(k) for k in ("title", "projects", "private", "path")}, sort_keys=True)]
    for name, p in files_of(home, doc):
        try:
            st = p.stat()
        except OSError:
            continue
        parts.append(f"{name}:{st.st_mtime_ns}:{st.st_size}")
    return "|".join(parts)


def view(home: str | Path | None, doc: dict[str, Any], names: dict[str, str] | None = None) -> dict[str, Any]:
    """A document as the page shows it, with plain words for who may use it."""
    names = names or {}
    p = doc.get("projects", "all")
    who = ("All projects" if p == "all" else
           ", ".join(names.get(x, "a project no longer here") for x in p) if p else "No projects")
    kind = "Folder" if doc.get("kind") == "folder" else TEXT_TYPES.get(Path(doc.get("name", "")).suffix.lower(), "File")
    files = files_of(home, doc)
    unread = [n for n, f in files if f.suffix.lower() in UNREAD]
    note = ("Its words can't be read yet (PDF), so it's found by its name only." if unread and len(unread) == len(files)
            else f"{len(files)} files" if doc.get("kind") == "folder" else "")
    return {**doc, "kind_words": kind, "who": who, "note": note,
            "private_words": "Never leaves this computer" if doc.get("private") else ""}


__all__ = ["DocumentError", "add_file", "add_upload", "all_documents", "change", "docx_text", "files_of",
           "for_models", "for_project", "get", "home_of", "html_text", "link_folder", "read_text", "remove", "removed",
           "stamp", "view"]
