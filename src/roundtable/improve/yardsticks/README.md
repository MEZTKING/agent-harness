# The yardstick

Small made-up tasks a learned change is tried on (`improve/yardstick.py`). Nothing here comes from the
owner's projects. One folder per task: `<job>/<id>/task.yaml`, with

- `files/` – the project at the start (builders and planners) or before the change (the reviewer),
- `hidden/` – checks copied in only after the builder has finished, so they can't be edited to pass,
- `change/` – the reviewer's tasks: the files after the change it judges,
- `solution/` – one right answer, used only by `yardstick.check_set()` and the tests.

Python files are kept as `name.py.txt` (the Windows app's data files leave `.py` out) and copied as
`name.py`. In a `run` check, `{python}` is the Python that runs the harness.

Raise a task's `version` whenever it changes: saved results are kept by task and version.
