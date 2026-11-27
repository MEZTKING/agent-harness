"""Turn run history into evidence and proposals.

Two sources of proposals:
* rules - deterministic, cheap, backed directly by production metrics
          (e.g. "the fallback model gets approved far more often: promote it")
* llm   - an analyst model reads the stats, reviewers' rejection feedback and
          the owner's ratings, and proposes prompt / routing / option changes

Wave 7 adds the panel's ledger (``.harness/reviews.jsonl``): how often each checker is overruled or
rejects without quoting what is broken (rule 4), and the per-tag numbers (rule 5). The analyst only sees a
project's rejection texts and titles when that project allows the analyst's maker (``makers.allowed``).
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..harness import makers
from ..harness import projectsettings as ps
from ..harness.agent import Budget, run_agent
from ..harness.config import HarnessConfig
from ..harness.tools import Tool, Toolbox, _obj
from ..providers.base import ToolSpec
from . import charter
from .lab import PROPOSAL_KINDS, RISKS, Lab, Proposal

QUALITY_OUTCOMES = ("approved", "rejected", "refusal", "max_steps")


@dataclass
class ModelStats:
    role: str
    model: str
    attempts: int = 0
    approved: int = 0
    rejected: int = 0
    errors: int = 0
    other_fail: int = 0  # refusal / max_steps
    first_try_ok: int = 0
    first_tries: int = 0
    cost: float = 0.0
    priced_attempts: int = 0
    seconds: float = 0.0
    owner_good: int = 0
    owner_bad: int = 0
    rival_wins: int = 0  # approved builds that were picked from several rivals (wave 6)
    rival_losses: int = 0  # rival builds that were not picked: never a failure, kept apart

    @property
    def judged(self) -> int:
        return self.approved + self.rejected + self.other_fail

    @property
    def quality(self) -> float | None:
        return self.approved / self.judged if self.judged else None

    @property
    def error_rate(self) -> float:
        return self.errors / self.attempts if self.attempts else 0.0

    @property
    def avg_cost(self) -> float | None:
        return self.cost / self.priced_attempts if self.priced_attempts else None

    @property
    def cost_per_success(self) -> float | None:
        """What one approved result really cost, failed attempts included (priced attempts only)."""
        if not self.priced_attempts or not self.approved:
            return None
        return self.cost / self.priced_attempts * self.attempts / self.approved


@dataclass
class TagStats(ModelStats):
    tag: str = ""


@dataclass
class CheckerStats:
    """One checker model's record in the panel's ledger (reviews.jsonl)."""

    model: str
    verdicts: int = 0
    approved: int = 0
    rejected: int = 0
    unquoted: int = 0  # rejections that counted without quoting what they break
    not_counted: int = 0  # verdicts that did not count (an unquoted rejection someone else decided)
    decided: int = 0  # verdicts with a decision to compare against
    overruled: int = 0  # the decision went the other way
    by_builder: dict[str, dict[str, int]] = field(default_factory=dict)  # builder's maker -> {verdicts, overruled}

    @property
    def overruled_share(self) -> float:
        return self.overruled / self.decided if self.decided else 0.0

    @property
    def unquoted_share(self) -> float:
        """Of its rejections, how many quoted nothing (counted as unquoted, or not counted at all)."""
        return (self.unquoted + self.not_counted) / self.rejected if self.rejected else 0.0


@dataclass
class Dataset:
    stats: dict[tuple[str, str], ModelStats] = field(default_factory=dict)
    by_tag: dict[tuple[str, str, str], TagStats] = field(default_factory=dict)  # (role, model, tag)
    checkers: dict[str, CheckerStats] = field(default_factory=dict)  # checker model -> its record (wave 7)
    rejections: list[dict[str, Any]] = field(default_factory=list)
    owner_feedback: list[dict[str, Any]] = field(default_factory=list)
    projects: list[Path] = field(default_factory=list)
    tasks: int = 0


def _read_jsonl(p: Path) -> list[dict[str, Any]]:
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def row_tags(row: dict[str, Any]) -> list[str]:
    """A metrics row's tags (what the task was about, wave 6), each once."""
    raw = row.get("tags") or []
    if isinstance(raw, str):
        raw = [raw]
    out: list[str] = []
    for t in raw:
        t = str(t).strip().lower()
        if t and t not in out:
            out.append(t)
    return out


def count_row(st: ModelStats, row: dict[str, Any], firsts: set, key: tuple) -> None:
    """Count one metrics row (not the owner's ratings) into ``st``. ``firsts``: the (key, task) pairs already
    seen, so only a task's first judged try (whoever made it) counts as a first try; ``key``: () for the main
    table, (tag,) for one kind of work.

    A rival build that was not picked (``rival_lost``) is counted on its own and never as a failure: it may
    have been good work that another rival bettered. A picked rival that was approved is a rival win too."""
    outcome = row.get("outcome")
    if outcome == "rival_lost":
        st.rival_losses += 1
        return
    st.attempts += 1
    if outcome == "approved":
        st.approved += 1
        if row.get("rival"):
            st.rival_wins += 1
    elif outcome == "rejected":
        st.rejected += 1
    elif outcome == "error":
        st.errors += 1
    else:
        st.other_fail += 1
    if outcome in QUALITY_OUTCOMES and (key, row.get("task")) not in firsts:
        firsts.add((key, row.get("task")))
        st.first_tries += 1
        st.first_try_ok += outcome == "approved"
    if row.get("cost_usd"):
        st.cost += row["cost_usd"]
        st.priced_attempts += 1
    st.seconds += row.get("seconds") or 0


def tag_stats(metric_files: list[Path]) -> dict[tuple[str, str, str], TagStats]:
    """(role, model, tag) -> stats from metrics files (the router's history: numbers only, any project)."""
    out: dict[tuple[str, str, str], TagStats] = {}
    for f in metric_files:
        firsts: set[tuple] = set()
        for row in _read_jsonl(Path(f)):
            if row.get("outcome") == "owner_feedback":
                continue
            key = (row.get("role", "?"), row.get("model", "?"))
            for tag in row_tags(row):
                count_row(out.setdefault((*key, tag), TagStats(*key, tag=tag)), row, firsts, (tag,))
    return out


def strengths(ds: Dataset | dict, min_n: int = 5) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """{role: {tag: [{model, quality, approved, n, cost_per_success}]}}, best first, for every (role, tag) where
    a model has at least ``min_n`` judged tries. ``ds``: a Dataset, or tag_stats' dict."""
    table = ds.by_tag if isinstance(ds, Dataset) else ds
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for (role, model, tag), s in table.items():
        if s.judged < max(1, min_n) or s.quality is None:
            continue
        cps = s.cost_per_success
        out.setdefault(role, {}).setdefault(tag, []).append({
            "model": model, "quality": round(s.quality, 3), "approved": s.approved, "n": s.judged,
            "cost_per_success": round(cps, 6) if cps is not None else None})
    for tags in out.values():
        for rows in tags.values():
            rows.sort(key=lambda r: (-r["quality"], r["cost_per_success"] if r["cost_per_success"] is not None
                                     else float("inf"), r["model"]))
    return out


def count_reviews(ds: Dataset, rows: list[dict[str, Any]]) -> None:
    """Add one project's reviews.jsonl to ``ds.checkers``. A decision row follows its verdicts with the same
    task and time, so each verdict is compared with the decision it led to."""
    groups: dict[tuple[Any, Any], dict[str, Any]] = {}
    for row in rows:
        g = groups.setdefault((row.get("task"), row.get("at")), {"verdicts": [], "decision": None})
        if row.get("kind") == "decision":
            g["decision"] = row
        elif row.get("kind") == "verdict":
            g["verdicts"].append(row)
    for g in groups.values():
        decision = g["decision"]
        for v in g["verdicts"]:
            model = str(v.get("model") or "?")
            st = ds.checkers.setdefault(model, CheckerStats(model))
            st.verdicts += 1
            ok = bool(v.get("approved"))
            st.approved += ok
            if not ok:
                st.rejected += 1
                if v.get("counted") == "unquoted":
                    st.unquoted += 1
                elif v.get("counted") is False:
                    st.not_counted += 1
            builder = str(v.get("builder_maker") or "?")
            mine = st.by_builder.setdefault(builder, {"verdicts": 0, "overruled": 0})
            mine["verdicts"] += 1
            if decision is not None and v.get("counted") is not False:
                st.decided += 1
                if ok != bool(decision.get("approved")):
                    st.overruled += 1
                    mine["overruled"] += 1


def collect(lab: Lab, extra: list[Path] | None = None) -> Dataset:
    ds = Dataset()
    seen = set()
    for proj in lab.projects() + [Path(p).resolve() for p in extra or []]:
        if proj in seen or not (proj / ".harness/project.json").is_file():
            continue
        seen.add(proj)
        ds.projects.append(proj)
        tasks = {t["id"]: t for t in json.loads((proj / ".harness/tasks.json").read_text(encoding="utf-8") or "[]")}
        ds.tasks += len(tasks)
        firsts: set[tuple] = set()
        for row in _read_jsonl(proj / ".harness/metrics.jsonl"):
            key = (row.get("role", "?"), row.get("model", "?"))
            st = ds.stats.setdefault(key, ModelStats(*key))
            if row.get("outcome") == "owner_feedback":
                if row.get("rating") == "good":
                    st.owner_good += 1
                elif row.get("rating") == "bad":
                    st.owner_bad += 1
                ds.owner_feedback.append({**row, "project": proj.name, "root": str(proj),
                                          "title": tasks.get(row.get("task"), {}).get("title", "")})
                continue
            count_row(st, row, firsts, ())
            for tag in row_tags(row):
                count_row(ds.by_tag.setdefault((*key, tag), TagStats(*key, tag=tag)), row, firsts, (tag,))
        for t in tasks.values():
            for a in t.get("attempts", []):
                if a.get("outcome") == "rejected" and a.get("review"):
                    ds.rejections.append({"project": proj.name, "root": str(proj), "task": t["id"],
                                          "title": t["title"],
                                          "role": t["role"], "model": a.get("model"), "feedback": a["review"][:800]})
        count_reviews(ds, _read_jsonl(proj / ".harness/reviews.jsonl"))
    return ds


def checkers_table(ds: Dataset) -> str:
    """How each checker did in the panel: verdicts, rejections, how many quoted nothing, how often the
    decision went the other way, and per builder's maker."""
    lines = [f"{'checker':38} {'verdicts':>8} {'ok':>4} {'no':>4} {'unquoted':>8} {'overruled':>9}  by builder"]
    for model, s in sorted(ds.checkers.items()):
        uq = f"{s.unquoted_share:.0%}" if s.rejected else "-"
        ov = f"{s.overruled_share:.0%}" if s.decided else "-"
        who = ", ".join(f"{m} {b['overruled']}/{b['verdicts']}" for m, b in sorted(s.by_builder.items()))
        lines.append(f"{model:38} {s.verdicts:8} {s.approved:4} {s.rejected:4} {uq:>8} {ov:>9}  {who}")
    return "\n".join(lines)


def stats_table(ds: Dataset, by_tag: bool = False, checkers: bool = False) -> str:
    """The table of how each model did per role; ``by_tag``: one line per kind of work too (the tag column);
    ``checkers``: the panel's checkers instead (reviews.jsonl)."""
    if checkers:
        return checkers_table(ds)
    if by_tag:
        lines = [f"{'role':12} {'model':38} {'tag':16} {'tries':>5} {'ok':>4} {'qual':>5} {'1st':>5} {'err':>4} "
                 f"{'avg $':>8} {'rival +/-':>9}"]
        for (role, model, tag), s in sorted(ds.by_tag.items()):
            q = f"{s.quality:.0%}" if s.quality is not None else "-"
            ft = f"{s.first_try_ok / s.first_tries:.0%}" if s.first_tries else "-"
            cost = f"{s.avg_cost:.4f}" if s.avg_cost is not None else "-"
            lines.append(f"{role:12} {model:38} {tag:16} {s.attempts:5} {s.approved:4} {q:>5} {ft:>5} {s.errors:4} "
                         f"{cost:>8} {s.rival_wins:>4}/{s.rival_losses:<4}")
        return "\n".join(lines)
    lines = [f"{'role':12} {'model':38} {'tries':>5} {'ok':>4} {'qual':>5} {'1st':>5} {'err':>4} {'avg $':>8} {'owner +/-':>9}"]
    for (role, model), s in sorted(ds.stats.items()):
        q = f"{s.quality:.0%}" if s.quality is not None else "-"
        ft = f"{s.first_try_ok / s.first_tries:.0%}" if s.first_tries else "-"
        cost = f"{s.avg_cost:.4f}" if s.avg_cost is not None else "-"
        lines.append(f"{role:12} {model:38} {s.attempts:5} {s.approved:4} {q:>5} {ft:>5} {s.errors:4} {cost:>8} "
                     f"{s.owner_good:>4}/{s.owner_bad:<4}")
    return "\n".join(lines)


# -- rule-based proposals ------------------------------------------------------------
def _rescue_proposal(role: str, chain: list[str], primary: ModelStats, ds: Dataset) -> Proposal | None:
    """The fallback keeps finishing what the primary can't, and each finished task costs less that way.

    Needs fewer of the fallback's tries than the other rules (3): it only takes over after the primary
    failed, so it gets few chances, and a cheap primary that mostly fails is the costly case.
    """
    if primary.quality > 0.5:
        return None
    for alt_ref in chain[1:]:
        alt = ds.stats.get((role, alt_ref))
        if not alt or alt.judged < 3 or alt.quality is None or alt.quality < 0.9:
            continue
        mine, theirs = primary.cost_per_success, alt.cost_per_success
        if mine is not None and theirs is not None and theirs >= mine:
            continue
        new_chain = [alt_ref] + [m for m in chain if m != alt_ref]
        cost = (f" Each finished task cost about ${theirs:.2f} with {alt_ref} against ${mine:.2f} with {chain[0]}, "
                "counting the failed attempts." if mine is not None and theirs is not None else "")
        return Proposal(
            id="", kind="routing", role=role, change={"models": new_chain}, risk="low",
            rationale=f"{chain[0]} finished only {primary.quality:.0%} of its {primary.judged} attempts; {alt_ref} "
                      f"finished {alt.quality:.0%} of {alt.judged} when it took over.{cost}",
            evidence={"primary": {"model": chain[0], "quality": round(primary.quality, 3), "n": primary.judged,
                                  "cost_per_success": mine},
                      "candidate": {"model": alt_ref, "quality": round(alt.quality, 3), "n": alt.judged,
                                    "cost_per_success": theirs}})
    return None


def _checker_proposal(cfg: HarnessConfig, ds: Dataset, min_n: int) -> Proposal | None:
    """Rule 4: a checker the decision keeps overruling, or that rejects without quoting what is broken, goes
    to the back of the reviewer's chain."""
    reviewer = cfg.roles.get(cfg.reviewer_role or "")
    if reviewer is None:
        return None
    chain = [str(m) for m in reviewer.models]
    if len(chain) < 2:
        return None
    for ref in chain[:-1]:
        st = ds.checkers.get(ref)
        if not st or st.verdicts < min_n:
            continue
        overruled = st.decided >= min_n and st.overruled_share >= 0.4
        loose = st.rejected >= 2 and st.unquoted_share >= 0.5
        if not (overruled or loose):
            continue
        why = (f"the final decision went the other way on {st.overruled_share:.0%} of its {st.decided} verdicts"
               if overruled else
               f"{st.unquoted_share:.0%} of its {st.rejected} rejections quoted nothing the work breaks")
        return Proposal(
            id="", kind="routing", role=reviewer.name, change={"models": [m for m in chain if m != ref] + [ref]},
            risk="medium", rationale=f"As a checker, {ref} was not reliable: {why}. It moves to the back.",
            evidence={"checker": ref, "verdicts": st.verdicts, "overruled": st.overruled, "decided": st.decided,
                      "rejected": st.rejected, "unquoted": st.unquoted + st.not_counted})
    return None


def _tag_proposal(role: str, chain: list[str], ds: Dataset, min_n: int) -> Proposal | None:
    """Rule 5: a fallback that beats the first model on three kinds of work (tags), each with enough judged
    tries on both and a lead of 0.15, is promoted."""
    for alt in chain[1:]:
        wins = []
        for (r, model, tag), st in ds.by_tag.items():
            if r != role or model != alt or st.judged < min_n or st.quality is None:
                continue
            first = ds.by_tag.get((role, chain[0], tag))
            if not first or first.judged < min_n or first.quality is None:
                continue
            if st.quality >= first.quality + 0.15:
                wins.append({"tag": tag, "candidate": round(st.quality, 3), "primary": round(first.quality, 3),
                             "n": [first.judged, st.judged]})
        if len(wins) >= 3:
            wins.sort(key=lambda w: w["tag"])
            return Proposal(
                id="", kind="routing", role=role, change={"models": [alt] + [m for m in chain if m != alt]},
                risk="low", evidence={"tags": wins, "primary": chain[0], "candidate": alt},
                rationale=f"{alt} beat {chain[0]} on {len(wins)} kinds of work ("
                          + ", ".join(f"{w['tag']} {w['candidate']:.0%} vs {w['primary']:.0%}" for w in wins)
                          + ").")
    return None


def rule_proposals(cfg: HarnessConfig, ds: Dataset) -> list[Proposal]:
    min_n = int(cfg.improve.get("min_samples", 5))
    out: list[Proposal] = []
    for role in cfg.roles.values():
        chain = [str(m) for m in role.models]
        if len(chain) < 2:
            continue
        before = len(out)
        _role_rules(cfg, ds, role, chain, min_n, out)
        if len(out) == before:
            tagged = _tag_proposal(role.name, chain, ds, min_n)
            if tagged:
                out.append(tagged)
    if not any(p.role == cfg.reviewer_role for p in out):
        checker = _checker_proposal(cfg, ds, min_n)
        if checker:
            out.append(checker)
    for p in out:
        p.source = "rules"
    return out


def _role_rules(cfg: HarnessConfig, ds: Dataset, role: Any, chain: list[str], min_n: int,
                out: list[Proposal]) -> None:
    """Rules 1 to 3 for one role (at most one proposal)."""
    primary = ds.stats.get((role.name, chain[0]))
    # 1. primary keeps failing at the provider level -> move it to the back
    if primary and primary.attempts >= min_n and primary.error_rate >= 0.3:
        out.append(Proposal(
            id="", kind="routing", role=role.name, change={"models": chain[1:] + chain[:1]}, risk="low",
            rationale=f"{chain[0]} failed with provider errors on {primary.error_rate:.0%} of {primary.attempts} attempts.",
            evidence={"error_rate": round(primary.error_rate, 3), "attempts": primary.attempts},
        ))
        return
    if not primary or primary.judged < min_n or primary.quality is None:
        return
    rescue = _rescue_proposal(role.name, chain, primary, ds)
    if rescue:
        out.append(rescue)
        return
    for alt_ref in chain[1:]:
        alt = ds.stats.get((role.name, alt_ref))
        if not alt or alt.judged < min_n or alt.quality is None:
            continue
        new_chain = [alt_ref] + [m for m in chain if m != alt_ref]
        ev = {"primary": {"model": chain[0], "quality": round(primary.quality, 3), "n": primary.judged,
                          "avg_cost": primary.avg_cost},
              "candidate": {"model": alt_ref, "quality": round(alt.quality, 3), "n": alt.judged, "avg_cost": alt.avg_cost}}
        # 2. clearly better quality
        if alt.quality >= primary.quality + 0.15:
            out.append(Proposal(
                id="", kind="routing", role=role.name, change={"models": new_chain}, risk="low", evidence=ev,
                rationale=f"{alt_ref} was approved {alt.quality:.0%} of the time vs {primary.quality:.0%} for "
                          f"{chain[0]} ({alt.judged} vs {primary.judged} judged attempts)."))
            return
        # 3. same quality, much cheaper
        if (abs(alt.quality - primary.quality) <= 0.05 and alt.avg_cost and primary.avg_cost
                and alt.avg_cost <= 0.5 * primary.avg_cost):
            out.append(Proposal(
                id="", kind="routing", role=role.name, change={"models": new_chain}, risk="medium", evidence=ev,
                rationale=f"{alt_ref} matched {chain[0]}'s approval rate ({alt.quality:.0%} vs {primary.quality:.0%}) "
                          f"at {alt.avg_cost / primary.avg_cost:.0%} of the cost per attempt."))
            return


# -- LLM analyst ----------------------------------------------------------------------
def _config_text(cfg: HarnessConfig) -> str:
    lines = ["# Current routing"]
    for r in cfg.roles.values():
        lines.append(f"- {r.name} ({r.kind}): {' -> '.join(str(m) for m in r.models)}"
                     f"  options={json.dumps(r.options)}  description={r.description!r}")
    lines.append(f"\nConfigured providers: {', '.join(sorted(cfg.providers))}")
    lines.append("\n# Current prompts (chat roles)")
    seen = set()
    for r in cfg.roles.values():
        if r.kind != "chat" or r.prompt in seen:
            continue
        seen.add(r.prompt)
        lines.append(f"\n## prompt '{r.prompt}' (used by role {r.name})\n```\n{cfg.prompt_text(r.prompt)[:4000]}\n```")
    return "\n".join(lines)


def llm_proposals(cfg: HarnessConfig, ds: Dataset, lab: Lab, max_cost: float, on_event=None) -> tuple[list[Proposal], float]:
    role_name = cfg.improve.get("analyst_role") or ("improver" if "improver" in cfg.roles else cfg.planner_role)
    role = cfg.roles[role_name]
    accepted: list[Proposal] = []

    def submit(args: dict) -> str:
        errors = []
        for i, raw in enumerate(args.get("proposals") or []):
            kind = raw.get("kind")
            change = {"routing": {"models": raw.get("models")}, "options": {"options": raw.get("options")},
                      "prompt": {"prompt_text": raw.get("prompt_text")}}.get(kind, {})
            if kind == "prompt" and isinstance(change["prompt_text"], str):
                change["prompt_text"] = charter.scrub(change["prompt_text"], lab)
            p = Proposal(id="", kind=kind, role=raw.get("role", ""), change=change,
                         rationale=charter.scrub(str(raw.get("rationale", "")), lab),
                         risk=raw.get("risk", "medium"), source="llm")
            try:
                p.validate(cfg)
            except (ValueError, KeyError) as e:
                errors.append(f"proposal #{i}: {e}")
                continue
            accepted.append(p)
        if errors:
            raise Exception("some proposals were invalid (the valid ones were kept): " + "; ".join(errors)
                            + ". Resubmit only corrected versions of the invalid ones, or stop.")
        return f"{len(accepted)} proposal(s) recorded"

    box = Toolbox()
    item = _obj({
        "kind": {"type": "string", "enum": list(PROPOSAL_KINDS)},
        "role": {"type": "string", "enum": sorted(cfg.roles)},
        "models": {"type": "array", "items": {"type": "string"}, "description": "routing: full chain, primary first"},
        "options": {"type": "object", "description": "options: the role's complete new options"},
        "prompt_text": {"type": "string", "description": "prompt: the complete new prompt"},
        "rationale": {"type": "string", "description": "the evidence behind this change"},
        "risk": {"type": "string", "enum": list(RISKS)},
    }, ["kind", "role", "rationale", "risk"])
    box.add(Tool(ToolSpec("submit_proposals", "Submit your proposed changes (may be an empty list).",
                          _obj({"proposals": {"type": "array", "items": item}}, ["proposals"])), submit, terminal=True))

    analyst = role.models[0]
    allowed: dict[str, bool] = {}

    def may_see(row: dict[str, Any]) -> bool:
        """Only a project that allows the analyst's maker gives it rejection texts and task titles."""
        root = str(row.get("root") or "")
        if root not in allowed:
            try:
                allowed[root] = bool(root) and makers.allowed(ps.load(Path(root)).values, analyst)
            except Exception:  # noqa: BLE001 - settings that can't be read: nothing from that project
                allowed[root] = False
        return allowed[root]

    rejections = "\n".join(f"- [{r['role']} / {r['model']}] {r['title']}: {r['feedback']}"
                           for r in [x for x in ds.rejections if may_see(x)][-30:])
    owner = "\n".join(f"- [{f['role']} / {f['model']}] {f['title']}: {f.get('rating')} - {f.get('note', '')}"
                      for f in [x for x in ds.owner_feedback if may_see(x)][-30:])
    pending = "\n".join(f"- {p.id} {p.status}: {p.summary()}" for p in lab.proposals() if p.status in ("proposed", "tested", "applied"))
    prompt = (
        f"# Performance by role and model ({len(ds.projects)} projects, {ds.tasks} tasks)\n"
        "qual = approved / judged attempts, 1st = approved on the first try, err = provider errors\n"
        f"```\n{stats_table(ds)}\n```\n\n"
        f"# Reviewer rejections (most recent)\n{rejections or '(none)'}\n\n"
        f"# Owner feedback\n{owner or '(none)'}\n\n"
        f"{_config_text(cfg)}\n\n"
        f"# Already proposed or applied (don't repeat)\n{pending or '(none)'}\n\n"
        "Propose the changes most likely to raise first-try approval and owner satisfaction per dollar. "
        "Call submit_proposals (an empty list is a fine answer when the evidence is thin)."
    )
    fixed = charter.fixed_block("improver")  # the lines no learned prompt can drop
    system = cfg.prompt_text("improver") + (f"\n\n{fixed}" if fixed else "")
    res = run_agent(cfg, role.models[0], system, prompt, box, Budget(max_cost),
                    max_steps=4, max_tokens=role.max_tokens, options=role.options,
                    require_terminal="submit_proposals", on_event=on_event)
    return accepted, res.cost_usd


def analyze(cfg: HarnessConfig, lab: Lab, use_llm: bool = False, max_cost: float = 2.0,
            extra: list[Path] | None = None, on_event=None) -> tuple[Dataset, list[Proposal], float]:
    for p in extra or []:
        if (Path(p) / ".harness/project.json").is_file():
            lab.register_project(p)  # so its tasks can be replayed by `improve test`
    ds = collect(lab)
    found = rule_proposals(cfg, ds)
    cost = 0.0
    if use_llm and ds.stats:
        more, cost = llm_proposals(cfg, ds, lab, max_cost, on_event)
        found += more
    new = []
    for p in found:
        if not lab.is_duplicate(p):
            new.append(lab.add_proposal(p))
    return ds, new, cost
