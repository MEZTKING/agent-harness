"""Managing plugins: list, add, remove, switch on and off, settings. Shared by the CLI and the app.

State lives in custom.yaml next to harness.yaml, under ``plugins:``::

    plugins:
      token-saver: {enabled: true, settings: {min_bytes: 2000}}
      cost-log: {enabled: true}
      my-plugin: {enabled: true, source: ./my-plugin, path: <app home>/plugin-code/my-plugin,
                  permissions: [network], version: 1.0.0, settings: {}}

Installing: every plugin's code is kept in ``<app home>/plugin-code/<id>/`` and loaded from
there (added to the end of Python's path). A local folder is copied there (``link=True``
uses it where it is, for writing your own); a git URL is cloned and then copied; a pip
package is downloaded as a wheel to read its manifest, then installed there with
``pip install --target``. Copying is what works in the Windows app, which has no pip of
its own; only pip packages (and plugins that list dependencies) need Python on the computer.

Nothing is installed until the owner has seen what the plugin asks for and said yes
(``confirm``). Built-in plugins are trusted and can't be removed, only switched off.

Every installed plugin runs in its own box (``sandbox.py``) unless the owner switched on
``trusted: true`` for it (``set_trusted``, behind a plain warning). A plugin with compiled parts
is refused before anything is asked, unless it asks to run programs.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable

from ..harness.config import find_config, load_custom, merge_custom, parse_config, save_custom
from .api import PluginError
from .builtin import BUILTIN_MANIFESTS
from .host import PluginHost, code_home, plugins_home
from .manifest import SKIP, Manifest, check_api, find_manifest, project_dependencies
from ..core.files import remove_tree
from ..brand import NAME

Confirm = Callable[[Manifest], bool]
Runner = Callable[..., Any]


TRUST_WARNING = (f"A Trusted plugin runs as {NAME} itself, outside its box: it can use the internet, every file on "
                 "this computer, your programs and your saved keys, whatever it says it needs. Only trust a "
                 "plugin you wrote yourself or have read.")


class NeedsSure(PluginError):
    """Making a plugin Trusted waits for the owner to read the warning and say yes."""

    def __init__(self, item: Any):
        super().__init__(TRUST_WARNING)
        self.item = item


class NeedsOk(PluginError):
    """The owner hasn't said yes to what the plugin asks for yet."""

    def __init__(self, manifest: Manifest):
        super().__init__(f"{manifest.name} needs your OK first")
        self.manifest = manifest


# -- state in custom.yaml ---------------------------------------------------------------
def _path(harness_path: str | Path | None) -> Path:
    return find_config(str(harness_path) if harness_path else None)


def _raw(path: Path) -> dict[str, Any]:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _save(path: Path, custom: dict[str, Any]) -> None:
    """Check the whole merged config still loads, then write custom.yaml."""
    parse_config(merge_custom(_raw(path), custom), path)
    save_custom(path, custom)


def _entry(custom: dict[str, Any], pid: str) -> dict[str, Any]:
    plugins = custom.get("plugins")
    if not isinstance(plugins, dict):
        plugins = custom["plugins"] = {}
    entry = plugins.get(pid)
    if not isinstance(entry, dict):
        entry = plugins[pid] = {}
    return entry


def _host(path: Path) -> PluginHost:
    return PluginHost.from_config(parse_config(merge_custom(_raw(path), load_custom(path)), path))


def _known(path: Path, pid: str):
    host = _host(path)
    host.close()  # only its facts are wanted here: no box stays running
    item = host.get(pid)
    if item is None:
        raise PluginError(f"there's no plugin {pid!r}; `roundtable plugin list` shows the ones you have")
    return item


# -- reading ----------------------------------------------------------------------------
def list_plugins(harness_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Every plugin with its manifest, permissions, status and settings (for the app's card)."""
    path = _path(harness_path)
    from .sandbox import BUILTIN_WORDS, TRUSTED_WORDS, supported

    state = (parse_config(merge_custom(_raw(path), load_custom(path)), path).plugins or {})
    host = _host(path)
    host.close()
    boxed_words = supported()["words"]
    out = []
    for p in host.plugins:
        trusted = bool((state.get(p.id) or {}).get("trusted")) and not p.builtin
        out.append({**p.manifest.view(), "builtin": p.builtin, "enabled": p.enabled, "status": p.status,
                    "boxed": not p.builtin and not trusted, "trusted": trusted,
                    "box_words": BUILTIN_WORDS if p.builtin else TRUSTED_WORDS if trusted else boxed_words,
                    "problem": p.problem, "source": (state.get(p.id) or {}).get("source", "built in" if p.builtin
                                                                                  else ""),
                    "folder": str(plugins_home() / p.id),
                    "settings": [s.view(p.settings.get(k, s.default)) for k, s in p.manifest.settings.items()]})
    return out


def get_settings(harness_path: str | Path | None, pid: str) -> dict[str, Any]:
    p = _known(_path(harness_path), pid)
    return {k: p.settings.get(k, s.default) for k, s in p.manifest.settings.items()}


# -- changing -----------------------------------------------------------------------------
def set_enabled(harness_path: str | Path | None, pid: str, enabled: bool, confirm: Confirm | None = None) -> dict:
    """Switch a plugin on or off. Switching on one that asks for more than it was allowed asks again."""
    path = _path(harness_path)
    item = _known(path, pid)
    custom = load_custom(path)
    entry = _entry(custom, pid)
    if enabled and not item.builtin:
        manifest = find_manifest(Path(entry.get("path") or item.path))
        check_api(manifest)
        if set(manifest.permissions) - set(entry.get("permissions") or []):
            if confirm is None or not confirm(manifest):
                raise NeedsOk(manifest)
            entry["permissions"] = list(manifest.permissions)
    entry["enabled"] = bool(enabled)
    _save(path, custom)
    return {"id": pid, "enabled": bool(enabled)}


def set_trusted(harness_path: str | Path | None, pid: str, trusted: bool, sure: bool = False) -> dict[str, Any]:
    """Let an installed plugin run as the app itself (``trusted``), or put it back in its box.

    Trusting asks first: without ``sure`` it raises ``NeedsSure`` with the warning to show.
    """
    path = _path(harness_path)
    item = _known(path, pid)
    if item.builtin:
        raise PluginError(f"{item.manifest.name} comes with {NAME}: it always runs as the app")
    if trusted and not sure:
        raise NeedsSure(item)
    custom = load_custom(path)
    entry = _entry(custom, pid)
    if trusted:
        entry["trusted"] = True
    else:
        entry.pop("trusted", None)
    _save(path, custom)
    return {"id": pid, "trusted": bool(trusted)}


def refuse_compiled(manifest: Manifest, folder: Path) -> None:
    """Compiled parts can't be watched in the box: refused unless the plugin asks to run programs."""
    from .host import compiled_words
    from .sandbox import compiled_files

    if "shell" in manifest.permissions:
        return
    found = compiled_files(folder)
    if found:
        raise PluginError(compiled_words(manifest.name, found))


def set_settings(harness_path: str | Path | None, pid: str, values: dict[str, Any]) -> dict[str, Any]:
    """Change some settings (checked against the plugin's schema); returns all of them."""
    path = _path(harness_path)
    item = _known(path, pid)
    clean = item.manifest.coerce_settings(values)
    custom = load_custom(path)
    entry = _entry(custom, pid)
    entry["settings"] = {**(entry.get("settings") or {}), **clean}
    _save(path, custom)
    return get_settings(path, pid)


def remove_plugin(harness_path: str | Path | None, pid: str, purge: bool = False) -> None:
    """Forget a plugin and delete its copied code; its data folder stays unless ``purge``."""
    if pid in BUILTIN_MANIFESTS:
        raise PluginError(f"{BUILTIN_MANIFESTS[pid].name} comes with {NAME}: switch it off instead "
                          f"(`roundtable plugin disable {pid}`)")
    path = _path(harness_path)
    custom = load_custom(path)
    entry = (custom.get("plugins") or {}).get(pid)
    if entry is None:
        raise PluginError(f"there's no plugin {pid!r} in custom.yaml")
    code = Path(str(entry.get("path") or ""))
    if not entry.get("linked") and code.is_dir() and code_home() in code.resolve().parents:
        remove_tree(code)
    if purge:
        remove_tree(plugins_home() / pid)
    del custom["plugins"][pid]
    _save(path, custom)


# -- installing -----------------------------------------------------------------------------
def source_kind(source: str) -> str:
    s = source.strip()
    if Path(s).expanduser().is_dir():
        return "folder"
    if s.startswith(("git+", "git@")) or s.endswith(".git") or (
            s.startswith(("https://", "http://")) and any(h in s for h in ("github.com", "gitlab.com", "codeberg.org"))):
        return "git"
    return "pip"


def _python() -> str:
    """A Python with pip: this one, or (in the Windows app, which has none) one on the computer."""
    if not getattr(sys, "frozen", False):
        return sys.executable
    found = shutil.which("python") or shutil.which("py")
    if not found:
        raise PluginError("Installing this needs Python on this computer (python.org). Or download the plugin's "
                          "folder and add that folder instead.")
    return found


def _run(runner: Runner, cmd: list[str], what: str) -> None:
    res = runner(cmd, capture_output=True, text=True)
    if getattr(res, "returncode", 1) != 0:
        tail = ((getattr(res, "stderr", "") or getattr(res, "stdout", "") or "").strip())[-500:]
        raise PluginError(f"{what} didn't work. Check the name or link and your internet connection.\n{tail}")


def _fetch(source: str, kind: str, tmp: Path, runner: Runner) -> Path:
    """A folder holding the plugin's files (and manifest) to look at before anything is installed."""
    if kind == "folder":
        return Path(source).expanduser().resolve()
    if kind == "git":
        url = source[4:] if source.startswith("git+") else source
        _run(runner, ["git", "clone", "--depth", "1", url, str(tmp / "src")], "Downloading the plugin with git")
        return tmp / "src"
    _run(runner, [_python(), "-m", "pip", "download", "--no-deps", "--only-binary=:all:", "-d", str(tmp / "dl"),
                  source], "Downloading the plugin with pip")
    wheels = sorted((tmp / "dl").glob("*.whl"))
    if not wheels:
        raise PluginError(f"pip found no ready-made package (wheel) for {source}")
    with zipfile.ZipFile(wheels[0]) as z:  # a wheel is a zip: reading it runs nothing
        z.extractall(tmp / "wheel")
    return tmp / "wheel"


def _install(source: str, kind: str, folder: Path, code: Path, runner: Runner, link: bool) -> Path:
    if kind == "pip":
        _run(runner, [_python(), "-m", "pip", "install", "--quiet", "--target", str(code), source],
             "Installing the plugin with pip")
        return code
    if link and kind == "folder":
        return folder
    shutil.copytree(folder, code, ignore=shutil.ignore_patterns(*SKIP))
    deps = project_dependencies(folder)
    if deps:
        _run(runner, [_python(), "-m", "pip", "install", "--quiet", "--target", str(code / ".deps"), *deps],
             "Installing what the plugin needs")
    return code


def add_plugin(harness_path: str | Path | None, source: str, confirm: Confirm, runner: Runner = subprocess.run,
               link: bool = False) -> dict[str, Any]:
    """Install a plugin from a local folder, a git URL or a pip package, once the owner says yes."""
    path = _path(harness_path)
    kind = source_kind(source)
    with tempfile.TemporaryDirectory() as t:
        folder = _fetch(source, kind, Path(t), runner)
        manifest = find_manifest(folder)
        check_api(manifest)
        if manifest.id in BUILTIN_MANIFESTS:
            raise PluginError(f"{manifest.id!r} is the name of a plugin that comes with {NAME}; "
                              "the plugin needs another id")
        refuse_compiled(manifest, folder)
        if not confirm(manifest):
            raise NeedsOk(manifest)
        code = code_home() / manifest.id
        if code.exists() and code.resolve() == folder.resolve():
            link = True  # adding the installed copy again: keep it where it is
        elif code.exists():
            shutil.rmtree(code)
        code.parent.mkdir(parents=True, exist_ok=True)
        where = _install(source, kind, folder, code, runner, link)
        try:
            refuse_compiled(manifest, Path(where))  # what pip brought with it
        except PluginError:
            if Path(where).resolve() == code.resolve() and code.exists():
                shutil.rmtree(code, ignore_errors=True)
            raise
    custom = load_custom(path)
    old = (custom.get("plugins") or {}).get(manifest.id) or {}
    custom.setdefault("plugins", {})[manifest.id] = {
        "enabled": True, "source": source, "path": str(where), "linked": Path(where).resolve() != code.resolve(),
        "version": manifest.version, "permissions": list(manifest.permissions),
        "settings": dict(old.get("settings") or {})}
    _save(path, custom)
    return {**manifest.view(), "path": str(where)}


# -- the app's JSON API (/api/plugins...) --------------------------------------------------
def api(method: str, subpath: str = "", query: dict[str, Any] | None = None, body: Any = None,
        harness_path: str | Path | None = None, cfg: Any = None, runner: Runner = subprocess.run) -> tuple[int, Any]:
    """One entry point for the desktop app. Returns (HTTP status, JSON-able reply).

    GET  /api/plugins                        {"plugins": [...]}
    POST /api/plugins  {"action": "enable"|"disable", "id", "confirmed": [permissions]}
                       {"action": "settings", "id", "values": {...}}
                       {"action": "remove", "id", "purge": false}
                       {"action": "trust", "id", "trusted": true|false, "sure": false}
                       {"action": "add", "source", "confirmed": [permissions], "link": false}
         A reply {"ok": false, "needs_ok": {manifest}} means: show its permissions, ask, and
         send the same request again with "confirmed" set to them. {"ok": false, "needs_sure":
         {"id", "name", "warning"}} means: show the warning, and send it again with "sure": true.
    ANY  /api/plugins/<id>/<path>            the plugin's own routes
    """
    sub = subpath.strip("/")
    harness_path = harness_path or (getattr(cfg, "path", None) if cfg is not None else None)
    try:
        if sub:
            pid, _, rest = sub.partition("/")
            host = cfg.plugin_host() if cfg is not None else _host(_path(harness_path))
            return host.route(method, pid, rest, query, body)
        if method.upper() == "GET":
            return 200, {"plugins": list_plugins(harness_path)}
        reply = _action(harness_path, body or {}, runner)
        if cfg is not None:
            cfg._shared.pop("plugin_host", None)  # the next run loads the plugins afresh
        return 200, {"ok": True, **reply}
    except NeedsOk as e:
        return 200, {"ok": False, "needs_ok": e.manifest.view(),
                     "message": f"{e.manifest.name} asks for: " + (", ".join(
                         p["words"] for p in e.manifest.view()["permissions"]) or "nothing special")}
    except NeedsSure as e:
        return 200, {"ok": False, "needs_sure": {"id": e.item.id, "name": e.item.manifest.name,
                                                 "warning": TRUST_WARNING}, "message": TRUST_WARNING}
    except (PluginError, ValueError, FileNotFoundError) as e:
        return 400, {"ok": False, "error": str(e)}


def _action(harness_path: Any, body: dict[str, Any], runner: Runner) -> dict[str, Any]:
    action, pid = body.get("action"), str(body.get("id") or "")
    confirmed = set(body.get("confirmed") or [])

    def ok(m: Manifest) -> bool:
        return set(m.permissions) <= confirmed

    if action in ("enable", "disable"):
        return set_enabled(harness_path, pid, action == "enable", confirm=ok)
    if action == "settings":
        return {"settings": set_settings(harness_path, pid, dict(body.get("values") or {}))}
    if action == "trust":
        return set_trusted(harness_path, pid, bool(body.get("trusted", True)), sure=bool(body.get("sure")))
    if action == "remove":
        remove_plugin(harness_path, pid, purge=bool(body.get("purge")))
        return {"removed": pid}
    if action == "add":
        return {"added": add_plugin(harness_path, str(body.get("source") or ""), ok, runner=runner,
                                    link=bool(body.get("link")))}
    raise PluginError("action must be enable, disable, settings, trust, remove or add")
