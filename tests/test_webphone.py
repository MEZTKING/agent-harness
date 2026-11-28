"""The page for an iPhone on your Wi-Fi (wave 9, DS-70): built switched off, the same allowed list as the phone."""

import json
import ssl
import urllib.error
import urllib.request

import pytest

from roundtable import phone, webphone

from .test_roundtable import setup  # noqa: F401  (fixture)


def _yes(home, monkeypatch):
    monkeypatch.setattr(webphone, "ADVISED", True)
    webphone.answer(home, True)
    webphone.set_enabled(home, True)


def test_it_is_built_off_and_serves_nothing(tmp_path):
    assert webphone.ADVISED is False  # Fable's advice and the owner's yes come first (plans/notes-for-owner.md)
    assert not webphone.enabled(tmp_path)
    for path in ("/m/", "/m", "/m/webphone/webphone.js", "/m/style.css"):
        status, _, body = webphone.serve(tmp_path, "GET", path, "192.168.1.20")
        assert status == 404 and body == b"Not here."


def test_it_cant_be_switched_on_before_the_advice_and_the_owners_yes(tmp_path, monkeypatch):
    with pytest.raises(PermissionError, match="advice"):
        webphone.set_enabled(tmp_path, True)
    webphone.answer(tmp_path, True)
    with pytest.raises(PermissionError, match="advice"):  # a yes alone isn't enough while the advice is missing
        webphone.set_enabled(tmp_path, True)
    monkeypatch.setattr(webphone, "ADVISED", True)
    webphone.answer(tmp_path, False)
    with pytest.raises(PermissionError, match="say yes"):
        webphone.set_enabled(tmp_path, True)
    webphone.answer(tmp_path, True)
    assert webphone.set_enabled(tmp_path, True) is True
    webphone.answer(tmp_path, False)  # a later no switches it off again
    assert not webphone.enabled(tmp_path)


def test_a_hand_edited_file_doesnt_switch_it_on(tmp_path):
    (tmp_path / "webphone.json").write_text(json.dumps({"enabled": True, "owner_yes": True}))
    assert not webphone.enabled(tmp_path)


def test_only_the_same_wifi_may_open_it(tmp_path, monkeypatch):
    _yes(tmp_path, monkeypatch)
    for ip in ("192.168.1.20", "10.0.0.5", "172.20.1.1", "127.0.0.1", "fe80::1", "::ffff:192.168.0.9"):
        assert webphone.serve(tmp_path, "GET", "/m/", ip)[0] == 200, ip
    for ip in ("8.8.8.8", "100.101.1.2", "2001:4860::8888", "::ffff:8.8.8.8", "not an address"):
        status, _, body = webphone.serve(tmp_path, "GET", "/m/", ip)
        assert status == 403 and b"same Wi-Fi" in body, ip


def test_it_only_reads_and_serves_nothing_outside_static(tmp_path, monkeypatch):
    _yes(tmp_path, monkeypatch)
    assert webphone.serve(tmp_path, "POST", "/m/", "192.168.1.20")[0] == 405
    for bad in ("/m/../phone.py", "/m/webphone/../../server.py", "/m/server.py", "/m/..%2f..%2fphone.py",
                "/m//etc/passwd", "/m/webphone\\..\\..\\phone.py", "/m/nothing.js", "/m/api/settings",
                "/m/api/pair/claim", "/m/../../../../etc/hosts", "/m/.%2e/phone.py", "/m/./style.css"):
        assert webphone.serve(tmp_path, "GET", bad, "192.168.1.20")[0] == 404, bad
    status, headers, body = webphone.serve(tmp_path, "GET", "/m/", "192.168.1.20")
    assert status == 200 and b"Pair" not in body and b"webphone/webphone.js" in body
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"] and headers["X-Frame-Options"] == "DENY"
    assert webphone.serve(tmp_path, "GET", "/m/style.css", "192.168.1.20")[0] == 200
    assert webphone.serve(tmp_path, "GET", "/m/webphone/webphone.js", "192.168.1.20")[1]["Content-Type"].startswith("text/javascript")
    assert webphone.serve(tmp_path, "GET", "/m", "192.168.1.20")[0] == 308


def test_the_certificate_is_said_the_same_way_on_both_screens():
    fp = "ab" * 32
    assert webphone.fingerprint_groups(fp).startswith("AB AB AB") and len(webphone.fingerprint_groups(fp).split()) == 32
    words = webphone.fingerprint_words(fp)
    assert len(words) == 6 and words == webphone.fingerprint_words(fp.upper())
    assert webphone.fingerprint_words("cd" * 32) != words
    assert len(set(webphone.WORDS)) == 64


# -- through the real phone server, with the one hook-up line ------------------------------------------------------
def _call(port, method, path, body=None, token=None):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(f"https://127.0.0.1:{port}{path}", method=method,
                                 data=json.dumps(body).encode() if method == "POST" else None)
    if method == "POST":
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


@pytest.fixture
def server(setup, tmp_path, monkeypatch):  # noqa: F811
    app, orch, brain, cfg = setup
    made = phone.make_phone_handler
    monkeypatch.setattr(phone, "make_phone_handler", lambda p: webphone.wrap(made(p), p))  # the hook-up line
    p = phone.PhoneAccess(app, tmp_path / "home", name="made-up-pc")
    app.phone = p
    p.enable(port=0)
    yield app, p
    p.stop()


def test_off_the_phone_server_answers_nothing_at_m(server):
    app, p = server
    status, body, _ = _call(p.port, "GET", "/m/")
    assert status == 404 and body == "Not here."
    assert _call(p.port, "GET", "/api/roundtable")[0] == 401  # the JSON routes are as they were


def test_on_the_iphone_pairs_and_meets_the_same_allowed_list(server, monkeypatch):
    app, p = server
    _yes(p.home, monkeypatch)
    status, body, headers = _call(p.port, "GET", "/m/")
    assert status == 200 and "webphone/webphone.js" in body and "Content-Security-Policy" in headers
    code = p.start_pairing()["code"]
    status, text, _ = _call(p.port, "POST", "/api/pair/claim", {"code": code, "device_name": webphone.DEVICE_NAME})
    assert status == 200, text
    token = json.loads(text)["token"]
    assert [d["name"] for d in p.devices()] == [webphone.DEVICE_NAME]  # listed on the PC, removable there
    assert _call(p.port, "GET", "/api/roundtable", token=token)[0] == 200
    for m, path in (("GET", "/api/counts"), ("GET", "/api/otel"), ("GET", "/api/webphone"), ("GET", "/api/config"),
                    ("POST", "/api/webphone/answer")):
        status, text, _ = _call(p.port, m, path, {} if m == "POST" else None, token=token)
        assert status == 403 and "only be done on the PC" in text, path
    status, text, _ = _call(p.port, "POST", "/api/asktimer", {"path": "/p", "id": "a1", "minutes": 5}, token=token)
    assert status == 403  # the same narrowing as the Android app
    assert _call(p.port, "GET", "/m/api/roundtable", token=token)[0] == 404
    assert _call(p.port, "POST", "/m/", {}, token=token)[0] == 405
    p.revoke(p.devices()[0]["id"])
    assert _call(p.port, "GET", "/api/roundtable", token=token)[0] == 401


def test_the_iphone_page_isnt_served_by_this_phone_itself(tmp_path, monkeypatch):
    _yes(tmp_path, monkeypatch)

    class Local:
        local, home = True, tmp_path

    class Base:
        def _handle(self, method):
            return "the phone's own handler"

    h = webphone.wrap(Base, Local())()
    h.path, h.client_address = "/m/", ("127.0.0.1", 1)
    assert h._handle("GET") == "the phone's own handler"


# -- the Settings card ------------------------------------------------------------------------------------------------
@pytest.fixture
def app(tmp_path, monkeypatch):
    from roundtable.ui import server as srv
    from roundtable.ui.server import UIApp

    monkeypatch.setattr(srv, "FEATURE_APIS", (*srv.FEATURE_APIS, "webphoneapi"))
    a = UIApp(None, "missing.yaml")
    a._backup_home = lambda: tmp_path
    return a


def test_the_card_says_why_it_cant_be_turned_on(app, monkeypatch):
    from roundtable.ui.server import ApiError

    v = app.dispatch("GET", "/api/webphone", {}, {})
    assert v["enabled"] is False and v["can_turn_on"] is False and "advice" in v["words"] and v["links"] == []
    with pytest.raises(ApiError) as e:
        app.dispatch("POST", "/api/webphone", {}, {"enabled": True})
    assert e.value.status == 403
    monkeypatch.setattr(webphone, "ADVISED", True)
    assert "say yes" in app.dispatch("GET", "/api/webphone", {}, {})["why_not"]
    assert app.dispatch("POST", "/api/webphone/answer", {}, {"yes": True})["can_turn_on"] is True
    v = app.dispatch("POST", "/api/webphone", {}, {"enabled": True})
    assert v["enabled"] is True and "phone access is off" in v["words"]
