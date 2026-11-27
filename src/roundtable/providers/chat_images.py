"""Image models reached through a chat endpoint (OpenRouter's image models: GPT Image, Nano Banana…).

These models answer a chat request that asks for `modalities: ["image", "text"]` with the picture
as a data address in `message.images`. The exact charge comes back in the usage block when asked
(OpenRouter's `usage.include`), so every picture is costed precisely.

Options: ``aspect_ratio`` (e.g. "16:9", "1:1") and ``size``: "1K", "2K" or "4K" (OpenRouter's
``image_config.image_size``), "largest" (4K, the most any of these models offers), or "WIDTHxHEIGHT" (sent as
``image_config.size``; verify at a real run which models read it). With no ``size`` nothing is sent and the
model uses its own default, so the price stays as before.
"""

from __future__ import annotations

import base64
import re
from typing import Any

from .base import ImageProvider, ProviderError, Usage
from .openai_compat import _client, _reported_cost, _wrap_errors

SIZES = ("1K", "2K", "4K")
LARGEST = "4K"
_WXH = re.compile(r"^\s*(\d{2,5})\s*[xX×]\s*(\d{2,5})\s*$")


def image_config(options: dict[str, Any]) -> dict[str, Any]:
    """The ``image_config`` block for these options ({} when neither an aspect nor a size is asked for)."""
    out: dict[str, Any] = {}
    if options.get("aspect_ratio"):  # e.g. "16:9" (Gemini image models)
        out["aspect_ratio"] = str(options["aspect_ratio"])
    size = str(options.get("size") or "").strip()
    if size:
        up = size.upper()
        m = _WXH.match(size)
        if up in SIZES:
            out["image_size"] = up
        elif up == "LARGEST":
            out["image_size"] = LARGEST
        elif m:
            out["size"] = f"{int(m.group(1))}x{int(m.group(2))}"
        else:
            raise ProviderError(f"a picture size of {size!r} isn't known: use 1K, 2K, 4K, largest or "
                                "WIDTHxHEIGHT", retryable=False)
    return out


_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}


def picture_from_message(msg: Any) -> tuple[bytes, str]:
    """The first picture in a chat answer: (bytes, extension). Raises if there's none."""
    extra = getattr(msg, "model_extra", None) or {}
    images = getattr(msg, "images", None) or extra.get("images") or []
    for img in images:
        url = (img.get("image_url") or {}).get("url") if isinstance(img, dict) else None
        if url and url.startswith("data:") and ";base64," in url:
            head, data = url.split(";base64,", 1)
            return base64.b64decode(data), _EXT.get(head[5:], "png")
    raise ProviderError("the image model answered without a picture", retryable=True)


class ChatImagesProvider(ImageProvider):
    def __init__(self, provider_id: str, api_key_env: str | None = "OPENROUTER_API_KEY",
                 base_url: str | None = "https://openrouter.ai/api/v1", timeout: float = 600.0, **client_opts):
        self.name = provider_id
        self.api_key_env = api_key_env
        self._openai, self.client = _client(api_key_env, base_url, timeout, **client_opts)

    def generate(self, model: str, prompt: str, options: dict[str, Any] | None = None) -> tuple[bytes, str, Usage]:
        options = options or {}
        extra: dict[str, Any] = {"modalities": ["image", "text"], "usage": {"include": True}}
        config = image_config(options)
        if config:
            extra["image_config"] = config
        resp = _wrap_errors(self._openai, self.name, model, self.api_key_env, lambda: self.client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}], extra_body=extra))
        if not resp.choices:
            raise ProviderError(f"{self.name}: empty answer from {model}", retryable=True)
        data, ext = picture_from_message(resp.choices[0].message)
        u = resp.usage
        return data, ext, Usage(input_tokens=getattr(u, "prompt_tokens", 0) or 0,
                                output_tokens=getattr(u, "completion_tokens", 0) or 0,
                                cost_usd=_reported_cost(u))
