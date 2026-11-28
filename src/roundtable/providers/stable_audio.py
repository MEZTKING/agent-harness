"""Stable Audio (Stability AI): pay as you go, a flat price a clip (wave 9).

One form ``POST /v2beta/audio/<model>/text-to-audio`` with ``Authorization: Bearer`` (never in a log line or
an error); the credits left from ``GET /v1/user/balance``.

The price (``docs/sound.md``, read 28 November 2026): credits at $0.01 each, Stable Audio 2.5 (and 3.0) 8 credits
a clip whatever its length. :meth:`quote` is that flat figure; the real charge is the fall in the balance read
before and after, else the quote. Standard library only (``urllib``).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from ..core import secrets as vault
from .base import ProviderError, SoundProvider, Usage

BASE_URL = "https://api.stability.ai"
USD_PER_CREDIT = 0.01
CREDITS = {"stable-audio-2.5": 8.0, "stable-audio-2": 8.0, "stable-audio-3": 8.0}  # docs/sound.md (verify 3.0)
DEFAULT_MODEL = "stable-audio-2.5"
SECONDS = (1.0, 190.0)
DEFAULT_SECONDS = {"effect": 2.0, "music": 30.0}
READ_ON = "28 November 2026"
TERMS = "https://stability.ai/license"
RETRY_WAIT = 2.0


def _urlopen(req, timeout):  # one place the network is reached, so tests can stand in for it
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - fixed API host


def _num(x, default: float) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if v > 0 else default


class StableAudioProvider(SoundProvider):
    kinds = ("effect", "music")

    def __init__(self, name: str = "stable_audio", api_key_env: str = "STABILITY_API_KEY",
                 base_url: str | None = None, credits: dict[str, float] | None = None, retry_wait: float = RETRY_WAIT):
        self.name = name
        self.api_key_env = api_key_env
        self.base_url = (base_url or BASE_URL).rstrip("/")
        self.credits = {**CREDITS, **(credits or {})}
        self.retry_wait = retry_wait

    @staticmethod
    def model_of(model: str) -> str:
        m = (model or "").strip()
        return m if m and m not in ("default", "sound", "music", "effects") else DEFAULT_MODEL

    def seconds(self, options: dict[str, Any] | None) -> float:
        k = str((options or {}).get("kind") or "effect")
        return max(SECONDS[0], min(SECONDS[1], _num((options or {}).get("seconds"), DEFAULT_SECONDS.get(k, 2.0))))

    def form(self, model: str, prompt: str, options: dict[str, Any] | None) -> tuple[str, dict[str, str]]:
        """The path and the form fields of one clip."""
        opts = options or {}
        fields = {"prompt": prompt, "duration": f"{self.seconds(opts):g}",
                  "output_format": "wav" if opts.get("format") == "wav" else "mp3"}
        if opts.get("seed") is not None:
            fields["seed"] = str(int(opts["seed"]))
        return f"/v2beta/audio/{self.model_of(model)}/text-to-audio", fields

    # -- http ------------------------------------------------------------------------------------------------------
    def _request(self, method: str, path: str, fields: dict[str, str] | None = None, raw: bool = False) -> Any:
        key = vault.get(self.api_key_env) or "proxy-injected"  # the proxy puts the real key in
        headers = {"Authorization": f"Bearer {key}", "Accept": "audio/*" if raw else "application/json"}
        data = None
        if fields is not None:  # multipart/form-data, as the API asks
            boundary = uuid.uuid4().hex
            parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
                     for k, v in fields.items()]
            data = ("".join(parts) + f"--{boundary}--\r\n").encode("utf-8")
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        try:
            with _urlopen(req, 300) as r:
                body = r.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:400]
            try:
                d = json.loads(detail)
                errs = d.get("errors") or [d.get("message") or d.get("name") or detail]
                detail = "; ".join(str(x) for x in errs)
            except (ValueError, AttributeError):
                pass
            if key != "proxy-injected":
                detail = detail.replace(key, "…")
            if e.code == 401:
                raise ProviderError(f"{self.name}: the key was refused (HTTP 401). Check the Stability key in "
                                    "Settings → Services.") from e
            if e.code == 402 or "insufficient" in detail.lower() and "credit" in detail.lower():
                raise ProviderError(f"{self.name}: out of credits ({detail}). Buy Stability credits, then make the "
                                    "sound again.", out_of_credit=True) from e
            raise ProviderError(f"{self.name}: HTTP {e.code} {detail}",
                                retryable=e.code in (408, 429, 500, 502, 503, 504)) from e
        except urllib.error.URLError as e:
            raise ProviderError(f"{self.name}: couldn't reach Stability ({e.reason}). Check the internet "
                                "connection, then try again.", retryable=True) from e
        if raw:
            return body
        try:
            return json.loads(body or b"{}")
        except ValueError as e:
            raise ProviderError(f"{self.name}: an answer that wasn't understood") from e

    def _credits(self) -> float | None:
        try:
            return float(self._request("GET", "/v1/user/balance").get("credits"))
        except (ProviderError, TypeError, ValueError):
            return None

    # -- the interface ------------------------------------------------------------------------------------------------
    def quote(self, model: str, prompt: str, options: dict[str, Any] | None = None) -> float | None:
        credits = self.credits.get(self.model_of(model))
        return None if credits is None else round(credits * USD_PER_CREDIT, 6)

    def generate(self, model: str, prompt: str, options: dict[str, Any] | None = None) -> tuple[bytes, str, Usage]:
        path, fields = self.form(model, prompt, options)
        before = self._credits()
        try:
            data = self._request("POST", path, fields, raw=True)
        except ProviderError as e:
            if not e.retryable:
                raise
            time.sleep(self.retry_wait)
            data = self._request("POST", path, fields, raw=True)  # once more, the same request
        if not data:
            raise ProviderError(f"{self.name}: the sound came back empty")
        cost = self.quote(model, prompt, options)
        after = self._credits() if before is not None else None
        if before is not None and after is not None and before >= after:
            cost = round((before - after) * USD_PER_CREDIT, 6)
        ext = "wav" if data[:4] == b"RIFF" else "mp3"
        return data, ext, Usage(cost_usd=cost)

    def licence(self) -> dict[str, Any]:
        return {"commercial": True, "words": "Stability's Community Licence: you may sell what it makes while your "
                "yearly revenue is under $1 million (above that, an Enterprise licence).", "link": TERMS,
                "read_on": READ_ON}

    def balance(self) -> float | None:
        c = self._credits()
        return None if c is None else round(c * USD_PER_CREDIT, 6)
