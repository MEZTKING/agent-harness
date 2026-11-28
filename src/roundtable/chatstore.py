"""The chat's history: one chat per project and one for everything ("hall"), the same on every device (1.5.0).

The chat replaces Letters. Step 0 freezes the shapes and the signatures below; chat-server fills them in.

Where it lives, in the hub (a private repository; nothing from it ever goes into this repository, a test or an
outside service other than the model that answers)::

    chats/<chat>/<day>.<seat>.jsonl     one JSON line per message, written only by the device <seat>
    chats/<chat>/files/<sha>.<ext>      an attached picture (made smaller: 1600 px, at most 1.5 MB) or small file
    chats/<chat>/claims/<turn>.json     {"seat", "at"}: who is answering a waiting message (first to reach the hub wins)

``<chat>`` is ``"hall"`` or a project's key in the hub (``sync.project_key``), see :func:`chat_id`. ``<day>`` is
the UTC day, ``YYYY-MM-DD``. ``<seat>`` is the writing device's seat (``sync.this_machine()["id"]``, a phone's
own seat id). Each device writes only its own day files, so two devices never write the same file (the rule
``sync.py`` follows); a reader merges every device's day files by :func:`order_key`.

Each device also keeps its own copy under the app's home, in the same layout (``<home>/chats/<chat>/…``), so a
chat opens at once and works offline; the hub is brought up to date after each answer. A file bigger than
1.5 MB stays on the device it was added on (``on``: that seat); the others show its name and size.

A line (:data:`LINE_KEYS`; only ``id``, ``at``, ``who``, ``seat`` and ``text`` are always there)::

    {"id":       "20261128T101500123-3fa9c1d2",   (new_id: sortable, unique across devices)
     "at":       "2026-11-28T10:15:00.123Z",      (UTC, milliseconds)
     "who":      "owner" | "chat" | "project" | "agent" | "app",
     "seat":     the device that wrote the line,
     "device":   that device's name for the foot ("This phone", "PC-Desk"),
     "text":     the words (the model's answer without its Action: line),
     "thinking": the model's thinking (shown folded, behind "More"),
     "files":    [{"name", "sha", "ext", "size", "kind": "picture" | "file", "on"?}],
     "card":     a card (CARD_KEYS below),
     "cost_usd": what the answer cost, from the tokens the service reported,
     "model":    the model that answered (behind "More"),
     "answers":  the id of the owner's line this answers,
     "state":    "waiting" | "answered" (an owner's line: has anything answered it yet),
     "from", "to": for who "agent" or "project": which project or agent spoke, and to whom}

``who``: ``owner`` the owner typed it; ``chat`` the chat model answered; ``project`` a project's agent wrote to
the owner (an ordinary message that counts in Needs you); ``agent`` agents speaking to each other (a folded grey
line the owner can read but not answer); ``app`` the app itself, when no model can answer (``chat.cannot``).

Trust: only lines this device wrote are trusted. A card is honoured only in a ``chat`` line that answers an
``owner`` line whose ``seat`` is this device's; a line written elsewhere is untrusted whatever its ``who`` says.

A card (:data:`CARD_KEYS`; the same for the desktop and the phone)::

    {"id", "title", "line", "price_usd"?, "cap_usd"?, "confirm"?, "command",
     "buttons": [{"id", "words", "primary"?}], "state": "open" | "queued" | "running" | "done" | "cancelled",
     "queued_for"?, "more"?}

``title``, ``line``, the price and ``command`` (the checked ``/`` command a tap runs) are built by the app from
the parsed command, never copied from the model's words. ``confirm`` is the "Are you sure?" sentence for what
can't be undone. ``queued_for`` names the machine it waits for ("PC-Desk · last listened 3 hours ago").
Button ids: :data:`BUTTONS`.

Old letters: :func:`earlier` reads ``inbox/`` and shows them read-only at the top of the chat they belong to
(nothing in ``inbox/`` is written but read marks, nothing deleted).
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HALL = "hall"
ROOT = "chats"  # in the hub and under the app's home
WHO = ("owner", "chat", "project", "agent", "app")
LINE_STATES = ("waiting", "answered")
LINE_KEYS = ("id", "at", "who", "seat", "device", "text", "thinking", "files", "card", "cost_usd", "model",
             "answers", "state", "from", "to")
LINE_NEEDS = ("id", "at", "who", "seat", "text")
FILE_KEYS = ("name", "sha", "ext", "size", "kind", "on")
FILE_KINDS = ("picture", "file")
CARD_KEYS = ("id", "title", "line", "price_usd", "cap_usd", "confirm", "command", "buttons", "state",
             "queued_for", "more")
CARD_NEEDS = ("id", "title", "line", "command", "buttons", "state")
CARD_STATES = ("open", "queued", "running", "done", "cancelled")
BUTTON_KEYS = ("id", "words", "primary")
# Button ids every device knows: do it, not now, cancel a queued card, run it on This phone instead, set up
# This phone first, add / change the DeepSeek key, top up, raise today's chat allowance
BUTTONS = ("do", "not_now", "cancel", "here", "setup_phone", "add_key", "change_key", "top_up", "raise_today")
PICTURE_PX = 1600  # an attached picture is made at most this wide or tall
FILE_MAX_BYTES = 1_500_000  # bigger stays on the device it was added on
_CHAT = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


# -- the shapes (frozen in Step 0) ------------------------------------------------------------------------------
def chat_id(project_or_none: str | None) -> str:
    """The chat of a project (its key in the hub, ``sync.project_key``), or ``"hall"`` for None or ""."""
    if not project_or_none:
        return HALL
    s = re.sub(r"[^a-z0-9]+", "-", str(project_or_none).lower()).strip("-")[:80].strip("-") or "x"
    return "project-hall" if s == HALL else s


def is_chat(chat: str) -> bool:
    return bool(_CHAT.match(str(chat or "")))


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def new_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")[:-3] + "-" + secrets.token_hex(4)


def day_path(chat: str, day: str, seat: str) -> str:
    """``chats/<chat>/<day>.<seat>.jsonl``, relative to the hub (and to the app's home for the local copy)."""
    return f"{ROOT}/{_need_chat(chat)}/{day}.{_safe(seat)}.jsonl"


def file_path(chat: str, sha: str, ext: str) -> str:
    return f"{ROOT}/{_need_chat(chat)}/files/{_safe(sha)}.{_safe(ext)}"


def claim_path(chat: str, turn: str) -> str:
    return f"{ROOT}/{_need_chat(chat)}/claims/{_safe(turn)}.json"


def order_key(line: dict[str, Any]) -> tuple[str, str, str]:
    """How a reader merges the day files: by ``at``, then ``seat``, then ``id``."""
    return (str(line.get("at") or ""), str(line.get("seat") or ""), str(line.get("id") or ""))


def check_line(line: dict[str, Any]) -> dict[str, Any]:
    """The line with only the known keys; ValueError when it isn't a line."""
    if not isinstance(line, dict):
        raise ValueError("a chat line is a JSON object")
    missing = [k for k in LINE_NEEDS if k not in line]
    if missing:
        raise ValueError(f"a chat line needs {', '.join(missing)}")
    if line["who"] not in WHO:
        raise ValueError(f"who must be one of {', '.join(WHO)}")
    if line.get("state") is not None and line["state"] not in LINE_STATES:
        raise ValueError(f"state must be one of {', '.join(LINE_STATES)}")
    for f in line.get("files") or []:
        if not isinstance(f, dict) or not {"name", "size", "kind"} <= set(f) or f["kind"] not in FILE_KINDS:
            raise ValueError("each file needs name, size and kind (picture or file)")
    if line.get("card") is not None:
        check_card(line["card"])
    return {k: line[k] for k in LINE_KEYS if k in line}


def check_card(card: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(card, dict):
        raise ValueError("a card is a JSON object")
    missing = [k for k in CARD_NEEDS if k not in card]
    if missing:
        raise ValueError(f"a card needs {', '.join(missing)}")
    if card["state"] not in CARD_STATES:
        raise ValueError(f"a card's state must be one of {', '.join(CARD_STATES)}")
    for b in card["buttons"]:
        if not isinstance(b, dict) or not {"id", "words"} <= set(b) or set(b) - set(BUTTON_KEYS):
            raise ValueError("each button is {id, words, primary?}")
    return {k: card[k] for k in CARD_KEYS if k in card}


def _need_chat(chat: str) -> str:
    if not is_chat(chat):
        raise ValueError(f"not a chat: {chat!r}")
    return chat


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(s or "")).strip(".-") or "x"


# -- stubs (chat-server fills these in; nothing is written or read yet) ------------------------------------------
def append(home: Path, hub, chat: str, line: dict[str, Any]) -> dict[str, Any]:
    """Add ``line`` to this device's day file (the local copy, then the hub); returns it with ``id`` and ``at``."""
    return check_line({"id": new_id(), "at": now(), **line})


def read(home: Path, hub, chat: str, since: str = "", limit: int = 200) -> dict[str, Any]:
    """The newest ``limit`` lines after ``since`` (an ``at``), every device's day files merged by order_key;
    ``at``: where the next read starts."""
    return {"lines": [], "at": since}


def earlier(hub, chat: str) -> list[dict[str, Any]]:
    """The old letters that belong to ``chat``, as read-only lines (``inbox/`` is never changed)."""
    return []


def attach(home: Path, hub, chat: str, name: str, data: bytes) -> dict[str, Any]:
    """Keep an attached file (a picture made smaller, location data removed); returns its FILE_KEYS entry."""
    return {"name": name, "size": len(data), "kind": "file"}


def waiting(hub) -> list[dict[str, Any]]:
    """Every owner's line with ``state: waiting`` in every chat, as ``{"chat", "line"}``."""
    return []


def claim(hub, chat: str, turn: str, seat: str) -> bool:
    """Take the claim to answer ``turn``; False when another device has it."""
    return False


def chats(app) -> list[dict[str, Any]]:
    """The list of chats, Hall first, the newest spoken-in next: ``[{id, name, last, unread, waiting}]``."""
    return []
