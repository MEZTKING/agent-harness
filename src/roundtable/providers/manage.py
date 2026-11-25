"""Add, remove, test and assign providers - shared by the app (Settings) and the CLI.

Changes are written to custom.yaml next to harness.yaml (harness.yaml is never
rewritten) and validated by loading the merged config before saving.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from ..harness.config import (ModelRef, find_config, load_custom, merge_custom, parse_config, save_custom)
from .base import ProviderError
from .catalog import PRESETS, preset_block, valid_provider_id


def _raw(harness_path: Path) -> dict[str, Any]:
    return yaml.safe_load(harness_path.read_text(encoding="utf-8")) or {}


def _validate(harness_path: Path, custom: dict[str, Any]) -> None:
    parse_config(merge_custom(_raw(harness_path), custom), harness_path)


def default_key_env(pid: str) -> str:
    return pid.upper().replace("-", "_") + "_API_KEY"


def list_providers(harness_path: str | Path | None = None) -> list[dict[str, Any]]:
    path = find_config(str(harness_path) if harness_path else None)
    base = _raw(path).get("providers") or {}
    custom = load_custom(path).get("providers") or {}
    out = []
    for pid, spec in {**custom, **base}.items():
        spec = spec or {}
        env = spec.get("api_key_env", "")
        out.append({
            "id": pid, "type": spec.get("type"), "base_url": spec.get("base_url", ""), "api_key_env": env,
            "preset": spec.get("preset", ""), "source": "harness.yaml" if pid in base else "custom.yaml",
            "key_set": bool(env and os.environ.get(env)), "needs_key": bool(env),
            "name": PRESETS.get(spec.get("preset", ""), {}).get("name", pid),
        })
    return sorted(out, key=lambda p: p["id"])


def add_provider(harness_path: str | Path | None, preset: str, pid: str | None = None, base_url: str | None = None,
                 api_key_env: str | None = None, **extra) -> dict[str, Any]:
    """Add a provider from the catalog (or `custom`/`plugin`) to custom.yaml."""
    path = find_config(str(harness_path) if harness_path else None)
    pid = (pid or preset).strip().lower()
    if not valid_provider_id(pid):
        raise ValueError("provider id: start with a letter; use a-z, 0-9, - or _ (max 40)")
    if preset == "plugin":
        if ":" not in str(extra.get("class", "")):
            raise ValueError("plugin providers need class: 'my_file.py:MyProvider'")
        block: dict[str, Any] = {"type": "plugin", "class": extra["class"], "preset": "plugin"}
        if extra.get("options"):
            block["options"] = extra["options"]
    else:
        if preset == "custom" and not api_key_env:
            api_key_env = default_key_env(pid)
        block = preset_block(preset, base_url=base_url, api_key_env=api_key_env)
        for k in ("auth_header", "auth_prefix", "headers", "query"):
            if extra.get(k):
                block[k] = extra[k]
    if pid in (_raw(path).get("providers") or {}):
        raise ValueError(f"{pid!r} is already defined in harness.yaml; pick another id")
    custom = load_custom(path)
    custom.setdefault("providers", {})[pid] = block
    _validate(path, custom)
    save_custom(path, custom)
    return {"id": pid, **block}


def remove_provider(harness_path: str | Path | None, pid: str) -> None:
    path = find_config(str(harness_path) if harness_path else None)
    if pid in (_raw(path).get("providers") or {}):
        raise ValueError(f"{pid!r} is defined in harness.yaml; remove it there (Settings > harness.yaml)")
    custom = load_custom(path)
    if pid not in (custom.get("providers") or {}):
        raise ValueError(f"no provider {pid!r} in custom.yaml")
    merged = merge_custom(_raw(path), custom)
    users = [r for r, spec in (merged.get("roles") or {}).items()
             if any(str(m).split("/", 1)[0] == pid for m in [spec.get("model", "")] + list(spec.get("fallback") or []))]
    if users:
        raise ValueError(f"{pid!r} is still used by role(s) {', '.join(users)}; switch them to another model first")
    del custom["providers"][pid]
    _validate(path, custom)
    save_custom(path, custom)


def set_role_models(harness_path: str | Path | None, role: str, models: list[str], kind: str | None = None,
                    description: str | None = None) -> dict[str, Any]:
    """Choose which model (and fallbacks) a role uses; creates the role if it's new."""
    path = find_config(str(harness_path) if harness_path else None)
    models = [m.strip() for m in models if m and m.strip()]
    if not models:
        raise ValueError("pick at least one model")
    for m in models:
        ModelRef.parse(m)
    custom = load_custom(path)
    entry = {"model": models[0], "fallback": models[1:]}
    if role not in ((_raw(path).get("roles") or {})):
        if kind:
            entry["kind"] = kind
        if description:
            entry["description"] = description
    custom.setdefault("roles", {})[role] = entry
    _validate(path, custom)
    save_custom(path, custom)
    return entry


def provider_models(cfg, pid: str) -> list[str]:
    provider = cfg.provider(pid)
    if not hasattr(provider, "list_models"):
        raise ProviderError(f"{pid}: this provider can't list its models; type the model name instead")
    return provider.list_models()


def test_provider(cfg, pid: str) -> dict[str, Any]:
    """Check a provider answers: list its models (free on every provider that supports it)."""
    try:
        models = provider_models(cfg, pid)
        return {"ok": True, "models": len(models), "sample": models[:12]}
    except (ProviderError, ValueError) as e:
        return {"ok": False, "error": str(e)}
