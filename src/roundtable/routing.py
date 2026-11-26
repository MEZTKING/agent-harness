"""Who does which job, in the owner's words, and changing it from the app (Models).

Each job (a role in harness.yaml: orchestrator, coder, reviewer...) has a plain name ("Planner", "Coder"),
its models (the first does the work, the others step in when it can't answer) and, per set of models
(Budget, Balanced, Quality), that set's own choice. Model references become names: ``anthropic/claude-opus-5-5``
is "Claude Opus 5.5 (Anthropic)".

Changes go where the rest of the app already writes them:

* the base choice (used when a set doesn't name the job) goes to custom.yaml through
  ``providers.manage.set_role_models``, the same as ``roundtable assign``;
* a set's own choice goes into that set in harness.yaml. The file is checked before it is written and the old
  one is kept next to it (``harness.yaml.before-<date>``), as the recommended setup does.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

# job names and what each does, for the owner
JOBS: dict[str, tuple[str, str]] = {
    "orchestrator": ("Planner", "Turns your idea into a plan, splits it into tasks and writes the final report."),
    "planner": ("Planner", "Turns your idea into a plan, splits it into tasks and writes the final report."),
    "manager": ("Project manager", "Writes specs, API documents and READMEs, and keeps the parts in step."),
    "critic": ("Critic", "Gives a second opinion on every new plan, from another maker's model."),
    "designer": ("Designer", "Designs the looks for you to choose from, with a picture of each."),
    "coder": ("Coder", "Writes and tests the code."),
    "scout": ("Researcher", "Reads the pages and projects you want yours to be like."),
    "stylist": ("Stylist", "Makes the screens look right."),
    "reviewer": ("Reviewer", "Checks every finished task against what it was meant to do."),
    "illustrator": ("Illustrator", "Makes pictures: art, backgrounds and icons."),
    "artist": ("Pixel artist", "Makes pixel-art game pictures."),
    "writer": ("Writer", "Writes words: marketing text and long pieces."),
    "tester": ("Tester", "Tries the app and reports what's broken."),
}
JOB_ORDER = list(JOBS)
SET_NAMES = {"budget": "Budget", "balanced": "Balanced", "quality": "Quality"}
EFFORTS = ("low", "medium", "high", "max")

PROVIDER_NAMES = {"anthropic": "Anthropic", "deepseek": "DeepSeek", "openai": "OpenAI", "openai_images": "OpenAI",
                  "gemini": "Google", "openrouter": "OpenRouter", "openrouter_images": "OpenRouter",
                  "openference": "Openference", "retrodiffusion": "Retro Diffusion", "scripted": "Test models"}
WORDS = {"gpt": "GPT", "glm": "GLM", "deepseek": "DeepSeek", "openai": "OpenAI", "rd": "RD", "ai": "AI", "xl": "XL",
         "qwen": "Qwen", "kimi": "Kimi", "llama": "Llama", "o1": "o1", "o3": "o3", "o4": "o4"}


def job_name(role: str) -> str:
    if role in JOBS:
        return JOBS[role][0]
    return " ".join(w[:1].upper() + w[1:] for w in re.split(r"[-_\s]+", role) if w) or role


def set_name(profile: str) -> str:
    return SET_NAMES.get(profile, job_name(profile))


def provider_name(pid: str, spec: dict[str, Any] | None = None) -> str:
    if pid in PROVIDER_NAMES:
        return PROVIDER_NAMES[pid]
    from .providers.manage import provider_label

    base = pid.removesuffix("_images")
    return PROVIDER_NAMES.get(base) or provider_label(base, spec)


def _pretty(name: str) -> str:
    """claude-opus-5-5 -> Claude Opus 5.5; deepseek-v4-flash -> DeepSeek V4 Flash; names with spaces stay."""
    if " " in name:
        return name
    out: list[str] = []
    for w in re.split(r"[-_]+", name):
        if not w:
            continue
        if w.isdigit() and out and re.fullmatch(r"\d+(\.\d+)*", out[-1]):
            out[-1] += "." + w  # 5-5 -> 5.5
        elif w.lower() in WORDS:
            out.append(WORDS[w.lower()])
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out) or name


def model_label(ref: str, providers: dict[str, Any] | None = None) -> str:
    """"anthropic/claude-opus-5-5" -> "Claude Opus 5.5 (Anthropic)"."""
    pid, sep, rest = str(ref).partition("/")
    if not sep:
        return _pretty(pid)
    name = rest.rsplit("/", 1)[-1]  # openrouter/anthropic/claude-sonnet-5.5: the maker's prefix goes
    return f"{_pretty(name)} ({provider_name(pid, (providers or {}).get(pid))})"


def _key_state(providers: dict[str, Any]) -> dict[str, dict[str, Any]]:
    import os

    out = {}
    for pid, spec in providers.items():
        env = (spec or {}).get("api_key_env") or ""
        out[pid] = {"name": provider_name(pid, spec), "needs_key": bool(env), "key_set": bool(env and os.environ.get(env))}
    return out


def _entry(models: list[str], options: dict[str, Any] | None, providers: dict[str, Any]) -> dict[str, Any]:
    return {"models": [{"ref": m, "label": model_label(m, providers)} for m in models],
            "effort": (options or {}).get("effort", "")}


def view(cfg) -> dict[str, Any]:
    """Every job with its models: the base choice and each set's own (for the Models page)."""
    providers = dict(cfg.providers)
    learned = set((getattr(cfg, "learned", {}) or {}).get("roles") or {})
    roles = sorted(cfg.roles.values(), key=lambda r: (JOB_ORDER.index(r.name) if r.name in JOB_ORDER else 99, r.name))
    sets = list(cfg.profiles)
    jobs = []
    seen: set[str] = set()
    for r in roles:
        base = _entry([str(m) for m in r.models], r.options, providers)
        per = {}
        for p in sets:
            spec = (cfg.profiles[p].get("roles") or {}).get(r.name)
            if spec and spec.get("model"):
                per[p] = _entry([spec["model"]] + list(spec.get("fallback") or []), spec.get("options") or r.options,
                                providers)
        for e in [base, *per.values()]:
            seen.update(m["ref"] for m in e["models"])
        jobs.append({"role": r.name, "name": job_name(r.name), "about": JOBS.get(r.name, ("", r.description))[1]
                     or r.description, "kind": r.kind, "base": base, "sets": per, "learned": r.name in learned,
                     "special": [w for w, k in (("plans", cfg.planner_role), ("reviews", cfg.reviewer_role),
                                                ("critic", cfg.critic_role)) if k == r.name]})
    from .recommended import template_raw

    tpl = template_raw()
    more = [str(r.get("model")) for r in (tpl.get("roles") or {}).values() if r and r.get("model")]
    for p in (tpl.get("profiles") or {}).values():
        for r in ((p or {}).get("roles") or {}).values():
            more += [r.get("model")] + list(r.get("fallback") or [])
    for r in (tpl.get("roles") or {}).values():
        more += list((r or {}).get("fallback") or [])
    choices = sorted({m for m in list(seen) + [m for m in more if m] if m.split("/", 1)[0] in providers},
                     key=lambda m: (provider_name(m.split("/", 1)[0]), model_label(m, providers)))
    return {
        "jobs": jobs,
        "sets": [{"id": p, "name": set_name(p), "about": cfg.profiles[p].get("description", "")} for p in sets],
        "default_set": cfg.default_profile or "",
        "choices": [{"ref": m, "label": model_label(m, providers), "provider": m.split("/", 1)[0]} for m in choices],
        "providers": _key_state(providers),
        "efforts": list(EFFORTS),
    }


def _backup(path: Path) -> Path:
    """The file as it was before the app's first change today (one copy a day, not one per click)."""
    from datetime import date

    target = path.with_name(f"{path.name}.before-{date.today().isoformat()}")
    if not target.exists():
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def set_job(harness_path: str | Path, role: str, models: list[str], profile: str | None = None,
            effort: str | None = None) -> dict[str, Any]:
    """Choose a job's models: the base choice (custom.yaml) or one set's own (harness.yaml)."""
    from .harness.config import ModelRef, load_custom, merge_custom, parse_config
    from .providers.manage import set_role_models

    models = [str(m).strip() for m in models or [] if m and str(m).strip()]
    models = list(dict.fromkeys(models))
    if not models:
        raise ValueError("Choose at least one model for this job.")
    for m in models:
        ModelRef.parse(m)
    if effort and effort not in EFFORTS:
        raise ValueError(f"How hard it thinks must be one of: {', '.join(EFFORTS)}.")
    path = Path(harness_path)
    if not profile:
        return {"saved": "base", **set_role_models(path, role, models)}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sets = raw.get("profiles") or {}
    if profile not in sets:
        raise ValueError(f"There's no {set_name(profile)} set. Choose another, then try again.")
    if role not in (raw.get("roles") or {}) and role not in (load_custom(path).get("roles") or {}):
        raise ValueError(f"There's no {job_name(role)} job. Refresh the page and try again.")
    spec = sets[profile] = dict(sets[profile] or {})
    roles = spec["roles"] = dict(spec.get("roles") or {})
    entry = dict(roles.get(role) or {})
    entry["model"], entry["fallback"] = models[0], models[1:]
    if effort is not None:
        opts = dict(entry.get("options") or {})
        if effort:
            opts["effort"] = effort
        else:
            opts.pop("effort", None)
        if opts:
            entry["options"] = opts
        else:
            entry.pop("options", None)
    roles[role] = entry
    raw["profiles"] = sets
    parse_config(merge_custom(raw, load_custom(path)), path)  # check before anything is written
    _write(path, raw)
    return {"saved": profile, **entry}


def set_default(harness_path: str | Path, profile: str) -> dict[str, Any]:
    """Which set every project uses unless it picks its own."""
    from .harness.config import load_custom, merge_custom, parse_config

    path = Path(harness_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if profile and profile not in (raw.get("profiles") or {}):
        raise ValueError(f"There's no {set_name(profile)} set. Choose another, then try again.")
    if profile:
        raw["default_profile"] = profile
    else:
        raw.pop("default_profile", None)
    parse_config(merge_custom(raw, load_custom(path)), path)
    _write(path, raw)
    return {"default_set": profile}


def _write(path: Path, raw: dict[str, Any]) -> None:
    backup = _backup(path)
    path.write_text("# Roundtable configuration: who does what. Changed in the Roundtable Hold app (Models);\n"
                    f"# the file before the change is {backup.name}.\n"
                    + yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
