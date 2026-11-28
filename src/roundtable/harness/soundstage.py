"""The sound job: effects and music made by the service the owner picked, priced first (wave 9).

A stage mixin like the picture job (orchestrator ``_run_image_task``). For each of the role's models in order:

1. the licence: a service whose ``licence()`` says it may not be sold is skipped with one plain line, unless the
   project is marked "just for me" (``project.json`` → ``sound.just_for_me``);
2. ``budget.check()``, then the price held against the project's sound cap (``soundprice.reserve``); a price that
   can't be told is never bought;
3. the call, then :mod:`soundcheck` (real audio of about the asked length), then the real charge settled;
4. the file (``assets/sounds/<name>.<ext>``), one metrics row, one line in ``assets/sounds/CREDITS.md`` and the
   same in ``.harness/sounds.json`` for the app.

A failed check is tried once more, inside the cap. No service, no key, the cap reached or a sound that keeps
failing: the task becomes an ordinary builder task, "make this sound in code" (WebAudio in a browser game, a
generated stream in Godot), and ``sounds.json`` and :func:`report_lines` say which sounds were bought and which
were made in code. A build never fails for want of a sound.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from ..providers.base import ProviderError, SoundProvider
from . import soundcheck, soundprice

SOUNDS_FILE = Path(".harness") / "sounds.json"
CREDITS_FILE = Path("assets") / "sounds" / "CREDITS.md"
_LOCK = threading.Lock()

IN_CODE = {
    "godot-game": "Make it in GDScript with an AudioStreamGenerator (a short generated tone, noise or sweep), "
                  "played by an AudioStreamPlayer where it happens.",
    "browser-game": "Make it with the Web Audio API (an OscillatorNode or a noise buffer with a quick envelope), "
                    "started on the player's first click or key so the browser allows sound.",
}
IN_CODE_OTHER = "Make it in code with the platform's own sound tools (a short generated tone, noise or sweep)."


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _today() -> str:
    return time.strftime("%d %B %Y", time.gmtime()).lstrip("0")


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return s[:48].strip("-")


def read_sounds(root) -> list[dict[str, Any]]:
    try:
        got = json.loads((Path(root) / SOUNDS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [x for x in got if isinstance(x, dict)] if isinstance(got, list) else []


def note_sound(root, entry: dict[str, Any]) -> None:
    """Keep one sound's line in ``.harness/sounds.json``, the latest for the same task replacing the last."""
    p = Path(root) / SOUNDS_FILE
    with _LOCK:
        rows = [r for r in read_sounds(root) if r.get("task") != entry.get("task")]
        rows.append(entry)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(".sounds.json.tmp")
        tmp.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(p)


def add_credit(root, entry: dict[str, Any]) -> None:
    """One line in ``assets/sounds/CREDITS.md``: what it is, the service, the licence as read that day, the prompt."""
    p = Path(root) / CREDITS_FILE
    lic = entry.get("licence") or {}
    line = (f"- `{entry.get('file')}`: {entry.get('title') or 'a sound'}. Made by {entry.get('service')} "
            f"({entry.get('model')}) on {entry.get('day')}. Licence as read that day: "
            f"{lic.get('words') or 'not known'}{(' (' + lic['link'] + ')') if lic.get('link') else ''}. "
            f"Prompt: \"{entry.get('prompt')}\"\n")
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        head = "" if p.is_file() else ("# Sounds\n\nWhere each bought sound came from and what may be done with it."
                                       " Sounds not listed were made in code.\n\n")
        with open(p, "a", encoding="utf-8") as f:
            f.write(head + line)


def report_lines(root) -> list[str]:
    """The finish report's plain lines: which sounds were bought (and what they cost) and which made in code."""
    rows = read_sounds(root)
    bought = [r for r in rows if r.get("made") == "bought"]
    code = [r for r in rows if r.get("made") == "code"]
    out = []
    if bought:
        usd = sum(float(r.get("usd") or 0) for r in bought)
        out.append(f"Sounds bought: {len(bought)} for ${usd:.2f} ("
                   + ", ".join(str(r.get("title") or r.get("file")) for r in bought) + ").")
    if code:
        out.append(f"Sounds made in code: {len(code)} (" + ", ".join(
            f"{r.get('title') or r.get('task')}: {r.get('why') or 'no service'}" for r in code) + ").")
    return out


class SoundStage:
    # -- helpers --------------------------------------------------------------------------------------------------
    def _sound_options(self, task, role) -> dict[str, Any]:
        opts = {**(getattr(role, "options", None) or {}), **(task.sound_options or {})}
        kind = str(opts.get("kind") or "effect")
        opts["kind"] = kind if kind in ("effect", "music") else "effect"
        opts["seconds"] = soundprice.seconds_of(opts["kind"], opts.get("seconds"))
        return opts

    def _sound_builder_role(self) -> str:
        own = getattr(self, "_coder_role", None)
        if callable(own):
            return own()
        if "coder" in self.cfg.roles and self.cfg.roles["coder"].kind == "chat":
            return "coder"
        return next((r.name for r in self.cfg.roles.values() if r.kind == "chat"
                     and r.name not in (self.cfg.planner_role, self.cfg.reviewer_role)), self.cfg.planner_role)

    def _sound_rel(self, task, ext: str) -> str:
        rel = task.output_path or f"assets/sounds/{slug(task.title) or task.id.lower()}.{ext}"
        if "." not in Path(rel).name:
            return f"{rel}.{ext}"
        if Path(rel).suffix.lower() in (".mp3", ".wav", ".ogg") and Path(rel).suffix.lower() != f".{ext}":
            return str(Path(rel).with_suffix(f".{ext}"))
        return rel

    # -- the job --------------------------------------------------------------------------------------------------
    def _run_sound_task(self, task, role) -> bool:
        root = self.project.root
        opts = self._sound_options(task, role)
        just_for_me = bool(soundprice.project_sound(root).get("just_for_me"))
        why: list[str] = []
        for ref in role.models:
            if self._blocked(ref):
                why.append(f"{ref.provider} has no credit left this run")
                continue
            try:
                provider = self.cfg.provider(ref.provider)
            except ProviderError:
                why.append(f"{ref.provider} isn't set up on this computer")
                continue
            if not isinstance(provider, SoundProvider):
                why.append(f"{ref} isn't a sound service")
                continue
            try:
                lic = provider.licence() or {}
            except Exception:  # noqa: BLE001 - not known: treated as not known, not as a no
                lic = {"commercial": None}
            if lic.get("commercial") is False and not just_for_me:
                why.append(f"{ref.provider}'s plan doesn't allow selling what it makes (mark the project "
                           "\"just for me\" to use it anyway)")
                self.emit("sound_skipped", {"task": task.id, "model": str(ref), "why": "licence"})
                continue
            for _try in (1, 2):  # a sound that fails the check is tried once more, inside the cap
                price = soundprice.quote(self.cfg, ref, task.description, opts)
                if price is None:
                    why.append(f"{ref}'s price can't be told before, so it isn't bought")
                    break
                self.budget.check()
                try:
                    token = soundprice.reserve(root, self.cfg, price)
                except soundprice.SoundCapReached:
                    limit = soundprice.cap(self.cfg, root)
                    self.emit("sound_cap", {"task": task.id, "model": str(ref), "price": price,
                                            "spent": soundprice.spent(root), "cap": limit})
                    why.append(f"the project's ${limit:.2f} for sound is used up")
                    break
                t0 = time.monotonic()
                try:
                    data, ext, usage = provider.generate(ref.model, task.description, opts)
                except ProviderError as e:
                    soundprice.release(root, token)
                    if getattr(e, "out_of_credit", False):
                        self._broke.add(ref.provider)
                    self.emit("provider_error", {"task": task.id, "model": str(ref), "error": str(e)})
                    self._metric(task, ref, "error", None)
                    why.append(str(e))
                    break
                real = usage.cost_usd if usage.cost_usd is not None else price
                usage.cost_usd = real
                self.budget.charge(real, ref=ref, usage=usage, role=task.role)
                self._save_spend()
                ok, bad = soundcheck.check(data, ext, opts["kind"], opts["seconds"])
                row = {"task": task.id, "title": task.title, "model": str(ref), "kind": opts["kind"],
                       "seconds": opts["seconds"], "quote": price, "ok": ok}
                soundprice.settle(root, token, real, row)
                if not ok:
                    self.emit("sound_check", {"task": task.id, "model": str(ref), "why": bad})
                    self._metric(task, ref, "error", None)
                    why.append(bad)
                    continue
                return self._sound_bought(task, ref, provider, lic, data, ext, real, opts, time.monotonic() - t0)
        return self._sound_in_code(task, "; ".join(why) or "no sound service is set up")

    def _sound_bought(self, task, ref, provider, lic, data, ext, usd, opts, seconds) -> bool:
        root = self.project.root
        rel = self._sound_rel(task, ext)
        path = self.ws.path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        entry = {"task": task.id, "title": task.title, "file": rel, "kind": opts["kind"], "seconds": opts["seconds"],
                 "loop": bool(opts.get("loop")), "made": "bought", "service": getattr(provider, "name", ref.provider),
                 "model": str(ref), "usd": round(float(usd or 0), 6), "prompt": task.description,
                 "licence": {k: lic.get(k) for k in ("commercial", "words", "link", "read_on") if k in lic},
                 "at": _now(), "day": _today()}
        add_credit(root, entry)
        note_sound(root, entry)
        task.summary = f"bought sound {rel} from {ref} for ${float(usd or 0):.2f}"
        self._add_attempt(task, ref, {"model": str(ref), "outcome": "approved", "cost_usd": usd})
        self.project.append("metrics.jsonl", self._parts(self.METRIC_PARTS, task, ref, {
            "at": _now(), "task": task.id, "role": task.role, "model": str(ref), "outcome": "approved",
            "steps": 1, "seconds": round(seconds, 2), "input_tokens": 0, "output_tokens": 0, "cost_usd": usd or 0,
            "sound_kind": opts["kind"], "sound_seconds": opts["seconds"]}))
        return True

    def _sound_in_code(self, task, why: str) -> bool:
        """The fallback, said plainly: the sound task becomes an ordinary builder task, "make this sound in code"."""
        root = self.project.root
        kind_id = ((self.project.meta().get("kind") or {}).get("id") or "")
        how = IN_CODE.get(kind_id, IN_CODE_OTHER)
        opts = task.sound_options or {}
        what = f"{'a music loop' if opts.get('kind') == 'music' else 'a sound effect'}"
        secs = opts.get("seconds")
        note_sound(root, {"task": task.id, "title": task.title, "file": "", "kind": opts.get("kind") or "effect",
                          "seconds": secs, "made": "code", "why": why, "usd": 0.0, "prompt": task.description,
                          "at": _now(), "day": _today()})
        self.emit("sound_in_code", {"task": task.id, "why": why})
        builder = self._sound_builder_role()
        task.role = builder
        task.description = (f"Make this sound in code, not as a bought file: {what}"
                            + (f" of about {float(secs):g} seconds" if secs else "") + f": {task.description}. {how} "
                            "Play it where it happens in the game.")
        if not task.acceptance:
            task.acceptance = "The sound plays in the game where it happens, made in code."
        tasks = [task if t.id == task.id else t for t in self.project.tasks()]
        if not any(t is task for t in tasks):
            tasks.append(task)
        ok = self._attempt_loop(task, tasks, self.cfg.roles[builder].models)
        task.summary = (f"made in code ({why}). " + (task.summary or "")).strip()
        return ok
