"""The app's own small Python (pyexec.py, ``--python``): what the frozen Windows app runs the yardstick's checks,
a drafted plug-in's tests and self-repair's test suite with. Tried here through the app's real entry script."""

import os
import subprocess
import sys
from pathlib import Path

from roundtable import pyexec

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "packaging" / "roundtable_app.py"


def _app(*args, cwd=None, env=None):
    e = {**os.environ, "PYTHONPATH": str(REPO / "src"), **(env or {})}
    return subprocess.run([sys.executable, str(APP), *args], cwd=cwd, capture_output=True, text=True, env=e,
                          timeout=120)


def test_python_mode_runs_code_modules_and_scripts(tmp_path):
    r = _app("--python", "-c", "import sys; print('hi', sys.argv[1:])", "x")
    assert r.returncode == 0 and "hi ['x']" in r.stdout, r.stderr
    assert _app("--python", "-c", "raise SystemExit(7)").returncode == 7
    (tmp_path / "tests").mkdir()
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calc.py").write_text("import calc\n\ndef test_add():\n    assert calc.add(2, 2) == 4\n",
                                                     encoding="utf-8")
    r = _app("--python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests", cwd=tmp_path,
             env={"PYTHONPATH": f"{REPO / 'src'}{os.pathsep}{tmp_path}"})
    assert r.returncode == 0 and "1 passed" in r.stdout, r.stdout + r.stderr
    # a script that starts sys.executable again (as tests often do) reaches Python, not the app's window
    (tmp_path / "inner.py").write_text("print('inner ran')\n", encoding="utf-8")
    (tmp_path / "outer.py").write_text(
        "import subprocess, sys\n"
        "print(subprocess.run([sys.executable, 'inner.py'], capture_output=True, text=True).stdout.strip())\n",
        encoding="utf-8")
    r = _app("--python", "-I", "outer.py", cwd=tmp_path)
    assert r.returncode == 0 and "inner ran" in r.stdout, r.stderr


def test_python_mode_says_what_it_cannot_do():
    r = _app("--python")
    assert r.returncode == 2 and "needs -m module" in r.stderr
    assert _app("--python", "-Z", "x.py").returncode == 2


def test_a_check_command_reaches_the_apps_own_python_when_frozen(monkeypatch):
    assert pyexec.command(["python", "-m", "pytest"]) == [sys.executable, "-m", "pytest"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\DarknessHarness\DarknessHarness.exe")
    exe = r"C:\Apps\DarknessHarness\DarknessHarness.exe"
    assert pyexec.python_command() == [exe, "--python"]
    for spelling in ("python", "python3", "py.exe", "{python}"):
        assert pyexec.command([spelling, "check.py"]) == [exe, "--python", "check.py"]
    assert pyexec.command(["git", "status"]) == ["git", "status"]
    from roundtable.improve import yardstick

    assert yardstick._command(["{python}", "check.py"]) == [exe, "--python", "check.py"]


def test_the_window_is_not_mistaken_for_python(monkeypatch):
    monkeypatch.delenv(pyexec.ENV, raising=False)
    assert not pyexec.wanted([]) and not pyexec.wanted(["notes.py"]) and pyexec.wanted(["--python", "-c", "1"])
    monkeypatch.setenv(pyexec.ENV, "1")
    assert pyexec.wanted(["notes.py"]) and not pyexec.wanted(["--plugin-box"])


def test_the_windows_build_bundles_pytest_and_lists_both_modes():
    spec = (REPO / "packaging" / "roundtable.spec").read_text(encoding="utf-8")
    assert 'collect_submodules("pytest")' in spec and '"pytest"]' not in spec  # no longer excluded
    for mod in ("roundtable.pyexec", "roundtable.plugins.boxworker", "roundtable.plugins.guard",
                "roundtable.plugins.boxapi"):
        assert mod in spec
    app = APP.read_text(encoding="utf-8")
    assert app.index("--plugin-box") < app.index("python_wanted(") < app.index("from roundtable.desktop import")
