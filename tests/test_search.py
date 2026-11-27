"""One search over everything (search.py, ui/searchapi.py): made-up projects and hub entries only."""

import json
import os

import pytest

from roundtable import memory, search
from roundtable.improve.lab import Lab
from roundtable.ui import searchapi
from roundtable.ui.server import ApiError

from .test_ui import app  # noqa: F401  (the fixture)


def make_project(root, name="Bakery site"):
    h = root / ".harness"
    h.mkdir(parents=True)
    (h / "project.json").write_text(json.dumps({"name": name}), encoding="utf-8")
    (h / "plan.md").write_text("# A bakery website\n\nA menu page with croissant prices.\n", encoding="utf-8")
    (h / "tasks.json").write_text(json.dumps([
        {"id": "T1", "title": "Menu page", "description": "List every pastry", "status": "done",
         "attempts": [{"outcome": "rejected", "review": "The sourdough row is missing."}]},
        {"id": "T2", "title": "Contact form", "description": "Email the baker", "status": "pending"}]), encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "menu.js").write_text("const items = ['croissant', 'baguette'];\n// opening hours: 8 till 4\n",
                                          encoding="utf-8")
    (root / "notes-about-flour.txt").write_text("rye only", encoding="utf-8")
    (root / ".env").write_text("SECRET_TOKEN=croissant", encoding="utf-8")
    (root / "node_modules" / "x").mkdir(parents=True)
    (root / "node_modules" / "x" / "index.js").write_text("croissant", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("croissant", encoding="utf-8")
    (root / "big.log").write_text("croissant " * 70000, encoding="utf-8")
    (root / "pic.png").write_bytes(b"\x89PNG\0\0croissant")
    memory.add_note(root, "The owner likes the croissant photo on top.")
    return root


def kinds(res):
    return [h["kind"] for h in res["hits"]]


def test_finds_each_project_source_and_skips_private_folders(tmp_path):
    root = make_project(tmp_path / "bakery")
    res = search.search("croissant", projects=[root], home=tmp_path / "home")
    where = {(h["kind"], h["title"]) for h in res["hits"]}
    assert ("plan", "A bakery website") in where
    assert ("file", "src/menu.js") in where
    assert any(k == "memory" for k, _ in where)
    files = [h["title"] for h in res["hits"] if h["kind"] == "file"]
    assert not any(f.startswith((".git", "node_modules", ".harness")) or f == ".env" or f == "pic.png" for f in files)
    assert "big.log" not in files  # too big to look inside, and not in its name
    assert kinds(search.search("sourdough", projects=[root]))[:1] == ["task"]  # the reviews are searched
    t = search.search("contact", projects=[root])["hits"][0]
    assert t["title"] == "Task T2: Contact form" and t["where"] == "Bakery site · Tasks"
    f = search.search("flour", projects=[root])["hits"][0]
    assert f["kind"] == "file" and f["snippet"] == "Found by its name."
    m = search.search("croissant photo", projects=[root])["hits"][0]
    assert m["kind"] == "memory" and m["open"] == {"room": "memory", "path": str(root.resolve()), "archive": False}
    hit = next(h for h in res["hits"] if h["title"] == "src/menu.js")
    assert hit["open"]["room"] == "file" and hit["open"]["line"] == 1
    assert search.search("big.log", projects=[root])["hits"][0]["snippet"].startswith("Too big")


def test_every_word_must_be_there_and_titles_rank_first(tmp_path):
    root = make_project(tmp_path / "bakery")
    assert search.search("croissant zebra", projects=[root])["total"] == 0
    assert search.search('"hours: 8"', projects=[root])["hits"][0]["title"] == "src/menu.js"
    assert search.search('"8 hours"', projects=[root])["total"] == 0
    assert search.terms('Menu  "opening hours" js') == ["opening hours", "menu", "js"]
    assert search.search("   ", projects=[root])["words"] == "Type a word to look for."
    assert search.score(["menu"], "Menu page", "menu") > search.score(["menu"], "Other", "menu")
    res = search.search("menu", projects=[root])
    assert res["hits"][0]["kind"] in ("task", "plan")


def test_memory_archive_and_machine_memory_are_searched(tmp_path):
    root = make_project(tmp_path / "bakery")
    path = memory.project_path(root)
    from types import SimpleNamespace
    for i in range(40):
        memory.add_note(root, f"Note {i}: the oven timer beeps twice", SimpleNamespace(sections={"memory": {"budget_chars": 400}}))
    home = tmp_path / "home"
    memory.refresh_machine(home, rows=[{"id": "godot", "name": "Godot", "state": "missing"}], os_name="linux",
                           which=lambda _: None)
    res = search.search('"note 0:" oven', projects=[root], home=home)
    assert res["hits"][0]["where"].endswith("Memory · archive") and res["hits"][0]["open"]["archive"] is True
    assert memory.archive_of(path).is_file()
    m = search.search("wine", projects=[], home=home)["hits"][0]
    assert m["where"] == "This computer · Memory" and m["open"]["machine"] is True


def test_finds_hub_journal_letters_notes_and_plans(app, tmp_path):  # noqa: F811
    hub = app.hub
    hub.journal.add("frontend", "decision", "Use the teal colour for the navbar")
    hub.send("frontend", ["backend"], "About the teal colour", "Is teal fine for the API docs too?")
    root = hub.store.root
    (root / "notes").mkdir(parents=True, exist_ok=True)
    (root / "notes" / "ideas.md").write_text("# Ideas\n\nA teal theme for winter.\n", encoding="utf-8")
    (root / "plans").mkdir(parents=True, exist_ok=True)
    (root / "plans" / "frontend.md").write_text("# Navbar redo\n\nTeal buttons everywhere.\n", encoding="utf-8")
    res = searchapi.routes(app)[("GET", "/api/search")]({"q": ["teal"]})
    got = {h["kind"]: h for h in res["hits"]}
    assert set(got) >= {"journal", "letter", "note", "hub_plan"}
    assert got["journal"]["open"] == {"room": "journal", "agent": "frontend", "id": got["journal"]["open"]["id"]}
    assert got["letter"]["title"] == "About the teal colour" and got["letter"]["where"].startswith("Letters · from")
    assert got["note"]["open"] == {"room": "note", "name": "ideas.md"}
    assert got["hub_plan"]["title"] == "Navbar redo"
    only = searchapi.routes(app)[("GET", "/api/search")]({"q": ["teal"], "kinds": ["note"]})
    assert kinds(only) == ["note"]
    assert hub.inbox("backend")  # searching didn't mark the letter read


def test_paths_cannot_escape_the_project(tmp_path):
    root = make_project(tmp_path / "bakery")
    outside = tmp_path / "outside.txt"
    outside.write_text("croissant secrets", encoding="utf-8")
    try:  # Windows without the right to make links: the other paths are still checked
        os.symlink(outside, root / "link.txt")
        os.symlink(tmp_path, root / "linkdir", target_is_directory=True)
    except OSError:
        pass
    for bad in ["../outside.txt", "/etc/passwd", "C:/Windows/win.ini", "link.txt", "linkdir/outside.txt",
                ".env", ".git/config", ".harness/plan.md", "node_modules/x/index.js", "src/../../outside.txt", ""]:
        assert search.safe_file(root, bad) is None, bad
        with pytest.raises(ValueError):
            search.peek_file(root, bad)
    assert search.safe_file(root, "src/menu.js") == (root / "src" / "menu.js").resolve()
    files = [h["title"] for h in search.search("croissant", projects=[root])["hits"] if h["kind"] == "file"]
    assert "link.txt" not in files and not any(f.startswith("linkdir") for f in files)
    p = search.peek_file(root, "src/menu.js", line=2)
    assert p["from"] == 1 and p["lines"][1].startswith("// opening hours")
    assert search.peek_file(root, "big.log")["words"] == "This file is too big to show here."


def test_api_memory_and_peek_only_for_registered_projects(app, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("ROUNDTABLE_HOME", str(tmp_path / "apphome"))
    root = make_project(tmp_path / "bakery")
    Lab(app.cfg().lab_dir).register_project(root)
    r = searchapi.routes(app)
    out = r[("POST", "/api/memory/note")]({"path": str(root), "text": "Closed on Mondays", "as": "fact"})
    assert out["added"] and out["counts"]["pinned"] == 1 and out["where"] == "Bakery site"
    got = r[("GET", "/api/memory")]({"path": [str(root)]})
    assert "Closed on Mondays" in got["markdown"]
    saved = r[("POST", "/api/memory")]({"path": str(root), "markdown": got["markdown"] + "- 2026-11-27 · Owner line\n"})
    assert saved["saved"] and "Owner line" in saved["markdown"]
    assert r[("GET", "/api/memory")]({"path": [str(root)], "archive": ["1"]})["archive"] is True
    m = r[("POST", "/api/memory/note")]({"machine": True, "text": "No Wine here", "as": "rule"})
    assert m["where"] == "This computer" and (tmp_path / "apphome" / "memory.md").is_file()
    assert r[("GET", "/api/search/peek")]({"path": [str(root)], "file": ["src/menu.js"], "line": ["1"]})["lines"]
    for bad in ({"path": str(tmp_path)}, {"path": "/etc"}):
        with pytest.raises(ApiError):
            r[("GET", "/api/memory")](bad)
    with pytest.raises(ApiError):
        r[("GET", "/api/search/peek")]({"path": [str(root)], "file": ["../outside.txt"]})
    with pytest.raises(ApiError):
        r[("POST", "/api/memory/note")]({"path": str(root), "text": " "})
    res = r[("GET", "/api/search")]({"q": ["mondays"]})
    assert res["hits"] and res["hits"][0]["kind"] == "memory"
