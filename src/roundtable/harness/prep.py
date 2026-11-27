"""Prep (parity MD-08): the owner's idea tidied into a short brief before anything is planned.

"All I'm doing is writing the initial plan/idea." Before the planner starts, one small call on the planner's
own model reads the idea with what is already to hand here (the repository's rules, what the harness remembers
about this project and this computer, the references, the kind) and writes it as a brief: what it is, who it's
for, what's unsaid but implied, and what's unclear.

- The owner's words stay the goal, word for word, and stay on top; the brief is folded under More.
- Anything the brief adds beyond the idea goes to the plan as ideas (to accept or not), never as scope.
- One call, capped by ``prep.max_usd`` (default $0.05). Too dear, no price known, an error or no answer:
  no brief, and planning goes on exactly as without it.
- Kept in ``.harness/prep.json`` (one record a goal) and in the plan document as ``doc["prep"]``.
- Nothing from the hub or other projects goes in.

harness.yaml::

    prep: {enabled: true, max_usd: 0.05}

``enabled`` left out means on, except for a scripted (test) planner, where it is on only when set to true.
"""

from __future__ import annotations

import json
from typing import Any

from ..core.models import utcnow
from .config import section

PREP_FILE = "prep.json"
MAX_USD = 0.05
MAX_TOKENS = 700
MAX_CONTEXT = 6000  # characters of what's to hand, so the call stays small
SYSTEM = ("You tidy a person's idea for an app or game into a short, clear brief for the people who will plan and "
          "build it. Keep to what they said and what it plainly implies. Never invent features; never decide for "
          "them. Plain, short British English. Answer only by calling submit_brief.")
WHY_WORDS = {"off": "the tidy-up is off", "too_dear": "it would cost more than its limit", "unpriced": "its price isn't known",
             "error": "the model didn't answer", "no_answer": "the model gave no brief", "budget": "the money limit is reached",
             "dry": "the planner is a test model"}


def settings(cfg) -> dict[str, Any]:
    s = section(cfg, "prep")
    try:
        cap = max(0.0, float(s.get("max_usd", MAX_USD)))
    except (TypeError, ValueError):
        cap = MAX_USD
    return {"enabled": s.get("enabled", "auto"), "max_usd": cap}


def _path(orch):
    return orch.project.dir / PREP_FILE


def read_all(orch) -> dict[str, Any]:
    p = _path(orch)
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def stored(orch, goal_index: int, goal: str) -> dict[str, Any] | None:
    """The brief already made for this goal (the same words), or None."""
    rec = read_all(orch).get(str(goal_index))
    return rec if isinstance(rec, dict) and rec.get("goal") == goal else None


def _save(orch, goal_index: int, rec: dict[str, Any]) -> None:
    data = read_all(orch)
    data[str(goal_index)] = rec
    p = _path(orch)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _quiet(fn) -> str:
    try:
        return str(fn() or "").strip()
    except Exception:  # noqa: BLE001 - what's to hand is a help; a missing piece never stops the tidy-up
        return ""


def gather(orch) -> str:
    """What is already to hand: the repository's rules, the owner's notes, memory (this project and this
    computer, its tools among them), the references and the kind. Nothing from the hub or other projects."""
    parts = []
    for name in ("_repo_rules_block", "_repo_plan_note", "_memory_part", "_references_text"):
        fn = getattr(orch, name, None)
        if callable(fn):
            text = _quiet(fn)
            if text:
                parts.append(text[:2500])
    kind = None
    fn = getattr(orch, "_kind", None)
    if callable(fn):
        try:
            kind = fn()
        except Exception:  # noqa: BLE001
            kind = None
    if kind is not None:
        blurb = str((getattr(kind, "spec", None) or {}).get("blurb") or "")
        parts.append(f"# What kind of thing it is\n{getattr(kind, 'name', '')}" + (f": {blurb}" if blurb else ""))
    return "\n\n".join(parts)[:MAX_CONTEXT]


def _tool():
    from ..providers.base import ToolSpec

    s = {"type": "string"}
    return ToolSpec("submit_brief", "Submit the tidied brief.", {
        "type": "object",
        "properties": {
            "what": {**s, "description": "one or two plain sentences: what it is"},
            "who": {**s, "description": "one plain sentence: who it's for (say 'not said' when it isn't)"},
            "implied": {"type": "array", "items": s,
                        "description": "at most 5 short lines: what the idea plainly needs but doesn't say"},
            "unclear": {"type": "array", "items": s,
                        "description": "at most 4 short questions only the person can answer"},
        },
        "required": ["what", "who", "implied", "unclear"],
    })


def _lines(raw: Any, most: int) -> list[str]:
    return [" ".join(str(x).split())[:200] for x in (raw if isinstance(raw, list) else []) if str(x).strip()][:most]


def brief(orch, goal: str, goal_index: int = 0) -> dict[str, Any]:
    """Tidy ``goal`` into a brief: {goal, goal_index, brief: {what, who, implied, unclear} | None, why?, model,
    cost_usd, at}. Never raises; ``goal`` is kept exactly as written. Money goes through the run's budget."""
    from ..providers.base import Usage
    from ..providers.scripted import ScriptedProvider

    rec: dict[str, Any] = {"goal": goal, "goal_index": goal_index, "brief": None, "model": "", "cost_usd": 0.0,
                           "at": utcnow()}
    s = settings(orch.cfg)
    if s["enabled"] is False or str(s["enabled"]).lower() in ("false", "off", "no"):
        return {**rec, "why": "off"}
    try:
        role = orch.cfg.roles[orch.cfg.planner_role]
        ref = role.models[0]
        provider = orch.cfg.provider(ref.provider)
    except Exception:  # noqa: BLE001 - no planner: nothing to tidy with
        return {**rec, "why": "error"}
    if isinstance(provider, ScriptedProvider) and s["enabled"] is not True:
        return {**rec, "why": "dry"}
    rec["model"] = str(ref)
    known = gather(orch)
    prompt = ((f"# What is already to hand\n{known}\n\n" if known else "")
              + f"# The idea, in the person's own words\n{goal}\n\n"
              "Write the brief: what it is, who it's for, what's unsaid but implied, and what's unclear.")
    est = orch.cfg.cost(ref, Usage(input_tokens=(len(SYSTEM) + len(prompt)) // 3 + 300, output_tokens=MAX_TOKENS))
    if est is None:
        return {**rec, "why": "unpriced"}
    if est > s["max_usd"]:
        return {**rec, "why": "too_dear", "estimate_usd": round(est, 6)}
    try:
        orch.budget.check()
    except Exception:  # noqa: BLE001 - the run's money limit is reached: don't spend more
        return {**rec, "why": "budget"}
    try:
        resp = provider.chat(ref.model, SYSTEM, [{"role": "user", "content": prompt}], tools=[_tool()],
                             max_tokens=MAX_TOKENS, options={})
    except Exception as e:  # noqa: BLE001 - the model is away: plan without a brief
        return {**rec, "why": "error", "error": str(e)[:300]}
    cost = orch.cfg.cost(ref, resp.usage)
    try:
        orch.budget.charge(cost, ref=ref, usage=resp.usage, role=orch.cfg.planner_role)
    except Exception:  # noqa: BLE001 - charging is bookkeeping
        pass
    rec["cost_usd"] = round(cost or 0.0, 6)
    call = next((c for c in resp.tool_calls if c.name == "submit_brief"), None)
    args = (call.arguments or {}) if call else {}
    what = " ".join(str(args.get("what") or "").split())[:600]
    if not what:
        return {**rec, "why": "no_answer"}
    rec["brief"] = {"what": what, "who": " ".join(str(args.get("who") or "").split())[:300],
                    "implied": _lines(args.get("implied"), 5), "unclear": _lines(args.get("unclear"), 4)}
    return rec


def plan_text(rec: dict[str, Any] | None) -> str:
    """The brief for the planner, under the owner's own words (which stay the goal)."""
    b = (rec or {}).get("brief")
    if not b:
        return ""
    out = ["\n\n# The idea, tidied (a helper's reading; the owner's own words above are the goal)",
           f"What it is: {b['what']}"]
    if b.get("who"):
        out.append(f"Who it's for: {b['who']}")
    if b.get("implied"):
        out.append("Implied but not said (offer these as ideas for the owner to accept, never as scope):")
        out += [f"- {x}" for x in b["implied"]]
    if b.get("unclear"):
        out.append("Unclear (ask as questions only what you can't sensibly decide yourself):")
        out += [f"- {x}" for x in b["unclear"]]
    return "\n".join(out) + "\n"


def to_doc(doc: dict[str, Any], rec: dict[str, Any] | None) -> None:
    """The brief into the plan document: ``doc["prep"]`` (shown under More), what it implies as ideas, and
    any scope line that only the brief brought in moved to the ideas. The goal itself is never touched."""
    from .plandoc import _similar

    b = (rec or {}).get("brief")
    if not b:
        return
    doc["prep"] = {"brief": b, "model": rec.get("model", ""), "cost_usd": rec.get("cost_usd", 0.0), "at": rec.get("at", "")}
    goal = str(doc.get("goal") or "")
    ideas = doc.setdefault("ideas", [])
    why = "Implied by your idea (from the tidy-up before planning)"
    n = 1
    ids = {i.get("id") for i in ideas}

    def add(text: str) -> None:
        nonlocal n
        if any(_similar(text, i.get("text", "")) for i in ideas):
            return
        while f"P{n}" in ids:
            n += 1
        ids.add(f"P{n}")
        ideas.append({"id": f"P{n}", "text": text, "why": why, "state": "open", "by": "prep"})

    keep = []
    for line in doc.get("in_scope") or []:
        if any(_similar(line, imp) for imp in b.get("implied") or []) and not _similar(line, goal):
            add(line)  # only the brief asked for it: the owner decides
        else:
            keep.append(line)
    if "in_scope" in doc:
        doc["in_scope"] = keep
    for imp in b.get("implied") or []:
        if not _similar(imp, goal) and not any(_similar(imp, s) for s in keep):
            add(imp)


class PrepStage:
    """The Orchestrator's side: the brief made once a goal (``_prep_plan_part``, before the planner's other
    parts) and laid into the plan document (``_prep_doc``)."""

    def _prep_goal(self) -> tuple[int, str]:
        goals = self.project.meta().get("goals") or [""]
        return len(goals) - 1, str(goals[-1])

    def _prep_record(self) -> dict[str, Any] | None:
        gi, goal = self._prep_goal()
        rec = stored(self, gi, goal)
        if rec is None:
            rec = brief(self, goal, gi)
            _save(self, gi, rec)
            self.emit("prep", {"brief": bool(rec.get("brief")), "why": rec.get("why", ""),
                               "cost_usd": rec.get("cost_usd", 0.0)})
        return rec

    def _prep_plan_part(self) -> str:
        return plan_text(self._prep_record())

    def _prep_doc(self, doc: dict[str, Any], args: dict[str, Any]) -> None:
        gi, goal = self._prep_goal()
        if int(doc.get("goal_index", gi)) != gi:
            return
        to_doc(doc, stored(self, gi, goal))
