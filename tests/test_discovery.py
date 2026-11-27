"""Finding the PC on the Wi-Fi (discovery.py): who gets an answer, what it says, the bound code."""

import json
import socket
import time

import pytest

from roundtable import discovery
from roundtable.discovery import Responder, bound_code, code_matches, is_private, reply_for

from .test_roundtable import setup  # noqa: F401  (fixture)

FP = "ab" * 32
OTHER = "cd" * 32


def test_private_ranges_only():
    for ip in ("10.1.2.3", "172.16.0.9", "172.31.255.1", "192.168.1.20", "169.254.3.4", "127.0.0.1", "::ffff:192.168.0.2"):
        assert is_private(ip), ip
    for ip in ("8.8.8.8", "172.32.0.1", "100.64.0.1", "1.1.1.1", "fe80::1", "2001:db8::1", "nonsense", ""):
        assert not is_private(ip), ip


def test_answers_only_a_proper_probe_from_a_private_sender():
    out = reply_for(b"ROUNDTABLE? v1", "192.168.1.30", "desk-pc", 8766, FP.upper())
    assert json.loads(out) == {"v": 1, "name": "desk-pc", "port": 8766, "fp": FP}
    assert reply_for(b"ROUNDTABLE? v1\n", "10.0.0.4", "desk-pc", 8766, FP)  # a trailing newline is fine
    assert reply_for(b"ROUNDTABLE? v1", "8.8.8.8", "desk-pc", 8766, FP) is None  # public sender
    for bad in (b"", b"ROUNDTABLE? v2", b"hello", b"\xff\xfe", b"ROUNDTABLE? v1 please send the code"):
        assert reply_for(bad, "192.168.1.30", "desk-pc", 8766, FP) is None


def test_the_answer_never_carries_the_pairing_code():
    code = bound_code(FP)
    out = reply_for(b"ROUNDTABLE? v1", "192.168.1.30", "desk-pc", 8766, FP)
    assert code.encode() not in out and set(json.loads(out)) == {"v", "name", "port", "fp"}


def test_bound_code_checks_against_the_certificate():
    for _ in range(200):
        code = bound_code(FP)
        assert len(code) == 8 and all(c in discovery.ALPHABET for c in code)
        assert code_matches(code, FP) and code_matches(code.lower(), FP.upper())
        assert code_matches(code, ":".join(FP[i:i + 2] for i in range(0, 64, 2)))  # colons are fine
    # a stand-in PC (another certificate) fails the check nearly always: 1 in 1024 by chance
    misses = sum(code_matches(bound_code(FP), OTHER) for _ in range(2000))
    assert misses < 15
    code = bound_code(FP)
    assert not code_matches(code[:6] + ("AA" if code[6:] != "AA" else "BB"), FP)
    for bad in ("", "ABC", "ABCDEFG0", "ABCDEFGHJ", None):
        assert not code_matches(bad, FP)


@pytest.fixture
def responder():
    r = Responder("desk-pc", 8766, FP, listen_port=0, host="127.0.0.1").start()
    yield r
    r.stop()


def _ask(addr, payload=b"ROUNDTABLE? v1", wait=1.0):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        discovery._no_udp_resets(s)
        s.settimeout(wait)
        s.sendto(payload, addr)
        try:
            return s.recvfrom(1024)[0]
        except (socket.timeout, ConnectionResetError):  # nobody listening (Windows reports it as a reset)
            return None


def test_responder_answers_and_ignores_junk(responder):
    assert responder.running and not responder.error
    assert json.loads(_ask(responder.address))["fp"] == FP
    assert _ask(responder.address, b"WHO IS THERE", wait=0.4) is None
    assert _ask(responder.address, b"\x00" * 600, wait=0.4) is None  # too long and malformed
    found = discovery.find(0.6, targets=(responder.address,))
    assert found == [{"host": "127.0.0.1", "name": "desk-pc", "port": 8766, "fp": FP}]


def test_responder_ignores_public_senders(monkeypatch, responder):
    monkeypatch.setattr(discovery, "is_private", lambda ip: False)  # as if the probe came from outside
    assert _ask(responder.address, wait=0.4) is None


def test_responder_stops_cleanly_and_frees_its_port():
    r = Responder("desk-pc", 8766, FP, listen_port=0, host="127.0.0.1").start()
    addr = r.address
    r.stop()
    assert not r.running and r.sock is None
    r.stop()  # twice is fine
    assert _ask(addr, wait=0.3) is None
    again = Responder("desk-pc", 8766, FP, listen_port=addr[1], host="127.0.0.1").start()
    try:
        assert again.running and _ask(again.address)
    finally:
        again.stop()


def test_a_taken_port_is_an_error_not_a_crash():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as busy:
        busy.bind(("127.0.0.1", 0))
        r = Responder("desk-pc", 8766, FP, listen_port=busy.getsockname()[1], host="127.0.0.1")
        # SO_REUSEADDR lets a second UDP socket share the port on some systems; force the failure
        import roundtable.discovery as d

        real = d.socket.socket

        class Taken(real):
            def bind(self, addr):
                raise OSError(98, "Address already in use")

        d.socket.socket = Taken
        try:
            r.start()
        finally:
            d.socket.socket = real
    assert not r.running and "QR code" in r.error


def test_flood_is_capped(responder, monkeypatch):
    monkeypatch.setattr(discovery, "MAX_ANSWERS_PER_S", 3)
    answers = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(0.3)
        for _ in range(10):
            s.sendto(b"ROUNDTABLE? v1", responder.address)
        end = time.monotonic() + 0.6
        while time.monotonic() < end:
            try:
                s.recvfrom(1024)
                answers += 1
            except socket.timeout:
                break
    assert 1 <= answers <= 3


def test_find_skips_bad_answers():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as fake:
        fake.bind(("127.0.0.1", 0))
        fake.settimeout(2)
        import threading

        def serve():
            _, addr = fake.recvfrom(64)
            for junk in (b"not json", b'{"v":2,"port":1,"fp":"x"}', json.dumps({"v": 1, "port": 0, "fp": FP}).encode(),
                         json.dumps({"v": 1, "name": "ok", "port": 8766, "fp": FP}).encode()):
                fake.sendto(junk, addr)

        t = threading.Thread(target=serve)
        t.start()
        found = discovery.find(0.6, targets=(fake.getsockname(),))
        t.join()
    assert [f["name"] for f in found] == ["ok"]


# -- the phone server answers while phone access is on (phone.py's hook-up lines) --------------------
def test_hook_up_lines_on_the_phone_server(setup, tmp_path):  # noqa: F811
    from roundtable.phone import PhoneAccess, cert_fingerprint

    app = setup[0]
    p = PhoneAccess(app, tmp_path / "home", name="made-up-pc")
    p.enable(port=0)
    try:
        fp = cert_fingerprint(p.cert)
        answer = json.loads(_ask(("127.0.0.1", p._beacon.address[1])))
        assert answer == {"v": 1, "name": "made-up-pc", "port": p.port, "fp": fp}
        pairing = p.start_pairing()
        assert code_matches(pairing["code"], fp)
        assert f"&c={pairing['code']}&" in pairing["uri"]
        assert p.claim(pairing["code"], "Made-up Phone")["token"]  # the PC still takes the whole code
        beacon = p._beacon
        addr = ("127.0.0.1", beacon.address[1])
        p.disable()  # phone access off: no more answers
        assert not beacon.running and p._beacon is None and _ask(addr, wait=0.3) is None
    finally:
        p.stop()
