"""The sound job (wave 9): a made-up game plans, prices and buys its sounds, stops at the cap and makes the rest
in code. Scripted providers only: no network, no keys, no money."""

import json

from roundtable.harness import plandoc, soundprice, soundstage
from roundtable.harness.orchestrator import Task
from roundtable.providers.base import ProviderError
from roundtable.providers.scripted import ScriptedSoundProvider

from .soundfakes import mp3, wav
from .test_harness import RAW, Brain, make

SOUNDS = ["the player lands a jump", "a coin is picked up", "the door opens", "the player is hit",
          "the boss explodes"]


def plan(n=5, **opts):
    tasks = [{"id": "T1", "title": "hello module", "role": "coder", "description": "create hello.py",
              "acceptance": "hello.py prints hi", "depends_on": []}]
    for i, what in enumerate(SOUNDS[:n], 1):
        tasks.append({"id": f"S{i}", "title": what, "role": "sounds", "description": what, "acceptance": "a sound",
                      "depends_on": [], "sound_options": {"kind": "effect", "seconds": 1, **opts}})
    return tasks


def setup(tmp_path, sounds, price=0.45, licence=None, n=5, raw=None, **opts):
    raw = json.loads(json.dumps(raw or RAW))
    raw["providers"]["snd"] = {"type": "scripted"}
    raw["roles"]["sounds"] = {"kind": "sound", "model": "snd/effects", "description": "makes the game's sounds"}
    orch, a, b, img, events = make(tmp_path, raw=raw, brain=Brain(plan=plan(n, **opts)))
    snd = ScriptedSoundProvider(sounds=sounds, price=price, licence=licence)
    orch.cfg.register("snd", snd)
    return orch, snd, events


def test_four_sounds_bought_then_the_fifth_made_in_code_at_the_cap(tmp_path):
    orch, snd, events = setup(tmp_path, [(mp3(1), "mp3", 0.45)] * 5)
    orch.start("a tiny platformer")
    assert orch.run() == "done"
    root = orch.project.root
    assert snd.calls == 4  # the fifth was refused before any call
    assert soundprice.spent(root) == 1.8
    rows = soundstage.read_sounds(root)
    assert [r["made"] for r in rows] == ["bought"] * 4 + ["code"]
    assert "$2.00 for sound is used up" in rows[-1]["why"]
    for r in rows[:4]:
        assert (root / r["file"]).read_bytes()[:3] == b"ID3" and r["file"].startswith("assets/sounds/")
    credits = (root / "assets/sounds/CREDITS.md").read_text()
    assert credits.count("\n- `assets/sounds/") == 4 and "Prompt: \"a coin is picked up\"" in credits
    s5 = next(t for t in orch.project.tasks() if t.id == "S5")
    assert s5.status == "done" and s5.role == "coder" and s5.description.startswith("Make this sound in code")
    assert s5.summary.startswith("made in code (the project's $2.00 for sound is used up)")
    lines = soundstage.report_lines(root)
    assert lines[0].startswith("Sounds bought: 4 for $1.80") and lines[1].startswith("Sounds made in code: 1")
    metrics = [json.loads(x) for x in (root / ".harness/metrics.jsonl").read_text().splitlines()]
    sound_rows = [m for m in metrics if m.get("sound_kind")]
    assert len(sound_rows) == 4 and all(m["cost_usd"] == 0.45 and m["sound_seconds"] == 1.0 for m in sound_rows)
    assert ("sound_cap" in {k for k, _ in events}) and ("sound_in_code" in {k for k, _ in events})


def test_no_service_means_made_in_code_and_the_build_still_finishes(tmp_path):
    raw = json.loads(json.dumps(RAW))
    raw["providers"]["snd"] = {"type": "scripted"}
    raw["roles"]["sounds"] = {"kind": "sound", "model": "snd/effects"}
    orch, a, b, img, _ = make(tmp_path, raw=raw, brain=Brain(plan=plan(1)))
    orch.cfg.register("snd", img)  # a picture service, not a sound service
    orch.start("a tiny platformer")
    assert orch.run() == "done"
    rows = soundstage.read_sounds(orch.project.root)
    assert rows[0]["made"] == "code" and "isn't a sound service" in rows[0]["why"]


def test_a_free_plan_is_skipped_unless_the_project_is_just_for_me(tmp_path):
    orch, snd, _ = setup(tmp_path / "a", [(mp3(1), "mp3", 0.01)], licence={"commercial": False}, n=1)
    orch.start("a game")
    assert orch.run() == "done" and snd.calls == 0
    assert "doesn't allow selling" in soundstage.read_sounds(orch.project.root)[0]["why"]

    orch, snd, _ = setup(tmp_path / "b", [(mp3(1), "mp3", 0.01)], licence={"commercial": False}, n=1)
    orch.start("a game")
    meta = orch.project.meta()
    meta["sound"] = {"just_for_me": True}
    orch.project.save_meta(meta)
    assert orch.run() == "done" and snd.calls == 1
    assert soundstage.read_sounds(orch.project.root)[0]["made"] == "bought"


def test_a_failed_check_is_tried_once_more_inside_the_cap(tmp_path):
    orch, snd, _ = setup(tmp_path, [(wav(1, loud=False), "wav", 0.1), (wav(1), "wav", 0.1)], n=1, price=0.1)
    orch.start("a game")
    assert orch.run() == "done" and snd.calls == 2
    root = orch.project.root
    assert soundprice.spent(root) == 0.2  # the silent one was paid for too
    assert soundstage.read_sounds(root)[0]["file"].endswith(".wav")


def test_a_failed_call_lets_the_money_go(tmp_path):
    orch, snd, _ = setup(tmp_path, [], n=1, price=0.3)
    orch.start("a game")
    assert orch.run() == "done" and snd.calls == 1
    assert soundprice.spent(orch.project.root) == 0.0
    assert soundstage.read_sounds(orch.project.root)[0]["made"] == "code"


def test_out_of_credit_marks_the_service_and_makes_it_in_code(tmp_path):
    orch, snd, _ = setup(tmp_path, [], n=2, price=0.1)

    def broke(model, prompt, options=None):
        snd.calls += 1
        raise ProviderError("no credits", out_of_credit=True)

    snd.generate = broke
    orch.start("a game")
    assert orch.run() == "done" and snd.calls == 1  # the second sound didn't ask the empty account again
    assert [r["made"] for r in soundstage.read_sounds(orch.project.root)] == ["code", "code"]


def test_the_estimate_with_a_known_price_and_unpriced(tmp_path):
    orch, snd, _ = setup(tmp_path, [], n=1, price=0.05)
    tasks = [Task(id="S1", title="jump", role="sounds", description="a jump",
                  sound_options={"kind": "effect", "seconds": 1})]
    est = plandoc.estimate(orch.cfg, tasks)
    assert est["by_role"]["sounds"]["cost_usd"] == 0.05 and est["unpriced"] == []
    assert soundprice.estimate_line(est["by_role"]["sounds"]["cost_usd"], orch.cfg) == "Sound: about $0.05 of your $2"
    snd.price = None
    est = plandoc.estimate(orch.cfg, tasks)
    assert est["unpriced"] == ["snd/effects"]


def test_music_options_reach_the_service(tmp_path):
    orch, snd, _ = setup(tmp_path, [(mp3(20), "mp3", 0.05)], n=1, kind="music", seconds=20, loop=True)
    seen = {}
    orig = snd.generate
    snd.generate = lambda m, p, o=None: (seen.update(o or {}), orig(m, p, o))[1]
    orch.start("a game")
    assert orch.run() == "done"
    assert seen == {"kind": "music", "seconds": 20.0, "loop": True}


# -- the app's API (ui/soundapi.py) ------------------------------------------------------------------------------
def api_app(tmp_path, monkeypatch, orch):
    import yaml

    from roundtable.ui import server
    from roundtable.ui.server import UIApp

    from .test_hub import RAW as HUB_RAW

    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "soundapi"))
    h = json.loads(json.dumps(HUB_RAW))
    h["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
    (tmp_path / "hub.yaml").write_text(yaml.safe_dump(h), encoding="utf-8")
    cfg = orch.cfg
    cfg.lab_dir = tmp_path / "lab"
    orch._register_with_lab()
    app = UIApp(str(tmp_path / "hub.yaml"), "missing.yaml", agent="backend")
    app.cfg = lambda: cfg
    return app


def test_the_api_lists_prices_first_and_makes_a_sound_again_inside_the_cap(tmp_path, monkeypatch):
    import pytest

    from roundtable.ui.server import ApiError

    orch, snd, _ = setup(tmp_path, [(mp3(1), "mp3", 0.45)] * 6)
    orch.start("a tiny platformer")
    assert orch.run() == "done"
    app = api_app(tmp_path, monkeypatch, orch)
    path = str(orch.project.root)
    v = app.dispatch("GET", "/api/sounds", {"path": [path]}, {})
    assert v["words"] == "$1.80 of $2 used. 4 bought, 1 made in code." and v["cap"] == 2.0 and len(v["sounds"]) == 5
    calls = snd.calls
    ask = app.dispatch("POST", "/api/sounds/again", {}, {"path": path, "task": "S2"})
    assert ask["confirm"] and ask["usd"] == 0.45 and "$0.20" in ask["question"] and snd.calls == calls  # nothing spent
    with pytest.raises(ApiError, match="past its"):  # $1.80 + $0.45 would pass $2
        app.dispatch("POST", "/api/sounds/again", {}, {"path": path, "task": "S2", "confirm": True})
    assert snd.calls == calls
    with pytest.raises(ApiError, match="at most \\$2"):
        app.dispatch("POST", "/api/sounds/project", {}, {"path": path, "max_usd": 5})
    v = app.dispatch("POST", "/api/sounds/project", {}, {"path": path, "max_usd": 1.0, "just_for_me": True})
    assert v["cap"] == 1.0 and v["just_for_me"] is True


def test_the_api_makes_a_sound_again_when_there_is_room(tmp_path, monkeypatch):
    orch, snd, _ = setup(tmp_path, [(mp3(1), "mp3", 0.1), (mp3(1), "mp3", 0.12)], n=1, price=0.1)
    orch.start("a game")
    assert orch.run() == "done"
    app = api_app(tmp_path, monkeypatch, orch)
    path = str(orch.project.root)
    v = app.dispatch("POST", "/api/sounds/again", {}, {"path": path, "task": "S1", "confirm": True})
    assert snd.calls == 2 and v["spent"] == 0.22 and v["sounds"][0]["usd"] == 0.12
    credits = (orch.project.root / "assets/sounds/CREDITS.md").read_text()
    assert credits.count("\n- `") == 2


def test_the_api_picks_a_service_into_custom_yaml(tmp_path, monkeypatch):
    import yaml

    orch, *_ = setup(tmp_path, [], n=1)
    app = api_app(tmp_path, monkeypatch, orch)
    harness = tmp_path / "harness.yaml"
    harness.write_text(yaml.safe_dump(RAW), encoding="utf-8")
    orch.cfg.path = harness
    cards = app.dispatch("GET", "/api/sounds/service", {}, {})
    assert [c["id"] for c in cards["cards"]] == ["elevenlabs_sound", "stable_audio"]
    assert all(c["price"] and c["licence"] and c["buys"] for c in cards["cards"])
    ask = app.dispatch("POST", "/api/sounds/service", {}, {"service": "elevenlabs_sound"})
    assert ask["confirm"] and not (tmp_path / "custom.yaml").exists()
    app.dispatch("POST", "/api/sounds/service", {}, {"service": "elevenlabs_sound", "confirm": True})
    custom = yaml.safe_load((tmp_path / "custom.yaml").read_text())
    assert custom["roles"]["sounds"] == {"kind": "sound", "model": "elevenlabs_sound/effects",
                                         "description": "makes the game's sound effects and music"}
    assert custom["providers"]["elevenlabs_sound"]["api_key_env"] == "ELEVENLABS_API_KEY"
    assert "key" not in json.dumps(custom).replace("api_key_env", "")  # never a key, only its name
    from roundtable.harness.config import load_config

    cfg = load_config(str(harness))
    assert cfg.roles["sounds"].kind == "sound" and str(cfg.roles["sounds"].models[0]) == "elevenlabs_sound/effects"
