"""Loading code named as ``module:object`` - shared by plugins and ``type: plugin`` providers.

Trust rule (the same for both): this runs the plugin's own Python code with the app's full
access. Nothing here is a sandbox; the safety is that the owner chose to install it.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any


def load_object(target: str, file_dirs: list[Path] = (), import_paths: list[Path] = (),
                module_alias: str | None = None) -> Any:
    """The object ``target`` ("module_or_file.py:Name", dots allowed in Name) names.

    ``file_dirs``: folders where ``module.py`` is looked for as a file first (loaded under
    ``module_alias``). ``import_paths``: folders added to the end of ``sys.path`` (so the
    app's own packages always win) before importing the module the usual way.
    """
    if ":" not in target:
        raise ValueError(f"{target!r} must be 'module:object'")
    modname, objname = target.rsplit(":", 1)
    module = None
    for d in file_dirs:
        candidate = d / modname if modname.endswith(".py") else d / f"{modname}.py"
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(module_alias or f"roundtable_plugin_{candidate.stem}",
                                                          candidate)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            break
    if module is None:
        for p in import_paths:
            if p.is_dir() and str(p) not in sys.path:
                sys.path.append(str(p))
        module = importlib.import_module(modname.removesuffix(".py"))
    obj = module
    for part in objname.split("."):
        obj = getattr(obj, part)
    return obj
