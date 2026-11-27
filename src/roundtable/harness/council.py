"""Rival plans, one merged plan (wave 6, d3-council).

When the dial says a plan gets more than one planner (Maximum), two or three planners from different makers
each plan the idea on their own, each reads the others' plans and says what it thinks, and a chair (the
owner's own planner) merges them into one plan. The owner sees one plan, with a fold "Where the planners
disagreed". A difference only the owner can settle goes into the plan's ordinary decisions, with the chair's
recommendation: there is no new kind of card.

Three rounds, all under one capped budget (``council.max_usd``, 1.50 by default), every charge also counted
in the project's own budget:

1. each planner plans (read-only calls, so they run side by side);
2. each planner reads the others' plans (labelled A, B and C) and calls ``submit_critique``;
3. the chair gets every plan and critique and submits the merged plan, with ``disagreements``.

A help, never a stop: when the cap is reached or a round fails, the best plan so far is used (the one the
others liked most, else the owner's planner's); when no plan came back at all, the usual single plan runs.
Only new plans have a council; a revision gets today's single critique. The record is ``doc["council"]``:
``{planners: [{label, model, maker, tasks, summary, votes}], disagreements: [{topic, options: [{who, says}],
chosen, why}], chair, merged, stopped, cost_usd, at}``. With it present, ``plan()`` skips the critique.

Settings (``council:`` in harness.yaml): ``enabled`` (true), ``max_usd`` (1.50), ``parallel`` (true), and the
sizes used for the estimate: ``plan_tokens`` ([60000, 8000]), ``critique_tokens`` ([25000, 2500]).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

from ..core.models import utcnow
from ..providers.base import ProviderError, ToolSpec, Usage
from . import dial, makers, plandoc
from .agent import BudgetExceeded
from .config import ModelRef, section
from .tools import READ_ONLY, Tool, _obj
from .unstick import _CappedBudget

LABELS = ("A", "B", "C")
DEFAULTS: dict[str, Any] = {"enabled": True, "max_usd": 1.50, "parallel": True,
                            "plan_tokens": [60_000, 8_000], "critique_tokens": [25_000, 2_500]}
NUMBERS = {2: "Two", 3: "Three"}
HEADING = "Where the planners disagreed"


def settings(cfg: Any) -> dict[str, Any]:
    out = dict(DEFAULTS)
    out.update({k: v for k, v in section(cfg, "council").items() if k in DEFAULTS})
    return out


def _tokens(value: Any, fallback: list[int]) -> Usage:
    try:
        i, o = (int(x) for x in value)
    except (TypeError, ValueError):
        i, o = fallback
    return Usage(i, o)


def _quality_planners(cfg: Any) -> list[ModelRef]:
    """The Quality set's planner chain, when the config has a Quality set."""
    profiles = getattr(cfg, "profiles", None) or {}
    quality = next((n for n in profiles if n.lower() == "quality"), None)
    if not quality:
        return []
    try:
        role = cfg.for_profile(quality).roles.get(cfg.planner_role)
    except Exception:  # noqa: BLE001 - a set with a mistake: no extra planner from it
        return []
    return list(role.models) if role else []


def candidates(cfg: Any, quality: list[ModelRef] | None = None) -> list[ModelRef]:
    """Who may plan, in order: the planner's chain, then the critic's, then the Quality set's planner."""
    out: list[ModelRef] = []
    for name in (cfg.planner_role, cfg.critic_role):
        role = cfg.roles.get(name or "")
        if role and role.kind == "chat":
            out += list(role.models)
    out += list(quality if quality is not None else _quality_planners(cfg))
    return out


def pick(cfg: Any, n: int, ok=lambda ref: True, quality: list[ModelRef] | None = None) -> list[ModelRef]:
    """Up to ``n`` planners, one per maker, each passing ``ok`` (the project's allowed lists)."""
    return makers.distinct([r for r in candidates(cfg, quality) if ok(r)])[:max(0, int(n))]


def estimate(cfg: Any, n: int, refs: list[ModelRef] | None = None) -> float | None:
    """What a council of ``n`` planners costs, shown before it runs: (2n + 1) calls at the default sizes – each
    planner plans and reads the others' plans, then the chair merges. None when a model has no price."""
    s = settings(cfg)
    refs = list(refs if refs is not None else pick(cfg, n))[:n]
    if not refs or n < 2:
        return 0.0
    refs += [refs[0]] * (n - len(refs))
    plan_u, crit_u = _tokens(s["plan_tokens"], DEFAULTS["plan_tokens"]), _tokens(s["critique_tokens"], DEFAULTS["critique_tokens"])
    planner = cfg.roles.get(cfg.planner_role)
    chair = planner.models[0] if planner and planner.models else refs[0]
    costs = [cfg.cost(r, plan_u) for r in refs] + [cfg.cost(r, crit_u) for r in refs] + [cfg.cost(chair, plan_u)]
    if any(c is None for c in costs):
        return None
    return round(sum(costs), 6)


# -- the words the owner reads --------------------------------------------------------------------------------
def words(council: dict[str, Any] | None) -> str:
    """The one line: "Three planners agreed on most of it; they differed on 2 things"."""
    if not council:
        return ""
    n = len(council.get("planners") or [])
    who = f"{NUMBERS.get(n, str(n))} planners"
    k = len(council.get("disagreements") or [])
    if not council.get("merged"):
        best = council.get("best") or ""
        return f"{who} each made a plan; the one the others liked best ({best}) was used" if best else f"{who} each made a plan"
    if not k:
        return f"{who} agreed on the whole plan"
    return f"{who} agreed on most of it; they differed on {k} thing{'' if k == 1 else 's'}"


def markdown(doc: dict[str, Any]) -> list[str]:
    """The plan's markdown part (plandoc.render_markdown): the line, then each disagreement. [] without a council."""
    c = (doc or {}).get("council")
    if not c:
        return []
    L = [f"## {HEADING}", words(c) + "."]
    for d in c.get("disagreements") or []:
        L.append(f"- {d.get('topic', '')}: " + "; ".join(f"{o.get('who', '')} said {o.get('says', '')}" for o in d.get("options") or [])
                 + (f". Chosen: {d['chosen']}" if d.get("chosen") else "") + (f" ({d['why']})" if d.get("why") else ""))
    return L + [""]


def view(doc: dict[str, Any] | None) -> dict[str, Any]:
    """What the app and the phone show (GET /api/tandem/council)."""
    c = (doc or {}).get("council")
    if not c:
        return {"found": False}
    return {"found": True, "words": words(c), **c}


def _clean_disagreements(raw: Any) -> list[dict[str, Any]]:
    out = []
    for d in raw if isinstance(raw, list) else []:
        if not isinstance(d, dict) or not str(d.get("topic") or "").strip():
            continue
        opts = [{"who": str(o.get("who") or "")[:20], "says": str(o.get("says") or "")[:400]}
                for o in d.get("options") or [] if isinstance(o, dict) and str(o.get("says") or "").strip()]
        out.append({"topic": str(d["topic"])[:200], "options": opts[:3], "chosen": str(d.get("chosen") or "")[:400],
                    "why": str(d.get("why") or "")[:400]})
    return out[:12]


class _CouncilCap(BudgetExceeded):
    """The council reached its own cap (not the project's limit): the best plan so far is used."""


class _CouncilBudget(_CappedBudget):
    """The council's own budget while it runs, standing in for the project's: every charge goes to the project's
    budget too, and what it reports as spent is the project's, so saving the spend writes the right total."""

    used: float = 0.0  # what the council spent (class defaults: the dataclass init above doesn't know them)
    cap: float = DEFAULTS["max_usd"]

    @classmethod
    def over(cls, parent, cap: float) -> "_CouncilBudget":
        b = cls(limit_usd=parent.limit_usd, parent=parent)
        b.used, b.cap = 0.0, float(cap)
        b._sync()
        return b

    def _sync(self) -> None:
        self.spent_usd, self.unpriced_calls = self.parent.spent_usd, self.parent.unpriced_calls

    def charge(self, cost, *, ref=None, usage=None, role=None) -> None:
        with self._lock:
            self.used += cost or 0.0
        self.parent.charge(cost, ref=ref, usage=usage, role=role)
        self._sync()

    def check(self) -> None:
        self.parent.check()  # the project's own limit: a real stop
        if self.used >= self.cap:
            raise _CouncilCap(f"the planners reached their cap of ${self.cap:.2f}")


class CouncilStage:
    """Rival planners and a chair (a mixin of the Orchestrator)."""

    # -- the hooks --------------------------------------------------------------------------------------------
    def _council_plan(self, job: str, existing: list) -> tuple[list, dict[str, Any]] | None:
        """A new plan made by two or three planners and a chair, or None for the usual single plan."""
        s = settings(self.cfg)
        if not s["enabled"] or self.cfg.planner_role not in self.cfg.roles:
            return None
        self._council_level()
        n = int((dial.for_plan(self) or {}).get("planners") or 1)
        if n < 2:
            return None
        refs = self._council_planners(n)
        if len(refs) < 2:
            return None  # one maker to hand: the usual plan and critique
        est = estimate(self.cfg, len(refs), refs)
        if not dial.allow(self, "council", est):
            self.emit("council", {"skipped": "the extra-checking allowance has no room", "estimate_usd": est})
            return None
        self.emit("council_start", {"planners": [str(r) for r in refs], "estimate_usd": est})
        cap = _CouncilBudget.over(self.budget, s["max_usd"])
        keep = self.budget
        self.budget = cap  # every planning call in the three rounds counts against the cap
        try:
            return self._council_rounds(job, existing, refs, cap, s)
        finally:
            self.budget = keep
            self._save_spend()
            dial.spent(self, "council", cap.used)

    def _council_schema(self, schema: dict[str, Any]) -> None:
        """Only the chair's submission has ``disagreements``."""
        if not getattr(self._tl, "council_chair", False):
            return
        opt = {"type": "object", "properties": {"who": {"type": "string", "description": "the plan's label: A, B or C"},
                                                "says": {"type": "string", "description": "what that plan does, in a plain sentence"}},
               "required": ["who", "says"]}
        schema.setdefault("properties", {})["disagreements"] = {
            "type": "array",
            "description": "each real point where the rival plans differed: the topic, what each said, what you "
                           "chose and why (plain words). One only the owner can settle also goes in decisions.",
            "items": {"type": "object", "properties": {
                "topic": {"type": "string"}, "options": {"type": "array", "items": opt},
                "chosen": {"type": "string"}, "why": {"type": "string"}}, "required": ["topic", "options", "chosen"]},
        }

    def _council_doc(self, doc: dict[str, Any], args: dict[str, Any]) -> None:
        rec = args.get("_council") if isinstance(args, dict) else None
        if rec:
            doc["council"] = dict(rec)

    # -- the parts --------------------------------------------------------------------------------------------
    def _council_level(self) -> None:
        """A new plan's level is set before the dial is asked (plan() sets the same value after this hook)."""
        try:
            meta = self.project.meta()
            level = dial.level_for_new_plan(self)
            if meta.get("checking") != level:
                meta["checking"] = level
                self.project.save_meta(meta)
        except Exception:  # noqa: BLE001 - bookkeeping
            pass

    def _council_planners(self, n: int) -> list[ModelRef]:
        quality = None
        try:
            name = next((p for p in self.base_cfg.profiles if p.lower() == "quality"), None)
            if name:
                role = self._settle_cfg(self.base_cfg.for_profile(name)).roles.get(self.cfg.planner_role)
                quality = list(role.models) if role else []
        except Exception:  # noqa: BLE001 - no Quality planner then
            quality = []
        return pick(self.cfg, n, lambda r: self._may_use(r) and not self._blocked(r), quality)

    def _council_rounds(self, job, existing, refs, cap, s) -> tuple[list, dict[str, Any]] | None:
        planner = self.cfg.roles[self.cfg.planner_role]
        stopped = ""
        # round 1: each plans on its own
        plans: list[dict[str, Any]] = []
        got = self._council_each(refs, lambda ref: self._plan_call(job, existing, role=replace(planner, models=[ref])),
                                 bool(s["parallel"]))
        for (ref, out, err), label in zip(got, LABELS):
            if err is None:
                tasks, args = out
                plans.append({"label": label, "ref": ref, "tasks": tasks, "args": args, "votes": 0})
            else:
                stopped = stopped or ("cap" if isinstance(err, _CouncilCap) else "a planner failed")
                self.emit("council_error", {"round": 1, "model": str(ref), "error": str(err)[:300]})
        if not plans:
            return None  # no plan came back: the usual single plan
        if len(plans) < 2:
            return plans[0]["tasks"], plans[0]["args"]  # nothing to weigh: one plan, and today's critique
        for i, p in enumerate(plans):
            p["label"] = LABELS[i]
        critiques: list[dict[str, Any]] = []
        if cap.used < cap.cap:
            critiques = self._council_critiques(plans, bool(s["parallel"]))
        stopped = stopped or ("cap" if cap.used >= cap.cap else "")
        for c in critiques:
            for p in plans:
                if p["label"] == c.get("best"):
                    p["votes"] += 1
        best = max(plans, key=lambda p: (p["votes"], -plans.index(p)))
        chair_args, chair_tasks, chair = None, None, ""
        if cap.used < cap.cap:
            chair_role = replace(planner, models=[m for m in planner.models if self._may_use(m)])
            if chair_role.models:
                chair = str(chair_role.models[0])
                try:
                    self._tl.council_chair = True
                    chair_tasks, chair_args = self._plan_call(self._council_chair_job(job, plans, critiques),
                                                              existing, role=chair_role)
                except BudgetExceeded as e:
                    if not isinstance(e, _CouncilCap):
                        raise
                    stopped = "cap"
                except Exception as e:  # noqa: BLE001 - the chair is a help: the best plan so far
                    stopped = stopped or "the chair failed"
                    self.emit("council_error", {"round": 3, "model": chair, "error": str(e)[:300]})
                finally:
                    self._tl.council_chair = False
        else:
            stopped = "cap"
        merged = chair_args is not None
        args = dict(chair_args if merged else best["args"])
        tasks = chair_tasks if merged else best["tasks"]
        record = {
            "planners": [{"label": p["label"], "model": str(p["ref"]), "maker": makers.maker(p["ref"]),
                          "tasks": len(p["tasks"]), "summary": str(p["args"].get("summary") or "")[:300],
                          "votes": p["votes"]} for p in plans],
            "critiques": [{"by": c["by"], "best": c.get("best", ""), "points": c.get("points", [])[:6]} for c in critiques],
            "disagreements": _clean_disagreements(args.pop("disagreements", None)) if merged else [],
            "chair": chair if merged else "", "merged": merged, "best": "" if merged else best["label"],
            "stopped": stopped if not merged or stopped != "cap" else "", "cost_usd": round(cap.used, 6), "at": utcnow(),
        }
        args["_council"] = record
        self.emit("council", {"planners": len(plans), "merged": merged, "disagreements": len(record["disagreements"]),
                              "cost_usd": record["cost_usd"], "stopped": record["stopped"]})
        return tasks, args

    def _council_each(self, refs, fn, parallel: bool) -> list[tuple[Any, Any, BaseException | None]]:
        """Run ``fn(ref)`` for each planner (side by side when allowed); money beyond the cap is raised."""
        def one(ref):
            try:
                return ref, fn(ref), None
            except Exception as e:  # noqa: BLE001 - written down; the project's money stop is raised below
                return ref, None, e

        if parallel and len(refs) > 1:
            with ThreadPoolExecutor(max_workers=len(refs)) as pool:
                got = list(pool.map(one, refs))
        else:
            got = [one(r) for r in refs]
        for _, _, err in got:
            if isinstance(err, BudgetExceeded) and not isinstance(err, _CouncilCap):
                raise err
        return got

    def _council_render(self, p: dict[str, Any]) -> str:
        meta = self.project.meta()
        gi = len(meta.get("goals") or [""]) - 1
        doc = plandoc.doc_from_submission(p["args"], (meta.get("goals") or [""])[-1], gi)
        body = plandoc.render_markdown(doc, p["tasks"], waiting=False)
        details = "\n".join(f"[{t.id}] ({t.role}) {t.title}: {t.description[:400]} | done when: {t.acceptance[:200]}"
                            for t in p["tasks"])
        return f"## Plan {p['label']}\n{body}\n### Its tasks\n{details}\n"

    def _council_critiques(self, plans: list[dict[str, Any]], parallel: bool) -> list[dict[str, Any]]:
        """Round 2: each planner reads the others' plans and says which is best and what is wrong."""
        planner = self.cfg.roles[self.cfg.planner_role]
        texts = {p["label"]: self._council_render(p) for p in plans}
        by_ref = {str(p["ref"]): p for p in plans}

        def critique(ref):
            mine = by_ref[str(ref)]
            got: dict[str, Any] = {}

            def submit_critique(args: dict) -> str:
                got.update(args)
                return "critique recorded"

            point = {"type": "object", "properties": {
                "about": {"type": "string", "description": "the plan's label: A, B or C"},
                "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                "text": {"type": "string"}}, "required": ["about", "text"]}
            box = self.ws.toolbox(READ_ONLY)
            box.add(Tool(ToolSpec("submit_critique", "Record what you think of the other plans, and which plan is best.",
                                  _obj({"best": {"type": "string", "enum": [p["label"] for p in plans]},
                                        "points": {"type": "array", "items": point}}, ["best", "points"])),
                         submit_critique, terminal=True))
            others = "\n".join(texts[p["label"]] for p in plans if p is not mine)
            prompt = (f"You wrote plan {mine['label']}:\n{texts[mine['label']]}\n\n# The other planners' plans\n{others}\n\n"
                      "# Your job\nRead the other plans. Say concretely what each gets wrong or misses, and what it does "
                      "better than yours. Then say which plan is best overall (yours may be). Be brief and fair; call "
                      "submit_critique.")
            self._run_with_fallback(replace(planner, models=[ref]),
                                    "You are one of several planners comparing rival plans for the same goal.",
                                    prompt, box, require="submit_critique", done=lambda: bool(got))
            if not got:
                raise ProviderError("no critique came back")
            return got

        out = []
        for ref, got, err in self._council_each([p["ref"] for p in plans], critique, parallel):
            if err is not None:
                self.emit("council_error", {"round": 2, "model": str(ref), "error": str(err)[:300]})
                continue
            best = str(got.get("best") or "")
            points = [{"about": str(x.get("about") or ""), "severity": str(x.get("severity") or "medium"),
                       "text": str(x.get("text") or "")[:400]}
                      for x in got.get("points") or [] if isinstance(x, dict) and x.get("text")]
            out.append({"by": by_ref[str(ref)]["label"], "best": best if best in texts else "", "points": points})
        return out

    def _council_chair_job(self, job: str, plans, critiques) -> str:
        said = "\n".join(f"- {c['by']} thinks {c['best'] or 'none'} is best. "
                         + " ".join(f"About {x['about']} ({x['severity']}): {x['text']}" for x in c["points"])
                         for c in critiques) or "(no critiques came back)"
        return (job + "\n\n# Rival plans for this goal\n" + "\n".join(self._council_render(p) for p in plans)
                + f"\n# What the planners said about each other's plans\n{said}\n\n"
                "# Your job as the chair\nMerge these into one plan: keep what most of them agree on, take the best "
                "idea where they differ, and drop what the critiques show is wrong. Call submit_plan with the "
                "complete plan and its tasks, written as one plan (never mention plan A, B or C in it). In "
                "disagreements, list each real point where the plans differed: the topic, what each plan said "
                "(who: its label), what you chose and why, in plain words. A difference only the owner can settle "
                "also goes in decisions, with your recommendation.")
