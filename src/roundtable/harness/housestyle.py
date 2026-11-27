"""The owner's house style: how agents write for the owner (parity MD-27).

    style: {on: true, text: "..."}     in custom.yaml (the app's choice), over harness.yaml's ``style:``

Up to 1,200 characters, added to every system prompt under "How to write for the owner" by
``CharterStage._style_system``. Only the owner changes it: the lab never writes custom.yaml.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from .config import section

MAX_CHARS = 1200
DEFAULT_TEXT = "Short, plain and factual. Say what was done, what was not, and what to do next."
HEADING = "## How to write for the owner"
DEFAULTS: dict[str, Any] = {"on": True, "text": DEFAULT_TEXT}

_cache: dict[str, tuple[float, Any]] = {}


def clean(value: Any, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """``{on, text}`` in its right shape (raises ValueError with plain words)."""
    out = dict(base or DEFAULTS)
    if value is None:
        return out
    if not isinstance(value, dict):
        raise ValueError("the house style must be a setting with on and text")
    if "on" in value:
        on = value["on"]
        if isinstance(on, str):
            on = on.strip().lower() in ("1", "true", "yes", "on")
        out["on"] = bool(on)
    if "text" in value:
        text = value["text"]
        if text is None:
            text = ""
        if not isinstance(text, str):
            raise ValueError("the house style's text must be words")
        text = "".join(ch for ch in unicodedata.normalize("NFC", text)
                       if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) > MAX_CHARS:
            raise ValueError(f"the house style can be at most {MAX_CHARS} characters (it is {len(text)})")
        out["text"] = text
    return out


def _custom_style(path: Path) -> Any:
    p = path.parent / "custom.yaml"
    try:
        stamp = p.stat().st_mtime
    except OSError:
        return None
    hit = _cache.get(str(p))
    if hit and hit[0] == stamp:
        return hit[1]
    from .config import load_custom

    try:
        mine = load_custom(path).get("style")
    except Exception:  # noqa: BLE001 - an unreadable custom.yaml is reported elsewhere
        mine = None
    _cache[str(p)] = (stamp, mine)
    return mine


def settings(cfg: Any) -> dict[str, Any]:
    """The house style: the default, harness.yaml's ``style:``, then the app's (custom.yaml)."""
    out = dict(DEFAULTS)
    if cfg is None:
        return out
    try:
        out = clean(section(cfg, "style") or None, out)
    except ValueError:
        pass
    path = getattr(cfg, "path", None)
    if path:
        mine = _custom_style(Path(path))
        if isinstance(mine, dict):
            try:
                out = clean(mine, out)
            except ValueError:
                pass
    return out


def block(cfg: Any) -> str:
    """The part added to the system prompt ("" when off or empty)."""
    s = settings(cfg)
    if not s["on"] or not s["text"].strip():
        return ""
    return f"{HEADING}\n{s['text'].strip()}"


def save(path: Path, body: dict[str, Any]) -> dict[str, Any]:
    """The owner's change, kept in custom.yaml (harness.yaml is never rewritten). ``reset``: the default."""
    from .config import load_custom, save_custom

    custom = load_custom(path)
    if body.get("reset"):
        mine = dict(DEFAULTS)
    else:
        mine = clean({k: v for k, v in body.items() if k in ("on", "text")},
                     clean(custom.get("style") if isinstance(custom.get("style"), dict) else None))
    custom["style"] = {"on": mine["on"], "text": mine["text"]}
    save_custom(path, custom)
    _cache.pop(str(path.parent / "custom.yaml"), None)
    return custom["style"]
