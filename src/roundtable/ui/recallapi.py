"""Search by meaning, asking, the owner's documents and the memory picture (recall.py, documents.py).

    GET  /api/recall?q=words[&limit=12]
                                {query, pieces: [{kind, kind_words, title, text, where, at, open, private}], name, words}
    POST /api/recall/ask        {question, confirm?: bool}: without confirm the price first, nothing sent;
                                with it {answer, quotes: [{text, source, title, open}], pieces, held, price_usd,
                                cost_usd, model, model_label, words}
    GET  /api/documents         {documents: [view], projects: [{id, name}], removed: n, words}
    POST /api/documents         {action: "add", name, data (base64), projects?, private?, title?}
                                {action: "link", folder, projects?, private?, title?}
                                {action: "change", id, projects?, private?, title?}
                                {action: "remove", id}            (moved aside, never deleted)
                                -> {document, ...the list}
    GET  /api/recall/graph      {nodes, edges, sentence, lines}

Only projects registered on this computer are read. ``ask`` is the owner's own tap: its price is shown first,
the spend goes into the usage ledger as "(search)", and a piece reaches the model only if its project allows the
model's maker; a "Never leaves this computer" document reaches none.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import documents as docs
from .. import recall


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/recall"): lambda q: find(app, q),
        ("POST", "/api/recall/ask"): lambda body: ask(app, body),
        ("GET", "/api/documents"): lambda q: documents_get(app),
        ("POST", "/api/documents"): lambda body: documents_post(app, body),
        ("GET", "/api/recall/graph"): lambda q: graph(app),
    }


def _first(q: dict, key: str, default: str = "") -> str:
    v = q.get(key)
    if v is None:
        return default
    return str(v[0] if isinstance(v, list) else v)


def _home(app) -> Path:
    from ..desktop import app_home

    return app_home()


def _names(app) -> dict[str, str]:
    from .searchapi import _names as names

    try:
        return names(app)
    except Exception:  # noqa: BLE001
        return {}


def _projects(app) -> list[Path]:
    return app._lab_projects()


def _project_names(app) -> dict[str, str]:
    from ..search import project_name

    return {recall.pid_of(p): project_name(p) for p in _projects(app)}


def find(app, q) -> dict[str, Any]:
    from .server import ApiError

    words = _first(q, "q").strip()
    if len(words) > 300:
        raise ApiError("That's a lot of words to look for. Try a few.")
    try:
        limit = min(50, max(1, int(_first(q, "limit", "12"))))
    except ValueError:
        limit = 12
    with app.hub_lock:
        return recall.find(words, _projects(app), _home(app), app.hub, app.agent, _names(app), limit)


def ask(app, body) -> dict[str, Any]:
    from ..harness import usage
    from ..routing import model_label
    from .server import ApiError

    question = str(body.get("question") or "").strip()
    if not question:
        raise ApiError("Write your question first.")
    if len(question) > 500:
        raise ApiError("That question is long. Ask it in a sentence or two.")
    cfg = app.need_cfg()
    home = _home(app)

    def on_use(ref, use, cost, role):
        try:
            usage.record(usage.row_for(ref, use, cost, "(search)", home), home)
        except OSError:
            pass

    with app.hub_lock:
        out = recall.ask(cfg, question, _projects(app), home, app.hub, app.agent, _names(app),
                         confirm=bool(body.get("confirm")), on_use=on_use)
    out["model_label"] = model_label(out["model"]) if out.get("model") else ""
    return out


def _list(app) -> dict[str, Any]:
    home = _home(app)
    names = _project_names(app)
    items = [docs.view(home, d, names) for d in docs.all_documents(home)]
    return {"documents": items, "projects": [{"id": k, "name": v} for k, v in names.items()],
            "removed": len(docs.removed(home)),
            "words": (f"{len(items)} document{'s' if len(items) != 1 else ''} your agents can look up."
                      if items else "No documents yet. Drop files here, or link a folder.")}


def documents_get(app) -> dict[str, Any]:
    return _list(app)


def documents_post(app, body) -> dict[str, Any]:
    from .server import ApiError

    home = _home(app)
    action = str(body.get("action") or "")
    kw = {k: body[k] for k in ("projects", "private", "title") if k in body}
    try:
        if action == "add":
            d = docs.add_upload(home, str(body.get("name") or ""), str(body.get("data") or ""), **kw)
        elif action == "link":
            d = docs.link_folder(home, str(body.get("folder") or ""), **kw)
        elif action == "change":
            d = docs.change(home, str(body.get("id") or ""), **kw)
        elif action == "remove":
            d = docs.remove(home, str(body.get("id") or ""))
        else:
            raise ApiError("Choose add, link, change or remove.")
    except docs.DocumentError as e:
        raise ApiError(str(e)) from None
    except OSError:
        raise ApiError("Couldn't save it: the documents folder couldn't be written. Try again.") from None
    return {"document": d, **_list(app)}


def graph(app) -> dict[str, Any]:
    with app.hub_lock:
        return recall.graph(_projects(app), _home(app), app.hub, _names(app))
