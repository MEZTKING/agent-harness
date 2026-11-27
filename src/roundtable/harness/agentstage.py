"""Named agents in a run (wave 6): the hired agent of a task's job brings its notes and what it has learned.

- ``_agent_worker_part(task)``: the agent's name, the owner's notes for it and, where allowed, what it has
  learned on earlier work (at most 1,500 characters) go into the worker's prompt.
- ``_agent_attempt`` / ``_agent_metric``: ``agent: <id>`` on the attempt and the metrics row.
- ``_agent_learn(task, line)``: a lesson the task taught goes into the agent's own memory.

The privacy rule: a project with an allowed list (services or makers), or one of the owner's own
repositories, neither reads nor writes an agent's memory unless its setting ``agent_memory`` is ``on``
(``off`` stops it everywhere). The lab's replays never touch it. Notes always apply: they are the owner's
own words. At the dial's "lean" (a plan made before 1.2.0) the stage does nothing, so those runs are as before.

Agents live in the app's home folder (``agents.py``); ``agents_home`` on the orchestrator points elsewhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import agents as agentlib
from . import dial


class AgentStage:
    agents_home: str | Path | None = None

    def _agents_dir_home(self) -> Path:
        if self.agents_home:
            return Path(self.agents_home)
        from ..desktop import app_home

        return app_home()

    def _agent_for(self, task: Any) -> agentlib.Agent | None:
        """The hired agent for this task's job, or None (no agent, or the dial is at "lean")."""
        if dial.level(self) == "lean":
            return None
        try:
            return agentlib.hired_for(self._agents_dir_home(), agentlib.job_of(self.cfg, task.role))
        except (OSError, agentlib.AgentError):
            return None

    def _agent_memory_ok(self) -> bool:
        """May this project read and write an agent's memory? (the privacy rule above)"""
        if not getattr(self, "mcp_allowed", True):  # a lab replay
            return False
        try:
            values = self.project_settings().values
        except Exception:  # noqa: BLE001 - settings with a mistake: keep the memory out
            return False
        choice = str(values.get("agent_memory") or "").strip().lower()
        if choice == "on":
            return True
        if choice == "off":
            return False
        if values.get("providers_allowed") or values.get("makers_allowed"):
            return False
        repo = getattr(self, "_repo_mode", None)
        try:
            if callable(repo) and repo():
                return False
        except Exception:  # noqa: BLE001
            return False
        return True

    def _agent_worker_part(self, task: Any) -> str:
        a = self._agent_for(task)
        if not a:
            return ""
        lines = [f"# Who you are\nYou are {a.name}, this project's {a.job_name.lower()}."
                 + (f" {a.about}" if a.about else "")]
        if a.notes:
            lines.append("The owner's notes for you (follow them unless the task or the project's rules say "
                         "otherwise):\n" + a.notes)
        if self._agent_memory_ok():
            got = agentlib.learned(self._agents_dir_home(), a.id)
            if got:
                lines.append("What you learned on earlier work (other projects; this task and this project's "
                             "rules win):\n" + got)
        return "\n\n".join(lines)

    def _agent_attempt(self, task: Any, ref: Any) -> dict[str, Any] | None:
        a = self._agent_for(task)
        return {"agent": a.id} if a else None

    def _agent_metric(self, task: Any, ref: Any) -> dict[str, Any] | None:
        return self._agent_attempt(task, ref)

    def _agent_learn(self, task: Any, line: str) -> None:
        """A lesson the task taught goes into its agent's memory, when the project allows it."""
        a = self._agent_for(task)
        if not a or not str(line or "").strip() or not self._agent_memory_ok():
            return
        if agentlib.learn(self._agents_dir_home(), a.id, line):
            self.emit("agent_learned", {"task": task.id, "agent": a.id, "text": str(line)[:300]})
