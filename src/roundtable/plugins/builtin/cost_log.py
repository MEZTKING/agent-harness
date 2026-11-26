"""Built-in example plugin ``cost-log``: each model call's model, tokens and cost in a CSV file.

The smallest useful plugin, to copy when writing your own (docs/plugins.md walks through it).
A plugin of your own would put the manifest below in ``roundtable-plugin.toml`` instead.
"""

from __future__ import annotations

import csv
import time
from typing import Any

from ..api import Plugin, PluginContext
from ..manifest import parse_manifest

MANIFEST = parse_manifest({
    "id": "cost-log",
    "name": "Cost log",
    "version": "1.0.0",
    "description": ("Writes every model call (which model, how many tokens, what it cost) to a spreadsheet "
                    "file you can open in Excel. Off until you switch it on."),
    "author": "Roundtable Hold",
    "licence": "MIT",
    "homepage": "",
    "entry": "roundtable.plugins.builtin.cost_log:CostLog",
    "api": 1,
    "hooks": ["after_model_call", "routes"],
    "permissions": [],
    "settings": {
        "file_name": {"type": "string", "default": "calls.csv",
                      "description": "The file's name, in the plugin's own folder."},
    },
})

COLUMNS = ["time", "project", "role", "model", "input_tokens", "output_tokens", "cache_read_tokens", "cost_usd"]


class CostLog(Plugin):
    def _file(self, ctx: PluginContext):
        name = str(ctx.settings.get("file_name") or "calls.csv").replace("/", "_").replace("\\", "_")
        return ctx.data_dir / name

    def after_model_call(self, ctx: PluginContext, role: str | None, model: str, response: Any, usage: Any) -> None:
        path = self._file(ctx)
        new = not path.exists()
        cost = ctx.cost_of(model, usage)
        with path.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(COLUMNS)
            w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), ctx.project_root.name if ctx.project_root else "",
                        role or "", model, usage.input_tokens, usage.output_tokens, usage.cache_read_tokens,
                        "" if cost is None else f"{cost:.6f}"])

    def routes(self):
        return {"GET summary": self.summary}

    def summary(self, ctx: PluginContext, query: dict[str, Any], body: Any) -> dict[str, Any]:
        """GET /api/plugins/cost-log/summary: calls and dollars so far."""
        path = self._file(ctx)
        if not path.exists():
            return {"calls": 0, "cost_usd": 0.0, "file": str(path)}
        with path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        return {"calls": len(rows), "cost_usd": round(sum(float(r["cost_usd"] or 0) for r in rows), 6),
                "file": str(path)}


def make(cfg: Any):
    state = (getattr(cfg, "plugins", None) or {}).get(MANIFEST.id) or {}
    settings = MANIFEST.defaults()
    try:
        settings.update(MANIFEST.coerce_settings(
            {k: v for k, v in (state.get("settings") or {}).items() if k in MANIFEST.settings}))
    except ValueError:
        pass  # a bad saved value: the defaults are used
    return MANIFEST, CostLog(), bool(state.get("enabled", False)), settings
