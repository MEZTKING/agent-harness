"""Move my data (wave 8, MD-61): the hub's folder or the projects folder to a new place, safely.

As a job: refused while anything is building. The folder is **copied** (a git hub as a whole folder with its
``.git``), the copy is checked file by file (the same count, the same SHA-256 of every file), and only then the
pointers are switched: for the hub, ``storage.path`` in the app's hub.yaml and the saved hub pointer
(``core.config.saved_hub_pointer``) when it points inside the old folder; for the projects, ``projects_dir`` in
the app's settings and every project path in the lab's ``projects.json``. **The old copy is kept, named in the
result and never deleted.** Each switch writes down the pointer files exactly as they were, so **Switch back**
puts them back (only if nobody changed them since).

The record: ``<app home>/datamove.json`` {"moves": [{id, what, from, to, at, files, bytes, pointers: [{file,
before, after}], switched_back}]}.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WHATS = ("hub", "projects")
RECORD = "datamove.json"
Line = Callable[[str], None]


class MoveError(ValueError):
    """Something the owner must fix, in a plain sentence."""


@dataclass
class Pointer:
    """One file that says where the data is, and how to point it at the new place."""
    file: Path
    kind: str  # "text": the whole file is a path; "json_key": key in a JSON object; "hub_yaml": storage.path;
    #            "json_paths": a JSON list of paths (the lab's projects.json)
    key: str = ""

    def rewrite(self, text: str, old: Path, new: Path) -> str:
        def move(p: str) -> str:
            try:
                rel = Path(p).expanduser().resolve().relative_to(old)
            except (ValueError, OSError):
                return p
            return str(new / rel) if str(rel) != "." else str(new)

        if self.kind == "text":
            return move(text.strip()) + ("\n" if text.endswith("\n") else "")
        if self.kind == "json_key":
            data = json.loads(text or "{}")
            if isinstance(data, dict) and data.get(self.key):
                data[self.key] = move(str(data[self.key]))
            return json.dumps(data, indent=2) + "\n"
        if self.kind == "json_paths":
            data = json.loads(text or "[]")
            return json.dumps([move(str(p)) for p in data] if isinstance(data, list) else data, indent=2) + "\n"
        if self.kind == "hub_yaml":
            import yaml

            head = "".join(ln + "\n" for ln in text.splitlines() if ln.startswith("#"))
            data = yaml.safe_load(text) or {}
            st = data.get("storage") or {}
            if st.get("path"):
                p = Path(str(st["path"])).expanduser()
                if p.is_absolute():
                    st["path"] = move(str(p))
            data["storage"] = st
            return head + yaml.safe_dump(data, sort_keys=False)
        raise MoveError(f"unknown pointer kind {self.kind}")


# -- checking a copy -----------------------------------------------------------------------------------
def fingerprint(root: Path) -> dict[str, str]:
    """{relative path: SHA-256} of every file under ``root`` (links recorded by their target, not followed)."""
    out: dict[str, str] = {}
    for dirpath, dirs, files in os.walk(root, followlinks=False):
        dirs.sort()
        for name in sorted(files) + [d for d in dirs if os.path.islink(os.path.join(dirpath, d))]:
            p = Path(dirpath) / name
            rel = p.relative_to(root).as_posix()
            if p.is_symlink():
                out[rel] = "link:" + os.readlink(p)
                continue
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            out[rel] = h.hexdigest()
    return out


def _size(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink())


# -- the record -------------------------------------------------------------------------------------------
def _record_file(home: Path) -> Path:
    return Path(home) / RECORD


def moves(home: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(_record_file(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [m for m in data.get("moves") or [] if isinstance(m, dict)]


def _save(home: Path, items: list[dict[str, Any]]) -> None:
    f = _record_file(home)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"moves": items[-50:]}, indent=2), encoding="utf-8")
    tmp.replace(f)


def _write(p: Path, text: str) -> None:
    tmp = p.with_name(p.name + ".moving")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)


# -- moving -------------------------------------------------------------------------------------------------
def check(src: Path, dest: Path) -> tuple[Path, Path]:
    src, dest = Path(src).expanduser().resolve(), Path(dest).expanduser().resolve()
    if not src.is_dir():
        raise MoveError(f"There's nothing to move: {src} isn't a folder.")
    if dest == src:
        raise MoveError("That is where it already is. Pick another folder.")
    if dest.is_relative_to(src):
        raise MoveError("The new place can't be inside the old one. Pick a folder somewhere else.")
    if src.is_relative_to(dest) and dest.exists() and any(dest.iterdir()):
        raise MoveError("The new place already has things in it. Pick an empty or new folder.")
    if dest.exists() and any(dest.iterdir()):
        raise MoveError("The new place already has things in it. Pick an empty or new folder.")
    return src, dest


def move(home: Path, what: str, src: Path, dest: Path, pointers: list[Pointer], busy: bool,
         line: Line = lambda s: None, copy: Callable[[Path, Path], Any] | None = None) -> dict[str, Any]:
    """Copy ``src`` to ``dest``, check the copy, switch ``pointers``. The old copy stays where it was."""
    if what not in WHATS:
        raise MoveError("Say what to move: the hub or the projects.")
    if busy:
        raise MoveError("Something is building. Wait for it to finish (or stop it), then move your data.")
    src, dest = check(src, dest)
    line(f"Copying {src} to {dest}…")
    before = fingerprint(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.rmdir()  # empty (checked above): copytree makes it
    (copy or (lambda a, b: shutil.copytree(a, b, symlinks=True)))(src, dest)
    line("Checking the copy, file by file…")
    after = fingerprint(dest)
    if after != before:
        missing = sorted(set(before) - set(after))[:3]
        changed = sorted(k for k in before if k in after and before[k] != after[k])[:3]
        raise MoveError("The copy doesn't match the original, so nothing was switched and your data stays where "
                        f"it was ({len(before)} files there, {len(after)} in the copy"
                        + (f"; missing {', '.join(missing)}" if missing else "")
                        + (f"; different {', '.join(changed)}" if changed else "")
                        + f"). The copy in {dest} can be deleted.")
    line(f"The copy matches: {len(after)} files, every one the same.")
    switched = []
    try:
        for p in pointers:
            if not p.file.is_file():
                continue
            old_text = p.file.read_text(encoding="utf-8")
            new_text = p.rewrite(old_text, src, dest)
            if new_text != old_text:
                _write(p.file, new_text)
                switched.append({"file": str(p.file), "before": old_text, "after": new_text})
                line(f"Pointed {p.file.name} at the new place.")
    except Exception as e:
        for s in reversed(switched):  # all or nothing
            _write(Path(s["file"]), s["before"])
        raise MoveError(f"Couldn't switch to the new place ({e}); everything still points at the old one.") from e
    entry = {"id": f"m{int(time.time() * 1000)}", "what": what, "from": str(src), "to": str(dest),
             "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "files": len(after), "bytes": _size(dest),
             "pointers": switched, "switched_back": False}
    _save(home, moves(home) + [entry])
    words = (f"Moved: {len(after)} files are now in {dest}, checked one by one. The old copy is still in {src}; "
             "nothing was deleted. Switch back puts everything as it was.")
    line(words)
    return {**{k: v for k, v in entry.items() if k != "pointers"}, "ok": True, "words": words, "old_copy": str(src)}


def switch_back(home: Path, move_id: str = "", busy: bool = False, line: Line = lambda s: None) -> dict[str, Any]:
    """Put the pointers of the newest move (or ``move_id``) back as they were. Both copies stay."""
    if busy:
        raise MoveError("Something is building. Wait for it to finish, then switch back.")
    items = moves(home)
    m = next((m for m in reversed(items) if (not move_id or m["id"] == move_id) and not m.get("switched_back")), None)
    if not m:
        raise MoveError("There's no move to switch back.")
    for s in m.get("pointers") or []:
        f = Path(s["file"])
        cur = f.read_text(encoding="utf-8") if f.is_file() else None
        if cur is not None and cur != s["after"]:
            raise MoveError(f"{f.name} was changed after the move, so it isn't switched back by itself. Nothing "
                            "was changed.")
    for s in m.get("pointers") or []:
        _write(Path(s["file"]), s["before"])
    m["switched_back"] = True
    _save(home, items)
    words = (f"Switched back: everything points at {m['from']} again. The copy in {m['to']} is kept; delete it "
             "yourself if you don't need it.")
    line(words)
    return {"ok": True, "id": m["id"], "words": words}


# -- where the desktop app's pointers are --------------------------------------------------------------
def hub_folder(hub_yaml: Path) -> Path | None:
    """The hub's data folder the app's hub.yaml points at."""
    import yaml

    from .core.config import storage_root

    try:
        raw = yaml.safe_load(Path(hub_yaml).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    return storage_root(raw, Path(hub_yaml))


def pointers_for(what: str, *, hub_yaml: Path | None = None, settings_file: Path | None = None,
                 lab_dir: Path | None = None, hub_pointer: Path | None = None) -> list[Pointer]:
    out: list[Pointer] = []
    if what == "hub":
        if hub_yaml:
            out.append(Pointer(Path(hub_yaml), "hub_yaml"))
        if hub_pointer:
            out.append(Pointer(Path(hub_pointer), "text"))
    elif what == "projects":
        if settings_file:
            out.append(Pointer(Path(settings_file), "json_key", "projects_dir"))
        if lab_dir:
            out.append(Pointer(Path(lab_dir) / "projects.json", "json_paths"))
    return out
