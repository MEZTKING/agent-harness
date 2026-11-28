"""A repository's set-up, declared (wave 9): siblings and system packages read from the project's settings,
shown first, done only after the owner's yes, a sibling over the size cap refused before a clone, and never
sudo by itself. Made-up projects; no network (stand-in runners)."""

from types import SimpleNamespace

import yaml

from roundtable.harness import setupdecl as sd


def _project(tmp_path, decl, where="roundtable.yaml"):
    root = tmp_path / "shop"
    (root / ".harness").mkdir(parents=True)
    (root / where).write_text(yaml.safe_dump(decl), encoding="utf-8")
    return root


class Runner:
    """Records every command; dpkg says nothing is installed; clones make the folder."""

    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[:2] == ["dpkg", "-s"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        if "clone" in cmd:
            from pathlib import Path

            Path(cmd[-1]).mkdir(parents=True)
            (Path(cmd[-1]) / "README").write_text("hi", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def test_what_is_declared_is_read_and_shown_first(tmp_path):
    root = _project(tmp_path, {"siblings": ["someone/shop-addons", {"repo": "https://github.com/someone/shop-data",
                                                                     "dir": "data"}, "not a repo"],
                               "system": ["qt-libs", {"name": "ffmpeg", "apt": "ffmpeg"}, "mystery"]})
    plan = sd.check(root, "linux", run=Runner())
    assert [s["repo"] for s in plan["siblings"]] == ["someone/shop-addons", "someone/shop-data"]
    assert plan["siblings"][1]["path"] == str(tmp_path / "data")
    assert plan["system"][0]["missing"] == ["libegl1", "libgl1", "libxkbcommon0", "libfontconfig1", "libdbus-1-3"]
    assert plan["missing"] and plan["words"].startswith("This computer needs to copy 2 repositories")
    assert len(plan["errors"]) == 2  # said plainly, never guessed
    # .harness/project.yaml wins, and the keys may sit under setup: too
    (root / ".harness" / "project.yaml").write_text(yaml.safe_dump({"setup": {"system": ["sqlite"]}}), encoding="utf-8")
    assert [p["name"] for p in sd.check(root, "linux", run=Runner())["system"]] == ["sqlite"]


def test_nothing_is_installed_without_the_cards_yes(tmp_path):
    root = _project(tmp_path, {"siblings": ["someone/shop-addons"], "system": ["ffmpeg"]})
    run = Runner()
    plan = sd.check(root, "linux", run=run)
    got = sd.do(root, plan, yes=False, run=run, size_of=lambda n: 1000)
    assert not got["ok"] and "waits for your yes" in got["words"]
    assert not any("clone" in c or c[:1] == ["apt-get"] for c in run.calls)

    # the run stops on a card; autopilot can't take it (the yes asks "Are you sure?")
    events = []
    orch = SimpleNamespace(project=SimpleNamespace(root=root), emit=lambda *a: events.append(a),
                           _set_status=lambda *a, **k: events.append(("status", a, k)),
                           _attention=lambda key, text, details="": events.append(("todo", key, text)),
                           _resolved=lambda *a, **k: events.append(("resolved", a)))
    assert sd.before_run(orch, run=run, size_of=lambda n: 1000) == "blocked"
    card = sd.ask(orch)
    assert card["kind"] == "setup_declared" and card["pc_only"]
    assert card["options"][0]["confirm"]  # installs are always the owner's tap
    assert "git clone https://github.com/someone/shop-addons" in card["more"]

    # yes: the run fetches and installs as root; a changed list asks again
    sd.apply(orch, card, ["yes"])
    assert sd.ask(orch) is None
    got = sd.do(root, sd.check(root, "linux", run=run), yes=True, run=run, size_of=lambda n: 1000, admin=True)
    assert got["ok"] and "copied someone/shop-addons" in got["done"] and ["apt-get", "install", "-y", "ffmpeg"] in run.calls


def test_a_sibling_over_the_cap_is_refused_before_a_clone(tmp_path):
    root = _project(tmp_path, {"siblings": ["someone/huge"]})
    run = Runner()
    got = sd.do(root, sd.check(root, "linux", run=run), yes=True, run=run, size_of=lambda n: sd.SIBLING_MAX_BYTES + 1)
    assert not got["ok"] and "nothing was downloaded" in got["refused"][0]
    assert not any("clone" in c for c in run.calls) and not (tmp_path / "huge").exists()


def test_sudo_is_never_run_by_itself(tmp_path):
    root = _project(tmp_path, {"system": ["qt-libs"]})
    run = Runner()
    got = sd.do(root, sd.check(root, "linux", run=run), yes=True, run=run, admin=False)
    assert not got["ok"] and got["needs_rights"] == [
        "sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3"]
    assert not any(c[:1] in (["sudo"], ["apt-get"]) for c in run.calls)
    assert "under More" in got["words"] and "sudo" not in got["words"]


def test_a_project_that_declares_nothing_is_unchanged(tmp_path):
    root = _project(tmp_path, {"test": "python -m pytest"})
    orch = SimpleNamespace(project=SimpleNamespace(root=root))
    assert sd.before_run(orch, run=Runner()) is None and sd.ask(orch) is None
