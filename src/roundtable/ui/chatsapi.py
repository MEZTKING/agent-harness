"""The chat (chat.py, chatstore.py) as an API, for the desktop's chat.js and the phone's ApiBrain (1.5.0).

Frozen in Step 0; chat-server fills them in. ``chat`` is ``"hall"`` or a project's chat id (chatstore.chat_id).

    GET  /api/chats                          {chats: [{id, name, last, unread, waiting}]}
    GET  /api/chats/read?chat=&since=        {lines, at, answering: {text, thinking, at, done, turn} | null,
                                              can: {answer: bool, why: "" | a chat.CANNOT code}, seat,
                                              earlier?: [lines, each with earlier: true] (only when since is empty)}
    POST /api/chats/say   {chat, text, key?} -> {line, turn}   (key: the composer draft whose files go with it;
                                              turn: the id the answer's line will have, and its stream
                                              ``chat-<turn>``, read through ``answering``)
    POST /api/chats/tap   {chat, card, button?, confirmed?} -> {line}   (the phone too: a PC-only command is
                                              refused, as POST /api/commands does)
    POST /api/chats/tap/pc   the same with every command, for the PC's own app (never offered to the phone)
    POST /api/chats/stop  {chat, turn}       -> {stopped: bool}
    GET  /api/chats/file?chat=&name=         {name, type, data: "data:<type>;base64,…"} (name: <sha>.<ext>, or the
                                              file's own name)

``button`` is one of chatstore.BUTTONS (default ``"do"``). No answer ever carries a key (``session.redact``).
"""

from __future__ import annotations

import base64
import re
import threading
from pathlib import Path
from typing import Any

from .. import chat as chatmod
from .. import chatstore
from ..harness import streamlog


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/chats"): lambda q: {"chats": _chats(app)},
        ("GET", "/api/chats/read"): lambda q: read(app, q or {}),
        ("POST", "/api/chats/say"): lambda b: say(app, b or {}),
        ("POST", "/api/chats/tap"): lambda b: tap(app, b or {}, pc=False),
        ("POST", "/api/chats/tap/pc"): lambda b: tap(app, b or {}, pc=True),
        ("POST", "/api/chats/stop"): lambda b: stop(app, b or {}),
        ("GET", "/api/chats/file"): lambda q: file(app, q or {}),
    }


def _chats(app) -> list[dict[str, Any]]:
    try:
        chatstore.bring_in_letters(chatmod.home_of(app), getattr(app, "hub", None), getattr(app, "agent", None) or "me")
    except Exception:  # noqa: BLE001
        pass
    return chatstore.chats(app)


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


# -- answers being written: one per chat at a time ---------------------------------------------------------------
_live: dict[str, dict[str, Any]] = {}  # chat -> {turn, root, thread, stop, owner}
_live_lock = threading.Lock()


def _home(app):
    return chatmod.home_of(app)


def _err(e: Exception):
    from .server import ApiError

    return ApiError(str(e))


def _stream_root(app, chat: str) -> Path:
    """Where an answer's words go as they are written: the project's folder when it is here, else the app's."""
    try:
        info = chatmod._info(app, chat)
    except chatmod.ChatError:
        info = {}
    return Path(info["path"]) if info.get("path") else _home(app) / "chat-live"


def _answering(app, chat: str) -> dict[str, Any] | None:
    with _live_lock:
        live = _live.get(chat)
    if not live:
        return None
    running = live["thread"].is_alive()
    got = streamlog.read(live["root"], f"chat-{live['turn']}", 0, done=not running)
    if not running:
        with _live_lock:
            if _live.get(chat) is live:
                _live.pop(chat, None)
    text = re.sub(r"(?m)^[ \t]*Action:.*$", "", got["text"])  # the card comes with the answer, not as words
    return {"text": text.rstrip(), "thinking": got["thinking"], "at": got["at"], "done": not running,
            "turn": live["turn"]}


def wait(chat: str, timeout: float = 20.0) -> bool:
    """Wait for the answer being written in ``chat`` (tests, the CLI); True when it has finished."""
    with _live_lock:
        live = _live.get(chat)
    if not live:
        return True
    live["thread"].join(timeout)
    return not live["thread"].is_alive()


def read(app, q: dict) -> dict[str, Any]:
    chat = _chat(_first(q, "chat"))
    home, hub = _home(app), getattr(app, "hub", None)
    since = _first(q, "since")
    try:
        chatstore.bring_in_letters(home, hub, getattr(app, "agent", None) or "me")
    except Exception:  # noqa: BLE001 - the chat still opens
        pass
    got = chatstore.read(home, hub, chat, since)
    lines = got["lines"]
    out: dict[str, Any] = {"lines": lines, "at": got["at"], "answering": _answering(app, chat),
                           "can": chatmod.can_answer(app, chat), "seat": chatstore.me()["id"]}
    if not since:  # the first page: the old letters, read-only, folded under "Earlier messages"
        have = {x["id"] for x in lines}
        out["earlier"] = [{**chatstore.public(x), "earlier": True} for x in chatstore.earlier(hub, chat)
                          if "letter-" + x["id"][len("earlier-"):] not in have]
    chatstore.mark_read(home, chat, got["at"])
    return out


def say(app, b: dict) -> dict[str, Any]:
    from .. import attachments as att

    chat = _chat(b.get("chat"))
    text = str(b.get("text") or "").strip()
    home, hub = _home(app), getattr(app, "hub", None)
    files: list[dict[str, Any]] = []
    draft = None
    if b.get("key"):
        try:
            draft = att.Draft(home, str(b["key"]))
            for item in draft.folder.items():
                files.append(chatstore.attach(home, hub, chat, item["name"], draft.folder.read(item)))
            if not text:
                text = str(draft.meta().get("text") or "").strip()
        except att.AttachmentError as e:
            raise _err(e) from None
    if not text and not files:
        raise _err(ValueError("Write something first."))
    try:
        chatmod._info(app, chat)
    except chatmod.ChatError as e:
        raise _err(e) from None
    with _live_lock:
        busy = chat in _live and _live[chat]["thread"].is_alive()
    if busy:
        raise _err(ValueError("Wait a moment: the last answer is still being written (or press Stop)."))
    hidden = chatstore.scrub(text)[1]
    owner = chatmod.say_line(app, chat, text, files)
    if draft is not None:
        draft.clear()
    if hidden:
        chatstore.append(home, hub, chat, chatmod._app_line(
            "I hid something that looked like a key before keeping or sending your message. Keys go in Settings "
            "→ Keys, never in the chat.", answers=""))
    turn = chatstore.new_id()
    root = _stream_root(app, chat)
    stop_ev = threading.Event()
    sink = streamlog.sink(root, f"chat-{turn}")
    th = threading.Thread(target=lambda: chatmod.answer(app, chat, owner, turn, on_delta=sink,
                                                        aloud=bool(b.get("aloud")), stop=stop_ev),
                          daemon=True, name=f"chat-{chat}")
    with _live_lock:
        _live[chat] = {"turn": turn, "root": root, "thread": th, "stop": stop_ev, "owner": owner["id"]}
    th.start()
    return {"line": chatstore.public(owner), "turn": turn}


def tap(app, b: dict, pc: bool) -> dict[str, Any]:
    chat = _chat(b.get("chat"))
    try:
        return {"line": chatmod.tap(app, chat, str(b.get("card") or ""), b.get("confirmed") is True,
                                    str(b.get("button") or "do"), pc=pc)}
    except chatmod.ChatError as e:
        raise _err(e) from None


def stop(app, b: dict) -> dict[str, Any]:
    chat = _chat(b.get("chat"))
    with _live_lock:
        live = _live.get(chat)
    if not live or (b.get("turn") and b["turn"] != live["turn"]) or not live["thread"].is_alive():
        return {"stopped": False}
    live["stop"].set()
    return {"stopped": True}


TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
         "txt": "text/plain", "md": "text/markdown", "json": "application/json", "pdf": "application/pdf"}


def file(app, q: dict) -> dict[str, Any]:
    from .server import ApiError

    chat = _chat(_first(q, "chat"))
    name = _first(q, "name")
    if not chatstore.file_bytes(_home(app), getattr(app, "hub", None), chat, name):  # a file's own name: its sha
        for x in reversed(chatstore.lines_of(_home(app), getattr(app, "hub", None), chat)):
            f = next((f for f in x.get("files") or [] if f.get("name") == name and f.get("sha")), None)
            if f:
                name = f"{f['sha']}.{f['ext']}"
                break
    data = chatstore.file_bytes(_home(app), getattr(app, "hub", None), chat, name)
    if data is None:
        raise ApiError("That file isn't here.", 404)
    ext = name.rsplit(".", 1)[-1].lower()
    ctype = TYPES.get(ext, "application/octet-stream")
    return {"name": name, "type": ctype, "data": f"data:{ctype};base64," + base64.b64encode(data).decode()}
