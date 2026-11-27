"""How a project is built to hand out, and the checks on what was built (pure: no running, no model).

A kind or an extra may carry a ``ship`` recipe (kinds/model.py checks it):

    ship: {build: "./gradlew assembleDebug", artefact: "app/build/outputs/apk/debug/*.apk",
           smoke: apk, needs: [java, android], os: [windows, mac, linux], target: apk, timeout: 1800}

``smoke`` is one of :data:`SMOKES` or a command of its own (it passes when it exits with 0, or is still
running after the smoke seconds). The stage that runs all this is ``shipstage.ShipStage``; this file only
says what to run, whether this machine can, and whether the file built looks right.
"""

from __future__ import annotations

import fnmatch
import glob as globlib
import re
import zipfile
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT = 1800  # seconds a build may take
SMOKE_SECONDS = 10.0  # a started program must still be running after this long
OSES = ("windows", "mac", "linux")
OS_WORDS = {"windows": "Windows", "mac": "a Mac", "linux": "Linux"}
SMOKES = ("start", "apk", "mod", "none")
# The first bytes a file of that sort starts with (zip-based ones all start "PK")
MAGIC = {"apk": b"PK", "aab": b"PK", "jar": b"PK", "zip": b"PK", "exe": b"MZ", "msi": b"\xd0\xcf\x11\xe0"}
TARGET_WORDS = {"apk": "Android app (APK)", "exe": "Windows program (EXE)", "jar": "mod file (JAR)",
                "zip": "zip file", "web": "web app"}
# What a mod jar holds to be a mod (Fabric, Quilt, Forge, NeoForge, old Forge, a server plug-in)
MOD_FILES = ("fabric.mod.json", "quilt.mod.json", "META-INF/mods.toml", "META-INF/neoforge.mods.toml",
             "mcmod.info", "plugin.yml", "paper-plugin.yml")
SKIP_JARS = re.compile(r"-(sources|javadoc|dev|dev-shadow|api)\.jar$", re.IGNORECASE)


def target_words(target: str) -> str:
    return TARGET_WORDS.get(target, target)


def recipes(kind: Any) -> list[dict[str, Any]]:
    """The ship recipes of a resolved kind (its own, then each extra's), one per target, each with where it
    came from: {target, name, build, artefact, smoke, needs, os, timeout, source, from}."""
    if kind is None:
        return []
    out: dict[str, dict[str, Any]] = {}
    spec = getattr(kind, "spec", {}) or {}
    own = spec.get("ship")
    if isinstance(own, dict) and own.get("build"):
        targets = list(spec.get("targets") or [])
        out_t = str(own.get("target") or (targets[0] if targets else kind.id))
        out[out_t] = _recipe(own, out_t, kind.name, getattr(kind, "source", "builtin"), kind.id,
                             list(spec.get("needs") or []))
    for e in getattr(kind, "extras", None) or []:
        r = e.get("ship")
        if not isinstance(r, dict) or not r.get("build"):
            continue
        t = str(r.get("target") or e.get("id"))
        out[t] = _recipe(r, t, e.get("name") or target_words(t), e.get("source") or "builtin", e.get("id", t), [])
    return list(out.values())


def _recipe(r: dict[str, Any], target: str, name: str, source: str, origin: str,
            needs_default: list[str]) -> dict[str, Any]:
    return {"target": target, "name": str(name), "build": str(r["build"]).strip(),
            "artefact": str(r.get("artefact") or "").strip(), "smoke": str(r.get("smoke") or default_smoke(target)),
            "needs": list(r.get("needs") or needs_default), "os": list(r.get("os") or OSES),
            "timeout": int(r.get("timeout") or DEFAULT_TIMEOUT), "source": source or "builtin", "from": origin}


def default_smoke(target: str) -> str:
    return {"exe": "start", "apk": "apk", "jar": "mod"}.get(target, "none")


def asks_first(recipe: dict[str, Any]) -> bool:
    """A recipe that isn't built in (the owner's own kind or an imported one) asks before its first run."""
    return recipe.get("source", "builtin") != "builtin"


def for_os(command: str, os_name: str) -> str:
    """``./gradlew`` is ``gradlew.bat`` on Windows (cmd can't start ./gradlew); nothing else changes."""
    if os_name != "windows":
        return command
    return re.sub(r"(^|&&\s*|;\s*)\./gradlew\b", lambda m: m.group(1) + "gradlew.bat", command)


# -- can this machine build it? -----------------------------------------------------------------------
def can_build(recipe: dict[str, Any], rows: list[dict[str, Any]], os_name: str) -> tuple[bool, str]:
    """(True, "") or (False, the plain reason) from ``prereq.status`` rows and the machine's system."""
    name = recipe.get("name") or target_words(recipe["target"])
    oses = recipe.get("os") or list(OSES)
    if os_name not in oses:
        where = " or ".join(OS_WORDS.get(o, o) for o in oses)
        return False, f"No {where} here: the {short(recipe)} can't be built on this machine."
    by = {r.get("id"): r for r in rows or []}
    gone = [n for n in missing_tools(recipe, rows)]
    if gone:
        parts = [f"{by[n]['name']} {'is too old' if by[n].get('state') == 'old' else 'is not on this computer'}"
                 for n in gone]
        return False, f"{' and '.join(parts)}, so the {short(recipe)} can't be built here yet ({name})."
    return True, ""


def short(recipe: dict[str, Any]) -> str:
    t = recipe.get("target", "")
    return {"apk": "APK", "exe": "EXE", "jar": "mod file"}.get(t, t or "thing")


def missing_tools(recipe: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    by = {r.get("id"): r for r in rows or []}
    return [n for n in recipe.get("needs") or [] if n in by and by[n].get("state") != "found"]


# -- the file built ------------------------------------------------------------------------------------
def find_artefact(root: Path, pattern: str) -> Path | None:
    """The newest file matching ``pattern`` inside the project (a mod's sources or javadoc jar is passed over)."""
    root = Path(root)
    if not pattern or Path(pattern).is_absolute() or ".." in Path(pattern).parts:
        return None
    hits = [Path(p) for p in globlib.glob(str(root / pattern), recursive=True)]
    hits = [p for p in hits if p.is_file()]
    if pattern.endswith(".jar"):
        hits = [p for p in hits if not SKIP_JARS.search(p.name)] or hits
    if not hits:
        return None
    return max(hits, key=lambda p: (p.stat().st_mtime, p.stat().st_size))


def check_artefact(root: Path, recipe: dict[str, Any]) -> dict[str, Any]:
    """{ok, words, path, size}: the file is there, isn't empty, and starts with the right bytes."""
    pattern = recipe.get("artefact") or ""
    p = find_artefact(root, pattern)
    if p is None:
        return {"ok": False, "words": f"The build finished but no file matching {pattern} was made.", "path": "",
                "size": 0}
    rel = p.relative_to(Path(root)).as_posix() if Path(root) in p.parents else str(p)
    size = p.stat().st_size
    if size == 0:
        return {"ok": False, "words": f"{rel} was made but it is empty.", "path": rel, "size": 0}
    kind = p.suffix.lower().lstrip(".")
    want = MAGIC.get(kind) or MAGIC.get(recipe.get("target", ""))
    if want:
        with open(p, "rb") as fh:
            head = fh.read(len(want))
        if head != want:
            return {"ok": False, "path": rel, "size": size,
                    "words": f"{rel} isn't a real {kind.upper()} file (it doesn't start the way one does)."}
    return {"ok": True, "words": f"{rel} was built ({_size(size)}).", "path": rel, "size": size}


def _size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    return f"{max(1, round(n / 1024))} KB"


def zip_names(path: Path) -> list[str] | None:
    try:
        with zipfile.ZipFile(path) as z:
            return z.namelist()
    except (OSError, zipfile.BadZipFile):
        return None


def mod_check(path: Path) -> dict[str, Any]:
    """A mod jar holds its mod file (fabric.mod.json, mods.toml…) and at least one class."""
    names = zip_names(path)
    if names is None:
        return {"ok": False, "words": f"{path.name} can't be opened as a jar."}
    found = [m for m in MOD_FILES if m in names]
    if not found:
        return {"ok": False, "words": f"{path.name} has no mod file inside (like fabric.mod.json or "
                                      f"META-INF/mods.toml), so the game wouldn't load it."}
    classes = sum(1 for n in names if n.endswith(".class"))
    if not classes:
        return {"ok": False, "words": f"{path.name} has {found[0]} but no compiled code."}
    return {"ok": True, "words": f"It holds {found[0]} and {classes} compiled class{'es' * (classes != 1)}."}


def apk_check(path: Path) -> dict[str, Any]:
    """The APK holds a manifest and compiled code (the SDK's own tools check more when they're there)."""
    names = zip_names(path)
    if names is None:
        return {"ok": False, "words": f"{path.name} can't be opened as an APK."}
    if "AndroidManifest.xml" not in names:
        return {"ok": False, "words": f"{path.name} has no AndroidManifest.xml, so a phone wouldn't install it."}
    if not any(fnmatch.fnmatch(n, "classes*.dex") for n in names):
        return {"ok": False, "words": f"{path.name} has no compiled code (classes.dex)."}
    return {"ok": True, "words": "It holds its manifest and compiled code."}


def exit_code(tool_text: str) -> int | None:
    """The exit code from ``Workspace.run_command``'s answer ("exit code: 0\\n--- stdout ---…")."""
    m = re.match(r"exit code: (-?\d+)", tool_text or "")
    return int(m.group(1)) if m else None


def tail(tool_text: str, lines: int = 25) -> str:
    """The last lines of a command's output, for a fix task (the end is where a build says what broke)."""
    body = [ln for ln in (tool_text or "").splitlines() if ln.strip() and not ln.startswith("--- ")]
    return "\n".join(body[-lines:])[-3000:]


def emulators(adb_devices_text: str) -> list[str]:
    """Running emulators from ``adb devices`` (never a plugged-in phone: those have other serials)."""
    out = []
    for line in (adb_devices_text or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("emulator-") and parts[1] == "device":
            out.append(parts[0])
    return out


def sdk_tool(sdk: Path | None, name: str, os_name: str) -> Path | None:
    """An SDK program: ``platform-tools/adb`` or the newest ``build-tools/<v>/aapt2``."""
    if not sdk:
        return None
    sdk = Path(sdk)
    ext = ".exe" if os_name == "windows" else ""
    if name == "adb":
        p = sdk / "platform-tools" / f"adb{ext}"
        return p if p.is_file() else None
    bt = sdk / "build-tools"
    try:
        versions = sorted((d for d in bt.iterdir() if d.is_dir()), key=lambda d: _vkey(d.name), reverse=True)
    except OSError:
        return None
    for d in versions:
        p = d / f"{name}{ext}"
        if p.is_file():
            return p
    return None


def _vkey(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4])
