"""The message box's attachments: pictures and files with an idea, a note or a chat message.

Where they live:

* **A draft** (what the owner is still writing): ``<app home>/drafts/<key>/`` – ``draft.json`` (the
  text, queue or steer, the files' list) and ``files/``. A draft survives closing the app; ``key`` is the
  box's own name (``new-idea``, ``chat:<project>``…).
* **A project**: ``<project>/.harness/attachments/`` – ``index.json`` and ``files/``. Sending a draft
  moves its files here (``claim``), each with a ``scope``: ``goal`` (the idea itself; ``goal_index``
  says which), ``note`` (a "Tell the planner" note) or ``chat`` (one question).

What the models get (``request_with_attachments``, called by the built-in plugin ``attachments`` before
every model call of a project's conversations): the first message gains a short list of what's attached;
text files come as their text; pictures come as picture content for a model that can see (Claude, GPT,
Gemini…: ``can_see``) and as a name and size for one that can't (DeepSeek). Goal and note attachments go to
every conversation of the project; a chat attachment only to the question it came with.

``@file`` references: ``@path/in/project`` in the text attaches that file's content as it is when sent
(``references``); paths outside the project, ``.git`` and ``.harness`` are refused.

Steer (``steer_now``): a note for the task running now. It is written to ``.harness/steer-now.jsonl`` and
added to the newest message of every conversation already under way, at its next step (and kept there, so
the request stays the same from step to step). Queue is the existing ``Orchestrator.steer``: the next task.

Settings (``attachments:`` in harness.yaml, all optional): ``max_mb`` (10, one file), ``max_total_mb``
(25, one message), ``max_files`` (10), ``image_px`` (1568: longer pictures are made smaller when Pillow is
there; the app makes them smaller before sending anyway), ``max_images`` (6 per request), ``text_chars``
(20000 per text file), ``to_workers`` (true: builders and reviewers see them too, not only the planner),
``pictures`` (true), ``vision`` ({word in a model's name: true or false}, on top of the built-in list).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import struct
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DIR = Path(".harness") / "attachments"
STEER_FILE = Path(".harness") / "steer-now.jsonl"
SCOPES = ("goal", "note", "chat")
MODES = ("queue", "steer")
SKIP_DIRS = {".git", ".harness", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".gradle", "build", "dist"}
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}
REF_RE = re.compile(r"(?<![\w@])@([\w][\w./\\-]*[\w])")
_LOCK = threading.RLock()

# Models known to see pictures, by a word in their name (lower case). DeepSeek's chat models can't.
SEEING = ("claude", "gpt-4o", "gpt-4.1", "gpt-5", "o3", "o4-mini", "gemini", "gemma-3", "llama-4", "pixtral",
          "-vl", "vl-", "qwen3.5", "qwen-vl", "glm-4.5v", "glm-4v", "kimi-k2.5", "grok-4", "llava", "mistral-medium",
          "mistral-small-3", "nova-")
BLIND = ("deepseek",)


class AttachmentError(ValueError):
    """Something the owner can fix (too big, not in the project…): the message says what to do."""


@dataclass
class Settings:
    max_mb: float = 10.0
    max_total_mb: float = 25.0
    max_files: int = 10
    image_px: int = 1568
    max_images: int = 6
    text_chars: int = 20000
    to_workers: bool = True
    pictures: bool = True
    vision: dict[str, bool] = field(default_factory=dict)

    @classmethod
    def from_config(cls, cfg: Any) -> "Settings":
        from .harness.config import section

        raw = section(cfg, "attachments") if cfg is not None else {}
        s = cls()
        for k, v in raw.items():
            if not hasattr(s, k):
                continue
            try:
                cur = getattr(s, k)
                setattr(s, k, dict(v) if isinstance(cur, dict) else type(cur)(v))
            except (TypeError, ValueError):
                pass
        return s


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def size_words(n: int) -> str:
    n = int(n or 0)
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    return f"{max(1, round(n / 1024))} KB" if n >= 1024 else f"{n} bytes"


def safe_name(name: str) -> str:
    """A file name with no folders, no odd characters and at most 80 characters."""
    base = re.split(r"[\\/]", str(name or ""))[-1].strip().strip(".")
    base = re.sub(r"[^\w.\- ()]+", "_", base)[:80].strip()
    return base or "file"


# -- what a file is ------------------------------------------------------------------------------
def sniff(data: bytes, name: str = "") -> str:
    """The picture's type from its first bytes, else text/plain for readable text, else a guess by name."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF"):
        return "application/pdf"
    head = data[:8192]
    if b"\x00" not in head:
        try:
            head.decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            if len(head) == 8192:  # cut in the middle of a character
                try:
                    head[:-4].decode("utf-8")
                    return "text/plain"
                except UnicodeDecodeError:
                    pass
    return "application/octet-stream"


def kind_of(mime: str) -> str:
    return "image" if mime in IMAGE_TYPES else "text" if mime.startswith("text/") else "file"


def image_size(data: bytes) -> tuple[int, int]:
    """Width and height from a PNG, GIF or JPEG header (0, 0 when unknown)."""
    try:
        if data.startswith(b"\x89PNG"):
            return struct.unpack(">II", data[16:24])
        if data[:3] == b"GIF":
            return struct.unpack("<HH", data[6:10])
        if data.startswith(b"\xff\xd8"):
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return w, h
                seg = struct.unpack(">H", data[i + 2:i + 4])[0]
                i += 2 + seg
        if data[:4] == b"RIFF" and data[12:16] == b"VP8X":
            return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
    except struct.error:
        pass
    return 0, 0


def shrink(data: bytes, mime: str, max_px: int) -> tuple[bytes, str]:
    """A picture longer than ``max_px`` made smaller (Pillow, when it's there); others unchanged."""
    w, h = image_size(data)
    if max_px <= 0 or (w and h and max(w, h) <= max_px):
        return data, mime
    try:
        from PIL import Image
    except ImportError:
        return data, mime
    try:
        with Image.open(io.BytesIO(data)) as im:
            if max(im.size) <= max_px:
                return data, mime
            im.thumbnail((max_px, max_px))
            out = io.BytesIO()
            if im.mode in ("RGBA", "LA", "P"):
                im.save(out, "PNG", optimize=True)
                return out.getvalue(), "image/png"
            im.convert("RGB").save(out, "JPEG", quality=85)
            return out.getvalue(), "image/jpeg"
    except Exception:  # a broken picture: keep it as it came
        return data, mime


# -- one folder of attachments (a draft's or a project's) -----------------------------------------
class Folder:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.files = self.path / "files"

    @property
    def index_path(self) -> Path:
        return self.path / "index.json"

    def items(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [x for x in data if isinstance(x, dict) and x.get("id")] if isinstance(data, list) else []

    def save(self, items: list[dict[str, Any]]) -> None:
        with _LOCK:
            self.path.mkdir(parents=True, exist_ok=True)
            tmp = self.path / ".index.json.tmp"
            tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            tmp.replace(self.index_path)

    def file(self, item: dict[str, Any]) -> Path:
        p = (self.files / str(item.get("file") or "")).resolve()
        if self.files.resolve() not in p.parents:
            raise AttachmentError("That attachment's file isn't where it should be.")
        return p

    def read(self, item: dict[str, Any]) -> bytes:
        return self.file(item).read_bytes()

    def add(self, name: str, data: bytes, settings: Settings | None = None, **extra: Any) -> dict[str, Any]:
        """Keep one file: checked against the caps, a big picture made smaller first."""
        s = settings or Settings()
        name = safe_name(name)
        mime = sniff(data, name)
        if mime in IMAGE_TYPES:
            data, mime = shrink(data, mime, s.image_px)
            if not name.lower().endswith("." + IMAGE_TYPES[mime]) and IMAGE_TYPES[mime] == "jpg" \
                    and not name.lower().endswith(".jpeg"):
                name = os.path.splitext(name)[0] + ".jpg"
        if not data:
            raise AttachmentError(f"{name} is empty.")
        if len(data) > s.max_mb * 1024 * 1024:
            raise AttachmentError(f"{name} is too big ({size_words(len(data))}). The most is {s.max_mb:g} MB: "
                                  "make it smaller or send part of it.")
        with _LOCK:
            items = self.items()
            if len(items) >= s.max_files:
                raise AttachmentError(f"That's the most files for one message ({s.max_files}). Remove one first.")
            total = sum(int(x.get("size") or 0) for x in items) + len(data)
            if total > s.max_total_mb * 1024 * 1024:
                raise AttachmentError(f"Together these are too big ({size_words(total)}). The most for one message is "
                                      f"{s.max_total_mb:g} MB: remove one or send it on its own.")
            iid = secrets.token_hex(4)
            fname = f"{iid}-{name}"
            self.files.mkdir(parents=True, exist_ok=True)
            (self.files / fname).write_bytes(data)
            item: dict[str, Any] = {"id": iid, "name": name, "file": fname, "kind": kind_of(mime), "mime": mime,
                                    "size": len(data), "at": now(), "sha": hashlib.sha256(data).hexdigest()[:16]}
            if mime in IMAGE_TYPES:
                w, h = image_size(data)
                if w and h:
                    item.update(width=w, height=h)
            item.update({k: v for k, v in extra.items() if v is not None})
            items.append(item)
            self.save(items)
            return item

    def remove(self, iid: str) -> bool:
        with _LOCK:
            items = self.items()
            keep = [x for x in items if x["id"] != iid]
            if len(keep) == len(items):
                return False
            for x in items:
                if x["id"] == iid:
                    try:
                        self.file(x).unlink()
                    except (OSError, AttachmentError):
                        pass
            self.save(keep)
            return True


def project_folder(root: str | Path) -> Folder:
    return Folder(Path(root) / DIR)


def project_root_of(path: str | Path | None) -> Path | None:
    """The project a folder belongs to: itself, or the project around a task's worktree
    (``<project>/.harness/worktrees/<task>``)."""
    if path is None:
        return None
    p = Path(path).resolve()
    parts = p.parts
    for i in range(len(parts) - 2, 0, -1):
        if parts[i] == ".harness" and parts[i + 1] == "worktrees":
            return Path(*parts[:i])
    return p


# -- drafts ----------------------------------------------------------------------------------------
def drafts_home(home: str | Path) -> Path:
    return Path(home) / "drafts"


def _draft_dir(home: str | Path, key: str) -> Path:
    key = str(key or "").strip()
    if not key or len(key) > 200:
        raise AttachmentError("This message box has no name.")
    return drafts_home(home) / hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


class Draft:
    """What the owner is still writing in one message box: text, queue or steer, and files."""

    def __init__(self, home: str | Path, key: str):
        self.key = key
        self.dir = _draft_dir(home, key)
        self.folder = Folder(self.dir)

    def _meta_path(self) -> Path:
        return self.dir / "draft.json"

    def meta(self) -> dict[str, Any]:
        try:
            d = json.loads(self._meta_path().read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def view(self, with_previews: bool = True) -> dict[str, Any]:
        m = self.meta()
        items = []
        for x in self.folder.items():
            v = public(x)
            if with_previews and x.get("kind") == "image" and int(x.get("size") or 0) <= 600_000:
                try:
                    v["preview"] = f"data:{x['mime']};base64," + base64.b64encode(self.folder.read(x)).decode()
                except (OSError, AttachmentError):
                    pass
            items.append(v)
        return {"key": self.key, "text": str(m.get("text") or ""), "mode": m.get("mode") if m.get("mode") in MODES else "queue",
                "saved_at": m.get("saved_at") or "", "items": items}

    def save_text(self, text: str, mode: str | None = None) -> dict[str, Any]:
        with _LOCK:
            m = self.meta()
            m.update(key=self.key, text=str(text or "")[:20000], saved_at=now())
            if mode in MODES:
                m["mode"] = mode
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.dir / ".draft.json.tmp"
            tmp.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._meta_path())
        return self.view(with_previews=False)

    def add(self, name: str, data: bytes, settings: Settings | None = None, **extra: Any) -> dict[str, Any]:
        return public(self.folder.add(name, data, settings, **extra))

    def remove(self, iid: str) -> bool:
        return self.folder.remove(iid)

    def clear(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    @property
    def empty(self) -> bool:
        return not self.folder.items() and not str(self.meta().get("text") or "").strip()


def public(item: dict[str, Any]) -> dict[str, Any]:
    """An attachment as the app shows it (no file paths)."""
    keys = ("id", "name", "kind", "mime", "size", "width", "height", "at", "scope", "goal_index", "ref", "pending")
    out = {k: item[k] for k in keys if k in item}
    out["size_words"] = size_words(int(item.get("size") or 0))
    return out


# chunked uploads: the app's servers take at most 2 MB a request, so a big file comes in parts
_UPLOADS: dict[str, dict[str, Any]] = {}


def upload_part(home: str | Path, key: str, name: str, chunk_b64: str, upload_id: str = "", last: bool = True,
                settings: Settings | None = None) -> dict[str, Any]:
    """One part of a file for a draft. Returns {upload_id} until ``last``, then {item, draft}."""
    s = settings or Settings()
    try:
        chunk = base64.b64decode(str(chunk_b64 or ""), validate=False)
    except (ValueError, TypeError):
        raise AttachmentError("That file didn't arrive whole. Try adding it again.")
    with _LOCK:
        for uid in [u for u, v in _UPLOADS.items() if time.monotonic() - v["t"] > 600]:
            _UPLOADS.pop(uid, None)  # forgotten halves
        if upload_id:
            up = _UPLOADS.get(upload_id)
            if not up or up["key"] != key:
                raise AttachmentError("That file didn't arrive whole. Try adding it again.")
        else:
            upload_id = secrets.token_hex(8)
            up = _UPLOADS[upload_id] = {"key": key, "buf": bytearray(), "t": time.monotonic()}
        up["buf"] += chunk
        up["t"] = time.monotonic()
        if len(up["buf"]) > s.max_mb * 1024 * 1024 * 4:  # a picture may still shrink; anything else is refused at add
            _UPLOADS.pop(upload_id, None)
            raise AttachmentError(f"{safe_name(name)} is too big. The most is {s.max_mb:g} MB.")
        if not last:
            return {"upload_id": upload_id}
        data = bytes(_UPLOADS.pop(upload_id)["buf"])
    d = Draft(home, key)
    item = d.add(name, data, s)
    return {"item": item, "draft": d.view()}


# -- @file references ------------------------------------------------------------------------------
def inside(root: str | Path, rel: str) -> Path:
    """``rel`` as a file inside the project, or AttachmentError (outside it, .git, .harness, missing)."""
    root = Path(root).resolve()
    rel = str(rel or "").strip().replace("\\", "/")
    if not rel or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel) or rel.startswith("~"):
        raise AttachmentError(f"@{rel}: only files inside the project can be attached.")
    p = (root / rel).resolve()
    if p != root and root not in p.parents:
        raise AttachmentError(f"@{rel}: only files inside the project can be attached.")
    first = p.relative_to(root).parts[:1]
    if first and first[0] in (".git", ".harness"):
        raise AttachmentError(f"@{rel}: The harness's own files can't be attached.")
    if not p.is_file():
        raise AttachmentError(f"@{rel}: there's no such file in the project.")
    return p


def project_files(root: str | Path, query: str = "", limit: int = 30) -> list[str]:
    """Files of the project for the @ list: names that contain the typed letters first, shortest first."""
    root = Path(root)
    if not root.is_dir():
        return []
    q = str(query or "").lower().replace("\\", "/")
    found: list[str] = []
    seen = 0
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for f in sorted(files):
            seen += 1
            if seen > 20000:
                break
            rel = os.path.relpath(os.path.join(dirpath, f), root).replace(os.sep, "/")
            if not q or q in rel.lower():
                found.append(rel)
    found.sort(key=lambda r: (q not in os.path.basename(r).lower(), not os.path.basename(r).lower().startswith(q),
                              len(r), r))
    return found[:limit]


def references(text: str) -> list[str]:
    """The ``@path`` words in a message, in order, once each (an email address isn't one)."""
    out: list[str] = []
    for m in REF_RE.finditer(str(text or "")):
        r = m.group(1).rstrip(".,;:")
        if r not in out:
            out.append(r)
    return out


def attach_references(root: str | Path, text: str, folder: Folder, settings: Settings | None = None,
                      **extra: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Attach each ``@file`` of ``text`` (the file's content now). Returns (added, problems in words).
    A word after @ that isn't a file (a name, a handle) is left alone."""
    added, problems = [], []
    for rel in references(text):
        try:
            p = inside(root, rel)
        except AttachmentError as e:
            if "no such file" not in str(e):
                problems.append(str(e))
            continue
        try:
            item = folder.add(p.name, p.read_bytes(), settings, ref=rel, **extra)
        except AttachmentError as e:
            problems.append(f"@{rel}: {e}")
            continue
        added.append(item)
    return added, problems


# -- sending: a draft becomes the project's ------------------------------------------------------------
def claim(draft: Draft, root: str | Path, scope: str, settings: Settings | None = None, **extra: Any) -> list[dict[str, Any]]:
    """Copy a draft's files into the project with ``scope`` (goal/note/chat); also its @file references.
    The caller clears the draft once the message went (so a failure keeps what the owner wrote)."""
    if scope not in SCOPES:
        raise AttachmentError(f"unknown scope {scope!r}")
    s = settings or Settings()
    folder = project_folder(root)
    loose = Settings(**{**s.__dict__, "max_files": 10 ** 6, "max_total_mb": 10 ** 6, "image_px": 0})  # checked as drafts
    out = []
    for x in draft.folder.items():
        try:
            out.append(folder.add(x["name"], draft.folder.read(x), loose, scope=scope, **extra))
        except (OSError, AttachmentError):
            continue
    text = str(draft.meta().get("text") or "")
    refs, _ = attach_references(root, text, folder, loose, scope=scope, **extra)
    return out + refs


def project_items(root: str | Path) -> list[dict[str, Any]]:
    return project_folder(root).items()


def finish_chat(root: str | Path, ids: list[str]) -> None:
    """A chat question was answered: its attachments are no longer sent with every call."""
    folder = project_folder(root)
    with _LOCK:
        items = folder.items()
        for x in items:
            if x["id"] in ids:
                x.pop("pending", None)
        folder.save(items)


def names_line(items: list[dict[str, Any]]) -> str:
    return ", ".join(f"{x['name']} ({size_words(int(x.get('size') or 0))})" for x in items)


# -- steer: into the running task, at its next step --------------------------------------------------------
def steer_now(root: str | Path, text: str) -> dict[str, Any]:
    text = str(text or "").strip()
    if not text:
        raise AttachmentError("Write what to change first.")
    row = {"id": secrets.token_hex(4), "at": now(), "t": time.time(), "text": text[:2000]}
    p = Path(root) / STEER_FILE
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def steers(root: str | Path) -> list[dict[str, Any]]:
    p = Path(root) / STEER_FILE
    out = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("text"):
                out.append(d)
    except OSError:
        pass
    return out


# -- what the models get -----------------------------------------------------------------------------------
def provider_type(cfg: Any, model: str) -> str:
    pid = str(model).split("/", 1)[0]
    return str(((getattr(cfg, "providers", None) or {}).get(pid) or {}).get("type") or "")


def can_see(cfg: Any, model: str, settings: Settings | None = None) -> bool:
    """Whether a model (``provider/model``) takes pictures: the owner's ``vision`` words first, then the list."""
    s = settings or Settings()
    ptype = provider_type(cfg, model)
    if ptype == "scripted":
        return True
    name = str(model).split("/", 1)[-1].lower()
    for word, yes in (s.vision or {}).items():
        if str(word).lower() in name:
            return bool(yes)
    if ptype not in ("anthropic", "openai_compat"):
        return False
    if ptype == "anthropic":
        return True
    if any(w in name for w in BLIND):
        return False
    return any(w in name for w in SEEING)


def picture_block(ptype: str, mime: str, data: bytes, name: str) -> dict[str, Any]:
    b64 = base64.b64encode(data).decode()
    if ptype == "anthropic":
        return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}}
    if ptype == "openai_compat":
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
    return {"type": "image", "media_type": mime, "data": b64, "name": name}  # scripted (tests)


def _chosen(items: list[dict[str, Any]], role: str | None, planner_roles: set[str], s: Settings) -> list[dict[str, Any]]:
    out = []
    for x in items:
        scope = x.get("scope")
        if scope == "chat":
            if x.get("pending") and (role in planner_roles or role is None):
                out.append(x)
        elif scope in ("goal", "note"):
            if s.to_workers or role in planner_roles or role is None:
                out.append(x)
    return out


def attachment_content(cfg: Any, model: str, root: Path, role: str | None = None,
                       settings: Settings | None = None) -> tuple[str, list[dict[str, Any]]]:
    """(text to add, picture blocks) for one conversation: what's attached to this project for it."""
    s = settings or Settings.from_config(cfg)
    folder = project_folder(root)
    items = folder.items()
    if not items:
        return "", []
    planner_roles = {r for r in (getattr(cfg, "planner_role", None), getattr(cfg, "critic_role", None),
                                 getattr(cfg, "design_role", None)) if r}
    items = _chosen(items, role, planner_roles, s)
    if not items:
        return "", []
    ptype = provider_type(cfg, model)
    sees = s.pictures and can_see(cfg, model, s)
    pictures = [x for x in items if x.get("kind") == "image"][-max(0, s.max_images):] if sees else []
    lines = ["# Attached by the owner"]
    blocks: list[dict[str, Any]] = []
    for x in items:
        where = {"goal": "with the idea", "note": "with a note", "chat": "with this question"}.get(x.get("scope"), "")
        label = f"- {x['name']} ({x.get('mime')}, {size_words(int(x.get('size') or 0))}{', ' + where if where else ''})"
        if x.get("ref"):
            label += f" – the project's file {x['ref']} as it was when the owner wrote"
        if x.get("kind") == "image":
            dims = f"{x['width']}×{x['height']} " if x.get("width") else ""
            if x in pictures:
                label += f": a {dims}picture, shown below"
                try:
                    blocks.append(picture_block(ptype, x["mime"], folder.read(x), x["name"]))
                except (OSError, AttachmentError):
                    label += " (missing)"
            elif sees:
                label += f": a {dims}picture (not shown: only the newest {s.max_images} are)"
            else:
                label += f": a {dims}picture. This model can't see pictures; go by its name and the owner's words"
        elif x.get("kind") == "text":
            try:
                text = folder.read(x).decode("utf-8", errors="replace")
            except (OSError, AttachmentError):
                text = "(missing)"
            cut = len(text) > s.text_chars
            label += f":\n```\n{text[:s.text_chars]}\n```" + (f"\n(cut: the first {s.text_chars} characters)" if cut else "")
        else:
            label += ": a file the harness can't read to you; go by its name"
        lines.append(label)
    return "\n".join(lines), blocks


def _with_text(msg: dict[str, Any], text: str) -> dict[str, Any]:
    m = dict(msg)
    c = m.get("content")
    if isinstance(c, list):
        m["content"] = [*c, {"type": "text", "text": text}]
    else:
        m["content"] = (c or "") + "\n\n" + text
    return m


def request_with_attachments(cfg: Any, model: str, messages: list[dict[str, Any]], project_root: Path | None,
                             role: str | None, state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The conversation as it is sent: the project's attachments in its first message, and steer notes
    written since it began added to the message that was newest when each arrived. ``state`` lasts one
    conversation (the plugin's ``ctx.state``), so every step sends the same earlier messages."""
    root = project_root_of(project_root)
    if root is None or not messages or not (root / ".harness").is_dir():
        return messages
    state = state if state is not None else {}
    s = Settings.from_config(cfg)
    if "started" not in state:
        state["started"] = time.time()
        state["steer_at"] = {}
        state["first"] = attachment_content(cfg, model, root, role, s)
    out = list(messages)
    text, blocks = state["first"]
    first = out[0]
    if first.get("role") == "user" and (text or blocks):
        c = first.get("content")
        if blocks:
            parts = c if isinstance(c, list) else [{"type": "text", "text": str(c or "")}]
            out[0] = {**first, "content": [*parts, {"type": "text", "text": text}, *blocks]}
        else:
            out[0] = _with_text(first, text)
    placed: dict[str, int] = state["steer_at"]
    for row in steers(root):
        if row["id"] not in placed and float(row.get("t") or 0) >= state["started"] and len(out) > 1:
            placed[row["id"]] = len(out) - 1
    by_id = {r["id"]: r for r in steers(root)} if placed else {}
    for rid, idx in placed.items():
        if rid in by_id and idx < len(out):
            out[idx] = _with_text(out[idx], f"[The owner, just now, about the work in progress: {by_id[rid]['text']}]")
    return out
