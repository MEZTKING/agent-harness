"""The office view (office.py, ui/officeapi.py, static/office.js; wave 9): where each agent stands, from what the
harness already knows, and a view that only places pictures. Made-up projects; plain stand-in pictures."""

from __future__ import annotations

import io
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from roundtable import agents, office, officeart
from roundtable.harness import livecmd
from roundtable.harness.orchestrator import Project

STATIC = Path(officeart.__file__).parent / "ui" / "static"
JS = (STATIC / "office.js").read_text(encoding="utf-8")


def at(seconds_ago: float) -> str:
    return datetime.fromtimestamp(time.time() - seconds_ago, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def project(lab: Path, name: str, status: str, tasks=(), events=(), **meta) -> Path:
    root = lab / name
    p = Project(root)
    p.save_meta({"goals": ["a made-up game"], "status": status, **meta})
    (root / ".harness" / "tasks.json").write_text(json.dumps(
        [{"id": t[0], "title": t[1], "role": t[2], "status": t[3]} for t in tasks]), encoding="utf-8")
    for e in events:
        p.append("events.jsonl", e)
    return root


class App:
    def __init__(self, tmp_path, roots):
        self.home = tmp_path / "home"
        self.roots = roots
        self.jobs = SimpleNamespace(jobs={})

    def cfg(self):
        return SimpleNamespace(roles={"artist": SimpleNamespace(kind="image")}, planner_role="planner", reviewer_role="reviewer",
                               critic_role="critic")

    def need_cfg(self):
        return self.cfg()

    def _backup_home(self):
        return self.home

    def _lab_projects(self):
        return list(self.roots)


def actors_of(sc, proj):
    return [a for a in sc["actors"] if a["project"] == proj]


def test_no_app_is_an_empty_office():
    assert office.scene(None) == {"rooms": [], "actors": [], "art": False}


def test_each_state_puts_the_agent_in_its_place(tmp_path):
    lab = tmp_path / "lab"
    building = project(lab, "build", "running", [("T1", "The menu", "builder", "running")],
                       [{"at": at(10), "event": "tool_call", "task": "T1", "tool": "write_file"}])
    reading = project(lab, "read", "running", [("T1", "The map", "builder", "running")],
                      [{"at": at(10), "event": "tool_call", "task": "T1", "tool": "read_file"}])
    command = project(lab, "cmd", "running", [("T1", "Tests", "builder", "running")],
                      [{"at": at(10), "event": "tool_call", "task": "T1", "tool": "run_command"}])
    reg = livecmd.live_dir(command)
    reg.mkdir(parents=True, exist_ok=True)
    (reg / livecmd.REGISTRY).write_text(json.dumps({"commands": [{"task": "T1", "pid": 1, "until": time.time() + 600}]}))
    waiting = project(lab, "wait", "awaiting_approval", [], [{"at": at(30), "event": "plan"}])
    sc = office.scene(App(tmp_path, [building, reading, command, waiting]))
    assert len(sc["rooms"]) == 4 and sc["more"] == 0
    assert sc["rooms"][0]["id"] == "wait"  # what waits for the owner comes first
    (b,) = actors_of(sc, "build")
    assert (b["name"], b["agent"], b["at"], b["bubble"], b["task"]) == ("Torvic", "torvic", "desk", None, "T1")
    assert "The menu" in b["doing"]
    assert actors_of(sc, "read")[0]["at"] == "shelf"
    assert actors_of(sc, "cmd")[0]["at"] == "terminal"
    (w,) = actors_of(sc, "wait")
    assert (w["name"], w["at"], w["bubble"], w["tone"]) == ("Maelin", "door", "question", "flare")
    for a in sc["actors"]:
        assert {"id", "name", "at", "doing", "bubble", "project"} <= set(a)


def test_money_quiet_resting_letters_and_a_task_passed(tmp_path):
    lab = tmp_path / "lab"
    money = project(lab, "money", "paused_budget", [("T2", "Sound", "builder", "pending")], [{"at": at(60), "event": "status"}])
    quiet = project(lab, "quiet", "running", [("T1", "Levels", "builder", "running")],
                    [{"at": at(1800), "event": "tool_call", "task": "T1", "tool": "write_file"}])
    resting = project(lab, "rest", "done", [("T1", "Art", "artist", "done")],
                      [{"at": at(600), "event": "task_end", "task": "T1", "status": "done"}])
    passed = project(lab, "passed", "done", [("T1", "Check", "reviewer", "done")],
                     [{"at": at(30), "event": "task_end", "task": "T1", "status": "done"}])
    sc = office.scene(App(tmp_path, [money, quiet, resting, passed]))
    assert actors_of(sc, "money")[0]["bubble"] == "coin" and actors_of(sc, "money")[0]["at"] == "door"
    q = actors_of(sc, "quiet")[0]
    assert (q["at"], q["bubble"]) == ("desk", "warning") and "Nothing has happened" in q["doing"]
    r = actors_of(sc, "rest")[0]
    assert (r["name"], r["at"], r["bubble"]) == ("Pell", "sofa", "asleep")
    p = actors_of(sc, "passed")[0]
    assert (p["name"], p["bubble"]) == ("Ondra", "tick")

    lab2 = tmp_path / "lab2"
    letter = project(lab2, "letter", "running", [("T1", "Ask", "builder", "running")],
                     [{"at": at(5), "event": "tool_call", "task": "T1", "tool": "mcp__roundtable__hub_send"}])
    (a,) = office.scene(App(tmp_path, [letter]))["actors"]
    assert (a["at"], a["bubble"]) == ("mailbox", "letter")


def test_no_actor_without_an_event(tmp_path):
    lab = tmp_path / "lab"
    silent = project(lab, "silent", "running", [])  # nothing ever happened
    old = project(lab, "old", "done", [("T1", "Art", "artist", "done")],
                  [{"at": at(86400), "event": "task_end", "task": "T1", "status": "done"}])
    idle = project(lab, "idle", "paused", [("T1", "x", "builder", "pending")], [{"at": at(20), "event": "status"}])
    sc = office.scene(App(tmp_path, [silent, old, idle]))
    assert sc["rooms"] == [] and sc["actors"] == [] and sc["words"] == "Nobody is working right now."


def test_at_most_four_rooms_and_the_rest_counted(tmp_path):
    lab = tmp_path / "lab"
    roots = [project(lab, f"p{i}", "running", [("T1", "x", "builder", "running")],
                     [{"at": at(5 + i), "event": "tool_call", "task": "T1", "tool": "write_file"}]) for i in range(7)]
    sc = office.scene(App(tmp_path, roots))
    assert len(sc["rooms"]) == 4 and sc["more"] == 3 and "and 3 more" in sc["words"]
    assert {a["project"] for a in sc["actors"]} == {r["id"] for r in sc["rooms"]}


def test_an_agent_with_no_figure_is_a_plain_helper(tmp_path):
    app = App(tmp_path, [])
    zed = agents.save(app.home, {"name": "Zed", "job": "builder", "hire": True})
    root = project(tmp_path / "lab", "z", "running", [("T1", "x", "builder", "running")],
                   [{"at": at(5), "event": "tool_call", "task": "T1", "tool": "write_file"}])
    app.roots = [root]
    (a,) = office.scene(app)["actors"]
    assert a["name"] == "Zed" and a["agent"] in ("helper-a", "helper-b") and a["id"].endswith(zed.id)


# -- the API ------------------------------------------------------------------------------------------------------------
def stand_ins(folder: Path) -> None:
    """Plain one-colour stand-in pictures for every piece (not art: they only prove the placing)."""
    folder.mkdir(parents=True, exist_ok=True)
    for p in officeart.manifest():
        b = io.BytesIO()
        Image.new("RGBA", (p["width"], p["height"]), (60, 40, 120, 255)).save(b, "PNG")
        (folder / f"{p['id']}.png").write_bytes(b.getvalue())


def test_the_api_with_no_art_and_then_with_stand_ins(tmp_path, monkeypatch):
    from roundtable.ui import server

    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "officeapi"))
    monkeypatch.setattr(officeart, "MANIFEST", _copy_manifest(tmp_path))  # never the shipped folder
    app = App(tmp_path, [])
    r = server._feature_routes(app)
    assert r[("GET", "/api/office/art")]({}) == {"art": False, "pieces": {}}
    assert r[("GET", "/api/office")]({})["art"] is False  # no art: the switch stays hidden
    st = r[("GET", "/api/office/status")]({})
    assert st["ask"] is None and st["spent"] == 0 and "Ring" in st["words"]
    with pytest.raises(server.ApiError, match="Retro Diffusion"):
        r[("POST", "/api/office/answer")]({"choice": "rest", "confirm": True})
    assert r[("POST", "/api/office/answer")]({"choice": "rest"})["done"] is False  # no confirm: nothing spent
    stand_ins(officeart.paths(app)[0])
    art = r[("GET", "/api/office/art")]({})
    assert art["art"] and len(art["pieces"]) == len(officeart.manifest()) and art["room"]["width"] > 0
    assert all(p["url"].startswith("data:image/png;base64,") for p in art["pieces"].values())
    assert r[("GET", "/api/office")]({})["art"] is True


def _copy_manifest(tmp_path: Path) -> Path:
    d = tmp_path / "static-office"
    d.mkdir()
    (d / "manifest.json").write_text(officeart.MANIFEST.read_text(encoding="utf-8"), encoding="utf-8")
    return d / "manifest.json"


def test_six_agents_in_the_right_places_with_stand_in_pictures(tmp_path, monkeypatch):
    """The wave's exit: with plain test pictures the office shows six agents where they belong."""
    monkeypatch.setattr(officeart, "MANIFEST", _copy_manifest(tmp_path))
    lab = tmp_path / "lab"
    roles = [("planner", "whiteboard"), ("builder", "desk"), ("reviewer", "shelf"), ("critic", "desk"),
             ("designer", "desk"), ("illustrator", "desk")]
    app = App(tmp_path, [])
    cfg = SimpleNamespace(roles={"illustrator": SimpleNamespace(kind="image")}, planner_role="planner",
                          reviewer_role="reviewer", critic_role="critic", design_role="designer")
    app.cfg = lambda: cfg
    tasks = [(f"T{i}", f"Part {i}", role, "running") for i, (role, _) in enumerate(roles, 1)]
    events = [{"at": at(5), "event": "tool_call", "task": "T3", "tool": "search"}]
    app.roots = [project(lab, "big", "running", tasks, events)]
    stand_ins(officeart.paths(app)[0])
    sc = office.scene(app)
    assert sc["art"] is True
    names = {a["name"]: a for a in sc["actors"]}
    assert set(names) == {"Maelin", "Torvic", "Ondra", "Kestrel", "Calla", "Pell"}
    assert names["Ondra"]["at"] == "shelf" and names["Torvic"]["at"] == "desk"
    assert {a["agent"] for a in sc["actors"]} == {"maelin", "torvic", "ondra", "kestrel", "calla", "pell"}
    spots = officeart.layout()["spots"]
    assert all(a["at"] in spots for a in sc["actors"])


# -- the view ----------------------------------------------------------------------------------------------------------
def test_office_js_parses():
    subprocess.run(["node", "--check", str(STATIC / "office.js")], check=True)


def test_office_js_draws_no_shape_only_pictures():
    code = re.sub(r"//.*", "", JS)
    for call in ("arc(", "lineTo(", "fillRect(", "strokeRect(", "bezierCurveTo(", "quadraticCurveTo(", "rect(",
                 "fillText(", "createLinearGradient(", "<svg"):
        assert call not in code, call
    assert "drawImage(" in code and "imageSmoothingEnabled = false" in code


def test_office_js_respects_reduced_motion_and_play_animations():
    assert "prefers-reduced-motion: reduce" in JS and "Play animations" in JS
    assert "requestAnimationFrame(tick)" in JS and "if (motion &&" in JS  # stills when motion is off


def test_office_js_has_no_switch_without_art_and_no_timer_of_its_own():
    assert "if (!(await officeAvailable())) return null;" in JS
    assert "setInterval" not in JS and "setTimeout" not in JS and "onHall(node" in JS


def test_office_js_styles_use_tokens_and_logical_sides():
    css = JS[JS.index("officeStyles() {"):]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", css)
    assert not re.search(r"(?<![-\w])(left|right)\s*:", css) and "margin-left" not in css and "padding-right" not in css
    assert "var(--color-" in css
