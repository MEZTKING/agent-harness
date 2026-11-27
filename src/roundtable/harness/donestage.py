"""The done stage: what "finished" means, written from the idea, and a run that can't be called done while
an item on that list fails.

A mixin, like the kind and look stages. It brings the prep stage with it (prep.py: the idea tidied first).

- ``_done_schema`` / ``_done_plan_part``: the planner gives 3 to 8 items ("You can start a game, lose and
  start again"), each with how it can be shown (harness/donelist.py ``HOWS``).
- ``_done_doc``: the items cleaned and merged with the kind's proof checks (``by: kind``) and the owner's own
  items (kept word for word), into ``doc["done_list"]`` and ``.harness/done.json``.
- ``_done_worker_part``: each task is told the items it serves (or the one it fixes).
- ``_done_gate`` (the last end step): a ``must`` item that failed stops the run as "blocked" with one card
  (``not_finished_ask``). Items nobody could check never stop it and never show a tick.

The checking itself is other stages' (finish, play, ship): they write results with ``donelist.record``.
"""

from __future__ import annotations

from typing import Any

from ..core.models import utcnow
from . import donelist
from .prep import PrepStage

ATTENTION = "not_finished"
ROUND_KEYS = ("finish_rounds", "done_rounds")  # the finish stages' round counters, cleared by "Try fixing again"


def _schema_item() -> dict[str, Any]:
    s = {"type": "string"}
    step = {"type": "object", "description": "one step, a single key from: " + ", ".join(donelist.JOURNEY_STEPS)
            + ' — e.g. {"open": "/"}, {"click": "Start"} (its visible text), {"type": "Ada", "into": "Name"}, '
              '{"press": "Enter"}, {"wait": 2}, {"expect_text": "Game over"}, {"expect_no_errors": true}'}
    return {
        "type": "object",
        "properties": {
            "text": {**s, "description": "one plain sentence a person can check, what they can do with the finished "
                                         "thing, e.g. 'You can start a game, lose and start again'"},
            "how": {"type": "string", "enum": list(donelist.HOWS),
                    "description": "how it can be shown: journey (steps in the app), page_opens, command (must "
                                   "succeed), file_exists, play (someone plays it), look (a person looks), owner "
                                   "(only the owner can say)"},
            "must": {"type": "boolean", "description": "false for a nice-to-have"},
            "steps": {"type": "array", "items": step, "description": "journey only"},
            "command": {**s, "description": "command only (empty: the project's own test command)"},
            "path": {**s, "description": "file_exists only: the file, e.g. dist/game.zip"},
            "part": {**s, "description": "optional: the part of the build it belongs to"},
            "serves": {"type": "array", "items": s, "description": "the ids of the tasks that make it work"},
        },
        "required": ["text", "how"],
    }


class DoneStage(PrepStage):
    # -- planning ------------------------------------------------------------------------------------------------------
    def _done_schema(self, schema: dict[str, Any]) -> None:
        schema.setdefault("properties", {})["done_list"] = {
            "type": "array", "items": _schema_item(),
            "description": "3 to 8 things a person can do with the finished thing: what 'done' means"}

    def _done_items_now(self) -> list[dict[str, Any]]:
        """The current goal's done list, when there is a plan for it already (a revision)."""
        doc = self.project.plan_doc() if self.project.exists else None
        goals = self.project.meta().get("goals") or [""]
        if not doc or int(doc.get("goal_index", -1)) != len(goals) - 1:
            return []
        return list(doc.get("done_list") or [])

    def _done_plan_part(self) -> str:
        out = ("\n\n# Done when\nIn done_list, give 3 to 8 short items: what a person can do with the finished thing, "
               "each one plain sentence they could check (\"You can start a game, lose and start again\"), with how it "
               "can be shown. Prefer journey (steps in the app, only these words: "
               + ", ".join(donelist.JOURNEY_STEPS) + "), page_opens, command or file_exists over look; owner only "
               "for what nobody but the owner can judge. Say in serves which tasks make each one work. Every task "
               "should serve at least one item.\n")
        now = self._done_items_now()
        if now:
            out += "The done list now (keep the owner's items word for word; change the rest only if the plan changed):\n"
            out += "".join(f"- [{i['id']}] {i['text']} ({i.get('how', 'look')}" + (", the owner's" if i.get("by") == "owner"
                                                                                  else "") + ")\n" for i in now)
        return out

    def _done_doc(self, doc: dict[str, Any], args: dict[str, Any]) -> None:
        root = self.project.root
        gi = int(doc.get("goal_index") or 0)
        old_doc = self.project.plan_doc() or {}
        same_goal = int(old_doc.get("goal_index", -1)) == gi if old_doc else False
        for k in ("done_removed", "done_accepted"):  # the owner's say on this goal's list survives a revision
            if same_goal and old_doc.get(k) and not doc.get(k):
                doc[k] = old_doc[k]
        data = donelist.read(root)
        old = data["items"] if data["goal_index"] == gi else []
        planner = [i for i in (donelist.clean_item(r) for r in args.get("done_list") or []) if i]
        if not planner:  # the planner gave none this time: keep its earlier ones
            planner = [donelist.clean_item(i) for i in (doc.get("done_list") or old) if i.get("by") == "planner"]
            planner = [i for i in planner if i]
        try:
            kind = donelist.from_kind(self._kind_proof()) if callable(getattr(self, "_kind_proof", None)) else []
        except Exception:  # noqa: BLE001 - a kind is a help
            kind = []
        items = donelist.merge(planner, kind, old, doc.get("done_removed"))
        if not items and not old:
            return  # nothing to say what done means: the project runs as before
        donelist.write_list(root, gi, items)
        doc["done_list"] = [donelist.public(i) for i in items]

    def _done_worker_part(self, task) -> str:
        items = donelist.read(self.project.root)["items"]
        if not items:
            return ""
        mine = donelist.for_task(items, task)
        fix = next((i for i in items if i["id"] == getattr(task, "fix_of", "")), None)
        out = ["# What finished means"]
        if fix is not None:
            out.append(f"This task fixes {fix['id']}: {fix['text']}"
                       + (f" The last check said: {fix['words']}" if fix.get("words") else ""))
        if mine and fix is None:
            out.append("Your work makes these work (check them before you finish):")
            out += [f"- [{i['id']}] {i['text']}" for i in mine]
        elif not mine:
            out.append("The finished thing must let a person:")
            out += [f"- [{i['id']}] {i['text']}" for i in items if i.get("must", True)][:8]
        return "\n".join(out)

    # -- the gate ------------------------------------------------------------------------------------------------------
    def _done_gate(self, tasks) -> str | None:
        root = self.project.root
        data = donelist.read(root)
        if not data["items"]:
            return None  # no done list: finished as before
        doc = self.project.plan_doc() or {}
        if doc and int(doc.get("goal_index") or 0) != data["goal_index"]:
            return None  # a list from another goal says nothing about this one
        v = donelist.verdict(root)
        meta = self.project.meta()
        if not v["failed"]:
            if ATTENTION in (meta.get("journal_todos") or {}):
                self._resolved(ATTENTION, note="everything on the done list that was checked works")
            meta = self.project.meta()
            if meta.pop("done_fix_rounds", None) is not None:
                self.project.save_meta(meta)
            return None
        failed = [i for i in data["items"] if i["id"] in v["failed"]]
        if meta.get("accepted_unfinished"):  # the owner said "Accept as it is": honoured once
            meta.pop("accepted_unfinished", None)
            meta.pop("done_fix_rounds", None)
            self.project.save_meta(meta)
            if doc:
                doc["done_accepted"] = {"at": utcnow(), "failed": [i["id"] for i in failed],
                                        "failed_text": [i["text"] for i in failed]}
                self.project.save_plan_doc(doc)
            self._resolved(ATTENTION, note="the owner accepted it as it is")
            self.emit("done_accepted", {"failed": [i["id"] for i in failed]})
            self._journal("note", "Finished as it is, as the owner chose: " + "; ".join(i["text"] for i in failed)[:300])
            return None
        self._set_status("blocked", pause="not_finished")
        n = len(failed)
        self._attention(ATTENTION, f"Not finished yet: {n} thing{'s' * (n != 1)} on the done list "
                                   f"{'don’t' if n != 1 else 'doesn’t'} work. Choose Try fixing again, or Accept as it is",
                        details="\n".join(f"[{i['id']}] {i['text']}: {i.get('words') or 'failed'}" for i in failed))
        self.emit("not_finished", {"failed": [i["id"] for i in failed]})
        return "blocked"

    def _done_report_note(self) -> str:
        """A line for the end report when the owner accepted it unfinished (``_finish`` adds it)."""
        acc = (self.project.plan_doc() or {}).get("done_accepted")
        if not acc:
            return ""
        return ("\n\n## Accepted as it is\nYou chose to finish with these not working yet:\n"
                + "".join(f"- {t}\n" for t in acc.get("failed_text") or acc.get("failed") or []))


# -- the card ("Not finished") ------------------------------------------------------------------------------------------
def fix_cost(orch, n: int) -> float | None:
    """About what n fix tasks cost: the plan's own price of a task, times n. None when it isn't known."""
    est = (orch.project.plan_doc() or {}).get("estimate") or {}
    tasks, cost = est.get("tasks") or 0, est.get("cost_usd")
    if not tasks or cost is None:
        return None
    return round(float(cost) / tasks * n, 2)


def not_finished_ask(orch, meta: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The card while the done gate has stopped the run, or None."""
    from ..asks import _ask, _money

    meta = meta if meta is not None else orch.project.meta()
    if meta.get("status") != "blocked" or meta.get("pause") != "not_finished":
        return None
    data = donelist.read(orch.project.root)
    failed = [i for i in data["items"] if i["id"] in donelist.verdict(orch.project.root)["failed"]]
    if not failed:
        return None
    cost = fix_cost(orch, len(failed))
    about = f" (about {_money(cost)})" if cost is not None else ""
    opts = [{"id": "fix", "label": f"Try fixing again{about}",
             "description": f"A task to fix each thing that doesn't work, then it's checked again{about}."},
            {"id": "accept", "label": "Accept as it is",
             "description": "Call it finished with these not working. The report says so.",
             "confirm": "Finish with these not working? The report will say they don't work yet."},
            {"id": "stop", "label": "Stop here", "description": "Nothing more is done or spent. You can decide later."}]
    n = len(failed)
    lines = "; ".join(f"{i['text']}" + (f" ({i['words'][:80]})" if i.get("words") else "") for i in failed[:4])
    return _ask(ATTENTION, "not_finished", "Not finished",
                f"Everything was built, but {n} thing{'s' * (n != 1)} on the done list {'don’t' if n != 1 else 'doesn’t'} work yet. What now?",
                opts, recommended="fix", detail=f"Doesn't work: {lines}",
                other_hint="Tell it what's wrong, then it tries fixing again",
                source={"failed": [i["id"] for i in failed], "fixes": int(meta.get("done_fix_rounds") or 0),
                        "cost": cost})


def _fix_role(orch, tasks) -> str:
    roles = orch.cfg.roles
    chat = [t.role for t in tasks if t.role in roles and getattr(roles[t.role], "kind", "chat") == "chat"
            and t.role not in (orch.cfg.planner_role, getattr(orch.cfg, "reviewer_role", ""))]
    if chat:
        return max(set(chat), key=chat.count)
    return next((r for r, spec in roles.items() if getattr(spec, "kind", "chat") == "chat"
                 and r != orch.cfg.planner_role), orch.cfg.planner_role)


def apply_not_finished(orch, ask: dict[str, Any], picked: list[str], other: str) -> dict[str, Any]:
    """The owner's answer (asks.APPLY["not_finished"])."""
    from ..asks import _dismiss
    from .orchestrator import HarnessError

    choice = picked[0] if picked else "fix"
    if choice == "stop":
        _dismiss(orch, ask)
        return {"reply": "Stopped. Nothing more is done until you say.", "then": None}
    meta = orch.project.meta()
    if choice == "accept":
        meta["accepted_unfinished"] = True
        orch.project.save_meta(meta)
        if other:
            orch.steer(other)
        return {"reply": "Accepted as it is. Finishing up; the report says what doesn't work.", "then": "run"}
    root = orch.project.root
    failed = [i for i in donelist.read(root)["items"] if i["id"] in (ask["source"].get("failed") or [])]
    tasks = orch.project.tasks()
    used = {t.id for t in tasks}
    role = _fix_role(orch, tasks)
    raw, n = [], 1
    for i in failed:
        while f"X{n}" in used:
            n += 1
        used.add(f"X{n}")
        raw.append({"id": f"X{n}", "title": f"Make it work: {i['text'][:60]}", "role": role, "depends_on": [],
                    "description": (f"The done list says: {i['text']}\nThe last check said: {i.get('words') or 'it failed'}\n"
                                    + (f"The owner says: {other}\n" if other else "")
                                    + "Find out why it doesn't work and fix it, without breaking what works."),
                    "acceptance": i["text"]})
    try:
        added = orch.add_tasks(raw, by="done", why="the done list: " + "; ".join(i["text"] for i in failed)[:200],
                               fix_of=failed[0]["id"] if len(failed) == 1 else "")
    except HarnessError as e:
        return {"reply": f"Couldn't add the fixes: {e}. Choose Accept as it is, or Stop.", "then": None}
    for t, i in zip(added, failed):  # each fix says which item it is for
        t.fix_of = i["id"]
    orch.project.save_tasks([next((a for a in added if a.id == t.id), t) for t in orch.project.tasks()])
    donelist.reopen(root, [i["id"] for i in failed], "being fixed")
    meta = orch.project.meta()
    for k in ROUND_KEYS:
        meta.pop(k, None)
    try:  # the finishing step's own round counter starts again too (finishstage.py)
        from . import finishstage

        finishstage.clear_rounds(root)
    except Exception:  # noqa: BLE001 - a help
        pass
    meta["done_fix_rounds"] = int(ask["source"].get("fixes") or 0) + 1
    orch.project.save_meta(meta)
    return {"reply": f"Trying again: {len(added)} fix{'es' * (len(added) != 1)} added.", "then": "run"}


def decide_not_finished(orch, ask: dict[str, Any], state: dict[str, Any]) -> tuple[list[str] | None, str]:
    """Autopilot: "Try fixing again" at most once, within its money; never "Accept as it is"."""
    if int(ask["source"].get("fixes") or 0) >= 1:
        return None, "autopilot already tried fixing it once; what next is up to you"
    cost = ask["source"].get("cost")
    if cost is None:
        return None, "the cost of fixing it isn't known, so it waits for you"
    left = float(state.get("spend_cap_usd") or 0) - float(state.get("spent_usd") or 0)
    if cost > left:
        return None, f"fixing it (about ${cost:.2f}) is more than what's left of autopilot's limit (${left:.2f})"
    if cost > orch.budget.limit_usd - orch.budget.spent_usd:
        return None, f"fixing it (about ${cost:.2f}) is more than this project's own limit allows"
    return ["fix"], f"fixing it (about ${cost:.2f}) fits what's left of autopilot's limit"
