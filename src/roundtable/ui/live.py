"""The project page's Live and Session tabs: what each project is making, as it is made.

* ``LivePreview``: the app itself, served read-only from its own folder by a second small web
  server on another port. Another port is another origin, so the app (written by a model) runs in
  its frame with its own storage but can't reach Roundtable's pages or API.
* ``live`` / ``session_view``: the data for the two tabs (pictures, history, steps, outputs);
* ``raw``: a project's picture or produced file for the page (images shown, the rest downloaded).
"""

from __future__ import annotations

import base64
import hashlib
import re
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ..harness import session as sessionlib
from ..harness import showit

PREVIEW_HOSTS = {"127.0.0.1", "localhost"}
# The app may use its own files, inline code and Google's fonts; nothing else leaves the computer.
PREVIEW_CSP = ("default-src 'self' data: blob: 'unsafe-inline' 'unsafe-eval'; connect-src 'self' data: blob:; "
               "img-src 'self' data: blob:; media-src 'self' data: blob:; "
               "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' data: https://fonts.gstatic.com; "
               "form-action 'self'; frame-ancestors http://127.0.0.1:* http://localhost:*")
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


def project_key(root: Path) -> str:
    return hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:16]


class LivePreview:
    """The second web server: /<project key>/<file> from the registered projects only."""

    def __init__(self, projects):
        self.projects = projects  # () -> list of project folders (the lab's)
        self.httpd: ThreadingHTTPServer | None = None

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}" if self.httpd else ""

    def resolve(self, rel: str) -> Path | None:
        key, _, rest = rel.partition("/")
        root = next((p for p in self.projects() if project_key(p) == key), None)
        return showit.safe_path(root, rest) if root and rest else None

    def start(self) -> "LivePreview":
        if self.httpd:
            return self
        handler = showit.make_file_handler(self.resolve, lambda: {"Content-Security-Policy": PREVIEW_CSP},
                                           hosts=PREVIEW_HOSTS)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    def url(self, root: Path, entry: str | None) -> str | None:
        if not self.httpd or not entry:
            return None
        return f"{self.origin}/{project_key(root)}/{entry}"


# -- the tabs' data ------------------------------------------------------------------------------
def _data_url(p: Path) -> str | None:
    if not p.is_file() or p.stat().st_size > showit.HUB_MAX_BYTES * 2:
        return None
    kind = "jpeg" if p.suffix == ".jpg" else "png"
    return f"data:image/{kind};base64," + base64.b64encode(p.read_bytes()).decode()


def inline_pictures(root: Path, record: dict[str, Any] | None) -> dict[str, str]:
    """The latest pictures as data addresses (the phone's PC mode: small jpgs)."""
    out: dict[str, str] = {}
    if not record:
        return out
    d = showit.shots_root(root) / record.get("dir", record.get("task", ""))
    for kind in record.get("pictures") or {}:
        url = _data_url(d / f"{kind}.jpg") or _data_url(d / f"{kind}.png")
        if url:
            out[kind] = url
    return out


def live(root: Path, preview: LivePreview | None, inline: bool = False) -> dict[str, Any]:
    entry = showit.entry_page(root)
    record = showit.latest(root)
    out = {"entry": entry, "preview": preview.url(root, entry) if preview else None,
           "start_command": showit.start_command(root), "latest": record, "history": showit.history(root)}
    if inline:
        out["images"] = inline_pictures(root, record)
        out.pop("history")
    return out


def session_view(root: Path, reviewer: str | None, since: int = 0) -> dict[str, Any]:
    now = sessionlib.cursor(root)
    if since and since == now:
        return {"cursor": now, "changed": False}
    return {**sessionlib.session(root, reviewer), "changed": True}


def raw(root: Path, kind: str, name: str, task: str = "") -> tuple[bytes, str, dict[str, str]]:
    """A picture of the app (kind 'shot') or a file the project made (kind 'file').

    Pictures are shown; anything else is a download, so nothing the project made runs as a page
    of Roundtable's own."""
    if kind == "shot":
        ok = re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", task or "")
        f = showit.safe_path(showit.shots_root(root) / task, name) if ok else None
    else:
        f = showit.safe_path(root, name)
    if f is None:
        raise FileNotFoundError("that file isn't there")
    headers = {"Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'"}
    if f.suffix.lower() not in IMAGE_TYPES:
        return f.read_bytes(), "application/octet-stream", {**headers, "Content-Disposition": f'attachment; filename="{f.name.replace(chr(34), "")}"'}
    return f.read_bytes(), showit.content_type(f), headers
