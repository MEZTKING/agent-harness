"""Finding the PC on the Wi-Fi: a small answer to the phone's "is Roundtable here?".

While phone access is on, the PC listens on UDP port 8767. A phone on the same Wi-Fi sends
the probe ``ROUNDTABLE? v1`` to the network's broadcast address; the PC answers that phone
alone with its name, the phone server's port and its certificate's fingerprint::

    {"v": 1, "name": "desk-pc", "port": 8766, "fp": "<sha256 of the certificate>"}

What it never does: announce itself unasked, put the pairing code in the answer, or answer
anyone outside the private ranges (home and office networks: 10/8, 172.16/12, 192.168/16,
169.254/16, and this computer itself). The answer is not trusted by the phone:

* for a PC it is already paired with, the phone only takes a new address from an answer whose
  fingerprint is the one it pinned, and TLS pinning still decides when it connects;
* for a first pairing without the QR code, the 8-letter code shown on the PC carries a check
  (:func:`bound_code`): its last two letters come from the certificate's fingerprint and the
  first six letters. The phone checks them against the certificate it is about to trust
  *before* it sends the code, so a stand-in PC on the same Wi-Fi never sees the code.

Standard library only.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import secrets
import socket
import threading
import time

PORT = 8767
PROBE = b"ROUNDTABLE? v1"
VERSION = 1
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I: easy to type; 32 letters, so no bias
CODE_LENGTH = 8
CHECK_LETTERS = 2
MAX_ANSWERS_PER_S = 20  # an answer is no bigger than the probe; this keeps a flood from going anywhere

_PRIVATE = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "127.0.0.0/8"))


def is_private(ip: str) -> bool:
    """A home or office address (or this computer): the only senders the PC answers."""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(a, ipaddress.IPv6Address):
        if a.ipv4_mapped is None:
            return False
        a = a.ipv4_mapped
    return any(a in n for n in _PRIVATE)


# -- the pairing code's check ---------------------------------------------------------------------
def _check(fingerprint: str, head: str) -> str:
    fp = fingerprint.lower().replace(":", "").strip()
    d = hashlib.sha256(f"roundtable-pair-v1:{fp}:{head.upper()}".encode()).digest()
    return "".join(ALPHABET[b % len(ALPHABET)] for b in d[:CHECK_LETTERS])


def bound_code(fingerprint: str) -> str:
    """A new pairing code: six random letters, then two that only this certificate gives."""
    head = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH - CHECK_LETTERS))
    return head + _check(fingerprint, head)


def code_matches(code: str, fingerprint: str) -> bool:
    """Whether a typed code belongs to the PC with this certificate (the phone's check, mirrored)."""
    c = str(code or "").strip().upper()
    if len(c) != CODE_LENGTH or any(ch not in ALPHABET for ch in c):
        return False
    return secrets.compare_digest(c[-CHECK_LETTERS:], _check(fingerprint, c[:-CHECK_LETTERS]))


# -- the answer -----------------------------------------------------------------------------------
def answer(name: str, port: int, fingerprint: str) -> bytes:
    return json.dumps({"v": VERSION, "name": str(name)[:60], "port": int(port), "fp": fingerprint.lower()},
                      separators=(",", ":")).encode()


def reply_for(data: bytes, sender: str, name: str, port: int, fingerprint: str) -> bytes | None:
    """What to send back to one datagram, or None to stay quiet."""
    if not is_private(sender):
        return None
    if data.strip() != PROBE:
        return None
    return answer(name, port, fingerprint)



def _no_udp_resets(s: socket.socket) -> None:
    """Windows: a reply that bounced back ("port unreachable") makes the next recvfrom raise
    ConnectionResetError (WinError 10054). Turn that off, so one stray answer can't stop discovery."""
    if hasattr(socket, "SIO_UDP_CONNRESET"):
        try:
            s.ioctl(socket.SIO_UDP_CONNRESET, False)
        except (OSError, ValueError):
            pass

class Responder:
    """Answers the phone's probe while phone access is on. ``start()`` never raises: a port that is
    taken leaves :attr:`error` set and the phone server running (the QR code still works)."""

    def __init__(self, name: str, port: int, fingerprint: str, *, listen_port: int = PORT, host: str = "0.0.0.0"):
        self.name, self.port, self.fingerprint = name, int(port), fingerprint
        self.listen_port, self.host = listen_port, host
        self.sock: socket.socket | None = None
        self.error = ""
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._window = (0.0, 0)

    @property
    def address(self) -> tuple[str, int] | None:
        return self.sock.getsockname() if self.sock else None

    def start(self) -> "Responder":
        if self.sock:
            return self
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: nobody else may share the port
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.host, self.listen_port))
            _no_udp_resets(s)
            s.settimeout(0.5)
        except OSError as e:
            self.error = (f"Couldn't listen on port {self.listen_port} so the phone can find this PC ({e}). "
                          "The phone can still pair with the QR code.")
            return self
        self.error = ""
        self.sock = s
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, daemon=True, name="phone-discovery")
        self._thread.start()
        return self

    def _allowed_now(self) -> bool:
        start, n = self._window
        now = time.monotonic()
        if now - start >= 1.0:
            self._window = (now, 1)
            return True
        if n >= MAX_ANSWERS_PER_S:
            return False
        self._window = (start, n + 1)
        return True

    def _serve(self) -> None:
        s = self.sock
        while s and not self._stop.is_set():
            try:
                data, addr = s.recvfrom(512)
            except (socket.timeout, ConnectionResetError):
                continue
            except OSError:  # closed by stop(), or Windows' "message too long" for an oversized probe
                if self._stop.is_set() or self.sock is not s:
                    break
                continue
            out = reply_for(data, addr[0], self.name, self.port, self.fingerprint)
            if out is None or not self._allowed_now():
                continue
            try:
                s.sendto(out, addr)
            except OSError:
                pass

    def stop(self) -> None:
        self._stop.set()
        s, self.sock = self.sock, None
        if s:
            try:
                s.close()
            except OSError:
                pass
        t, self._thread = self._thread, None
        if t and t is not threading.current_thread():
            t.join(2)

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())


def find(timeout_s: float = 1.5, targets: tuple[tuple[str, int], ...] = (("255.255.255.255", PORT),)) -> list[dict]:
    """The PCs that answer a probe (the phone's side, for tests and `roundtable phone find`)."""
    found: dict[tuple[str, str], dict] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        _no_udp_resets(s)
        s.settimeout(0.2)
        for t in targets:
            try:
                s.sendto(PROBE, t)
            except OSError:
                pass
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            try:
                data, addr = s.recvfrom(1024)
            except (socket.timeout, ConnectionResetError):
                continue
            try:
                d = json.loads(data)
                if d.get("v") != VERSION or not 0 < int(d["port"]) < 65536 or len(str(d["fp"])) != 64:
                    continue
            except (ValueError, KeyError, TypeError):
                continue
            found[(addr[0], d["fp"])] = {"host": addr[0], "name": str(d.get("name", "")), "port": int(d["port"]), "fp": d["fp"]}
    return list(found.values())
