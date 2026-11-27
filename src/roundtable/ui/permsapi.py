"""What each job may do (harness/perms.py) and the builders' own settings, as an API for the desktop. Stays on
the PC: the phone may only read ``GET /api/perms`` (a preset is changed on the PC).

    GET  /api/perms            ?path=<project>? -> {presets: [{id, title, words}], default, jobs: [{job, preset,
                                title, source, computer, project}], box: {can, words}, allowed: {mcp, hosts,
                                paths, tools}?, project?}
    POST /api/perms            {job?, preset, path?, sure?} -> the same as GET. Without ``path`` it is this
                                computer's choice (custom.yaml ``perms``: ``default``, or ``roles[job]``); with
                                ``path`` the project's own (``perms`` in ``.harness/project.yaml``). ``preset: ""``
                                takes the choice away. Free needs ``sure: true`` (else {needs_sure, words}, nothing
                                saved).
    POST /api/perms/forget     {path, kind, value} -> GET (one "Always allow" taken back)
    GET  /api/builders         -> {values: {...}, fields: [{key, label, tip, kind, min, max, more}], not_applied}
    POST /api/builders         {key: value, ...} -> the same as GET (custom.yaml; harness.yaml is never rewritten)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..harness import perms

FREE_SURE = ("Free means nothing waits for you: every command and every change runs straight away, risky ones too. "
             "Are you sure?")


def routes(app) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/api/perms"): lambda q: view(app, q or {}),
        ("POST", "/api/perms"): lambda body: save(app, body or {}),
        ("POST", "/api/perms/forget"): lambda body: forget(app, body or {}),
        ("GET", "/api/builders"): lambda q: builders_view(app),
        ("POST", "/api/builders"): lambda body: builders_save(app, body or {}),
    }


def _error(text: str, status: int = 400):
    from .server import ApiError

    return ApiError(text, status)


def _first(q: dict, key: str, default: str = "") -> str:
    v = (q or {}).get(key, default)
    if isinstance(v, list):
        v = v[0] if v else default
    return str(v if v is not None else default)


def _cfg(app):
    try:
        return app.cfg()
    except Exception:  # noqa: BLE001
        return None


def _harness_path(app) -> Path | None:
    cfg = _cfg(app)
    p = getattr(cfg, "path", None) or getattr(app, "harness_config_path", None)
    return Path(p) if p else None


def _root(app, path: str) -> Path | None:
    if not path:
        return None
    cfg = _cfg(app)
    if not cfg:
        raise _error("The harness isn't set up on this computer yet. Finish the set-up in Settings first.", 503)
    return app.project(cfg, path).root  # only registered projects (404 otherwise)


def _jobs(cfg) -> list[str]:
    roles = list(getattr(cfg, "roles", {}) or {}) if cfg is not None else []
    return roles


# -- what each job may do ---------------------------------------------------------------------------------------
def view(app, q: dict) -> dict[str, Any]:
    cfg = _cfg(app)
    root = _root(app, _first(q, "path"))
    mine = perms.computer_choices(cfg)
    project_table = _project_table(root) if root else {}
    jobs = []
    for job in _jobs(cfg):
        got = perms.explain(root or Path("."), cfg, job) if root else _computer_only(cfg, job)
        jobs.append({"job": job, "preset": got["preset"], "title": perms.TITLES[got["preset"]],
                     "source": got["source"], "computer": perms.norm_preset((mine.get("roles") or {}).get(job)) or "",
                     "project": perms.norm_preset(project_table.get(job)) or ""})
    layer = perms._box_layer()
    import os

    box_words = ("There's no box on Windows: a command you allow runs with this computer's full reach." if os.name == "nt"
                 else "Under Careful and Ask every time, a task that doesn't need the internet runs its commands "
                      "with the internet off." if layer
                 else "There's no box on this computer (bwrap isn't installed): commands can use the internet.")
    out: dict[str, Any] = {
        "presets": [{"id": p, "title": perms.TITLES[p], "words": perms.WORDS[p]} for p in perms.PRESETS],
        "default": perms.norm_preset(mine.get("default")) or "", "jobs": jobs,
        "box": {"can": bool(layer), "words": box_words}, "free_sure": FREE_SURE,
    }
    if root:
        out["project"] = str(root)
        out["allowed"] = perms.allowed(root)
    return out


def _computer_only(cfg, job: str) -> dict[str, str]:
    """The preset a job gets on this computer when its project says nothing."""
    import tempfile

    with tempfile.TemporaryDirectory() as empty:  # a made-up, empty project: only this computer decides
        return perms.explain(Path(empty), cfg, job)


def _project_table(root: Path) -> dict[str, Any]:
    from ..harness import projectsettings as ps

    try:
        raw, _ = ps._read_raw(root / ps.PROJECT_FILE)
    except Exception:  # noqa: BLE001
        return {}
    t = raw.get("perms")
    return t if isinstance(t, dict) else {}


def save(app, body: dict[str, Any]) -> dict[str, Any]:
    job = str(body.get("job") or "").strip()
    raw = body.get("preset")
    preset = "" if raw in (None, "") else perms.norm_preset(raw)
    if preset is None:
        raise _error(f"Nothing was changed: “{raw}” isn't one of Ask every time, Careful, Free or Read only.")
    cfg = _cfg(app)
    if job and job not in _jobs(cfg):
        raise _error(f"Nothing was changed: there's no job called “{job}”. Choose one from Who does what.")
    if preset == "free" and body.get("sure") is not True:
        return {"needs_sure": True, "words": FREE_SURE}
    path = str(body.get("path") or "")
    if path:
        if not job:
            raise _error("Choose a job first: a project's own choice is made for one job at a time.")
        root = _root(app, path)
        _save_project(root, job, preset)
        return view(app, {"path": path})
    hp = _harness_path(app)
    if not hp or not hp.is_file():
        raise _error("The harness's settings aren't set up on this computer yet. Run the set-up in Settings first.",
                     503)
    from ..harness.config import load_custom, save_custom

    custom = load_custom(hp)
    mine = dict(custom.get("perms") or {}) if isinstance(custom.get("perms"), dict) else {}
    if job:
        roles = dict(mine.get("roles") or {})
        if preset:
            roles[job] = preset
        else:
            roles.pop(job, None)
        mine["roles"] = roles
    elif preset:
        mine["default"] = preset
    else:
        mine.pop("default", None)
    custom["perms"] = mine
    save_custom(hp, custom)
    return view(app, {})


def _save_project(root: Path, job: str, preset: str) -> None:
    """The project's own choice for one job, in ``.harness/project.yaml`` (the project-settings file)."""
    import yaml

    from ..harness import projectsettings as ps

    p = root / ps.PROJECT_FILE
    raw, _ = ps._read_raw(p)
    table = dict(raw.get("perms") or {}) if isinstance(raw.get("perms"), dict) else {}
    if preset:
        table[job] = preset
    else:
        table.pop(job, None)
    if table:
        raw["perms"] = table
    else:
        raw.pop("perms", None)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")


def forget(app, body: dict[str, Any]) -> dict[str, Any]:
    path = str(body.get("path") or "")
    root = _root(app, path)
    if root is None:
        raise _error("Choose a project first.")
    kind, value = str(body.get("kind") or ""), str(body.get("value") or "")
    if kind not in perms.KINDS:
        raise _error("Nothing was changed: that isn't something “Always allow” keeps.")
    perms.forget(root, kind, value)
    return view(app, {"path": path})


# -- the builders' own settings (existing config keys, kept in custom.yaml) ---------------------------------------
FIELDS: tuple[dict[str, Any], ...] = (
    {"key": "max_parallel", "label": "Tasks at once", "kind": "number", "min": 1, "max": 8, "more": False,
     "tip": "How many tasks may be built at the same time, each in its own copy of the project."},
    {"key": "max_steps_per_task", "label": "Steps per task", "kind": "number", "min": 5, "max": 400, "more": True,
     "tip": "How many steps (a read, an edit, a command) one try at a task may take before it stops."},
    {"key": "web_search", "label": "Web search", "kind": "switch", "more": False,
     "tip": "Builders may search the web and read pages (web_search, web_read)."},
    {"key": "commands", "label": "Commands", "kind": "switch", "more": False,
     "tip": "Builders may run commands (tests, builds). Off: they can only read and write files."},
    {"key": "compaction", "label": "Sum up long tasks", "kind": "switch", "more": True,
     "tip": "When a task's conversation gets very big, a cheap model sums up the older steps."},
    {"key": "compaction_at_tokens", "label": "Sum up at (tokens)", "kind": "number", "min": 10000, "max": 2000000,
     "more": True, "tip": "How long a conversation gets before it's summed up."},
    {"key": "breaker_repeats", "label": "Stop after the same step", "kind": "number", "min": 0, "max": 100,
     "more": True, "tip": "The safety check stops a task that repeats the same step this many times (0: never)."},
    {"key": "breaker_errors", "label": "Stop after errors in a row", "kind": "number", "min": 0, "max": 100,
     "more": True, "tip": "The safety check stops a task after this many failed steps in a row (0: never)."},
    {"key": "breaker_no_progress_minutes", "label": "Stop when nothing changes (minutes)", "kind": "number",
     "min": 0, "max": 600, "more": True, "tip": "The safety check stops a task that changes nothing for this long."},
)
BY_FIELD = {f["key"]: f for f in FIELDS}
COMPACTOR = "compactor"


def _effective(cfg) -> dict[str, Any]:
    from ..harness import websearch
    from ..harness.breaker import BreakerSettings
    from ..plugins.builtin import compactor

    on, comp = compactor.settings_from(cfg)
    br = BreakerSettings.from_config(cfg)
    return {"max_parallel": cfg.limits.max_parallel, "max_steps_per_task": cfg.limits.max_steps_per_task,
            "web_search": bool(websearch.settings(cfg).get("enabled")), "commands": bool(cfg.allow_shell),
            "compaction": bool(on), "compaction_at_tokens": int(comp.get("at_tokens") or 0),
            "breaker_repeats": br.repeats, "breaker_errors": br.errors,
            "breaker_no_progress_minutes": br.no_progress_minutes}


def _fresh_cfg(app):
    hp = _harness_path(app)
    if not hp or not hp.is_file():
        return None
    from ..harness.config import load_config

    try:
        return load_config(str(hp))
    except Exception:  # noqa: BLE001
        return _cfg(app)


def builders_view(app, not_applied: list[str] | None = None) -> dict[str, Any]:
    cfg = _fresh_cfg(app)
    if cfg is None:
        raise _error("The harness's settings aren't set up on this computer yet. Run the set-up in Settings first.",
                     503)
    return {"values": _effective(cfg), "fields": list(FIELDS), "not_applied": not_applied or [],
            "words": "How the builders work on every project on this computer."}


def _coerce(key: str, value: Any) -> Any:
    f = BY_FIELD[key]
    if f["kind"] == "switch":
        if not isinstance(value, bool):
            raise ValueError(f"{f['label']} is on or off")
        return value
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{f['label']} must be a number") from None
    if n < f["min"] or n > f["max"]:
        raise ValueError(f"{f['label']} must be between {f['min']} and {f['max']}")
    return n if key == "breaker_no_progress_minutes" else int(n)


def builders_save(app, body: dict[str, Any]) -> dict[str, Any]:
    from ..harness.config import load_custom, save_custom

    hp = _harness_path(app)
    if not hp or not hp.is_file():
        raise _error("The harness's settings aren't set up on this computer yet. Run the set-up in Settings first.",
                     503)
    changes = {k: v for k, v in body.items() if k in BY_FIELD}
    if not changes:
        raise _error("Nothing was changed: no builders' setting was given.")
    try:
        clean = {k: _coerce(k, v) for k, v in changes.items()}
    except ValueError as e:
        raise _error(f"Nothing was changed: {e}.") from None
    custom = load_custom(hp)
    keep = dict(custom)
    lim = dict(custom.get("limits") or {})
    for k in ("max_parallel", "max_steps_per_task"):
        if k in clean:
            lim[k] = clean[k]
    if lim:
        custom["limits"] = lim
    if "web_search" in clean:
        custom["websearch"] = {**(custom.get("websearch") or {}), "enabled": clean["web_search"]}
    if "commands" in clean:
        custom["workspace"] = {**(custom.get("workspace") or {}), "allow_shell": clean["commands"]}
    br = {k[len("breaker_"):]: v for k, v in clean.items() if k.startswith("breaker_")}
    if br:
        custom["breaker"] = {**(custom.get("breaker") or {}), **br}
    if "compaction" in clean or "compaction_at_tokens" in clean:
        plugins = dict(custom.get("plugins") or {})
        entry = dict(plugins.get(COMPACTOR) or {})
        if "compaction" in clean:
            entry["enabled"] = clean["compaction"]
        if "compaction_at_tokens" in clean:
            entry["settings"] = {**(entry.get("settings") or {}), "at_tokens": clean["compaction_at_tokens"]}
        plugins[COMPACTOR] = entry
        custom["plugins"] = plugins
    save_custom(hp, custom)
    try:
        from ..harness.config import load_config

        cfg = load_config(str(hp))
    except Exception as e:  # noqa: BLE001 - never leave settings this computer can't load
        save_custom(hp, keep)
        raise _error(f"Nothing was changed: the settings wouldn't load with that ({e}).") from None
    got = _effective(cfg)
    not_applied = [BY_FIELD[k]["label"] for k, v in clean.items() if got.get(k) != v]
    return builders_view(app, not_applied)
