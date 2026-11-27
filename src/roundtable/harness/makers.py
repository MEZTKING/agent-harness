"""Who made a model, and whether a project may use it: privacy in one place.

A project's settings can keep it to some AI services (``providers_allowed``: the company it is sent through,
such as openrouter or deepseek) and to some makers (``makers_allowed``: the company that made the model, such
as anthropic or openai, whichever service carries it). A model may see the project only when both lists
allow it; an empty list means any. Every stage that picks a model asks ``allowed`` (the orchestrator's
``_may_use``); none reads the lists itself.
"""

from __future__ import annotations

from typing import Any, Iterable

# a model's maker from its name, when the provider id doesn't say (a router, a custom endpoint)
_MAKERS = (("claude", "anthropic"), ("gpt", "openai"), ("o1", "openai"), ("o3", "openai"), ("o4", "openai"),
           ("codex", "openai"), ("deepseek", "deepseek"), ("gemini", "google"), ("gemma", "google"),
           ("glm", "zhipu"), ("kimi", "moonshot"), ("moonshot", "moonshot"), ("qwen", "alibaba"), ("grok", "xai"),
           ("llama", "meta"), ("mistral", "mistral"), ("codestral", "mistral"), ("minimax", "minimax"))


def maker(ref: Any) -> str:
    """Who made a model: "openrouter/anthropic/claude-x" -> anthropic, "deepseek/deepseek-v4" -> deepseek."""
    pid, _, model = str(ref).partition("/")
    if "/" in model:  # a router: the maker is the model's own prefix
        return model.split("/", 1)[0].lower()
    m = model.lower()
    for word, who in _MAKERS:
        if m.startswith(word):
            return who
    return pid.lower()


def _provider(ref: Any) -> str:
    pid = getattr(ref, "provider", None)
    return str(pid if pid is not None else str(ref).partition("/")[0]).lower()


def _names(values: dict[str, Any] | None, key: str) -> list[str]:
    raw = (values or {}).get(key) or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(v).strip().lower() for v in raw if str(v).strip()]


def allowed(values: dict[str, Any] | None, ref: Any) -> bool:
    """May this model see the project? ``values``: the project's settings (``providers_allowed``,
    ``makers_allowed``); an empty list means any."""
    providers, makers = _names(values, "providers_allowed"), _names(values, "makers_allowed")
    if providers and _provider(ref) not in providers:
        return False
    if makers and maker(ref) not in makers:
        return False
    return True


def why_not(values: dict[str, Any] | None, ref: Any) -> str:
    """Plain words for a refusal ("" when the model is allowed)."""
    providers, makers = _names(values, "providers_allowed"), _names(values, "makers_allowed")
    if providers and _provider(ref) not in providers:
        return (f"{ref} comes through {_provider(ref)}, and this project may only be sent through "
                f"{', '.join(providers)} (providers_allowed in its settings).")
    if makers and maker(ref) not in makers:
        return (f"{ref} is made by {maker(ref)}, and this project may only be seen by models made by "
                f"{', '.join(makers)} (makers_allowed in its settings).")
    return ""


def distinct(refs: Iterable[Any], not_maker: str = "") -> list:
    """One model per maker, in the order given, leaving out ``not_maker``'s."""
    seen = {not_maker.lower()} if not_maker else set()
    out = []
    for ref in refs:
        who = maker(ref)
        if who in seen:
            continue
        seen.add(who)
        out.append(ref)
    return out
