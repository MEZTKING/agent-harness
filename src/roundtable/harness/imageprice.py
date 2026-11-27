"""What one picture costs, for the estimate (plandoc.estimate), without inventing a price.

In order:

1. what the provider really charged for that model before: the picture rows of any project's
   ``metrics.jsonl`` (an image task writes one row a picture, with the charge the provider reported);
2. ``pricing: {<model>: {per_image: 0.04}}`` in harness.yaml;
3. otherwise None: the model stays "unpriced", so the owner sees that the cost isn't known and autopilot
   leaves the plan for them.

Nothing here reaches the network: an estimate is made before anything runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def reported(metric_files: Iterable[Path]) -> dict[str, float]:
    """The average real charge per row, by model, from rows a provider priced (cost_usd above 0)."""
    sums: dict[str, list[float]] = {}
    for f in metric_files or []:
        try:
            lines = Path(f).read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for ln in lines:
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if not isinstance(d, dict) or d.get("outcome") in ("owner_feedback", "error"):
                continue
            model, cost = d.get("model"), d.get("cost_usd")
            try:
                cost = float(cost or 0)
            except (TypeError, ValueError):
                continue
            if model and cost > 0:
                s = sums.setdefault(str(model), [0.0, 0.0])
                s[0] += cost
                s[1] += 1
    return {m: s[0] / s[1] for m, s in sums.items() if s[1]}


def _listed(cfg, model) -> float | None:
    pricing = getattr(cfg, "pricing", None) or {}
    name = str(model)
    bare = getattr(model, "model", name.split("/", 1)[-1])
    for key in (name, bare):
        price = pricing.get(key)
        if isinstance(price, dict) and price.get("per_image") is not None:
            try:
                x = float(price["per_image"])
            except (TypeError, ValueError):
                return None
            return x if x > 0 else None
    return None


def per_image(cfg, model, metric_files: Iterable[Path] | None = None,
              charges: dict[str, float] | None = None) -> float | None:
    """The price of one picture from ``model``: real charges first, then the pricing table, else None.
    ``charges``: :func:`reported` already worked out (the estimate reads the files once)."""
    got = charges if charges is not None else reported(metric_files or [])
    if str(model) in got:
        return round(got[str(model)], 6)
    return _listed(cfg, model)


def charges_from_history(history: dict[str, dict[str, Any]] | None) -> dict[str, float]:
    """The real charges by model that plandoc.history_by_role carried along (its "charges" entry)."""
    out: dict[str, float] = {}
    for h in (history or {}).values():
        if isinstance(h, dict):
            for m, c in (h.get("charges") or {}).items():
                out.setdefault(str(m), float(c))
    return out
