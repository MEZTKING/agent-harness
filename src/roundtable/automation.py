"""Automations: work that starts by itself.

Three kinds, each with its last run, its next run and what it made:

* **schedule** – "every weekday at 9:00", "every Sunday", "once on 2026-12-01 at 9:00": plans a new idea, plans a
  project's next goal, checks the models are working (a health check) or backs up the settings and plans;
* **issues** – open GitHub issues with a chosen label in a chosen repository become new ideas (a new plan) or
  tasks on an existing project (its next goal, planned into tasks);
* **ci** – a failed check (GitHub Actions run) on a watched repository and branch becomes a fix task on a project,
  with the failing job's last lines.

GitHub is asked, never the other way round (no public address opens the PC: plans/notes-for-owner.md): issues and
runs are read through GitHub's REST API with the owner's GitHub key (``ROUNDTABLE_GITHUB_TOKEN`` entered on the
Automations page, else the phone's hub key ``ROUNDTABLE_HUB_TOKEN``), held in the in-memory vault
(``core/secrets.py``) and sent to api.github.com only. Each automation is asked at most every ``poll_minutes``.

**Money is the owner's.** An automation plans (that is how the estimate is made: a few cents) and the build waits
for the owner's OK, the same card as any plan. Only with **start by itself** switched on for that automation, and
while the estimate fits what's left of its spending limit, it approves and builds, the run itself capped at what's
left. A health check (it calls the models) waits on the Automations page for "Start it" unless it may start by
itself. A backup costs nothing and just runs. Once an automation has spent its limit it asks first again.

**Once per slot**, even after a restart and across machines: each machine keeps its own state
(``<app home>/automations/state-<machine>.json``: last slot, last run, what it made, issues and runs already
handled), and with a hub every slot, issue and run is claimed first (``automations/<id>/<slot>.json`` in the hub,
written and read back, as sync.py's project claims), so the PC and the phone never both act on one. A slot missed
while the computer was off still fires within ``catch_up_hours`` (6); older ones are skipped.

Times are stored in UTC and shown in the owner's own time: a schedule keeps the time zone it was saved in.

Where the settings are: ``automation:`` in harness.yaml (``enabled``, ``poll_minutes``, ``catch_up_hours``,
``projects_dir``, ``max_new_per_poll`` and ``list``: automations written by hand, ``when`` in plain words) and the
list the app edits, ``<app home>/automations/automations.json``.

Runs inside the desktop app's auto-sync (``app_tick``) and ``roundtable automation --watch 60``.

The schedule's arithmetic (catch-up window, early wake, a schedule keeping its zone, the plain summary) follows
Munder Difflin's ``src/shared/weeklySchedule.ts`` (MIT, Copyright (c) 2026 Chaitanya Giri); the next-run words
follow DSH Mobile's ``AutomationPresentation.kt`` (MIT, Copyright (c) 2026 DSH Mobile contributors).
"""

from __future__ import annotations

import json
import re
import secrets as _random
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .core import secrets as vault

TOKEN_KEY = "ROUNDTABLE_GITHUB_TOKEN"  # the owner's GitHub key, entered on the Automations page
TOKEN_FALLBACKS = ("ROUNDTABLE_HUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN")
vault.remember_name(TOKEN_KEY)  # workers' commands never see it (harness/safeenv.py)

API = "https://api.github.com"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_WORDS = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday", "fri": "Friday",
             "sat": "Saturday", "sun": "Sunday"}
KINDS = ("schedule", "issues", "ci")
WHATS = ("idea", "goal", "health", "backup")
WHATS += ("learn",)  # wave 7: learning within its weekly allowance (improve/wallet.py)
CATCH_UP_H = 6.0  # a slot missed while the computer was off still fires this long after
EARLY_S = 5  # a wake this close before a slot was that slot's
POLL_MINUTES = 5.0
MAX_NEW = 3  # issues or failed runs turned into work per poll, so an old label can't start 50 plans at once
LOG_LINES = 40
KEEP_MADE = 20
BUSY_STATES = ("running", "planning")
FAILED = ("failure", "timed_out", "startup_failure")
HEALTH_MAX_USD = 1.00

_lock = threading.RLock()


class AutomationError(ValueError):
    """Something the owner can fix; the message says what to do."""


# -- time ------------------------------------------------------------------------------------------------
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(t: datetime | None) -> str | None:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def parse_iso(text: Any) -> datetime | None:
    if not text:
        return None
    try:
        t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def zone_of(when: dict[str, Any]):
    """The schedule's own clock: its IANA zone, else the offset saved with it (a computer without the zone
    database), else this computer's time."""
    name = when.get("zone")
    if name:
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(str(name))
        except Exception:  # unknown here (Windows without tzdata): the offset it was saved with
            pass
    if when.get("offset_min") is not None:
        try:
            return timezone(timedelta(minutes=int(when["offset_min"])))
        except (TypeError, ValueError):
            pass
    return datetime.now().astimezone().tzinfo


def _hm(text: Any) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(text or "").strip())
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        raise AutomationError("Give the time as hours and minutes, like 09:00.")
    return int(m[1]), int(m[2])


def _at(d: date, hm: tuple[int, int], tz) -> datetime:
    """The UTC instant of a wall-clock time on a day, in the schedule's zone (calendar fields, not adding
    hours, so a clock change lands on the same wall time)."""
    return datetime(d.year, d.month, d.day, hm[0], hm[1], tzinfo=tz).astimezone(timezone.utc)


def _once_at(when: dict[str, Any]) -> datetime | None:
    try:
        local = datetime.fromisoformat(str(when.get("at") or ""))
    except ValueError:
        return None
    return _at(local.date(), (local.hour, local.minute), zone_of(when))


def previous_slot(when: dict[str, Any], now: datetime) -> datetime | None:
    """The most recent slot at or before ``now``."""
    if when.get("kind") == "once":
        t = _once_at(when)
        return t if t and t <= now else None
    days, hm, tz = when.get("days") or [], _hm(when.get("time")), zone_of(when)
    today = now.astimezone(tz).date()
    for off in range(0, -9, -1):
        d = today + timedelta(days=off)
        if DAYS[d.weekday()] in days:
            t = _at(d, hm, tz)
            if t <= now:
                return t
    return None


def next_slot(when: dict[str, Any], now: datetime) -> datetime | None:
    """The first slot strictly after ``now``."""
    if when.get("kind") == "once":
        t = _once_at(when)
        return t if t and t > now else None
    days, hm, tz = when.get("days") or [], _hm(when.get("time")), zone_of(when)
    today = now.astimezone(tz).date()
    for off in range(9):
        d = today + timedelta(days=off)
        if DAYS[d.weekday()] in days:
            t = _at(d, hm, tz)
            if t > now:
                return t
    return None


def due_slot(a: dict[str, Any], st: dict[str, Any], now: datetime, catch_up_h: float = CATCH_UP_H) -> datetime | None:
    """The slot to fire now, or None: it has passed, it came after the automation was made, it hasn't been fired
    and it isn't older than the catch-up window."""
    when = a.get("when") or {}
    prev = previous_slot(when, now)
    if not prev:
        return None
    made = parse_iso(a.get("created_at"))
    if made and prev < made - timedelta(seconds=EARLY_S):
        return None
    last = parse_iso(st.get("last_slot"))
    if last and prev <= last + timedelta(seconds=EARLY_S):
        return None
    if now - prev > timedelta(hours=catch_up_h):
        return None
    return prev


def when_words(when: dict[str, Any]) -> str:
    """"Weekdays at 09:00 (Europe/London)", "Mondays and Thursdays at 14:30", "Once on 1 December 2026 at 09:00"."""
    zone = f" ({when['zone']})" if when.get("zone") else ""
    if when.get("kind") == "once":
        try:
            t = datetime.fromisoformat(str(when.get("at")))
        except ValueError:
            return "Once (no time set)"
        return f"Once on {t.day} {t:%B %Y} at {t:%H:%M}{zone}"
    days = [d for d in DAYS if d in (when.get("days") or [])]
    at = f"at {when.get('time')}{zone}"
    if len(days) == 7:
        return f"Every day {at}"
    if days == list(DAYS[:5]):
        return f"Weekdays {at}"
    if days == ["sat", "sun"]:
        return f"Weekends {at}"
    names = [DAY_WORDS[d] + "s" for d in days]
    if not names:
        return "No days picked"
    return f"{', '.join(names[:-1])} and {names[-1]} {at}" if len(names) > 1 else f"{names[0]} {at}"


def normalise_when(raw: Any) -> dict[str, Any]:
    """A schedule as the app or harness.yaml gives it: a dict, or plain words."""
    if isinstance(raw, str):
        return parse_schedule(raw)
    if not isinstance(raw, dict):
        raise AutomationError("Say when it should run, for example every weekday at 09:00.")
    out: dict[str, Any] = {}
    for k in ("zone", "offset_min"):
        if raw.get(k) not in (None, ""):
            out[k] = raw[k]
    if raw.get("kind") == "once" or raw.get("at"):
        try:
            t = datetime.fromisoformat(str(raw.get("at") or "").replace("Z", ""))
        except ValueError:
            raise AutomationError("Pick the day and the time it should run.") from None
        return {"kind": "once", "at": t.strftime("%Y-%m-%dT%H:%M"), **out}
    days = [str(d).lower()[:3] for d in raw.get("days") or []]
    days = [d for d in DAYS if d in days]
    if not days:
        raise AutomationError("Pick at least one day.")
    h, m = _hm(raw.get("time") or "09:00")
    return {"kind": "weekly", "days": days, "time": f"{h:02d}:{m:02d}", **out}


_DAY_RE = {d: re.compile(rf"\b{d}[a-z]*\b") for d in DAYS}


def parse_schedule(text: str, zone: str | None = None) -> dict[str, Any]:
    """Plain words to a schedule: "every weekday at 9:00", "every Sunday", "weekends at 10am", "daily at 18:30",
    "every Monday and Thursday at 9", "once on 2026-12-01 at 9:00", "tomorrow at 7pm". Default time 09:00."""
    t = " ".join(str(text or "").lower().replace(".", ":").split())
    hm = (9, 0)
    tm = re.search(r"\bat (\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", t) or re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?\b", t) \
        or re.search(r"\b(\d{1,2})()\s*(am|pm)\b", t)
    if "noon" in t or "midday" in t:
        hm = (12, 0)
    elif "midnight" in t:
        hm = (0, 0)
    elif tm:
        h, m = int(tm[1]), int(tm[2] or 0)
        if tm[3] == "pm" and h < 12:
            h += 12
        if tm[3] == "am" and h == 12:
            h = 0
        if h > 23 or m > 59:
            raise AutomationError(f"{tm[0].replace('at ', '')} isn't a time of day. Give it like 09:00.")
        hm = (h, m)
    base = {"zone": zone} if zone else {}
    dm = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t) or re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)
    if dm or "once" in t or "today" in t or "tomorrow" in t:
        if dm and len(dm[1]) == 4:
            y, mo, d = int(dm[1]), int(dm[2]), int(dm[3])
        elif dm:  # British order: day/month/year
            d, mo, y = int(dm[1]), int(dm[2]), int(dm[3])
        else:
            local = datetime.now(zone_of(base)).date() + timedelta(days=1 if "tomorrow" in t else 0)
            y, mo, d = local.year, local.month, local.day
            if "today" not in t and "tomorrow" not in t:
                raise AutomationError("Say which day, for example “once on 2026-12-01 at 9:00”.")
        try:
            day = date(y, mo, d)
        except ValueError:
            raise AutomationError("That date doesn't exist. Give it like 2026-12-01.") from None
        return {"kind": "once", "at": f"{day.isoformat()}T{hm[0]:02d}:{hm[1]:02d}", **base}
    if re.search(r"\bweekdays?\b|\bworking days?\b", t):
        days = list(DAYS[:5])
    elif re.search(r"\bweekends?\b", t):
        days = ["sat", "sun"]
    elif re.search(r"\b(every ?day|daily|each day|every morning|every evening|every night)\b", t):
        days = list(DAYS)
    else:
        days = [d for d in DAYS if _DAY_RE[d].search(t)]
    if not days:
        raise AutomationError("Say when, for example “every weekday at 9:00”, “every Sunday” or "
                              "“once on 2026-12-01 at 9:00”.")
    return {"kind": "weekly", "days": days, "time": f"{hm[0]:02d}:{hm[1]:02d}", **base}


# -- where it lives ----------------------------------------------------------------------------------------
def app_home(home: str | Path | None = None) -> Path:
    if home:
        return Path(home)
    from .desktop import app_home as default_home

    return default_home()


def _dir(home: Path) -> Path:
    return home / "automations"


def _list_file(home: Path) -> Path:
    return _dir(home) / "automations.json"


def _state_file(home: Path, machine: dict[str, str]) -> Path:
    from .sync import slug

    return _dir(home) / f"state-{slug(machine['id'], 60)}.json"


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _me(machine: dict[str, str] | None) -> dict[str, str]:
    if machine:
        return machine
    from .sync import this_machine

    return this_machine()


def settings(cfg) -> dict[str, Any]:
    """``automation:`` in harness.yaml, with the defaults."""
    from .harness.config import section

    s = section(cfg, "automation") if cfg else {}
    return {"enabled": bool(s.get("enabled", True)), "poll_minutes": float(s.get("poll_minutes") or POLL_MINUTES),
            "catch_up_hours": float(s.get("catch_up_hours") or CATCH_UP_H),
            "max_new_per_poll": int(s.get("max_new_per_poll") or MAX_NEW),
            "projects_dir": s.get("projects_dir") or "", "list": s.get("list") or []}


def saved(home: Path) -> list[dict[str, Any]]:
    data = _read(_list_file(home), {})
    return [a for a in (data.get("automations") or []) if isinstance(a, dict)]


def _save_list(home: Path, items: list[dict[str, Any]]) -> None:
    _write(_list_file(home), {"automations": items})


def every(cfg, home: Path) -> list[dict[str, Any]]:
    """Every automation: the app's list, then harness.yaml's (``source: settings``, edited there)."""
    out = []
    for a in saved(home):
        try:
            out.append(normalise(a))
        except AutomationError:
            continue
    for i, raw in enumerate(settings(cfg)["list"]):
        if not isinstance(raw, dict):
            continue
        try:
            a = normalise({"id": raw.get("id") or f"settings-{i + 1}", "created_at": raw.get("created_at") or
                           "2000-01-01T00:00:00Z", **raw})
        except AutomationError:
            continue
        a["source"] = "settings"
        out.append(a)
    from .improve import wallet  # the built-in weekly learning slot, only while there's an allowance

    try:
        extra = wallet.automation(cfg) if cfg else None
    except Exception:  # noqa: BLE001 - a broken allowance setting means no learning slot
        extra = None
    if extra and not any(a["id"] == extra["id"] for a in out):
        out.append(extra)
    return out


def load_state(home: Path, machine: dict[str, str] | None = None) -> dict[str, Any]:
    return _read(_state_file(home, _me(machine)), {})


def _update_state(home: Path, aid: str, fn: Callable[[dict[str, Any]], None],
                  machine: dict[str, str] | None = None) -> dict[str, Any]:
    with _lock:
        path = _state_file(home, _me(machine))
        all_ = _read(path, {})
        st = all_.setdefault(aid, {})
        fn(st)
        _write(path, all_)
        return st


# -- one automation --------------------------------------------------------------------------------------
def normalise(raw: dict[str, Any]) -> dict[str, Any]:
    """Check an automation and put it in its saved shape; AutomationError says what's missing."""
    kind = raw.get("kind") or "schedule"
    if kind not in KINDS:
        raise AutomationError("Pick what starts it: a time, GitHub issues or a failed check.")
    a: dict[str, Any] = {"id": str(raw.get("id") or _random.token_hex(4)), "kind": kind,
                         "name": " ".join(str(raw.get("name") or "").split())[:80],
                         "on": raw.get("on", True) is not False,
                         "start_by_itself": bool(raw.get("start_by_itself")),
                         "cap_usd": round(max(0.0, float(raw.get("cap_usd") or 0)), 2),
                         "created_at": raw.get("created_at") or iso(utcnow())}
    if a["start_by_itself"] and a["cap_usd"] <= 0:
        raise AutomationError("To let it start by itself, give it a spending limit (in dollars).")
    if kind == "schedule":
        a["when"] = normalise_when(raw.get("when"))
        do = dict(raw.get("do") or {})
        what = do.get("what") or "idea"
        if what not in WHATS:
            raise AutomationError("Pick what it does: a new idea, a project's next goal, a health check or a backup.")
        a["do"] = {"what": what}
        if what in ("idea", "goal"):
            text = str(do.get("text") or "").strip()
            if not text:
                raise AutomationError("Say what to plan, in a sentence or two.")
            a["do"]["text"] = text[:4000]
        if what == "goal":
            if not do.get("project"):
                raise AutomationError("Pick the project the goal is for.")
            a["do"]["project"] = str(do["project"])
    else:
        repo = str(raw.get("repo") or "").strip().removeprefix("https://github.com/").strip("/")
        repo = repo.removesuffix(".git")
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            raise AutomationError("Give the GitHub repository as owner/name, for example acme/shop.")
        a["repo"] = repo
        if kind == "issues":
            label = str(raw.get("label") or "").strip()
            if not label:
                raise AutomationError("Say which label marks the issues to pick up, for example roundtable.")
            a["label"] = label[:50]
            a["make"] = "task" if raw.get("make") == "task" else "idea"
            if a["make"] == "task" and not raw.get("project"):
                raise AutomationError("Pick the project the tasks are for.")
        else:
            a["branch"] = str(raw.get("branch") or "main").strip() or "main"
            if not raw.get("project"):
                raise AutomationError("Pick the project the fix tasks are for.")
        if raw.get("project"):
            a["project"] = str(raw["project"])
    if raw.get("source"):
        a["source"] = raw["source"]
    if not a["name"]:
        a["name"] = default_name(a)
    return a


def _project_name(path: Any) -> str:
    return Path(str(path or "")).name or "a project"


def default_name(a: dict[str, Any]) -> str:
    if a["kind"] == "issues":
        return f"Issues labelled {a['label']} in {a['repo']}"
    if a["kind"] == "ci":
        return f"Fix failed checks on {a['repo']} {a['branch']}"
    what = a["do"]["what"]
    if what == "health":
        return "Health check"
    if what == "backup":
        return "Backup"
    first = re.split(r"(?<=[.!?])\s", a["do"]["text"])[0][:60]
    return first if what == "idea" else f"{_project_name(a['do']['project'])}: {first}"


def what_words(a: dict[str, Any]) -> str:
    """What it does, in one sentence."""
    if a["kind"] == "issues":
        to = "new ideas" if a["make"] == "idea" else f"tasks for {_project_name(a.get('project'))}"
        return f"Open GitHub issues labelled “{a['label']}” in {a['repo']} become {to}."
    if a["kind"] == "ci":
        return (f"A failed check on {a['branch']} in {a['repo']} becomes a fix task for "
                f"{_project_name(a.get('project'))}.")
    what = a["do"]["what"]
    if what == "health":
        return "Checks that your models are working."
    if what == "backup":
        return "Backs up your settings and plans."
    if what == "learn":
        return "Learns from your past runs, within its weekly allowance."
    if what == "idea":
        return f"Plans a new project: “{a['do']['text'][:140]}”."
    return f"Plans the next goal for {_project_name(a['do']['project'])}: “{a['do']['text'][:140]}”."


def money_words(a: dict[str, Any], st: dict[str, Any], cfg: Any = None) -> str:
    if a["kind"] == "schedule" and a["do"]["what"] == "backup":
        return "Costs nothing."
    if a["kind"] == "schedule" and a["do"]["what"] == "learn":
        if cfg is not None:
            from .improve import wallet

            try:
                return wallet.money_words(cfg)
            except Exception:  # noqa: BLE001
                pass
        return "Spends only learning's own weekly allowance."
    spent = float(st.get("spent_usd") or 0)
    if a["start_by_itself"]:
        left = max(0.0, a["cap_usd"] - spent)
        if left <= 0:
            return f"It has spent its limit (${a['cap_usd']:.2f}), so it asks you first again. Raise the limit to let it go on."
        return f"Starts by itself while the estimate fits what's left of its limit: ${left:.2f} of ${a['cap_usd']:.2f}."
    if a["kind"] == "schedule" and a["do"]["what"] == "health":
        return "Asks you before it starts (a check costs up to $1.00)."
    return "Planning costs a few cents; building waits for your OK."


def next_run(a: dict[str, Any], st: dict[str, Any], now: datetime) -> str | None:
    if not a["on"]:
        return None
    if a["kind"] != "schedule":
        return st.get("next_poll") or iso(now)
    when = a["when"]
    if when["kind"] == "once":
        return None if st.get("last_slot") else iso(_once_at(when))
    return iso(due_slot(a, st, now) or next_slot(when, now))


def view(a: dict[str, Any], st: dict[str, Any], now: datetime | None = None, cfg: Any = None) -> dict[str, Any]:
    """An automation as the page shows it."""
    now = now or utcnow()
    return {**a, "what": what_words(a), "when_words": when_words(a["when"]) if a["kind"] == "schedule" else
            "Looks at GitHub every few minutes", "money": money_words(a, st, cfg),
            "last_run": st.get("last_run"), "last_result": st.get("last_result") or "",
            "last_ok": st.get("last_ok", True), "next_run": next_run(a, st, now),
            "made": list(reversed(st.get("made") or []))[:10], "waiting": st.get("waiting") or [],
            "spent_usd": round(float(st.get("spent_usd") or 0), 4), "editable": a.get("source") not in ("settings", "builtin")}


# -- the app's list: add, edit, switch, remove -------------------------------------------------------------
def add(home: Path, raw: dict[str, Any]) -> dict[str, Any]:
    a = normalise({k: v for k, v in raw.items() if k not in ("id", "created_at", "source")})
    with _lock:
        items = saved(home)
        items.append(a)
        _save_list(home, items)
    return a


def edit(home: Path, aid: str, changes: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        items = saved(home)
        for i, cur in enumerate(items):
            if cur.get("id") == aid:
                merged = {**cur, **{k: v for k, v in changes.items() if k not in ("id", "created_at", "source")}}
                if "when" in changes and changes["when"] != cur.get("when"):
                    merged["created_at"] = iso(utcnow())  # a new time: no slot from before the change fires
                items[i] = normalise(merged)
                _save_list(home, items)
                return items[i]
    raise AutomationError("That automation isn't there any more. Refresh the page.")


def remove(home: Path, aid: str) -> None:
    with _lock:
        items = saved(home)
        left = [a for a in items if a.get("id") != aid]
        if len(left) == len(items):
            raise AutomationError("That automation isn't there any more. Refresh the page.")
        _save_list(home, left)


def switch(home: Path, aid: str, on: bool, cfg=None) -> dict[str, Any]:
    if any(a.get("id") == aid for a in saved(home)):
        return edit(home, aid, {"on": bool(on)})
    for a in every(cfg, home):  # one from harness.yaml: switched in this machine's state
        if a["id"] == aid:
            _update_state(home, aid, lambda st: st.__setitem__("off", not on))
            return a
    raise AutomationError("That automation isn't there any more. Refresh the page.")


# -- GitHub ---------------------------------------------------------------------------------------------
Http = Callable[[str, dict[str, str]], tuple[int, dict[str, str], bytes]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # the log's download address is fetched apart, without the key
        return None


def http_get(url: str, headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    """Roundtable's GET: (status, headers, body); a redirect is returned, not followed."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(req, timeout=30) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(4_000_000)
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read() if e.fp else b""
    except (urllib.error.URLError, OSError) as e:
        raise AutomationError(f"Couldn't reach GitHub ({getattr(e, 'reason', e)}). It tries again in a few "
                              "minutes.") from None


def github_token() -> str | None:
    for name in (TOKEN_KEY, *TOKEN_FALLBACKS):
        v = vault.get(name)
        if v:
            return v
    return None


class GitHub:
    def __init__(self, token: str | None, http: Http | None = None):
        self.token, self.http = token, http or http_get

    def _headers(self, auth: bool = True) -> dict[str, str]:
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
             "User-Agent": "roundtable-hold"}
        if auth and self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _check(self, status: int, body: bytes, repo: str) -> None:
        if status < 300:
            return
        if status == 401:
            raise AutomationError("GitHub didn't accept your GitHub key. Add a new one on the Automations page.")
        if status == 404:
            raise AutomationError(f"GitHub can't find {repo}, or your GitHub key can't read it. Check the name, "
                                  "or give the key access to that repository.")
        if status in (403, 429):
            raise AutomationError("GitHub asked the harness to slow down. It tries again in a few minutes.")
        raise AutomationError(f"GitHub answered with an error ({status}). It tries again in a few minutes.")

    def get(self, repo: str, path: str, **params: Any) -> Any:
        url = f"{API}/repos/{repo}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        status, _, body = self.http(url, self._headers())
        self._check(status, body, repo)
        return json.loads(body or b"null")

    def log(self, repo: str, job_id: int) -> str:
        """A job's log: GitHub sends a short-lived address to download it from; that one gets no key."""
        status, headers, body = self.http(f"{API}/repos/{repo}/actions/jobs/{job_id}/logs", self._headers())
        if status in (301, 302, 303, 307, 308) and headers.get("location"):
            status, _, body = self.http(headers["location"], {"User-Agent": "roundtable-hold"})
        if status >= 300:
            return ""
        return body.decode("utf-8", "replace")


_STAMP = re.compile(r"^﻿?\d{4}-\d\d-\d\dT[\d:.]+Z ?")


def last_lines(log: str, n: int = LOG_LINES) -> str:
    """The end of a job's log, without GitHub's time stamps and with any key Roundtable holds hidden."""
    lines = [_STAMP.sub("", ln.rstrip()) for ln in (log or "").splitlines()]
    lines = [ln for ln in lines if ln.strip()][-n:]
    text = "\n".join(ln[:300] for ln in lines)
    for v in vault.values():
        if len(v) >= 8:
            text = text.replace(v, "***")
    return text


def issue_items(a: dict[str, Any], issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Open issues (not pull requests) as work: a new idea, or the next goal of the chosen project."""
    out = []
    for it in issues or []:
        if not isinstance(it, dict) or it.get("pull_request") or it.get("state", "open") != "open":
            continue
        n, title = it.get("number"), " ".join(str(it.get("title") or "").split())[:200]
        body = str(it.get("body") or "").strip()[:4000]
        url = it.get("html_url") or f"https://github.com/{a['repo']}/issues/{n}"
        text = f"{title}\n\n{body}\n\n(From GitHub issue {a['repo']}#{n}: {url})".replace("\n\n\n\n", "\n\n")
        out.append({"key": f"issue-{n}", "what": "idea" if a["make"] == "idea" else "goal", "title": title,
                    "text": text, "project": a.get("project"), "link": url, "folder": f"{title}"})
    return out


def failed_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The newest finished run of each workflow, when it failed (a later green run means it's fixed)."""
    newest: dict[Any, dict[str, Any]] = {}
    for r in sorted(runs or [], key=lambda r: str(r.get("created_at") or ""), reverse=True):
        if r.get("status") != "completed":
            continue
        newest.setdefault(r.get("workflow_id") or r.get("name"), r)
    return [r for r in newest.values() if r.get("conclusion") in FAILED]


def ci_item(a: dict[str, Any], run: dict[str, Any], jobs: list[dict[str, Any]], logs: dict[Any, str]) -> dict[str, Any]:
    """A failed run as a fix task: which check, which job and step, and the job's last lines."""
    name = run.get("name") or "a check"
    bad = [j for j in jobs or [] if j.get("conclusion") in FAILED] or list(jobs or [])[:1]
    parts = [f"Fix the failing check “{name}” on the {a['branch']} branch of {a['repo']}."]
    for j in bad[:2]:
        step = next((s.get("name") for s in j.get("steps") or [] if s.get("conclusion") in FAILED), None)
        parts.append(f"The job “{j.get('name')}” failed" + (f" at the step “{step}”." if step else "."))
        tail = last_lines(logs.get(j.get("id"), ""))
        if tail:
            parts.append(f"Its last lines:\n```\n{tail}\n```")
    url = run.get("html_url") or ""
    sha = str(run.get("head_sha") or "")[:7]
    parts.append(f"(The run: {url}" + (f", commit {sha}" if sha else "") + ")")
    return {"key": f"run-{run.get('id')}", "what": "goal", "title": f"Fix “{name}” on {a['branch']}",
            "text": "\n\n".join(parts), "project": a.get("project"), "link": url}


def poll(a: dict[str, Any], gh: GitHub) -> list[dict[str, Any]]:
    """What GitHub has for this automation now, as work items (oldest first)."""
    if a["kind"] == "issues":
        issues = gh.get(a["repo"], "/issues", labels=a["label"], state="open", sort="created", direction="asc",
                        per_page=50)
        return issue_items(a, issues if isinstance(issues, list) else [])
    data = gh.get(a["repo"], "/actions/runs", branch=a["branch"], status="completed", per_page=30)
    out = []
    for run in failed_runs((data or {}).get("workflow_runs") or []):
        jobs = (gh.get(a["repo"], f"/actions/runs/{run['id']}/jobs", filter="latest") or {}).get("jobs") or []
        bad = [j for j in jobs if j.get("conclusion") in FAILED][:2]
        logs = {j.get("id"): gh.log(a["repo"], j["id"]) for j in bad if j.get("id")}
        out.append(ci_item(a, run, jobs, logs))
    return out


# -- once per slot across machines (the hub) -----------------------------------------------------------------
def claim(hub, aid: str, key: str, machine: dict[str, str], lock=None) -> bool:
    """Take a slot, an issue or a run for this machine. No hub: this machine's own state is enough. A slot
    already taken (by any machine, this one before a restart included) is refused."""
    if hub is None:
        return True
    from .sync import slug

    rel = f"automations/{slug(aid, 60)}/{slug(key, 80)}.json"
    with (lock or _lock):
        hub.store.sync(force=True)
        if hub.store.read_json(rel):
            return False
        mine = {"machine": machine["id"], "machine_name": machine.get("name", ""), "at": iso(utcnow()),
                "automation": aid, "slot": key}
        hub.store.write_json({rel: mine}, f"automation({aid}): {machine.get('name') or machine['id']} takes {key}")
        now = hub.store.read_json(rel) or {}
    return now.get("machine") == machine["id"] and now.get("at") == mine["at"]


# -- doing it --------------------------------------------------------------------------------------------
Starter = Callable[[str, str, str, Callable[[Callable[[str], None]], dict[str, Any]]], Any]


def _inline(kind: str, title: str, target: str, fn) -> Any:
    return fn(lambda s: None)


@dataclass
class Ctx:
    cfg: Any
    home: Path
    hub: Any = None
    now: datetime = field(default_factory=utcnow)
    http: Http | None = None
    start: Starter = _inline
    busy: Callable[[Path], bool] | None = None
    projects_dir: Path | None = None
    lock: Any = None
    machine: dict[str, str] | None = None
    backup_sources: Callable[[], Any] | None = None


def _projects(cfg) -> list[Path]:
    from .remote import project_dirs

    return [p.resolve() for p in project_dirs(cfg)] if cfg else []


def _target(ctx: Ctx, item: dict[str, Any]) -> Path | None:
    """The project a goal is for: only a registered project (no other folder)."""
    p = Path(str(item.get("project") or "")).expanduser()
    try:
        p = p.resolve()
    except OSError:
        return None
    return p if p in _projects(ctx.cfg) else None


def _is_busy(ctx: Ctx, root: Path | None) -> bool:
    if not root:
        return False
    if ctx.busy and ctx.busy(root):
        return True
    from .harness.orchestrator import Project

    return Project(root).meta().get("status") in BUSY_STATES if Project(root).exists else False


def _new_folder(ctx: Ctx, title: str) -> Path:
    from .sync import slug

    base = Path(ctx.projects_dir or settings(ctx.cfg)["projects_dir"] or _default_projects())
    base = base.expanduser()
    name = slug(title, 40)
    p, n = base / name, 2
    while p.exists():
        p, n = base / f"{name}-{n}", n + 1
    return p


def _record(ctx: Ctx, a: dict[str, Any], text: str, ok: bool = True, made: dict[str, Any] | None = None,
            slot: str | None = None, spent: float = 0.0) -> dict[str, Any]:
    def upd(st: dict[str, Any]) -> None:
        st["last_run"], st["last_result"], st["last_ok"] = iso(utcnow()), text, ok
        if slot:
            st["last_slot"] = slot
        if spent:
            st["spent_usd"] = round(float(st.get("spent_usd") or 0) + spent, 6)
        if made:
            st["made"] = ((st.get("made") or []) + [{"at": iso(utcnow()), **made}])[-KEEP_MADE:]

    _update_state(ctx.home, a["id"], upd, ctx.machine)
    return {"id": a["id"], "name": a["name"], "text": text, "ok": ok}


def _left(a: dict[str, Any], home: Path, machine) -> float:
    st = load_state(home, machine).get(a["id"]) or {}
    return max(0.0, a["cap_usd"] - float(st.get("spent_usd") or 0)) if a["start_by_itself"] else 0.0


def _plan_job(ctx: Ctx, a: dict[str, Any], item: dict[str, Any], root: Path, new: bool):
    """Plan the idea or the goal; the build waits for the owner's OK unless this automation may start by itself and
    the estimate fits what's left of its limit."""
    from .harness.orchestrator import Orchestrator, Project

    cfg, title = ctx.cfg, item.get("title") or item["text"][:60]

    def run(log: Callable[[str], None]) -> dict[str, Any]:
        def on_event(kind, d):
            from .ui.server import harness_event_line

            line = harness_event_line(kind, d)
            if line:
                log(line)

        before = float(Project(root).meta().get("spent_usd") or 0) if Project(root).exists else 0.0
        try:
            orch = Orchestrator(cfg, root, on_event=on_event)
            if new:
                orch.start(item["text"], require_approval=True)
            else:
                orch.extend(item["text"])
                meta = orch.project.meta()
                meta["plan_approved"] = False  # an automation's goal always waits for the owner's OK
                orch.project.save_meta(meta)
            status = orch.run()  # plans, then stops at "awaiting approval"
            doc = Project(root).plan_doc() or {}
            est = (doc.get("estimate") or {}).get("cost_usd")
            est_words = f" Its estimate: about ${est:.2f}." if est is not None else ""
            text = f"Planned “{title}” in {root.name}.{est_words}"
            left = _left(a, ctx.home, ctx.machine) - (float(Project(root).meta().get("spent_usd") or 0) - before)
            if status == "awaiting_approval" and a["start_by_itself"] and est is not None and est <= left:
                orch = Orchestrator(cfg, root, on_event=on_event)
                orch.approve()
                orch.budget.limit_usd = min(orch.budget.limit_usd, orch.budget.spent_usd + left)
                orch._journal("decision", f"Automation “{a['name']}” started the build by itself: its estimate "
                                          f"(about ${est:.2f}) fits what's left of its limit (${left:.2f}).")
                status = orch.run()
                text += f" Started building by itself (it had ${left:.2f} of its limit left); the run ended as: {status}."
            elif status == "awaiting_approval":
                why = ""
                if a["start_by_itself"]:
                    why = (f" Its estimate is more than what's left of this automation's limit (${max(left, 0):.2f})."
                           if est is not None else " It has no estimate, so it won't start by itself.")
                text += f"{why} It waits for your OK in Needs you."
            else:
                text += f" The run ended as: {status}."
            ok = True
        except Exception as e:  # the owner reads it on the page
            text, ok, status = f"Couldn't plan “{title}”: {e}", False, "error"
        spent = max(0.0, (float(Project(root).meta().get("spent_usd") or 0) if Project(root).exists else 0) - before)
        _record(ctx, a, text, ok, made={"text": title, "project": str(root), "link": item.get("link") or "",
                                        "status": status}, spent=spent)
        log(text)
        return {"status": status, "path": str(root), "text": text}

    return run


def _health_job(ctx: Ctx, a: dict[str, Any], max_cost: float):
    def run(log: Callable[[str], None]) -> dict[str, Any]:
        try:
            from .improve.probe import check, models_in_config

            chat, image = models_in_config(ctx.cfg)
            reports = check(ctx.cfg, ctx.cfg.lab_dir, chat, image, max_cost=max_cost)
            good = sum(1 for r in reports if not r.bad)
            cost = sum(float(r.cost_usd or 0) for r in reports)
            bad = [r.model for r in reports if r.bad]
            text = f"Health check: {good} of {len(reports)} models are working" + (
                f"; not working: {', '.join(bad[:5])}." if bad else ".")
            ok = not bad
        except Exception as e:
            text, ok, cost = f"The health check couldn't run: {e}", False, 0.0
        _record(ctx, a, text, ok, made={"text": "Health check", "status": "done" if ok else "problems"}, spent=cost)
        log(text)
        return {"text": text}

    return run


def _backup_job(ctx: Ctx, a: dict[str, Any]):
    def run(log: Callable[[str], None]) -> dict[str, Any]:
        from . import backup

        try:
            res = backup.backup_now(sources=ctx.backup_sources() if ctx.backup_sources else None, home=ctx.home)
            text, ok = res.message(), True
        except Exception as e:
            text, ok = f"The backup didn't work: {e}", False
        _record(ctx, a, text, ok, made={"text": "Backup", "status": "done" if ok else "failed"})
        log(text)
        return {"text": text}

    return run


def _ask_first(ctx: Ctx, a: dict[str, Any], item: dict[str, Any], why: str) -> dict[str, Any]:
    """Something that would spend: kept on the Automations page until the owner taps Start it."""
    entry = {"key": item["key"], "what": item["what"], "text": why, "at": iso(utcnow())}

    def upd(st):
        st["waiting"] = [w for w in st.get("waiting") or [] if w.get("key") != item["key"]] + [entry]

    _update_state(ctx.home, a["id"], upd, ctx.machine)
    return _record(ctx, a, why, True)


def act(ctx: Ctx, a: dict[str, Any], item: dict[str, Any], approved: bool = False) -> dict[str, Any] | None:
    """Do one piece of work: plan an idea or a goal, run a health check or a backup. None: not now (its project
    is busy); it is tried again on the next tick."""
    what = item["what"]
    if what in ("idea", "goal"):
        if what == "goal":
            root = _target(ctx, item)
            if not root:
                return _record(ctx, a, f"Couldn't add “{item.get('title') or 'the goal'}”: the project "
                                       f"{_project_name(item.get('project'))} isn't on this computer. Pick another "
                                       "one in Edit.", False)
            if _is_busy(ctx, root):
                return None
            new = False
        else:
            root, new = _new_folder(ctx, item.get("folder") or item.get("title") or "idea"), True
        try:
            ctx.start("plan", f"plan {root.name} ({a['name']})", str(root), _plan_job(ctx, a, item, root, new))
        except Exception as e:
            return _record(ctx, a, f"Couldn't start planning: {e}", False)
        return {"id": a["id"], "name": a["name"], "text": f"Planning “{item.get('title') or root.name}”…", "ok": True}
    if what == "health":
        left = _left(a, ctx.home, ctx.machine)
        if not approved and not (a["start_by_itself"] and left >= 0.05):
            return _ask_first(ctx, a, item, "A health check is due. It calls your models (up to $1.00): tap "
                                            "Start it when you want it.")
        cost = HEALTH_MAX_USD if approved else min(HEALTH_MAX_USD, left)
        ctx.start("probe", f"health check ({a['name']})", "probe", _health_job(ctx, a, cost))
        return {"id": a["id"], "name": a["name"], "text": "Health check started.", "ok": True}
    if what == "backup":
        ctx.start("backup", f"backup ({a['name']})", "backup", _backup_job(ctx, a))
        return {"id": a["id"], "name": a["name"], "text": "Backup started.", "ok": True}
    if what == "learn":
        from .improve import wallet

        job = getattr(wallet, "job", None)  # filled in by the learning loop (wave 7); until then: not now
        if not callable(job):
            return None
        ctx.start("improve", "learning", "improve", job(ctx, a))
        return {"id": a["id"], "name": a["name"], "text": "Learning started.", "ok": True}
    return None


def _schedule_item(a: dict[str, Any], slot: str) -> dict[str, Any]:
    do = a["do"]
    item = {"key": f"slot-{slot}", "what": do["what"], "title": a["name"], "text": do.get("text", ""),
            "project": do.get("project"), "folder": a["name"]}
    return item


def _still_open(ctx: Ctx, st: dict[str, Any]) -> bool:
    """A fix this automation made earlier is still being worked on (or waits for the owner)."""
    from .harness.orchestrator import Project

    last = next((m for m in reversed(st.get("made") or []) if m.get("project")), None)
    if not last or not Project(Path(last["project"])).exists:
        return False
    return Project(Path(last["project"])).meta().get("status") not in ("done", None)


def _run_schedule(ctx: Ctx, a: dict[str, Any], st: dict[str, Any], s: dict[str, Any]) -> list[dict[str, Any]]:
    when = a["when"]
    slot = due_slot(a, st, ctx.now, s["catch_up_hours"])
    if not slot:
        if when["kind"] == "once" and not st.get("last_slot"):
            t = _once_at(when)
            if t and ctx.now - t > timedelta(hours=s["catch_up_hours"]):  # missed for good
                _update_state(ctx.home, a["id"], lambda x: x.update(last_slot=iso(t)), ctx.machine)
                return [_record(ctx, a, "Missed: the harness wasn't running at that time, so it didn't run.", False)]
        return []
    item = _schedule_item(a, iso(slot))
    root = _target(ctx, item) if item["what"] == "goal" else None
    if root and _is_busy(ctx, root):
        return []  # tried again on the next tick, inside the catch-up window
    if item["what"] == "learn":
        from .improve import wallet

        if wallet.busy(ctx):
            return []  # learning never runs while a project builds: tried again inside the catch-up window
    if not claim(ctx.hub, a["id"], item["key"], _me(ctx.machine), ctx.lock):
        _update_state(ctx.home, a["id"], lambda x: x.update(last_slot=iso(slot)), ctx.machine)
        return []  # another machine (or this one before a restart) did this slot
    _update_state(ctx.home, a["id"], lambda x: x.update(last_slot=iso(slot)), ctx.machine)
    r = act(ctx, a, item)
    return [r] if r else []


def _run_github(ctx: Ctx, a: dict[str, Any], st: dict[str, Any], s: dict[str, Any], force: bool = False) -> list:
    nxt = parse_iso(st.get("next_poll"))
    if nxt and ctx.now < nxt and not force:
        return []
    _update_state(ctx.home, a["id"], lambda x: x.update(next_poll=iso(ctx.now + timedelta(minutes=s["poll_minutes"]))),
                  ctx.machine)
    token = github_token()
    if not token:
        return [_record(ctx, a, "Add your GitHub key on the Automations page, so the harness can read GitHub.", False)]
    try:
        items = poll(a, GitHub(token, ctx.http))
    except AutomationError as e:
        return [_record(ctx, a, str(e), False)]
    except Exception as e:  # never let one automation stop the others
        return [_record(ctx, a, f"Couldn't read GitHub: {e}", False)]
    seen = set(st.get("seen") or [])
    fresh = [it for it in items if it["key"] not in seen]
    out: list[dict[str, Any]] = []
    if a["kind"] == "ci" and fresh and _still_open(ctx, st):
        return [_record(ctx, a, "A check failed again; the earlier fix is still waiting or being built, so no new "
                                "task yet.", True)]
    for it in fresh[:s["max_new_per_poll"]]:
        root = _target(ctx, it) if it["what"] == "goal" else None
        if root and _is_busy(ctx, root):
            break  # its project is busy: the rest wait for the next poll
        if not claim(ctx.hub, a["id"], it["key"], _me(ctx.machine), ctx.lock):
            _mark_seen(ctx, a, it["key"])
            continue
        _mark_seen(ctx, a, it["key"])
        r = act(ctx, a, it)
        if r:
            out.append(r)
        if a["kind"] == "ci":
            break  # one fix task at a time
    if not out and not fresh:
        _record(ctx, a, "Nothing new on GitHub.", True)
    return out


def _mark_seen(ctx: Ctx, a: dict[str, Any], key: str) -> None:
    _update_state(ctx.home, a["id"], lambda x: x.__setitem__("seen", ((x.get("seen") or []) + [key])[-500:]),
                  ctx.machine)


def tick(cfg, hub=None, home: str | Path | None = None, now: datetime | None = None, http: Http | None = None,
         start: Starter | None = None, busy: Callable[[Path], bool] | None = None, projects_dir: Path | None = None,
         lock=None, machine: dict[str, str] | None = None, backup_sources=None) -> list[dict[str, Any]]:
    """One pass over every automation that is on. Returns what each one did."""
    s = settings(cfg)
    if not cfg or not s["enabled"]:
        return []
    ctx = Ctx(cfg=cfg, home=app_home(home), hub=hub, now=now or utcnow(), http=http, start=start or _inline,
              busy=busy, projects_dir=Path(projects_dir) if projects_dir else None, lock=lock, machine=_me(machine),
              backup_sources=backup_sources)
    out: list[dict[str, Any]] = []
    for a in every(cfg, ctx.home):
        st = load_state(ctx.home, ctx.machine).get(a["id"]) or {}
        if not a["on"] or st.get("off"):
            continue
        try:
            out += _run_schedule(ctx, a, st, s) if a["kind"] == "schedule" else _run_github(ctx, a, st, s)
        except Exception as e:  # one broken automation never stops the others
            out.append(_record(ctx, a, f"Something went wrong: {e}", False))
    return out


def run_now(ctx: Ctx, aid: str) -> dict[str, Any]:
    """The owner's Run now: a schedule's work at once (the build still waits for their OK), or GitHub asked now.
    A health check started by the owner's tap needs no other OK."""
    a = next((x for x in every(ctx.cfg, ctx.home) if x["id"] == aid), None)
    if not a:
        raise AutomationError("That automation isn't there any more. Refresh the page.")
    if a["kind"] == "schedule":
        item = _schedule_item(a, iso(ctx.now))
        item["key"] = f"now-{iso(ctx.now)}"
        if item["what"] == "goal" and _is_busy(ctx, _target(ctx, item)):
            raise AutomationError("Its project is busy right now. Try again when that job has finished.")
        r = act(ctx, a, item, approved=True)
        return r or {"id": aid, "text": "Nothing to do now.", "ok": True}
    st = load_state(ctx.home, ctx.machine).get(aid) or {}
    done = _run_github(ctx, a, st, settings(ctx.cfg), force=True)
    st = load_state(ctx.home, ctx.machine).get(aid) or {}
    return {"id": aid, "text": "; ".join(r["text"] for r in done) or st.get("last_result") or "Asked GitHub.",
            "ok": all(r.get("ok", True) for r in done)}


def start_waiting(ctx: Ctx, aid: str, key: str) -> dict[str, Any]:
    """The owner's Start it on something that waited for their OK."""
    a = next((x for x in every(ctx.cfg, ctx.home) if x["id"] == aid), None)
    st = load_state(ctx.home, ctx.machine).get(aid) or {}
    w = next((x for x in st.get("waiting") or [] if x.get("key") == key), None)
    if not a or not w:
        raise AutomationError("That isn't waiting any more. Refresh the page.")
    dismiss(ctx.home, aid, key, ctx.machine)
    r = act(ctx, a, {"key": key, "what": w["what"], "title": a["name"], "text": (a.get("do") or {}).get("text", ""),
                     "project": (a.get("do") or {}).get("project")}, approved=True)
    return r or {"id": aid, "text": "Nothing to do now.", "ok": True}


def dismiss(home: Path, aid: str, key: str, machine=None) -> None:
    _update_state(home, aid, lambda st: st.__setitem__("waiting", [w for w in st.get("waiting") or []
                                                                   if w.get("key") != key]), machine)


def needs(cfg, home: str | Path | None = None, machine=None) -> list[dict[str, Any]]:
    """What waits for the owner's tap (for Needs you): [{id, name, key, text, at}]."""
    home = app_home(home)
    state = load_state(home, machine)
    out = []
    for a in every(cfg, home):
        for w in (state.get(a["id"]) or {}).get("waiting") or []:
            out.append({"id": a["id"], "name": a["name"], **w})
    return out


# -- the desktop app and the command line ---------------------------------------------------------------------
def _load_token(app) -> None:
    """The desktop's saved GitHub key into the in-memory vault (only Roundtable's own GitHub calls read it)."""
    d = getattr(app, "desktop", None)
    if not d or vault.get(TOKEN_KEY):
        return
    try:
        v = d["keys"].get(TOKEN_KEY)
    except Exception:
        v = None
    if v:
        vault.put(TOKEN_KEY, v)


def app_context(app) -> Ctx:
    def start(kind, title, target, fn):
        return app.jobs.start(kind, title, lambda job: fn(job.line), target=target)

    _load_token(app)
    return Ctx(cfg=app.cfg(), home=app._backup_home(), hub=app.hub, start=start, busy=app._busy,
               projects_dir=app.projects_dir, lock=app.hub_lock, machine=_me(None),
               backup_sources=app._backup_sources)


def app_tick(app) -> list[dict[str, Any]]:
    """From the desktop app's auto-sync: never raises."""
    try:
        ctx = app_context(app)
        if not ctx.cfg:
            return []
        return tick(ctx.cfg, hub=ctx.hub, home=ctx.home, start=ctx.start, busy=ctx.busy, projects_dir=ctx.projects_dir,
                    lock=ctx.lock, machine=ctx.machine, backup_sources=ctx.backup_sources)
    except Exception as e:
        app.auto_sync_error = f"automations: {e}"[:300]
        return []


def main(argv: list[str]) -> None:
    """``roundtable automation [list | run ID] [--watch SECONDS] [--config harness.yaml]``"""
    import argparse
    import sys
    import time

    p = argparse.ArgumentParser(prog="roundtable automation", description=(
        "Work that starts by itself: schedules, GitHub issues and failed checks (set them up in the app's "
        "Automations page, or under automation: in harness.yaml)."))
    p.add_argument("what", nargs="*", help="list (default), or run ID")
    p.add_argument("--config", help="harness.yaml (default $HARNESS_CONFIG or ./harness.yaml)")
    p.add_argument("--watch", type=float, metavar="SECONDS", help="keep checking every SECONDS")
    args = p.parse_args(argv)
    from .harness.config import load_config

    try:
        cfg = load_config(args.config)
    except Exception as e:
        sys.exit(f"roundtable automation: couldn't read harness.yaml ({e})")
    hub = None
    if cfg.hub:
        from .core.config import load_config as load_hub
        from .hub.service import Hub

        try:
            hub = Hub(load_hub(cfg.hub.get("config"), nearby=True))
        except Exception as e:
            print(f"(no hub, so only this computer keeps count: {e})", file=sys.stderr)
    home = app_home()
    from .backup import find_sources

    sources = lambda: find_sources(args.config, None, home)
    what = args.what or ["list"]
    if args.watch:
        while True:
            for r in tick(cfg, hub, home, backup_sources=sources):
                print(f"{r['name']}: {r['text']}", flush=True)
            time.sleep(args.watch)
    if what[0] == "run" and len(what) > 1:
        ctx = Ctx(cfg=cfg, home=home, hub=hub, machine=_me(None), backup_sources=sources)
        try:
            print(run_now(ctx, what[1])["text"])
        except AutomationError as e:
            sys.exit(str(e))
        return
    state = load_state(home)
    items = every(cfg, home)
    if not items:
        print("No automations yet. Add one on the Automations page of the app.")
    for a in items:
        v = view(a, state.get(a["id"]) or {}, cfg=cfg)
        print(f"{a['id']}  {'on ' if a['on'] else 'off'}  {a['name']}\n    {v['what']} {v['when_words']}."
              f"\n    last: {v['last_run'] or 'never'} {v['last_result']}\n    next: {v['next_run'] or '-'}")


def _default_projects() -> Path:
    """The desktop app's projects folder (Darkness Projects, or an existing Roundtable Projects)."""
    from .desktop import default_projects_dir
    return Path(default_projects_dir())
