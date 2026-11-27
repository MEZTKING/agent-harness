"""Built-in plugin ``compactor``: a long task's older steps summarised by a cheap model.

Once a conversation passes ``at_tokens`` (about 120,000 by default), the steps between the task
(the first message, kept word for word) and the last ``keep_last_steps`` steps (also kept word for
word) become one message: the task and its "done when", the files changed so far (from the
workspace's own record), and the cheap model's notes on decisions made, errors met and what
fixed them, and where the work stands. The system prompt (with the repository's rules) is never
touched, so it stays in the provider's cache. A step is an assistant turn with its tool results,
so a tool call never loses its result.

Settings: ``compaction:`` in harness.yaml (``enabled``, ``at_tokens``, ``keep_last_steps``,
``model`` as ``provider/model``, ``role``), with choices made in the app (custom.yaml
``plugins: compactor:``) on top. The model: ``model`` if set, else the last fallback of
``role`` (or of the conversation's own role), else ``deepseek/deepseek-v4-flash`` when DeepSeek
is set up, else the conversation's own model. What the summary costs goes on the task's budget.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..api import Plugin, PluginContext
from ..manifest import parse_manifest
from ...brand import NAME

CHEAP_MODEL = "deepseek/deepseek-v4-flash"
MARK = "[Earlier steps, summarised to save room]"
MAX_TRANSCRIPT_CHARS = 240_000  # what the cheap model is given to read (start and end kept)
MAX_RESULT_CHARS = 2_000  # of each tool result in that transcript
SUMMARY_TOKENS = 4_000

MANIFEST = parse_manifest({
    "id": "compactor",
    "name": "Compaction",
    "version": "1.0.0",
    "description": ("When a long task's conversation gets very big, a cheap model sums up the older steps, so "
                    "each step costs less. The task, the files changed and the last few steps are kept as "
                    "they were."),
    "author": NAME,
    "licence": "MIT",
    "homepage": "",
    "entry": "roundtable.plugins.builtin.compactor:Compactor",
    "api": 1,
    "hooks": ["compact"],
    "permissions": [],
    "settings": {
        "at_tokens": {"type": "integer", "default": 120_000,
                      "description": "Sum up once a conversation is this many tokens long."},
        "keep_last_steps": {"type": "integer", "default": 4,
                            "description": "How many of the latest steps are kept word for word."},
        "model": {"type": "string", "default": "",
                  "description": ("The model that writes the summary, as provider/model. Empty: a cheap one "
                                  "(the role's last fallback, or DeepSeek's flash model).")},
        "role": {"type": "string", "default": "",
                 "description": "Use this role's last fallback for the summary. Empty: the task's own role."},
    },
})

SYSTEM = ("You sum up the earlier part of a coding agent's work so it can carry on without the full "
          "transcript. Be exact and brief. Use these headings, each with short bullet points:\n"
          "Decisions: what was decided and why.\n"
          "Errors and fixes: each error met (the message, shortened) and what fixed it, or that it is still open.\n"
          "Progress: what is done and what is left, against the task's 'done when'.\n"
          "Facts to keep: names, paths, commands, versions and values the rest of the work needs.\n"
          "Never invent anything that is not in the transcript.")


class Compactor(Plugin):
    def compact(self, ctx: PluginContext, messages: list[dict[str, Any]],
                info: dict[str, Any]) -> list[dict[str, Any]] | None:
        at = int(ctx.settings.get("at_tokens") or 0)
        keep = max(1, int(ctx.settings.get("keep_last_steps") or 1))
        if at <= 0 or int(info.get("tokens") or 0) < at:
            return None
        cut = split_point(messages, keep)
        if cut is None:
            return None
        step = int(info.get("step") or 0)
        if step and step - int(ctx.state.get("last_step", -10**9)) < keep:
            return None  # just done: the kept steps alone are too big; wait for new ones
        middle = messages[1:cut]
        cfg = info.get("cfg")
        notes = self._summarise(ctx, cfg, info, middle)
        ctx.state["last_step"] = step
        ctx.state["times"] = int(ctx.state.get("times", 0)) + 1
        summary = build_summary(str(info.get("task") or ""), list(info.get("changed") or []), notes,
                                steps=sum(1 for m in middle if m.get("role") == "assistant"), kept=keep)
        return [messages[0], {"role": "user", "content": summary}] + messages[cut:]

    # -- the cheap model ------------------------------------------------------------
    def _summarise(self, ctx: PluginContext, cfg: Any, info: dict[str, Any], middle: list[dict[str, Any]]) -> str:
        if cfg is None:
            return ""
        from ...harness.config import ModelRef

        ref = ModelRef.parse(pick_model(cfg, ctx.settings, info.get("role"), str(info.get("model") or "")))
        prompt = ("The task:\n" + str(info.get("task") or "")[:6000] + "\n\nThe earlier steps to sum up:\n"
                  + transcript(middle))
        resp = cfg.provider(ref.provider).chat(ref.model, SYSTEM, [{"role": "user", "content": prompt}], [],
                                               max_tokens=SUMMARY_TOKENS)
        info["charge"](cfg.cost(ref, resp.usage))
        return (resp.text or "").strip()


def pick_model(cfg: Any, settings: dict[str, Any], role: str | None, own: str) -> str:
    """The summary's model: the setting, a role's last fallback, DeepSeek's flash model, or the task's own."""
    if settings.get("model"):
        return str(settings["model"])
    roles = getattr(cfg, "roles", None) or {}
    spec = roles.get(settings.get("role") or role or "")
    if spec is not None and len(spec.models) > 1:
        return str(spec.models[-1])
    if "deepseek" in (getattr(cfg, "providers", None) or {}):
        return CHEAP_MODEL
    return own or (str(spec.models[-1]) if spec is not None else CHEAP_MODEL)


def split_point(messages: list[dict[str, Any]], keep: int) -> int | None:
    """Where the kept steps start: the ``keep``-th last assistant turn. None when nothing is older."""
    starts = [i for i, m in enumerate(messages) if i > 0 and m.get("role") == "assistant"]
    if len(starts) <= keep:
        return None
    cut = starts[-keep]
    return cut if cut > 2 else None  # at least two older messages, or a summary saves nothing


def transcript(middle: list[dict[str, Any]]) -> str:
    """The older steps as plain text for the cheap model (long results shortened)."""
    lines = []
    for m in middle:
        role = m.get("role")
        content = str(m.get("content") or "")
        if role == "assistant":
            calls = "; ".join(f"{c.get('name')}({_args(c.get('arguments'))})" for c in m.get("tool_calls") or [])
            lines.append(f"ASSISTANT: {content}" + (f"\n  calls: {calls}" if calls else ""))
        elif role == "tool":
            flag = " (error)" if m.get("is_error") else ""
            lines.append(f"RESULT of {m.get('name')}{flag}: {_clip(content, MAX_RESULT_CHARS)}")
        else:
            lines.append(f"{str(role).upper()}: {_clip(content, MAX_RESULT_CHARS * 3)}")
    return _clip("\n".join(lines), MAX_TRANSCRIPT_CHARS)


def build_summary(task: str, changed: list[str], notes: str, steps: int, kept: int) -> str:
    parts = [f"{MARK} {steps} earlier step{'s' if steps != 1 else ''} were summed up; the last {kept} follow as "
             "they were. The task is still the first message above."]
    title, done_when = task_parts(task)
    if title:
        parts.append("The task: " + title)
    if done_when:
        parts.append("Done when: " + done_when)
    parts.append("Files changed so far: " + (", ".join(changed) if changed else "none yet"))
    if notes:
        parts.append(notes)
    return "\n\n".join(parts)


def task_parts(task: str) -> tuple[str, str]:
    """The task's heading and its 'done when' (the worker prompt's '# Your task' and '# Acceptance criteria')."""
    sections = _sections(task)
    title = ""
    for k, v in sections:
        if k.lower().startswith("your task"):
            title = (k[len("your task"):].strip() + " " + (v.splitlines()[0] if v else "")).strip()
            break
    done = next((v for k, v in sections if k.lower().startswith(("acceptance", "done when"))), "")
    if not done:
        m = re.search(r"(?i)done when:?\s*(.+)", task)
        done = m.group(1) if m else ""
    if not title:
        title = next((line.strip() for line in task.splitlines() if line.strip()), "")
    return _clip(title, 400), _clip(done.strip(), 1500)


def _sections(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for block in re.split(r"(?m)^# ", text)[1:]:
        head, _, body = block.partition("\n")
        out.append((head.strip(), body.strip()))
    return out


def _args(args: Any) -> str:
    try:
        return _clip(json.dumps(args, ensure_ascii=False, default=str), 300)
    except (TypeError, ValueError):
        return _clip(str(args), 300)


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n... ({len(text) - limit} characters left out) ...\n" + text[-half:]


def settings_from(cfg: Any) -> tuple[bool, dict[str, Any]]:
    """(on, settings): the defaults, then ``compaction:`` in harness.yaml, then the app's choices."""
    from ...harness.config import section

    raw = section(cfg, "compaction")
    state = (getattr(cfg, "plugins", None) or {}).get(MANIFEST.id) or {}
    settings = MANIFEST.defaults()
    for values in (raw, state.get("settings") or {}):
        for k, v in values.items():
            if k in MANIFEST.settings:
                try:
                    settings[k] = MANIFEST.settings[k].coerce(v)
                except ValueError:
                    pass  # a bad value: the default stays
    enabled = state["enabled"] if "enabled" in state else raw.get("enabled", True)
    return bool(enabled), settings


def make(cfg: Any):
    enabled, settings = settings_from(cfg)
    return MANIFEST, Compactor(), enabled, settings
