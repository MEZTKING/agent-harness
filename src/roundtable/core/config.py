"""Loading ``hub.yaml``.

Lookup order: explicit path > $HUB_CONFIG > ./hub.yaml > the hub saved by `roundtable connect` > the desktop
app's hub > ~/.roundtable/hub.yaml > ~/.agent-hub/hub.yaml. With ``nearby`` (used by the CLI, the MCP server and
the Claude Code hooks), also ~/agent-hub-data/hub.yaml and an ``agent-hub-data`` checkout next to the current repo,
which is how cloud sessions find the hub without any per-machine setup.
Relative storage paths are resolved against the config file's directory.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .policy import Policy

AGENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")


@dataclass
class AgentSpec:
    id: str
    repo: str = ""
    description: str = ""
    role: str = ""
    tags: list[str] = field(default_factory=list)
    title: str = ""  # the friendly name the owner reads (hub.yaml ``title:``); the id when empty


@dataclass
class HubConfig:
    path: Path
    storage: dict[str, Any]
    agents: dict[str, AgentSpec]
    policy: Policy

    @property
    def base_dir(self) -> Path:
        return self.path.parent


HUB_REPO_DIR = "agent-hub-data"


def saved_hub_pointer() -> Path:
    """File where `roundtable connect` remembers this computer's hub.yaml."""
    from ..desktop import app_home

    return app_home() / "hub-path"


def _pointer_target() -> str | None:
    try:
        return saved_hub_pointer().read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _nearby_candidates() -> list[str]:
    out = [f"~/{HUB_REPO_DIR}/hub.yaml"]
    cwd = Path.cwd()
    for d in [cwd, *cwd.parents][:4]:  # the repo root (or a folder in it) sits next to the hub checkout
        out.append(str(d.parent / HUB_REPO_DIR / "hub.yaml"))
    return out


def find_config(explicit: str | None = None, nearby: bool = False) -> Path:
    from ..desktop import app_home

    candidates = [explicit, os.environ.get("HUB_CONFIG"), "hub.yaml", _pointer_target(),
                  str(app_home() / "config" / "hub.yaml"), "~/.roundtable/hub.yaml", "~/.agent-hub/hub.yaml"]
    if nearby:
        candidates += _nearby_candidates()
    for c in candidates:
        if c and Path(c).expanduser().is_file():
            return Path(c).expanduser().resolve()
    raise FileNotFoundError(
        "No hub config found. Pass --config, set HUB_CONFIG, or run `roundtable init`."
    )


def parse_config(raw: dict[str, Any], path: Path) -> HubConfig:
    agents: dict[str, AgentSpec] = {}
    for agent_id, spec in (raw.get("agents") or {}).items():
        agent_id = str(agent_id)
        if not AGENT_ID_RE.match(agent_id):
            raise ValueError(
                f"invalid agent id {agent_id!r}: use lowercase letters, digits, '-', '_', '.'"
            )
        spec = spec or {}
        agents[agent_id] = AgentSpec(
            id=agent_id,
            repo=spec.get("repo", ""),
            description=spec.get("description", ""),
            role=spec.get("role", ""),
            tags=list(spec.get("tags", [])),
            title=str(spec.get("title") or ""),
        )
    policy = Policy.from_config(raw.get("rules"), raw.get("default_policy", "deny"))
    return HubConfig(path=path, storage=raw.get("storage") or {}, agents=agents, policy=policy)


SHARED_KEYS = ("agents", "rules", "default_policy")


def storage_root(raw: dict[str, Any], path: Path) -> Path | None:
    """The hub data folder a config points at (relative paths against the config's folder)."""
    storage = raw.get("storage") or {}
    if not storage.get("path"):
        return None
    root = Path(str(storage["path"])).expanduser()
    return root if root.is_absolute() else path.parent / root


def with_repository_agents(raw: dict[str, Any], path: Path) -> dict[str, Any]:
    """The hub repository's own hub.yaml is the source of truth for the projects and the rules.

    The desktop app keeps a hub.yaml of its own (where the clone is on this computer); it used to copy the
    agents across once, when the hub was connected, so projects added to the hub later never showed. Now
    the agents, rules and default policy are read from the repository's hub.yaml every time, and the app's
    file only says where the data is."""
    root = storage_root(raw, path)
    repo_yaml = root / "hub.yaml" if root else None
    if not repo_yaml or not repo_yaml.is_file():
        return raw
    try:
        if repo_yaml.resolve() == path.resolve():
            return raw
        repo = yaml.safe_load(repo_yaml.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return raw  # a half-written or broken file: keep what this computer had
    if not isinstance(repo, dict) or not isinstance(repo.get("agents"), dict) or not repo["agents"]:
        return raw
    return {**raw, **{k: repo[k] for k in SHARED_KEYS if k in repo}}


def read_config(path: Path) -> HubConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return parse_config(with_repository_agents(raw, path), path)


def load_config(explicit: str | None = None, nearby: bool = False) -> HubConfig:
    return read_config(find_config(explicit, nearby=nearby))
