"""A repository's machine set-up, declared (wave 9, w9-gaps).

A project can say what a new machine needs before its first task, in ``roundtable.yaml`` (committed) or
``.harness/project.yaml`` (this computer's), next to ``setup:``::

    siblings:                       # repositories cloned next to this one, read only
      - someone/shop-addons         # owner/name or a GitHub address
      - {repo: someone/shop-data, dir: shop-data}
    system:                         # packages by name, mapped per system
      - qt-libs                     # a name the harness knows (KNOWN)
      - {name: ffmpeg, apt: ffmpeg, winget: Gyan.FFmpeg, brew: ffmpeg}

On a new machine the harness shows what it will fetch and install and asks once (a card; installs are always
the owner's tap: the "yes" carries an "Are you sure?" so autopilot never picks it), then does it in the run.
Each sibling goes through the references' size check first (``scout.check_size``: refused before a clone when
it's too big). ``sudo`` is never run by itself: where the rights are missing it says the exact line that needs
them. Nothing here calls a model.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml

FILES = ("roundtable.yaml", ".harness/project.yaml")  # the second wins, as projectsettings
STATE_FILE = "setup-declared.json"
SIBLING_MAX_BYTES = 500_000_000
CLONE_TIMEOUT = 600
INSTALL_TIMEOUT = 30 * 60
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+._-]{0,80}$")
_DIR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,100}$")

# names a project can use without spelling out each system's package
KNOWN: dict[str, dict[str, Any]] = {
    "qt-libs": {"about": "the system libraries Qt apps need to start",
                "apt": ["libegl1", "libgl1", "libxkbcommon0", "libfontconfig1", "libdbus-1-3"]},
    "ffmpeg": {"about": "sound and video tools", "apt": ["ffmpeg"], "winget": ["Gyan.FFmpeg"], "brew": ["ffmpeg"]},
    "git-lfs": {"about": "big files kept in git", "apt": ["git-lfs"], "winget": ["GitHub.GitLFS"], "brew": ["git-lfs"]},
    "sqlite": {"about": "a small database", "apt": ["sqlite3"], "winget": ["SQLite.SQLite"], "brew": ["sqlite"]},
}
VIA = {"linux": "apt", "windows": "winget", "mac": "brew"}

Runner = Callable[..., Any]


def os_name() -> str:
    if os.name == "nt":
        return "windows"
    return "mac" if sys.platform == "darwin" else "linux"


def _raw(root: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in FILES:
        p = root / name
        if not p.is_file():
            continue
        try:
            d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if isinstance(d, dict):
            for key in ("siblings", "system"):
                if key in d:
                    out[key] = d[key]
            setup = d.get("setup")
            if isinstance(setup, dict):  # also accepted nested under setup:
                for key in ("siblings", "system"):
                    if key in setup:
                        out[key] = setup[key]
    return out


def _list(v: Any) -> list[str]:
    if isinstance(v, str):
        v = v.split()
    return [str(x).strip() for x in (v or []) if str(x).strip()]


def declared(root: Path | str) -> dict[str, Any]:
    """{siblings: [{repo, dir}], system: [{name, about, apt, winget, brew}], errors: [plain sentences]}."""
    from .scout import _github_repo

    root = Path(root)
    raw = _raw(root)
    errors: list[str] = []
    sibs: list[dict[str, str]] = []
    for item in raw.get("siblings") or []:
        repo = item.get("repo") if isinstance(item, dict) else item
        name = _github_repo(str(repo or "").strip())
        if not name:
            errors.append(f"{repo!r} isn't a GitHub repository (write it as owner/name)")
            continue
        d = str(item.get("dir") if isinstance(item, dict) and item.get("dir") else name.split("/")[1])
        if not _DIR.match(d):
            errors.append(f"{d!r} can't be a folder name for {name}")
            continue
        sibs.append({"repo": name, "dir": d})
    system: list[dict[str, Any]] = []
    for item in raw.get("system") or []:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            base = dict(KNOWN.get(name, {}))
            base.update({k: _list(item[k]) for k in VIA.values() if k in item})
        else:
            name = str(item).strip()
            if name not in KNOWN:
                errors.append(f"The harness doesn't know the package {name!r}: write it as {{name, apt, winget, brew}}")
                continue
            base = dict(KNOWN[name])
        if not _NAME.match(name):
            errors.append(f"{name!r} can't be a package name")
            continue
        pk = {k: [p for p in _list(base.get(k)) if _NAME.match(p)] for k in VIA.values()}
        system.append({"name": name, "about": str(base.get("about") or ""), **pk})
    return {"siblings": sibs, "system": system, "errors": errors}


def _installed(pkg: str, via: str, run: Runner) -> bool:
    """Is a system package there? apt: dpkg's status; winget and brew: their own list."""
    cmd = {"apt": ["dpkg", "-s", pkg], "winget": ["winget", "list", "--id", pkg, "-e"], "brew": ["brew", "list", pkg]}[via]
    try:
        r = run(cmd, capture_output=True, text=True, timeout=60)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def check(root: Path | str, os_: str | None = None, run: Runner = subprocess.run) -> dict[str, Any]:
    """What this machine still needs: {siblings: [{repo, dir, path, present}], system: [{name, via, packages,
    missing}], missing: bool, words, errors}. Reads the disk and the package lists only."""
    root = Path(root)
    os_ = os_ or os_name()
    via = VIA.get(os_, "apt")
    d = declared(root)
    sibs = []
    for s in d["siblings"]:
        path = root.parent / s["dir"]
        sibs.append({**s, "path": str(path), "present": path.is_dir() and any(path.iterdir())})
    system = []
    for p in d["system"]:
        pkgs = p.get(via) or []
        missing = [x for x in pkgs if not _installed(x, via, run)]
        system.append({"name": p["name"], "about": p["about"], "via": via, "packages": pkgs, "missing": missing,
                       "unknown_here": not pkgs})
    need_s = [s for s in sibs if not s["present"]]
    need_p = [p for p in system if p["missing"]]
    bits = []
    if need_s:
        bits.append(f"copy {len(need_s)} repositor{'ies' if len(need_s) != 1 else 'y'} next to this one "
                    f"({', '.join(s['repo'] for s in need_s)})")
    if need_p:
        bits.append(f"install {', '.join(p['name'] for p in need_p)}")
    words = ("This computer needs to " + " and ".join(bits) + " before the first task.") if bits else \
        "This computer has everything the project asks for."
    return {"siblings": sibs, "system": system, "missing": bool(need_s or need_p), "words": words,
            "errors": d["errors"], "os": os_}


def _stamp(plan: dict[str, Any]) -> str:
    import hashlib

    key = json.dumps([[s["repo"] for s in plan["siblings"] if not s["present"]],
                      [(p["name"], p["missing"]) for p in plan["system"] if p["missing"]]], sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _state_path(root: Path) -> Path:
    return root / ".harness" / STATE_FILE


def _state(root: Path) -> dict[str, Any]:
    try:
        d = json.loads(_state_path(root).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(root: Path, d: dict[str, Any]) -> None:
    p = _state_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")


def answer(root: Path | str, yes: bool, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """The owner's tap on the card: remembered for exactly what it showed (a changed list asks again)."""
    root = Path(root)
    plan = plan or check(root)
    d = {"stamp": _stamp(plan), "yes": bool(yes)}
    _save_state(root, d)
    return d


def _is_admin() -> bool:
    try:
        return os.geteuid() == 0  # type: ignore[attr-defined]
    except AttributeError:
        return True  # Windows: winget asks for itself; macOS has no geteuid-less case


def do(root: Path | str, plan: dict[str, Any] | None = None, *, yes: bool = False, run: Runner = subprocess.run,
       size_of: Callable[[str], int | None] | None = None, admin: bool | None = None,
       log: Callable[[str], None] = lambda s: None) -> dict[str, Any]:
    """Fetch and install what ``check`` found missing. Never without ``yes`` (the owner's tap).

    {ok, done: [...], refused: [...], needs_rights: [exact lines], words}."""
    from . import scout
    from .safeenv import clean_env

    root = Path(root)
    plan = plan or check(root)
    if not yes:
        return {"ok": False, "done": [], "refused": [], "needs_rights": [],
                "words": "Nothing was fetched or installed: that waits for your yes on the card."}
    done, refused, rights = [], [], []
    for s in plan["siblings"]:
        if s["present"]:
            continue
        try:
            scout.check_size(s["repo"], SIBLING_MAX_BYTES, size_of)
        except scout.FetchError as e:
            refused.append(str(e))
            log(f"Not copied: {e}")
            continue
        dest = Path(s["path"])
        if dest.exists() and any(dest.iterdir()):
            refused.append(f"{dest} is there already and isn't empty: left as it is")
            continue
        cmd = ["git", "-c", "core.hooksPath=/dev/null", "clone", "--depth", "1", "--no-recurse-submodules",
               f"https://github.com/{s['repo']}.git", str(dest)]
        log(f"Copying {s['repo']} next to this project…")
        try:
            r = run(cmd, capture_output=True, text=True, timeout=CLONE_TIMEOUT, env=clean_env({"GIT_LFS_SKIP_SMUDGE": "1"}))
            ok = r.returncode == 0
        except (OSError, subprocess.SubprocessError) as e:
            ok, r = False, type("R", (), {"stderr": str(e)})()
        if ok:
            done.append(f"copied {s['repo']}")
        else:
            refused.append(f"couldn't copy {s['repo']} (it may be private: this computer's git needs to be able "
                           f"to read it): {(getattr(r, 'stderr', '') or '').strip()[-200:]}")
    admin = _is_admin() if admin is None else admin
    for p in plan["system"]:
        if not p["missing"]:
            continue
        via, pkgs = p["via"], p["missing"]
        if via == "apt":
            cmd = ["apt-get", "install", "-y", *pkgs]
            if not admin:  # never sudo by itself: say the exact line
                rights.append("sudo " + " ".join(cmd))
                continue
        elif via == "winget":
            cmd = None
            for pkg in pkgs:
                c = ["winget", "install", "--id", pkg, "-e", "--silent", "--accept-package-agreements",
                     "--accept-source-agreements"]
                log(f"Installing {pkg}…")
                try:
                    r = run(c, capture_output=True, text=True, timeout=INSTALL_TIMEOUT)
                    (done if r.returncode == 0 else refused).append(
                        f"installed {pkg}" if r.returncode == 0 else f"couldn't install {pkg} (code {r.returncode})")
                except (OSError, subprocess.SubprocessError) as e:
                    refused.append(f"couldn't install {pkg}: {e}")
            continue
        else:
            cmd = ["brew", "install", *pkgs]
        if not shutil.which(cmd[0]) and run is subprocess.run:
            refused.append(f"{cmd[0]} isn't on this computer, so {p['name']} can't be installed here")
            continue
        log(f"Installing {p['name']}…")
        try:
            r = run(cmd, capture_output=True, text=True, timeout=INSTALL_TIMEOUT)
            (done if r.returncode == 0 else refused).append(
                f"installed {p['name']}" if r.returncode == 0 else f"couldn't install {p['name']} (code {r.returncode})")
        except (OSError, subprocess.SubprocessError) as e:
            refused.append(f"couldn't install {p['name']}: {e}")
    ok = not refused and not rights
    words = ("Done: " + "; ".join(done) + "." if done else "Nothing needed doing.") if ok else \
        ("Not everything could be done. " + " ".join(f"{x[:1].upper()}{x[1:]}." for x in refused)
         + (" Some packages need an administrator: the exact lines are under More." if rights else ""))
    return {"ok": ok, "done": done, "refused": refused, "needs_rights": rights, "words": words}


# -- the card and the run -------------------------------------------------------------------------------------
def ask(orch) -> dict[str, Any] | None:
    """The one card before the first task on a new machine (PC only, never answered by autopilot)."""
    from ..asks import _ask

    root = Path(orch.project.root)
    plan = check(root)
    if not plan["missing"]:
        return None
    st = _state(root)
    if st.get("stamp") == _stamp(plan) and "yes" in st:
        return None
    more = [f"git clone https://github.com/{s['repo']} {s['path']}" for s in plan["siblings"] if not s["present"]]
    more += [f"{p['via']}: {' '.join(p['missing'])}" for p in plan["system"] if p["missing"]]
    opts = [{"id": "yes", "label": "Fetch and install", "description": "Done here as part of the run.",
             "confirm": "Fetch these repositories and install these packages on this computer?"},
            {"id": "no", "label": "Not now", "description": "Nothing is fetched or installed; the run waits."}]
    a = _ask("setupdecl", "setup_declared", "Set-up", plan["words"], opts, recommended="yes",
             detail="Only what the project's settings list. Nothing runs as administrator by itself.",
             source={"setup_declared": _stamp(plan)}, pc_only=True, more="\n".join(more))
    a["allow_other"] = False
    return a


def apply(orch, ask_: dict[str, Any], picked: list[str] | None, other: str = "") -> dict[str, Any]:
    yes = (picked or ["no"])[0] == "yes"
    answer(orch.project.root, yes)
    if not yes:
        return {"reply": "Left for now: nothing was fetched or installed.", "then": None}
    return {"reply": "Fetching and installing, then building…", "then": "run"}


def before_run(orch, run: Runner = subprocess.run, size_of=None) -> str | None:
    """Called first thing in ``_prepare_run``: None to carry on, or a status to stop with (the card waits)."""
    root = Path(orch.project.root)
    plan = check(root, run=run)
    if not plan["missing"]:
        return None
    st = _state(root)
    if st.get("stamp") != _stamp(plan) or not st.get("yes"):
        orch._set_status("blocked", pause="setup_declared")
        orch._attention("setup_declared", plan["words"] + " Choose Fetch and install on its card.")
        return "blocked"
    got = do(root, plan, yes=True, run=run, size_of=size_of, log=lambda s: orch.emit("setup_declared", {"line": s}))
    st.update(last=got)
    _save_state(root, st)
    if not got["ok"]:
        orch._set_status("blocked", pause="setup_declared")
        orch._attention("setup_declared_failed", got["words"], details="\n".join(got["needs_rights"]))
        return "blocked"
    orch._resolved("setup_declared", "setup_declared_failed", note="set-up done")
    return None
