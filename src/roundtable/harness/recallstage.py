"""The agents look things up instead of guessing (wave 7, MD-56, MD-60): ``RecallStage``.

A mixin like ``refstage.py``. Its hooks:

* ``_recall_tools(role)`` (TOOL_PARTS): ``look_up(query)`` for every chat role – the planner, the builders and
  the reviewer. Up to ``recall.LOOKUP_PIECES`` pieces and ``recall.LOOKUP_CHARS`` characters, each with its
  source, only from this project's own memory, plan and tasks, this computer's and the agents' memories, and the
  documents this project may use (its ``documents`` setting; never one ticked "Never leaves this computer").
  No tool when there is nothing to look up (memory off or empty, and no documents), so such a run's requests
  are exactly as before.
* ``_docs_plan_part()`` (PLAN_PARTS): one line naming the documents the planner may look up, and to use
  look_up before guessing a fact. "" when there are none.
* ``_recall_attempt(task, ref)`` (ATTEMPT_PARTS): ``{"looked_up": n}`` when the attempt looked anything up (and
  the ids go to ``.harness/recall.jsonl`` for the memory picture); None otherwise.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .. import documents as docs
from .. import memory
from .. import recall
from ..providers.base import ToolSpec
from .tools import Tool


class RecallStage:
    def _recall_home(self) -> Path:
        home = getattr(self, "recall_home", None) or getattr(self, "agents_home", None)
        if home:
            return Path(home)
        from ..desktop import app_home

        return app_home()

    def _recall_documents_setting(self) -> str:
        try:
            values = self.project_settings().values
        except Exception:  # noqa: BLE001 - settings with a mistake: no documents
            return "none"
        v = str((values or {}).get("documents") or "all").lower()
        return v if v in ("all", "none") else "all"

    def _recall_documents(self) -> list[dict[str, Any]]:
        try:
            return docs.for_models(self._recall_home(), recall.pid_of(self.project.root),
                                   self._recall_documents_setting())
        except Exception:  # noqa: BLE001
            return []

    def _recall_memory_on(self) -> bool:
        try:
            return bool(memory.settings(self.cfg)["enabled"])
        except Exception:  # noqa: BLE001
            return False

    def _recall_anything(self) -> bool:
        """Is there anything to look up? Memory on with a memory file, or a document this project may use."""
        if self._recall_documents():
            return True
        if not self._recall_memory_on():
            return False
        files = [memory.project_path(self.project.root)]
        if memory.settings(self.cfg).get("machine"):
            files.append(memory.machine_path(self._recall_home()))
        return any(f.is_file() and f.stat().st_size for f in files)

    # -- the tool --------------------------------------------------------------------------------------------
    def _recall_tools(self, role: Any) -> list[Tool]:
        if getattr(role, "kind", "chat") != "chat" or not recall.settings(self.cfg)["enabled"]:
            return []
        if not self._recall_anything():
            return []
        # the attempt's own thread and role: its row counts what this box looked up
        owner = (threading.get_ident(), getattr(role, "name", ""))
        root, home = self.project.root, self._recall_home()
        setting = self._recall_documents_setting()
        kinds = None if self._recall_memory_on() else {"document", "decision", "answer", "task", "plan"}

        def look_up(args: dict[str, Any]) -> str:
            q = str(args.get("query") or "").strip()[:300]
            if not q:
                return "Say what to look up."
            pieces = recall.for_project(root, q, home, setting)
            if kinds is not None:
                pieces = [p for p in pieces if p.kind in kinds]
            with self._recall_lock():
                self._recall_found().setdefault(owner, []).extend(pieces)
            self.emit("looked_up", {"query": q, "n": len(pieces), "role": getattr(role, "name", "")})
            return recall.lookup_text(pieces)

        return [Tool(ToolSpec(
            "look_up",
            "Look up what the owner and earlier work already settled: this project's memory, its decisions and "
            "finished tasks, this computer's memory and the owner's documents. Use it before guessing a fact. "
            "Gives up to five pieces with their sources.",
            {"type": "object", "properties": {"query": {"type": "string", "description": "what to look up, in words"}},
             "required": ["query"]}), look_up)]

    def _recall_lock(self) -> threading.Lock:
        lock = self.__dict__.get("_recall_lock_obj")
        if lock is None:
            lock = self.__dict__.setdefault("_recall_lock_obj", threading.Lock())
        return lock

    def _recall_found(self) -> dict[tuple[int, str], list[recall.Piece]]:
        return self.__dict__.setdefault("_recall_found_by", {})

    # -- the planner's line and the attempt's count --------------------------------------------------------------
    def _docs_plan_part(self) -> str:
        if not recall.settings(self.cfg)["enabled"]:
            return ""
        found = self._recall_documents()
        if not found:
            return ""
        titles = ", ".join(d["title"] for d in found[:12]) + (f" and {len(found) - 12} more" if len(found) > 12 else "")
        return (f"\n\n# The owner's documents\nYou can look these up with look_up: {titles}. "
                "Use look_up before guessing a fact.\n")

    def _recall_attempt(self, task: Any, ref: Any) -> dict[str, Any] | None:
        with self._recall_lock():
            me = threading.get_ident()
            roles = {getattr(task, "role", ""), getattr(self.cfg, "reviewer_role", "")}
            pieces = [p for key in [k for k in self._recall_found() if k[0] == me and k[1] in roles]
                      for p in self._recall_found().pop(key)]
        if not pieces:
            return None
        recall.note_lookup(self.project.root, getattr(task, "id", ""), pieces)
        return {"looked_up": len(pieces)}


__all__ = ["RecallStage"]
