"""The done list: what a person can do with the finished thing, and whether each item was shown to work.

Kept in ``<project>/.harness/done.json``:

    {"goal_index": 0,
     "items":  [{id, text, how, must, by, steps?, command?, path?, part?, state, words, evidence}],
     "rounds": [{at, item, passed, words, by}]}

``state`` is ``open`` (not checked yet), ``passed``, ``failed`` or ``unchecked`` (looked at but no answer:
``record(..., passed=None)``). ``path``, ``read``, ``add_item``, ``record`` and ``verdict`` are the frozen seam
the stages build on (step 0 of wave 5): their signatures never change. The rest is for the done stage
(donestage.py), the plan document, the API and the owner's edits.

An item, besides the fields above, may carry ``serves`` (the task ids that make it work, from the planner) and
``kind_id`` (the kind's proof check it stands for). A ``journey`` item's ``steps`` use a fixed vocabulary that
the finish stage runs (``JOURNEY_STEPS``): each step is a mapping with one of those words as its key, such as
``{"open": "/"}``, ``{"click": "Start"}`` (by its visible text), ``{"type": "Ada", "into": "Name"}``,
``{"press": "Enter"}``, ``{"wait": 2}``, ``{"expect_text": "Game over"}``, ``{"expect_no_errors": true}``.
A journey with any other step can't be run by a machine, so it is kept as ``look`` (a person looks).
"""

from __future__ import annotations

import base64
import json
import re
import threading
from pathlib import Path
from typing import Any

from ..core.models import utcnow

HOWS = ("journey", "page_opens", "command", "file_exists", "play", "look", "owner")
BYS = ("planner", "kind", "owner")
STATES = ("open", "passed", "failed", "unchecked")
OPTIONAL = ("steps", "command", "path", "part", "serves", "kind_id")
JOURNEY_STEPS = ("open", "click", "type", "press", "wait", "expect_text", "expect_no_errors")
MAX_ITEMS = 12  # the planner gives 3 to 8; the kind's checks and the owner's own come on top
HOW_WORDS = {"journey": "a person's steps, tried by the harness", "page_opens": "it opens with no errors",
             "command": "a command that must succeed", "file_exists": "a file that must be there",
             "play": "someone plays it", "look": "a person (or a model that can see) looks", "owner": "you say so"}
# the kind's proof checks (kinds/model.PROOF_HOW) as done-list items
KIND_HOW = {"page_opens": "page_opens", "command": "command", "play": "play", "picture": "look",
            "file_exists": "file_exists"}
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


# -- the planner's items, cleaned --------------------------------------------------------------------------------
def clean_steps(steps: Any) -> list[dict[str, Any]] | None:
    """A journey's steps in the fixed vocabulary, or None when any step is something a machine can't do.

    Takes ``{"click": "Start"}`` (the vocabulary word as the key) or ``{"do": "click", "what": "Start"}``."""
    if not isinstance(steps, list) or not steps:
        return None
    out: list[dict[str, Any]] = []
    for st in steps[:30]:
        if not isinstance(st, dict):
            return None
        if "do" in st:
            verb, val = str(st.get("do") or "").strip(), st.get("what", st.get("text", ""))
            rest = set(st) - {"do", "what", "text", "into"}
        else:
            verbs = [k for k in st if k in JOURNEY_STEPS]
            if len(verbs) != 1:
                return None
            verb, val = verbs[0], st[verbs[0]]
            rest = set(st) - {verb, "into"}
        if verb not in JOURNEY_STEPS or rest:
            return None
        step: dict[str, Any] = {}
        if verb == "expect_no_errors":
            step[verb] = True
        elif verb == "wait":
            try:
                step[verb] = max(0.0, min(float(val), 60.0))  # seconds
            except (TypeError, ValueError):
                text = " ".join(str(val or "").split())[:300]  # or until these words show
                if not text:
                    return None
                step[verb] = text
        else:
            text = "" if val is True or val is None else " ".join(str(val).split())[:300]
            if not text:
                if verb != "open":
                    return None
                text = "/"
            step[verb] = text
        if verb == "type" and st.get("into"):
            step["into"] = " ".join(str(st["into"]).split())[:200]
        out.append(step)
    return out


def clean_item(raw: Any, by: str = "planner") -> dict[str, Any] | None:
    """One done-list item from what the planner (or the owner) wrote; None when it has no words.

    A journey whose steps a machine can't run is kept as ``look``; a ``file_exists`` with no path too. A
    ``command`` item with no command means the project's own check command."""
    if isinstance(raw, str):
        raw = {"text": raw}
    if not isinstance(raw, dict):
        return None
    text = " ".join(str(raw.get("text") or "").split())[:500]
    if not text:
        return None
    how = raw.get("how") if raw.get("how") in HOWS else "look"
    item: dict[str, Any] = {"text": text, "how": how, "must": bool(raw.get("must", True)),
                            "by": by if by in BYS else "planner"}
    if str(raw.get("id") or "").strip():
        item["id"] = str(raw["id"]).strip()[:20]
    for k in ("command", "path", "part", "kind_id"):
        v = raw.get(k)
        if isinstance(v, str) and v.strip():
            item[k] = v.strip()[:500]
    if how == "journey":
        steps = clean_steps(raw.get("steps"))
        if steps:
            item["steps"] = steps
        else:
            item["how"] = "look"
    if item["how"] == "file_exists" and not item.get("path"):
        item["how"] = "look"
    serves = raw.get("serves")
    if isinstance(serves, list):
        got = [str(x).strip()[:40] for x in serves if str(x).strip()]
        if got:
            item["serves"] = got[:20]
    return item


def from_kind(proof: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The kind's proof checks (``kinds.proof_plan``) as done-list items, ``by: kind``. A check marked
    optional, or one that can't be checked yet (``not_yet``), is listed but isn't a must."""
    out = []
    for p in proof or []:
        if not isinstance(p, dict) or not str(p.get("words") or "").strip():
            continue
        raw = {"text": p["words"], "how": KIND_HOW.get(p.get("how"), "look"), "kind_id": str(p.get("id") or ""),
               "must": not p.get("optional") and p.get("status", "trial") != "not_yet"}
        for k in ("command", "path"):
            if isinstance(p.get(k), str) and p[k].strip():
                raw[k] = p[k]
        item = clean_item(raw, by="kind")
        if item:
            out.append(item)
    return out


def _key(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def _same_check(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Two items that would be checked the same way: the same words, or the same command, path or page."""
    if _key(a["text"]) == _key(b["text"]):
        return True
    if a["how"] != b["how"]:
        return False
    if a["how"] == "command":
        return a.get("command", "") == b.get("command", "")
    if a["how"] == "file_exists":
        return bool(a.get("path")) and a.get("path") == b.get("path")
    return a["how"] == "page_opens"


def merge(planner: list[dict[str, Any]], kind: list[dict[str, Any]], old: list[dict[str, Any]],
          removed: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The done list for a plan: the owner's own items (kept word for word), then the planner's, then the
    kind's checks no planner item already covers (a planner item that does takes the check's ``kind_id``).

    An item that was there before with the same words keeps its id and its result; a new one gets the next
    free ``D<n>``. What the owner took off the list (``removed``) doesn't come back."""
    gone = {_key(r.get("text", "")) for r in removed or []} | {r["kind_id"] for r in removed or [] if r.get("kind_id")}
    owner = [dict(i) for i in old if i.get("by") == "owner"]
    out: list[dict[str, Any]] = list(owner)
    for p in planner[:8]:
        if _key(p["text"]) in gone or any(_key(p["text"]) == _key(o["text"]) for o in out):
            continue
        out.append(dict(p))
    for k in kind:
        if _key(k["text"]) in gone or k.get("kind_id") in gone:
            continue
        twin = next((o for o in out if o.get("by") != "owner" and _same_check(o, k)), None)
        if twin is not None:
            twin.setdefault("kind_id", k.get("kind_id"))
            continue
        if any(_key(k["text"]) == _key(o["text"]) for o in out):
            continue
        out.append(dict(k))
    out = out[:MAX_ITEMS + len(owner)]
    before = {_key(i.get("text", "")): i for i in old}
    used = {str(i.get("id")) for i in old} | {str(i["id"]) for i in owner}
    taken: set[str] = {str(i["id"]) for i in owner}
    n = 1
    for item in out:
        if item.get("by") == "owner":
            continue
        prev = before.get(_key(item["text"]))
        item.pop("id", None)
        if prev and prev.get("id") not in taken and prev.get("by") != "owner":
            item["id"] = prev["id"]
            if prev.get("how") == item["how"]:
                for k in ("state", "words", "evidence", "checked_at", "checked_by"):
                    if k in prev:
                        item[k] = prev[k]
        else:
            while f"D{n}" in used or f"D{n}" in taken:
                n += 1
            item["id"] = f"D{n}"
            used.add(item["id"])
        taken.add(item["id"])
    for item in out:
        item.setdefault("state", "open")
        item.setdefault("words", "")
        item.setdefault("evidence", {})
    return out


def write_list(root, goal_index: int, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep ``items`` as the done list of goal ``goal_index``; the checks' history goes when the goal changes."""
    with _LOCK:
        data = read(root)
        if data["goal_index"] != int(goal_index):
            data["rounds"] = []
        data["goal_index"] = int(goal_index)
        data["items"] = [dict(i) for i in items]
        _write(root, data)
    return data


def public(item: dict[str, Any]) -> dict[str, Any]:
    """The item as the plan document keeps it: what it is, not how its check went."""
    return {k: v for k, v in item.items() if k not in ("state", "words", "evidence", "checked_at", "checked_by")}


def reopen(root, ids: list[str], why: str = "") -> list[str]:
    """Items to check again (after a fix): back to ``open``. Returns the ids that were there."""
    done: list[str] = []
    with _LOCK:
        data = read(root)
        for i in data["items"]:
            if i["id"] in ids:
                i.update(state="open", words=str(why or "")[:300], evidence={})
                done.append(i["id"])
        if done:
            _write(root, data)
    return done


# -- reading it -------------------------------------------------------------------------------------------------
MARK = {"passed": "✓", "failed": "✗", "unchecked": "?", "open": "·"}
MARK_WORDS = {"passed": "It was shown to work", "failed": "It was tried and doesn't work yet",
              "unchecked": "It couldn't be checked here", "open": "Not checked yet"}


def summary(root, finished: bool = False) -> dict[str, Any]:
    """The done list for the app and the phone: {items, checked, passed, failed, unchecked, words, rounds}.

    ``unchecked`` counts both "not checked yet" and "couldn't be checked here": neither ever shows a tick.
    ``words`` is the one line ("Done when: 5 of 7 ✓"); ``finished``: the project has been called done."""
    data = read(root)
    items = data["items"]
    count = lambda s: sum(1 for i in items if i.get("state") == s)  # noqa: E731
    passed, failed = count("passed"), count("failed")
    unchecked = len(items) - passed - failed
    return {"goal_index": data["goal_index"], "items": items, "checked": passed + failed, "passed": passed,
            "failed": failed, "unchecked": unchecked, "must_failed": verdict(root)["failed"],
            "words": words(len(items), passed, failed, unchecked, finished), "rounds": data["rounds"][-50:]}


def words(n: int, passed: int, failed: int, unchecked: int, finished: bool = False) -> str:
    if not n:
        return "No done list yet."
    if failed:
        return f"Done when: {passed} of {n} ✓ · {failed} {'doesn’t' if failed == 1 else 'don’t'} work yet"
    if finished:
        if not unchecked:
            return f"Finished: all {n} checked ✓"
        return f"Finished: {passed} of {n} checked, {unchecked} couldn’t be checked here"
    if not passed:
        return f"Done when: {n} {'thing works' if n == 1 else 'things work'} · none checked yet"
    return f"Done when: {passed} of {n} ✓" + (f" · {unchecked} not checked yet" if unchecked else "")


def for_task(items: list[dict[str, Any]], task: Any) -> list[dict[str, Any]]:
    """The items a task serves: the planner said so (``serves``), the same part, or the item it fixes."""
    tid, part, fix = getattr(task, "id", ""), getattr(task, "part", ""), getattr(task, "fix_of", "")
    return [i for i in items if tid in (i.get("serves") or []) or (part and i.get("part") == part)
            or (fix and i.get("id") == fix)]


def markdown(doc: dict[str, Any] | None) -> list[str]:
    """The plan's "Done when" section (plandoc.render_markdown), ids in braces for the phone's commands."""
    items = (doc or {}).get("done_list") or []
    if not items:
        return []
    out = ["## Done when"]
    for i in items:
        tail = [] if i.get("must", True) else ["nice to have"]
        if i.get("by") == "owner":
            tail.append("yours")
        out.append(f"- {i['text']}" + (f" ({', '.join(tail)})" if tail else "") + f" {{{i['id']}}}")
    return out + [""]


def context(doc: dict[str, Any] | None) -> str:
    """What every task and review is told (plandoc.context_text): what "finished" means for this plan."""
    items = (doc or {}).get("done_list") or []
    if not items:
        return ""
    lines = ["Done when (what a person must be able to do with the finished thing; the work isn't finished "
             "while one of these fails):"]
    lines += [f"- [{i['id']}] {i['text']}" + ("" if i.get("must", True) else " (nice to have)") for i in items]
    acc = (doc or {}).get("done_accepted")
    if acc:
        lines.append("The owner accepted it as it is, with these not working: "
                     + "; ".join(acc.get("failed_text") or acc.get("failed") or []))
    return "\n".join(lines)


def proof_lines(root) -> list[dict[str, Any]] | None:
    """The kind's proof checks with their results from the done list ({id, words, passed, optional,
    status}), for the Gallery (kindstage._kind_proof_lines). None until one of them was really checked, so
    the kind stage's own look at the pictures still counts until then."""
    items = [i for i in read(root)["items"] if i.get("kind_id")]
    if not any(i.get("state") in ("passed", "failed", "unchecked") for i in items):
        return None
    return [{"id": i["kind_id"], "words": i["text"], "optional": not i.get("must", True), "status": "trial",
             "passed": {"passed": True, "failed": False}.get(i.get("state"))} for i in items]


# -- the owner's edits (plan_update "done_add" and "done_remove") -------------------------------------------------------
def _goal_of(doc: dict[str, Any]) -> int:
    return int(doc.get("goal_index") or 0)


def owner_add(root, doc: dict[str, Any], kw: dict[str, Any], note) -> dict[str, Any]:
    """The owner adds their own item. It's kept word for word through every revision of the plan.
    ``note(text, key)`` is plan_update's: the planner hears about it at the next update."""
    raw = {"text": kw.get("text"), "how": kw.get("how") or "owner", "must": kw.get("must", True)}
    for k in ("steps", "command", "path"):
        if kw.get(k):
            raw[k] = kw[k]
    item = clean_item(raw, by="owner")
    if not item:
        raise ValueError("write what you want to be able to do with the finished thing")
    with _LOCK:
        data = read(root)
        if data["goal_index"] != _goal_of(doc):
            data = {"goal_index": _goal_of(doc), "items": [], "rounds": []}
        n = 1
        ids = {i["id"] for i in data["items"]} | {i.get("id") for i in doc.get("done_list") or []}
        while f"D{n}" in ids:
            n += 1
        kept = {**item, "id": f"D{n}", "state": "open", "words": "", "evidence": {}}
        data["items"].append(kept)
        _write(root, data)
    doc.setdefault("done_list", []).append(public(kept))
    note(f"The owner adds to the done list (keep it word for word): {kept['text']}", f"done:{kept['id']}")
    return kept


def owner_remove(root, doc: dict[str, Any], kw: dict[str, Any], note) -> dict[str, Any]:
    """The owner takes an item off the list; a later plan doesn't bring it back."""
    iid = str(kw.get("id") or "").strip()
    item = next((i for i in doc.get("done_list") or [] if i.get("id") == iid), None)
    if item is None:
        raise KeyError(f"no item {iid!r} on the done list")
    doc["done_list"] = [i for i in doc["done_list"] if i.get("id") != iid]
    doc.setdefault("done_removed", []).append({"id": iid, "text": item["text"], "kind_id": item.get("kind_id", "")})
    with _LOCK:
        data = read(root)
        data["items"] = [i for i in data["items"] if i["id"] != iid]
        _write(root, data)
    note(f"The owner took this off the done list, don't add it back: {item['text']}", f"done:{iid}")
    return item


# -- evidence ---------------------------------------------------------------------------------------------------------
PICTURE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
               ".gif": "image/gif"}


def _pictures_in(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if Path(value).suffix.lower() in PICTURE_EXT else []
    if isinstance(value, list):
        return [p for v in value for p in _pictures_in(v)]
    if isinstance(value, dict):
        return [p for v in value.values() for p in _pictures_in(v)]
    return []


def evidence(root, item_id: str, limit: int = 600_000, most: int = 6) -> dict[str, Any] | None:
    """One item's evidence for the app: its words, the short texts, and its pictures as small inline data
    addresses (only files inside the project, none bigger than ``limit``). None when there's no such item."""
    item = next((i for i in read(root)["items"] if i["id"] == str(item_id)), None)
    if item is None:
        return None
    base = Path(root).resolve()
    ev = item.get("evidence") or {}
    pictures = []
    for rel in dict.fromkeys(_pictures_in(ev)):
        p = (base / rel).resolve() if not Path(rel).is_absolute() else Path(rel).resolve()
        if base not in p.parents or not p.is_file() or p.stat().st_size > limit:
            continue
        data = base64.b64encode(p.read_bytes()).decode()
        pictures.append({"name": p.name, "data": f"data:{PICTURE_EXT[p.suffix.lower()]};base64,{data}"})
        if len(pictures) >= most:
            break
    texts = {k: str(v)[:2000] for k, v in ev.items() if isinstance(v, (str, int, float)) and not _pictures_in(v)}
    return {"item": item["id"], "text": item["text"], "state": item.get("state", "open"), "words": item.get("words", ""),
            "texts": texts, "pictures": pictures}
