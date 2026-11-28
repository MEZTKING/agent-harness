"""The page for an iPhone on your Wi-Fi (wave 9, DS-70): the desktop's own screens, narrow, from the phone server.

The owner's answer (27 November 2026): no iPhone app; the phone's screens as a page an iPhone opens on the
same Wi-Fi. **Built switched off.** Nothing is served at ``/m/`` until it is on, and it can only be turned on
once Fable's advice has been taken (``ADVISED``, set in code by the coordinator with a note in
``plans/notes-for-owner.md``) and the owner has said yes on its card (:func:`answer`).

* ``/m/`` serves the page's shell (``ui/static/webphone/``) and the desktop's own modules from ``ui/static/``,
  GET only, nothing outside that folder, only the kinds of file the page uses.
* The page's calls go to the phone server's ``/api/…`` with the paired token, so they meet the same
  ``PHONE_ROUTES``, the same narrowing (``PHONE_NARROW``) and the same refusals as the Android app.
* Pairing as now: the PC shows a code; the page sends it to ``/api/pair/claim`` and keeps the token for the
  session, or longer with "Keep me signed in on this iPhone". The iPhone shows on the PC as a paired device
  that can be removed.
* **The honest problem.** A browser can't pin our certificate the way the Android app does: Safari warns the
  first time. The PC shows the certificate's fingerprint (in the groups Safari's certificate view shows) and
  the same thing as six words, to compare before going on. Only the comparison with Safari's own certificate
  view protects against someone in the middle: words drawn by the page itself come through the same
  connection.
* Same Wi-Fi only: a request to ``/m/`` from outside the private ranges is refused.
"""

from __future__ import annotations

import ipaddress
import json
import mimetypes
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

FILE = "webphone.json"
STATIC = Path(__file__).resolve().parent / "ui" / "static"
SHELL = "webphone/index.html"
PREFIX = "/m/"
DEVICE_NAME = "iPhone (web page)"
# Fable's advice on the certificate warning: False until it has been asked and the answer noted for the owner
ADVISED = False
KINDS = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".png": "image/png", ".webp": "image/webp", ".woff2": "font/woff2",
         ".svg": "image/svg+xml", ".md": "text/plain; charset=utf-8"}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self'; connect-src 'self'; frame-src 'self' about:; object-src 'none'; base-uri 'none'; "
       "form-action 'self'; frame-ancestors 'none'")
WAITS_ADVICE = ("Not yet: the page for an iPhone waits for advice on its certificate warning, then for your yes "
                "on its card in Needs you.")
WAITS_OWNER = "Not yet: say yes on the card about the page for an iPhone (in Needs you) first."
_LOCK = threading.Lock()
# 64 short, plain words: six of them carry the first 36 bits of the fingerprint
WORDS = ("apple", "badge", "cabin", "daisy", "eagle", "fable", "grape", "harbour", "island", "jelly", "kettle",
         "lemon", "maple", "noodle", "otter", "pepper", "quilt", "raven", "salmon", "tiger", "umbrella", "violet",
         "walnut", "yellow", "zebra", "anchor", "bridge", "candle", "dragon", "ember", "forest", "garden",
         "hollow", "ivory", "jacket", "kitten", "ladder", "meadow", "nectar", "orange", "pebble", "rocket",
         "saddle", "thunder", "velvet", "willow", "breeze", "copper", "dolphin", "falcon", "glacier", "hazel",
         "lantern", "marble", "nickel", "olive", "parrot", "ribbon", "silver", "timber", "valley", "winter",
         "button", "cherry")


# -- the switch ------------------------------------------------------------------------------------------------------
def _file(home) -> Path:
    if home is None:
        from .desktop import app_home

        home = app_home()
    return Path(home) / FILE


def _load(home) -> dict[str, Any]:
    try:
        d = json.loads(_file(home).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(home, d: dict[str, Any]) -> None:
    p = _file(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def enabled(home) -> bool:
    """On only when the owner turned it on, after the advice and their yes (a file edited by hand can't skip)."""
    d = _load(home)
    return bool(d.get("enabled")) and ADVISED and d.get("owner_yes") is True


def can_turn_on(home) -> tuple[bool, str]:
    if not ADVISED:
        return False, WAITS_ADVICE
    if _load(home).get("owner_yes") is not True:
        return False, WAITS_OWNER
    return True, ""


def set_enabled(home, on: bool) -> bool:
    if on:
        ok, why = can_turn_on(home)
        if not ok:
            raise PermissionError(why)
    with _LOCK:
        d = _load(home)
        d["enabled"] = bool(on)
        _save(home, d)
    return enabled(home)


def answer(home, yes: bool) -> dict[str, Any]:
    """The owner's answer on the card. A no also switches the page off."""
    with _LOCK:
        d = _load(home)
        d["owner_yes"] = bool(yes)
        d["answered_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        if not yes:
            d["enabled"] = False
        _save(home, d)
    return state(home)


def state(home) -> dict[str, Any]:
    d = _load(home)
    ok, why = can_turn_on(home)
    return {"enabled": enabled(home), "can_turn_on": ok, "why_not": why, "advised": ADVISED,
            "owner_yes": d.get("owner_yes"), "answered_at": d.get("answered_at", "")}


# -- the certificate, said so a person can compare it ------------------------------------------------------------------
def fingerprint_groups(fp: str) -> str:
    """``AB CD EF …``: the SHA-256 in the pairs Safari's certificate view shows."""
    fp = "".join(c for c in str(fp or "").upper() if c in "0123456789ABCDEF")
    return " ".join(fp[i:i + 2] for i in range(0, len(fp), 2))


def fingerprint_words(fp: str) -> list[str]:
    """Six words from the fingerprint's first 36 bits (the same on the PC and the page)."""
    fp = "".join(c for c in str(fp or "").lower() if c in "0123456789abcdef")
    if len(fp) < 9:
        return []
    bits = int(fp[:9], 16)
    return [WORDS[(bits >> (6 * (5 - i))) & 63] for i in range(6)]


# -- who may ask ---------------------------------------------------------------------------------------------------
_PRIVATE = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
                                                "127.0.0.0/8", "fc00::/7", "fe80::/10", "::1/128")]


def is_private(address: str) -> bool:
    """A home Wi-Fi's own addresses (and this computer). Tailscale's and public addresses are not."""
    try:
        ip = ipaddress.ip_address(str(address).split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in n for n in _PRIVATE if n.version == ip.version)


# -- serving the page ----------------------------------------------------------------------------------------------
def _headers(kind: str) -> dict[str, str]:
    h = {"Content-Type": kind, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
         "Cache-Control": "no-store" if kind.startswith("text/html") else "private, max-age=300"}
    if kind.startswith("text/html"):
        h["Content-Security-Policy"] = CSP
        h["X-Frame-Options"] = "DENY"
    return h


def _plain(status: int, text: str) -> tuple[int, dict[str, str], bytes]:
    return status, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff"}, text.encode()


def is_page(path: str) -> bool:
    return path == "/m" or path.startswith(PREFIX)


def file_for(path: str) -> Path | None:
    """The file ``/m/<rel>`` names, inside ``ui/static/`` only, or None."""
    rel = path[len(PREFIX):] if path.startswith(PREFIX) else ""
    rel = rel or SHELL
    if "\\" in rel or "\x00" in rel or rel.startswith("/") or any(p in ("..", ".", "") for p in rel.split("/")):
        return None
    if Path(rel).suffix.lower() not in KINDS:
        return None
    f = (STATIC / rel).resolve()
    try:
        f.relative_to(STATIC)
    except ValueError:
        return None
    return f if f.is_file() else None


def serve(home, method: str, path: str, client: str) -> tuple[int, dict[str, str], bytes]:
    """(status, headers, body) for a request under ``/m/``. Off: nothing is served at all."""
    if not enabled(home):
        return _plain(404, "Not here.")
    if not is_private(client):
        return _plain(403, "The page for an iPhone only opens on the same Wi-Fi as the PC.")
    if method != "GET":
        return _plain(405, "This page only reads: the buttons on it talk to the PC's phone server.")
    if path == "/m":
        return 308, {"Location": PREFIX, "Content-Length": "0", "Cache-Control": "no-store"}, b""
    f = file_for(path)
    if f is None:
        return _plain(404, "That isn't part of the page.")
    kind = KINDS.get(f.suffix.lower()) or mimetypes.guess_type(f.name)[0] or "application/octet-stream"
    return 200, _headers(kind), f.read_bytes()


def wrap(handler_cls, phone):
    """The phone server's handler with ``/m/`` in front (one hook-up line in ``PhoneAccess.start``):
    ``make_phone_handler(self)`` becomes ``webphone.wrap(make_phone_handler(self), self)``."""

    class Handler(handler_cls):
        def _handle(self, method: str):
            path = self.path.split("?", 1)[0]
            if is_page(path) and not getattr(phone, "local", False):
                status, headers, body = serve(phone.home, method, path, self.client_address[0])
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                if "Content-Length" not in headers:
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return None
            return super()._handle(method)

    return Handler


def status(home, phone_status: dict[str, Any] | None) -> dict[str, Any]:
    """The Settings card: the switch, why it can't be on yet, the addresses and the certificate to compare."""
    st = state(home)
    ps = phone_status or {}
    fp = str(ps.get("fingerprint") or "")
    port = ps.get("port") or 0
    addresses = [a for a in ps.get("addresses") or [] if is_private(a)]
    if not st["enabled"]:
        words = st["why_not"] or "Off. Turn it on to open your projects in Safari on an iPhone on this Wi-Fi."
    elif not ps.get("running"):
        words = "On, but phone access is off: turn on phone access above first."
    else:
        words = "On. Open the address below in Safari on your iPhone."
    return {**st, "words": words, "phone_on": bool(ps.get("running")),
            "links": [f"https://{a}:{port}{PREFIX}" for a in addresses] if st["enabled"] and ps.get("running") else [],
            "fingerprint": fingerprint_groups(fp), "fingerprint_words": fingerprint_words(fp),
            "devices": [d for d in ps.get("devices") or [] if d.get("name") == DEVICE_NAME],
            "warning": ("Safari will warn that the connection isn't private the first time: the PC made its own "
                        "certificate. Before you go on, open the certificate in Safari and check its SHA-256 "
                        "matches the letters shown here.")}
