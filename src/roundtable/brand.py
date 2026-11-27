"""The name the owner reads, in one place (Darkness Harness, from 1.0.0).

Only words people see read from here. Names machines read – the `roundtable` command and package,
`%APPDATA%\\RoundtableHold`, the installer's AppId, the phone's applicationId, the `roundtable:`
hub prefix, `ROUNDTABLE_*` variables – stay as they are, so nothing installed breaks.
"""

NAME = "Darkness Harness"          # the full name: window titles, installer, notes
SHORT = "Darkness"                 # where space is short: the phone's icon label
LEGACY_NAME = "Roundtable Hold"    # what installed copies were called before 1.0.0
EXE = "DarknessHarness.exe"
LEGACY_EXE = "RoundtableHold.exe"

# How the harness signs a choice it made by itself in the journal. Entries written before 1.0.0
# start with the legacy words; anything that reads them must accept both (see `is_switched`).
SWITCHED = "Switched by the harness:"
LEGACY_SWITCHED = "Switched by Roundtable:"


def is_switched(text: str) -> bool:
    """True for a journal line the harness wrote about a choice it made itself, old name or new."""
    return text.startswith((SWITCHED, LEGACY_SWITCHED))
