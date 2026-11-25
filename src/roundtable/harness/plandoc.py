"""The living plan: the project's plan as a document the owner can argue with.

``.harness/plan.json`` (and a readable ``plan.md`` next to it) holds, for the current goal:

* summary, what's in and out of scope, and a "don't do" list;
* the spec: short sections (stack, screens, data, art style...) that tasks hang off;
* decisions: a question, options, the planner's recommendation and why, and the owner's choice;
* questions for the owner, and ideas the planner recommends beyond the goal;
* a critique of the plan by a second model (ideally from another maker);
* an estimate of cost and time before anything runs;
* pending owner changes (choices, answers, edits) until the plan is revised with them;
* a history of versions and what changed.

The owner edits the document; ``Orchestrator.revise_plan`` sends the changes to the planner,
which returns the updated document and tasks, keeping the tasks that the changes don't touch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.models import utcnow

# defaults for the estimate when there's no history yet (tokens per attempt, minutes per attempt)
DEFAULT_TOKENS = {"chat": (60_000, 8_000)}
DEFAULT_REVIEW_TOKENS = (25_000, 2_500)
DEFAULT_MINUTES = {"chat": 4.0, "image": 0.5}
REVIEW_MINUTES = 1.5


def _items(raw: Any, prefix: str, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    """Normalise a list of strings or objects into objects with ids."""
    out = []
    for i, x in enumerate(raw or []):
        if isinstance(x, str):
            x = {fields[0]: x}
        if not isinstance(x, dict) or not str(x.get(fields[0], "")).strip():
            continue
        item = {k: x.get(k, "") for k in fields}
        item["id"] = str(x.get("id") or f"{prefix}{i + 1}")
        out.append(item)
    return out


def doc_from_submission(args: dict[str, Any], goal: str, goal_index: int) -> dict[str, Any]:
    """Build the plan document from what the planner submitted (every part is optional)."""
    decisions = []
    for i, d in enumerate(args.get("decisions") or []):
        if not isinstance(d, dict) or not d.get("question"):
            continue
        opts = _items(d.get("options"), "o", ("label", "detail", "cost"))
        if len(opts) < 2:
            continue
        ids = [o["id"] for o in opts]
        rec = str(d.get("recommended") or ids[0])
        decisions.append({"id": str(d.get("id") or f"C{i + 1}"), "question": str(d["question"]), "options": opts,
                          "recommended": rec if rec in ids else ids[0], "why": str(d.get("why", "")),
                          "section": str(d.get("section", "")), "chosen": None})
    return {
        "goal": goal, "goal_index": goal_index, "version": 1,
        "summary": str(args.get("summary") or args.get("notes") or ""),
        "in_scope": [str(x) for x in args.get("in_scope") or [] if str(x).strip()],
        "out_of_scope": [str(x) for x in args.get("out_of_scope") or [] if str(x).strip()],
        "dont": [{**x, "by": "planner"} for x in _items(args.get("dont"), "D", ("text", "why"))],
        "spec": _items(args.get("spec"), "S", ("title", "text")),
        "decisions": decisions,
        "questions": [{**q, "answer": ""} for q in _items(args.get("questions"), "Q", ("text", "why"))],
        "ideas": [{**x, "state": "open"} for x in _items(args.get("ideas"), "I", ("text", "why"))],
        "critique": None, "estimate": None, "pending": [], "history": [{"at": utcnow(), "version": 1,
                                                                         "change": "first plan"}],
    }


def carry_over(new: dict[str, Any], old: dict[str, Any]) -> dict[str, Any]:
    """Keep the owner's choices, answers, own don'ts and idea decisions across a revision."""
    chosen = {d["id"]: d.get("chosen") for d in old.get("decisions", [])}
    for d in new["decisions"]:
        if chosen.get(d["id"]) and any(o["id"] == chosen[d["id"]] for o in d["options"]):
            d["chosen"] = chosen[d["id"]]
    answers = {q["id"]: q.get("answer", "") for q in old.get("questions", [])}
    for q in new["questions"]:
        q["answer"] = q.get("answer") or answers.get(q["id"], "")
    texts = {x["text"] for x in new["dont"]}
    new["dont"] += [x for x in old.get("dont", []) if x.get("by") == "owner" and x["text"] not in texts]
    states = {i["id"]: i.get("state", "open") for i in old.get("ideas", [])}
    for i in new["ideas"]:
        i["state"] = states.get(i["id"], "open")
    new["version"] = old.get("version", 1) + 1
    new["history"] = old.get("history", [])
    new["critique"] = old.get("critique")
    return new


def open_items(doc: dict[str, Any] | None) -> dict[str, int]:
    if not doc:
        return {"choices": 0, "questions": 0, "ideas": 0, "pending": 0}
    return {
        "choices": sum(1 for d in doc.get("decisions", []) if not d.get("chosen")),
        "questions": sum(1 for q in doc.get("questions", []) if not q.get("answer")),
        "ideas": sum(1 for i in doc.get("ideas", []) if i.get("state") == "open"),
        "pending": len(doc.get("pending", [])),
    }


def summary_line(doc: dict[str, Any] | None) -> str:
    o = open_items(doc)
    bits = []
    if o["choices"]:
        bits.append(f"{o['choices']} choice{'s' * (o['choices'] > 1)}")
    if o["questions"]:
        bits.append(f"{o['questions']} question{'s' * (o['questions'] > 1)}")
    if o["pending"]:
        bits.append(f"{o['pending']} change{'s' * (o['pending'] > 1)} to apply")
    est = (doc or {}).get("estimate") or {}
    cost = f"about ${est['cost_usd']:.2f}" if est.get("cost_usd") is not None else ""
    if est.get("unpriced"):
        cost = (cost + " + " if cost else "") + "unpriced models"
    tail = ", ".join(x for x in [cost, f"~{round(est['minutes'])} min" if est.get("minutes") else ""] if x)
    return "plan ready" + (": " + ", ".join(bits) if bits else "") + (f" ({tail})" if tail else "")


# -- the estimate ---------------------------------------------------------------------------
def history_by_role(metric_files: list[Path]) -> dict[str, dict[str, float]]:
    """Average cost, minutes and attempts per task, per role, from past runs' metrics."""
    rows: dict[str, list[dict[str, Any]]] = {}
    for f in metric_files:
        try:
            for ln in f.read_text(encoding="utf-8").splitlines():
                d = json.loads(ln)
                if d.get("role") and d.get("outcome") != "owner_feedback":
                    rows.setdefault(d["role"], []).append(d)
        except (OSError, ValueError):
            continue
    out = {}
    for role, rs in rows.items():
        tasks = {(r.get("task"), str(r.get("at", ""))[:10]) for r in rs}
        n = max(1, len(tasks))
        priced = [r for r in rs if r.get("cost_usd")]
        out[role] = {
            "cost": sum(r.get("cost_usd") or 0 for r in priced) / n if priced else None,
            "minutes": sum(r.get("seconds") or 0 for r in rs) / 60 / n,
            "attempts": len(rs) / n,
            "samples": len(rs),
        }
    return out


def estimate(cfg, tasks, history: dict[str, dict[str, float]] | None = None) -> dict[str, Any]:
    """Rough cost and time for the given pending tasks, before anything runs."""
    from .config import ModelRef  # noqa: F401  (type only)
    from ..providers.base import Usage

    history = history or {}
    total, minutes, unpriced = 0.0, 0.0, []
    by_role: dict[str, dict[str, Any]] = {}
    reviewer = cfg.roles.get(cfg.reviewer_role or "")
    for t in tasks:
        role = cfg.roles.get(t.role)
        if not role:
            continue
        h = history.get(t.role)
        if h and h.get("samples", 0) >= 3:
            cost, mins, basis = h["cost"], h["minutes"] + (REVIEW_MINUTES if role.review and reviewer else 0), "history"
        else:
            basis = "default"
            mins = DEFAULT_MINUTES.get(role.kind, 4.0)
            if role.kind == "image":
                cost = cfg.cost(role.models[0], Usage(0, 0))
                cost = None if not cost else cost
            else:
                i, o = DEFAULT_TOKENS["chat"]
                cost = cfg.cost(role.models[0], Usage(i, o))
            if role.review and reviewer and role.kind == "chat":
                rc = cfg.cost(reviewer.models[0], Usage(*DEFAULT_REVIEW_TOKENS))
                cost = None if cost is None or rc is None else cost + rc
                mins += REVIEW_MINUTES
            cost = None if cost is None else cost * 1.4  # retries and longer tasks
        r = by_role.setdefault(t.role, {"tasks": 0, "cost_usd": 0.0, "minutes": 0.0, "basis": basis,
                                        "model": str(role.models[0])})
        r["tasks"] += 1
        r["minutes"] += mins
        if cost is None:
            r["cost_usd"] = None
            if str(role.models[0]) not in unpriced:
                unpriced.append(str(role.models[0]))
        else:
            total += cost
            if r["cost_usd"] is not None:
                r["cost_usd"] += cost
        minutes += mins
    for r in by_role.values():
        if r["cost_usd"] is not None:
            r["cost_usd"] = round(r["cost_usd"], 4)
        r["minutes"] = round(r["minutes"], 1)
    return {"cost_usd": round(total, 4), "minutes": round(minutes, 1), "tasks": len(tasks),
            "unpriced": unpriced, "by_role": by_role, "at": utcnow(),
            "note": "rough: from past runs where there are some, else typical sizes; unpriced models aren't counted"}


# -- reading it -------------------------------------------------------------------------------
def render_markdown(doc: dict[str, Any], tasks: list[Any] | None = None) -> str:
    """Readable plan. Items end with their id in braces ({C1}-style ids for options {a}, questions {Q1},
    ideas {I1}, don'ts {D1}; decisions and spec sections carry [C1]/[S1] in their heading) so a phone
    can send commands about them."""
    L = [f"# Plan v{doc.get('version', 1)}: {doc.get('goal', '')}", ""]
    if doc.get("summary"):
        L += [doc["summary"], ""]
    est = doc.get("estimate") or {}
    if est:
        L += [f"Estimate: about ${est.get('cost_usd', 0):.2f}, about {round(est.get('minutes', 0))} minutes"
              + (f" (not counting {', '.join(est['unpriced'])})" if est.get("unpriced") else ""), ""]
    for title, key in (("In scope", "in_scope"), ("Out of scope", "out_of_scope")):
        if doc.get(key):
            L += [f"## {title}"] + [f"- {x}" for x in doc[key]] + [""]
    if doc.get("dont"):
        L += ["## Don't"] + [f"- {x['text']}" + (f" ({x['why']})" if x.get("why") else "") + f" {{{x['id']}}}"
                             for x in doc["dont"]] + [""]
    for s in doc.get("spec", []):
        L += [f"## {s['title']} [{s['id']}]", s.get("text", ""), ""]
    if doc.get("decisions"):
        L += ["## Decisions"]
        for d in doc["decisions"]:
            L.append(f"### {d['question']} [{d['id']}]")
            for o in d["options"]:
                mark = " (chosen)" if d.get("chosen") == o["id"] else " (recommended)" if d["recommended"] == o["id"] else ""
                L.append(f"- {o['label']}{mark}" + (f": {o['detail']}" if o.get("detail") else "")
                         + (f" [{o['cost']}]" if o.get("cost") else "") + f" {{{o['id']}}}")
            if d.get("why"):
                L.append(f"Why: {d['why']}")
            L.append("")
    if doc.get("questions"):
        L += ["## Questions for the owner"] + [
            f"- {q['text']} {{{q['id']}}}" + (f"\n  Answer: {q['answer']}" if q.get("answer") else "")
            for q in doc["questions"]] + [""]
    if doc.get("ideas"):
        L += ["## Ideas"] + [f"- [{i['state']}] {i['text']}" + (f" ({i['why']})" if i.get("why") else "")
                             + f" {{{i['id']}}}" for i in doc["ideas"]] + [""]
    c = doc.get("critique")
    if c and c.get("points"):
        L += [f"## Critique by {c.get('model', 'a second model')}"] + [
            f"- [{p.get('severity', '?')}] {p.get('text', '')}" for p in c["points"]] + [""]
    if tasks:
        L += ["## Tasks"] + [f"- [{t.id}] {t.status} {t.title} ({t.role})" for t in tasks] + [""]
    return "\n".join(L)


def context_text(doc: dict[str, Any] | None) -> str:
    """What every task and review is told about the plan: spec, choices, scope and don'ts."""
    if not doc:
        return ""
    L = ["# The plan (agreed with the owner; follow it)"]
    if doc.get("summary"):
        L.append(doc["summary"])
    if doc.get("out_of_scope"):
        L.append("Out of scope: " + "; ".join(doc["out_of_scope"]))
    if doc.get("dont"):
        L.append("Don't: " + "; ".join(x["text"] for x in doc["dont"]))
    for d in doc.get("decisions", []):
        pick = d.get("chosen") or d.get("recommended")
        opt = next((o for o in d["options"] if o["id"] == pick), None)
        if opt:
            L.append(f"Decision - {d['question']}: {opt['label']}" + (" (owner's choice)" if d.get("chosen") else ""))
    for q in doc.get("questions", []):
        if q.get("answer"):
            L.append(f"Owner answered - {q['text']}: {q['answer']}")
    accepted = [i["text"] for i in doc.get("ideas", []) if i.get("state") == "accepted"]
    if accepted:
        L.append("Also wanted: " + "; ".join(accepted))
    for s in doc.get("spec", []):
        L.append(f"## {s['title']}\n{s.get('text', '')}")
    return "\n".join(L)


def submission_schema(task_schema: dict[str, Any]) -> dict[str, Any]:
    """The submit_plan tool's parameters: tasks plus the optional plan document parts."""
    s = {"type": "string"}
    item = lambda props, req: {"type": "object", "properties": props, "required": req}  # noqa: E731
    return {
        "type": "object",
        "properties": {
            "summary": {**s, "description": "two or three sentences: what will be built and how"},
            "in_scope": {"type": "array", "items": s},
            "out_of_scope": {"type": "array", "items": s},
            "dont": {"type": "array", "description": "things not to do (traps, over-engineering, risky choices)",
                     "items": item({"text": s, "why": s}, ["text"])},
            "spec": {"type": "array", "description": "short spec sections: stack, structure, screens, data, style...",
                     "items": item({"id": {**s, "description": "S1, S2..."}, "title": s, "text": s}, ["id", "title", "text"])},
            "decisions": {"type": "array", "description": "real choices the owner may want to make, with your recommendation",
                          "items": item({
                              "id": {**s, "description": "C1, C2..."}, "question": s,
                              "options": {"type": "array", "items": item({"id": s, "label": s, "detail": s,
                                                                         "cost": {**s, "description": "effort/cost note"}},
                                                                        ["id", "label"])},
                              "recommended": {**s, "description": "option id"}, "why": s,
                              "section": {**s, "description": "spec section id it affects"}},
                              ["id", "question", "options", "recommended", "why"])},
            "questions": {"type": "array", "description": "what you need the owner to tell you (only real unknowns)",
                          "items": item({"id": {**s, "description": "Q1, Q2..."}, "text": s, "why": s}, ["id", "text"])},
            "ideas": {"type": "array", "description": "worthwhile extras beyond the goal, for the owner to accept or not",
                      "items": item({"id": {**s, "description": "I1, I2..."}, "text": s, "why": s}, ["id", "text"])},
            "tasks": {"type": "array", "items": task_schema},
            "notes": s,
        },
        "required": ["tasks"],
    }
