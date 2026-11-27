"""Any OpenAI-compatible chat API: DeepSeek, OpenAI, Gemini (OpenAI endpoint),
OpenRouter, Groq, Together, Mistral, local Ollama / vLLM ...

Role options understood here (all optional):
    temperature, reasoning_effort, extra_body (dict passed through)
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from ..core import secrets as vault
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


def _needs_cache_marks(model: str) -> bool:
    """Claude only re-uses what it has already read when the request marks it (cache_control); OpenAI and
    DeepSeek do it by themselves. Through a gateway (OpenRouter, Openference) the marks must be sent."""
    m = model.lower()
    return "claude" in m or m.startswith("anthropic/")


def _mark_cache(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark the system prompt and the newest user or tool message as cacheable (2 of Claude's 4 marks):
    each step then reads everything up to the previous step's mark at the cache price."""
    out = [dict(m) for m in messages]
    targets = [i for i, m in enumerate(out) if m["role"] == "system"][:1]
    last = next((i for i in range(len(out) - 1, -1, -1) if out[i]["role"] in ("user", "tool")), None)
    if last is not None and last not in targets:
        targets.append(last)
    for i in targets:
        c = out[i].get("content")
        if isinstance(c, str) and c:
            out[i]["content"] = [{"type": "text", "text": c, "cache_control": {"type": "ephemeral"}}]
    return out


def _expand(value: str) -> str:
    """Expand ${ENV_VAR} references in configured header/query values (the key vault first)."""
    text = re.sub(r"\$\{(\w+)\}", lambda m: vault.get(m.group(1)) or m.group(0), str(value))
    return os.path.expandvars(text)


def _client(api_key_env: str | None, base_url: str | None, timeout: float, auth_header: str | None = None,
            auth_prefix: str = "", headers: dict | None = None, query: dict | None = None):
    """An OpenAI SDK client for any OpenAI-compatible API.

    auth_header: send the key in this header instead of `Authorization: Bearer`
                 (e.g. Azure OpenAI uses `api-key`); auth_prefix goes before the key.
    headers/query: extra headers / URL query parameters (values may use ${ENV_VAR}).
    """
    import openai

    key = vault.get(api_key_env)
    default_headers = {k: _expand(v) for k, v in (headers or {}).items()}
    if auth_header and key:
        default_headers[auth_header] = f"{auth_prefix}{key}"
        key = None  # don't also send it as a Bearer token
    # Some setups inject credentials at a proxy (or need none, e.g. Ollama); the SDK insists on a value.
    return openai, openai.OpenAI(api_key=key or "not-set", base_url=base_url, timeout=timeout, max_retries=3,
                                 default_headers=default_headers or None,
                                 default_query={k: _expand(v) for k, v in (query or {}).items()} or None)


def list_openai_models(openai, client, provider_id: str) -> list[str]:
    return _wrap_errors(openai, provider_id, "-", None, lambda: sorted(m.id for m in client.models.list()))


def _reported_cost(u) -> float | None:
    """The charge a service put in its usage block (OpenRouter's usage.cost), if any."""
    if u is None:
        return None
    cost = getattr(u, "cost", None)
    if cost is None:
        cost = (getattr(u, "model_extra", None) or {}).get("cost")
    try:
        return float(cost) if cost is not None else None
    except (TypeError, ValueError):
        return None


def _said(e) -> str:
    """What the service itself said: its error message when the body has one, else the client's summary."""
    body = getattr(e, "body", None)
    if isinstance(body, str) and body.strip():
        return body.strip()[:300]
    if isinstance(body, dict):
        err = body.get("error", body)
        msg = err.get("message") if isinstance(err, dict) else err
        if isinstance(msg, str) and msg.strip():
            return msg.strip()[:300]
    return str(getattr(e, "message", e))[:300]


def _wrap_errors(openai, provider_id: str, model: str, api_key_env: str | None, fn):
    try:
        return fn()
    except openai.AuthenticationError as e:
        raise ProviderError(f"{provider_id}: authentication failed - check the API key{(' (' + api_key_env + ')') if api_key_env else ''} ({e.message})") from e
    except openai.NotFoundError as e:
        raise ProviderError(f"{provider_id}: model or endpoint not found: {model} ({e.message})") from e
    except openai.BadRequestError as e:
        raise ProviderError(f"{provider_id}: bad request ({e.message})") from e
    except openai.RateLimitError as e:
        raise ProviderError(f"{provider_id}: rate limited after retries ({e.message})", retryable=True) from e
    except openai.APIStatusError as e:
        if e.status_code == 402:
            raise ProviderError(f"{provider_id}: out of credit for {model} - top up your balance with "
                                f"{provider_id} ({_said(e)})", out_of_credit=True) from e
        raise ProviderError(f"{provider_id}: API error {e.status_code} ({_said(e)})", retryable=e.status_code >= 500) from e
    except openai.APIConnectionError as e:
        raise ProviderError(f"{provider_id}: connection error ({e})", retryable=True) from e


class OpenAICompatProvider(Provider):
    def __init__(
        self,
        provider_id: str,
        api_key_env: str | None = "OPENAI_API_KEY",
        base_url: str | None = None,
        timeout: float = 600.0,
        routing: str | None = None,
        **client_opts,
    ):
        self.name = provider_id
        self.api_key_env = api_key_env
        # OpenRouter tells the exact charge of each call when asked (usage.include)
        self.reports_cost = "openrouter.ai" in (base_url or "")
        # OpenRouter sends a model to one of many companies, at prices up to 30x apart for the same model:
        # by default ask for the cheapest that supports what the request needs ("price"); "throughput"
        # or "latency" for speed; "none" to leave it to OpenRouter.
        self.routing = (routing or "price") if self.reports_cost else None
        self.last_route: str | None = None  # which company answered the last call
        self._openai, self.client = _client(api_key_env, base_url, timeout, **client_opts)

    def list_models(self) -> list[str]:
        return list_openai_models(self._openai, self.client, self.name)

    def chat(self, model, system, messages, tools=None, max_tokens=16000, options=None, *,
             on_delta=None) -> ChatResponse:  # on_delta: not streamed yet (wave 8, p1-chat)
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
        if self.reports_cost:
            extra = {**params.get("extra_body", {}), "usage": {"include": True}}
            if self.routing and self.routing != "none":
                extra["provider"] = {"sort": self.routing, "require_parameters": True, **extra.get("provider", {})}
            params["extra_body"] = extra

        if _needs_cache_marks(model):
            params["messages"] = _mark_cache(params["messages"])
        resp = _wrap_errors(
            self._openai, self.name, model, self.api_key_env, lambda: self.client.chat.completions.create(**params)
        )
        self.last_route = getattr(resp, "provider", None) or (getattr(resp, "model_extra", None) or {}).get("provider")
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
            cost_usd=_reported_cost(u) if self.reports_cost else None,
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

    def __init__(self, provider_id: str, api_key_env: str | None = "OPENAI_API_KEY", base_url: str | None = None,
                 timeout: float = 600.0, **client_opts):
        self.name = provider_id
        self.api_key_env = api_key_env
        self._openai, self.client = _client(api_key_env, base_url, timeout, **client_opts)

    def list_models(self) -> list[str]:
        return [m for m in list_openai_models(self._openai, self.client, self.name) if "image" in m or "dall" in m] \
            or list_openai_models(self._openai, self.client, self.name)

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
