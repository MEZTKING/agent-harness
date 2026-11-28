"""Sound money: the cap a project may spend on sound, decided in one place (wave 9).

* ``sound.max_per_project_usd`` in harness.yaml is the owner's figure (default :data:`CAP_DEFAULT`). A project's
  own figure (``project.json`` → ``sound.max_usd``, set by the app) may lower it; the owner's tap may raise it
  again, but never above the owner's figure.
* :func:`reserve` before every call, for the quoted price, under one lock (this program's threads and other
  programs on the computer), as an append-only line in ``.harness/sound-spend.jsonl``; :func:`settle` with the
  real charge after; :func:`release` when the call failed. Money reserved and not yet settled counts as spent,
  so two sounds at once can't slip past the cap. A real charge above its quote is counted whole.
* :func:`per_sound` prices one sound for the estimate without reaching the network (None: "unpriced").

Learning may never change any of it (improve/charter.py).
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Iterable, Iterator

CAP_DEFAULT = 2.0
SPEND_FILE = Path(".harness") / "sound-spend.jsonl"
DEFAULT_SECONDS = {"effect": 2.0, "music": 30.0}  # the length a sound is priced and made at when none is asked

_LOCK = threading.Lock()


class SoundCapReached(Exception):
    """A sound would take the project past its sound cap: nothing was asked of the service."""


# -- the cap ---------------------------------------------------------------------------------------------------
def _usd(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v >= 0 and v == v and v != float("inf") else None


def owner_cap(cfg) -> float:
    """The owner's own figure: ``sound.max_per_project_usd`` in the app's settings (harness.yaml)."""
    from .config import section

    v = _usd(section(cfg, "sound").get("max_per_project_usd"))
    return CAP_DEFAULT if v is None else v


def project_sound(root) -> dict[str, Any]:
    """The project's own sound settings (``project.json`` → ``sound``): ``max_usd``, ``just_for_me``."""
    try:
        meta = json.loads((Path(root) / ".harness" / "project.json").read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, TypeError):
        return {}
    got = meta.get("sound") if isinstance(meta, dict) else None
    return dict(got) if isinstance(got, dict) else {}


def cap(cfg, root) -> float:
    """``sound.max_per_project_usd``, never above the owner's figure."""
    top = owner_cap(cfg)
    own = _usd(project_sound(root).get("max_usd")) if root is not None else None
    return round(top if own is None else min(own, top), 6)


# -- the spend file ----------------------------------------------------------------------------------------------
def _file(root) -> Path:
    return Path(root) / SPEND_FILE


@contextlib.contextmanager
def _locked(root) -> Iterator[None]:
    """One lock for this program's threads and, through a lock file, for other programs on the computer."""
    p = _file(root)
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(p) + ".lock", os.O_RDWR | os.O_CREAT, 0o644)
        try:
            if os.name == "nt":  # pragma: no cover - Windows
                import msvcrt

                os.lseek(fd, 0, 0)
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":  # pragma: no cover
                    import msvcrt

                    os.lseek(fd, 0, 0)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _append(root, row: dict[str, Any]) -> None:
    line = (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(_file(root), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def _rows(root) -> list[dict[str, Any]]:
    try:
        lines = _file(root).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("token"):
            out.append(d)
    return out


def _tally(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Each token's state: {"usd", "state": "held" | "settled" | "released", "row"}."""
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        tok, op = str(r["token"]), r.get("op")
        usd = _usd(r.get("usd")) or 0.0
        if op == "reserve":
            out.setdefault(tok, {"usd": usd, "state": "held", "row": {}})
        elif op == "settle" and tok in out:
            out[tok].update(usd=usd, state="settled", row=r.get("row") or {})
        elif op == "release" and tok in out and out[tok]["state"] == "held":
            out[tok].update(usd=0.0, state="released")
    return out


def spent(root) -> float:
    """What sound has cost this project so far, reserved money included."""
    return round(sum(t["usd"] for t in _tally(_rows(root)).values()), 6)


def lines(root) -> list[dict[str, Any]]:
    """The settled sounds, oldest first: each its row (what it was, the service) with ``usd``."""
    return [{**t["row"], "usd": t["usd"], "token": k} for k, t in _tally(_rows(root)).items() if t["state"] == "settled"]


def reserve(root, cfg, usd: float) -> str:
    """Hold ``usd`` against the cap under one lock; raises :class:`SoundCapReached`; returns a token."""
    want = _usd(usd)
    if want is None:
        raise SoundCapReached("This sound's price can't be told, so it isn't bought: the sound limit must hold.")
    limit = cap(cfg, root)
    with _locked(root):
        have = spent(root)
        if have + want > limit + 1e-9:
            raise SoundCapReached(f"This sound (about ${want:.2f}) would take the project past its ${limit:.2f} "
                                  f"for sound (${have:.2f} used), so it's made in code instead.")
        token = uuid.uuid4().hex
        _append(root, {"op": "reserve", "token": token, "usd": round(want, 6)})
    return token


def settle(root, token: str, real_usd: float, row: dict) -> None:
    """The call was made: record its real charge (``row`` is the sound's own line). Counted whole, even when it
    is above the quote: the next reserve sees it."""
    with _locked(root):
        _append(root, {"op": "settle", "token": str(token), "usd": round(_usd(real_usd) or 0.0, 6),
                       "row": dict(row or {})})


def release(root, token: str) -> None:
    """The call failed: nothing was charged, so the money held is let go."""
    with _locked(root):
        _append(root, {"op": "release", "token": str(token)})


# -- prices ------------------------------------------------------------------------------------------------------
def seconds_of(kind: str, seconds: Any) -> float:
    s = _usd(seconds)
    return s if s else DEFAULT_SECONDS.get(kind, DEFAULT_SECONDS["effect"])


def rate_key(model, kind: str) -> str:
    """The key :func:`per_sound` reads a real charge per second under (see :func:`rates`)."""
    return f"{model}#{kind}"


def rates(metric_files: Iterable[Path]) -> dict[str, float]:
    """The average real charge per second, by model and kind, from the sound rows of ``metrics.jsonl``
    (rows with ``sound_kind`` and ``sound_seconds``, a charge above 0). Keys from :func:`rate_key`."""
    sums: dict[str, list[float]] = {}
    for f in metric_files or []:
        try:
            text = Path(f).read_text(encoding="utf-8")
        except OSError:
            continue
        for ln in text.splitlines():
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if not isinstance(d, dict) or d.get("outcome") != "approved" or not d.get("sound_kind"):
                continue
            cost, secs = _usd(d.get("cost_usd")), _usd(d.get("sound_seconds"))
            if cost and secs:
                s = sums.setdefault(rate_key(d.get("model"), str(d["sound_kind"])), [0.0, 0.0])
                s[0] += cost
                s[1] += secs
    return {k: s[0] / s[1] for k, s in sums.items() if s[1]}


def listed(cfg, model, kind: str, seconds: float) -> float | None:
    """``pricing: {<model>: {per_sound | per_second | per_minute}}`` in harness.yaml (``<kind>_`` first, e.g.
    ``music_per_minute``)."""
    pricing = getattr(cfg, "pricing", None) or {}
    name = str(model)
    bare = getattr(model, "model", name.split("/", 1)[-1])
    for key in (name, bare):
        p = pricing.get(key)
        if not isinstance(p, dict):
            continue
        for k, mult in (("per_sound", 1.0), ("per_second", seconds), ("per_minute", seconds / 60.0)):
            v = _usd(p.get(f"{kind}_{k}", p.get(k)))
            if v:
                return round(v * mult, 6)
    return None


def _ref(model):
    if hasattr(model, "provider") and hasattr(model, "model"):
        return model
    from .config import ModelRef

    try:
        return ModelRef.parse(str(model))
    except ValueError:
        return None


def adapter_quote(cfg, model, kind: str, seconds: float, prompt: str = "") -> float | None:
    """The service's own quote (offline: every adapter works its price out without a call)."""
    from ..providers.base import SoundProvider

    ref = _ref(model)
    if cfg is None or ref is None:
        return None
    try:
        p = cfg.provider(ref.provider)
    except Exception:  # noqa: BLE001 - not set up here: no price
        return None
    if not isinstance(p, SoundProvider):
        return None
    try:
        q = p.quote(ref.model, prompt, {"kind": kind, "seconds": seconds})
    except Exception:  # noqa: BLE001 - a quote never stops an estimate
        return None
    return _usd(q)


def per_sound(cfg, model, kind: str, seconds: float, charges: dict[str, Any] | None = None) -> float | None:
    """The price of one sound of ``kind`` and ``seconds`` from ``model``: what the service really charged
    before (``charges``: per second under :func:`rate_key`, or per sound under the model's name), then the
    pricing table, then the adapter's quote, else None ("unpriced"). Never reaches the network."""
    kind = kind if kind in DEFAULT_SECONDS else "effect"
    secs = seconds_of(kind, seconds)
    got = charges or {}
    rate = _usd(got.get(rate_key(model, kind)))
    if rate:
        return round(rate * secs, 6)
    each = _usd(got.get(str(model)))
    if each:
        return round(each, 6)
    if cfg is None:
        return None
    return listed(cfg, model, kind, secs) or adapter_quote(cfg, model, kind, secs)


def quote(cfg, model, prompt: str, options: dict[str, Any] | None) -> float | None:
    """What the stage reserves before one sound: the pricing table, else the adapter's quote."""
    opts = options or {}
    kind = str(opts.get("kind") or "effect")
    kind = kind if kind in DEFAULT_SECONDS else "effect"
    secs = seconds_of(kind, opts.get("seconds"))
    return listed(cfg, model, kind, secs) or adapter_quote(cfg, model, kind, secs, prompt)


def money(x: float | None) -> str:
    return "unpriced" if x is None else f"${x:.2f}"


def estimate_line(sound_usd: float | None, cfg, root=None) -> str:
    """The plan page's one line: "Sound: about $0.38 of your $2"."""
    limit = cap(cfg, root) if root is not None else owner_cap(cfg)
    lim = f"${limit:g}" if float(limit).is_integer() else f"${limit:.2f}"
    if sound_usd is None:
        return f"Sound: the price isn't known yet (at most {lim})"
    return f"Sound: about ${sound_usd:.2f} of your {lim}"
