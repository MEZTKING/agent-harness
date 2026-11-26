"""A plugin's manifest: who made it, what it hooks into, what it asks for, its settings.

Written as ``roundtable-plugin.toml`` in the plugin's folder (or inside its package, for one
installed with pip), or as ``[tool.roundtable.plugin]`` in its ``pyproject.toml``::

    id = "cost-log"
    name = "Cost log"
    version = "1.0.0"
    description = "Writes each model call's tokens and cost to a spreadsheet file."
    author = "Someone"
    licence = "MIT"
    homepage = "https://example.org/cost-log"
    entry = "cost_log:plugin"          # module:object
    api = 1                            # the plugin API version it needs
    hooks = ["after_model_call"]
    permissions = []                   # network, files, shell, secrets:<host>

    [settings.file_name]
    type = "string"                    # string, integer, number or boolean
    default = "calls.csv"
    description = "The file's name in the plugin's folder."
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .api import API_VERSION, HOOKS, PERMISSIONS, SECRET_PERMISSION, PluginError, permission_words

MANIFEST_FILE = "roundtable-plugin.toml"
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
SETTING_TYPES = {"string": str, "integer": int, "number": float, "boolean": bool}
SKIP = {".git", "__pycache__", ".venv", "venv", "node_modules", ".deps"}


@dataclass
class Setting:
    key: str
    type: str
    default: Any
    description: str = ""

    def coerce(self, value: Any) -> Any:
        """The value as this setting's type; words like "yes" and "off" work for true/false."""
        if self.type == "boolean":
            if isinstance(value, str):
                v = value.strip().lower()
                if v in ("true", "yes", "on", "1"):
                    return True
                if v in ("false", "no", "off", "0"):
                    return False
                raise ValueError(f"{self.key} must be true or false")
            return bool(value)
        try:
            return SETTING_TYPES[self.type](value)
        except (TypeError, ValueError):
            raise ValueError(f"{self.key} must be {'a whole number' if self.type == 'integer' else 'a number'}")

    def view(self, value: Any) -> dict[str, Any]:
        return {"key": self.key, "type": self.type, "default": self.default, "value": value,
                "description": self.description}


@dataclass
class Manifest:
    id: str
    name: str
    version: str
    description: str
    entry: str
    api: int = API_VERSION
    author: str = ""
    licence: str = ""
    homepage: str = ""
    hooks: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    settings: dict[str, Setting] = field(default_factory=dict)

    def defaults(self) -> dict[str, Any]:
        return {k: s.default for k, s in self.settings.items()}

    def coerce_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        unknown = sorted(set(values) - set(self.settings))
        if unknown:
            raise ValueError(f"{self.name} has no setting {', '.join(unknown)}; "
                             f"it has: {', '.join(self.settings) or 'none'}")
        return {k: self.settings[k].coerce(v) for k, v in values.items()}

    def view(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "version": self.version, "description": self.description,
                "author": self.author, "licence": self.licence, "homepage": self.homepage, "api": self.api,
                "hooks": list(self.hooks),
                "permissions": [{"id": p, "words": permission_words(p)} for p in self.permissions]}


def _need(raw: dict[str, Any], key: str) -> str:
    v = raw.get(key)
    if not isinstance(v, str) or not v.strip():
        raise PluginError(f"the plugin's manifest needs {key} (text)")
    return v.strip()


def _settings(raw: Any) -> dict[str, Setting]:
    out = {}
    for key, spec in (raw or {}).items():
        spec = spec or {}
        kind = spec.get("type", "string")
        if kind not in SETTING_TYPES:
            raise PluginError(f"setting {key}: type must be one of {', '.join(SETTING_TYPES)}")
        s = Setting(str(key), kind, None, str(spec.get("description", "")))
        s.default = s.coerce(spec["default"]) if "default" in spec else SETTING_TYPES[kind]()
        out[str(key)] = s
    return out


def parse_manifest(raw: dict[str, Any]) -> Manifest:
    """Check a manifest (a dict read from TOML, or a built-in's) and return it."""
    pid = _need(raw, "id")
    if not ID_RE.match(pid):
        raise PluginError(f"plugin id {pid!r}: use 2 to 40 of a-z, 0-9 and -, starting with a letter")
    entry = _need(raw, "entry")
    if ":" not in entry:
        raise PluginError(f"{pid}: entry must be 'module:object', e.g. 'my_plugin:plugin'")
    try:
        api = int(raw.get("api", API_VERSION))
    except (TypeError, ValueError):
        raise PluginError(f"{pid}: api must be a whole number (this Roundtable speaks {API_VERSION})")
    if api < 1:
        raise PluginError(f"{pid}: api must be 1 or more")
    hooks = [str(h) for h in raw.get("hooks") or []]
    bad = [h for h in hooks if h not in HOOKS]
    if bad:
        raise PluginError(f"{pid}: unknown hook(s) {', '.join(bad)}; the hooks are {', '.join(HOOKS)}")
    perms = [str(p) for p in raw.get("permissions") or []]
    bad = [p for p in perms if p not in PERMISSIONS and not (p.startswith(SECRET_PERMISSION) and len(p) > 8)]
    if bad:
        raise PluginError(f"{pid}: unknown permission(s) {', '.join(bad)}; "
                          f"use {', '.join(PERMISSIONS)} or secrets:<host>")
    return Manifest(id=pid, name=_need(raw, "name"), version=str(raw.get("version") or "0"),
                    description=str(raw.get("description", "")).strip(), entry=entry, api=api,
                    author=str(raw.get("author", "")), licence=str(raw.get("licence") or raw.get("license") or ""),
                    homepage=str(raw.get("homepage", "")), hooks=hooks, permissions=perms,
                    settings=_settings(raw.get("settings")))


def check_api(m: Manifest) -> None:
    if m.api > API_VERSION:
        raise PluginError(f"{m.name} needs a newer Roundtable Hold (plugin API {m.api}; this one has "
                          f"{API_VERSION}). Update Roundtable Hold, then try again.")


def _toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        try:
            import tomli as tomllib
        except ModuleNotFoundError:
            raise PluginError("reading a plugin's manifest needs Python 3.11 or newer (or the tomli package)")
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise PluginError(f"{path.name} could not be read: {e}")


def _manifest_in(folder: Path) -> dict[str, Any] | None:
    if (folder / MANIFEST_FILE).is_file():
        return _toml(folder / MANIFEST_FILE)
    if (folder / "pyproject.toml").is_file():
        table = ((_toml(folder / "pyproject.toml").get("tool") or {}).get("roundtable") or {}).get("plugin")
        if table:
            return table
    return None


def find_manifest(folder: Path) -> Manifest:
    """The manifest in a folder, its src/ or one package folder down (where pip puts it)."""
    folder = Path(folder)
    places = [folder, folder / "src"]
    for base in (folder, folder / "src"):
        if base.is_dir():
            places += sorted(p for p in base.iterdir() if p.is_dir() and p.name not in SKIP)
    for place in places:
        raw = _manifest_in(place) if place.is_dir() else None
        if raw is not None:
            return parse_manifest(raw)
    raise PluginError(f"no plugin found in {folder}: it needs a {MANIFEST_FILE} file "
                      "(or [tool.roundtable.plugin] in pyproject.toml)")


def project_dependencies(folder: Path) -> list[str]:
    """What a plugin folder's pyproject.toml says it needs from pip ([project] dependencies)."""
    p = Path(folder) / "pyproject.toml"
    if not p.is_file():
        return []
    deps = (_toml(p).get("project") or {}).get("dependencies") or []
    return [str(d) for d in deps if not str(d).lower().startswith("roundtable")]
