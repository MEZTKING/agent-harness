"""Proof for a task: the app before and after it, the tests, and what a model that can see said (proof.py).

    GET /api/proof       ?path=<project>&task=<id>[&inline=1]
                         -> {found, task, words, before, after, pairs, tests, judge, lines, lines_text, ok,
                             images: {before: {kind: data address}, after: {...}} (with inline=1)}
    GET /api/proof/list  ?path=<project> -> {items: [{task, at, words, verdict, tests, changed, lines}]}, newest first

Read only. The pictures are sent as data addresses (small jpgs), so the page and the phone need no file route.
"""

from __future__ import annotations

import re
from typing import Any

from ..harness import proof as prooflib

_TASK = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,80}")


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/proof"): lambda q: one(app, q),
        ("GET", "/api/proof/list"): lambda q: listing(app, q),
    }


def _arg(q, name: str) -> str:
    return str((q.get(name) or [""])[0] or "")


def _root(app, q):
    return app.project(app.need_cfg(), _arg(q, "path")).root


def one(app, q) -> dict[str, Any]:
    from .server import ApiError

    task = _arg(q, "task")
    if not _TASK.fullmatch(task):
        raise ApiError("say which task: task=<its id, such as T3>")
    root = _root(app, q)
    rec = prooflib.read(root, task)
    if not rec:
        return {"found": False, "task": task, "words": "No proof for this task yet: it shows once the task is finished."}
    out = {"found": True, **rec, "lines_text": prooflib.lines_text(rec.get("lines") or [])}
    if _arg(q, "inline") == "1":
        out["images"] = prooflib.inline_pictures(root, rec)
    return out


def listing(app, q) -> dict[str, Any]:
    root = _root(app, q)
    return {"items": [prooflib.summary(r) for r in prooflib.history(root)]}
