"""Show it: pictures of the project's own screens after every approved task.

* ``entry_page`` / ``start_command`` / ``supports_dark``: what there is to open in the project;
* ``safe_path`` / ``content_type`` / ``make_file_handler``: serving files from one folder only
  (no ``..``, no absolute paths, no hidden files, no links that lead outside);
* ``StaticServer``: a tiny local web server on a free port for the length of the pictures;
* ``render_pages``: the pictures, with Playwright for Python or for Node (optional, like the looks);
* ``take_shots``: the whole step, saved to ``.harness/shots/<task>/`` with ``shots.json``;
* ``hub_files``: the latest set (and one picture per finished task, at most ``HUB_KEEP``) for the hub.

Pictures are a help, never a reason to fail a task: every problem is written down instead.
"""

from __future__ import annotations

import json
import mimetypes
import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import quote, unquote, urlparse

from . import look as looklib

SHOTS_DIR = "shots"  # under .harness/
# kind: (width, height, dark)
KINDS = {"desktop": (1280, 800, False), "phone": (390, 844, False), "dark": (1280, 800, True)}
ENTRY_DIRS = ("", "public", "www", "web", "site", "app", "dist", "build", "docs", "src")
SKIP_DIRS = {"node_modules", ".git", ".harness", "vendor", "__pycache__"}
HUB_KEEP = 20  # pictures of earlier tasks kept in the hub (the oldest go first)
HUB_MAX_BYTES = 300_000
TYPES = {
    ".html": "text/html", ".htm": "text/html", ".css": "text/css", ".js": "text/javascript",
    ".mjs": "text/javascript", ".json": "application/json", ".map": "application/json",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".ico": "image/x-icon", ".avif": "image/avif",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".m4a": "audio/mp4",
    ".mp4": "video/mp4", ".webm": "video/webm", ".wasm": "application/wasm",
    ".txt": "text/plain", ".md": "text/plain", ".xml": "application/xml", ".webmanifest": "application/manifest+json",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# -- what there is to open --------------------------------------------------------------------
def entry_page(root: Path) -> str | None:
    """The app's first page (index.html at the top, or in public/, www/, dist/ ...), or None."""
    root = Path(root)
    for d in ENTRY_DIRS:
        p = root / d / "index.html"
        if p.is_file():
            return (PurePosixPath(d) / "index.html").as_posix() if d else "index.html"
    return None


def start_command(root: Path) -> str | None:
    """The app's own start command from package.json (npm start / npm run dev), when it has one."""
    p = Path(root) / "package.json"
    try:
        scripts = (json.loads(p.read_text(encoding="utf-8")) or {}).get("scripts") or {}
    except (OSError, ValueError, AttributeError):
        return None
    if "start" in scripts:
        return "npm start"
    return "npm run dev" if "dev" in scripts else None


def supports_dark(root: Path, limit: int = 200) -> bool:
    """True when the app's pages or styles answer the computer's dark mode (prefers-color-scheme)."""
    root = Path(root)
    seen = 0
    for p in root.rglob("*"):
        if p.suffix.lower() not in (".css", ".html", ".htm", ".js", ".mjs") or not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        seen += 1
        if seen > limit:
            break
        try:
            if "prefers-color-scheme" in p.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            continue
    return False


# -- serving one folder safely ------------------------------------------------------------------
def safe_path(root: Path, rel: str) -> Path | None:
    """The file ``rel`` inside ``root``, or None when it is outside, hidden, a link out, or missing."""
    if not rel or "\x00" in rel:
        return None
    rel = rel.replace("\\", "/")
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        return None
    parts = PurePosixPath(rel).parts
    if any(part in ("..", "") or part.startswith(".") for part in parts):
        return None  # no climbing out, and no .git, .harness or .env
    base = Path(root).resolve()
    full = (base / Path(*parts)).resolve()  # resolve follows links: one that leads outside is refused
    if base not in full.parents or not full.is_file():
        return None
    return full


def content_type(path: Path) -> str:
    ctype = TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype in ("application/json", "application/xml", "image/svg+xml"):
        ctype += "; charset=utf-8"
    return ctype


def make_file_handler(resolve: Callable[[str], Path | None], headers: Callable[[], dict[str, str]] | None = None,
                      hosts: set[str] | None = None):
    """A read-only web handler: GET /<rel> serves ``resolve(rel)``; a folder means its index.html."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "roundtable-show"

        def log_message(self, fmt, *args):  # quiet
            pass

        def _reply(self, status: int, body: bytes, ctype: str, head: bool = False) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (headers() if headers else {}).items():
                self.send_header(k, v)
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def _serve(self, head: bool) -> None:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            if hosts is not None and host not in hosts:
                return self._reply(403, b"forbidden", "text/plain", head)  # DNS-rebinding guard
            rel = unquote(urlparse(self.path).path).lstrip("/")
            if not rel or rel.endswith("/"):
                rel += "index.html"
            f = resolve(rel)
            if f is None:
                return self._reply(404, b"not found", "text/plain", head)
            self._reply(200, f.read_bytes(), content_type(f), head)

        def do_GET(self):
            self._serve(False)

        def do_HEAD(self):
            self._serve(True)

    return Handler


class StaticServer:
    """A local web server for one folder, on a free port, only while the pictures are taken."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.httpd: ThreadingHTTPServer | None = None
        self.url = ""

    def __enter__(self) -> "StaticServer":
        handler = make_file_handler(lambda rel: safe_path(self.root, rel), hosts={"127.0.0.1", "localhost"})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()


# -- pictures -----------------------------------------------------------------------------------
class NoRenderer(RuntimeError):
    """Playwright isn't installed: no pictures, and that's fine."""


_NODE_SCRIPT = r"""
const { chromium } = require('playwright');
let input = '';
process.stdin.on('data', (c) => (input += c));
process.stdin.on('end', async () => {
  const jobs = JSON.parse(input);
  const out = [];
  const browser = await chromium.launch();
  try {
    for (const j of jobs) {
      const ctx = await browser.newContext({ viewport: { width: j.width, height: j.height }, colorScheme: j.dark ? 'dark' : 'light' });
      const page = await ctx.newPage();
      const errors = [];
      page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
      page.on('pageerror', (e) => errors.push(String(e && e.message || e)));
      await page.route('**/*', (r) => {
        const u = r.request().url();
        return (u.startsWith(j.base) || u.startsWith('data:') || u.startsWith('blob:') || /^https:\/\/fonts\.(googleapis|gstatic)\.com\//.test(u))
          ? r.continue() : r.abort();
      });
      try { await page.goto(j.url, { waitUntil: 'load', timeout: 20000 }); }
      catch (e) { errors.push('the page did not finish loading: ' + String(e && e.message || e).slice(0, 200)); }
      await page.waitForTimeout(700);
      await page.screenshot({ path: j.png });
      await page.screenshot({ path: j.jpg, type: 'jpeg', quality: 72 });
      out.push({ kind: j.kind, errors, title: await page.title().catch(() => '') });
      await ctx.close();
    }
  } finally { await browser.close(); }
  process.stdout.write(JSON.stringify(out));
});
"""


_FONTS = re.compile(r"https://fonts\.(googleapis|gstatic)\.com/")


def _may_load(url: str, base: str) -> bool:
    """The app's own files and Google's fonts only: nothing else leaves the computer."""
    return url.startswith((base, "data:", "blob:")) or bool(_FONTS.match(url))


def _render_python(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for j in jobs:
                ctx = browser.new_context(viewport={"width": j["width"], "height": j["height"]},
                                          color_scheme="dark" if j["dark"] else "light")
                page = ctx.new_page()
                errors: list[str] = []
                page.on("console", lambda m, e=errors: e.append(m.text) if m.type == "error" else None)
                page.on("pageerror", lambda exc, e=errors: e.append(str(exc)))
                page.route("**/*", lambda r, b=j["base"]: r.continue_() if _may_load(r.request.url, b) else r.abort())
                try:
                    page.goto(j["url"], wait_until="load", timeout=20000)
                except Exception as e:  # a slow page still gets its picture
                    errors.append(f"the page did not finish loading: {str(e)[:200]}")
                page.wait_for_timeout(700)
                page.screenshot(path=j["png"])
                page.screenshot(path=j["jpg"], type="jpeg", quality=72)
                out.append({"kind": j["kind"], "errors": errors, "title": page.title()})
                ctx.close()
        finally:
            browser.close()
    return out


def _render_node(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    res = subprocess.run([shutil.which("node") or "node", "-e", _NODE_SCRIPT], input=json.dumps(jobs),
                         capture_output=True, text=True, timeout=90 + 30 * len(jobs))
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout).strip()[-400:])
    return json.loads(res.stdout or "[]")


def render_pages(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Take each job's picture (png and a smaller jpg); returns [{kind, errors, title}]."""
    how = looklib.renderer()
    if not how:
        raise NoRenderer("Playwright isn't installed")
    return (_render_python if how == "python" else _render_node)(jobs)


# -- the step ---------------------------------------------------------------------------------
def shots_root(project_root: Path) -> Path:
    return Path(project_root) / ".harness" / SHOTS_DIR


def _safe_task(task_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", task_id).strip(".-") or "task"


def _write_record(out_dir: Path, record: dict[str, Any]) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(record, indent=1, ensure_ascii=False) + "\n"
    (out_dir / "shots.json").write_text(text, encoding="utf-8")
    (out_dir.parent / "latest.json").write_text(text, encoding="utf-8")
    return record


def _errors(results: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for r in results:
        for e in r.get("errors") or []:
            e = str(e).strip()[:300]
            if e and e not in seen:
                seen.append(e)
    return seen[:20]


def take_shots(project_root: Path, task_id: str, render: Callable | None = None) -> dict[str, Any]:
    """Start the app from its folder, take its pictures, and write ``shots.json``. Never raises."""
    root = Path(project_root)
    out_dir = shots_root(root) / _safe_task(task_id)
    record: dict[str, Any] = {"task": task_id, "dir": out_dir.name, "at": _now(), "entry": None, "title": "",
                              "pictures": {}, "errors": [], "note": ""}
    entry = entry_page(root)
    if not entry:
        record["note"] = ("nothing to open yet: no index.html (apps started with a command come in a later "
                          "version of Roundtable)")
        return _write_record(out_dir, record)
    record["entry"] = entry
    start = start_command(root)
    if start:
        record["note"] = f"the app has a start command ({start}); for now Roundtable shows its page as it is"
    kinds = [k for k in KINDS if k != "dark" or supports_dark(root)]
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.*"):
        if old.suffix in (".png", ".jpg"):
            old.unlink()
    try:
        with StaticServer(root) as srv:
            jobs = [{"kind": k, "url": srv.url + quote(entry), "base": srv.url, "png": str(out_dir / f"{k}.png"),
                     "jpg": str(out_dir / f"{k}.jpg"), "width": KINDS[k][0], "height": KINDS[k][1],
                     "dark": KINDS[k][2]} for k in kinds]
            results = (render or render_pages)(jobs)
    except NoRenderer:
        record["note"] = "pictures skipped: Playwright isn't installed on this computer"
        results = []
    except Exception as e:  # pictures are a help, never a reason to fail
        record["failed"] = f"the pictures couldn't be taken: {str(e)[:300]}"
        results = []
    record["pictures"] = {k: f"{k}.png" for k in kinds if (out_dir / f"{k}.png").is_file()}
    record["errors"] = _errors(results or [])
    record["title"] = next((str(r.get("title") or "") for r in results or [] if r.get("title")), "")[:200]
    return _write_record(out_dir, record)


def latest(project_root: Path) -> dict[str, Any] | None:
    p = shots_root(project_root) / "latest.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def history(project_root: Path, limit: int = 40) -> list[dict[str, Any]]:
    """Every task's pictures, newest first."""
    out = []
    for p in shots_root(project_root).glob("*/shots.json"):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda r: r.get("at", ""), reverse=True)[:limit]


# -- the hub ----------------------------------------------------------------------------------
def hub_picture(out_dir: Path, kind: str) -> tuple[str, bytes] | None:
    """The small version of a picture for the hub (jpg; the png only when it is small enough)."""
    for ext in (".jpg", ".png"):
        p = out_dir / f"{kind}{ext}"
        if p.is_file() and p.stat().st_size <= HUB_MAX_BYTES:
            return ext, p.read_bytes()
    return None


def hub_files(project_root: Path, record: dict[str, Any], previous: dict[str, Any] | None,
              base: str) -> dict[str, Any]:
    """Files to write under ``base`` (plans/shots/<project>/): the latest set, one picture per finished
    task (at most HUB_KEEP, the oldest removed: value None), and latest.json listing them."""
    from ..core.store import BinaryFile, TextFile

    out_dir = shots_root(project_root) / record.get("dir", _safe_task(record["task"]))
    files: dict[str, Any] = {}
    pictures: dict[str, str] = {}
    for kind in record.get("pictures") or {}:
        got = hub_picture(out_dir, kind)
        if got:
            name = f"latest-{kind}{got[0]}"
            files[f"{base}/{name}"] = BinaryFile(got[1])
            pictures[kind] = name
    for ext in (".jpg", ".png"):  # a kind (or a format) the latest set no longer has
        for kind in KINDS:
            name = f"latest-{kind}{ext}"
            if pictures.get(kind) != name and name in ((previous or {}).get("pictures") or {}).values():
                files[f"{base}/{name}"] = None
    old = (previous or {}).get("history") or []
    hist = [h for h in old if h.get("task") != record["task"]]
    gone = [h for h in old if h.get("task") == record["task"]]
    if "desktop" in pictures:
        name = f"{_safe_task(record['task'])}-desktop{Path(pictures['desktop']).suffix}"
        files[f"{base}/{name}"] = files[f"{base}/{pictures['desktop']}"]
        hist.insert(0, {"task": record["task"], "at": record["at"], "title": record.get("title", ""), "picture": name})
    for h in gone + hist[HUB_KEEP:]:
        if h.get("picture") and f"{base}/{h['picture']}" not in files:
            files[f"{base}/{h['picture']}"] = None
    files[f"{base}/latest.json"] = TextFile(json.dumps({
        "task": record["task"], "at": record["at"], "title": record.get("title", ""), "pictures": pictures,
        "errors": record.get("errors", [])[:10], "note": record.get("note", ""), "history": hist[:HUB_KEEP],
    }, indent=1, ensure_ascii=False) + "\n")
    return files
