"""A picture of a running program's window (harness/winshot.py, and the ship stage taking it).

No window is needed: the finder and the grabber are stand-ins, and the ship stage's "EXE" is a little shell
script on a made-up Windows computer.
"""

import io
import json
import os

import pytest
from PIL import Image

from roundtable.harness import donelist, ship, winshot

from .test_ship import build, fake_system, item, made_kind, script


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    monkeypatch.setattr(winshot, "POLL", 0.01)


def win(w=800, h=600, title="Made-up app", visible=True, minimised=False, handle=1):
    return {"handle": handle, "pid": 42, "title": title, "rect": (10, 10, 10 + w, 10 + h), "visible": visible,
            "minimised": minimised}


def drawn(w=80, h=60):
    im = Image.new("RGB", (w, h), (20, 20, 30))
    for x in range(w // 2):
        im.putpixel((x, h // 2), (240, 200, 10))
    return im


def test_the_window_is_found_after_a_moment_and_pictured(tmp_path):
    looks = []

    def find(pid):
        looks.append(pid)
        if len(looks) < 3:
            return []  # the program is still starting
        # a tiny helper window, a hidden one, and the real (biggest) one
        return [win(50, 20, "tiny", handle=2), win(900, 700, "hidden", visible=False, handle=3),
                win(640, 480, "Made-up app", handle=4), win(300, 200, "about box", handle=5)]

    grabbed = []
    got = winshot.window_picture(42, tmp_path / "w.png", wait=2, find=find,
                                 grab=lambda w: grabbed.append(w["handle"]) or drawn())
    assert got["ok"] and got["state"] == "passed", got
    assert grabbed == [4] and set(looks) == {42}
    assert "Made-up app" in got["why"] and got["size"] == [80, 60]
    assert Image.open(got["file"]).size == (80, 60)


def test_png_bytes_from_the_grabber_are_fine(tmp_path):
    buf = io.BytesIO()
    drawn().save(buf, "PNG")
    got = winshot.window_picture(1, tmp_path / "w.png", wait=0, find=lambda p: [win()], grab=lambda w: buf.getvalue())
    assert got["state"] == "passed"


def test_a_window_that_never_appears_is_said_plainly(tmp_path):
    got = winshot.window_picture(7, tmp_path / "w.png", wait=0.1, find=lambda p: [win(visible=False)],
                                 grab=lambda w: drawn())
    assert not got["ok"] and got["state"] == "missing" and got["file"] is None
    assert got["why"].startswith("No window appeared within 0.1 seconds")
    assert not (tmp_path / "w.png").exists()


def test_an_empty_window_is_recorded_as_empty_and_kept(tmp_path):
    tries = []

    def grab(w):
        tries.append(1)
        return Image.new("RGB", (200, 100), (0, 0, 0))  # black all over: nothing drawn

    got = winshot.window_picture(3, tmp_path / "w.png", wait=0.1, find=lambda p: [win()], grab=grab)
    assert not got["ok"] and got["state"] == "empty"
    assert got["why"].startswith("The window was empty")
    assert len(tries) > 1  # tried again while the wait lasted: a window can take a moment to paint
    assert (tmp_path / "w.png").is_file()


def test_one_colour_with_a_little_noise_is_empty_but_a_drawing_is_not():
    im = Image.new("RGB", (40, 40), (255, 255, 255))
    im.putpixel((3, 3), (251, 252, 250))
    assert winshot.is_empty(im)
    assert not winshot.is_empty(drawn())


def test_a_broken_finder_or_grabber_never_crashes(tmp_path):
    def bad(_):
        raise OSError("access denied")

    got = winshot.window_picture(3, tmp_path / "w.png", wait=0, find=bad, grab=lambda w: drawn())
    assert got["state"] == "missing" and "access denied" in got["why"]
    got = winshot.window_picture(3, tmp_path / "w.png", wait=0, find=lambda p: [win()], grab=bad)
    assert got["state"] == "failed" and "access denied" in got["why"]


def test_elsewhere_than_windows_it_is_not_checked_never_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(winshot, "is_windows", lambda: False)
    got = winshot.window_picture(1, tmp_path / "w.png")
    assert got == {"ok": False, "file": None, "state": "unchecked", "title": "", "size": [],
                   "why": got["why"]}
    assert got["why"].startswith("Not checked:") and "Windows" in got["why"]


# -- the ship stage takes it while the smoke start runs -------------------------------------------------------
EXE_BUILDER = ("import os, pathlib; pathlib.Path('dist').mkdir(); p = pathlib.Path('dist/a.exe');"
               " p.write_text('MZ=1\\nsleep 30\\n'); os.chmod(p, 0o755)\n")


def _exe_project(tmp_path, picture):
    root = tmp_path / "proj"
    cmd = script(root, "build.py", EXE_BUILDER)
    orch, events = build(tmp_path, made_kind({"build": cmd, "artefact": "dist/*.exe", "smoke": "start"},
                                             targets=["exe"]), system=fake_system(tmp_path, "windows"))
    seen = []

    def fake(pid, out, wait=8.0):
        seen.append((pid, wait))
        return picture(out)

    orch.ship_window_picture = fake
    orch.start("a made-up tool")
    return orch, events, seen


@pytest.fixture(autouse=True)
def _gate_off(monkeypatch):
    from roundtable.harness.gate import ENV

    monkeypatch.setenv(ENV, "off")


@pytest.mark.skipif(os.name == "nt", reason="the made-up program is a shell script")
def test_the_exe_s_window_joins_the_proof(tmp_path):
    def picture(out):
        drawn().save(out, "PNG")
        return {"ok": True, "file": str(out), "state": "passed", "why": "Its window (Made-up) was pictured.",
                "title": "Made-up", "size": [80, 60]}

    orch, events, seen = _exe_project(tmp_path, picture)
    assert orch._ship_step(orch.project.tasks()) is None
    it = item(orch, "ship:exe")
    assert it["state"] == "passed", it["words"]
    assert "Its window (Made-up) was pictured." in it["words"]
    assert seen and seen[0][0] > 0 and seen[0][1] <= 1.0  # the started command's own process, within its seconds
    rec = json.loads((orch.project.root / ".harness" / "shots" / "ship-exe" / "shots.json").read_text())
    assert rec["pictures"] == {"window": "window.png"} and rec["task"] == "ship:exe"
    assert ("shots", {"task": "ship:exe", "dir": "ship-exe", "pictures": ["window"]}) in events
    assert it["evidence"]["picture"].endswith("window.png")


@pytest.mark.skipif(os.name == "nt", reason="the made-up program is a shell script")
def test_an_empty_window_fails_and_makes_one_fix_task(tmp_path):
    def picture(out):
        Image.new("RGB", (200, 100)).save(out, "PNG")
        return {"ok": False, "file": str(out), "state": "empty", "title": "",
                "why": "The window was empty: the program opened a window but it stayed one plain colour."}

    orch, _, _ = _exe_project(tmp_path, picture)
    assert orch._ship_step(orch.project.tasks()) == "again"
    it = item(orch, "ship:exe")
    assert it["state"] == "failed" and "The window was empty" in it["words"]
    fix = [t for t in orch.project.tasks() if t.id.startswith("SHIP-exe")]
    assert len(fix) == 1 and fix[0].title == "Make the Made-up thing show its window"
    assert "stayed one plain colour" in fix[0].description
    assert orch._ship_step(orch.project.tasks()) is None  # one fix task only; then the done gate decides
    assert len([t for t in orch.project.tasks() if t.id.startswith("SHIP-exe")]) == 1


@pytest.mark.skipif(os.name == "nt", reason="the made-up program is a shell script")
def test_not_windows_means_not_checked_and_the_start_still_passes(tmp_path):
    def picture(out):
        return {"ok": False, "file": None, "state": "unchecked", "why": "Not checked: not Windows.", "title": ""}

    orch, _, _ = _exe_project(tmp_path, picture)
    assert orch._ship_step(orch.project.tasks()) is None
    it = item(orch, "ship:exe")
    assert it["state"] == "passed" and "Not checked: not Windows." in it["words"]


@pytest.mark.skipif(os.name == "nt", reason="the made-up program is a shell script")
def test_switched_off_no_picture_is_asked_for(tmp_path):
    orch, _, seen = _exe_project(tmp_path, lambda out: {})
    orch.cfg.sections["winshot"] = {"off": True}
    assert orch._ship_step(orch.project.tasks()) is None
    assert seen == [] and item(orch, "ship:exe")["state"] == "passed"
    assert donelist.read(orch.project.root)["items"]
    assert ship.recipes(orch.made)[0]["target"] == "exe"
