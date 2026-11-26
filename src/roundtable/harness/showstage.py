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

    def _game_tool(self):
        """``run_game`` when the project is a Godot game and Godot is on this computer, else None."""
        return godotlib.game_tool(self.project.root, self.cfg.godot)

    def _after_task(self, task, ok: bool) -> None:
        record = self._show_it(task) if ok else None
        self._publish_live(record)

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
