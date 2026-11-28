"""The sound cap (wave 9): one place decides sound money, under one lock, never past the cap."""

import json
import threading

import pytest

from roundtable.harness import soundprice
from roundtable.harness.config import ModelRef, parse_config
from roundtable.improve import charter
from roundtable.providers.scripted import ScriptedSoundProvider

from .test_harness import RAW


def cfg_with(sound=None, pricing=None):
    raw = json.loads(json.dumps(RAW))
    raw["providers"]["snd"] = {"type": "scripted"}
    raw["roles"]["sounds"] = {"kind": "sound", "model": "snd/effects"}
    if sound is not None:
        raw["sound"] = sound
    if pricing:
        raw["pricing"].update(pricing)
    return parse_config(raw)


def project(tmp_path, sound=None):
    (tmp_path / ".harness").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".harness" / "project.json").write_text(json.dumps({"sound": sound} if sound else {}))
    return tmp_path


def test_the_cap_is_the_owners_figure_and_a_project_may_only_lower_it(tmp_path):
    cfg = cfg_with()
    assert soundprice.cap(cfg, project(tmp_path)) == 2.0
    assert soundprice.cap(cfg_with({"max_per_project_usd": 1.5}), tmp_path) == 1.5
    assert soundprice.cap(cfg, project(tmp_path, {"max_usd": 0.5})) == 0.5
    assert soundprice.cap(cfg, project(tmp_path, {"max_usd": 9})) == 2.0  # never above the owner's figure
    assert soundprice.cap(cfg, project(tmp_path, {"max_usd": "lots"})) == 2.0


def test_reserve_settle_release(tmp_path):
    cfg = cfg_with()
    t1 = soundprice.reserve(tmp_path, cfg, 0.5)
    assert soundprice.spent(tmp_path) == 0.5  # held money counts as spent
    soundprice.settle(tmp_path, t1, 0.7, {"task": "S1"})  # above its quote: counted whole
    assert soundprice.spent(tmp_path) == 0.7
    t2 = soundprice.reserve(tmp_path, cfg, 1.0)
    soundprice.release(tmp_path, t2)
    assert soundprice.spent(tmp_path) == 0.7
    assert [x["task"] for x in soundprice.lines(tmp_path)] == ["S1"]
    with pytest.raises(soundprice.SoundCapReached, match=r"past its \$2.00"):
        soundprice.reserve(tmp_path, cfg, 1.31)
    soundprice.reserve(tmp_path, cfg, 1.3)  # exactly to the cap is fine
    with pytest.raises(soundprice.SoundCapReached):
        soundprice.reserve(tmp_path, cfg, None)  # an unknown price is never bought


def test_twenty_sounds_from_four_threads_never_pass_the_cap(tmp_path):
    cfg = cfg_with()
    got, refused = [], []

    def worker():
        for _ in range(5):
            try:
                got.append(soundprice.reserve(tmp_path, cfg, 0.15))
            except soundprice.SoundCapReached:
                refused.append(1)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(got) == 13 and len(refused) == 7  # 13 × $0.15 = $1.95; a 14th would pass $2
    assert soundprice.spent(tmp_path) == pytest.approx(1.95)


def test_a_real_charge_above_its_quote_is_seen_by_the_next_reserve(tmp_path):
    cfg = cfg_with()
    soundprice.settle(tmp_path, soundprice.reserve(tmp_path, cfg, 0.1), 1.95, {})
    with pytest.raises(soundprice.SoundCapReached):
        soundprice.reserve(tmp_path, cfg, 0.1)


def test_per_sound_real_charges_then_the_table_then_the_quote_else_unpriced(tmp_path):
    cfg = cfg_with()
    m = ModelRef("snd", "effects")
    assert soundprice.per_sound(cfg, m, "effect", 2) is None  # a chat provider: no quote, so unpriced
    cfg.register("snd", ScriptedSoundProvider(price=0.03))
    assert soundprice.per_sound(cfg, m, "effect", 2) == 0.03
    priced = cfg_with(pricing={"snd/effects": {"per_minute": 0.12, "music_per_minute": 0.15}})
    assert soundprice.per_sound(priced, m, "effect", 30) == 0.06
    assert soundprice.per_sound(priced, m, "music", 60) == 0.15
    assert soundprice.per_sound(cfg, m, "effect", 4, charges={"snd/effects#effect": 0.01}) == 0.04
    assert soundprice.per_sound(cfg, m, "effect", 4, charges={"snd/effects": 0.09}) == 0.09
    assert soundprice.per_sound(None, "m", "effect", 1.0) is None


def test_rates_from_the_metrics_rows(tmp_path):
    f = tmp_path / "metrics.jsonl"
    rows = [{"model": "el/sfx", "outcome": "approved", "cost_usd": 0.02, "sound_kind": "effect", "sound_seconds": 2},
            {"model": "el/sfx", "outcome": "approved", "cost_usd": 0.06, "sound_kind": "effect", "sound_seconds": 4},
            {"model": "el/sfx", "outcome": "error", "cost_usd": 9, "sound_kind": "effect", "sound_seconds": 1},
            {"model": "a/coder", "outcome": "approved", "cost_usd": 0.5}]
    f.write_text("\n".join(json.dumps(r) for r in rows))
    assert soundprice.rates([f]) == {"el/sfx#effect": pytest.approx(0.08 / 6)}


def test_the_estimate_line():
    cfg = cfg_with()
    assert soundprice.estimate_line(0.38, cfg) == "Sound: about $0.38 of your $2"
    assert soundprice.estimate_line(None, cfg) == "Sound: the price isn't known yet (at most $2)"


def test_learning_may_never_change_the_cap():
    assert "sound" in charter.PROTECTED_KEYS and "harness/soundprice.py" in charter.NO_TOUCH_FILES
