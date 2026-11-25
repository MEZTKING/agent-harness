"""Claude via the official Anthropic SDK (native, not an OpenAI shim), so
thinking, prompt caching, effort and refusal fallbacks all keep working.

Role options understood here (all optional):
    effort:            low | medium | high | xhigh | max   -> output_config.effort
    refusal_fallback:  "default" | [model ids] | null      -> server-side fallbacks
                       (beta server-side-fallback-2026-07-01). On by default.
"""

from __future__ import annotations

import os
from typing import Any

from .base import ChatResponse, Provider, ProviderError, ToolCall, ToolSpec, Usage

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _to_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pending_results: list[dict[str, Any]] = []

    def flush():
        if pending_results:
            # all tool results of one turn go back in a single user message
            out.append({"role": "user", "content": list(pending_results)})
            pending_results.clear()

    for m in messages:
        role = m["role"]
        if role == "tool":
            pending_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": m["tool_call_id"],
                    "content": m["content"] or "(empty)",
                    "is_error": bool(m.get("is_error")),
                }
            )
            continue
        flush()
        if role == "user":
            out.append({"role": "user", "content": m["content"]})
        elif role == "assistant":
            raw = m.get("raw")
            if isinstance(raw, dict) and raw.get("provider") == "anthropic":
                # replay Claude's own blocks unchanged (thinking signatures, fallback markers)
                out.append({"role": "assistant", "content": raw["content"]})
            else:
                blocks: list[dict[str, Any]] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for c in m.get("tool_calls") or []:
                    blocks.append({"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["arguments"]})
                out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "(no output)"}]})
    flush()
    return out


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, api_key_env: str = "ANTHROPIC_API_KEY", base_url: str | None = None, timeout: float = 900.0):
        import anthropic

        self._anthropic = anthropic
        key = os.environ.get(api_key_env) if api_key_env else None
        kwargs: dict[str, Any] = {"timeout": timeout, "max_retries": 3}
        if key:
            kwargs["api_key"] = key
        if base_url:
            kwargs["base_url"] = base_url
        try:
            self.client = anthropic.Anthropic(**kwargs)
        except Exception as e:  # missing credentials etc.
            raise ProviderError(f"anthropic: could not create client ({e}); set {api_key_env}") from e

    def chat(self, model, system, messages, tools=None, max_tokens=16000, options=None) -> ChatResponse:
        a = self._anthropic
        options = options or {}
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": _to_anthropic_messages(messages),
            "cache_control": {"type": "ephemeral"},  # automatic prompt caching of the growing prefix
        }
        if tools:
            params["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools
            ]
        if options.get("effort"):
            params["output_config"] = {"effort": options["effort"]}

        fallback = options.get("refusal_fallback", "default")
        try:
            if fallback:
                resp = self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks=fallback, **params)
            else:
                resp = self.client.messages.create(**params)
        except a.AuthenticationError as e:
            raise ProviderError(f"anthropic: authentication failed - check your API key ({e.message})") from e
        except a.NotFoundError as e:
            raise ProviderError(f"anthropic: model or endpoint not found: {model} ({e.message})") from e
        except a.BadRequestError as e:
            raise ProviderError(f"anthropic: bad request ({e.message})") from e
        except a.RateLimitError as e:
            raise ProviderError(f"anthropic: rate limited after retries ({e.message})", retryable=True) from e
        except a.APIStatusError as e:
            raise ProviderError(f"anthropic: API error {e.status_code} ({e.message})", retryable=e.status_code >= 500) from e
        except a.APIConnectionError as e:
            raise ProviderError(f"anthropic: connection error ({e})", retryable=True) from e

        text_parts, calls = [], []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {})))

        stop = {
            "end_turn": "end",
            "tool_use": "tool_use",
            "max_tokens": "max_tokens",
            "refusal": "refusal",
        }.get(resp.stop_reason or "", "other")
        u = resp.usage
        usage = Usage(
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )
        if stop == "refusal":
            details = getattr(resp, "stop_details", None)
            cat = getattr(details, "category", None) if details else None
            text_parts.append(f"[refused{f': {cat}' if cat else ''}]")
        return ChatResponse(
            text="\n".join(text_parts).strip(),
            tool_calls=calls,
            stop_reason=stop,
            usage=usage,
            model=resp.model,
            raw={"provider": "anthropic", "content": [b.to_dict() for b in resp.content]},
        )
