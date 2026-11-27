"""Move my data (datamove.py): a made-up hub (with a .git folder) and two made-up projects moved, checked by count
and hash, the old copy left intact, switch back, refused during a run."""

import json

import pytest
import yaml

from roundtable import datamove as dm


def hub_and_projects(tmp_path):
    hub = tmp_path / "old" / "hub-repo"
    (hub / ".git" / "objects").mkdir(parents=True)
    (hub / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (hub / ".git" / "objects" / "ab").write_bytes(b"\x00\x01made-up object")
    (hub / "cards").mkdir()
    (hub / "cards" / "me.json").write_text('{"agent": "me"}')
    (hub / "hub.yaml").write_text("agents: {me: {}}\n")
    projects = tmp_path / "old" / "projects"
    for name in ("shop", "game"):
        (projects / name / ".harness").mkdir(parents=True)
        (projects / name / ".harness" / "project.json").write_text(json.dumps({"status": "done"}))
        (projects / name / "index.html").write_text(f"<h1>{name}</h1>")
    home = tmp_path / "home"
    (home / "config").mkdir(parents=True)
    app_hub = home / "config" / "hub.yaml"
    app_hub.write_text("# my hub\n" + yaml.safe_dump({"storage": {"type": "git", "path": str(hub), "branch": "main"},
                                                       "agents": {"me": {}}}, sort_keys=False))
    pointer = home / "hub-path"
    pointer.write_text(str(hub / "hub.yaml") + "\n")
    settings = home / "config" / "app.json"
    settings.write_text(json.dumps({"projects_dir": str(projects), "agent": "me"}))
    lab = tmp_path / "lab"
    lab.mkdir()
    (lab / "projects.json").write_text(json.dumps([str(projects / "shop"), str(projects / "game"), "/elsewhere/x"]))
    return home, hub, projects, app_hub, pointer, settings, lab


def test_the_hub_is_moved_whole_checked_and_switched_back(tmp_path):
    home, hub, _, app_hub, pointer, _, _ = hub_and_projects(tmp_path)
    before = dm.fingerprint(hub)
    new = tmp_path / "new" / "hub"
    res = dm.move(home, "hub", hub, new, dm.pointers_for("hub", hub_yaml=app_hub, hub_pointer=pointer), busy=False)
    assert res["ok"] and res["files"] == len(before) == 4 and res["old_copy"] == str(hub.resolve())
    assert dm.fingerprint(new) == before and dm.fingerprint(hub) == before  # the copy is the same; the old one intact
    assert (new / ".git" / "HEAD").is_file()
    assert dm.hub_folder(app_hub) == new.resolve() and app_hub.read_text().startswith("# my hub")
    assert pointer.read_text().strip() == str(new.resolve() / "hub.yaml")
    back = dm.switch_back(home)
    assert back["ok"] and dm.hub_folder(app_hub) == hub.resolve()
    assert pointer.read_text().strip() == str(hub / "hub.yaml")
    assert new.is_dir() and hub.is_dir()  # both copies stay
    with pytest.raises(dm.MoveError, match="no move"):
        dm.switch_back(home)


def test_the_projects_are_moved_with_every_pointer(tmp_path):
    home, _, projects, _, _, settings, lab = hub_and_projects(tmp_path)
    new = tmp_path / "D" / "Projects"
    ptrs = dm.pointers_for("projects", settings_file=settings, lab_dir=lab)
    res = dm.move(home, "projects", projects, new, ptrs, busy=False)
    assert res["files"] == 4
    assert json.loads(settings.read_text())["projects_dir"] == str(new.resolve())
    assert json.loads(settings.read_text())["agent"] == "me"
    listed = json.loads((lab / "projects.json").read_text())
    assert listed == [str(new.resolve() / "shop"), str(new.resolve() / "game"), "/elsewhere/x"]
    assert (projects / "shop" / "index.html").read_text() == "<h1>shop</h1>"  # the old copy is never deleted
    dm.switch_back(home)
    assert json.loads((lab / "projects.json").read_text())[0] == str(projects / "shop")


def test_a_move_is_refused_while_building_or_to_a_bad_place(tmp_path):
    home, hub, projects, app_hub, _, settings, _ = hub_and_projects(tmp_path)
    with pytest.raises(dm.MoveError, match="building"):
        dm.move(home, "hub", hub, tmp_path / "n", [], busy=True)
    with pytest.raises(dm.MoveError, match="inside the old one"):
        dm.move(home, "hub", hub, hub / "sub", [], busy=False)
    full = tmp_path / "full"
    full.mkdir()
    (full / "x").write_text("x")
    with pytest.raises(dm.MoveError, match="already has things"):
        dm.move(home, "hub", hub, full, [], busy=False)
    assert not (tmp_path / "n").exists() and dm.moves(home) == []


def test_a_copy_that_doesnt_match_switches_nothing(tmp_path):
    home, hub, _, app_hub, pointer, _, _ = hub_and_projects(tmp_path)
    before = app_hub.read_text()

    def bad_copy(a, b):
        import shutil

        shutil.copytree(a, b)
        (b / "cards" / "me.json").write_text("changed")

    with pytest.raises(dm.MoveError, match="doesn't match"):
        dm.move(home, "hub", hub, tmp_path / "new", dm.pointers_for("hub", hub_yaml=app_hub, hub_pointer=pointer),
                busy=False, copy=bad_copy)
    assert app_hub.read_text() == before and dm.moves(home) == []


def test_switch_back_refuses_a_pointer_changed_since(tmp_path):
    home, _, projects, _, _, settings, lab = hub_and_projects(tmp_path)
    dm.move(home, "projects", projects, tmp_path / "new", dm.pointers_for("projects", settings_file=settings), busy=False)
    settings.write_text(json.dumps({"projects_dir": "/somewhere/else"}))
    with pytest.raises(dm.MoveError, match="changed after the move"):
        dm.switch_back(home)
    assert json.loads(settings.read_text())["projects_dir"] == "/somewhere/else"
