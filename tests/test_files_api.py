"""Files in the app (ui/filesapi.py): the rules, the previews, the command log and Run the tests (made-up projects)."""

from __future__ import annotations

import base64
import json
import os
import sys
import time

import pytest

from roundtable.ui import filesapi
from roundtable.ui.server import ApiError


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / "lantern"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (root / "README.md").write_text("# Lantern\n\nA made-up app.\n", encoding="utf-8")
    (root / "data.csv").write_text("name,count\nwick,3\noil,7\n", encoding="utf-8")
    (root / "config.json").write_text('{"a": [1, 2], "b": {"c": true}}', encoding="utf-8")
    (root / "broken.json").write_text('{"a": ', encoding="utf-8")
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    (root / "guide.pdf").write_bytes(b"%PDF-1.4\n%made up\n")
    (root / "blob.bin").write_bytes(b"\x00\x01\x02")
    (root / "notes").write_text("plain words\n", encoding="utf-8")
    # what must never show
    (root / ".env").write_text("KEY=proxy-injected\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (root / ".harness").mkdir()
    (root / ".harness" / "project.json").write_text("{}", encoding="utf-8")
    (root / "release.keystore").write_bytes(b"x")
    (root / "server.pem").write_text("x", encoding="utf-8")
    (root / "secrets").mkdir()
    (root / "secrets" / "plain.txt").write_text("x", encoding="utf-8")
    (root / "credentials.json").write_text("{}", encoding="utf-8")
    (root / "__pycache__").mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("not the project's", encoding="utf-8")
    try:
        (root / "leak.txt").symlink_to(outside)
        (root / "leakdir").symlink_to(tmp_path)
    except (OSError, NotImplementedError):
        pass  # Windows without the right to make links
    return root


def test_the_listing_hides_secrets_dotfiles_and_links_out(proj):
    out = filesapi.list_dir(proj)
    names = [i["name"] for i in out["items"]]
    assert names[:1] == ["src"]  # folders first
    for hidden in (".env", ".git", ".harness", "release.keystore", "server.pem", "secrets", "credentials.json",
                   "__pycache__", "leak.txt", "leakdir"):
        assert hidden not in names, hidden
    for shown in ("README.md", "data.csv", "config.json", "logo.png", "guide.pdf", "notes"):
        assert shown in names
    kinds = {i["name"]: i["kind"] for i in out["items"]}
    assert kinds["README.md"] == "markdown" and kinds["data.csv"] == "csv" and kinds["logo.png"] == "image"
    assert kinds["guide.pdf"] == "pdf" and kinds["config.json"] == "json" and kinds["src"] == "folder"
    sub = filesapi.list_dir(proj, "src")
    assert sub["items"][0]["path"] == "src/app.py" and [c["dir"] for c in sub["crumbs"]] == ["", "src"]


@pytest.mark.parametrize("rel", ["../outside.txt", "src/../../outside.txt", "/etc/passwd", "C:/Windows/win.ini",
                                 "..\\outside.txt", ".env", ".git/config", ".harness/project.json", "src/.hidden",
                                 "release.keystore", "server.pem", "secrets/plain.txt", "credentials.json",
                                 "leak.txt", "a\x00b", ""])
def test_files_outside_or_private_are_refused(proj, rel):
    with pytest.raises(ApiError) as e:
        filesapi.read_file(proj, rel)
    assert e.value.status == 404 and "private" in str(e.value)


@pytest.mark.parametrize("rel", ["..", "../", ".git", ".harness", "secrets", "leakdir", "/tmp", "nope"])
def test_folders_outside_or_private_are_refused(proj, rel):
    with pytest.raises(ApiError):
        filesapi.list_dir(proj, rel)


def test_each_kind_opens_as_itself(proj):
    md = filesapi.read_file(proj, "README.md")
    assert md["kind"] == "markdown" and md["text"].startswith("# Lantern")
    code = filesapi.read_file(proj, "src/app.py")
    assert code["kind"] == "code" and code["lang"] == "python" and "hello" in code["text"]
    table = filesapi.read_file(proj, "data.csv")
    assert table["rows"] == [["name", "count"], ["wick", "3"], ["oil", "7"]]
    js = filesapi.read_file(proj, "config.json")
    assert js["kind"] == "json" and json.loads(js["text"])["b"]["c"] is True
    bad = filesapi.read_file(proj, "broken.json")
    assert bad["kind"] == "code" and "mistake" in bad["words"] and bad["text"]
    assert filesapi.read_file(proj, "notes")["text"] == "plain words\n"
    other = filesapi.read_file(proj, "blob.bin")
    assert "text" not in other and "Save a copy" in other["words"]
    pic = filesapi.read_file(proj, "logo.png")
    assert pic["kind"] == "image" and "data" not in pic  # the desktop uses /raw/pfile
    pic = filesapi.read_file(proj, "logo.png", inline=True)
    assert base64.b64decode(pic["data"]).startswith(b"\x89PNG")
    pdf = filesapi.read_file(proj, "guide.pdf", inline=True)
    assert pdf["kind"] == "pdf" and base64.b64decode(pdf["data"]).startswith(b"%PDF")


def test_big_files_say_so_instead_of_loading(proj, monkeypatch):
    monkeypatch.setattr(filesapi, "TEXT_MAX", 10)
    monkeypatch.setattr(filesapi, "INLINE_MAX", 10)
    big = filesapi.read_file(proj, "README.md")
    assert big["too_big"] and "text" not in big and "too big" in big["words"] and "Save a copy" in big["words"]
    pic = filesapi.read_file(proj, "logo.png", inline=True)
    assert pic["too_big"] and "data" not in pic
    monkeypatch.setattr(filesapi, "CSV_ROWS", 2)
    monkeypatch.setattr(filesapi, "TEXT_MAX", 10_000)
    t = filesapi.read_file(proj, "data.csv")
    assert len(t["rows"]) == 2 and "first 2 rows" in t["words"]


def test_save_a_copy_sends_any_file_but_never_a_private_one(proj, monkeypatch):
    c = filesapi.copy_of(proj, "blob.bin")
    assert base64.b64decode(c["data"]) == b"\x00\x01\x02" and c["name"] == "blob.bin"
    assert filesapi.copy_of(proj, "README.md")["mime"] == "text/plain"
    with pytest.raises(ApiError):
        filesapi.copy_of(proj, ".env")
    monkeypatch.setattr(filesapi, "INLINE_MAX", 2)
    with pytest.raises(ApiError) as e:
        filesapi.copy_of(proj, "README.md")
    assert e.value.status == 413 and "too big" in str(e.value)


def test_raw_answers_show_pictures_and_pdfs_and_save_the_rest(proj):
    body, ctype, headers = filesapi.raw_answer(proj / "logo.png")
    assert ctype == "image/png" and "sandbox" in headers["Content-Security-Policy"]
    body, ctype, headers = filesapi.raw_answer(proj / "guide.pdf")
    assert ctype == "application/pdf" and headers["Content-Disposition"].startswith("inline")
    body, ctype, headers = filesapi.raw_answer(proj / "README.md")  # never shown as a page
    assert ctype == "application/octet-stream" and "attachment" in headers["Content-Disposition"]
    body, ctype, headers = filesapi.raw_answer(proj / "logo.png", download=True)
    assert "attachment" in headers["Content-Disposition"]


# -- the command log -------------------------------------------------------------------------------
def _events(root, rows):
    (root / ".harness").mkdir(exist_ok=True)
    (root / ".harness" / "events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows) + "not json\n",
                                                    encoding="utf-8")


def test_the_command_log_from_made_up_events(proj):
    _events(proj, [
        {"at": "2026-11-27T10:00:00Z", "event": "setup", "command": "pip install -e .", "passed": True},
        {"at": "2026-11-27T10:00:05Z", "event": "baseline", "command": "pytest -q", "passed": False, "failing": 1},
        {"at": "2026-11-27T10:01:00Z", "event": "tool_call", "task": "T1", "role": "coder", "tool": "run_command",
         "args": {"command": "pytest -q"}, "error": False, "result": "exit code: 1\n--- stdout ---\n1 failed",
         "output": "exit code: 1\n--- stdout ---\n1 failed\n--- stderr ---\n"},
        {"at": "2026-11-27T10:02:00Z", "event": "tool_call", "task": "T1", "role": "reviewer", "tool": "run_command",
         "args": {"command": "ls"}, "error": False, "result": "exit code: 0\n--- stdout ---\nsrc", "output": "exit code: 0\nsrc"},
        {"at": "2026-11-27T10:02:30Z", "event": "tool_call", "task": "T1", "role": "coder", "tool": "read_file",
         "args": {"path": "src/app.py"}, "error": False, "result": "print"},
        {"at": "2026-11-27T10:02:40Z", "event": "tool_call", "task": "T2", "role": "coder", "tool": "run_command",
         "args": {"command": "rm -rf /"}, "error": True, "refused": True, "result": "You said no to this command."},
        {"at": "2026-11-27T10:03:00Z", "event": "checks", "task": "T1", "verdict": "new", "new": ["test_wick"], "old": 0},
    ])
    meta = {"setup": {"command": "pip install -e .", "passed": True, "tail": "installed"},
            "baseline": {"command": "pytest -q", "passed": False, "exit_code": 1, "tail": "1 failed"}}
    log = filesapi.command_log(proj, tasks={"T1": "Light the wick"}, reviewer="reviewer", meta=meta, test_cmd="pytest -q")
    assert [r["kind"] for r in log] == ["checks", "task", "task", "task", "baseline", "setup"]  # newest first
    checks, refused, ls_, pytest_, base, setup = log
    assert checks["command"] == "pytest -q" and checks["passed"] is False and "test_wick" in checks["output"]
    assert refused["refused"] and refused["passed"] is False and refused["words"].startswith("wasn't run")
    assert ls_["who"] == "reviewer" and ls_["exit_code"] == 0 and ls_["passed"] and ls_["words"] == "worked"
    assert pytest_["exit_code"] == 1 and pytest_["words"] == "failed (exit code 1)" and pytest_["task_title"] == "Light the wick"
    assert "1 failed" in pytest_["output"] and pytest_["who"] == "coder"
    assert base["output"] == "1 failed" and base["exit_code"] == 1 and not base["passed"]
    assert setup["passed"] and setup["output"] == "installed"
    only = filesapi.command_log(proj, task="T2")
    assert [r["command"] for r in only] == ["rm -rf /"]


def test_long_output_is_cut_in_the_middle(proj, monkeypatch):
    monkeypatch.setattr(filesapi, "OUTPUT_MAX", 5000)
    out = "exit code: 0\n" + "a" * 3000 + "MIDDLE" + "b" * 9000 + "END"
    _events(proj, [{"at": "x", "event": "tool_call", "tool": "run_command", "args": {"command": "make"}, "output": out}])
    row = filesapi.command_log(proj)[0]
    assert row["output"].endswith("END") and "MIDDLE" not in row["output"] and row["output"].startswith("exit code: 0")


# -- through the app -------------------------------------------------------------------------------
@pytest.fixture
def app_proj(tmp_path):
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
    (root / "index.html").write_text("<h1>Bakery</h1>", encoding="utf-8")
    return app, root


def test_through_the_server_once_listed_in_feature_apis(app_proj, monkeypatch):
    from roundtable.ui import server

    app, root = app_proj
    monkeypatch.setattr(server, "FEATURE_APIS", ("filesapi",))
    d = app.dispatch("GET", "/api/files", {"path": [str(root)]}, {})
    assert d["here"] and any(i["name"] == "index.html" for i in d["items"]) and d["test_command"] == ""
    f = app.dispatch("GET", "/api/files/open", {"path": [str(root)], "file": ["index.html"]}, {})
    assert f["kind"] == "code" and f["lang"] == "html" and f["text"] == "<h1>Bakery</h1>"
    log = app.dispatch("GET", "/api/files/log", {"path": [str(root)]}, {})
    assert log["can_run"] is False and "test command" in log["why_not"]
    with pytest.raises(ApiError) as e:
        app.dispatch("POST", "/api/files/run_tests", {}, {"path": str(root)})
    assert "no test command" in str(e.value)
    body, ctype, _ = filesapi.raw_file(app, {"path": [str(root)], "file": ["index.html"]})
    assert body == b"<h1>Bakery</h1>" and ctype == "application/octet-stream"


def test_a_project_elsewhere_says_where_it_is(app_proj, monkeypatch):
    from roundtable import sync

    app, _ = app_proj
    d = filesapi.listing(app, {"path": ["C:/somewhere/else/tide-clock"]})
    assert d["here"] is False and "aren't on this computer" in d["words"]
    app.hub = object()
    monkeypatch.setattr(sync, "where_is", lambda hub, name: {"machine_name": "Phone (Pixel)"} if name == "tide-clock" else None)
    d = filesapi.listing(app, {"name": ["tide-clock"]})
    assert d["here"] is False and d["machine_name"] == "Phone (Pixel)" and "on Phone (Pixel)" in d["words"]
    with pytest.raises(FileNotFoundError):
        filesapi.raw_file(app, {"name": ["tide-clock"], "file": ["index.html"]})


def test_run_the_tests_starts_the_projects_own_test_command(app_proj):
    from roundtable.harness import projectsettings as ps

    app, root = app_proj
    cmd = f'"{sys.executable}" -c "print(\'2 passed\')"'
    ps.update(root, {"test": cmd})
    job = filesapi.run_tests(app, {"path": str(root)})
    assert job["status"] == "running"
    with pytest.raises(ApiError) as e:  # one thing at a time on a project
        filesapi.run_tests(app, {"path": str(root)})
    assert e.value.status == 409
    j = app.jobs.jobs[job["id"]]
    for _ in range(200):
        if j.status != "running":
            break
        time.sleep(0.05)
    assert j.status == "done" and j.result["ok"] and j.result["words"] == "The tests passed."
    assert j.kind == "tests" and j.log[0].endswith(f"$ {cmd}")
    row = filesapi.command_log(root)[0]
    assert row["kind"] == "tests" and row["who"] == "you" and row["command"] == cmd and "2 passed" in row["output"]
    assert row["passed"] and row["words"] == "you ran the tests: worked"
    view = filesapi.command_log_view(app, {"path": [str(root)]})
    assert view["can_run"] and view["test_command"] == cmd


def test_run_the_tests_never_runs_while_roundtable_works_on_the_project(app_proj, monkeypatch):
    from roundtable.harness import projectsettings as ps

    app, root = app_proj
    ps.update(root, {"test": "echo hi"})
    monkeypatch.setattr(app, "_busy", lambda path: True)
    with pytest.raises(ApiError) as e:
        filesapi.run_tests(app, {"path": str(root)})
    assert e.value.status == 409 and "working on this project" in str(e.value)
    assert not (root / ".harness" / filesapi.RUNS_FILE).exists()
    assert os.path.isdir(root)
