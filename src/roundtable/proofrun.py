"""The proof run: one idea, one small game, built end to end for a known, capped price (wave 9).

The owner: "You should be able to create entire application, entire games etc… All I'm doing is writing the
initial plan/idea." The proof run checks that on a made-up idea (``proofrun/idea.md``, Lantern Run), with
DeepSeek V4 Flash for every chat job (never V4 Pro: the owner's standing "no V4 Pro for now") and one maker
only, so it proves the harness and not a script:

1. :func:`prepare` makes a lab folder: the set-up (``proofrun/harness.deepseek.yaml``, filled in), a made-up
   hub of its own (never ``agent-hub-data``'s projects), autopilot's own settings, the idea and the caps.
2. :func:`plan_phase`: the pictures and the sound are priced first (free quotes; a service that can't be
   priced is left out, and the game's sounds are then made in code); the real balance is read; ``new`` with
   the idea, the kind (Browser game) and the project's own limits; ``plan``. The estimate is checked against
   each cap and the run stops there, before anything is built, when it is over one or can't be priced.
3. A yes (the command line asks; the app's card has a button).
4. :func:`build_phase`: autopilot, switched on in the lab only with the caps as its limit, approves under its
   own rules and starts the run (the finishing step starts the game, walks the done list and fixes what
   breaks); the balance is read again; :func:`report`.

The caps are the harness's own limits, not this module's: the project's ``max_cost_usd`` (every counted
dollar: text, pictures and sound), ``max_real_usd_per_run`` (the text cap: DeepSeek's real balance, which
also stops the run at half with nothing passed), ``sound.max_per_project_usd`` (soundprice.py) and autopilot's
allowance. The proof run adds only the check of the estimate before building.

:func:`report` puts the estimate, the harness's own count and the real fall in the balance side by side;
:func:`findings` turns it into lines (where, what was expected, what happened, the file most likely at fault)
for the coordinator, written to ``<lab>/proofrun-findings.md``. Nothing from the lab reaches the real hub but
one journal line (:func:`journal_line`), with no project content.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from typing import Any, Callable

import yaml

MODEL = "deepseek/deepseek-v4-flash"  # every chat job (the owner: no V4 Pro for now)
CHAT_PROVIDER = "deepseek"
NEVER = ("deepseek-v4-pro", "v4-pro")  # never in the proof run's set-up
OWNER_MAX_USD = 3.0  # the owner's yes (28 November 2026): the proof run may cost at most $3
CAPS = {"text_usd": 2.0, "art_usd": 0.5, "sound_usd": 0.5}  # text is also the project's real-money limit
SEEING_PASS_USD = 0.20  # the optional second pass with one model that can see
PROJECT = "lantern-run"
HUB_AGENT = "proofrun"
KIND = "browser-game"
STATE_FILE = Path(".harness") / "proofrun-state.json"
REPORT_FILE = Path(".harness") / "proofrun.json"
EVENTS_FILE = Path(".harness") / "proofrun-events.jsonl"
FINDINGS_FILE = "proofrun-findings.md"
WRONG_ESTIMATE = 0.25  # an estimate more than this far off what it cost is a finding (money.over_estimate)
WRONG_COUNT = 0.10  # the harness's count more than this far off the real fall is a finding
ART_ROLE, SOUND_ROLE = "artist", "sound"
ABOUT = "Prove it: build a small game from one idea. About $1, at most $3."
ERRORS_AT = {"hub_error": "src/roundtable/hub/service.py", "stage_error": "src/roundtable/harness/stages.py",
             "proof_error": "src/roundtable/harness/proof.py", "unstick_error": "src/roundtable/harness/unstick.py",
             "provider_error": "src/roundtable/providers/openai_compat.py",
             "council_error": "src/roundtable/harness/council.py", "memory_error": "src/roundtable/memory.py",
             "usage_error": "src/roundtable/harness/usage.py", "split_failed": "src/roundtable/harness/orchestrator.py",
             "learn_failed": "src/roundtable/improve/lab.py", "mcp_error": "src/roundtable/harness/mcp_tools.py",
             "kind_error": "src/roundtable/harness/kindstage.py"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _usd(x: float | None) -> str:
    return "not known" if x is None else f"${x:.2f}"


def _data(name: str) -> str:
    return resources.files("roundtable").joinpath(f"proofrun/{name}").read_text(encoding="utf-8")


def default_idea() -> str:
    return _data("idea.md").strip()


def default_lab() -> Path:
    """Where the app keeps its proof run: ``<app home>/proofrun``."""
    from .desktop import app_home

    return Path(app_home()) / "proofrun"


# -- the caps -------------------------------------------------------------------------------------------------
def caps_for(art: bool = True, sound: bool = True) -> dict[str, float]:
    """The proof run's caps: $2 text, $0.50 pictures, $0.50 sound (a part left out gets $0)."""
    return {"text_usd": CAPS["text_usd"], "art_usd": CAPS["art_usd"] if art else 0.0,
            "sound_usd": CAPS["sound_usd"] if sound else 0.0}


def checked_caps(caps: dict[str, Any] | None) -> dict[str, float]:
    """The caps as numbers, with the total; refuses anything past the owner's $3 with a plain sentence."""
    out: dict[str, float] = {}
    for key, default in CAPS.items():
        raw = (caps or {}).get(key, default)
        try:
            v = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"The proof run's {key.split('_')[0]} limit must be a number of dollars, such as "
                             f"{default}.") from None
        if v < 0:
            raise ValueError("A limit can't be below $0. Use $0 to leave that part out.")
        out[key] = round(v, 4)
    if out["text_usd"] <= 0:
        raise ValueError("The text limit must be more than $0: the game can't be built without it.")
    out["total_usd"] = round(out["text_usd"] + out["art_usd"] + out["sound_usd"], 4)
    if out["total_usd"] > OWNER_MAX_USD + 1e-9:
        raise ValueError(f"Those limits add up to {_usd(out['total_usd'])}, more than the {_usd(OWNER_MAX_USD)} you "
                         "allowed for the proof run. Lower one of them.")
    return out


# -- the set-up -----------------------------------------------------------------------------------------------
def problems(cfg) -> list[str]:
    """What's wrong with a proof run's set-up, in plain words ([] when it may run): one maker for every chat
    job (DeepSeek V4 Flash, no fallback to another), never V4 Pro, pictures and sound from one service each."""
    out = []
    for name, role in cfg.roles.items():
        refs = [str(m) for m in role.models]
        if any(n in r.lower() for r in refs for n in NEVER):
            out.append(f"The job '{name}' uses DeepSeek V4 Pro, which you said not to use for now.")
        if role.kind == "chat" and refs != [MODEL]:
            out.append(f"The job '{name}' must use {MODEL} alone (it has {', '.join(refs) or 'no model'}).")
        if role.kind == "image" and any(not r.startswith("retrodiffusion/") for r in refs):
            out.append(f"The picture job '{name}' must use Retro Diffusion alone.")
        if role.kind == "sound" and len({r.split('/')[0] for r in refs}) > 1:
            out.append(f"The sound job '{name}' must use one sound service.")
    for pname, prof in (getattr(cfg, "profiles", None) or {}).items():
        out.append(f"The set-up has a setting '{pname}' that could switch models: take it out.")
    return out


def _write_yaml(path: Path, raw: dict[str, Any]) -> None:
    head = "# The proof run's set-up, made by `roundtable proofrun` from proofrun/harness.deepseek.yaml.\n"
    path.write_text(head + yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _drop_role(lab: Path, cfg, name: str) -> None:
    """Leave a job out (pictures or sound): from the running set-up and from the lab's file."""
    if cfg is not None:
        cfg.roles.pop(name, None)
    p = Path(lab) / "harness.yaml"
    if p.is_file():
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        (raw.get("roles") or {}).pop(name, None)
        _write_yaml(p, raw)


def _hub_raw(lab: Path) -> dict[str, Any]:
    return {"storage": {"type": "file", "path": str(lab / "hub-data")}, "default_policy": "deny",
            "agents": {HUB_AGENT: {"repo": "", "description": "The proof run's own made-up hub"}},
            "rules": [{"from": "*", "to": "*", "allow": ["read_card"]}]}


def _state_path(lab: Path) -> Path:
    return Path(lab) / STATE_FILE


def read_state(lab) -> dict[str, Any]:
    try:
        data = json.loads(_state_path(Path(lab)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(lab: Path, state: dict[str, Any]) -> None:
    p = _state_path(lab)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _step(lab: Path, state: dict[str, Any], step: str, words: str, **extra: Any) -> None:
    state.setdefault("steps", []).append({"step": step, "at": _now(), "words": words, **extra})
    _save_state(lab, state)


def prepare(lab, idea: str, caps: dict[str, Any]) -> dict[str, Any]:
    """Make the lab folder and a made-up hub for ``idea`` under ``caps``. Spends nothing and reaches no network.

    ``caps``: ``text_usd`` (default $2), ``art_usd`` ($0.50; 0 leaves the pictures out), ``sound_usd`` ($0.50;
    0 leaves sound out); together never more than $3. Returns what was made and the steps still to come."""
    from .harness.config import parse_config

    lab = Path(lab).expanduser().resolve()
    idea = str(idea or "").strip()
    if not idea:
        raise ValueError("Write the idea first: one or two sentences about the game.")
    c = checked_caps(caps)
    if (lab / PROJECT / ".harness" / "project.json").is_file():
        raise ValueError(f"{lab} already has a proof run. Read its report, or choose a new folder for another.")
    lab.mkdir(parents=True, exist_ok=True)
    (lab / ".harness").mkdir(exist_ok=True)
    (lab / "hub-data").mkdir(exist_ok=True)
    (lab / "idea.md").write_text(idea + "\n", encoding="utf-8")
    (lab / "hub.yaml").write_text(yaml.safe_dump(_hub_raw(lab), sort_keys=False), encoding="utf-8")

    raw = yaml.safe_load(_data("harness.deepseek.yaml")) or {}
    roles = raw.setdefault("roles", {})
    if c["art_usd"] <= 0:
        roles.pop(ART_ROLE, None)
    if c["sound_usd"] <= 0:
        roles.pop(SOUND_ROLE, None)
    raw["hub"] = {"config": str(lab / "hub.yaml"), "agent": HUB_AGENT}
    raw.setdefault("improve", {})["lab_dir"] = str(lab / ".harness-lab")
    raw.setdefault("limits", {})["max_cost_usd"] = c["total_usd"]
    raw["sound"] = {**(raw.get("sound") or {}), "max_per_project_usd": c["sound_usd"]}
    cfg = parse_config(json.loads(json.dumps(raw)), lab / "harness.yaml")
    bad = problems(cfg)
    if bad:  # the shipped set-up is checked by the tests; this guards a hand-edited one
        raise ValueError(" ".join(bad))
    _write_yaml(lab / "harness.yaml", raw)

    state = {"idea": idea, "caps": c, "created_at": _now(), "lab": str(lab), "project": str(lab / PROJECT),
             "config": str(lab / "harness.yaml"), "phase": "prepared",
             "art": {"on": c["art_usd"] > 0, "words": "" if c["art_usd"] > 0 else "Pictures are left out (--no-art)."},
             "sound": {"on": c["sound_usd"] > 0,
                       "words": "" if c["sound_usd"] > 0 else "Sound is left out (--no-sound): the game's sounds are made in code."},
             "steps": []}
    _step(lab, state, "prepare", f"The lab is ready, with its own made-up hub. At most {_usd(c['total_usd'])}.")
    return {"lab": str(lab), "config": state["config"], "project": state["project"], "hub": str(lab / "hub.yaml"),
            "caps": c, "art": state["art"]["on"], "sound": state["sound"]["on"],
            "steps": ["Price the pictures and the sound first (free)", "Read the real balance",
                      "Make the project from the idea and plan it", "Check the estimate against each limit",
                      "Your yes", "Autopilot approves and builds it; the game is started and played",
                      "Read the balance again and write the report"],
            "words": f"Ready. It plans first and stops before building if the plan would cost more than "
                     f"{_usd(c['text_usd'])} of text work or {_usd(c['total_usd'])} in all."}


# -- the money ------------------------------------------------------------------------------------------------
def read_balances(cfg) -> dict[str, dict[str, Any]] | None:
    """The real money left with the chat service (DeepSeek reports it), or None when it can't be read."""
    try:
        from .providers.balance import balances

        got = balances(cfg, [CHAT_PROVIDER])
    except Exception:  # noqa: BLE001 - unreadable is said, never guessed
        return None
    return got or None


def real_fall(before: dict[str, Any] | None, after: dict[str, Any] | None) -> float | None:
    """How far the balance fell between two readings (only services read both times); None when unknown."""
    if not before or not after:
        return None
    both = [p for p in before if p in after]
    if not both:
        return None
    return round(sum(float(before[p]["amount"]) - float(after[p]["amount"]) for p in both), 4)


def price_first(lab, cfg, state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Price one picture and one sound before anything runs (free). A part that can't be priced, or whose cap
    can't pay for one, is left out of the set-up, and the report says so."""
    from .harness import soundprice

    lab = Path(lab)
    state = state if state is not None else read_state(lab)
    caps = state.get("caps") or checked_caps(None)
    art = dict(state.get("art") or {})
    role = cfg.roles.get(ART_ROLE)
    if role and art.get("on", True):
        ref = role.models[0]
        why, usd = "", None
        quote = getattr(cfg.provider(ref.provider), "check_cost", None)
        if quote is None:
            why = "the picture service can't price a picture before making it"
        else:
            try:
                usd = float(quote(ref.model, "a small moth with soft glowing wings, side view",
                                  {k: v for k, v in role.options.items() if k != "record"}))
            except Exception as e:  # noqa: BLE001 - no key, no network: the pictures are left out
                why = f"the picture service couldn't price a picture ({str(e)[:120]})"
        if usd is not None and usd <= 0:
            why, usd = "the picture service gave no price", None
        if usd is not None and usd > float(caps["art_usd"]):
            why = f"one picture costs {_usd(usd)}, more than the pictures' limit of {_usd(caps['art_usd'])}"
        if why:
            art = {"on": False, "words": f"Pictures are left out: {why}. The game is drawn in code instead."}
            _drop_role(lab, cfg, ART_ROLE)
        else:
            cfg.pricing[str(ref)] = {"per_image": usd}  # the estimate prices the picture tasks with it
            p = lab / "harness.yaml"
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            raw.setdefault("pricing", {})[str(ref)] = {"per_image": usd}
            _write_yaml(p, raw)
            art = {"on": True, "usd_each": usd, "most": int(float(caps["art_usd"]) // usd),
                   "words": f"Pictures: about {_usd(usd)} each, at most {_usd(caps['art_usd'])} in all."}
    elif not role:
        art = {"on": False, "words": art.get("words") or "Pictures are left out."}
    sound = dict(state.get("sound") or {})
    role = cfg.roles.get(SOUND_ROLE)
    if role and sound.get("on", True):
        ref = role.models[0]
        try:
            usd = soundprice.per_sound(cfg, ref, "effect", 2.0)
        except Exception:  # noqa: BLE001
            usd = None
        if usd is None:
            sound = {"on": False, "words": "Sound is left out: the sound service couldn't be priced before the run, "
                                           "so the game's sounds are made in code."}
            _drop_role(lab, cfg, SOUND_ROLE)
        else:
            sound = {"on": True, "usd_each": float(usd),
                     "words": f"Sound: about {_usd(float(usd))} a short effect, at most {_usd(caps['sound_usd'])} in all."}
    elif not role:
        sound = {"on": False, "words": sound.get("words") or "Sound is left out: the game's sounds are made in code."}
    state["art"], state["sound"] = art, sound
    _step(lab, state, "price", " ".join(w for w in (art.get("words"), sound.get("words")) if w))
    return {"art": art, "sound": sound}


def split_estimate(cfg, est: dict[str, Any] | None) -> dict[str, Any]:
    """The plan's estimate as text, pictures and sound (the stages' extras and the picture checks are text)."""
    est = est or {}
    art = sound = 0.0
    for name, r in (est.get("by_role") or {}).items():
        role = cfg.roles.get(name)
        kind = getattr(role, "kind", "chat")
        usd = r.get("cost_usd")
        if usd is None:
            continue
        if kind == "image":
            art += float(usd)
        elif kind == "sound":
            sound += float(usd)
    total = est.get("cost_usd")
    text = None if total is None else round(float(total) - art - sound, 4)
    return {"text_usd": text, "art_usd": round(art, 4), "sound_usd": round(sound, 4),
            "total_usd": None if total is None else round(float(total), 4), "unpriced": list(est.get("unpriced") or [])}


def over_caps(parts: dict[str, Any], caps: dict[str, float]) -> str:
    """Why the plan may not be built, in plain words, or "" when it fits every cap."""
    if parts.get("unpriced"):
        return (f"The plan uses something with no price ({', '.join(parts['unpriced'])}), so its cost can't be told. "
                "Nothing was built.")
    if parts.get("total_usd") is None:
        return "The plan has no estimate, so its cost can't be told. Nothing was built."
    for key, what in (("text_usd", "the text work"), ("art_usd", "the pictures"), ("sound_usd", "the sound"),
                      ("total_usd", "everything")):
        if float(parts.get(key) or 0) > float(caps[key]) + 1e-9:
            return (f"The plan's estimate for {what} ({_usd(parts[key])}) is over its limit of {_usd(caps[key])}. "
                    "Nothing was built.")
    return ""


# -- the run --------------------------------------------------------------------------------------------------
def load_lab_config(lab):
    from .harness.config import load_config

    return load_config(str(Path(lab) / "harness.yaml"))


def _events(lab: Path, on_event: Callable[[str, dict[str, Any]], None] | None):
    path = lab / EVENTS_FILE

    def ev(kind: str, data: dict[str, Any]) -> None:
        try:
            row = {"at": _now(), "kind": kind,
                   **{k: (v if isinstance(v, (int, float, bool)) or v is None else str(v)[:300])
                      for k, v in (data or {}).items()}}
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass
        if on_event:
            on_event(kind, data)
    return ev


def _orch(cfg, lab: Path, ev):
    from .harness.orchestrator import Orchestrator

    return Orchestrator(cfg, lab / PROJECT, on_event=ev)


def plan_phase(lab, cfg=None, *, on_event=None, balance: Callable[[Any], Any] | None = None) -> dict[str, Any]:
    """Price first, read the balance, make the project from the idea and plan it, then check the estimate.

    Returns {"go": bool, "words", "estimate": {text_usd, art_usd, sound_usd, total_usd, unpriced}, "status"}.
    ``go`` False: it stopped before anything was built (over a cap, unpriced, or the plan didn't come)."""
    from .harness import projectsettings

    lab = Path(lab).expanduser().resolve()
    state = read_state(lab)
    if not state:
        raise ValueError("Make the lab first (roundtable proofrun does it for you).")
    if state.get("phase") not in ("prepared",):
        raise ValueError(f"This proof run is already {state.get('phase')}. Read its report, or start a new one.")
    cfg = cfg if cfg is not None else load_lab_config(lab)
    bad = problems(cfg)
    if bad:
        raise ValueError(" ".join(bad))
    balance = balance or read_balances
    ev = _events(lab, on_event)
    state["started_at"] = _now()
    state["t0"] = time.time()
    price_first(lab, cfg, state)
    state["balance_before"] = balance(cfg)
    _step(lab, state, "balance", "The real balance before: " + _balance_words(state["balance_before"]))

    orch = _orch(cfg, lab, ev)
    orch.start(state["idea"], require_approval=True)
    try:
        orch.set_kind(KIND, extras=[], by="proofrun", replan=False)
    except Exception as e:  # noqa: BLE001 - the kind is a help: the run still proves the rest
        _step(lab, state, "kind", f"The kind couldn't be set to Browser game ({str(e)[:200]}).")
    caps = state["caps"]
    allowed = [CHAT_PROVIDER] + [cfg.roles[r].models[0].provider for r in (ART_ROLE, SOUND_ROLE) if r in cfg.roles]
    projectsettings.update(orch.project.root, {
        "checking": "lean", "ask_first": "risky", "providers_allowed": sorted(set(allowed)),
        "limits": {"max_cost_usd": caps["total_usd"], "max_real_usd_per_run": caps["text_usd"],
                   **({"max_image_usd": caps["art_usd"]} if caps.get("art_usd") else {})},
    })
    orch = _orch(cfg, lab, ev)  # the project's own limits are read when it starts
    status = orch.run()
    doc = orch.project.plan_doc() or {}
    parts = split_estimate(orch.cfg, doc.get("estimate"))
    state["estimate"] = parts
    state["plan_status"] = status
    why = "" if status == "awaiting_approval" else f"Planning ended as {status.replace('_', ' ')}, not with a plan."
    why = why or over_caps(parts, caps)
    if why:
        state["phase"], state["stopped"] = "stopped", why
        state["ended_at"] = _now()
        _step(lab, state, "estimate", why)
        _finish_up(lab, cfg, state, balance, read_after=True)
        return {"go": False, "words": why, "estimate": parts, "status": status}
    state["phase"] = "estimated"
    words = (f"The plan: {len(orch.project.tasks())} tasks, about {_usd(parts['total_usd'])} "
             f"({_usd(parts['text_usd'])} text, {_usd(parts['art_usd'])} pictures, {_usd(parts['sound_usd'])} sound). "
             f"It stops at {_usd(caps['total_usd'])}.")
    _step(lab, state, "estimate", words)
    return {"go": True, "words": words, "estimate": parts, "status": status}


def build_phase(lab, cfg=None, *, on_event=None, balance: Callable[[Any], Any] | None = None,
                max_ticks: int = 30, real_hub=None, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """After the owner's yes: autopilot (in the lab only, the caps as its limit) approves under its own rules
    and builds; the balance is read again; the report and the findings are written. Returns the report."""
    from . import autopilot
    from .asks import finish

    lab = Path(lab).expanduser().resolve()
    state = read_state(lab)
    if state.get("phase") != "estimated":
        raise ValueError("There's no plan waiting for a yes. Start the proof run first.")
    cfg = cfg if cfg is not None else load_lab_config(lab)
    bad = problems(cfg)
    if bad:
        raise ValueError(" ".join(bad))
    balance = balance or read_balances
    ev = _events(lab, on_event)
    state["phase"] = "building"
    state["build_started_at"] = _now()
    _step(lab, state, "yes", "You said yes. Autopilot approves the plan under its own rules and builds it.")
    home = lab / "autopilot"
    runs: list[dict[str, Any]] = []

    def start(c, root, r):
        o = _orch(c, lab, ev)
        line = finish(o, r)
        runs.append({"at": _now(), "then": r.get("then"), "line": line, "status": o.project.meta().get("status")})
        return line

    until = _until(_orch(cfg, lab, ev))
    autopilot.turn_on(until=until, cap=state["caps"]["total_usd"], home=home, cfg=cfg)
    chose = left = 0
    try:
        for _ in range(max(1, int(max_ticks))):
            out = autopilot.tick(cfg, home=home, start=start)
            picked = [e for e in out if e.get("kind") == "chose"]
            chose += len(picked)
            left += sum(1 for e in out if e.get("kind") == "left")
            if _wait_for_half_price(lab, cfg, ev, state, runs, sleep):
                continue
            if not picked:
                break
    finally:
        autopilot.turn_off("the proof run finished.", home, cfg)
    state["runs"], state["autopilot"] = runs, {"chose": chose, "left": left}
    state["phase"] = "done"
    state["ended_at"] = _now()
    _step(lab, state, "build", f"Autopilot answered {chose} card{'s' * (chose != 1)}; {left} left for a person.")
    return _finish_up(lab, cfg, state, balance, read_after=True, real_hub=real_hub)


HALF_PRICE_WAIT_MIN = 45  # half price starting sooner than this is waited for; later, it builds now


def _until(orch) -> str | None:
    """When the lab's autopilot stops: never, unless half price is far off, so autopilot builds now instead of
    waiting hours for it (it prefers half price only when that starts before it stops)."""
    try:
        at = orch.cheap_start_at()
    except Exception:  # noqa: BLE001
        at = None
    if at is None or (at - datetime.now(timezone.utc)).total_seconds() < HALF_PRICE_WAIT_MIN * 60:
        return None
    return (at - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _wait_for_half_price(lab: Path, cfg, ev, state: dict[str, Any], runs: list, sleep) -> bool:
    """Autopilot chose half price, soon: wait for it, then start the run as the desktop app would. True when
    it ran (so autopilot looks at the cards again)."""
    from .harness.orchestrator import Project

    meta = Project(lab / PROJECT).meta()
    after = meta.get("start_after")
    if meta.get("status") != "waiting_cheap" or not after:
        return False
    try:
        at = datetime.fromisoformat(str(after).replace("Z", "+00:00"))
    except ValueError:
        return False
    wait = max(0.0, (at - datetime.now(timezone.utc)).total_seconds())
    if wait > HALF_PRICE_WAIT_MIN * 60 + 60:
        return False  # not ours to wait so long: the report says it's waiting
    _step(lab, state, "half_price", f"Autopilot chose half price, which starts at {at.strftime('%H:%M')} UTC: "
                                    f"waiting {wait / 60:.0f} minutes.")
    sleep(wait + 5)
    o = _orch(cfg, lab, ev)
    runs.append({"at": _now(), "then": "run", "line": f"The run ended as: {o.run().replace('_', ' ')}.",
                 "status": o.project.meta().get("status")})
    return True


def _finish_up(lab: Path, cfg, state: dict[str, Any], balance, read_after: bool, real_hub=None) -> dict[str, Any]:
    if read_after:
        state["balance_after"] = balance(cfg)
        _step(lab, state, "balance", "The real balance after: " + _balance_words(state["balance_after"]))
    rep = report(lab)
    (lab / REPORT_FILE).write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    found = findings(rep)
    (lab / FINDINGS_FILE).write_text(findings_markdown(found, rep), encoding="utf-8")
    if real_hub is not None:
        state["journal"] = write_journal_line(real_hub, rep, found)
        _save_state(lab, state)
    return rep


def run(lab, cfg=None, *, yes: Callable[[str], bool] | None = None, on_event=None,
        balance: Callable[[Any], Any] | None = None, max_ticks: int = 30, real_hub=None,
        sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Plan, show the estimate to ``yes`` (None: stop there and wait), then build. Returns the report."""
    lab = Path(lab).expanduser().resolve()
    got = plan_phase(lab, cfg, on_event=on_event, balance=balance)
    if not got["go"]:
        return report(lab)
    if yes is None or not yes(got["words"]):
        state = read_state(lab)
        _step(lab, state, "wait", "Waiting for your yes: nothing is built until then.")
        return report(lab)
    return build_phase(lab, cfg, on_event=on_event, balance=balance, max_ticks=max_ticks, real_hub=real_hub,
                       sleep=sleep)


# -- the report -----------------------------------------------------------------------------------------------
def _balance_words(b: dict[str, Any] | None) -> str:
    if not b:
        return "couldn't be read (it isn't guessed)."
    return ", ".join(f"{name} {float(v['amount']):.4f} {v.get('currency', 'USD')}" for name, v in b.items()) + "."


def _short(evidence: Any, n: int = 300) -> str:
    if not evidence:
        return ""
    text = evidence if isinstance(evidence, str) else json.dumps(evidence, ensure_ascii=False)
    return text if len(text) <= n else text[:n - 1] + "…"


def _gap(a: float | None, b: float | None) -> float | None:
    """How far ``a`` is from ``b``, as a percentage of ``b``."""
    if a is None or b is None or b <= 0:
        return None
    return round((a - b) / b * 100, 1)


def _files(root: Path, patterns: tuple[str, ...], under: str = "") -> list[str]:
    base = root / under if under else root
    out: list[str] = []
    if not base.is_dir():
        return out
    for pat in patterns:
        for p in sorted(base.rglob(pat)):
            rel = p.relative_to(root).as_posix()
            if p.is_file() and "/.git/" not in f"/{rel}" and "node_modules/" not in rel and rel not in out:
                out.append(rel)
    return out[:60]


def _seeing(cfg) -> dict[str, Any]:
    from . import attachments

    sees = []
    for name, role in (cfg.roles.items() if cfg is not None else []):
        for ref in role.models if role.kind == "chat" else []:
            try:
                if attachments.can_see(cfg, str(ref)):
                    sees.append(str(ref))
            except Exception:  # noqa: BLE001
                continue
    if sees:
        return {"can_see": True, "models": sorted(set(sees)), "words": "A model that can see looked at the game."}
    return {"can_see": False, "models": [],
            "words": "Playing it for a minute: not checked: no model that can see was allowed.",
            "offer": {"usd_max": SEEING_PASS_USD,
                      "words": f"A second pass with one model that can see would look at the game for at most "
                               f"{_usd(SEEING_PASS_USD)}. Only with your yes."}}


def report(lab) -> dict[str, Any]:
    """The estimate, the harness's own count and the real fall in the balance, side by side, with the tasks,
    every place a person had to step in, the done list, the pictures, the time and the game's looks and sounds."""
    lab = Path(lab).expanduser()
    state = read_state(lab)
    if not state:
        return {"ready": False, "words": "No proof run yet."}
    from .harness.orchestrator import Project

    root = Path(state.get("project") or lab / PROJECT)
    proj = Project(root)
    meta = proj.meta() if proj.exists else {}
    tasks = proj.tasks() if proj.exists else []
    doc = (proj.plan_doc() or {}) if proj.exists else {}
    caps = state.get("caps") or {}
    est = state.get("estimate") or {}
    estimate = (meta.get("agreed") or {}).get("usd")
    if estimate is None:
        estimate = est.get("total_usd")
    counted = round(float(meta.get("spent_usd") or 0), 4) if meta else None
    real = real_fall(state.get("balance_before"), state.get("balance_after"))
    real_words = ("The real balance couldn't be read before and after, so the real cost isn't known (it isn't "
                  "guessed)." if real is None and state.get("phase") in ("done", "stopped")
                  else "Read before and after." if real is not None else "Not read yet.")
    money = {"estimate_usd": estimate, "counted_usd": counted, "real_usd": real,
             "gap_pct": _gap(real if real is not None else counted, estimate),
             "count_gap_pct": _gap(counted, real), "caps": caps, "real_words": real_words,
             "table": [{"what": "The estimate before building", "usd": estimate},
                       {"what": "The harness's own count", "usd": counted},
                       {"what": "The real fall in the balance", "usd": real}]}

    split_ids: list[str] = []
    try:
        split_ids = json.loads((root / ".harness" / "split.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    first = [t.id for t in tasks if t.status == "done" and len(t.attempts) <= 1]
    retried = [t.id for t in tasks if t.status == "done" and len(t.attempts) > 1]
    parked = [t.id for t in tasks if t.parked or t.status == "skipped"]
    failed = [t.id for t in tasks if t.status == "failed"]
    task_part = {"total": len(tasks), "first_time": first, "retried": retried, "split": list(split_ids),
                 "parked": parked, "failed": failed,
                 "pending": [t.id for t in tasks if t.status in ("pending", "running")],
                 "items": [{"id": t.id, "title": t.title, "role": t.role, "status": t.status,
                            "attempts": len(t.attempts), "summary": (t.summary or "")[:300]} for t in tasks]}

    from .harness import donelist

    done = donelist.read(root)["items"] if proj.exists else []
    done_part = [{"id": i.get("id"), "text": i.get("text", ""), "how": i.get("how", ""), "state": i.get("state", "open"),
                  "words": i.get("words", ""), "evidence": _short(i.get("evidence"))} for i in done]

    cfg = None
    try:
        cfg = load_lab_config(lab) if (lab / "harness.yaml").is_file() else None
    except Exception:  # noqa: BLE001 - the report still says what it can
        cfg = None
    seeing = _seeing(cfg)

    people: list[dict[str, str]] = []
    try:
        from . import autopilot

        for e in autopilot.entries(lab / "autopilot", limit=200):
            if e.get("kind") == "left":
                people.append({"where": "a card", "what": str(e.get("text") or "")})
    except Exception:  # noqa: BLE001
        pass
    for tid in failed:
        t = next(x for x in tasks if x.id == tid)
        people.append({"where": f"task {tid}", "what": f"Stuck: “{t.title}” didn't pass ({(t.summary or '')[:160]})."})
    if estimate and counted is not None and abs(_gap(counted, estimate) or 0) > WRONG_ESTIMATE * 100:
        people.append({"where": "the estimate",
                       "what": f"The estimate ({_usd(estimate)}) was {abs(_gap(counted, estimate)):.0f}% off what "
                               f"it cost ({_usd(counted)})."})
    for i in done_part:
        if i["state"] in ("open", "unchecked") and state.get("phase") == "done":
            people.append({"where": f"done list {i['id']}", "what": f"Not checked: {i['text'][:160]}"})
    if not seeing["can_see"] and state.get("phase") == "done":
        people.append({"where": "playing it", "what": seeing["words"]})

    kinds: dict[str, int] = {}
    errors: list[dict[str, str]] = []
    try:
        for ln in (lab / EVENTS_FILE).read_text(encoding="utf-8").splitlines():
            row = json.loads(ln)
            k = str(row.get("kind"))
            kinds[k] = kinds.get(k, 0) + 1
            if k in ERRORS_AT and len(errors) < 30:
                errors.append({"kind": k, "error": str(row.get("error") or row.get("summary") or "")[:300]})
    except (OSError, ValueError):
        pass

    pics = [p for p in _files(root, ("*.png", "*.gif", "*.webp"), "assets")]
    sounds = _files(root, ("*.mp3", "*.wav", "*.ogg"))
    shots = [p for p in _files(root, ("*.png",), ".harness") if "/by-commit/" not in p]
    t0, t1 = state.get("started_at"), state.get("ended_at")
    minutes = None
    try:
        if t0 and t1:
            a = datetime.fromisoformat(t0.replace("Z", "+00:00"))
            b = datetime.fromisoformat(t1.replace("Z", "+00:00"))
            minutes = round((b - a).total_seconds() / 60, 1)
    except ValueError:
        minutes = None
    status = meta.get("status") or state.get("phase")
    n_done = len(first) + len(retried)
    if state.get("stopped"):
        words = f"Stopped before building: {state['stopped']}"
    elif state.get("phase") == "done":
        words = (f"{'Built' if status == 'done' else 'Not finished'}: {n_done} of {len(tasks)} tasks passed; "
                 f"{_usd(counted)} counted, {_usd(real)} real, estimate {_usd(estimate)}.")
    elif state.get("phase") == "estimated":
        words = "Planned and priced; waiting for your yes. Nothing is built until then."
    else:
        words = f"The proof run is {state.get('phase', 'prepared')}."
    return {"ready": True, "words": words, "phase": state.get("phase"), "status": status,
            "pause": meta.get("pause") or "", "reason": str(meta.get("reason") or "")[:300],
            "stopped": state.get("stopped", ""), "idea": state.get("idea", ""), "lab": str(lab), "project": str(root),
            "title": (doc.get("title") or "") if doc else "", "money": money, "estimate": est, "tasks": task_part,
            "people": people, "done_list": done_part, "screenshots": shots,
            "looks": {"pictures": pics, "words": state.get("art", {}).get("words", "")},
            "sounds": {"files": sounds, "words": state.get("sound", {}).get("words", "")},
            "seeing": seeing, "time": {"started": t0, "ended": t1, "minutes": minutes},
            "autopilot": state.get("autopilot") or {}, "runs": state.get("runs") or [],
            "events": kinds, "errors": errors, "steps": state.get("steps") or [], "about": ABOUT}


# -- the findings ---------------------------------------------------------------------------------------------
def findings(rep: dict[str, Any]) -> list[dict[str, str]]:
    """Each place the run fell short, as {where, expected, happened, file}: the file most likely at fault.
    The rule (CLAUDE.md): each becomes a fix with a test, or a line in plans/gaps.md with its release."""
    if not rep.get("ready"):
        return []
    out: list[dict[str, str]] = []

    def add(where: str, expected: str, happened: str, file: str) -> None:
        out.append({"where": where, "expected": expected, "happened": happened, "file": file})

    money = rep.get("money") or {}
    est, counted, real = money.get("estimate_usd"), money.get("counted_usd"), money.get("real_usd")
    if rep.get("stopped"):
        add("before building", "a plan that fits the limits, priced", rep["stopped"],
            "src/roundtable/harness/plandoc.py (estimate)")
    if rep.get("phase") in ("done", "stopped") and real is None:
        add("the real balance", "read before and after the run",
            "It couldn't be read, so the real cost isn't known.", "src/roundtable/providers/balance.py")
    gap = _gap(counted, est)
    if est and counted is not None and rep.get("phase") == "done" and abs(gap or 0) > WRONG_ESTIMATE * 100:
        add("the estimate", f"within {WRONG_ESTIMATE:.0%} of what it cost",
            f"estimated {_usd(est)}, counted {_usd(counted)} ({gap:+.0f}%)", "src/roundtable/harness/plandoc.py (estimate)")
    cgap = money.get("count_gap_pct")
    if cgap is not None and abs(cgap) > WRONG_COUNT * 100:
        add("the harness's own count", f"within {WRONG_COUNT:.0%} of the real fall in the balance",
            f"counted {_usd(counted)}, the balance fell {_usd(real)} ({cgap:+.0f}%)",
            "src/roundtable/harness/config.py (DEFAULT_PRICING) and providers/openai_compat.py (usage)")
    tasks = rep.get("tasks") or {}
    items = {t["id"]: t for t in tasks.get("items") or []}
    for tid in tasks.get("failed") or []:
        t = items.get(tid, {})
        add(f"task {tid} ({t.get('role', '')})", "it passes its check, at most after the stuck-task helper",
            f"stuck after {t.get('attempts', 0)} attempts: {t.get('summary', '')[:200]}",
            "src/roundtable/harness/unstick.py, then the role's prompt")
    for tid in tasks.get("split") or []:
        add(f"task {tid}", "small enough for one attempt", "it ran out of steps and was split",
            "src/roundtable/prompts/orchestrator.md (task sizes)")
    for tid in tasks.get("retried") or []:
        t = items.get(tid, {})
        add(f"task {tid} ({t.get('role', '')})", "passed the first time",
            f"passed after {t.get('attempts', 0)} attempts", "the role's prompt (src/roundtable/prompts/)")
    if rep.get("phase") == "done" and rep.get("status") != "done":
        why = f" ({rep['reason']})" if rep.get("reason") else ""
        add("the run", "it ends done", f"it ended as {str(rep.get('status')).replace('_', ' ')}{why}",
            "src/roundtable/harness/orchestrator.py (_run)")
    for p in rep.get("people") or []:
        if p["where"] == "a card":
            add("a card", "autopilot or the harness answers it", p["what"], "src/roundtable/autopilot.py (decide)")
        elif p["where"].startswith("done list"):
            add(p["where"], "checked by the finishing step", p["what"], "src/roundtable/harness/finishstage.py")
    seeing = rep.get("seeing") or {}
    if rep.get("phase") == "done" and not seeing.get("can_see"):
        add("playing it", "a model that can see plays it for a minute",
            "not checked: no model that can see was allowed (an all-DeepSeek build can't see)",
            "src/roundtable/proofrun/harness.deepseek.yaml (one seeing model, at most $0.20, with a yes)")
    for part, what in (("looks", "pictures"), ("sounds", "sound")):
        w = (rep.get(part) or {}).get("words", "")
        if " left out: " in w and "(--no-" not in w:
            add(what, f"{what} made by the service, priced first", w,
                "src/roundtable/providers/retrodiffusion.py" if part == "looks" else "src/roundtable/harness/soundprice.py")
    seen = set()
    for e in rep.get("errors") or []:
        key = (e["kind"], e["error"][:80])
        if key in seen:
            continue
        seen.add(key)
        add(f"an event ({e['kind']})", "no errors", e["error"] or e["kind"], ERRORS_AT.get(e["kind"], "?"))
    return out


def findings_markdown(found: list[dict[str, str]], rep: dict[str, Any]) -> str:
    money = rep.get("money") or {}
    lines = ["# Proof run findings", "",
             f"_{rep.get('words', '')}_", "",
             "| What | Dollars |", "|---|---|"]
    for row in money.get("table") or []:
        lines.append(f"| {row['what']} | {_usd(row['usd'])} |")
    gap = money.get("gap_pct")
    lines += ["", f"Gap between the estimate and what it cost: {'not known' if gap is None else f'{gap:+.1f}%'}.", ""]
    if not found:
        lines.append("Nothing fell short.")
    for i, f in enumerate(found, 1):
        lines += [f"{i}. **{f['where']}**: expected {f['expected']}; {f['happened']}. Most likely: `{f['file']}`."]
    lines += ["", "Each becomes a fix with a test, or a line in plans/gaps.md with the release it belongs to.", ""]
    return "\n".join(lines)


# -- the one line for the real hub ----------------------------------------------------------------------------
def journal_line(rep: dict[str, Any], found: list[dict[str, str]]) -> str:
    """The only thing the real hub hears of a proof run: numbers, no idea, no task, no file."""
    t = rep.get("tasks") or {}
    m = rep.get("money") or {}
    n = len(t.get("first_time") or []) + len(t.get("retried") or [])
    state = "stopped before building" if rep.get("stopped") else str(rep.get("status") or "").replace("_", " ")
    return (f"Proof run {state}: {n} of {t.get('total', 0)} tasks passed; estimate {_usd(m.get('estimate_usd'))}, "
            f"counted {_usd(m.get('counted_usd'))}, real {_usd(m.get('real_usd'))}; {len(found)} finding"
            f"{'s' * (len(found) != 1)}.")


def write_journal_line(real_cfg, rep: dict[str, Any], found: list[dict[str, str]]) -> str | None:
    """Write that one line in the real hub's journal (the harness config's ``hub``), as a note. None: no hub."""
    hub_spec = getattr(real_cfg, "hub", None)
    if not hub_spec:
        return None
    try:
        from .core.config import load_config as load_hub_config
        from .hub.service import Hub

        hub = Hub(load_hub_config(hub_spec.get("config")))
        return hub.journal.add(hub_spec.get("agent") or "harness", "note", journal_line(rep, found),
                               source="proofrun")["id"]
    except Exception:  # noqa: BLE001 - the hub is optional
        return None


# -- the command line -----------------------------------------------------------------------------------------
def add_arguments(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
    p.add_argument("--lab", help="the folder for the proof run (default: the app's own, <app home>/proofrun)")
    p.add_argument("--idea", metavar="FILE", help="the idea, from a file (default: Lantern Run, a made-up game)")
    p.add_argument("--no-art", action="store_true", help="no pictures from a picture service (drawn in code)")
    p.add_argument("--no-sound", action="store_true", help="no sounds from a sound service (made in code)")
    p.add_argument("--yes", action="store_true", help="build without asking once the estimate fits the limits")
    p.add_argument("--report", action="store_true", help="only show the report of the lab's proof run")
    return p


def _print_report(rep: dict[str, Any], out=print) -> None:
    out(rep.get("words", ""))
    if not rep.get("ready"):
        return
    for row in (rep.get("money") or {}).get("table") or []:
        out(f"  {row['what']:32} {_usd(row['usd'])}")
    gap = (rep.get("money") or {}).get("gap_pct")
    if gap is not None:
        out(f"  {'Gap from the estimate':32} {gap:+.1f}%")
    for p in rep.get("people") or []:
        out(f"  needed a person · {p['where']}: {p['what']}")


def main(args: argparse.Namespace, *, real_cfg_loader: Callable[[], Any] | None = None,
         ask: Callable[[str], str] = input, out=print) -> int:
    """``roundtable proofrun``: prepare, price first, plan, the estimate, a yes, the run, the report."""
    lab = Path(args.lab).expanduser() if getattr(args, "lab", None) else default_lab()
    if getattr(args, "report", False):
        _print_report(report(lab), out)
        return 0
    idea = Path(args.idea).read_text(encoding="utf-8") if getattr(args, "idea", None) else default_idea()
    caps = caps_for(art=not args.no_art, sound=not args.no_sound)
    if not read_state(lab):
        got = prepare(lab, idea, caps)
        out(got["words"])
    real = None
    if real_cfg_loader is not None:
        try:
            real = real_cfg_loader()
        except Exception:  # noqa: BLE001 - no harness.yaml of your own: no journal line
            real = None
    try:
        from .harness_cli import _printer

        printer = _printer(bool(getattr(args, "verbose", False)))
    except Exception:  # noqa: BLE001
        printer = None

    def yes(words: str) -> bool:
        out(words)
        if args.yes:
            return True
        return str(ask("Build it? [y/N] ")).strip().lower() in ("y", "yes")

    state = read_state(lab)
    if state.get("phase") == "estimated":
        rep = build_phase(lab, on_event=printer, real_hub=real) if yes(state["steps"][-1]["words"]) else report(lab)
    elif state.get("phase") == "prepared":
        rep = run(lab, yes=yes, on_event=printer, real_hub=real)
    else:
        rep = report(lab)
    _print_report(rep, out)
    if rep.get("phase") in ("done", "stopped"):
        out(f"Findings: {lab / FINDINGS_FILE}")
    return 0 if not rep.get("stopped") else 1


def copy_findings(lab, dest) -> Path:
    """Copy the findings into the repository (plans/proofrun-findings.md) for the coordinator."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(lab) / FINDINGS_FILE, dest)
    return dest
