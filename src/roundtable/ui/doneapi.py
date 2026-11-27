"""The done list: what a person can do with the finished thing, and whether each was shown to work.

    GET /api/done            ?path=<project>
                             -> {items, checked, passed, failed, unchecked, must_failed, words, rounds, finished}
    GET /api/done/evidence   ?path=<project>&item=<id>
                             -> {found, item, text, state, words, texts, pictures: [{name, data}]}

Read only: the owner's edits go through the plan's own actions (plan_update "done_add" / "done_remove"). The
pictures are small inline data addresses, so the page and the phone need no file route.
"""

from __future__ import annotations

import re
from typing import Any

from ..harness import donelist

_ITEM = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,30}")


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/done"): lambda q: listing(app, q),
        ("GET", "/api/done/evidence"): lambda q: evidence(app, q),
    }


def _arg(q, name: str) -> str:
    return str((q.get(name) or [""])[0] or "")


def _project(app, q):
    return app.project(app.need_cfg(), _arg(q, "path"))


def listing(app, q) -> dict[str, Any]:
    proj = _project(app, q)
    finished = (proj.meta() if proj.exists else {}).get("status") == "done"
    return {**donelist.summary(proj.root, finished=finished), "finished": finished,
            "marks": donelist.MARK, "mark_words": donelist.MARK_WORDS}


def evidence(app, q) -> dict[str, Any]:
    from .server import ApiError

    item = _arg(q, "item")
    if not _ITEM.fullmatch(item):
        raise ApiError("say which item: item=<its id, such as D2>")
    got = donelist.evidence(_project(app, q).root, item)
    if got is None:
        return {"found": False, "item": item, "words": "There's no such item on the done list."}
    return {"found": True, **got}
