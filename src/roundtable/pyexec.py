"""Running Python for the harness's own checks, in the Windows app too.

The Windows app is frozen (PyInstaller): there is no ``python`` beside it, so the yardstick's checks, a drafted
plug-in's tests, the box's trials and self-repair's test suite would have nothing to run. The app's own exe
therefore has a ``--python`` mode that behaves like a small ``python``: ``-m module``, ``-c code`` or a
script, with its arguments (pytest is bundled, so ``--python -m pytest`` works). Not frozen, it is this
Python itself.

``python_command()`` is how to start it; ``command(argv)`` turns a check's ``python ...`` (or ``{python}``)
into that. In ``--python`` mode the marker ``ROUNDTABLE_AS_PYTHON`` is set in the environment, so a script that
starts ``sys.executable some_script.py`` (as tests often do) reaches Python again, not the app's window.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ENV = "ROUNDTABLE_AS_PYTHON"
NAMES = {"python", "python3", "py", "python.exe", "python3.exe", "py.exe", "{python}"}
# the interpreter's own switches that take no value (ignored here: the frozen app has one fixed setup)
_FLAGS = set("IBSsEuqOdvR")


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def python_command() -> list[str]:
    """How to start Python: the app's exe in ``--python`` mode when frozen, else this interpreter."""
    return [sys.executable, "--python"] if frozen() else [sys.executable]


def is_python(name: str) -> bool:
    return Path(str(name)).name.lower() in NAMES or str(name) == sys.executable


def command(argv: list[str]) -> list[str]:
    """``argv`` with a leading ``python`` (any spelling, or ``{python}``) replaced by ``python_command()``."""
    argv = [str(a) for a in argv]
    if argv and is_python(argv[0]):
        return [*python_command(), *argv[1:]]
    return argv


def wanted(argv: list[str]) -> bool:
    """Whether the frozen app was started as Python (``argv`` without the program name)."""
    return argv[:1] == ["--python"] or (os.environ.get(ENV) == "1" and bool(argv) and not argv[0].startswith("--"))


def main(argv: list[str]) -> int:
    """Behave like ``python [switches] (-m module | -c code | script) [args]``; returns the exit code."""
    import runpy

    args = list(argv)
    if args[:1] == ["--python"]:
        args = args[1:]
    os.environ[ENV] = "1"  # a child started as sys.executable runs as Python too
    for name in ("stdout", "stderr"):  # a windowed exe started without pipes has none
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115
    while args and args[0].startswith("-") and args[0] not in ("-m", "-c", "-"):
        flag = args.pop(0)
        if flag in ("-X", "-W") and args:
            args.pop(0)  # its value
        elif not set(flag[1:]) <= _FLAGS:
            print(f"--python: {flag} isn't supported here", file=sys.stderr)
            return 2
    if not args or args[0] == "-":
        print("--python needs -m module, -c code or a script (there is no interactive Python here)", file=sys.stderr)
        return 2
    try:
        if args[0] == "-m" and len(args) > 1:
            sys.argv = [args[1], *args[2:]]
            sys.path.insert(0, os.getcwd())
            runpy.run_module(args[1], run_name="__main__", alter_sys=True)
        elif args[0] == "-c" and len(args) > 1:
            sys.argv = ["-c", *args[2:]]
            sys.path.insert(0, "")
            exec(compile(args[1], "<string>", "exec"), {"__name__": "__main__"})  # noqa: S102
        else:
            script = Path(args[0])
            sys.argv = [str(script), *args[1:]]
            sys.path.insert(0, str(script.resolve().parent))
            runpy.run_path(str(script), run_name="__main__")
    except SystemExit as e:
        code = e.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        print(code, file=sys.stderr)
        return 1
    return 0
