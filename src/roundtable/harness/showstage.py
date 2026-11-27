"""Show it, the Orchestrator's side: pictures after each approved task, and the hub's live files.

A mixin, like the Look stage. After every task: pictures when the task was approved and the project
has screens, then ``plans/shots/<project>/`` in the hub (the latest pictures, one per finished task,
and ``session.json`` with the latest task's steps as short lines for the phone).
"""

from __future__ import annotations

import json
from typing import Any

import threading

from . import godot as godotlib
from . import proof as prooflib
from . import session as sessionlib
from . import showit


class ProofStage:
    """Before and after for every task (proof.py): pictures when the task starts, pictures and the
    tests when it is reviewed (with a model that can see as advice for the reviewer), and
    ``proof.json`` when it is finished.

    Hook-up: ``_proof_before(task)`` before a task runs, ``_proof_text(task, checks)`` in the review
    prompt; ``_proof_after`` is called by ``_after_task``. Every step is a help, never a reason to fail."""

    def _proof_box(self) -> dict[str, Any]:
        box = self.__dict__.get("_proof_state")
        if box is None:
            box = self.__dict__.setdefault("_proof_state", {"lock": threading.Lock(), "tasks": {}})
        return box

    def _proof_entry(self, task_id: str) -> dict[str, Any]:
        box = self._proof_box()
        with box["lock"]:
            return box["tasks"].setdefault(task_id, {"spent": 0.0})

    def _proof_on(self) -> bool:
        return prooflib.Settings.from_config(self.cfg).enabled

    def _proof_plan(self) -> list[dict[str, Any]]:
        """The kind's proof list as a plan (kinds, KindStage._kind_proof), when there is one."""
        get = getattr(self, "_kind_proof", None)
        if not callable(get):
            return []
        try:
            return prooflib.plan_for(get() or [])
        except Exception:  # a kind is a help here too
            return []

    def _proof_root(self):
        return self._work_root() if hasattr(self, "_work_root") else self.project.root

    def _proof_before(self, task) -> dict[str, Any] | None:
        """The pictures of the project as this task finds it (reused by commit when there are some)."""
        try:
            if not self._proof_on() or not self._shots_wanted():
                return None
            rec = prooflib.before(self.project.root, task, work_root=self._proof_root(),
                                  render=getattr(self, "shot_renderer", None), godot=self.cfg.godot)
            self._proof_entry(task.id)["before"] = rec
            self.emit("proof_before", {"task": task.id, "commit": rec.get("commit", ""), "reused": bool(rec.get("reused")),
                                       "pictures": list(rec.get("pictures") or {})})
            return rec
        except Exception as e:
            self.emit("proof_error", {"task": getattr(task, "id", ""), "error": str(e)[:300]})
            return None

    def _proof_text(self, task, checks: dict[str, Any] | None = None) -> str:
        """For the review prompt: the pictures after the work (taken now, of the task's own folder), what
        changed, the tests, and the judge's advice. "" when there is nothing to show."""
        try:
            entry = self._proof_entry(task.id)
            if checks is not None:
                entry["checks"] = checks
            if not self._proof_on():
                return ""
            s = prooflib.Settings.from_config(self.cfg)
            after = None
            if self._shots_wanted():
                after = showit.take_shots(self._proof_root(), task.id, render=getattr(self, "shot_renderer", None),
                                          godot=self.cfg.godot, out_dir=showit.shots_root(self.project.root)
                                          / showit._safe_task(task.id), latest=False)
            before = entry.get("before")
            prs = prooflib.pairs(self.project.root, before, after)
            tests = prooflib.tests_part(self._proof_baseline(), entry.get("checks"))
            judged = prooflib.judge(self.cfg, task, prs, tests, self.budget, project_root=self.project.root,
                                    before_rec=before, after_rec=after, spent=entry["spent"], settings=s)
            entry["spent"] += float(judged.get("cost_usd") or 0.0)
            entry.update(after=after, pairs=prs, tests=tests, judge=judged)
            if not prs and not tests:
                return ""
            rec = prooflib.build(self.project.root, task, before, after, tests, judged, prs, self._proof_plan())
            prooflib.write(self.project.root, rec)  # ok: None until the review is done
            self.emit("proof", {"task": task.id, "words": rec["words"], "verdict": judged.get("verdict"),
                                "cost_usd": judged.get("cost_usd", 0.0)})
            return prooflib.review_text(rec, strict=s.strict)
        except Exception as e:
            self.emit("proof_error", {"task": getattr(task, "id", ""), "error": str(e)[:300]})
            return ""

    def _proof_baseline(self) -> dict[str, Any] | None:
        get = getattr(self, "_checks_baseline", None)
        try:
            return get() if callable(get) else self.project.meta().get("baseline")
        except Exception:
            return None

    def _proof_shots(self, task) -> dict[str, Any] | None:
        """The pictures the review saw, as the task's pictures now it is approved (no second render)."""
        entry = self._proof_box()["tasks"].get(task.id) or {}
        after = entry.get("after")
        if not after or not after.get("pictures"):
            return None
        rec = {**after, "commit": showit.commit_of(self.project.root)}
        showit._write_record(showit.shots_root(self.project.root) / str(after.get("dir") or task.id), rec)
        self.emit("shots", {"task": task.id, "dir": rec.get("dir", ""), "pictures": list(rec.get("pictures") or {}),
                            "errors": len(rec.get("errors") or []), "title": rec.get("title", ""),
                            "note": rec.get("failed") or rec.get("note", "")})
        return rec

    def _proof_after(self, task, ok: bool, checks: dict[str, Any] | None = None,
                     shots: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """``proof.json`` for the finished task, and its pictures kept by commit for the next tasks."""
        try:
            box = self._proof_box()
            with box["lock"]:
                entry = box["tasks"].pop(task.id, None) or {}
            if not self._proof_on():
                return None
            after = shots if shots is not None else entry.get("after")
            if shots is not None and shots.get("commit"):
                prooflib.keep_by_commit(self.project.root, shots)
            before = entry.get("before")
            tests = entry.get("tests")
            if checks is not None or tests is None:
                tests = prooflib.tests_part(self._proof_baseline(), checks or entry.get("checks"))
            prs = prooflib.pairs(self.project.root, before, after) if shots is not None else entry.get("pairs") or []
            judged = entry.get("judge") or ({"looked": False, "why": "not_asked", "words": prooflib.NOBODY}
                                            if prs else None)
            if not prs and not tests:
                return None  # nothing to show for this task
            rec = prooflib.build(self.project.root, task, before, after, tests, judged, prs, self._proof_plan(), ok=ok)
            prooflib.write(self.project.root, rec)
            return rec
        except Exception as e:
            self.emit("proof_error", {"task": getattr(task, "id", ""), "error": str(e)[:300]})
            return None


class ShowStage(ProofStage):
    def _hub_name(self) -> str:
        """The project's name in the hub: its own hub project, or <harness agent>--<folder>."""
        agent = self._hub_agent()
        return agent if agent == self.project.root.name else f"{agent}--{self.project.root.name}"

    def _shots_wanted(self) -> bool:
        if self.cfg.show_it == "off":
            return False
        has_ui = bool((self.project.plan_doc() or {}).get("has_ui"))
        if has_ui or showit.entry_page(self.project.root) is not None:
            return True
        return self.cfg.godot.enabled and godotlib.project_dir(self.project.root) is not None

    def _show_it(self, task) -> dict[str, Any] | None:
        """Pictures of the app after an approved task (never fails the task)."""
        if not self._shots_wanted():
            return None
        try:
            record = showit.take_shots(self.project.root, task.id, render=getattr(self, "shot_renderer", None),
                                         godot=self.cfg.godot)
        except Exception as e:  # take_shots writes its problems down; this is for the unexpected
            record = {"task": task.id, "pictures": {}, "errors": [], "failed": str(e)[:300]}
        self.emit("shots", {"task": task.id, "dir": record.get("dir", ""), "pictures": list(record.get("pictures") or {}),
                            "errors": len(record.get("errors") or []), "title": record.get("title", ""),
                            "note": record.get("failed") or record.get("note", "")})
        return record

    def show_it_now(self) -> dict[str, Any]:
        """Pictures of the app as it is now, after the newest finished task, and the hub's live files (the
        owner's "Take pictures now" for a project built before Roundtable took pictures)."""
        done = [t for t in self.project.tasks() if t.status == "done"]
        if not done:
            return {"ok": False, "reply": "Couldn't take pictures: no task has finished yet."}
        if not self._shots_wanted():
            return {"ok": False, "reply": "Couldn't take pictures: this project has no screens to show."}
        record = self._show_it(done[-1])
        self._publish_live(record)
        n = len((record or {}).get("pictures") or {})
        if not n:
            why = (record or {}).get("failed") or (record or {}).get("note") or "the app didn't open"
            return {"ok": False, "reply": f"Couldn't take pictures: {why}.", "record": record}
        return {"ok": True, "reply": f"Took {n} picture{'s' * (n > 1)} of the app. They're on the Live tab.",
                "record": record}

    def _game_tool(self):
        """``run_game`` when the project is a Godot game and Godot is on this computer, else None."""
        root = self._work_root() if hasattr(self, "_work_root") else self.project.root  # the task's own copy
        return godotlib.game_tool(root, self.cfg.godot)

    def _after_task(self, task, ok: bool) -> None:
        self._learn_from_task(task)
        record = None
        if ok:  # the pictures the review already saw, else fresh ones
            record = self._proof_shots(task) if self._shots_wanted() else None
            record = record or self._show_it(task)
        self._proof_after(task, ok, shots=record)
        self._publish_live(record)

    def _learn_from_task(self, task) -> None:
        """What the task taught (a fix after a rejection, why it failed) goes in the project's memory."""
        try:
            from .. import memory

            line = memory.learn_from_task(self.project.root, task, self.cfg)
            if line:
                self.emit("remembered", {"task": task.id, "text": line[:300]})
                self._hook("_agent_learn", task, line)  # the hired agent keeps it too, where allowed (agentstage.py)
        except Exception as e:  # memory is a help; never fail a run over it
            self.emit("memory_error", {"error": str(e)[:300]})

    def _publish_live(self, record: dict[str, Any] | None) -> None:
        """The hub's live files for the phone: session.json always, the pictures when there are new ones."""
        try:
            hub = self._hub()
            if not hub:
                return
            from ..core.store import TextFile

            name = self._hub_name()
            base = f"plans/shots/{name}"
            summary = sessionlib.hub_session(self.project.root, name, self.cfg.reviewer_role)
            files: dict[str, Any] = {f"{base}/session.json": TextFile(json.dumps(summary, indent=1, ensure_ascii=False) + "\n")}
            if record and record.get("pictures"):
                files.update(showit.hub_files(self.project.root, record, hub.store.read_json(f"{base}/latest.json"), base))
            hub.store.write_json(files, f"shots({name}): {(summary.get('task') or {}).get('id', '')}")
        except Exception as e:  # the hub is optional; never fail a run over it
            self.emit("hub_error", {"error": f"live view: {e}"})
