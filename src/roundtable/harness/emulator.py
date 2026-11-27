"""An Android emulator the harness starts and stops itself (wave 8, stub: p1-proof fills it).

``ready(rows, os_name)`` says whether this machine can (the Android SDK's emulator, an AVD, hardware
acceleration) and why not: ``{"can", "why", "avds": [...]}``. ``start(avd, sdk)`` starts one without saving
its state and waits for it to finish booting: a ``Running`` with ``.serial`` and ``.stop()``. The signatures
are frozen.
"""

from pathlib import Path


class EmulatorError(RuntimeError):
    """The emulator couldn't be started; the message says what to do."""


class Running:
    """A started emulator: ``serial`` for adb, ``stop()`` to shut it down (and make sure it is gone)."""

    def __init__(self, serial: str, stop=None):
        self.serial = serial
        self._stop = stop

    def stop(self) -> None:
        if self._stop:
            self._stop()


def ready(rows, os_name) -> dict:
    """Stub: not yet."""
    return {"can": False, "why": "Starting an emulator by itself isn't built yet.", "avds": []}


def start(avd: str, sdk: Path, run=None, timeout: float = 240) -> "Running":
    """Stub: refuses, plainly."""
    raise EmulatorError("Starting an emulator by itself isn't built yet. For now an app is checked on an emulator that is already running.")
