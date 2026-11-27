"""Richer previews for the Files tab (DS-50, DS-54), with the standard library only. Nothing here runs,
unpacks or fetches anything.

* ``notebook(data)`` – a Jupyter notebook's cells (Markdown, code, raw) and their kept outputs: text, errors and
  PNG or JPEG pictures from the file itself. HTML, JavaScript and SVG outputs are shown as their plain-text
  form only, never as a page. The notebook is never run.
* ``archive(path)`` – the names and sizes inside a ``.zip`` (and ``.jar``, ``.apk``, ``.whl``, ``.aar``) or a
  ``.tar`` (plain or compressed). Never unpacked: a name that would land outside the folder (``../``, an
  absolute path) is listed and marked, and nothing is ever written.
* ``docx(data)``, ``xlsx(data)``, ``pptx(data)`` – Word as headings, paragraphs (bold and italic), lists and
  tables; Excel as one table per sheet (the first ``ROWS`` rows); PowerPoint as each slide's text. Macros,
  embedded objects and outside links are ignored. The page draws the result with text nodes only.
* ``libreoffice()`` / ``to_pdf`` – "Open as PDF" where LibreOffice is on this computer: the file is copied
  to a temporary folder and converted there with the clean environment (no keys) and a profile of its own,
  so an open LibreOffice isn't disturbed.

``kind(name)`` says which of these a file has: notebook, archive, office, video or audio ("" for none).
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from xml.etree import ElementTree as ET

ROWS, COLS = 500, 60
CELLS_MAX = 400
OUTPUT_TEXT_MAX = 20_000
PICTURE_MAX = 3_000_000  # bytes of one picture in a notebook's output
ENTRIES_MAX = 2000
MEMBER_MAX = 30_000_000  # an office file's part bigger than this (unpacked) is not read: a zip bomb
PDF_TIMEOUT = 120.0

NOTEBOOKS = {".ipynb"}
ZIPS = {".zip", ".jar", ".apk", ".whl", ".aar", ".war", ".nupkg", ".vsix", ".xpi"}
TARS = (".tar", ".tgz", ".tar.gz", ".tbz2", ".tar.bz2", ".txz", ".tar.xz")
OFFICE = {".docx", ".xlsx", ".pptx"}
VIDEO = {".mp4": "video/mp4", ".webm": "video/webm", ".ogv": "video/ogg", ".m4v": "video/mp4", ".mov": "video/quicktime"}
AUDIO = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".m4a": "audio/mp4",
         ".flac": "audio/flac", ".aac": "audio/aac", ".opus": "audio/ogg"}


class PreviewError(ValueError):
    """Plain words for the owner."""


def kind(name: str) -> str:
    low = name.lower()
    ext = PurePosixPath(low).suffix
    if ext in NOTEBOOKS:
        return "notebook"
    if ext in ZIPS or low.endswith(TARS):
        return "archive"
    if ext in OFFICE:
        return "office"
    if ext in VIDEO:
        return "video"
    if ext in AUDIO:
        return "audio"
    return ""


def media_type(name: str) -> str:
    ext = PurePosixPath(name.lower()).suffix
    return VIDEO.get(ext) or AUDIO.get(ext) or ""


# -- notebooks --------------------------------------------------------------------------------------
def _joined(v: Any) -> str:
    return "".join(v) if isinstance(v, list) else str(v or "")


def _cut(text: str, n: int = OUTPUT_TEXT_MAX) -> str:
    return text if len(text) <= n else text[:n] + "\n…"


_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _output(o: dict[str, Any]) -> dict[str, Any] | None:
    t = o.get("output_type")
    if t == "stream":
        return {"kind": "text", "text": _cut(_joined(o.get("text"))), "stream": o.get("name", "stdout")}
    if t == "error":
        tb = "\n".join(_ANSI.sub("", str(x)) for x in (o.get("traceback") or []))
        return {"kind": "error", "text": _cut(tb or f"{o.get('ename', '')}: {o.get('evalue', '')}")}
    if t in ("execute_result", "display_data"):
        data = o.get("data") or {}
        for mime in ("image/png", "image/jpeg", "image/gif"):
            if mime in data:
                raw = _joined(data[mime]).replace("\n", "")
                try:
                    if len(base64.b64decode(raw, validate=True)) <= PICTURE_MAX:
                        return {"kind": "image", "mime": mime, "data": raw}
                except ValueError:
                    pass
                return {"kind": "text", "text": "(a picture too big to show here)"}
        if "text/plain" in data:
            return {"kind": "text", "text": _cut(_joined(data["text/plain"]))}
        if data:
            return {"kind": "text", "text": "(output that only shows when the notebook is run: "
                    + ", ".join(sorted(data)) + ")"}
    return None


def notebook(data: bytes) -> dict[str, Any]:
    try:
        nb = json.loads(data.decode("utf-8", "replace"))
    except ValueError:
        raise PreviewError("This notebook has a mistake in it, so it's shown as plain text.") from None
    if not isinstance(nb, dict):
        raise PreviewError("This doesn't look like a notebook, so it's shown as plain text.")
    cells_in = nb.get("cells")
    if cells_in is None:  # the old format (version 3): cells inside worksheets
        cells_in = [c for w in nb.get("worksheets") or [] for c in (w.get("cells") or [])]
    meta = nb.get("metadata") or {}
    lang = ((meta.get("language_info") or {}).get("name") or (meta.get("kernelspec") or {}).get("language")
            or "python")
    cells = []
    for c in (cells_in or [])[:CELLS_MAX]:
        if not isinstance(c, dict):
            continue
        ctype = c.get("cell_type") if c.get("cell_type") in ("markdown", "code", "raw") else "raw"
        outs = [x for x in (_output(o) for o in (c.get("outputs") or []) if isinstance(o, dict)) if x]
        cells.append({"type": ctype, "source": _cut(_joined(c.get("source", c.get("input", ""))), 200_000),
                      "count": c.get("execution_count"), "outputs": outs})
    return {"language": str(lang).lower(), "cells": cells, "more": max(0, len(cells_in or []) - CELLS_MAX)}


# -- archives ----------------------------------------------------------------------------------------
def _unsafe(name: str) -> bool:
    n = name.replace("\\", "/")
    return n.startswith("/") or bool(re.match(r"^[A-Za-z]:", n)) or ".." in PurePosixPath(n).parts


def archive(path: Path) -> dict[str, Any]:
    """The names and sizes inside, read from the archive's own list. Nothing is unpacked or written."""
    path = Path(path)
    rows: list[dict[str, Any]] = []
    total = count = 0
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    count += 1
                    total += info.file_size
                    if len(rows) < ENTRIES_MAX:
                        rows.append({"name": info.filename, "size": info.file_size, "packed": info.compress_size,
                                     "folder": info.is_dir(), "unsafe": _unsafe(info.filename)})
            fmt = "zip"
        elif tarfile.is_tarfile(path):
            with tarfile.open(path, "r:*") as t:
                for m in t:
                    count += 1
                    total += m.size if m.isfile() else 0
                    if len(rows) < ENTRIES_MAX:
                        rows.append({"name": m.name, "size": m.size if m.isfile() else 0, "folder": m.isdir(),
                                     "link": m.issym() or m.islnk(), "unsafe": _unsafe(m.name)
                                     or ((m.issym() or m.islnk()) and _unsafe(m.linkname))})
            fmt = "tar"
        else:
            raise PreviewError("This archive can't be read: it may be damaged or a kind the harness doesn't know.")
    except (OSError, zipfile.BadZipFile, tarfile.TarError, EOFError) as e:
        raise PreviewError(f"This archive can't be read ({e}). It may be damaged.") from None
    unsafe = sum(1 for r in rows if r["unsafe"])
    return {"format": fmt, "entries": rows, "count": count, "total": total, "more": max(0, count - len(rows)),
            "unsafe": unsafe}


# -- office files --------------------------------------------------------------------------------------
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _zip(data: bytes | Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(data) if isinstance(data, (bytes, bytearray)) else data)
    except (zipfile.BadZipFile, OSError):
        raise PreviewError("This file can't be read: it may be damaged, or saved by an old program. "
                           "Save a copy to open it with another app.") from None


def _xml(z: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MEMBER_MAX:
        raise PreviewError("This file is too big inside to show here. Save a copy to open it with another app.")
    raw = z.read(info)
    if b"<!DOCTYPE" in raw[:2000] or b"<!ENTITY" in raw[:4000]:
        raise PreviewError("This file has something unusual inside, so it isn't shown. Save a copy to open it.")
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        raise PreviewError("This file has a mistake inside, so it can't be shown here.") from None


def _rels(z: zipfile.ZipFile, name: str) -> dict[str, str]:
    """A part's relationships: id -> the target's path inside the zip (outside links left out)."""
    base = PurePosixPath(name).parent
    rel = _xml(z, str(base / "_rels" / (PurePosixPath(name).name + ".rels")))
    out: dict[str, str] = {}
    for r in (rel if rel is not None else []):
        if r.get("TargetMode") == "External":
            continue
        target = str(r.get("Target") or "")
        full = target.lstrip("/") if target.startswith("/") else os.path.normpath(str(base / target)).replace("\\", "/")
        out[str(r.get("Id"))] = full
    return out


def _runs(p: ET.Element) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in p.iter(f"{W}r"):
        rp = r.find(f"{W}rPr")
        bold = rp is not None and rp.find(f"{W}b") is not None and rp.find(f"{W}b").get(f"{W}val") not in ("0", "false")
        ital = rp is not None and rp.find(f"{W}i") is not None and rp.find(f"{W}i").get(f"{W}val") not in ("0", "false")
        text = ""
        for el in r:
            if el.tag == f"{W}t":
                text += el.text or ""
            elif el.tag == f"{W}tab":
                text += "\t"
            elif el.tag in (f"{W}br", f"{W}cr"):
                text += "\n"
        if not text:
            continue
        if out and out[-1]["bold"] == bold and out[-1]["italic"] == ital:
            out[-1]["text"] += text
        else:
            out.append({"text": text, "bold": bold, "italic": ital})
    return out


def _para_text(p: ET.Element) -> str:
    return "".join(r["text"] for r in _runs(p))


def docx(data: bytes | Path) -> dict[str, Any]:
    z = _zip(data)
    doc = _xml(z, "word/document.xml")
    if doc is None:
        raise PreviewError("This Word file has no text part, so there's nothing to show.")
    body = doc.find(f"{W}body")
    blocks: list[dict[str, Any]] = []
    for el in (body if body is not None else []):
        if el.tag == f"{W}p":
            ppr = el.find(f"{W}pPr")
            style = ""
            listed = False
            if ppr is not None:
                ps = ppr.find(f"{W}pStyle")
                style = str(ps.get(f"{W}val") or "") if ps is not None else ""
                listed = ppr.find(f"{W}numPr") is not None
            runs = _runs(el)
            if not runs:
                continue
            m = re.match(r"(?i)^heading\s*(\d)$", style)
            if m or style.lower() == "title":
                blocks.append({"type": "heading", "level": int(m.group(1)) if m else 1, "text": _para_text(el)})
            elif listed or style.lower().startswith("list"):
                ordered = "number" in style.lower()
                if blocks and blocks[-1]["type"] == "list":
                    blocks[-1]["items"].append(runs)
                else:
                    blocks.append({"type": "list", "ordered": ordered, "items": [runs]})
            else:
                blocks.append({"type": "para", "runs": runs})
        elif el.tag == f"{W}tbl":
            rows = []
            for tr in el.iter(f"{W}tr"):
                rows.append(["\n".join(_para_text(p) for p in tc.iter(f"{W}p")) for tc in tr.iter(f"{W}tc")][:COLS])
                if len(rows) >= ROWS:
                    break
            blocks.append({"type": "table", "rows": rows})
    return {"office": "docx", "blocks": blocks}


def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]*", ref.upper()).group(0):
        n = n * 26 + (ord(ch) - 64)
    return max(0, n - 1)


def xlsx(data: bytes | Path) -> dict[str, Any]:
    z = _zip(data)
    wb = _xml(z, "xl/workbook.xml")
    if wb is None:
        raise PreviewError("This Excel file has no sheets part, so there's nothing to show.")
    rels = _rels(z, "xl/workbook.xml")
    shared: list[str] = []
    sst = _xml(z, "xl/sharedStrings.xml")
    for si in (sst if sst is not None else []):
        shared.append("".join(t.text or "" for t in si.iter(f"{S}t")))
    sheets = []
    for sh in wb.iter(f"{S}sheet"):
        part = rels.get(str(sh.get(f"{R}id")), "")
        root = _xml(z, part) if part else None
        rows: list[list[str]] = []
        cut = False
        for row in (root.iter(f"{S}row") if root is not None else []):
            if len(rows) >= ROWS:
                cut = True
                break
            cells: list[str] = []
            for i, c in enumerate(row.iter(f"{S}c")):
                at = _col(c.get("r")) if c.get("r") else i
                if at >= COLS:
                    cut = True
                    continue
                t = c.get("t")
                v = c.find(f"{S}v")
                if t == "s" and v is not None:
                    try:
                        val = shared[int(v.text or 0)]
                    except (ValueError, IndexError):
                        val = ""
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(f"{S}t"))
                elif t == "b" and v is not None:
                    val = "TRUE" if v.text == "1" else "FALSE"
                else:
                    val = v.text if v is not None and v.text is not None else ""
                while len(cells) < at:
                    cells.append("")
                cells.append(val)
            rows.append(cells)
        sheets.append({"name": str(sh.get("name") or f"Sheet {len(sheets) + 1}"), "rows": rows, "cut": cut})
    return {"office": "xlsx", "sheets": sheets}


def pptx(data: bytes | Path) -> dict[str, Any]:
    z = _zip(data)
    pres = _xml(z, "ppt/presentation.xml")
    if pres is None:
        raise PreviewError("This PowerPoint file has no slides part, so there's nothing to show.")
    rels = _rels(z, "ppt/presentation.xml")
    slides = []
    for n, sid in enumerate(pres.iter(f"{P}sldId"), 1):
        part = rels.get(str(sid.get(f"{R}id")), "")
        root = _xml(z, part) if part else None
        lines = []
        for p in (root.iter(f"{A}p") if root is not None else []):
            text = "".join(t.text or "" for t in p.iter(f"{A}t")).strip()
            if text:
                lines.append(text)
        slides.append({"n": n, "title": lines[0] if lines else "", "lines": lines[1:]})
    return {"office": "pptx", "slides": slides}


def office(path: Path) -> dict[str, Any]:
    ext = Path(path).suffix.lower()
    fn = {".docx": docx, ".xlsx": xlsx, ".pptx": pptx}.get(ext)
    if fn is None:
        raise PreviewError("The harness can't show this kind of file.")
    return fn(Path(path))


# -- Open as PDF -----------------------------------------------------------------------------------------
def libreoffice(which: Callable[[str], str | None] = shutil.which, env: dict[str, str] | None = None) -> str:
    """Where LibreOffice's program is on this computer ("" when it isn't)."""
    for n in ("soffice", "libreoffice"):
        p = which(n)
        if p:
            return p
    env = os.environ if env is None else env
    for base in (env.get("ProgramFiles"), env.get("ProgramFiles(x86)")):
        if base:
            p = Path(base) / "LibreOffice" / "program" / "soffice.exe"
            if p.is_file():
                return str(p)
    mac = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    return str(mac) if mac.is_file() else ""


def _run(argv: list[str], timeout: float, env: dict[str, str]) -> int:
    kw: dict[str, Any] = {}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        return subprocess.run(argv, capture_output=True, timeout=timeout, env=env, **kw).returncode
    except subprocess.TimeoutExpired:
        raise PreviewError("LibreOffice took too long to make the PDF. Try again, or Save a copy instead.") from None


def to_pdf(src: Path, out: Path, soffice: str, run: Callable[[list[str], float, dict[str, str]], int] | None = None,
           timeout: float = PDF_TIMEOUT) -> Path:
    """``src`` converted to the PDF ``out`` by LibreOffice, in a temporary folder of its own."""
    from .harness.safeenv import clean_env

    run = run or _run
    with tempfile.TemporaryDirectory(prefix="rt-pdf-") as tmp:
        t = Path(tmp)
        copy = t / ("in" + Path(src).suffix.lower())
        shutil.copyfile(src, copy)
        profile = (t / "profile").resolve().as_uri()
        argv = [soffice, f"-env:UserInstallation={profile}", "--headless", "--norestore", "--convert-to", "pdf",
                "--outdir", str(t / "out"), str(copy)]
        code = run(argv, timeout, clean_env())
        made = t / "out" / "in.pdf"
        if code != 0 or not made.is_file():
            raise PreviewError("LibreOffice couldn't make a PDF of this file. Save a copy to open it instead.")
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(made, out)
    return out


__all__ = ["PreviewError", "archive", "docx", "kind", "libreoffice", "media_type", "notebook", "office", "pptx",
           "to_pdf", "xlsx"]
