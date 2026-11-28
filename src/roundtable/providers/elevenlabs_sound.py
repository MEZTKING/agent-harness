"""ElevenLabs: sound effects and Eleven Music, one key (wave 9).

Effects through ``POST /v1/sound-generation``, music through ``POST /v1/music``, the key in the ``xi-api-key``
header (never in a log line or an error), the credits left from ``GET /v1/user/subscription``.

The price (``docs/sound.md``, read 28 November 2026): the API is billed by the minute of sound made, $0.12 for
effects and $0.15 for music. Every call carries an explicit length, so :meth:`quote` knows the price before the
call without asking the service. The real charge is the fall in the subscription's credits read before and
after, worked into dollars with ``usd_per_credit`` when it is known; otherwise the quote.

Standard library only (``urllib``), as ``retrodiffusion.py``.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from ..core import secrets as vault
from .base import ProviderError, SoundProvider, Usage

BASE_URL = "https://api.elevenlabs.io"
USD_PER_MINUTE = {"effect": 0.12, "music": 0.15}  # docs/sound.md, read 28 November 2026
EFFECT_SECONDS = (0.5, 30.0)
MUSIC_SECONDS = (10.0, 300.0)  # (verify at the first real call)
DEFAULT_SECONDS = {"effect": 2.0, "music": 30.0}
READ_ON = "28 November 2026"
TERMS = "https://elevenlabs.io/pricing/api"
RETRY_WAIT = 2.0


def _urlopen(req, timeout):  # one place the network is reached, so tests can stand in for it
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - fixed API host


def _num(x, default: float) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if v > 0 else default


class ElevenLabsSoundProvider(SoundProvider):
    kinds = ("effect", "music")

    def __init__(self, name: str = "elevenlabs_sound", api_key_env: str = "ELEVENLABS_API_KEY",
                 base_url: str | None = None, usd_per_credit: float | None = None,
                 usd_per_minute: dict[str, float] | None = None, retry_wait: float = RETRY_WAIT):
        self.name = name
        self.api_key_env = api_key_env
        self.base_url = (base_url or BASE_URL).rstrip("/")
        self.usd_per_credit = usd_per_credit
        self.usd_per_minute = {**USD_PER_MINUTE, **(usd_per_minute or {})}
        self.retry_wait = retry_wait
        self._sub: dict[str, Any] | None = None

    # -- the shape of one call ------------------------------------------------------------------------------------
    @staticmethod
    def kind_of(options: dict[str, Any] | None) -> str:
        k = str((options or {}).get("kind") or "effect")
        return k if k in ("effect", "music") else "effect"

    def seconds(self, options: dict[str, Any] | None) -> float:
        kind = self.kind_of(options)
        lo, hi = EFFECT_SECONDS if kind == "effect" else MUSIC_SECONDS
        return max(lo, min(hi, _num((options or {}).get("seconds"), DEFAULT_SECONDS[kind])))

    def build(self, model: str, prompt: str, options: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
        """The path and JSON body for one sound (always an explicit length, so the price is known first)."""
        opts = options or {}
        kind, secs = self.kind_of(opts), self.seconds(opts)
        if kind == "music":
            body: dict[str, Any] = {"prompt": prompt, "music_length_ms": int(round(secs * 1000))}
            if model and model not in ("music", "default"):
                body["model_id"] = model
            return "/v1/music?output_format=mp3_44100_128", body
        body = {"text": prompt, "duration_seconds": round(secs, 2), "loop": bool(opts.get("loop")),
                "prompt_influence": float(opts.get("prompt_influence", 0.3))}
        if model and model not in ("effects", "sound", "default"):
            body["model_id"] = model
        return "/v1/sound-generation?output_format=mp3_44100_128", body

    # -- http -------------------------------------------------------------------------------------------------------
    def _request(self, method: str, path: str, body: dict | None = None, raw: bool = False) -> Any:
        key = vault.get(self.api_key_env) or "proxy-injected"  # the proxy puts the real key in
        req = urllib.request.Request(
            self.base_url + path, data=json.dumps(body).encode() if body is not None else None, method=method,
            headers={"xi-api-key": key, "Content-Type": "application/json",
                     "Accept": "audio/mpeg" if raw else "application/json"})
        try:
            with _urlopen(req, 180) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:400]
            try:
                d = json.loads(detail).get("detail")
                detail = (d.get("message") or d.get("status") or detail) if isinstance(d, dict) else (d or detail)
            except (ValueError, AttributeError):
                pass
            detail = str(detail).replace(key, "…") if key != "proxy-injected" else str(detail)
            low = detail.lower()
            if e.code == 401:
                raise ProviderError(f"{self.name}: the key was refused (HTTP 401). Check the ElevenLabs key in "
                                    "Settings → Services.") from e
            if e.code == 402 or "quota" in low or "credits" in low and ("out of" in low or "insufficient" in low):
                raise ProviderError(f"{self.name}: out of credits ({detail}). Top up or wait for next month's "
                                    "ElevenLabs credits, then make the sound again.", out_of_credit=True) from e
            raise ProviderError(f"{self.name}: HTTP {e.code} {detail}",
                                retryable=e.code in (408, 429, 500, 502, 503, 504)) from e
        except urllib.error.URLError as e:
            raise ProviderError(f"{self.name}: couldn't reach ElevenLabs ({e.reason}). Check the internet "
                                "connection, then try again.", retryable=True) from e
        if raw:
            return data
        try:
            return json.loads(data or b"{}")
        except ValueError as e:
            raise ProviderError(f"{self.name}: an answer that wasn't understood") from e

    def subscription(self) -> dict[str, Any]:
        self._sub = self._request("GET", "/v1/user/subscription") or {}
        return self._sub

    def _credits_left(self) -> float | None:
        try:
            s = self.subscription()
            return float(s["character_limit"]) - float(s["character_count"])
        except (ProviderError, KeyError, TypeError, ValueError):
            return None

    # -- the interface -------------------------------------------------------------------------------------------------
    def quote(self, model: str, prompt: str, options: dict[str, Any] | None = None) -> float | None:
        kind = self.kind_of(options)
        return round(self.seconds(options) / 60.0 * self.usd_per_minute[kind], 6)

    def generate(self, model: str, prompt: str, options: dict[str, Any] | None = None) -> tuple[bytes, str, Usage]:
        path, body = self.build(model, prompt, options)
        before = self._credits_left()
        try:
            data = self._request("POST", path, body, raw=True)
        except ProviderError as e:
            if not e.retryable:
                raise
            time.sleep(self.retry_wait)
            data = self._request("POST", path, body, raw=True)  # once more, the same request
        if not data:
            raise ProviderError(f"{self.name}: the sound came back empty")
        cost = self.quote(model, prompt, options)
        after = self._credits_left() if before is not None else None
        if before is not None and after is not None and self.usd_per_credit and before >= after:
            cost = round((before - after) * float(self.usd_per_credit), 6)
        ext = "wav" if data[:4] == b"RIFF" else "mp3"
        return data, ext, Usage(cost_usd=cost)

    def licence(self) -> dict[str, Any]:
        try:
            tier = str((self._sub or self.subscription()).get("tier") or "").lower()
        except ProviderError:
            tier = ""
        if not tier:
            return {"commercial": None, "words": "ElevenLabs' plan couldn't be read, so whether you may sell what it "
                    "makes isn't known.", "link": TERMS, "read_on": READ_ON, "tier": ""}
        if tier == "free":
            return {"commercial": False, "words": "ElevenLabs' free plan doesn't allow selling what it makes and "
                    "wants a credit line. A paid plan (Starter or above) does.", "link": TERMS, "read_on": READ_ON,
                    "tier": tier}
        return {"commercial": True, "words": f"ElevenLabs' paid plan ({tier}): you may use what it makes in a game "
                "you sell.", "link": TERMS, "read_on": READ_ON, "tier": tier}

    def balance(self) -> float | None:
        if not self.usd_per_credit:  # credits can't be turned into dollars: not known
            return None
        left = self._credits_left()
        if left is None:
            return None
        return round(left * float(self.usd_per_credit), 6)
