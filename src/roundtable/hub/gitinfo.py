"""Pull a short commit log from a local repo to keep a card's
``recent_commits`` current without the agent writing it by hand."""

from __future__ import annotations

import subprocess
from pathlib import Path


def recent_commits(repo_path: str | Path = ".", count: int = 10) -> list[str]:
    res = subprocess.run(
        ["git", "log", f"-{int(count)}", "--date=short", "--pretty=format:%h %ad %s"],
        cwd=Path(repo_path),
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(f"git log failed in {repo_path}: {res.stderr.strip()}")
    return [line for line in res.stdout.splitlines() if line.strip()]
