"""One project's own settings: ``.harness/project.yaml``, over the repository's ``roundtable.yaml``.

``roundtable.yaml`` at the project's top folder can be committed with the app (defaults for everyone
who runs Roundtable on it); ``.harness/project.yaml`` is this computer's own and wins key by key.
Keys this version doesn't know are kept in their file and warned about, never dropped.

Read and written by ``roundtable settings`` / ``roundtable set``, the desktop app's Settings section
and the phone (``GET``/``POST /api/project/settings``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROJECT_FILE = ".harness/project.yaml"
REPO_FILE = "roundtable.yaml"
DEFAULT_RULES_FILES = ["CLAUDE.md", ".claude/CLAUDE.md", "AGENTS.md", "HANDOFF.md", "DEVLOG.md"]
LIMIT_KEYS = {"max_real_usd_per_run": float, "max_cost_usd": float, "max_attempts_per_task": int,
              "max_steps_per_task": int}
SWITCH = ["auto", "on", "off"]


@dataclass(frozen=True)
class Setting:
    key: str
    type: str  # text, lines, map, int, number-map, choice
    default: Any
    description: str
    choices: tuple[str, ...] = ()
    example: str = ""


SETTINGS: tuple[Setting, ...] = (
    Setting("test", "text", "", "The command that checks the app (e.g. python -m pytest tests -q). A task that makes a "
            "test fail that passed before is sent back.", example="python -m pytest tests -q"),
    Setting("env", "map", {}, "Settings for that command, such as QT_QPA_PLATFORM: offscreen. Never keys or passwords.",
            example="QT_QPA_PLATFORM: offscreen"),
    Setting("setup", "text", "", "A command run once before the first task, e.g. pip install -e .[dev].",
            example="pip install -e .[dev]"),
    Setting("timeout", "int", 900, "How many seconds the test or setup command may take."),
    Setting("branch", "text", "roundtable/", "Where the harness's work goes in an existing app. Ending in / means that "
            "start plus a name from the goal; anything else is the exact branch. Never main or master."),
    Setting("rules_files", "lines", list(DEFAULT_RULES_FILES), "The files that hold the app's own rules, which every "
            "model follows. For a devlog or handoff only the newest entry is read."),
    Setting("rules_budget", "int", 12000, "At most this many characters of those rules go to the models (headings "
            "are always kept)."),
    Setting("providers_allowed", "lines", [], "Only these AI providers may see this project (e.g. deepseek). Empty: "
            "any. A role whose models are all from other providers stops the run with a message.", example="[deepseek]"),
    Setting("makers_allowed", "lines", [], "Only models made by these companies may see this project (e.g. anthropic, "
            "openai, deepseek), whichever service they come through. Empty: any.", example="[anthropic, deepseek]"),
    Setting("agent_memory", "choice", "", "Let your named agents use and add to what they learned on other projects. "
            "Empty: yes, except for projects kept to some services or makers and your own repositories. on: always. "
            "off: never.", ("", "on", "off")),
    Setting("profile", "choice", "", "Which set of models builds it (e.g. Budget, Balanced, Quality). Empty: the "
            "app's own choice."),
    Setting("checking", "choice", "", "How much extra checking this project gets: lean, balanced or maximum. Empty: "
            "the app's choice.", ("", "lean", "balanced", "maximum")),
    Setting("limits", "number-map", {}, "Money and effort limits for this project only: max_real_usd_per_run, "
            "max_cost_usd, max_attempts_per_task, max_steps_per_task.", example="max_real_usd_per_run: 2"),
    Setting("look", "choice", "auto", "Offer looks to choose from before building. auto: only for new apps with screens, "
            "or a web app.", tuple(SWITCH)),
    Setting("show_it", "choice", "auto", "Take pictures of the app's screens after each task. auto: when it has "
            "screens the harness can open.", tuple(SWITCH)),
    Setting("stage_stop", "choice", "off", "Stop after each stage so you can try it before the next one starts. off: "
            "keep going (it still notes when each stage is ready).", ("off", "each")),
    Setting("ask_first", "choice", "", "Before a builder runs a command: off (run it), risky (ask only for risky ones) or all (ask every time). Empty: this computer's choice.", ("", "off", "risky", "all")),
    Setting("web_search", "choice", "", "Let the builders look things up on the web (their search words go to a search "
            "service). Empty: this computer's choice; a project kept to some providers gets none unless this says on.",
            ("", "on", "off")),
    Setting("documents", "choice", "all", "Which of your documents this project's agents may look up: all, or none.",
            ("all", "none")),
    Setting("notes", "text", "", "Anything the planner should know about this project, in your own words."),
)
BY_KEY = {s.key: s for s in SETTINGS}


@dataclass
class ProjectSettings:
    values: dict[str, Any]
    sources: dict[str, str]  # key -> "default", "roundtable.yaml" or ".harness/project.yaml"
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def __getattr__(self, key: str) -> Any:
        try:
            return self.__dict__["values"][key]
        except KeyError:
            raise AttributeError(key) from None


# -- checking one value ----------------------------------------------------------------------------
def coerce(key: str, value: Any, where: str = "", profiles: list[str] | None = None) -> Any:
    """``value`` checked and in its proper shape for ``key``; ValueError in plain words when it's wrong.
    Strings are accepted for every type (the command line and simple forms send text)."""
    s = BY_KEY.get(key)
    at = f"{where}: " if where else ""
    if not s:
        raise ValueError(f"{at}there's no setting called {key!r}; the settings are {', '.join(BY_KEY)}")
    if value is None:
        return _copy(s.default)
    if s.type == "text":
        if isinstance(value, (dict, list)):
            raise ValueError(f"{at}{key} should be one line of text")
        return str(value).strip()
    if s.type == "int":
        try:
            n = int(str(value).strip() or s.default)
        except ValueError:
            raise ValueError(f"{at}{key} should be a whole number, like {s.default}") from None
        if n < 1:
            raise ValueError(f"{at}{key} should be at least 1")
        return n
    if s.type == "lines":
        if isinstance(value, str):
            value = [x for x in re.split(r"[,\n]", value.strip().strip("[]"))]
        if not isinstance(value, list):
            raise ValueError(f"{at}{key} should be a list, like [a, b]")
        out = []
        for x in value:
            x = str(x).strip().strip("'\"")
            if x and x not in out:
                out.append(x)
        return out
    if s.type in ("map", "number-map"):
        if isinstance(value, str):
            pairs = [p for p in re.split(r"[,\n]", value) if p.strip()]
            value = {}
            for p in pairs:
                name, sep, val = p.partition("=") if "=" in p else p.partition(":")
                if not sep:
                    raise ValueError(f"{at}write {key} as NAME=VALUE, e.g. {s.example or 'NAME=value'}")
                value[name.strip()] = val.strip()
        if not isinstance(value, dict):
            raise ValueError(f"{at}{key} should be pairs like {s.example or 'NAME: value'}")
        out_map: dict[str, Any] = {}
        for k, v in value.items():
            k = str(k).strip()
            if s.type == "map":
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
                    raise ValueError(f"{at}{k!r} can't be a variable name in {key} (letters, digits and _ only)")
                out_map[k] = "" if v is None else str(v).lower() if isinstance(v, bool) else str(v)
            else:
                kind = LIMIT_KEYS.get(k)
                if not kind:
                    raise ValueError(f"{at}{k!r} isn't a limit; use {', '.join(LIMIT_KEYS)}")
                try:
                    num = kind(v)
                except (TypeError, ValueError):
                    raise ValueError(f"{at}limits {k} should be a number") from None
                if num < 0:
                    raise ValueError(f"{at}limits {k} can't be below 0")
                out_map[k] = num
        return out_map
    if s.type == "choice":
        text = str(value).strip()
        choices = list(s.choices) or list(profiles or [])
        if key == "profile":
            if not text:
                return ""
            match = next((c for c in choices if c.lower() == text.lower()), None)
            if profiles is not None and not match:
                raise ValueError(f"{at}there's no profile {text!r}; choose "
                                 + (", ".join(choices) if choices else "none: no profiles are set up in harness.yaml"))
            return match or text
        if isinstance(value, bool):  # YAML reads on/off as true/false
            text = "on" if value else "off"
        text = text.lower()
        if text not in choices:
            raise ValueError(f"{at}{key} should be one of {', '.join(choices)}")
        return text
    raise ValueError(f"{at}{key}: unknown type")  # pragma: no cover


def _copy(v: Any) -> Any:
    return list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v


# -- reading ------------------------------------------------------------------------------------------
def _read_raw(p: Path) -> tuple[dict[str, Any], str | None]:
    if not p.is_file():
        return {}, None
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return {}, f"{p.name} can't be read ({str(e).splitlines()[0]}): fix the file or delete it"
    if raw is None:
        return {}, None
    if not isinstance(raw, dict):
        return {}, f"{p.name} should be a list of settings like `test: python -m pytest`"
    return raw, None


def load(root: str | Path, profiles: list[str] | None = None) -> ProjectSettings:
    """The merged settings: defaults, then roundtable.yaml, then .harness/project.yaml (key by key).
    Problems don't raise: a wrong value is left at the one below it and listed in ``errors``."""
    root = Path(root)
    values = {s.key: _copy(s.default) for s in SETTINGS}
    sources = {s.key: "default" for s in SETTINGS}
    warnings: list[str] = []
    errors: list[str] = []
    for name in (REPO_FILE, PROJECT_FILE):
        raw, err = _read_raw(root / name)
        if err:
            errors.append(err)
        for key, value in raw.items():
            if key not in BY_KEY:
                warnings.append(f"{name}: the harness doesn't know the setting {key!r} (kept as it is)")
                continue
            try:
                values[key] = coerce(key, value, name, profiles)
                sources[key] = name
            except ValueError as e:
                errors.append(str(e))
    return ProjectSettings(values, sources, warnings, errors)


def view(root: str | Path, profiles: list[str] | None = None) -> dict[str, Any]:
    """For the apps: every setting with its value, where it came from, what it does, its type and choices."""
    st = load(root, profiles)
    items = []
    for s in SETTINGS:
        choices = list(s.choices) if s.choices else ([""] + list(profiles or []) if s.key == "profile" else [])
        items.append({"key": s.key, "value": st.values[s.key], "source": st.sources[s.key], "default": s.default,
                      "description": s.description, "type": s.type, "choices": choices,
                      **({"keys": list(LIMIT_KEYS)} if s.key == "limits" else {})})
    return {"settings": items, "warnings": st.warnings, "errors": st.errors,
            "files": {"project": str(Path(root) / PROJECT_FILE), "repository": str(Path(root) / REPO_FILE)},
            "order": f"{PROJECT_FILE} wins over {REPO_FILE}, which wins over the defaults"}


# -- writing --------------------------------------------------------------------------------------------
HEADER = """\
# This project's own settings for Darkness Harness. Change them here, with
#   roundtable set DIR KEY VALUE
# or in the desktop app (the project's Settings). This file wins over roundtable.yaml in the
# project's top folder (settings you can commit with the app), key by key.
# A line starting with # is a note; remove the # in front of a setting to use it.
"""


def render(raw: dict[str, Any]) -> str:
    """A clean, commented project.yaml: every setting explained, the ones in use filled in."""
    out = [HEADER]
    for s in SETTINGS:
        out.append(f"\n# {s.description}")
        if s.key in raw:
            out.append(yaml.safe_dump({s.key: raw[s.key]}, sort_keys=False, allow_unicode=True,
                                      default_flow_style=False, width=1000).rstrip())
        else:
            ex = s.example or (yaml.safe_dump(s.default, default_flow_style=True).strip().removesuffix("...").strip()
                               if s.default not in ("", {}, []) else "")
            if s.type in ("map", "number-map") and s.example:
                out.append(f"# {s.key}:\n#   {s.example}")
            else:
                out.append(f"# {s.key}: {ex}".rstrip())
    extra = {k: v for k, v in raw.items() if k not in BY_KEY}
    if extra:
        out.append("\n# Not known to this version of the harness (kept as they are):")
        out.append(yaml.safe_dump(extra, sort_keys=False, allow_unicode=True, default_flow_style=False).rstrip())
    return "\n".join(out) + "\n"


def ensure(root: str | Path) -> Path:
    """Write the explained project.yaml when there's none yet (nothing set: everything as its default)."""
    p = Path(root) / PROJECT_FILE
    if not p.is_file():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(render({}), encoding="utf-8")
    return p


def update(root: str | Path, changes: dict[str, Any], profiles: list[str] | None = None) -> dict[str, Any]:
    """Change settings in .harness/project.yaml. A value of None (or "" for text) removes it from the file, so
    roundtable.yaml or the default applies again. Every value is checked first: nothing is written if one is wrong."""
    root = Path(root)
    p = root / PROJECT_FILE
    raw, err = _read_raw(p)
    if err:
        raise ValueError(err)
    problems, new = [], dict(raw)
    for key, value in (changes or {}).items():
        try:
            if value is None or (isinstance(value, str) and not value.strip()):
                coerce(key, None)  # still says so when the key doesn't exist
                new.pop(key, None)
                continue
            new[key] = coerce(key, value, "", profiles)
        except ValueError as e:
            problems.append(str(e))
    if problems:
        raise ValueError("; ".join(problems))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render(new), encoding="utf-8")
    return view(root, profiles)


def set_from_text(root: str | Path, key: str, text: str, profiles: list[str] | None = None) -> dict[str, Any]:
    """``roundtable set DIR KEY VALUE``. For env and limits, NAME=VALUE adds or changes one entry and NAME=
    removes it; for lists, a comma-separated list; an empty value removes the setting from project.yaml."""
    s = BY_KEY.get(key)
    if not s:
        raise ValueError(f"there's no setting called {key!r}; the settings are {', '.join(BY_KEY)}")
    text = (text or "").strip()
    if s.type in ("map", "number-map") and text:
        current = dict(load(root, profiles).values[key])
        for part in [x for x in re.split(r"[,\n]", text) if x.strip()]:
            name, sep, val = part.partition("=")
            if not sep:
                raise ValueError(f"write {key} as NAME=VALUE, e.g. {(s.example or 'NAME: value').replace(': ', '=')}")
            if val.strip():
                current[name.strip()] = val.strip()
            else:
                current.pop(name.strip(), None)
        return update(root, {key: current}, profiles)
    return update(root, {key: text if text else None}, profiles)
