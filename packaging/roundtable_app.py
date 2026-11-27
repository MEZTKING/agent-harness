"""PyInstaller entry point for the Darkness Harness desktop app (DarknessHarness.exe)."""
import sys

# the plug-in box and the app's own Python come first, so neither loads the desktop or the key vault
if "--plugin-box" in sys.argv:
    from roundtable.plugins.boxworker import main as box
    raise SystemExit(box(sys.argv[1:]))
from roundtable.pyexec import main as as_python, wanted as python_wanted  # noqa: E402  (standard library only)

if python_wanted(sys.argv[1:]):
    raise SystemExit(as_python(sys.argv[1:]))

from roundtable.desktop import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
