"""Wave 8's safety fixes, each with its test: no save or put-back through a link, no branch switch while the
project is busy in any way, outside text never starts a build by itself, one answer for a hook that isn't there
and a wrong secret, an install in a task's copy gets its own folders first, and the phone can't change files.
Made-up projects in tmp_path, scripted models, no network."""

from __future__ import annotations

import io
import os
import sys

import pytest

from roundtable import automation as au
from roundtable import reach
from roundtable.harness import gitview, perms
from roundtable.harness.gate import Gate
from roundtable.harness.orchestrator import Project
from roundtable.harness.worktrees import Worktrees, _is_link, links_out
from roundtable.ui import filesapi
from roundtable.ui.server import ApiError

from .test_edit import _app, _git, _open, _save
from .test_worktree_links import deps, lane, repo

links = pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need extra rights on Windows")


@pytest.fixture
def git_proj(tmp_path, monkeypatch):
    app, root = _app(tmp_path, monkeypatch, run=True)
    assert (root / ".git").exists()
    return app, root


# -- 1. saving never goes through a link ---------------------------------------------------------------------------
@links
@pytest.mark.parametrize("target", [".git/config", ".env", ".harness/project.json"])
def test_a_file_that_links_into_a_private_place_cant_be_opened_or_saved(git_proj, target):
    app, root = git_proj
    (root / ".env").write_text("TOKEN=made-up\n", encoding="utf-8")
    (root / "notes.txt").symlink_to(root / target)
    assert filesapi.safe_file(root, "notes.txt") is None or filesapi.writable_file(root, "notes.txt") is None
    assert filesapi.writable_file(root, "notes.txt") is None
    with pytest.raises(ApiError):
        _open(app, root, "notes.txt")
    before = (root / target).read_bytes()
    with pytest.raises(ApiError):
        _save(app, root, "notes.txt", "overwritten\n", "")
    assert (root / target).read_bytes() == before


@links
def test_a_folder_link_on_the_way_is_refused_too(git_proj):
    app, root = git_proj
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "a.txt").write_text("a\n", encoding="utf-8")
    (root / "shortcut").symlink_to(root / "docs", target_is_directory=True)
    assert filesapi.writable_file(root, "docs/a.txt") is not None  # the real path is fine
    assert filesapi.writable_file(root, "shortcut/a.txt") is None  # but never through the link


# -- 2. putting a hand edit back checks the file the commit names ---------------------------------------------------
@links
def test_putting_back_a_hand_edit_refuses_a_file_that_became_a_link(git_proj):
    app, root = git_proj
    d = _open(app, root, "hello.py")
    _save(app, root, "hello.py", "print('fresh bread')\n", d["base"])
    sha = _git(root, "rev-parse", "HEAD")
    config = (root / ".git" / "config").read_bytes()
    (root / "hello.py").unlink()
    (root / "hello.py").symlink_to(root / ".git" / "config")
    with pytest.raises(gitview.GitViewError) as e:
        gitview.undo_edit(root, sha)
    assert "link" in str(e.value)
    assert (root / ".git" / "config").read_bytes() == config


# -- 3. the branch switch waits for every kind of busy ---------------------------------------------------------------
def _preview(app, root):
    _git(root, "branch", "-f", "trial")
    return app.dispatch("GET", "/api/git/checkout", {"path": [str(root)], "branch": ["trial"]}, {})


@pytest.mark.parametrize("status", ["running", "planning"])
def test_checkout_waits_while_the_project_says_it_is_working(git_proj, monkeypatch, status):
    app, root = git_proj
    monkeypatch.setattr(app, "_busy", lambda p: False)  # this app isn't running it: another program may be
    p = Project(root)
    meta = p.meta()
    meta["status"] = status
    p.save_meta(meta)
    assert "right now" in _preview(app, root)["blocked"]


def test_checkout_waits_for_unfinished_tasks_and_kept_task_copies(git_proj, monkeypatch):
    app, root = git_proj
    monkeypatch.setattr(app, "_busy", lambda p: False)
    p = Project(root)
    tasks = p.tasks()
    tasks[0].status = "pending"
    p.save_tasks(tasks)
    assert "tasks still to build" in _preview(app, root)["blocked"]
    tasks[0].status = "done"
    p.save_tasks(tasks)
    lanes = root / ".harness" / "worktrees" / "T9"
    lanes.mkdir(parents=True)
    (lanes / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    assert "task copy" in _preview(app, root)["blocked"]


def test_an_unreadable_hub_means_cant_tell_not_nobody(git_proj, monkeypatch):
    from roundtable import sync
    from roundtable.ui import rewindapi

    app, root = git_proj

    def broken(*a, **k):
        raise OSError("the hub can't be read")

    app.hub = object()
    monkeypatch.setattr(sync, "where_is", broken)
    assert "can't be told" in rewindapi.elsewhere(app, root)


# -- 4. outside text never starts a build by itself -----------------------------------------------------------------
@pytest.mark.parametrize("kind,extra", [
    ("local", {"hook": {"secret": "s" * 40}}),
    ("poll", {"hook": {"url": "https://example.com/s.json", "every_minutes": 15}}),
    ("events", {"hook": {"repo": "acme/shop", "events": ["push"]}}),
])
def test_hooks_never_start_by_themselves(tmp_path, kind, extra):
    a = au.normalise({"kind": kind, "start_by_itself": True, "cap_usd": 5, **extra})
    assert a["start_by_itself"] is False


def test_a_new_local_hook_from_the_app_never_starts_by_itself(tmp_path, monkeypatch):
    from roundtable.ui import server

    monkeypatch.setattr(server, "FEATURE_APIS", ("automationapi", "reachapi"))
    monkeypatch.setenv("ROUNDTABLE_HOME", str(tmp_path / "home"))
    app = server.UIApp(hub_config=str(tmp_path / "missing-hub.yaml"), harness_config=str(tmp_path / "missing.yaml"),
                       projects_dir=str(tmp_path / "projects"))
    app.cfg = lambda: None
    r = app.dispatch("POST", "/api/hooks/new", {}, {"name": "My script", "start_by_itself": True, "cap_usd": 9})
    [a] = [x for x in au.saved(au.app_home(tmp_path / "home")) if x["id"] == r["id"]]
    assert a["start_by_itself"] is False


def test_the_page_never_sees_a_hooks_hashed_secret(tmp_path):
    secret = reach.new_secret()
    a = au.add(tmp_path / "home", {"kind": "local", "hook": {"secret": secret}})
    shown = au.view(a, {})
    assert "secret_hash" not in shown.get("hook", {}) and secret not in str(shown)


# -- 5. a hook says the same whether it isn't there or the secret is wrong; the phone never serves one -------------
def test_no_such_hook_and_a_wrong_secret_get_one_answer(tmp_path):
    secret = reach.new_secret()
    a = au.add(tmp_path / "home", {"kind": "local", "hook": {"secret": secret}})
    head = {"Host": "127.0.0.1", "Content-Length": "2", reach.SECRET_HEADER: "wrong"}
    wrong = reach.receive(tmp_path / "home", [a], f"/hooks/{a['id']}", "127.0.0.1", head, io.BytesIO(b"{}"))
    none = reach.receive(tmp_path / "home", [a], "/hooks/abcdef12", "127.0.0.1", head, io.BytesIO(b"{}"))
    off = reach.receive(tmp_path / "home", [{**a, "on": False}], f"/hooks/{a['id']}", "127.0.0.1",
                        {**head, reach.SECRET_HEADER: secret}, io.BytesIO(b"{}"))
    assert wrong == none == off and wrong[0] == 403


def test_the_desktop_reads_the_sockets_own_address_and_the_phone_has_no_hooks():
    import inspect

    from roundtable import phone
    from roundtable.ui import server

    src = inspect.getsource(server.make_handler)
    assert "reach.receive_for_app(app, url.path, self.client_address[0]" in src
    assert "X-Forwarded-For" not in src and "x-forwarded-for" not in src.lower()
    assert not phone.phone_allowed("POST", "/hooks/abc") and not phone.phone_allowed("GET", "/hooks/abc")
    assert 'path.startswith("/hooks/")' in inspect.getsource(phone)


# -- 6. an install in a task's copy gets its own folders first -------------------------------------------------------
@links
@pytest.mark.parametrize("command", ["npm ci", "npm install left-pad", "pnpm install", "yarn",
                                     "python -m pip install -r requirements.txt", "uv sync", "./gradlew build"])
def test_an_install_in_a_lane_takes_the_link_away_first(tmp_path, command):
    root = repo(tmp_path)
    before = deps(root)
    trees, path = lane(root)
    trees.link_deps("T1")
    assert _is_link(path / "node_modules")
    guard = perms.guard(root, None, "coder", Gate(root, poll=0.01, timeout=0.05))
    guard.ws_root = path
    guard("run_command", {"command": command})  # it may still wait for a tap: what matters is the link went
    assert not os.path.lexists(path / "node_modules")
    assert {p.relative_to(root / "node_modules").as_posix(): p.read_bytes()
            for p in (root / "node_modules").rglob("*") if p.is_file()} == before


@links
def test_an_ordinary_command_in_a_lane_keeps_the_link(tmp_path):
    root = repo(tmp_path)
    deps(root)
    trees, path = lane(root)
    trees.link_deps("T1")
    guard = perms.guard(root, None, "coder", Gate(root, poll=0.01, timeout=0.05))
    guard.ws_root = path
    guard("run_command", {"command": "npm test"})
    assert _is_link(path / "node_modules")
    assert perms.is_install("npm ci") and not perms.is_install("npm run build") and perms.is_install("gradle test")


@links
def test_a_lane_with_a_link_out_left_in_it_is_kept(tmp_path):
    root = repo(tmp_path)
    trees, path = lane(root)
    (path / "node_modules").mkdir()  # the lane's own folder (git ignores it), with a link out inside it
    (path / "node_modules" / "escape").symlink_to(root, target_is_directory=True)
    (path / "node_modules" / "inside").symlink_to(path / "index.js")  # a link that stays in the lane is harmless
    assert links_out(path) == ["node_modules/escape"]
    removed, why = trees.remove("T1")
    assert not removed and "link out" in why
    assert (root / "index.js").is_file()


# -- the phone never changes files or switches branch ----------------------------------------------------------------
def test_the_phone_may_not_change_files_or_switch_branch():
    from roundtable.phone import phone_allowed

    for method in ("GET", "POST"):
        for p in ("/api/files/save", "/api/files/undo_edit", "/api/files/edit", "/api/git/checkout",
                  "/api/files/as_pdf", "/api/board/move", "/api/commands/pc", "/api/asktimer"):
            assert not phone_allowed(method, p), (method, p)
    assert phone_allowed("GET", "/api/perms") and not phone_allowed("POST", "/api/perms")
