"""Questions with a timer (wave 8, DS-44).

Any card may carry ``expires_at`` and ``on_expire``: ``recommended`` (the harness takes the recommended answer),
``nothing`` (the card stays, nothing happens) or ``pause`` (the project's next run waits for the answer). No
card has a timer unless whoever asks sets one: ``set_timer`` (the owner's "decide for me in…", or a planner's
question that says how long it can wait), or a ``timer`` on the card itself (``{"minutes", "on_expire"}``).

Safety: a card whose recommended answer spends or can't be undone (``confirm``), or one about money, a plan's
approval, a stopped task, the models, or a command, may only expire to ``nothing`` or ``pause`` – a timer never
spends and never deletes.

Typing in the card sends a ``hold``: the clock stops while the owner writes (90 seconds a hold, renewed as they
type), and starts again where it was.

A late answer is still kept and applied when the question's ``stamp`` still matches (``answer`` wraps
``asks.answer_ask``); when it doesn't, the reply says plainly that the moment passed and what was done instead.

Kept in the project's ``.harness/asktimers.json``: ``{ask_id: {stamp, expires_at, on_expire, left, held_until,
set_at, fired: {at, did, label}}}``; ``.harness/asktimers-pause.json`` while a ``pause`` holds the next run.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FILE = Path(".harness") / "asktimers.json"
PAUSE_FILE = Path(".harness") / "asktimers-pause.json"
ON_EXPIRE = ("recommended", "nothing", "pause")
HOLD_S = 90.0
MIN_S, MAX_S = 60.0, 7 * 24 * 3600.0
NEVER_AUTO = ("money", "approve", "failed", "profile", "command", "not_finished", "stuck")
_lock = threading.RLock()


class TimerError(ValueError):
    """A timer that can't be set, in the owner's words."""


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _secs(iso: str) -> float | None:
    try:
        return datetime.strptime(str(iso), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def _load(root) -> dict[str, Any]:
    try:
        d = json.loads((Path(root) / FILE).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(root, data: dict[str, Any]) -> None:
    p = Path(root) / FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def may_choose_for_you(ask: dict[str, Any]) -> bool:
    """May this card expire to its recommended answer? Only when that answer spends nothing and deletes
    nothing."""
    rec = ask.get("recommended")
    if not rec or ask.get("kind") in NEVER_AUTO or ask.get("multi"):
        return False
    opt = next((o for o in ask.get("options") or [] if o.get("id") == rec), None)
    return bool(opt) and not opt.get("confirm")


def set_timer(root, ask: dict[str, Any], seconds: float, on_expire: str = "recommended",
              now: float | None = None) -> dict[str, Any]:
    """Give one card a timer (or a new one). ``ask`` is the card as listed (its ``id`` and ``stamp``)."""
    if on_expire not in ON_EXPIRE:
        raise TimerError("When the time runs out it can take the recommended answer, do nothing, or pause.")
    if on_expire == "recommended" and not may_choose_for_you(ask):
        raise TimerError("This question's answer spends money or can't be undone, so the time running out may only "
                         "leave it waiting or pause the project, never answer it for you.")
    seconds = float(seconds)
    if not MIN_S <= seconds <= MAX_S:
        raise TimerError("Choose between a minute and a week.")
    now = time.time() if now is None else now
    with _lock:
        data = _load(root)
        data[str(ask["id"])] = {"stamp": ask.get("stamp", ""), "expires_at": _iso(now + seconds), "on_expire": on_expire,
                                "set_at": _iso(now), "held_until": "", "left": 0, "fired": None}
        _save(root, data)
    return data[str(ask["id"])]


def clear_timer(root, ask_id: str) -> bool:
    with _lock:
        data = _load(root)
        gone = data.pop(str(ask_id), None) is not None
        if gone:
            _save(root, data)
    return gone


def hold(root, ask_id: str, now: float | None = None) -> dict[str, Any] | None:
    """The owner is typing an answer: stop the clock for HOLD_S (renewed by each hold)."""
    now = time.time() if now is None else now
    with _lock:
        data = _load(root)
        t = data.get(str(ask_id))
        if not t or t.get("fired"):
            return None
        held = (_secs(t.get("held_until", "")) or 0) > now
        exp = _secs(t["expires_at"]) or now
        left = float(t.get("left") or 0) if held else max(0.0, exp - now)
        t["left"] = left
        t["held_until"] = _iso(now + HOLD_S)
        t["expires_at"] = _iso(now + HOLD_S + left)
        _save(root, data)
        return t


def stamp(ask: dict[str, Any], root=None, now: float | None = None) -> dict[str, Any]:
    """Put a card's timer on it as it is made (``expires_at``, ``on_expire``, ``held``, ``timed_out``). A card
    carrying its own ``timer`` gets one the first time it is seen. A timer set for an older version of the
    question (another ``stamp``) doesn't count. Returns the card."""
    if root is None or not ask.get("id"):
        return ask
    now = time.time() if now is None else now
    data = _load(root)
    t = data.get(str(ask["id"]))
    own = ask.get("timer")
    if (not t or t.get("stamp") != ask.get("stamp")) and isinstance(own, dict) and own.get("minutes"):
        try:
            t = set_timer(root, ask, float(own["minutes"]) * 60, str(own.get("on_expire") or "recommended"), now=now)
        except TimerError:
            t = set_timer(root, ask, float(own["minutes"]) * 60, "nothing", now=now)
    if not t or t.get("stamp") != ask.get("stamp"):
        return ask
    if t.get("fired"):
        ask["timed_out"] = t["fired"]
        return ask
    ask["expires_at"] = t["expires_at"]
    ask["on_expire"] = t["on_expire"]
    ask["held"] = (_secs(t.get("held_until", "")) or 0) > now
    return ask


def sweep(orch, asks: list[dict[str, Any]], now: float | None = None) -> list[dict[str, Any]]:
    """Where cards are listed: do what each card whose time ran out says. Returns the cards still to show (one
    answered for you drops out, like any answered card). Marked as done before it is applied, so listing the
    cards again while applying it never applies it twice."""
    now = time.time() if now is None else now
    root = orch.project.root
    out = []
    for a in asks:
        t = _load(root).get(str(a.get("id")))
        exp = _secs((t or {}).get("expires_at", ""))
        held = (_secs((t or {}).get("held_until", "")) or 0) > now
        if not t or t.get("fired") or t.get("stamp") != a.get("stamp") or a.get("answer") or exp is None \
                or exp > now or held:
            out.append(a)
            continue
        did, label = _fire(orch, a, t, now)
        if did != "recommended":
            out.append({**a, "timed_out": {"at": _iso(now), "did": did, "label": label}})
    return out


def _fire(orch, ask: dict[str, Any], t: dict[str, Any], now: float) -> tuple[str, str]:
    root = orch.project.root
    did = t["on_expire"]
    if did == "recommended" and not may_choose_for_you(ask):
        did = "nothing"  # the card changed into one that spends: never answer it for you
    label = next((o["label"] for o in ask.get("options") or [] if o["id"] == ask.get("recommended")), "")
    with _lock:
        data = _load(root)
        data[str(ask["id"])] = {**t, "fired": {"at": _iso(now), "did": did, "label": label if did == "recommended" else ""}}
        _save(root, data)
    if did == "recommended":
        from .asks import answer_ask

        try:
            answer_ask(orch, ask["id"], [ask["recommended"]], stamp=ask.get("stamp"))
            orch.emit("ask_timed_out", {"ask": ask["id"], "did": did, "label": label})
            return did, label
        except Exception as e:  # noqa: BLE001 - it couldn't answer: leave the card waiting
            with _lock:
                data = _load(root)
                data[str(ask["id"])]["fired"] = {"at": _iso(now), "did": "nothing", "label": "", "why": str(e)[:200]}
                _save(root, data)
            return "nothing", ""
    if did == "pause":
        (Path(root) / PAUSE_FILE).parent.mkdir(parents=True, exist_ok=True)
        (Path(root) / PAUSE_FILE).write_text(json.dumps({"ask": ask["id"], "question": ask.get("question", ""),
                                                         "at": _iso(now)}), encoding="utf-8")
    orch.emit("ask_timed_out", {"ask": ask["id"], "did": did})
    return did, ""


def paused(root) -> dict[str, Any] | None:
    """A timed-out question holds the next run (``on_expire: pause``): what it is, else None."""
    try:
        d = json.loads((Path(root) / PAUSE_FILE).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def answer(orch, ask_id: str, chosen=None, other: str = "", confirmed: bool = False, stamp_seen: str | None = None,
           skip: bool = False) -> dict[str, Any]:
    """``asks.answer_ask``, aware of timers: an answer after the time ran out is still applied when the question
    hasn't changed; when it has, the reply says the moment passed and what was done instead. Answering lifts a
    pause the card put on the project."""
    from .asks import answer_ask
    from .harness.orchestrator import HarnessError

    root = orch.project.root
    t = _load(root).get(str(ask_id))
    try:
        r = answer_ask(orch, ask_id, chosen, other, confirmed=confirmed, stamp=stamp_seen, skip=skip)
    except HarnessError:
        fired = (t or {}).get("fired")
        if fired and _current_stamp(orch, ask_id) != (stamp_seen or t.get("stamp")):
            raise HarnessError(late_words(fired)) from None
        raise
    p = paused(root)
    if p and p.get("ask") == ask_id:
        try:
            (Path(root) / PAUSE_FILE).unlink()
        except OSError:
            pass
    if t:
        clear_timer(root, ask_id)
    return r


def _current_stamp(orch, ask_id: str) -> str | None:
    """The question's stamp as it is now, None when it is gone."""
    from .asks import open_asks

    try:
        return next((a["stamp"] for a in open_asks(orch, answered=True) if a["id"] == ask_id), None)
    except Exception:  # noqa: BLE001
        return None


def late_words(fired: dict[str, Any]) -> str:
    at = str(fired.get("at", ""))[11:16]
    when = f" at {at}" if at else ""
    if fired.get("did") == "recommended":
        return (f"The moment has passed: the time ran out{when}, so the harness took the recommended answer "
                f"(“{fired.get('label', '')}”), and the question has changed since. Your answer wasn't applied; "
                "look at what's waiting now.")
    if fired.get("did") == "pause":
        return (f"The moment has passed: the time ran out{when} and the project was paused, and the question has "
                "changed since. Your answer wasn't applied; look at what's waiting now.")
    return (f"The moment has passed: the time ran out{when} and nothing was done, and the question has changed "
            "since. Your answer wasn't applied; look at what's waiting now.")
