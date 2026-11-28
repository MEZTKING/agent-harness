"""ElevenLabs: sound effects and Eleven Music, one key (wave 9).

A stub with its frozen shape: Helper w9-sound fills it (``docs/sound.md`` has the prices and terms as read).
Effects through ``POST /v1/sound-generation``, music through ``POST /v1/music``, the key in the ``xi-api-key``
header (never in a log line), the credits left from ``GET /v1/user/subscription``.
"""

from __future__ import annotations

from typing import Any

from .base import ProviderError, SoundProvider, Usage

BASE_URL = "https://api.elevenlabs.io"


class ElevenLabsSoundProvider(SoundProvider):
    kinds = ("effect", "music")

    def __init__(self, name: str = "elevenlabs_sound", api_key_env: str = "ELEVENLABS_API_KEY",
                 base_url: str | None = None, usd_per_credit: float | None = None):
        self.name = name
        self.api_key_env = api_key_env
        self.base_url = (base_url or BASE_URL).rstrip("/")
        self.usd_per_credit = usd_per_credit

    def quote(self, model: str, prompt: str, options: dict[str, Any] | None = None) -> float | None:
        return None

    def generate(self, model: str, prompt: str, options: dict[str, Any] | None = None) -> tuple[bytes, str, Usage]:
        raise ProviderError("not built yet")
