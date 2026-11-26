"""Proof for Godot games (harness/godot.py): finding Godot, checking a game, its pictures, Show it, run_game.

No real Godot runs here: tests/fixtures/fake_godot.py stands in, started through a small wrapper
(a .cmd file on Windows, a shell script elsewhere) so it looks like a program on PATH."""

import json
import os
import sys
from pathlib import Path

import pytest

from roundtable.harness import godot as godotlib
from roundtable.harness import showit
from roundtable.harness.config import GodotSettings, parse_config
from roundtable.providers.scripted import reply

from .test_harness import RAW, Brain, make, tool_names

FAKE = Path(__file__).parent / "fixtures" / "fake_godot.py"
PROJECT = '; Engine configuration file.\nconfig_version=5\n\n[application]\n\nconfig/name="Tiny Dungeon"\nrun/main_scene="res://main.tscn"\n'
BROKEN = "extends Node\n\nfunc _ready():\n\tprint(\"hi\") oops\n"


def fake_godot(folder: Path, name: str = "godot") -> Path:
    """A program called ``name`` in ``folder`` that runs the fake Godot."""
    folder.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        p = folder / f"{name}.cmd"
        p.write_text(f'@"{sys.executable}" "{FAKE}" %*\r\n', encoding="utf-8")
    else:
        p = folder / name
        p.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n', encoding="utf-8")
        p.chmod(0o755)
    return p


def game(folder: Path, broken: bool = False) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "project.godot").write_text(PROJECT, encoding="utf-8")
    (folder / "main.gd").write_text("extends Node\n", encoding="utf-8")
    if broken:
        (folder / "broken.gd").write_text(BROKEN, encoding="utf-8")
    return folder


@pytest.fixture
def no_godot(monkeypatch, tmp_path):
    """A computer without Godot: nothing on PATH, no $GODOT, no usual places."""
    monkeypatch.delenv("GODOT", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    monkeypatch.setattr(godotlib, "_usual_places", lambda: [])


@pytest.fixture
def has_screen(monkeypatch):
    """Pictures without needing a display or xvfb on the computer running the tests."""
    monkeypatch.setattr(godotlib, "display_prefix", lambda: [])


# -- finding Godot and the project ------------------------------------------------------------
def test_godot_is_found_from_the_setting_then_env_then_path(tmp_path, no_godot, monkeypatch):
    assert godotlib.find_godot() is None and godotlib.find_godot(str(tmp_path / "missing.exe")) is None
    on_path = fake_godot(tmp_path / "bin", "godot4")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    assert Path(godotlib.find_godot()).name.startswith("godot4")
    from_env = fake_godot(tmp_path / "env", "mygodot")
    monkeypatch.setenv("GODOT", str(from_env))
    assert godotlib.find_godot() == str(from_env)
    configured = fake_godot(tmp_path / "cfg", "Godot_v4.4")
    assert godotlib.find_godot(str(configured)) == str(configured)
    assert Path(godotlib.find_godot("godot4")).name.startswith("godot4")  # a name on PATH works as the setting
    assert on_path.is_file()


def test_the_godot_setting():
    cfg = parse_config(json.loads(json.dumps(RAW)))
    assert cfg.godot == GodotSettings(path=None, frames=90, timeout=120, enabled=True)
    raw = {**json.loads(json.dumps(RAW)), "godot": {"path": "C:/Tools/Godot/Godot_v4.4_console.exe", "frames": 30,
                                                     "timeout": 40, "enabled": False}}
    g = parse_config(raw).godot
    assert g.frames == 30 and g.timeout == 40 and g.enabled is False and g.path.endswith("Godot_v4.4_console.exe")
    assert parse_config({**raw, "godot": False}).godot.enabled is False
    assert parse_config({**raw, "godot": "godot4"}).godot.path == "godot4"
    with pytest.raises(ValueError):
        parse_config({**raw, "godot": {"frames": -1}})


def test_the_project_is_found_at_the_top_or_one_folder_down(tmp_path):
    assert godotlib.project_dir(tmp_path) is None
    game(tmp_path / "game")
    assert godotlib.project_dir(tmp_path) == tmp_path / "game"
    game(tmp_path)
    assert godotlib.project_dir(tmp_path) == tmp_path
    assert godotlib.game_name(tmp_path) == "Tiny Dungeon"
    game(tmp_path / "other" / "deeper" / "still")  # two folders down: not looked for
    assert godotlib.project_dir(tmp_path / "other") is None


# -- the check ------------------------------------------------------------------------------
def test_a_broken_script_is_reported_once_with_where_it_is(tmp_path, monkeypatch):
    exe = fake_godot(tmp_path / "bin")
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_GODOT_LOG", str(log))
    p = game(tmp_path / "proj", broken=True)
    r = godotlib.check(p, str(exe), timeout=60)
    assert r["ok"] is False
    assert r["errors"][0].startswith("SCRIPT ERROR: Parse Error") and "res://broken.gd:3" in r["errors"][0]
    assert any(e.startswith('ERROR: Failed to load script "res://broken.gd"') and "gdscript.cpp" in e for e in r["errors"])
    assert len(r["errors"]) == 2  # the same error from both runs, once
    assert "café" in r["output_tail"] and r["seconds"] >= 0
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert calls == [["--headless", "--path", str(p), "--import"],
                     ["--headless", "--path", str(p), "--quit-after", "60"]]


def test_a_clean_game_is_ok(tmp_path):
    exe = fake_godot(tmp_path / "bin")
    r = godotlib.check(game(tmp_path / "proj"), str(exe), timeout=60)
    assert r == {**r, "ok": True, "errors": []}
    assert "ran without errors" in godotlib.check_text(r)


def test_a_game_that_never_stops_is_stopped_with_a_plain_error(tmp_path):
    exe = fake_godot(tmp_path / "bin")
    p = game(tmp_path / "proj")
    (p / "hang.marker").write_text("", encoding="utf-8")
    r = godotlib.check(p, str(exe), timeout=2)
    assert r["ok"] is False and r["seconds"] < 40
    assert r["errors"] == [("Godot took longer than 2 seconds to import the project, so it was stopped: look for an "
                            "endless loop, or raise godot: timeout in harness.yaml")]


def test_error_lines_are_capped_and_kept_short():
    out = "\n".join(f"ERROR: thing {i} " + "x" * 400 for i in range(50))
    errs = godotlib.errors_in(out)
    assert len(errs) == godotlib.MAX_ERRORS and all(len(e) <= godotlib.MAX_LINE for e in errs)
    assert godotlib.errors_in("WARNING: just a warning\nall fine") == []


# -- pictures ------------------------------------------------------------------------------
def test_screenshots_keep_three_frames_and_delete_the_rest(tmp_path, monkeypatch, has_screen):
    exe = fake_godot(tmp_path / "bin")
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_GODOT_LOG", str(log))
    p = game(tmp_path / "proj")
    out = tmp_path / "frames"
    kept = godotlib.screenshots(p, str(exe), out, frames=20, timeout=60)
    assert [k.name for k in kept] == ["frame00000002.png", "frame00000010.png", "frame00000019.png"]
    assert sorted(f.name for f in out.iterdir()) == [k.name for k in kept]  # no other frames, no sound
    args = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert args == ["--path", str(p), "--write-movie", str(out.resolve() / "frame.png"), "--fixed-fps", "30",
                    "--quit-after", "20"]


def test_without_a_screen_or_xvfb_pictures_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(godotlib, "display_prefix", lambda: None)
    with pytest.raises(godotlib.NoDisplay):
        godotlib.screenshots(game(tmp_path / "proj"), "godot", tmp_path / "out")


@pytest.mark.skipif(os.name == "nt" or sys.platform == "darwin", reason="the display check is for Linux")
def test_linux_without_a_display_uses_xvfb_when_it_is_there(tmp_path, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(godotlib.shutil, "which", lambda name: "/usr/bin/xvfb-run" if name == "xvfb-run" else None)
    assert godotlib.display_prefix() == ["/usr/bin/xvfb-run", "-a"]
    monkeypatch.setattr(godotlib.shutil, "which", lambda name: None)
    assert godotlib.display_prefix() is None
    monkeypatch.setenv("DISPLAY", ":0")
    assert godotlib.display_prefix() == []
    # under xvfb Godot draws with its OpenGL renderer
    seen = []
    monkeypatch.setattr(godotlib, "display_prefix", lambda: ["xvfb-run", "-a"])
    monkeypatch.setattr(godotlib, "run", lambda cmd, timeout, cwd=None: (seen.append(cmd), (0, ""))[1])
    with pytest.raises(godotlib.GodotError):
        godotlib.screenshots(game(tmp_path / "proj"), "godot", tmp_path / "out")
    assert seen[0][:3] == ["xvfb-run", "-a", "godot"] and seen[0][-2:] == ["--rendering-driver", "opengl3"]


# -- Show it ---------------------------------------------------------------------------------
def test_show_it_on_a_godot_game_writes_pictures_and_errors(tmp_path, has_screen):
    exe = fake_godot(tmp_path / "bin")
    root = tmp_path / "proj"
    game(root / "game", broken=True)
    rec = showit.take_shots(root, "G1", godot=GodotSettings(path=str(exe), frames=12, timeout=60))
    out = showit.shots_root(root) / "G1"
    assert rec["game"] == "godot" and rec["entry"] == "game/project.godot" and rec["title"] == "Tiny Dungeon"
    assert rec["pictures"] == {"start": "start.png", "middle": "middle.png", "desktop": "desktop.png"}
    assert sorted(f.name for f in out.iterdir()) == ["desktop.png", "middle.png", "shots.json", "start.png"]
    assert rec["errors"] and "res://broken.gd:3" in rec["errors"][0] and rec["check"]["ok"] is False
    assert json.loads((out / "shots.json").read_text(encoding="utf-8")) == rec == showit.latest(root)
    # the hub gets the game's pictures like a web page's
    files = showit.hub_files(root, rec, None, "plans/shots/p")
    assert {"plans/shots/p/latest-desktop.png", "plans/shots/p/latest-start.png", "plans/shots/p/G1-desktop.png"} <= set(files)
    assert json.loads(files["plans/shots/p/latest.json"])["errors"] == rec["errors"][:10]


def test_show_it_says_plainly_when_godot_is_not_installed(tmp_path, no_godot):
    root = game(tmp_path / "proj")
    rec = showit.take_shots(root, "G1", godot=GodotSettings())
    assert rec["pictures"] == {} and rec["note"] == ("Godot isn't installed here, so the game wasn't started: install "
                                                     "Godot 4 and set godot: path in harness.yaml")


def test_a_web_page_still_comes_first_and_godot_can_be_turned_off(tmp_path, no_godot):
    root = game(tmp_path / "proj")
    off = showit.take_shots(root, "G1", godot=GodotSettings(enabled=False))
    assert "game" not in off and off["note"].startswith("nothing to open yet")
    (root / "index.html").write_text("<title>x</title>", encoding="utf-8")
    web = showit.take_shots(root, "G2", render=lambda jobs: [], godot=GodotSettings())
    assert "game" not in web and web["entry"] == "index.html"


def test_a_godot_game_that_records_nothing_is_written_down(tmp_path, has_screen):
    exe = fake_godot(tmp_path / "bin")
    root = game(tmp_path / "proj")
    (root / "noframes.marker").write_text("", encoding="utf-8")
    rec = showit.take_shots(root, "G1", godot=GodotSettings(path=str(exe), timeout=60))
    assert rec["pictures"] == {} and rec["failed"].startswith("the pictures couldn't be taken: Godot recorded no frames")
    assert rec["errors"] == [] and not (showit.shots_root(root) / "G1" / "frames").exists()


# -- in a run: Show it after each task, run_game for coders and the reviewer --------------------
GAME_PLAN = [{"id": "G1", "title": "the player", "role": "coder", "description": "add player.gd",
              "acceptance": "the game starts", "depends_on": []}]


class GameBrain(Brain):
    """A coder that writes a script, runs the game once, and finishes; it notes the tools it was offered."""

    def __init__(self):
        super().__init__(plan=GAME_PLAN)
        self.offered = {}
        self.game_output = []

    def __call__(self, model, system, messages, tools):
        names = tool_names(tools)
        if "submit_review" in names:
            self.offered.setdefault("reviewer", names)
            self.offered.setdefault("review_prompt", messages[0]["content"])
        if "finish_task" not in names:
            return super().__call__(model, system, messages, tools)
        self.offered.setdefault("coder", names)
        done = sum(1 for m in messages if m["role"] == "tool")
        if done == 0:
            return reply(calls=[("write_file", {"path": "game/player.gd", "content": "extends Node2D\n"})])
        if done == 1 and "run_game" in names:
            return reply(calls=[("run_game", {})])
        if done == 2:
            self.game_output.append(messages[-1]["content"])
        return reply(calls=[("finish_task", {"summary": "player added"})])


def test_a_godot_project_gets_run_game_and_pictures_after_each_task(tmp_path, has_screen):
    exe = fake_godot(tmp_path / "bin")
    raw = {**json.loads(json.dumps(RAW)), "godot": {"path": str(exe), "frames": 9, "timeout": 60}}
    brain = GameBrain()
    orch, *_r, events = make(tmp_path, raw=raw, brain=brain)
    game(orch.project.root / "game", broken=True)
    orch.start("a tiny dungeon game")
    assert orch.run() == "done"
    assert "run_game" in brain.offered["coder"] and "run_game" in brain.offered["reviewer"]
    assert "This project is a Godot game: call run_game" in brain.offered["review_prompt"]
    assert "The game has problems" in brain.game_output[0] and "res://broken.gd:3" in brain.game_output[0]
    shots = [d for k, d in events if k == "shots"]
    assert shots and shots[0]["pictures"] == ["start", "middle", "desktop"] and shots[0]["errors"] == 2


def test_other_projects_are_not_offered_run_game(tmp_path, monkeypatch):
    exe = fake_godot(tmp_path / "bin")
    raw = {**json.loads(json.dumps(RAW)), "godot": {"path": str(exe)}}
    brain = GameBrain()
    orch, *_r, events = make(tmp_path, raw=raw, brain=brain)
    orch.start("a python greeter")
    assert orch.run() == "done"
    assert "run_game" not in brain.offered["coder"] and "run_game" not in brain.offered["reviewer"]
    assert "Godot" not in brain.offered["review_prompt"]
    assert not [k for k, _ in events if k == "shots"]
