"""The project's own checks: running its ``test`` command (settings in ``projectsettings.py``).

A baseline run is recorded before the first task, so a test that was already failing is never
blamed on a task: the reviewer is shown only the failures that are new since then.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from ..core.models import utcnow
from .safeenv import clean_env

MAX_TAIL = 4000


# -- running ------------------------------------------------------------------------------------
def run(root: str | Path, command: str, env: dict[str, str] | None = None, timeout: int = 900) -> dict[str, Any]:
    """Run a shell command in the project folder with ``env`` added to a cleaned copy of the
    environment (no keys, tokens or git login: ``safeenv.clean_env``)."""
    full_env = clean_env(env)
    full_env.setdefault("PYTHONIOENCODING", "utf-8")
    t0 = time.monotonic()
    kw: dict[str, Any] = {}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kw["start_new_session"] = True  # so a timeout stops the whole test run, not just the shell
    proc = subprocess.Popen(command, shell=True, cwd=str(root), env=full_env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kw)
    timed_out = False
    try:
        raw, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill(proc)
        raw, _ = proc.communicate()
    output = (raw or b"").decode("utf-8", errors="replace")
    return {"command": command, "exit_code": proc.returncode, "timed_out": timed_out, "output": output,
            "seconds": round(time.monotonic() - t0, 1)}


def _kill(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        proc.kill()


_PYTEST = re.compile(r"^(?:FAILED|ERROR)\s+(\S+?)(?:\s+-\s.*)?$")
_UNITTEST = re.compile(r"^(?:FAIL|ERROR):\s+(\S+)\s+\(([^)]+)\)")


def failing_names(output: str) -> list[str]:
    """The failing tests' names when the output is pytest- or unittest-like (else empty)."""
    names: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        m = _PYTEST.match(line)
        name = m.group(1) if m else None
        if not name:
            u = _UNITTEST.match(line)
            name = f"{u.group(2)}.{u.group(1)}" if u else None
        if name and name not in names:
            names.append(name)
    return names[:500]


def summarise(result: dict[str, Any], commit: str | None = None) -> dict[str, Any]:
    """A run kept in project.json: passed or not, the failing names, the end of the output."""
    passed = result["exit_code"] == 0 and not result["timed_out"]
    names = [] if passed else failing_names(result["output"])
    return {"command": result["command"], "at": utcnow(), "commit": commit or "", "passed": passed,
            "exit_code": result["exit_code"], "timed_out": result["timed_out"], "failing": names,
            "names_found": bool(names), "seconds": result["seconds"], "tail": result["output"][-MAX_TAIL:]}


def compare(baseline: dict[str, Any] | None, now: dict[str, Any]) -> dict[str, Any]:
    """Is a failure the task's fault? ``verdict``: pass, old_only (only failures that were there before),
    new (the task broke something) or unknown (it was failing before and the names can't be read)."""
    if now["passed"]:
        return {"verdict": "pass", "new": [], "old": []}
    before = set((baseline or {}).get("failing") or [])
    if now["names_found"]:
        new = [n for n in now["failing"] if n not in before]
        old = [n for n in now["failing"] if n in before]
        return {"verdict": "new" if new else "old_only", "new": new, "old": old}
    if baseline and not baseline.get("passed"):
        return {"verdict": "unknown", "new": [], "old": []}
    return {"verdict": "new", "new": [], "old": []}


def filtered_tail(now: dict[str, Any], old: list[str], limit: int = 3000) -> str:
    """The end of the output without the lines about failures that were there before the run."""
    lines = [ln for ln in now.get("tail", "").splitlines() if not any(o in ln for o in old)]
    text = "\n".join(lines)
    return text[-limit:]


# -- a task's own worktree (several tasks at once, worktrees.py) ----------------------------------
def prepare_worktree(root: str | Path, values: dict[str, Any], commit: str = "",
                     repo_baseline: dict[str, Any] | None = None, fresh: bool = True) -> dict[str, Any]:
    """Get a new worktree ready for its task: the setup command once (its dependencies aren't in git), and
    the checks' starting point there. The repository's baseline is used when the worktree starts from the
    commit it was taken on; otherwise the test command runs once before the task changes anything, so a
    failure that came with work merged since is never blamed on this task."""
    out: dict[str, Any] = {"setup": None, "baseline": None}
    timeout = int(values.get("timeout") or 900)
    if fresh and values.get("setup"):
        res = run(root, values["setup"], values.get("env"), timeout)
        out["setup"] = {"command": values["setup"], "passed": res["exit_code"] == 0 and not res["timed_out"],
                        "at": utcnow(), "tail": res["output"][-2000:]}
    test = values.get("test")
    if test:
        if (repo_baseline and repo_baseline.get("command") == test and commit
                and repo_baseline.get("commit") == commit and not repo_baseline.get("after_tasks")):
            out["baseline"] = repo_baseline
        else:
            out["baseline"] = summarise(run(root, test, values.get("env"), timeout), commit)
            out["baseline"]["worktree"] = True
    return out
