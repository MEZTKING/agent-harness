"""Prices that providers publish themselves, fetched once and kept for a day.

OpenRouter lists every model's price per token at a public address (no key needed). Roundtable
uses it for OpenRouter models that have no `pricing:` line, so estimates and budgets count them.
"""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

URL = "https://openrouter.ai/api/v1/models"
_cache: dict[str, Any] = {"at": 0.0, "prices": None}


def _fetch(timeout: float = 10.0) -> dict[str, dict[str, float]]:
    with urllib.request.urlopen(URL, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    out = {}
    for m in data.get("data", []):
        p = m.get("pricing") or {}
        try:
            price = {"input": float(p.get("prompt") or 0) * 1e6, "output": float(p.get("completion") or 0) * 1e6}
            if p.get("input_cache_read"):
                price["cache_read"] = float(p["input_cache_read"]) * 1e6
        except (TypeError, ValueError):
            continue
        out[m.get("id", "")] = price
    return out


def openrouter_price(model: str) -> dict[str, float] | None:
    if _cache["prices"] is None or time.time() - _cache["at"] > 86400:
        try:
            _cache["prices"], _cache["at"] = _fetch(), time.time()
        except Exception:  # offline or changed: no price rather than a wrong one
            _cache["prices"], _cache["at"] = _cache["prices"] or {}, time.time()
    return (_cache["prices"] or {}).get(model)
