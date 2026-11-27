"""What each model is good at, from real runs: the strength map the router uses (harness/router.py).

    GET /api/strengths   ?path=<project, optional: its runs counted too>
                         -> {lines: [{model, label, role, tag, words, approved, n}],
                             roles: {role: {tag: [{model, quality, approved, n, cost_per_success}]}},
                             table: [{role, model, label, tag, approved, n, quality, cost_per_success}],
                             min_samples, projects}

``lines`` is the short first view: one plain line per model ("Best at game logic: 9 of 10"). ``table`` is
the detail behind More. Read only; numbers only, from every project the lab knows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..harness import tasktags
from ..harness.config import section


def routes(app) -> dict[tuple[str, str], Any]:
    return {("GET", "/api/strengths"): lambda q: listing(app, q)}


def _arg(q, name: str) -> str:
    return str((q.get(name) or [""])[0] or "")


def listing(app, q) -> dict[str, Any]:
    from ..improve.analysis import Dataset, collect, strengths
    from ..routing import model_label

    cfg = app.need_cfg()
    min_n = int(section(cfg, "router").get("min_samples") or 5)
    extra = []
    path = _arg(q, "path")
    if path:
        extra.append(Path(app.project(cfg, path).root))
    if cfg.lab_dir:
        from ..improve.lab import Lab

        ds = collect(Lab(cfg.lab_dir), extra=extra)
    else:
        ds = Dataset()
        if extra:
            from ..improve.analysis import tag_stats

            ds.by_tag = tag_stats([p / ".harness" / "metrics.jsonl" for p in extra])
            ds.projects = extra
    roles = strengths(ds, min_n)
    providers = getattr(cfg, "providers", None) or {}
    table, best = [], {}
    for role, tags in sorted(roles.items()):
        for tag, rows in sorted(tags.items()):
            for r in rows:
                table.append({"role": role, "model": r["model"], "label": model_label(r["model"], providers),
                              "tag": tag, "tag_words": tasktags.words(tag), **{k: r[k] for k in
                              ("approved", "n", "quality", "cost_per_success")}})
                key = r["model"]
                mine = (r["quality"], r["n"])
                if key not in best or mine > (best[key]["quality"], best[key]["n"]):
                    best[key] = {"role": role, "tag": tag, **r}
    lines = []
    for model, b in sorted(best.items(), key=lambda kv: (-kv[1]["quality"], -kv[1]["n"], kv[0])):
        lines.append({"model": model, "label": model_label(model, providers), "role": b["role"], "tag": b["tag"],
                      "approved": b["approved"], "n": b["n"],
                      "words": f"Best at {tasktags.words(b['tag'])}: {b['approved']} of {b['n']}"})
    return {"lines": lines, "roles": roles, "table": table, "min_samples": min_n, "projects": len(ds.projects)}
