"""The plan's stages and parts (harness/stages.py).

    GET /api/stages  ?path=<project> -> {stages: [{id, title, shows, done, total, state, tasks, ready_at}],
                                         parts: [{id, name, folder, kind?}], words, warnings, strayed, files}

``state`` is done, now (being built), stuck (being built, something failed) or waiting. ``words`` is the one plain
sentence of where it stands. Read only.
"""

from __future__ import annotations

from typing import Any

from ..harness import stages as stagelib


def routes(app) -> dict[tuple[str, str], Any]:
    return {("GET", "/api/stages"): lambda q: one(app, q)}


def one(app, q) -> dict[str, Any]:
    path = str((q.get("path") or [""])[0] or "")
    root = app.project(app.need_cfg(), path).root
    return stagelib.view(root)
