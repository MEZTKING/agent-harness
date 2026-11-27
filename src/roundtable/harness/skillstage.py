"""Skills, the Orchestrator's side (wave 7, d4-tools): a builder gets the know-how that fits its task.

A mixin. ``_skills_worker_part(task)`` adds at most two switched-on skills whose tags meet the task's tags
(``tasktags.for_task``: the planner's work words, the files' languages, ``kind:<id>``), within 3,000 characters
(``skills.pick``). ``_skills_attempt(task, ref)`` records ``skills: [ids]`` on the attempt, so the lab can later
tell whether a skill helps. Settings (``skills:`` in harness.yaml): ``enabled`` (true), ``most`` (2),
``chars`` (3000). Free: no model call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import skills as skilllib
from .config import section
from .tasktags import for_task


class SkillStage:
    def _skills_settings(self) -> dict[str, Any]:
        s = section(getattr(self, "cfg", None), "skills")
        try:
            most = max(0, min(int(s.get("most", skilllib.PICK_MOST)), 4))
        except (TypeError, ValueError):
            most = skilllib.PICK_MOST
        try:
            chars = max(0, min(int(s.get("chars", skilllib.PICK_CHARS)), 8000))
        except (TypeError, ValueError):
            chars = skilllib.PICK_CHARS
        return {"enabled": s.get("enabled", True) is not False, "most": most, "chars": chars}

    def _skills_home(self) -> Path:
        from ..desktop import app_home

        return app_home()

    def _skills_for(self, task: Any) -> list[skilllib.Skill]:
        s = self._skills_settings()
        if not s["enabled"] or not s["most"]:
            return []
        cache = self.__dict__.setdefault("_skills_chosen", {})
        tid = str(getattr(task, "id", "") or id(task))
        if tid not in cache:
            cache[tid] = skilllib.pick(for_task(self, task), home=self._skills_home(), most=s["most"],
                                       chars=s["chars"])
        return cache[tid]

    def _skills_worker_part(self, task: Any) -> str:
        return skilllib.block(self._skills_for(task))

    def _skills_attempt(self, task: Any, ref: Any) -> dict[str, Any] | None:
        chosen = self._skills_for(task)
        return {"skills": [s.id for s in chosen]} if chosen else None
