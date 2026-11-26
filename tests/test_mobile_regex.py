"""Android's regex engine (ICU) refuses a bare ']' or '}' that Java accepts; the phone app crashed on one
(November 2026). Every Regex("…") in the Kotlin sources must escape them."""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "mobile" / "app" / "src" / "main"


def _bare_closers(pattern: str) -> bool:
    p = re.sub(r"\\.", "", pattern.replace("\\\\", "\\"))   # drop escaped characters
    p = re.sub(r"\[[^\]]*\]", "", p)                        # drop character classes
    p = re.sub(r"\{\d+(,\d*)?\}", "", p)                    # drop counts like {2,}
    return "]" in p or "}" in p


def test_kotlin_patterns_work_on_android():
    bad = []
    for f in SRC.rglob("*.kt"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for pat in re.findall(r'Regex\("((?:[^"\\]|\\.)*)"', line):
                if _bare_closers(pat):
                    bad.append(f"{f.relative_to(SRC)}:{n}: {pat}")
    assert not bad, "escape ] and } for Android:\n" + "\n".join(bad)


def test_the_check_catches_the_crash():
    assert _bare_closers(r"\\s+\\{([A-Za-z0-9_:.-]+)}$") and not _bare_closers(r"\\s+\\{([A-Za-z0-9_:.-]+)\\}$")
