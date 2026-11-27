"""CI shown (wave 8, MD-72): the newest GitHub Actions runs for a project's repository and branch, read through
automation's GitHub reader with the owner's GitHub key (asked for, never called in), kept for 60 seconds.

``status(root)`` -> {state, words, repo, branch, failing: [{name, url}], runs: [{name, conclusion, status, url,
at, sha}], link}; ``state`` is one of ``passing``, ``failing``, ``running``, ``none`` (no runs yet), ``not_github``
(no GitHub remote), ``no_key`` or ``error``. ``words`` is what the project's chip says ("Checks passing",
"1 check failing").
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

CACHE_S = 60.0
_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()
_REMOTE = re.compile(r"github\.com[:/]+([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
Git = Callable[[list[str], Path], str]


def _git(args: list[str], root: Path) -> str:
    from .harness.safeenv import NO_GIT_LOGIN, clean_env

    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=10,
                           env=clean_env(NO_GIT_LOGIN))
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def repo_of(root: Path, git: Git | None = None) -> tuple[str, str]:
    """(owner/name, branch) of a project's GitHub remote and current branch; ("", "") when it has none."""
    git = git or _git
    url = git(["remote", "get-url", "origin"], root)
    m = _REMOTE.search(url or "")
    if not m:
        return "", ""
    branch = git(["rev-parse", "--abbrev-ref", "HEAD"], root) or "main"
    return f"{m.group(1)}/{m.group(2)}", ("main" if branch == "HEAD" else branch)


def summarise(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """The newest run of each workflow: failing if any newest finished run failed, running if one is going."""
    from .automation import FAILED

    newest: dict[Any, dict[str, Any]] = {}
    for r in sorted(runs or [], key=lambda r: str(r.get("created_at") or ""), reverse=True):
        newest.setdefault(r.get("workflow_id") or r.get("name"), r)
    rows = [{"name": r.get("name") or "a check", "conclusion": r.get("conclusion"), "status": r.get("status"),
             "url": r.get("html_url") or "", "at": r.get("created_at"), "sha": str(r.get("head_sha") or "")[:7]}
            for r in newest.values()]
    failing = [r for r in rows if r["status"] == "completed" and r["conclusion"] in FAILED]
    going = [r for r in rows if r["status"] != "completed"]
    if not rows:
        return {"state": "none", "words": "No checks yet", "runs": [], "failing": []}
    if failing:
        n = len(failing)
        return {"state": "failing", "words": f"{n} check{'s' if n != 1 else ''} failing", "runs": rows,
                "failing": [{"name": r["name"], "url": r["url"]} for r in failing]}
    if going:
        return {"state": "running", "words": "Checks running", "runs": rows, "failing": []}
    return {"state": "passing", "words": "Checks passing", "runs": rows, "failing": []}


def status(root: str | Path, http=None, git: Git | None = None, now: float | None = None,
           fresh: bool = False) -> dict[str, Any]:
    from . import automation as au

    root = Path(root)
    repo, branch = repo_of(root, git)
    if not repo:
        return {"state": "not_github", "words": "Not on GitHub", "repo": "", "branch": "", "runs": [], "failing": []}
    key, t = (repo, branch), (now if now is not None else time.monotonic())
    with _lock:
        hit = _cache.get(key)
    if hit and not fresh and t - hit[0] < CACHE_S:
        return hit[1]
    base = {"repo": repo, "branch": branch, "link": f"https://github.com/{repo}/actions?query=branch%3A{branch}"}
    token = au.github_token()
    if not token:
        return {**base, "state": "no_key", "words": "Add your GitHub key to see checks", "runs": [], "failing": []}
    try:
        data = au.GitHub(token, http).get(repo, "/actions/runs", branch=branch, per_page=20)
        out = {**base, **summarise((data or {}).get("workflow_runs") or [])}
    except au.AutomationError as e:
        out = {**base, "state": "error", "words": "Checks can't be read", "detail": str(e), "runs": [], "failing": []}
    except Exception as e:  # noqa: BLE001 - offline: say so, try again in a minute
        out = {**base, "state": "error", "words": "Checks can't be read", "detail": f"Couldn't reach GitHub: {e}",
               "runs": [], "failing": []}
    with _lock:
        _cache[key] = (t, out)
    return out


def forget() -> None:
    with _lock:
        _cache.clear()
