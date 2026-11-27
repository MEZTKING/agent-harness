"""Costs also shown in pounds ("≈ £0.95" beside the dollars; the bills stay in dollars, so dollars come first).

``rate(home, section)`` -> ``{currency: "GBP", per_usd, at, source, stale, show, words}``: pounds for one dollar.

- Once a day it reads the European Central Bank's public daily file (one GET with nothing about the owner in it)
  and keeps it in the app's folder (``rates.json``). If that fails it uses the last value it had; a typed rate
  wins over both. With pounds switched off it asks nobody.
- Settings: ``money:`` in harness.yaml (``show: usd | usd+gbp``, ``rate: auto | <number>``), with the choice made
  in the app's Settings → Spending on top (``money.json`` in the app's folder, like the tidy-up switch).
- ``stale``: the rate is more than five days old (the bank publishes on working days only).
"""

from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
RATES_FILE = "rates.json"
SETTINGS_FILE = "money.json"
STALE_DAYS = 5
RETRY = timedelta(hours=1)  # after a failed fetch, wait this long before the next try
SHOWS = ("usd", "usd+gbp")
DEFAULT = {"show": "usd+gbp", "rate": "auto"}  # the owner's decision: pounds on, the bank's rate

Opener = Callable[[str, float], bytes]
_lock = threading.Lock()


def _default_opener(url: str, timeout: float) -> bytes:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "Roundtable"})
    with urllib.request.urlopen(req, timeout=timeout) as res:  # noqa: S310 - a fixed https address
        return res.read(300_000)


OPENER: Opener = _default_opener  # tests put a made-up one here; nothing in the tests goes out


def parse_ecb(text: str) -> tuple[str, float]:
    """The bank's date and pounds for one dollar from its daily file (rates are per euro)."""
    day = re.search(r"<Cube\s+time=['\"](\d{4}-\d{2}-\d{2})['\"]", text)
    usd = re.search(r"currency=['\"]USD['\"]\s+rate=['\"]([\d.]+)['\"]", text)
    gbp = re.search(r"currency=['\"]GBP['\"]\s+rate=['\"]([\d.]+)['\"]", text)
    if not (day and usd and gbp):
        raise ValueError("not the bank's daily file")
    u, g = float(usd.group(1)), float(gbp.group(1))
    if u <= 0 or g <= 0:
        raise ValueError("a rate of nothing")
    return day.group(1), round(g / u, 6)


# -- settings -------------------------------------------------------------------------------------------
def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)


def _typed(value: Any) -> float | None:
    if value in (None, "", "auto"):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if 0 < v < 100 else None


def settings(home: str | Path | None, section: dict[str, Any] | None = None) -> dict[str, Any]:
    """harness.yaml's ``money:`` with the app's own choice on top."""
    out = dict(DEFAULT)
    for layer in (section or {}, _read(Path(home) / SETTINGS_FILE) if home else {}):
        if layer.get("show") in SHOWS:
            out["show"] = layer["show"]
        if "rate" in layer and (layer["rate"] == "auto" or _typed(layer["rate"]) is not None):
            out["rate"] = "auto" if layer["rate"] == "auto" else _typed(layer["rate"])
    return out


def save(home: str | Path, body: dict[str, Any]) -> dict[str, Any]:
    """Settings → Spending: ``{show?, rate?}`` (rate: "auto" or pounds for one dollar). Raises ValueError."""
    path = Path(home) / SETTINGS_FILE
    data = _read(path)
    if "show" in body:
        if body["show"] not in SHOWS:
            raise ValueError("Choose dollars only, or dollars and pounds.")
        data["show"] = body["show"]
    if "rate" in body:
        r = body["rate"]
        if r in ("auto", "", None):
            data["rate"] = "auto"
        elif _typed(r) is None:
            raise ValueError("Type how many pounds one dollar is worth, for example 0.79, or choose the bank's rate.")
        else:
            data["rate"] = _typed(r)
    _write(path, data)
    return data


# -- the rate -------------------------------------------------------------------------------------------
def _stale(at: str, today: date) -> bool:
    try:
        return (today - date.fromisoformat(at)).days > STALE_DAYS
    except ValueError:
        return True


def _nice_day(at: str) -> str:
    try:
        d = date.fromisoformat(at)
        return f"{d.day} {d.strftime('%b')}"
    except ValueError:
        return at


def rate(home: str | Path | None, section: dict[str, Any] | None = None, opener: Opener | None = None,
         now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    s = settings(home, section)
    out: dict[str, Any] = {"currency": "GBP", "per_usd": None, "at": "", "source": "none", "stale": False,
                           "show": s["show"], "setting": s["rate"]}
    if s["rate"] != "auto":
        out.update(per_usd=float(s["rate"]), source="typed", at=now.date().isoformat())
        return _words(out)
    if s["show"] == "usd":
        return _words(out)  # pounds are off: no request to anyone
    cache_path = Path(home) / RATES_FILE if home else None
    with _lock:
        cache = _read(cache_path) if cache_path else {}
        fetched = cache.get("fetched", "")
        tried = cache.get("tried", "")
        due = fetched[:10] != now.date().isoformat()
        try:
            recent_try = tried and now - datetime.fromisoformat(tried) < RETRY
        except ValueError:
            recent_try = False
        if due and not recent_try:
            cache["tried"] = now.isoformat()
            try:
                at, per_usd = parse_ecb((opener or OPENER)(ECB_URL, 8.0).decode("utf-8", errors="replace"))
                cache.update(at=at, per_usd=per_usd, fetched=now.isoformat())
            except Exception:  # noqa: BLE001 - offline, the bank's file changed: the last value stays
                pass
            if cache_path:
                try:
                    _write(cache_path, cache)
                except OSError:
                    pass
    if cache.get("per_usd"):
        fresh = cache.get("fetched", "")[:10] == now.date().isoformat()
        out.update(per_usd=float(cache["per_usd"]), at=cache.get("at", ""), source="ecb" if fresh else "saved",
                   stale=_stale(cache.get("at", ""), now.date()))
    return _words(out)


def _words(r: dict[str, Any]) -> dict[str, Any]:
    p = r.get("per_usd")
    if r["show"] == "usd":
        r["words"] = "Costs are shown in dollars only."
    elif not p:
        r["words"] = "No pound rate yet: costs show in dollars. It tries the bank again within the hour."
    elif r["source"] == "typed":
        r["words"] = f"$1 = £{p:.4f}, the rate you typed. Pounds are a guide: the bills are in dollars."
    else:
        r["words"] = (f"$1 = £{p:.4f}, the European Central Bank's rate of {_nice_day(r['at'])}"
                      + (" (old: it couldn't get a newer one)" if r["stale"] else "")
                      + ". Pounds are a guide: the bills are in dollars.")
    return r


def pounds_text(usd: Any, per_usd: Any) -> str:
    """'≈ £0.95' for a dollar amount, or '' (no rate, or no amount). The phone's Pounds.kt does the same."""
    try:
        u = Decimal(str(usd))
        p = Decimal(str(per_usd))
    except (InvalidOperation, ValueError, TypeError):
        return ""
    if not p.is_finite() or not u.is_finite() or p <= 0 or u < 0:
        return ""
    gbp = u * p
    if gbp == 0:
        return "≈ £0.00"
    if gbp < Decimal("0.005"):  # would round to nothing
        return "≈ under £0.01"
    if gbp >= 100:
        return f"≈ £{int(gbp.quantize(Decimal('1'), rounding=ROUND_HALF_UP)):,}"
    return f"≈ £{gbp.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"
