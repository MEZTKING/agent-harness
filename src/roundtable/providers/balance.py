"""The real money left with a provider, so Roundtable can check its own cost count.

Roundtable counts cost from token usage and the pricing table; a wrong price (for example
for text the model has already seen) makes that count wrong. Where a provider reports the
account balance, a run notes it at the start and the end, and the difference is the truth.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from ..core import secrets as vault
# provider base URL host -> path of its balance endpoint and how to read it
_KNOWN = {"api.deepseek.com": "/user/balance", "openrouter.ai": "/api/v1/credits"}


def balance_url(spec: dict[str, Any]) -> str | None:
    if spec.get("balance_url"):
        return str(spec["balance_url"])
    base = str(spec.get("base_url") or "").rstrip("/")
    for host, path in _KNOWN.items():
        if host in base:
            return f"https://{host}{path}"
    return None


def read_balance(spec: dict[str, Any], timeout: float = 10.0) -> dict[str, Any] | None:
    """{"amount": float, "currency": str} or None when the provider can't say."""
    url = balance_url(spec)
    key = vault.get(spec.get("api_key_env"))
    if not url or not key:
        return None
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
    except Exception:
        return None
    return parse(data)


def check_key(spec: dict[str, Any], timeout: float = 15.0) -> dict[str, Any] | None:
    """Ask the provider whether its key works, on an address that needs the key.

    {"ok": True, "balance": {...} | None}, {"ok": False, "refused": True, "status": 401}, or
    {"ok": False, "error": "..."} when it couldn't be reached; None when this provider has no such
    address (the caller then uses its model list, which needs the key on most services).
    """
    url = balance_url(spec)
    key = vault.get(spec.get("api_key_env"))
    if not url or not key:
        return None
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode() or "{}"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return {"ok": False, "refused": True, "status": e.code}
        return {"ok": False, "error": f"the service answered {e.code}"}
    except Exception as e:  # noqa: BLE001 - offline, DNS, timeout
        return {"ok": False, "error": f"couldn't reach it ({type(e).__name__})"}
    try:
        data = json.loads(body)
    except ValueError:
        data = {}
    return {"ok": True, "balance": parse(data) if isinstance(data, dict) else None}


def parse(data: dict[str, Any]) -> dict[str, Any] | None:
    d = data.get("data") if isinstance(data.get("data"), dict) else None
    if d and "total_credits" in d:  # OpenRouter: credits bought minus credits used
        try:
            return {"amount": float(d["total_credits"]) - float(d.get("total_usage") or 0), "currency": "USD"}
        except (TypeError, ValueError):
            return None
    infos = data.get("balance_infos") or []
    usd = next((b for b in infos if b.get("currency") == "USD"), infos[0] if infos else None)
    if not usd:
        return None
    try:
        return {"amount": float(usd.get("total_balance")), "currency": usd.get("currency", "USD")}
    except (TypeError, ValueError):
        return None


def balances(cfg, names: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Balances of the configured providers that report one (all of them, or just `names`)."""
    out = {}
    for name, spec in cfg.providers.items():
        if names is not None and name not in names:
            continue
        b = read_balance(spec)
        if b:
            out[name] = b
    return out
