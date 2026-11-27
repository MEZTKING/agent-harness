"""The list of plug-ins and skills to add (wave 7, d4-tools).

``catalogue.json`` ships with the app. Each entry::

    {"id", "name", "blurb", "kind": "plugin" | "skill", "source": a git address or "builtin", "commit",
     "path": the folder inside the repository (optional), "permissions": [...], "version", "checked": a date}

- ``refresh(fetch)`` reads a newer list from one fixed address in the harness's own repository (``REFRESH_URL``)
  and keeps it in ``<app home>/market/catalogue.json``. A refreshed list is only shown: nothing is installed or
  updated because of it.
- ``install(id, confirm)`` fetches that exact commit into a temporary folder, checks the manifest's id and
  permissions match the entry (a plug-in that asks for more than the list says is refused), then hands the folder
  to ``manage.add_plugin`` (which asks the owner, ``confirm``). A skill goes through ``skills.add`` (the whole text
  in the confirm).
- ``updates()`` compares the installed versions with the list's.
- ``remove(id)`` moves a plug-in's code aside (``<app home>/put-aside/plugins/``) before forgetting it, and a skill
  aside too (skills.remove); nothing is deleted.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from importlib import resources
from pathlib import Path
from typing import Any, Callable

from .. import skills as skilllib
from ..core.models import utcnow
from .api import PluginError, permission_words
from .manifest import Manifest, find_manifest

REFRESH_URL = "https://raw.githubusercontent.com/MEZTKING/agent-harness/main/src/roundtable/plugins/catalogue.json"
KINDS = ("plugin", "skill")
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
MAX_LIST_BYTES = 512 * 1024

Runner = Callable[..., Any]
Fetch = Callable[[str], bytes]


class MarketError(PluginError):
    """The list can't be read, or an entry can't be added (the message is for the owner)."""


# -- the list ---------------------------------------------------------------------------------------------------
def _home(home: Path | str | None = None) -> Path:
    if home:
        return Path(home)
    from ..desktop import app_home

    return app_home()


def shipped_path() -> Path:
    return Path(str(resources.files("roundtable").joinpath("plugins/catalogue.json")))


def refreshed_path(home: Path | str | None = None) -> Path:
    return _home(home) / "market" / "catalogue.json"


def parse(raw: Any) -> dict[str, Any]:
    """A checked list: {"version", "updated", "entries": [...]}; MarketError when it isn't one."""
    if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list):
        raise MarketError("The list isn't in the right shape (it needs entries).")
    seen: set[str] = set()
    out = []
    for i, e in enumerate(raw["entries"]):
        if not isinstance(e, dict):
            raise MarketError(f"Entry {i + 1} of the list isn't in the right shape.")
        eid = str(e.get("id") or "")
        if not ID_RE.match(eid) or eid in seen:
            raise MarketError(f"Entry {i + 1} of the list needs its own id.")
        seen.add(eid)
        kind = e.get("kind")
        if kind not in KINDS:
            raise MarketError(f"{eid}: kind must be plugin or skill.")
        source, commit = str(e.get("source") or ""), str(e.get("commit") or "")
        if source != "builtin":
            if not (source.startswith("https://") or Path(source).is_absolute()):
                raise MarketError(f"{eid}: its source must be a git address (https://...).")
            if not SHA_RE.match(commit):
                raise MarketError(f"{eid}: it must name the exact commit that was checked.")
        perms = e.get("permissions") or []
        if not isinstance(perms, list) or not all(isinstance(p, str) for p in perms):
            raise MarketError(f"{eid}: permissions must be a list.")
        rel = str(e.get("path") or "")
        if rel and (rel.startswith(("/", "\\")) or ".." in Path(rel).parts or ":" in rel):
            raise MarketError(f"{eid}: its path must be a folder inside the repository.")
        out.append({"id": eid, "name": str(e.get("name") or eid), "blurb": str(e.get("blurb") or ""), "kind": kind,
                    "source": source, "commit": commit, "path": rel, "permissions": list(perms),
                    "version": str(e.get("version") or "0"), "checked": str(e.get("checked") or ""),
                    "licence": str(e.get("licence") or ""), "author": str(e.get("author") or "")})
    return {"version": int(raw.get("version") or 1), "updated": str(raw.get("updated") or ""), "entries": out}


def load(home: Path | str | None = None) -> dict[str, Any]:
    """The list to show: the refreshed one when there is a good one, else the one that came with the app."""
    rp = refreshed_path(home)
    if rp.is_file():
        try:
            got = parse(json.loads(rp.read_text(encoding="utf-8")))
            return {**got, "from": "refreshed", "refreshed_at": json.loads(rp.read_text(encoding="utf-8")).get(
                "_refreshed_at", "")}
        except (OSError, ValueError, MarketError):
            pass
    return {**parse(json.loads(shipped_path().read_text(encoding="utf-8"))), "from": "shipped", "refreshed_at": ""}


def entry(eid: str, catalogue: dict[str, Any] | None = None, home: Path | str | None = None) -> dict[str, Any]:
    for e in (catalogue or load(home))["entries"]:
        if e["id"] == eid:
            return e
    raise MarketError(f"There's nothing called {eid!r} in the list.")


def _urlopen(url: str) -> bytes:
    import urllib.request

    with urllib.request.urlopen(url, timeout=20) as r:  # noqa: S310 - the one fixed https address
        return r.read(MAX_LIST_BYTES + 1)


def refresh(fetch: Fetch | None = None, home: Path | str | None = None) -> dict[str, Any]:
    """Read the newer list from ``REFRESH_URL`` and keep it. Only shown: nothing is installed because of it."""
    try:
        data = (fetch or _urlopen)(REFRESH_URL)
    except Exception as e:  # noqa: BLE001 - any network trouble, said plainly
        raise MarketError(f"The newer list couldn't be read ({type(e).__name__}). Check the internet connection "
                          "and try again.") from None
    if len(data) > MAX_LIST_BYTES:
        raise MarketError("The newer list is too big to be right, so it wasn't kept.")
    try:
        raw = json.loads(data.decode("utf-8"))
        parse(raw)
    except (ValueError, UnicodeDecodeError) as e:
        raise MarketError(f"The newer list couldn't be read: {e}") from None
    raw["_refreshed_at"] = utcnow()
    p = refreshed_path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return load(home)


# -- fetching one entry -----------------------------------------------------------------------------------------
def _run(runner: Runner, cmd: list[str], what: str) -> None:
    from ..harness.safeenv import clean_env

    res = runner(cmd, capture_output=True, text=True, env=clean_env())
    if getattr(res, "returncode", 1) != 0:
        tail = ((getattr(res, "stderr", "") or getattr(res, "stdout", "") or "").strip())[-400:]
        raise MarketError(f"{what} didn't work. Check the internet connection and try again.\n{tail}")


def fetch_entry(e: dict[str, Any], tmp: Path, runner: Runner = subprocess.run) -> Path:
    """That exact commit of the entry's repository, in ``tmp``; the folder holding the plug-in or skill."""
    repo = tmp / "src"
    _run(runner, ["git", "clone", "--quiet", "--no-checkout", e["source"], str(repo)], f"Downloading {e['name']}")
    _run(runner, ["git", "-C", str(repo), "-c", "advice.detachedHead=false", "checkout", "--quiet", e["commit"]],
         f"Getting the checked version of {e['name']}")
    folder = (repo / e["path"]).resolve() if e.get("path") else repo
    if repo.resolve() not in (folder, *folder.parents) or not folder.is_dir():
        raise MarketError(f"{e['name']}: the folder the list names isn't in that version.")
    shutil.rmtree(repo / ".git", ignore_errors=True)
    return folder


def check_against(e: dict[str, Any], m: Manifest) -> None:
    """The fetched manifest must be the entry's plug-in, asking for no more than the list says."""
    if m.id != e["id"]:
        raise MarketError(f"{e['name']}: the download holds the plug-in {m.id!r}, not {e['id']!r}, so it wasn't added.")
    more = sorted(set(m.permissions) - set(e["permissions"]))
    if more:
        raise MarketError(f"{e['name']} asks for more than the list says ({', '.join(permission_words(p) for p in more)}), "
                          "so it wasn't added.")


def install(eid: str, confirm: Callable[[Any], bool], harness_path: str | Path | None = None,
            runner: Runner = subprocess.run, catalogue: dict[str, Any] | None = None,
            home: Path | str | None = None) -> dict[str, Any]:
    """Add one entry of the list, once the owner has said yes (``confirm`` gets the Manifest or the Skill)."""
    from . import manage

    e = entry(eid, catalogue, home)
    if e["kind"] == "skill" and e["source"] == "builtin":
        skilllib.get(eid, home)
        return {"kind": "skill", **skilllib.switch(eid, True, home)}
    if e["source"] == "builtin":
        raise MarketError(f"{e['name']} comes with the app: switch it on in Plug-ins.")
    with tempfile.TemporaryDirectory(prefix="market-") as t:
        folder = fetch_entry(e, Path(t), runner)
        if e["kind"] == "skill":
            s = skilllib.add(folder, confirm, home)
            return {"kind": "skill", "id": s.id, "name": s.name, "added": True}
        check_against(e, find_manifest(folder))
        added = manage.add_plugin(harness_path, str(folder), confirm, runner=runner)
    _note_source(harness_path, e)
    return {"kind": "plugin", **added}


def _note_source(harness_path: Any, e: dict[str, Any]) -> None:
    """custom.yaml's plugins: entry says where it came from (the list and the exact commit), not the temp folder."""
    from ..harness.config import load_custom, save_custom
    from . import manage

    path = manage._path(harness_path)
    custom = load_custom(path)
    spec = (custom.get("plugins") or {}).get(e["id"])
    if isinstance(spec, dict):
        spec["source"] = f"{e['source']}@{e['commit']}"
        spec["from_list"] = e["id"]
        save_custom(path, custom)


def _version(v: str) -> tuple:
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-+]", str(v or "0"))[:4])


def updates(harness_path: str | Path | None = None, catalogue: dict[str, Any] | None = None,
            home: Path | str | None = None) -> list[dict[str, Any]]:
    """Installed plug-ins the list has a newer version of: [{id, name, have, newer}]."""
    from . import manage

    cat = catalogue or load(home)
    by = {e["id"]: e for e in cat["entries"] if e["kind"] == "plugin"}
    out = []
    for p in manage.list_plugins(harness_path):
        e = by.get(p["id"])
        if e and not p.get("builtin") and _version(e["version"]) > _version(p.get("version")):
            out.append({"id": p["id"], "name": p["name"], "have": p.get("version"), "newer": e["version"]})
    return out


def remove(eid: str, harness_path: str | Path | None = None, home: Path | str | None = None) -> dict[str, Any]:
    """Take a plug-in or skill away: its files are moved aside, never deleted."""
    from ..harness.config import load_custom
    from . import manage
    from .builtin import BUILTIN_MANIFESTS
    from .host import code_home

    skill_ids = {s.id: s for s in skilllib.list_skills(home)}
    plugins = (load_custom(manage._path(harness_path)).get("plugins") or {})
    if eid in plugins and eid not in BUILTIN_MANIFESTS:
        code = Path(str((plugins[eid] or {}).get("path") or ""))
        moved = ""
        if not (plugins[eid] or {}).get("linked") and code.is_dir() and code_home() in code.resolve().parents:
            aside = _home(home) / "put-aside" / "plugins" / f"{eid}-{utcnow().replace(':', '').replace('-', '')[:15]}"
            aside.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(code, aside)
            moved = str(aside)
        manage.remove_plugin(harness_path, eid, purge=False)  # its data folder stays too
        return {"kind": "plugin", "id": eid, "moved_to": moved}
    if eid in skill_ids:
        s = skill_ids[eid]
        if s.source == "builtin":
            return {"kind": "skill", **skilllib.switch(eid, False, home)}
        return {"kind": "skill", **skilllib.remove(eid, home)}
    raise MarketError(f"There's no plug-in or skill called {eid!r} to take away.")


# -- what the app shows -------------------------------------------------------------------------------------------
def view(harness_path: str | Path | None = None, home: Path | str | None = None) -> dict[str, Any]:
    from . import manage

    cat = load(home)
    try:
        installed = {p["id"]: p for p in manage.list_plugins(harness_path)}
    except Exception:  # noqa: BLE001 - without a harness config the list still shows
        installed = {}
    newer = {u["id"]: u for u in (updates(harness_path, cat, home) if installed else [])}
    skills = {s.id: s for s in skilllib.list_skills(home)}
    plugins_out, skills_out = [], []
    for e in cat["entries"]:
        row = {**e, "permission_words": [permission_words(p) for p in e["permissions"]] or ["Nothing special"]}
        if e["kind"] == "plugin":
            have = installed.get(e["id"])
            row.update({"installed": bool(have), "enabled": bool(have and have.get("enabled")),
                        "have_version": (have or {}).get("version", ""), "update": newer.get(e["id"])})
            plugins_out.append(row)
        else:
            s = skills.get(e["id"])
            row.update({"installed": bool(s), "enabled": bool(s and s.enabled)})
            skills_out.append(row)
    listed = {e["id"] for e in cat["entries"]}
    for s in skills.values():  # the owner's own skills, not in the list
        if s.id not in listed:
            skills_out.append({"id": s.id, "name": s.name, "blurb": s.when, "kind": "skill", "source": s.source,
                               "installed": True, "enabled": s.enabled, "own": True, "tags": s.tags,
                               "permissions": [], "permission_words": ["Nothing: a skill is only words"]})
    for row in skills_out:
        s = skills.get(row["id"])
        if s:
            row["tags"], row["when"] = s.tags, s.when
    n_p, n_s = len(plugins_out), len([r for r in skills_out if not r.get("own")])
    words = (f"The list has {n_s} skill{'s' if n_s != 1 else ''} and {n_p} plug-in{'s' if n_p != 1 else ''}"
             + (": it is small for now, and grows as more are checked." if n_p + n_s < 30 else "."))
    return {"plugins": plugins_out, "skills": skills_out, "updates": list(newer.values()), "words": words,
            "from": cat["from"], "updated": cat["updated"], "refreshed_at": cat["refreshed_at"]}
