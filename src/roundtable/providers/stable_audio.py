"""Stable Audio (Stability AI): pay as you go, a flat price a clip (wave 9).

A stub with its frozen shape: Helper w9-sound fills it (``docs/sound.md`` has the prices and terms as read).
One form ``POST /v2beta/audio/stable-audio-2/text-to-audio`` with ``Authorization: Bearer`` (never in a log
line); the credits left from ``GET /v1/user/balance``.
"""

from __future__ import annotations

from typing import Any

from .base import ProviderError, SoundProvider, Usage

BASE_URL = "https://api.stability.ai"


class StableAudioProvider(SoundProvider):
    kinds = ("effect", "music")

    def __init__(self, name: str = "stable_audio", api_key_env: str = "STABILITY_API_KEY",
                 base_url: str | None = None):
        self.name = name
        self.api_key_env = api_key_env
        self.base_url = (base_url or BASE_URL).rstrip("/")

    def quote(self, model: str, prompt: str, options: dict[str, Any] | None = None) -> float | None:
        return None

    def generate(self, model: str, prompt: str, options: dict[str, Any] | None = None) -> tuple[bytes, str, Usage]:
        raise ProviderError("not built yet")
