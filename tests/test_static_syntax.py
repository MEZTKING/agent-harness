"""Every desktop module parses as the ES module the browser loads. Plain ``node --check file.js`` can miss a
module's errors (it reads a .js file by guesswork), so each is checked as a .mjs copy. Skipped without Node."""

import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "roundtable" / "ui" / "static"


@pytest.mark.skipif(not shutil.which("node"), reason="Node isn't installed here")
def test_every_desktop_module_parses(tmp_path):
    bad = []
    for f in sorted(STATIC.glob("*.js")):
        copy = tmp_path / (f.stem + ".mjs")
        copy.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
        res = subprocess.run(["node", "--check", str(copy)], capture_output=True, text=True, timeout=60)
        if res.returncode:
            bad.append(f"{f.name}: {res.stderr.strip().splitlines()[-1] if res.stderr.strip() else res.returncode}")
    assert not bad, "\n".join(bad)
