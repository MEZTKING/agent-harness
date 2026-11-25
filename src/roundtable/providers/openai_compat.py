"""Any OpenAI-compatible chat API: DeepSeek, OpenAI, Gemini (OpenAI endpoint),
OpenRouter, Groq, Together, Mistral, local Ollama / vLLM ...

Role options understood here (all optional):
    temperature, reasoning_effort, extra_body (dict passed through)
"""

from __future__ import annotations

import json
import os
from typing import Any

from .base import ChatResponse, ImageProvider, Provider, ProviderError, ToolCall, ToolSpec, Usage


def _to_openai_messages(system: str, messages: list[dict[str, Any]], provider_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        role = m["role"]
        if role == "user":
            out.append({"role": "user", "content": m["content"]})
        elif role == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"] or "(empty)"})
        elif role == "assistant":
            raw = m.get("raw")
            if isinstance(raw, dict) and raw.get("provider") == provider_id:
                # same provider: replay its native message (keeps e.g. reasoning_content)
                out.append(raw["message"])
                continue
            msg: dict[str, Any] = {"role": "assistant", "content": m.get("content") or ""}
            if m.get("tool_calls"):
                msg["tool_calls"] = [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])},
                    }
                    for c in m["tool_calls"]
                ]
            out.append(msg)
    return out


def _client(api_key_env: str | None, base_url: str | None, timeout: float):
    import openai

    key = os.environ.get(api_key_env) if api_key_env else None
    # Some setups inject credentials at a proxy; the SDK still insists on a value.
    return openai, openai.OpenAI(api_key=key or "not-set", base_url=base_url, timeout=timeout, max_retries=3)


def _wrap_errors(openai, provider_id: str, model: str, api_key_env: str | None, fn):
    try:
        return fn()
    except openai.AuthenticationError as e:
        raise ProviderError(f"{provider_id}: authentication failed - set {api_key_env} ({e.message})") from e
    except openai.NotFoundError as e:
        raise ProviderError(f"{provider_id}: model or endpoint not found: {model} ({e.message})") from e
    except openai.BadRequestError as e:
        raise ProviderError(f"{provider_id}: bad request ({e.message})") from e
    except openai.RateLimitError as e:
        raise ProviderError(f"{provider_id}: rate limited after retries ({e.message})", retryable=True) from e
    except openai.APIStatusError as e:
        raise ProviderError(f"{provider_id}: API error {e.status_code} ({e.message})", retryable=e.status_code >= 500) from e
    except openai.APIConnectionError as e:
        raise ProviderError(f"{provider_id}: connection error ({e})", retryable=True) from e


class OpenAICompatProvider(Provider):
    def __init__(
        self,
        provider_id: str,
        api_key_env: str | None = "OPENAI_API_KEY",
        base_url: str | None = None,
        timeout: float = 600.0,
    ):
        self.name = provider_id
        self.api_key_env = api_key_env
        self._openai, self.client = _client(api_key_env, base_url, timeout)

    def chat(self, model, system, messages, tools=None, max_tokens=16000, options=None) -> ChatResponse:
        options = options or {}
        params: dict[str, Any] = {
            "model": model,
            "messages": _to_openai_messages(system, messages, self.name),
            "max_tokens": max_tokens,
        }
        if tools:
            params["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in tools
            ]
        for key in ("temperature", "reasoning_effort"):
            if key in options:
                params[key] = options[key]
        if options.get("extra_body"):
            params["extra_body"] = options["extra_body"]

        resp = _wrap_errors(
            self._openai, self.name, model, self.api_key_env, lambda: self.client.chat.completions.create(**params)
        )
        if not resp.choices:
            raise ProviderError(f"{self.name}: empty response", retryable=True)
        choice = resp.choices[0]
        msg = choice.message
        calls = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_invalid_json": tc.function.arguments}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args if isinstance(args, dict) else {"value": args}))

        stop = {"stop": "end", "tool_calls": "tool_use", "length": "max_tokens", "content_filter": "refusal"}.get(
            choice.finish_reason or "", "other"
        )
        u = resp.usage
        cached = 0
        if u is not None:
            details = getattr(u, "prompt_tokens_details", None)
            cached = (getattr(details, "cached_tokens", 0) or 0) if details else 0
            cached = cached or (getattr(u, "prompt_cache_hit_tokens", 0) or 0)
        usage = Usage(
            input_tokens=(u.prompt_tokens or 0) - cached if u else 0,
            output_tokens=(u.completion_tokens or 0) if u else 0,
            cache_read_tokens=cached,
        )
        native = msg.model_dump(exclude_none=True)
        native.pop("refusal", None)
        native.pop("annotations", None)
        native.pop("audio", None)
        return ChatResponse(
            text=(msg.content or "").strip(),
            tool_calls=calls,
            stop_reason=stop,
            usage=usage,
            model=resp.model or model,
            raw={"provider": self.name, "message": native},
        )


class OpenAIImagesProvider(ImageProvider):
    """OpenAI Images API (e.g. gpt-image-1). Works with any API exposing /images/generations."""

    def __init__(self, provider_id: str, api_key_env: str | None = "OPENAI_API_KEY", base_url: str | None = None, timeout: float = 600.0):
        self.name = provider_id
        self.api_key_env = api_key_env
        self._openai, self.client = _client(api_key_env, base_url, timeout)

    def generate(self, model, prompt, options=None):
        import base64

        options = options or {}
        params: dict[str, Any] = {"model": model, "prompt": prompt, "n": 1}
        for key in ("size", "quality", "background", "output_format"):
            if key in options:
                params[key] = options[key]
        resp = _wrap_errors(self._openai, self.name, model, self.api_key_env, lambda: self.client.images.generate(**params))
        item = resp.data[0]
        if getattr(item, "b64_json", None):
            data = base64.b64decode(item.b64_json)
        elif getattr(item, "url", None):
            import urllib.request

            with urllib.request.urlopen(item.url, timeout=120) as r:  # noqa: S310 - URL comes from the provider
                data = r.read()
        else:
            raise ProviderError(f"{self.name}: image response had no data")
        usage = Usage()
        if getattr(resp, "usage", None):
            usage = Usage(
                input_tokens=getattr(resp.usage, "input_tokens", 0) or 0,
                output_tokens=getattr(resp.usage, "output_tokens", 0) or 0,
            )
        return data, options.get("output_format", "png"), usage
