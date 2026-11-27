"""appserver.Running: an app started with a command, found on its port, and always ended (made-up apps)."""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from roundtable.harness import appserver, livecmd, showit
from roundtable.harness.tools import Workspace

SERVER = """
import http.server, os, socketserver
class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
port = int(os.environ["PORT"])
with socketserver.TCPServer(("127.0.0.1", port), H) as s:
    s.serve_forever()
"""


def made_up_app(tmp_path: Path, script: str = SERVER) -> Path:
    app = tmp_path / "app"
    app.mkdir()
    (app / "server.py").write_text(script, encoding="utf-8")
    (app / "index.html").write_text("<h1>Made-up shop</h1>", encoding="utf-8")
    # a package.json-style recipe: the app's own start script
    (app / "package.json").write_text(json.dumps({"scripts": {"start": f'"{sys.executable}" server.py'}}),
                                      encoding="utf-8")
    return app


def gone(pid: int) -> bool:
    """True once the process has ended (waits up to two seconds)."""
    import subprocess

    for _ in range(40):
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
            if str(pid) not in out:
                return True
        else:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            except PermissionError:
                return False
            try:  # a zombie still answers kill(0): it has ended if it is waiting to be reaped
                if os.waitpid(pid, os.WNOHANG) != (0, 0):
                    return True
            except ChildProcessError:
                return True
        time.sleep(0.05)
    return False


def open_ws(folder: Path) -> Workspace:
    ws = Workspace(folder)
    ws.gate = None  # no gate settings in a test: every command may run
    return ws


def test_running_starts_finds_its_port_and_leaves_nothing_behind(tmp_path):
    app = made_up_app(tmp_path)
    cmd = f'"{sys.executable}" server.py'
    with appserver.Running(app, cmd, ws=open_ws(app), seconds=20) as run:
        assert run.ok, run.error
        assert run.url.startswith("http://127.0.0.1:")
        body = urllib.request.urlopen(run.url + "index.html", timeout=5).read().decode()
        assert "Made-up shop" in body
        pid = run.proc.pid
        assert any(r["pid"] == pid for r in livecmd.running(app))  # the app's Stop and stop_strays see it
    assert gone(pid)
    assert not any(r["pid"] == pid for r in livecmd.running(app))
    assert not appserver.port_open(run.port)


def test_running_ends_the_app_even_on_an_exception(tmp_path):
    app = made_up_app(tmp_path)
    pid = 0
    with pytest.raises(RuntimeError):
        with appserver.Running(app, f'"{sys.executable}" server.py', ws=open_ws(app), seconds=20) as run:
            assert run.ok
            pid = run.proc.pid
            raise RuntimeError("the walk broke")
    assert pid and gone(pid)


def test_a_command_that_never_opens_its_port_is_written_down_not_raised(tmp_path):
    app = made_up_app(tmp_path, "import time\ntime.sleep(60)\n")
    t = time.time()
    with appserver.Running(app, f'"{sys.executable}" server.py', ws=open_ws(app), seconds=1.5) as run:
        assert not run.ok and not run.refused
        assert "didn't open its address within 1.5 seconds" in run.error
        assert run.proc is None  # already ended
    assert time.time() - t < 15


def test_a_command_that_ends_at_once_says_so(tmp_path):
    app = made_up_app(tmp_path, "import sys\nprint('cannot find module express')\nsys.exit(3)\n")
    with appserver.Running(app, f'"{sys.executable}" server.py', ws=open_ws(app), seconds=10) as run:
        assert not run.ok
        assert "ended at once (exit code 3)" in run.error and "express" in run.error


def test_the_gate_is_asked_first_and_a_no_is_a_refusal(tmp_path):
    app = made_up_app(tmp_path)
    asked = []
    with appserver.Running(app, "echo hi", ws=open_ws(app), ask=lambda c: asked.append(c) or "the owner said no") as run:
        assert not run.ok and run.refused and run.error == "the owner said no" and run.proc is None
    assert asked == ["echo hi"]
    ws = open_ws(app)
    ws.allow_shell = False
    with appserver.Running(app, "echo hi", ws=ws) as run:
        assert run.refused and "switched off" in run.error


def test_the_app_gets_a_clean_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-made-up-0123456789")
    app = made_up_app(tmp_path, "import os, sys\nprint('KEY=' + os.environ.get('ANTHROPIC_API_KEY', 'none'))\n"
                                "print('PORT=' + os.environ['PORT'])\nsys.exit(1)\n")
    with appserver.Running(app, f'"{sys.executable}" server.py', ws=open_ws(app), seconds=10) as run:
        pass
    assert "KEY=none" in run.output() and "PORT=" in run.output()


def test_start_recipe_and_needs_start(tmp_path):
    app = made_up_app(tmp_path)
    assert appserver.start_recipe(app) == {"command": "npm start", "from": "package.json"}
    assert appserver.start_recipe(app, {"command": "python -m http.server {port}", "port": "8123", "ready": "health"}) \
        == {"command": "python -m http.server {port}", "port": 8123, "ready": "/health", "from": "kind"}
    assert appserver.needs_start(app, appserver.start_recipe(app)) is False  # a plain page is the app
    (app / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}, "devDependencies": {"vite": "5"}}))
    assert appserver.needs_start(app, appserver.start_recipe(app)) is True  # a bundler builds it
    (app / "package.json").write_text(json.dumps({"scripts": {"start": "node server.js"}}))
    (app / "index.html").write_text('<script type="module" src="/src/main.tsx"></script>')
    assert appserver.needs_start(app, appserver.start_recipe(app)) is True  # the page loads source files
    (app / "index.html").unlink()
    assert appserver.needs_start(app, appserver.start_recipe(app)) is True  # no page without the command
    assert appserver.start_recipe(tmp_path) is None and appserver.needs_start(tmp_path, None) is False


def test_take_shots_starts_an_app_that_needs_it_and_ends_it(tmp_path):
    app = made_up_app(tmp_path)
    (app / "index.html").unlink()
    (app / "page.html").write_text("<h1>Served</h1>")
    (app / "package.json").write_text(json.dumps({"scripts": {"start": f'"{sys.executable}" server.py'}}))
    seen = []

    def render(jobs):
        for j in jobs:
            seen.append(urllib.request.urlopen(j["url"] + "page.html", timeout=5).read().decode())
            Path(j["png"]).write_bytes(b"png")
        return [{"kind": j["kind"], "errors": [], "title": "Served"} for j in jobs]

    rec = showit.take_shots(app, "T1", render=render, ws=open_ws(app))
    assert rec["started"] == "npm start" and rec["entry"] == "/" and set(rec["pictures"]) == {"desktop", "phone"}
    assert seen and all("Served" in s for s in seen)
    assert not livecmd.running(app)


def test_take_shots_without_a_workspace_starts_nothing(tmp_path):
    app = made_up_app(tmp_path)
    (app / "index.html").unlink()
    rec = showit.take_shots(app, "T1", render=lambda jobs: [])
    assert rec["note"] == "nothing to open yet: the app starts with a command (start it from the App tab)"
    assert "started" not in rec
    (app / "package.json").unlink()
    assert showit.take_shots(app, "T2", render=lambda jobs: [])["note"] == \
        "nothing to open yet: no index.html and no start command"


def test_take_shots_on_a_static_project_is_as_it_was(tmp_path):
    """The same record, field for field, with or without a workspace handed in (nothing to start)."""
    def render(jobs):
        for j in jobs:
            Path(j["png"]).write_bytes(b"png-" + j["kind"].encode())
            Path(j["jpg"]).write_bytes(b"jpg")
        return [{"kind": j["kind"], "errors": ["x"], "title": "Shop"} for j in jobs]

    outs = []
    for i, ws in enumerate((None, "ws")):
        app = tmp_path / f"s{i}"
        app.mkdir()
        (app / "index.html").write_text("<h1>Shop</h1>")
        rec = showit.take_shots(app, "T1", render=render, commit="", ws=open_ws(app) if ws else None)
        rec.pop("at")
        outs.append((rec, sorted(p.name for p in (app / ".harness/shots/T1").iterdir())))
    assert outs[0] == outs[1]
    assert outs[0][0] == {"task": "T1", "dir": "T1", "seq": 1, "commit": "", "entry": "index.html", "title": "Shop",
                          "pictures": {"desktop": "desktop.png", "phone": "phone.png"}, "errors": ["x"], "note": ""}


# -- the App tab (ui/appapi.py) --------------------------------------------------------------------------------
class FakeApp:
    def __init__(self, root, local_only=True):
        self.root, self.local_only = root, local_only

    def cfg(self):
        return object()

    def project(self, cfg, path):
        from types import SimpleNamespace

        assert Path(path) == self.root
        return SimpleNamespace(root=self.root)


def wait_for(fn, seconds=20):
    end = time.time() + seconds
    while time.time() < end:
        got = fn()
        if got:
            return got
        time.sleep(0.1)
    return fn()


def test_the_app_tab_starts_shows_and_stops_an_app(tmp_path):
    from roundtable.ui import appapi

    app_dir = made_up_app(tmp_path)
    (app_dir / "package.json").write_text(json.dumps({"scripts": {"start": f'"{sys.executable}" server.py'}}))
    fake = FakeApp(app_dir)
    routes = appapi.routes(fake)
    v = routes[("GET", "/api/app")]({"path": [str(app_dir)]})
    assert v["command"] == "npm start" and v["static"] == "index.html" and v["state"] == "off"
    assert "starts with a command" in v["words"]
    try:
        v = routes[("POST", "/api/app/start")]({"path": str(app_dir)})
        assert v["state"] in ("starting", "running")
        v = wait_for(lambda: (x := routes[("GET", "/api/app")]({"path": str(app_dir)}))["state"] == "running" and x)
        assert v and v["running"] and v["url"].startswith("http://127.0.0.1:")
        assert "Made-up shop" in urllib.request.urlopen(v["url"], timeout=5).read().decode()
        pid = appapi._apps[str(app_dir.resolve())]["run"].proc.pid
        v = routes[("POST", "/api/app/stop")]({"path": str(app_dir)})
        assert v["state"] == "off" and gone(pid)
    finally:
        appapi.stop_all()


def test_the_app_routes_plug_into_the_server(monkeypatch, tmp_path):
    from roundtable.ui import server

    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "appapi"))
    got = server._feature_routes(FakeApp(tmp_path))
    assert {("GET", "/api/app"), ("POST", "/api/app/start"), ("POST", "/api/app/stop")} <= set(got)


def test_the_app_tab_refuses_when_open_to_other_computers(tmp_path):
    from roundtable.ui import appapi
    from roundtable.ui.server import ApiError

    app_dir = made_up_app(tmp_path)
    routes = appapi.routes(FakeApp(app_dir, local_only=False))
    for route in (("POST", "/api/app/start"), ("POST", "/api/app/stop")):
        with pytest.raises(ApiError) as e:
            routes[route]({"path": str(app_dir)})
        assert e.value.status == 403 and "this computer" in str(e.value)
    assert not appapi._apps


def test_an_app_nobody_looks_at_is_stopped_and_all_stop_at_exit(tmp_path):
    from roundtable.ui import appapi

    app_dir = made_up_app(tmp_path)
    (app_dir / "package.json").write_text(json.dumps({"scripts": {"start": f'"{sys.executable}" server.py'}}))
    try:
        appapi.start_folder(app_dir.resolve())
        rec = wait_for(lambda: appapi._apps.get(str(app_dir.resolve()), {}).get("state") == "running"
                       and appapi._apps[str(app_dir.resolve())])
        pid = rec["run"].proc.pid
        assert appapi.reap(time.time() + 60) == 0  # looked at a minute ago: kept
        assert appapi.reap(time.time() + appapi.IDLE_MINUTES * 60 + 5) == 1 and gone(pid)
        appapi.start_folder(app_dir.resolve())
        assert appapi.stop_all() == 1 and not appapi._apps
    finally:
        appapi.stop_all()


def test_the_phone_never_starts_an_app():
    from roundtable import phone

    assert not [r for r in phone.PHONE_ROUTES if r[1].startswith("/api/app")]
