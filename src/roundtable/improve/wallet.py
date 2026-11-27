"""The learning allowance: the only money unattended learning may spend (wave 7).

``improve.allowance_usd_per_week`` in harness.yaml or the app's settings (custom.yaml); 0 (the default) means
off, so nothing paid happens by itself. Only the owner sets it (``save_allowance``, from the PC's Settings).
Unused money does not roll over: each week starts again at the full allowance.

    <lab>/wallet.jsonl        one line per charge: {at, week, what, proposal, usd, machine} – numbers only
    <lab>/wallet-state.json   when the analyst last ran, and how many judged tasks there were then

``budget(cfg, lab, what, most)`` hands a step its ``Budget``: at most ``most``, never past what is left of the
week or of the owner's day limit (``limits.max_usd_per_day``, which counts learning too). Every charge writes a
line here (``on_charge``) and a line in the usage ledger with the project "(learning)" (``on_use``), so the
services' limits and "What's used" count it. When nothing is left it raises ``AllowanceUsed``.

``automation(cfg)`` is the one built-in automation ("Learning", Sundays at 03:00) while the allowance is above
0, and ``job(ctx, a)`` runs a learning cycle as an automation's job (never while a project is building).
The signatures of ``allowance``, ``left``, ``budget`` and ``spent_today`` are frozen.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..harness.agent import Budget, BudgetExceeded

LEDGER = "wallet.jsonl"
STATE = "wallet-state.json"
WHATS = ("analyst", "replay", "yardstick", "probe", "tool")
LEARNING_PROJECT = "(learning)"  # the usage ledger's "project" for learning's own calls
CHOICES = (0.0, 1.0, 2.0, 5.0)  # the card's choices (the owner may type another figure)
MOST_PER_WEEK = 100.0  # a figure above this is refused: a slip of the finger, not a weekly allowance
SCHEDULE = {"kind": "weekly", "days": ["sun"], "time": "03:00"}
AUTOMATION_ID = "learning"
BUSY_STATES = ("running", "planning")

_LOCK = threading.Lock()  # one line at a time from this program (another program: one write per line)


class AllowanceUsed(BudgetExceeded):
    """This week's learning allowance is spent (or it is off)."""

    pause = "learning"


# -- small helpers ---------------------------------------------------------------------------------------------
def money(x: float | None) -> str:
    """$2, $0.42, $0.0031: whole dollars without the cents."""
    n = float(x or 0)
    if n and abs(n - round(n)) < 1e-9:
        return f"${n:.0f}"
    return f"${n:.4f}" if 0 < n < 0.01 else f"${n:.2f}"


def _utc(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def week_of(now: datetime | None = None) -> str:
    """The week a moment falls in, in this computer's own time: "2026-W48" (Monday to Sunday)."""
    y, w, _ = _utc(now).astimezone().isocalendar()
    return f"{y}-W{w:02d}"


def _day(now: datetime | None = None) -> str:
    """Today in UTC, as the day limit counts it (orchestrator._spent_today)."""
    return _utc(now).strftime("%Y-%m-%d")


def _machine() -> str:
    from ..sync import this_machine

    try:
        return this_machine()["id"]
    except Exception:  # noqa: BLE001 - a name for the line, never a reason to fail
        return ""


def _root(lab: Any) -> Path:
    return Path(getattr(lab, "root", lab))


def _improve(cfg: Any) -> dict[str, Any]:
    return dict(getattr(cfg, "improve", None) or {})


# -- the ledger --------------------------------------------------------------------------------------------------
def lines(lab: Any, week: str | None = None, machine: str | None = None) -> list[dict[str, Any]]:
    """The ledger's lines, of one week and one machine when asked (a broken line is skipped)."""
    p = _root(lab) / LEDGER
    try:
        raw = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in raw:
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        if week is not None and row.get("week") != week:
            continue
        if machine is not None and row.get("machine", "") != machine:
            continue
        out.append(row)
    return out


def charge(lab: Any, what: str, usd: float, proposal: str = "", now: datetime | None = None) -> dict[str, Any] | None:
    """Write one line: what learning spent on. Nothing for a charge of 0."""
    usd = round(float(usd or 0), 6)
    if usd <= 0:
        return None
    t = _utc(now)
    row = {"at": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "week": week_of(t), "what": what if what in WHATS else "tool",
           "proposal": str(proposal or ""), "usd": usd, "machine": _machine()}
    root = _root(lab)
    with _LOCK:
        root.mkdir(parents=True, exist_ok=True)
        with open(root / LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
    return row


def spent_week(lab: Any, week: str | None = None, machine: str | None = None) -> float:
    """What this machine (or ``machine``) spent on learning in ``week`` (default: this week)."""
    me = _machine() if machine is None else machine
    return round(sum(float(r.get("usd") or 0) for r in lines(lab, week or week_of(), me)), 6)


def others_spent(lab: Any, week: str | None = None) -> float:
    """What the owner's other machines spent on learning this week, when sharing (share.py) knows it; else 0."""
    try:
        from . import share
    except Exception:  # noqa: BLE001
        return 0.0
    fn = getattr(share, "others_spent", None)
    if not callable(fn):
        return 0.0
    try:
        return max(0.0, float(fn(lab, week or week_of()) or 0))
    except Exception:  # noqa: BLE001 - another machine's number that can't be read counts as nothing
        return 0.0


def spent_today(lab: Any) -> float:
    """What learning spent today (UTC) on this machine."""
    today, me = _day(), _machine()
    total = 0.0
    for r in lines(lab, machine=me):
        if str(r.get("at", "")).startswith(today):
            total += float(r.get("usd") or 0)
    return round(total, 6)


# -- what is left --------------------------------------------------------------------------------------------------
def allowance(cfg: Any) -> float:
    """The weekly allowance in dollars; 0 means off (the default)."""
    raw = _improve(cfg).get("allowance_usd_per_week") or 0
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 0.0


def left(cfg: Any, lab: Any, now: datetime | None = None) -> float:
    """What is left of this week's allowance: the allowance, less this week on this machine, less the other
    machines' totals when sharing gives them."""
    have = allowance(cfg)
    if have <= 0:
        return 0.0
    week = week_of(now)
    return max(0.0, round(have - spent_week(lab, week) - others_spent(lab, week), 6))


def _spent_today_everywhere(cfg: Any, lab: Any) -> float:
    """Today's spending on every project of the lab plus learning's (what the owner's day limit counts)."""
    today = _day()
    roots: set[Path] = set()
    try:
        roots |= {Path(p).resolve() for p in lab.projects()}
    except Exception:  # noqa: BLE001
        pass
    total = spent_today(lab)
    for root in roots:
        try:
            rows = (root / ".harness" / "spend.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for ln in rows:
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            if str(row.get("at", "")).startswith(today):
                total += float(row.get("cost_usd") or 0)
    return total


def day_room(cfg: Any, lab: Any) -> float | None:
    """What the owner's day limit (``limits.max_usd_per_day``) still allows today; None when there is none."""
    day = float(getattr(getattr(cfg, "limits", None), "max_usd_per_day", 0) or 0)
    if day <= 0:
        return None
    return max(0.0, day - _spent_today_everywhere(cfg, lab))


def used_words(cfg: Any, lab: Any) -> str:
    """"Learning: $0.42 of $2 this week" (or that it is off)."""
    have = allowance(cfg)
    if have <= 0:
        return "Learning by itself is off"
    return f"Learning: {money(have - left(cfg, lab))} of {money(have)} this week"


def stop_words(cfg: Any) -> str:
    return f"Learning has used this week's {money(allowance(cfg))}; it carries on next week."


DAY_WORDS = "Today's spending limit is reached, so learning waits until tomorrow."
OFF_WORDS = "Learning by itself is off, so it spends nothing."


# -- the budget ------------------------------------------------------------------------------------------------------
@dataclass
class LearningBudget(Budget):
    """A Budget whose charges are learning's: each one a wallet line and a usage line. ``proposal`` may be set
    after it is made (the step it pays for). Running out raises AllowanceUsed when the week or the day was the
    cap, the plain BudgetExceeded when only the step's own ``most`` was."""

    what: str = "tool"
    proposal: str = ""
    cap: str = "most"  # what set the limit: "week", "day" or "most"
    words: str = ""
    lab: Any = field(default=None, repr=False, compare=False)
    cfg: Any = field(default=None, repr=False, compare=False)
    usage_home: Any = field(default=None, repr=False, compare=False)

    def check(self) -> None:
        if self.spent_usd >= self.limit_usd:
            if self.cap in ("week", "day"):
                raise AllowanceUsed(self.words or f"learning's money ran out: ${self.spent_usd:.4f}")
            raise BudgetExceeded(f"budget exhausted: ${self.spent_usd:.4f} of ${self.limit_usd:.2f}")


def _usage_line(b: LearningBudget, ref: Any, use: Any, cost: float | None, role: str | None) -> None:
    """The usage ledger's line for one of learning's calls (numbers and names only), then the services' limits."""
    if ref is None:
        return
    from ..harness import usage

    row = usage.row_for(ref, use, cost, role, LEARNING_PROJECT)
    row["project"], row["pid"] = LEARNING_PROJECT, "learning"
    try:
        usage.record(row, b.usage_home)
    except OSError:
        return  # bookkeeping never stops learning; the wallet's own line is written already
    try:
        limits = usage.settings(b.cfg)
    except Exception:  # noqa: BLE001
        return
    if limits.get("services"):
        hit = usage.service_hit(limits, str(ref).partition("/")[0], b.usage_home, b.cfg)
        if hit:
            raise usage.ServiceCapReached(hit["words"], [hit])


def budget(cfg: Any, lab: Any, what: str, most: float | None = None) -> Budget:
    """A Budget for one unattended learning step, at most ``most`` and never past what is left.
    Raises AllowanceUsed when nothing is left (always, while the allowance is 0)."""
    if allowance(cfg) <= 0:
        raise AllowanceUsed(OFF_WORDS)
    room, cap, words = left(cfg, lab), "week", stop_words(cfg)
    day = day_room(cfg, lab)
    if day is not None and day < room:
        room, cap, words = day, "day", DAY_WORDS
    if room <= 0:
        raise AllowanceUsed(words)
    if most is not None and float(most) < room:
        room, cap = max(0.0, float(most)), "most"
    b = LearningBudget(limit_usd=room, what=what, cap=cap, words=words, lab=lab, cfg=cfg)
    b.on_charge = lambda cost: charge(lab, b.what, cost, b.proposal)
    b.on_use = lambda ref, use, cost, role: _usage_line(b, ref, use, cost, role)
    return b


def lump(b: Budget, cost: float, ref: Any = None, role: str | None = None, use: Any = None) -> None:
    """Count a cost a step reported as one sum (a step that kept its own Budget inside): the same lines as
    the step's own calls would have written."""
    if cost is None or cost <= 0:
        return
    from ..providers.base import Usage

    b.charge(float(cost), ref=ref, usage=use or Usage(), role=role)


# -- the owner's figure ------------------------------------------------------------------------------------------------
def clean_allowance(raw: Any) -> float:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        raise ValueError("Give the weekly allowance in dollars, for example 2") from None
    if v != v or v < 0:
        raise ValueError("The allowance can't be below 0")
    if v > MOST_PER_WEEK:
        raise ValueError(f"That is more than {money(MOST_PER_WEEK)} a week; type a smaller figure")
    return round(v, 2)


def save_allowance(harness_path: str | Path, usd: Any) -> dict[str, Any]:
    """Keep the owner's weekly allowance in custom.yaml's ``improve:`` (harness.yaml is never rewritten).
    When it goes above 0 and nothing says what may apply by itself, "low" is chosen (the owner's decision:
    model order and small option changes that passed a test). Returns custom.yaml's ``improve:``."""
    from ..harness.config import load_custom, save_custom

    value = clean_allowance(usd)
    path = Path(harness_path)
    custom = load_custom(path)
    mine = dict(custom.get("improve") or {}) if isinstance(custom.get("improve"), dict) else {}
    mine["allowance_usd_per_week"] = value
    if value > 0 and "auto_apply" not in mine:
        try:
            import yaml

            base = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("improve") or {}
        except Exception:  # noqa: BLE001
            base = {}
        if not base.get("auto_apply"):
            mine["auto_apply"] = "low"
    custom["improve"] = mine
    save_custom(path, custom)
    return mine


# -- the analyst's turn ------------------------------------------------------------------------------------------------
def _state(lab: Any) -> dict[str, Any]:
    try:
        data = json.loads((_root(lab) / STATE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(lab: Any, data: dict[str, Any]) -> None:
    root = _root(lab)
    root.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        (root / STATE).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def judged_count(lab: Any) -> int:
    """Judged tasks (approved or rejected) in every project of the lab."""
    n = 0
    try:
        roots = list(lab.projects())
    except Exception:  # noqa: BLE001
        return 0
    for root in roots:
        try:
            rows = (Path(root) / ".harness" / "metrics.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for ln in rows:
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if d.get("outcome") in ("approved", "rejected") and not d.get("rival"):
                n += 1
    return n


ANALYST_EVERY = 20  # new judged tasks before the analyst is asked again
ANALYST_SHARE = 0.5  # and at least this share of the week's allowance left


def analyst_due(cfg: Any, lab: Any) -> tuple[bool, str]:
    """Whether the analyst (a paid model) may look this time, and why not in plain words."""
    imp = _improve(cfg)
    every = int(imp.get("analyst_every_tasks", ANALYST_EVERY) or ANALYST_EVERY)
    share = float(imp.get("analyst_share", ANALYST_SHARE) or 0)
    new = judged_count(lab) - int(_state(lab).get("analyst_judged") or 0)
    if new < every:
        return False, f"the analyst waits for {every} new judged tasks ({max(new, 0)} so far)"
    if left(cfg, lab) < share * allowance(cfg):
        return False, "the analyst waits for next week: too little of this week's allowance is left"
    return True, ""


def analyst_ran(lab: Any) -> None:
    st = _state(lab)
    st["analyst_judged"], st["analyst_at"] = judged_count(lab), _utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    _save_state(lab, st)


# -- the schedule ------------------------------------------------------------------------------------------------------
def automation(cfg: Any) -> dict[str, Any] | None:
    """The built-in "Learning" automation (weekly, Sunday 03:00 in this computer's time, or the zone in
    ``improve.learning_zone``), present only while the allowance is above 0."""
    if allowance(cfg) <= 0 or not getattr(cfg, "lab_dir", None):
        return None
    from .. import automation as auto

    when = dict(SCHEDULE)
    zone = _improve(cfg).get("learning_zone")
    if zone:
        when["zone"] = str(zone)
    a = auto.normalise({"id": AUTOMATION_ID, "kind": "schedule", "name": "Learning", "when": when,
                        "do": {"what": "learn"}, "created_at": "2000-01-01T00:00:00Z", "source": "builtin"})
    a["source"] = "builtin"
    return a


def money_words(cfg: Any, lab: Any = None) -> str:
    """The automation card's money line."""
    if allowance(cfg) <= 0:
        return OFF_WORDS
    if lab is None and getattr(cfg, "lab_dir", None):
        from .lab import Lab

        lab = Lab(cfg.lab_dir)
    spent = f"{used_words(cfg, lab)}." if lab is not None else ""
    return f"Spends only learning's own allowance ({money(allowance(cfg))} a week). {spent}".strip()


def busy(ctx: Any) -> bool:
    """A project of the lab is building or planning (learning never runs then)."""
    cfg = getattr(ctx, "cfg", None)
    if not cfg or not getattr(cfg, "lab_dir", None):
        return False
    from ..harness.orchestrator import Project
    from .lab import Lab

    for root in Lab(cfg.lab_dir).projects():
        try:
            if getattr(ctx, "busy", None) and ctx.busy(root):
                return True
            if Project(root).meta().get("status") in BUSY_STATES:
                return True
        except Exception:  # noqa: BLE001 - a project that can't be read isn't building
            continue
    return False


def report_words(report: dict[str, Any]) -> str:
    """One cycle's report in a sentence or two."""
    parts = []
    if report.get("stopped"):
        parts.append(report["stopped"])
    n_new, n_test, n_app = len(report.get("new") or []), len(report.get("tested") or []), len(report.get("applied") or [])
    did = []
    if n_new:
        did.append(f"{n_new} new idea{'s' if n_new != 1 else ''}")
    if n_test:
        did.append(f"{n_test} tested")
    if n_app:
        did.append(f"{n_app} applied")
    if report.get("undone"):
        did.append(f"{len(report['undone'])} undone by itself")
    head = ("Learning: " + ", ".join(did) + ".") if did else "Learning: nothing new to change this time."
    spent = float(report.get("spent_usd") or 0)
    tail = f" It spent {money(spent)}." if spent else ""
    return " ".join([head + tail, *parts]).strip()


def run_cycle(cfg: Any, lab: Any, on_event: Callable[[str, dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """The watch first, then one learning cycle on the wallet's money (what the schedule and the after-run step
    use)."""
    from . import canary
    from .loop import cycle

    undone = canary.check(cfg, lab)
    report = cycle(cfg, lab, use_llm=True, test=True, on_event=on_event, wallet=True)
    report["undone"] = [*undone, *(report.get("undone") or [])]
    return report


def job(ctx: Any, a: dict[str, Any]) -> Callable[[Callable[[str], None]], dict[str, Any]]:
    """The scheduled learning cycle as an automation's job: the watch, then the cycle within the allowance."""
    from .. import automation as auto

    def run(log: Callable[[str], None]) -> dict[str, Any]:
        cfg = ctx.cfg
        if busy(ctx):
            text = "A project is building, so learning waits for the next time."
            auto._record(ctx, a, text, True)
            log(text)
            return {"text": text}
        if allowance(cfg) <= 0:
            text = OFF_WORDS
            auto._record(ctx, a, text, True)
            log(text)
            return {"text": text}
        from .lab import Lab

        lab = Lab(cfg.lab_dir)
        before = spent_week(lab)
        try:
            c = cfg.variant()
            lab.apply_learned(c)
            report = run_cycle(c, lab, on_event=lambda kind, d: log(f"{kind}: {d.get('id', '')}".strip()))
            text, ok = report_words(report), True
        except Exception as e:  # the owner reads it on the Automations page
            report, text, ok = {}, f"Learning couldn't run: {e}", False
        spent = max(0.0, spent_week(lab) - before)
        auto._record(ctx, a, text, ok, made={"text": "Learning", "status": "done" if ok else "failed"}, spent=spent)
        for u in report.get("undone") or []:
            _journal(ctx, f"Undone by itself: {u.get('summary', '')}. Why: {u.get('why', '')}")
        log(text)
        return {"text": text, "report": {k: report.get(k) for k in ("new", "tested", "applied", "stopped")}}

    return run


def _journal(ctx: Any, text: str) -> None:
    hub = getattr(ctx, "hub", None)
    if not hub:
        return
    try:
        from ..sync import this_machine

        hub.journal.add(this_machine()["id"], "decision", text, source="harness")
    except Exception:  # noqa: BLE001 - the journal is a note; the undo itself is already done
        pass


# -- the card ------------------------------------------------------------------------------------------------------------
def view(cfg: Any, lab: Any, now: datetime | None = None) -> dict[str, Any]:
    """{allowance, spent, left, week, lines, next_run, words}: numbers only."""
    have = allowance(cfg)
    week = week_of(now)
    rows = lines(lab, week) if lab is not None else []
    spent = round(sum(float(r.get("usd") or 0) for r in rows if r.get("machine", "") == _machine()), 6)
    others = others_spent(lab, week) if lab is not None else 0.0
    by_what: dict[str, float] = {}
    for r in rows:
        by_what[r.get("what") or "tool"] = round(by_what.get(r.get("what") or "tool", 0.0) + float(r.get("usd") or 0), 6)
    nxt = None
    a = automation(cfg)
    if a:
        from .. import automation as auto

        nxt = auto.iso(auto.next_slot(a["when"], _utc(now)))
    return {"allowance": have, "spent": round(spent + others, 6), "spent_here": spent, "spent_elsewhere": others,
            "left": left(cfg, lab, now) if lab is not None else 0.0, "week": week,
            "lines": [{k: r.get(k) for k in ("at", "what", "proposal", "usd", "machine")} for r in rows[-50:]],
            "by_what": by_what, "next_run": nxt, "on": have > 0, "choices": list(CHOICES),
            "words": used_words(cfg, lab), "day_limit": float(getattr(getattr(cfg, "limits", None),
                                                                      "max_usd_per_day", 0) or 0)}


__all__ = ["AllowanceUsed", "LearningBudget", "allowance", "left", "budget", "spent_today", "charge", "lines",
           "week_of", "automation", "job", "view", "save_allowance", "used_words", "stop_words", "money"]
