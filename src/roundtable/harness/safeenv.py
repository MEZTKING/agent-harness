"""A cleaned environment for every process an AI worker can cause.

A denylist, not an allowlist: Windows tools need SYSTEMROOT, PATHEXT, COMSPEC and the rest, and
build tools need their own settings, so everything is passed on except what could carry the
owner's secrets:

* every key name Roundtable knows (the app's known keys, every provider's ``api_key_env``, every
  name in the in-memory vault, ``core/secrets.py``);
* any name containing KEY, TOKEN, SECRET, PASSWORD, PASSWD or CREDENTIAL (any case);
* git's settings from the environment (``GIT_CONFIG_*``: the phone's hub token travels that way),
  ``GH_TOKEN``, ``GITHUB_TOKEN``, ``GIT_ASKPASS``, ``SSH_ASKPASS``, ``ROUNDTABLE_LAUNCH_TOKEN``;
* any variable whose value is a stored secret, whatever its name.

Then git is told not to ask for a login and not to use a saved one (an empty credential helper),
so a worker's ``git push`` can't borrow the owner's GitHub sign-in.

The honest limit: a command still runs as the owner, so it could read Windows' own credential store
or the keys file directly. The full fix is a sandbox (planned).
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

from ..core import secrets as vault

_SECRET_WORDS = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL", re.I)
_DROP = {"GH_TOKEN", "GITHUB_TOKEN", "GIT_ASKPASS", "SSH_ASKPASS", "ROUNDTABLE_LAUNCH_TOKEN",
         "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"}
# names that match the words above but hold nothing secret, and that tools need (Windows' and others')
_KEEP = {"KEYBOARD_LAYOUT"}
_MIN_SECRET_LEN = 6  # a short value ("1", "true") is never treated as a secret by value

NO_GIT_LOGIN = {
    "GIT_TERMINAL_PROMPT": "0",
    "GCM_INTERACTIVE": "never",
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "credential.helper",
    "GIT_CONFIG_VALUE_0": "",
}


def _known_names() -> set[str]:
    names = set(vault.names())
    try:
        from ..desktop import KNOWN_KEYS

        names.update(KNOWN_KEYS)
    except Exception:  # noqa: BLE001 - the desktop module is optional here
        pass
    return {n.upper() for n in names}


def is_secret_name(name: str, known: set[str] | None = None) -> bool:
    up = name.upper()
    if up in _KEEP:
        return False
    if up in _DROP or up.startswith("GIT_CONFIG_"):
        return True
    if up in (known if known is not None else _known_names()):
        return True
    return bool(_SECRET_WORDS.search(up))


def clean_env(extra: Mapping[str, str] | None = None, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """A copy of the environment (``base``, default ``os.environ``) without secrets, with git's
    logins turned off and ``extra`` (the project's or a tool server's own declared settings) on top."""
    known = _known_names()
    secret_values = {v for v in vault.values() if len(v) >= _MIN_SECRET_LEN}
    src = os.environ if base is None else base
    env = {k: v for k, v in src.items() if not is_secret_name(k, known) and v not in secret_values}
    env.update(NO_GIT_LOGIN)
    for k, v in (extra or {}).items():
        env[str(k)] = str(v)
    return env
