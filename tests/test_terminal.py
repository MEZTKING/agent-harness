"""The desktop's command line (terminal.py, ui/terminalapi.py): folders, typing, Stop, limits, keys kept out.

Made-up folders, no network.
"""

from __future__ import annotations

import json
import os
import sys
import time

import pytest

from roundtable import terminal
from roundtable.phone import phone_allowed

PY = f'"{sys.executable}"'


def wait_for(s: terminal.Session, text: str, since: int = 0, seconds: float = 15) -> dict:
    end = time.monotonic() + seconds
    got = ""
    while time.monotonic() < end:
        r = s.read(since, wait=0.5)
        got += r["text"]
        since = r["next"]
        if text in got:
            return {"text": got, "next": since, "running": r["running"]}
    raise AssertionError(f"never printed {text!r}; got {got!r}")


def wait_idle(s: terminal.Session, seconds: float = 15) -> None:
    end = time.monotonic() + seconds
    while s.proc is not None and time.monotonic() < end:
        time.sleep(0.05)
    assert s.proc is None


@pytest.fixture
def lines():
    t = terminal.Terminals()
    yield t
    t.close_all()


def test_runs_changes_folder_and_takes_typed_input(tmp_path, lines):
    (tmp_path / "kitchen" / "oven").mkdir(parents=True)
    s = lines.open(tmp_path / "kitchen")
    s.run(f"{PY} -c \"import os; print('here', os.getcwd())\"")
    assert str(tmp_path / "kitchen") in wait_for(s, "here")["text"]
    wait_idle(s)
    s.run("cd oven")
    assert s.folder == (tmp_path / "kitchen" / "oven").resolve()
    s.run("cd nowhere-at-all")
    assert "There's no folder called nowhere-at-all" in s.read(0)["text"]
    s.run("cd ..")
    assert s.folder == (tmp_path / "kitchen").resolve()
    s.run("cd")
    assert s.folder == s.start
    mark = s.end
    s.run(f"{PY} -c \"name = input(); print('hello ' + name)\"")
    assert s.view()["running"]
    with pytest.raises(terminal.TerminalError):
        s.run("echo too soon")
    s.input("Ada")
    assert "hello Ada" in wait_for(s, "hello Ada", mark)["text"]
    wait_idle(s)
    with pytest.raises(terminal.TerminalError):
        s.input("nobody is listening")
    s.run(f"{PY} -c \"raise SystemExit(4)\"")
    wait_idle(s)
    assert "(exit code 4)" in s.read(0)["text"]
    assert s.view()["history"][-1].endswith("SystemExit(4)\"")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return True


def test_stop_ends_a_sleeping_child_and_its_own_child(tmp_path, lines):
    marker = tmp_path / "grandchild.pid"
    (tmp_path / "grand.py").write_text(
        f"import os, time\nopen({str(marker)!r}, 'w').write(str(os.getpid()))\ntime.sleep(60)\n", encoding="utf-8")
    (tmp_path / "child.py").write_text(
        "import subprocess, sys, time\nsubprocess.Popen([sys.executable, 'grand.py'])\n"
        "print('started', flush=True)\ntime.sleep(60)\n", encoding="utf-8")
    s = lines.open(tmp_path)
    s.run(f"{PY} child.py")
    wait_for(s, "started")
    for _ in range(100):
        if marker.exists() and marker.read_text():
            break
        time.sleep(0.05)
    pid = int(marker.read_text())
    s.stop()
    wait_idle(s)
    assert "(stopped)" in s.read(0)["text"]
    time.sleep(0.3)
    assert not _alive(pid)


def test_the_buffer_is_capped(tmp_path, lines):
    s = lines.open(tmp_path)
    s.write(b"a" * (terminal.BUFFER_MAX + 1000))
    s.write(b"END")
    assert len(s.buf) == terminal.BUFFER_MAX and s.base == 1003
    r = s.read(0)
    assert r["cut"] and r["text"].endswith("END") and r["next"] == s.end


def test_the_environment_has_no_keys(tmp_path, lines, monkeypatch):
    from roundtable.core import secrets as vault

    vault.put("DEEPSEEK_API_KEY", "sk-made-up-terminal-0123456789")
    monkeypatch.setenv("MY_SERVICE_TOKEN", "tok-made-up-terminal")
    s = lines.open(tmp_path)
    (tmp_path / "dump.py").write_text("import json, os\nprint('ENV=' + json.dumps(dict(os.environ)))\n",
                                      encoding="utf-8")
    s.run(f"{PY} dump.py")
    out = wait_for(s, "}")["text"]
    wait_idle(s)
    env = json.loads(out.split("ENV=", 1)[1].splitlines()[0])
    assert "DEEPSEEK_API_KEY" not in env and "MY_SERVICE_TOKEN" not in env
    assert "sk-made-up-terminal" not in out and "tok-made-up-terminal" not in out


def test_at_most_four_and_idle_ones_close(tmp_path, lines):
    opened = [lines.open(tmp_path, fresh=True) for _ in range(terminal.MAX_SESSIONS)]
    with pytest.raises(terminal.TerminalError) as e:
        lines.open(tmp_path, fresh=True)
    assert "Close one" in str(e.value)
    assert lines.open(tmp_path) in opened  # the same folder's own line comes back
    opened[0].used -= terminal.IDLE_SECONDS + 1
    lines.reap()
    assert opened[0].id not in lines.sessions and opened[0].closed
    with pytest.raises(terminal.TerminalError):
        lines.get(opened[0].id)


def test_never_a_phone_route():
    for path in ("open", "run", "input", "stop", "close"):
        assert not phone_allowed("POST", f"/api/terminal/{path}")
    assert not phone_allowed("GET", "/api/terminal/read")


def _app(tmp_path):
    from .test_livecmd import _app as make

    return make(tmp_path)


def test_through_the_app_and_refused_when_remote(tmp_path, monkeypatch):
    from roundtable.ui import server

    app, root = _app(tmp_path)
    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "terminalapi"))
    try:
        v = app.dispatch("POST", "/api/terminal/open", {}, {"path": str(root)})
        assert v["folder"] == str(root.resolve())
        app.dispatch("POST", "/api/terminal/run", {}, {"id": v["id"], "line": f"{PY} -c \"print('rolls')\""})
        got, since = "", 0
        for _ in range(40):
            r = app.dispatch("GET", "/api/terminal/read", {"id": [v["id"]], "since": [str(since)], "wait": ["1"]}, {})
            got += r["text"]
            since = r["next"]
            if "rolls" in got and not r["running"]:
                break
        assert "rolls" in got
        assert app.dispatch("POST", "/api/terminal/open", {}, {"path": str(root)})["id"] == v["id"]
        assert app.dispatch("POST", "/api/terminal/close", {}, {"id": v["id"]}) == {"closed": True}
        with pytest.raises(server.ApiError):
            app.dispatch("GET", "/api/terminal/read", {"id": [v["id"]]}, {})
        app.local_only = False  # the app opened to other computers
        for method, path, body in (("POST", "/api/terminal/open", {"path": str(root)}),
                                   ("POST", "/api/terminal/run", {"id": "x", "line": "echo hi"}),
                                   ("GET", "/api/terminal/read", {})):
            with pytest.raises(server.ApiError) as e:
                app.dispatch(method, path, {"id": ["x"]} if method == "GET" else {}, body)
            assert e.value.status == 403 and "this computer" in str(e.value)
    finally:
        from roundtable.ui import terminalapi

        terminalapi.terminals(app).close_all()
