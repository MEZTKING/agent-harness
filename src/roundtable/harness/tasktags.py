"""What a task is about: a few words, so the harness can learn which model wins which kind of work (wave 6).

A task's tags join three things, at no cost:

- the planner's work words (``Task.tags``; the fixed list is ``WORK``, others are kept too);
- the languages its files are written in, from their endings (``task.files``);
- ``kind:<id>``, the project's kind (a website, a Godot game…).

The planner also marks a task ``hard`` (often fails the first time; at most a quarter of a plan) or ``risky``
(a mistake would be costly or hard to see). ``trim_hard`` keeps a plan to that quarter.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

WORK = ("layout", "styling", "logic", "data", "api", "game-logic", "graphics", "shaders", "physics", "tests",
        "build", "docs", "refactor", "bugfix", "network", "database", "security")

# a file's ending -> its language (or, for shaders, the kind of work it always is)
LANGUAGES = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript", ".jsx": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".html": "html", ".htm": "html", ".css": "css", ".scss": "css", ".kt": "kotlin",
    ".kts": "kotlin", ".java": "java", ".gd": "gdscript", ".cs": "csharp", ".cpp": "cpp", ".cc": "cpp",
    ".hpp": "cpp", ".h": "cpp", ".c": "c", ".rs": "rust", ".go": "go", ".swift": "swift", ".rb": "ruby",
    ".php": "php", ".lua": "lua", ".sh": "shell", ".ps1": "shell", ".sql": "sql", ".dart": "dart",
    ".glsl": "shaders", ".gdshader": "shaders", ".shader": "shaders", ".hlsl": "shaders", ".wgsl": "shaders",
    ".frag": "shaders", ".vert": "shaders",
}

MAX_TAGS = 6
# plain words for a tag in a sentence ("won 9 of 10 shader tasks")
_WORDS = {"shaders": "shader", "tests": "test", "game-logic": "game logic", "bugfix": "bug fix",
          "api": "API", "docs": "docs", "graphics": "graphics", "physics": "physics", "css": "CSS", "html": "HTML",
          "sql": "SQL", "gdscript": "GDScript", "csharp": "C#", "cpp": "C++"}

PLAN_WORDS = (
    "\n# What each task is about\n"
    "For every task give `tags`: one to three of these words for the kind of work it is: "
    + ", ".join(WORK) + ". "
    "Mark `hard: true` only for work that often fails the first time (at most a quarter of the tasks), and say "
    "why in `why_hard`, in one sentence. Mark `risky: true` where a mistake would be costly or hard to see: "
    "money, signing in, saved data, deleting things, security.\n"
)


def clean(raw: Any) -> list[str]:
    """Short lower-case words, each once, at most MAX_TAGS."""
    if isinstance(raw, str):
        raw = [raw]
    out: list[str] = []
    for t in raw or []:
        w = "-".join(str(t).strip().lower().split())[:30]
        if w and w not in out:
            out.append(w)
    return out[:MAX_TAGS]


def languages(files: Any) -> list[str]:
    """The languages a task's files are written in, from their endings."""
    out: list[str] = []
    for f in files or []:
        lang = LANGUAGES.get(PurePosixPath(str(f).replace("\\", "/")).suffix.lower())
        if lang and lang not in out:
            out.append(lang)
    return out


def kind_tag(orch: Any) -> str:
    """``kind:<id>`` for the project's kind, "" for none (or when it can't be told)."""
    try:
        kind = orch._kind()
    except Exception:  # noqa: BLE001 - the kind is a help here
        return ""
    kid = str(getattr(kind, "id", "") or "").strip().lower()
    return f"kind:{kid}" if kid else ""


def for_task(orch: Any, task: Any) -> list[str]:
    """Every tag of a task: the planner's words (work words first), its languages, the project's kind."""
    own = clean(getattr(task, "tags", None))
    out = [t for t in own if t in WORK] + [t for t in own if t not in WORK]
    for t in languages(getattr(task, "files", None)):
        if t not in out:
            out.append(t)
    kt = kind_tag(orch) if orch is not None else ""
    if kt and kt not in out:
        out.append(kt)
    return out


def words(tag: str) -> str:
    """A tag in plain words: "game-logic" -> "game logic", "kind:website" -> "website"."""
    t = str(tag)
    if t.startswith("kind:"):
        t = t[5:]
    return _WORDS.get(t, t.replace("-", " "))


def max_hard(n: int) -> int:
    """How many of ``n`` tasks may be marked hard: a quarter, and at least one."""
    return max(1, n // 4) if n else 0


def trim_hard(tasks: list[Any]) -> dict[str, Any] | None:
    """Keep the hard mark on the first quarter of the marked tasks only (in plan order); the others lose it
    (their ``why_hard`` too, unless they are risky). Returns the plan's warning, or None when nothing changed."""
    marked = [t for t in tasks if getattr(t, "hard", False)]
    keep = max_hard(len(tasks))
    if len(marked) <= keep:
        return None
    dropped = marked[keep:]
    for t in dropped:
        t.hard = False
        if not getattr(t, "risky", False):
            t.why_hard = ""
    return {"id": "hard:trimmed", "by": "tags", "kind": "hard", "tasks": [t.id for t in dropped],
            "text": (f"The plan marked {len(marked)} of {len(tasks)} tasks as hard. Only the first {keep} keep the "
                     "mark, so the extra builders and checkers go where they matter most.")}
