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
(nothing in ``inbox/`` is written but read marks, nothing deleted). Each comes as a line whose ``id`` starts
with ``earlier-`` (the apps fold those under "Earlier messages"). A letter to the owner that hasn't been read
yet is brought into the chat once as an ordinary line (``id`` ``letter-<message id>``) and marked read.

Changing a line (a card tapped, a message marked waiting): the device appends the whole line again, with the
same ``id`` and a later ``at``, to its own day file. A reader keeps one line per ``id``: the first ``at`` gives
its place, the furthest card state (open < queued < running < done, cancelled) wins, then the latest ``at``;
a reader asking ``since`` sees a line again when any copy of it is newer. An owner's line is ``answered`` as
soon as a ``chat`` or ``project`` line answers it, whatever its own ``state`` says.

Secrets: every line's words and every text file go through :func:`scrub` before they are kept or sent
anywhere (keys, tokens, private keys, ``NAME=secret`` lines are replaced by :data:`HIDDEN`). A picture is made
smaller and written again without its EXIF data (location, camera); one that can't be read again stays on the
device it was added on.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import threading
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


# -- secrets: scrubbed before anything is kept or sent ------------------------------------------------------------
HIDDEN = "[hidden: looks like a key]"
_PEM = re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----[\s\S]*?(?:-----END (?:[A-Z]+ )*PRIVATE KEY-----|\Z)")
_ENV = re.compile(r"(?im)^([ \t]*(?:export[ \t]+)?[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD|PAT)"
                  r"[A-Z0-9_]*[ \t]*=[ \t]*['\"]?)(?!proxy-injected)([^\s'\"]{8,})")


def _secret_patterns() -> list[re.Pattern]:
    from .backup import SECRET_PATTERNS

    return [re.compile(p.pattern.decode()) for p, _ in SECRET_PATTERNS]


def scrub(text: Any) -> tuple[str, int]:
    """``text`` with every key-shaped piece replaced by :data:`HIDDEN`, and how many were."""
    from .backup import SETTING_PATTERN

    s = str(text or "")
    n = 0
    s, k = _PEM.subn(HIDDEN, s)
    n += k
    for p in _secret_patterns():
        s, k = p.subn(HIDDEN, s)
        n += k
    s, k = _ENV.subn(lambda m: m.group(1) + HIDDEN, s)
    n += k
    setting = re.compile(SETTING_PATTERN.pattern.decode())
    found = [m for m in setting.finditer(s) if m.group(1) != HIDDEN and HIDDEN not in m.group(1)]
    for m in reversed(found):
        s = s[:m.start(1)] + HIDDEN + s[m.end(1):]
    return s, n + len(found)


def _scrub_line(line: dict[str, Any]) -> dict[str, Any]:
    out = dict(line)
    for k in ("text", "thinking"):
        if isinstance(out.get(k), str):
            out[k] = scrub(out[k])[0]
    if isinstance(out.get("card"), dict):
        card = dict(out["card"])
        for k in ("title", "line", "confirm", "more", "command", "queued_for"):
            if isinstance(card.get(k), str):
                card[k] = scrub(card[k])[0]
        out["card"] = card
    return out


# -- where things are -------------------------------------------------------------------------------------------
CARD_RANK = {"open": 0, "queued": 1, "running": 2, "done": 3, "cancelled": 3}
CLAIM_STALE_S = 600  # a claim without an answer for 10 minutes may be taken by another device
DAY_MAX_BYTES = 30_000_000  # what one device sends to the hub's chat files in a day; more stays on the device
_lock = threading.RLock()


def _hub_dir(hub) -> Path | None:
    root = getattr(getattr(hub, "store", None), "root", None)
    return Path(root) if root else None


def _local(home) -> Path | None:
    return Path(home) / ROOT if home else None


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _seat_of_file(name: str) -> str:
    # <day>.<seat>.jsonl
    stem = name[:-len(".jsonl")] if name.endswith(".jsonl") else name
    if stem.endswith(".local"):
        stem = stem[:-len(".local")]
    return stem.split(".", 1)[1] if "." in stem else ""


def me() -> dict[str, str]:
    from .sync import this_machine

    return this_machine()


def _day_files(base: Path | None, chat: str) -> dict[str, Path]:
    d = base / chat if base else None
    if not d or not d.is_dir():
        return {}
    return {p.name: p for p in d.glob("*.jsonl") if p.is_file()}


def _text(p: Path | None) -> str:
    try:
        return p.read_text(encoding="utf-8") if p else ""
    except OSError:
        return ""


def _write_local(home, rel: str, text: str) -> None:
    base = Path(home)
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)


def _push(home, hub, chat: str, seat: str) -> int:
    """This device's day files of ``chat`` brought to the hub where they differ. Never raises (offline: the next
    one carries everything)."""
    root = _hub_dir(hub)
    if hub is None or root is None or not home:
        return 0
    from .core.store import TextFile

    items: dict[str, Any] = {}
    for name, p in _day_files(_local(home), chat).items():
        if name.endswith(".local.jsonl") or _seat_of_file(name) != _safe(seat):
            continue
        mine = _text(p)
        if mine and mine != _text(root / ROOT / chat / name):
            items[f"{ROOT}/{chat}/{name}"] = TextFile(mine)
    if not items:
        return 0
    try:
        hub.store.write_json(items, f"chat({chat}): {seat}"[:200])
        return len(items)
    except Exception:  # noqa: BLE001 - offline: kept on this device, sent with the next line
        return 0


def push(home, hub, seat: str | None = None) -> int:
    """Every chat's lines this device hasn't got into the hub yet (the auto-sync calls it)."""
    seat = seat or me()["id"]
    base = _local(home)
    if not base or not base.is_dir():
        return 0
    return sum(_push(home, hub, d.name, seat) for d in sorted(base.iterdir()) if d.is_dir() and is_chat(d.name))


def append(home: Path, hub, chat: str, line: dict[str, Any]) -> dict[str, Any]:
    """Add ``line`` to this device's day file (the local copy, then the hub); returns it with ``id`` and ``at``."""
    _need_chat(chat)
    line = check_line(_scrub_line({"id": new_id(), "at": now(), **line}))
    seat = str(line.get("seat") or me()["id"])
    rel = day_path(chat, today(), seat)
    row = json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n"
    if not _for_hub(line):  # the app's own notices stay on this device (the phone does the same)
        if home:
            with _lock:
                lrel = rel[:-len(".jsonl")] + ".local.jsonl"
                _write_local(home, lrel, _text(Path(home) / lrel) + row)
        return line
    with _lock:
        if home:
            _write_local(home, rel, _text(Path(home) / rel) + row)
            _push(home, hub, chat, seat)
        elif _hub_dir(hub) is not None:  # no local copy (a machine without an app home): straight to the hub
            from .core.store import TextFile

            try:
                hub.store.write_json({rel: TextFile(_text(_hub_dir(hub) / rel) + row)}, f"chat({chat}): {seat}")
            except Exception:  # noqa: BLE001
                pass
    return line


def _for_hub(line: dict[str, Any]) -> bool:
    """Every line reaches the hub but the app's own notices ("Nothing can answer…"): an ``app`` line goes only
    when it says a card's new state (its card is a model's card, not the notice's own buttons)."""
    if line.get("who") != "app":
        return True
    card = line.get("card")
    return isinstance(card, dict) and not str(card.get("id") or "").startswith("app-")


def _files_of(home, hub, chat: str) -> dict[str, str]:
    """Every device's day files of ``chat``, the local copy and the hub's merged (the longer copy of each wins:
    a file is only ever added to). The hub's files of other devices are copied to the local copy for offline."""
    local = _day_files(_local(home), chat)
    hub_files = _day_files((_hub_dir(hub) / ROOT) if _hub_dir(hub) else None, chat)
    out: dict[str, str] = {}
    for name in sorted(set(local) | set(hub_files)):
        a, b = _text(local.get(name)), _text(hub_files.get(name))
        out[name] = a if len(a) >= len(b) else b
        if home and len(b) > len(a):
            try:
                _write_local(home, f"{ROOT}/{chat}/{name}", b)
            except OSError:
                pass
    return out


def lines_of(home, hub, chat: str) -> list[dict[str, Any]]:
    """Every line of ``chat`` merged, one per id, in order; each with ``_writer`` (the seat whose file held its
    chosen copy) and ``_changed`` (the newest ``at`` of any copy). For chat.py; the routes use :func:`read`."""
    if not is_chat(chat):
        return []
    groups: dict[str, list[dict[str, Any]]] = {}
    for name, text in _files_of(home, hub, chat).items():
        writer = _seat_of_file(name)
        for raw in text.splitlines():
            try:
                line = check_line(json.loads(raw))
            except (ValueError, TypeError):
                continue  # half written, or not a line: skipped
            line["_writer"] = writer
            groups.setdefault(str(line["id"]), []).append(line)
    out = []
    answered = set()
    for versions in groups.values():
        for v in versions:
            if v["who"] in ("chat", "project") and v.get("answers"):
                answered.add(str(v["answers"]))
    for lid, versions in groups.items():
        first = min(str(v["at"]) for v in versions)
        best = max(versions, key=lambda v: (CARD_RANK.get((v.get("card") or {}).get("state"), -1), str(v["at"])))
        line = dict(best)
        line["_changed"] = max(str(v["at"]) for v in versions)
        line["at"] = first
        if line["who"] == "owner" and lid in answered:
            line["state"] = "answered"
        out.append(line)
    out.sort(key=order_key)
    # a card's later states come as further lines carrying the same card id (any device): the first carrier
    # shows the card with the furthest state; the others keep their words only
    origin: dict[str, dict[str, Any]] = {}
    for line in sorted(out, key=lambda x: x["who"] == "app"):  # the card's own line first, its state lines after
        card = line.get("card")
        if isinstance(card, dict) and card.get("id") and str(card["id"]) not in origin:
            origin[str(card["id"])] = line
    for line in out:
        card = line.get("card")
        if not isinstance(card, dict) or not card.get("id"):
            continue
        cid = str(card["id"])
        first = origin[cid]
        if first is line:
            continue
        if CARD_RANK.get(card.get("state"), -1) >= CARD_RANK.get(first["card"].get("state"), -1):
            keep = {k: card[k] for k in ("state", "queued_for", "buttons", "more") if k in card}
            first["card"] = {**first["card"], **keep}
        first["_changed"] = max(str(first["_changed"]), str(line["_changed"]))
        line.pop("card", None)
        line["_state_of"] = cid
    return out


def public(line: dict[str, Any]) -> dict[str, Any]:
    """A line as the apps get it: no inner fields, every key-shaped piece hidden (``session.redact``)."""
    from .harness.session import redact

    out = {k: v for k, v in line.items() if not k.startswith("_")}
    for k in ("text", "thinking"):
        if isinstance(out.get(k), str):
            out[k] = redact(out[k])
    return out


def read(home: Path, hub, chat: str, since: str = "", limit: int = 200) -> dict[str, Any]:
    """The newest ``limit`` lines after ``since`` (an ``at``), every device's day files merged by order_key;
    ``at``: where the next read starts."""
    every = lines_of(home, hub, chat)
    new = [x for x in every if str(x["_changed"]) > str(since or "")]
    at = max([str(since or "")] + [str(x["_changed"]) for x in every])
    return {"lines": [public(x) for x in new[-max(1, int(limit)):]], "at": at}


STATE_WORDS = {"queued": "Queued.", "running": "Started.", "done": "Done.", "cancelled": "Not done.", "open": ""}


def update(home: Path, hub, chat: str, line: dict[str, Any], words: str = "", **changes: Any) -> dict[str, Any]:
    """``line`` changed. A card's new state is a further line (``who: app``, a new id, the same card id,
    answering what the card's line answers) that every device reads alike; any other change (an owner's line
    marked waiting) is the whole line appended again with the same id and a later ``at``. Returns the line as
    readers now see it."""
    _need_chat(chat)
    base = {k: v for k, v in line.items() if not k.startswith("_")}
    if "card" in changes:
        card = check_card(changes.pop("card"))
        state_line = {"who": "app", "seat": me()["id"], "card": card,
                      "text": words or card.get("queued_for") or STATE_WORDS.get(card["state"], ""),
                      "answers": base.get("answers") or base.get("id")}
        append(home, hub, chat, state_line)
        base = {**base, "card": card}
        if not changes:
            return check_line(base) if "id" in base else base
    first = base.get("at")
    seat = me()["id"]
    row = {**base, **changes, "at": now()}
    kept = check_line(_scrub_line(row))
    rel = day_path(chat, today(), seat)
    text = json.dumps(kept, ensure_ascii=False, sort_keys=True) + "\n"
    with _lock:
        if home:
            _write_local(home, rel, _text(Path(home) / rel) + text)
            _push(home, hub, chat, seat)
        elif _hub_dir(hub) is not None:
            from .core.store import TextFile

            try:
                hub.store.write_json({rel: TextFile(_text(_hub_dir(hub) / rel) + text)}, f"chat({chat}): {seat}")
            except Exception:  # noqa: BLE001
                pass
    return {**kept, "at": first or kept["at"]}


# -- old letters -------------------------------------------------------------------------------------------------
def owners(hub) -> set[str]:
    """Who speaks for the owner in the hub: ``me`` and the owner's own machines (seats of role machine)."""
    out = {"me"}
    for a, spec in getattr(getattr(hub, "config", None), "agents", {}).items():
        if getattr(spec, "role", None) == "machine":
            out.add(a)
    return out


def _runner_agents(hub) -> set[str]:
    """Hub agents that report for several projects (``harness``): their letters carry the project's folder."""
    root = _hub_dir(hub)
    out = set()
    if root and (root / "plans").is_dir():
        for md in (root / "plans").glob("*--*.md"):
            out.add(md.stem.split("--", 1)[0])
    return out


def agent_chat(hub, agent: str, folder: str = "") -> str:
    """The chat of a hub agent: Hall for the owner and the owner's machines, ``<agent>--<folder>`` for a
    project reported through a shared agent, else the agent's own."""
    if not agent or agent in owners(hub):
        return HALL
    spec = getattr(getattr(hub, "config", None), "agents", {}).get(agent)
    if getattr(spec, "role", None) == "machine":
        return HALL
    if folder and folder != agent:
        return chat_id(f"{agent}--{folder}")
    root = _hub_dir(hub)
    if root is not None and (root / "plans").is_dir() and agent in _runner_agents(hub):
        mine = sorted(p.stem for p in (root / "plans").glob(f"{agent}--*.md"))
        return chat_id(mine[0]) if len(mine) == 1 else HALL  # which of its projects: only clear with one
    return chat_id(agent)


def _letters(hub) -> list[dict[str, Any]]:
    root = _hub_dir(hub)
    if not root or not (root / "inbox").is_dir():
        return []
    out = []
    for d in sorted((root / "inbox").iterdir()):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json")):
            try:
                m = json.loads(f.read_text(encoding="utf-8"))  # read only: inbox/ is never written here
            except (OSError, ValueError):
                continue
            if isinstance(m, dict) and m.get("id"):
                out.append(m)
    return out


def _folder_of(m: dict[str, Any]) -> str:
    if str(m.get("subject", "")).startswith("roundtable:"):
        try:
            body = json.loads(m.get("body") or "{}")
            return str(body.get("project_folder") or "") if isinstance(body, dict) else ""
        except ValueError:
            return ""
    return ""


def _ms(ts: str) -> str:
    """A hub time (``…:SSZ``) in the chat's form (``…:SS.000Z``)."""
    s = str(ts or "")
    return s[:-1] + ".000Z" if re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", s) else (s or "1970-01-01T00:00:00.000Z")


COMMAND_WORDS = {"approve": "approve and build", "run": "build", "carry_on": "carry on building", "build": "build",
                 "retry": "try a task again", "skip": "leave a task out", "revise": "update the plan",
                 "answer": "answer a question", "choose": "choose", "looks": "make new looks", "steer": "note something",
                 "ask": "answer a question", "show_it": "take pictures", "todo_done": "tick off a to-do",
                 "autopilot": "change autopilot", "shared_settings": "change the shared settings",
                 "accept": "accept a task as it is", "profile": "change the model set"}


def letter_lines(hub, letter: dict[str, Any], by_thread: dict[str, str] | None = None,
                 replied: set[str] | None = None, prefix: str = "earlier-") -> list[tuple[str, dict[str, Any]]]:
    """One letter as chat lines: ``[(chat, line)]`` (an agent's letter to another sits in both their chats)."""
    who_owner = owners(hub)
    s, r = str(letter.get("sender") or ""), str(letter.get("recipient") or "")
    folder = _folder_of(letter) or (by_thread or {}).get(str(letter.get("thread_id") or ""), "")
    subject, body = str(letter.get("subject") or ""), str(letter.get("body") or "")
    base = {"id": prefix + _safe(letter["id"]), "at": _ms(letter.get("created_at")), "seat": "", "from": s, "to": r}
    if s in who_owner and r in who_owner:
        return [(HALL, {**base, "who": "owner", "text": (subject + "\n\n" + body).strip()})]
    if s in who_owner:
        chat = agent_chat(hub, r, folder)
        if subject.startswith("roundtable:"):
            try:
                action = str((json.loads(body or "{}") or {}).get("action") or "")
            except (ValueError, AttributeError):
                action = ""
            done = letter["id"] in (replied or set())
            words = COMMAND_WORDS.get(action, action.replace("_", " ") or "do something")
            return [(chat, {**base, "who": "owner", "text": f"You asked it to {words} · {'done' if done else 'sent'}"})]
        return [(chat, {**base, "who": "owner", "text": (subject + "\n\n" + body).strip()})]
    if r in who_owner:
        chat = agent_chat(hub, s, folder)
        text = body if subject.lower().startswith("re: roundtable:") else (subject + "\n\n" + body).strip()
        return [(chat, {**base, "who": "project", "text": text})]
    text = (subject + "\n\n" + body).strip()
    chats_ = {agent_chat(hub, s, folder), agent_chat(hub, r, folder)}
    return [(c, {**base, "who": "agent", "text": text}) for c in sorted(chats_)]


def _thread_maps(letters: list[dict[str, Any]]) -> tuple[dict[str, str], set[str]]:
    by_thread, replied = {}, set()
    for m in letters:
        f = _folder_of(m)
        if f:
            by_thread[str(m.get("thread_id") or m["id"])] = f
        if m.get("in_reply_to"):
            replied.add(str(m["in_reply_to"]))
    return by_thread, replied


def earlier(hub, chat: str) -> list[dict[str, Any]]:
    """The old letters that belong to ``chat``, as read-only lines (``inbox/`` is never changed)."""
    letters = _letters(hub)
    by_thread, replied = _thread_maps(letters)
    out = []
    for m in letters:
        for c, line in letter_lines(hub, m, by_thread, replied):
            if c == chat:
                try:
                    out.append(check_line(_scrub_line(line)))
                except ValueError:
                    continue
    out.sort(key=order_key)
    return out


def bring_in_letters(home, hub, owner: str = "me") -> int:
    """Unread letters to the owner become ordinary chat lines once (``letter-<id>``), then are marked read
    (the only thing written for them: read marks, in ``state/``)."""
    if hub is None:
        return 0
    try:
        unread = hub.inbox(owner, unread_only=True, limit=200)
    except Exception:  # noqa: BLE001 - no owner in this hub
        return 0
    if not unread:
        return 0
    letters = _letters(hub)
    by_thread, replied = _thread_maps(letters)
    seat = me()
    done = []
    for m in unread:
        for chat, line in letter_lines(hub, m, by_thread, replied, prefix="letter-"):
            if any(x["id"] == line["id"] for x in lines_of(home, hub, chat)):
                continue
            append(home, hub, chat, {**line, "at": now(), "seat": seat["id"]})
        done.append(m["id"])
    try:
        hub.mark_read(owner, done)
    except Exception:  # noqa: BLE001
        pass
    return len(done)


# -- attached files ----------------------------------------------------------------------------------------------
_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}


def _picture(data: bytes) -> tuple[bytes, str] | None:
    """The picture made at most PICTURE_PX, written again without EXIF (location, camera); None when it can't
    be read (then it isn't sent anywhere)."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            try:
                im = ImageOps.exif_transpose(im)
            except Exception:  # noqa: BLE001
                pass
            im.thumbnail((PICTURE_PX, PICTURE_PX))
            out = io.BytesIO()
            if im.mode in ("RGBA", "LA", "P"):
                im.save(out, "PNG", optimize=True)
                return out.getvalue(), "png"
            im.convert("RGB").save(out, "JPEG", quality=85)
            got = out.getvalue()
            if len(got) > FILE_MAX_BYTES:
                out = io.BytesIO()
                im.convert("RGB").save(out, "JPEG", quality=60)
                got = out.getvalue()
            return got, "jpg"
    except Exception:  # noqa: BLE001 - not a picture after all
        return None


def _sent_today(home) -> int:
    base = _local(home)
    if not base or not base.is_dir():
        return 0
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    total = 0
    for p in base.glob("*/files/*"):
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_mtime >= start and not p.name.startswith("."):
            total += st.st_size
    return total


def attach(home: Path, hub, chat: str, name: str, data: bytes) -> dict[str, Any]:
    """Keep an attached file (a picture made smaller, location data removed); returns its FILE_KEYS entry."""
    from .attachments import kind_of, safe_name, sniff

    _need_chat(chat)
    name = safe_name(name)[:120] or "file"
    mime = sniff(data, name)
    kind = "picture" if kind_of(mime) == "image" else "file"
    keep_here = False
    if kind == "picture":
        pic = _picture(data)
        if pic is None:
            keep_here = True  # its EXIF can't be taken out: it stays on this device
            ext = _EXT.get(mime, "bin")
        else:
            data, ext = pic
    else:
        ext = (name.rsplit(".", 1)[-1].lower() if "." in name else "bin")[:8]
        if kind_of(mime) == "text":
            text, n = scrub(data.decode("utf-8", errors="replace"))
            if n:
                data = text.encode("utf-8")
    ext = _safe(ext)
    sha = hashlib.sha256(data).hexdigest()[:20]
    rel = file_path(chat, sha, ext)
    if home:
        p = Path(home) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    entry: dict[str, Any] = {"name": name, "sha": sha, "ext": ext, "size": len(data), "kind": kind}
    if keep_here or len(data) > FILE_MAX_BYTES or _sent_today(home) > DAY_MAX_BYTES or _hub_dir(hub) is None:
        entry["on"] = me()["id"]
        return entry
    from .core.store import BinaryFile

    try:
        hub.store.write_json({rel: BinaryFile(data)}, f"chat({chat}): a {kind}")
    except Exception:  # noqa: BLE001 - offline: it stays here, the others see its name and size
        entry["on"] = me()["id"]
    return entry


def file_bytes(home, hub, chat: str, name: str) -> bytes | None:
    """An attached file by ``<sha>.<ext>``: the local copy, else the hub's."""
    if not is_chat(chat) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}\.[A-Za-z0-9_-]{1,8}", str(name or "")):
        return None
    for base in (Path(home) if home else None, _hub_dir(hub)):
        if base is None:
            continue
        p = base / ROOT / chat / "files" / name
        if p.is_file():
            try:
                return p.read_bytes()
            except OSError:
                continue
    return None


# -- waiting messages and who answers them -----------------------------------------------------------------------
def chat_dirs(home, hub) -> list[str]:
    out = set()
    for base in (_local(home), (_hub_dir(hub) / ROOT) if _hub_dir(hub) else None):
        if base and base.is_dir():
            out |= {d.name for d in base.iterdir() if d.is_dir() and is_chat(d.name)}
    return sorted(out)


def waiting(hub) -> list[dict[str, Any]]:
    """Every owner's line with ``state: waiting`` in every chat, as ``{"chat", "line"}``."""
    out = []
    for chat in chat_dirs(None, hub):
        for line in lines_of(None, hub, chat):
            if line["who"] == "owner" and line.get("state") == "waiting":
                out.append({"chat": chat, "line": line})
    return out


def _age(ts: str) -> float:
    try:
        then = datetime.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return 1e12
    return (datetime.now(timezone.utc) - then).total_seconds()


def claim(hub, chat: str, turn: str, seat: str) -> bool:
    """Take the claim to answer ``turn``; False when another device has it."""
    root = _hub_dir(hub)
    if root is None:
        return False
    rel = claim_path(chat, turn)
    p = root / rel
    with _lock:
        try:
            hub.store.sync(force=True)
        except Exception:  # noqa: BLE001 - offline: the local copy decides, the push settles it
            pass
        cur = _read_json(p)
        if cur and cur.get("seat") == seat:
            return True
        if cur and _age(cur.get("at")) < CLAIM_STALE_S:
            return False
        data = {"seat": seat, "at": now()}
        p.parent.mkdir(parents=True, exist_ok=True)
        if not cur:
            try:  # first to make the file on this disk (two devices sharing one folder, or two threads)
                fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f)
            except FileExistsError:
                got = _read_json(p)
                return bool(got and got.get("seat") == seat)
        try:
            hub.store.write_json({rel: data}, f"chat({chat}): {seat} answers {turn}"[:200])
            hub.store.sync(force=True)
        except Exception:  # noqa: BLE001 - another device's claim reached the hub first, or offline
            got = _read_json(p)
            if not got or got.get("seat") != seat:
                return False
        got = _read_json(p)
        return bool(got and got.get("seat") == seat)


def _read_json(p: Path) -> dict[str, Any] | None:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


# -- the list of chats ---------------------------------------------------------------------------------------------
def _marks_path(home) -> Path | None:
    return Path(home) / ROOT / "read.json" if home else None


def read_marks(home) -> dict[str, str]:
    p = _marks_path(home)
    return (_read_json(p) or {}) if p else {}


def mark_read(home, chat: str, at: str) -> None:
    p = _marks_path(home)
    if not p or not at:
        return
    with _lock:
        marks = read_marks(home)
        if str(marks.get(chat) or "") >= at:
            return
        marks[chat] = at
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(marks, sort_keys=True), encoding="utf-8")


def chats(app) -> list[dict[str, Any]]:
    """The list of chats, Hall first, the newest spoken-in next: ``[{id, name, last, unread, waiting}]``."""
    if app is None:
        return []
    from . import chat as brain

    home, hub = brain.home_of(app), getattr(app, "hub", None)
    known = brain.projects(app)
    marks = read_marks(home)
    ids = set(chat_dirs(home, hub)) | set(known) | {HALL}
    out = []
    for cid in ids:
        lines = lines_of(home, hub, cid)
        mark = str(marks.get(cid) or "")
        last = lines[-1] if lines else None
        out.append({"id": cid, "name": "Hall" if cid == HALL else (known.get(cid) or {}).get("name") or cid,
                    "last": (str(last.get("text") or "")[:120] if last else ""),
                    "last_at": str(last["_changed"]) if last else "",
                    "unread": sum(1 for x in lines if x["who"] in ("chat", "project", "app")
                                  and str(x["_changed"]) > mark),
                    "waiting": sum(1 for x in lines if x["who"] == "owner" and x.get("state") == "waiting")})
    out.sort(key=lambda c: (c["id"] != HALL, "" if c["id"] == HALL else _inv(c["last_at"]), c["name"].lower()))
    return [{k: c[k] for k in ("id", "name", "last", "unread", "waiting")} for c in out]


def _inv(s: str) -> str:
    """Sorts newest first."""
    return "".join(chr(0x10FFFF - ord(ch)) for ch in s) if s else "\U0010ffff"
