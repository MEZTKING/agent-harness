"""A running app's frame on the phone, view only (wave 9, the DS-53 leftover): ui/appframeapi.py."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from roundtable.phone import phone_allowed
from roundtable.ui import appapi, appframeapi
from roundtable.ui.server import ApiError

PAGE = b"""<!doctype html><html><head><title>Made-up Game</title>
<meta http-equiv="refresh" content="0; url=http://outside.example/">
<link rel="stylesheet" href="/game.css"><link rel="icon" href="/icon.png">
<script src="game.js"></script></head>
<body><img src="/hero.png" alt="hero"><a href="/level2?x=1">Level 2</a>
<a href="http://outside.example/steal">Outside</a><form action="/save" method="post"><button>Save</button></form>
</body></html>"""
FILES = {"/": (PAGE, "text/html; charset=utf-8"), "/level2?x=1": (b"<html><head></head><body>Two</body></html>", "text/html"),
         "/game.css": (b"body{color:red}", "text/css"), "/game.js": (b"window.score=1;</script>", "text/javascript"),
         "/hero.png": (b"\x89PNG\r\n\x1a\nfake", "image/png"), "/data.json": (b"{}", "application/json")}


class Made(BaseHTTPRequestHandler):
    posts = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/away":
            self.send_response(302)
            self.send_header("Location", "http://outside.example/")
            self.end_headers()
            return
        if self.path == "/home":
            self.send_response(302)
            self.send_header("Location", "/level2?x=1")
            self.end_headers()
            return
        body, kind = FILES.get(self.path, (b"", ""))
        self.send_response(200 if kind else 404)
        self.send_header("Content-Type", kind or "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        Made.posts.append(self.path)
        self.send_response(200)
        self.end_headers()


@pytest.fixture
def made_app(monkeypatch, tmp_path):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Made)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    state = {"running": True, "url": f"http://127.0.0.1:{port}/"}
    monkeypatch.setattr(appapi, "_root", lambda app, path: Path(tmp_path))
    monkeypatch.setattr(appapi, "_state", lambda root: dict(state))
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")  # a proxy in the way is never used
    app = type("App", (), {})()
    yield app, port, state
    httpd.shutdown()
    httpd.server_close()


def test_the_page_comes_back_whole_with_its_reach_cut(made_app):
    app, port, _ = made_app
    r = appframeapi.frame(app, {"path": ["/p"]})
    html = r["html"]
    assert r["title"] == "Made-up Game" and r["page"] == "/"
    head = html.index("<head>") + len("<head>")
    assert html[head:].startswith('<meta http-equiv="Content-Security-Policy"')
    assert "connect-src 'none'" in html and "form-action 'none'" in html
    assert "<style>body{color:red}</style>" in html and "window.score=1;<\\/script>" in html
    assert 'src="data:image/png;base64,' in html and "/hero.png" not in html
    assert 'data-relay="/level2?x=1"' in html and "outside.example" not in html
    assert "refresh" not in html.lower().replace("look", "") and "icon.png" not in html
    assert html.endswith("</script>") and "postMessage" in html
    assert Made.posts == []


def test_links_are_followed_through_the_relay_and_redirects_stay_on_the_app(made_app):
    app, port, _ = made_app
    assert "Two" in appframeapi.frame(app, {"path": ["/p"], "page": ["/level2?x=1"]})["html"]
    assert appframeapi.frame(app, {"path": ["/p"], "page": ["/home"]})["page"] == "/level2?x=1"
    with pytest.raises(ApiError) as e:
        appframeapi.frame(app, {"path": ["/p"], "page": ["/away"]})
    assert e.value.status == 403
    assert appframeapi.frame(app, {"path": ["/p"], "page": ["/data.json"]})["html"] == ""


@pytest.mark.parametrize("page", ["http://outside.example/", "//outside.example/x", "outside.example",
                                  "/\\outside", "https://127.0.0.1:8765/", "/x\nHost: evil"])
def test_only_the_apps_own_pages_are_asked_for(made_app, page):
    app, *_ = made_app
    with pytest.raises(ApiError) as e:
        appframeapi.frame(app, {"path": ["/p"], "page": [page]})
    assert e.value.status == 403


def test_nothing_is_shown_unless_the_app_tabs_start_is_running(made_app):
    app, port, state = made_app
    state["running"] = False
    with pytest.raises(ApiError) as e:
        appframeapi.frame(app, {"path": ["/p"]})
    assert e.value.status == 409 and "Press Start" in str(e.value)


def test_the_harness_own_ports_are_never_relayed(made_app):
    app, port, state = made_app
    for own in (8765, 8766, 4318):
        state["url"] = f"http://127.0.0.1:{own}/"
        with pytest.raises(ApiError) as e:
            appframeapi.frame(app, {"path": ["/p"]})
        assert e.value.status == 403
    state["url"] = f"http://127.0.0.1:{port}/"
    app.ui_port = port  # the desktop happens to be on that port: refused too
    with pytest.raises(ApiError):
        appframeapi.frame(app, {"path": ["/p"]})
    state["url"] = f"http://localhost:{port}/"
    del app.ui_port
    with pytest.raises(ApiError):
        appframeapi.frame(app, {"path": ["/p"]})


def test_a_post_is_refused(monkeypatch):
    from roundtable.ui import server
    from roundtable.ui.server import UIApp

    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "appframeapi"))
    a = UIApp(None, "missing.yaml")
    assert ("GET", "/api/app/frame") in a.routes() and ("POST", "/api/app/frame") not in a.routes()
    with pytest.raises(ApiError) as e:
        a.dispatch("POST", "/api/app/frame", {}, {"path": "/p", "page": "/save"})
    assert e.value.status == 404
    assert not phone_allowed("POST", "/api/app/frame")
