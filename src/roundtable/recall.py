"""Search by meaning (on this computer): "what did we decide about X?" across everything (wave 7, MD-56, MD-59).

The index is ``<app home>/recall/index.sqlite``, one per machine, rebuilt from its sources and never synced
(delete it and it is made again). The sources, each read only:

* each project's memory and its archive, the plan's settled choices and answered questions, the plan itself,
  and its tasks' summaries (``.harness/plan.json``, ``plan.md``, ``tasks.json``);
* this computer's memory and the agents' own memories (``<app home>/agents/*/memory.md``);
* the owner's documents (``documents.py``);
* the hub: the journal, the owner's letters and saved notes (as ``search.py`` reads them).

Text is cut into pieces of about ``PIECE_CHARS`` characters, each with its source and date. A source is read
again only when its files' dates or sizes change (hub sources: when their text changes, looked at no more often
than every ``HUB_EVERY`` seconds).

Ranking, with no network, no key and no model to download:

1. word scores: BM25 over the pieces' words, cut to their stems ("decided", "decision" and "decide" are one);
2. related words: a small hand-written table of words that mean nearly the same in apps and games
   ("sign-in", "login", "log on"…), counted at a little less than the word itself;
3. letter-group likeness: a query word the index doesn't have is matched to the index's words that share most
   of their three-letter groups ("colour" and "color", "sync" and "synced"), counted at less again.

That is honestly called "Search by meaning (on this computer)": better than every-word search, not as good as a
maker's embeddings (``recall.embeddings`` is read, and not built yet: see ``settings``).

``find`` gives pieces; ``ask`` gives them to one cheap model that answers with quotes and their sources, after a
price is shown. A piece goes to a model only when its project allows that model's maker (``makers.allowed``);
a document ticked "Never leaves this computer" goes to none. ``graph`` is the memory picture: who knows what.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import documents as docs

NAME = "Search by meaning (on this computer)"
DIR = "recall"
INDEX = "index.sqlite"
SCHEMA = 1
PIECE_CHARS = 800
HUB_EVERY = 30.0  # seconds between looks at the hub's sources
LOOKUP_PIECES = 5
LOOKUP_CHARS = 2500
ASK_PIECES = 8
LOG = "recall.jsonl"  # .harness/: what look_up found for which task (the picture's "used which document")
KIND_WEIGHT = {"decision": 0.6, "answer": 0.6, "memory": 0.35, "document": 0.3, "agent": 0.3, "task": 0.15,
               "plan": 0.1, "journal": 0.15, "letter": 0.1, "note": 0.2}
KIND_WORDS = {"decision": "Decided", "answer": "Answered", "memory": "Memory", "document": "Your document",
              "agent": "Agent's memory", "task": "Task", "plan": "Plan", "journal": "Journal", "letter": "Earlier message",
              "note": "My notes"}

# -- words ------------------------------------------------------------------------------------------------------
STOP = set("""a an and are as at be been but by can could did do does doing done for from had has have how i if in
into is it its me my no not of on or our out so than that the their them then there these they this those to too
up us was we were what when where which who whom why will with would you your about should shall any some all
just more most very much also""".split())
_JOIN = re.compile(r"\b(sign|log|check|set|back|start|shut|look|pop)(?:s|ging|ged|ing|ed)?[\s-]+(in|on|out|up|off)\b")
RELATED = [
    {"login", "signin", "logon", "signon", "auth", "authent", "authoris", "authoriz", "credential", "password"},
    {"logout", "signout", "logoff"},
    {"signup", "regist", "creat account"},
    {"sav", "store", "persist", "keep"},
    {"databas", "db", "sqlite", "postgr", "storag"},
    {"colour", "color", "palett", "hue", "theme"},
    {"font", "typefac", "lettering"},
    {"bug", "fault", "error", "crash", "defect", "issu"},
    {"test", "check", "verif"},
    {"fast", "speed", "quick", "perform", "slow", "lag"},
    {"pay", "payment", "billing", "purchas", "checkout", "pric"},
    {"money", "cost", "spend", "budget", "credit", "pric"},
    {"music", "song", "soundtrack", "audio", "sound"},
    {"enemy", "foe", "monster", "opponent"},
    {"level", "stage", "map", "world"},
    {"player", "character", "hero", "avatar"},
    {"screen", "page", "view", "window"},
    {"button", "control", "tap", "click"},
    {"phone", "mobil", "android"},
    {"desktop", "pc", "window", "computer"},
    {"releas", "ship", "publish", "deploy"},
    {"remov", "delet", "eras"},
    {"pictur", "imag", "art", "artwork", "graphic", "sprit", "icon"},
    {"decid", "choic", "choos", "chosen", "decis", "pick", "settl"},
    {"sync", "synchronis", "synchroniz", "share"},
    {"notif", "alert", "remind"},
    {"search", "find", "look"},
]
RELATED_WEIGHT = 0.6
LIKE_WEIGHT = 0.45
LIKE_MIN = 0.45


def stem(w: str) -> str:
    """A word cut to its stem, small and English: decide, decided, deciding and decision all give "decid"."""
    if len(w) <= 3 or w.isdigit():
        return w
    if w.endswith("'s"):
        w = w[:-2]
    for suf, rep in (("ational", "ate"), ("isation", "ise"), ("ization", "ize"), ("sions", "d"), ("sion", "d"),
                     ("tions", "t"), ("tion", "t"), ("ings", ""), ("ing", ""), ("edly", ""), ("ied", "y"),
                     ("ies", "y"), ("ed", ""), ("ly", ""), ("ments", ""), ("ment", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[:-len(suf)] + rep
            break
    else:
        if (w.endswith(("ches", "shes")) or (w.endswith("es") and len(w) > 4 and w[-3] in "sxz")):
            w = w[:-2]
        elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
            w = w[:-1]
    if w.endswith("e") and len(w) >= 4:
        w = w[:-1]
    return w


def tokens(text: str) -> list[str]:
    """The stems of the words in ``text``, without the little words ("the", "what", "we"…)."""
    low = _JOIN.sub(r"\1\2", str(text or "").lower())
    return [stem(w) for w in re.findall(r"[a-z0-9]+", low) if w not in STOP and len(w) > 1]


def grams(w: str) -> set[str]:
    p = f"^{w}$"
    return {p[i:i + 3] for i in range(len(p) - 2)}


def likeness(a: str, b: str) -> float:
    ga, gb = grams(a), grams(b)
    return len(ga & gb) / len(ga | gb) if ga and gb else 0.0


def related(word: str) -> set[str]:
    out: set[str] = set()
    for group in RELATED:
        if word in group:
            out |= group
    out.discard(word)
    return {w for w in out if " " not in w}


# -- pieces ------------------------------------------------------------------------------------------------------
@dataclass
class Piece:
    kind: str
    title: str
    text: str
    where: str
    at: str = ""
    project: str = ""  # the project's id (usage.project_id) or "" (this computer, the hub, a document)
    doc: str = ""  # the document's id
    doc_projects: Any = "all"  # a document's "all" or [project ids]
    private: bool = False  # never leaves this computer
    open: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    id: int = 0

    def view(self) -> dict[str, Any]:
        return {"kind": self.kind, "kind_words": KIND_WORDS.get(self.kind, self.kind), "title": self.title,
                "text": self.text, "where": self.where, "at": self.at, "open": self.open, "doc": self.doc,
                "private": self.private, "score": round(self.score, 3)}

    def source_line(self) -> str:
        return f"{self.where}" + (f" ({self.at[:10]})" if self.at else "")


def chunk(text: str, size: int = PIECE_CHARS) -> list[str]:
    """The text in pieces of about ``size`` characters, cut between paragraphs, then lines, then words."""
    text = str(text or "").strip()
    if not text:
        return []
    out: list[str] = []
    cur = ""
    for line in text.splitlines():
        line = line.rstrip()
        while len(line) > size:
            cut = line.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            if cur:
                out.append(cur.strip())
                cur = ""
            out.append(line[:cut].strip())
            line = line[cut:].strip()
        if len(cur) + len(line) + 1 > size and cur.strip():
            out.append(cur.strip())
            cur = ""
        cur += line + "\n"
    if cur.strip():
        out.append(cur.strip())
    return [c for c in out if c]


@dataclass
class Source:
    """One thing read into the index: ``read()`` gives its pieces; ``stamp`` changes when it changes (None:
    the text's own fingerprint is the stamp)."""
    key: str
    read: Callable[[], list[Piece]]
    stamp: str | None = None
    hub: bool = False


def _mtime(*paths: Path) -> str:
    out = []
    for p in paths:
        try:
            st = p.stat()
            out.append(f"{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            out.append("-")
    return "|".join(out)


def _read(p: Path) -> str:
    from .search import _read as read

    return read(p, 8 * 512 * 1024)


def pid_of(root: str | Path) -> str:
    from .harness.usage import project_id

    return project_id(root)


def _memory_pieces(path: Path, where: str, kind: str, project: str, open_: dict[str, Any]) -> list[Piece]:
    from . import memory

    out: list[Piece] = []
    for archive, f in ((False, path), (True, memory.archive_of(path))):
        lines = [ln for ln in _read(f).splitlines() if ln.strip() and not ln.startswith("# ")
                 and not ln.startswith("What the harness remembers")]
        for c in chunk("\n".join(lines)):
            day = re.search(r"(\d{4}-\d{2}-\d{2})", c)
            out.append(Piece(kind, c.splitlines()[0].lstrip("-*# ").strip()[:120], c,
                             where + (" · archive" if archive else ""), at=day.group(1) if day else "",
                             project=project, open={**open_, "archive": archive}))
    return out


def project_sources(root: str | Path) -> list[Source]:
    """A project's memory, its plan (the settled choices and answers first) and its tasks."""
    from . import memory
    from .search import project_name

    root = Path(root).resolve()
    name, pid, h = project_name(root), pid_of(root), root / ".harness"
    mem = memory.project_path(root)

    def read_memory() -> list[Piece]:
        return _memory_pieces(mem, f"{name} · Memory", "memory", pid, {"room": "memory", "path": str(root)})

    def read_plan() -> list[Piece]:
        out: list[Piece] = []
        opened = {"room": "project", "path": str(root), "tab": "plan"}
        try:
            doc = json.loads(_read(h / "plan.json") or "null") or {}
        except ValueError:
            doc = {}
        for d in doc.get("decisions") or [] if isinstance(doc, dict) else []:
            if not isinstance(d, dict) or not d.get("chosen"):
                continue
            label = next((o.get("label", "") for o in d.get("options") or [] if o.get("id") == d["chosen"]), "")
            label = label or str(d["chosen"])
            why = f" Why: {d['why']}" if d.get("why") else ""
            out.append(Piece("decision", f"Decided: {d.get('question', '')}"[:160],
                             f"Decided: {d.get('question', '')} – {label}.{why}", f"{name} · Plan",
                             project=pid, open=opened))
        for q in doc.get("questions") or [] if isinstance(doc, dict) else []:
            if isinstance(q, dict) and str(q.get("answer") or "").strip():
                out.append(Piece("answer", f"Answered: {q.get('text', '')}"[:160],
                                 f"Answered: {q.get('text', '')} – {q['answer']}", f"{name} · Plan",
                                 project=pid, open=opened))
        plan = _read(h / "plan.md")
        title = next((ln.lstrip("# ").strip() for ln in plan.splitlines() if ln.startswith("#")), "The plan")
        for c in chunk(plan):
            out.append(Piece("plan", title[:120], c, f"{name} · Plan", project=pid, open=opened))
        return out

    def read_tasks() -> list[Piece]:
        try:
            tasks = json.loads(_read(h / "tasks.json") or "[]")
        except ValueError:
            tasks = []
        out: list[Piece] = []
        for t in tasks if isinstance(tasks, list) else []:
            if not isinstance(t, dict) or not str(t.get("summary") or "").strip():
                continue
            title = f"Task {t.get('id', '')}: {t.get('title') or ''}".strip()
            body = f"{title}. What was done: {t['summary']}"
            for c in chunk(body):
                out.append(Piece("task", title[:120], c, f"{name} · Tasks", at=str(t.get("finished_at") or "")[:19],
                                 project=pid, open={"room": "project", "path": str(root), "tab": "plan",
                                                    "task": str(t.get("id") or "")}))
        return out

    return [Source(f"memory:{pid}", read_memory, _mtime(mem, memory.archive_of(mem))),
            Source(f"plan:{pid}", read_plan, _mtime(h / "plan.json", h / "plan.md")),
            Source(f"tasks:{pid}", read_tasks, _mtime(h / "tasks.json"))]


def machine_sources(home: str | Path) -> list[Source]:
    """This computer's memory and each agent's own memory."""
    from . import memory

    home = Path(home)
    mem = memory.machine_path(home)
    out = [Source("memory:machine", lambda: _memory_pieces(mem, "This computer · Memory", "memory", "",
                                                           {"room": "memory", "machine": True}),
                  _mtime(mem, memory.archive_of(mem)))]
    agents = home / "agents"
    for f in sorted(agents.glob("*/memory.md")) if agents.is_dir() else []:
        aid = f.parent.name
        if aid.startswith("."):
            continue

        def read_agent(f: Path = f, aid: str = aid) -> list[Piece]:
            who = _agent_name(f.parent) or aid
            return [Piece("agent", f"{who} remembers", c, f"{who} · Agent's memory", open={"room": "agent", "id": aid})
                    for c in chunk(_read(f))]

        out.append(Source(f"agent:{aid}", read_agent, _mtime(f, f.parent / "agent.yaml")))
    return out


def _agent_yaml(folder: Path) -> dict[str, Any]:
    import yaml

    try:
        data = yaml.safe_load(_read(folder / "agent.yaml")) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _agent_name(folder: Path) -> str:
    return str(_agent_yaml(folder).get("name") or "").strip()


def document_sources(home: str | Path) -> list[Source]:
    out = []
    for d in docs.all_documents(home):
        def read_doc(d: dict[str, Any] = d) -> list[Piece]:
            pieces: list[Piece] = []
            folder = d.get("kind") == "folder"
            for name, f in docs.files_of(home, d):
                title = f"{d['title']} · {name}" if folder else d["title"]
                text = docs.read_text(f)
                for c in chunk(text) or [title]:
                    pieces.append(Piece("document", title[:160], c, f"Your documents · {d['title']}",
                                        at=str(d.get("added_at") or "")[:10], doc=d["id"],
                                        doc_projects=d.get("projects", "all"), private=bool(d.get("private")),
                                        open={"room": "document", "id": d["id"], "file": name if folder else ""}))
            return pieces

        out.append(Source(f"doc:{d['id']}", read_doc, docs.stamp(home, d)))
    return out


def hub_sources(hub, me: str | None, names: dict[str, str] | None = None) -> list[Source]:
    """The journal (each seat the owner may read), the owner's letters and the saved notes."""
    if hub is None:
        return []
    names = dict(names or {})
    out: list[Source] = []
    for agent in list(getattr(hub.config, "agents", {}) or {}):
        def read_journal(agent: str = agent) -> list[Piece]:
            try:
                entries = hub.journal.entries(me or agent, agent)
            except Exception:  # noqa: BLE001 - not allowed or unreadable: nothing
                return []
            who = names.get(agent) or agent
            pieces = []
            for e in entries:
                body = " \n".join(str(e.get(k) or "") for k in ("text", "details", "closed_note"))
                body += " " + " ".join(str(x) for x in e.get("next") or [])
                title = re.sub(r"\s+", " ", str(e.get("text") or "")).strip()[:100] or "Entry"
                for c in chunk(body):
                    pieces.append(Piece("journal", title, c, f"{who} · Journal", at=str(e.get("created_at") or "")[:19],
                                        open={"room": "journal", "agent": agent, "id": str(e.get("id") or "")}))
            return pieces

        out.append(Source(f"journal:{agent}", read_journal, hub=True))
    if me:
        def read_letters() -> list[Piece]:
            try:
                letters = hub.inbox(me, unread_only=False, mark_read=False, limit=0)
            except Exception:  # noqa: BLE001
                return []
            pieces = []
            for m in letters:
                sender = names.get(str(m.get("sender") or "")) or str(m.get("sender") or "someone")
                for c in chunk(f"{m.get('subject') or ''}\n{m.get('body') or ''}"):
                    pieces.append(Piece("letter", str(m.get("subject") or "A letter")[:120], c,
                                        f"Earlier messages · from {sender}", at=str(m.get("created_at") or "")[:19],
                                        open={"room": "letter", "id": str(m.get("id") or ""), "agent": str(m.get("sender") or ""),
                                              "thread": str(m.get("thread_id") or m.get("id") or "")}))
            return pieces

        out.append(Source("letters", read_letters, hub=True))

    def read_notes() -> list[Piece]:
        from .ui import hall

        pieces = []
        try:
            notes = hall.hub_notes(hub)
        except Exception:  # noqa: BLE001
            return []
        for n in notes:
            try:
                text = hall.hub_note(hub, n["name"])["markdown"]
            except Exception:  # noqa: BLE001
                continue
            for c in chunk(text):
                pieces.append(Piece("note", n["title"][:120], c, "My notes", at=str(n.get("at") or "")[:19],
                                    open={"room": "note", "name": n["name"]}))
        return pieces

    out.append(Source("notes", read_notes, hub=True))
    return out


# -- the index ---------------------------------------------------------------------------------------------------
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_LOCK = threading.Lock()
_HUB_SEEN: dict[tuple[str, str], float] = {}


def _lock(path: Path) -> threading.RLock:
    with _LOCKS_LOCK:
        return _LOCKS.setdefault(str(path), threading.RLock())


@dataclass
class Scope:
    """What a search may return. ``projects``: project ids (None: every project); ``machine``: this computer's
    and the agents' memories; ``documents``: "all" or "none"; ``doc_project``: only documents this project may
    use; ``private``: include "Never leaves this computer" documents (only the owner's own search);
    ``hub``: the journal, letters and notes."""
    projects: set[str] | None = None
    machine: bool = True
    documents: str = "all"
    doc_project: str | None = None
    private: bool = True
    hub: bool = True
    kinds: set[str] | None = None

    def allows(self, p: Piece) -> bool:
        if self.kinds is not None and p.kind not in self.kinds:
            return False
        if p.kind == "document":
            if self.documents == "none" or (p.private and not self.private):
                return False
            if self.doc_project is not None and not (p.doc_projects == "all" or self.doc_project in (p.doc_projects or [])):
                return False
            return True
        if p.kind in ("journal", "letter", "note"):
            return self.hub
        if p.project:
            return self.projects is None or p.project in self.projects
        return self.machine


class Index:
    def __init__(self, home: str | Path | None = None):
        if home is None:
            from .desktop import app_home

            home = app_home()
        self.home = Path(home)
        self.path = self.home / DIR / INDEX
        self.lock = _lock(self.path)

    def _db(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(self.path), timeout=30)
        db.execute("PRAGMA journal_mode=WAL")
        v = db.execute("PRAGMA user_version").fetchone()[0]
        if v != SCHEMA:
            for t in ("sources", "pieces", "postings"):
                db.execute(f"DROP TABLE IF EXISTS {t}")
            db.executescript("""
                CREATE TABLE sources (key TEXT PRIMARY KEY, stamp TEXT);
                CREATE TABLE pieces (id INTEGER PRIMARY KEY, key TEXT, kind TEXT, title TEXT, place TEXT, text TEXT,
                    at TEXT, project TEXT, doc TEXT, doc_projects TEXT, private INTEGER, open TEXT, length INTEGER);
                CREATE INDEX pieces_key ON pieces(key);
                CREATE TABLE postings (term TEXT, piece INTEGER, tf INTEGER);
                CREATE INDEX postings_term ON postings(term);
                CREATE INDEX postings_piece ON postings(piece);
            """)
            db.execute(f"PRAGMA user_version={SCHEMA}")
            db.commit()
        return db

    # -- keeping it up to date --------------------------------------------------------------------------------
    def refresh(self, sources: Iterable[Source], prune: bool = False, force: bool = False) -> dict[str, int]:
        """Read again the sources that changed. ``prune``: forget sources not in ``sources`` (a full set)."""
        sources = list(sources)
        counts = {"read": 0, "kept": 0, "gone": 0}
        with self.lock:
            db = self._db()
            try:
                known = dict(db.execute("SELECT key, stamp FROM sources").fetchall())
                for s in sources:
                    if s.hub and not force and known.get(s.key) is not None:
                        last = _HUB_SEEN.get((str(self.path), s.key), 0.0)
                        if time.monotonic() - last < HUB_EVERY:
                            counts["kept"] += 1
                            continue
                    if s.stamp is not None and known.get(s.key) == s.stamp and not force:
                        counts["kept"] += 1
                        continue
                    try:
                        pieces = s.read()
                    except Exception:  # noqa: BLE001 - one unreadable source never stops the rest
                        pieces = []
                    stamp = s.stamp if s.stamp is not None else hashlib.sha1(json.dumps(
                        [(p.title, p.text, p.at) for p in pieces], ensure_ascii=False).encode()).hexdigest()
                    if s.hub:
                        _HUB_SEEN[(str(self.path), s.key)] = time.monotonic()
                    if known.get(s.key) == stamp and not force:
                        counts["kept"] += 1
                        continue
                    self._forget(db, s.key)
                    for p in pieces:
                        self._add(db, s.key, p)
                    db.execute("INSERT OR REPLACE INTO sources (key, stamp) VALUES (?, ?)", (s.key, stamp))
                    counts["read"] += 1
                if prune:
                    keep = {s.key for s in sources}
                    for key in set(known) - keep:
                        self._forget(db, key)
                        db.execute("DELETE FROM sources WHERE key = ?", (key,))
                        counts["gone"] += 1
                db.commit()
            finally:
                db.close()
        return counts

    @staticmethod
    def _forget(db: sqlite3.Connection, key: str) -> None:
        db.execute("DELETE FROM postings WHERE piece IN (SELECT id FROM pieces WHERE key = ?)", (key,))
        db.execute("DELETE FROM pieces WHERE key = ?", (key,))

    @staticmethod
    def _add(db: sqlite3.Connection, key: str, p: Piece) -> None:
        toks = tokens(f"{p.title} {p.text}")
        cur = db.execute(
            "INSERT INTO pieces (key, kind, title, place, text, at, project, doc, doc_projects, private, open, length)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (key, p.kind, p.title, p.where, p.text, p.at, p.project, p.doc, json.dumps(p.doc_projects),
             int(p.private), json.dumps(p.open, ensure_ascii=False), max(1, len(toks))))
        db.executemany("INSERT INTO postings (term, piece, tf) VALUES (?, ?, ?)",
                       [(t, cur.lastrowid, n) for t, n in Counter(toks).items()])

    def count(self) -> int:
        with self.lock:
            db = self._db()
            try:
                return int(db.execute("SELECT COUNT(*) FROM pieces").fetchone()[0])
            finally:
                db.close()

    # -- looking ---------------------------------------------------------------------------------------------
    def query_terms(self, db: sqlite3.Connection, query: str) -> dict[str, float]:
        """Each term to look for and how much it counts: the words (1), related words, then look-alikes."""
        want: dict[str, float] = {}
        words = list(dict.fromkeys(tokens(query)))
        for w in words:
            want[w] = 1.0
        vocab = None
        for w in words:
            for r in related(w):
                want.setdefault(r, RELATED_WEIGHT)
            if len(w) >= 4:
                if vocab is None:
                    vocab = [t for (t,) in db.execute("SELECT DISTINCT term FROM postings")]
                near = sorted(((likeness(w, t), t) for t in vocab if t != w and abs(len(t) - len(w)) <= 4
                               and t[:1] == w[:1]), reverse=True)
                for sim, t in near[:3]:
                    if sim >= LIKE_MIN:
                        want.setdefault(t, LIKE_WEIGHT * sim)
        return want

    def find(self, query: str, scope: Scope | None = None, limit: int = 8) -> list[Piece]:
        scope = scope or Scope()
        with self.lock:
            db = self._db()
            try:
                want = self.query_terms(db, query)
                if not want:
                    return []
                n_all = int(db.execute("SELECT COUNT(*) FROM pieces").fetchone()[0]) or 1
                avg = float(db.execute("SELECT AVG(length) FROM pieces").fetchone()[0] or 1)
                scores: dict[int, float] = defaultdict(float)
                matched: dict[int, set[str]] = defaultdict(set)
                lengths: dict[int, int] = {}
                for term, weight in want.items():
                    rows = db.execute("SELECT p.piece, p.tf, x.length FROM postings p JOIN pieces x ON x.id = p.piece"
                                      " WHERE p.term = ?", (term,)).fetchall()
                    if not rows:
                        continue
                    idf = math.log(1 + (n_all - len(rows) + 0.5) / (len(rows) + 0.5))
                    for pid, tf, length in rows:
                        lengths[pid] = length
                        k1, b = 1.2, 0.75
                        scores[pid] += weight * idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / avg))
                        matched[pid].add(term)
                if not scores:
                    return []
                ids = sorted(scores, key=lambda i: -scores[i])[:max(200, limit * 20)]
                marks = ",".join("?" * len(ids))
                rows = db.execute(f"SELECT id, kind, title, place, text, at, project, doc, doc_projects, private, open"
                                  f" FROM pieces WHERE id IN ({marks})", ids).fetchall()
            finally:
                db.close()
        top = max(scores.values())
        out = []
        for r in rows:
            p = Piece(r[1], r[2], r[4], r[3], at=r[5] or "", project=r[6] or "", doc=r[7] or "",
                      doc_projects=json.loads(r[8] or '"all"'), private=bool(r[9]), open=json.loads(r[10] or "{}"),
                      id=r[0])
            if not scope.allows(p):
                continue
            p.score = scores[r[0]] / top + KIND_WEIGHT.get(p.kind, 0.0) * (scores[r[0]] / top)
            out.append(p)
        out.sort(key=lambda p: (-p.score, p.at and -_stamp(p.at) or 0, p.where))
        return out[:max(1, int(limit))]


def _stamp(ts: str) -> float:
    from datetime import datetime

    for fmt, n in (("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(ts[:n], fmt).timestamp()
        except ValueError:
            continue
    return 0.0


# -- the settings ---------------------------------------------------------------------------------------------
DEFAULTS = {"enabled": True, "model": "", "embeddings": ""}


def settings(cfg: Any = None) -> dict[str, Any]:
    """``recall:`` in harness.yaml: ``enabled`` (look_up for the agents), ``model`` (the one ``ask`` uses;
    otherwise the cheapest chat model in the roles) and ``embeddings`` (a maker's embeddings: read, but not
    built yet – the index stays on this computer)."""
    from .harness.config import section

    out = dict(DEFAULTS)
    if cfg is not None:
        out.update({k: v for k, v in section(cfg, "recall").items() if k in DEFAULTS})
    out["enabled"] = bool(out["enabled"])
    return out


# -- the owner's search ---------------------------------------------------------------------------------------
def all_sources(projects: Iterable[str | Path] = (), home: str | Path | None = None, hub=None, me: str | None = None,
                names: dict[str, str] | None = None) -> list[Source]:
    idx_home = Index(home).home
    out: list[Source] = []
    for r in projects:
        if Path(r).is_dir():
            out += project_sources(r)
    return out + machine_sources(idx_home) + document_sources(idx_home) + hub_sources(hub, me, names)


def find(query: str, projects: Iterable[str | Path] = (), home: str | Path | None = None, hub=None,
         me: str | None = None, names: dict[str, str] | None = None, limit: int = 12,
         scope: Scope | None = None) -> dict[str, Any]:
    """The owner's search by meaning across everything on this computer: {query, pieces, words, name}."""
    query = str(query or "").strip()
    if not tokens(query):
        return {"query": query, "pieces": [], "name": NAME, "words": "Write what you're looking for."}
    idx = Index(home)
    idx.refresh(all_sources(projects, idx.home, hub, me, names), prune=True)
    found = idx.find(query, scope or Scope(), limit)
    return {"query": query, "pieces": [p.view() for p in found], "name": NAME,
            "words": f"{len(found)} found." if found else "Nothing found. Try other words."}


# -- for the agents: look_up ----------------------------------------------------------------------------------
def for_project(root: str | Path, query: str, home: str | Path | None = None, setting: str = "all",
                limit: int = LOOKUP_PIECES, chars: int = LOOKUP_CHARS) -> list[Piece]:
    """What an agent working on this project may look up: this project's own memory, plan and tasks, this
    computer's memory and the agents' memories, and the documents the project may use (never a private one)."""
    idx = Index(home)
    pid = pid_of(root)
    srcs = project_sources(root) + machine_sources(idx.home)
    if setting != "none":
        srcs += document_sources(idx.home)
    idx.refresh(srcs)
    scope = Scope(projects={pid}, machine=True, documents="none" if setting == "none" else "all", doc_project=pid,
                  private=False, hub=False)
    out, used = [], 0
    for p in idx.find(query, scope, limit):
        if p.private:  # checked twice: a private document never reaches a model
            continue
        if used + len(p.text) > chars:
            room = chars - used
            if room < 200:
                break
            p.text = p.text[:room].rstrip() + "…"
        used += len(p.text)
        out.append(p)
    return out


def lookup_text(pieces: list[Piece]) -> str:
    if not pieces:
        return "Nothing found for that. Don't guess: say what you couldn't find, or ask in your summary."
    return "\n\n".join(f"[{i}] {p.source_line()} – {p.title}\n{p.text}" for i, p in enumerate(pieces, 1))


# -- asking ---------------------------------------------------------------------------------------------------
def _chat_models(cfg: Any) -> list[Any]:
    out = []
    for r in (getattr(cfg, "roles", {}) or {}).values():
        if getattr(r, "kind", "chat") == "chat":
            out += [m for m in r.models if m not in out]
    return out


def answer_model(cfg: Any) -> Any:
    """The model ``ask`` uses: ``recall.model``, else the cheapest priced chat model in the roles."""
    from .harness.config import ModelRef
    from .providers.base import Usage

    chosen = str(settings(cfg).get("model") or "").strip()
    if chosen:
        try:
            return ModelRef.parse(chosen)
        except ValueError:
            pass
    models = _chat_models(cfg)
    if not models:
        return None

    def price(m: Any) -> float:
        c = cfg.cost(m, Usage(input_tokens=1000, output_tokens=1000))
        return math.inf if c is None else c

    return min(models, key=price)


def may_send(piece: Piece, ref: Any, values_of: Callable[[str], dict[str, Any] | None]) -> bool:
    """May this piece go to this model? Never a private document; a project's piece only to a model the project
    allows; a document kept to some projects only to a model every one of them allows."""
    from .harness import makers

    if piece.private:
        return False
    if piece.project:
        return makers.allowed(values_of(piece.project), ref)
    if piece.kind == "document" and isinstance(piece.doc_projects, list):
        return all(makers.allowed(values_of(p), ref) for p in piece.doc_projects)
    return True


ASK_SYSTEM = ("You answer the owner's question from the numbered pieces below, which come from their own projects, "
              "memories and documents. Use only what the pieces say. Quote the exact words you rely on, each with "
              "the number of its piece. If the pieces don't answer it, say so plainly. Plain, short British English. "
              "Call submit_answer once.")


def _ask_prompt(question: str, pieces: list[Piece]) -> str:
    body = "\n\n".join(f"[{i}] {p.source_line()} – {p.title}\n{p.text}" for i, p in enumerate(pieces, 1))
    return f"# The owner's question\n{question}\n\n# Pieces\n{body}"


def estimate(cfg: Any, ref: Any, prompt: str) -> float | None:
    from .providers.base import Usage

    return cfg.cost(ref, Usage(input_tokens=len(ASK_SYSTEM + prompt) // 4 + 300, output_tokens=500))


def ask(cfg: Any, question: str, projects: Iterable[str | Path] = (), home: str | Path | None = None, hub=None,
        me: str | None = None, names: dict[str, str] | None = None, confirm: bool = False,
        values_of: Callable[[str], dict[str, Any] | None] | None = None, on_use: Any = None,
        max_usd: float | None = None) -> dict[str, Any]:
    """Answer ``question`` from the best pieces. Without ``confirm``: the price first (nothing is sent). With it:
    one call to the answer model with only the pieces it may see; ``{answer, quotes: [{text, source, open}],
    pieces, held, price_usd, cost_usd, model, words}``. With no model allowed, the pieces as they are."""
    from .harness.agent import Budget, run_agent
    from .harness.tools import Tool, Toolbox
    from .providers.base import ToolSpec

    question = str(question or "").strip()
    projects = [Path(p).resolve() for p in projects]
    if values_of is None:
        from .harness import projectsettings as ps

        by_id = {pid_of(r): r for r in projects}

        def values_of(pid: str) -> dict[str, Any] | None:
            r = by_id.get(pid)
            if r is None:
                return {"makers_allowed": ["(unknown project)"]}  # a project not registered here: nothing goes
            st = ps.load(r)
            return {"makers_allowed": ["(settings with a mistake)"]} if st.errors else st.values

    idx = Index(home)
    pieces: list[Piece] = []
    if tokens(question):
        idx.refresh(all_sources(projects, idx.home, hub, me, names), prune=True)
        pieces = idx.find(question, Scope(), ASK_PIECES)
    ref = answer_model(cfg) if cfg is not None else None
    base = {"question": question, "pieces": [p.view() for p in pieces], "name": NAME}
    if not pieces:
        return {**base, "answer": "", "quotes": [], "held": 0, "price_usd": 0.0, "cost_usd": 0.0, "model": "",
                "words": "Nothing found to answer that from. Try other words."}
    sendable = [p for p in pieces if ref is not None and may_send(p, ref, values_of)]
    held = len(pieces) - len(sendable)
    model = str(ref or "")
    if not sendable:
        return {**base, "answer": "", "quotes": [], "held": held, "price_usd": 0.0, "cost_usd": 0.0, "model": model,
                "words": "No model may see these, so here they are as they are."}
    prompt = _ask_prompt(question, sendable)
    price = estimate(cfg, ref, prompt)
    held_words = f" {held} piece{'s' if held != 1 else ''} stay{'s' if held == 1 else ''} on this computer." if held else ""
    if not confirm:
        return {**base, "answer": "", "quotes": [], "held": held, "price_usd": price, "cost_usd": 0.0, "model": model,
                "words": ("About " + (f"${price:.4f}" if price is not None else "an unknown price")
                          + f" to answer from {len(sendable)} pieces.{held_words}")}
    got: dict[str, Any] = {}

    def submit(args: dict[str, Any]) -> str:
        got.update(args)
        return "answer recorded"

    box = Toolbox()
    box.add(Tool(ToolSpec("submit_answer", "Give the answer and the quotes it rests on.", {
        "type": "object", "required": ["answer"], "properties": {
            "answer": {"type": "string"},
            "quotes": {"type": "array", "items": {"type": "object", "required": ["piece", "text"], "properties": {
                "piece": {"type": "integer", "description": "the piece's number"},
                "text": {"type": "string", "description": "the exact words quoted"}}}}}}), submit, terminal=True))
    limit = max_usd if max_usd is not None else max(0.05, 3 * (price or 0.0))
    res = run_agent(cfg, ref, ASK_SYSTEM, prompt, box, Budget(limit, on_use=on_use), max_steps=3, max_tokens=1500,
                    require_terminal="submit_answer", role="(search)")
    quotes = []
    for q in got.get("quotes") or []:
        try:
            p = sendable[int(q.get("piece")) - 1]
        except (TypeError, ValueError, IndexError):
            continue
        quotes.append({"text": str(q.get("text") or "")[:600], "source": p.source_line(), "title": p.title,
                       "open": p.open, "found": str(q.get("text") or "").strip()[:60].lower() in p.text.lower()})
    return {**base, "answer": str(got.get("answer") or res.text or "").strip(), "quotes": quotes, "held": held,
            "price_usd": price, "cost_usd": round(res.cost_usd, 6), "model": model,
            "words": "Answered from your own things." + held_words}


# -- the memory picture: who knows what ----------------------------------------------------------------------------
def _jsonl(p: Path) -> list[dict[str, Any]]:
    out = []
    for ln in _read(p).splitlines():
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def graph(projects: Iterable[str | Path] = (), home: str | Path | None = None, hub=None,
          names: dict[str, str] | None = None, topics: int = 6) -> dict[str, Any]:
    """Who knows what: {nodes: [{id, kind, label, weight}], edges: [{from, to, kind, count, words}], sentence,
    lines}. Nodes: named agents, projects, documents, the busiest topics. Edges: who built in which project
    (metrics), who checked whose work (reviews.jsonl), which project used which document (recall.jsonl), the
    hub's letters between seats. Numbers and names only."""
    from .search import project_name

    home = Index(home).home
    agent_names: dict[str, str] = {}
    agents = home / "agents"
    for f in sorted(agents.glob("*/agent.yaml")) if agents.is_dir() else []:
        agent_names[f.parent.name] = _agent_name(f.parent) or f.parent.name
    nodes: dict[str, dict[str, Any]] = {}
    edges: Counter = Counter()
    topic_count: Counter = Counter()

    def node(nid: str, kind: str, label: str) -> str:
        n = nodes.setdefault(nid, {"id": nid, "kind": kind, "label": label, "weight": 0})
        n["weight"] += 1
        return nid

    def who(agent: str, role: str) -> tuple[str, str]:
        if agent:
            return f"agent:{agent}", agent_names.get(agent) or agent
        from .routing import job_name

        return f"job:{role or 'builder'}", job_name(role or "builder")

    doc_titles = {d["id"]: d["title"] for d in docs.all_documents(home)}
    for r in projects:
        root = Path(r).resolve()
        h = root / ".harness"
        if not h.is_dir():
            continue
        proj = f"project:{pid_of(root)}"
        nodes.setdefault(proj, {"id": proj, "kind": "project", "label": project_name(root), "weight": 0})
        built_by: dict[str, str] = {}
        for row in _jsonl(h / "metrics.jsonl"):
            nid, label = who(str(row.get("agent") or ""), str(row.get("role") or ""))
            node(nid, "agent" if nid.startswith("agent:") else "job", label)
            nodes[proj]["weight"] += 1
            edges[(nid, proj, "built")] += 1
            built_by[str(row.get("task") or "")] = nid
            for t in row.get("tags") or []:
                topic_count[str(t)] += 1
        checker = next((f"agent:{a}" for a, f in _hired(home, "checker")), "")
        for row in _jsonl(h / "reviews.jsonl"):
            if row.get("kind") != "verdict":
                continue
            src = checker or "job:reviewer"
            node(src, "agent" if checker else "job", agent_names.get(checker[6:], "") if checker else "Reviewer")
            dst = built_by.get(str(row.get("task") or "")) or who("", str(row.get("role") or ""))[0]
            if dst not in nodes:
                node(dst, "job", who("", str(row.get("role") or ""))[1])
            edges[(src, dst, "checked")] += 1
        for row in _jsonl(h / LOG):
            for d in row.get("docs") or []:
                if d in doc_titles:
                    did = f"doc:{d}"
                    node(did, "document", doc_titles[d])
                    edges[(proj, did, "used")] += 1
    for tag, n in topic_count.most_common(max(0, topics)):
        tid = f"topic:{tag}"
        nodes[tid] = {"id": tid, "kind": "topic", "label": tag.replace("_", " "), "weight": n}
    if hub is not None:
        seats = list(getattr(hub.config, "agents", {}) or {})
        for seat in seats:
            try:
                msgs = hub.inbox(seat, unread_only=False, mark_read=False, limit=0)
            except Exception:  # noqa: BLE001 - not readable: no lines for it
                continue
            for m in msgs:
                sender = str(m.get("sender") or "")
                if not sender or sender == seat:
                    continue
                a = node(f"seat:{sender}", "seat", (names or {}).get(sender) or sender)
                b = node(f"seat:{seat}", "seat", (names or {}).get(seat) or seat)
                edges[(a, b, "wrote")] += 1
    verbs = {"built": "built in", "checked": "checked the work of", "used": "used", "wrote": "wrote to"}
    edge_list = [{"from": a, "to": b, "kind": k, "count": n,
                  "words": f"{nodes[a]['label']} {verbs[k]} {nodes[b]['label']}" + (f" ({n} times)" if n > 1 else "")}
                 for (a, b, k), n in sorted(edges.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {"nodes": sorted(nodes.values(), key=lambda n: (n["kind"], -n["weight"], n["label"])), "edges": edge_list,
            "sentence": _sentence(nodes, edges), "lines": [e["words"] for e in edge_list]}


def _hired(home: Path, job: str) -> list[tuple[str, Path]]:
    out = []
    agents = home / "agents"
    for f in sorted(agents.glob("*/agent.yaml")) if agents.is_dir() else []:
        data = _agent_yaml(f.parent)
        if data.get("job") == job and data.get("hired") is True:
            out.append((f.parent.name, f))
    return out


def _sentence(nodes: dict[str, dict[str, Any]], edges: Counter) -> str:
    """One plain sentence on top: who built in most projects, and who checked most of the work."""
    built: dict[str, set[str]] = defaultdict(set)
    work: Counter = Counter()
    checked: Counter = Counter()
    for (a, b, k), n in edges.items():
        if k == "built":
            built[a].add(b)
            work[a] += n
        elif k == "checked":
            checked[a] += n
    if not built:
        return "Nothing built yet, so there's no one to show."
    top = max(built, key=lambda a: (len(built[a]), a.startswith("agent:"), work[a], a))  # named agents first
    n = len(built[top])
    out = f"{nodes[top]['label']} has built in {n} project{'s' if n != 1 else ''}"
    if checked:
        c = checked.most_common(1)[0][0]
        share = checked[c] / max(1, sum(checked.values()))
        out += f"; {nodes[c]['label']} checked {'most' if share > 0.5 else 'some'} of it"
    return out + "."


def note_lookup(root: str | Path, task: str, pieces: list[Piece]) -> None:
    """What look_up found, for the picture: numbers and ids only, in the project's .harness/recall.jsonl."""
    from .core.models import utcnow

    row = {"at": utcnow(), "task": str(task or ""), "n": len(pieces),
           "docs": sorted({p.doc for p in pieces if p.doc}), "kinds": sorted({p.kind for p in pieces})}
    try:
        h = Path(root) / ".harness"
        h.mkdir(parents=True, exist_ok=True)
        with open(h / LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass


__all__ = ["Index", "NAME", "Piece", "Scope", "Source", "answer_model", "ask", "chunk", "find", "for_project",
           "graph", "likeness", "lookup_text", "may_send", "note_lookup", "project_sources", "related", "settings",
           "stem", "tokens"]
