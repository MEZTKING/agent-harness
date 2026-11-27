"""The owner's keys, held in memory for this process only.

The desktop app and Roundtable on the phone load the saved API keys here at start-up instead of
into ``os.environ``, so a command an AI worker runs (which gets a cleaned copy of the environment
anyway, ``harness/safeenv.py``) never inherits them. Reading falls back to ``os.environ``, so the
command line, CI and a key the owner set in their own environment keep working.

The hub's own git credentials (the phone's hub token as git settings) are kept here too
(``set_git_env``): only the hub's own git calls get them (``core/store.py``).
"""

from __future__ import annotations

import os
import threading

_lock = threading.Lock()
_vault: dict[str, str] = {}
_names: set[str] = set()  # key names known to be secret even when no value is stored (providers' api_key_env)
_git_env: dict[str, str] = {}


def put(name: str, value: str | None) -> None:
    """Keep ``value`` under ``name``; an empty value removes it."""
    value = (value or "").strip()
    with _lock:
        _names.add(name)
        if value:
            _vault[name] = value
        else:
            _vault.pop(name, None)


def get(name: str | None, default: str | None = None) -> str | None:
    """The vault's value, else the environment's (set by the owner themselves), else ``default``."""
    if not name:
        return default
    with _lock:
        v = _vault.get(name)
    return v or os.environ.get(name) or default


def has(name: str | None) -> bool:
    return bool(get(name))


def remember_name(*names: str | None) -> None:
    """Mark key names as secret (a provider's ``api_key_env``), so workers never see them."""
    with _lock:
        _names.update(n for n in names if isinstance(n, str) and n)


def names() -> list[str]:
    """Every name known to hold a secret: stored ones and remembered ones."""
    with _lock:
        return sorted(_names | set(_vault))


def values() -> list[str]:
    """Every stored secret value (the hub token's git settings included)."""
    with _lock:
        return [v for v in [*_vault.values(), *_git_env.values()] if v]


def set_git_env(env: dict[str, str] | None) -> None:
    """The git settings the hub's own git calls need (e.g. the phone's hub token); empty clears."""
    with _lock:
        _git_env.clear()
        _git_env.update(env or {})


def git_env() -> dict[str, str]:
    with _lock:
        return dict(_git_env)


def clear() -> None:
    """Forget everything (tests)."""
    with _lock:
        _vault.clear()
        _names.clear()
        _git_env.clear()
