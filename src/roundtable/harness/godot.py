"""Proof for Godot games: Roundtable starts a Godot 4 project itself, without the editor.

* ``find_godot``: the Godot program (harness.yaml ``godot: path``, then ``$GODOT``, then PATH, then a
  few usual places); nothing is ever downloaded;
* ``project_dir``: the folder with ``project.godot`` (the project's own folder or one folder down);
* ``check``: import the project, run its main scene headless for a moment, and collect the errors;
* ``screenshots``: run the main scene with Movie Maker and keep three frames (early, middle, last);
* ``game_tool``: ``run_game``, the check as a worker tool, offered only for Godot projects.

Godot's own words (the error lines) are passed on as they are; everything else is plain.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from .safeenv import clean_env

NAMES = ("godot", "godot4", "Godot")
MARKERS = ("SCRIPT ERROR", "ERROR:", "Parse Error", "Failed to load")
MAX_ERRORS = 20
MAX_LINE = 300
TAIL_CHARS = 3000
CHECK_FRAMES = 60  # frames the headless check runs the main scene for
KEEP = 3  # frames kept from the recording
SKIP_DIRS = {".git", ".harness", ".godot", "node_modules", "addons", "build", "export"}
NOT_INSTALLED = ("Godot isn't installed here, so the game wasn't started: install Godot 4 and set godot: path "
                 "in harness.yaml")


class GodotError(RuntimeError):
    """Godot couldn't be run (it timed out or isn't there): the message says what to do."""


class NoDisplay(GodotError):
    """No screen to draw on (Linux without a display or xvfb-run): no pictures, and that's fine."""


# -- finding Godot and the project ------------------------------------------------------------
def _usual_places() -> list[Path]:
    """Where Godot is usually unpacked on Windows and macOS (Godot has no installer of its own)."""
    if sys.platform == "darwin":
        return [Path(p) for p in ("/Applications/Godot.app/Contents/MacOS/Godot",
                                  str(Path.home() / "Applications/Godot.app/Contents/MacOS/Godot"))]
    if os.name != "nt":
        return []
    dirs = [Path(os.environ[v]) for v in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA") if os.environ.get(v)]
    dirs += [Path.home() / "Godot", Path.home() / "Desktop", Path.home() / "Downloads"]
    found: list[Path] = []
    for d in dirs:
        for pattern in ("Godot*/Godot_v4*console.exe", "Godot_v4*console.exe", "Godot*/Godot_v4*.exe",
                        "Godot_v4*.exe", "Godot*/Godot*.exe", "Programs/Godot*/Godot*.exe"):
            try:
                found += sorted(d.glob(pattern), reverse=True)  # the newest version first
            except OSError:
                continue
    return found


def _usable(value: str | None) -> str | None:
    if not value:
        return None
    p = Path(value).expanduser()
    if p.is_file():
        return str(p)
    return shutil.which(value)


def find_godot(cfg_value: str | None = None) -> str | None:
    """The Godot program to run, or None. The setting first, then ``$GODOT``, then PATH."""
    for value in (cfg_value, os.environ.get("GODOT")):
        got = _usable(value)
        if got:
            return got
    for name in NAMES:
        got = shutil.which(name)
        if got:
            return got
    for p in _usual_places():
        if p.is_file():
            return str(p)
    return None


def project_dir(root: Path) -> Path | None:
    """The folder with ``project.godot``: the project's own folder, or one folder down (e.g. game/)."""
    root = Path(root)
    if (root / "project.godot").is_file():
        return root
    try:
        subs = sorted(p for p in root.iterdir() if p.is_dir() and p.name not in SKIP_DIRS and not p.name.startswith("."))
    except OSError:
        return None
    return next((d for d in subs if (d / "project.godot").is_file()), None)


def game_name(project: Path) -> str:
    """The game's name from project.godot (``config/name="..."``), or the folder's name."""
    try:
        text = (Path(project) / "project.godot").read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    m = re.search(r'^\s*config/name\s*=\s*"((?:[^"\\]|\\.)*)"', text, re.M)
    return (m.group(1) if m else Path(project).name)[:200]


# -- running Godot ----------------------------------------------------------------------------
def _kill(proc: subprocess.Popen) -> None:
    """Stop Godot and anything it started (a wrapper script's child too)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=30)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def run(cmd: list[str], timeout: int, cwd: Path | None = None) -> tuple[int | None, str]:
    """Run a command; returns (exit code, output). Exit code None means it ran out of time.

    The output goes to a temporary file rather than a pipe, so a program left behind by a wrapper
    can't keep Roundtable waiting after the time is up."""
    with tempfile.TemporaryFile() as out:
        kw: dict[str, Any] = {"start_new_session": True} if os.name != "nt" else {}
        proc = subprocess.Popen(cmd, cwd=str(cwd) if cwd else None, stdin=subprocess.DEVNULL, stdout=out,
                                stderr=subprocess.STDOUT, env=clean_env(), **kw)
        try:
            code: int | None = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill(proc)
            code = None
        out.seek(0)
        return code, out.read().decode("utf-8", errors="replace")


def errors_in(output: str) -> list[str]:
    """Godot's error lines, each with the ``at:`` line after it; no repeats, at most MAX_ERRORS."""
    lines = output.splitlines()
    found: list[str] = []
    for i, line in enumerate(lines):
        text = line.strip()
        if not text or not any(m in text for m in MARKERS):
            continue
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if nxt.startswith("at:"):
            text = f"{text} {nxt}"
        text = text[:MAX_LINE]
        if text not in found:
            found.append(text)
        if len(found) >= MAX_ERRORS:
            break
    return found


def check(project: Path, godot: str, timeout: int = 120, frames: int = CHECK_FRAMES) -> dict[str, Any]:
    """Import the project, then run its main scene headless for ``frames`` frames.

    Returns {ok, errors, output_tail, seconds}. Never raises for Godot's own problems."""
    project = Path(project)
    t0 = time.monotonic()
    errors: list[str] = []
    tail = ""
    steps = (("import", [godot, "--headless", "--path", str(project), "--import"]),
             ("run", [godot, "--headless", "--path", str(project), "--quit-after", str(frames)]))
    code: int | None = 0
    for what, cmd in steps:
        try:
            code, output = run(cmd, timeout, cwd=project)
        except OSError as e:
            errors.append(f"Godot couldn't be started ({e}): check godot: path in harness.yaml")
            code = 1
            break
        tail = (tail + f"\n--- {what} ---\n" + output)[-TAIL_CHARS:]
        for e in errors_in(output):
            if e not in errors:
                errors.append(e)
        if code is None:
            errors.append(f"Godot took longer than {timeout} seconds to {'import the project' if what == 'import' else 'run the game'}, "
                          "so it was stopped: look for an endless loop, or raise godot: timeout in harness.yaml")
            break
    if code not in (None, 0) and not errors:
        errors.append(f"Godot stopped with exit code {code}: see the output below")
    return {"ok": not errors, "errors": errors[:MAX_ERRORS], "output_tail": tail.strip()[-TAIL_CHARS:],
            "seconds": round(time.monotonic() - t0, 2)}


def check_text(result: dict[str, Any]) -> str:
    """The check as a short text for a model."""
    if result.get("ok"):
        return f"The game started and ran without errors ({result.get('seconds', 0)} s)."
    lines = "\n".join(f"- {e}" for e in result.get("errors") or [])
    tail = result.get("output_tail") or ""
    return (f"The game has problems ({len(result.get('errors') or [])}):\n{lines}"
            + (f"\n\nGodot's last output:\n{tail[-1500:]}" if tail else ""))


# -- pictures ---------------------------------------------------------------------------------
def display_prefix() -> list[str] | None:
    """What to put before Godot so it has a screen: [] when there is one, ``xvfb-run -a`` on a Linux
    computer without a display, None when there is no way to draw."""
    if os.name == "nt" or sys.platform == "darwin":
        return []
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return []
    xvfb = shutil.which("xvfb-run")
    return [xvfb, "-a"] if xvfb else None


def screenshots(project: Path, godot: str, out_dir: Path, frames: int = 90, timeout: int = 120) -> list[Path]:
    """Run the main scene with Movie Maker for ``frames`` frames and keep three of them (early, middle,
    last) in ``out_dir``; the other frames and the sound are deleted. Raises NoDisplay or GodotError."""
    prefix = display_prefix()
    if prefix is None:
        raise NoDisplay("pictures skipped: this computer has no screen to draw the game on (install xvfb to take "
                        "them without one)")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame*"):
        old.unlink()
    cmd = prefix + [godot, "--path", str(project), "--write-movie", str(out_dir.resolve() / "frame.png"),
                    "--fixed-fps", "30", "--quit-after", str(frames)]
    if prefix:  # xvfb has no graphics card: Godot's OpenGL renderer draws in software there
        cmd += ["--rendering-driver", "opengl3"]
    try:
        code, output = run(cmd, timeout, cwd=Path(project))
    except OSError as e:
        raise GodotError(f"Godot couldn't be started ({e}): check godot: path in harness.yaml")
    # Movie Maker numbers the frames after the name: frame00000000.png, frame00000001.png, ...
    shots = sorted(out_dir.glob("frame*.png"))
    for wav in out_dir.glob("frame*.wav"):
        wav.unlink()
    if not shots:
        if code is None:
            raise GodotError(f"Godot took longer than {timeout} seconds to record the game, so it was stopped")
        last = " ".join(errors_in(output)[:2]) or output.strip()[-300:]
        raise GodotError(f"Godot recorded no frames{': ' + last if last else ''}")
    n = len(shots)
    keep = []
    for i in (n // 10, n // 2, n - 1):
        if shots[i] not in keep:
            keep.append(shots[i])
    for p in shots:
        if p not in keep:
            p.unlink()
    return keep


# -- the worker's tool ------------------------------------------------------------------------
def available(root: Path, settings: Any) -> tuple[Path, str] | None:
    """(the Godot project, the Godot program) when the project is a Godot game and Godot is here."""
    if settings is not None and not getattr(settings, "enabled", True):
        return None
    project = project_dir(root)
    if project is None:
        return None
    godot = find_godot(getattr(settings, "path", None))
    return (project, godot) if godot else None


def game_tool(root: Path, settings: Any):
    """``run_game`` for a Godot project with Godot installed; None for every other project."""
    got = available(root, settings)
    if not got:
        return None
    from ..providers.base import ToolSpec
    from .tools import Tool, _obj

    project, godot = got
    timeout = int(getattr(settings, "timeout", 120) or 120)

    def run_game(args: dict) -> str:
        return check_text(check(project, godot, timeout=timeout))

    return Tool(ToolSpec(
        "run_game", "Start the Godot game without a window for a moment (after importing it) and report its "
                    "script and loading errors. Use it to test your GDScript and scenes.", _obj({}, [])), run_game)


# -- playing it (harness/playtest.py) ---------------------------------------------------------
# Godot can't be steered turn by turn from outside, so a play is planned first: a list of inputs at set
# frames, read by a small driver script given on the command line (``--script``). The driver loads the
# game's main scene and presses the inputs; the project's own files are never changed. The driver and
# its input file live in a temporary folder outside the project and are removed afterwards.
PLAY_FPS = 10  # Movie Maker's frames a second while playing (60 seconds are 600 pictures, most deleted)
DEFAULT_ACTIONS = ("ui_right", "ui_accept", "ui_left", "ui_up", "ui_down")
INPUT_FLAG = "--harness-input="
PLAY_DRIVER = """extends SceneTree
# Written by the harness for one play and deleted afterwards: it loads the game's main scene and
# presses the inputs listed in the file given after --harness-input= (an action, pressed or released,
# at a frame). Nothing in the game's own folder is changed.

var events = []
var frame = 0
var next_event = 0


func _initialize():
	var path = ""
	for a in OS.get_cmdline_user_args():
		if a.begins_with("%(flag)s"):
			path = a.substr(%(flag_len)d)
	var f = FileAccess.open(path, FileAccess.READ)
	if f:
		var got = JSON.parse_string(f.get_as_text())
		if got is Array:
			events = got
	var main = str(ProjectSettings.get_setting("application/run/main_scene", ""))
	if main == "":
		push_error("No main scene is set: Project Settings, Application, Run, Main Scene")
	else:
		change_scene_to_file.call_deferred(main)


func _process(_delta):
	while next_event < events.size() and int(events[next_event].get("frame", 0)) <= frame:
		var e = events[next_event]
		next_event += 1
		var act = str(e.get("action", ""))
		if not InputMap.has_action(act):
			continue
		var ev = InputEventAction.new()
		ev.action = act
		ev.pressed = bool(e.get("pressed", false))
		Input.parse_input_event(ev)
		print("HARNESS_INPUT frame=%%d %%s %%s" %% [frame, act, "down" if ev.pressed else "up"])
	frame += 1
	return false
""" % {"flag": INPUT_FLAG, "flag_len": len(INPUT_FLAG)}


def input_actions(project: Path) -> list[str]:
    """The game's own input actions from project.godot's [input] section, then Godot's usual ui_ ones."""
    try:
        text = (Path(project) / "project.godot").read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    own: list[str] = []
    section = ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1].strip()
            continue
        if section == "input":
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]{0,60})\s*=", s)
            if m and m.group(1) not in own:
                own.append(m.group(1))
    return own[:12] + [a for a in DEFAULT_ACTIONS if a not in own]


def play_schedule(actions: list[str], seconds: float, fps: int = PLAY_FPS) -> list[dict[str, Any]]:
    """A plan for a play: each action held in turn (a short tap for jump-like ones, longer for moving),
    with a pause between, round and round until the time is up. [{frame, action, pressed}]."""
    total = max(1, int(seconds * fps))
    out: list[dict[str, Any]] = []
    if not actions:
        return out
    frame, i = fps // 2, 0  # half a second to start
    while frame < total - 1:
        name = actions[i % len(actions)]
        short = any(w in name.lower() for w in ("jump", "accept", "fire", "shoot", "attack", "select", "action"))
        hold = max(1, fps // 5) if short else max(2, fps)
        out.append({"frame": frame, "action": name, "pressed": True})
        out.append({"frame": min(total - 1, frame + hold), "action": name, "pressed": False})
        frame += hold + max(1, fps // 2)
        i += 1
    return out


def schedule_text(schedule: list[dict[str, Any]], fps: int = PLAY_FPS, limit: int = 30) -> str:
    """The plan in words for the model that watches: "0.5 s: ui_right held 1.0 s"."""
    downs = {}
    lines = []
    for e in schedule:
        if e["pressed"]:
            downs[e["action"]] = e["frame"]
        elif e["action"] in downs:
            start = downs.pop(e["action"])
            lines.append(f"{start / fps:.1f} s: {e['action']} held {(e['frame'] - start) / fps:.1f} s")
    more = f"\n… and {len(lines) - limit} more" if len(lines) > limit else ""
    return "\n".join(lines[:limit]) + more


def record_play(project: Path, godot: str, seconds: float, out_dir: Path, schedule: list[dict[str, Any]],
                keep: int = 12, runner: Any = None, fps: int = PLAY_FPS, timeout: int | None = None) -> dict[str, Any]:
    """Play the game with the planned inputs while Movie Maker records, and keep ``keep`` frames spread
    over the play as ``turn-01.png`` … in ``out_dir``. ``runner(cmd, timeout, cwd) -> (code, output)`` is
    how the command runs (the workspace's own command path in a run; ``run`` here by default).

    Returns {frames: [Path], errors, output_tail, code, timed_out}. Raises NoDisplay or GodotError."""
    prefix = display_prefix()
    if prefix is None:
        raise NoDisplay("not played: this computer has no screen to draw the game on (install xvfb to play "
                        "it without one)")
    project, out_dir = Path(project), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("turn-*.png"):
        old.unlink()
    frames_dir = out_dir / "frames"
    shutil.rmtree(frames_dir, ignore_errors=True)
    frames_dir.mkdir()
    total = max(2, int(seconds * fps))
    timeout = int(timeout or max(60, seconds * 4 + 60))
    tmp = Path(tempfile.mkdtemp(prefix="harness-play-"))  # outside the project, removed below
    try:
        driver, inputs = tmp / "harness_play_driver.gd", tmp / "harness_play_input.json"
        driver.write_text(PLAY_DRIVER, encoding="utf-8")
        import json as _json

        inputs.write_text(_json.dumps(sorted(schedule, key=lambda e: e["frame"])), encoding="utf-8")
        cmd = prefix + [godot, "--path", str(project), "--script", str(driver),
                        "--write-movie", str(frames_dir.resolve() / "frame.png"), "--fixed-fps", str(fps),
                        "--quit-after", str(total)]
        if prefix:
            cmd += ["--rendering-driver", "opengl3"]
        cmd += ["--", INPUT_FLAG + str(inputs)]
        try:
            code, output = (runner or run)(cmd, timeout, project)
        except OSError as e:
            raise GodotError(f"Godot couldn't be started ({e}): check godot: path in harness.yaml")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    shots = sorted(frames_dir.glob("frame*.png"))
    kept: list[Path] = []
    if shots:
        n, k = len(shots), max(1, min(keep, len(shots)))
        picks = sorted({round(i * (n - 1) / max(1, k - 1)) for i in range(k)}) if k > 1 else [n - 1]
        for j, i in enumerate(picks, 1):
            dest = out_dir / f"turn-{j:02d}.png"
            shots[i].replace(dest)
            kept.append(dest)
    shutil.rmtree(frames_dir, ignore_errors=True)
    return {"frames": kept, "errors": errors_in(output or ""), "output_tail": (output or "").strip()[-TAIL_CHARS:],
            "code": code, "timed_out": code is None}


def test_command(project: Path, godot: str = "godot") -> list[str] | None:
    """The game's own tests, when it has GUT or gdUnit4 in addons/ (verify at implementation: beta)."""
    project = Path(project)
    if (project / "addons" / "gut" / "gut_cmdln.gd").is_file():
        return [godot, "--headless", "--path", str(project), "-s", "res://addons/gut/gut_cmdln.gd", "-gexit"]
    if (project / "addons" / "gdUnit4" / "bin" / "GdUnitCmdTool.gd").is_file():
        return [godot, "--headless", "--path", str(project), "-s", "res://addons/gdUnit4/bin/GdUnitCmdTool.gd",
                "--ignoreHeadlessMode", "-a", "res://test"]
    return None
