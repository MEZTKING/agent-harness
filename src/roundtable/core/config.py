"""Loading ``hub.yaml``.

Lookup order: explicit path > $HUB_CONFIG > ./hub.yaml > ~/.roundtable/hub.yaml > ~/.agent-hub/hub.yaml
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


@dataclass
class HubConfig:
    path: Path
    storage: dict[str, Any]
    agents: dict[str, AgentSpec]
    policy: Policy

    @property
    def base_dir(self) -> Path:
        return self.path.parent


def find_config(explicit: str | None = None) -> Path:
    candidates = [explicit, os.environ.get("HUB_CONFIG"), "hub.yaml", "~/.roundtable/hub.yaml", "~/.agent-hub/hub.yaml"]
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
        )
    policy = Policy.from_config(raw.get("rules"), raw.get("default_policy", "deny"))
    return HubConfig(path=path, storage=raw.get("storage") or {}, agents=agents, policy=policy)


def load_config(explicit: str | None = None) -> HubConfig:
    path = find_config(explicit)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return parse_config(raw, path)
