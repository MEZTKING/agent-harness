"""Who built each task, who checked it, where they disagreed, and the checking dial (harness/dial.py).

    GET /api/tandem ?path=<project>
        -> {level, label, words, allowance: {usd, spent, used_up}, estimates: {lean, balanced, maximum:
            {cost_usd, minutes, extra_usd, planning_usd, unpriced}},
            tasks: {<id>: {built_by, built_by_label, agent?, routed?, rivals?, reviews, disagreed, same_maker,
                           line, fold: [plain lines]}}}

Read only: the level is changed through the plan (``plan_update`` action ``checking``). ``line`` is the one
sentence shown under a task ("Built by Claude Opus · checked by GPT and Gemini · they disagreed"); ``fold`` is
what shows behind More (each try, why a rival won, each checker's verdict and quote).
"""

from __future__ import annotations

from typing import Any

from ..harness import dial

_BUILT = ("approved", "built", "accepted")
_OUTCOME = {"approved": "passed its check", "rejected": "sent back", "built": "built (a rival)", "error": "failed to run",
            "accepted": "accepted", "rival_lost": "not chosen"}


def routes(app) -> dict[tuple[str, str], Any]:
    return {("GET", "/api/tandem"): lambda q: view(app, q)}


def _arg(q, name: str) -> str:
    return str((q.get(name) or [""])[0] or "")


def short(ref: Any) -> str:
    """"anthropic/claude-opus-5-5" -> "Claude Opus 5.5" (no service: the line stays short)."""
    if not ref:
        return ""
    from ..routing import model_label

    return model_label(str(ref)).split(" (", 1)[0]


def _and(names: list[str]) -> str:
    names = [n for i, n in enumerate(names) if n and n not in names[:i]]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1] if names else ""


def task_view(task: dict[str, Any]) -> dict[str, Any] | None:
    """One task's who-did-what from its attempts, None when nothing was built yet."""
    atts = [a for a in task.get("attempts") or [] if isinstance(a, dict)]
    if not atts:
        return None
    last = next((a for a in reversed(atts) if a.get("outcome") in _BUILT), atts[-1])
    rivals = next((a.get("rivals") for a in reversed(atts) if isinstance(a.get("rivals"), list)), None)
    built = last.get("model") or ""
    if rivals:
        won = next((r for r in rivals if isinstance(r, dict) and r.get("picked")), None)
        built = (won or {}).get("model") or built
    reviews = [r for r in last.get("reviews") or [] if isinstance(r, dict)]
    out: dict[str, Any] = {"built_by": built, "built_by_label": short(built), "reviews": reviews,
                           "disagreed": bool(last.get("disagreed")), "same_maker": bool(last.get("same_maker"))}
    for k in ("agent", "routed"):
        if last.get(k):
            out[k] = last[k]
    if rivals:
        out["rivals"] = rivals
    out["line"] = line(out)
    out["fold"] = fold(atts, out)
    return out


def line(v: dict[str, Any]) -> str:
    """"Built by Claude Opus · checked by GPT and Gemini · they disagreed"."""
    parts = [f"Built by {v.get('built_by_label') or short(v.get('built_by')) or 'a model'}"]
    if v.get("agent"):
        parts[0] += f" ({v.get('agent_name') or v['agent']})"
    n = len(v.get("rivals") or [])
    if n > 1:
        parts.append(f"best of {n}")
    checkers = _and([short(r.get("model")) for r in v.get("reviews") or []])
    if checkers:
        parts.append(f"checked by {checkers}")
    if v.get("disagreed"):
        parts.append("they disagreed")
    if v.get("same_maker"):
        parts.append("one checker is from the same company")
    return " · ".join(parts)


def fold(atts: list[dict[str, Any]], v: dict[str, Any]) -> list[str]:
    """Behind More: each try, why a rival won, each checker's verdict and the words it quoted."""
    out = []
    for i, a in enumerate(atts, 1):
        tag = f" (rival {a['rival']})" if a.get("rival") else ""
        out.append(f"Try {i}{tag}: {short(a.get('model')) or 'a model'} – "
                   f"{_OUTCOME.get(str(a.get('outcome')), str(a.get('outcome') or 'unknown'))}")
    if isinstance(v.get("routed"), dict) and v["routed"].get("why"):
        out.append(f"Chosen instead of {short(v['routed'].get('from'))}: {v['routed']['why']}")
    for r in v.get("rivals") or []:
        if not isinstance(r, dict):
            continue
        what = "chosen" if r.get("picked") else "not chosen"
        why = f": {r['why']}" if r.get("why") else ""
        out.append(f"Rival {r.get('id') or ''} {short(r.get('model'))}: {what}{why}".replace("  ", " "))
    for r in v.get("reviews") or []:
        verdict = "approved" if r.get("approved") else "sent it back"
        quote = r.get("breaks") or ""
        said = f" – “{quote}”" if quote else (f" – {r['feedback']}" if r.get("feedback") else "")
        tail = "" if r.get("counted", True) else " (not counted)"
        out.append(f"{short(r.get('model'))} {verdict}{tail}{said}"[:400])
    return out


def view(app, q) -> dict[str, Any]:
    project = app.project(app.need_cfg(), _arg(q, "path"))
    meta = project.meta()
    doc = project.plan_doc() or {}
    lvl = dial._known(meta.get("checking")) or "lean"
    tasks: dict[str, Any] = {}
    for t in project._read("tasks.json", []):
        if isinstance(t, dict) and t.get("id"):
            got = task_view(t)
            if got and got.get("agent"):  # the agent's own name ("Torvic"), not its id
                got["agent_name"] = _agent_name(app, got["agent"])
                got["line"] = line(got)
            if got:
                tasks[str(t["id"])] = got
    return {"level": lvl, "label": dial.label(lvl), "words": dial.words_for(lvl, doc.get("estimate")),
            "allowance": dial.allowance_view(project.root, meta), "estimates": doc.get("checking_estimates") or {},
            "tasks": tasks}


def _agent_name(app, agent_id: str) -> str:
    try:
        from .. import agents

        return agents.get(app._backup_home(), agent_id).name
    except Exception:  # noqa: BLE001 - a removed agent: its id is shown
        return ""
