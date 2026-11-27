"""An Android emulator the harness starts and stops itself (wave 8).

``ready(rows, os_name)`` says whether this machine can (the Android SDK's ``emulator``, a virtual phone (AVD),
hardware acceleration) and why not otherwise: ``{"can", "why", "avds": [...], "avd", "sdk", "emulator",
"offer"}``. With no virtual phone, ``offer`` is the one card that offers to make one, with the download's size
said first (:func:`make_offer`; :func:`make_avd` does it once the owner says yes).

``start(avd, sdk)`` starts one without saving its state (``-no-snapshot``), on a port no device is using, waits
for ``sys.boot_completed`` and gives a :class:`Running` with ``.serial`` (always ``emulator-<port>``, one this
call made: a plugged-in phone is never touched) and ``.stop()`` (``adb emu kill``, then the process tree ended
with ``livecmd.kill_tree`` as the backstop, so none is left running). One emulator at a time; a boot that
never finishes is stopped and reported.

``run(argv, timeout) -> (exit code, text)`` runs adb (tests pass their own); the emulator itself is started by
``_spawn`` (a process with ``.pid``, ``.poll()``, ``.wait()``).
"""


import atexit
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import ship

# The system image a new virtual phone is made from, and what downloading it costs in disk and time
# (verify at a real run: Google changes the images' names and sizes).
SYSTEM_IMAGE = "system-images;android-35;google_apis;x86_64"
SYSTEM_IMAGE_ARM = "system-images;android-35;google_apis;arm64-v8a"
DOWNLOAD_SIZE = "about 1.5 GB"
AVD_NAME = "darkness-test-phone"
DEVICE = "pixel_6"
FIRST_PORT, LAST_PORT = 5554, 5682  # the emulator's own console ports (even numbers)
POLL = 2.0  # seconds between "has it finished starting?"
STOP_WAIT = 20.0  # seconds the emulator gets to close after "emu kill" before its process tree is ended
_sleep = time.sleep
_clock = time.monotonic

Runner = Callable[[list, float], "tuple[int, str]"]


class EmulatorError(RuntimeError):
    """The emulator couldn't be started; the message says what to do."""


class Running:
    """A started emulator: ``serial`` for adb, ``stop()`` to shut it down (and make sure it is gone)."""

    def __init__(self, serial: str, stop=None):
        self.serial = serial
        self._stop = stop
        self.avd = ""
        self.log = ""  # the file the emulator's own output goes to
        self.proc = None
        self.stopped = False

    def alive(self) -> bool:
        return not self.stopped and (self.proc is None or self.proc.poll() is None)

    def stop(self) -> None:
        if self.stopped:
            return
        self.stopped = True
        if self._stop:
            self._stop()

    def __enter__(self) -> "Running":
        return self

    def __exit__(self, *exc) -> None:
        self.stop()


_lock = threading.Lock()
_current: Running | None = None


def current() -> Running | None:
    """The emulator this program started and hasn't stopped yet (one at a time)."""
    with _lock:
        return _current if _current is not None and _current.alive() else None


@atexit.register
def _stop_at_exit() -> None:  # never leave one running when the app closes
    r = current()
    if r is not None:
        try:
            r.stop()
        except Exception:  # noqa: BLE001
            pass


# -- what this machine has ---------------------------------------------------------------------------------
def _os_name() -> str:
    from .. import prereq

    return prereq._os_name()


def emulator_tool(sdk: Path | str | None, os_name: str) -> Path | None:
    """The SDK's ``emulator/emulator`` program (``.exe`` on Windows)."""
    if not sdk:
        return None
    p = Path(sdk) / "emulator" / ("emulator.exe" if os_name == "windows" else "emulator")
    return p if p.is_file() else None


def sdk_manager(sdk: Path | str | None, os_name: str, name: str = "sdkmanager") -> Path | None:
    """``cmdline-tools/<latest or newest>/bin/sdkmanager`` (or ``avdmanager``); ``.bat`` on Windows."""
    if not sdk:
        return None
    exe = f"{name}.bat" if os_name == "windows" else name
    base = Path(sdk) / "cmdline-tools"
    try:
        dirs = sorted((d for d in base.iterdir() if d.is_dir()), key=lambda d: (d.name == "latest", d.name),
                      reverse=True)
    except OSError:
        dirs = []
    for d in dirs:
        if (d / "bin" / exe).is_file():
            return d / "bin" / exe
    old = Path(sdk) / "tools" / "bin" / exe
    return old if old.is_file() else None


def avd_home(env: dict[str, str] | None = None, home: Path | None = None) -> Path:
    """Where virtual phones live: ``ANDROID_AVD_HOME``, else ``ANDROID_USER_HOME/avd``, else ``~/.android/avd``."""
    env = os.environ if env is None else env
    home = Path.home() if home is None else Path(home)
    if env.get("ANDROID_AVD_HOME"):
        return Path(env["ANDROID_AVD_HOME"])
    if env.get("ANDROID_USER_HOME"):
        return Path(env["ANDROID_USER_HOME"]) / "avd"
    if env.get("ANDROID_SDK_HOME"):
        return Path(env["ANDROID_SDK_HOME"]) / ".android" / "avd"
    return home / ".android" / "avd"


def list_avds(env: dict[str, str] | None = None, home: Path | None = None) -> list[str]:
    """The virtual phones made so far (each has ``<name>.ini`` and its ``<name>.avd`` folder)."""
    d = avd_home(env, home)
    try:
        return sorted(p.stem for p in d.glob("*.ini") if (d / f"{p.stem}.avd").is_dir())
    except OSError:
        return []


def acceleration(os_name: str, dev_kvm: Path = Path("/dev/kvm")) -> tuple[bool | None, str]:
    """(True, ""), (False, why) or (None, "") when only the emulator itself can tell (Windows: it says so
    when it starts)."""
    if os_name == "linux":
        if dev_kvm.exists() and os.access(dev_kvm, os.R_OK | os.W_OK):
            return True, ""
        return False, ("This computer's hardware acceleration (KVM) isn't switched on or isn't open to you, so an "
                       "emulator would be far too slow. Switch on virtualisation in the computer's start-up "
                       "settings (BIOS), then add yourself to the kvm group.")
    if os_name == "mac":
        return True, ""  # the Hypervisor framework is part of macOS
    return None, ""


def ready(rows, os_name) -> dict:
    """Can this machine start an emulator by itself? See the module. (The signature is frozen: the options
    tests need are on :func:`ready_on`.)"""
    return ready_on(rows, os_name)


def ready_on(rows, os_name, *, env: dict[str, str] | None = None, home: Path | None = None,
             accel: Callable[[str], tuple[bool | None, str]] | None = None) -> dict:
    """:func:`ready` with where the virtual phones live (``env``, ``home``) and the acceleration check passed in."""
    out: dict[str, Any] = {"can": False, "why": "", "avds": [], "avd": "", "sdk": "", "emulator": "", "offer": None}
    row = next((r for r in rows or [] if r.get("id") == "android"), None)
    if not row or row.get("state") != "found" or not row.get("where"):
        out["why"] = "The Android SDK isn't on this computer, so no emulator can be started. Install it from Tools."
        return out
    sdk = Path(row["where"])
    out["sdk"] = str(sdk)
    emu = emulator_tool(sdk, os_name)
    if emu is None:
        out["why"] = "The Android SDK has no emulator yet."
        out["offer"] = make_offer(sdk, os_name, need_emulator=True)
        return out
    out["emulator"] = str(emu)
    if ship.sdk_tool(sdk, "adb", os_name) is None:
        out["why"] = "The Android SDK has no adb (its platform tools), so an app can't be put on an emulator."
        out["offer"] = make_offer(sdk, os_name, need_emulator=False)
        return out
    avds = list_avds(env, home)
    out["avds"] = avds
    if not avds:
        out["why"] = "There's no virtual phone on this computer yet."
        out["offer"] = make_offer(sdk, os_name, need_emulator=False)
        return out
    ok, why = (accel or acceleration)(os_name)
    if ok is False:
        out["why"] = why
        return out
    out["avd"] = AVD_NAME if AVD_NAME in avds else avds[0]
    out["can"] = True
    return out


# -- making a virtual phone (only after the owner's yes on the card) -------------------------------------------------
def _image(arch: str | None = None) -> str:
    import platform

    arch = (arch or platform.machine() or "").lower()
    return SYSTEM_IMAGE_ARM if arch in ("arm64", "aarch64") else SYSTEM_IMAGE


def make_offer(sdk: Path | str, os_name: str, need_emulator: bool = False, arch: str | None = None) -> dict:
    """The one card: the download's size first, then what it gives. ``commands`` are what :func:`make_avd`
    runs (shown behind More)."""
    sm, am = sdk_manager(sdk, os_name), sdk_manager(sdk, os_name, "avdmanager")
    image = _image(arch)
    packages = ["platform-tools", image] + (["emulator"] if need_emulator else [])
    cmds = []
    if sm:
        cmds.append([str(sm), "--install", *packages])
    if am:
        cmds.append([str(am), "create", "avd", "-n", AVD_NAME, "-k", image, "-d", DEVICE])
    can = bool(sm and am)
    return {"title": "Make a test phone on this computer",
            "size": DOWNLOAD_SIZE,
            "words": (f"A download of {DOWNLOAD_SIZE}. Then the harness can open your Android apps on a phone it "
                      "starts and stops by itself, and show you a picture of them." if can else
                      "The Android SDK's command-line tools are missing, so a test phone can't be made from here. "
                      "Add them from Tools first."),
            "can": can, "commands": cmds, "avd": AVD_NAME}


def make_avd(sdk: Path | str, os_name: str, run: Runner | None = None, arch: str | None = None,
             timeout: float = 3600) -> dict:
    """Download the system image and make the virtual phone: {ok, words, avd}. Licences are answered "y" (the
    SDK's own licences, which the owner accepted by saying yes on the card)."""
    offer = make_offer(sdk, os_name, need_emulator=emulator_tool(sdk, os_name) is None, arch=arch)
    if not offer["can"]:
        return {"ok": False, "words": offer["words"], "avd": ""}
    for argv in offer["commands"]:
        code, text = (run or _run)(argv, timeout, "y\n" * 20 if "--install" in argv else "no\n")
        if code != 0:
            tail = " ".join(ln.strip() for ln in (text or "").splitlines()[-3:] if ln.strip())[:300]
            return {"ok": False, "avd": "",
                    "words": f"Making the test phone stopped (exit code {code}). {tail}".strip()}
    return {"ok": True, "avd": AVD_NAME, "words": "The test phone is made."}


# -- running things ------------------------------------------------------------------------------------------
def _run(argv: list, timeout: float, stdin: str | None = None) -> tuple[int, str]:
    from .safeenv import clean_env

    kw: dict[str, Any] = {}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run([str(a) for a in argv], input=stdin, capture_output=True, text=True, timeout=timeout,
                           env=clean_env(), encoding="utf-8", errors="replace", **kw)
    except subprocess.TimeoutExpired as e:
        return 124, f"timed out after {timeout:g} seconds\n{e.stdout or ''}"
    except OSError as e:
        return 127, str(e)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _spawn(argv: list, log: Path):
    from .safeenv import clean_env

    kw: dict[str, Any] = {}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True  # its own group, so kill_tree ends the emulator and its helpers
    fh = open(log, "wb")  # noqa: SIM115 - the emulator writes to it as long as it runs
    try:
        return subprocess.Popen([str(a) for a in argv], stdout=fh, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=clean_env(), **kw)
    finally:
        fh.close()


def serials(adb_devices_text: str) -> list[str]:
    """Every device adb lists (phones too), in any state."""
    out = []
    for line in (adb_devices_text or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and not line.startswith("List of devices") and not line.startswith("*"):
            out.append(parts[0])
    return out


def free_port(taken: list[str]) -> int:
    """The first console port no device (an emulator another program started included) is on."""
    used = set()
    for s in taken:
        m = re.fullmatch(r"emulator-(\d+)", s)
        if m:
            used.add(int(m.group(1)))
    for port in range(FIRST_PORT, LAST_PORT + 1, 2):
        if port not in used:
            return port
    raise EmulatorError("Every emulator port is in use. Close an emulator, then try again.")


def _tail(path: Path | str, n: int = 4) -> str:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return " ".join(ln.strip() for ln in lines[-n:] if ln.strip())[:400]


def _why_closed(log_tail: str) -> str:
    low = log_tail.lower()
    if any(w in low for w in ("accel", "hypervisor", "haxm", "kvm", "whpx", "virtualization", "aehd")):
        return ("The emulator needs hardware acceleration, which is off on this computer. Switch on "
                "virtualisation in the computer's start-up settings (BIOS) and Windows' Hypervisor Platform, "
                "then try again.")
    if "unknown avd" in low or "no such avd" in low or "cannot find avd" in low:
        return "That virtual phone couldn't be found. Make one again from the card, then try again."
    return f"The emulator closed while it was starting. What it said last: {log_tail or 'nothing'}"


def start(avd: str, sdk: Path, run=None, timeout: float = 240) -> "Running":
    """Start ``avd`` and wait until it has finished booting; see the module. (The signature is frozen: the
    other options are on :func:`start_on`.)"""
    return start_on(avd, sdk, run, timeout)


def start_on(avd: str, sdk: Path, run=None, timeout: float = 240, *, os_name: str | None = None,
             window: bool = False, spawn=None) -> "Running":
    """:func:`start` for a given system; ``window=False`` runs the emulator without a window of its own (the
    pictures come from ``screencap``); ``spawn(argv, log)`` starts the emulator process."""
    global _current
    run = run or _run
    os_name = os_name or _os_name()
    emu, adb = emulator_tool(sdk, os_name), ship.sdk_tool(sdk, "adb", os_name)
    if emu is None:
        raise EmulatorError("The Android SDK has no emulator yet. Add it from the card in Tools, then try again.")
    if adb is None:
        raise EmulatorError("The Android SDK has no adb (its platform tools). Add them from Tools, then try again.")
    with _lock:
        if _current is not None and _current.alive():
            raise EmulatorError("An emulator the harness started is still running: it starts one at a time. "
                                "Wait for that check to finish, then try again.")
        code, text = run([adb, "devices"], 60)
        port = free_port(serials(text) if code == 0 else [])
        serial = f"emulator-{port}"
        argv = [emu, "-avd", avd, "-port", str(port), "-no-snapshot", "-no-boot-anim", "-no-audio"]
        if not window:
            argv.append("-no-window")
        log = Path(tempfile.mkdtemp(prefix="darkness-emulator-")) / "emulator.log"
        proc = (spawn or _spawn)(argv, log)
        r = Running(serial)
        r.avd, r.log, r.proc = avd, str(log), proc
        r._stop = lambda: _stop(r, adb, run)
        _current = r
    deadline = _clock() + max(1.0, float(timeout))
    while True:
        if proc.poll() is not None:
            r.stop()
            raise EmulatorError(_why_closed(_tail(log)))
        c, out = run([adb, "-s", serial, "shell", "getprop", "sys.boot_completed"], 30)
        if c == 0 and out.strip().splitlines()[-1:] == ["1"]:
            return r
        if _clock() >= deadline:
            r.stop()
            mins = max(1, round(float(timeout) / 60))
            raise EmulatorError(f"The emulator didn't finish starting within {mins} minute{'s' * (mins != 1)}, so it "
                                "was stopped. A slow computer may need longer: raise the emulator's start time in "
                                "Settings, then try again.")
        _sleep(POLL)


def _stop(r: Running, adb: Path, run) -> None:
    """``adb emu kill``; if it is still there after STOP_WAIT seconds, its whole process tree is ended."""
    global _current
    try:
        run([adb, "-s", r.serial, "emu", "kill"], 30)
    except Exception:  # noqa: BLE001 - the backstop below still runs
        pass
    proc = r.proc
    if proc is not None:
        end = _clock() + STOP_WAIT
        while proc.poll() is None and _clock() < end:
            _sleep(0.2)
        if proc.poll() is None:
            from .livecmd import kill_tree

            kill_tree(proc.pid)
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                pass
    with _lock:
        if _current is r:
            _current = None


def find_emulator_tool(s, tool) -> dict[str, Any] | None:
    """A ``prereq.Tool`` finder for the "Android emulator" row: the SDK's emulator and how many test phones."""
    from .. import prereq

    for d in prereq._sdk_dirs(s):
        emu = emulator_tool(d, s.os)
        if emu is None:
            continue
        avds = list_avds(s.env, s.home)
        detail = (f"{len(avds)} test phone{'s' * (len(avds) != 1)}" if avds else "no test phone made yet")
        return {"where": str(emu), "version": "", "detail": detail}
    return None
