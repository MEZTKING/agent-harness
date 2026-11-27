"""What I learned: the lab's changes in plain words, each with an undo (wave 7).

``view(cfg, lab)`` is what the desktop's Learning tab and the phone's card show::

    {lines:    [{id, when, words, why, state: on | watching | undone | put_back, by, can_undo, can_put_back,
                 kind, role, before_after?}],
     waiting:  [{id, words, why, kind, role, from}]   what needs the owner (tools, kind tweaks, a protected
                                                      prompt, a change from another machine the charter holds)
     not_here: [{id, words, why}]                     shared changes this machine can't use (a model it lacks)
     never:    [str]                                  what the charter says the lab can never change
     wallet:   {on, allowance, left, words}           the learning allowance in one line
     counts:   {on, undone, waiting}}

The words are built from the numbers a change carries (its test, its evidence, its watch), never from the
analyst's free text: a rationale can hold a project's name, a number can't. ``by`` is "by itself", "you" or
the other machine's name.

``act(cfg, lab, body, via)`` is the one way the apps change it: ``undo`` (any machine, the phone too),
``put_back`` (applied again by the owner, watched again), ``apply`` and ``turn_down`` for waiting items.

``settle(lab, cfg)`` makes the learned state the pure function of every change in force, in ``(at, id)``
order (``Lab.rebuild``). Sharing (share.py) uses it after pulling; an undo uses it when a change from
another machine is in force, because those have no snapshot of their own here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..harness.config import HarnessConfig
from .lab import KINDS, Lab, Proposal

IN_FORCE = ("applied",)
TAKEN_OUT = ("undone", "rolled_back")
WAITS = ("needs_owner",)
CORE_KINDS = ("routing", "options", "prompt")  # the kinds whose change is laid as settings (shared as such)
MAX_LINES = 60
_REF = re.compile(r"^[\w.-]+/[\w.:/-]+$")
_SAFE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


# -- names --------------------------------------------------------------------------------------------
def this_machine() -> dict[str, str]:
    from ..sync import this_machine as mine

    try:
        return mine()
    except Exception:  # noqa: BLE001 - a name for the line, never a reason to fail
        return {"id": "", "name": "", "kind": "pc"}


def _stamp(at: str) -> str:
    return re.sub(r"\D", "", str(at or ""))[:14] or "0"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:40] or "x"


def pulled(p: Proposal, me: str | None = None) -> bool:
    """A change that came from another machine and is still that machine's application."""
    me = this_machine()["id"] if me is None else me
    return bool(p.origin) and bool(p.machine) and p.machine != me


def shared_id(p: Proposal, me: str | None = None) -> str:
    """The id a change has between machines: its maker, its id and when it was applied. A pulled change keeps
    the id it came with; putting a change back makes a new one (an undo anywhere stays an undo)."""
    if pulled(p, me):
        return p.origin
    return f"{_slug(p.machine or 'here')}-{_slug(p.id)}-{_stamp(p.applied_at)}"


def order_key(p: Proposal, me: str | None = None) -> tuple[str, str]:
    return (str(p.applied_at or p.created_at or ""), shared_id(p, me))


def in_force(lab: Lab, me: str | None = None) -> list[Proposal]:
    """Every change in force, in the order the learned state lays them."""
    return sorted((p for p in lab.proposals() if p.status in IN_FORCE and p.kind in KINDS),
                  key=lambda p: order_key(p, me))


def settle(lab: Lab, cfg: HarnessConfig, me: str | None = None, why: str = "settle") -> bool:
    """Rebuild learned.yaml and the prompts from every change in force. Returns whether anything changed.
    A snapshot of the state before is kept (so `roundtable improve rollback` still has it)."""
    before = lab.state_id()
    changes = in_force(lab, me)
    probe = Lab(lab.root / ".settle-probe")
    try:
        probe.rebuild(changes, cfg)
        same = probe.state_id() == before
    finally:
        import shutil

        shutil.rmtree(probe.root, ignore_errors=True)
    if same:
        return False
    versions = lab._versions()
    version = (versions or [0])[-1] + 1
    from ..core.models import utcnow

    lab._snapshot(version, {"at": utcnow(), "summary": f"learned state rebuilt ({why})", "reason": why,
                            "rebuild": [p.id for p in changes]})
    lab.rebuild(changes, cfg)
    lab._log("rebuilt", version=version, why=why, changes=[p.id for p in changes])
    return True


def _any_pulled(lab: Lab, me: str | None = None) -> bool:
    return any(pulled(p, me) for p in lab.proposals() if p.status in IN_FORCE)


# -- words from numbers ---------------------------------------------------------------------------------
def _job(role: str) -> str:
    from ..routing import job_name

    return job_name(role) if role else "The harness"


def _model(ref: str, cfg: HarnessConfig | None) -> str:
    from ..routing import model_label

    if not _REF.match(str(ref or "")):
        return "another model"
    label = model_label(ref, getattr(cfg, "providers", None) or {})
    return label.split(" (", 1)[0]


def _int(x: Any) -> int | None:
    try:
        return int(round(float(x)))
    except (TypeError, ValueError):
        return None


def _num(x: Any) -> float | None:
    if isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) < 1e9 else None


def numbers(p: Proposal) -> dict[str, Any]:
    """The counts and costs a change carries, and nothing else: no task ids, no titles, no review text, no
    rationale. What the ledger words come from, and all that sharing sends with a change."""
    out: dict[str, Any] = {}
    t = p.test or {}
    if isinstance(t, dict) and t:
        n = _int(t.get("tasks_compared") if t.get("tasks_compared") is not None else t.get("n"))
        test: dict[str, Any] = {"n": n or 0, "passed": bool(t.get("passed"))}
        for side in ("current", "candidate"):
            s = t.get(side) if isinstance(t.get(side), dict) else {}
            ok = s.get("approved") if s.get("approved") is not None else s.get("passed")
            test[side] = {"ok": _int(ok) or 0, "cost_usd": _num(s.get("cost_usd"))}
        if t.get("yardstick") or t.get("veto") is not None:
            test["yardstick"] = True
        y = t.get("yardstick") if isinstance(t.get("yardstick"), dict) else {}
        if y and _int((y.get("candidate") or {}).get("of") or (y.get("current") or {}).get("of")):
            cur, cand = (y.get("current") or {}), (y.get("candidate") or {})
            practice = {"n": _int(cand.get("of") or cur.get("of")) or 0,
                        "current": {"ok": _int(cur.get("passed")) or 0, "cost_usd": _num(cur.get("cost_usd"))},
                        "candidate": {"ok": _int(cand.get("passed")) or 0, "cost_usd": _num(cand.get("cost_usd"))}}
            if not test["n"]:  # tested on the practice tasks alone (no past tasks to replay): their counts
                test.update(practice, practice=True)
            else:  # both: past tasks first, the practice tasks beside them
                test["practice_tasks"] = practice
        out["test"] = test
    ev = p.evidence if isinstance(p.evidence, dict) else {}
    for side in ("primary", "candidate"):
        s = ev.get(side)
        if isinstance(s, dict):
            row = {"model": str(s.get("model") or "") if _REF.match(str(s.get("model") or "")) else "",
                   "quality": _num(s.get("quality")), "n": _int(s.get("n")) or 0,
                   "cost_per_success": _num(s.get("cost_per_success"))}
            out[side] = row
    for k in ("error_rate", "attempts"):
        v = _num(ev.get(k))
        if v is not None:
            out[k] = v
    shared = ev.get("numbers") if isinstance(ev.get("numbers"), dict) else None  # a pulled change's numbers
    if shared and not out:
        out = _clean_numbers(shared)
    w = p.watch if isinstance(p.watch, dict) else {}
    if w:
        watch = {k: _num(w.get(k)) for k in ("tasks", "before", "after", "n", "seen", "approved_before",
                                             "approved_after") if _num(w.get(k)) is not None}
        if watch:
            out["watch"] = watch
    return out


def _clean_numbers(d: Any, depth: int = 0) -> Any:
    """Only numbers, yes/no and model ids under short plain keys (anything else is dropped)."""
    if depth > 3 or not isinstance(d, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in d.items():
        if not isinstance(k, str) or not _SAFE_KEY.match(k):
            continue
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float)) and _num(v) is not None:
            out[k] = v
        elif v is None:
            out[k] = None
        elif isinstance(v, str) and k == "model" and _REF.match(v):
            out[k] = v
        elif isinstance(v, dict):
            out[k] = _clean_numbers(v, depth + 1)
    return out


def _of(a: int | None, n: int | None) -> str:
    return f"{a} of {n}" if a is not None and n else ""


def reason(p: Proposal, cfg: HarnessConfig | None = None, nums: dict[str, Any] | None = None) -> str:
    """Why, in a few words, from the numbers only ("it passed 9 of 10 against 6 of 10")."""
    nums = numbers(p) if nums is None else nums
    t = nums.get("test") or {}
    if t.get("n"):
        n = t["n"]
        cur, cand = (t.get("current") or {}), (t.get("candidate") or {})
        tasks = " practice tasks" if t.get("practice") else ""
        words = f"it passed {cand.get('ok', 0)} of {n}{tasks} against {cur.get('ok', 0)} of {n}"
        c0, c1 = cur.get("cost_usd"), cand.get("cost_usd")
        if c0 is not None and c1 is not None and c1 < c0 and cand.get("ok", 0) >= cur.get("ok", 0):
            words += f", for ${c1:.2f} instead of ${c0:.2f}"
        pt = t.get("practice_tasks") or {}
        if pt.get("n"):
            m = pt["n"]
            words += (f", and {(pt.get('candidate') or {}).get('ok', 0)} of {m} practice tasks against "
                      f"{(pt.get('current') or {}).get('ok', 0)} of {m}")
        return words
    pr, ca = nums.get("primary") or {}, nums.get("candidate") or {}
    if pr.get("n") and ca.get("n") and pr.get("quality") is not None and ca.get("quality") is not None:
        a = _of(_int(ca["quality"] * ca["n"]), ca["n"])
        b = _of(_int(pr["quality"] * pr["n"]), pr["n"])
        return f"it was approved {a} times against {b} for the one before"
    if nums.get("error_rate") is not None and nums.get("attempts"):
        return f"the one before failed {round(nums['error_rate'] * 100)}% of {int(nums['attempts'])} tries"
    return ""


def what(p: Proposal, cfg: HarnessConfig | None = None) -> str:
    """The change itself in plain words, from its settings (model ids become names)."""
    job = _job(p.role)
    ch = p.change if isinstance(p.change, dict) else {}
    if p.kind == "routing":
        models = [m for m in ch.get("models") or [] if isinstance(m, str)]
        if not models:
            return f"{job} has a new order of models"
        backup = f", then {_model(models[1], cfg)}" if len(models) > 1 else ""
        return f"{job} now starts with {_model(models[0], cfg)}{backup}"
    if p.kind == "options":
        opts = ch.get("options") if isinstance(ch.get("options"), dict) else {}
        parts = []
        for k, v in sorted(opts.items()):
            if not isinstance(k, str) or not _SAFE_KEY.match(k):
                continue
            if isinstance(v, (int, float, bool)) or (isinstance(v, str) and re.match(r"^[\w.-]{1,20}$", v)):
                parts.append(f"thinks {v}" if k == "effort" else f"{k.replace('_', ' ')} {v}")
        return f"{job} now " + (", ".join(parts) if parts else "has new settings")
    if p.kind == "prompt":
        return f"{job} has new instructions"
    kind = str(p.kind or "change").replace("_", " ")
    return f"{job}: a new {kind}"


def _who(p: Proposal, rows: list[dict[str, Any]], names: dict[str, str], me: str) -> str:
    if pulled(p, me):
        return names.get(p.machine) or _machine_words(p.machine)
    applied = [r for r in rows if r.get("event") == "applied"]
    last = str((applied[-1] if applied else {}).get("reason") or "")
    return "by itself" if last.startswith("auto") else "you"


def _machine_words(mid: str) -> str:
    if mid.startswith("phone-"):
        return "your phone"
    if mid.startswith("pc-"):
        return f"your PC ({mid[3:].upper()})"
    return "another machine"


def _watching(p: Proposal) -> bool:
    w = p.watch if isinstance(p.watch, dict) else None
    if not w:
        return False
    return not any(w.get(k) for k in ("done", "ended", "kept", "finished")) and w.get("state") not in (
        "kept", "done", "undone", "ended")


def _builtin_prompt(name: str) -> str:
    p = Path(__file__).resolve().parent.parent / "prompts" / f"{name}.md"
    try:
        return p.read_text(encoding="utf-8") if p.is_file() else ""
    except OSError:
        return ""


def _before_after(p: Proposal, cfg: HarnessConfig | None) -> dict[str, Any] | None:
    from . import charter

    ch = p.change if isinstance(p.change, dict) else {}
    if p.kind == "routing":
        before = ((numbers(p).get("primary") or {}).get("model")) or ""
        return {"before": [_model(before, cfg)] if before else [],
                "after": [_model(m, cfg) for m in ch.get("models") or [] if isinstance(m, str)]}
    if p.kind == "prompt":
        name = p.role
        try:
            name = cfg.roles[p.role].prompt if cfg and cfg.roles.get(p.role) else p.role
        except Exception:  # noqa: BLE001
            pass
        old, new = _builtin_prompt(name), str(ch.get("prompt_text") or "")
        lines = charter.diff(old, new)
        if not lines:
            olds, news = old.splitlines(), new.splitlines()
            lines = ([{"op": "gone", "text": x} for x in olds if x not in news]
                     + [{"op": "new", "text": x} for x in news if x not in olds])
        return {"diff": lines[:400]}
    if p.kind == "options":
        return {"after": {k: v for k, v in (ch.get("options") or {}).items()
                          if isinstance(v, (int, float, bool, str)) and len(str(v)) <= 20}}
    return None


# -- the view -------------------------------------------------------------------------------------------------
def _shared_state(lab: Lab) -> dict[str, Any]:
    p = lab.root / "shared.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def _never() -> list[str]:
    """The charter's own list of what the lab can never change, as it words it (asked, never copied)."""
    from . import charter

    for name in ("never", "never_words", "protected_words"):
        fn = getattr(charter, name, None)
        if callable(fn):
            try:
                out = fn()
            except Exception:  # noqa: BLE001
                continue
            if isinstance(out, (list, tuple)):
                return [w for w in map(_never_line, out) if w]
    for name in ("NEVER", "NEVER_WORDS"):
        val = getattr(charter, name, None)
        if isinstance(val, (list, tuple)):
            return [w for w in map(_never_line, val) if w]
    return []


def _never_line(x: Any) -> str:
    """One line of the never-list in words: a row's title (a dict from the charter's table), or the text."""
    if isinstance(x, dict):
        return str(x.get("title") or x.get("words") or "").strip()
    return str(x).strip()


def _wallet(cfg: HarnessConfig, lab: Lab) -> dict[str, Any]:
    from . import wallet

    try:
        allowance = float(wallet.allowance(cfg))
        left = float(wallet.left(cfg, lab))
    except Exception:  # noqa: BLE001 - the line says so rather than failing the page
        return {"on": False, "allowance": 0.0, "left": 0.0, "words": "Couldn't read the learning allowance."}
    if allowance <= 0:
        words = "Learning by itself is off: it only suggests, and spends nothing on its own."
    else:
        words = f"Learning by itself: ${left:.2f} of ${allowance:.2f} left this week."
    return {"on": allowance > 0, "allowance": round(allowance, 4), "left": round(max(0.0, left), 4), "words": words}


def _why_waits(p: Proposal, rows: list[dict[str, Any]]) -> str:
    from . import charter

    for r in reversed(rows):
        if r.get("event") == "needs_owner" and r.get("why"):
            return str(r["why"])[:300]
    if p.status == "needs_owner":
        return "This kind of change always waits for your yes."
    if not charter.may_auto(p):
        return "Changes like this always wait for you."
    return "Waiting for your yes."


def view(cfg: HarnessConfig, lab: Lab, me: dict[str, str] | None = None) -> dict[str, Any]:
    from . import charter

    me = me or this_machine()
    hist: dict[str, list[dict[str, Any]]] = {}
    for r in lab.history():
        if r.get("proposal"):
            hist.setdefault(str(r["proposal"]), []).append(r)
    shared = _shared_state(lab)
    names = {str(k): str(v) for k, v in (shared.get("names") or {}).items()}
    lines, waiting = [], []
    for p in lab.proposals():
        rows = hist.get(p.id, [])
        if p.status in IN_FORCE + TAKEN_OUT and (p.applied_at or p.applied_version is not None or pulled(p, me["id"])):
            was_out = any(r.get("event") == "undone" for r in rows) and p.status in IN_FORCE
            state = ("undone" if p.status in TAKEN_OUT else "watching" if _watching(p)
                     else "put_back" if was_out else "on")
            nums = numbers(p)
            head, why = what(p, cfg), reason(p, cfg, nums)
            if state == "undone":
                why = _undone_words(p, rows, names, me["id"]) or why
            line = {"id": p.id, "when": p.applied_at or p.created_at, "words": f"{head}: {why}." if why else f"{head}.",
                    "what": head, "why": why, "state": state, "by": _who(p, rows, names, me["id"]),
                    "can_undo": p.status in IN_FORCE, "can_put_back": p.status in TAKEN_OUT and p.kind in KINDS,
                    "kind": p.kind, "role": p.role, "numbers": nums}
            ba = _before_after(p, cfg)
            if ba:
                line["before_after"] = ba
            lines.append(line)
        elif p.status in WAITS or (p.status in ("proposed", "tested") and not charter.may_auto(p)):
            waiting.append({"id": p.id, "words": f"{what(p, cfg)}.", "why": _why_waits(p, rows), "kind": p.kind,
                            "role": p.role, "from": names.get(p.machine) if pulled(p, me["id"]) else "",
                            "can_apply": True})
    for sid, item in sorted((shared.get("elsewhere") or {}).items()):
        if isinstance(item, dict):
            waiting.append({"id": sid, "words": str(item.get("words") or "A change made on another machine."),
                            "why": f"Made on {item.get('from') or 'another machine'}: open it there to look at it.",
                            "kind": str(item.get("kind") or ""), "role": str(item.get("role") or ""),
                            "from": str(item.get("from") or ""), "can_apply": False})
    not_here = []
    for sid, item in sorted((shared.get("unusable") or {}).items()):
        if isinstance(item, dict):
            not_here.append({"id": sid, "words": str(item.get("words") or "A change from another machine."),
                             "why": str(item.get("why") or "Not usable here.")})
    lines.sort(key=lambda x: str(x["when"]), reverse=True)
    lines = lines[:MAX_LINES]
    counts = {"on": sum(1 for x in lines if x["state"] != "undone"),
              "undone": sum(1 for x in lines if x["state"] == "undone"), "waiting": len(waiting)}
    return {"lines": lines, "waiting": waiting, "not_here": not_here, "never": _never(),
            "wallet": _wallet(cfg, lab), "counts": counts, "machine": me.get("id", ""),
            "share": _share_on(cfg)}


def _share_on(cfg: HarnessConfig) -> bool:
    from ..harness.config import section

    return section(cfg, "learning").get("share", True) is not False


def _undone_words(p: Proposal, rows: list[dict[str, Any]], names: dict[str, str], me: str) -> str:
    undo = [r for r in rows if r.get("event") == "undone"]
    last = undo[-1] if undo else {}
    by = str(last.get("by") or "")
    if p.status == "rolled_back" and (by in ("", "owner")):
        return "you undid it"
    if by.startswith(("pc-", "phone-")) and by != me:
        return f"undone on {names.get(by) or _machine_words(by)}"
    if p.undone_why and re.search(r"\d", p.undone_why) and len(p.undone_why) <= 160:
        return p.undone_why.rstrip(".")  # the watch's own numbers ("approved 2 of 6 after, 5 of 6 before")
    return "undone by itself: the next tasks went worse" if by and by != "owner" else "undone"


# -- what the apps may do ------------------------------------------------------------------------------------
class LedgerError(ValueError):
    pass


PHONE_ACTIONS = ("undo",)
ACTIONS = ("undo", "put_back", "apply", "turn_down")


def act(cfg: HarnessConfig, lab: Lab, body: dict[str, Any], via: str = "pc") -> dict[str, Any]:
    """One tap from an app. The phone may only undo."""
    action = str(body.get("action") or "")
    if action not in ACTIONS:
        raise LedgerError(f"Unknown action {action!r}: choose undo, put back, use it or turn down.")
    if via == "phone" and action not in PHONE_ACTIONS:
        raise PermissionError("From the phone you can undo a change. Putting back, using or turning one down is "
                              "done on the PC.")
    pid = str(body.get("id") or "")
    try:
        p = lab.proposal(pid)
    except KeyError:
        raise LedgerError("That change isn't here any more. Refresh the list.") from None
    me = this_machine()["id"]
    if action == "undo":
        undo(cfg, lab, p, by="owner", me=me)
    elif action == "put_back":
        if p.status not in TAKEN_OUT:
            raise LedgerError("That change is in use already.")
        lab.apply(p, cfg, reason="put back", by_owner=True)
        if _any_pulled(lab, me):
            settle(lab, cfg, me, "put back")
    elif action == "apply":
        if p.status not in ("proposed", "tested", "needs_owner"):
            raise LedgerError("That change isn't waiting any more.")
        lab.apply(p, cfg, reason="owner", by_owner=True)
        if _any_pulled(lab, me):
            settle(lab, cfg, me, "owner said yes")
    else:
        if p.status not in ("proposed", "tested", "needs_owner"):
            raise LedgerError("That change isn't waiting any more.")
        p.status = "rejected"
        lab.save_proposal(p)
        lab._log("rejected", proposal=p.id, summary=p.summary(), by="owner")
    return {"ok": True, "id": p.id, "action": action, **view(cfg, lab)}


def undo(cfg: HarnessConfig, lab: Lab, p: Proposal, by: str = "owner", why: str = "",
         me: str | None = None) -> None:
    """Undo one change by itself. A change made here goes through ``Lab.undo`` (its snapshot); a change from
    another machine has none here, so it is taken out of the list and the state rebuilt."""
    me = this_machine()["id"] if me is None else me
    if p.status not in IN_FORCE:
        raise LedgerError("That change isn't in use, so there's nothing to undo.")
    if p.applied_version is not None and p.applied_version in lab._versions() and not pulled(p, me):
        lab.undo(p.id, why=why, by=by, cfg=cfg)
        if _any_pulled(lab, me):
            settle(lab, cfg, me, "undo")
        return
    p.status = "rolled_back" if by == "owner" else "undone"
    p.undone_why = why
    lab.save_proposal(p)
    spec = KINDS.get(p.kind)
    if spec and spec.on_undo:
        spec.on_undo(lab, p)
    lab._log("undone", proposal=p.id, summary=p.summary(), by=by, why=why)
    settle(lab, cfg, me, "undo")
