"""Named agents: a person-like helper the owner keeps, with a name, a face, notes and what it has learned.

Each job (planner, builder, checker, second opinion, designer, artist) can be held by one hired agent. The
agent's notes (the owner's own words) go into the prompt of every task of that job; what it has learned on
earlier work goes in too, where the project allows it (harness/agentstage.py has the privacy rule).

Where they live, in the app's home folder::

    agents/<id>/agent.yaml     name, job, about, notes, traits, hired, built_in, made_at, face
    agents/<id>/face.webp      made by an image model (never drawn in code); until then initials in a ring
    agents/<id>/memory.md      what it has learned (memory.py's format; memory.add_note writes it)
    agents/.removed/<id>-<when>/   a removed agent: moved here, never deleted
    agents/.seeded             the starters already put in (a removed starter doesn't come back)

Starters: one per job, with invented names; their faces are made once and ship in ``ui/static/agents/``.

Sharing: ``export`` makes a ``.rtagent`` file (a zip of text and one picture; memory only when the owner
ticks it) and ``import_file`` reads one back, showing everything first and writing nothing without confirm.
An agent file never carries model choices; anything that isn't text or a picture is refused.
"""

from __future__ import annotations

import base64
import io
import json
import re
import shutil
import stat
import threading
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .core.models import utcnow

JOBS: dict[str, tuple[str, str]] = {
    "planner": ("Planner", "Turns your idea into a plan and splits it into tasks."),
    "builder": ("Builder", "Writes and tests the code for each task."),
    "checker": ("Checker", "Checks every finished task against what it was meant to do."),
    "second_opinion": ("Second opinion", "Reads each new plan and says what it would change."),
    "designer": ("Designer", "Designs the looks for you to choose from."),
    "artist": ("Artist", "Makes the pictures: art, backgrounds and icons."),
}
# the starters: invented names, no real person or brand; the owner can rename them
STARTERS: tuple[dict[str, Any], ...] = (
    {"id": "maelin", "name": "Maelin", "job": "planner", "about": "Calm and thorough; thinks before anyone builds.",
     "traits": ["calm", "thoughtful", "wise"]},
    {"id": "torvic", "name": "Torvic", "job": "builder", "about": "Steady hands; finishes what it starts.",
     "traits": ["steady", "practical", "cheerful"]},
    {"id": "ondra", "name": "Ondra", "job": "checker", "about": "Sharp eyes; quotes exactly what is wrong.",
     "traits": ["sharp", "fair", "watchful"]},
    {"id": "kestrel", "name": "Kestrel", "job": "second_opinion", "about": "Sees the plan from above.",
     "traits": ["curious", "frank", "keen"]},
    {"id": "calla", "name": "Calla", "job": "designer", "about": "Cares how things look and feel.",
     "traits": ["elegant", "warm", "bold"]},
    {"id": "pell", "name": "Pell", "job": "artist", "about": "Paints the pictures your app needs.",
     "traits": ["dreamy", "bright", "gentle"]},
)

NAME_MAX = 40
ABOUT_MAX = 200
NOTES_MAX = 2000
LEARNED_MAX = 1500
TRAITS_MAX = 3
FACE_MAX = 60 * 1024  # a face is kept under 60 KB
FACE_SIDE = 256
FACE_KEEP_MAX = 2 * 1024 * 1024  # without Pillow a paid-for face is kept as it came, up to this
FACE_SHARE_MAX = 200 * 1024  # a face in a shared file
MEMORY_SHARE_MAX = 40 * 1024
TEXT_MAX = 20 * 1024
FILE_SUFFIX = ".rtagent"
SHARE_FILES = {"agent.yaml", "face.webp", "face.png", "face.jpg", "memory.md"}
SHARE_KEYS = ("name", "job", "about", "notes", "traits")
# what an agent file must never bring: model choices and anything that steers the harness
MODEL_KEYS = {"model", "models", "provider", "providers", "fallback", "fallbacks", "role", "roles", "effort",
              "profile", "options", "tools", "commands", "command", "prompt", "system"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_TRAIT = re.compile(r"^[a-z]{2,20}$")
_LOCK = threading.RLock()
# the Eclipse style words (docs/art.md), the same for every face
FACE_STYLE = ("Square 1:1 portrait for an app's avatar, centred head and shoulders of an invented, friendly "
              "character (not a real person, not anyone famous), stylised digital painting. Near-black deep "
              "space background (#0a0a0f) with a faint indigo haze; soft violet-white rim light (lavender "
              "#a78bfa) like an eclipse corona behind the head, one small warm orange accent (#ff9d4d). Calm, "
              "premium, high contrast, readable at 32 pixels. No text, no letters, no logos, no frame, no "
              "watermark, no artist's or brand's style.")
FACE_JOB = {"planner": "a planner holding a softly glowing map", "builder": "a builder with a small glowing tool",
            "checker": "a careful inspector with a small glowing lens",
            "second_opinion": "an advisor with a thoughtful look", "designer": "a designer with a glowing swatch",
            "artist": "a painter with a glowing brush"}


class AgentError(ValueError):
    """A plain-words problem with an agent (shown to the owner as it is)."""


@dataclass
class Agent:
    id: str
    name: str
    job: str
    about: str = ""
    notes: str = ""
    traits: list[str] = field(default_factory=list)
    hired: bool = False
    built_in: bool = False
    made_at: str = ""
    face: dict[str, Any] = field(default_factory=dict)  # {file, model, cost_usd, made_at} once made

    @property
    def job_name(self) -> str:
        return JOBS.get(self.job, (self.job, ""))[0]


# -- where things are -------------------------------------------------------------------------------------------
def agents_dir(home: Path | str) -> Path:
    return Path(home) / "agents"


def removed_dir(home: Path | str) -> Path:
    return agents_dir(home) / ".removed"


def folder(home: Path | str, agent_id: str) -> Path:
    if not ID_RE.match(str(agent_id or "")):
        raise AgentError("That isn't an agent's name the harness knows.")
    return agents_dir(home) / agent_id


def memory_file(home: Path | str, agent_id: str) -> Path:
    return folder(home, agent_id) / "memory.md"


def starter_faces_dir() -> Path:
    return Path(__file__).resolve().parent / "ui" / "static" / "agents"


# -- reading and writing -------------------------------------------------------------------------------------------
def _from(raw: dict[str, Any], agent_id: str) -> Agent | None:
    if not isinstance(raw, dict):
        return None
    job = str(raw.get("job") or "")
    if job not in JOBS:
        return None
    traits = [t for t in (raw.get("traits") or []) if isinstance(t, str)][:TRAITS_MAX]
    face = raw.get("face") if isinstance(raw.get("face"), dict) else {}
    return Agent(id=agent_id, name=str(raw.get("name") or agent_id)[:NAME_MAX], job=job,
                 about=str(raw.get("about") or "")[:ABOUT_MAX], notes=str(raw.get("notes") or "")[:NOTES_MAX],
                 traits=traits, hired=bool(raw.get("hired")), built_in=bool(raw.get("built_in")),
                 made_at=str(raw.get("made_at") or ""), face=dict(face))


def _read(p: Path) -> Agent | None:
    try:
        raw = yaml.safe_load((p / "agent.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return None
    return _from(raw, p.name)


def _write(home: Path | str, agent: Agent) -> Agent:
    p = folder(home, agent.id)
    p.mkdir(parents=True, exist_ok=True)
    body = {k: v for k, v in asdict(agent).items() if k != "id"}
    tmp = p / ".agent.yaml.tmp"
    tmp.write_text(yaml.safe_dump(body, sort_keys=False, allow_unicode=True), encoding="utf-8")
    tmp.replace(p / "agent.yaml")
    return agent


def _seed(home: Path | str) -> None:
    """Put in the starters once; a starter the owner removed doesn't come back."""
    base = agents_dir(home)
    mark = base / ".seeded"
    try:
        done = set(json.loads(mark.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        done = set()
    todo = [s for s in STARTERS if s["id"] not in done]
    if not todo:
        return
    taken = {a.job for a in _all(home) if a.hired}
    for s in todo:
        if not (base / s["id"]).exists():
            _write(home, Agent(id=s["id"], name=s["name"], job=s["job"], about=s["about"], traits=list(s["traits"]),
                               hired=s["job"] not in taken, built_in=True, made_at=utcnow()))
            taken.add(s["job"])
        done.add(s["id"])
    base.mkdir(parents=True, exist_ok=True)
    mark.write_text(json.dumps(sorted(done)) + "\n", encoding="utf-8")


def _all(home: Path | str) -> list[Agent]:
    base = agents_dir(home)
    if not base.is_dir():
        return []
    out = []
    for p in sorted(base.iterdir()):
        if p.is_dir() and not p.name.startswith(".") and ID_RE.match(p.name):
            a = _read(p)
            if a:
                out.append(a)
    return out


def load_all(home: Path | str) -> list[Agent]:
    """Every agent, in the jobs' order, hired first."""
    with _LOCK:
        _seed(home)
        order = {j: i for i, j in enumerate(JOBS)}
        return sorted(_all(home), key=lambda a: (order.get(a.job, 99), not a.hired, a.name.lower()))


def get(home: Path | str, agent_id: str) -> Agent:
    with _LOCK:
        _seed(home)
        a = _read(folder(home, agent_id))
    if not a:
        raise AgentError("There's no agent by that name any more. It may have been removed.")
    return a


def hired_for(home: Path | str, job: str) -> Agent | None:
    return next((a for a in load_all(home) if a.job == job and a.hired), None)


def _slug(name: str, home: Path | str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "agent"
    if not base[0].isalnum():
        base = "a" + base
    out, n = base, 2
    while (agents_dir(home) / out).exists():
        out = f"{base}-{n}"
        n += 1
    return out


def clean_traits(words: Any) -> list[str]:
    """Up to three plain lower-case words (letters only): nothing else of the owner's text reaches a picture."""
    if isinstance(words, str):
        words = re.split(r"[,;\s]+", words)
    out: list[str] = []
    for w in words or []:
        w = str(w).strip().lower()
        if _TRAIT.match(w) and w not in out:
            out.append(w)
        if len(out) == TRAITS_MAX:
            break
    return out


def _check_text(name: str, about: str, notes: str) -> None:
    from .kinds.model import key_shaped

    if not name.strip():
        raise AgentError("Give the agent a name.")
    if len(name) > NAME_MAX:
        raise AgentError(f"Keep the name under {NAME_MAX} characters.")
    if len(about) > ABOUT_MAX:
        raise AgentError(f"Keep the one line about it under {ABOUT_MAX} characters.")
    if len(notes) > NOTES_MAX:
        raise AgentError(f"Keep the notes under {NOTES_MAX:,} characters (they are {len(notes):,} now).")
    if key_shaped("\n".join((name, about, notes))):
        raise AgentError("That has something shaped like a key or a password in it. Take it out and save again.")


def save(home: Path | str, data: dict[str, Any]) -> Agent:
    """Make a new agent (no ``id``) or change one: its name, job, one line about it, notes and trait words.
    ``hire: true`` also hires it for its job."""
    with _LOCK:
        _seed(home)
        agent_id = str(data.get("id") or "")
        old = get(home, agent_id) if agent_id else None
        name = str(data.get("name", old.name if old else "") or "").strip()
        about = str(data.get("about", old.about if old else "") or "").strip()
        notes = str(data.get("notes", old.notes if old else "") or "").replace("\r\n", "\n").strip()
        job = str(data.get("job", old.job if old else "") or "")
        if job not in JOBS:
            raise AgentError("Choose the job this agent does.")
        _check_text(name, about, notes)
        traits = clean_traits(data["traits"]) if "traits" in data else (old.traits if old else [])
        if old:
            a = Agent(**{**asdict(old), "name": name, "about": about, "notes": notes, "job": job, "traits": traits})
            if job != old.job:
                a.hired = False
        else:
            a = Agent(id=_slug(name, home), name=name, job=job, about=about, notes=notes, traits=traits,
                      made_at=utcnow())
        _write(home, a)
        if data.get("hire") is True:
            return hire(home, a.id)
        if data.get("hire") is False and a.hired:
            a.hired = False
            _write(home, a)
        return a


def hire(home: Path | str, agent_id: str) -> Agent:
    """Hire this agent for its job: the one who had that job steps back (kept, not removed)."""
    with _LOCK:
        a = get(home, agent_id)
        for other in _all(home):
            if other.job == a.job and other.hired and other.id != a.id:
                other.hired = False
                _write(home, other)
        a.hired = True
        return _write(home, a)


def remove(home: Path | str, agent_id: str) -> dict[str, Any]:
    """Move the agent's folder to ``agents/.removed/``: nothing is deleted."""
    with _LOCK:
        a = get(home, agent_id)
        src = folder(home, agent_id)
        stamp = re.sub(r"[^0-9T]", "", utcnow())[:15]
        dest, n = removed_dir(home) / f"{agent_id}-{stamp}", 2
        while dest.exists():
            dest = removed_dir(home) / f"{agent_id}-{stamp}-{n}"
            n += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
    return {"removed": a.id, "kept_in": str(dest),
            "reply": f"{a.name} is no longer on the team. Its folder is kept in agents/.removed."}


# -- what it has learned ---------------------------------------------------------------------------------------------
def learned(home: Path | str, agent_id: str, limit: int = LEARNED_MAX) -> str:
    """What the agent has learned, newest first, within ``limit`` characters ("" when nothing)."""
    from . import memory

    p = memory_file(home, agent_id)
    if not p.is_file():
        return ""
    m = memory.read(p)
    lines = [*m.notes(memory.RULES), *m.notes(memory.PINNED)] + list(reversed(m.notes(memory.RECENT)))
    out: list[str] = []
    used = 0
    for line in lines:
        line = line.strip()
        if used + len(line) + 1 > limit:
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)


def learn(home: Path | str, agent_id: str, line: str) -> bool:
    """Keep one lesson in the agent's memory (dated, not twice). True when added."""
    from . import memory

    if not str(line or "").strip():
        return False
    try:
        get(home, agent_id)  # puts the starters in first; a removed agent learns nothing
    except AgentError:
        return False
    return memory.add_note(memory_file(home, agent_id), line)


# -- faces -------------------------------------------------------------------------------------------------------------
def initials(name: str) -> str:
    words = [w for w in re.split(r"[\s_-]+", str(name or "")) if w]
    return ("".join(w[0] for w in words[:2]) or "?").upper()


def face_path(home: Path | str, agent: Agent) -> Path | None:
    """The agent's own face, else a starter's shipped face, else None (the app shows initials)."""
    own = agents_dir(home) / agent.id
    for name in ("face.webp", "face.png", "face.jpg"):
        if (own / name).is_file():
            return own / name
    if agent.built_in:
        p = starter_faces_dir() / f"{agent.id}.webp"
        if p.is_file():
            return p
    return None


def face_prompt(agent: Agent) -> str:
    """The fixed template: the job, up to three trait words the owner typed, and the Eclipse style words.
    Never the agent's name, its notes or anything from a project."""
    traits = clean_traits(agent.traits)
    who = FACE_JOB.get(agent.job, "a helper")
    mood = f", who looks {', '.join(traits[:-1]) + ' and ' + traits[-1] if len(traits) > 1 else traits[0]}" if traits else ""
    return f"{FACE_STYLE} The character: {who}{mood}."


def face_model(cfg: Any) -> tuple[str, Any] | None:
    """The picture job's model: an image role made for art (the illustrator first), not pixel art when
    there's a choice. (role name, ModelRef) or None when no picture job is set up."""
    roles = [(n, r) for n, r in (getattr(cfg, "roles", {}) or {}).items() if r.kind == "image" and r.models]
    if not roles:
        return None

    def rank(item):
        n, r = item
        pixel = "retrodiffusion" in str(r.models[0].provider)
        return (n != "illustrator", pixel, n)

    name, role = sorted(roles, key=rank)[0]
    return name, role.models[0]


def _spend_file(home: Path | str) -> Path:
    return agents_dir(home) / "spend.jsonl"


def face_price(cfg: Any, home: Path | str) -> dict[str, Any]:
    """What one face costs, before anything is made: the real charge of faces made before, else the
    pricing table. ``usd`` is None when the price isn't known (the owner is told and still asked)."""
    from .harness import imageprice
    from .routing import model_label

    got = face_model(cfg)
    if not got:
        return {"ok": False, "usd": None, "model": "",
                "words": "There's no picture job set up yet. Add one in Models (an illustrator) to make faces."}
    _, ref = got
    usd = imageprice.per_image(cfg, ref, [_spend_file(home)])
    label = model_label(str(ref))
    words = (f"A face costs about ${usd:.3f} with {label}." if usd is not None
             else f"The price of a picture from {label} isn't known yet: it is usually a few cents.")
    return {"ok": True, "usd": usd, "model": str(ref), "label": label, "words": words}


def shrink_face(data: bytes) -> tuple[bytes, str] | None:
    """The picture as a square webp under 60 KB (Pillow). Without Pillow (not in every build) it is kept as it
    came, up to 2 MB, so a face already paid for isn't thrown away; None when it isn't a picture."""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 - Pillow is optional
        return (data, _kind_of(data)) if len(data) <= FACE_KEEP_MAX and _kind_of(data) else None
    try:
        im = Image.open(io.BytesIO(data)).convert("RGB")
        w, h = im.size
        s = min(w, h)
        im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
        for side, q in ((FACE_SIDE, 82), (FACE_SIDE, 70), (192, 70), (128, 65)):
            c = im.resize((min(side, s), min(side, s)))
            out = io.BytesIO()
            c.save(out, "WEBP", quality=q, method=4)
            if out.tell() <= FACE_MAX:
                return out.getvalue(), "webp"
    except Exception:  # noqa: BLE001 - one Pillow can't read is kept only when already small and a picture
        return (data, _kind_of(data)) if len(data) <= FACE_MAX and _kind_of(data) else None
    return None


def make_face(cfg: Any, agent: Agent, home: Path | str) -> dict[str, Any]:
    """Ask the picture job's model for this agent's face (square), keep it small, and note what it cost."""
    from .routing import model_label

    got = face_model(cfg)
    if not got:
        raise AgentError("There's no picture job set up yet. Add one in Models (an illustrator) to make faces.")
    role_name, ref = got
    role = cfg.roles[role_name]
    provider = cfg.provider(ref.provider)
    opts = {k: v for k, v in (role.options or {}).items() if k not in ("aspect_ratio", "size", "width", "height")}
    if "retrodiffusion" in str(ref.provider):
        opts.update(width=128, height=128)
    else:
        opts.update(aspect_ratio="1:1", size="1K")
    prompt = face_prompt(agent)
    data, _ext, usage = provider.generate(ref.model, prompt, opts)
    cost = cfg.cost(ref, usage)
    try:
        from .harness import imageprice  # one whole line at a time, safe when several pictures finish at once

        p = _spend_file(home)
        p.parent.mkdir(parents=True, exist_ok=True)
        imageprice.record(p, {"at": utcnow(), "model": str(ref), "cost_usd": round(cost or 0.0, 6),
                              "outcome": "face", "agent": agent.id})
    except OSError:
        pass
    small = shrink_face(data)
    if small is None:
        raise AgentError("The face came back too big to keep on this computer. Try again, or ask for a smaller "
                         "picture size in Models.")
    body, ext = small
    with _LOCK:
        a = get(home, agent.id)
        d = folder(home, a.id)
        for old in ("face.webp", "face.png", "face.jpg"):
            if (d / old).exists() and old != f"face.{ext}":
                (d / old).replace(d / f".{old}.old")  # kept, never deleted
        (d / f"face.{ext}").write_bytes(body)
        a.face = {"file": f"face.{ext}", "model": str(ref), "cost_usd": round(cost, 6) if cost is not None else None,
                  "made_at": utcnow()}
        _write(home, a)
    return {"agent": a.id, "bytes": len(body), "cost_usd": cost, "model": str(ref),
            "reply": f"{a.name} has a face now, made by {model_label(str(ref))}"
                     + (f" for ${cost:.3f}." if cost is not None else ".")}


def _kind_of(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return ""


def data_url(p: Path | None) -> str:
    if not p:
        return ""
    try:
        body = p.read_bytes()
    except OSError:
        return ""
    kind = _kind_of(body)
    mime = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}.get(kind)
    return f"data:{mime};base64,{base64.b64encode(body).decode()}" if mime else ""


def card(home: Path | str, a: Agent, full: bool = False) -> dict[str, Any]:
    """What the app shows: one line first; the notes, the memory and the face's details behind More."""
    words = JOBS[a.job][0] + (" · hired" if a.hired else "")
    out: dict[str, Any] = {"id": a.id, "name": a.name, "job": a.job, "job_name": a.job_name, "about": a.about,
                           "hired": a.hired, "built_in": a.built_in, "initials": initials(a.name),
                           "face": data_url(face_path(home, a)), "traits": list(a.traits), "line": words}
    if full:
        out["notes"] = a.notes
        out["learned"] = learned(home, a.id, limit=20_000)
        out["face_info"] = dict(a.face)
    return out


# -- sharing -------------------------------------------------------------------------------------------------------------
def _share_body(a: Agent) -> dict[str, Any]:
    return {"schema": "rtagent@1", **{k: getattr(a, k) for k in SHARE_KEYS}}


def export_preview(home: Path | str, a: Agent, with_memory: bool = False) -> dict[str, Any]:
    """Exactly what the file would hold, for the owner to see before saving it."""
    face = face_path(home, a)
    files = ["agent.yaml"]
    if face and face.stat().st_size <= FACE_SHARE_MAX:
        files.append(f"face.{_kind_of(face.read_bytes()) or 'webp'}")
    mem = ""
    if with_memory:
        p = memory_file(home, a.id)
        mem = p.read_text(encoding="utf-8") if p.is_file() else ""
        if mem:
            files.append("memory.md")
    return {"files": files, "card": _share_body(a), "memory": mem}


def export(home: Path | str, a: Agent, with_memory: bool = False) -> bytes:
    """The agent as a ``.rtagent`` (a zip): its name, job, notes and trait words, its face, and its memory only
    when ``with_memory``. Never a model choice; refuses to share anything shaped like a key."""
    from .kinds.model import key_shaped

    look = export_preview(home, a, with_memory)
    text = yaml.safe_dump(look["card"], sort_keys=False, allow_unicode=True)
    if key_shaped(text) or (look["memory"] and key_shaped(look["memory"])):
        raise AgentError("Something in it is shaped like a key or a password. Take it out, then share again.")
    if len(look["memory"].encode("utf-8")) > MEMORY_SHARE_MAX:
        raise AgentError("Its memory is too long to share. Share it without the memory, or trim the memory first.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("agent.yaml", text)
        face = face_path(home, a)
        face_name = next((f for f in look["files"] if f.startswith("face.")), "")
        if face and face_name:
            z.writestr(face_name, face.read_bytes())
        if "memory.md" in look["files"]:
            z.writestr("memory.md", look["memory"])
    return buf.getvalue()


def import_file(data: bytes, home: Path | str, confirm: bool = False) -> dict[str, Any]:
    """Read a ``.rtagent``. Without ``confirm`` nothing is written: the answer shows its name, job, the whole
    of its notes and its memory. With ``confirm`` it joins the team (not hired; a new id when the name is
    taken, so nobody is replaced). Model choices in it are dropped and named; anything that isn't text or a
    picture, a link, a path outside the file, or anything shaped like a key refuses the whole file."""
    from .kinds.model import key_shaped

    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError):
        return {"ok": False, "problems": ["This isn't an agent file (.rtagent)."]}
    problems: list[str] = []
    files: dict[str, bytes] = {}
    infos = z.infolist()
    if len(infos) > 8:
        return {"ok": False, "problems": ["It holds too many files for an agent."]}
    for i in infos:
        name = i.filename
        if i.is_dir():
            continue
        if ((i.external_attr >> 16) & 0o170000) == stat.S_IFLNK:
            problems.append(f"{name}: a link to somewhere else isn't allowed")
            continue
        if name not in SHARE_FILES:
            problems.append(f"{name}: an agent file holds only its card, one face and its memory: never code, "
                            "programs or other files")
            continue
        cap = FACE_SHARE_MAX if name.startswith("face.") else MEMORY_SHARE_MAX if name == "memory.md" else TEXT_MAX
        if i.file_size > cap:
            problems.append(f"{name}: it's too big")
            continue
        body = z.read(i)
        if len(body) > cap:
            problems.append(f"{name}: it's too big")
            continue
        if name.startswith("face."):
            if _kind_of(body) != name.split(".", 1)[1]:
                problems.append(f"{name}: it isn't a picture")
                continue
        elif key_shaped(body.decode("utf-8", "replace")):
            problems.append(f"{name}: it has something shaped like a key or a password in it")
            continue
        files[name] = body
    if "agent.yaml" not in files and not problems:
        problems.append("There's no agent.yaml in it.")
    if problems:
        return {"ok": False, "problems": problems}
    try:
        raw = yaml.safe_load(files["agent.yaml"].decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError):
        return {"ok": False, "problems": ["Its agent.yaml couldn't be read."]}
    if not isinstance(raw, dict):
        return {"ok": False, "problems": ["Its agent.yaml couldn't be read."]}
    dropped = sorted(k for k in raw if str(k).lower() in MODEL_KEYS)
    unknown = sorted(k for k in raw if k not in SHARE_KEYS and k != "schema" and k not in dropped)
    name = str(raw.get("name") or "").strip()
    job = str(raw.get("job") or "")
    about = str(raw.get("about") or "").strip()
    notes = str(raw.get("notes") or "").strip()
    if job not in JOBS:
        return {"ok": False, "problems": ["It doesn't say which job the agent does."]}
    try:
        _check_text(name, about, notes)
    except AgentError as e:
        return {"ok": False, "problems": [str(e)]}
    memory_text = files.get("memory.md", b"").decode("utf-8", "replace")
    face_name = next((n for n in files if n.startswith("face.")), "")
    would = {"name": name, "job": job, "job_name": JOBS[job][0], "about": about, "notes": notes,
             "traits": clean_traits(raw.get("traits")), "face": bool(face_name), "memory": memory_text,
             "dropped": dropped, "ignored": unknown}
    if not confirm:
        return {"ok": True, "added": False, "would": would,
                "reply": f"{name} the {JOBS[job][0].lower()} is ready to join. Nothing changes until you say yes."}
    with _LOCK:
        _seed(home)
        a = Agent(id=_slug(name, home), name=name, job=job, about=about, notes=notes, traits=would["traits"],
                  made_at=utcnow())
        _write(home, a)
        d = folder(home, a.id)
        if face_name:
            (d / face_name).write_bytes(files[face_name])
            a.face = {"file": face_name, "model": "", "cost_usd": None, "made_at": utcnow(), "imported": True}
            _write(home, a)
        if memory_text:
            (d / "memory.md").write_text(memory_text, encoding="utf-8")
    return {"ok": True, "added": True, "would": would, "id": a.id,
            "reply": f"{name} joined the team. Hire it in Models → Agents to give it the {JOBS[job][0].lower()}'s job."}


# -- which job a role is --------------------------------------------------------------------------------------------------
def job_of(cfg: Any, role: str) -> str:
    """The agent job a harness role belongs to: the planner, the checker (reviewer), the second opinion
    (critic), the designer, the artist (a picture role); every other chat role is a builder."""
    r = (getattr(cfg, "roles", {}) or {}).get(role)
    if role == getattr(cfg, "planner_role", None):
        return "planner"
    if role == getattr(cfg, "reviewer_role", None):
        return "checker"
    if role and role == getattr(cfg, "critic_role", None):
        return "second_opinion"
    if r is not None and r.kind == "image":
        return "artist"
    if role in ("designer", "stylist") or (role and role == getattr(cfg, "design_role", None)
                                            and role != getattr(cfg, "planner_role", None)):
        return "designer"
    return "builder"
