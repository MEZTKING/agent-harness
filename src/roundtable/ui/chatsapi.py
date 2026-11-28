"""The chat (chat.py, chatstore.py) as an API, for the desktop's chat.js and the phone's ApiBrain (1.5.0).

Frozen in Step 0; chat-server fills them in. ``chat`` is ``"hall"`` or a project's chat id (chatstore.chat_id).

    GET  /api/chats                          {chats: [{id, name, last, unread, waiting}]}
    GET  /api/chats/read?chat=&since=        {lines, at, answering: {text, thinking, at, done} | null,
                                              can: {answer: bool, why: "" | a chat.CANNOT code}}
    POST /api/chats/say   {chat, text, key?} -> {line, turn}   (key: the composer draft whose files go with it;
                                              turn: the id the answer's line will have, and its stream
                                              ``chat-<turn>``, read through ``answering``)
    POST /api/chats/tap   {chat, card, button?, confirmed?} -> {line}   (the phone too: a PC-only command is
                                              refused, as POST /api/commands does)
    POST /api/chats/tap/pc   the same with every command, for the PC's own app (never offered to the phone)
    POST /api/chats/stop  {chat, turn}       -> {stopped: bool}
    GET  /api/chats/file?chat=&name=         {name, type, data: "data:<type>;base64,…"}

``button`` is one of chatstore.BUTTONS (default ``"do"``). No answer ever carries a key (``session.redact``).
"""

from __future__ import annotations

from typing import Any

from .. import chat as chatmod
from .. import chatstore


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/chats"): lambda q: {"chats": chatstore.chats(app)},
        ("GET", "/api/chats/read"): lambda q: read(app, q or {}),
        ("POST", "/api/chats/say"): lambda b: say(app, b or {}),
        ("POST", "/api/chats/tap"): lambda b: tap(app, b or {}, pc=False),
        ("POST", "/api/chats/tap/pc"): lambda b: tap(app, b or {}, pc=True),
        ("POST", "/api/chats/stop"): lambda b: stop(app, b or {}),
        ("GET", "/api/chats/file"): lambda q: file(app, q or {}),
    }


def _first(q: dict, key: str, default: str = "") -> str:
    v = (q or {}).get(key, default)
    if isinstance(v, list):
        v = v[0] if v else default
    return str(v if v is not None else default)


def _chat(value: Any) -> str:
    chat = str(value or "")
    if not chatstore.is_chat(chat):
        from .server import ApiError

        raise ApiError("Choose a chat first.")
    return chat


# -- stubs (chat-server fills these in) --------------------------------------------------------------------------
def read(app, q: dict) -> dict[str, Any]:
    chat = _chat(_first(q, "chat"))
    got = chatstore.read(getattr(app, "home", None), getattr(app, "hub", None), chat, _first(q, "since"))
    return {"lines": got["lines"], "at": got["at"], "answering": None, "can": {"answer": False, "why": "off"}}


def say(app, b: dict) -> dict[str, Any]:
    _chat(b.get("chat"))
    line = chatmod.cannot("off")
    return {"line": line, "turn": ""}


def tap(app, b: dict, pc: bool) -> dict[str, Any]:
    chat = _chat(b.get("chat"))
    return {"line": chatmod.tap(app, chat, str(b.get("card") or ""), bool(b.get("confirmed")),
                                str(b.get("button") or "do"), pc=pc)}


def stop(app, b: dict) -> dict[str, Any]:
    _chat(b.get("chat"))
    return {"stopped": False}


def file(app, q: dict) -> dict[str, Any]:
    from .server import ApiError

    _chat(_first(q, "chat"))
    raise ApiError("That file isn't here.", 404)
