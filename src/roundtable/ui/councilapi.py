"""The planning council's record on a plan (harness/council.py).

    GET /api/tandem/council  ?path=<project> -> {found, words, planners: [{label, model, maker, tasks, summary, votes}],
                                                 disagreements: [{topic, options: [{who, says}], chosen, why}],
                                                 chair, merged, best, stopped, cost_usd, at}

``found`` is false for a plan made by one planner. ``words`` is the one plain line. Read only.
"""

from __future__ import annotations

from typing import Any

from ..harness import council


def routes(app) -> dict[tuple[str, str], Any]:
    return {("GET", "/api/tandem/council"): lambda q: one(app, q)}


def one(app, q) -> dict[str, Any]:
    path = str((q.get("path") or [""])[0] or "")
    proj = app.project(app.need_cfg(), path)
    return council.view(proj.plan_doc() if proj.exists else None)
