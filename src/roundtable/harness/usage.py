"""What each service and each job may use, what is left, and who has seen a project (wave 6, d3-limits).

The owner: "Money is the owner's." One agent can't run up the bill, and the owner sees how much is left.

* **The ledger.** One line per charge in ``<app home>/usage/<yyyy-mm>.jsonl``:
  ``{at, day, provider, maker, model, role, project, pid, input, output, usd}``. Numbers and names only, never
  what was sent: ``project`` is the folder's name, ``pid`` a short fingerprint of its full path (so two folders
  of the same name stay apart, and the path itself is never written). Sums are cached by file size: a file is
  read once, then only what was added since. Several projects (threads or programs) may write at once: each
  line is one append.
* **The owner's limits**, in ``usage:`` (harness.yaml, then custom.yaml on top, which the app writes)::

      usage:
        services: {deepseek: {usd_per_day: 2, usd_per_month: 20, tokens_per_day: 0}}
        jobs: {coder: {tokens_per_project: 2000000, usd_per_project: 5}}

  Zero or absent means no limit. Nothing is limited until the owner sets a figure.
* :class:`UsageStage` (an Orchestrator mixin): ``_usage_use`` writes the line after every charge, then
  - a **service at its limit** raises a ``ProviderError`` with ``out_of_credit=True``: the build loop skips that
    service for the rest of the run and the next model carries on (``_usage_blocked`` also keeps a run from
    starting a call it would have to drop). When no model is left the run pauses with
    ``_usage_out(providers)``: a :class:`ServiceCapReached` in the limit's own words;
  - a **job at its limit** raises :class:`JobCapReached` (``pause = "job_cap"``): the run pauses with one card,
    :func:`job_cap_ask` (Carry on with as much again, or Stop here).
* **What is left** (:func:`view`): per service, used today and this month against the owner's limit, with the
  real balance where the service reports one (``balance.balances``). For the coding helpers on the owner's own
  subscriptions the harness can't read what is left: it shows what it used and says so.
* **Who has seen a project** (:func:`seen`): ``[{maker, service, first, last, calls}]`` from the ledger.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..brand import NAME
from ..providers.base import ProviderError
from .agent import BudgetExceeded, OutOfCredit
from .config import section
from . import makers

SERVICE_FIELDS = ("usd_per_day", "usd_per_month", "tokens_per_day")
JOB_FIELDS = ("tokens_per_project", "usd_per_project")
PAUSES = ("service_cap", "job_cap")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
MAKER_NAMES = {"anthropic": "Anthropic", "openai": "OpenAI", "deepseek": "DeepSeek", "google": "Google",
               "zhipu": "Zhipu", "moonshot": "Moonshot", "alibaba": "Alibaba", "xai": "xAI", "meta": "Meta",
               "mistral": "Mistral", "minimax": "MiniMax"}

_WRITE = threading.Lock()  # one append at a time within this program (other programs: one write per line)
_SUMS = threading.Lock()
_CACHE: dict[str, dict[str, Any]] = {}  # ledger file -> {"offset": bytes read, "agg": its sums}


class ServiceCapReached(OutOfCredit):
    """Every model left is with a service whose limit (set by the owner) is reached."""
    pause = "service_cap"

    def __init__(self, words: str, hits: list[dict[str, Any]] | None = None):
        super().__init__(words)
        self.hits = list(hits or [])


class JobCapReached(BudgetExceeded):
    """A job (coder, reviewer…) used what the owner allowed it on this project: the run waits for the owner."""
    pause = "job_cap"

    def __init__(self, words: str, role: str = ""):
        super().__init__(words)
        self.role = role


# -- words -----------------------------------------------------------------------------------------------------
def usd(x: float | None) -> str:
    """$20 for whole amounts, $3.10 otherwise, $0.0040 under a cent."""
    n = float(x or 0)
    if n and abs(n) < 0.01:
        return f"${n:.4f}"
    return f"${n:,.0f}" if abs(n - round(n)) < 0.005 else f"${n:,.2f}"


def tokens(n: float | None) -> str:
    return f"{int(n or 0):,} tokens"


def service_name(pid: str, cfg: Any = None) -> str:
    from ..routing import provider_name

    try:
        return provider_name(pid, (getattr(cfg, "providers", None) or {}).get(pid))
    except Exception:  # noqa: BLE001 - a name is only words
        return pid


def maker_name(mid: str) -> str:
    return MAKER_NAMES.get(mid) or (mid[:1].upper() + mid[1:] if mid else "")


def job_name(role: str) -> str:
    from ..routing import job_name as name

    return name(role)


# -- where the ledger lives ----------------------------------------------------------------------------------------
def home_dir(home: str | Path | None = None) -> Path:
    if home:
        return Path(home)
    from ..desktop import app_home

    return app_home()


def ledger_dir(home: str | Path | None = None) -> Path:
    return home_dir(home) / "usage"


def project_id(root: str | Path) -> str:
    """A short fingerprint of the project's full path: tells projects apart without writing the path."""
    return hashlib.sha256(str(Path(root).resolve()).encode("utf-8")).hexdigest()[:12]


def _now() -> tuple[str, str]:
    """(UTC time, the local day) for a line."""
    return (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), datetime.now().strftime("%Y-%m-%d"))


def row_for(ref: Any, usage: Any, cost: float | None, role: str | None, root: str | Path) -> dict[str, Any]:
    """One ledger line: numbers and names only."""
    at, day = _now()
    pid, _, model = str(ref).partition("/")
    inp = sum(int(getattr(usage, k, 0) or 0) for k in ("input_tokens", "cache_read_tokens", "cache_write_tokens"))
    return {"at": at, "day": day, "provider": pid, "maker": makers.maker(ref), "model": model, "role": role or "",
            "project": Path(root).name, "pid": project_id(root), "input": inp,
            "output": int(getattr(usage, "output_tokens", 0) or 0),
            "usd": None if cost is None else round(float(cost), 6)}


def record(row: dict[str, Any], home: str | Path | None = None) -> None:
    d = ledger_dir(home)
    d.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _WRITE:
        with open(d / f"{str(row.get('day') or _now()[1])[:7]}.jsonl", "a", encoding="utf-8") as f:
            f.write(line)


# -- sums, cached by file size -------------------------------------------------------------------------------------
def _empty() -> dict[str, Any]:
    return {"services": {}, "projects": {}}


def _add(agg: dict[str, Any], r: dict[str, Any]) -> None:
    pid, day = str(r.get("provider") or ""), str(r.get("day") or "")
    toks = int(r.get("input") or 0) + int(r.get("output") or 0)
    money = r.get("usd")
    s = agg["services"].setdefault(pid, {"usd": 0.0, "tokens": 0, "calls": 0, "unpriced": 0, "days": {}})
    d = s["days"].setdefault(day, {"usd": 0.0, "tokens": 0, "calls": 0})
    for x in (s, d):
        x["usd"] += float(money or 0)
        x["tokens"] += toks
        x["calls"] += 1
    if money is None:
        s["unpriced"] += 1
    p = agg["projects"].setdefault(str(r.get("pid") or ""), {"roles": {}, "seen": {}})
    j = p["roles"].setdefault(str(r.get("role") or ""), {"usd": 0.0, "tokens": 0})
    j["usd"] += float(money or 0)
    j["tokens"] += toks
    key = f"{r.get('maker') or ''}|{pid}"
    seen_row = p["seen"].setdefault(key, {"maker": str(r.get("maker") or ""), "provider": pid,
                                          "first": r.get("at"), "last": r.get("at"), "calls": 0})
    seen_row["calls"] += 1
    at = r.get("at")
    if at and (not seen_row["first"] or at < seen_row["first"]):
        seen_row["first"] = at
    if at and (not seen_row["last"] or at > seen_row["last"]):
        seen_row["last"] = at


def _sums(path: Path, fn):
    """``fn(sums of this file)``, worked out under the cache's lock (only the lines added since are read)."""
    with _SUMS:
        key = str(path)
        try:
            size = path.stat().st_size
        except OSError:
            return fn(_empty())
        c = _CACHE.get(key)
        if c is None or size < c["offset"]:
            c = _CACHE[key] = {"offset": 0, "agg": _empty()}
        if size > c["offset"]:
            with open(path, "rb") as f:
                f.seek(c["offset"])
                data = f.read(size - c["offset"])
            end = data.rfind(b"\n") + 1  # a line still being written is read next time
            for ln in data[:end].splitlines():
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    _add(c["agg"], r)
            c["offset"] += end
        return fn(c["agg"])


def _months(home: str | Path | None) -> list[Path]:
    d = ledger_dir(home)
    return sorted(d.glob("*.jsonl")) if d.is_dir() else []


def service_used(provider: str, home: str | Path | None = None, day: str | None = None) -> dict[str, Any]:
    """{day_usd, day_tokens, month_usd, month_tokens, calls, unpriced} for one service, this month."""
    day = day or _now()[1]
    path = ledger_dir(home) / f"{day[:7]}.jsonl"

    def pick(agg):
        s = agg["services"].get(provider) or {}
        d = (s.get("days") or {}).get(day) or {}
        return {"day_usd": round(d.get("usd", 0.0), 6), "day_tokens": int(d.get("tokens", 0)),
                "month_usd": round(s.get("usd", 0.0), 6), "month_tokens": int(s.get("tokens", 0)),
                "calls": int(s.get("calls", 0)), "unpriced": int(s.get("unpriced", 0))}

    return _sums(path, pick)


def services_seen(home: str | Path | None = None, day: str | None = None) -> list[str]:
    day = day or _now()[1]
    return _sums(ledger_dir(home) / f"{day[:7]}.jsonl", lambda agg: sorted(agg["services"]))


def job_used(root: str | Path, role: str, home: str | Path | None = None) -> dict[str, Any]:
    """What one job used on one project, every month together: {usd, tokens}."""
    pid = project_id(root)
    out = {"usd": 0.0, "tokens": 0}
    for path in _months(home):
        got = _sums(path, lambda agg: dict(((agg["projects"].get(pid) or {}).get("roles") or {}).get(role) or {}))
        out["usd"] += float(got.get("usd") or 0)
        out["tokens"] += int(got.get("tokens") or 0)
    out["usd"] = round(out["usd"], 6)
    return out


def seen(root: str | Path, home: str | Path | None = None) -> list[dict[str, Any]]:
    """Which makers have received this project: [{maker, service, first, last, calls}], the earliest first."""
    pid = project_id(root)
    rows: dict[str, dict[str, Any]] = {}
    for path in _months(home):
        part = _sums(path, lambda agg: {k: dict(v) for k, v in ((agg["projects"].get(pid) or {}).get("seen")
                                                                 or {}).items()})
        for k, v in part.items():
            have = rows.get(k)
            if have is None:
                rows[k] = v
                continue
            have["calls"] += v["calls"]
            have["first"] = min(x for x in (have["first"], v["first"]) if x) if (have["first"] or v["first"]) else ""
            have["last"] = max(x for x in (have["last"], v["last"]) if x) if (have["last"] or v["last"]) else ""
    out = [{"maker": v["maker"], "service": v["provider"], "first": v["first"] or "", "last": v["last"] or "",
            "calls": v["calls"]} for v in rows.values()]
    return sorted(out, key=lambda r: (r["first"], r["maker"], r["service"]))


# -- the owner's limits ----------------------------------------------------------------------------------------------
def _number(v: Any, whole: bool, what: str) -> float | int:
    if v in (None, "", False):
        return 0
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number (0 means no limit)") from None
    if n < 0 or n != n or n == float("inf"):
        raise ValueError(f"{what} can't be below 0 (0 means no limit)")
    return int(n) if whole else round(n, 4)


def clean_limits(raw: Any) -> dict[str, Any]:
    """``{services: {id: {...}}, jobs: {role: {...}}}`` with only figures above 0. Raises ValueError in plain words."""
    raw = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {"services": {}, "jobs": {}}
    for part, fields in (("services", SERVICE_FIELDS), ("jobs", JOB_FIELDS)):
        given = raw.get(part) or {}
        if not isinstance(given, dict):
            raise ValueError(f"{part} must be a list of names with their limits")
        for name, caps in given.items():
            if not _ID.fullmatch(str(name)):
                raise ValueError(f"{name!r} isn't a service or job name")
            caps = caps if isinstance(caps, dict) else {}
            unknown = set(caps) - set(fields)
            if unknown:
                raise ValueError(f"{', '.join(sorted(unknown))} isn't a limit {NAME} knows (it knows "
                                 f"{', '.join(fields)})")
            got = {f: _number(caps.get(f), f.startswith("tokens"), f.replace("_", " ")) for f in fields}
            got = {k: v for k, v in got.items() if v}
            if got:
                out[part][str(name)] = got
    return out


def settings(cfg: Any) -> dict[str, Any]:
    """The limits: harness.yaml's ``usage:``, then the app's (custom.yaml) on top, figure by figure."""
    base = section(cfg, "usage") if cfg is not None else {}
    mine: dict[str, Any] = {}
    path = getattr(cfg, "path", None)
    if path:
        mine = _custom_usage(Path(path))
    out: dict[str, Any] = {"services": {}, "jobs": {}}
    for layer in (base, mine):
        try:
            got = clean_limits(layer)
        except ValueError:
            continue  # a limit written by hand with a mistake: the other layer still holds
        for part in ("services", "jobs"):
            for name, caps in (layer.get(part) or {}).items():
                row = {**out[part].get(str(name), {})}
                for f in (caps or {}) if isinstance(caps, dict) else ():
                    row.pop(f, None)  # this layer says it: its figure, or no limit when 0
                row.update(got[part].get(str(name), {}))
                if row:
                    out[part][str(name)] = row
                else:
                    out[part].pop(str(name), None)
    return out


_CUSTOM: dict[str, tuple[float, dict[str, Any]]] = {}


def _custom_usage(path: Path) -> dict[str, Any]:
    """custom.yaml's ``usage:``, re-read only when the file changes (it is asked after every charge)."""
    from .config import custom_path, load_custom

    p = custom_path(path)
    try:
        stamp = p.stat().st_mtime_ns
    except OSError:
        return {}
    have = _CUSTOM.get(str(p))
    if have and have[0] == stamp:
        return have[1]
    try:
        got = load_custom(path).get("usage") or {}
    except Exception:  # noqa: BLE001 - an unreadable custom.yaml is reported elsewhere
        got = {}
    got = got if isinstance(got, dict) else {}
    _CUSTOM[str(p)] = (stamp, got)
    return got


def save_limits(harness_path: str | Path, body: dict[str, Any]) -> dict[str, Any]:
    """Change some limits in custom.yaml (harness.yaml is never rewritten). ``body``: {services?, jobs?}, each
    {name: {field: figure}}; a figure of 0 takes that limit away. Returns what custom.yaml now holds."""
    from .config import load_custom, save_custom

    clean_limits(body)  # refuse the whole change on any mistake
    path = Path(harness_path)
    custom = load_custom(path)
    mine = custom.get("usage") if isinstance(custom.get("usage"), dict) else {}
    out: dict[str, Any] = {}
    for part, fields in (("services", SERVICE_FIELDS), ("jobs", JOB_FIELDS)):
        have = {k: dict(v) for k, v in (mine.get(part) or {}).items() if isinstance(v, dict)}
        for name, caps in (body.get(part) or {}).items():
            row = have.setdefault(str(name), {})
            for f in fields:
                if f in (caps or {}):
                    row[f] = _number(caps[f], f.startswith("tokens"), f)
        out[part] = {k: v for k, v in have.items() if v}
    custom["usage"] = out
    save_custom(path, custom)
    _CUSTOM.pop(str(path.parent / "custom.yaml"), None)
    return out


# -- is a limit reached? --------------------------------------------------------------------------------------------
def service_hit(limits: dict[str, Any], provider: str, home: str | Path | None = None,
                cfg: Any = None) -> dict[str, Any] | None:
    """The first of the service's limits that is reached: {provider, field, cap, used, words}, or None."""
    caps = (limits.get("services") or {}).get(provider) or {}
    if not caps:
        return None
    used = service_used(provider, home)
    name = service_name(provider, cfg)
    for field, have, when, money in (("usd_per_month", used["month_usd"], "this month", True),
                                     ("usd_per_day", used["day_usd"], "today", True),
                                     ("tokens_per_day", used["day_tokens"], "today", False)):
        cap = caps.get(field)
        if cap and have >= cap:
            amount = usd(cap) if money else tokens(cap)
            return {"provider": provider, "field": field, "cap": cap, "used": round(have, 6),
                    "words": f"The limit you set for {name} {when} ({amount}) is reached"}
    return None


def _extra(meta: dict[str, Any], role: str) -> int:
    try:
        return max(0, int((meta.get("job_cap_extra") or {}).get(role) or 0))
    except (TypeError, ValueError):
        return 0


def job_hit(limits: dict[str, Any], root: str | Path, role: str, meta: dict[str, Any],
            home: str | Path | None = None) -> dict[str, Any] | None:
    """The job's limit on this project, when reached: {role, field, cap, allowed, used, words}, or None.
    ``allowed`` is the limit times (1 + the times the owner said Carry on)."""
    caps = (limits.get("jobs") or {}).get(role) or {}
    if not caps:
        return None
    used = job_used(root, role, home)
    times = 1 + _extra(meta, role)
    for field, have, money in (("usd_per_project", used["usd"], True), ("tokens_per_project", used["tokens"], False)):
        cap = caps.get(field)
        if cap and have >= cap * times:
            allowed = cap * times
            amount = (usd(allowed) if money else tokens(allowed))
            spent = (usd(have) if money else tokens(have))
            return {"role": role, "field": field, "cap": cap, "allowed": allowed, "used": round(have, 6),
                    "words": f"The limit you set for the {job_name(role)} on this project ({amount}) is reached: "
                             f"it has used {spent}"}
    return None


# -- the stage ------------------------------------------------------------------------------------------------------
class UsageStage:
    """A mixin for Orchestrator: the ledger, the owner's limits per service and per job."""

    usage_home: str | Path | None = None  # where the ledger lives; the app's own folder when None

    def _usage_limits(self) -> dict[str, Any]:
        try:
            return settings(self.base_cfg if getattr(self.cfg, "path", None) is None else self.cfg)
        except Exception:  # noqa: BLE001 - limits that can't be read limit nothing
            return {"services": {}, "jobs": {}}

    def _usage_hits(self) -> dict[str, dict[str, Any]]:
        hits = getattr(self, "_usage_hit", None)
        if hits is None:
            hits = self._usage_hit = {}
        return hits

    def _usage_mark(self, hit: dict[str, Any]) -> None:
        """A service's limit is reached: skip it for the rest of this run, and say why once."""
        hits = self._usage_hits()
        first = hit["provider"] not in hits
        hits[hit["provider"]] = hit
        self._broke.add(hit["provider"])  # the build loop's "no point trying it again this run"
        if first:
            self.emit("usage_cap", {"provider": hit["provider"], "words": hit["words"]})

    def _usage_use(self, ref: Any, usage: Any, cost: float | None, role: str | None) -> None:
        """After every charge (Budget.on_use): write the line, then the owner's limits."""
        if ref is None:
            return
        home = self.usage_home
        try:
            record(row_for(ref, usage, cost, role, self.project.root), home)
        except OSError as e:  # the ledger is bookkeeping: it never stops a run
            self.emit("usage_error", {"error": str(e)[:300]})
            return
        limits = self._usage_limits()
        if not (limits["services"] or limits["jobs"]):
            return
        pid = str(ref).partition("/")[0]
        hit = service_hit(limits, pid, home, self.cfg)
        if hit:
            self._usage_mark(hit)
            spec = self.cfg.roles.get(role or "")
            if spec is None or spec.kind != "image":  # a picture already made is kept; the next one is skipped
                raise ProviderError(hit["words"], out_of_credit=True)
        if role:
            with self._lock:
                meta = self.project.meta()
                job = job_hit(limits, self.project.root, role, meta, home)
                if job:
                    meta["job_cap"] = {k: job[k] for k in ("role", "field", "cap", "allowed", "used", "words")}
                    self.project.save_meta(meta)
            if job:
                self.emit("usage_cap", {"role": role, "words": job["words"]})
                raise JobCapReached(job["words"], role=role)

    def _usage_blocked(self, ref: Any) -> bool:
        """True for a service whose limit is reached, so a run doesn't start a call it would have to drop."""
        pid = str(ref).partition("/")[0]
        if pid in self._usage_hits():
            return True
        limits = self._usage_limits()
        if not limits["services"]:
            return False
        hit = service_hit(limits, pid, self.usage_home, self.cfg)
        if hit:
            self._usage_mark(hit)
            return True
        return False

    def _usage_out(self, providers: list[str]) -> ServiceCapReached | None:
        """No model is left for a task: when the owner's limits are why, the pause in their words (else None:
        an account really ran out of credit)."""
        hits = [self._usage_hits()[p] for p in providers if p in self._usage_hits()]
        if not hits:
            return None
        words = "; ".join(h["words"] for h in hits)
        rest = [p for p in providers if p not in self._usage_hits()]
        if rest:
            words += f", and no credit is left with {', '.join(service_name(p, self.cfg) for p in rest)}"
        with self._lock:
            meta = self.project.meta()
            meta["service_cap"] = [{k: h[k] for k in ("provider", "field", "cap", "used", "words")} for h in hits]
            self.project.save_meta(meta)
        return ServiceCapReached(words, hits)

    def _usage_words(self, providers: list[str]) -> str | None:
        """The same, as words only."""
        e = self._usage_out(providers)
        return str(e) if e else None


# -- the owner's card -----------------------------------------------------------------------------------------------
def _stop() -> dict[str, str]:
    return {"id": "stop", "label": "Stop here", "description": "Nothing more is spent. You can carry on later."}


def job_cap_ask(orch) -> dict[str, Any] | None:
    """The card for a run paused at a limit the owner set, as plain data: {question, options, recommended,
    source}. asks.py wraps it as a money card. None: not paused at one of these limits."""
    meta = orch.project.meta()
    why = meta.get("pause")
    if meta.get("status") != "paused" or why not in PAUSES:
        return None
    at = meta.get("updated_at", "")
    if why == "job_cap":
        job = meta.get("job_cap") or {}
        role, cap, money = str(job.get("role") or ""), job.get("cap") or 0, job.get("field") == "usd_per_project"
        amount = usd(cap) if money else tokens(cap)
        q = f"{job.get('words') or 'A limit you set is reached'}. Carry on?"
        opts = [{"id": "more", "label": f"Carry on with as much again ({amount} more)",
                 "description": f"The {job_name(role)} may use {amount} more on this project, then it asks again.",
                 "confirm": f"This lets the {job_name(role)} use {amount} more on this project"
                            + (" of your credit" if money else "") + ". Carry on?"},
                _stop()]
        return {"question": q, "options": opts, "recommended": None,
                "source": {"pause": why, "at": at, "extra": float(cap) if money else 0.0, "role": role}}
    hits = meta.get("service_cap") or []
    words = "; ".join(str(h.get("words") or "") for h in hits) or str(meta.get("reason") or "A limit you set is reached")
    raised = ", ".join(f"{service_name(h.get('provider', ''), getattr(orch, 'cfg', None))} to "
                       f"{_amount(h.get('field'), 2 * (h.get('cap') or 0))} {_when(h.get('field'))}" for h in hits)
    opts = [_stop()]
    if hits:
        opts.insert(0, {"id": "more", "label": f"Raise it and carry on ({raised})",
                        "description": "Doubles the limit you set, for every project, then carries on.",
                        "confirm": f"This raises {raised}, for every project. Carry on?"})
    return {"question": f"{words}. It waits for you.", "options": opts, "recommended": None,
            "source": {"pause": why, "at": at, "extra": 0.0}}


def _amount(field: Any, cap: float) -> str:
    return tokens(cap) if str(field or "").startswith("tokens") else usd(cap)


def _when(field: Any) -> str:
    return "this month" if field == "usd_per_month" else "a day"


def apply_answer(orch, pause: str, choice: str) -> dict[str, Any]:
    """The owner's answer on that card ("stop" is asks.py's own): {"reply", "then"}."""
    meta = orch.project.meta()
    if pause == "job_cap":
        job = meta.pop("job_cap", None) or {}
        role = str(job.get("role") or "")
        extra = dict(meta.get("job_cap_extra") or {})
        extra[role] = _extra(meta, role) + 1  # as much again, once: it asks again at the new figure
        meta["job_cap_extra"] = extra
        orch.project.save_meta(meta)
        cap = job.get("cap") or 0
        allowed = cap * (1 + extra[role])
        return {"reply": f"Carrying on: the {job_name(role)} may now use up to {_amount(job.get('field'), allowed)} "
                         "on this project.", "then": "run"}
    hits = meta.pop("service_cap", None) or []
    path = getattr(getattr(orch, "base_cfg", None), "path", None)
    if hits and not path:
        from .orchestrator import HarnessError

        raise HarnessError(f"{NAME} can't find its settings file to raise the limit. Raise it in Settings → "
                           "Money, then carry on.")
    if hits:
        body: dict[str, Any] = {"services": {}}
        for h in hits:
            body["services"].setdefault(str(h["provider"]), {})[str(h["field"])] = 2 * float(h.get("cap") or 0)
        save_limits(path, body)
        for h in hits:
            getattr(orch, "_usage_hit", {}).pop(h["provider"], None)
            getattr(orch, "_broke", set()).discard(h["provider"])
    orch.project.save_meta(meta)
    words = ", ".join(f"{service_name(h['provider'], getattr(orch, 'cfg', None))}'s limit {_when(h.get('field'))} "
                      f"is now {_amount(h.get('field'), 2 * float(h.get('cap') or 0))}" for h in hits)
    return {"reply": (words + ". Carrying on.") if words else "Carrying on.", "then": "run"}


# -- what is left (Settings → Money) --------------------------------------------------------------------------------
def view(cfg: Any, home: str | Path | None = None, balances: dict[str, Any] | None = None) -> dict[str, Any]:
    """{services: [...], jobs: [...], words, note}: per service what was used today and this month against the
    owner's limits, the real balance where the service reports one, and the jobs' limits per project."""
    limits = settings(cfg)
    specs = dict(getattr(cfg, "providers", None) or {})
    ids = [p for p in specs if (specs[p] or {}).get("type") not in ("scripted", "scripted_images")]
    ids += [p for p in [*services_seen(home), *limits["services"]] if p not in ids]
    services = []
    for pid in ids:
        spec = specs.get(pid) or {}
        used = service_used(pid, home)
        caps = limits["services"].get(pid, {})
        sub = spec.get("type") == "cli"
        bal = (balances or {}).get(pid)
        name = service_name(pid, cfg)
        if sub:
            line = (f"{name}: {tokens(used['month_tokens'])} this month. Your subscription's own limit can't be read: "
                    f"this is what {NAME} used")
        elif caps.get("usd_per_month"):
            line = f"{name}: {usd(used['month_usd'])} of {usd(caps['usd_per_month'])} this month"
        elif caps.get("usd_per_day"):
            line = f"{name}: {usd(used['day_usd'])} of {usd(caps['usd_per_day'])} today"
        else:
            line = f"{name}: {usd(used['month_usd'])} this month, no limit set"
        left = {}
        if caps.get("usd_per_month"):
            left["month_usd"] = round(max(0.0, caps["usd_per_month"] - used["month_usd"]), 4)
        if caps.get("usd_per_day"):
            left["day_usd"] = round(max(0.0, caps["usd_per_day"] - used["day_usd"]), 4)
        if caps.get("tokens_per_day"):
            left["day_tokens"] = max(0, int(caps["tokens_per_day"] - used["day_tokens"]))
        hit = service_hit(limits, pid, home, cfg)
        services.append({"id": pid, "name": name, "used": used, "caps": caps, "left": left, "subscription": sub,
                         "balance": bal, "reached": hit["words"] if hit else "", "words": line,
                         "balance_words": (f"{usd(bal['amount'])} left in your {name} account" if bal else
                                           ("" if sub else f"{name} doesn't say what's left in the account")),
                         "unpriced_words": (f"{used['unpriced']} call{'s' if used['unpriced'] != 1 else ''} had no "
                                            "price, so the money count is low" if used["unpriced"] and not sub else "")})
    roles = [r for r, spec in (getattr(cfg, "roles", None) or {}).items()]
    jobs = [{"role": r, "name": job_name(r), "caps": limits["jobs"].get(r, {})} for r in roles]
    jobs += [{"role": r, "name": job_name(r), "caps": c} for r, c in limits["jobs"].items() if r not in roles]
    capped = sum(1 for s in services if s["caps"])
    words = (f"Limits set for {capped} service{'s' if capped != 1 else ''}." if capped
             else "No limits set: each project's own money limit still holds.")
    return {"services": services, "jobs": jobs, "words": words,
            "note": (f"{NAME} counts what it sent from this computer. The coding helpers on your own subscriptions "
                     "don't say what's left: their line is what was used.")}


def seen_view(root: str | Path, home: str | Path | None = None) -> dict[str, Any]:
    rows = seen(root, home)
    for r in rows:
        r["maker_name"] = maker_name(r["maker"])
        r["service_name"] = service_name(r["service"])
    names = sorted({r["maker_name"] for r in rows})
    if not rows:
        words = "No model has seen this project yet."
    elif len(names) == 1:
        words = f"Only {names[0]} has seen this project."
    else:
        words = f"{len(names)} makers have seen this project: {', '.join(names)}."
    return {"makers": rows, "words": words,
            "note": f"From {NAME}'s own record of every call, since it began keeping one (version 1.2.0)."}
