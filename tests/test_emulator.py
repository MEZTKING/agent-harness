"""An Android emulator the harness starts and stops itself (harness/emulator.py, and the ship stage using it).

The Android SDK is made up: its ``emulator``, ``adb`` and ``aapt2`` are little Python scripts that keep their
state in a folder, so a boot, an install, an open, a picture and a stop are all real processes, without a phone.
A plugged-in phone (``R58M12345``) is always listed by the fake adb, and an emulator someone else started
(``emulator-5554``) is too when starting one; neither must ever be used.
"""

import json
import os
import sys
import time
import zipfile
from pathlib import Path

import pytest

from roundtable import prereq
from roundtable.harness import donelist, emulator, shipstage

from .test_ship import build, item, made_kind, script

PHONE = "R58M12345"
OTHERS = "emulator-5554"

EMULATOR = r'''#!{py}
import json, os, sys, time
from pathlib import Path
st = Path({state!r})
mode = (st / "mode").read_text() if (st / "mode").exists() else "boots"
args = sys.argv[1:]
(st / "emu_args.json").write_text(json.dumps(args))
port = args[args.index("-port") + 1]
if mode == "crash":
    print("INFO: starting")
    print("ERROR: x86_64 emulation currently requires hardware acceleration!")
    sys.exit(1)
(st / "port").write_text(port)
(st / "started").write_text(str(time.time()))
(st / "pid").write_text(str(os.getpid()))
while True:
    if (st / "kill").exists() and mode != "ignore_kill":
        (st / "port").unlink()
        sys.exit(0)
    time.sleep(0.02)
'''

ADB = r'''#!{py}
import json, sys, time
from pathlib import Path
st = Path({state!r})
args = sys.argv[1:]
with open(st / "adb.log", "a") as f:
    f.write(json.dumps(args) + "\n")
mode = (st / "mode").read_text() if (st / "mode").exists() else "boots"
running = (st / "port").exists() and not (st / "kill").exists()
mine = "emulator-" + (st / "port").read_text() if (st / "port").exists() else None
if args == ["devices"]:
    print("List of devices attached")
    print("{phone}\tdevice")
    if (st / "others").exists():
        print("{others}\tdevice")
    if running:
        print(mine + "\tdevice")
    sys.exit(0)
if args[0] != "-s":
    sys.exit(2)
serial, rest = args[1], args[2:]
if serial != mine:
    print("error: device '%s' not found" % serial)
    sys.exit(1)
if rest == ["shell", "getprop", "sys.boot_completed"]:
    if mode == "boots" and running and time.time() - float((st / "started").read_text()) > 0.1:
        print("1")
    sys.exit(0)
if rest == ["emu", "kill"]:
    (st / "kill").write_text("1")
    print("OK: killing emulator, bye bye")
    sys.exit(0)
if rest[:2] == ["install", "-r"]:
    (st / "installed").write_text(rest[2])
    print("Success")
    sys.exit(0)
if rest[:2] == ["shell", "monkey"]:
    (st / "opened").write_text(rest[3])
    print("Events injected: 1")
    sys.exit(0)
if rest[:2] == ["shell", "screencap"]:
    sys.exit(0)
if rest[0] == "pull":
    from PIL import Image
    im = Image.new("RGB", (108, 240), (250, 250, 250))
    for x in range(20, 80):
        im.putpixel((x, 100), (30, 90, 200))
    im.save(rest[2])
    print("1 file pulled")
    sys.exit(0)
sys.exit(3)
'''

AAPT = r'''#!{py}
print("package: name='com.example.madeup' versionCode='1' versionName='1.0'")
print("launchable-activity: name='com.example.madeup.Main'")
'''


def _exe(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    p.chmod(0o755)


def fake_sdk(tmp_path: Path, mode: str = "boots", with_emulator: bool = True,
             others: bool = True) -> tuple[Path, Path]:
    sdk, st = tmp_path / "sdk", tmp_path / "state"
    st.mkdir(parents=True, exist_ok=True)
    (st / "mode").write_text(mode)
    if others:  # an emulator someone else started is listed too
        (st / "others").write_text("1")
    fill = {"py": sys.executable, "state": str(st), "phone": PHONE, "others": OTHERS}
    if with_emulator:
        _exe(sdk / "emulator" / "emulator", EMULATOR.format(**fill))
    _exe(sdk / "platform-tools" / "adb", ADB.replace("{py}", fill["py"]).replace("{state!r}", repr(fill["state"]))
         .replace("{phone}", PHONE).replace("{others}", OTHERS))
    _exe(sdk / "build-tools" / "34.0.0" / "aapt2", AAPT.format(**fill))
    (sdk / "platforms" / "android-34").mkdir(parents=True)
    return sdk, st


def avd_dir(tmp_path: Path, names=("darkness-test-phone",)) -> Path:
    d = tmp_path / "avd"
    d.mkdir(exist_ok=True)
    for n in names:
        (d / f"{n}.ini").write_text("path=x\n")
        (d / f"{n}.avd").mkdir()
    return d


def adb_calls(st: Path) -> list[list[str]]:
    p = st / "adb.log"
    return [json.loads(ln) for ln in p.read_text().splitlines()] if p.exists() else []


def gone(pid: int) -> bool:
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        try:  # a finished child is a zombie until reaped: count that as gone
            if Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z":
                return True
        except OSError:
            return True
        time.sleep(0.05)
    return False


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    from roundtable.harness.gate import ENV

    monkeypatch.setenv(ENV, "off")
    monkeypatch.setattr(emulator, "POLL", 0.05)
    monkeypatch.setattr(emulator, "STOP_WAIT", 3.0)
    yield
    r = emulator.current()
    if r is not None:
        r.stop()


def rows_for(sdk: Path | None) -> list[dict]:
    if sdk is None:
        return [{"id": "android", "state": "missing", "name": "Android SDK"}]
    return [{"id": "android", "state": "found", "name": "Android SDK", "where": str(sdk)}]


pytestmark = pytest.mark.skipif(os.name == "nt", reason="the made-up SDK's programs are scripts")


# -- can this machine? ---------------------------------------------------------------------------------------
def test_ready_says_why_not_and_offers_a_test_phone_with_its_size_first(tmp_path):
    no = emulator.ready_on(rows_for(None), "linux")
    assert not no["can"] and no["why"].startswith("The Android SDK isn't on this computer")
    sdk, _ = fake_sdk(tmp_path, with_emulator=False)
    r = emulator.ready_on(rows_for(sdk), "linux", env={"ANDROID_AVD_HOME": str(tmp_path / "none")})
    assert not r["can"] and r["why"] == "The Android SDK has no emulator yet." and r["offer"]
    sdk2, _ = fake_sdk(tmp_path / "b")
    r = emulator.ready_on(rows_for(sdk2), "linux", env={"ANDROID_AVD_HOME": str(tmp_path / "none")})
    assert not r["can"] and r["why"] == "There's no virtual phone on this computer yet."
    assert r["offer"]["size"] == emulator.DOWNLOAD_SIZE
    assert r["offer"]["words"].startswith("The Android SDK's command-line tools are missing")  # none in this SDK
    sm = sdk2 / "cmdline-tools" / "latest" / "bin"
    _exe(sm / "sdkmanager", "#!/bin/sh\n")
    _exe(sm / "avdmanager", "#!/bin/sh\n")
    r = emulator.ready_on(rows_for(sdk2), "linux", env={"ANDROID_AVD_HOME": str(tmp_path / "none")})
    assert r["offer"]["words"].startswith(f"A download of {emulator.DOWNLOAD_SIZE}.")
    assert r["offer"]["commands"][1][:3] == [str(sm / "avdmanager"), "create", "avd"]


def test_ready_needs_hardware_acceleration_and_then_can(tmp_path):
    sdk, _ = fake_sdk(tmp_path)
    env = {"ANDROID_AVD_HOME": str(avd_dir(tmp_path, ("old-phone", "darkness-test-phone")))}
    r = emulator.ready_on(rows_for(sdk), "linux", env=env, accel=lambda o: (False, "KVM is off."))
    assert not r["can"] and r["why"] == "KVM is off." and r["avds"] == ["darkness-test-phone", "old-phone"]
    r = emulator.ready_on(rows_for(sdk), "linux", env=env, accel=lambda o: (True, ""))
    assert r["can"] and r["avd"] == "darkness-test-phone" and r["emulator"].endswith("emulator")
    assert emulator.acceleration("linux", tmp_path / "no-kvm")[0] is False
    assert emulator.acceleration("windows")[0] is None  # only the emulator itself can tell there


def test_make_avd_installs_the_image_then_makes_the_phone(tmp_path):
    sdk, _ = fake_sdk(tmp_path)
    sm = sdk / "cmdline-tools" / "latest" / "bin"
    _exe(sm / "sdkmanager", "#!/bin/sh\n")
    _exe(sm / "avdmanager", "#!/bin/sh\n")
    calls = []

    def run(argv, timeout, stdin=None):
        calls.append((argv, stdin))
        return 0, "done"

    got = emulator.make_avd(sdk, "linux", run=run, arch="x86_64")
    assert got == {"ok": True, "avd": emulator.AVD_NAME, "words": "The test phone is made."}
    assert calls[0][0][1:] == ["--install", "platform-tools", emulator.SYSTEM_IMAGE]
    assert calls[0][1].startswith("y\n")  # the SDK's licences, accepted on the card
    assert calls[1][0][-4:] == ["-k", emulator.SYSTEM_IMAGE, "-d", emulator.DEVICE]
    bad = emulator.make_avd(sdk, "linux", run=lambda a, t, s=None: (1, "no space left"), arch="x86_64")
    assert not bad["ok"] and "exit code 1" in bad["words"] and "no space left" in bad["words"]


# -- starting and stopping --------------------------------------------------------------------------------
def test_it_boots_on_a_free_port_and_stops_leaving_nothing_running(tmp_path):
    sdk, st = fake_sdk(tmp_path)
    r = emulator.start_on("darkness-test-phone", sdk, timeout=20, os_name="linux")
    assert r.serial == "emulator-5556"  # 5554 is someone else's emulator
    args = json.loads((st / "emu_args.json").read_text())
    assert args[:2] == ["-avd", "darkness-test-phone"] and "-no-snapshot" in args and "-no-window" in args
    assert emulator.current() is r
    pid = int((st / "pid").read_text())
    r.stop()
    assert gone(pid) and emulator.current() is None
    used = [c[1] for c in adb_calls(st) if c[0] == "-s"]
    assert set(used) == {"emulator-5556"} and ["-s", "emulator-5556", "emu", "kill"] in adb_calls(st)
    r.stop()  # twice is fine


def test_one_emulator_at_a_time(tmp_path):
    sdk, _ = fake_sdk(tmp_path)
    with emulator.start_on("darkness-test-phone", sdk, timeout=20, os_name="linux"):
        with pytest.raises(emulator.EmulatorError, match="one at a time"):
            emulator.start_on("darkness-test-phone", sdk, timeout=20, os_name="linux")
    assert emulator.current() is None


def test_a_boot_that_never_completes_is_stopped_and_reported(tmp_path):
    sdk, st = fake_sdk(tmp_path, mode="never")
    t0 = time.monotonic()
    with pytest.raises(emulator.EmulatorError, match="didn't finish starting within 1 minute, so it was stopped"):
        emulator.start_on("darkness-test-phone", sdk, timeout=0.5, os_name="linux")
    assert time.monotonic() - t0 < 10
    assert gone(int((st / "pid").read_text())) and emulator.current() is None


def test_an_emulator_that_ignores_emu_kill_is_ended_with_its_process_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(emulator, "STOP_WAIT", 0.3)
    sdk, st = fake_sdk(tmp_path, mode="ignore_kill")
    (st / "mode").write_text("boots")
    r = emulator.start_on("darkness-test-phone", sdk, timeout=20, os_name="linux")
    (st / "mode").write_text("ignore_kill")
    pid = int((st / "pid").read_text())
    r.stop()
    assert gone(pid)


def test_no_acceleration_is_said_plainly(tmp_path):
    sdk, _ = fake_sdk(tmp_path, mode="crash")
    with pytest.raises(emulator.EmulatorError, match="needs hardware acceleration"):
        emulator.start_on("darkness-test-phone", sdk, timeout=20, os_name="linux")
    assert emulator.current() is None


def test_without_an_emulator_program_it_says_what_to_do(tmp_path):
    sdk, _ = fake_sdk(tmp_path, with_emulator=False)
    with pytest.raises(emulator.EmulatorError, match="no emulator yet"):
        emulator.start_on("x", sdk, os_name="linux")


def test_the_prereq_finder_counts_the_test_phones(tmp_path):
    sdk, _ = fake_sdk(tmp_path)
    s = prereq.System(os="linux", path=[], env={"ANDROID_HOME": str(sdk),
                                                "ANDROID_AVD_HOME": str(avd_dir(tmp_path))},
                      home=tmp_path / "home")
    got = emulator.find_emulator_tool(s, None)
    assert got["where"].endswith("emulator") and got["detail"] == "1 test phone"


# -- the ship stage: built, installed, opened, pictured, stopped -----------------------------------------------------
APK_BUILDER = """
import zipfile, pathlib
pathlib.Path("out").mkdir(exist_ok=True)
with zipfile.ZipFile("out/app.apk", "w") as z:
    z.writestr("AndroidManifest.xml", "x")
    z.writestr("classes.dex", "x")
"""


def _apk_project(tmp_path, mode="boots"):
    sdk, st = fake_sdk(tmp_path, mode=mode, others=False)  # one already running would be used as it is
    root = tmp_path / "proj"
    cmd = script(root, "build.py", APK_BUILDER)
    s = prereq.System(os="linux", path=[], env={"ANDROID_HOME": str(sdk)}, home=tmp_path / "home",
                      root=tmp_path / "fakeroot", run=lambda argv, timeout: (0, "version 99.0.0"))
    orch, events = build(tmp_path, made_kind({"build": cmd, "artefact": "out/*.apk", "smoke": "apk"},
                                             targets=["apk"]), system=s)
    avds = avd_dir(tmp_path)
    orch.ship_emulator_ready = lambda rows, os_name: emulator.ready_on(rows, os_name,
                                                                    env={"ANDROID_AVD_HOME": str(avds)},
                                                                    accel=lambda o: (True, ""))
    orch.ship_open_seconds = 0
    orch.start("a made-up phone app")
    return orch, events, st


def test_the_apk_goes_on_an_emulator_the_harness_starts_and_is_pictured(tmp_path):
    orch, events, st = _apk_project(tmp_path)
    assert orch._ship_estimate([])["minutes"] == 6.0 + shipstage.EMULATOR_MINUTES
    again = orch._ship_step(orch.project.tasks())
    it = item(orch, "ship:apk")
    assert it["state"] == "passed" and again is None, it["words"]
    for words in ("The Android SDK's own check passed.", "It installed on an emulator the harness started "
                  "(darkness-test-phone).", "It opened.", "Its screen was pictured.",
                  "The emulator was stopped afterwards."):
        assert words in it["words"]
    assert (st / "opened").read_text() == "com.example.madeup"
    shots = orch.project.root / ".harness" / "shots" / "ship-apk"
    assert (shots / "phone.png").is_file()
    assert json.loads((shots / "shots.json").read_text())["pictures"] == {"phone": "phone.png"}
    assert gone(int((st / "pid").read_text())) and emulator.current() is None
    calls = adb_calls(st)
    assert all(PHONE not in c for c in calls)  # the plugged-in phone is never used
    assert {c[1] for c in calls if c[0] == "-s"} == {"emulator-5554"}  # only the one it started


def test_a_boot_that_never_completes_in_a_run_is_reported_and_the_apk_still_passes(tmp_path):
    orch, _, st = _apk_project(tmp_path, mode="never")
    orch.cfg.sections["emulator"] = {"boot_seconds": 0.5}
    assert orch._ship_step(orch.project.tasks()) is None
    it = item(orch, "ship:apk")
    assert it["state"] == "passed" and "didn't finish starting" in it["words"]
    assert gone(int((st / "pid").read_text())) and emulator.current() is None
    assert not (st / "installed").exists()


def test_switched_off_no_emulator_is_started(tmp_path):
    orch, _, st = _apk_project(tmp_path)
    orch.cfg.sections["emulator"] = {"start": False}
    assert orch._ship_step(orch.project.tasks()) is None
    it = item(orch, "ship:apk")
    assert it["state"] == "passed" and "switched off in the settings" in it["words"]
    assert not (st / "emu_args.json").exists()
    assert donelist.read(orch.project.root)["items"]


def test_with_no_test_phone_the_card_is_offered(tmp_path):
    orch, events, st = _apk_project(tmp_path)
    orch.ship_emulator_ready = lambda rows, os_name: emulator.ready_on(rows, os_name,
                                                                    env={"ANDROID_AVD_HOME": str(tmp_path / "x")})
    assert orch._ship_step(orch.project.tasks()) is None
    assert "There's no virtual phone on this computer yet." in item(orch, "ship:apk")["words"]
    offers = [d for k, d in events if k == "ship_offer"]
    assert offers and offers[0]["offer"]["size"] == emulator.DOWNLOAD_SIZE
    assert zipfile.is_zipfile(orch.project.root / "out" / "app.apk")
