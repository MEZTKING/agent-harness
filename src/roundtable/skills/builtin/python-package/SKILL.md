---
name: Small Python packages
when: Making or tidying a small Python package or command-line tool.
tags: [python, build, refactor]
---
- Layout: `pyproject.toml`, `src/<name>/__init__.py`, `src/<name>/...`, `tests/`. The `src/` folder stops tests importing the wrong copy.
- `pyproject.toml` holds the name, version, `requires-python`, dependencies and, for a command, `[project.scripts] name = "pkg.cli:main"`.
- Keep dependencies few; prefer the standard library (`pathlib`, `json`, `argparse`, `dataclasses`, `logging`).
- `main(argv=None) -> int` that parses its own arguments makes the command easy to test; `raise SystemExit(main())` at the bottom.
- Errors the user can fix get a plain message and a non-zero exit code, not a stack trace.
- Read and write text files with `encoding="utf-8"` every time.
- Type hints on public functions; a one-line docstring saying what it returns.
- Data files the package needs go under the package folder and are read with `importlib.resources`.
- Check it installs: `pip install -e .` then run the command once.
