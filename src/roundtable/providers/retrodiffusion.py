"""Retro Diffusion (pixel art) image provider - API v2.

Flow: POST /v2/inferences -> {task_id} -> poll GET /v2/inferences/tasks/{id}
until succeeded/failed -> result.base64_images (or output_urls for large
results). Each result reports its real USD charge (balance_cost), which is
passed to the harness budget as an exact cost.

Model reference = default style, e.g. ``retrodiffusion/rd_lite__default``.
Options (role-level in harness.yaml, overridable per task by the planner):
    style            prompt_style id, overrides the model's default style
    width, height    pixels (checked against the style's limits)
    remove_bg        transparent background
    tile_x, tile_y   seamless tiling
    seed             reproducible output
    upscale_output_factor, input_palette, frames_duration, return_spritesheet
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from ..core import secrets as vault
from .base import ImageProvider, ProviderError, Usage

BASE_URL = "https://api.retrodiffusion.ai/v2"
PASS_THROUGH = ("remove_bg", "tile_x", "tile_y", "seed", "upscale_output_factor", "input_palette",
                "frames_duration", "return_spritesheet", "strength", "input_image", "reference_images")
RETRYABLE_CODES = {"inference_failed", "provider_busy", "provider_timeout", "request_timeout"}


class RetroDiffusionProvider(ImageProvider):
    def __init__(self, provider_id: str = "retrodiffusion", api_key_env: str | None = "RETRODIFFUSION_API_KEY",
                 base_url: str | None = None, poll_interval: float = 2.0, timeout: float = 600.0):
        self.name = provider_id
        self.api_key_env = api_key_env
        self.base_url = (base_url or BASE_URL).rstrip("/")
        self.poll_interval = poll_interval
        self.timeout = timeout
        self._styles: dict[str, dict[str, Any]] | None = None

    # -- http -------------------------------------------------------------------
    def _request(self, method: str, path: str, body: dict | None = None, headers: dict | None = None) -> dict:
        key = vault.get(self.api_key_env) or "proxy-injected"  # a proxy may inject the real key
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={"X-RD-Token": key, "Content-Type": "application/json", "Accept": "application/json",
                     **(headers or {})},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 - fixed API host
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            try:
                err = json.loads(detail).get("error", {})
                detail = f"{err.get('code')}: {err.get('message')}" if err else detail
            except (json.JSONDecodeError, AttributeError):
                pass
            hint = {401: f" - check the API key ({self.api_key_env})", 402: " - insufficient Retro Diffusion balance"}
            raise ProviderError(f"{self.name}: HTTP {e.code} {detail}{hint.get(e.code, '')}",
                                retryable=e.code in (429, 500, 502, 503, 504)) from e
        except urllib.error.URLError as e:
            raise ProviderError(f"{self.name}: connection error ({e.reason})", retryable=True) from e

    # -- catalog ------------------------------------------------------------------
    def styles(self) -> dict[str, dict[str, Any]]:
        if self._styles is None:
            data = self._request("GET", "/styles/selector")
            self._styles = {s["prompt_style"]: s for s in data.get("styles", [])}
        return self._styles

    def list_models(self) -> list[str]:
        return sorted(self.styles())

    def balance(self) -> float:
        return float(self._request("GET", "/inferences/credits").get("balance", 0.0))

    def build_body(self, style: str, prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        spec = self.styles().get(style)
        if spec is None:
            raise ProviderError(f"{self.name}: unknown style {style!r} (see `roundtable image --styles`)")
        if spec.get("require_input_image") and not options.get("input_image"):
            raise ProviderError(f"{self.name}: style {style!r} needs an input image")

        def fit(value, lo, hi, default):
            v = int(value or default)
            return max(int(lo), min(int(hi), v))

        default_w = min(max(64, spec["min_width"]), spec["max_width"])
        default_h = min(max(64, spec["min_height"]), spec["max_height"])
        body: dict[str, Any] = {
            "prompt": prompt,
            "prompt_style": style,
            "width": fit(options.get("width"), spec["min_width"], spec["max_width"], default_w),
            "height": fit(options.get("height"), spec["min_height"], spec["max_height"], default_h),
            "num_images": 1,
        }
        for k in PASS_THROUGH:
            if options.get(k) is not None:
                body[k] = options[k]
        return body

    def check_cost(self, style: str, prompt: str, options: dict[str, Any] | None = None) -> float:
        body = self.build_body(style, prompt, options or {})
        body["check_cost"] = True
        res = self._submit_and_wait(body)
        return float(res.get("balance_cost") or 0.0)

    # -- generation -----------------------------------------------------------------
    def _submit_and_wait(self, body: dict[str, Any]) -> dict[str, Any]:
        headers = {} if body.get("check_cost") else {"Idempotency-Key": str(uuid.uuid4())}
        submitted = self._request("POST", "/inferences", body, headers)
        if "base64_images" in submitted or "balance_cost" in submitted:
            return submitted  # synchronous answer (e.g. check_cost)
        task_id = submitted.get("task_id")
        if not task_id:
            raise ProviderError(f"{self.name}: unexpected submit response {str(submitted)[:300]}")
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            task = self._request("GET", f"/inferences/tasks/{task_id}")
            status = task.get("status")
            if status == "succeeded":
                return task.get("result") or {}
            if status == "failed":
                err = task.get("error") or {}
                code = err.get("code") if isinstance(err, dict) else None
                msg = (err.get("message") or err.get("detail")) if isinstance(err, dict) else err
                raise ProviderError(f"{self.name}: generation failed ({code or 'error'}: {msg}) - refunded",
                                    retryable=code in RETRYABLE_CODES)
            time.sleep(self.poll_interval)
        raise ProviderError(f"{self.name}: timed out waiting for task {task_id}", retryable=True)

    def generate(self, model: str, prompt: str, options: dict[str, Any] | None = None) -> tuple[bytes, str, Usage]:
        options = options or {}
        body = self.build_body(options.get("style") or model, prompt, options)
        try:
            result = self._submit_and_wait(body)
        except ProviderError as e:
            if not e.retryable:
                raise
            time.sleep(self.poll_interval)
            result = self._submit_and_wait(body)  # docs: retry once with identical parameters

        images = result.get("base64_images") or []
        if images:
            data = base64.b64decode(images[0])
        elif result.get("output_urls"):
            with urllib.request.urlopen(result["output_urls"][0], timeout=120) as r:  # noqa: S310 - provider URL
                data = r.read()
        else:
            raise ProviderError(f"{self.name}: result had no image")
        ext = "gif" if data[:4] == b"GIF8" else "png"
        return data, ext, Usage(cost_usd=float(result.get("balance_cost") or 0.0))
