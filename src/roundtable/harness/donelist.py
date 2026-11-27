"""The done list: what a person can do with the finished thing, and whether each item was shown to work.

Kept in ``<project>/.harness/done.json``:

    {"goal_index": 0,
     "items":  [{id, text, how, must, by, steps?, command?, path?, part?, state, words, evidence}],
     "rounds": [{at, item, passed, words, by}]}

``state`` is ``open`` (not checked yet), ``passed``, ``failed`` or ``unchecked`` (looked at but no answer:
``record(..., passed=None)``). The five functions below are the frozen seam the stages build on (step 0 of
wave 5); d2-done owns this file and adds to it, never changing their signatures.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from ..core.models import utcnow

HOWS = ("journey", "page_opens", "command", "file_exists", "play", "look", "owner")
BYS = ("planner", "kind", "owner")
STATES = ("open", "passed", "failed", "unchecked")
OPTIONAL = ("steps", "command", "path", "part")
_LOCK = threading.RLock()  # several tasks at once may record results


def path(root) -> Path:
    """Where the done list lives: ``<project>/.harness/done.json``."""
    return Path(root) / ".harness" / "done.json"


def _empty() -> dict[str, Any]:
    return {"goal_index": 0, "items": [], "rounds": []}


def read(root) -> dict[str, Any]:
    """The done list ({"goal_index", "items", "rounds"}); an empty one when there is none or it can't be read."""
    p = path(root)
    with _LOCK:
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
        except (OSError, ValueError):
            data = None
    if not isinstance(data, dict):
        return _empty()
    out = _empty()
    out["goal_index"] = int(data.get("goal_index") or 0)
    out["items"] = [i for i in data.get("items") or [] if isinstance(i, dict) and i.get("id")]
    out["rounds"] = [r for r in data.get("rounds") or [] if isinstance(r, dict)]
    return out


def _write(root, data: dict[str, Any]) -> None:
    p = path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(".done.json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(p)


def add_item(root, item: dict[str, Any]) -> dict[str, Any]:
    """Add one item ({id?, text, how, must, by, steps?, command?, path?, part?}) and return it as kept.

    Without an id it gets the next ``D<n>``; an item with an id already there replaces that one (its state
    starts again). ``text`` is required; an unknown ``how`` is kept as ``look`` (a person looks), an unknown
    ``by`` as ``planner``."""
    if not isinstance(item, dict):
        raise ValueError("a done-list item is a set of settings")
    text = " ".join(str(item.get("text") or "").split())
    if not text:
        raise ValueError("a done-list item needs its words: what a person can do with the finished thing")
    with _LOCK:
        data = read(root)
        ids = {i["id"] for i in data["items"]}
        iid = str(item.get("id") or "").strip()
        if not iid:
            n = len(data["items"]) + 1
            while f"D{n}" in ids:
                n += 1
            iid = f"D{n}"
        how = item.get("how") if item.get("how") in HOWS else "look"
        kept: dict[str, Any] = {
            "id": iid, "text": text[:500], "how": how, "must": bool(item.get("must", True)),
            "by": item.get("by") if item.get("by") in BYS else "planner",
            "state": "open", "words": "", "evidence": {},
        }
        for k in OPTIONAL:
            if item.get(k) not in (None, "", []):
                kept[k] = item[k]
        data["items"] = [i for i in data["items"] if i["id"] != iid] + [kept]
        _write(root, data)
    return kept


def record(root, item_id, passed: bool | None, words: str, evidence: dict | None = None, by: str = "") -> dict:
    """Write one check's result on an item: passed (True), failed (False) or no answer (None, "unchecked").
    Returns the item as it now stands; a ``KeyError`` when there is no such item."""
    with _LOCK:
        data = read(root)
        item = next((i for i in data["items"] if i["id"] == str(item_id)), None)
        if item is None:
            raise KeyError(f"no done-list item {item_id!r}")
        item["state"] = "unchecked" if passed is None else ("passed" if passed else "failed")
        item["words"] = str(words or "")[:1000]
        item["evidence"] = dict(evidence or {})
        if by:
            item["checked_by"] = str(by)
        item["checked_at"] = utcnow()
        data["rounds"].append({"at": item["checked_at"], "item": item["id"], "passed": passed,
                               "words": item["words"][:300], "by": str(by or "")})
        _write(root, data)
    return item


def verdict(root) -> dict[str, Any]:
    """Can the project be called done? {"done": bool, "failed": [ids], "unchecked": [ids]}.

    Only the ``must`` items count: done when every one of them passed. A list with no items doesn't stop
    anything (an old project, a plan from before the done list)."""
    items = [i for i in read(root)["items"] if i.get("must", True)]
    failed = [i["id"] for i in items if i.get("state") == "failed"]
    unchecked = [i["id"] for i in items if i.get("state") in ("open", "unchecked")]
    return {"done": not failed and not unchecked, "failed": failed, "unchecked": unchecked}
