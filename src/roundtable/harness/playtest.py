"""Play-testing: a model that can see plays the game for a minute and says what broke or felt wrong.

* ``play_browser``: a browser game, turn by turn. Each turn a picture; the chooser picks one input from a
  fixed set (a key tapped or held, a click at a point, a wait); the input is applied. The console's errors
  are collected, a screen that stops changing while it is being played is spotted (``proof.difference`` on
  consecutive pictures), and only the game's own address may load.
* ``play_godot``: a Godot game. Godot can't be steered turn by turn from outside, so the inputs are planned
  first from the game's own input actions and pressed by a temporary driver script given on the command
  line (``godot.record_play``); Movie Maker records it and the frames are kept. The model watches the frames
  afterwards. The project's own files are never changed.
* ``ModelChooser``: the chooser in a real run, the seeing model ``proof._seeing_ref`` picks (the same rule
  as the proof's: a project kept to named providers only uses those). It ends with one tool, ``report_play``
  {worked, summary, findings: [{what, severity, when}]}, ``severity`` broken, rough or idea. Capped by money
  (``max_usd`` a play, charged to the run's budget) and by turns.
* ``PlayStage``: the Orchestrator's side. ``_play_check(item)`` for a done-list item with ``how: play``
  returns {passed, words, evidence}; broken findings fail it (so the finish step makes fix tasks), rough
  ones and ideas are listed for the owner and never built by themselves. ``_play_estimate(tasks)`` is the
  line in the estimate, only for kinds with a play check.

Playing is a help: with no model that can see, no Playwright or no Godot, the item stays unchecked with the
reason, never passed. Pictures go to ``.harness/play/goal-<n>/<item>/``.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from ..brand import NAME
from ..core.models import utcnow
from . import godot as godotlib
from . import proof as prooflib

PLAY_DIR = "play"  # under .harness/
RECORD = "play.json"
KEYS = ("ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Space", "Enter", "Escape", "KeyW", "KeyA", "KeyS",
        "KeyD", "KeyZ", "KeyX", "ShiftLeft")
DOS = ("tap", "hold", "click", "wait")
SEVERITIES = ("broken", "rough", "idea")
WIDTH, HEIGHT = 1280, 800
FROZEN_CHANGE = 0.002  # less than this share of the picture changed: the same screen
FROZEN_TURNS = 3  # this many played turns in a row on the same screen: frozen
MAX_TURNS = 30
MAX_HOLD_MS = 3000
MAX_FINDINGS = 12
CHOOSE_MAX_TOKENS = 300
REPORT_MAX_TOKENS = 900
REPORT_PICTURES = 4  # pictures the model sees when it writes the report on a Godot play
MAX_ERRORS = 20

SYSTEM = ("You play-test a game for its owner, who isn't a programmer. Play it as a person would: start it, try "
          "every control, try to lose and start again. Each turn you see the screen and choose one input with "
          "play_input. When you have seen enough, or on the last turn, call report_play once: worked (true or "
          "false), summary (one short plain sentence), and findings. A finding's severity is broken (play stops "
          "or is plainly wrong: a freeze, an error, a control that does nothing, a crash), rough (it works but "
          "feels wrong) or idea (a suggestion). Be honest and never guess: only report what you saw.")
WATCH_SYSTEM = ("You check a play-test of a game for its owner, who isn't a programmer. The harness played it with "
                "the inputs listed and recorded it; you see pictures taken through the play. Call report_play once: "
                "worked (true or false), summary (one short plain sentence), and findings with severity broken "
                "(play stops or is plainly wrong), rough (works but feels wrong) or idea (a suggestion). Be "
                "honest and never guess: only report what the pictures and the errors show.")


@dataclass
class Settings:
    enabled: str = "auto"  # auto | on | off (auto: when the kind has a play check)
    seconds: int = 60
    turns: int = 12
    max_usd: float = 0.30
    role: str = "proof"

    @classmethod
    def from_config(cls, cfg: Any) -> "Settings":
        from .config import section

        s = cls()
        raw = section(cfg, "playtest") if cfg is not None else {}
        if "enabled" in raw:
            v = raw["enabled"]
            s.enabled = ("on" if v else "off") if isinstance(v, bool) else (
                {"true": "on", "yes": "on", "false": "off", "no": "off"}.get(str(v).strip().lower(),
                                                                                str(v).strip().lower()))
            if s.enabled not in ("auto", "on", "off"):
                s.enabled = "auto"
        for k, typ in (("seconds", int), ("turns", int), ("max_usd", float), ("role", str)):
            if raw.get(k) is not None:
                try:
                    setattr(s, k, typ(raw[k]))
                except (TypeError, ValueError):
                    pass
        s.seconds = max(5, min(300, s.seconds))
        s.turns = max(2, min(MAX_TURNS, s.turns))
        s.max_usd = max(0.0, s.max_usd)
        return s

    @property
    def on(self) -> bool:
        return self.enabled != "off"

    def for_seconds(self, seconds: Any) -> tuple[int, int, float]:
        """(seconds, turns, money) for one play: a shorter play gets fewer turns and less money."""
        try:
            secs = int(float(seconds)) if seconds else self.seconds
        except (TypeError, ValueError):
            secs = self.seconds
        secs = max(5, min(self.seconds, secs))
        share = secs / self.seconds
        return secs, max(2, min(self.turns, round(self.turns * share))), round(self.max_usd * share, 4)


# -- small pure pieces -----------------------------------------------------------------------------------------
def clean_action(raw: Any) -> dict[str, Any]:
    """One input from the fixed set; anything else is a wait."""
    raw = raw if isinstance(raw, dict) else {}
    do = str(raw.get("do") or "").strip().lower()
    if do not in DOS:
        return {"do": "wait", "ms": 0}
    out: dict[str, Any] = {"do": do}
    try:
        out["ms"] = max(0, min(MAX_HOLD_MS, int(raw.get("ms") or (600 if do == "hold" else 0))))
    except (TypeError, ValueError):
        out["ms"] = 0
    if do in ("tap", "hold"):
        key = str(raw.get("key") or "")
        if key not in KEYS:
            return {"do": "wait", "ms": out["ms"]}
        out["key"] = key
    if do == "click":
        try:
            out["x"] = max(0, min(WIDTH - 1, int(raw.get("x"))))
            out["y"] = max(0, min(HEIGHT - 1, int(raw.get("y"))))
        except (TypeError, ValueError):
            return {"do": "wait", "ms": 0}
    return out


def action_words(a: dict[str, Any]) -> str:
    if a.get("do") == "tap":
        return f"tapped {a['key']}"
    if a.get("do") == "hold":
        return f"held {a['key']} for {a.get('ms', 0)} ms"
    if a.get("do") == "click":
        return f"clicked at {a['x']},{a['y']}"
    return "waited"


def clean_report(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    findings = []
    for f in raw.get("findings") or []:
        if not isinstance(f, dict) or not str(f.get("what") or "").strip():
            continue
        sev = str(f.get("severity") or "").strip().lower()
        findings.append({"what": str(f["what"]).strip()[:300], "severity": sev if sev in SEVERITIES else "rough",
                         "when": str(f.get("when") or "").strip()[:80], "by": "model"})
    worked = raw.get("worked")
    return {"worked": worked if isinstance(worked, bool) else str(worked).strip().lower() in ("true", "yes", "1"),
            "summary": str(raw.get("summary") or "").strip()[:300], "findings": findings[:MAX_FINDINGS]}


def frozen_at(changes: list[float | None], acted: list[bool], need: int = FROZEN_TURNS) -> int | None:
    """The turn (1-based) a screen stopped changing while being played, or None.

    ``changes[i]`` is how much picture i differs from picture i-1 (None for the first); ``acted[i]`` is
    whether an input went in between them. ``need`` played turns in a row on the same screen is a freeze."""
    run = 0
    for i, c in enumerate(changes):
        if i == 0 or c is None:
            run = 0
            continue
        played = acted[i] if i < len(acted) else True
        if c < FROZEN_CHANGE:
            if played:
                run += 1
                if run >= need:
                    return i - need + 2  # the first turn on the same screen, counted from 1
        else:
            run = 0
    return None


def verdict(report: dict[str, Any] | None, findings: list[dict[str, Any]]) -> bool | None:
    """Failed on any broken finding (the harness's own or the model's); passed only when the model reported
    it worked with nothing broken; otherwise not checked."""
    if any(f["severity"] == "broken" for f in findings):
        return False
    if report is None:
        return None
    return bool(report.get("worked"))


def words_for(result: dict[str, Any]) -> str:
    """The line the owner reads."""
    secs = result.get("seconds") or 0
    if result.get("passed") is None:
        return "Not played: " + (result.get("why_words") or "it couldn't be played here")
    broken = [f for f in result.get("findings") or [] if f["severity"] == "broken"]
    rest = [f for f in result.get("findings") or [] if f["severity"] != "broken"]
    ideas = f" ({len(rest)} idea{'s' * (len(rest) != 1)} for you)" if rest else ""
    if result["passed"]:
        return f"Played for {secs} seconds: it worked" + (f" – {result['summary']}" if result.get("summary") else "") + ideas
    first = broken[0]["what"] if broken else (result.get("summary") or "it didn't work")
    more = f" (and {len(broken) - 1} more)" if len(broken) > 1 else ""
    return f"Played for {secs} seconds: {first}{more}"


def _unchecked(why: str, words: str, **kw: Any) -> dict[str, Any]:
    return {"checked": False, "passed": None, "why": why, "why_words": words, "findings": [], "errors": [],
            "pictures": [], "frozen": None, "turns": 0, "cost_usd": 0.0, "summary": "", **kw,
            "words": "Not played: " + words}


def _finish(result: dict[str, Any], report: dict[str, Any] | None, own: list[dict[str, Any]]) -> dict[str, Any]:
    findings = own + (report or {}).get("findings", [])
    result.update(findings=findings[:MAX_FINDINGS], summary=(report or {}).get("summary", ""),
                  worked=(report or {}).get("worked"), checked=report is not None or bool(own))
    if report is not None and report.get("worked") is False and not any(f["severity"] == "broken" for f in findings):
        result["findings"].insert(0, {"what": report.get("summary") or "the model that played it says it didn't work",
                                      "severity": "broken", "when": "", "by": "model"})
    result["passed"] = verdict(report, result["findings"])
    result["words"] = words_for(result)
    return result


# -- the browser -----------------------------------------------------------------------------------------------
class NoDriver(RuntimeError):
    """Playwright for Python isn't installed: the game can't be played here."""


class PlaywrightDriver:
    """A real browser through Playwright for Python: one page, the game's own address only."""

    def __init__(self) -> None:
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError as e:
            raise NoDriver("Playwright for Python isn't installed") from e
        self._pw = self._browser = self.page = None
        self._errors: list[str] = []
        self.blocked: list[str] = []

    def open(self, url: str, base: str) -> None:
        from playwright.sync_api import sync_playwright

        from .showit import _may_load

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        ctx = self._browser.new_context(viewport={"width": WIDTH, "height": HEIGHT})
        self.page = ctx.new_page()
        self.page.on("console", lambda m: self._errors.append(m.text) if m.type == "error" else None)
        self.page.on("pageerror", lambda exc: self._errors.append(str(exc)))

        def route(r):
            u = r.request.url
            if _may_load(u, base):
                return r.continue_()
            self.blocked.append(u[:200])
            return r.abort()

        self.page.route("**/*", route)
        try:
            self.page.goto(url, wait_until="load", timeout=20000)
        except Exception as e:  # a slow page is still played
            self._errors.append(f"the page did not finish loading: {str(e)[:200]}")
        self.page.mouse.click(WIDTH // 2, HEIGHT // 2)  # the game gets the keyboard

    def shot(self, path: Path) -> None:
        self.page.screenshot(path=str(path))

    def apply(self, action: dict[str, Any], wait_ms: int) -> None:
        kb, do = self.page.keyboard, action.get("do")
        if do == "tap":
            kb.press(action["key"])
        elif do == "hold":
            kb.down(action["key"])
            self.page.wait_for_timeout(action.get("ms") or 600)
            kb.up(action["key"])
        elif do == "click":
            self.page.mouse.click(action["x"], action["y"])
        self.page.wait_for_timeout(max(0, wait_ms))

    def take_errors(self) -> list[str]:
        got, self._errors = self._errors, []
        # a request the harness stopped (outside the game's address) is listed apart, not as the game's error
        return [e for e in got if not (self.blocked and "net::ERR_FAILED" in e)]

    def close(self) -> None:
        for thing, how in ((self._browser, "close"), (self._pw, "stop")):
            try:
                if thing is not None:
                    getattr(thing, how)()
            except Exception:  # noqa: BLE001
                pass


def play_browser(url: str, base: str, seconds: int, turns: int, chooser: Callable[[dict], dict], out_dir: Path,
                 driver: Any = None) -> dict[str, Any]:
    """Play a browser game for about ``seconds`` in ``turns`` turns. Never raises.

    ``driver`` has open(url, base), shot(path), apply(action, wait_ms), take_errors(), close() and
    ``blocked`` (addresses stopped); by default Playwright. ``chooser(state)`` answers {"do": {...}},
    {"report": {...}} or {"stop": reason}; on the last turn it must report."""
    out_dir = Path(out_dir)
    turns = max(1, min(MAX_TURNS, int(turns)))
    if driver is None:
        try:
            driver = PlaywrightDriver()
        except NoDriver:
            return _unchecked("no_playwright", "Playwright for Python isn't installed on this computer",
                              seconds=seconds)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("turn-*.png"):
        old.unlink()
    step_ms = int(seconds * 1000 / turns)
    pictures: list[str] = []
    changes: list[float | None] = []
    acted: list[bool] = [False]
    errors: list[str] = []
    history: list[str] = []
    report: dict[str, Any] | None = None
    stop = ""
    result: dict[str, Any] = {"kind": "browser", "seconds": seconds, "url": url}
    try:
        driver.open(url, base)
        for turn in range(1, turns + 1):
            pic = out_dir / f"turn-{turn:02d}.png"
            driver.shot(pic)
            pictures.append(pic.name)
            changes.append(prooflib.difference(out_dir / pictures[-2], pic)[0] if len(pictures) > 1 else None)
            new = [e[:300] for e in driver.take_errors()]
            errors += [e for e in new if e not in errors]
            final = turn == turns
            got = chooser({"turn": turn, "turns": turns, "final": final, "picture": pic, "errors": new,
                           "history": list(history), "seconds_in": round((turn - 1) * step_ms / 1000, 1)}) or {}
            if got.get("stop"):
                stop = str(got["stop"])
                break
            if got.get("report") is not None:
                report = clean_report(got["report"])
                break
            if final:
                stop = "no_report"
                break
            action = clean_action(got.get("do"))
            driver.apply(action, step_ms)
            acted.append(action["do"] != "wait")
            history.append(f"turn {turn}: {action_words(action)}")
        errors += [e[:300] for e in driver.take_errors() if e[:300] not in errors]
    except Exception as e:  # the browser itself failed: written down, never raised
        result["failed"] = f"the game couldn't be played: {str(e)[:300]}"
    finally:
        try:
            driver.close()
        except Exception:  # noqa: BLE001
            pass
    own: list[dict[str, Any]] = []
    at = frozen_at(changes, acted)
    if at is not None:
        own.append({"what": f"The screen stopped changing at turn {at} while it was being played",
                    "severity": "broken", "when": f"turn {at}", "by": NAME})
    for e in errors[:MAX_ERRORS]:
        own.append({"what": f"The console showed an error: {e[:200]}", "severity": "broken", "when": "", "by": NAME})
    blocked = list(getattr(driver, "blocked", None) or [])
    if blocked:
        own.append({"what": f"It tried to load something from outside the game ({blocked[0][:80]}); that was stopped",
                    "severity": "rough", "when": "", "by": NAME})
    result.update(pictures=pictures, errors=errors[:MAX_ERRORS], frozen=at, turns=len(history) + (1 if pictures else 0),
                  history=history, blocked=blocked[:10], stop=stop)
    _finish(result, report, own)
    if result["passed"] is None:
        result["why"] = stop or ("failed" if result.get("failed") else "no_report")
        result["why_words"] = STOP_WORDS.get(result["why"], result.get("failed") or "it couldn't be played here")
        result["words"] = words_for(result)
    return result


STOP_WORDS = {
    "money": "playing it more would cost more than allowed for one play",
    "budget": "the run's money limit is reached",
    "no_report": "the model that played it gave no report",
    "error": "the model that can see didn't answer",
    "no_model": "none of the models can see",
}


# -- Godot ---------------------------------------------------------------------------------------------------------
def play_godot(project: Path, godot: str, seconds: int, chooser: Callable[[dict], dict], out_dir: Path,
               turns: int = 12, runner: Any = None, fps: int = godotlib.PLAY_FPS,
               timeout: int | None = None) -> dict[str, Any]:
    """Play a Godot game with planned inputs, record it, and let the model watch the frames. Never raises."""
    out_dir = Path(out_dir)
    actions = godotlib.input_actions(project)
    schedule = godotlib.play_schedule(actions, seconds, fps)
    result: dict[str, Any] = {"kind": "godot", "seconds": seconds, "actions": actions}
    try:
        got = godotlib.record_play(project, godot, seconds, out_dir, schedule, keep=turns, runner=runner, fps=fps,
                                   timeout=timeout)
    except godotlib.NoDisplay:
        return _unchecked("no_display", "this computer has no screen to draw the game on", seconds=seconds,
                          kind="godot")
    except Exception as e:  # Godot couldn't be run: written down, never raised
        return _unchecked("failed", f"Godot couldn't play it ({str(e)[:200]})", seconds=seconds, kind="godot")
    frames: list[Path] = got["frames"]
    changes = [None] + [prooflib.difference(a, b)[0] for a, b in zip(frames, frames[1:])]
    own: list[dict[str, Any]] = []
    at = frozen_at(changes, [True] * len(changes)) if len(frames) > FROZEN_TURNS else None
    if at is not None:
        own.append({"what": f"The picture stopped changing at frame {at} of {len(frames)} while it was being played",
                    "severity": "broken", "when": f"about {round(seconds * (at - 1) / max(1, len(frames) - 1))} s",
                    "by": NAME})
    for e in got["errors"][:MAX_ERRORS]:
        own.append({"what": f"Godot showed an error: {e[:200]}", "severity": "broken", "when": "", "by": NAME})
    if got["timed_out"] and not frames:
        own.append({"what": "The game stopped answering, so it was stopped", "severity": "broken", "when": "",
                    "by": NAME})
    result.update(pictures=[p.name for p in frames], errors=got["errors"][:MAX_ERRORS], frozen=at,
                  turns=len(frames), output_tail=got["output_tail"][-1500:], schedule=schedule[:200])
    report = None
    stop = ""
    if frames:
        pick = sorted({round(i * (len(frames) - 1) / max(1, REPORT_PICTURES - 1)) for i in range(REPORT_PICTURES)})
        answer = chooser({"turn": 1, "turns": 1, "final": True, "pictures": [frames[i] for i in pick],
                          "errors": got["errors"], "history": godotlib.schedule_text(schedule, fps).splitlines(),
                          "seconds_in": seconds}) or {}
        if answer.get("report") is not None:
            report = clean_report(answer["report"])
        else:
            stop = str(answer.get("stop") or "no_report")
    else:
        stop = "no_frames"
    _finish(result, report, own)
    if result["passed"] is None:
        result["why"] = stop
        result["why_words"] = ("Godot recorded no pictures of the game" if stop == "no_frames"
                               else STOP_WORDS.get(stop, "it couldn't be played here"))
        result["words"] = words_for(result)
    return result


# -- the chooser: a model that can see -----------------------------------------------------------------------------
def _input_spec():
    from ..providers.base import ToolSpec

    return ToolSpec("play_input", "Do one thing in the game: tap or hold a key, click at a point, or wait.", {
        "type": "object",
        "properties": {
            "do": {"type": "string", "enum": list(DOS)},
            "key": {"type": "string", "enum": list(KEYS), "description": "for tap and hold"},
            "ms": {"type": "integer", "description": f"how long to hold the key, at most {MAX_HOLD_MS}"},
            "x": {"type": "integer", "description": f"for click: 0 to {WIDTH - 1}"},
            "y": {"type": "integer", "description": f"for click: 0 to {HEIGHT - 1}"},
        },
        "required": ["do"],
    })


def _report_spec():
    from ..providers.base import ToolSpec

    return ToolSpec("report_play", "Say how the play went. Call it once, at the end.", {
        "type": "object",
        "properties": {
            "worked": {"type": "boolean"},
            "summary": {"type": "string", "description": "one short plain sentence"},
            "findings": {"type": "array", "items": {"type": "object", "properties": {
                "what": {"type": "string"}, "severity": {"type": "string", "enum": list(SEVERITIES)},
                "when": {"type": "string", "description": "the turn or the moment"}},
                "required": ["what", "severity"]}},
        },
        "required": ["worked", "summary", "findings"],
    })


class ModelChooser:
    """The seeing model, one call a turn, inside ``max_usd`` for the play and the run's budget.

    Money is kept back for the report: when the next turn and the report together would pass the cap, the
    model is asked for its report now."""

    def __init__(self, cfg: Any, ref: Any, budget: Any, max_usd: float, goal: str = "", how_to_play: str = ""):
        self.cfg, self.ref, self.budget, self.max_usd = cfg, ref, budget, float(max_usd)
        self.goal, self.how_to_play = str(goal or "")[:1500], str(how_to_play or "")[:1500]
        self.spent = 0.0
        self.calls = 0

    def _est(self, pictures: int, text: str, out_tokens: int) -> float:
        from ..providers.base import Usage

        got = self.cfg.cost(self.ref, Usage(input_tokens=prooflib.PICTURE_TOKENS * pictures + len(text) // 3 + 400,
                                            output_tokens=out_tokens))
        return float(got or 0.0)

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        from .. import attachments

        pics = [Path(p) for p in (state.get("pictures") or ([state["picture"]] if state.get("picture") else []))]
        watching = bool(state.get("pictures"))
        head = (f"# The game\n{self.goal or '(no description)'}\n\n"
                + (f"# How it is played\n{self.how_to_play}\n\n" if self.how_to_play else ""))
        hist = "\n".join(state.get("history") or []) or "(nothing yet)"
        errs = "\n".join(f"- {e}" for e in state.get("errors") or [])
        if watching:
            text = (head + f"# The inputs the harness pressed\n{hist}\n\n"
                    + (f"# Errors while it ran\n{errs}\n\n" if errs else "")
                    + f"The pictures were taken through a {state.get('seconds_in', 0)} second play. Call report_play.")
        else:
            text = (head + f"# So far\n{hist}\n\n" + (f"# New errors in the console\n{errs}\n\n" if errs else "")
                    + f"Turn {state['turn']} of {state['turns']}, about {state.get('seconds_in', 0)} s in. The screen "
                      "is below.")
        report_cost = self._est(len(pics), text, REPORT_MAX_TOKENS)
        final = bool(state.get("final"))
        if not final and self.spent + self._est(len(pics), text, CHOOSE_MAX_TOKENS) + report_cost > self.max_usd:
            final = True  # what's left is kept for the report
        if self.spent + report_cost > self.max_usd:
            return {"stop": "money"}
        try:
            self.budget.check()
        except Exception:  # the run's own money limit is reached
            return {"stop": "budget"}
        if final and not watching:
            text += "\n\nThis is the last turn: call report_play now."
        ptype = attachments.provider_type(self.cfg, str(self.ref))
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        for p in pics:
            try:
                content.append(attachments.picture_block(ptype, "image/png", p.read_bytes(), p.name))
            except OSError:
                continue
        tools = [_report_spec()] if final else [_input_spec(), _report_spec()]
        try:
            resp = self.cfg.provider(self.ref.provider).chat(
                self.ref.model, WATCH_SYSTEM if watching else SYSTEM, [{"role": "user", "content": content}],
                tools=tools, max_tokens=REPORT_MAX_TOKENS if final else CHOOSE_MAX_TOKENS, options={})
        except Exception:  # the model is away or refused
            return {"stop": "error"}
        self.calls += 1
        cost = float(self.cfg.cost(self.ref, resp.usage) or 0.0)
        self.spent += cost
        try:
            self.budget.charge(cost, ref=self.ref, usage=resp.usage, role="playtest")
        except Exception:  # noqa: BLE001 - charging is bookkeeping; the next turn's check stops it
            pass
        for call in resp.tool_calls or []:
            if call.name == "report_play":
                return {"report": call.arguments or {}}
            if call.name == "play_input" and not final:
                return {"do": call.arguments or {}}
        return {"stop": "no_report"} if final else {"do": {"do": "wait"}}


# -- the Orchestrator's side -----------------------------------------------------------------------------------------
def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", str(name or "play")).strip("-")[:40] or "play"


def play_dir(project_root: Path, goal_index: int, item_id: str) -> Path:
    return Path(project_root) / ".harness" / PLAY_DIR / f"goal-{int(goal_index) + 1}" / _safe(item_id)


def read_record(project_root: Path, goal_index: int, item_id: str) -> dict[str, Any] | None:
    try:
        return json.loads((play_dir(project_root, goal_index, item_id) / RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class PlayStage:
    """A mixin for the Orchestrator. ``play_driver`` (a fake browser) and ``play_runner`` (a fake command
    runner for Godot) may be set by tests, as ``shot_renderer`` is. ``_product_url``, when the finish step
    has started the product with its own command, is played instead of the static page."""

    def _play_settings(self) -> Settings:
        return Settings.from_config(self.cfg)

    def _play_items(self) -> list[dict[str, Any]]:
        try:
            items = self._kind_proof() if callable(getattr(self, "_kind_proof", None)) else []
        except Exception:  # noqa: BLE001
            items = []
        return [i for i in items or [] if i.get("how") == "play" and i.get("status", "trial") != "not_yet"]

    def _play_goal(self) -> tuple[int, str]:
        meta = self.project.meta()
        goals = meta.get("goals") or [""]
        doc = self.project.plan_doc() or {}
        gi = int(doc.get("goal_index", len(goals) - 1))
        return gi, str(goals[gi] if 0 <= gi < len(goals) else goals[-1])

    def _play_runner(self):
        """Godot's play command through the workspace's own path (the gate, a clean environment, live output)."""
        fake = getattr(self, "play_runner", None)
        if fake is not None:
            return fake

        def runner(cmd: list[str], timeout: int, cwd: Path) -> tuple[int | None, str]:
            from .tools import ToolError

            line = subprocess.list2cmdline(cmd) if os.name == "nt" else shlex.join(cmd)
            try:
                out = self.ws.run_command({"command": line, "timeout": timeout})
            except ToolError as e:
                if "timed out" in str(e):
                    return None, ""
                raise godotlib.GodotError(str(e)[:300]) from e
            m = re.match(r"exit code: (-?\d+)", out)
            return (int(m.group(1)) if m else 1), out

        return runner

    def _play_check(self, item: dict[str, Any]) -> dict[str, Any]:
        """Play the game for a done-list item with ``how: play``: {passed, words, evidence}. Never raises."""
        item_id = str(item.get("id") or "play")
        s = self._play_settings()
        secs, turns, cap = s.for_seconds(item.get("seconds"))
        gi, goal = self._play_goal()
        out_dir = play_dir(self.project.root, gi, item_id)
        result = self._play_run(s, secs, turns, cap, goal, out_dir)
        rel = out_dir.relative_to(self.project.root).as_posix()
        ideas = [f for f in result.get("findings") or [] if f["severity"] in ("rough", "idea")]
        record = {"at": utcnow(), "item": item_id, "goal_index": gi, "dir": rel, **{k: v for k, v in result.items()
                                                                                  if k != "schedule"}}
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / RECORD).write_text(json.dumps(record, indent=1, ensure_ascii=False, default=str) + "\n",
                                          encoding="utf-8")
        except OSError:
            pass
        self.emit("play", {"item": item_id, "passed": result.get("passed"), "words": result["words"],
                           "cost_usd": result.get("cost_usd", 0.0), "dir": rel})
        if ideas:  # for the owner to choose from; never built by themselves
            self._journal("note", f"Ideas from playing it ({len(ideas)})",
                          details="\n".join(f"- ({f['severity']}) {f['what']}" for f in ideas))
        evidence = {"kind": result.get("kind", ""), "dir": rel,
                    "pictures": [f"{rel}/{p}" for p in result.get("pictures") or []],
                    "findings": result.get("findings") or [], "errors": result.get("errors") or [],
                    "broken": [f["what"] for f in result.get("findings") or [] if f["severity"] == "broken"],
                    "ideas": ideas, "summary": result.get("summary", ""), "frozen": result.get("frozen"),
                    "cost_usd": result.get("cost_usd", 0.0), "why": result.get("why", "")}
        return {"passed": result.get("passed"), "words": result["words"], "evidence": evidence}

    def _play_run(self, s: Settings, secs: int, turns: int, cap: float, goal: str, out_dir: Path) -> dict[str, Any]:
        if not s.on:
            return _unchecked("off", "playing is off in harness.yaml (playtest: enabled)", seconds=secs)
        ref = prooflib._seeing_ref(self.cfg, prooflib.Settings(role=s.role))
        if ref is None:
            return _unchecked("no_model", "none of the models can see, so nobody could play it", seconds=secs)
        chooser = ModelChooser(self.cfg, ref, self.budget, cap, goal)
        root = self.project.root
        gs = getattr(self.cfg, "godot", None)
        game = godotlib.project_dir(root) if getattr(gs, "enabled", True) else None
        try:
            if game is not None:
                godot = godotlib.find_godot(getattr(gs, "path", None))
                if not godot:
                    return _unchecked("no_godot", godotlib.NOT_INSTALLED, seconds=secs, kind="godot")
                result = play_godot(game, godot, secs, chooser, out_dir, turns=turns, runner=self._play_runner(),
                                    timeout=int(getattr(gs, "timeout", 120) or 120) + secs * 3)
            else:
                result = self._play_page(secs, turns, chooser, out_dir)
        except Exception as e:  # noqa: BLE001 - playing is a help
            result = _unchecked("failed", f"it couldn't be played ({str(e)[:200]})", seconds=secs)
        result["cost_usd"] = round(chooser.spent, 6)
        result["model"] = str(ref)
        result["calls"] = chooser.calls
        return result

    def _play_page(self, secs: int, turns: int, chooser: ModelChooser, out_dir: Path) -> dict[str, Any]:
        from . import showit

        driver = getattr(self, "play_driver", None)
        url = getattr(self, "_product_url", None)
        if url:
            base = re.match(r"^[a-z]+://[^/]+/", url + ("/" if url.count("/") < 3 else ""))
            return play_browser(url, base.group(0) if base else url, secs, turns, chooser, out_dir, driver=driver)
        entry = showit.entry_page(self.project.root)
        if not entry:
            return _unchecked("nothing", "there's no page to open yet (no index.html)", seconds=secs)
        with showit.StaticServer(self.project.root) as srv:
            return play_browser(srv.url + quote(entry), srv.url, secs, turns, chooser, out_dir, driver=driver)

    def _play_estimate(self, tasks: list) -> dict[str, Any] | None:
        """The estimate's line for playing it, only when the kind has a play check."""
        items = self._play_items()
        s = self._play_settings()
        if not items or not s.on:
            return None
        if prooflib._seeing_ref(self.cfg, prooflib.Settings(role=s.role)) is None:
            return {"id": "play", "usd": 0.0, "minutes": 0.0,
                    "words": "playing it: not possible here, none of the models can see"}
        usd = minutes = 0.0
        for it in items:
            secs, turns, cap = s.for_seconds(it.get("seconds"))
            usd += cap
            minutes += secs / 60 + turns * 0.1
        return {"id": "play", "usd": round(usd, 4), "minutes": round(minutes, 1),
                "words": f"playing it to see what breaks: up to ${usd:.2f} ({len(items)} "
                         f"play{'s' * (len(items) != 1)}, more if a fix needs another play)"}
