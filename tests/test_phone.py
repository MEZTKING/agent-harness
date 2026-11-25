import hashlib
import json
import ssl
import threading
import time
import urllib.error
import urllib.request

import pytest

from roundtable.phone import PhoneAccess, phone_allowed, wait_for_change

from .test_roundtable import setup  # noqa: F401  (fixture)


def call(phone, method, path, body=None, token=None):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # the app pins the fingerprint instead; checked below
    req = urllib.request.Request(f"https://127.0.0.1:{phone.port}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.fixture
def phone(setup, tmp_path):  # noqa: F811
    app, orch, brain, cfg = setup
    p = PhoneAccess(app, tmp_path / "home", name="test-pc")
    app.phone = p
    p.enable(port=0)
    yield app, orch, p
    p.stop()


def test_pairing_tls_and_tokens(phone):
    app, orch, p = phone
    st = p.status()
    assert st["running"] and st["port"] and len(st["fingerprint"]) == 64
    # the certificate served is the one whose fingerprint goes in the QR code
    der = ssl.get_server_certificate(("127.0.0.1", p.port))
    assert hashlib.sha256(ssl.PEM_cert_to_DER_cert(der)).hexdigest() == st["fingerprint"]

    assert call(p, "POST", "/api/pair/claim", {"code": "X", "device_name": "pixel"})[0] == 403  # not pairing
    pairing = p.start_pairing()
    assert pairing["uri"].startswith("roundtable://pair?v=1&n=test-pc&h=") and f"&p={p.port}&" in pairing["uri"]
    assert f"&c={pairing['code']}&f={st['fingerprint']}" in pairing["uri"]
    assert call(p, "POST", "/api/pair/claim", {"code": "WRONG123", "device_name": "pixel"})[0] == 403
    code, r = call(p, "POST", "/api/pair/claim", {"code": pairing["code"].lower(), "device_name": "Pixel 9"})
    assert code == 200 and r["name"] == "test-pc"
    token = r["token"]
    assert call(p, "POST", "/api/pair/claim", {"code": pairing["code"], "device_name": "x"})[0] == 403  # single use
    assert "token" not in json.dumps(p.devices()) and p.devices()[0]["name"] == "Pixel 9"
    assert token not in p.file.read_text()  # only its hash is kept

    assert call(p, "GET", "/api/ping")[0] == 401
    assert call(p, "GET", "/api/ping", token="nope")[0] == 401
    code, r = call(p, "GET", "/api/ping", token=token)
    assert code == 200 and r["device"] == "Pixel 9" and r["name"] == "test-pc"

    orch._register_with_lab()
    orch.start("bakery site", require_approval=True)
    orch.run()
    code, data = call(p, "GET", "/api/roundtable", token=token)
    assert code == 200 and data["needs_you"][0]["actions"] == ["approve"]
    # settings, keys and updates stay on the PC
    for method, path in [("GET", "/api/config"), ("POST", "/api/setup/keys"), ("GET", "/api/providers"),
                         ("POST", "/api/update"), ("GET", "/api/phone"), ("POST", "/api/phone")]:
        assert call(p, method, path, {} if method == "POST" else None, token=token)[0] == 403
    # a removed phone is locked out
    p.revoke(p.devices()[0]["id"])
    assert call(p, "GET", "/api/roundtable", token=token)[0] == 401


def test_wrong_codes_end_the_pairing(phone):
    app, orch, p = phone
    code = p.start_pairing()["code"]
    for _ in range(5):
        assert call(p, "POST", "/api/pair/claim", {"code": "AAAAAAAA"})[0] == 403
    assert call(p, "POST", "/api/pair/claim", {"code": code})[0] == 403


def test_changes_long_poll(phone):
    app, orch, p = phone
    v = wait_for_change(app, "", 0)["version"]
    t = time.monotonic()
    assert wait_for_change(app, v, 0.3, poll_s=0.1) == {"version": v, "changed": False}
    assert time.monotonic() - t >= 0.3
    result = {}
    th = threading.Thread(target=lambda: result.update(wait_for_change(app, v, 10, poll_s=0.1)))
    th.start()
    time.sleep(0.3)
    app.hub.journal.add("frontend", "todo", "a new todo shows up on the phone", priority="high")
    th.join(10)
    assert result["changed"] and result["version"] != v


def test_desktop_phone_settings(phone):
    app, orch, p = phone
    st = app.dispatch("POST", "/api/phone", {}, {"action": "pair"})
    assert st["pairing"]["qr"].startswith("data:image/svg+xml;base64,") and len(st["pairing"]["code"]) == 8
    st = app.dispatch("POST", "/api/phone", {}, {"action": "disable"})
    assert not st["running"] and not st["enabled"] and st["pairing"] is None
    assert not phone_allowed("GET", "/api/config") and phone_allowed("GET", "/api/journal/frontend")
