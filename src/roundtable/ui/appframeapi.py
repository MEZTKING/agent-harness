"""A running app's frame on the phone, view only (wave 9, the DS-53 leftover).

    GET /api/app/frame ?path=<project>&page=/<page> -> {html, page, title, words}

The App tab's Start runs an app on this PC (``ui/appapi.py``); this relay lets a paired phone *look* at it:

* only while that Start is running, only the app's own address (``127.0.0.1`` and the port the App tab knows),
  never the harness's own ports, never a host given by the phone: ``page`` is a path and nothing else;
* GET only: there is no POST route, and the page's forms can't send (``form-action 'none'``);
* the page comes back as one piece of HTML with its scripts, styles and pictures inlined from the same app,
  a strict content policy in front (no network for its scripts: ``connect-src 'none'``, pictures only as
  ``data:``), and every link turned into a request back through this relay (``data-relay``), which the phone's
  frame (``static/appframe.js``) or the Android app follows;
* no new open port: it is answered by the phone server that is already listening.
"""

from __future__ import annotations

import base64
import html as htmllib
import re
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urljoin, urlparse

MAX_PAGE = 2_000_000  # the page and everything inlined into it
MAX_HOPS = 3
TIMEOUT_S = 5.0
FRAME_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; "
             "font-src data:; media-src data:; connect-src 'none'; form-action 'none'; frame-src 'none'; "
             "base-uri 'none'")
# the one script added: a tap on a link asks the frame's owner for that page through the relay
LINK_SCRIPT = ("<script>document.addEventListener('click',function(e){var a=e.target.closest&&"
               "e.target.closest('[data-relay]');if(!a)return;e.preventDefault();parent.postMessage("
               "{relay:a.getAttribute('data-relay')},'*');},true);</script>")
NOT_RUNNING = "The app isn't running. Press Start in the project's App tab on the PC, then look again."
_ATTR = r"""(?P<q>["'])(?P<v>.*?)(?P=q)"""
_SCRIPT = re.compile(r"<script\b(?P<a>[^>]*?)\bsrc\s*=\s*" + _ATTR + r"(?P<b>[^>]*)>\s*</script>", re.I | re.S)
_LINK = re.compile(r"<link\b[^>]*>", re.I)
_IMG = re.compile(r"(<img\b[^>]*?\bsrc\s*=\s*)" + _ATTR, re.I | re.S)
_HREF = re.compile(r"(<a\b[^>]*?)\bhref\s*=\s*" + _ATTR, re.I | re.S)
_HEAD = re.compile(r"<head\b[^>]*>", re.I)
_REFRESH = re.compile(r"<meta\b[^>]*http-equiv\s*=\s*[\"']?refresh[^>]*>", re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def routes(app) -> dict[tuple[str, str], Any]:
    return {("GET", "/api/app/frame"): lambda q: frame(app, q or {})}


def _error(text: str, status: int = 400):
    from .server import ApiError

    return ApiError(text, status)


def _first(q: dict, key: str) -> str:
    v = q.get(key, "")
    if isinstance(v, list):
        v = v[0] if v else ""
    return str(v or "")


def harness_ports(app) -> set[int]:
    """The ports the harness itself answers on: never relayed."""
    from .. import otel, phone

    ports = {8765, phone.DEFAULT_PORT, otel.RECEIVER_PORT}
    for p in (getattr(app, "ui_port", None), getattr(getattr(app, "phone", None), "port", None),
              getattr(getattr(app, "_otel_receiver", None), "port", None)):
        if p:
            ports.add(int(p))
    return ports


def clean_page(page: str) -> str:
    """A path on the app's own address, or ValueError. A host, a scheme or a way out of the path is refused."""
    page = str(page or "/").strip() or "/"
    u = urlparse(page)
    if (not page.startswith("/") or page.startswith("//") or "\\" in page or u.scheme or u.netloc
            or any(ord(c) < 32 for c in page)):
        raise _error("That isn't a page of the app: only its own pages can be shown.", 403)
    return page


def running_port(app, path: str) -> int:
    from . import appapi

    root = appapi._root(app, path)
    info = appapi._state(root)
    if not info.get("running") or not info.get("url"):
        raise _error(NOT_RUNNING, 409)
    u = urlparse(info["url"])
    if u.hostname != "127.0.0.1" or not u.port:
        raise _error("That app isn't on this PC's own address, so it isn't shown.", 403)
    if u.port in harness_ports(app):
        raise _error("That address is the harness itself, not your app.", 403)
    return int(u.port)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def fetch(url: str, limit: int) -> tuple[int, str, bytes, str]:
    """(status, content type, body, Location) from the app; never through a proxy, never following a redirect."""
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "darkness-frame"})
    try:
        with _OPENER.open(req, timeout=TIMEOUT_S) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read(limit + 1), ""
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "") if e.headers else "", b"", (e.headers or {}).get("Location", "")
    except (urllib.error.URLError, OSError) as e:
        raise _error(f"The app didn't answer ({getattr(e, 'reason', e)}). Look at the App tab on the PC.", 502) from None


def _same_app(base: str, ref: str) -> str | None:
    """The path (with query) of ``ref`` when it is on the same app as ``base``; else None."""
    if not ref or ref.startswith(("#", "javascript:", "data:", "mailto:", "tel:")):
        return None
    full = urlparse(urljoin(base, ref))
    b = urlparse(base)
    if (full.scheme, full.hostname, full.port) != (b.scheme, b.hostname, b.port):
        return None
    return (full.path or "/") + (f"?{full.query}" if full.query else "")


class _Budget:
    def __init__(self, n: int):
        self.left = n

    def take(self, base: str, ref: str) -> tuple[str, bytes] | None:
        path = _same_app(base, ref)
        if path is None or self.left <= 0:
            return None
        b = urlparse(base)
        status, kind, body, _ = fetch(f"{b.scheme}://{b.hostname}:{b.port}{path}", self.left)
        if status != 200 or len(body) > self.left:
            return None
        self.left -= len(body)
        return kind.split(";")[0].strip() or "application/octet-stream", body


def rewrite(base: str, page: str, raw: str, budget: _Budget) -> str:
    """The page as one piece: scripts, styles and pictures inlined, links back through the relay, the policy."""

    def script(m):
        got = budget.take(base, htmllib.unescape(m.group("v")))
        if not got:
            return ""
        code = got[1].decode("utf-8", "replace").replace("</script", "<\\/script")
        attrs = (m.group("a") + m.group("b")).replace("defer", "").replace("async", "")
        return f"<script{attrs}>{code}</script>"

    def link(m):
        tag = m.group(0)
        if not re.search(r"\brel\s*=\s*[\"']?stylesheet", tag, re.I):
            return ""  # icons, preloads and the like: nothing to fetch from the frame
        href = re.search(r"\bhref\s*=\s*" + _ATTR, tag, re.I | re.S)
        got = budget.take(base, htmllib.unescape(href.group("v"))) if href else None
        if not got:
            return ""
        return "<style>" + got[1].decode("utf-8", "replace").replace("</style", "<\\/style") + "</style>"

    def img(m):
        got = budget.take(base, htmllib.unescape(m.group("v")))
        if not got or not got[0].startswith("image/"):
            return m.group(1) + '""'
        return m.group(1) + f'"data:{got[0]};base64,{base64.b64encode(got[1]).decode()}"'

    def href(m):
        target = _same_app(base, htmllib.unescape(m.group("v")))
        if target is None:
            return m.group(1) + 'data-outside="1"'
        return m.group(1) + f'href="#" data-relay="{htmllib.escape(target)}"'

    out = _REFRESH.sub("", raw)  # the frame never moves itself elsewhere
    out = _SCRIPT.sub(script, out)
    out = _LINK.sub(link, out)
    out = _IMG.sub(img, out)
    out = _HREF.sub(href, out)
    head = f'<meta http-equiv="Content-Security-Policy" content="{FRAME_CSP}">'
    m = _HEAD.search(out)
    out = (out[:m.end()] + head + out[m.end():]) if m else head + out
    return out + LINK_SCRIPT


def frame(app, q: dict) -> dict[str, Any]:
    port = running_port(app, _first(q, "path"))
    page = clean_page(_first(q, "page") or "/")
    for _ in range(MAX_HOPS + 1):
        base = f"http://127.0.0.1:{port}{page}"
        status, kind, body, location = fetch(base, MAX_PAGE)
        if status in (301, 302, 303, 307, 308):
            nxt = _same_app(base, location)
            if nxt is None:
                raise _error("The app sent the page somewhere else, so it isn't shown here.", 403)
            page = nxt
            continue
        if status != 200:
            raise _error(f"The app answered {status} for that page.", 502)
        if len(body) > MAX_PAGE:
            raise _error("That page is too big to show on the phone.", 413)
        if not kind.lower().startswith(("text/html", "application/xhtml")):
            return {"html": "", "page": page, "title": "", "words": "That isn't a page, so there's nothing to show."}
        raw = body.decode("utf-8", "replace")
        title = _TITLE.search(raw)
        html = rewrite(base, page, raw, _Budget(MAX_PAGE - len(body)))
        return {"html": html, "page": page, "title": htmllib.unescape(title.group(1).strip())[:120] if title else "",
                "words": "A view of the app running on the PC. Tap links to move around; nothing can be sent."}
    raise _error("The app kept sending the page elsewhere.", 508)
