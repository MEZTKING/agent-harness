"""Phone access: a second, separate server for Roundtable Mobile (the Android app).

The desktop server stays on 127.0.0.1. When phone access is on, this one listens on the
network (Wi-Fi, or anywhere through Tailscale) with:

* TLS with a self-signed certificate made on this computer; the phone pins its SHA-256
  fingerprint, which travels in the pairing QR code (so no certificate authority is needed
  and nobody in the middle can pose as the PC);
* paired devices only: pairing takes a one-time code shown on the PC (valid 5 minutes,
  5 tries), the phone gets its own random token, and the PC keeps only its hash; any
  device can be removed from Settings;
* a fixed list of routes: the Roundtable, projects and their actions, chat, the activity
  feed, the hub (journal and messages) and jobs. Settings, API keys, providers and updates
  stay on the PC.
* `GET /api/changes?since=V&wait=S`: long-poll that returns as soon as anything on the
  Roundtable changes, so the phone updates live and can notify without a push service.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import socket
import ssl
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

DEFAULT_PORT = 8766
PAIR_TTL_S = 300
PAIR_TRIES = 5
MAX_WAIT_S = 30

# (method, path) -> allowed for paired phones. Parametrised routes are matched by prefix below.
PHONE_ROUTES = {
    ("GET", "/api/roundtable"), ("GET", "/api/activity"), ("GET", "/api/chat"), ("POST", "/api/chat"),
    ("GET", "/api/projects"), ("GET", "/api/project"), ("POST", "/api/projects"), ("POST", "/api/project"),
    ("GET", "/api/where"), ("GET", "/api/cards"), ("POST", "/api/send"), ("POST", "/api/reply"),
    ("GET", "/api/thread"), ("GET", "/api/jobs"), ("GET", "/api/roles"), ("GET", "/api/probes"),
    ("GET", "/api/plan"), ("POST", "/api/plan"), ("GET", "/api/asks"), ("POST", "/api/asks"),
    ("GET", "/api/autopilot"), ("POST", "/api/autopilot"),
    ("GET", "/api/project/live"), ("GET", "/api/project/session"),
}
PHONE_PREFIXES = (("GET", "/api/journal/"), ("POST", "/api/journal/"), ("GET", "/api/inbox/"),
                  ("POST", "/api/inbox/"), ("GET", "/api/jobs/"))


def phone_allowed(method: str, path: str) -> bool:
    return (method, path) in PHONE_ROUTES or any(method == m and path.startswith(p) for m, p in PHONE_PREFIXES)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def local_addresses() -> list[str]:
    """This computer's IPv4 addresses a phone could reach (Wi-Fi first, then Tailscale)."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; picks the outgoing interface
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    out = []
    for ip in found:
        if ip.startswith("127.") or ip in out:
            continue
        out.append(ip)
    tail = [ip for ip in out if ip.startswith("100.")]  # Tailscale's range, for away from home
    return [ip for ip in out if ip not in tail] + tail


def make_certificate(cert: Path, key: Path, name: str) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    pk = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Roundtable Hold on {name}"[:64])])
    now = datetime.now(timezone.utc)
    c = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(pk.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
         .not_valid_after(now + timedelta(days=3650))
         .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
         .sign(pk, hashes.SHA256()))
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_bytes(pk.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption()))
    try:
        key.chmod(0o600)
    except OSError:
        pass
    cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))


def cert_fingerprint(cert: Path) -> str:
    der = ssl.PEM_cert_to_DER_cert(cert.read_text(encoding="utf-8"))
    return hashlib.sha256(der).hexdigest()


class PhoneAccess:
    """Paired devices, pairing codes, the certificate and the phone server's life cycle."""

    def __init__(self, app, home: Path, name: str | None = None):
        self.app, self.home = app, Path(home)
        self.name = name or socket.gethostname() or "this PC"
        self.file = self.home / "phone.json"
        self.cert, self.key = self.home / "phone-cert.pem", self.home / "phone-key.pem"
        self._lock = threading.Lock()
        self._pairing: dict[str, Any] | None = None
        self.httpd: ThreadingHTTPServer | None = None
        self.port = 0  # the port actually listening (settings may say 0: any free port)
        self.error = ""

    # -- state -------------------------------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.file)

    def settings(self) -> dict[str, Any]:
        d = self._load()
        port = d.get("port")
        return {"enabled": bool(d.get("enabled")), "port": int(DEFAULT_PORT if port is None else port)}

    def devices(self) -> list[dict[str, Any]]:
        return [{k: v for k, v in dev.items() if k != "token_sha256"} for dev in self._load().get("devices", [])]

    def status(self) -> dict[str, Any]:
        s = self.settings()
        running = self.httpd is not None
        out = {**s, "port": self.port or s["port"], "running": running, "error": self.error, "name": self.name, "devices": self.devices(),
               "addresses": local_addresses(), "pairing": None}
        if running and self.cert.is_file():
            out["fingerprint"] = cert_fingerprint(self.cert)
        p = self._pairing
        if p and p["expires"] > time.time():
            out["pairing"] = {"code": p["code"], "uri": self.pair_uri(p["code"]), "expires_in": int(p["expires"] - time.time())}
        return out

    # -- on / off ----------------------------------------------------------------------------
    def ensure_certificate(self) -> None:
        if not (self.cert.is_file() and self.key.is_file()):
            make_certificate(self.cert, self.key, self.name)

    def enable(self, port: int | None = None) -> dict[str, Any]:
        with self._lock:
            d = self._load()
            d["enabled"] = True
            d["port"] = int(port if port is not None else d.get("port") or DEFAULT_PORT)
            self._save(d)
        self.start()
        return self.status()

    def disable(self) -> dict[str, Any]:
        with self._lock:
            d = self._load()
            d["enabled"] = False
            self._save(d)
        self.stop()
        self._pairing = None
        return self.status()

    def start(self) -> None:
        """Start the phone server if phone access is on (called at app start too)."""
        s = self.settings()
        if not s["enabled"] or self.httpd:
            return
        try:
            self.ensure_certificate()
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(self.cert, self.key)
            httpd = ThreadingHTTPServer(("0.0.0.0", s["port"]), make_phone_handler(self))
            httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
            httpd.daemon_threads = True
        except OSError as e:
            self.error = f"couldn't open port {s['port']}: {e}"
            return
        self.error = ""
        self.httpd, self.port = httpd, httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True, name="phone-server").start()

    def stop(self) -> None:
        httpd, self.httpd, self.port = self.httpd, None, 0
        if httpd:
            httpd.shutdown()
            httpd.server_close()

    # -- pairing -----------------------------------------------------------------------------
    def start_pairing(self) -> dict[str, Any]:
        if not self.httpd:
            raise RuntimeError("turn phone access on first")
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I: easy to type
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        self._pairing = {"code": code, "expires": time.time() + PAIR_TTL_S, "tries": 0}
        return self.status()["pairing"]

    def pair_uri(self, code: str) -> str:
        hosts = ",".join(local_addresses())
        fp = cert_fingerprint(self.cert) if self.cert.is_file() else ""
        return (f"roundtable://pair?v=1&n={quote(self.name)}&h={quote(hosts)}&p={self.port}"
                f"&c={code}&f={fp}")

    def claim(self, code: str, device_name: str) -> dict[str, Any]:
        with self._lock:
            p = self._pairing
            if not p or p["expires"] < time.time():
                raise PermissionError("no pairing in progress: press Pair a phone on the PC")
            p["tries"] += 1
            if p["tries"] > PAIR_TRIES:
                self._pairing = None
                raise PermissionError("too many wrong codes: press Pair a phone on the PC again")
            if not secrets.compare_digest(str(code).strip().upper(), p["code"]):
                raise PermissionError("wrong code")
            self._pairing = None
            token = secrets.token_urlsafe(32)
            dev = {"id": secrets.token_hex(4), "name": (device_name or "phone").strip()[:60], "paired_at": _now(),
                   "last_seen": _now(), "token_sha256": _hash(token)}
            d = self._load()
            d.setdefault("devices", []).append(dev)
            self._save(d)
        return {"token": token, "device_id": dev["id"], "name": self.name}

    def revoke(self, device_id: str) -> dict[str, Any]:
        with self._lock:
            d = self._load()
            before = len(d.get("devices", []))
            d["devices"] = [x for x in d.get("devices", []) if x.get("id") != device_id]
            if len(d["devices"]) == before:
                raise ValueError("no such device")
            self._save(d)
        return self.status()

    def device_for(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        h = _hash(token)
        d = self._load()
        for dev in d.get("devices", []):
            if secrets.compare_digest(dev.get("token_sha256", ""), h):
                if dev.get("last_seen", "")[:16] != _now()[:16]:  # at most one write a minute
                    with self._lock:
                        dev["last_seen"] = _now()
                        self._save(d)
                return dev
        return None

    # -- desktop API (localhost server only) --------------------------------------------------
    def api(self, body: dict[str, Any]) -> dict[str, Any]:
        action = body.get("action")
        if action == "enable":
            return self.enable(body.get("port"))
        if action == "disable":
            return self.disable()
        if action == "pair":
            self.start_pairing()
            return self.status()
        if action == "revoke":
            return self.revoke(str(body.get("device_id", "")))
        raise ValueError("action: enable, disable, pair or revoke")


# -- live changes ------------------------------------------------------------------------------
def change_version(app) -> str:
    """A short digest of everything the Roundtable shows; changes whenever the phone should refresh."""
    from .ui.roundtable import activity, build

    data = build(app)
    data.pop("synced_at", None)
    feed = activity(app, limit=1)
    jobs = sorted((j.id, j.status) for j in app.jobs.jobs.values())
    raw = json.dumps([data, feed[:1], jobs], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def wait_for_change(app, since: str, wait_s: float, poll_s: float = 1.5) -> dict[str, Any]:
    end = time.monotonic() + max(0.0, min(wait_s, MAX_WAIT_S))
    while True:
        v = change_version(app)
        if v != since or time.monotonic() >= end:
            return {"version": v, "changed": v != since}
        time.sleep(poll_s)


# -- the phone server -------------------------------------------------------------------------
def make_phone_handler(phone: PhoneAccess):
    app = phone.app

    class Handler(BaseHTTPRequestHandler):
        server_version = "roundtable-phone"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        def _json(self, status: int, data: Any):
            body = json.dumps(data, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _device(self):
            auth = self.headers.get("Authorization") or ""
            return phone.device_for(auth[7:].strip() if auth.startswith("Bearer ") else "")

        def _body(self) -> dict[str, Any] | None:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 2_000_000:
                self._json(413, {"error": "too large"})
                return None
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid JSON"})
                return None
            return body if isinstance(body, dict) else {}

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def _handle(self, method: str):
            url = urlparse(self.path)
            path, q = url.path, parse_qs(url.query)
            if method == "POST" and not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._json(415, {"error": "json only"})
            body = self._body() if method == "POST" else {}
            if body is None:
                return
            if (method, path) == ("POST", "/api/pair/claim"):
                try:
                    return self._json(200, phone.claim(body.get("code", ""), body.get("device_name", "")))
                except PermissionError as e:
                    return self._json(403, {"error": str(e)})
            dev = self._device()
            if not dev:
                return self._json(401, {"error": "this phone isn't paired (or was removed): pair it again"})
            try:
                if (method, path) == ("GET", "/api/ping"):
                    from . import __version__

                    return self._json(200, {"name": phone.name, "version": __version__, "device": dev["name"],
                                            "agent": app.agent})
                if (method, path) == ("GET", "/api/changes"):
                    since = (q.get("since") or [""])[0]
                    wait = float((q.get("wait") or ["25"])[0])
                    return self._json(200, wait_for_change(app, since, wait))
                if not phone_allowed(method, path):
                    return self._json(403, {"error": "not available from the phone; use the PC"})
                self._json(200, app.dispatch(method, path, q, body))
            except Exception as e:  # same error shapes as the desktop API
                from .ui.server import ApiError

                status = e.status if isinstance(e, ApiError) else 400 if isinstance(
                    e, (ValueError, KeyError, PermissionError, RuntimeError, FileNotFoundError)) else 500
                self._json(status, {"error": str(e).strip("'\"") if status != 500 else f"{type(e).__name__}: {e}"})

    return Handler
