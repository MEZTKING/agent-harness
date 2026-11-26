"""Small file helpers that behave the same on Windows as elsewhere."""

from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path


def remove_tree(path: str | Path) -> None:
    """Delete a folder even when it holds read-only files (git marks its objects read-only on Windows)."""
    def unlock(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    if not Path(path).exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=unlock)
    else:  # Python 3.10 and 3.11 call it onerror
        shutil.rmtree(path, onerror=unlock)
