"""Show it, the Orchestrator's side: pictures after each approved task, and the hub's live files.

A mixin, like the Look stage. After every task: pictures when the task was approved and the project
has screens, then ``plans/shots/<project>/`` in the hub (the latest pictures, one per finished task,
and ``session.json`` with the latest task's steps as short lines for the phone).
"""

from __future__ import annotations

import json
from typing import Any

from . import godot as godotlib
from . import session as sessionlib
from . import showit


class ShowStage:
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
        record = self._show_it(task) if ok else None
        self._publish_live(record)

    def _learn_from_task(self, task) -> None:
        """What the task taught (a fix after a rejection, why it failed) goes in the project's memory."""
        try:
            from .. import memory

            line = memory.learn_from_task(self.project.root, task, self.cfg)
            if line:
                self.emit("remembered", {"task": task.id, "text": line[:300]})
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
