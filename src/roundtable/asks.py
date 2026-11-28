"""Questions for the owner as cards to tap: one shape for everything that waits for them.

Every ask looks the same on the desktop, the phone and through the hub::

    {id, kind, project, header, question, detail, options: [{id, label, description, confirm?}],
     recommended, multi, allow_other: true, other_hint, stamp, answer: null, source: {...}}

``header`` is a chip of at most 12 characters; the recommended option comes first; ``allow_other``
always offers "Other…" with a text box. An option with ``confirm`` spends money beyond the shown
estimate (or can't be undone), so the app asks "Are you sure?" first and sends ``confirmed``.

A command waiting for "Ask me first" (harness/gate.py) is a card of kind ``command``: it also carries
``command`` (the whole text), ``preview`` and ``folded`` (a long one is shown folded, "Show all"),
``reasons``, ``task`` {id, title}, ``remember`` (what "Always allow" keeps) and ``expires_at``. Its answers
are ``allow`` (Allow once), ``always`` (Always allow in this project) and ``deny`` (Don't allow); typed
words alone mean "Don't allow" with a note for the builder. It can't be left for later.

``open_asks`` turns the project's state into asks: waiting commands, then money and failures first. ``answer_ask`` applies
an answer through the orchestrator's own actions (choose, answer, idea, look, approve, retry, accept,
skip, profile, steer): there is no second way of changing things. Long work an answer starts (a run,
a plan update, new looks) is returned as ``then`` for the caller to start as a job (``finish`` does
it in the foreground, for the hub's remote commands).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from .harness import plandoc
from .harness.orchestrator import HarnessError

OTHER_HINT = "Type your own answer"
SKIP = "_skip"


def _ask(aid: str, kind: str, header: str, question: str, options: list[dict[str, Any]], *,
         recommended: str | None = None, multi: bool = False, detail: str = "", other_hint: str = OTHER_HINT,
         source: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    """One card. The recommended option is moved to the front and marked."""
    opts = [{"id": str(o["id"]), "label": str(o["label"])[:80], "description": str(o.get("description") or "")[:200],
             **({"confirm": o["confirm"]} if o.get("confirm") else {}),
             **({"picture": o["picture"]} if o.get("picture") else {})} for o in options]
    rec = recommended if any(o["id"] == recommended for o in opts) else None
    if rec:
        opts.sort(key=lambda o: o["id"] != rec)
    ask = {"id": aid, "kind": kind, "header": " ".join(header.split())[:12].strip(), "question": question,
           "detail": detail[:400], "options": opts, "recommended": rec, "multi": bool(multi and len(opts) > 1),
           "allow_other": True, "other_hint": other_hint, "answer": None, "source": source or {}, **extra}
    ask["stamp"] = _stamp(ask)
    return ask


def _stamp(ask: dict[str, Any]) -> str:
    """Changes when the question changes, so an old answer can't settle a new question."""
    raw = json.dumps([ask["question"], [(o["id"], o["label"]) for o in ask["options"]], ask["source"]], sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:10]


def _money(x: float | None) -> str:
    return f"${(x or 0):.2f}"


# -- what waits ------------------------------------------------------------------------------------
def open_asks(orch, answered: bool = False) -> list[dict[str, Any]]:
    """Everything waiting for the owner on one project, as cards, most urgent first.

    ``answered``: also the plan's cards the owner has answered already (with ``answer`` filled in), so the
    plan page can show them and the owner can change an answer before approving."""
    meta = orch.project.meta()
    doc = orch.project.plan_doc()
    tasks = orch.project.tasks()
    from .harness import donestage  # here, not at the top: the harness imports this module
    from . import asktimer

    asks = command_asks(orch.project.root) + _money_asks(orch, meta) + _failed_asks(orch, meta, tasks)
    asks += [a for a in [donestage.not_finished_ask(orch, meta)] if a]  # the done gate stopped it
    from .harness import quiet

    asks += [a for a in [quiet.quiet_ask(orch, meta)] if a]  # a run gone quiet: wait, or stop it (quiet.py)
    asks += [a for a in [ship_offer_ask(orch)] if a]  # make a test phone on this PC (shipstage.py, emulator.py)
    if doc and not meta.get("plan_approved"):  # once building, the plan's questions are settled
        asks += _plan_asks(orch, doc, meta)
    name = orch.project.root.name
    dismissed = meta.get("asks_dismissed") or {}
    out = []
    for a in asks:
        if a["answer"] is None and dismissed.get(a["id"]) == a["stamp"]:
            continue
        if a["answer"] is not None and not answered:
            continue
        a["project"], a["path"] = name, str(orch.project.root)
        asktimer.stamp(a, orch.project.root)  # a card with a timer says when it runs out (asktimer.py)
        out.append(a)
    out = asktimer.sweep(orch, out)  # the cards whose time ran out are answered as they said
    return out


def _ship_offer_path(orch) -> Path:
    from .harness.shipstage import SHIP_OFFER_FILE

    return orch.project.root / ".harness" / SHIP_OFFER_FILE


def ship_offer_ask(orch) -> dict[str, Any] | None:
    """The one-tap card when an APK could not be tried on a phone: make a test phone on this computer?
    The download's size and what it gives first; the exact commands only behind More. PC only."""
    try:
        d = json.loads(_ship_offer_path(orch).read_text(encoding="utf-8"))
        offer = d["offer"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not offer.get("can"):
        return None
    opts = [{"id": "yes", "label": "Make it", "description": f"Downloads {offer.get('size') or 'the test phone'} "
                                                          "and makes it. Then your app is opened and pictured."},
            {"id": "no", "label": "Not now", "description": "Nothing is downloaded. It asks again next time."}]
    commands = "\n".join(" ".join(str(x) for x in c) for c in offer.get("commands") or [])
    ask = _ask("shipoffer", "ship_offer", "Test phone", f"{offer.get('title') or 'Make a test phone'}?", opts,
               recommended="yes", detail=str(offer.get("words") or ""), source={"ship_offer": d.get("target", "")},
               pc_only=True, more=commands)
    ask["allow_other"] = False
    return ask


def _apply_ship_offer(orch, ask, picked, other):
    path = _ship_offer_path(orch)
    if (picked or ["no"])[0] != "yes":
        try:
            path.unlink()
        except OSError:
            pass
        return {"reply": "Left for now: no test phone is made.", "then": None}
    return {"reply": "Making the test phone (a big download: this takes a while)…", "then": "emulator"}


def _make_test_phone(orch) -> str:
    """The long step of "Make it": download the system image and make the virtual phone."""
    from .harness import emulator

    path = _ship_offer_path(orch)
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "The offer has gone: try the build again."
    r = emulator.make_avd(Path(d.get("sdk") or ""), str(d.get("os") or ""))
    if r.get("ok"):
        try:
            path.unlink()
        except OSError:
            pass
    return str(r.get("words") or "")


def command_asks(root: Path) -> list[dict[str, Any]]:
    """The commands waiting for the owner's tap in this project ("Ask me first")."""
    from .harness.gate import Gate

    try:
        waiting = Gate(root).pending()
    except OSError:
        return []
    return [{**command_ask(w), "project": Path(root).name, "path": str(root)} for w in waiting]


def _sentence(reasons: list[str]) -> str:
    text = "; ".join(r for r in reasons[:3] if r)
    return (text[:1].upper() + text[1:] + ".") if text else ""


def command_ask(w: dict[str, Any]) -> dict[str, Any]:
    """One waiting command as a card."""
    task = w.get("task") or {}
    who = f"Task {task['id']} “{task.get('title', '')}”" if task.get("id") else "A builder"
    why = _sentence(list(w.get("reasons") or []))
    remember = str(w.get("remember") or "this exact command")
    opts = [{"id": "allow", "label": "Allow once", "description": "It runs this time. Next time it asks again."},
            {"id": "always", "label": "Always allow in this project",
             "description": f"It runs now, and {remember} runs without asking in this project from now on."},
            {"id": "deny", "label": "Don't allow", "description": "It doesn't run. The builder is told and carries on without it."}]
    doing = str(w.get("doing") or "")  # a tool that waits (perms.py): what it wants to do, in plain words
    question = (f"{who} wants to {doing[:1].lower() + doing[1:]}. Allow it?" if doing
                else f"{who} wants to run a command. Allow it?")
    ask = _ask(f"command:{w['id']}", "command", "Command", question, opts,
               detail=f"Why it asks: {why}" if why else "",
               other_hint="Don't allow, and tell it what to do instead",
               source={"command": w["id"]})
    ask.update({"command": w.get("command", ""), "preview": w.get("preview", ""), "folded": bool(w.get("folded")),
                "lines": w.get("lines", 1), "size": w.get("size", 0), "reasons": list(w.get("reasons") or []),
                "task": task, "remember": remember, "asked_at": w.get("asked_at", ""),
                "expires_at": w.get("expires_at", ""), "tool": w.get("tool", ""), "box": w.get("box", "")})
    return ask


def _plan_asks(orch, doc: dict[str, Any], meta: dict[str, Any]) -> list[dict[str, Any]]:
    asks = []
    kind = _kind_ask(orch)
    if kind:
        asks.append(kind)  # first: "This looks like a website. Right?"
    asks += [_decision_ask(d) for d in doc.get("decisions", [])]
    asks += [_question_ask(q) for q in doc.get("questions", [])]
    if (doc.get("look") or {}).get("directions"):
        asks.append(_look_ask(doc["look"]))
    if doc.get("estimates") and meta.get("status") == "awaiting_approval":
        asks.append(_answered(profile_ask(orch.base_cfg, doc), [meta["profile"]] if meta.get("profile") else None))
    asks += [_idea_ask(i) for i in doc.get("ideas", []) if i.get("state") in ("open", "accepted", "rejected")]
    if meta.get("status") == "awaiting_approval":
        try:
            at = orch.cheap_start_at()
        except Exception:  # a price question must never hide the approve card
            at = None
        try:
            from .harness import dial

            checking = dial.words(orch) if dial.level(orch) != "lean" else ""  # a plan before 1.2.0: as before
        except Exception:  # noqa: BLE001 - the words must never hide the approve card
            checking = ""
        asks.append(_approve_ask(doc, at.strftime("%H:%M") if at else None, checking))
    return asks


def _answered(ask: dict[str, Any], chosen: list[str] | None, other: str = "") -> dict[str, Any]:
    """Mark a card answered (None: still open)."""
    if chosen is not None or other:
        ask["answer"] = {"chosen": chosen or [], "other": other}
    return ask


def _decision_ask(d: dict[str, Any]) -> dict[str, Any]:
    opts = [{"id": o["id"], "label": o["label"],
             "description": " · ".join(x for x in (o.get("detail"), o.get("cost")) if x)} for o in d["options"]]
    return _ask(f"choose:{d['id']}", "decision", d.get("header") or "Choice", d["question"], opts,
                recommended=d.get("recommended"), detail=f"Recommended because: {d['why']}" if d.get("why") else "",
                other_hint="Something else? Say what you want", source={"decision": d["id"]},
                **({"timer": d["timer"]} if d.get("timer") else {})) \
        | {"answer": {"chosen": [d["chosen"]], "other": ""} if d.get("chosen") else None}


def _question_ask(q: dict[str, Any]) -> dict[str, Any]:
    opts = [{"id": o["id"], "label": o["label"], "description": o.get("detail", "")} for o in q.get("options") or []]
    return _ask(f"answer:{q['id']}", "question", q.get("header") or "Question", q["text"], opts,
                recommended=q.get("recommended") or None, multi=bool(q.get("multi")), detail=q.get("why") or "",
                other_hint="Type your answer" if not opts else OTHER_HINT, source={"question": q["id"]},
                **({"timer": q["timer"]} if q.get("timer") else {})) \
        | {"answer": _question_answer(q)}


def _question_answer(q: dict[str, Any]) -> dict[str, Any] | None:
    """What the owner answered: the tapped answers, and whatever else they typed."""
    if not q.get("answer"):
        return None
    chosen = list(q.get("chosen") or [])
    labels = {o["label"] for o in q.get("options") or [] if o["id"] in chosen}
    typed = "; ".join(x for x in q["answer"].split("; ") if x not in labels)
    return {"chosen": chosen, "other": typed}


def _idea_ask(i: dict[str, Any]) -> dict[str, Any]:
    opts = [{"id": "yes", "label": "Yes, add it", "description": "The planner adds it to the plan."},
            {"id": "no", "label": "No thanks", "description": "It won't be suggested again."}]
    state = {"accepted": ["yes"], "rejected": ["no"]}.get(i.get("state", ""))
    return _answered(_ask(f"idea:{i['id']}", "idea", "Idea", f"Add this? {i['text']}", opts,
                          recommended=None if i.get("recommended") is False else "yes", detail=i.get("why") or "", other_hint="Yes, but… (say what to change)",
                          source={"idea": i["id"]}), state)


def _kind_ask(orch) -> dict[str, Any] | None:
    """What kind of thing the project is (kinds; harness/kindstage.py), until the plan is approved."""
    get = getattr(orch, "_kind_doc", None)
    try:
        d = get() if callable(get) else None
    except Exception:  # a kind is a help: it never hides the other cards
        d = None
    if not d or d.get("fixed"):
        return None
    if d["id"] == "other" and not d.get("confirmed"):
        return None  # no clue what it is: no question to ask (the plan page still lets the owner say)
    opts = [{"id": c["id"], "label": c["name"]} for c in d.get("choices") or []]
    ask = _ask("kind", "kind", "Kind", d["question"], opts, recommended=d["id"],
               detail=d.get("change_words") or "", other_hint="Something else? Say what it is",
               source={"kind": d["id"], "extras": [e["id"] for e in d.get("extras") or []]})
    return _answered(ask, [d["id"]] if d.get("confirmed") else None)


def _look_ask(look: dict[str, Any]) -> dict[str, Any]:
    opts = [{"id": d["id"], "label": f"{d['id']} · {d['name']}", "description": d.get("mood", ""), "picture": d["id"]}
            for d in look.get("directions", [])]
    ask = _ask("look", "look", "Look", "Which look should the app have?", opts, recommended=opts[0]["id"],
               detail="Every screen then follows the look you choose.",
               other_hint="A note on the one you pick, or what new looks should be like",
               source={"look": [o["id"] for o in opts]}, pictures=True)
    return _answered(ask, [look["chosen"]] if look.get("chosen") else None, look.get("note", "") if look.get("chosen") else "")


def profile_ask(cfg, doc: dict[str, Any] | None = None) -> dict[str, Any]:
    """Budget / Balanced / Quality, with each one's estimate when there's a plan."""
    ests = (doc or {}).get("estimates") or {}
    opts = []
    for name, prof in cfg.profiles.items():
        e = ests.get(name)
        cost = f"About {_money(e.get('cost_usd'))}" + (f", about {round(e['minutes'])} min" if e.get("minutes") else "") \
            if e else ""
        opts.append({"id": name, "label": name[:1].upper() + name[1:],
                     "description": ". ".join(x for x in (cost, str((prof or {}).get("description") or "")) if x)})
    rec = (doc or {}).get("profile") or ("balanced" if "balanced" in cfg.profiles else cfg.default_profile)
    return _ask("profile", "profile", "Setting", "Which setting should do the work?", opts, recommended=rec,
                detail="Budget uses cheaper models, Quality the strongest. You can change it later.",
                source={"profiles": list(cfg.profiles)})


def _approve_ask(doc: dict[str, Any], cheap_at: str | None = None, checking: str = "") -> dict[str, Any]:
    pending = len(doc.get("pending") or [])
    est = doc.get("estimate") or {}
    cost = f"About {_money(est.get('cost_usd'))}, about {round(est.get('minutes') or 0)} minutes."
    if checking:  # "Checking: Balanced (about $0.40 of this)" (dial.py)
        cost += f" {checking}."
    if pending:
        opts = [{"id": "revise", "label": "Update the plan", "description":
                 "The planner applies your changes. You see the new plan before anything is built."},
                {"id": "not_now", "label": "Not now", "description": "Your changes wait here."}]
        return _ask("approve", "approve", "Plan", f"Update the plan with your {pending} change{'s' * (pending > 1)}?",
                    opts, recommended="revise", other_hint="Anything else to change? Say it here",
                    source={"pending": pending, "version": doc.get("version")})
    opts = [{"id": "approve", "label": "Approve and start", "description": f"Builds it now. {cost}"}]
    if cheap_at:  # a provider doing the work is half price later today
        opts.append({"id": "approve_cheap", "label": f"Approve, start at {cheap_at} UTC",
                     "description": "Waits for off-peak hours, when DeepSeek charges half. The desktop app starts it then."})
    opts.append({"id": "not_now", "label": "Not now", "description": "Keep the plan; nothing is built yet."})
    return _ask("approve", "approve", "Plan", "Is the plan right? Start building?", opts, recommended="approve",
                other_hint="Change something… (say what)", source={"version": doc.get("version")})


def _failed_asks(orch, meta: dict[str, Any], tasks) -> list[dict[str, Any]]:
    if meta.get("status") != "blocked":
        return []
    from .harness import unstick

    card = unstick.stuck_ask(orch, tasks)  # worked out and parked: one card for them all
    if card:
        return [card]
    out = []
    for t in tasks:
        if t.status != "failed":
            continue
        last = t.attempts[-1] if t.attempts else {}
        why = (last.get("review") or last.get("error") or "").strip()
        opts = [{"id": "retry", "label": "Retry", "description": "Try again, with the reviewer's notes."}]
        strong = orch.stronger_models(t)
        if strong:
            opts.append({"id": "stronger", "label": "Retry with the stronger model",
                         "description": f"Uses {strong[0]} (the Quality setting) for this task.",
                         "confirm": f"The stronger model costs more than the estimate. Retry {t.id} with {strong[0]}?"})
        opts += [{"id": "accept", "label": "Accept as it is", "description": "Keep the work in the files; it counts as done."},
                 {"id": "skip", "label": "Skip it", "description": "Leave it out and carry on with the rest."}]
        out.append(_ask(f"task:{t.id}", "failed", "Task failed",
                        f"{t.id} “{t.title}” didn't pass after {len(t.attempts)} tr{'ies' if len(t.attempts) != 1 else 'y'}."
                        " What now?", opts, recommended="retry", detail=f"Last note: {why[:300]}" if why else "",
                        other_hint="Tell it what to do differently, then it tries again",
                        source={"task": t.id, "attempts": len(t.attempts)},
                        **({"engine": eng} if (eng := _missing_engine(last)) else {})))
    return out


def _missing_engine(attempt: dict[str, Any]) -> str:
    """The coding helper (claude-code, codex) a task stopped for because it isn't installed, else "": its card
    then offers "Install it and carry on" (prereq.engine_offer, ui/reachapi.py)."""
    model, error = str(attempt.get("model") or ""), str(attempt.get("error") or "")
    if not model.startswith("cli/") or "isn't installed on this computer" not in error:
        return ""
    return model.split("/", 1)[1].split("@", 1)[0]


def _money_asks(orch, meta: dict[str, Any]) -> list[dict[str, Any]]:
    status, why = meta.get("status"), meta.get("pause")
    if status == "paused_budget" or why == "budget":
        extra = _carry_on_amount(orch)
        q = f"This project reached its limit of {_money(orch.budget.limit_usd)}. Carry on?"
        more = {"id": "more", "label": f"Carry on with {_money(extra)} more",
                "description": "Raises this project's limit and carries on with the tasks left.",
                "confirm": f"This lets the project spend up to {_money(extra)} more of your credit. Carry on?"}
    elif status == "paused" and why in ("money", "money_nothing_done"):
        extra = orch.cfg.limits.max_real_usd_per_run
        q = ("This run spent half its money limit and finished nothing. Carry on?" if why == "money_nothing_done"
             else f"This run spent {_money(extra)} of real credit, the limit you set. Carry on?")
        more = {"id": "more", "label": f"Carry on with {_money(extra)} more",
                "description": "Starts the run again with the same limit.",
                "confirm": f"This can spend up to {_money(extra)} more of your credit. Carry on?"}
    elif status == "paused" and why in ("over_estimate", "allowance"):
        from .harness import moneystage

        card = moneystage.over_estimate_ask(orch)
        if not card:
            return []
        return [_ask("money", "money", "Money", card["question"], card["options"], recommended=card["recommended"],
                     other_hint="Anything to tell it before it carries on?", source=card["source"])]
    elif status == "paused" and why in ("job_cap", "service_cap"):
        from .harness import usage

        card = usage.job_cap_ask(orch)
        if not card:
            return []
        return [_ask("money", "money", "Money", card["question"], card["options"], recommended=card["recommended"],
                     other_hint="Anything to tell it before it carries on?", source=card["source"])]
    elif status == "paused" and why == "credit":
        q = f"An account ran out of credit ({meta.get('reason', '')[:120]}). Top it up, then carry on."
        more = {"id": "more", "label": "I've topped it up: carry on", "description": "Starts the run again."}
        extra = 0.0
    else:
        return []
    opts = [more, {"id": "stop", "label": "Stop here", "description": "Nothing more is spent. You can carry on later."}]
    cheaper = next((n for n in orch.base_cfg.profiles if n.lower() == "budget"), None)
    if cheaper and orch.profile() != cheaper:
        opts.append({"id": "budget", "label": "Switch to the Budget setting",
                     "description": "Cheaper models for the tasks left, then carry on.",
                     "confirm": "Switch to cheaper models and carry on? It still spends some credit."})
    return [_ask("money", "money", "Money", q, opts, recommended="more",
                 other_hint="Anything to tell it before it carries on?",
                 source={"pause": why or status, "at": meta.get("updated_at", ""), "extra": extra})]


def _carry_on_amount(orch) -> float:
    """Enough for the tasks left (from the estimate), at least $1, rounded up to whole dollars."""
    try:
        est = orch._estimate(orch.project.tasks()).get("cost_usd") or 0
    except Exception:
        est = 0
    return float(max(1, math.ceil(est or orch.cfg.limits.max_cost_usd * 0.5)))


# -- answering ---------------------------------------------------------------------------------------
def find_ask(orch, ask_id: str) -> dict[str, Any]:
    for a in open_asks(orch, answered=True):  # an answer can be changed until the plan is approved
        if a["id"] == ask_id:
            return a
    raise HarnessError("That question has been answered already or has changed. Look again for what's waiting.")


def answer_ask(orch, ask_id: str, chosen: list[str] | str | None = None, other: str = "",
               confirmed: bool = False, stamp: str | None = None, skip: bool = False) -> dict[str, Any]:
    """Apply the owner's answer. Returns {"reply": plain words, "then": None | "run" | "revise" | "looks",
    "text": what a long step needs}."""
    ask = find_ask(orch, ask_id)
    if stamp and stamp != ask["stamp"]:
        raise HarnessError("That question changed since you saw it. Look at it again, then answer.")
    if skip and ask["kind"] == "command":
        raise HarnessError("A command can't wait for later: tap Allow once or Don't allow.")
    if skip:
        _dismiss(orch, ask)
        return {"reply": "Left for later.", "then": None}
    picked = _picked(ask, chosen)
    other = str(other or "").strip()[:2000]
    if not picked and not other:
        raise HarnessError("Pick an answer, or type one.")
    need = next((o["confirm"] for o in ask["options"] if o["id"] in picked and o.get("confirm")), None)
    if need and not confirmed:
        raise HarnessError(f"Are you sure? {need}")
    return APPLY[ask["kind"]](orch, ask, picked, other)


def _picked(ask: dict[str, Any], chosen) -> list[str]:
    if isinstance(chosen, str):
        chosen = [c.strip() for c in chosen.split(",") if c.strip()]
    picked = [str(c) for c in chosen or []]
    ids = [o["id"] for o in ask["options"]]
    bad = [c for c in picked if c not in ids]
    if bad:
        raise HarnessError(f"{', '.join(bad)} isn't one of the answers. Look at the question again.")
    if len(picked) > 1 and not ask["multi"]:
        raise HarnessError("Pick one answer for this question.")
    return picked


def _dismiss(orch, ask: dict[str, Any]) -> None:
    meta = orch.project.meta()
    meta.setdefault("asks_dismissed", {})[ask["id"]] = ask["stamp"]
    orch.project.save_meta(meta)


def _label(ask: dict[str, Any], oid: str) -> str:
    return next(o["label"] for o in ask["options"] if o["id"] == oid)


def _apply_decision(orch, ask, picked, other):
    did = ask["source"]["decision"]
    if picked:
        orch.plan_update("choose", decision=did, option=picked[0])
    if other:
        orch.plan_update("note", text=f"For '{ask['question']}' the owner says: {other}")
    return {"reply": f"Noted: {_label(ask, picked[0]) if picked else other}. Update the plan to apply it.", "then": None}


def _apply_question(orch, ask, picked, other):
    text = "; ".join([_label(ask, p) for p in picked] + ([other] if other else []))
    orch.plan_update("answer", question=ask["source"]["question"], text=text, chosen=picked)
    return {"reply": f"Answer saved: {text}. Update the plan to apply it.", "then": None}


def _apply_idea(orch, ask, picked, other):
    iid = ask["source"]["idea"]
    accept = picked != ["no"]  # "Yes, but…" (typed) adds it with the owner's change
    orch.plan_update("idea", id=iid, accept=accept)
    if other:
        orch.plan_update("note", text=f"About the idea '{ask['question'][10:]}', the owner says: {other}")
    return {"reply": "Idea added." if accept else "Left out.", "then": None}


def _apply_look(orch, ask, picked, other):
    if picked:
        orch.plan_update("look", id=picked[0], note=other)
        return {"reply": f"Look {picked[0]} chosen. Update the plan to apply it.", "then": None}
    return {"reply": "Making three new looks from your note…", "then": "looks", "text": other}


def _apply_profile(orch, ask, picked, other):
    if not picked:
        raise HarnessError("Pick one of the settings.")
    r = orch.set_profile(picked[0])
    if other:
        orch.steer(other)
    return {"reply": f"This project now uses the {r['profile']} setting.", "then": None}


def _apply_approve(orch, ask, picked, other):
    if other and not picked:
        orch.plan_update("note", text=other)
        return {"reply": "Updating the plan with your change…", "then": "revise"}
    if picked == ["not_now"]:
        _dismiss(orch, ask)
        return {"reply": "Left as it is. Nothing is built until you approve.", "then": None}
    if picked == ["revise"]:
        if other:
            orch.plan_update("note", text=other)
        return {"reply": "Updating the plan with your changes…", "then": "revise"}
    orch.approve()
    if picked == ["approve_cheap"]:
        at = orch.start_when_cheap()
        if at:
            return {"reply": f"Approved: it starts at {at} UTC, when it's half price.", "then": None}
    return {"reply": "Approved: building has started.", "then": "run"}


def _apply_failed(orch, ask, picked, other):
    tid = ask["source"]["task"]
    if other:
        orch.steer(f"About task {tid}: {other}")
    choice = picked[0] if picked else "retry"
    if choice == "accept":
        orch.accept(tid, other)
        return {"reply": f"{tid} accepted as it is. Carrying on.", "then": "run"}
    if choice == "skip":
        orch.skip(tid)
        return {"reply": f"{tid} skipped. Carrying on.", "then": "run"}
    orch.retry(tid, stronger=choice == "stronger")
    return {"reply": f"Trying {tid} again" + (" with the stronger model." if choice == "stronger" else "."), "then": "run"}


def _apply_money(orch, ask, picked, other):
    choice = picked[0] if picked else "more"
    if other:
        orch.steer(other)
    if choice == "stop":
        _dismiss(orch, ask)
        return {"reply": "Stopped. Nothing more is spent until you carry on.", "then": None}
    if choice == "budget":
        r = orch.set_profile(next(n for n in orch.base_cfg.profiles if n.lower() == "budget"))
        return {"reply": f"Switched to the {r['profile']} setting. Carrying on.", "then": "run"}
    if ask["source"]["pause"] in ("over_estimate", "allowance"):
        from .harness import moneystage

        return moneystage.apply_answer(orch, ask["source"]["pause"], choice)
    if ask["source"]["pause"] in ("job_cap", "service_cap"):
        from .harness import usage

        return usage.apply_answer(orch, ask["source"]["pause"], choice)
    if ask["source"]["pause"] in ("budget", "paused_budget"):
        limit = orch.raise_budget(ask["source"]["extra"])
        return {"reply": f"The limit is now {_money(limit)}. Carrying on.", "then": "run"}
    return {"reply": "Carrying on.", "then": "run"}


def _apply_command(orch, ask, picked, other):
    from .harness.gate import ALLOW, ALWAYS, DENY, Gate

    choice = picked[0] if picked else DENY  # typed words alone: don't allow, with a note for the builder
    if not Gate(orch.project.root).answer(ask["source"]["command"], {"allow": ALLOW, "always": ALWAYS}.get(choice, DENY),
                                          other):
        raise HarnessError("That command isn't waiting any more (it was answered, or it waited too long).")
    if choice == "always":
        return {"reply": f"Allowed: it runs now, and {ask.get('remember') or 'this command'} won't ask again here.",
                "then": None}
    if choice == "allow":
        return {"reply": "Allowed: it runs now.", "then": None}
    return {"reply": "Not allowed: it won't run. The builder carries on without it.", "then": None}


def _apply_kind(orch, ask, picked, other):
    old = (orch.project.meta().get("kind") or {}).get("id")
    kid = picked[0] if picked else ""
    if not kid and other:
        from . import kinds as kindlib

        kid = kindlib.from_wizard("other", other=other, home=orch._kind_home())["kind"]
    if not kid:
        raise HarnessError("Pick what kind of thing it is, or say it in your own words.")
    r = orch.set_kind(kid, None if kid == old else [], by="owner", replan=False)
    name = (r.get("kind") or {}).get("name") or kid
    if kid == old:
        return {"reply": f"Kept as a {name}.", "then": None}
    orch.plan_update("note", text=f"The owner says this is a {name}"
                     + (f": {other}" if other else "") + ". Re-plan it as one: follow 'What this project is'.")
    return {"reply": f"It's a {name} now. Updating the plan for it…", "then": "revise"}


APPLY = {"kind": _apply_kind, "command": _apply_command, "decision": _apply_decision, "question": _apply_question, "idea": _apply_idea, "look": _apply_look,
         "profile": _apply_profile, "approve": _apply_approve, "failed": _apply_failed, "money": _apply_money,
         "not_finished": lambda *a: _lazy("donestage", "apply_not_finished")(*a),
         "stuck": lambda *a: _lazy("unstick", "apply_stuck")(*a),
         "quiet": lambda *a: _lazy("quiet", "apply_quiet")(*a), "ship_offer": _apply_ship_offer}


def _lazy(module: str, name: str):
    """A stage's own answer function, imported when it's needed (the stages import the orchestrator)."""
    import importlib

    return getattr(importlib.import_module(f".harness.{module}", __package__), name)


def finish(orch, result: dict[str, Any]) -> str:
    """Do the long step an answer started, in the foreground; returns a plain line about how it ended."""
    then = result.get("then")
    if then == "run":
        return f"The run ended as: {orch.run().replace('_', ' ')}."
    if then == "revise":
        return orch.revise_plan()["summary"] + "."
    if then == "emulator":
        return _make_test_phone(orch)
    if then == "looks":
        r = orch.look(result.get("text", ""))
        return "New looks: " + ", ".join(f"{x['id']} {x['name']}" for x in r["looks"]) + "."
    return ""


# -- the new-project wizard ------------------------------------------------------------------------------
KINDS = {"web": "Web app", "game": "Game", "android": "Android app", "windows": "Windows app"}


def _kinds_home():
    from .desktop import app_home

    return app_home()


def wizard_asks(cfg) -> list[dict[str, Any]]:
    """The cards of a new project, in order. The client asks them one by one, then posts the answers."""
    from . import kinds as kindlib

    options = kindlib.wizard_options(_kinds_home())  # the kinds usable now; the rest greyed under "Coming"
    make = _ask("kind", "wizard", "Make", "What do you want to make?", options, recommended="web-app",
                other_hint="Say what it is in your own words")
    extra = {o["id"]: o for o in options}
    for o in make["options"]:
        o.update({k: extra[o["id"]][k] for k in ("group", "disabled", "tip") if k in extra.get(o["id"], {})})
    asks = [
        make,
        {**_ask("idea", "wizard", "Idea", "Your idea, in a few words", [],
                detail="For example: “a bakery site with opening hours and a menu”. You can say more later.",
                other_hint="Describe your idea"), "required": True},
        _ask("like", "wizard", "Like this", "Make it like something you know?", [
            {"id": "no", "label": "No", "description": "Just from your idea."}], recommended="no",
            other_hint="Add links, repositories or names, one per line",
            detail="The harness makes something similar, never a copy: no names, art, music or text taken."),
    ]
    if cfg.profiles:
        asks.append(profile_ask(cfg))
    asks.append(_ask("look", "wizard", "Look", "Show you three looks to choose from?", [
        {"id": "yes", "label": "Yes, show me three looks", "description": "A designer draws three; you pick one."},
        {"id": "no", "label": "No", "description": "The builders choose a plain look."}], recommended="yes",
        other_hint="What should it look like?"))
    return asks


def slug(text: str, taken: set[str] | None = None) -> str:
    """A folder name from the idea: a few lowercase words joined with hyphens, unique among ``taken``."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    base = "-".join(w for w in words if w not in {"a", "an", "the", "with", "and", "for", "of"})[:40].strip("-") \
        or "project"
    name, n = base, 2
    while taken and name in taken:
        name, n = f"{base}-{n}", n + 1
    return name


def wizard_project(answers: dict[str, Any], projects_dir: Path) -> dict[str, Any]:
    """Turn the wizard's answers into what ``Orchestrator.start`` needs: folder, goal, references, setting, look."""
    def one(key: str) -> tuple[list[str], str]:
        a = answers.get(key) or {}
        chosen = a.get("chosen") or []
        return ([chosen] if isinstance(chosen, str) else list(chosen)), str(a.get("other") or "").strip()

    kind, kind_other = one("kind")
    _, idea = one("idea")
    if not idea:
        raise HarnessError("Write your idea in a few words first.")
    from . import kinds as kindlib

    chosen = kind[0] if kind else ""
    try:
        cat = kindlib.load_all(_kinds_home())
        picked = kindlib.from_wizard(chosen or "other", other=kind_other, idea=idea, catalog=cat)
    except Exception:  # a kind is a help: the project still starts without one
        cat, picked = None, {"kind": "", "extras": [], "by": "roundtable"}
    if isinstance(answers.get("extras"), list) and cat:  # "Make another like this": the same extras
        allowed = (set(kindlib.resolve(picked["kind"], catalog=cat).spec.get("extras_allowed") or [])
                   if picked["kind"] in cat.kinds else set())
        picked["extras"] = [str(x) for x in answers["extras"] if str(x) in allowed]
    named = cat.kinds[chosen].name if cat and chosen in cat.kinds and chosen != "other" else ""
    what = kind_other or KINDS.get(chosen, "") or named
    goal = f"{what}: {idea}" if what else idea
    _, like = one("like")
    refs = [x.strip() for x in like.splitlines() if x.strip()]
    prof, prof_note = one("profile")
    look, look_note = one("look")
    taken = {p.name for p in projects_dir.iterdir()} if projects_dir.is_dir() else set()
    return {"dir": projects_dir / slug(idea, taken), "goal": goal + (f"\nSetting note: {prof_note}" if prof_note else ""),
            "references": refs, "profile": prof[0] if prof else None,
            "look": (look != ["no"]) if (look or look_note) else None,
            "look_note": look_note, "kind": picked["kind"], "extras": picked["extras"], "kind_by": picked["by"]}


def apply_wizard_kind(orch, w: dict[str, Any]) -> None:
    """After ``start``: the kind the owner picked in the wizard (a guess from their words stays a guess)."""
    if not w.get("kind") or w.get("kind_by") != "owner" or not hasattr(orch, "set_kind"):
        return
    try:
        orch.set_kind(w["kind"], w.get("extras") or [], by="owner", replan=False)
    except HarnessError:
        pass  # not ready or not allowed: Roundtable's own guess stands


# -- the app's own cards (not a project's): the harness's fixes to itself (improve/selfrepair.py) ----------------
def app_asks(app) -> list[dict[str, Any]]:
    """Cards about the harness itself: a fault it found in its own code, and a fix ready to look at."""
    try:
        from .improve import selfrepair

        return [{**a, "path": "", "app": True} for a in selfrepair.ask(app)]
    except Exception:  # noqa: BLE001 - a card about the harness never breaks the owner's list
        return []


def is_app_ask(ask_id: str) -> bool:
    return str(ask_id or "").startswith("selfrepair-")


def answer_app_ask(app, ask_id: str, chosen) -> dict[str, Any]:
    """The owner's answer to one of the app's own cards; a yes to a fix starts it as a background job."""
    from .improve import selfrepair

    r = selfrepair.answer(app, ask_id, chosen)
    if ask_id.startswith("selfrepair-done-"):
        return {"reply": "Got it."}
    if r.get("started") is False:
        return {"reply": "Left as it is."}
    return {"reply": "Trying a fix: it works on a copy and opens a draft pull request only if every test passes."}

