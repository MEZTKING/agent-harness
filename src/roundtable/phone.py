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

from roundtable import discovery

DEFAULT_PORT = 8766
PAIR_TTL_S = 300
PAIR_TRIES = 5
MAX_WAIT_S = 30

# (method, path) -> allowed for paired phones. Parametrised routes are matched by prefix below.
PHONE_ROUTES = {
    ("GET", "/api/tools"), ("GET", "/api/notifications"), ("GET", "/api/automations"), ("POST", "/api/automations"),
    ("GET", "/api/roundtable"), ("GET", "/api/activity"), ("GET", "/api/chat"), ("POST", "/api/chat"),
    ("GET", "/api/projects"), ("GET", "/api/project"), ("POST", "/api/projects"), ("POST", "/api/project"),
    ("GET", "/api/where"), ("GET", "/api/cards"), ("POST", "/api/send"), ("POST", "/api/reply"),
    ("GET", "/api/thread"), ("GET", "/api/jobs"), ("GET", "/api/roles"), ("GET", "/api/probes"),
    ("GET", "/api/plan"), ("POST", "/api/plan"), ("GET", "/api/asks"), ("POST", "/api/asks"),
    ("GET", "/api/autopilot"), ("POST", "/api/autopilot"),
    ("GET", "/api/project/live"), ("GET", "/api/project/session"),
    ("GET", "/api/files"), ("GET", "/api/files/open"), ("GET", "/api/files/log"), ("POST", "/api/files/run_tests"),
    ("GET", "/api/whatsnew"), ("POST", "/api/whatsnew/seen"),  # what's new after an update (ui/whatsnewapi.py)
    ("GET", "/api/search"), ("GET", "/api/search/peek"), ("GET", "/api/memory"),  # search and memory (ui/searchapi.py)
    # the message box: drafts, attachments, start and send (ui/attachapi.py)
    ("GET", "/api/attach/draft"), ("POST", "/api/attach/draft"), ("POST", "/api/attach/upload"),
    ("POST", "/api/attach/remove"), ("POST", "/api/attach/clear"), ("GET", "/api/attach/files"),
    ("GET", "/api/attach/list"), ("POST", "/api/attach/start"), ("POST", "/api/attach/send"),
    ("GET", "/api/project/settings"), ("POST", "/api/project/settings"),
    ("GET", "/api/setup/recommended"), ("POST", "/api/setup/recommended"),  # the recommended setup, one tap
    # projects that run elsewhere, and the phone and the PC as one Roundtable (sync.py, ui/syncapi.py)
    ("GET", "/api/hub/plan"), ("GET", "/api/hub/live"), ("GET", "/api/notes"), ("GET", "/api/note"), ("POST", "/api/hub/command"), ("GET", "/api/hub/session"), ("POST", "/api/hub/carry_on"),
    ("GET", "/api/machines"), ("GET", "/api/settings/shared"), ("POST", "/api/settings/shared"),
    # undo a task, go back, put it back, try another way (ui/rewindapi.py)
    ("GET", "/api/rewind"), ("GET", "/api/rewind/preview"), ("POST", "/api/rewind"), ("POST", "/api/rewind/undo"),
    ("POST", "/api/rewind/fork"),
    ("GET", "/api/proof"), ("GET", "/api/proof/list"),  # before and after each task (ui/proofapi.py)
    # a task's live command output and its Stop; never the command line itself (ui/terminalapi.py)
    ("GET", "/api/terminal/task"), ("POST", "/api/terminal/task/stop"),
    ("GET", "/api/rates"),  # pounds beside dollars, read through the PC (ui/moneyapi.py)
    # kinds and the Gallery; import and export stay on the PC (ui/kindsapi.py)
    ("GET", "/api/kinds"), ("GET", "/api/kinds/one"), ("POST", "/api/kinds/propose"), ("POST", "/api/kinds/set"),
    ("GET", "/api/gallery"), ("GET", "/api/gallery/one"), ("POST", "/api/gallery/hide"), ("POST", "/api/gallery/star"),
    ("POST", "/api/gallery/again"),
    # what "finished" means and how each check went, with its pictures (ui/doneapi.py)
    ("GET", "/api/done"), ("GET", "/api/done/evidence"),
    ("GET", "/api/stages"),  # the plan's stages and parts (ui/stagesapi.py); the App tab's Start stays on the PC
    ("GET", "/api/tandem/council"),  # where the planners disagreed (ui/councilapi.py); read only
    ("GET", "/api/tandem"),  # the checking level, its allowance and who built and checked each task (ui/tandemapi.py)
    ("GET", "/api/usage"),  # what each service has used against the owner's limits (ui/usageapi.py); limits stay on the PC
    ("GET", "/api/agents"),  # the named agents, to name who did what (ui/agentsapi.py); changes stay on the PC
    # wave 7 (it learns): read-only, except an undo of a learned change and the owner's own house style
    ("GET", "/api/learning/wallet"),  # learning's weekly allowance and what it spent; the figure is set on the PC
    ("GET", "/api/style"), ("POST", "/api/style"),  # the house style (how agents write for the owner)
    ("GET", "/api/charter"),  # what the harness can never change by itself
    ("GET", "/api/market"),  # the plug-ins and skills list; adding or removing stays on the PC
    ("GET", "/api/learned"), ("POST", "/api/learned/undo"),  # what it learned; the phone may only undo a line
    ("GET", "/api/recall"), ("POST", "/api/recall/ask"),  # search by meaning, and Ask (the price comes first)
    # wave 8: words as they are written, / commands, follow-ups and the queue (ui/chatapi.py); the PC-only
    # commands, the question timers and Talk stay on the PC
    ("GET", "/api/stream"), ("GET", "/api/commands"), ("POST", "/api/commands"), ("GET", "/api/follow"),
    ("POST", "/api/follow"), ("GET", "/api/queue"), ("POST", "/api/queue"),
    ("GET", "/api/perms"),  # what each job may do: seen on the phone, changed on the PC (ui/permsapi.py)
    ("GET", "/api/board"),  # the board, read only (ui/boardapi.py); moving a card stays on the PC
    # git history and previews, read only (ui/editapi.py, harness/gitview.py, preview.py): never save, undo,
    # make a PDF or switch branch from the phone
    ("GET", "/api/git/log"), ("GET", "/api/git/commit"), ("GET", "/api/git/diff"), ("GET", "/api/files/preview"),
    ("GET", "/api/browser"),
    # CI, the services list and who is listening, read only (ui/reachapi.py); never /hooks
    ("GET", "/api/ci"), ("GET", "/api/integrations"), ("GET", "/api/listening"),
}
PC_ONLY_ASKS = ("shipoffer",)  # cards answered only on the PC (a download onto the PC itself)
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

    discovery_port = discovery.PORT  # UDP: the phone's "who's there?" on the Wi-Fi (tests use 0: any free port)

    def __init__(self, app, home: Path, name: str | None = None):
        self.app, self.home = app, Path(home)
        self.name = name or socket.gethostname() or "this PC"
        self.file = self.home / "phone.json"
        self.cert, self.key = self.home / "phone-cert.pem", self.home / "phone-key.pem"
        self._lock = threading.Lock()
        self._pairing: dict[str, Any] | None = None
        self._beacon: discovery.Responder | None = None
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
            self.error = f"Couldn't open port {s['port']} for the phone ({e}): choose another port in Settings, or close what uses it."
            return
        self.error = ""
        self.httpd, self.port = httpd, httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True, name="phone-server").start()
        # the phone can find this PC on the Wi-Fi (answers only when asked, private senders only, no code)
        self._beacon = discovery.Responder(self.name, self.port, cert_fingerprint(self.cert),
                                           listen_port=self.discovery_port).start()

    def stop(self) -> None:
        httpd, self.httpd, self.port = self.httpd, None, 0
        beacon, self._beacon = getattr(self, "_beacon", None), None
        if beacon:
            beacon.stop()
        if httpd:
            httpd.shutdown()
            httpd.server_close()

    # -- pairing -----------------------------------------------------------------------------
    def start_pairing(self) -> dict[str, Any]:
        if not self.httpd:
            raise RuntimeError("Turn on phone access first, then press Pair a phone.")
        # 8 letters, the last two bound to this PC's certificate: a stand-in PC fails the phone's check
        code = discovery.bound_code(cert_fingerprint(self.cert))
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
                raise PermissionError("The PC isn't waiting for a phone (the code lasts 5 minutes): press Pair a phone on the PC and try again.")
            p["tries"] += 1
            if p["tries"] > PAIR_TRIES:
                self._pairing = None
                raise PermissionError("Too many wrong codes: press Pair a phone on the PC for a new one.")
            if not secrets.compare_digest(str(code).strip().upper(), p["code"]):
                raise PermissionError("That code isn't right: check the code on the PC and type it again.")
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
                raise ValueError("That phone isn't paired any more: refresh the list.")
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
        raise ValueError("Unknown phone action: use enable, disable, pair or revoke.")


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
    """The phone server's handler. `phone.local` (onphone.LocalAccess) is Roundtable running on the
    phone itself: plain HTTP on 127.0.0.1, the app's launch token, no pairing, plus health and keys."""
    app = phone.app
    local = bool(getattr(phone, "local", False))

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
            dev = None
            if path.startswith("/hooks/"):  # a local hook is only ever the desktop app's, on loopback (reach.py)
                return self._json(404, {"error": "Not here."})
            if local:  # Roundtable on the phone itself (onphone.py): the launch token, before anything else
                if (method, path) == ("GET", "/api/health"):
                    return self._json(200, phone.health())
                dev = self._device()
                if not dev:
                    return self._json(401, {"error": phone.unauthorized})
            if method == "POST" and not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._json(415, {"error": "json only"})
            body = self._body() if method == "POST" else {}
            if body is None:
                return
            if not local and (method, path) == ("POST", "/api/pair/claim"):
                try:
                    return self._json(200, phone.claim(body.get("code", ""), body.get("device_name", "")))
                except PermissionError as e:
                    return self._json(403, {"error": str(e)})
            dev = dev or self._device()
            if not dev:
                return self._json(401, {"error": "This phone isn't paired with the PC (or was removed): pair it again from the PC's Settings."})
            try:
                if local:
                    done, data = phone.local_api(method, path, q, body)
                    if done:
                        return self._json(200, data)
                if (method, path) == ("GET", "/api/ping"):
                    from . import __version__

                    return self._json(200, {"name": phone.name, "version": __version__, "device": dev["name"],
                                            "agent": app.agent})
                if (method, path) == ("GET", "/api/changes"):
                    since = (q.get("since") or [""])[0]
                    wait = float((q.get("wait") or ["25"])[0])
                    return self._json(200, wait_for_change(app, since, wait))
                if not phone_allowed(method, path):
                    return self._json(403, {"error": "That can only be done on the PC itself."})
                if (method, path) == ("POST", "/api/asks") and str(body.get("id", "")).startswith(PC_ONLY_ASKS):
                    return self._json(403, {"error": "That can only be done on the PC itself."})
                data = app.dispatch(method, path, q, body)
                if (method, path) == ("GET", "/api/asks") and isinstance(data, dict):  # PC-only cards stay there
                    data = {**data, "asks": [a for a in data.get("asks") or [] if not a.get("pc_only")]}
                self._json(200, data)
            except Exception as e:  # same error shapes as the desktop API
                from .ui.server import ApiError

                status = e.status if isinstance(e, ApiError) else 400 if isinstance(
                    e, (ValueError, KeyError, PermissionError, RuntimeError, FileNotFoundError)) else 500
                self._json(status, {"error": str(e).strip("'\"") if status != 500 else f"{type(e).__name__}: {e}"})

    return Handler
