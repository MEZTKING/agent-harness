"""The recommended setup: who plans, who codes and who checks, in one click (Settings).

It writes the shipped template's providers, roles and profiles into harness.yaml and keeps
everything else the owner set there (hub, limits, pricing, plugins, improve, workspace...).
custom.yaml is never touched. The old file is kept as ``harness.yaml.before-<date>``.
"""

from __future__ import annotations

from datetime import date
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

# what the recommended setup owns in harness.yaml; every other setting stays the owner's
OWNED = ("roles", "profiles", "default_profile", "planner_role", "critic_role", "reviewer_role", "design_role",
         "scout_role")

SUMMARY = ("Claude plans the project and designs the screens, DeepSeek writes the code, and models from other "
           "makers (GPT, GLM) check every plan and every task. A typical task costs roughly 1 to 10 US cents, "
           "plus a little for the plan; the plan shows its estimate before anything is built. Every job falls "
           "back to DeepSeek, so a DeepSeek key alone is enough to start.")


def template_text() -> str:
    return resources.files("roundtable").joinpath("templates/harness.example.yaml").read_text(encoding="utf-8")


def template_raw() -> dict[str, Any]:
    return yaml.safe_load(template_text()) or {}


def merged(raw: dict[str, Any]) -> dict[str, Any]:
    """The owner's harness.yaml with the recommended providers, roles and profiles laid in."""
    tpl = template_raw()
    out = dict(raw)
    out["providers"] = {**(raw.get("providers") or {}), **(tpl.get("providers") or {})}
    roles = {k: v for k, v in (raw.get("roles") or {}).items() if k not in (tpl.get("roles") or {})}
    out["roles"] = {**(tpl.get("roles") or {}), **roles}  # the owner's own extra roles stay
    for key in OWNED:
        if key != "roles" and key in tpl:
            out[key] = tpl[key]
    return out


def _routing(raw: dict[str, Any], path: Path) -> dict[str, list[str]]:
    from .harness.config import load_custom, merge_custom, parse_config

    try:
        cfg = parse_config(merge_custom(raw, load_custom(path)), path)
    except ValueError:
        return {}
    cfg = cfg.for_profile(cfg.default_profile)
    return {r.name: [str(m) for m in r.models] for r in cfg.roles.values()}


def preview(harness_path: str | Path) -> dict[str, Any]:
    """Each role's models now and after, for the Settings card."""
    path = Path(harness_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {} if path.exists() else {}
    before, after = _routing(raw, path), _routing(merged(raw), path)
    rows = [{"role": r, "before": before.get(r, []), "after": after.get(r, []),
             "same": before.get(r) == after.get(r)} for r in dict.fromkeys(list(after) + list(before))]
    profiles = template_raw().get("profiles") or {}
    return {"summary": SUMMARY, "rows": rows, "in_use": all(r["same"] for r in rows),
            "profiles": [{"name": n, "description": (p or {}).get("description", "")} for n, p in profiles.items()],
            "default_profile": template_raw().get("default_profile")}


def backup_path(path: Path, today: date | None = None) -> Path:
    stamp = (today or date.today()).isoformat()
    target = path.with_name(f"{path.name}.before-{stamp}")
    n = 2
    while target.exists():
        target = path.with_name(f"{path.name}.before-{stamp}-{n}")
        n += 1
    return target


def apply(harness_path: str | Path, today: date | None = None) -> dict[str, Any]:
    """Write the recommended setup into harness.yaml; returns the backup's path."""
    from .harness.config import load_custom, merge_custom, parse_config

    path = Path(harness_path)
    old_text = path.read_text(encoding="utf-8") if path.exists() else ""
    raw = yaml.safe_load(old_text) or {} if old_text else {}
    new = merged(raw)
    parse_config(merge_custom(new, load_custom(path)), path)  # check before anything is written
    backup = None
    if old_text:
        backup = backup_path(path, today)
        backup.write_text(old_text, encoding="utf-8")
    tpl = template_raw()
    mine = {k: v for k, v in new.items() if k not in OWNED and k != "providers"}
    stamp = (today or date.today()).isoformat()
    text = (f"# Roundtable configuration: who does what. The recommended setup, written by Roundtable Hold on {stamp}"
            + (f";\n# the file before it is {backup.name}." if backup else ".") + "\n"
            "# Model references are \"<provider>/<model>\". Change them in the app (Models) or here.\n\n"
            + yaml.safe_dump({"providers": new["providers"]}, sort_keys=False, allow_unicode=True) + "\n"
            + yaml.safe_dump({k: new[k] for k in OWNED if k in new}, sort_keys=False, allow_unicode=True))
    if mine:
        text += "\n# Your own settings, kept as they were\n" + yaml.safe_dump(mine, sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")
    return {"written": str(path), "backup": str(backup) if backup else "",
            "roles": sorted((tpl.get("roles") or {}))}
