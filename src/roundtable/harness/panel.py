"""Several checkers from different makers, who must quote what is broken (wave 6, "checking each other").

The project's own tests have had their say first (``Orchestrator._review``). Then, unless the plan is "lean"
(a plan made before 1.2.0, or the owner's choice), the panel checks the work:

- **Who checks** (``pick``): models from the reviewer's chain, then the critic's, then (Maximum only) the
  planner's; one per maker, never the builder's maker, each one the project allows (``_may_use``) and not out
  of credit. With no other maker to hand, the first reviewer checks and the record says ``same_maker``.
- **The quote rule** (``quoted``): a rejection's ``breaks`` must be found in the task's description, its
  done-when, the plan's don't list, the done list or the failing test output (case and spacing ignored, at
  least 12 characters, or a whole short line). If it isn't, the same checker is asked once more: "Quote the
  line it breaks, or approve." Still unquoted: a checker from another maker decides when there is one and the
  dial allows it; otherwise the rejection counts, marked ``counted: "unquoted"``. An unquoted rejection is
  never turned into a pass by itself.
- **The verdict**: checkers run one after another (they share one working copy and may run its tests). With
  one checker, its verdict. With two or three, two that agree end it; a split goes to a third maker (or the
  strongest reviewer left), who decides. A split nobody can settle stays a rejection.
- **Money**: every call beyond the first checker asks ``dial.allow`` first and tells ``dial.spent`` after.
  The result is one ``AgentResult`` with the costs added up.

What each checker said goes into the task's attempt (``reviews``, ``disagreed``, ``same_maker``, through
``_panel_attempt``) and into ``.harness/reviews.jsonl`` (one row per verdict and one for the decision).
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from ..core.models import utcnow
from . import dial, makers

SAME_MAKER = "The checker is from the same maker as the builder: it checks less."
REASK = ("Your rejection did not quote what the work breaks. A rejection counts only when it quotes the exact "
         "words it breaks: from the task, its acceptance criteria (done-when), the plan's don't list, the done "
         "list, or the failing test output. Quote the line it breaks in `breaks`, or approve.")
MIN_QUOTE = 12
LEDGER = "reviews.jsonl"  # in .harness/, beside metrics.jsonl (the lab learns from it in wave 7)

_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-",
                         "`": "'"})
_ELLIPSIS = re.compile(r"\.\.\.+|…")


def _norm(text: Any) -> str:
    return " ".join(str(text or "").translate(_QUOTES).lower().split())


def _trim(text: str) -> str:
    """A quote without the marks around it: "…", «…», a trailing full stop."""
    return text.strip().strip("\"'«»<>()[]").strip().rstrip(".,;:").strip()


def sources(orch: Any, task: Any, checks: dict[str, Any] | None) -> list[str]:
    """Everything a rejection may quote: the task, its done-when, the plan's don'ts and done list, and the
    failing test output."""
    out = [getattr(task, "description", ""), getattr(task, "acceptance", "")]
    try:
        doc = orch.project.plan_doc() or {}
    except Exception:  # noqa: BLE001 - no plan document: the task alone
        doc = {}
    for key in ("dont", "done_list"):
        out += [str(x.get("text") or "") for x in doc.get(key) or [] if isinstance(x, dict)]
    if checks and checks.get("verdict") != "pass":
        now = checks.get("now") or {}
        out += [str(checks.get("text") or ""), str(now.get("tail") or ""), *map(str, checks.get("new") or [])]
    return [s for s in out if s and s.strip()]


def quoted(breaks: Any, texts: list[str]) -> bool:
    """Is ``breaks`` really in one of ``texts``? Case, spacing and quote marks are ignored; it needs at least
    12 characters, or to be a whole short line. A quote cut with "..." needs every piece in the same text."""
    pieces = [_trim(_norm(p)) for p in _ELLIPSIS.split(_norm(breaks))]
    pieces = [p for p in pieces if p]
    if not pieces:
        return False
    for text in texts:
        t = _norm(text)
        lines = {_trim(_norm(x)) for x in str(text).splitlines()} | {_trim(t)}
        if not all(p in t for p in pieces):
            continue
        if sum(len(p) for p in pieces) >= MIN_QUOTE or (len(pieces) == 1 and pieces[0] in lines):
            return True
    return False


def _chain(orch: Any, name: str | None) -> list:
    role = orch.cfg.roles.get(name or "") if name else None
    return list(role.models) if role and role.kind == "chat" else []


def _usable(orch: Any, refs: list) -> list:
    out, seen = [], set()
    for r in refs:
        if str(r) in seen or not orch._may_use(r) or orch._blocked(r):
            continue
        seen.add(str(r))
        out.append(r)
    return out


def _pool(orch: Any, stronger: bool = False) -> list:
    """Every model that may check, in order: the reviewer's chain (turned round after a rejection, as the
    usual review does), the critic's, then the planner's at Maximum. Only models the project allows and
    that still have credit."""
    rev = _chain(orch, orch.cfg.reviewer_role)
    if stronger and len(rev) > 1:
        rev = rev[1:] + rev[:1]
    refs = rev + _chain(orch, orch.cfg.critic_role)
    if dial.level(orch) == "maximum":
        refs += _chain(orch, orch.cfg.planner_role)
    return _usable(orch, refs)


def pick(orch: Any, task: Any, built_by: Any, n: int, stronger: bool = False) -> list:
    """Up to ``n`` checkers, one per maker, never the builder's maker. With no other maker to hand: the
    first reviewer alone (same maker; warned about, never refused)."""
    pool = _pool(orch, stronger)
    others = makers.distinct(pool, not_maker=makers.maker(built_by) if built_by else "")
    return others[:max(1, n)] if others else pool[:1]


def _spare(orch: Any, used: set[str], built_by: Any) -> Any:
    """The strongest checker left when no new maker is: the Quality set's reviewers, then anyone in the
    pool not used yet (never the builder itself)."""
    strong: list = []
    try:
        quality = next((p for p in orch.base_cfg.profiles if p.lower() == "quality"), None)
        if quality and orch.cfg.reviewer_role:
            role = orch._settle_cfg(orch.base_cfg.for_profile(quality)).roles.get(orch.cfg.reviewer_role)
            strong = list(role.models) if role else []
    except Exception:  # noqa: BLE001 - no Quality set: the pool alone
        strong = []
    for r in _usable(orch, strong) + _pool(orch):
        if str(r) not in used and str(r) != str(built_by):
            return r
    return None


def same_maker_warnings(cfg: Any) -> list[str]:
    """For Models: one line when some job's work can only be checked by its own maker's models."""
    names = [cfg.reviewer_role, cfg.critic_role]
    checkers = {makers.maker(m) for n in names if n and n in cfg.roles for m in cfg.roles[n].models}
    if not checkers or not cfg.reviewer_role or cfg.reviewer_role not in cfg.roles:
        return []
    for name, role in cfg.roles.items():
        if name in names or role.kind != "chat" or not getattr(role, "review", True) or not role.models:
            continue
        if name == getattr(cfg, "planner_role", None):
            continue
        if checkers <= {makers.maker(role.models[0])}:
            return [SAME_MAKER]
    return []


class PanelStage:
    """Several checkers from different makers (``_panel_review``), recorded on the attempt
    (``_panel_attempt``)."""

    def _panel_review(self, task, worker_summary, checks, stronger, built_by):
        if dial.level(self) == "lean":
            return None  # today's one reviewer, exactly as before
        plan = dial.for_task(self, task) or {}
        n = max(1, min(3, int(plan.get("panel") or 1)))
        queue = pick(self, task, built_by, 99, stronger)  # every other maker: seats, spares, tiebreak
        if not queue:
            return None
        texts = sources(self, task, checks)
        p = _Panel(self, task, worker_summary, checks, built_by, texts, queue, why=str(plan.get("why") or ""))
        got = p.run(n)
        if got is None:
            return None
        record = p.record()
        self._panel_keep(task, built_by, record)
        p.ledger(got[0])
        self.emit("panel", {"task": task.id, "approved": bool(got[0]), "checkers": len(p.seats),
                            "disagreed": record["disagreed"], "same_maker": record["same_maker"]})
        return got

    def _panel_keep(self, task, built_by, record):
        with self._lock:
            if not hasattr(self, "_panel_last"):
                self._panel_last = {}
            self._panel_last[task.id] = (str(built_by), record)

    def _panel_attempt(self, task, ref):
        with self._lock:
            kept = getattr(self, "_panel_last", {}).pop(task.id, None)
        if not kept or kept[0] != str(ref):
            return None
        return kept[1]


class _Panel:
    """One task's checking: the seats, the quote rule, the tiebreak."""

    def __init__(self, orch, task, summary, checks, built_by, texts, queue, why=""):
        self.o, self.task, self.summary, self.checks = orch, task, summary, checks
        self.built_by, self.texts, self.queue, self.why = built_by, texts, list(queue), why
        self.builder = makers.maker(built_by) if built_by else ""
        self.used: set[str] = set()
        self.reviews: list[dict[str, Any]] = []
        self.results: list = []
        self.calls = 0
        self.disagreed = False
        self.last_cost: float | None = None

    # -- money -----------------------------------------------------------------------------------------------
    def _may_spend(self) -> bool:
        """The first call is today's one review; every one after it is extra and asks the dial first."""
        return self.calls == 0 or bool(dial.allow(self.o, "panel", self.last_cost))

    # -- one call --------------------------------------------------------------------------------------------
    def _ask(self, ref, note="") -> dict[str, Any] | None:
        """One checker's verdict, or None when it could not be reached (the next one is tried)."""
        from .orchestrator import HarnessError

        extra = self.calls > 0
        self.calls += 1
        self.used.add(str(ref))
        try:
            ok, fb, res, verdict = self.o._review_once(self.task, self.summary, self.checks, [ref], note=note)
        except HarnessError as e:  # its service failed or refused: try the next checker
            self.o.emit("panel_skip", {"task": self.task.id, "model": str(ref), "error": str(e)[:300]})
            return None
        if res is not None:
            self.results.append(res)
            self.last_cost = res.cost_usd
            if extra:
                dial.spent(self.o, "panel", res.cost_usd, self.task.id)
        return {"ref": ref, "ok": ok, "fb": fb, "verdict": verdict, "breaks": str(verdict.get("breaks") or "")}

    def _note(self, ref, got, counted, reasked=False, seat=0):
        self.reviews.append({"model": str(ref), "maker": makers.maker(ref), "approved": bool(got["ok"]),
                             "feedback": got["fb"][:1000], "breaks": got["breaks"][:500], "counted": counted,
                             "reasked": reasked, "seat": seat})

    def _next(self, avoid: set[str]):
        for i, ref in enumerate(self.queue):
            if str(ref) not in self.used and makers.maker(ref) not in avoid:
                return self.queue.pop(i)
        return None

    # -- one seat: a checker, the quote rule, and who decides an unquoted rejection ---------------------------
    def seat(self, ref, number: int, escalate: bool = True) -> dict[str, Any] | None:
        """A counted verdict ``{"ok", "fb", "breaks", "ref", "counted"}``, or None when nobody could check."""
        while ref is not None:
            if not self._may_spend():
                return None
            got = self._ask(ref)
            if got is None or not got["verdict"]:  # unreachable, or no verdict: the next checker
                if got is not None:
                    self._note(ref, got, False, seat=number)
                ref = self._next({self.builder} | {r["maker"] for r in self.reviews})
                continue
            if got["ok"] or quoted(got["breaks"], self.texts):
                self._note(ref, got, True, seat=number)
                return {**got, "counted": True}
            # unquoted: ask the same checker once more
            again = self._ask(ref, note=f"{REASK}\n\nYou said: {got['fb'][:800]}") if self._may_spend() else None
            reasked = again is not None
            if again is not None and again["verdict"]:
                self._note(ref, got, False, seat=number)
                got = again
                if got["ok"] or quoted(got["breaks"], self.texts):
                    self._note(ref, got, True, reasked=True, seat=number)
                    return {**got, "counted": True}
            # still unquoted: a checker from another maker decides, when there is one and the dial allows it
            self._note(ref, got, False, reasked=reasked, seat=number)
            mine = self.reviews[-1]
            other = self._next({self.builder, makers.maker(ref)}) if escalate else None
            if other is not None:
                decided = self.seat(other, number, escalate=False)
                if decided is not None:
                    return decided
            mine["counted"] = "unquoted"  # nobody else could decide: it counts, marked as unquoted
            return {**got, "counted": "unquoted"}
        return None

    def run(self, n: int):
        first = self.seat(self._next({self.builder}) or self._first_any(), 1)
        if first is None:
            return self._no_verdict()
        seats = [first]
        if n > 1:
            second = self._extra_seat(2)
            if second is not None:
                seats.append(second)
                if second["ok"] != first["ok"]:
                    self.disagreed = True
                    third = self._extra_seat(3)
                    if third is not None:
                        seats.append(third)
        return self._decide(seats)

    def _first_any(self):
        return self.queue.pop(0) if self.queue else None

    def _extra_seat(self, number: int):
        if not dial.allow(self.o, "panel", self.last_cost):
            return None
        ref = self._next({self.builder} | {r["maker"] for r in self.reviews}) or _spare(self.o, self.used,
                                                                                        self.built_by)
        return self.seat(ref, number) if ref is not None else None

    def _decide(self, seats):
        if len(seats) == 3:
            final = seats[2]["ok"]  # the third decides a split
        elif len(seats) == 2 and seats[0]["ok"] != seats[1]["ok"]:
            final = False  # a split nobody could settle: the rejection stands (never a pass by itself)
        else:
            final = seats[0]["ok"]
        self.final = final
        self.seats = seats
        return final, self._feedback(seats, final), self._result()

    def _feedback(self, seats, final) -> str:
        from ..routing import model_label

        if final:
            words = [s["fb"].strip() for s in seats if s["ok"] and s["fb"].strip()]
            return " / ".join(words) or "approved"
        out = []
        against = [s for s in seats if not s["ok"]]
        for s in against:  # each rejecting checker's words, with its quote (named when there are several)
            line = (f"{model_label(str(s['ref']))} found a problem: " if len(against) > 1 else "") + s["fb"].strip()
            if s["counted"] is True and s["breaks"]:
                line += f"\nIt breaks: “{s['breaks'].strip()}”"
            else:
                line += "\n(It did not quote the line of the task it breaks.)"
            out.append(line)
        return "\n\n".join(out)

    def _no_verdict(self):
        if not self.results:
            return None  # nobody could be reached: the usual review (and its usual errors)
        res = self.results[-1]
        self.final, self.seats = False, []
        return False, f"reviewer gave no verdict ({res.stop}): {res.text[:500]}", self._result()

    def _result(self):
        if not self.results:
            return None
        first = self.results[0]
        usage = first.usage
        for r in self.results[1:]:
            usage = usage + r.usage
        # the checkers after the first are the dial's extras: kept apart so the estimate's history (the metrics
        # row's review cost) never counts them twice (dial.price adds them on its own)
        extra = sum(r.cost_usd for r in self.results[1:])
        return replace(first, text=self.results[-1].text, stop=self.results[-1].stop,
                       captured={**(first.captured or {}), "panel_extra_usd": round(extra, 6)},
                       steps=sum(r.steps for r in self.results), usage=usage,
                       cost_usd=sum(r.cost_usd for r in self.results),
                       seconds=sum(r.seconds for r in self.results),
                       saved_tokens_est=sum(r.saved_tokens_est for r in self.results),
                       model=",".join(r.model for r in self.results))

    # -- what is kept ----------------------------------------------------------------------------------------
    def record(self) -> dict[str, Any]:
        same = any(r["maker"] == self.builder for r in self.reviews if r["counted"] is not False) \
            if self.builder else False
        return {"reviews": list(self.reviews), "disagreed": self.disagreed, "same_maker": same}

    def ledger(self, approved: bool) -> None:
        rec = self.record()
        base = {"at": utcnow(), "task": self.task.id, "role": self.task.role, "built_by": str(self.built_by or ""),
                "builder_maker": self.builder, "level": dial.level(self.o), "why": self.why}
        try:
            for r in self.reviews:
                self.o.project.append(LEDGER, {**base, "kind": "verdict", **r})
            self.o.project.append(LEDGER, {**base, "kind": "decision", "approved": bool(approved),
                                           "disagreed": rec["disagreed"], "same_maker": rec["same_maker"],
                                           "checkers": len(self.seats),
                                           "cost_usd": round(sum(r.cost_usd for r in self.results), 6)})
        except OSError:  # bookkeeping: never stops a run
            pass
