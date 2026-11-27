"""Ship it (harness/ship.py, harness/shipstage.py): it really builds, and the thing built really starts.

Every project is made up, in tmp_path; the "builders" are small Python or shell scripts that write files, the
models are scripted, and the computer is a made-up one (prereq.System) where a test needs one.
"""

import json
import os
import stat
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

from roundtable import prereq
from roundtable.harness import donelist, ship, shipstage
from roundtable.harness.config import parse_config
from roundtable.harness.gate import ENV as GATE_ENV
from roundtable.harness.gate import Gate
from roundtable.harness.orchestrator import Orchestrator
from roundtable.harness.shipstage import ShipStage
from roundtable.kinds import model as K
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider

from .test_harness import RAW, Brain

ONE = [{"id": "T1", "title": "one", "role": "coder", "description": "write hello.py", "acceptance": "exists",
        "depends_on": []}]
PY = f'"{sys.executable}"'


def made_kind(ship_block, source="builtin", targets=("zip",)):
    return K.Kind(id="made-up", name="Made-up thing", spec={"targets": list(targets), "ship": ship_block},
                  source=source)


class O(Orchestrator):
    made = None  # the kind this test's project has

    def _ship_recipes(self):  # the project's own kind stays as it is; only the recipes are made up
        return ship.recipes(self.made)

    def _kind_proof(self):
        return []  # only the shipping items here: the guessed kind's own checks would join the done list


def build(tmp_path, kind, system=None, plan=ONE):
    cfg = parse_config(json.loads(json.dumps(RAW)))
    brain = Brain(plan=plan)
    for name in ("a", "b"):
        cfg.register(name, ScriptedProvider(name, brain))
    cfg.register("img", ScriptedImages())
    events = []
    cls = type("Made", (O,), {"made": kind, "ship_system": system, "ship_smoke_seconds": 1.0})
    orch = cls(cfg, tmp_path / "proj", on_event=lambda k, d: events.append((k, d)))
    return orch, events


def script(root: Path, name: str, body: str) -> str:
    """A little builder script in the project; returns the command that runs it."""
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(body, encoding="utf-8")
    return f"{PY} {name}"


ZIP_BUILDER = """
import zipfile, pathlib
pathlib.Path("out").mkdir(exist_ok=True)
with zipfile.ZipFile("out/thing.zip", "w") as z:
    z.writestr("hello.txt", "hi")
"""


def fake_system(tmp_path, os_name="linux", tools=()):
    """A made-up computer: only the named programs are on it (each says version 99.0)."""
    bin_ = tmp_path / "fakebin"
    bin_.mkdir(parents=True, exist_ok=True)
    for t in tools:
        p = bin_ / (t + (".exe" if os_name == "windows" else ""))
        p.write_text("", encoding="utf-8")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return prereq.System(os=os_name, path=[bin_], env={"PATHEXT": ".EXE"}, home=tmp_path / "home",
                         root=tmp_path / "fakeroot", run=lambda argv, timeout: (0, "version 99.0.0"))


def item(orch, iid):
    return next(i for i in donelist.read(orch.project.root)["items"] if i["id"] == iid)


@pytest.fixture(autouse=True)
def _gate_off(monkeypatch):
    monkeypatch.setenv(GATE_ENV, "off")  # the project "never asks": only a kind's own recipe may still ask


# -- the pure checks ---------------------------------------------------------------------------------------------
def test_check_artefact_good_missing_empty_and_wrong_first_bytes(tmp_path):
    r = {"target": "apk", "artefact": "out/*.apk"}
    got = ship.check_artefact(tmp_path, r)
    assert not got["ok"] and "no file matching out/*.apk" in got["words"]
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "a.apk").write_bytes(b"")
    got = ship.check_artefact(tmp_path, r)
    assert not got["ok"] and "empty" in got["words"]
    (tmp_path / "out" / "a.apk").write_bytes(b"MZ not a zip")
    got = ship.check_artefact(tmp_path, r)
    assert not got["ok"] and "isn't a real APK file" in got["words"]
    (tmp_path / "out" / "a.apk").write_bytes(b"PK\x03\x04 a zip")
    got = ship.check_artefact(tmp_path, r)
    assert got["ok"] and got["path"] == "out/a.apk" and "was built" in got["words"]
    exe = {"target": "exe", "artefact": "dist/*.exe"}
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "a.exe").write_bytes(b"PK..")
    assert not ship.check_artefact(tmp_path, exe)["ok"]
    (tmp_path / "dist" / "a.exe").write_bytes(b"MZ\x90\x00")
    assert ship.check_artefact(tmp_path, exe)["ok"]
    # outside the project is never looked at
    assert ship.find_artefact(tmp_path, "../*.exe") is None


def test_a_mod_jar_must_hold_its_mod_file_and_code(tmp_path):
    libs = tmp_path / "build" / "libs"
    libs.mkdir(parents=True)
    with zipfile.ZipFile(libs / "lantern-1.0.jar", "w") as z:
        z.writestr("com/example/Lantern.class", b"\xca\xfe")
    with zipfile.ZipFile(libs / "lantern-1.0-sources.jar", "w") as z:
        z.writestr("fabric.mod.json", "{}")
    found = ship.find_artefact(tmp_path, "build/libs/*.jar")
    assert found.name == "lantern-1.0.jar"  # the sources jar is passed over
    got = ship.mod_check(found)
    assert not got["ok"] and "no mod file inside" in got["words"]
    with zipfile.ZipFile(libs / "lantern-1.0.jar", "w") as z:
        z.writestr("fabric.mod.json", "{}")
        z.writestr("com/example/Lantern.class", b"\xca\xfe")
    got = ship.mod_check(found)
    assert got["ok"] and "fabric.mod.json" in got["words"]


def test_an_apk_needs_its_manifest_and_code(tmp_path):
    p = tmp_path / "a.apk"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("AndroidManifest.xml", b"\x03\x00")
    assert not ship.apk_check(p)["ok"]
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("AndroidManifest.xml", b"\x03\x00")
        z.writestr("classes.dex", b"dex\n")
    assert ship.apk_check(p)["ok"]


def test_only_running_emulators_never_a_plugged_in_phone():
    text = "List of devices attached\nR58M12ABCDE\tdevice\nemulator-5554\tdevice\nemulator-5556\toffline\n"
    assert ship.emulators(text) == ["emulator-5554"]


def test_gradlew_on_windows_and_the_exit_code():
    assert ship.for_os("cd android && ./gradlew assembleDebug", "windows") == "cd android && gradlew.bat assembleDebug"
    assert ship.for_os("./gradlew build", "linux") == "./gradlew build"
    assert ship.exit_code("exit code: 3\n--- stdout ---\n") == 3 and ship.exit_code("nope") is None


def test_can_build_says_why_not(tmp_path):
    rows = prereq.status(fake_system(tmp_path))
    exe = {"target": "exe", "name": "Windows program (EXE)", "needs": ["node"], "os": ["windows"]}
    ok, why = ship.can_build(exe, rows, "linux")
    assert not ok and why == "No Windows here: the EXE can't be built on this machine."
    jar = {"target": "jar", "name": "Minecraft or Java mod", "needs": ["java"], "os": list(ship.OSES)}
    ok, why = ship.can_build(jar, rows, "linux")
    assert not ok and "Java (JDK 17 or newer) is not on this computer" in why and "mod file" in why
    rows = prereq.status(fake_system(tmp_path / "b", tools=["java"]))
    assert ship.can_build(jar, rows, "linux") == (True, "")


# -- the schema --------------------------------------------------------------------------------------------------
BASE = "schema: kind@1\nid: made-up\nname: Made-up\n"


@pytest.mark.parametrize("block,line,words", [
    ("ship: npm run dist\n", 4, "ship must be a list of settings"),
    ("ship:\n  build: npm run dist\n", 4, "ship needs artefact"),
    ("ship:\n  build: npm run dist\n  artefact: ../out.exe\n", 6, "inside the project"),
    ("ship:\n  build: x\n  artefact: a.exe\n  sign: yes\n", 7, "'sign' isn't a setting ship: can have"),
    ("ship:\n  build: x\n  artefact: a.exe\n  os: [windows, amiga]\n", 7, "'amiga', which isn't one of"),
    ("ship:\n  build: x\n  artefact: a.exe\n  needs: [rocket]\n", 7, "'rocket', which isn't one of"),
    ("ship:\n  build: x\n  artefact: a.exe\n  timeout: 99999\n", 7, "at most 7200"),
    ("ship:\n  build: \"a\\nb\"\n  artefact: a.exe\n", 5, "ship needs build: one line"),
    ("start:\n  port: 8080\n", 4, "start needs command"),
    ("start:\n  command: npm start\n  port: 99999\n", 6, "port must be a number"),
])
def test_the_schema_refuses_a_bad_ship_or_start_block_with_its_line(block, line, words):
    data, probs = K.parse_text(BASE + block)
    assert data is None, probs
    assert any(p.startswith(f"line {line}:") and words in p for p in probs), probs


def test_a_good_ship_and_start_block_pass():
    data, probs = K.parse_text(BASE + "ship: {build: ./gradlew build, artefact: build/libs/*.jar, smoke: mod, "
                               "needs: [java], os: [linux, windows], target: jar, timeout: 900}\n"
                               "start: {command: npm start, port: 5173, ready: /}\n")
    assert probs == [] and data["ship"]["target"] == "jar" and data["start"]["port"] == 5173


def test_an_imported_kind_shows_its_ship_commands_before_it_goes_in(tmp_path):
    k = K.load_all(None).kinds["java-mod"]
    got = K.import_file(K.export(k), tmp_path, confirm=False)
    assert "./gradlew build" in got["would"]["commands"] and not got["installed"]


# -- the kinds ---------------------------------------------------------------------------------------------------
def test_android_app_and_java_mod_load_and_are_proposed():
    cat = K.load_all(None)
    assert not cat.problems
    assert cat.kinds["java-mod"].usable and cat.kinds["android-app"].usable
    assert K.propose("a minecraft mod with copper lanterns", cat)[0][0] == "java-mod"
    assert K.propose("a native android app in kotlin for my shopping list", cat)[0][0] == "android-app"
    mod = ship.recipes(K.resolve("java-mod", catalog=cat))
    assert mod == [{**mod[0], "target": "jar", "build": "./gradlew build", "artefact": "build/libs/*.jar",
                    "smoke": "mod", "source": "builtin"}]
    apk = ship.recipes(K.resolve("android-app", catalog=cat))[0]
    assert (apk["target"], apk["smoke"], apk["needs"]) == ("apk", "apk", ["java", "android"])
    both = {r["target"]: r for r in ship.recipes(K.resolve("web-app", ["apk", "exe"], catalog=cat))}
    assert both["exe"]["os"] == ["windows"] and both["exe"]["smoke"] == "start"
    assert both["apk"]["build"] == "cd android && ./gradlew assembleDebug"


# -- the stage ---------------------------------------------------------------------------------------------------
def test_a_good_build_passes_all_three_checks_in_a_run(tmp_path):
    root = tmp_path / "proj"
    cmd = script(root, "build.py", ZIP_BUILDER)
    orch, events = build(tmp_path, made_kind({"build": cmd, "artefact": "out/*.zip", "smoke": "none"}))
    orch.start("a made-up tool")
    assert orch.run() == "done"
    it = item(orch, "ship:zip")
    assert it["state"] == "passed" and it["evidence"]["path"] == "out/thing.zip" and it["checked_by"] == "ship"
    assert "out/thing.zip was built" in it["words"]
    assert ("ship", {"target": "zip", "name": "Made-up thing", "passed": True, "words": it["words"]}) in events
    assert orch.ship_status()["targets"][0]["state"] == "passed"
    # the build's output was shown live under "ship"
    assert any(p.name.startswith("ship-") for p in (root / ".harness" / "live").iterdir())


def test_a_missing_artefact_fails_with_a_plain_reason(tmp_path):
    root = tmp_path / "proj"
    cmd = script(root, "build.py", "print('built nothing')\n")
    orch, _ = build(tmp_path, made_kind({"build": cmd, "artefact": "out/*.zip", "smoke": "none"}))
    got = orch._ship_one(ship.recipes(orch.made)[0], "linux", [])
    assert not got["passed"] and got["words"] == "The build finished but no file matching out/*.zip was made."


def test_a_wrong_first_byte_fails_with_a_plain_reason(tmp_path):
    root = tmp_path / "proj"
    cmd = script(root, "build.py", "import pathlib; pathlib.Path('out').mkdir(); "
                                   "pathlib.Path('out/a.zip').write_text('hello')\n")
    orch, _ = build(tmp_path, made_kind({"build": cmd, "artefact": "out/*.zip", "smoke": "none"}))
    got = orch._ship_one(ship.recipes(orch.made)[0], "linux", [])
    assert not got["passed"] and "out/a.zip isn't a real ZIP file" in got["words"]


def test_a_failed_build_makes_one_fix_task_and_only_once(tmp_path):
    root = tmp_path / "proj"
    cmd = script(root, "build.py", "import sys; print('error: missing semicolon'); sys.exit(3)\n")
    orch, events = build(tmp_path, made_kind({"build": cmd, "artefact": "out/*.zip", "smoke": "none"}))
    orch.start("a made-up tool")
    assert orch.run() == "blocked"  # its one fix didn't mend it: the done gate waits for the owner
    assert orch.project.meta()["pause"] == "not_finished"
    tasks = orch.project.tasks()
    fixes = [t for t in tasks if t.added_by == "ship"]
    assert len(fixes) == 1 and fixes[0].fix_of == "ship:zip" and fixes[0].status == "done"
    assert "missing semicolon" in fixes[0].description and "exit code 3" in fixes[0].description
    it = item(orch, "ship:zip")
    assert it["state"] == "failed" and it["words"] == "The build failed (exit code 3)."
    assert donelist.verdict(root) == {"done": False, "failed": ["ship:zip"], "unchecked": []}
    assert sum(1 for k, _ in events if k == "tasks_added") == 1


def test_a_fix_task_that_works_turns_it_green(tmp_path):
    root = tmp_path / "proj"
    # it builds once the fix task has written its file (the scripted builder writes test_hello.py)
    cmd = script(root, "build.py", "import pathlib, sys, zipfile\n"
                                   "if not pathlib.Path('test_hello.py').exists(): sys.exit(1)\n"
                                   + ZIP_BUILDER)
    orch, _ = build(tmp_path, made_kind({"build": cmd, "artefact": "out/*.zip", "smoke": "none"}))
    orch.start("a made-up tool")
    assert orch.run() == "done"
    assert [t.id for t in orch.project.tasks()] == ["T1", "SHIP-zip"]
    assert item(orch, "ship:zip")["state"] == "passed"
    assert donelist.verdict(root)["done"]


def test_a_target_this_machine_cant_build_is_unchecked_and_the_plan_says_why(tmp_path):
    cat = K.load_all(None)
    kind = K.resolve("web-app", ["exe"], catalog=cat)
    kind.spec["ship"] = cat.kinds["java-mod"].spec["ship"]  # and a mod jar, which needs Java
    orch, _ = build(tmp_path, kind, system=fake_system(tmp_path))
    part = orch._ship_plan_part()
    assert "This machine runs Linux." in part
    assert "No Windows here: the EXE can't be built on this machine." in part
    assert "Java (JDK 17 or newer) is not on this computer" in part and "offered Java" in part
    orch.start("a made-up tool")
    assert orch._ship_step(orch.project.tasks()) is None
    exe, jar = item(orch, "ship:exe"), item(orch, "ship:jar")
    assert exe["state"] == jar["state"] == "unchecked"
    assert exe["words"] == "No Windows here: the EXE can't be built on this machine."
    # what this machine can't build never traps the project: shown as not checked, and not a must
    assert not exe["must"] and not jar["must"]
    assert donelist.verdict(orch.project.root) == {"done": True, "failed": [], "unchecked": []}
    assert not [t for t in orch.project.tasks() if t.added_by]  # nothing to fix: it just can't be built here
    est = orch._ship_estimate([])
    assert est["minutes"] == 0 and est["usd"] == 0 and "not checked" in est["words"]


def alive(pid: int) -> bool:
    try:
        st = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return st.rsplit(")", 1)[1].split()[0] != "Z"  # a zombie is gone too


@pytest.mark.skipif(os.name == "nt", reason="the made-up program is a shell script")
def test_the_exe_extra_on_a_made_up_windows_builder_builds_checks_and_starts_it(tmp_path, monkeypatch):
    """The exit check: a web app with the EXE extra ends with a built file that passed the checks."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    npm = bin_ / "npm"
    # the made-up builder: `npm run dist` writes an "EXE" (it starts MZ; the shell runs it as a script) that
    # starts a helper of its own and keeps running
    npm.write_text("#!/bin/sh\nif [ \"$1\" = run ]; then mkdir -p dist; "
                   "printf 'MZ=1\\nsleep 30 &\\necho $! > child.pid\\nwait\\n' > dist/app.exe; "
                   "chmod +x dist/app.exe; fi\n", encoding="utf-8")
    npm.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    kind = K.resolve("web-app", ["exe"], catalog=K.load_all(None))
    orch, _ = build(tmp_path, kind, system=fake_system(tmp_path, "windows", tools=["node"]))
    assert "Windows program (EXE): it can be built here (Node.js found)" in orch._ship_plan_part()
    est = orch._ship_estimate([])
    assert est["minutes"] == 5.0 and est["usd"] > 0 and "Windows program (EXE)" in est["words"]
    orch.start("a made-up tool")
    t0 = time.monotonic()
    assert orch._ship_step(orch.project.tasks()) is None
    it = item(orch, "ship:exe")
    assert it["state"] == "passed", it["words"]
    assert "dist/app.exe was built" in it["words"] and "still running after 1 seconds" in it["words"]
    assert time.monotonic() - t0 < 20
    pid = int((orch.project.root / "child.pid").read_text())
    for _ in range(50):  # the smoke-started program and what it started are gone afterwards
        if not alive(pid):
            break
        time.sleep(0.1)
    assert not alive(pid)


@pytest.mark.skipif(os.name == "nt", reason="the made-up program is a shell script")
def test_a_program_that_quits_straight_away_fails_its_start(tmp_path):
    root = tmp_path / "proj"
    cmd = script(root, "build.py", "import os, pathlib; pathlib.Path('dist').mkdir(); p = pathlib.Path('dist/a.exe');"
                                   " p.write_text('MZ=1\\nexit 2\\n'); os.chmod(p, 0o755)\n")
    orch, _ = build(tmp_path, made_kind({"build": cmd, "artefact": "dist/*.exe", "smoke": "start"}, targets=["exe"]))
    got = orch._ship_one(ship.recipes(orch.made)[0], "windows", [])
    assert not got["passed"] and "closed by itself straight after starting (exit code 2)" in got["words"]


def _answer_when_asked(root: Path, choice: str, seen: list) -> threading.Thread:
    def go():
        d = root / ".harness" / "gate"
        for _ in range(200):
            for f in sorted(d.glob("*.ask.json")) if d.is_dir() else []:
                card = json.loads(f.read_text(encoding="utf-8"))
                seen.append(card)
                Gate(root).answer(card["id"], choice)
                return
            time.sleep(0.05)

    t = threading.Thread(target=go, daemon=True)
    t.start()
    return t


def test_an_imported_kinds_recipe_waits_for_the_owner_even_when_the_project_never_asks(tmp_path):
    root = tmp_path / "proj"
    cmd = script(root, "build.py", ZIP_BUILDER)
    orch, _ = build(tmp_path, made_kind({"build": cmd, "artefact": "out/*.zip", "smoke": "none"}, source="own"))
    orch.start("a made-up tool")
    seen = []
    t = _answer_when_asked(orch.project.root, "allow", seen)
    assert orch._ship_step(orch.project.tasks()) is None
    t.join(5)
    assert len(seen) == 1 and seen[0]["command"] == cmd and shipstage.ASK_REASON in seen[0]["reasons"]
    assert item(orch, "ship:zip")["state"] == "passed"
    # once allowed in this project it doesn't ask again
    donelist.record(orch.project.root, "ship:zip", False, "again")
    asked = []
    orig = shipstage._AskEveryTime.check
    shipstage._AskEveryTime.check = lambda self, c: asked.append(c) or orig(self, c)
    try:
        assert orch._ship_step(orch.project.tasks()) is None
    finally:
        shipstage._AskEveryTime.check = orig
    assert asked == [] and item(orch, "ship:zip")["state"] == "passed"


def test_a_refused_recipe_is_not_checked_and_makes_no_fix_task(tmp_path):
    root = tmp_path / "proj"
    cmd = script(root, "build.py", ZIP_BUILDER)
    orch, _ = build(tmp_path, made_kind({"build": cmd, "artefact": "out/*.zip", "smoke": "none"}, source="own"))
    orch.start("a made-up tool")
    seen = []
    t = _answer_when_asked(orch.project.root, "deny", seen)
    assert orch._ship_step(orch.project.tasks()) is None
    t.join(5)
    it = item(orch, "ship:zip")
    assert it["state"] == "unchecked" and it["words"].startswith("Not built: its build command didn't run")
    assert not (root / "out").exists() and not [x for x in orch.project.tasks() if x.added_by]


def test_a_built_in_recipe_runs_under_the_projects_own_rules(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    cmd = script(root, "build.py", ZIP_BUILDER)
    orch, _ = build(tmp_path, made_kind({"build": cmd, "artefact": "out/*.zip", "smoke": "none"}))
    asked = []
    monkeypatch.setattr(shipstage._AskEveryTime, "check", lambda self, c: asked.append(c))
    orch.start("a made-up tool")
    assert orch._ship_step(orch.project.tasks()) is None
    assert asked == [] and item(orch, "ship:zip")["state"] == "passed"


def test_no_recipe_means_the_stage_does_nothing(tmp_path):
    orch, _ = build(tmp_path, None)
    orch.start("a made-up tool")
    assert orch._ship_plan_part() == "" and orch._ship_estimate([]) is None
    assert orch._ship_step([]) is None and not donelist.path(orch.project.root).exists()
