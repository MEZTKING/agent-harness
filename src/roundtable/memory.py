"""What Roundtable remembers: a project's memory file and this computer's, kept small without a model.

Each project has ``.harness/memory.md``; this computer has ``memory.md`` in the app's home folder. Both are
plain markdown the owner can edit in the app, in three parts, top to bottom::

    # Memory
    ## Rules (never moved)      what must always or never be done – never trimmed
    ## Pinned facts             facts to keep (the owner's answers, the owner's own lines); capped
    ## Recent                   one dated line per thing learned, newest last

Any other ``## `` part the owner adds is kept as it is and never moved. The computer's file also has
``## Tools found`` (written by ``refresh_machine`` from ``prereq.status``: what this computer can build with,
where the Android SDK is, "no Wine"), rewritten each time it is checked.

When a file grows past its budget (``memory: budget_chars``), the oldest Recent lines move out first, then the
oldest pinned lines past ``memory: pinned_chars``. They move **word for word** to ``memory-archive.md`` beside
it (append only, never read into a prompt, searched by ``search.py``): the archive is written and read back
first, then a check makes sure the new memory.md lost exactly those whole lines and nothing else, and only then
is memory.md swapped in one step. If anything fails, memory.md stays byte for byte as it was.

What goes in: ``learn_from_task`` (a fix that worked after the reviewer turned an attempt down, why a task
failed), ``learn_answer`` (the owner's answers, pinned), ``add_note`` / ``pin`` / ``add_rule`` (anything).
What comes out: ``memory_block(project_root, cfg)``, a short block for the planner's and the workers' prompts
(``memory: block_chars``), rules first, then pinned facts, then the newest notes that fit, then this computer.

Settings (``memory:`` in harness.yaml, all optional): ``enabled`` (true), ``budget_chars`` (12000),
``pinned_chars`` (4000), ``block_chars`` (3000), ``machine`` (true: add this computer's memory to the block).

The regions (rules never moved, capped pinned notes, recent notes moved word for word to an archive that is
searched, a gate that checks memory.md loses only whole lines that were read back) follow Munder Difflin's memory
job (src/main/reflect.ts, src/shared/memoryShape.ts; MIT, Copyright (c) 2026 Chaitanya Giri); the code is
Roundtable's own.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FILE = "memory.md"
ARCHIVE = "memory-archive.md"
TITLE = "# Memory"
RULES = "## Rules (never moved)"
PINNED = "## Pinned facts"
RECENT = "## Recent"
TOOLS = "## Tools found"
INTRO = ("What Roundtable remembers. Edit it freely: Rules never move; old lines move word for word to "
         "memory-archive.md when this gets long.")

DEFAULTS: dict[str, Any] = {"enabled": True, "budget_chars": 12000, "pinned_chars": 4000, "block_chars": 3000,
                            "machine": True}
LINE_CHARS = 400  # one note is at most this long (longer text is cut, with "…")

_LOCK = threading.RLock()


def settings(cfg: Any = None) -> dict[str, Any]:
    """The memory settings, with the defaults filled in (``memory:`` in harness.yaml)."""
    from .harness.config import section

    out = dict(DEFAULTS)
    if cfg is not None:
        for k, v in section(cfg, "memory").items():
            if k in DEFAULTS:
                out[k] = v
    for k in ("budget_chars", "pinned_chars", "block_chars"):
        try:
            out[k] = max(200, int(out[k]))
        except (TypeError, ValueError):
            out[k] = DEFAULTS[k]
    out["enabled"], out["machine"] = bool(out["enabled"]), bool(out["machine"])
    return out


# -- where the files are ---------------------------------------------------------------------
def project_path(root: str | Path) -> Path:
    return Path(root).resolve() / ".harness" / FILE


def machine_path(home: str | Path | None = None) -> Path:
    if home is None:
        from .desktop import app_home

        home = app_home()
    return Path(home) / FILE


def archive_of(path: Path) -> Path:
    return path.with_name(ARCHIVE)


# -- the file's shape ----------------------------------------------------------------------------
@dataclass
class Part:
    heading: str
    lines: list[str] = field(default_factory=list)


@dataclass
class Memory:
    head: list[str] = field(default_factory=list)  # the title and anything before the first "## "
    parts: list[Part] = field(default_factory=list)

    def part(self, heading: str, create: bool = True) -> Part | None:
        for p in self.parts:
            if _same(p.heading, heading):
                return p
        if not create:
            return None
        p = Part(heading)
        order = [RULES, PINNED, TOOLS, RECENT]
        # keep the usual order: rules, pinned, tools, recent; anything else stays where the owner put it
        at = len(self.parts)
        canon = next((x for x in order if _same(x, heading)), None)
        if canon:
            later = order[order.index(canon) + 1:]
            for i, q in enumerate(self.parts):
                if any(_same(q.heading, x) for x in later):
                    at = i
                    break
        self.parts.insert(at, p)
        return p

    def notes(self, heading: str) -> list[str]:
        p = self.part(heading, create=False)
        return [x for x in (p.lines if p else []) if x.strip()]

    def text(self) -> str:
        out = list(self.head)
        for p in self.parts:
            while out and not out[-1].strip():
                out.pop()
            out += ["", p.heading]
            body = list(p.lines)
            while body and not body[-1].strip():
                body.pop()
            while body and not body[0].strip():
                body.pop(0)
            out += body
        return "\n".join(out).strip("\n") + "\n"


def _same(a: str, b: str) -> bool:
    """Headings match on their words (so "## Rules" and "## Rules (never moved)" are one part)."""
    def key(s: str) -> str:
        return re.sub(r"\(.*?\)", "", s.lstrip("#").strip()).strip().lower()
    return key(a) == key(b)


def parse(text: str) -> Memory:
    m = Memory()
    cur: Part | None = None
    for line in (text or "").splitlines():
        if line.startswith("## "):
            cur = Part(line)
            m.parts.append(cur)
        elif cur is None:
            m.head.append(line)
        else:
            cur.lines.append(line)
    return m


def read(path: Path) -> Memory:
    try:
        m = parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        m = Memory()
    if not m.head and not m.parts:
        m.head = [TITLE, "", INTRO]
    return m


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _one_line(text: str) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= LINE_CHARS else s[: LINE_CHARS - 1].rstrip() + "…"


def _bullet(text: str) -> str:
    s = _one_line(text)
    return s if s.startswith(("- ", "* ")) else f"- {s}"


def _bare(line: str) -> str:
    """A note without its bullet and date, for spotting the same note twice."""
    s = re.sub(r"^[-*]\s+", "", _one_line(line))
    return re.sub(r"^\d{4}-\d{2}-\d{2}\s*[·:-]\s*", "", s).strip().lower()


# -- writing ------------------------------------------------------------------------------------------
def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def _add(path: Path, heading: str, text: str, dated: bool, cfg: Any = None) -> bool:
    """Add one line under ``heading`` (not twice); then keep the file within its budget. True when added."""
    if not _one_line(text):
        return False
    with _LOCK:
        m = read(path)
        part = m.part(heading)
        if any(_bare(x) == _bare(text) for x in part.lines if x.strip()):
            return False
        line = _bullet(f"{_today()} · {_one_line(text)}" if dated else text)
        while part.lines and not part.lines[-1].strip():
            part.lines.pop()
        part.lines.append(line)
        _write_atomic(path, m.text())
        trim(path, cfg)
        return True


def add_note(target: str | Path, text: str, cfg: Any = None) -> bool:
    """A dated line under Recent. ``target``: a project folder, or the memory file itself."""
    return _add(_file(target), RECENT, text, True, cfg)


def pin(target: str | Path, text: str, cfg: Any = None) -> bool:
    return _add(_file(target), PINNED, text, False, cfg)


def add_rule(target: str | Path, text: str, cfg: Any = None) -> bool:
    return _add(_file(target), RULES, text, False, cfg)


def _file(target: str | Path) -> Path:
    p = Path(target)
    return p if p.name == FILE else project_path(p)


def save_text(path: Path, text: str, cfg: Any = None) -> dict[str, Any]:
    """The owner's own edit of a whole memory file (from the app); then kept within its budget."""
    with _LOCK:
        body = str(text or "").replace("\r\n", "\n")
        if len(body) > 200_000:
            raise ValueError("That's too long for a memory file. Keep the important lines and try again.")
        _write_atomic(path, body if body.endswith("\n") else body + "\n")
        moved = trim(path, cfg)
    return {"saved": True, "moved": moved}


# -- keeping it small ---------------------------------------------------------------------------------
def trim(path: Path, cfg: Any = None) -> int:
    """Move the oldest lines word for word to the archive until the file is within its budget.

    Recent lines go first (oldest first), then pinned lines past their cap. Rules and the owner's other parts
    never move. Returns how many lines moved (0 when nothing had to, or a step failed and nothing changed)."""
    st = settings(cfg)
    with _LOCK:
        try:
            before = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return 0
        m = parse(before)
        moved: list[tuple[str, str]] = []  # (part, line)

        def size() -> int:
            return len(m.text())

        pinned = m.part(PINNED, create=False)
        if pinned:
            while sum(len(x) + 1 for x in pinned.lines if x.strip()) > st["pinned_chars"]:
                i = next((i for i, x in enumerate(pinned.lines) if x.strip()), None)
                if i is None:
                    break
                moved.append(("Pinned facts", pinned.lines.pop(i)))
        recent = m.part(RECENT, create=False)
        while recent and size() > st["budget_chars"]:
            i = next((i for i, x in enumerate(recent.lines) if x.strip()), None)
            if i is None or len([x for x in recent.lines if x.strip()]) <= 1:
                break  # the newest note always stays
            moved.append(("Recent", recent.lines.pop(i)))
        while pinned and size() > st["budget_chars"]:
            i = next((i for i, x in enumerate(pinned.lines) if x.strip()), None)
            if i is None:
                break
            moved.append(("Pinned facts", pinned.lines.pop(i)))
        if not moved:
            return 0
        after = m.text()
        if not _only_lost(before, after, [line for _, line in moved]):
            return 0
        arch = archive_of(path)
        batch = _batch(moved)
        try:
            old = arch.read_text(encoding="utf-8") if arch.is_file() else ""
            with open(arch, "a", encoding="utf-8", newline="\n") as f:
                if not old:
                    f.write("# Memory archive\n\nLines moved out of memory.md, word for word. Never read into a "
                            "prompt; the app's search finds them.\n")
                f.write(batch)
                f.flush()
                os.fsync(f.fileno())
            if not arch.read_text(encoding="utf-8").endswith(batch):
                return 0
            _write_atomic(path, after)
        except OSError:
            return 0
        return len(moved)


def _batch(moved: list[tuple[str, str]]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = [f"\n## Moved {stamp}"]
    for part in dict.fromkeys(p for p, _ in moved):
        out.append(f"From {part}:")
        out += [line for p, line in moved if p == part]
    return "\n".join(out) + "\n"


def _only_lost(before: str, after: str, lines: list[str]) -> bool:
    """The new file is the old one less exactly these whole lines (blank lines aside)."""
    from collections import Counter

    b = Counter(x for x in before.splitlines() if x.strip())
    a = Counter(x for x in after.splitlines() if x.strip())
    lost = b - a
    return lost == Counter(x for x in lines if x.strip()) and not (a - b)


# -- learning -----------------------------------------------------------------------------------------------
def _first_sentence(text: str, limit: int = 160) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    m = re.match(r"(.+?[.!?])(\s|$)", s)
    s = m.group(1) if m else s
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def lesson(task: Any) -> str:
    """What a finished task taught, in one line ("" when nothing worth keeping): a fix that worked after the
    reviewer turned an attempt down, or why it failed."""
    d = task if isinstance(task, dict) else getattr(task, "__dict__", {})
    title = str(d.get("title") or d.get("id") or "a task")
    attempts = [a for a in d.get("attempts") or [] if isinstance(a, dict)]
    rejected = [a for a in attempts if a.get("outcome") == "rejected" and a.get("review")]
    status = str(d.get("status") or "")
    if status in ("done", "approved") and rejected:
        worked = next((a for a in reversed(attempts) if a.get("outcome") == "approved"), {})
        fix = _first_sentence(worked.get("summary") or d.get("summary") or "")
        return (f"{title}: the reviewer first said \"{_first_sentence(rejected[-1]['review'])}\""
                + (f" What worked: {fix}" if fix else ""))
    if status == "failed" and attempts:
        last = attempts[-1]
        why = _first_sentence(last.get("review") or last.get("error") or last.get("outcome") or "")
        return f"{title} didn't get done: {why}" if why else ""
    return ""


def learn_from_task(project_root: str | Path, task: Any, cfg: Any = None) -> str:
    """After each task: keep what it taught under Recent. Returns the line added ("" when none)."""
    if not settings(cfg)["enabled"]:
        return ""
    line = lesson(task)
    return line if line and add_note(project_root, line, cfg) else ""


def learn_answer(project_root: str | Path, question: str, answer: str, cfg: Any = None) -> bool:
    """The owner's answer to a question, pinned: answers are decisions and shouldn't fade."""
    if not settings(cfg)["enabled"] or not str(answer or "").strip():
        return False
    q = _first_sentence(question, 140).rstrip("?") or "A question"
    return pin(project_root, f"You answered \"{q}?\": {_one_line(answer)[:200]}", cfg)


# -- this computer -----------------------------------------------------------------------------------------------
def machine_facts(rows: Iterable[dict[str, Any]], os_name: str | None = None,
                  which=shutil.which) -> list[str]:
    """What this computer can build with, as short lines (from ``prereq.status`` rows)."""
    rows = list(rows)
    os_name = os_name or {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    out = []
    found = [r for r in rows if r.get("state") in ("found", "old")]
    missing = [r for r in rows if r.get("state") not in ("found", "old")]
    for r in found:
        bits = [str(r.get("name") or r.get("id"))]
        if r.get("version"):
            bits.append(str(r["version"]))
        line = " ".join(bits)
        if r.get("where"):
            line += f" at {r['where']}"
        if r.get("state") == "old":
            line += f" (too old: needs {r.get('min_version') or 'a newer one'})"
        out.append(f"- Has {line}")
    if missing:
        out.append("- Not here: " + ", ".join(str(r.get("name") or r.get("id")) for r in missing))
    if os_name != "windows" and not (which("wine") or which("wine64")):
        out.append("- No Wine: Windows programs (.exe) can't be built or tried on this computer")
    if os_name == "linux":
        out.append("- Linux: no Windows or Mac builds here; Android builds need the Android SDK")
    ids = {r.get("id") for r in found}
    if "android" in ids and not which("gradle"):
        out.append("- No system Gradle: Android projects must use their own ./gradlew")
    return out


def refresh_machine(home: str | Path | None = None, rows: list[dict[str, Any]] | None = None,
                    os_name: str | None = None, which=shutil.which) -> Path:
    """Write ``## Tools found`` in this computer's memory from what is here now (the owner's lines stay)."""
    if rows is None:
        from . import prereq

        rows = prereq.status(versions=True)
    path = machine_path(home)
    with _LOCK:
        m = read(path)
        part = m.part(f"{TOOLS} (checked {_today()})")
        part.heading = f"{TOOLS} (checked {_today()})"
        part.lines = machine_facts(rows, os_name, which)
        _write_atomic(path, m.text())
    return path


# -- reading into a prompt --------------------------------------------------------------------------------------
def _block_of(m: Memory, budget: int) -> list[str]:
    """The lines worth a prompt, rules first, newest notes last, within ``budget`` characters."""
    out: list[str] = []
    used = 0

    def take(lines: list[str], newest_first: bool = False) -> list[str]:
        nonlocal used
        kept: list[str] = []
        for line in (reversed(lines) if newest_first else lines):
            line = _one_line(line)
            if used + len(line) + 1 > budget:
                if newest_first:
                    break
                continue
            kept.append(line)
            used += len(line) + 1
        return list(reversed(kept)) if newest_first else kept

    known = (RULES, PINNED, RECENT, TOOLS)
    order = [(m.notes(RULES), "Rules (always follow these):", False),
             (m.notes(PINNED), "Facts:", False)]
    for p in m.parts:
        if p.heading.startswith(TOOLS):
            order.append(([x for x in p.lines if x.strip()], "This computer:", False))
        elif not any(_same(p.heading, k) for k in known):
            order.append(([x for x in p.lines if x.strip()], p.heading.lstrip("# ").strip() + ":", False))
    order.append((m.notes(RECENT), "Recent (newest last):", True))
    for lines, label, newest in order:
        if not lines:
            continue
        used += len(label) + 1
        got = take(lines, newest)
        if got:
            out += [label, *got]
        else:
            used -= len(label) + 1
    return out


def memory_block(project_root: str | Path | None, cfg: Any = None, home: str | Path | None = None) -> str:
    """The short block for the planner's and workers' prompts: the project's memory, then this computer's.

    Within ``memory: block_chars`` (the machine's part gets at most a third); "" when there's nothing or memory
    is off. Put it after the repository's own rules and before the task, e.g.::

        block = memory_block(self.project.root, self.cfg)
        if block: prompt += "\\n\\n" + block
    """
    st = settings(cfg)
    if not st["enabled"]:
        return ""
    budget = st["block_chars"]
    header = ("What Roundtable remembers (from earlier work and the owner; the owner's rules win over "
              "anything else here):")
    machine: list[str] = []
    if st["machine"]:
        try:
            machine = _block_of(read(machine_path(home)), budget // 3)
        except Exception:  # no app home on this computer: no machine memory
            machine = []
    room = budget - len(header) - 1 - sum(len(x) + 1 for x in machine) - (14 if machine else 0)
    proj = _block_of(read(project_path(project_root)), room) if project_root else []
    if not proj and not machine:
        return ""
    lines = [header, *proj]
    if machine:
        lines += ["On this computer:", *[x for x in machine if x != "This computer:"]]
    text = "\n".join(lines)
    return text[:budget]


def view(path: Path) -> dict[str, Any]:
    """The memory file for the app: its text and a plain count of what's in it."""
    m = read(path)
    arch = archive_of(path)
    archived = 0
    if arch.is_file():
        try:
            archived = sum(1 for x in arch.read_text(encoding="utf-8").splitlines() if x.startswith(("- ", "* ")))
        except (OSError, UnicodeDecodeError):
            archived = 0
    text = path.read_text(encoding="utf-8") if path.is_file() else read(path).text()
    counts = {"rules": len(m.notes(RULES)), "pinned": len(m.notes(PINNED)), "recent": len(m.notes(RECENT))}
    words = ", ".join(f"{n} {one if n == 1 else many}" for n, one, many in (
        (counts["rules"], "rule", "rules"), (counts["pinned"], "fact", "facts"),
        (counts["recent"], "recent note", "recent notes")) if n) or "Nothing remembered yet"
    if archived:
        words += f"; {archived} older line{'' if archived == 1 else 's'} kept in the archive"
    return {"markdown": text, "counts": counts, "archived": archived, "words": words, "exists": path.is_file()}


__all__ = [
    "add_note",
    "add_rule",
    "learn_answer",
    "learn_from_task",
    "machine_facts",
    "machine_path",
    "memory_block",
    "pin",
    "project_path",
    "refresh_machine",
    "save_text",
    "settings",
    "trim",
    "view",
]
