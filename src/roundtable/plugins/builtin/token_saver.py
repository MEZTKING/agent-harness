"""Built-in plugin ``token-saver``: the token saver (``harness/saver.py``) behind the plugin API.

It is always first in line for ``on_tool_result``, so later plugins see what the model will
see. Its settings are ``token_saver:`` in harness.yaml, with any choices made in the app
(custom.yaml ``plugins: token-saver:``) on top; ``HarnessConfig.token_saver`` holds the result.

The saver is one per conversation. The orchestrator hands its own in (``run_agent(saver=)``,
which puts it in ``ctx.shared["token_saver"]``); when none is handed in but the conversation
has a project folder, the plugin makes one, so originals can be spilled there.
"""

from __future__ import annotations

from dataclasses import asdict, fields
from typing import Any

from ...harness.saver import SaverConfig, TokenSaver
from ..api import Plugin, PluginContext
from ..manifest import parse_manifest

WORDS = {
    "dedupe_enabled": "Replace a result that is exactly the same as one a moment ago with a short note.",
    "min_bytes": "Results smaller than this many bytes are left alone.",
    "error_min_bytes": "Error results smaller than this many bytes are left alone.",
    "keep_ratio_max": "Only shorten when the short version is at most this share of the original (0.72 = 72%).",
    "min_saved_bytes": "Only shorten when it saves at least this many bytes.",
    "max_lines": "Text with more lines than this is shortened.",
    "head_lines": "Lines kept from the start of long text.",
    "tail_lines": "Lines kept from the end of long text.",
    "tabular_head_rows": "Rows kept from the start of a long table.",
    "tabular_tail_rows": "Rows kept from the end of a long table.",
    "tabular_stride_samples": "About how many rows from the middle of a long table are kept as samples.",
    "long_line_chars": "Lines longer than this many characters are trimmed in the middle.",
    "json_max_parse_bytes": "JSON bigger than this many bytes is treated as plain text.",
    "dedupe_ttl_seconds": "How many seconds an earlier result counts as 'a moment ago'.",
    "error_lines_kept": "How many error-like lines from the left-out middle are kept.",
}
TYPES = {bool: "boolean", int: "integer", float: "number"}
_DEFAULTS = SaverConfig()


def _schema() -> dict[str, dict[str, Any]]:
    out = {}
    for f in fields(SaverConfig):
        if f.name == "enabled":
            continue  # switching the plugin on and off is enabled
        value = getattr(_DEFAULTS, f.name)
        out[f.name] = {"type": TYPES[type(value)], "default": value, "description": WORDS.get(f.name, "")}
    return out


MANIFEST = parse_manifest({
    "id": "token-saver",
    "name": "Token saver",
    "version": "2.1.3",
    "description": ("Big tool results (long logs, tables, JSON) are shortened before a model reads them, so each "
                    "step costs less. Nothing is lost: the full text is kept and the model can ask for it."),
    "author": "Roundtable Hold (ported from dsh-plugin-save-token by PlayWithAI)",
    "licence": "MIT",
    "homepage": "https://github.com/vibe-any/dsh-plugin-save-token",
    "entry": "roundtable.plugins.builtin.token_saver:TokenSaverPlugin",
    "api": 1,
    "hooks": ["on_tool_result", "tools"],
    "permissions": [],
    "settings": _schema(),
})


class TokenSaverPlugin(Plugin):
    def _saver(self, ctx: PluginContext) -> TokenSaver | None:
        saver = ctx.shared.get("token_saver")
        if saver is None and ctx.project_root is not None:
            cfg = SaverConfig(enabled=True, **{k: v for k, v in ctx.settings.items() if k in MANIFEST.settings})
            saver = ctx.shared["token_saver"] = TokenSaver(cfg, ctx.project_root, on_event=ctx.shared.get("emit"))
        return saver

    def tools(self, ctx: PluginContext):
        saver = self._saver(ctx)
        if saver is None or not saver.cfg.enabled:
            return []
        saver.on_event = saver.on_event or ctx.shared.get("emit")
        return [saver.tool()]

    def on_tool_result(self, ctx: PluginContext, tool: str, args: dict[str, Any], text: str, is_error: bool) -> str:
        saver = self._saver(ctx)
        return saver.process(tool, args, text, is_error) if saver is not None else text


def make(cfg: Any):
    sc = getattr(cfg, "token_saver", None) or SaverConfig()
    settings = {k: v for k, v in asdict(sc).items() if k != "enabled"}
    return MANIFEST, TokenSaverPlugin(), sc.enabled, settings
