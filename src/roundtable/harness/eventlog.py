"""A project's event log and its archives: ``.harness/events.jsonl`` plus ``.harness/events-<when>.jsonl.gz``.

The live log only grows; once it is big (retention.py), its older half moves into a compressed archive beside
it, so nothing of a project's history is lost. ``read_events`` gives the whole history back in order: the
archives (oldest first) and then the live log. Archives are read once and kept in memory while unchanged.
"""

from __future__ import annotations

import gzip
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

LIVE = "events.jsonl"
ARCHIVE_GLOB = "events-*.jsonl.gz"

_cache: dict[str, tuple[float, int, list[dict[str, Any]]]] = {}
_cache_lock = threading.Lock()


def _parse(text: str) -> list[dict[str, Any]]:
    out = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def archives(root: Path) -> list[Path]:
    """The project's archives, oldest first (their names sort by when they were made)."""
    hdir = Path(root) / ".harness"
    return sorted(p for p in hdir.glob(ARCHIVE_GLOB) if p.is_file()) if hdir.is_dir() else []


def _read_archive(p: Path) -> list[dict[str, Any]]:
    try:
        st = p.stat()
    except OSError:
        return []
    key = str(p)
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
            return hit[2]
    try:
        with gzip.open(p, "rt", encoding="utf-8", errors="replace") as f:
            rows = _parse(f.read())
    except (OSError, EOFError):
        return []
    with _cache_lock:
        _cache[key] = (st.st_mtime, st.st_size, rows)
    return rows


def read_events(root: Path, include_archives: bool = True) -> list[dict[str, Any]]:
    """Every event of the project in order: the archives first (when asked), then the live log."""
    rows: list[dict[str, Any]] = []
    if include_archives:
        for p in archives(root):
            rows.extend(_read_archive(p))
    live = Path(root) / ".harness" / LIVE
    try:
        rows.extend(_parse(live.read_text(encoding="utf-8", errors="replace")))
    except OSError:
        pass
    return rows


def _archive_name(hdir: Path, now: float) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    p = hdir / f"events-{stamp}.jsonl.gz"
    n = 1
    while p.exists():
        n += 1
        p = hdir / f"events-{stamp}-{n}.jsonl.gz"
    return p


def archive_older_half(root: Path, max_bytes: int, dry_run: bool = False,
                       now: float | None = None) -> dict[str, Any] | None:
    """Move the older half of a live log bigger than ``max_bytes`` into a new archive.

    Safe order: the archive is written and put in place first, then the kept half replaces the live log; if the
    log changed meanwhile, the archive is taken back and nothing changes. Returns {archive, moved, archive_bytes,
    saved} or None when there was nothing to do (or it changed while working)."""
    hdir = Path(root) / ".harness"
    live = hdir / LIVE
    try:
        if live.is_symlink() or not live.is_file():
            return None
        st = live.stat()
    except OSError:
        return None
    if max_bytes <= 0 or st.st_size <= max_bytes:
        return None
    data = live.read_bytes()
    cut = data.find(b"\n", max(len(data) - max_bytes // 2, 0))
    if cut < 0:
        return None
    older, kept = data[:cut + 1], data[cut + 1:]
    now = time.time() if now is None else now
    target = _archive_name(hdir, now)
    packed = gzip.compress(older)
    out = {"archive": str(target), "moved": len(older), "archive_bytes": len(packed),
           "saved": max(len(older) - len(packed), 0)}
    if dry_run:
        return out
    fd, tmp = tempfile.mkstemp(dir=hdir, prefix=".events-archive-")
    with os.fdopen(fd, "wb") as f:
        f.write(packed)
    os.replace(tmp, target)
    fd, tmp = tempfile.mkstemp(dir=hdir, prefix=".events-kept-")
    with os.fdopen(fd, "wb") as f:
        f.write(kept)
    try:
        st2 = live.stat()
        if (st2.st_size, st2.st_mtime) != (st.st_size, st.st_mtime):  # something wrote meanwhile: undo
            raise OSError("the event log changed while it was being archived")
        os.replace(tmp, live)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise
    return out
