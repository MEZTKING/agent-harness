"""Storage backends for hub data.

* ``FileStore``  – a plain directory. Good for one machine and for tests.
* ``GitStore``   – a directory that is a git clone. Every write is committed
  and pushed, every read pulls first, so agents in different repos / machines
  share state through an ordinary GitHub repo. No server needed.

The layout is designed so concurrent writers rarely touch the same file
(one file per message, one card per agent), which keeps git merges trivial.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Iterable


class TextFile(str):
    """Marks a value to be written as raw text (e.g. Markdown) instead of JSON."""


class BinaryFile(bytes):
    """Marks a value to be written as raw bytes (e.g. a PNG picture)."""


class Store:
    def sync(self, force: bool = False) -> None:  # pull latest state (no-op for local stores)
        pass

    def read_json(self, rel: str) -> Any | None:
        raise NotImplementedError

    def write_json(self, items: dict[str, Any], message: str) -> None:
        """Atomically (as far as the backend allows) write several files."""
        raise NotImplementedError

    def list(self, rel_dir: str) -> list[str]:
        raise NotImplementedError


class FileStore(Store):
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValueError(f"path escapes store root: {rel!r}")
        return p

    def read_json(self, rel: str) -> Any | None:
        p = self._path(rel)
        if not p.is_file():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def _write_files(self, items: dict[str, Any]) -> list[str]:
        written = []
        for rel, data in items.items():
            p = self._path(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-")
            if isinstance(data, BinaryFile):
                with os.fdopen(fd, "wb") as f:
                    f.write(bytes(data))
                os.replace(tmp, p)
                written.append(rel)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                if isinstance(data, TextFile):
                    f.write(str(data))
                else:
                    json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
                    f.write("\n")
            os.replace(tmp, p)
            written.append(rel)
        return written

    def write_json(self, items: dict[str, Any], message: str) -> None:
        self._write_files(items)

    def list(self, rel_dir: str) -> list[str]:
        d = self._path(rel_dir)
        if not d.is_dir():
            return []
        return sorted(
            str(p.relative_to(self.root)) for p in d.iterdir() if p.is_file() and p.suffix == ".json"
        )


class GitError(RuntimeError):
    pass


_GIT_LOCKS: dict[str, threading.RLock] = {}
_GIT_LOCKS_GUARD = threading.Lock()


def _lock_for(root: Path) -> threading.RLock:
    with _GIT_LOCKS_GUARD:
        return _GIT_LOCKS.setdefault(str(root), threading.RLock())


class GitStore(FileStore):
    """FileStore whose directory is a git working tree synced with a remote.

    Git operations on one working tree are serialised in-process, so several
    Hub objects (e.g. the web UI and a roundtable run in a background thread) can
    share a data directory safely.
    """

    def __init__(
        self,
        root: str | Path,
        remote: str | None = None,
        branch: str = "main",
        push: bool = True,
        retries: int = 4,
        author: str = "roundtable",
        sync_interval: float = 20.0,
    ):
        root = Path(root).resolve()
        self.branch = branch
        # Reads reuse a sync this recent (each sync is a network round-trip to the
        # remote); writes always sync first, so no change is ever lost.
        self.sync_interval = sync_interval
        self._last_sync = 0.0
        self.last_sync_error = ""
        self.push_enabled = push
        self.retries = retries
        self.author = author
        if not (root / ".git").exists():
            if remote:
                root.parent.mkdir(parents=True, exist_ok=True)
                self._run(["git", "clone", remote, str(root)], cwd=root.parent)
            else:
                root.mkdir(parents=True, exist_ok=True)
                self._run(["git", "init", "-b", branch], cwd=root)
        super().__init__(root)
        self._has_remote = bool(self._git("remote").strip())
        if self._has_remote and self._remote_branch_exists():
            current = self._run(["git", "branch", "--show-current"], cwd=self.root).strip()
            if current != branch:
                # FETCH_HEAD, not origin/<branch>: a clone made while the repo was still
                # empty has no remote-tracking ref for it
                self._git("checkout", "-B", branch, "FETCH_HEAD")

    # -- git plumbing -------------------------------------------------
    @staticmethod
    def _run(cmd: list[str], cwd: Path) -> str:
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        if res.returncode != 0:
            raise GitError(f"{' '.join(cmd)} failed: {res.stderr.strip() or res.stdout.strip()}")
        return res.stdout

    def _git(self, *args: str) -> str:
        env_args = ["-c", f"user.name={self.author}", "-c", "user.email=agent-hub@localhost"]
        return self._run(["git", *env_args, *args], cwd=self.root)

    def _remote_branch_exists(self) -> bool:
        try:
            self._git("fetch", "origin", self.branch)
            return True
        except GitError:
            return False

    def sync(self, force: bool = False) -> None:
        with _lock_for(self.root):
            if not self._has_remote:
                return
            if not force and time.monotonic() - self._last_sync < self.sync_interval:
                return  # recent enough for reading
            try:
                try:
                    self._git("fetch", "origin", self.branch)
                    remote_has_branch = True
                except GitError as e:
                    if "couldn't find remote ref" not in str(e).lower():
                        raise  # unreachable remote, auth, ... (not just "branch not created yet")
                    remote_has_branch = False
                if remote_has_branch:
                    self._git("pull", "--rebase", "origin", self.branch)
                self._last_sync = time.monotonic()
                self.last_sync_error = ""
            except GitError as e:
                if force:
                    raise
                # offline or remote trouble: reading the local copy beats failing the page
                self.last_sync_error = str(e)
                self._last_sync = time.monotonic()

    def write_json(self, items: dict[str, Any], message: str) -> None:
        with _lock_for(self.root):
            self._write_json_locked(items, message)

    def _write_json_locked(self, items: dict[str, Any], message: str) -> None:
        self.sync(force=True)
        written = self._write_files(items)
        self._git("add", "--", *written)
        if not self._git("status", "--porcelain", "--", *written).strip():
            return  # nothing changed
        self._git("commit", "-m", message, "--", *written)
        if not (self._has_remote and self.push_enabled):
            return
        delay = 1.0
        for attempt in range(self.retries + 1):
            try:
                self._git("push", "origin", f"HEAD:{self.branch}")
                return
            except GitError:
                if attempt == self.retries:
                    raise
                time.sleep(delay)
                delay *= 2
                self._git("pull", "--rebase", "origin", self.branch)


def make_store(cfg: dict[str, Any], base_dir: Path) -> Store:
    kind = cfg.get("type", "file")
    path = Path(cfg.get("path", "hub-data"))
    if not path.is_absolute():
        path = base_dir / path
    if kind == "file":
        return FileStore(path)
    if kind == "git":
        return GitStore(
            path,
            remote=cfg.get("remote"),
            branch=cfg.get("branch", "main"),
            sync_interval=float(cfg.get("sync_interval", 20)),
            push=cfg.get("push", True),
        )
    raise ValueError(f"unknown storage type {kind!r} (expected 'file' or 'git')")


def iter_json(store: Store, rel_dir: str) -> Iterable[tuple[str, Any]]:
    for rel in store.list(rel_dir):
        data = store.read_json(rel)
        if data is not None:
            yield rel, data
