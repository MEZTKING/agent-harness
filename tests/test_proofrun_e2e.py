"""The proof run's dress rehearsal (wave 9): the same steps as the real one, with scripted providers registered
under the real set-up's own names (deepseek, retrodiffusion, elevenlabs_sound), a tiny scripted game, a fake
balance that falls by a known amount, a scripted picture and a scripted sound. No network, no keys. It proves
the wiring, the caps, the stop when the estimate is over, and the three-number table."""

from __future__ import annotations

import json

import pytest

from roundtable import proofrun
from roundtable.providers.base import ProviderError
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider, ScriptedSoundProvider, reply

from .soundfakes import mp3

GAME = """<!doctype html><html><head><title>Lantern Run</title></head><body><canvas id="c"></canvas>
<script src="game.js"></script></body></html>
"""

PLAN = [
    {"id": "T1", "title": "the page", "role": "coder", "description": "index.html with a canvas",
     "acceptance": "index.html opens", "depends_on": []},
    {"id": "T2", "title": "the moth", "role": "artist", "description": "a small moth sprite",
     "acceptance": "the png exists", "depends_on": [], "output_path": "assets/moth.png"},
    {"id": "T3", "title": "the lantern sound", "role": "sound", "description": "a soft chime when a lantern lights",
     "acceptance": "the sound exists", "depends_on": [], "output_path": "assets/sounds/chime.mp3",
     "sound_options": {"kind": "effect", "seconds": 1}},
    {"id": "T4", "title": "the game", "role": "coder", "description": "game.js: hold to rise, lanterns, score",
     "acceptance": "game.js draws the moth", "depends_on": ["T1"]},
]


class GameBrain:
    """The planner plans the tiny game; builders write it; every check passes; anything else just answers."""

    def __init__(self, plan=None, stuck: str = ""):
        self.plan = plan or PLAN
        self.stuck = stuck  # a task id whose builder never finishes
        self.calls = 0
        self.builder_calls = 0

    def __call__(self, model, system, messages, tools):
        self.calls += 1
        names = {t.name for t in tools}
        last = messages[-1]
        if "submit_plan" in names:
            if last["role"] == "tool":
                return reply("planned")
            return reply(calls=[("submit_plan", {"summary": "A small moth game in the browser.", "has_ui": True,
                                                 "tasks": self.plan})])
        if "submit_review" in names:
            if last["role"] == "tool":
                return reply("ok")
            return reply(calls=[("submit_review", {"approved": True, "feedback": "looks right"})])
        if "finish_task" in names:
            self.builder_calls += 1
            tid = messages[0]["content"].split("# Your task [", 1)[1].split("]", 1)[0]
            if tid == self.stuck:
                raise ProviderError("deepseek: the model stopped answering")
            if last["role"] == "user":
                name, text = ("index.html", GAME) if tid == "T1" else (f"{tid.lower()}.js", "// the moth rises\n")
                if tid == "T4":
                    name = "game.js"
                return reply(calls=[("write_file", {"path": name, "content": text})])
            return reply(calls=[("finish_task", {"summary": f"{tid} done"})])
        terminal = [t for t in tools if t.name.startswith("submit_")]
        if terminal and last["role"] != "tool":
            return reply(calls=[(terminal[0].name, {})])
        return reply("Final report: Lantern Run is built.")


class PricedImages(ScriptedImages):
    """Retro Diffusion's stand-in: a free price check, then a picture that costs what it said."""

    def __init__(self, name="retrodiffusion", price=0.02):
        super().__init__(name)
        self.price = price
        self.checked = 0

    def check_cost(self, style, prompt, options=None):
        self.checked += 1
        return self.price

    def generate(self, model, prompt, options=None):
        data, ext, usage = super().generate(model, prompt, options)
        usage.cost_usd = self.price
        return data, ext, usage


class FakeBalance:
    """DeepSeek's balance, falling by a known amount between the first reading and the last."""

    def __init__(self, start=10.0, fall=0.05, readable=True):
        self.amounts = [start, start - fall]
        self.readable = readable
        self.reads = 0

    def __call__(self, cfg):
        self.reads += 1
        if not self.readable:
            return None
        amount = self.amounts[min(self.reads - 1, 1)]
        return {"deepseek": {"amount": amount, "currency": "USD"}}


@pytest.fixture
def quiet(monkeypatch):
    from roundtable.harness.orchestrator import Orchestrator

    monkeypatch.setattr(Orchestrator, "cheap_start_at", lambda self: None)  # half price is tried apart, below
    for k in ("DEEPSEEK_API_KEY", "RETRODIFFUSION_API_KEY", "ELEVENLABS_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ROUNDTABLE_NO_BALANCE", "1")  # the orchestrator's own reading; the proof run's is faked


def lab_with(tmp_path, brain, *, art=True, sound=True, images=None, sounds=None, caps=None):
    lab = tmp_path / "lab"
    proofrun.prepare(lab, proofrun.default_idea(), caps or proofrun.caps_for(art=art, sound=sound))
    cfg = proofrun.load_lab_config(lab)
    cfg.register("deepseek", ScriptedProvider("deepseek", brain))
    images = images or PricedImages()
    sounds = sounds or ScriptedSoundProvider("elevenlabs_sound", sounds=[(mp3(1.0), "mp3", 0.013)] * 4,
                                             price=0.013)
    if art:
        cfg.register("retrodiffusion", images)
    if sound:
        cfg.register("elevenlabs_sound", sounds)
    return lab, cfg, images, sounds


def test_the_dress_rehearsal_builds_the_game_end_to_end(tmp_path, monkeypatch, quiet):
    brain = GameBrain()
    lab, cfg, images, sounds = lab_with(tmp_path, brain)
    bal = FakeBalance(fall=0.05)
    asked = []
    rep = proofrun.run(lab, cfg, yes=lambda words: asked.append(words) or True, balance=bal)

    # priced first, then the estimate was shown before the yes
    assert images.checked == 1 and asked and "It stops at $3.00" in asked[0]
    assert rep["phase"] == "done" and rep["status"] == "done", rep["words"]
    # the game, its picture and its sound are there
    root = lab / proofrun.PROJECT
    assert (root / "index.html").is_file() and (root / "game.js").is_file()
    assert rep["looks"]["pictures"] == ["assets/moth.png"] and rep["sounds"]["files"] == ["assets/sounds/chime.mp3"]
    # the three numbers side by side
    money = rep["money"]
    assert [r["what"] for r in money["table"]] == ["The estimate before building", "The harness's own count",
                                                   "The real fall in the balance"]
    assert money["real_usd"] == pytest.approx(0.05) and money["estimate_usd"] > 0 and money["counted_usd"] > 0
    assert money["gap_pct"] is not None and bal.reads == 2
    # the tasks, and autopilot approved it under its own rules
    assert sorted(rep["tasks"]["first_time"]) == ["T1", "T2", "T3", "T4"] and not rep["tasks"]["failed"]
    assert rep["autopilot"]["chose"] >= 1
    # every chat job ran on DeepSeek V4 Flash (the scripted stand-in carries its name)
    assert {c["model"] for c in cfg.provider("deepseek").calls} == {"deepseek-v4-flash"}
    # an all-DeepSeek build can't see: said, not guessed, and offered as a second pass
    assert not rep["seeing"]["can_see"] and rep["seeing"]["offer"]["usd_max"] == 0.20
    assert any(f["where"] == "playing it" for f in proofrun.findings(rep))
    # the report and the findings are written in the lab
    assert json.loads((lab / proofrun.REPORT_FILE).read_text(encoding="utf-8"))["phase"] == "done"
    md = (lab / proofrun.FINDINGS_FILE).read_text(encoding="utf-8")
    assert "| The real fall in the balance | $0.05 |" in md
    # the project's own limits are the caps
    import yaml

    settings = yaml.safe_load((root / ".harness" / "project.yaml").read_text(encoding="utf-8"))
    assert settings["limits"] == {"max_cost_usd": 3.0, "max_real_usd_per_run": 2.0, "max_image_usd": 0.5}
    assert settings["checking"] == "lean"
    assert settings["providers_allowed"] == ["deepseek", "elevenlabs_sound", "retrodiffusion"]


def test_without_art_and_sound_the_game_is_drawn_and_heard_in_code(tmp_path, quiet):
    plan = [PLAN[0], PLAN[3]]
    lab, cfg, _, _ = lab_with(tmp_path, GameBrain(plan), art=False, sound=False)
    rep = proofrun.run(lab, cfg, yes=lambda w: True, balance=FakeBalance())
    assert rep["status"] == "done" and "artist" not in cfg.roles and "sound" not in cfg.roles
    assert "made in code" in rep["sounds"]["words"] and "(--no-art)" in rep["looks"]["words"]
    # leaving a part out by choice is not a finding
    assert not [f for f in proofrun.findings(rep) if f["where"] in ("pictures", "sound")]


def test_a_sound_service_that_cant_be_priced_is_left_out_and_said(tmp_path, quiet):
    plan = [PLAN[0], PLAN[3]]
    unpriced = ScriptedSoundProvider("elevenlabs_sound", price=None)  # a sound service that gives no price
    lab, cfg, _, _ = lab_with(tmp_path, GameBrain(plan), art=False, sounds=unpriced)
    rep = proofrun.run(lab, cfg, yes=lambda w: True, balance=FakeBalance())
    assert "sound" not in cfg.roles and "couldn't be priced" in rep["sounds"]["words"]
    assert any(f["where"] == "sound" for f in proofrun.findings(rep))
    import yaml

    assert "sound" not in yaml.safe_load((lab / "harness.yaml").read_text(encoding="utf-8"))["roles"]


def test_half_price_soon_is_waited_for_and_far_off_isnt(tmp_path, monkeypatch, quiet):
    from datetime import datetime, timedelta, timezone

    from roundtable.harness.orchestrator import Orchestrator, Project

    plan = [PLAN[0], PLAN[3]]
    soon = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=10)
    monkeypatch.setattr(Orchestrator, "cheap_start_at", lambda self: soon)
    lab, cfg, _, _ = lab_with(tmp_path, GameBrain(plan), art=False, sound=False)
    waited = []

    def sleep(seconds):  # time passes: half price has started
        waited.append(seconds)
        root = lab / proofrun.PROJECT
        meta = Project(root).meta()
        meta["start_after"] = "2000-01-01T00:00:00Z"
        Project(root).save_meta(meta)

    rep = proofrun.run(lab, cfg, yes=lambda w: True, balance=FakeBalance(), sleep=sleep)
    assert waited and 500 < waited[0] < 700 and rep["status"] == "done"
    assert any(s["step"] == "half_price" for s in rep["steps"])

    far = datetime.now(timezone.utc) + timedelta(hours=5)
    monkeypatch.setattr(Orchestrator, "cheap_start_at", lambda self: far)
    lab2 = tmp_path / "two"
    proofrun.prepare(lab2, proofrun.default_idea(), proofrun.caps_for(art=False, sound=False))
    cfg2 = proofrun.load_lab_config(lab2)
    cfg2.register("deepseek", ScriptedProvider("deepseek", GameBrain(plan)))
    rep = proofrun.run(lab2, cfg2, yes=lambda w: True, balance=FakeBalance(), sleep=lambda s: pytest.fail("waited"))
    assert rep["status"] == "done"
