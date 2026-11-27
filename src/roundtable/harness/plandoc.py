"""The living plan: the project's plan as a document the owner can argue with.

``.harness/plan.json`` (and a readable ``plan.md`` next to it) holds, for the current goal:

* summary, what's in and out of scope, and a "don't do" list;
* the spec: short sections (stack, screens, data, art style...) that tasks hang off;
* decisions: a question, options, the planner's recommendation and why, and the owner's choice;
* questions for the owner, and ideas the planner recommends beyond the goal;
* a critique of the plan by a second model (ideally from another maker);
* references ("Make it like this"): what the owner wants it to be like, each read by the scout
  (``scout.py``, ``refstage.py``);
* the look: visual directions for an app with screens, and the one the owner chose (``look.py``);
* an estimate of cost and time before anything runs;
* pending owner changes (choices, answers, edits) until the plan is revised with them;
* a history of versions and what changed.

The owner edits the document; ``Orchestrator.revise_plan`` sends the changes to the planner,
which returns the updated document and tasks, keeping the tasks that the changes don't touch.
"""

from __future__ import annotations

import json
import re
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


def _header(raw: Any) -> str:
    """The short label on a question's card (at most 12 characters)."""
    return " ".join(str(raw or "").split())[:12].strip()


def _questions(raw: Any) -> list[dict[str, Any]]:
    """Questions for the owner, each with 0-4 ready answers to tap (the first is the recommendation).

    Old plans and planners that send only text still work: the card then shows only the text box."""
    out = []
    for i, x in enumerate(raw or []):
        src = x if isinstance(x, dict) else {"text": x} if isinstance(x, str) else {}
        text = str(src.get("text", "")).strip()
        if not text:
            continue
        opts = _items(src.get("options"), "a", ("label", "detail"))[:4]
        ids = [o["id"] for o in opts]
        rec = str(src.get("recommended") or (ids[0] if ids else ""))
        out.append({"text": text, "why": str(src.get("why") or ""), "id": str(src.get("id") or f"Q{i + 1}"),
                    "header": _header(src.get("header")), "options": opts,
                    "recommended": rec if rec in ids else (ids[0] if ids else ""),
                    "multi": bool(src.get("multi")) and len(opts) > 1, "answer": ""})
    return out


_CLAIMED_BY_OWNER = re.compile(
    r"^\s*(?:this (?:was|is) )?(?:settled|decided|chosen|agreed|picked|answered)(?: already)? by the owner[,.:;]?\s*(?:and\s+)?",
    re.IGNORECASE)


def _unclaimed(why: str) -> str:
    """A planner may not say the owner settled a choice: only the owner's own answer does that.

    (MSE Studio, 26 November: a revision wrote "Settled by the owner" on three choices nobody had made.)"""
    out = _CLAIMED_BY_OWNER.sub("", why or "").strip()
    return out[:1].upper() + out[1:] if out else out


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
                          "header": _header(d.get("header")),
                          "recommended": rec if rec in ids else ids[0], "why": _unclaimed(str(d.get("why", ""))),
                          "section": str(d.get("section", "")), "chosen": None})
    summary = str(args.get("summary") or args.get("notes") or "")
    return {
        "goal": goal, "goal_index": goal_index, "version": 1,
        "title": short_title(args.get("title")) if str(args.get("title") or "").strip() else "",
        "summary": summary,
        "has_ui": bool(args["has_ui"]) if isinstance(args.get("has_ui"), bool) else None,
        "in_scope": [str(x) for x in args.get("in_scope") or [] if str(x).strip()],
        "out_of_scope": [str(x) for x in args.get("out_of_scope") or [] if str(x).strip()],
        "dont": [{**x, "by": "planner"} for x in _items(args.get("dont"), "D", ("text", "why"))],
        "spec": _items(args.get("spec"), "S", ("title", "text")),
        "decisions": decisions,
        "questions": _questions(args.get("questions")),
        "ideas": [{**x, "state": "open"} for x in _items(args.get("ideas"), "I", ("text", "why"))],
        "critique": None, "estimate": None, "pending": [], "history": [{"at": utcnow(), "version": 1,
                                                                         "change": "first plan"}],
    }


def carry_over(new: dict[str, Any], old: dict[str, Any]) -> dict[str, Any]:
    """Keep the owner's choices, answers, own don'ts and idea decisions across a revision.

    Matched by the item's wording, not its id: a planner may reuse "I1" for a different idea.
    """
    norm = lambda t: " ".join(str(t).lower().split())  # noqa: E731
    chosen = {norm(d["question"]): d for d in old.get("decisions", []) if d.get("chosen")}
    for d in new["decisions"]:
        prev = chosen.get(norm(d["question"]))
        if prev:
            label = next((o["label"] for o in prev["options"] if o["id"] == prev["chosen"]), None)
            match = next((o["id"] for o in d["options"] if norm(o["label"]) == norm(label or "")), None)
            if match:
                d["chosen"] = match
    answers = {norm(q["text"]): q.get("answer", "") for q in old.get("questions", [])}
    for q in new["questions"]:
        q["answer"] = q.get("answer") or answers.get(norm(q["text"]), "")
    texts = {norm(x["text"]) for x in new["dont"]}
    new["dont"] += [x for x in old.get("dont", []) if x.get("by") == "owner" and norm(x["text"]) not in texts]
    states = {norm(i["text"]): i.get("state", "open") for i in old.get("ideas", [])}
    for i in new["ideas"]:
        i["state"] = states.get(norm(i["text"]), "open")
    # The planner drops what's settled; keep the owner's record of it so the page (and the next
    # revision) still shows it, and never re-offer an idea the owner turned down, even reworded.
    turned_down = [i["text"] for i in old.get("ideas", []) if i.get("state") == "rejected"]
    new["ideas"] = [i for i in new["ideas"]
                    if i["state"] != "open" or not any(_similar(i["text"], t) for t in turned_down)]
    seen = {norm(i["text"]) for i in new["ideas"]}
    new["ideas"] += [dict(i) for i in old.get("ideas", []) if i.get("state") in ("accepted", "rejected")
                     and norm(i["text"]) not in seen]
    seen = {norm(q["text"]) for q in new["questions"]}
    new["questions"] += [dict(q) for q in old.get("questions", []) if q.get("answer") and norm(q["text"]) not in seen]
    seen = {norm(d["question"]) for d in new["decisions"]}
    new["decisions"] += [dict(d) for d in old.get("decisions", []) if d.get("chosen") and norm(d["question"]) not in seen]
    for key, items, prefix in (("ideas", new["ideas"], "I"), ("questions", new["questions"], "Q"),
                               ("decisions", new["decisions"], "C"), ("dont", new["dont"], "D")):
        if len({x.get("id") for x in items}) < len(items):  # a kept item may clash with a new id
            for n, x in enumerate(items):
                x["id"] = f"{prefix}{n + 1}"
    if new.get("has_ui") is None:
        new["has_ui"] = old.get("has_ui")
    if old.get("kind") and not new.get("kind"):
        new["kind"] = old["kind"]  # what kind of thing it is (kinds) lasts across revisions
    if not new.get("title") and old.get("title"):
        new["title"] = old["title"]  # a revision that didn't name it keeps the name the owner knows
    if old.get("look"):
        new["look"] = old["look"]  # the looks aren't the planner's: they stay as they were
    if old.get("references"):
        new["references"] = old["references"]  # the owner's, read by the scout: never the planner's to drop
    # the stages' parts (wave 5) last too, and the council's record and the dial's prices (wave 6)
    for k in ("done_list", "stages", "parts", "prep", "warnings", "council", "checking_estimates"):
        if old.get(k) and not new.get(k):
            new[k] = old[k]
    new["version"] = old.get("version", 1) + 1
    new["history"] = old.get("history", [])
    new["critique"] = old.get("critique")
    return new


_STOP = set("a an the and or of to in for with on by is be it its this that add show".split())


def _similar(a: str, b: str) -> bool:
    """Roughly the same idea: most of the shorter one's words are in the other."""
    words = lambda t: {w.rstrip("s") for w in re.findall(r"[a-z0-9]+", t.lower())} - _STOP  # noqa: E731
    wa, wb = words(a), words(b)
    small = min(len(wa), len(wb))
    return small > 0 and len(wa & wb) / small >= 0.5


def look_open(doc: dict[str, Any] | None) -> bool:
    """There are looks to choose from and the owner hasn't chosen one."""
    look = (doc or {}).get("look") or {}
    return bool(look.get("directions")) and not look.get("chosen")


def open_items(doc: dict[str, Any] | None) -> dict[str, int]:
    if not doc:
        return {"choices": 0, "questions": 0, "ideas": 0, "pending": 0}
    return {
        "choices": sum(1 for d in doc.get("decisions", []) if not d.get("chosen")) + look_open(doc),
        "questions": sum(1 for q in doc.get("questions", []) if not q.get("answer")),
        "ideas": sum(1 for i in doc.get("ideas", []) if i.get("state") == "open"),
        "pending": len(doc.get("pending", [])),
    }


def summary_line(doc: dict[str, Any] | None) -> str:
    o = open_items(doc)
    bits = []
    choices = o["choices"] - look_open(doc)
    if choices:
        bits.append(f"{choices} choice{'s' * (choices > 1)}")
    if look_open(doc):
        bits.append("a look to choose")
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


# -- the owner's words for a plan -------------------------------------------------------------
_TECH = re.compile(r"\b(?:APK|EXE|Electron|Kotlin|WebView\w*|Capacitor|npm|node|React|Vue|API|SDK|JSON|HTML|CSS|JS|"
                   r"TypeScript|Python|Gradle|PyInstaller|v?\d+\.\d+(?:\.\d+)?)\b", re.I)
_FILE = re.compile(r"\S+\.(?:html|css|js|json|py|kt|md|ts|yaml|yml|txt|png|exe|apk)\b|\S*/\S+")


def _first_sentence(text: str) -> str:
    text = " ".join(str(text or "").split())
    m = re.search(r"(?<=[.!?])\s|[:;](?:\s|$)", text)
    return (text[:m.start()] if m else text).rstrip(".!?:; ")


def _plainer(text: str) -> str:
    """Drop file names, versions and bracketed asides; tidy the spaces and the ends."""
    t = re.sub(r"\([^)]*\)", "", text)
    t = _FILE.sub("", t)
    t = re.sub(r"\s+", " ", t).strip(" ,-–—")
    return t


_DANGLING = re.compile(r"(?:\s+|^)(?:and|or|with|as|an?|the|for|to|of|in|on|by|from|using)$", re.I)


def _tidy_end(text: str) -> str:
    """No sentence ends on "and", "with" or a comma."""
    prev = None
    while prev != text:
        prev, text = text, _DANGLING.sub("", text.rstrip(" ,-–—:;")).rstrip(" ,-–—:;")
    return text


def _cut(text: str, limit: int = 60) -> str:
    if len(text) <= limit:
        return _tidy_end(text) or text
    cut = _tidy_end(text[:limit].rsplit(" ", 1)[0])
    return cut or text[:limit]


def short_title(title: Any, summary: str = "", goal: str = "") -> str:
    """The plan's heading for the owner: the planner's own title (at most 8 words), else made from the summary's
    first sentence, else the goal's, at most 60 characters, without file names and tool names where possible."""
    t = " ".join(str(title or "").split()).strip(" .")
    if t:
        return _cut(" ".join(t.split()[:8]))
    for src in (summary, re.sub(r"^\s*(?:plan\s+v\d+\s*:\s*)", "", goal or "", flags=re.I)):
        first = _first_sentence(src)
        if not first:
            continue
        plain = _plainer(first)
        cleaner = re.sub(r"\s+", " ", _TECH.sub("", plain)).strip(" ,-–—")
        # keep the tool names only when taking them out would leave almost nothing
        pick = cleaner if len(cleaner.split()) >= 3 else plain or first
        pick = _tidy_end(pick)
        if pick:
            pick = re.sub(r"^(?:a|an|the)\s+", "", pick, flags=re.I)
            return _cut(pick[:1].upper() + pick[1:])
    return "The plan"


def plan_title(doc: dict[str, Any] | None) -> str:
    doc = doc or {}
    return short_title(doc.get("title"), doc.get("summary", ""), doc.get("goal", ""))


def estimate_line(est: dict[str, Any] | None, agreed: float | dict[str, Any] | None = None) -> str:
    """"about $3.45 and 45 minutes" (the one line shown while a plan waits for approval). ``agreed``: what
    the owner agreed to (meta["agreed"] or its usd); shown as "(you agreed to about $Y)" when it differs."""
    est = est or {}
    mins = max(1, round(est.get("minutes") or 0))
    time = f"{mins} minutes" if mins < 90 else f"{round(mins / 60, 1):g} hours"
    tail = " (some models have no price yet)" if est.get("unpriced") else ""
    if isinstance(agreed, dict):
        agreed = agreed.get("usd")
    try:
        agreed = None if agreed is None else float(agreed)
    except (TypeError, ValueError):
        agreed = None
    cost = est.get("cost_usd") or 0
    if agreed is not None and f"{agreed:.2f}" != f"{cost:.2f}":
        tail += f" (you agreed to about ${agreed:.2f})"
    return f"about ${cost:.2f} and {time}{tail}"


def waiting_items(doc: dict[str, Any] | None) -> list[str]:
    """What waits for the owner, in words: "2 questions", "1 choice", "a look to choose", "3 changes to apply"."""
    o = open_items(doc)
    out = []
    choices = o["choices"] - look_open(doc)
    if choices:
        out.append(f"{choices} choice{'s' * (choices > 1)}")
    if look_open(doc):
        out.append("a look to choose")
    if o["questions"]:
        out.append(f"{o['questions']} question{'s' * (o['questions'] > 1)}")
    if o["pending"]:
        out.append(f"{o['pending']} change{'s' * (o['pending'] > 1)} to apply")
    return out


def state_sentence(doc: dict[str, Any] | None, tasks: list[Any] | None, meta: dict[str, Any] | None) -> str:
    """One plain sentence of where the plan stands: "Finished – 16 tasks, $5.01", "Waiting for you: 2 questions",
    "Building task 3 of 7"."""
    meta, tasks = meta or {}, list(tasks or [])
    status = meta.get("status") or ""
    spent = meta.get("spent_usd") or 0
    n = len(tasks)
    done = sum(1 for t in tasks if getattr(t, "status", None) == "done")
    money = f", ${spent:.2f}" if spent >= 0.005 else ""
    if status == "done" or (n and done == n and meta.get("plan_approved")):
        return f"Finished – {n} task{'s' * (n != 1)}{money}"
    if not meta.get("plan_approved"):
        wait = waiting_items(doc)
        return "Waiting for you: " + ", ".join(wait) if wait else "Ready for you to approve"
    failed = sum(1 for t in tasks if getattr(t, "status", None) == "failed")
    if failed:
        return f"Stopped: {failed} task{'s' * (failed > 1)} need{'s' * (failed == 1)} you"
    if status == "running":
        return f"Building task {min(n, done + 1)} of {n}"
    return f"Paused – {done} of {n} task{'s' * (n != 1)} done{money}"


# -- the estimate ---------------------------------------------------------------------------
def history_by_role(metric_files: list[Path]) -> dict[str, dict[str, float]]:
    """Average cost, minutes and attempts per task, per role, from past runs' metrics."""
    rows: dict[str, list[dict[str, Any]]] = {}
    for f in metric_files:
        try:
            for ln in f.read_text(encoding="utf-8").splitlines():
                d = json.loads(ln)
                # a rival's extra build (and the winner's row) are the dial's extras, priced on their own
                if d.get("rival") or d.get("outcome") == "rival_lost":
                    continue
                if d.get("role") and d.get("outcome") != "owner_feedback":
                    rows.setdefault(d["role"], []).append(d)
        except (OSError, ValueError):
            continue
    out = {}
    for role, rs in rows.items():
        tasks = {(r.get("task"), str(r.get("at", ""))[:10]) for r in rs}
        n = max(1, len(tasks))
        priced = [r for r in rs if r.get("cost_usd")]
        models = [r.get("model") for r in rs if r.get("model")]
        out[role] = {
            "cost": sum(r.get("cost_usd") or 0 for r in priced) / n if priced else None,
            "minutes": sum(r.get("seconds") or 0 for r in rs) / 60 / n,
            "attempts": len(rs) / n,
            "samples": len(rs),
            # what that cost bought, so another model's price can be put on the same work
            "model": max(set(models), key=models.count) if models else None,
            "input": sum(r.get("input_tokens") or 0 for r in rs) / n,
            "output": sum(r.get("output_tokens") or 0 for r in rs) / n,
        }
    from .imageprice import reported

    charges = reported(metric_files)  # what providers really charged, by model (pictures: imageprice.py)
    for role, rs in rows.items():
        used = {str(r.get("model")) for r in rs if r.get("model")}
        out[role]["charges"] = {m: round(c, 6) for m, c in charges.items() if m in used}
    return out


def _reprice(cfg, cost, h: dict[str, Any], model) -> float | None:
    """Past cost of a role's work, at today's model's price (the same work: the same tokens)."""
    from .config import ModelRef
    from ..providers.base import Usage

    if cost is None or not h.get("model") or h["model"] == str(model):
        return cost
    try:
        then = cfg.cost(ModelRef.parse(h["model"]), Usage(int(h["input"]), int(h["output"])))
        now = cfg.cost(model, Usage(int(h["input"]), int(h["output"])))
    except ValueError:
        return cost
    if not then or now is None:
        return cost
    return cost * now / then


def estimate(cfg, tasks, history: dict[str, dict[str, float]] | None = None, screens: bool = False,
             extras: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Rough cost and time for the given pending tasks, before anything runs. ``screens``: the app has screens,
    so each reviewed task may also have its pictures checked by a model that can see (proof.py, capped).
    ``extras``: the stages' own work (starting it, playing it, shipping it), each {id, usd, minutes, words},
    added to the totals and returned as ``extras``."""
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
            cost = _reprice(cfg, cost, h, role.models[0])
            if cost is None and role.kind == "image":  # unpriced pictures before: the pricing table may know
                from .imageprice import per_image

                cost = per_image(cfg, role.models[0], charges={})
        else:
            basis = "default"
            mins = DEFAULT_MINUTES.get(role.kind, 4.0)
            if role.kind == "image":  # one picture a task: what it really cost before, or per_image, else unknown
                from .imageprice import charges_from_history, per_image

                cost = per_image(cfg, role.models[0], charges=charges_from_history(history))
                if cost is None:
                    listed = cfg.cost(role.models[0], Usage(0, 0))
                    cost = listed or None
            else:
                i, o = DEFAULT_TOKENS["chat"]
                cost = cfg.cost(role.models[0], Usage(i, o))
            if role.review and reviewer and role.kind == "chat":
                rc = cfg.cost(reviewer.models[0], Usage(*DEFAULT_REVIEW_TOKENS))
                cost = None if cost is None or rc is None else cost + rc
                mins += REVIEW_MINUTES
            if role.kind != "image":
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
    proof_usd = 0.0
    if screens:
        from . import proof as prooflib

        looked = sum(1 for t in tasks if (cfg.roles.get(t.role) is not None and cfg.roles[t.role].kind == "chat"
                                          and cfg.roles[t.role].review and reviewer))
        proof_usd = prooflib.estimate_usd(cfg, looked)
        total += proof_usd
    kept = []
    for e in extras or []:
        if not isinstance(e, dict):
            continue
        try:
            usd, mins = float(e.get("usd") or 0), float(e.get("minutes") or 0)
        except (TypeError, ValueError):
            continue
        total += usd
        minutes += mins
        kept.append({"id": str(e.get("id") or ""), "usd": round(usd, 4), "minutes": round(mins, 1),
                     "words": str(e.get("words") or "")})
    for r in by_role.values():
        if r["cost_usd"] is not None:
            r["cost_usd"] = round(r["cost_usd"], 4)
        r["minutes"] = round(r["minutes"], 1)
    return {"cost_usd": round(total, 4), "minutes": round(minutes, 1), "tasks": len(tasks), "extras": kept,
            "unpriced": unpriced, "by_role": by_role, "at": utcnow(), "proof_usd": proof_usd,
            "note": "rough: from past runs where there are some, else typical sizes; unpriced models aren't counted"}


# -- reading it -------------------------------------------------------------------------------
def _look_markdown(look: dict[str, Any], image_base: str) -> list[str]:
    L = ["## Look", "Choose the look of the app: send `look` with its id (a note may say what to change).", ""]
    pics = look.get("pictures") or {}
    for d in look.get("directions", []):
        mark = " (chosen)" if look.get("chosen") == d["id"] else ""
        light, dark = d["palette"]["light"], d["palette"]["dark"]
        L += [f"### {d['name']}{mark} {{{d['id']}}}", d.get("mood", ""),
              f"Signature: {d.get('signature', '')}",
              f"Accent: {light['accent']} (light), {dark['accent']} (dark) · Fonts: {d['fonts']['display']['family']}"
              f" and {d['fonts']['body']['family']}"]
        if d["id"] in pics:
            L.append(f"![{d['id']}: {d['name']}]({image_base}{d['id']}.png)")
        L.append("")
    if look.get("chosen") and look.get("note"):
        L += [f"The owner's note: {look['note']}", ""]
    return L


def _references_markdown(refs: list[dict[str, Any]]) -> list[str]:
    L = ["## Like these", "What you want it to be like. Similar, never a copy: no names, characters, art, music or "
         "text taken; code only where the licence allows it, with credit.", ""]
    for r in refs:
        rep = r.get("report") or {}
        L.append(f"### {rep.get('title') or r['input'][:120]} {{{r['id']}}}")
        if r.get("status") == "new":
            L += ["Not read yet: it is read when the plan is next updated.", ""]
            continue
        if r.get("status") == "failed":
            L += [r.get("error") or "Couldn't read it.", f"You gave: {r['input'][:300]}", ""]
            continue
        L.append(rep.get("what_it_is", ""))
        for title, key in (("Borrow", "borrow"), ("Avoid", "avoid")):
            if rep.get(key):
                L.append(f"{title}: " + "; ".join(rep[key]))
        L.append(f"Licence: {rep.get('licence', 'unknown')} · code: {rep.get('code_reuse', 'not allowed')}")
        if rep.get("unreadable"):
            L.append("Couldn't read: " + "; ".join(rep["unreadable"]))
        L.append("")
    return L


def _question_markdown(q: dict[str, Any]) -> str:
    line = f"- {q['text']} {{{q['id']}}}"
    opts = q.get("options") or []
    if opts:
        marks = lambda o: " (recommended)" if o["id"] == q.get("recommended") else ""  # noqa: E731
        line += ("\n  Answers" + (" (any of)" if q.get("multi") else "") + ": "
                 + "; ".join(f"{o['label']}{marks(o)} {{{o['id']}}}" for o in opts))
    return line + (f"\n  Answer: {q['answer']}" if q.get("answer") else "")


def render_markdown(doc: dict[str, Any], tasks: list[Any] | None = None, image_base: str = "look/",
                    waiting: bool = True) -> str:
    """Readable plan, short first: the owner's title, the plain summary, the estimate (only while the plan
    waits for approval), then the rest (the builders' brief, scope, spec, choices...) as sections.

    Items end with their id in braces ({C1}-style ids for options {a}, questions {Q1},
    ideas {I1}, don'ts {D1}, looks {A}; decisions and spec sections carry [C1]/[S1] in their heading) so a
    phone can send commands about them. ``image_base`` is where the look pictures are, relative to the page."""
    L = [f"# {plan_title(doc)}", ""]
    if doc.get("summary"):
        L += [doc["summary"], ""]
    est = doc.get("estimate") or {}
    if est and waiting:
        L += [f"Estimate: {estimate_line(est)}", ""]
    if doc.get("goal"):
        L += [f"## The builders' brief (version {doc.get('version', 1)})", doc["goal"], ""]
    if doc.get("estimates"):
        current = doc.get("profile")
        L += ["## Sets of models", "Settings: " + "; ".join(
            f"{name}{' (chosen)' if name == current else ''} about ${e.get('cost_usd') or 0:.2f}"
            + (f", not counting {len(e['unpriced'])} unpriced" if e.get("unpriced") else "")
            for name, e in doc["estimates"].items()), ""]
    for title, key in (("In scope", "in_scope"), ("Out of scope", "out_of_scope")):
        if doc.get(key):
            L += [f"## {title}"] + [f"- {x}" for x in doc[key]] + [""]
    if doc.get("dont"):
        L += ["## Don't"] + [f"- {x['text']}" + (f" ({x['why']})" if x.get("why") else "") + f" {{{x['id']}}}"
                             for x in doc["dont"]] + [""]
    from . import donelist  # lazy: donelist imports nothing from here

    L += donelist.markdown(doc)  # "Done when"
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
    if doc.get("references"):
        L += _references_markdown(doc["references"])
    if (doc.get("look") or {}).get("directions"):
        L += _look_markdown(doc["look"], image_base)
    if doc.get("questions"):
        L += ["## Questions for the owner"] + [_question_markdown(q) for q in doc["questions"]] + [""]
    if doc.get("ideas"):
        L += ["## Ideas"] + [f"- [{i['state']}] {i['text']}" + (f" ({i['why']})" if i.get("why") else "")
                             + f" {{{i['id']}}}" for i in doc["ideas"]] + [""]
    c = doc.get("critique")
    if c and c.get("points"):
        of = c.get("version")
        older = f" (of version {of}; this version may already answer it)" if of and of != doc.get("version") else ""
        L += [f"## Critique by {c.get('model', 'a second model')}{older}"] + [
            f"- [{p.get('severity', '?')}] {p.get('text', '')}" for p in c["points"]] + [""]
    if doc.get("council"):
        from . import council as _council  # lazy: "Where the planners disagreed"

        L += _council.markdown(doc)
    if tasks:
        from . import stages as _stages  # under a heading per stage; the same "## Tasks" list with none

        L += _stages.markdown(doc, tasks)
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
    from . import donelist

    c = donelist.context(doc)
    if c:
        L.append(c)
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
    declined = [i["text"] for i in doc.get("ideas", []) if i.get("state") == "rejected"]
    if declined:
        L.append("The owner doesn't want: " + "; ".join(declined))
    look = doc.get("look") or {}
    chosen = next((d for d in look.get("directions", []) if d["id"] == look.get("chosen")), None)
    if chosen:
        L.append(f"Look (owner's choice): {chosen['name']}, see design/DESIGN.md")
    L += _references_context(doc.get("references") or [])
    for s in doc.get("spec", []):
        L.append(f"## {s['title']}\n{s.get('text', '')}")
    return "\n".join(L)


def _references_context(refs: list[dict[str, Any]]) -> list[str]:
    """The short form of the references for tasks and reviews, with the rule about copying."""
    read = [r for r in refs if r.get("report")]
    if not read:
        return []
    L = ["Make it like these (similar, never a copy: borrow ideas, mechanics and general style; never their names, "
         "characters, story, art, music, sounds, levels, logos or text; never copy their images, sounds, fonts or "
         "models):"]
    for r in read:
        rep = r["report"]
        L.append(f"- {r['id']} {rep.get('title', '')}: {rep.get('what_it_is', '')[:300]}"
                 + (f" Borrow: {'; '.join(rep.get('borrow', []))[:400]}." if rep.get("borrow") else "")
                 + (f" Avoid: {'; '.join(rep.get('avoid', []))[:300]}." if rep.get("avoid") else ""))
    credit = [r for r in read if r["report"].get("code_reuse") == "allowed with credit"]
    if credit:
        L.append("Code may be taken only from " + ", ".join(f"{r['id']} ({r['report'].get('licence')})" for r in credit)
                 + ", and then its licence and copyright line go into THIRD_PARTY_NOTICES.md. Code from any other "
                 "reference must not be copied.")
    else:
        L.append("No reference's code may be copied: write your own.")
    return L


# what every question, decision and idea for the owner must be like (they read it on a phone)
PLAIN = ("for someone who isn't a programmer: one short plain sentence about what they will see or get, no tool "
         "names or jargon (adb, Electron, smoke test, API, framework...)")


def submission_schema(task_schema: dict[str, Any]) -> dict[str, Any]:
    """The submit_plan tool's parameters: tasks plus the optional plan document parts."""
    s = {"type": "string"}
    plain = {**s, "description": PLAIN}
    option_plain = {**s, "description": "one line: what choosing it means for the owner, in plain words"}
    item = lambda props, req: {"type": "object", "properties": props, "required": req}  # noqa: E731
    return {
        "type": "object",
        "properties": {
            "title": {**s, "description": "the plan's name for the owner: at most 8 plain words about what they get, "
                                         "e.g. \"Music player for phone and PC\"; no file names, tools or versions"},
            "summary": {**s, "description": "one or two plain sentences for the owner: what will be built (what they "
                                           "will see or get), no tool names or file names"},
            "in_scope": {"type": "array", "items": s},
            "out_of_scope": {"type": "array", "items": s},
            "dont": {"type": "array", "description": "things not to do (traps, over-engineering, risky choices)",
                     "items": item({"text": s, "why": s}, ["text"])},
            "spec": {"type": "array", "description": "short spec sections: stack, structure, screens, data, style...",
                     "items": item({"id": {**s, "description": "S1, S2..."}, "title": s, "text": s}, ["id", "title", "text"])},
            "decisions": {"type": "array", "description": "real choices the owner may want to make, with your recommendation",
                          "items": item({
                              "id": {**s, "description": "C1, C2..."}, "question": plain,
                              "header": {**s, "description": "a label of at most 12 characters, e.g. Art style"},
                              "options": {"type": "array", "items": item({"id": s, "label": s, "detail": option_plain,
                                                                         "cost": {**s, "description": "effort/cost note"}},
                                                                        ["id", "label"])},
                              "recommended": {**s, "description": "option id"}, "why": s,
                              "section": {**s, "description": "spec section id it affects"}},
                              ["id", "question", "options", "recommended", "why"])},
            "questions": {"type": "array", "description": "what you need the owner to tell you (only real unknowns); "
                                                           "offer 2-4 likely answers to tap, your recommendation first "
                                                           "(the owner can still type their own)",
                          "items": item({
                              "id": {**s, "description": "Q1, Q2..."}, "text": plain, "why": s,
                              "header": {**s, "description": "a label of at most 12 characters, e.g. Audience"},
                              "options": {"type": "array", "description": "2-4 likely answers, the recommended first",
                                          "items": item({"id": {**s, "description": "a, b, c..."}, "label": s,
                                                         "detail": option_plain}, ["id", "label"])},
                              "recommended": {**s, "description": "option id (normally the first)"},
                              "multi": {"type": "boolean", "description": "true when more than one answer can apply"}},
                              ["id", "text"])},
            "ideas": {"type": "array", "description": "worthwhile extras beyond the goal, for the owner to accept or not",
                      "items": item({"id": {**s, "description": "I1, I2..."}, "text": plain, "why": s}, ["id", "text"])},
            "has_ui": {"type": "boolean", "description": "true when the project is an app or game with screens "
                                                         "people look at (web, desktop, phone); false for a library, "
                                                         "command-line tool or service"},
            "tasks": {"type": "array", "items": task_schema},
            "notes": s,
        },
        "required": ["tasks"],
    }
