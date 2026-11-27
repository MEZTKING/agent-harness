"""PyInstaller entry point for the Darkness Harness desktop app (DarknessHarness.exe)."""
import sys

from roundtable.desktop import main

if __name__ == "__main__":
    sys.exit(main())
