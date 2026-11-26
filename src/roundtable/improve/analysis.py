"""Turn run history into evidence and proposals.

Two sources of proposals:
* rules - deterministic, cheap, backed directly by production metrics
          (e.g. "the fallback model gets approved far more often: promote it")
* llm   - an analyst model reads the stats, reviewers' rejection feedback and
          the owner's ratings, and proposes prompt / routing / option changes
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..harness.agent import Budget, run_agent
from ..harness.config import HarnessConfig
from ..harness.tools import Tool, Toolbox, _obj
from ..providers.base import ToolSpec
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
class Dataset:
    stats: dict[tuple[str, str], ModelStats] = field(default_factory=dict)
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


def collect(lab: Lab, extra: list[Path] | None = None) -> Dataset:
    ds = Dataset()
    seen = set()
    for proj in lab.projects() + [Path(p).resolve() for p in extra or []]:
        if proj in seen or not (proj / ".harness/project.json").is_file():
            continue
        seen.add(proj)
        ds.projects.append(proj)
        tasks = {t["id"]: t for t in json.loads((proj / ".harness/tasks.json").read_text() or "[]")}
        ds.tasks += len(tasks)
        firsts: set[str] = set()
        for row in _read_jsonl(proj / ".harness/metrics.jsonl"):
            key = (row.get("role", "?"), row.get("model", "?"))
            st = ds.stats.setdefault(key, ModelStats(*key))
            if row.get("outcome") == "owner_feedback":
                if row.get("rating") == "good":
                    st.owner_good += 1
                elif row.get("rating") == "bad":
                    st.owner_bad += 1
                ds.owner_feedback.append({**row, "project": proj.name,
                                          "title": tasks.get(row.get("task"), {}).get("title", "")})
                continue
            st.attempts += 1
            outcome = row.get("outcome")
            if outcome == "approved":
                st.approved += 1
            elif outcome == "rejected":
                st.rejected += 1
            elif outcome == "error":
                st.errors += 1
            else:
                st.other_fail += 1
            if outcome in QUALITY_OUTCOMES and row.get("task") not in firsts:
                firsts.add(row.get("task"))
                st.first_tries += 1
                st.first_try_ok += outcome == "approved"
            if row.get("cost_usd"):
                st.cost += row["cost_usd"]
                st.priced_attempts += 1
            st.seconds += row.get("seconds") or 0
        for t in tasks.values():
            for a in t.get("attempts", []):
                if a.get("outcome") == "rejected" and a.get("review"):
                    ds.rejections.append({"project": proj.name, "task": t["id"], "title": t["title"],
                                          "role": t["role"], "model": a.get("model"), "feedback": a["review"][:800]})
    return ds


def stats_table(ds: Dataset) -> str:
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


def rule_proposals(cfg: HarnessConfig, ds: Dataset) -> list[Proposal]:
    min_n = int(cfg.improve.get("min_samples", 5))
    out: list[Proposal] = []
    for role in cfg.roles.values():
        chain = [str(m) for m in role.models]
        if len(chain) < 2:
            continue
        primary = ds.stats.get((role.name, chain[0]))
        # 1. primary keeps failing at the provider level -> move it to the back
        if primary and primary.attempts >= min_n and primary.error_rate >= 0.3:
            out.append(Proposal(
                id="", kind="routing", role=role.name, change={"models": chain[1:] + chain[:1]}, risk="low",
                rationale=f"{chain[0]} failed with provider errors on {primary.error_rate:.0%} of {primary.attempts} attempts.",
                evidence={"error_rate": round(primary.error_rate, 3), "attempts": primary.attempts},
            ))
            continue
        if not primary or primary.judged < min_n or primary.quality is None:
            continue
        rescue = _rescue_proposal(role.name, chain, primary, ds)
        if rescue:
            out.append(rescue)
            continue
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
                break
            # 3. same quality, much cheaper
            if (abs(alt.quality - primary.quality) <= 0.05 and alt.avg_cost and primary.avg_cost
                    and alt.avg_cost <= 0.5 * primary.avg_cost):
                out.append(Proposal(
                    id="", kind="routing", role=role.name, change={"models": new_chain}, risk="medium", evidence=ev,
                    rationale=f"{alt_ref} matched {chain[0]}'s approval rate ({alt.quality:.0%} vs {primary.quality:.0%}) "
                              f"at {alt.avg_cost / primary.avg_cost:.0%} of the cost per attempt."))
                break
    for p in out:
        p.source = "rules"
    return out


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
            p = Proposal(id="", kind=kind, role=raw.get("role", ""), change=change, rationale=raw.get("rationale", ""),
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

    rejections = "\n".join(f"- [{r['role']} / {r['model']}] {r['title']}: {r['feedback']}" for r in ds.rejections[-30:])
    owner = "\n".join(f"- [{f['role']} / {f['model']}] {f['title']}: {f.get('rating')} - {f.get('note', '')}"
                      for f in ds.owner_feedback[-30:])
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
    res = run_agent(cfg, role.models[0], cfg.prompt_text("improver"), prompt, box, Budget(max_cost),
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
