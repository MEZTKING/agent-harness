"""A task's command shown as it prints, and a Stop for that one command (harness/livecmd.py). Made-up projects."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

import pytest

from roundtable.harness import livecmd
from roundtable.harness.safeenv import clean_env
from roundtable.harness.tools import ToolError, Workspace, _truncate

PY = f'"{sys.executable}"'

def old_run_command(root, command, timeout):
    """run_command as it was before live output, to compare the text byte for byte."""
    try:
        res = subprocess.run(command, shell=True, cwd=root, capture_output=True, text=True, timeout=timeout,
                             env=clean_env())
    except subprocess.TimeoutExpired:
        raise ToolError(f"command timed out after {timeout}s")
    return _truncate(f"exit code: {res.returncode}\n--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}")

def _py(code: str) -> str:
    return f"{PY} -c \"{code}\""

CASES = {
    "plain": _py("print('bread and butter')"),
    "both_and_exit": _py("import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"),
    "newlines": _py("import sys; sys.stdout.buffer.write(b'a\\r\\nb\\rc\\n')"),
    "accents": _py("import sys; sys.stdout.buffer.write('crème brûlée £3\\n'.encode('utf-8'))"),
    "silent": _py("pass"),
    "long": _py("print('x' * 30000)"),
}

@pytest.mark.parametrize("name", sorted(CASES))
def test_run_command_text_is_the_same_as_before(tmp_path, name):
    ws = Workspace(tmp_path / "bakery")
    cmd = CASES[name]
    assert ws.run_command({"command": cmd}) == old_run_command(ws.root, cmd, 120)

def test_a_timeout_says_the_same_and_ends_the_whole_tree(tmp_path):
    ws = Workspace(tmp_path / "bakery", command_timeout=1)
    marker = tmp_path / "child.pid"
    child = _py(f"import os,time; open(r'{marker}','w').write(str(os.getpid())); time.sleep(60)")
    cmd = f"{child} & {child}" if os.name != "nt" else child
    with pytest.raises(ToolError) as new:
        ws.run_command({"command": cmd, "timeout": 1})
    with pytest.raises(ToolError) as old:
        old_run_command(ws.root, _py("import time; time.sleep(5)"), 1)
    assert str(new.value) == str(old.value) == "command timed out after 1s"
    if os.name != "nt" and marker.exists():
        pid = int(marker.read_text())
        time.sleep(0.3)
        assert not _alive(pid)  # the grandchild went with it
    log = (ws.root / ".harness" / "live" / "run-1.log").read_text(encoding="utf-8")
    assert log.endswith("[timed out after 1s]\n")

def test_output_is_written_as_it_arrives_and_tailed_with_since(tmp_path):
    ws = Workspace(tmp_path / "bakery")
    ws.live = (tmp_path / "bakery", "t2")
    flag = tmp_path / "go"
    cmd = _py(f"import os,time,sys; print('first', flush=True); "
              f"[time.sleep(0.05) for _ in range(200) if not os.path.exists(r'{flag}')]; print('second')")
    out: list[str] = []
    th = threading.Thread(target=lambda: out.append(ws.run_command({"command": cmd})))
    th.start()
    root = ws.root
    for _ in range(100):
        t = livecmd.tail(root, "t2")
        if "first" in t["text"]:
            break
        time.sleep(0.05)
    assert t["running"] and t["n"] == 1 and "first" in t["text"] and "second" not in t["text"]
    assert t["command"].startswith(PY.strip('"')) or "print" in t["command"]
    assert [c["task"] for c in livecmd.running(root)] == ["t2"]
    flag.write_text("x")
    th.join(20)
    t2 = livecmd.tail(root, "t2", since=t["next"], n=1)
    assert "second" in t2["text"] and "first" not in t2["text"]
    assert not t2["running"] and t2["ended"] == "[exit code 0]" and t2["words"] == "Finished."
    assert livecmd.running(root) == []
    assert out[0].startswith("exit code: 0\n--- stdout ---\nfirst\n")
    # the next command is n=2; a reader still on n=1 starts again from its beginning
    ws.run_command({"command": _py("print('third')")})
    t3 = livecmd.tail(root, "t2", since=t2["next"], n=1)
    assert t3["n"] == 2 and "third" in t3["text"] and "second" not in t3["text"]

def test_a_task_never_ran_says_so(tmp_path):
    t = livecmd.tail(tmp_path, "t9")
    assert t["n"] == 0 and t["text"] == "" and "No command" in t["words"]

def test_stop_ends_one_command_and_the_worker_is_told(tmp_path):
    ws = Workspace(tmp_path / "bakery")
    ws.live = (ws.root, "t3")
    got: list[BaseException] = []

    def go():
        try:
            ws.run_command({"command": _py("import time; print('working', flush=True); time.sleep(60)")})
        except ToolError as e:
            got.append(e)

    th = threading.Thread(target=go)
    th.start()
    for _ in range(100):
        if livecmd.running(ws.root):
            break
        time.sleep(0.05)
    assert livecmd.stop(ws.root, "other-task") == 0
    assert livecmd.stop(ws.root, "t3") == 1
    th.join(20)
    assert not th.is_alive() and got and "owner stopped" in str(got[0])
    t = livecmd.tail(ws.root, "t3")
    assert t["ended"] == "[stopped]" and t["words"] == "The owner stopped it."

def test_strays_are_stopped(tmp_path):
    root = tmp_path / "bakery"
    root.mkdir()
    # one started by this process ...
    th = threading.Thread(target=lambda: _quiet(lambda: livecmd.run_streaming(
        _py("import time; time.sleep(60)"), root, clean_env(), 60, livecmd.slot(root, "t4"), root=root)))
    th.start()
    # ... and one left by an earlier run that crashed (only its pid is in running.json)
    kw = {"start_new_session": True} if os.name != "nt" else {}
    left = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], env=clean_env(), **kw)
    reg = root / ".harness" / "live" / "running.json"
    for _ in range(100):
        if livecmd.running(root):
            break
        time.sleep(0.05)
    data = json.loads(reg.read_text())
    data["commands"].append({"pid": left.pid, "task": "t5", "n": 1, "command": "sleep", "started": time.time(),
                             "until": time.time() + 120, "log": "t5-1.log"})
    reg.write_text(json.dumps(data))
    assert livecmd.stop_strays(root) == 2
    th.join(20)
    assert left.wait(10) is not None
    assert livecmd.running(root) == []
    # a listing past its own deadline is left alone: that number may be someone else's by now
    reg.write_text(json.dumps({"commands": [{"pid": os.getpid(), "task": "t6", "n": 1, "until": time.time() - 5}]}))
    assert livecmd.stop_strays(root) == 0

def _alive(pid: int) -> bool:
    """Running (a killed process nobody has reaped yet counts as gone)."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return True


def _quiet(fn):
    try:
        fn()
    except (livecmd.Stopped, subprocess.TimeoutExpired):
        pass

def test_through_the_app(tmp_path, monkeypatch):
    from roundtable.ui import server

    from .test_files_api import app_proj  # noqa: F401 - the fixture's body, used below

    app, root = _app(tmp_path)
    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "terminalapi"))
    ws = Workspace(root)
    ws.live = (root, "t1")
    ws.run_command({"command": _py("print('baked')")})
    d = app.dispatch("GET", "/api/terminal/task", {"path": [str(root)], "task": ["t1"]}, {})
    assert "baked" in d["text"] and d["ended"] == "[exit code 0]"
    s = app.dispatch("POST", "/api/terminal/task/stop", {}, {"path": str(root), "task": "t1"})
    assert s["stopped"] == 0 and "Nothing" in s["words"]
    with pytest.raises(server.ApiError):
        app.dispatch("GET", "/api/terminal/task", {"path": [str(root)], "task": ["../x"]}, {})

def _app(tmp_path):
    from roundtable.ui.server import UIApp

    from .test_harness import make as make_harness

    orch, *_ = make_harness(tmp_path)
    cfg = orch.cfg
    cfg.lab_dir = tmp_path / "lab"
    app = UIApp(str(tmp_path / "missing-hub.yaml"), "missing.yaml")
    app.cfg = lambda: cfg
    orch._register_with_lab()
    root = orch.project.root
    (root / ".harness").mkdir(parents=True, exist_ok=True)
    (root / ".harness" / "project.json").write_text('{"goals": ["a made-up bakery site"]}', encoding="utf-8")
    return app, root
