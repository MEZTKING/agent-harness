"""Backups: settings, what Roundtable learned and every project's plan and history, in one file.

    roundtable backup now [--to PATH] [--with-code] [--passphrase]
    roundtable backup list [--to PATH]
    roundtable backup restore FILE [--passphrase] [--yes]
    roundtable backup where
    roundtable backup settings [--to auto|PATH] [--keep N] [--daily on|off] [--encrypt on|off]

A backup is one ``.zip`` (``roundtable-backup-<host>-<YYYY-MM-DD-HHMM>.zip``) with a
``manifest.json`` listing every file with its size and SHA-256. With a passphrase the zip
is locked with AES-256-GCM (key from scrypt) and the file ends ``.zip.enc``.

What goes in: the app's settings, harness.yaml and custom.yaml, hub.yaml and the saved hub
pointer (not a GitHub hub's data: that is on GitHub already; a hub kept only on this
computer is included), the lab (learned settings, proposals, versions, probe history;
files over 20 MB are left out and listed), each project's ``.harness/`` (not spill/,
scratch/ or references/), the paired phones list, and with ``--with-code`` each project's
code as a ``git bundle``.

What never goes in: API keys and secrets. Every file is checked for things that look
like keys; such a file is left out and named. The phone server's private key is never
included, so phones pair again after a restore.

Where backups go: ``auto`` finds Google Drive for desktop's ``My Drive`` folder and uses
``My Drive/Roundtable backups``; any other folder works too (OneDrive, a USB stick).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

FORMAT = 1
MAGIC = b"RTBK"
MAX_FILE = 20 * 1024 * 1024
FOLDER_NAME = "Roundtable backups"
DEFAULTS = {"to": "auto", "keep": 10, "daily": True, "encrypt": False}
APP_FILES = ("config/app.json", "config/hub.yaml", "config/harness.yaml", "config/custom.yaml",
             "hub-path", "phone.json")
HARNESS_SKIP = {"spill", "scratch", "references"}  # rebuildable or someone else's files
NEVER_NAMES = {"keys.json", "phone-key.pem", "phone-cert.pem", "backup-state.json", "update-check.json"}
NOT_SCANNED = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico"}
PHONE_NOTE = "Phones must pair again after a restore (the phone connection's key is never backed up)."
KEYS_NOTE = "API keys are never in a backup: type them again in Settings → API keys after a restore."

SECRET_PATTERNS = [
    (re.compile(rb"sk-or-v1-[A-Za-z0-9]{20,}"), "an OpenRouter key"),
    (re.compile(rb"sk-ant-[A-Za-z0-9_-]{20,}"), "an Anthropic key"),
    (re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}"), "an API key (sk-…)"),
    (re.compile(rb"\bAKIA[0-9A-Z]{16}\b"), "an Amazon key"),
    (re.compile(rb"\bghp_[A-Za-z0-9]{30,}"), "a GitHub token"),
    (re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{20,}"), "a GitHub token"),
    (re.compile(rb"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "a Slack token"),
    (re.compile(rb"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----"), "a private key"),
]
# In settings files only: a key written straight into a setting (`api_key: abc…`), not a
# reference to one (`api_key_env: DEEPSEEK_API_KEY`, `proxy-injected`, `${VAR}`).
SETTING_PATTERN = re.compile(
    rb"""(?im)(?:^|[\s{,"'])(?:api[_-]?key|secret[_-]?key|client[_-]?secret|access[_-]?token|auth[_-]?token|password)["']?"""
    rb"""\s*[:=]\s*["']?(?!proxy-injected)([A-Za-z0-9_\-+/=.]{12,})""")
SETTINGS_SUFFIXES = {".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".conf"}

_session_passphrase: str | None = None  # remembered in memory only, for the app's daily backups


class BackupError(Exception):
    """A problem the owner can fix; the message says how."""


# -- small helpers -------------------------------------------------------------------------------
def host_name() -> str:
    name = re.sub(r"[^a-z0-9-]+", "-", (socket.gethostname() or "pc").lower()).strip("-")
    return name or "pc"


def _home(home: Path | None) -> Path:
    from .desktop import app_home

    return Path(home) if home else app_home()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def human_size(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} bytes"


def remember_passphrase(passphrase: str | None) -> None:
    """Keep the passphrase in memory for this session only (never written anywhere)."""
    global _session_passphrase
    _session_passphrase = passphrase or None


def remembered_passphrase() -> str | None:
    return _session_passphrase


# -- settings and state (in the app's own settings file) ----------------------------------------
def load_settings(home: Path | None = None) -> dict:
    from .desktop import Paths

    saved = Paths(_home(home)).load_settings().get("backup") or {}
    return {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}


def save_settings(home: Path | None = None, **changes) -> dict:
    from .desktop import Paths

    paths = Paths(_home(home))
    current = load_settings(paths.home)
    for key, value in changes.items():
        if value is None:
            continue
        if key == "keep":
            value = int(value)
            if not 1 <= value <= 100:
                raise BackupError("Keep between 1 and 100 backups.")
        elif key in ("daily", "encrypt"):
            value = bool(value)
        elif key == "to":
            value = str(value).strip() or "auto"
        else:
            raise BackupError(f"Unknown backup setting {key!r}.")
        current[key] = value
    data = paths.load_settings()
    data["backup"] = current
    paths.save_settings(data)
    return current


def _state_file(home: Path | None) -> Path:
    return _home(home) / "backup-state.json"


def load_state(home: Path | None = None) -> dict:
    try:
        return json.loads(_state_file(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(home: Path | None, state: dict) -> None:
    path = _state_file(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def note(home: Path | None, text: str, ok: bool = True) -> None:
    """Record a plain message for the app's Backups card and activity feed."""
    state = load_state(home)
    entry = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "text": text, "ok": ok}
    state["log"] = ([entry] + list(state.get("log") or []))[:10]
    if not ok:
        state["last_error"] = text
    _save_state(home, state)


def feed_items(home: Path | None = None) -> list[dict]:
    return [{"at": e["at"], "seq": 0, "project": "backups", "kind": "backup", "who": "", "task": "",
             "role": "", "model": "", "text": e["text"]} for e in load_state(home).get("log") or []]


# -- where backups go ---------------------------------------------------------------------------
def _windows_roots() -> list[Path]:
    return [Path(f"{letter}:\\") for letter in "DEFGHIJKLMNOPQRSTUVWXYZ"]


def find_drive_folders(home: Path | None = None, platform: str | None = None) -> list[Path]:
    """Google Drive for desktop's "My Drive" folders on this computer, best first."""
    home = Path(home) if home else Path.home()
    platform = platform or sys.platform
    found: list[Path] = []
    if platform == "win32":
        found += [root / "My Drive" for root in _windows_roots()]
    if platform == "darwin":
        cloud = home / "Library" / "CloudStorage"
        found += sorted(cloud.glob("GoogleDrive-*/My Drive")) if cloud.is_dir() else []
    found += [home / "Google Drive" / "My Drive", home / "My Drive", home / "Google Drive"]
    out: list[Path] = []
    for p in found:
        try:
            if p.is_dir() and p not in out and not any(p.is_relative_to(o) or o.is_relative_to(p) for o in out):
                out.append(p)
        except OSError:  # a drive letter that isn't ready (a card reader, a DVD drive)
            continue
    return out


def resolve_destination(settings: dict | None = None, explicit: str | None = None,
                        home: Path | None = None) -> Path | None:
    to = explicit or (settings or load_settings(home)).get("to") or "auto"
    if to != "auto":
        return Path(to).expanduser()
    found = find_drive_folders()
    return found[0] / FOLDER_NAME if found else None


NO_DRIVE = ("No Google Drive folder found on this computer. Install Google Drive for desktop "
            "(https://www.google.com/drive/download/) and sign in, or choose another folder "
            "in Settings → Backups.")


# -- what goes in --------------------------------------------------------------------------------
@dataclass
class Sources:
    home: Path
    harness: Path | None = None  # harness.yaml
    hub: Path | None = None  # hub.yaml
    lab: Path | None = None
    hub_data: Path | None = None  # a hub kept only on this computer
    projects: list[Path] = field(default_factory=list)


def _find(finder, explicit: str | None, fallback: Path) -> Path | None:
    try:
        return finder(explicit)
    except FileNotFoundError:
        return fallback if fallback.is_file() else None


def find_sources(harness_config: str | None = None, hub_config: str | None = None,
                 home: Path | None = None) -> Sources:
    import yaml

    from .core.config import find_config as find_hub
    from .harness.config import _lab_dir, find_config as find_harness
    from .improve.lab import Lab

    home = _home(home)
    src = Sources(home=home)
    src.harness = _find(find_harness, harness_config, home / "config" / "harness.yaml")
    src.hub = _find(find_hub, hub_config, home / "config" / "hub.yaml")
    if src.harness:
        raw = yaml.safe_load(src.harness.read_text(encoding="utf-8")) or {}
        src.lab = _lab_dir(raw, src.harness.parent, src.harness)
        if src.lab and src.lab.is_dir():
            src.projects = Lab(src.lab).projects()
    if src.hub:
        storage = (yaml.safe_load(src.hub.read_text(encoding="utf-8")) or {}).get("storage") or {}
        if storage.get("type", "file") == "file":
            path = Path(storage.get("path", "hub-data")).expanduser()
            src.hub_data = path if path.is_absolute() else src.hub.parent / path
    return src


@dataclass
class Item:
    root: str
    rel: str
    src: Path

    @property
    def name(self) -> str:
        return f"{self.root}/{self.rel}"


def _walk(base: Path, skip_top: set[str] = frozenset(), skip_any: set[str] = frozenset({".git"})):
    if not base.is_dir():
        return
    for path in sorted(base.rglob("*")):
        rel = path.relative_to(base)
        if rel.parts[0] in skip_top or skip_any & set(rel.parts) or path.is_symlink() or not path.is_file():
            continue
        if path.suffix == ".tmp":
            continue
        yield rel.as_posix(), path


def _roots(src: Sources) -> dict[str, Path]:
    roots = {"app": src.home}
    if src.harness:
        roots["harness"] = src.harness.parent
    if src.hub:
        roots["hub"] = src.hub.parent
    if src.lab:
        roots["lab"] = src.lab
    if src.hub_data:
        roots["hub-data"] = src.hub_data
    for i, p in enumerate(src.projects, 1):
        roots[f"project-{i}"] = p
    return roots


def collect(src: Sources) -> list[Item]:
    items = [Item("app", rel, src.home / rel) for rel in APP_FILES if (src.home / rel).is_file()]
    if src.harness:
        items += [Item("harness", p.name, p) for p in (src.harness, src.harness.parent / "custom.yaml") if p.is_file()]
    if src.hub:
        items.append(Item("hub", src.hub.name, src.hub))
    if src.lab:
        items += [Item("lab", rel, p) for rel, p in _walk(src.lab)]
    if src.hub_data:
        items += [Item("hub-data", rel, p) for rel, p in _walk(src.hub_data)]
    for i, proj in enumerate(src.projects, 1):
        items += [Item(f"project-{i}", f".harness/{rel}", p) for rel, p in _walk(proj / ".harness", HARNESS_SKIP)]
    seen: set[Path] = set()
    unique = []
    for it in items:  # the same file reached two ways (harness.yaml in the app folder) goes in once
        key = it.src.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(it)
    return unique


def secret_reason(path: Path, data: bytes) -> str | None:
    """Why this file must not go in a backup, or None."""
    name = path.name.lower()
    if name in NEVER_NAMES:
        return "it holds keys"
    if name == ".env" or name.startswith(".env.") or name.endswith(".env"):
        return "it's an .env file (these hold keys)"
    if path.suffix.lower() in NOT_SCANNED:
        return None
    for pattern, what in SECRET_PATTERNS:
        if pattern.search(data):
            return f"it looks like it contains {what}"
    if path.suffix.lower() in SETTINGS_SUFFIXES and SETTING_PATTERN.search(data):
        return "it looks like it has a key written into a setting"
    return None


def _portable(path: Path, home: Path) -> dict:
    """Where a folder is, so a restore on another computer (or user name) finds the right place."""
    path = Path(path).resolve()
    out = {"path": str(path), "app": None, "user": None}
    for key, base in (("app", home), ("user", Path.home())):
        try:
            out[key] = path.relative_to(Path(base).resolve()).as_posix()
            break
        except ValueError:
            continue
    return out


def _bundle(project: Path) -> bytes | None:
    if not (project / ".git").exists():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "code.bundle"
        res = subprocess.run(["git", "-C", str(project), "bundle", "create", str(out), "--all"],
                             capture_output=True, text=True, timeout=900)
        return out.read_bytes() if res.returncode == 0 and out.is_file() else None


# -- encryption ----------------------------------------------------------------------------------
def _key(passphrase: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode("utf-8"))


def encrypt(data: bytes, passphrase: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt, nonce = os.urandom(16), os.urandom(12)
    header = MAGIC + bytes([FORMAT]) + salt + nonce
    return header + AESGCM(_key(passphrase, salt)).encrypt(nonce, data, header)


def decrypt(blob: bytes, passphrase: str) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not blob.startswith(MAGIC) or len(blob) < 33:
        raise BackupError("This file isn't a locked Roundtable backup.")
    header, salt, nonce = blob[:33], blob[5:21], blob[21:33]
    try:
        return AESGCM(_key(passphrase, salt)).decrypt(nonce, blob[33:], header)
    except InvalidTag:
        raise BackupError("That passphrase doesn't open this backup. Check it (capital letters count) "
                          "and try again.") from None


# -- making a backup -----------------------------------------------------------------------------
@dataclass
class Result:
    path: Path
    size: int
    files: int
    skipped: list[dict]
    refused: list[dict]
    pruned: list[Path] = field(default_factory=list)

    def message(self) -> str:
        text = f"Backed up {self.files} files ({human_size(self.size)}) to {self.path}."
        if not self.files:
            text += " There was nothing to back up yet: no settings or projects were found."
        if self.refused:
            text += " Left out because they look like they hold keys: " + ", ".join(r["path"] for r in self.refused) + "."
        if self.skipped:
            text += f" {len(self.skipped)} big or unreadable file(s) left out (listed in the backup)."
        return text


def _file_name(dest: Path, host: str, now: datetime, encrypted: bool, suffix: str) -> Path:
    stem = f"roundtable-backup-{host}-{now:%Y-%m-%d-%H%M}{suffix}"
    ext = ".zip.enc" if encrypted else ".zip"
    path, n = dest / f"{stem}{ext}", 2
    while path.exists():
        path, n = dest / f"{stem}-{n}{ext}", n + 1
    return path


def make_backup(dest: Path, src: Sources, passphrase: str | None = None, with_code: bool = False,
                now: datetime | None = None, suffix: str = "") -> Result:
    """Write one backup file into dest; nothing else in dest is touched."""
    from . import __version__

    now = now or datetime.now()
    dest = Path(dest)
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise BackupError(f"Can't use the folder {dest} for backups ({e.strerror}). Choose another folder.") from None
    files, skipped, refused = [], [], []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for it in collect(src):
            entry = _add(zf, it, skipped, refused)
            if entry:
                files.append(entry)
        projects = []
        for i, proj in enumerate(src.projects, 1):
            info = {"root": f"project-{i}", "name": proj.name, "code": None}
            if with_code:
                data = _bundle(proj)
                if data is None:
                    skipped.append({"path": str(proj), "reason": "its code isn't in git, so it wasn't bundled"})
                else:
                    info["code"] = f"code/project-{i}.bundle"
                    zf.writestr(info["code"], data)
                    files.append({"name": info["code"], "size": len(data), "sha256": _sha256(data)})
            projects.append(info)
        manifest = {"format": FORMAT, "created": now.astimezone().isoformat(timespec="seconds"), "host": host_name(),
                    "roundtable": __version__, "encrypted": bool(passphrase),
                    "roots": {k: _portable(v, src.home) for k, v in _roots(src).items()},
                    "projects": projects, "files": files, "skipped": skipped, "refused": refused,
                    "notes": [KEYS_NOTE, PHONE_NOTE]}
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    data = buf.getvalue()
    if passphrase:
        data = encrypt(data, passphrase)
    path = _file_name(dest, host_name(), now, bool(passphrase), suffix)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)
    return Result(path, len(data), len(files), skipped, refused)


def _add(zf: zipfile.ZipFile, it: Item, skipped: list, refused: list) -> dict | None:
    try:
        size = it.src.stat().st_size
        if size > MAX_FILE:
            skipped.append({"path": it.name, "reason": "bigger than 20 MB", "size": size})
            return None
        data = it.src.read_bytes()
    except OSError as e:
        skipped.append({"path": it.name, "reason": f"couldn't be read ({e.strerror})"})
        return None
    reason = secret_reason(it.src, data)
    if reason:
        refused.append({"path": str(it.src), "reason": reason})
        return None
    zf.writestr(it.name, data)
    return {"name": it.name, "size": len(data), "sha256": _sha256(data)}


BACKUP_RE = r"^roundtable-backup-{host}-\d{{4}}-\d{{2}}-\d{{2}}-\d{{4}}(-\d+)?\.zip(\.enc)?$"


def prune(dest: Path, keep: int, host: str | None = None) -> list[Path]:
    """Delete this computer's older regular backups beyond the newest `keep`. Nothing else."""
    pattern = re.compile(BACKUP_RE.format(host=re.escape(host or host_name())))
    mine = [p for p in Path(dest).iterdir() if p.is_file() and pattern.match(p.name)] if Path(dest).is_dir() else []
    mine.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    old = mine[max(keep, 1):]
    for p in old:
        p.unlink()
    return old


def list_backups(dest: Path) -> list[dict]:
    if not dest or not Path(dest).is_dir():
        return []
    host = host_name()
    out = []
    for p in Path(dest).iterdir():
        if p.is_file() and p.name.startswith("roundtable-backup-") and p.name.endswith((".zip", ".zip.enc")):
            st = p.stat()
            out.append({"name": p.name, "path": str(p), "size": st.st_size, "mtime": st.st_mtime,
                        "at": datetime.fromtimestamp(st.st_mtime).astimezone().isoformat(timespec="seconds"),
                        "locked": p.name.endswith(".enc"), "this_pc": p.name.startswith(f"roundtable-backup-{host}-")})
    return sorted(out, key=lambda b: (b["mtime"], b["name"]), reverse=True)


def _pick_passphrase(settings: dict, passphrase: str | None) -> str | None:
    passphrase = passphrase or (remembered_passphrase() if settings.get("encrypt") else None)
    if settings.get("encrypt") and not passphrase:
        raise BackupError("Backups are set to be locked with a passphrase, and none was typed this session. "
                          "Type it in Settings → Backups (or use --passphrase), then try again.")
    return passphrase


def backup_now(dest: str | Path | None = None, with_code: bool = False, passphrase: str | None = None,
               sources: Sources | None = None, home: Path | None = None, now: datetime | None = None,
               fallback: Path | None = None) -> Result:
    """A backup with the owner's settings: destination, passphrase, keep the newest N."""
    home = _home(home)
    settings = load_settings(home)
    target = Path(dest).expanduser() if dest else resolve_destination(settings) or fallback
    if not target:
        raise BackupError(NO_DRIVE)
    passphrase = _pick_passphrase(settings, passphrase)
    result = make_backup(target, sources or find_sources(home=home), passphrase, with_code, now)
    result.pruned = prune(target, int(settings.get("keep") or DEFAULTS["keep"]))
    state = load_state(home)
    state.update({"last_at": (now or datetime.now()).astimezone().isoformat(timespec="seconds"),
                  "last_file": str(result.path), "last_size": result.size, "last_error": ""})
    _save_state(home, state)
    note(home, result.message())
    return result


# -- automatic backups ----------------------------------------------------------------------------
def run_daily(home: Path | None = None, busy: bool = False, sources: Callable[[], Sources] | None = None,
              now: datetime | None = None) -> str | None:
    """The app's daily backup: at most once a day, never while a project job runs. Never raises."""
    home = _home(home)
    now = now or datetime.now()
    try:
        settings = load_settings(home)
        state = load_state(home)
        today = now.strftime("%Y-%m-%d")
        if not settings.get("daily") or busy or state.get("last_try_day") == today:
            return None
        if str(state.get("last_at", "")).startswith(today):
            return None
        state["last_try_day"] = today
        _save_state(home, state)
        if not resolve_destination(settings):
            msg = "Daily backup skipped: " + NO_DRIVE
            note(home, msg, ok=False)
            return msg
        return backup_now(sources=sources() if sources else None, home=home, now=now).message()
    except Exception as e:  # noqa: BLE001 - a backup problem must never stop the app
        msg = f"Daily backup didn't work: {e}"
        try:
            note(home, msg, ok=False)
        except OSError:
            pass
        return msg


def before_update(home: Path | None = None) -> str:
    """A backup just before the updater installs a new version (the app folder if no Drive)."""
    home = _home(home)
    try:
        result = backup_now(home=home, fallback=home / "backups")
        return f"Before updating: {result.message()}"
    except BackupError as e:
        note(home, f"Backup before the update skipped: {e}", ok=False)
        return f"Backup before the update skipped: {e}"


# -- restore -------------------------------------------------------------------------------------
@dataclass
class Opened:
    path: Path
    manifest: dict
    zf: zipfile.ZipFile


def open_backup(file: str | Path, passphrase: str | None = None) -> Opened:
    path = Path(file).expanduser()
    try:
        data = path.read_bytes()
    except OSError:
        raise BackupError(f"Can't open {path}. Check the file is there (and Google Drive has finished "
                          "downloading it).") from None
    if data.startswith(MAGIC):
        if not passphrase:
            raise BackupError("This backup is locked with a passphrase. Type the passphrase and try again.")
        data = decrypt(data, passphrase)
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        manifest = json.loads(zf.read("manifest.json"))
    except (zipfile.BadZipFile, KeyError, ValueError):
        raise BackupError(f"{path.name} isn't a Roundtable backup, or it's damaged.") from None
    if manifest.get("format", 0) > FORMAT:
        raise BackupError("This backup was made by a newer Roundtable Hold. Update Roundtable Hold first.")
    return Opened(path, manifest, zf)


def _root_target(info: dict, home: Path) -> Path:
    if info.get("app") is not None:
        return home / info["app"]
    if info.get("user") is not None:
        return Path.home() / info["user"]
    return Path(info["path"])


def _target(name: str, roots: dict, home: Path) -> Path:
    root, _, rel = name.partition("/")
    parts = Path(rel).parts
    if root not in roots or not rel or ".." in parts or Path(rel).is_absolute() or ":" in rel:
        raise BackupError(f"This backup has a file in an odd place ({name}); it won't be restored. "
                          "The backup may be damaged.")
    return _root_target(roots[root], home) / rel


def restore_plan(opened: Opened, home: Path | None = None) -> list[dict]:
    """Every file the restore would write, and whether it is new, replaces a file, or is the same."""
    home = _home(home)
    roots = opened.manifest.get("roots") or {}
    plan = []
    for f in opened.manifest.get("files", []):
        if f["name"].startswith("code/"):
            continue
        target = _target(f["name"], roots, home)
        if not target.is_file():
            action = "new"
        else:
            action = "same" if _sha256(target.read_bytes()) == f["sha256"] else "replace"
        plan.append({"name": f["name"], "target": str(target), "action": action, "size": f["size"]})
    return plan


def summary(opened: Opened, plan: list[dict]) -> list[str]:
    m = opened.manifest
    count = {a: sum(p["action"] == a for p in plan) for a in ("new", "replace", "same")}
    lines = [f"Backup of {m.get('host', '?')} made {m.get('created', '?')} (Roundtable Hold {m.get('roundtable', '?')}).",
             f"{len(plan)} files: {count['new']} new, {count['replace']} would replace what's here now, "
             f"{count['same']} already the same."]
    for proj in m.get("projects", []):
        lines.append(f"Project {proj['name']}" + (" (with its code)" if proj.get("code") else ""))
    lines += [f"  replaces {p['target']}" for p in plan if p["action"] == "replace"][:40]
    return lines


@dataclass
class Restored:
    written: int = 0
    safety: Path | None = None
    projects: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    cancelled: bool = False


def _check(opened: Opened) -> None:
    for f in opened.manifest.get("files", []):
        try:
            data = opened.zf.read(f["name"])
        except KeyError:
            raise BackupError(f"This backup is missing {f['name']}; it's damaged. Try an older backup.") from None
        if _sha256(data) != f["sha256"]:
            raise BackupError(f"{f['name']} in this backup is damaged. Try an older backup.")


def _restore_code(opened: Opened, roots: dict, home: Path, out: Restored) -> None:
    for proj in opened.manifest.get("projects", []):
        target = _root_target(roots[proj["root"]], home)
        if not proj.get("code"):
            continue
        if target.exists() and any(target.iterdir()):
            out.notes.append(f"{proj['name']}: its folder is already there, so its code was left as it is.")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "code.bundle"
            bundle.write_bytes(opened.zf.read(proj["code"]))
            res = subprocess.run(["git", "clone", str(bundle), str(target)], capture_output=True, text=True, timeout=900)
        if res.returncode != 0:
            out.notes.append(f"{proj['name']}: its code couldn't be put back ({res.stderr.strip()[-200:]}).")


def _fix_lab_projects(opened: Opened, roots: dict, home: Path) -> None:
    """The lab lists projects by folder; point it at where they are now."""
    if "lab" not in roots:
        return
    listing = _root_target(roots["lab"], home) / "projects.json"
    if not listing.is_file():
        return
    moved = {roots[p["root"]]["path"]: str(_root_target(roots[p["root"]], home).resolve())
             for p in opened.manifest.get("projects", [])}
    paths = json.loads(listing.read_text(encoding="utf-8"))
    fixed = list(dict.fromkeys([moved.get(p, p) for p in paths] + list(moved.values())))
    listing.write_text(json.dumps(fixed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def restore(file: str | Path, passphrase: str | None = None, yes: bool = False,
            confirm: Callable[[list[str]], bool] | None = None, home: Path | None = None,
            sources: Sources | None = None, log: Callable[[str], None] = print) -> Restored:
    """Put a backup back: show what it replaces, ask, make a safety backup first, then write."""
    home = _home(home)
    opened = open_backup(file, passphrase)
    _check(opened)
    plan = restore_plan(opened, home)
    lines = summary(opened, plan)
    if not yes and not (confirm and confirm(lines)):
        return Restored(cancelled=True)
    out = Restored()
    safety_dir = opened.path.parent
    try:
        out.safety = make_backup(safety_dir, sources or find_sources(home=home), passphrase,
                                 suffix="-before-restore").path
    except (BackupError, OSError):
        out.safety = make_backup(home / "backups", sources or find_sources(home=home), passphrase,
                                 suffix="-before-restore").path
    log(f"Saved what was here before as {out.safety}")
    roots = opened.manifest.get("roots") or {}
    _restore_code(opened, roots, home, out)
    for p in plan:
        if p["action"] == "same":
            continue
        target = Path(p["target"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(opened.zf.read(p["name"]))
        out.written += 1
    _fix_lab_projects(opened, roots, home)
    out.projects = [p["name"] for p in opened.manifest.get("projects", [])]
    out.notes += [KEYS_NOTE, PHONE_NOTE]
    note(home, f"Restored {out.written} files from {opened.path.name}.")
    return out


# -- command line ----------------------------------------------------------------------------------
def _ask_passphrase(new: bool) -> str:
    import getpass

    first = getpass.getpass("Passphrase: ")
    if new and getpass.getpass("Type it again: ") != first:
        raise BackupError("The two passphrases are different. Try again.")
    if not first:
        raise BackupError("The passphrase is empty. Try again, or leave out --passphrase.")
    return first


def _where() -> None:
    found = find_drive_folders()
    if found:
        print("Google Drive folder found: " + str(found[0]))
        print(f"Backups go into: {found[0] / FOLDER_NAME}")
        for extra in found[1:]:
            print(f"(also found {extra})")
    else:
        print(NO_DRIVE)
        print("Or back up to any folder: roundtable backup now --to \"D:\\Backups\"")
    s = load_settings()
    print(f"Settings: to {s['to']}, keep {s['keep']}, daily {'on' if s['daily'] else 'off'}, "
          f"locked with a passphrase {'yes' if s['encrypt'] else 'no'}")


def _on(value: str | None) -> bool | None:
    return None if value is None else value.lower() in ("on", "yes", "true", "1")


def main(argv: list[str]) -> None:
    import argparse

    p = argparse.ArgumentParser(prog="roundtable backup", description="Back up settings, learned settings and "
                                "every project's plan and history (never API keys).")
    p.add_argument("action", choices=["now", "list", "restore", "where", "settings"])
    p.add_argument("file", nargs="?", help="the backup to restore")
    p.add_argument("--to", help="a folder (default: your Google Drive folder); with settings: auto or a folder")
    p.add_argument("--with-code", action="store_true", help="also each project's own files (a git bundle)")
    p.add_argument("--passphrase", action="store_true", help="lock (or open) the backup with a passphrase you type")
    p.add_argument("--yes", action="store_true", help="restore without asking")
    p.add_argument("--config", help="harness.yaml (default $HARNESS_CONFIG or ./harness.yaml)")
    p.add_argument("--keep", type=int, help="settings: how many backups of this computer to keep")
    p.add_argument("--daily", help="settings: on or off")
    p.add_argument("--encrypt", help="settings: on or off")
    args = p.parse_args(argv)
    try:
        _run(args)
    except BackupError as e:
        sys.exit(f"roundtable backup: {e}")


def _run(args) -> None:
    if args.action == "where":
        return _where()
    if args.action == "settings":
        s = save_settings(to=args.to, keep=args.keep, daily=_on(args.daily), encrypt=_on(args.encrypt))
        print(json.dumps(s, indent=2))
        return None
    if args.action == "list":
        dest = resolve_destination(explicit=args.to)
        if not dest:
            raise BackupError(NO_DRIVE)
        rows = list_backups(dest)
        print(f"In {dest}:" if rows else f"No backups in {dest} yet.")
        for b in rows:
            print(f"  {b['name']}  {human_size(b['size'])}" + ("  (locked)" if b["locked"] else ""))
        return None
    if args.action == "now":
        settings = load_settings()
        phrase = _ask_passphrase(new=True) if args.passphrase or settings.get("encrypt") else None
        result = backup_now(args.to, args.with_code, phrase, sources=find_sources(args.config))
        print(result.message())
        if not phrase:
            print("Tip: add --passphrase to lock the backup; it holds your plans.")
        return None
    if not args.file:
        raise BackupError("Say which backup to restore: roundtable backup restore FILE")
    phrase = _ask_passphrase(new=False) if args.passphrase or str(args.file).endswith(".enc") else None

    def ask(lines: list[str]) -> bool:
        print("\n".join(lines))
        return input("Put these back? A safety backup of what's here now is made first. Type yes: ").strip().lower() in ("y", "yes")

    done = restore(args.file, phrase, yes=args.yes, confirm=ask, sources=find_sources(args.config))
    if done.cancelled:
        print("Nothing changed.")
        return None
    print(f"Restored {done.written} files. What was here before is in {done.safety}.")
    for n in done.notes:
        print(n)
    return None
