"""One dial for how much extra checking a plan gets: lean, balanced or maximum (wave 6).

Every tandem stage (the router, the panel of checkers, rival builders, the planning council, named agents)
asks the dial before it does anything extra, and tells it what it spent. At "lean" a stage does nothing, so
a project planned before 1.2.0 (its meta has no ``checking``) runs exactly as before.

| Level    | Ordinary task                                  | Risky task               | Hard task                | The plan                    |
|----------|------------------------------------------------|--------------------------|--------------------------|-----------------------------|
| lean     | 1 builder, 1 checker                           | the same                 | the same                 | 1 planner, today's critique |
| balanced | 1 builder, 1 checker; may try a newer model    | 2 checkers               | 2 builders, 2 checkers   | 1 planner, today's critique |
| maximum  | 2 builders, 3 checkers                         | 2 builders, 3 checkers   | 3 builders, 3 checkers   | 3 planners and a chair      |

Each number can be changed in harness.yaml, for example::

    tandem:
      default: balanced                 # the level a new plan starts at (the project's `checking` setting wins)
      balanced: {hard: {rivals: 2, panel: 2}, risky: {panel: 2}, ordinary: {explore: true}}
      maximum: {planners: 3}
      allowance_over: 1.25              # the extra checking's own share: its line in the agreed estimate times this
      allowance_least_usd: 0.25         # ... and never less than this
      third_checker: {balanced: 0.25, maximum: 0.34}   # how often a third checker is counted (a tie)

The keys each stage writes into a task's attempt (``task.attempts[i]``), read by the dial and the app:

- ``routed``: ``{"from": <the model the role would have used>, "why": <plain words>}`` (the router);
- ``reviews``: ``[{"model", "maker", "approved", "feedback", "breaks", "counted"}]``, one per checker (the panel);
- ``disagreed``: bool, the checkers did not agree (the panel);
- ``same_maker``: bool, a checker was made by the builder's maker (the panel; warned about, never refused);
- ``rival``: ``"r1"``, which rival attempt this was (rivals);
- ``rivals``: ``[{"id", "model", "maker", "tests", "picked", "why", "branch", "cost_usd"}]`` (rivals);
- ``agent``: the named agent's id who did the work (agents).

**Its own share of the money.** At approval the extra checking gets an allowance: the dial's line in the
agreed estimate times 1.25, never less than $0.25 (``.harness/tandem.json``). ``allow`` says no once what the
stages spent since (``.harness/tandem.jsonl``) plus the next extra would pass it; from then on every stage runs
the usual way, with one note in the journal. The whole run stays under the money gate (moneystage.py).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from ..core.models import utcnow

LEVELS = ("lean", "balanced", "maximum")
DEFAULT_LEVEL = "balanced"
LEDGER = Path(".harness") / "tandem.jsonl"
ALLOWANCE = Path(".harness") / "tandem.json"
NAMES = {"lean": "Lean", "balanced": "Balanced", "maximum": "Maximum"}
TIPS = {
    "lean": "One model builds each task and one checks it, as before",
    "balanced": "Tasks the planner marked hard get a second builder and a second checker; risky ones a second "
                "checker. Easy tasks may try a newer model",
    "maximum": "Every task gets two builders (three when hard) and up to three checkers, and three planners "
               "write rival plans that a chair merges",
}
ALLOWANCE_OVER = 1.25
ALLOWANCE_LEAST_USD = 0.25
THIRD_CHECKER = {"lean": 0.0, "balanced": 0.25, "maximum": 1 / 3}  # a tie between two checkers asks a third
ALLOWANCE_NOTE = ("Extra checking has used its share of the money for this goal; the rest is built the usual way.")

# the table: (level, kind of task) -> counts. "ordinary" / "risky" / "hard"; "plan" for the planners
TABLE: dict[str, dict[str, dict[str, Any]]] = {
    "lean": {"ordinary": {"rivals": 1, "panel": 1, "explore": False}, "risky": {"rivals": 1, "panel": 1, "explore": False},
             "hard": {"rivals": 1, "panel": 1, "explore": False}, "plan": {"planners": 1}},
    "balanced": {"ordinary": {"rivals": 1, "panel": 1, "explore": True}, "risky": {"rivals": 1, "panel": 2, "explore": False},
                 "hard": {"rivals": 2, "panel": 2, "explore": False}, "plan": {"planners": 1}},
    "maximum": {"ordinary": {"rivals": 2, "panel": 3, "explore": False}, "risky": {"rivals": 2, "panel": 3, "explore": False},
                "hard": {"rivals": 3, "panel": 3, "explore": False}, "plan": {"planners": 3}},
}

_LOCK = threading.RLock()  # the allowance file and the ledger: read and written by stages in parallel lanes


def _known(value: Any) -> str:
    v = str(value or "").strip().lower()
    return v if v in LEVELS else ""


def _tandem(cfg: Any) -> dict[str, Any]:
    try:
        from .config import section

        return section(cfg, "tandem")
    except Exception:  # noqa: BLE001 - no config: the table as written
        return {}


def _count(v: Any, default: int) -> int:
    try:
        return max(1, min(3, int(v)))
    except (TypeError, ValueError):
        return default


def table(cfg: Any, lvl: str) -> dict[str, dict[str, Any]]:
    """The level's row of the table with harness.yaml's ``tandem:`` overrides laid over it."""
    base = {k: dict(v) for k, v in TABLE.get(lvl, TABLE["lean"]).items()}
    if lvl == "lean":
        return base  # lean is today's behaviour: nothing can switch extras on at lean
    over = _tandem(cfg).get(lvl)
    if not isinstance(over, dict):
        return base
    if "planners" in over:  # tandem: {maximum: {planners: 2}}
        base["plan"]["planners"] = _count(over["planners"], base["plan"]["planners"])
    for kind in ("ordinary", "risky", "hard", "plan"):
        o = over.get(kind)
        if not isinstance(o, dict):
            continue
        for k, v in o.items():
            if k in ("rivals", "panel", "planners"):
                base[kind][k] = _count(v, base[kind].get(k, 1))
            elif k == "explore":
                base[kind][k] = v is True
    return base


def _kind(task: Any) -> str:
    return "hard" if getattr(task, "hard", False) else "risky" if getattr(task, "risky", False) else "ordinary"


def _num(cfg: Any, key: str, default: float) -> float:
    try:
        return max(0.0, float(_tandem(cfg).get(key, default)))
    except (TypeError, ValueError):
        return default


def third_share(cfg: Any, lvl: str) -> float:
    """How often a third checker is counted on a task with two or more (a tie): one in four under Balanced,
    one in three under Maximum."""
    raw = _tandem(cfg).get("third_checker")
    try:
        if isinstance(raw, dict) and lvl in raw:
            return max(0.0, min(1.0, float(raw[lvl])))
    except (TypeError, ValueError):
        pass
    return THIRD_CHECKER.get(lvl, 0.0)


# -- the level ------------------------------------------------------------------------------------------------
def level(orch: Any) -> str:
    """The plan's level (``meta["checking"]``); "lean" when absent (plans made before 1.2.0)."""
    as_if = _known(getattr(orch, "_dial_as", ""))  # pricing another level (checking_estimates)
    if as_if:
        return as_if
    try:
        return _known(orch.project.meta().get("checking")) or "lean"
    except Exception:  # noqa: BLE001 - no project yet: the safe answer
        return "lean"


def level_for_new_plan(orch: Any) -> str:
    """The level a new plan starts at: the project's ``checking`` setting, else the owner's own last choice
    for this project (``set_checking``), else ``tandem.default`` in harness.yaml, else "balanced"."""
    try:
        chosen = _known(orch.project_settings().values.get("checking"))
    except Exception:  # noqa: BLE001 - settings with a mistake never stop a plan here
        chosen = ""
    if chosen:
        return chosen
    try:
        chosen = _known(orch.project.meta().get("checking_chosen"))
    except Exception:  # noqa: BLE001
        chosen = ""
    if chosen:
        return chosen
    return _known(_tandem(getattr(orch, "cfg", None)).get("default")) or DEFAULT_LEVEL


def for_task(orch: Any, task: Any) -> dict[str, Any]:
    """How many builders (``rivals``) and checkers (``panel``) this task gets, whether the router may try a
    newer model (``explore``), and why (``""``, ``"hard"``, ``"risky"`` or ``"maximum"``). Once the extra
    checking has used its share of the money, every task gets the lean answer."""
    lvl = level(orch)
    lean = {"rivals": 1, "panel": 1, "explore": False, "why": ""}
    if lvl == "lean" or (not getattr(orch, "_dial_as", "") and _used_up(orch)):
        return lean
    return _answer(getattr(orch, "cfg", None), lvl, task)


def _answer(cfg: Any, lvl: str, task: Any) -> dict[str, Any]:
    kind = _kind(task)
    row = table(cfg, lvl)[kind]
    why = ""
    if row["rivals"] > 1 or row["panel"] > 1:
        why = kind if kind != "ordinary" else "maximum"
    return {"rivals": row["rivals"], "panel": row["panel"], "explore": bool(row["explore"]) and kind == "ordinary",
            "why": why}


def for_plan(orch: Any) -> dict[str, Any]:
    """How many rival planners this plan gets (1: one planner and today's critique). A new plan is asked
    about before its level is written, so this reads the level the new plan will get."""
    as_if = _known(getattr(orch, "_dial_as", ""))
    lvl = as_if or level_for_new_plan(orch)
    return {"planners": table(getattr(orch, "cfg", None), lvl)["plan"]["planners"] if lvl != "lean" else 1}


# -- its own share of the money -------------------------------------------------------------------------------
def _root(orch: Any) -> Path:
    return Path(orch.project.root)


def _goal(orch: Any) -> int:
    try:
        return max(0, len(orch.project.meta().get("goals") or []) - 1)
    except Exception:  # noqa: BLE001
        return 0


def _ledger_rows(root: Path) -> list[dict[str, Any]]:
    p = root / LEDGER
    try:
        lines = p.read_text(encoding="utf-8").splitlines() if p.is_file() else []
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            d = json.loads(ln)
        except ValueError:
            d = {}
        out.append(d if isinstance(d, dict) else {})
    return out


def read_allowance(root: Path | str) -> dict[str, Any] | None:
    """The saved allowance (``.harness/tandem.json``), None when there is none."""
    p = Path(root) / ALLOWANCE
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _write_allowance(root: Path, d: dict[str, Any]) -> None:
    p = root / ALLOWANCE
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(".tandem.json.tmp")
    tmp.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def spent_since(root: Path | str, allowance: dict[str, Any] | None) -> float:
    """What the stages noted spending since the allowance was set (all of it when there is none)."""
    rows = _ledger_rows(Path(root))
    start = int((allowance or {}).get("ledger_from") or 0)
    return round(sum(float(r.get("usd") or 0) for r in rows[start:]), 6)


def _current(orch: Any) -> dict[str, Any] | None:
    """This goal's allowance, None before approval (planning) or for an older goal."""
    a = read_allowance(_root(orch))
    if not a or int(a.get("goal", -1)) != _goal(orch):
        return None
    return a


def _used_up(orch: Any) -> bool:
    try:
        a = _current(orch)
    except Exception:  # noqa: BLE001
        return False
    return bool(a and a.get("used_up"))


def _use_up(orch: Any, a: dict[str, Any]) -> None:
    """The allowance said no for the first time: from now on the usual way, and one note for the owner."""
    a["used_up"] = True
    a["used_up_at"] = utcnow()
    _write_allowance(_root(orch), a)
    for fn, args in (("emit", ("tandem_allowance", {"usd": a.get("usd"), "spent": spent_since(_root(orch), a)})),
                     ("_journal", ("note", ALLOWANCE_NOTE))):
        f = getattr(orch, fn, None)
        if callable(f):
            try:
                f(*args)
            except Exception:  # noqa: BLE001 - a note never stops a run
                pass


def allow(orch: Any, what: str, usd: float | None) -> bool:
    """Is there room left in the extra-checking allowance for ``what`` (a stage's name) to spend ``usd``?

    Never at lean. Before approval (the council plans before anything is agreed) there is no allowance yet:
    yes, within the stage's own cap and the money gate. After approval: no once the spend so far plus ``usd``
    would pass the allowance, and from then on no for the rest of the goal. ``usd`` None (no price): yes while
    something is left."""
    if level(orch) == "lean":
        return False
    try:
        with _LOCK:
            a = _current(orch)
            if a is None:
                return True
            if a.get("used_up"):
                return False
            used = spent_since(_root(orch), a)
            limit = float(a.get("usd") or 0)
            need = 0.0 if usd is None else max(0.0, float(usd))
            if (used + need <= limit + 1e-9) if usd is not None else used < limit:
                return True
            _use_up(orch, a)
            return False
    except (OSError, TypeError, ValueError):  # the bookkeeping can't be read: the usual way, to be safe
        return False


def spent(orch: Any, what: str, usd: float, task_id: str = "") -> None:
    """Note money a stage spent on extra checking: one line in ``.harness/tandem.jsonl``."""
    try:
        p = Path(orch.project.root) / LEDGER
        row = {"at": utcnow(), "what": str(what), "usd": round(float(usd or 0.0), 6), "task": str(task_id or ""),
               "goal": _goal(orch)}
        with _LOCK:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
    except (OSError, TypeError, ValueError):  # bookkeeping: never stops a run
        pass


def agree(orch: Any) -> dict[str, Any]:
    """Set this goal's allowance from the dial's line in the agreed estimate (at approval, and when the level
    changes after it). Money already spent on extras this goal stays counted."""
    doc = orch.project.plan_doc() or {}
    line = _line(doc.get("estimate"))
    over = _num(orch.cfg, "allowance_over", ALLOWANCE_OVER)
    least = _num(orch.cfg, "allowance_least_usd", ALLOWANCE_LEAST_USD)
    with _LOCK:
        root = _root(orch)
        old = _current(orch)
        if old is not None:  # the level changed after approval: what's left to do, on top of what was spent
            done = spent_since(root, old)
            start = int(old.get("ledger_from") or 0)
        else:
            done, start = 0.0, len(_ledger_rows(root))
        usd = round(done + max(line * over, least), 4)
        a = {"goal": _goal(orch), "usd": usd, "line_usd": round(line, 4), "level": level(orch), "at": utcnow(),
             "ledger_from": start, "used_up": False}
        _write_allowance(root, a)
    return a


def _line(est: dict[str, Any] | None) -> float:
    for e in (est or {}).get("extras") or []:
        if isinstance(e, dict) and e.get("id") == "dial":
            try:
                return float(e.get("usd") or 0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def allowance_view(root: Path | str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """{usd, spent, used_up} for this goal (usd None before approval)."""
    a = read_allowance(root)
    goal = max(0, len((meta or {}).get("goals") or []) - 1)
    if not a or (meta is not None and int(a.get("goal", -1)) != goal):
        return {"usd": None, "spent": 0.0, "used_up": False}
    return {"usd": a.get("usd"), "spent": spent_since(root, a), "used_up": bool(a.get("used_up"))}


# -- the price --------------------------------------------------------------------------------------------------
def _units(cfg: Any, role: Any, h: dict[str, Any] | None) -> tuple[float | None, float | None, float]:
    """(one build, one review, attempts a task) for a role: from past runs where there are some (the same
    sizes the estimate uses), else the typical sizes."""
    from ..providers.base import Usage
    from . import plandoc

    model = role.models[0]
    reviewer = cfg.roles.get(cfg.reviewer_role or "")
    default_review = cfg.cost(reviewer.models[0], Usage(*plandoc.DEFAULT_REVIEW_TOKENS)) if reviewer else None
    if h and h.get("samples", 0) >= 3 and h.get("cost") is not None:
        cost = plandoc._reprice(cfg, h["cost"], h, model)
        attempts = max(1.0, float(h.get("attempts") or 1))
        try:
            build = cfg.cost(model, Usage(int(h.get("input") or 0), int(h.get("output") or 0)))
        except ValueError:
            build = None
        if cost is not None and build is not None and build <= cost:
            review = (cost - build) / attempts if role.review and reviewer else default_review
            return build / attempts, review, attempts
    i, o = plandoc.DEFAULT_TOKENS["chat"]
    return cfg.cost(model, Usage(i, o)), default_review, 1.0


def _task_price(cfg: Any, lvl: str, task: Any, history: dict[str, Any]) -> dict[str, Any] | None:
    """One task's extras at a level: {rivals, panel, usd, minutes, checkers, builders}, None when it has none."""
    from . import plandoc

    role = cfg.roles.get(getattr(task, "role", ""))
    if role is None or role.kind != "chat" or lvl == "lean":
        return None
    ans = _answer(cfg, lvl, task)
    reviewer = cfg.roles.get(cfg.reviewer_role or "")
    reviewed = bool(role.review and reviewer)
    builders = ans["rivals"] - 1
    checkers = (1 + third_share(cfg, lvl)) if (ans["panel"] > 1 and reviewed) else 0.0
    if not builders and not checkers:
        return None
    build, review, attempts = _units(cfg, role, history.get(task.role))
    picks = 1 if builders and reviewer else 0  # one "pick" call when several rivals pass
    rivals_usd = None if build is None or (picks and review is None) else builders * build + picks * (review or 0)
    panel_usd = None if checkers and review is None else checkers * (review or 0) * attempts
    usd = None if rivals_usd is None or panel_usd is None else rivals_usd + panel_usd
    minutes = (picks + checkers) * plandoc.REVIEW_MINUTES  # rival builders work side by side
    return {"rivals": rivals_usd, "panel": panel_usd, "usd": usd, "minutes": minutes, "builders": builders,
            "checkers": checkers, "why": ans["why"]}


def price(cfg: Any, tasks: list[Any], level: str, history: dict[str, Any] | None = None) -> dict[str, Any]:
    """What a level's extra checking adds to these tasks, before anything runs: {usd, minutes, parts: {rivals,
    panel}, words, tasks (how many get extras), unpriced}. An extra checker is one review; a rival is one build
    with no retry allowance, plus one pick call a task; a third checker is counted at one task in four under
    Balanced and one in three under Maximum. ``usd`` None when a model has no price."""
    lvl = _known(level) or "lean"
    history = history or {}
    usd: float | None = 0.0
    minutes, parts, n, unpriced = 0.0, {"rivals": 0.0, "panel": 0.0}, 0, False
    hard_or_risky = True
    for t in tasks:
        if getattr(t, "status", "pending") != "pending":
            continue
        p = _task_price(cfg, lvl, t, history)
        if not p:
            continue
        n += 1
        hard_or_risky = hard_or_risky and p["why"] in ("hard", "risky")
        minutes += p["minutes"]
        for k in ("rivals", "panel"):
            if p[k] is None:
                unpriced = True
            else:
                parts[k] += p[k]
        if p["usd"] is None:
            usd = None
        elif usd is not None:
            usd += p["usd"]
    out = {"usd": None if usd is None else round(usd, 4), "minutes": round(minutes, 1),
           "parts": {k: round(v, 4) for k, v in parts.items()}, "tasks": n, "unpriced": unpriced, "level": lvl}
    out["words"] = price_words(out, hard_or_risky)
    return out


def price_words(p: dict[str, Any], hard_or_risky: bool = True) -> str:
    """"extra checking on 4 hard or risky tasks: about $0.40" ("" when there is none)."""
    n = int(p.get("tasks") or 0)
    if not n:
        return ""
    which = "hard or risky " if hard_or_risky else ""
    head = f"extra checking on {n} {which}task{'s' * (n != 1)}"
    if p.get("usd") is None:
        return head + " (some models have no price yet)"
    return f"{head}: about ${float(p['usd']):.2f}"


def task_cost(orch: Any, task: Any, what: str) -> float | None:
    """The estimate's figure for one stage's extra on one task ("rivals" or "panel"), for that stage's
    ``allow`` call. None when a model has no price."""
    try:
        hist = _history(orch)
        p = _task_price(orch.cfg, level(orch), task, hist)
    except Exception:  # noqa: BLE001
        return None
    return 0.0 if not p else p.get(what)


def _metric_files(orch: Any) -> list[Path]:
    """The past runs the estimate reads: this project's metrics and the lab's (the same files as _estimate)."""
    files = [orch.project.dir / "metrics.jsonl"]
    if getattr(orch.cfg, "lab_dir", None):
        try:
            from ..improve.lab import Lab

            files += [p / ".harness" / "metrics.jsonl" for p in Lab(orch.cfg.lab_dir).projects()]
        except Exception:  # noqa: BLE001 - the estimate never stops anything
            pass
    seen, uniq = set(), []
    for f in files:
        if f.is_file() and f.resolve() not in seen:
            seen.add(f.resolve())
            uniq.append(f)
    return uniq


def _history(orch: Any) -> dict[str, Any]:
    from . import plandoc

    return plandoc.history_by_role(_metric_files(orch))


def planning_usd(cfg: Any, planners: int) -> float | None:
    """What rival planners and a chair cost before anything is approved: the council's own figure when it is
    there, else (2n + 1) planning calls at the typical sizes."""
    if planners < 2:
        return 0.0
    try:
        from . import council  # d3-council

        got = council.estimate(cfg, planners)
        if isinstance(got, dict):
            got = got.get("usd", got.get("cost_usd"))
        return None if got is None else float(got)
    except Exception:  # noqa: BLE001 - not there yet, or it failed: the same sum here
        pass
    from ..providers.base import Usage
    from . import plandoc

    role = cfg.roles.get(cfg.planner_role or "") if hasattr(cfg, "planner_role") else None
    role = role or cfg.roles.get("orchestrator")
    if role is None:
        return None
    one = cfg.cost(role.models[0], Usage(*plandoc.DEFAULT_TOKENS["chat"]))
    return None if one is None else round((2 * planners + 1) * one, 4)


# -- words the owner reads --------------------------------------------------------------------------------------
def label(lvl: str) -> str:
    """"Checking: Balanced" (always labelled: the model sets have a Balanced too)."""
    return f"Checking: {NAMES.get(_known(lvl) or 'lean')}"


def words(orch: Any) -> str:
    """"Checking: Balanced (about $0.40 of this)" for the approval card; "Checking: Lean" with no extras."""
    try:
        doc = orch.project.plan_doc() or {}
        return words_for(level(orch), doc.get("estimate"))
    except Exception:  # noqa: BLE001
        return label(level(orch))


def words_for(lvl: str, est: dict[str, Any] | None) -> str:
    line = next((e for e in (est or {}).get("extras") or [] if isinstance(e, dict) and e.get("id") == "dial"), None)
    if not line or _known(lvl) in ("", "lean"):
        return label(lvl)
    return f"{label(lvl)} (about ${float(line.get('usd') or 0):.2f} of this)"


# -- changing it ------------------------------------------------------------------------------------------------
def estimates(orch: Any, tasks: list[Any] | None = None, has_ui: bool | None = None) -> dict[str, dict[str, Any]]:
    """The plan under every level: {lean, balanced, maximum: {cost_usd, minutes, extra_usd, planning_usd}}.
    Maximum's figure includes its rival planners (the council)."""
    tasks = orch.project.tasks() if tasks is None else tasks
    out: dict[str, dict[str, Any]] = {}
    keep = getattr(orch, "_dial_as", "")
    try:
        for lvl in LEVELS:
            orch._dial_as = lvl
            e = orch._estimate(tasks, has_ui)
            extra = _line(e)
            plan = planning_usd(orch.cfg, for_plan(orch)["planners"]) if lvl != "lean" else 0.0
            cost = e.get("cost_usd")
            if cost is not None and plan:
                cost = round(cost + plan, 4)
            out[lvl] = {"cost_usd": cost, "minutes": e.get("minutes"), "extra_usd": round(extra, 4),
                        "planning_usd": plan, "unpriced": bool(e.get("unpriced")) or plan is None}
    finally:
        orch._dial_as = keep
    return out


def confirm(orch: Any, name: str) -> dict[str, Any]:
    """What to ask before changing the level: {ask, words, from_usd, to_usd, planning_usd}. Maximum always
    asks, with both figures and its planning cost."""
    name = _known(name)
    doc = orch.project.plan_doc() or {}
    ests = doc.get("checking_estimates") or estimates(orch, _pending(orch), doc.get("has_ui"))
    now = level(orch)
    a, b = ests.get(now) or {}, ests.get(name) or {}
    plan = b.get("planning_usd") or 0
    text = ""
    if name == "maximum":
        text = (f"Maximum checking: about ${float(b.get('cost_usd') or 0):.2f} instead of about "
                f"${float(a.get('cost_usd') or 0):.2f} ({NAMES.get(now, 'Lean')}).")
        if plan:
            text += f" Three planners and a chair cost about ${float(plan):.2f} of that, the next time it plans."
    return {"ask": name == "maximum", "words": text, "from_usd": a.get("cost_usd"), "to_usd": b.get("cost_usd"),
            "planning_usd": plan}


def _pending(orch: Any) -> list[Any]:
    doc = orch.project.plan_doc() or {}
    gi = doc.get("goal_index")
    return [t for t in orch.project.tasks() if t.status == "pending" and (gi is None or t.goal_index == gi)]


def set_checking(orch: Any, name: str) -> dict[str, Any]:
    """The owner chose a level (never autopilot). Re-estimates the plan. After approval the allowance follows
    the new level, and a dearer level simply meets the money gate's card when the run goes on."""
    lvl = _known(name)
    if not lvl:
        from .orchestrator import HarnessError

        raise HarnessError(f"checking must be one of {', '.join(LEVELS)}")
    meta = orch.project.meta()
    meta["checking"] = lvl
    meta["checking_chosen"] = lvl
    orch.project.save_meta(meta)
    doc = orch.project.plan_doc()
    if doc:
        pend = _pending(orch)
        doc["checking"] = lvl
        doc["estimate"] = orch._estimate(pend, doc.get("has_ui"))
        doc["checking_estimates"] = estimates(orch, pend, doc.get("has_ui"))
        orch.project.save_plan_doc(doc)
        if meta.get("plan_approved"):
            agree(orch)
        pub = getattr(orch, "_publish_plan", None)
        if callable(pub):
            pub()
    try:
        orch.emit("checking", {"level": lvl})
    except Exception:  # noqa: BLE001
        pass
    return {"level": lvl, "words": words(orch), "estimates": (doc or {}).get("checking_estimates") or {}}


# -- the stage ---------------------------------------------------------------------------------------------------
class DialStage:
    """A mixin for Orchestrator: the dial's line in the estimate, its part of the plan document, its share of
    the money at approval."""

    def _dial_estimate(self, tasks) -> dict[str, Any] | None:
        lvl = level(self)
        if lvl == "lean":
            return None
        p = price(self.cfg, [t for t in tasks if t.status == "pending"], lvl, _history(self))
        if not p["tasks"]:
            return None
        return {"id": "dial", "usd": p["usd"] or 0.0, "minutes": p["minutes"], "words": p["words"],
                "level": lvl, "unpriced": p["unpriced"]}

    def _dial_doc(self, doc: dict[str, Any], args: dict[str, Any]) -> None:
        """The level and the plan's figure under each level. A new plan (version 1) takes the level it will
        be given; a revised one keeps the project's."""
        new = int(doc.get("version") or 1) <= 1
        lvl = level_for_new_plan(self) if new else level(self)
        doc["checking"] = lvl
        tasks = _tasks_from(args, self.cfg) or _pending(self)
        keep = getattr(self, "_dial_as", "")
        try:  # the estimate made right after this part reads meta, written by plan() just after the parts
            doc["checking_estimates"] = estimates(self, tasks, doc.get("has_ui"))
        finally:
            self._dial_as = keep

    def _dial_agreed(self) -> dict[str, Any] | None:
        """At approval (after _money_agreed): the extra checking's own share of the agreed money."""
        if level(self) == "lean" or not self.project.plan_doc():
            return None
        return agree(self)


def _tasks_from(args: dict[str, Any], cfg: Any) -> list[Any]:
    """The submitted tasks as Task objects for pricing (the plan's tasks aren't saved yet when revising)."""
    from .orchestrator import Task

    out = []
    for t in (args or {}).get("tasks") or []:
        if not isinstance(t, dict) or t.get("role") not in cfg.roles:
            continue
        out.append(Task(id=str(t.get("id") or ""), title=str(t.get("title") or ""), role=t["role"],
                        description=str(t.get("description") or ""), hard=t.get("hard") is True,
                        risky=t.get("risky") is True))
    return out
