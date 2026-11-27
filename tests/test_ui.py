import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
import yaml

from roundtable.ui.server import ApiError, UIApp, make_handler

from .test_hub import RAW as HUB_RAW
from .test_harness import RAW as HARNESS_RAW, Brain, make as make_harness


@pytest.fixture
def app(tmp_path):
    hub_raw = json.loads(json.dumps(HUB_RAW))
    hub_raw["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
    (tmp_path / "hub.yaml").write_text(yaml.safe_dump(hub_raw), encoding="utf-8")
    a = UIApp(hub_config=str(tmp_path / "hub.yaml"), harness_config=str(tmp_path / "missing.yaml"),
              agent="backend", projects_dir=str(tmp_path / "projects"))
    # harness side: scripted providers, injected
    orch, *_ = make_harness(tmp_path, brain=Brain())
    cfg = orch.cfg
    cfg.lab_dir = tmp_path / "lab"
    a.cfg = lambda: cfg
    a._cfg = cfg
    return a


def call(app, method, route, body=None, **q):
    return app.dispatch(method, route, {k: [v] for k, v in q.items()}, body or {})


def wait_job(app, job_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = call(app, "GET", f"/api/jobs/{job_id}")
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_journal_and_where(app):
    e = call(app, "POST", "/api/journal/backend", {"kind": "todo", "text": "ship it", "priority": "high"})
    call(app, "POST", "/api/journal/frontend", {"kind": "session", "text": "did navbar", "next": ["footer"]})
    briefs = call(app, "GET", "/api/where")
    assert [b["agent"] for b in briefs][:2] == ["frontend", "backend"]  # most recent first, all agents listed
    assert briefs[1]["open_todos"][0]["id"] == e["id"]
    call(app, "POST", f"/api/journal/backend/{e['id']}/close", {})
    assert call(app, "GET", "/api/journal/backend", status="open") == []
    with pytest.raises(ValueError):
        call(app, "POST", "/api/journal/backend", {"kind": "todo", "text": ""})


def test_cards_and_messages(app):
    call(app, "POST", "/api/cards/backend", {"status": "live", "change_note": "v1"})
    assert next(c for c in call(app, "GET", "/api/cards") if c["agent"] == "backend")["status"] == "live"
    [m] = call(app, "POST", "/api/send", {"from": "frontend", "to": ["backend"], "subject": "hi", "body": "q?"})
    inbox = call(app, "GET", "/api/inbox/backend")
    assert inbox[0]["id"] == m["id"]
    r = call(app, "POST", "/api/reply", {"as": "backend", "message_id": m["id"], "body": "a!"})
    assert r["recipient"] == "frontend"
    call(app, "POST", "/api/inbox/backend/read", {"ids": [m["id"]]})
    assert call(app, "GET", "/api/inbox/backend") == []
    thread = call(app, "GET", "/api/thread", **{"as": "frontend", "thread": m["thread_id"]})
    assert [t["body"] for t in thread] == ["q?", "a!"]


def test_harness_project_lifecycle_via_ui(app, tmp_path):
    job = call(app, "POST", "/api/projects", {"dir": "site", "goal": "bakery", "approve": True})
    j = wait_job(app, job["id"])
    assert j["status"] == "done" and j["result"]["status"] == "awaiting_approval"
    assert any("Plan:" in line for line in j["log"])
    [p] = call(app, "GET", "/api/projects")
    assert p["status"] == "awaiting_approval"
    call(app, "POST", "/api/project", {"path": p["path"], "action": "approve"})
    j = wait_job(app, call(app, "POST", "/api/project", {"path": p["path"], "action": "run"})["id"])
    assert j["result"]["status"] == "done"
    d = call(app, "GET", "/api/project", path=p["path"])
    assert {t["status"] for t in d["tasks"]} == {"done"} and d["summary"] and d["events"]
    call(app, "POST", "/api/project", {"path": p["path"], "action": "feedback", "task": "T1", "rating": "bad", "note": "meh"})
    assert "owner_feedback" in (tmp_path / "projects/site/.harness/metrics.jsonl").read_text(encoding="utf-8")
    with pytest.raises(ApiError):  # only registered projects are addressable
        call(app, "GET", "/api/project", path="/etc")
    with pytest.raises(ApiError):
        call(app, "POST", "/api/projects", {"dir": "site", "goal": "again"})


def test_one_run_per_project(app):
    gate = threading.Event()
    app.jobs.start("run", "slow", lambda job: gate.wait(5), target="X")
    with pytest.raises(ApiError):
        app.jobs.start("run", "again", lambda job: None, target="X")
    gate.set()


def test_improve_and_models_endpoints(app):
    roles = call(app, "GET", "/api/roles")
    assert {r["name"] for r in roles["roles"]} >= {"coder", "reviewer"}
    p = call(app, "POST", "/api/improve", {"action": "propose", "role": "coder", "kind": "routing",
                                           "models": ["b/coder2", "a/coder"], "risk": "low"})
    assert call(app, "GET", "/api/proposals")["proposals"][0]["id"] == p["id"]
    j = wait_job(app, call(app, "POST", "/api/improve", {"action": "apply", "id": p["id"], "skip_probe": True})["id"])
    assert j["status"] == "failed" and "no passed replay test" in j["error"]  # owner routing needs a test or force
    j = wait_job(app, call(app, "POST", "/api/improve", {"action": "apply", "id": p["id"], "skip_probe": True,
                                                         "force": True})["id"])
    assert j["status"] == "done"
    assert "coder" in call(app, "GET", "/api/proposals")["learned"]["roles"]
    call(app, "POST", "/api/improve", {"action": "rollback"})
    assert call(app, "GET", "/api/proposals")["learned"] == {}
    assert call(app, "GET", "/api/probes") == {"models": []}


@pytest.fixture
def server(app):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app, token=None, allow_remote=False))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def http(url, method="GET", body=None, headers=None):
    req = urllib.request.Request(url, method=method, headers=headers or {},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def test_http_serves_ui_and_guards_writes(server):
    status, body, headers = http(server + "/")
    assert status == 200 and (b"Darkness Harness" in body or b"Roundtable Hold" in body) and "script-src 'self'" in headers["Content-Security-Policy"]
    assert http(server + "/app.js")[0] == 200

    # the Candlelit Oak look: everything it needs is served from here (nothing outside), with the right types
    for name, ctype in (("style.css", "text/css"), ("theme.js", "javascript"), ("fraunces.woff2", "font/woff2"),
                        ("nunito-sans.woff2", "font/woff2"), ("hall.webp", "image/webp"), ("table.webp", "image/webp"),
                        ("emblem.png", "image/png"), ("icon.png", "image/png")):
        st, data, hd = http(server + "/" + name)
        assert st == 200 and data and ctype in hd["Content-Type"], name
    css = http(server + "/style.css")[1].decode()
    assert "@media (prefers-color-scheme: dark)" in css and ':root[data-theme="dark"]' in css and "prefers-reduced-motion" in css
    assert "http://" not in css and "https://" not in css
    assert http(server + "/../pyproject.toml")[0] == 404
    assert http(server + "/api/where")[0] == 200
    ok_headers = {"Content-Type": "application/json", "X-Agent-Hub": "1"}
    body = {"kind": "note", "text": "x"}
    assert http(server + "/api/journal/backend", "POST", body, {"Content-Type": "application/json"})[0] == 403
    assert http(server + "/api/journal/backend", "POST", body, {"X-Agent-Hub": "1", "Content-Type": "text/plain"})[0] == 415
    assert http(server + "/api/journal/backend", "POST", body, ok_headers)[0] == 200
    assert http(server + "/api/where", headers={"Host": "attacker.example"})[0] == 403  # DNS rebinding
    status, body, _ = http(server + "/api/journal/backend", "POST", {"kind": "bogus", "text": "x"}, ok_headers)
    assert status == 400 and b"kind must be" in body


def test_token_required_when_remote(app):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app, token="s3cret", allow_remote=True))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        assert http(url + "/api/where")[0] == 403
        assert http(url + "/api/where", headers={"X-Token": "s3cret"})[0] == 200
        import http.client as hc

        conn = hc.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
        conn.request("GET", "/?token=s3cret")
        r = conn.getresponse()
        assert r.status == 302 and "ahtoken=s3cret" in r.getheader("Set-Cookie")  # login link sets a cookie
        assert http(url + "/api/where", headers={"Cookie": "ahtoken=s3cret"})[0] == 200
        assert http(url + "/api/where", headers={"Cookie": "ahtoken=wrong"})[0] == 403
    finally:
        httpd.shutdown()
