"""Skills: short written know-how a builder gets when its task is about that thing (wave 7, d4-tools).

A skill is a folder holding ``SKILL.md``: a few lines at the top (name, when to use it, tags) and then the advice,
up to 6,000 characters. Text only: no scripts, no links that are followed, nothing that runs::

    ---
    name: Pytest basics
    when: Writing or fixing Python tests with pytest.
    tags: [tests, python]
    ---
    The advice, in plain words...

Where they live: the ones that come with the app in ``skills/builtin/<id>/`` (ours, written for this harness),
the owner's own in ``<app home>/skills/<id>/``. Switching one off is remembered in ``<app home>/skills/state.json``;
removing one moves it to ``<app home>/skills/.aside/`` (nothing is deleted). Adding one shows its whole text first
and needs the owner's yes (``confirm``), and comes from a file on this computer, never from a web link.

A builder gets at most two skills whose tags meet its task's tags (``harness/tasktags.for_task``), within 3,000
characters together (``pick``); the attempt records which (``harness/skillstage.py``), so the lab can later tell
whether a skill helps.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Callable

import yaml

from .core.models import utcnow

SKILL_FILE = "SKILL.md"
MAX_CHARS = 6000  # one skill's whole file
MAX_TAGS = 8
PICK_MOST = 2  # skills per task
PICK_CHARS = 3000  # all of them together, in the builder's prompt
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)
_LINK = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)


class SkillError(ValueError):
    """A skill can't be read, added or changed (the message is for the owner)."""


@dataclass
class Skill:
    id: str
    name: str
    when: str
    tags: list[str]
    body: str
    source: str = "builtin"  # builtin | own
    folder: str = ""
    enabled: bool = True
    text: str = ""  # the whole file, as the owner sees it before adding it

    def view(self, full: bool = False) -> dict[str, Any]:
        out = {"id": self.id, "name": self.name, "when": self.when, "tags": list(self.tags), "source": self.source,
               "enabled": self.enabled, "chars": len(self.text or self.body)}
        if full:
            out["text"] = self.text
        return out


# -- reading --------------------------------------------------------------------------------------------------
def _clean_tags(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [t for t in re.split(r"[,\s]+", raw) if t]
    out: list[str] = []
    for t in raw or []:
        w = "-".join(str(t).strip().lower().split())[:40]
        if w and w not in out:
            out.append(w)
    return out[:MAX_TAGS]


def parse(text: str, sid: str = "", source: str = "own", folder: str = "") -> Skill:
    """A skill from its SKILL.md text; SkillError (plain words) when it isn't one."""
    if not isinstance(text, str) or not text.strip():
        raise SkillError("The skill's file is empty.")
    if len(text) > MAX_CHARS:
        raise SkillError(f"The skill is {len(text):,} characters long; a skill can have up to {MAX_CHARS:,}. "
                         "Make it shorter, then add it again.")
    if "\x00" in text:
        raise SkillError("That file isn't plain text, so it can't be a skill.")
    m = _FRONT.match(text.replace("\r\n", "\n"))
    if not m:
        raise SkillError("A skill starts with a few lines between --- and --- (name:, when:, tags:), then the advice.")
    try:
        head = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise SkillError(f"The lines at the top of the skill couldn't be read: {e}") from None
    if not isinstance(head, dict):
        raise SkillError("The lines at the top of the skill need to be name:, when: and tags:.")
    name, when = str(head.get("name") or "").strip(), str(head.get("when") or "").strip()
    if not name:
        raise SkillError("The skill needs a name: line at the top.")
    if not when:
        raise SkillError("The skill needs a when: line at the top: when a builder should use it.")
    tags = _clean_tags(head.get("tags"))
    if not tags:
        raise SkillError("The skill needs tags: at the top (like [tests, python]), so it reaches the right tasks.")
    body = m.group(2).strip()
    if len(body) < 40:
        raise SkillError("The skill has almost no advice in it.")
    sid = sid or str(head.get("id") or "") or slug(name)
    if not ID_RE.match(sid):
        raise SkillError(f"The skill's id {sid!r} must be 2 to 40 of a-z, 0-9 and -, starting with a letter.")
    return Skill(id=sid, name=name, when=when, tags=tags, body=body, source=source, folder=folder, text=text)


def slug(name: str) -> str:
    words = re.findall(r"[a-z0-9]+", str(name).lower())
    s = "-".join(words)[:40].strip("-")
    return s if s and s[0].isalpha() else f"skill-{s}"[:40].strip("-")


def builtin_dir() -> Path:
    return Path(str(resources.files("roundtable").joinpath("skills/builtin")))


def _home(home: Path | str | None) -> Path:
    if home:
        return Path(home)
    from .desktop import app_home

    return app_home()


def own_dir(home: Path | str | None = None) -> Path:
    return _home(home) / "skills"


def _state_path(home: Path | str | None) -> Path:
    return own_dir(home) / "state.json"


def _state(home: Path | str | None) -> dict[str, Any]:
    p = _state_path(home)
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def _write_state(home: Path | str | None, data: dict[str, Any]) -> None:
    p = _state_path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_folder(folder: Path, source: str) -> Skill | None:
    f = folder / SKILL_FILE
    try:
        return parse(f.read_text(encoding="utf-8"), sid=folder.name, source=source, folder=str(folder))
    except (OSError, UnicodeDecodeError, SkillError):
        return None


def list_skills(home: Path | str | None = None, problems: list[dict[str, str]] | None = None) -> list[Skill]:
    """Every skill: the built-in ones, then the owner's own (an own skill with a built-in's id replaces it)."""
    off = (_state(home).get("off") or [])
    found: dict[str, Skill] = {}
    for base, source in ((builtin_dir(), "builtin"), (own_dir(home), "own")):
        if not base.is_dir():
            continue
        for d in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
            if not (d / SKILL_FILE).is_file():
                continue
            s = _read_folder(d, source)
            if s is None:
                if problems is not None:
                    problems.append({"where": f"{source}: {d.name}", "problem": "its SKILL.md couldn't be read"})
                continue
            s.enabled = s.id not in off
            found[s.id] = s
    return list(found.values())


def get(sid: str, home: Path | str | None = None) -> Skill:
    for s in list_skills(home):
        if s.id == sid:
            return s
    raise SkillError(f"There's no skill called {sid!r}.")


# -- changing ---------------------------------------------------------------------------------------------------
def preview(source: str | Path) -> Skill:
    """The skill a file (or a folder holding SKILL.md) on this computer would add. Never a web link."""
    s = str(source or "").strip()
    if not s:
        raise SkillError("Choose a skill file (SKILL.md) on this computer.")
    if _LINK.match(s):
        raise SkillError("Skills are added from a file on this computer, not from a web link. Save the file first, "
                         "then add it.")
    p = Path(s).expanduser()
    if p.is_dir():
        p = p / SKILL_FILE
    if not p.is_file():
        raise SkillError(f"There's no skill file at {p}.")
    if p.stat().st_size > MAX_CHARS * 4:
        raise SkillError(f"That file is too big for a skill (up to {MAX_CHARS:,} characters).")
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise SkillError("That file isn't plain text, so it can't be a skill.") from None
    sid = p.parent.name if p.name == SKILL_FILE and ID_RE.match(p.parent.name) else ""
    return parse(text, sid=sid, source="own")


def add(source: str | Path, confirm: Callable[[Skill], bool], home: Path | str | None = None) -> Skill:
    """Add a skill from a file once the owner has read its whole text (``confirm`` gets the Skill, ``.text`` is
    everything that will be added) and said yes. An own skill with the same id is put aside first."""
    s = preview(source)
    if not confirm(s):
        raise SkillError(f"{s.name} wasn't added: it needs your yes after reading it.")
    dest = own_dir(home) / s.id
    if dest.exists():
        _aside(dest, home)
    dest.mkdir(parents=True)
    (dest / SKILL_FILE).write_text(s.text, encoding="utf-8")
    s.folder, s.source = str(dest), "own"
    st = _state(home)
    st["off"] = [x for x in st.get("off") or [] if x != s.id]
    _write_state(home, st)
    return s


def _aside(folder: Path, home: Path | str | None) -> Path:
    aside = own_dir(home) / ".aside" / f"{folder.name}-{utcnow().replace(':', '').replace('-', '')[:15]}"
    n = 1
    while aside.exists():
        aside = aside.with_name(f"{aside.name}-{n}")
        n += 1
    aside.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(folder), str(aside))
    return aside


def remove(sid: str, home: Path | str | None = None) -> dict[str, Any]:
    """Move one of the owner's own skills aside (kept in skills/.aside). A built-in one can only be switched off."""
    s = get(sid, home)
    if s.source == "builtin":
        raise SkillError(f"{s.name} comes with the app: switch it off instead.")
    where = _aside(Path(s.folder), home)
    return {"id": sid, "moved_to": str(where)}


def switch(sid: str, on: bool, home: Path | str | None = None) -> dict[str, Any]:
    get(sid, home)  # it must exist
    st = _state(home)
    off = [x for x in st.get("off") or [] if x != sid]
    if not on:
        off.append(sid)
    st["off"] = sorted(off)
    _write_state(home, st)
    return {"id": sid, "enabled": bool(on)}


# -- for a task ---------------------------------------------------------------------------------------------------
def pick(tags: list[str], home: Path | str | None = None, skills: list[Skill] | None = None,
         most: int = PICK_MOST, chars: int = PICK_CHARS) -> list[Skill]:
    """At most ``most`` switched-on skills whose tags meet ``tags``, the best match first, that fit in ``chars``
    together (a skill that doesn't fit in what's left is skipped; one that fits nowhere is never cut)."""
    want = set(_clean_tags(tags))
    if not want:
        return []
    pool = skills if skills is not None else list_skills(home)
    scored = []
    for s in pool:
        if not s.enabled:
            continue
        hit = len(want & set(s.tags))
        if hit:
            scored.append((-hit, s.id, s))
    out: list[Skill] = []
    room = chars
    for _, _, s in sorted(scored, key=lambda x: (x[0], x[1])):
        size = len(block([s]))
        if size <= room:
            out.append(s)
            room -= size
        if len(out) >= most:
            break
    return out


def block(chosen: list[Skill]) -> str:
    """The skills as the builder reads them."""
    if not chosen:
        return ""
    parts = ["# Know-how for this task (skills)\nUse what fits; your task and the project's own rules come first."]
    for s in chosen:
        parts.append(f"## {s.name}\n_When:_ {s.when}\n\n{s.body}")
    return "\n\n".join(parts) + "\n"
