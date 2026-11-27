"""RoundtableHold.exe from 1.0.0 on: a small starter that opens DarknessHarness.exe beside it.

Kept for two releases so a taskbar pin or shortcut made by hand before the rename still opens the app.
It passes its arguments on; with --self-test it waits and returns the app's answer (the upgrade test in CI
uses that), otherwise it starts the app and leaves at once. Standard library only, so it stays small.
"""
import os
import subprocess
import sys

NEW_EXE = "DarknessHarness.exe"  # brand.EXE (this file is built on its own, without the package)


def main(argv: list[str], here: str | None = None) -> int:
    here = here or os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    target = os.path.join(here, NEW_EXE)
    if not os.path.isfile(target):
        return 2
    if "--self-test" in argv:
        return subprocess.call([target, *argv])
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([target, *argv], cwd=here, creationflags=flags, close_fds=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
