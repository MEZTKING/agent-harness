"""One search over everything: plans, tasks, journal entries, letters, memory, saved notes and project files.

``search(query, projects=..., hub=..., me=...)`` gives plain result lines – where it is ("Music player · Plan"),
a title and a short snippet around the words – best first. Every word must be there (any order; "quoted words"
must be together). Ranking is simple: words in the title count most, then how often they appear, then the kind
(memory and plans before files), then the newest.

Sources, each read only:

* each project's ``.harness/plan.md``, ``tasks.json`` (title, what to do, what was done, the reviews) and its
  memory (``.harness/memory.md`` and the archive beside it), and this computer's memory;
* its files: names always, text of files up to ``MAX_FILE_BYTES`` that aren't binary; never ``.git``,
  ``.harness``, ``node_modules`` and other build folders, ``.env`` files, keys or symlinks;
* the hub: every journal entry the owner may read (``hub.journal.entries``), the owner's letters, the saved
  notes (``notes/*.md``) and plans published by projects that run elsewhere (``plans/*.md``).

Each hit carries ``open``, what the app opens: ``{"room": "project", "path", "tab"}``, ``{"room": "file",
"path", "file", "line"}``, ``{"room": "memory", "path" | "machine", "archive"}``, ``{"room": "journal", "agent"}``,
``{"room": "letter", "id", "thread"}``, ``{"room": "note", "name"}`` or ``{"room": "hub_plan", "name"}``.
``peek_file`` reads lines around a hit, only inside the project (``safe_file``).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

MAX_FILE_BYTES = 512 * 1024  # bigger files are found by name only
MAX_FILES = 5000  # per project
MAX_TEXT_BYTES = 24 * 1024 * 1024  # text read from one project's files, in all
SKIP_DIRS = {".git", ".harness", "node_modules", ".venv", "venv", "env", "__pycache__", ".godot", ".gradle", ".idea",
             ".vscode", "dist", "build", ".next", ".cache", "target", ".pytest_cache", ".mypy_cache", "site-packages"}
SECRET_NAME = re.compile(r"^(\.env(\..*)?|.*\.(pem|key|p12|pfx|jks|keystore)|id_(rsa|ed25519|ecdsa)(\.pub)?|"
                         r"\.npmrc|\.pypirc|\.netrc|credentials(\.json)?)$", re.IGNORECASE)
KIND_WEIGHT = {"memory": 3, "plan": 3, "task": 2, "journal": 2, "letter": 2, "note": 2, "hub_plan": 2, "file": 0}
KIND_WORDS = {"memory": "Memory", "plan": "Plan", "task": "Task", "journal": "Journal", "letter": "Letter",
              "note": "My notes", "hub_plan": "Plan", "file": "File"}
SNIPPET = 180


@dataclass
class Hit:
    kind: str
    title: str
    where: str
    snippet: str = ""
    score: float = 0.0
    at: str = ""
    open: dict[str, Any] = field(default_factory=dict)

    def view(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind_words"] = KIND_WORDS.get(self.kind, self.kind)
        return d


# -- matching ----------------------------------------------------------------------------------------
def terms(query: str) -> list[str]:
    """The words to look for: "quoted words" stay together; everything lower case."""
    q = str(query or "").strip().lower()
    out = [m.strip() for m in re.findall(r'"([^"]+)"', q) if m.strip()]
    rest = re.sub(r'"[^"]*"?', " ", q)
    out += [w for w in re.findall(r"[\w.+#/-]+", rest) if w]
    return list(dict.fromkeys(out))[:12]


def score(words: list[str], title: str, text: str, phrase: str = "") -> float:
    """0 when a word is missing; otherwise more for words in the title, then for each time they appear."""
    t, x = title.lower(), text.lower()
    s = 0.0
    for w in words:
        in_title, n = w in t, x.count(w)
        if not in_title and not n:
            return 0.0
        s += (4 if in_title else 0) + min(n, 5)
    if phrase and len(words) > 1 and (phrase in t or phrase in x):
        s += 6
    return s


def snippet(text: str, words: list[str], size: int = SNIPPET) -> str:
    """A short piece of the text around the first word found, on one line."""
    plain = re.sub(r"(?m)^\s*#{1,6}\s+", "", text or "")  # markdown marks don't help a snippet
    plain = re.sub(r"\*\*|__|`", "", plain)
    flat = re.sub(r"\s+", " ", plain).strip()
    low = flat.lower()
    at = min([i for i in (low.find(w) for w in words) if i >= 0] or [0])
    start = max(0, at - size // 3)
    if start:
        sp = flat.rfind(" ", 0, start + 1)
        start = sp + 1 if sp >= 0 and start - sp < 20 else start
    piece = flat[start:start + size].strip()
    return ("…" if start else "") + piece + ("…" if start + size < len(flat) else "")


def _line_of(text: str, words: list[str]) -> int:
    low = text.lower()
    at = min([i for i in (low.find(w) for w in words) if i >= 0] or [0])
    return low.count("\n", 0, at) + 1


# -- the project's own files ---------------------------------------------------------------------------
def project_name(root: Path) -> str:
    try:
        meta = json.loads((root / ".harness" / "project.json").read_text(encoding="utf-8"))
        name = str(meta.get("name") or meta.get("title") or "").strip()
        if name:
            return name
    except (OSError, ValueError, AttributeError):
        pass
    return root.name.replace("-", " ").replace("_", " ").strip().capitalize() or str(root)


def _read(p: Path, limit: int = MAX_FILE_BYTES) -> str:
    try:
        if p.is_symlink() or not p.is_file() or p.stat().st_size > limit:
            return ""
        raw = p.read_bytes()
    except OSError:
        return ""
    if b"\0" in raw[:4096]:
        return ""
    return raw.decode("utf-8", errors="replace")


def _plan_and_tasks(root: Path, name: str, words: list[str], phrase: str) -> list[Hit]:
    out: list[Hit] = []
    plan = _read(root / ".harness" / "plan.md")
    if plan:
        title = next((ln.lstrip("# ").strip() for ln in plan.splitlines() if ln.startswith("#")), "The plan")
        s = score(words, title, plan, phrase)
        if s:
            out.append(Hit("plan", title, f"{name} · Plan", snippet(plan, words), s,
                           open={"room": "project", "path": str(root), "tab": "plan"}))
    try:
        tasks = json.loads(_read(root / ".harness" / "tasks.json") or "[]")
    except ValueError:
        tasks = []
    for t in tasks if isinstance(tasks, list) else []:
        if not isinstance(t, dict):
            continue
        title = str(t.get("title") or t.get("id") or "A task")
        reviews = " ".join(str(a.get("review") or "") for a in t.get("attempts") or [] if isinstance(a, dict))
        body = " \n".join(str(t.get(k) or "") for k in ("description", "acceptance", "summary")) + " " + reviews
        s = score(words, title, body, phrase)
        if s:
            out.append(Hit("task", f"Task {t.get('id', '')}: {title}".replace("Task : ", "Task: "),
                           f"{name} · Tasks", snippet(body, words), s,
                           open={"room": "project", "path": str(root), "tab": "plan", "task": str(t.get("id") or "")}))
    return out


def _memory_hits(path: Path, where: str, open_: dict[str, Any], words: list[str], phrase: str) -> list[Hit]:
    from . import memory

    out: list[Hit] = []
    for archive, f in ((False, path), (True, memory.archive_of(path))):
        text = _read(f, 8 * MAX_FILE_BYTES)
        if not text:
            continue
        # one hit per matching line: memory is lines, and the line is the answer
        for line in text.splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            s = score(words, "", line, phrase)
            if s:
                bare = line.lstrip("-* ").strip()
                m = re.match(r"^(\d{4}-\d{2}-\d{2})\s*·\s*(.*)$", bare)
                day, bare = (m.group(1), m.group(2)) if m else ("", bare)
                title = bare if len(bare) <= 120 else bare[:119].rstrip() + "…"
                out.append(Hit("memory", title, where + (" · archive" if archive else ""),
                               snippet(bare, words) if len(bare) > 120 else "", s - (1 if archive else 0),
                               at=f"{day}T12:00:00Z" if day else "", open={**open_, "archive": archive}))
    return out[:20]


def safe_file(root: str | Path, rel: str) -> Path | None:
    """``rel`` inside the project, or None: no absolute paths, no "..", nothing in a skipped folder, no
    secrets, no symlinks, and the real path must stay inside the project."""
    base = Path(root).resolve()
    s = str(rel or "").replace("\\", "/").strip()
    if not s or s.startswith("/") or re.match(r"^[A-Za-z]:", s):
        return None
    parts = PurePosixPath(s).parts
    if any(p in ("..", "") for p in parts) or any(p in SKIP_DIRS for p in parts[:-1]) or SECRET_NAME.match(parts[-1]):
        return None
    p = base.joinpath(*parts)
    try:
        if any(q.is_symlink() for q in [p, *p.parents] if base in q.parents or q == p):
            return None
        real = p.resolve()
    except OSError:
        return None
    if base not in real.parents or not real.is_file():
        return None
    return real


def walk_files(root: Path, max_files: int = MAX_FILES) -> Iterable[tuple[str, Path]]:
    """(relative path, file) for the project's own files, skipping build folders, secrets and symlinks."""
    n = 0
    for here, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(here, d)))
        for f in sorted(files):
            if SECRET_NAME.match(f):
                continue
            full = Path(here) / f
            if full.is_symlink():
                continue
            n += 1
            if n > max_files:
                return
            yield full.relative_to(root).as_posix(), full


def _file_hits(root: Path, name: str, words: list[str], phrase: str) -> list[Hit]:
    out: list[Hit] = []
    budget = MAX_TEXT_BYTES
    for rel, full in walk_files(root):
        text = ""
        try:
            size = full.stat().st_size
        except OSError:
            continue
        if size <= MAX_FILE_BYTES and budget > 0:
            text = _read(full)
            budget -= len(text)
        s = score(words, rel, text, phrase)
        if not s:
            continue
        line = _line_of(text, words) if text else 0
        snip = snippet(text, words) if text and any(w in text.lower() for w in words) else (
            "Too big to look inside: found by its name." if size > MAX_FILE_BYTES else "Found by its name.")
        out.append(Hit("file", rel, f"{name} · Files", snip, s,
                       open={"room": "file", "path": str(root), "file": rel, "line": line}))
    return out


def peek_file(root: str | Path, rel: str, line: int = 0, around: int = 20) -> dict[str, Any]:
    """Lines around ``line`` of a project file, for the app to show (only inside the project)."""
    p = safe_file(root, rel)
    if p is None:
        raise ValueError("That file isn't one Roundtable can show (it's outside the project, private or gone).")
    if p.stat().st_size > MAX_FILE_BYTES:
        return {"file": rel, "lines": [], "from": 0, "words": "This file is too big to show here."}
    text = _read(p)
    if not text and p.stat().st_size:
        return {"file": rel, "lines": [], "from": 0, "words": "This file isn't text, so it can't be shown here."}
    lines = text.splitlines()
    at = max(1, int(line or 1))
    start = max(1, at - around)
    return {"file": rel, "from": start, "line": at, "lines": lines[start - 1:start - 1 + 2 * around + 1], "words": ""}


# -- the hub --------------------------------------------------------------------------------------------
def _hub_hits(hub, me: str | None, words: list[str], phrase: str, names: dict[str, str]) -> list[Hit]:
    out: list[Hit] = []
    if hub is None:
        return out
    from .ui import hall

    agents = list(getattr(hub.config, "agents", {}) or {})
    for agent in agents:
        try:
            entries = hub.journal.entries(me or agent, agent)
        except Exception:  # not allowed to read it, or unreadable: skip
            continue
        who = names.get(agent) or agent
        for e in entries:
            body = " \n".join(str(e.get(k) or "") for k in ("text", "details", "closed_note"))
            body += " " + " ".join(str(x) for x in e.get("next") or [])
            title = re.sub(r"\s+", " ", str(e.get("text") or "")).strip()[:100] or str(e.get("kind") or "Entry")
            s = score(words, "", body, phrase)
            if s:
                out.append(Hit("journal", title, f"{who} · Journal ({e.get('kind', 'note')})", snippet(body, words), s,
                               at=str(e.get("created_at") or ""), open={"room": "journal", "agent": agent,
                                                                        "id": str(e.get("id") or "")}))
    if me:
        try:
            letters = hub.inbox(me, unread_only=False, mark_read=False, limit=0)
        except Exception:
            letters = []
        for m in letters:
            subject, body = str(m.get("subject") or ""), str(m.get("body") or "")
            s = score(words, subject, body, phrase)
            if s:
                sender = names.get(str(m.get("sender") or "")) or str(m.get("sender") or "someone")
                out.append(Hit("letter", subject or "A letter", f"Letters · from {sender}", snippet(body or subject, words),
                               s, at=str(m.get("created_at") or ""),
                               open={"room": "letter", "id": str(m.get("id") or ""),
                                     "thread": str(m.get("thread_id") or m.get("id") or "")}))
    try:
        notes = hall.hub_notes(hub)
    except Exception:
        notes = []
    for n in notes:
        try:
            text = hall.hub_note(hub, n["name"])["markdown"]
        except Exception:
            continue
        s = score(words, n["title"], text, phrase)
        if s:
            out.append(Hit("note", n["title"], "My notes", snippet(text, words), s, at=n.get("at", ""),
                           open={"room": "note", "name": n["name"]}))
    root = hall.hub_root(hub)
    plans = root / "plans" if root else None
    if plans and plans.is_dir():
        for md in sorted(plans.glob("*.md")):
            if not hall.SAFE_NAME.match(md.stem):
                continue
            text = _read(md)
            title = next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.startswith("# ")), md.stem)
            s = score(words, title, text, phrase)
            if s:
                out.append(Hit("hub_plan", title, f"{names.get(md.stem) or md.stem.replace('--', ' · ')} · Plan (in the hub)",
                               snippet(text, words), s, open={"room": "hub_plan", "name": md.stem}))
    return out


# -- all of it ------------------------------------------------------------------------------------------
KINDS = ("plan", "task", "memory", "file", "journal", "letter", "note", "hub_plan")


def search(query: str, projects: Iterable[str | Path] = (), hub=None, me: str | None = None,
           home: str | Path | None = None, limit: int = 40, kinds: Iterable[str] | None = None,
           names: dict[str, str] | None = None) -> dict[str, Any]:
    """Everything that matches ``query``, best first: {query, hits: [...], total, words}."""
    words = terms(query)
    if not words:
        return {"query": query, "hits": [], "total": 0, "words": "Type a word to look for."}
    phrase = " ".join(words)
    want = set(kinds or KINDS)
    names = dict(names or {})
    hits: list[Hit] = []
    from . import memory

    for r in projects:
        root = Path(r).resolve()
        if not root.is_dir():
            continue
        name = project_name(root)
        if want & {"plan", "task"}:
            hits += [h for h in _plan_and_tasks(root, name, words, phrase) if h.kind in want]
        if "memory" in want:
            hits += _memory_hits(memory.project_path(root), f"{name} · Memory",
                                 {"room": "memory", "path": str(root)}, words, phrase)
        if "file" in want:
            hits += _file_hits(root, name, words, phrase)
    if "memory" in want:
        try:
            hits += _memory_hits(memory.machine_path(home), "This computer · Memory",
                                 {"room": "memory", "machine": True}, words, phrase)
        except Exception:
            pass
    if want & {"journal", "letter", "note", "hub_plan"}:
        hits += [h for h in _hub_hits(hub, me, words, phrase, names) if h.kind in want]
    for h in hits:
        h.score += KIND_WEIGHT.get(h.kind, 0)
    hits.sort(key=lambda h: (-h.score, h.at and -_stamp(h.at) or 0, h.where, h.title))
    total = len(hits)
    shown = hits[:max(1, int(limit))]
    words_ = ("Nothing found. Try fewer or shorter words." if not total else
              f"{total} found" + (f", the best {len(shown)} shown." if total > len(shown) else "."))
    return {"query": query, "hits": [h.view() for h in shown], "total": total, "words": words_}


def _stamp(ts: str) -> float:
    from datetime import datetime

    try:
        return datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").timestamp()
    except ValueError:
        return 0.0


__all__ = ["KINDS", "Hit", "peek_file", "safe_file", "score", "search", "snippet", "terms", "walk_files"]
