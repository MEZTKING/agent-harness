"""Built-in updater: `roundtable update [--check] [--ref BRANCH]`.

Knows how Roundtable Hold was installed (pip writes PEP 610 ``direct_url.json``):

* from git   (``pip install "git+https://github.com/...@branch"``): compares the
  installed commit with the remote branch head, and reinstalls from the same URL.
* the Windows app (PyInstaller build): checks the latest GitHub Release, downloads
  its installer and runs it (the app closes and reopens on the new version).
* editable   (``pip install -e /path/to/checkout``): ``git pull --ff-only`` in the
  checkout (refusing if it has uncommitted changes), then ``pip install -e`` so new
  dependencies and commands are picked up.

A passive check runs at most once a day after a CLI command (2-second timeout)
and prints a one-line notice. Turn it off with ROUNDTABLE_NO_UPDATE_CHECK=1.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

DIST = "roundtable-hold"
DEFAULT_URL = "https://github.com/MEZTKING/agent-harness"
RELEASES_API = "https://api.github.com/repos/MEZTKING/agent-harness/releases/latest"
CHECK_EVERY = 24 * 3600
STATE_FILE = Path(os.environ.get("ROUNDTABLE_HOME", "~/.roundtable")).expanduser() / "update-check.json"

Runner = Callable[..., subprocess.CompletedProcess]


def _run(cmd: list[str], cwd: str | Path | None = None, timeout: float = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


@dataclass
class InstallInfo:
    kind: str  # app | git | editable | other
    url: str = ""  # git remote URL
    ref: str = ""  # branch/tag the install tracks
    commit: str = ""  # installed commit
    path: str = ""  # checkout dir (editable)
    version: str = ""


@dataclass
class UpdateStatus:
    install: InstallInfo
    latest: str = ""  # remote commit
    available: bool = False
    message: str = ""
    changes: list[str] = field(default_factory=list)


class UpdateError(RuntimeError):
    pass


def _parse_version(v: str) -> tuple:
    parts = []
    for p in v.lstrip("vV").split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts)


def latest_release(fetch=None) -> dict:
    """{version, url (installer asset), notes} of the newest GitHub Release."""
    import urllib.request

    if fetch is None:
        def fetch(url):
            req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                       "User-Agent": "roundtable-hold-updater"})
            with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 - fixed GitHub API URL
                return json.loads(r.read())
    try:
        rel = fetch(RELEASES_API)
    except Exception as e:
        raise UpdateError(f"could not reach GitHub Releases ({e})") from e
    asset = next((a for a in rel.get("assets", []) if a.get("name", "").lower().endswith("setup.exe")
                  or ("setup" in a.get("name", "").lower() and a.get("name", "").lower().endswith(".exe"))), None)
    return {"version": rel.get("tag_name", "").lstrip("vV"), "url": asset["browser_download_url"] if asset else "",
            "notes": (rel.get("body") or "")[:2000], "page": rel.get("html_url", "")}


def install_info(direct_url: dict | None = None, version: str | None = None, runner: Runner = _run) -> InstallInfo:
    if getattr(sys, "frozen", False) and direct_url is None:
        from . import __version__

        return InstallInfo("app", version=__version__, ref="releases", url=DEFAULT_URL)
    try:
        dist = metadata.distribution(DIST)
        version = version or dist.version
        if direct_url is None:
            raw = dist.read_text("direct_url.json")
            direct_url = json.loads(raw) if raw else {}
    except metadata.PackageNotFoundError:
        direct_url = direct_url or {}
    direct_url = direct_url or {}
    url = direct_url.get("url", "")
    if "vcs_info" in direct_url:
        vcs = direct_url["vcs_info"]
        return InstallInfo("git", url=url, ref=vcs.get("requested_revision", ""), commit=vcs.get("commit_id", ""),
                           version=version or "")
    if direct_url.get("dir_info", {}).get("editable"):
        path = urlparse(url).path
        info = InstallInfo("editable", path=path, version=version or "")
        if (Path(path) / ".git").exists():
            info.commit = runner(["git", "rev-parse", "HEAD"], cwd=path).stdout.strip()
            info.ref = runner(["git", "branch", "--show-current"], cwd=path).stdout.strip()
            info.url = runner(["git", "remote", "get-url", "origin"], cwd=path).stdout.strip()
        return info
    return InstallInfo("other", version=version or "")


def remote_head(url: str, ref: str, runner: Runner = _run, timeout: float = 30) -> str:
    res = runner(["git", "ls-remote", url, f"refs/heads/{ref}" if ref else "HEAD"], timeout=timeout)
    if res.returncode != 0:
        raise UpdateError(f"could not reach {url}: {res.stderr.strip()[:200]}")
    line = res.stdout.strip().splitlines()
    if not line:
        raise UpdateError(f"branch {ref!r} not found at {url}")
    return line[0].split()[0]


def check(ref: str | None = None, info: InstallInfo | None = None, runner: Runner = _run,
          timeout: float = 30) -> UpdateStatus:
    info = info or install_info(runner=runner)
    if info.kind == "app":
        rel = latest_release()
        newer = _parse_version(rel["version"]) > _parse_version(info.version)
        st = UpdateStatus(info, latest=rel["version"], available=newer and bool(rel["url"]))
        st.message = (f"Roundtable Hold {rel['version']} is available (you have {info.version})" if st.available
                      else f"up to date (version {info.version})")
        st.changes = [ln for ln in rel["notes"].splitlines() if ln.strip()][:20]
        st.install.path = rel["url"]
        return st
    if info.kind == "other":
        return UpdateStatus(info, message="installed from a package archive; reinstall with "
                                          f"pip install --upgrade \"git+{DEFAULT_URL}\" to enable updates")
    url = info.url or DEFAULT_URL
    branch = ref or info.ref
    latest = remote_head(url, branch, runner, timeout)
    st = UpdateStatus(info, latest=latest, available=bool(info.commit) and latest != info.commit)
    st.message = (f"update available: {info.commit[:7]} -> {latest[:7]} ({branch or 'default branch'})"
                  if st.available else f"up to date ({(info.commit or latest)[:7]}, {branch or 'default branch'})")
    return st


def update(ref: str | None = None, force: bool = False, runner: Runner = _run,
           log: Callable[[str], None] = print, info: InstallInfo | None = None) -> UpdateStatus:
    info = info or install_info(runner=runner)
    st = check(ref, info, runner)
    if info.kind == "other":
        raise UpdateError(st.message)
    if not st.available and not force:
        log(st.message)
        return st
    if info.kind == "app":
        return _update_app(st, log)
    pip = [sys.executable, "-m", "pip", "install", "--quiet"]
    if info.kind == "git":
        target = f"{DIST} @ git+{info.url or DEFAULT_URL}@{ref or info.ref or 'HEAD'}"
        log(f"installing {target}")
        res = runner(pip + ["--upgrade", "--force-reinstall", target])
        if res.returncode != 0:
            raise UpdateError(f"pip failed: {(res.stderr or res.stdout).strip()[-600:]}")
    else:  # editable checkout
        path = info.path
        dirty = runner(["git", "status", "--porcelain", "--untracked-files=no"], cwd=path).stdout.strip()
        if dirty and not force:
            raise UpdateError(f"{path} has uncommitted changes; commit or stash them first (or use --force "
                              "to update anyway - your changes are kept, the pull may still refuse)")
        branch = ref or info.ref
        if ref and ref != info.ref:
            res = runner(["git", "fetch", "origin", ref], cwd=path)
            if res.returncode == 0:
                res = runner(["git", "checkout", ref], cwd=path)
        else:
            res = runner(["git", "pull", "--ff-only", "origin", branch], cwd=path)
        if res.returncode != 0:
            raise UpdateError(f"git could not update {path}: {(res.stderr or res.stdout).strip()[-400:]}")
        log(f"pulled {branch} in {path}; reinstalling")
        res = runner(pip + ["-e", path])
        if res.returncode != 0:
            raise UpdateError(f"pip failed: {(res.stderr or res.stdout).strip()[-600:]}")
        new = runner(["git", "rev-parse", "HEAD"], cwd=path).stdout.strip()
        if info.commit and new:
            st.changes = runner(["git", "log", "--oneline", f"{info.commit}..{new}"], cwd=path).stdout.splitlines()
        st.latest = new or st.latest
    _save_state({"checked_at": time.time(), "latest": st.latest, "installed": st.latest})
    st.available = False
    st.message = f"updated to {st.latest[:7]}. Restart any running `roundtable ui` / `mcp` servers."
    log(st.message)
    for c in st.changes[:30]:
        log(f"  {c}")
    return st


def _update_app(st: UpdateStatus, log: Callable[[str], None]) -> UpdateStatus:
    """Download the new installer and run it; it closes this app and reopens the new version."""
    import tempfile
    import urllib.request

    url = st.install.path
    if not url:
        raise UpdateError("the latest release has no Windows installer attached yet")
    dest = Path(tempfile.gettempdir()) / f"RoundtableHold-Setup-{st.latest}.exe"
    log(f"downloading {url}")
    with urllib.request.urlopen(url, timeout=300) as r, open(dest, "wb") as f:  # noqa: S310 - GitHub release asset
        while chunk := r.read(1 << 20):
            f.write(chunk)
    log(f"starting the installer ({dest.stat().st_size // 1_000_000} MB); Roundtable Hold will close and reopen")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(dest), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"], creationflags=flags)
    st.available = False
    st.message = f"installing {st.latest}..."

    def _exit_soon():
        time.sleep(3)
        os._exit(0)  # let the installer replace our files

    import threading

    threading.Thread(target=_exit_soon, daemon=True).start()
    return st


# -- passive daily check ------------------------------------------------------------
def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state))
    except OSError:
        pass


def cached_notice(runner: Runner = _run, now: float | None = None) -> str | None:
    """One-line notice if an update is available. Hits the network at most once a day."""
    if os.environ.get("ROUNDTABLE_NO_UPDATE_CHECK"):
        return None
    now = now or time.time()
    try:
        info = install_info(runner=runner)
        if info.kind in ("other", "app") or not info.commit:
            return None  # the app shows its own banner
        state = _load_state()
        if now - state.get("checked_at", 0) > CHECK_EVERY or state.get("installed") != info.commit:
            st = check(info=info, runner=runner, timeout=2)
            state = {"checked_at": now, "latest": st.latest, "installed": info.commit}
            _save_state(state)
        if state.get("latest") and state["latest"] != info.commit:
            return f"Roundtable Hold update available ({info.commit[:7]} -> {state['latest'][:7]}): run `roundtable update`"
    except Exception:  # never let the update check break a command
        return None
    return None


def status_dict(runner: Runner = _run) -> dict:
    try:
        st = check(runner=runner, timeout=10)
        return asdict(st) | {"error": ""}
    except Exception as e:
        return {"available": False, "error": str(e), "message": str(e)}
