"""Rewrite a layer tar so the phone can unpack it.

The phone's unpacker (mobile/.../runtime/TarExtractor.kt) refuses hard links and pax headers on
purpose. Docker's tar export keeps both (Debian ships hard links, e.g. usr/bin/perl5.36.0), so every
hard link becomes an ordinary copy of the file it points at, and the archive is written in GNU format
(long names use GNU long-name entries, which the unpacker reads).

    python3 runtime/flatten_tar.py layer.tar          # rewrites it in place
"""

from __future__ import annotations

import os
import sys
import tarfile
import tempfile


def flatten(src: str, dst: str) -> dict:
    """Copy src to dst with every hard link turned into a regular file. Returns counts."""
    with tarfile.open(src, "r:") as t:
        targets = {m.linkname for m in t if m.islnk()}
    kept: dict[str, bytes] = {}
    n = {"entries": 0, "hardlinks": 0}
    with tarfile.open(src, "r:") as t, tarfile.open(dst, "w:", format=tarfile.GNU_FORMAT) as out:
        for m in t:
            n["entries"] += 1
            if m.islnk():
                data = kept.get(m.linkname)
                if data is None:
                    raise ValueError(f"hard link {m.name!r} points at {m.linkname!r}, which came later or isn't a file")
                copy = tarfile.TarInfo(m.name)
                copy.size, copy.mode, copy.mtime = len(data), m.mode, m.mtime
                copy.uid, copy.gid, copy.uname, copy.gname = m.uid, m.gid, m.uname, m.gname
                copy.type = tarfile.REGTYPE
                out.addfile(copy, _reader(data))
                n["hardlinks"] += 1
                continue
            m.pax_headers = {}
            if m.isreg():
                f = t.extractfile(m)
                if m.name in targets:
                    data = f.read()
                    kept[m.name] = data
                    out.addfile(m, _reader(data))
                else:
                    out.addfile(m, f)
            else:
                out.addfile(m)
    return n


def _reader(data: bytes):
    import io
    return io.BytesIO(data)


def main(argv: list[str]) -> int:
    for path in argv:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix=".tar")
        os.close(fd)
        try:
            n = flatten(path, tmp)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        print(f"{path}: {n['entries']} entries, {n['hardlinks']} hard links made into copies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
