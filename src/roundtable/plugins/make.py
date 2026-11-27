"""Make a plugin from one sentence (wave 7, d4-tools).

``draft(cfg, idea, budget, on_event)``: a builder model works in a fresh folder seeded with a template (a
manifest asking for nothing, one ``Tool`` and one test file); the plugin's own tests then run inside the box
(``sandbox.trial``); and static checks refuse anything that asks for a permission, holds compiled files, is bigger
than 10 files or 50 KB, names a tool like one of the workspace's, or holds text the charter would scrub (a path,
a key-like string). The result::

    {folder, id, name, files: [{path, text}], tools, tests_passed, test_output, problems, cost_usd, model,
     words, offered}

``offered`` is True only when the tests passed and there were no problems; only then does the app show "Add it"
(``manage.add_plugin(folder, confirm)``). Who pays: the owner's tap shows ``estimate`` first and passes its own
Budget; the lab's "tool" proposals (improve/toolkind.py) pass a Budget from the learning allowance.
"""

from __future__ import annotations

import ast
import re
import shutil
import textwrap
from pathlib import Path
from typing import Any, Callable

from ..core.models import utcnow
from ..harness.agent import Budget, BudgetExceeded, run_agent
from ..harness.config import ModelRef, section
from ..harness.tools import Tool, Toolbox, ToolSpec, Workspace, _obj
from ..providers.base import Usage
from .api import PluginError
from .manifest import MANIFEST_FILE, find_manifest

MAX_FILES = 10
MAX_BYTES = 50 * 1024
COMPILED = {".so", ".pyd", ".dll", ".dylib", ".pyc", ".pyo", ".exe", ".bin", ".class", ".jar", ".whl", ".o",
            ".a", ".lib", ".egg", ".zip"}
CACHES = {"__pycache__", ".pytest_cache"}
# the standard library's unittest: the box holds the standard library and the plug-in's own code only (no pytest),
# frozen or not, so this is what runs there
TEST_COMMAND = ["python", "-m", "unittest", "discover", "-s", "tests"]
# Tools every builder already has (the workspace's, the loop's own, the web's): a plugin tool never takes their names.
RESERVED_TOOLS = {"read_file", "write_file", "edit_file", "list_files", "search", "run_command", "finish_task",
                  "expand_output", "web_search", "web_read", "fetch_url", "clone_repo", "submit_plan",
                  "submit_review", "submit_critique", "submit_proposals", "submit_fixes", "submit_brief",
                  "submit_looks", "submit_proof", "submit_reference", "pick_best", "play_input", "report_play",
                  "recall", "remember"}
EST_USAGE = Usage(input_tokens=60_000, output_tokens=8_000)  # about a dozen turns writing three small files
MAX_STEPS = 20

Emit = Callable[[str, dict[str, Any]], None]


# -- names and the template -----------------------------------------------------------------------------------
def plugin_id(idea: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", str(idea).lower()) if w not in {"a", "an", "the", "that", "to",
                                                                                 "for", "of", "and", "which"}]
    pid = "-".join(words[:4])[:32].strip("-") or "my-tool"
    if not pid[0].isalpha():
        pid = f"tool-{pid}"[:32].strip("-")
    return pid if len(pid) >= 2 else "my-tool"


def module_name(pid: str) -> str:
    return "rt_" + pid.replace("-", "_")


def drafts_home() -> Path:
    from ..desktop import app_home

    return app_home() / "plugin-drafts"


def seed(folder: Path, pid: str, idea: str) -> None:
    """The template: a manifest with no permissions, one tool, one test."""
    mod = module_name(pid)
    tool = pid.replace("-", "_")[:40]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "tests").mkdir(exist_ok=True)
    name = " ".join(w.capitalize() for w in pid.split("-"))
    blurb = " ".join(str(idea).split())[:200].replace('"', "'").replace("\\", "/")
    (folder / MANIFEST_FILE).write_text(textwrap.dedent(f"""\
        id = "{pid}"
        name = "{name}"
        version = "0.1.0"
        description = "{blurb}"
        author = "Made in the app"
        licence = "MIT"
        entry = "{mod}:plugin"
        api = 1
        hooks = ["tools"]
        permissions = []
        """), encoding="utf-8")
    (folder / f"{mod}.py").write_text(textwrap.dedent(f'''\
        """{name}: {blurb}"""

        from roundtable.plugins.api import Plugin, Tool, ToolSpec, _obj


        def run(args):
            """What the tool does: takes the model's arguments, returns text."""
            return str(args.get("text", ""))


        class {name.replace(" ", "")}Plugin(Plugin):
            def tools(self, ctx):
                return [Tool(ToolSpec("{tool}", "Say what this tool does, in one line.",
                                      _obj({{"text": {{"type": "string"}}}}, ["text"])), run)]


        plugin = {name.replace(" ", "")}Plugin()
        '''), encoding="utf-8")
    (folder / "tests" / f"test_{mod}.py").write_text(textwrap.dedent(f"""\
        import sys
        import unittest
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

        import {mod}


        class TheTool(unittest.TestCase):
            def test_the_tool_answers(self):
                self.assertEqual({mod}.run({{"text": "hi"}}), "hi")
        """), encoding="utf-8")


# -- checks -----------------------------------------------------------------------------------------------------
def _files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file() and not (set(p.relative_to(folder).parts) & CACHES))


def tool_names(folder: Path) -> list[str]:
    """The tool names the plugin's code gives (``ToolSpec("name", ...)``), read without running it."""
    out: list[str] = []
    for f in _files(folder):
        if f.suffix != ".py" or "tests" in f.relative_to(folder).parts:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
                if name == "ToolSpec" and node.args and isinstance(node.args[0], ast.Constant) \
                        and isinstance(node.args[0].value, str) and node.args[0].value not in out:
                    out.append(node.args[0].value)
    return out


def check(folder: Path, lab: Any = None) -> list[str]:
    """Plain-words problems that stop a made plugin being offered; [] when it may be."""
    from ..improve import charter

    folder = Path(folder)
    probs: list[str] = []
    try:
        manifest = find_manifest(folder)
    except PluginError as e:
        return [f"Its manifest couldn't be read: {e}"]
    if manifest.permissions:
        probs.append(f"It asks for permissions ({', '.join(manifest.permissions)}); a made plugin may ask for none.")
    files = _files(folder)
    for f in files:
        rel = f.relative_to(folder).as_posix()
        if f.suffix.lower() in COMPILED:
            probs.append(f"{rel} is a compiled or packed file; a made plugin holds only text you can read.")
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            probs.append(f"{rel} isn't plain text; a made plugin holds only text you can read.")
            continue
        if "\x00" in text:
            probs.append(f"{rel} isn't plain text; a made plugin holds only text you can read.")
            continue
        if charter.scrub(text, lab) != text:
            probs.append(f"{rel} holds a path, a project name or something like a key; take it out.")
    if len(files) > MAX_FILES:
        probs.append(f"It has {len(files)} files; a made plugin may have up to {MAX_FILES}.")
    size = sum(f.stat().st_size for f in files)
    if size > MAX_BYTES:
        probs.append(f"It is {size // 1024} KB; a made plugin may be up to {MAX_BYTES // 1024} KB.")
    names = tool_names(folder)
    if not names:
        probs.append("It gives no tool (no ToolSpec with a name was found).")
    clash = sorted(n for n in names if n in RESERVED_TOOLS)
    if clash:
        probs.append(f"Its tool {', '.join(clash)} has the name of a tool the builders already have; rename it.")
    if not any(f.relative_to(folder).parts[0] == "tests" for f in files if len(f.relative_to(folder).parts) > 1):
        probs.append("It has no tests.")
    return probs


def _prune(folder: Path) -> None:
    for d in list(folder.rglob("*")):
        if d.is_dir() and d.name in CACHES:
            shutil.rmtree(d, ignore_errors=True)


# -- the builder -----------------------------------------------------------------------------------------------
def builder(cfg: Any) -> tuple[str, ModelRef]:
    """The role and model that writes plugins: ``market.builder_role``, else the coder, else the planner."""
    want = section(cfg, "market").get("builder_role")
    for name in (want, "coder", "worker", getattr(cfg, "planner_role", None)):
        role = cfg.roles.get(name) if name else None
        if role and role.kind == "chat" and role.models:
            return name, role.models[0]
    for name, role in cfg.roles.items():
        if role.kind == "chat" and role.models:
            return name, role.models[0]
    raise PluginError("There's no model set up to write code. Add one in Models, then try again.")


def estimate(cfg: Any) -> dict[str, Any]:
    """What making one plugin should cost, shown before the owner taps Make it."""
    role, ref = builder(cfg)
    usd = cfg.cost(ref, EST_USAGE)
    words = (f"About ${usd:.2f}, paid from your credit with {ref.model}." if usd is not None
             else f"{ref.model} has no price set, so the cost can't be shown first.")
    return {"usd": None if usd is None else round(usd, 4), "role": role, "model": str(ref), "words": words}


SYSTEM = """You write small plugins for an AI build harness. A plugin gives the builders one or more extra tools.

Rules (a plugin that breaks one is thrown away):
- Change only the files in this folder. At most 10 files, 50 KB in all, plain text only.
- The plugin runs in a box with no internet, no other programs and no files outside its own folder. Write it so it
  needs none of those: plain Python, the standard library only. Never ask for permissions: leave `permissions = []`.
- Keep the manifest (roundtable-plugin.toml) as it is apart from name and description.
- A tool is `Tool(ToolSpec("name", "what it does", _obj({...json schema properties...}, [required])), fn)`; `fn(args)`
  returns text. Give each tool a clear, specific snake_case name that isn't a common one like read_file or search.
- Put the real work in plain functions the tests can call. Write tests in tests/test_*.py with the standard
  library's unittest (unittest.TestCase classes; pytest isn't there) that check the behaviour properly, including an
  edge case. They must pass.
- No file paths of this computer, no keys, no project names in any file.
When it is done, call finish_task with a one-paragraph summary."""


def draft(cfg: Any, idea: str, budget: Budget, on_event: Emit | None = None,
          folder: Path | None = None) -> dict[str, Any]:
    """Make a plugin for ``idea`` (see the module's docstring). Never installs anything."""
    from . import sandbox

    idea = " ".join(str(idea or "").split())
    if len(idea) < 8:
        raise PluginError("Say in a sentence what the tool should do.")
    emit = on_event or (lambda *_: None)
    role, ref = builder(cfg)
    pid = plugin_id(idea)
    folder = Path(folder) if folder else drafts_home() / f"{pid}-{utcnow().replace(':', '').replace('-', '')[:15]}"
    if folder.exists() and any(folder.iterdir()):
        raise PluginError("That folder isn't empty; a plugin is made in an empty one.")
    seed(folder, pid, idea)
    ws = Workspace(folder, allow_shell=False)
    box: Toolbox = ws.toolbox(["read_file", "write_file", "edit_file", "list_files"])
    box.add(Tool(ToolSpec("finish_task", "Call when the plugin and its tests are written.",
                          _obj({"summary": {"type": "string"}}, ["summary"])), lambda a: "ok", terminal=True))
    emit("make_plugin", {"step": "writing", "id": pid, "model": str(ref)})
    spent0 = budget.spent_usd
    summary, cost = "", 0.0
    try:
        res = run_agent(cfg, ref, SYSTEM,
                        f"Make a plugin that does this:\n\n{idea}\n\nThe folder already holds a template: read it "
                        "first, then change it.", box, budget, max_steps=MAX_STEPS, max_tokens=8000,
                        require_terminal="finish_task", on_event=on_event, role=role)
        summary = str((box.captured.get("finish_task") or {}).get("summary") or res.text or "")[:1000]
    except BudgetExceeded:
        raise
    finally:
        cost = round(budget.spent_usd - spent0, 6)
    problems = check(folder)
    tests_passed, output = False, ""
    if not problems:
        emit("make_plugin", {"step": "testing", "id": pid})
        trial = sandbox.trial(folder, list(TEST_COMMAND), timeout=float(section(cfg, "market").get("test_seconds", 60)))
        tests_passed, output = bool(trial.get("ok")), str(trial.get("output") or "")[-4000:]
        _prune(folder)
        problems = check(folder)  # the tests must not have left anything behind that isn't allowed
    try:
        name = find_manifest(folder).name
    except PluginError:
        name = pid
    offered = tests_passed and not problems
    if offered:
        words = f"{name} is ready: its tests passed in the box. Read it under More, then Add it."
    elif problems:
        words = f"{name} can't be offered: " + " ".join(problems[:3])
    else:
        words = f"{name} can't be offered: its tests didn't pass in the box."
    out = {"folder": str(folder), "id": pid, "name": name, "idea": idea, "summary": summary,
           "files": [{"path": f.relative_to(folder).as_posix(), "text": f.read_text(encoding="utf-8", errors="replace")}
                     for f in _files(folder)][:MAX_FILES + 2],
           "tools": tool_names(folder), "tests_passed": tests_passed, "test_output": output, "problems": problems,
           "cost_usd": cost, "model": str(ref), "words": words, "offered": offered}
    emit("make_plugin", {"step": "done", "id": pid, "offered": offered, "cost_usd": cost})
    return out


def is_draft(folder: str | Path) -> bool:
    """Whether ``folder`` is one this module made (the only folders "Add it" accepts)."""
    try:
        p, home = Path(folder).resolve(), drafts_home().resolve()
    except OSError:
        return False
    return home in p.parents and p.is_dir()
