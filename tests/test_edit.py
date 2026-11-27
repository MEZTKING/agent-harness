"""Changing a project's files from the app (ui/editapi.py): what may be saved, a stale base, the warning while a
task builds the file, one commit per save and Undo, the copy kept in a project without git, the guarded branch
switch, the rich preview and the Browser's addresses. Made-up projects, scripted models."""

from __future__ import annotations

import json
import subprocess

import pytest

from roundtable.ui import editapi
from roundtable.ui.server import ApiError

from .test_harness import make


def _git(root, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@localhost", *args], cwd=root,
                          capture_output=True, text=True, check=True).stdout.strip()


def _app(tmp_path, monkeypatch, run: bool):
    from roundtable.ui import server
    from roundtable.ui.server import UIApp

    orch, *_ = make(tmp_path)
    if run:
        orch.start("build a bakery site")
        assert orch.run() == "done"
    else:
        hd = orch.project.root / ".harness"
        hd.mkdir(parents=True, exist_ok=True)
        (hd / "project.json").write_text('{"goals": ["a made-up bakery site"]}', encoding="utf-8")
    cfg = orch.cfg
    cfg.lab_dir = tmp_path / "lab"
    orch._register_with_lab()
    app = UIApp(str(tmp_path / "missing-hub.yaml"), "missing.yaml")
    app.cfg = lambda: cfg
    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "editapi"))
    root = orch.project.root
    root.mkdir(parents=True, exist_ok=True)
    return app, root


@pytest.fixture
def git_proj(tmp_path, monkeypatch):
    app, root = _app(tmp_path, monkeypatch, run=True)
    assert (root / ".git").exists()
    return app, root


@pytest.fixture
def plain_proj(tmp_path, monkeypatch):
    app, root = _app(tmp_path, monkeypatch, run=False)
    if (root / ".git").exists():
        import shutil

        shutil.rmtree(root / ".git")
    (root / "menu.txt").write_text("bread\r\ncake\r\n", encoding="utf-8", newline="")
    return app, root


def _open(app, root, file):
    return app.dispatch("GET", "/api/files/edit", {"path": [str(root)], "file": [file]}, {})


def _save(app, root, file, text, base, **kw):
    return app.dispatch("POST", "/api/files/save", {}, {"path": str(root), "file": file, "text": text, "base": base, **kw})


def test_a_save_makes_exactly_one_commit_and_undo_restores_the_old_text(git_proj):
    app, root = git_proj
    old = (root / "hello.py").read_text(encoding="utf-8")
    (root / "test_hello.py").write_text("# the owner's own unsaved change\n", encoding="utf-8")
    before = int(_git(root, "rev-list", "--count", "HEAD"))
    d = _open(app, root, "hello.py")
    assert d["text"] == old and d["git"] and d["warn"] == ""
    res = _save(app, root, "hello.py", "print('fresh bread')\n", d["base"])
    assert res["ok"] and res["commit"] and int(_git(root, "rev-list", "--count", "HEAD")) == before + 1
    assert _git(root, "log", "-1", "--format=%s") == "Edited by hand: hello.py"
    assert _git(root, "show", "--name-only", "--format=", "HEAD") == "hello.py"
    assert "test_hello.py" in _git(root, "status", "--porcelain")  # not swept in
    edits = app.dispatch("GET", "/api/files/edits", {"path": [str(root)]}, {})["edits"]
    assert edits[0]["file"] == "hello.py" and not edits[0]["undone"]
    back = app.dispatch("POST", "/api/files/undo_edit", {}, {"path": str(root), "id": edits[0]["id"]})
    assert back["ok"] and (root / "hello.py").read_text(encoding="utf-8") == old
    assert app.dispatch("GET", "/api/files/edits", {"path": [str(root)]}, {})["edits"][0]["undone"]


def test_a_stale_base_is_refused_and_both_versions_come_back(git_proj):
    app, root = git_proj
    d = _open(app, root, "hello.py")
    (root / "hello.py").write_text("changed by a task\n", encoding="utf-8")
    res = _save(app, root, "hello.py", "mine\n", d["base"])
    assert res["ok"] is False and res["conflict"] and res["theirs"] == "changed by a task\n"
    assert "changed while you were editing" in res["words"]
    assert (root / "hello.py").read_text(encoding="utf-8") == "changed by a task\n"
    assert _save(app, root, "hello.py", "mine\n", res["base"])["ok"]


@pytest.mark.parametrize("rel", ["../outside.txt", ".git/config", ".harness/tasks.json", ".env", "secrets/a.txt",
                                 "server.pem", "/etc/passwd", "nope.txt"])
def test_save_refuses_paths_outside_hidden_or_private(git_proj, rel):
    app, root = git_proj
    (root / ".env").write_text("KEY=proxy-injected\n", encoding="utf-8")
    (root / "server.pem").write_text("x", encoding="utf-8")
    (root / "secrets").mkdir(exist_ok=True)
    (root / "secrets" / "a.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ApiError) as e:
        _save(app, root, rel, "x", "y")
    assert e.value.status == 404
    assert (root / ".env").read_text(encoding="utf-8") == "KEY=proxy-injected\n"


def test_save_refuses_a_binary_and_a_file_over_the_cap(git_proj):
    app, root = git_proj
    (root / "logo.bin").write_bytes(b"\x00\x01\x02")
    with pytest.raises(ApiError) as e:
        _open(app, root, "logo.bin")
    assert e.value.status == 415
    with pytest.raises(ApiError):
        _save(app, root, "logo.bin", "x", "y")
    (root / "big.txt").write_text("a" * (editapi.EDIT_MAX + 1), encoding="utf-8")
    with pytest.raises(ApiError) as e:
        _save(app, root, "big.txt", "x", "y")
    assert e.value.status == 413
    d = _open(app, root, "hello.py")
    with pytest.raises(ApiError) as e:
        _save(app, root, "hello.py", "a" * (editapi.EDIT_MAX + 1), d["base"])
    assert e.value.status == 413
    with pytest.raises(ApiError):
        _save(app, root, "hello.py", "a\x00b", d["base"])


def test_a_task_building_the_file_asks_first(git_proj):
    app, root = git_proj
    tasks = json.loads((root / ".harness/tasks.json").read_text(encoding="utf-8"))
    tasks[0].update(status="running", files=["hello.py"])
    (root / ".harness/tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
    d = _open(app, root, "hello.py")
    assert "is changing this file right now" in d["warn"]
    res = _save(app, root, "hello.py", "mine\n", d["base"])
    assert res["ok"] is False and res["needs_confirm"]
    assert (root / "hello.py").read_text(encoding="utf-8") != "mine\n"
    assert _save(app, root, "hello.py", "mine\n", d["base"], confirm=True)["ok"]


def test_without_git_the_old_text_is_kept_and_line_endings_stay(plain_proj):
    app, root = plain_proj
    d = _open(app, root, "menu.txt")
    assert d["eol"] == "crlf" and d["git"] is False and d["text"] == "bread\r\ncake\r\n"
    res = _save(app, root, "menu.txt", "bread\ncake\npie\n", d["base"])
    assert res["ok"] and res["commit"] == "" and res["kept"]
    assert (root / "menu.txt").read_bytes() == b"bread\r\ncake\r\npie\r\n"
    kept = list((root / ".harness" / "edits").iterdir())
    assert len(kept) == 1 and kept[0].read_bytes() == b"bread\r\ncake\r\n"
    edits = app.dispatch("GET", "/api/files/edits", {"path": [str(root)]}, {})["edits"]
    assert edits[0]["git"] is False and edits[0]["file"] == "menu.txt"
    app.dispatch("POST", "/api/files/undo_edit", {}, {"path": str(root), "id": edits[0]["id"]})
    assert (root / "menu.txt").read_bytes() == b"bread\r\ncake\r\n"
    with pytest.raises(ApiError):
        app.dispatch("POST", "/api/files/undo_edit", {}, {"path": str(root), "id": edits[0]["id"]})


def test_undo_without_git_is_refused_when_the_file_changed_since(plain_proj):
    app, root = plain_proj
    d = _open(app, root, "menu.txt")
    _save(app, root, "menu.txt", "one\n", d["base"])
    (root / "menu.txt").write_text("two\n", encoding="utf-8")
    eid = app.dispatch("GET", "/api/files/edits", {"path": [str(root)]}, {})["edits"][0]["id"]
    with pytest.raises(ApiError) as e:
        app.dispatch("POST", "/api/files/undo_edit", {}, {"path": str(root), "id": eid})
    assert e.value.status == 409 and "changed since" in str(e.value)


def test_checkout_is_refused_on_a_dirty_tree_and_during_a_run(git_proj, monkeypatch):
    app, root = git_proj
    _git(root, "branch", "trial")
    q = {"path": [str(root)], "branch": ["trial"]}
    pv = app.dispatch("GET", "/api/git/checkout", q, {})
    assert pv["blocked"] == "" or pv["blocked"] == "The project is on that branch already." or pv["stamp"]
    (root / "hello.py").write_text("unsaved\n", encoding="utf-8")
    pv = app.dispatch("GET", "/api/git/checkout", q, {})
    assert pv["blocked"] and pv["stamp"] == ""
    with pytest.raises(ApiError) as e:
        app.dispatch("POST", "/api/git/checkout", {}, {"path": str(root), "branch": "trial", "stamp": "x"})
    assert e.value.status == 409
    _git(root, "checkout", "--", "hello.py")
    monkeypatch.setattr(app, "_busy", lambda p: True)
    pv = app.dispatch("GET", "/api/git/checkout", q, {})
    assert "working on this project" in pv["blocked"]
    with pytest.raises(ApiError) as e:
        app.dispatch("POST", "/api/git/checkout", {}, {"path": str(root), "branch": "trial", "stamp": pv["stamp"]})
    assert "working on this project" in str(e.value)
    monkeypatch.setattr(app, "_busy", lambda p: False)
    pv = app.dispatch("GET", "/api/git/checkout", q, {})
    res = app.dispatch("POST", "/api/git/checkout", {}, {"path": str(root), "branch": "trial", "stamp": pv["stamp"]})
    assert res["ok"] and _git(root, "branch", "--show-current") == "trial"


def test_git_routes_through_the_app_and_private_files_are_marked(git_proj):
    app, root = git_proj
    q = {"path": [str(root)]}
    log = app.dispatch("GET", "/api/git/log", q, {})
    tasks = [c for c in log["commits"] if c["kind"] == "task"]
    assert {c["task"] for c in tasks} >= {"T1", "T2", "T3"}
    c = app.dispatch("GET", "/api/git/commit", {**q, "sha": [tasks[-1]["sha"]]}, {})
    assert c["files"] and all("private" in f for f in c["files"])
    f = c["files"][0]["path"]
    d = app.dispatch("GET", "/api/git/diff", {**q, "sha": [c["sha"]], "file": [f]}, {})
    assert d["file"] == f
    with pytest.raises(ApiError):
        app.dispatch("GET", "/api/git/diff", {**q, "sha": [c["sha"]], "file": [".env"]}, {})
    with pytest.raises(ApiError):
        app.dispatch("GET", "/api/git/log", {**q, "branch": ["main; rm -rf ~"]}, {})
    assert app.dispatch("GET", "/api/git/branches", q, {})["current"]


def test_every_file_for_links_leaves_out_private_ones(git_proj):
    app, root = git_proj
    (root / ".env").write_text("x", encoding="utf-8")
    (root / "node_modules" / "x").mkdir(parents=True)
    (root / "node_modules" / "x" / "i.js").write_text("x", encoding="utf-8")
    files = app.dispatch("GET", "/api/files/all", {"path": [str(root)]}, {})["files"]
    assert "hello.py" in files and ".env" not in files and not any(f.startswith((".", "node_modules")) for f in files)


def test_the_rich_preview_route(git_proj):
    import io
    import zipfile

    app, root = git_proj
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.txt", "x")
    (root / "parts.zip").write_bytes(buf.getvalue())
    d = app.dispatch("GET", "/api/files/preview", {"path": [str(root)], "file": ["parts.zip"]}, {})
    assert d["preview"] == "archive" and d["count"] == 1
    (root / "broken.docx").write_bytes(b"nope")
    d = app.dispatch("GET", "/api/files/preview", {"path": [str(root)], "file": ["broken.docx"]}, {})
    assert d["failed"] and "damaged" in d["words"]
    with pytest.raises(ApiError):
        app.dispatch("GET", "/api/files/preview", {"path": [str(root)], "file": [".harness/tasks.json"]}, {})


def test_the_browser_lists_local_addresses_the_agents_printed(git_proj):
    app, root = git_proj
    rows = [{"event": "tool_call", "tool": "run_command", "task": "T2", "at": "2026-11-27T10:00:00Z",
             "output": "exit code: 0\nLocal:   http://localhost:5173/\nNetwork: http://192.168.1.4:5173/"},
            {"event": "tool_call", "tool": "run_command", "task": "T3", "at": "2026-11-27T11:00:00Z",
             "output": "Serving on http://0.0.0.0:8000. Also see https://example.com"}]
    with open(root / ".harness" / "events.jsonl", "a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    d = app.dispatch("GET", "/api/browser", {"path": [str(root)]}, {})
    assert d["local"] and [a["frame"] for a in d["addresses"]] == ["http://127.0.0.1:8000/", "http://127.0.0.1:5173/"]
    assert d["addresses"][1]["url"] == "http://localhost:5173/" and d["addresses"][1]["from"] == "task T2"
    app.local_only = False
    assert "can't be opened from here" in app.dispatch("GET", "/api/browser", {"path": [str(root)]}, {})["words"]


def test_frame_url_only_ever_points_at_this_computer():
    assert editapi.frame_url("http://localhost:3000/a?b=1") == "http://127.0.0.1:3000/a?b=1"
    assert editapi.frame_url("http://[::1]:8080") == "http://127.0.0.1:8080/"
    for bad in ("http://example.com", "http://localhost.evil.com:80/", "javascript:alert(1)", "file:///etc/passwd",
                "http://127.0.0.1:99999/", "http://192.168.1.4:5173/"):
        assert editapi.frame_url(bad) == "", bad


def test_editing_routes_are_not_offered_to_the_phone():
    from roundtable import phone

    routes = {(m, p) for m, p in phone.PHONE_ROUTES}
    for p in ("/api/files/save", "/api/files/undo_edit", "/api/git/checkout", "/api/files/edit"):
        assert ("POST", p) not in routes and ("GET", p) not in routes


def test_open_as_pdf_makes_the_pdf_in_a_job_and_the_raw_route_serves_it(git_proj, monkeypatch, tmp_path):
    import time

    from roundtable import preview

    from .test_preview import make_docx

    app, root = git_proj
    (root / "guide.docx").write_bytes(make_docx())
    monkeypatch.setattr(editapi, "_pdf_cache", lambda: tmp_path / "pdfs")
    monkeypatch.setattr(preview, "libreoffice", lambda: "")
    d = app.dispatch("GET", "/api/files/preview", {"path": [str(root)], "file": ["guide.docx"]}, {})
    assert d["office"] == "docx" and d["can_pdf"] is False and "LibreOffice" in d["pdf_words"]
    with pytest.raises(ApiError) as e:
        app.dispatch("POST", "/api/files/as_pdf", {}, {"path": str(root), "file": "guide.docx"})
    assert "Tools page" in str(e.value)
    with pytest.raises(FileNotFoundError):
        editapi.raw_office_pdf(app, {"path": [str(root)], "file": ["guide.docx"]})
    monkeypatch.setattr(preview, "libreoffice", lambda: "/opt/lo/soffice")
    made = []
    monkeypatch.setattr(preview, "to_pdf", lambda src, out, soffice: made.append(src) or out.parent.mkdir(parents=True, exist_ok=True)
                        or out.write_bytes(b"%PDF-1.4 made up"))
    job = app.dispatch("POST", "/api/files/as_pdf", {}, {"path": str(root), "file": "guide.docx"})
    for _ in range(100):
        j = app.dispatch("GET", f"/api/jobs/{job['id']}", {}, {})
        if j["status"] != "running":
            break
        time.sleep(0.05)
    assert j["status"] == "done" and made
    body, ctype, headers = editapi.raw_office_pdf(app, {"path": [str(root)], "file": ["guide.docx"]})
    assert body.startswith(b"%PDF") and ctype == "application/pdf"
    with pytest.raises(ApiError):
        app.dispatch("POST", "/api/files/as_pdf", {}, {"path": str(root), "file": "hello.py"})


def test_a_file_git_doesnt_track_yet_is_kept_the_other_way(git_proj):
    app, root = git_proj
    (root / "draft.txt").write_text("first\n", encoding="utf-8")
    d = _open(app, root, "draft.txt")
    assert d["git"] is False
    res = _save(app, root, "draft.txt", "second\n", d["base"])
    assert res["ok"] and res["commit"] == "" and res["kept"]
    assert "draft.txt" not in _git(root, "ls-files")
    edits = app.dispatch("GET", "/api/files/edits", {"path": [str(root)]}, {})["edits"]
    app.dispatch("POST", "/api/files/undo_edit", {}, {"path": str(root), "id": edits[0]["id"]})
    assert (root / "draft.txt").read_text(encoding="utf-8") == "first\n"
