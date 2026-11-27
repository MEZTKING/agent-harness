"""Built-in plugin ``attachments``: what the owner attached (pictures, files, @file references) reaches
the models, and a "steer" note reaches the task running now at its next step.

The work is in ``roundtable/attachments.py`` (``request_with_attachments``); this is its seat in the
model-call line. On by default; switched off, models see only the words.
"""

from __future__ import annotations

from typing import Any

from ..api import Plugin, PluginContext
from ..manifest import parse_manifest

MANIFEST = parse_manifest({
    "id": "attachments",
    "name": "Pictures and files",
    "version": "1.0.0",
    "description": ("Sends the pictures and files you attach to an idea, a note or a question to the models "
                    "(pictures only to models that can see them), and gives a note you send with Steer to the "
                    "task working now."),
    "author": "Roundtable Hold",
    "licence": "MIT",
    "homepage": "",
    "entry": "roundtable.plugins.builtin.attachments:Attachments",
    "api": 1,
    "hooks": ["before_model_call"],
    "permissions": [],
    "settings": {},
})


class Attachments(Plugin):
    def __init__(self, cfg: Any = None):
        self.cfg = cfg

    def before_model_call(self, ctx: PluginContext, role, model, system, messages):
        from ...attachments import request_with_attachments

        return system, request_with_attachments(self.cfg, model, messages, ctx.project_root, role, ctx.state)


def make(cfg: Any):
    state = (getattr(cfg, "plugins", None) or {}).get(MANIFEST.id) or {}
    return MANIFEST, Attachments(cfg), bool(state.get("enabled", True)), MANIFEST.defaults()
