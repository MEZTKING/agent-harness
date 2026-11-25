"""Provider-neutral types every adapter speaks.

Conversation messages are plain dicts so they serialise straight to JSON:

    {"role": "user", "content": "..."}
    {"role": "assistant", "content": "...", "tool_calls": [ToolCall-as-dict...], "raw": <provider-native>}
    {"role": "tool", "tool_call_id": "...", "name": "...", "content": "...", "is_error": False}

``raw`` holds the provider's own representation of an assistant turn (e.g.
Claude's content blocks with thinking signatures, or DeepSeek's
``reasoning_content``). Adapters replay it unchanged when the conversation
stays on the same provider, which some APIs require inside tool loops.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema (type: object)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
        )


@dataclass
class ChatResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end"  # end | tool_use | max_tokens | refusal | other
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    raw: Any = None  # provider-native assistant turn, replayed on the next call

    def as_message(self) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": self.text,
            "tool_calls": [c.to_dict() for c in self.tool_calls],
            "raw": self.raw,
        }


class ProviderError(RuntimeError):
    """A provider call failed (auth, network, rate limit after retries, bad request)."""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class Provider:
    """Chat-capable model provider."""

    name: str = "provider"

    def chat(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 16000,
        options: dict[str, Any] | None = None,
    ) -> ChatResponse:
        raise NotImplementedError


class ImageProvider:
    """Image-generation provider."""

    name: str = "images"

    def generate(self, model: str, prompt: str, options: dict[str, Any] | None = None) -> tuple[bytes, str, Usage]:
        """Return (image bytes, file extension, usage)."""
        raise NotImplementedError
