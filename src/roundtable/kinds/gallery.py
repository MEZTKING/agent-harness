"""The Gallery: everything finished, one record per finished goal (and, beside it, what Roundtable can make).

A record lives at ``<app folder>/gallery/<project>/<goal>/entry.json`` with up to four small pictures beside it
(each at most 200 KB) and a cover of at most 60 KB sent inline. It is written once per finished goal: a re-run
of the same goal keeps the first record and the owner's flags. Hiding never deletes; the Gallery offers no
deletion at all. The private hub gets the same record (without the big pictures) under ``plans/gallery/``, so
the phone sees it in Hub mode.
"""

from __future__ import annotations

import base64
import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

PICTURE_MAX = 200 * 1024
COVER_MAX = 60 * 1024
MAX_PICTURES = 4
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class GalleryError(ValueError):
    pass


def gallery_dir(home: Path | str) -> Path:
    return Path(home) / "gallery"


def safe(name: str) -> str:
    s = _SAFE.sub("-", str(name or "")).strip("-.")[:80]
    return s or "project"


def goal_key(goal_index: int) -> str:
    return f"goal-{int(goal_index) + 1}"


def entry_dir(home: Path | str, project: str, goal: str) -> Path:
    p, g = safe(project), safe(goal)
    if p != project or g != goal:
        raise GalleryError("That gallery entry isn't there.")
    return gallery_dir(home) / p / g


def _read(p: Path) -> dict[str, Any] | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(p: Path, data: dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(p)


# -- pictures ---------------------------------------------------------------------------------------------------------
def _shrink(data: bytes, limit: int, side: int) -> tuple[bytes, str] | None:
    """The picture as a JPEG under ``limit`` bytes (Pillow), or as it is when already small enough; None when
    it can't be made small enough here."""
    try:
        from PIL import Image  # optional
    except Exception:  # noqa: BLE001
        return (data, "png") if len(data) <= limit else None
    try:
        im = Image.open(io.BytesIO(data))
        im = im.convert("RGB")
        for s, q in ((side, 82), (side * 3 // 4, 75), (side // 2, 70), (side // 3, 60)):
            c = im.copy()
            c.thumbnail((s, s))
            out = io.BytesIO()
            c.save(out, "JPEG", quality=q, optimize=True)
            if out.tell() <= limit:
                return out.getvalue(), "jpg"
    except Exception:  # noqa: BLE001 - a broken picture is simply left out
        return (data, "png") if len(data) <= limit else None
    return None


def keep_pictures(folder: Path, sources: list[Path]) -> tuple[list[str], str]:
    """Copy up to four pictures (each ≤ 200 KB) into the entry's folder; returns (file names, cover data URL)."""
    names, cover = [], ""
    for src in sources[:MAX_PICTURES]:
        try:
            data = src.read_bytes()
        except OSError:
            continue
        small = _shrink(data, PICTURE_MAX, 1280)
        if not small:
            continue
        body, ext = small
        name, n = f"{safe(src.stem)}.{ext}", 2
        while name in names:
            name, n = f"{safe(src.stem)}-{n}.{ext}", n + 1
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(body)
        names.append(name)
        if not cover:
            c = _shrink(data, COVER_MAX, 480)
            if c:
                cover = f"data:image/{'jpeg' if c[1] == 'jpg' else 'png'};base64," + base64.b64encode(c[0]).decode()
    return names, cover


def _data_url(p: Path) -> str:
    mime = "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


# -- records --------------------------------------------------------------------------------------------------------------
def record(home: Path | str, entry: dict[str, Any], pictures: list[Path] | None = None) -> dict[str, Any]:
    """Write a finished goal's record once. Returns {written, entry}; a second call for the same goal keeps the
    first record (and the owner's hidden and starred flags) and writes nothing."""
    folder = entry_dir(home, safe(entry["project"]), safe(entry["goal"]))
    p = folder / "entry.json"
    old = _read(p)
    if old:
        return {"written": False, "entry": old}
    e = dict(entry)
    e["project"], e["goal"] = safe(entry["project"]), safe(entry["goal"])
    names, cover = keep_pictures(folder, list(pictures or []))
    e.update(pictures=names, cover=cover, hidden=False, starred=False, schema="gallery@1")
    _write(p, e)
    refresh_state(home)
    return {"written": True, "entry": e}


def entries(home: Path | str, hidden: bool = False) -> list[dict[str, Any]]:
    """Every record, newest first (hidden ones only when asked)."""
    base = gallery_dir(home)
    out = []
    if base.is_dir():
        for p in base.glob("*/*/entry.json"):
            e = _read(p)
            if e and (hidden or not e.get("hidden")):
                out.append(e)
    out.sort(key=lambda e: (bool(e.get("starred")), e.get("finished_at") or ""), reverse=True)
    return out


def refresh_state(home: Path | str) -> dict[str, Any]:
    """The kinds' earned status (kinds/state.json) from every record, hidden ones too: hiding isn't unbuilding."""
    from .model import write_state

    return write_state(home, entries(home, hidden=True))


def _day(ts: str) -> str:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return ""
    return f"{d.day} {d.strftime('%b')}"


def line(e: dict[str, Any]) -> str:
    """"26 Nov · $3.45 · 41 min"."""
    usd = (e.get("cost") or {}).get("counted_usd")
    parts = [_day(e.get("finished_at") or ""), f"${usd:.2f}" if isinstance(usd, (int, float)) else "",
             f"{round(e['minutes'])} min" if isinstance(e.get("minutes"), (int, float)) else ""]
    return " · ".join(x for x in parts if x)


def proof_words(e: dict[str, Any]) -> str:
    """"Opens with no errors ✓ · Tests pass ✓ · Played for a minute – not checked yet"."""
    out = []
    for p in e.get("proof") or []:
        mark = {True: "✓", False: "✗"}.get(p.get("passed"))
        out.append(f"{p['words']} {mark}" if mark else f"{p['words']} – not checked yet")
    return " · ".join(out)


def summary(e: dict[str, Any]) -> dict[str, Any]:
    """A record as one tile of the grid: title, kind chip, one line, the cover."""
    return {"project": e["project"], "goal": e["goal"], "title": e.get("title") or e["project"],
            "kind": (e.get("kind") or {}).get("id", ""), "kind_name": (e.get("kind") or {}).get("name", ""),
            "line": line(e), "cover": e.get("cover", ""), "hidden": bool(e.get("hidden")),
            "starred": bool(e.get("starred")), "path": e.get("path", ""), "proven": _proven(e)}


def _proven(e: dict[str, Any]) -> bool:
    from .model import counted

    return counted(e.get("proof") or [])


def one(home: Path | str, project: str, goal: str) -> dict[str, Any]:
    folder = entry_dir(home, project, goal)
    e = _read(folder / "entry.json")
    if not e:
        raise GalleryError("That gallery entry isn't there.")
    pics = [{"name": n, "src": _data_url(folder / n)} for n in e.get("pictures") or [] if (folder / n).is_file()]
    return {**summary(e), "summary": e.get("summary", ""), "pictures": pics, "proof": e.get("proof") or [],
            "proof_words": proof_words(e), "outputs": e.get("outputs") or [], "extras": e.get("extras") or [],
            "tasks": e.get("tasks"), "minutes": e.get("minutes"), "cost": e.get("cost") or {},
            "finished_at": e.get("finished_at", ""),
            "more": {"models": e.get("models") or [], "commit": e.get("commit", ""), "profile": e.get("profile")}}


def _flag(home: Path | str, project: str, goal: str, key: str, value: bool) -> dict[str, Any]:
    folder = entry_dir(home, project, goal)
    p = folder / "entry.json"
    e = _read(p)
    if not e:
        raise GalleryError("That gallery entry isn't there.")
    e[key] = bool(value)
    _write(p, e)
    return summary(e)


def hide(home: Path | str, project: str, goal: str, hidden: bool = True) -> dict[str, Any]:
    """Hide (or show again) an entry. Nothing is ever deleted."""
    return _flag(home, project, goal, "hidden", hidden)


def star(home: Path | str, project: str, goal: str, starred: bool = True) -> dict[str, Any]:
    return _flag(home, project, goal, "starred", starred)


def again(home: Path | str, project: str, goal: str) -> dict[str, Any]:
    """"Make another like this": the wizard filled in with the kind, extras and model set. No files copied."""
    e = _read(entry_dir(home, project, goal) / "entry.json")
    if not e:
        raise GalleryError("That gallery entry isn't there.")
    k = e.get("kind") or {}
    wizard = {"kind": {"chosen": [k.get("id") or "other"]},
              "extras": [x.get("id") for x in e.get("extras") or [] if x.get("id")]}
    if e.get("profile"):
        wizard["profile"] = {"chosen": [e["profile"]]}
    return {"wizard": wizard, "reply": f"The new project starts as a {k.get('name') or 'project'} like "
                                       f"{e.get('title') or e['project']}. Say what this one is."}


def hub_files(entry: dict[str, Any], hub_name: str) -> dict[str, str]:
    """The record for the private hub (the phone's Hub mode): the entry with its cover, not the big pictures."""
    e = {k: v for k, v in entry.items() if k != "pictures"}
    return {f"plans/gallery/{safe(hub_name)}/{safe(entry['goal'])}/entry.json":
            json.dumps(e, indent=1, ensure_ascii=False) + "\n"}
