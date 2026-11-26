"""The phone and the PC as one Roundtable: seats, claims, live sessions, shared settings and machines.

Everything goes through the hub repository (git), in files that one machine (or one run) owns, so two
machines pushing at once never edit the same file:

    hub.yaml                          every machine is a seat (``role: machine``, ``title: "Phone (OPPO)"``)
    machines/<seat>.json              each machine's heartbeat: {id, name, kind, last_seen, version, listening}
    claims/<project-key>.json         who builds a project now: {machine, machine_name, since, heartbeat,
                                      run_id, state: building | released, hub_name, folder, ...}
    sessions/<project-key>/about.json the project's names (hub_name, folder)
    sessions/<project-key>/<run>.jsonl one line per event of a run, for watching it from the other machine
    settings/shared.yaml              what should match on every machine (limits, autopilot, profile,
                                      the owner's role choices), with who changed it and when

Rules:

* one machine builds a project at a time: ``Orchestrator.run`` takes the claim, renews its heartbeat at
  least every ``HEARTBEAT_S`` and on every task, and releases it when the run ends or pauses. A claim
  with no heartbeat for ``CLAIM_STALE_S`` is stale and may be taken (the run notes it). When two
  machines claim at the same moment, the claim that reached the hub first stays (core.store).
* a run publishes its session at most every ``FLUSH_S`` and at every task's end; the last ``KEEP_RUNS``
  runs of each project are kept.
* shared settings: the last change wins; keys never leave the machine.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MACHINE_ENV = "ROUNDTABLE_MACHINE"  # set by `roundtable phone serve --local`: the phone's seat
MACHINE_NAME_ENV = "ROUNDTABLE_MACHINE_NAME"
CLAIM_STALE_S = 600  # a claim without news for 10 minutes may be taken
HEARTBEAT_S = 90  # a running build renews its claim at least this often (well inside 2 minutes)
FLUSH_S = 30  # a running build's session reaches the hub at most this often (and at every task's end)
KEEP_RUNS = 3  # sessions kept per project
MACHINE_EVERY_S = 300  # a machine's heartbeat file is written this often (or when something changed)
MACHINE_OFF_S = 900  # no heartbeat for this long: the machine is off
MAX_LINES = 3000  # lines kept in one run's session file (the start line and the newest)
SHARED_FILE = "settings/shared.yaml"
SHARED_LIMITS = ("max_cost_usd", "max_real_usd_per_run", "max_usd_per_day")
APPLIED_FILE = "shared-settings.json"  # in the app home: what this machine last took from or gave the hub


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def age_s(ts: str | None) -> float:
    try:
        then = datetime.strptime(str(ts), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return 1e12
    return (datetime.now(timezone.utc) - then).total_seconds()


def slug(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return s[:limit].strip("-") or "x"


# -- this machine ----------------------------------------------------------------------------------
def this_machine() -> dict[str, str]:
    """This machine's seat: the phone's (set by onphone.py), else ``pc-<hostname>`` → "PC (HOSTNAME)"."""
    mid = (os.environ.get(MACHINE_ENV) or "").strip()
    if mid:
        kind = "phone" if mid.startswith("phone-") else "pc"
        name = os.environ.get(MACHINE_NAME_ENV) or ("Phone" if kind == "phone" else f"PC ({mid[3:].upper()})")
        return {"id": mid, "name": name, "kind": kind}
    host = socket.gethostname() or "computer"
    short = host.split(".")[0] or host
    return {"id": f"pc-{slug(short, 50)}", "name": f"PC ({short.upper()})", "kind": "pc"}


def phone_title(device: str | None) -> str:
    device = " ".join(str(device or "").split())[:40]
    return f"Phone ({device})" if device else "Phone"


def words_for(kind: str) -> str:
    return "phone" if kind == "phone" else "PC"


# -- the hub's own hub.yaml: every machine a seat ----------------------------------------------------
def hub_root(hub) -> Path | None:
    root = getattr(getattr(hub, "store", None), "root", None)
    return Path(root) if root else None


def _seat_lines(seat: str, title: str, kind: str, description: str, indent: str) -> list[str]:
    import yaml

    body = yaml.safe_dump({"title": title, "role": "machine", "tags": [kind], "description": description},
                          sort_keys=False, allow_unicode=True).splitlines()
    return [f"{indent}{seat}:"] + [f"{indent}{indent}{ln}" for ln in body]


def register_seat(hub, seat: str, title: str, kind: str = "pc", description: str = "") -> bool:
    """Add this machine to the hub repository's hub.yaml (the PC sees it after its next sync).

    Idempotent: a seat that is already there is left as it is (the owner may have renamed it). The
    owner's comments are kept: the seat is written in under ``agents:``. True when it was added."""
    import yaml

    from .core.config import AGENT_ID_RE
    from .core.store import TextFile

    if not AGENT_ID_RE.match(seat):
        raise ValueError(f"{seat!r} can't be a seat name")
    root = hub_root(hub)
    if root is None:
        return False
    description = description or f"Roundtable on this {words_for(kind)}"
    for _ in range(3):  # another machine may have changed hub.yaml at the same moment: read it again
        hub.store.sync(force=True)
        path = root / "hub.yaml"
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        try:
            raw = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            return False  # a broken hub.yaml: leave it to the owner rather than make it worse
        agents = raw.get("agents") if isinstance(raw, dict) else None
        if isinstance(agents, dict) and seat in agents:
            hub.refresh_config()
            return False
        lines = text.splitlines()
        at = next((i for i, ln in enumerate(lines) if re.match(r"^agents:\s*(#.*)?$", ln)), None)
        if at is not None and isinstance(agents, dict):
            nxt = next((ln for ln in lines[at + 1:] if ln.strip() and not ln.lstrip().startswith("#")), "")
            indent = re.match(r"^(\s*)", nxt).group(1) or "  "
            lines[at + 1:at + 1] = _seat_lines(seat, title, kind, description, indent)
            new = "\n".join(lines) + "\n"
        else:  # no agents block to write into: write the whole file again
            raw = raw if isinstance(raw, dict) else {}
            if not raw:  # no hub.yaml in the hub yet: start from this machine's (its projects and rules)
                raw = _local_shared_part(hub)
            raw.setdefault("default_policy", "deny")
            if not isinstance(raw.get("agents"), dict):
                raw["agents"] = {}
            agents = raw["agents"]
            agents[seat] = {"title": title, "role": "machine", "tags": [kind], "description": description}
            raw.setdefault("rules", [{"from": "*", "to": "*", "allow": ["read_card", "message"]}])
            new = yaml.safe_dump(raw, sort_keys=False, allow_unicode=True)
        hub.store.write_json({"hub.yaml": TextFile(new)}, f"seat({seat}): {title}")
        try:
            check = yaml.safe_load((root / "hub.yaml").read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            check = {}
        if seat in (check.get("agents") or {}):
            hub.refresh_config()
            return True
    return False


def _local_shared_part(hub) -> dict[str, Any]:
    """The projects and rules of this machine's own hub.yaml (never where its data is kept)."""
    import yaml

    from .core.config import SHARED_KEYS

    try:
        raw = yaml.safe_load(Path(hub.config.path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError, TypeError):
        raw = {}
    return {k: raw[k] for k in SHARED_KEYS if isinstance(raw, dict) and k in raw}


# -- which project: the same one started on two machines is recognised ----------------------------------
def _git_out(root: Path, *args: str) -> str:
    try:
        res = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return res.stdout.strip() if res.returncode == 0 else ""


def normalise_remote(url: str) -> str:
    """github.com/owner/repo for every spelling of a remote (https, ssh, with a token, with .git)."""
    u = str(url or "").strip()
    u = re.sub(r"^[a-z+]+://", "", u, flags=re.I)
    u = re.sub(r"^[^@/]+@", "", u)  # user, or a token, before the host
    u = re.sub(r"^([^/:]+):(?!\d)", r"\1/", u)  # git@host:owner/repo
    u = re.sub(r"\.git/?$", "", u).strip("/")
    return u.lower()


def project_key(root: Path, hub_name: str) -> str:
    """A project's key in the hub: its repository (remote address + the folder inside it) when it has
    one, else its name in the hub (``harness--bakery``)."""
    root = Path(root)
    remote = _git_out(root, "remote", "get-url", "origin")
    if remote:
        inside = _git_out(root, "rev-parse", "--show-prefix").strip("/")
        base = normalise_remote(remote) + ("/" + inside if inside else "")
        readable = slug(base.split("/", 1)[-1].replace("/", "-"), 40)
        return f"{readable}-{hashlib.sha256(base.encode()).hexdigest()[:8]}"
    return slug(hub_name, 80)


# -- claims: one machine builds a project at a time ------------------------------------------------------
class ClaimedElsewhere(RuntimeError):
    """Another machine is building this project right now."""


def claim_path(key: str) -> str:
    return f"claims/{key}.json"


def claim_fresh(c: dict[str, Any] | None) -> bool:
    return bool(c and c.get("state") == "building" and age_s(c.get("heartbeat")) < CLAIM_STALE_S)


def _minutes(seconds: float) -> str:
    m = max(1, int(seconds // 60))
    return f"{m} minute{'s' if m != 1 else ''}"


class Claim:
    """The claim file of one run of one project."""

    def __init__(self, hub, key: str, run_id: str, machine: dict[str, str] | None = None, **about: Any):
        self.hub, self.key, self.run_id = hub, key, run_id
        self.machine = machine or this_machine()
        self.about = about  # hub_name, folder, project
        self.path = claim_path(key)
        self.since = ""
        self.lost = False  # another machine took the project over while this run went on

    def read(self, sync: bool = True) -> dict[str, Any] | None:
        if sync:
            self.hub.store.sync(force=True)
        return self.hub.store.read_json(self.path)

    def record(self, state: str = "building", **extra: Any) -> dict[str, Any]:
        return {"machine": self.machine["id"], "machine_name": self.machine["name"], "kind": self.machine["kind"],
                "since": self.since, "heartbeat": utcnow(), "run_id": self.run_id, "state": state, "key": self.key,
                **self.about, **extra}

    def _mine(self, c: dict[str, Any] | None) -> bool:
        return bool(c and c.get("machine") == self.machine["id"] and c.get("run_id") == self.run_id)

    def take(self) -> str:
        """Take the project, or raise ClaimedElsewhere naming the other machine. Returns a note when a
        stale claim was taken over."""
        cur = self.read()
        note = ""
        if cur and cur.get("machine") != self.machine["id"] and cur.get("state") == "building":
            if claim_fresh(cur):
                raise ClaimedElsewhere(self.refusal(cur))
            note = (f"Took over from {cur.get('machine_name') or cur.get('machine')}: it had sent no news for "
                    f"{_minutes(age_s(cur.get('heartbeat')))}.")
        self.since = utcnow()
        self.hub.store.write_json({self.path: self.record(**({"took_over": note} if note else {}))},
                                  f"claim({self.key}): {self.machine['name']} builds it")
        now = self.read()
        if not self._mine(now):  # another machine's claim reached the hub first
            raise ClaimedElsewhere(self.refusal(now or {}))
        return note

    def refusal(self, c: dict[str, Any]) -> str:
        who = c.get("machine_name") or c.get("machine") or "another computer"
        when = f" (for {_minutes(age_s(c.get('since')))})" if c.get("since") else ""
        return (f"This project is being built on {who} right now{when}. Only one machine builds a project at a "
                f"time: wait for it to finish or pause there, then carry on.")

    def beat(self) -> dict[str, Any] | None:
        """The claim with a new heartbeat, to write; None when another machine has taken the project."""
        cur = self.hub.store.read_json(self.path)
        if cur and not self._mine(cur) and claim_fresh(cur):
            self.lost = True
            return None
        return self.record()

    def released(self, status: str) -> dict[str, Any] | None:
        """The claim marked released (it remembers which machine holds the project's files)."""
        cur = self.hub.store.read_json(self.path)
        if cur and not self._mine(cur):
            return None  # it isn't ours any more: leave the other machine's claim alone
        return self.record("released", ended=utcnow(), status=status)


def read_claims(hub) -> dict[str, dict[str, Any]]:
    """Every claim in the hub by project key (fresh or not)."""
    from .core.store import iter_json

    out = {}
    for rel, data in iter_json(hub.store, "claims"):
        out[Path(rel).stem] = data
    return out


# -- the live session: one line per event, written while the run goes on --------------------------------
def session_line(kind: str, d: dict[str, Any]) -> dict[str, Any] | None:
    """One event as a line for watching from the other machine: no prompts, no file contents."""
    from .harness import session as sessionlib

    at = d.get("at") or utcnow()
    if kind == "task_start":
        line = {"kind": "task", "task": d.get("task"), "title": d.get("title", ""), "role": d.get("role", "")}
    elif kind == "attempt":
        line = {"kind": "attempt", "task": d.get("task"), "model": d.get("model", ""), "attempt": d.get("attempt")}
    elif kind == "model_turn":
        text = " ".join(str(d.get("text") or "").split())[:200]
        line = {"kind": "turn", "model": d.get("model", ""), "role": d.get("role", ""), "text": text,
                "tools": list(d.get("tools") or [])[:8], "cost": round(float(d.get("cost") or 0), 6)}
    elif kind == "tool_call":
        step = sessionlib.tool_step(d)
        if step["kind"] == "hidden" or str(d.get("tool", "")).startswith("submit_"):  # the plan's own plumbing
            return None
        line = {"kind": "tool", "tool": d.get("tool", ""), "line": sessionlib.step_line(step)[:240],
                "error": bool(step.get("error"))}
        if step.get("path"):
            line["path"] = step["path"]
    elif kind == "review":
        line = {"kind": "review", "task": d.get("task"), "approved": bool(d.get("approved")),
                "text": str(d.get("feedback") or "")[:300]}
    elif kind == "task_end":
        line = {"kind": "task_end", "task": d.get("task"), "status": d.get("status", ""),
                "summary": str(d.get("summary") or "")[:300]}
    elif kind == "shots":
        line = {"kind": "shots", "task": d.get("task"), "dir": d.get("dir", ""), "pictures": d.get("pictures", [])}
    elif kind == "provider_error":
        line = {"kind": "error", "text": f"{d.get('model')}: {d.get('error', '')}"[:300]}
    elif kind == "status":
        line = {"kind": "status", "status": d.get("status", "")}
    elif kind in ("planning", "plan"):
        line = {"kind": kind, "text": str(d.get("summary") or d.get("model") or "")[:200]}
    else:
        return None
    return sessionlib._redact_all({"at": at, **line})


def new_run_id(machine: dict[str, str]) -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{machine['id']}-{secrets.token_hex(2)}"


def session_dir(key: str) -> str:
    return f"sessions/{key}"


class LiveRun:
    """While a run goes on: its claim kept alive and its session published, in one commit at a time."""

    def __init__(self, hub, claim: Claim, start: dict[str, Any] | None = None):
        self.hub, self.claim = hub, claim
        self.key, self.run_id = claim.key, claim.run_id
        self.rel = f"{session_dir(self.key)}/{self.run_id}.jsonl"
        self.lines: list[dict[str, Any]] = [{"at": utcnow(), "kind": "start", "run_id": self.run_id,
                                             "machine": claim.machine["id"], "machine_name": claim.machine["name"],
                                             **claim.about, **(start or {})}]
        self._lock = threading.Lock()
        self._dirty = True
        self._urgent = False
        self._beat_due = False
        self._last_flush = 0.0
        self._last_beat = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error = ""
        self.flushes = 0

    @property
    def lost(self) -> bool:
        return self.claim.lost

    def add(self, kind: str, data: dict[str, Any]) -> None:
        try:
            line = session_line(kind, data)
        except Exception:  # watching is a help: never fail a run over it
            return
        if not line:
            return
        with self._lock:
            self.lines.append(line)
            if len(self.lines) > MAX_LINES:
                self.lines[1:] = self.lines[-(MAX_LINES - 1):]
            self._dirty = True
            if kind in ("task_start", "task_end"):
                self._urgent = True
                self._beat_due = True

    def start(self) -> "LiveRun":
        self.flush(first=True)
        self._thread = threading.Thread(target=self._loop, daemon=True, name=f"live-{self.key}")
        self._thread.start()
        return self

    def _loop(self) -> None:
        while not self._stop.wait(1.0):
            now = time.monotonic()
            with self._lock:
                due = (self._dirty and (self._urgent or now - self._last_flush >= FLUSH_S)) or self._beat_due \
                      or now - self._last_beat >= HEARTBEAT_S
            if due:
                self.flush()

    def _trim(self) -> dict[str, Any]:
        """Old runs of this project to remove (the newest KEEP_RUNS stay, this one among them)."""
        root = hub_root(self.hub)
        d = root / session_dir(self.key) if root else None
        if not d or not d.is_dir():
            return {}
        runs = sorted(p.name for p in d.glob("*.jsonl") if p.name != Path(self.rel).name)
        old = runs[:max(0, len(runs) - (KEEP_RUNS - 1))]
        return {f"{session_dir(self.key)}/{name}": None for name in old}

    def _text(self) -> str:
        with self._lock:
            self._dirty = self._urgent = False
            return "".join(json.dumps(ln, ensure_ascii=False) + "\n" for ln in self.lines)

    def flush(self, first: bool = False, end: str | None = None) -> None:
        from .core.store import TextFile

        try:
            files: dict[str, Any] = {}
            self.hub.store.sync(force=True)
            if first:
                files.update(self._trim())
                files[f"{session_dir(self.key)}/about.json"] = {"key": self.key, **self.claim.about}
            beat = self.claim.released(end) if end is not None else self.claim.beat()
            if beat is not None and (end is not None or not first):
                files[self.claim.path] = beat
            files[self.rel] = TextFile(self._text())
            what = f"ended: {end}" if end is not None else f"{len(self.lines)} lines"
            self.hub.store.write_json(files, f"session({self.key}): {what}")
            self.flushes += 1
            self.error = ""
        except Exception as e:  # offline: the next flush carries everything
            self.error = str(e)[:300]
        finally:
            self._last_flush = time.monotonic()
            with self._lock:
                self._beat_due = False
            self._last_beat = time.monotonic()

    def stop(self, status: str) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=30)
        with self._lock:
            self.lines.append({"at": utcnow(), "kind": "end", "status": status})
            self._dirty = True
        self.flush(end=status)


def hold(hub, root: Path, hub_name: str, folder: str, start: dict[str, Any] | None = None) -> tuple[LiveRun, str]:
    """Take the project for this machine and start publishing its session. Raises ClaimedElsewhere."""
    machine = this_machine()
    key = project_key(root, hub_name)
    claim = Claim(hub, key, new_run_id(machine), machine, hub_name=hub_name, folder=folder)
    note = claim.take()
    live = LiveRun(hub, claim, start)
    if note:
        live.lines.append({"at": utcnow(), "kind": "note", "text": note})
    return live.start(), note


# -- reading sessions (the desktop, the phone's PC and This-phone modes) -----------------------------------
def _read_lines(path: Path) -> list[dict[str, Any]]:
    out = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for ln in text.splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def find_key(hub, name: str) -> str | None:
    """A project's key from its hub name, its folder or the key itself."""
    root = hub_root(hub)
    if not root or not name:
        return None
    base = root / "sessions"
    if (base / slug(name, 80)).is_dir() and slug(name, 80) == name:
        return name
    for about in sorted(base.glob("*/about.json")):
        try:
            a = json.loads(about.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if name in (a.get("hub_name"), a.get("folder"), a.get("key")):
            return about.parent.name
    for key, c in read_claims(hub).items():
        if name in (c.get("hub_name"), c.get("folder")):
            return key
    return None


def run_summary(lines: list[dict[str, Any]]) -> dict[str, Any]:
    head = lines[0] if lines else {}
    end = next((ln for ln in reversed(lines) if ln.get("kind") == "end"), None)
    cost = round(sum(float(ln.get("cost") or 0) for ln in lines), 6)
    task = next((ln for ln in reversed(lines) if ln.get("kind") == "task"), None)
    return {"run_id": head.get("run_id", ""), "machine": head.get("machine", ""),
            "machine_name": head.get("machine_name", ""), "started": head.get("at", ""),
            "ended": (end or {}).get("at", ""), "status": (end or {}).get("status", "running"),
            "cost_usd": cost, "task": ({"id": task.get("task"), "title": task.get("title", "")} if task else None),
            "lines": len(lines)}


def sessions(hub, name: str, run: str = "", since: int = 0) -> dict[str, Any]:
    """The project's recent runs and one run's lines (the newest unless ``run`` names one).

    ``since``: the number of lines the caller already has, so only the new ones come back."""
    key = find_key(hub, name)
    out: dict[str, Any] = {"name": name, "key": key, "runs": [], "run": None, "live": False}
    root = hub_root(hub)
    if not key or not root:
        return out
    d = root / session_dir(key)
    files = sorted(d.glob("*.jsonl"), reverse=True)
    runs = []
    chosen = None
    for f in files:
        lines = _read_lines(f)
        s = run_summary(lines)
        s["run_id"] = s["run_id"] or f.stem
        runs.append(s)
        if (run and f.stem == run) or (not run and chosen is None):
            chosen = (s, lines)
    out["runs"] = runs
    claim = hub.store.read_json(claim_path(key))
    if chosen:
        s, lines = chosen
        out["live"] = bool(claim_fresh(claim) and (claim or {}).get("run_id") == s["run_id"])
        out["run"] = {**s, "since": max(0, int(since or 0)), "events": lines[max(0, int(since or 0)):]}
    if claim:
        out["claim"] = {k: claim.get(k) for k in ("machine", "machine_name", "state", "since", "heartbeat", "run_id")}
        out["claim"]["fresh"] = claim_fresh(claim)
    return out


# -- machines: who is on, who listens, who builds what ----------------------------------------------------
_last_beat: dict[tuple[str, str], tuple[float, str]] = {}


def write_heartbeat(hub, machine: dict[str, str] | None = None, listening: bool = True, force: bool = False,
                    **extra: Any) -> bool:
    """machines/<seat>.json: written when something changed, else at most every MACHINE_EVERY_S."""
    from . import __version__

    machine = machine or this_machine()
    rel = f"machines/{machine['id']}.json"
    state = {"id": machine["id"], "name": machine["name"], "kind": machine["kind"], "version": __version__,
             "listening": bool(listening), **extra}
    digest = json.dumps(state, sort_keys=True)
    slot = (str(hub_root(hub) or ""), rel)
    last = _last_beat.get(slot)
    if not force and last and last[1] == digest and time.monotonic() - last[0] < MACHINE_EVERY_S:
        return False
    hub.store.write_json({rel: {**state, "last_seen": utcnow()}}, f"machine({machine['id']}): here")
    _last_beat[slot] = (time.monotonic(), digest)
    return True


def machines(hub, me: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Every machine seat, its last news, whether it listens for commands and what it builds."""
    from .core.store import iter_json

    me = me or this_machine()
    seen: dict[str, dict[str, Any]] = {}
    for agent_id, spec in hub.config.agents.items():
        if spec.role == "machine":
            kind = "phone" if "phone" in spec.tags or agent_id.startswith("phone-") else "pc"
            seen[agent_id] = {"id": agent_id, "name": spec.title or agent_id, "kind": kind}
    for _, beat in iter_json(hub.store, "machines"):
        mid = str(beat.get("id") or "")
        if not mid:
            continue
        m = seen.setdefault(mid, {"id": mid, "name": beat.get("name") or mid, "kind": beat.get("kind") or "pc"})
        m.update(last_seen=beat.get("last_seen", ""), version=beat.get("version", ""),
                 listening=bool(beat.get("listening")))
    claims = read_claims(hub)
    out = []
    for mid, m in seen.items():
        m.setdefault("last_seen", "")
        m.setdefault("version", "")
        m.setdefault("listening", False)
        m["this"] = mid == me["id"]
        m["online"] = m["this"] or age_s(m["last_seen"]) < MACHINE_OFF_S
        m["building"] = [{"key": k, "hub_name": c.get("hub_name", ""), "folder": c.get("folder", ""),
                          "since": c.get("since", ""), "run_id": c.get("run_id", "")}
                         for k, c in claims.items() if c.get("machine") == mid and claim_fresh(c)]
        m["state"] = machine_words(m)
        out.append(m)
    return sorted(out, key=lambda m: (not m["this"], m["kind"] != "pc", m["name"].lower()))


def machine_words(m: dict[str, Any]) -> str:
    """How a machine is, as the owner reads it."""
    yours = "This " + words_for(m.get("kind", "pc")) if m.get("this") else "Your " + words_for(m.get("kind", "pc"))
    if not m.get("online"):
        return f"{yours} is off: it'll pick things up when it's on."
    if m.get("building"):
        b = m["building"][0]
        return f"{yours} is building {b.get('folder') or b.get('hub_name') or 'a project'}."
    if not m.get("listening") and not m.get("this"):
        return f"{yours} is on, but not listening for commands: open Roundtable Hold there."
    return f"{yours} is on."


def where_is(hub, name: str) -> dict[str, Any] | None:
    """The machine that holds a project's files: its claim (building or released), else who published it."""
    key = find_key(hub, name)
    c = hub.store.read_json(claim_path(key)) if key else None
    if not c:
        for k, cl in read_claims(hub).items():
            if name in (cl.get("hub_name"), cl.get("folder")):
                c = cl
                break
    if not c:
        root = hub_root(hub)
        try:
            asks = json.loads((root / "plans" / f"{name}.asks.json").read_text(encoding="utf-8")) if root else {}
        except (OSError, ValueError):
            asks = {}
        if asks.get("machine"):
            return {"machine": asks["machine"], "machine_name": asks.get("machine_name") or asks["machine"],
                    "building": False}
        return None
    return {"machine": c.get("machine"), "machine_name": c.get("machine_name") or c.get("machine"),
            "building": claim_fresh(c), "key": key}


# -- shared settings: what should match on every machine ---------------------------------------------------
def local_snapshot(harness_path: Path | None, home: Path) -> dict[str, Any]:
    """This machine's values of the shared settings (keys never)."""
    from . import autopilot
    from .harness.config import load_config, load_custom

    out: dict[str, Any] = {"limits": {}, "autopilot": {}, "default_profile": None, "roles": {}}
    if harness_path and Path(harness_path).is_file():
        try:
            cfg = load_config(str(harness_path))
            out["limits"] = {"max_cost_usd": cfg.limits.max_cost_usd,
                             "max_real_usd_per_run": cfg.limits.max_real_usd_per_run,
                             "max_usd_per_day": cfg.limits.max_usd_per_day}
            out["default_profile"] = cfg.default_profile
        except Exception:
            pass
        roles = load_custom(Path(harness_path)).get("roles") or {}
        out["roles"] = {r: {k: v for k, v in (spec or {}).items() if k in ("model", "fallback")}
                        for r, spec in roles.items()}
    st = autopilot.load(home)
    out["autopilot"] = {"on": bool(st["on"]), "until": st["until"], "cap": float(st["spend_cap_usd"])}
    return out


def read_shared(hub) -> dict[str, Any] | None:
    import yaml

    root = hub_root(hub)
    p = root / SHARED_FILE if root else None
    if not p or not p.is_file():
        return None
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    """Only the shared settings, in their right shapes (anything else is dropped, keys above all)."""
    out: dict[str, Any] = {}
    lim = values.get("limits")
    if isinstance(lim, dict):
        out["limits"] = {}
        for k in SHARED_LIMITS:
            if lim.get(k) is not None:
                v = float(lim[k])
                if v < 0:
                    raise ValueError(f"{k} can't be below 0")
                out["limits"][k] = v
    ap = values.get("autopilot")
    if isinstance(ap, dict):
        out["autopilot"] = {"on": bool(ap.get("on")), "until": ap.get("until") or None,
                            "cap": float(ap.get("cap") or 2.0)}
    if "default_profile" in values:
        out["default_profile"] = values.get("default_profile") or None
    roles = values.get("roles")
    if isinstance(roles, dict):
        out["roles"] = {}
        for r, spec in roles.items():
            spec = spec or {}
            if not isinstance(spec, dict):
                raise ValueError(f"role {r}: give it a model, like {{model: deepseek/deepseek-v4-flash}}")
            keep = {k: spec[k] for k in ("model", "fallback") if spec.get(k)}
            if keep:
                out["roles"][str(r)] = keep
    return out


def publish_shared(hub, values: dict[str, Any], machine: dict[str, str] | None = None) -> dict[str, Any]:
    import yaml

    from .core.store import TextFile

    machine = machine or this_machine()
    data = {**_clean(values), "changed_by": machine["id"], "changed_by_name": machine["name"],
            "changed_at": utcnow(), "change_id": secrets.token_hex(6)}
    text = ("# Settings every Roundtable machine shares (written by Roundtable Hold; the last change wins).\n"
            "# API keys are never here: they stay on each machine.\n" + yaml.safe_dump(data, sort_keys=False))
    hub.store.write_json({SHARED_FILE: TextFile(text)}, f"settings: changed on {machine['name']}")
    return data


def apply_shared(shared: dict[str, Any], harness_path: Path | None, home: Path, cfg=None) -> list[str]:
    """Make this machine match the shared settings; returns what changed, in words."""
    from . import autopilot
    from .harness.config import load_custom, save_custom

    done: list[str] = []
    values = _clean(shared)
    by = shared.get("changed_by_name") or shared.get("changed_by") or "another machine"
    if harness_path and Path(harness_path).is_file():
        custom = load_custom(Path(harness_path))
        before = json.dumps(custom, sort_keys=True, default=str)
        if "limits" in values:
            custom["limits"] = {**(custom.get("limits") or {}), **values["limits"]}
        if "roles" in values:
            roles = {r: dict(s or {}) for r, s in (custom.get("roles") or {}).items()}
            for r, spec in values["roles"].items():
                roles.setdefault(r, {}).update(spec)
            custom["roles"] = roles
        if values.get("default_profile"):
            custom["default_profile"] = values["default_profile"]
        if json.dumps(custom, sort_keys=True, default=str) != before:
            old = Path(harness_path).parent / "custom.yaml"
            keep = old.read_text(encoding="utf-8") if old.is_file() else None
            save_custom(Path(harness_path), custom)
            try:  # never leave a setting this machine can't load (a profile or role it doesn't have)
                from .harness.config import load_config

                load_config(str(harness_path))
                done.append("limits and models")
            except Exception:
                if keep is None:
                    old.unlink(missing_ok=True)
                else:
                    old.write_text(keep, encoding="utf-8")
    ap = values.get("autopilot")
    if ap is not None:
        st = autopilot.load(home)
        if ap["on"] and not st["on"]:
            autopilot.turn_on(ap.get("until"), ap.get("cap"), home=home, cfg=cfg)
            done.append("autopilot on")
        elif not ap["on"] and st["on"]:
            autopilot.turn_off(f"turned off on {by}.", home=home, cfg=cfg)
            done.append("autopilot off")
        elif ap["on"] and (float(st["spend_cap_usd"]) != ap["cap"] or st["until"] != ap.get("until")):
            st.update(spend_cap_usd=round(ap["cap"], 2), until=ap.get("until"))
            autopilot.save(st, home)
            done.append("autopilot's limit")
    return done


def _applied(home: Path) -> dict[str, Any]:
    try:
        return json.loads((Path(home) / APPLIED_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_applied(home: Path, stamp: str, snapshot: dict[str, Any]) -> None:
    p = Path(home) / APPLIED_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"stamp": stamp, "snapshot": snapshot}, indent=1, default=str), encoding="utf-8")


def sync_shared(hub, harness_path: Path | None, home: Path, cfg=None,
                machine: dict[str, str] | None = None) -> dict[str, Any]:
    """Once a sync: the owner changed a shared setting here → the hub gets it; the hub has a newer one →
    this machine takes it. A machine joining for the first time takes the hub's."""
    home = Path(home)
    remote = read_shared(hub)
    applied = _applied(home)
    local = local_snapshot(harness_path, home)
    stamp = (remote or {}).get("change_id") or (remote or {}).get("changed_at") or ""
    seen_before = "snapshot" in applied
    changed_here = seen_before and json.dumps(local, sort_keys=True, default=str) != json.dumps(
        applied["snapshot"], sort_keys=True, default=str)
    if remote and (not seen_before or (stamp != applied.get("stamp") and not changed_here)):
        done = apply_shared(remote, harness_path, home, cfg)
        _save_applied(home, stamp, local_snapshot(harness_path, home))
        return {"took": done, "from": remote.get("changed_by_name") or remote.get("changed_by")}
    if changed_here or not remote:
        data = publish_shared(hub, local, machine)
        _save_applied(home, data["change_id"], local)
        return {"gave": True}
    return {}


def change_shared(hub, changes: dict[str, Any], harness_path: Path | None, home: Path, cfg=None,
                  machine: dict[str, str] | None = None) -> dict[str, Any]:
    """The owner changed shared settings in the app: this machine first, then the hub (last change wins)."""
    current = {**local_snapshot(harness_path, home), **{k: v for k, v in (read_shared(hub) or {}).items()
                                                         if k in ("limits", "autopilot", "default_profile", "roles")}}
    clean = _clean(changes)
    if "limits" in clean:
        clean["limits"] = {**(current.get("limits") or {}), **clean["limits"]}
    if "roles" in clean:
        clean["roles"] = {**(current.get("roles") or {}), **clean["roles"]}
    merged = {**current, **clean}
    data = {**_clean(merged), "changed_by_name": (machine or this_machine())["name"]}
    done = apply_shared(data, harness_path, home, cfg)
    published = publish_shared(hub, local_snapshot(harness_path, home), machine)
    _save_applied(home, published["change_id"], local_snapshot(harness_path, home))
    return {"settings": published, "changed": done}


# -- once a sync (the desktop app's auto-sync and the phone's) ---------------------------------------------
def tick(app, listening: bool = True) -> dict[str, Any]:
    """This machine's seat, its heartbeat and the shared settings, after the hub was synced."""
    hub = app.hub
    if not hub:
        return {}
    me = this_machine()
    out: dict[str, Any] = {"machine": me["id"]}
    try:
        with app.hub_lock:
            out["seat_added"] = register_seat(hub, me["id"], me["name"], me["kind"])
    except Exception as e:
        out["error"] = f"seat: {e}"[:300]
    try:
        building = [c.get("folder") for c in read_claims(hub).values()
                    if c.get("machine") == me["id"] and claim_fresh(c)]
        with app.hub_lock:
            write_heartbeat(hub, me, listening=listening, building=sorted(x for x in building if x))
    except Exception as e:
        out["error"] = f"heartbeat: {e}"[:300]
    try:
        home = app._backup_home()
        harness = Path(app.harness_config_path) if app.harness_config_path else None
        with app.hub_lock:
            out["shared"] = sync_shared(hub, harness, home, app.cfg(), me)
    except Exception as e:
        out["error"] = f"shared settings: {e}"[:300]
    return out
