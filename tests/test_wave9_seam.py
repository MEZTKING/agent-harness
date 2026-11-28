"""Wave 9, step 0: the seams wave 9's seven helpers fill.

With every stub in place and nothing using them, the harness behaves exactly as before: a bare scripted
plan-and-run sends byte for byte the same requests as the golden recorded before the seams (the golden of
test_sweep_seam.py, unchanged), a project with no sound role is planned as before, the words stay British English
and an estimate never invents a price for a sound.
"""

import gzip
import inspect
import json
import re
from pathlib import Path

import pytest

from roundtable import localcounts, office, officeart, otel, phone, proofrun, todoactions, translate, words
from roundtable.harness import config as hconfig
from roundtable.harness import plandoc, soundprice
from roundtable.harness.config import parse_config
from roundtable.harness.orchestrator import Orchestrator, Task
from roundtable.harness.soundstage import SoundStage
from roundtable.improve import charter
from roundtable.providers import base
from roundtable.providers.catalog import PRESETS, preset_block
from roundtable.providers.elevenlabs_sound import ElevenLabsSoundProvider
from roundtable.providers.scripted import ScriptedSoundProvider
from roundtable.providers.stable_audio import StableAudioProvider

from .test_harness import RAW, make
from .test_sweep_seam import GOLDEN, requests_of

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/roundtable/ui/static"
KT = ROOT / "mobile/app/src/main/java/com/meztking/roundtable"


def _sig(fn):
    return re.sub(r"pathlib(\._local)?\.Path", "Path", str(inspect.signature(fn))).replace("'", "")


def with_sound(raw=RAW):
    raw = json.loads(json.dumps(raw))
    raw["providers"]["snd"] = {"type": "scripted"}
    raw["roles"]["sounds"] = {"kind": "sound", "model": "snd/effects", "description": "makes the game's sounds"}
    return raw


# -- byte for byte as before ----------------------------------------------------------------------------------
def test_a_bare_plan_and_run_still_sends_the_golden_requests(tmp_path, monkeypatch):
    assert requests_of(tmp_path, monkeypatch) == gzip.decompress(GOLDEN.read_bytes()).decode("utf-8")


def test_a_project_with_no_sound_role_is_planned_as_before(tmp_path):
    orch, *_ = make(tmp_path)
    assert "sound_options" not in orch._task_schema()["properties"]
    assert "sound generation" not in orch._roles_text()
    assert Task(id="T1", title="t", role="coder", description="d").sound_options == {}


def test_a_sound_role_is_offered_to_the_planner_with_its_options(tmp_path):
    cfg = parse_config(with_sound())
    orch = Orchestrator(cfg, tmp_path / "proj")
    props = orch._task_schema()["properties"]
    assert props["sound_options"]["properties"]["kind"]["enum"] == ["effect", "music"]
    assert "- sounds (sound generation:" in orch._roles_text()
    assert cfg.roles["sounds"].kind == "sound" and cfg.roles["sounds"].review is False


def test_a_sound_task_goes_to_the_sound_stage_which_makes_it_in_code_without_a_service(tmp_path):
    cfg = parse_config(with_sound())
    orch = Orchestrator(cfg, tmp_path / "proj")
    assert isinstance(orch, SoundStage)
    t = Task(id="S1", title="jump", role="sounds", description="the player lands a jump",
             sound_options={"kind": "effect", "seconds": 1})
    orch._run_task(t, [t])  # no sound service here: w9-sound's fallback turns it into a builder task
    assert t.summary.startswith("made in code (") and t.role == "coder"


def test_a_bad_role_kind_is_refused_in_plain_words():
    raw = json.loads(json.dumps(RAW))
    raw["roles"]["x"] = {"kind": "video", "model": "a/x"}
    with pytest.raises(ValueError, match="'chat', 'image' or 'sound'"):
        parse_config(raw)


def test_the_planners_sound_options_are_kept_on_the_task():
    from roundtable.harness.orchestrator import _validate_plan

    cfg = parse_config(with_sound())
    got = _validate_plan([{"id": "S1", "title": "jump", "role": "sounds", "description": "a jump",
                           "sound_options": {"kind": "effect", "seconds": 1.5}},
                          {"id": "S2", "title": "bad", "role": "sounds", "description": "x", "sound_options": "loud"}],
                         cfg.roles, [])
    assert got[0].sound_options == {"kind": "effect", "seconds": 1.5} and got[1].sound_options == {}


# -- the estimate never invents a price ---------------------------------------------------------------------------
def test_an_estimate_with_an_unpriced_sound_says_unpriced():
    cfg = parse_config(with_sound())
    tasks = [Task(id="S1", title="jump", role="sounds", description="a jump", sound_options={"kind": "effect",
                                                                                              "seconds": 1})]
    est = plandoc.estimate(cfg, tasks)
    assert est["unpriced"] == ["snd/effects"] and est["by_role"]["sounds"]["cost_usd"] is None
    assert "(some models have no price yet)" in plandoc.estimate_line(est)


def test_an_estimate_with_a_priced_sound_uses_soundprice(monkeypatch):
    seen = []
    monkeypatch.setattr(soundprice, "per_sound", lambda cfg, model, kind, seconds, charges=None:
                        seen.append((str(model), kind, seconds)) or 0.05)
    cfg = parse_config(with_sound())
    tasks = [Task(id="S1", title="jump", role="sounds", description="a jump",
                  sound_options={"kind": "music", "seconds": 20})]
    est = plandoc.estimate(cfg, tasks)
    assert est["unpriced"] == [] and est["by_role"]["sounds"]["cost_usd"] == 0.05
    assert seen == [("snd/effects", "music", 20.0)]


# -- the stubs, with their frozen signatures ------------------------------------------------------------------
def test_the_sound_provider_interface():
    for name in ("quote", "generate", "licence", "balance"):
        assert callable(getattr(base.SoundProvider, name))
    assert base.SoundProvider.kinds == ("effect", "music") and base.SoundProvider.name == "sounds"
    assert _sig(base.SoundProvider.quote) == "(self, model: str, prompt: str, options: dict[str, Any] | None = None) -> float | None"
    assert _sig(base.SoundProvider.generate) == ("(self, model: str, prompt: str, options: dict[str, Any] | None = None)"
                                                 " -> tuple[bytes, str, Usage]")
    for cls in (ElevenLabsSoundProvider, StableAudioProvider):
        p = cls()
        assert isinstance(p, base.SoundProvider)  # filled by w9-sound: tests/test_sound_providers.py


def test_the_scripted_sound_provider_plays_back_and_counts():
    s = ScriptedSoundProvider(sounds=[(b"ID3", "mp3", 0.02)], price=0.03, licence={"commercial": False})
    assert s.quote("m", "a jump") == 0.03 and s.calls == 0
    data, ext, usage = s.generate("m", "a jump")
    assert (data, ext, usage.cost_usd, s.calls) == (b"ID3", "mp3", 0.02, 1) and s.licence() == {"commercial": False}
    with pytest.raises(base.ProviderError):
        s.generate("m", "another")


def test_the_sound_services_are_known_to_config_and_the_catalog():
    assert {"elevenlabs_sound", "stable_audio"} <= set(hconfig.PROVIDER_TYPES) and hconfig.ROLE_KINDS[-1] == "sound"
    cfg = parse_config({**with_sound(), "providers": {**with_sound()["providers"],
                                                       "el": {"type": "elevenlabs_sound"}, "sa": {"type": "stable_audio"}}})
    assert isinstance(cfg.provider("el"), ElevenLabsSoundProvider) and isinstance(cfg.provider("sa"), StableAudioProvider)
    assert PRESETS["elevenlabs_sound"]["api_key_env"] == "ELEVENLABS_API_KEY"
    assert PRESETS["stable_audio"]["api_key_env"] == "STABILITY_API_KEY"
    assert {PRESETS[k]["category"] for k in ("elevenlabs_sound", "stable_audio")} == {"sound"}
    assert preset_block("stable_audio") == {"type": "stable_audio", "api_key_env": "STABILITY_API_KEY",
                                             "preset": "stable_audio"}


def test_soundprice_and_soundstage_have_their_frozen_signatures(tmp_path):
    assert soundprice.CAP_DEFAULT == 2.0 and issubclass(soundprice.SoundCapReached, Exception)
    assert _sig(soundprice.cap) == "(cfg, root) -> float"
    assert _sig(soundprice.spent) == "(root) -> float"
    assert _sig(soundprice.reserve) == "(root, cfg, usd: float) -> str"
    assert _sig(soundprice.settle) == "(root, token: str, real_usd: float, row: dict) -> None"
    assert _sig(soundprice.release) == "(root, token: str) -> None"
    assert _sig(soundprice.per_sound) == ("(cfg, model, kind: str, seconds: float, charges: dict[str, Any] | None = None)"
                                          " -> float | None")
    assert _sig(SoundStage._run_sound_task) == "(self, task, role) -> bool"
    assert soundprice.per_sound(None, "m", "effect", 1.0) is None and soundprice.spent(tmp_path) == 0.0
    with pytest.raises(soundprice.SoundCapReached):  # filled by w9-sound: never past the cap
        soundprice.reserve(tmp_path, None, 2.01)


def test_the_other_stubs_have_their_frozen_signatures_and_do_nothing(tmp_path):
    assert _sig(office.scene) == "(app) -> dict[str, Any]"
    assert office.scene(None) == {"rooms": [], "actors": [], "art": False}
    assert (officeart.CAP_USD, officeart.SAMPLE_CAP_USD) == (10.0, 1.5)
    assert _sig(officeart.manifest) == "() -> list[dict[str, Any]]"
    assert _sig(officeart.quote) == "(provider) -> dict[str, Any]"
    assert _sig(officeart.make) == "(provider, stage: str, out, spent_file) -> dict[str, Any]"
    assert officeart.manifest() == [] and officeart.quote(None)["cap"] == 10.0
    assert _sig(translate.price) == "(cfg, text: str, lang: str) -> float | None"
    assert _sig(translate.words) == "(cfg, root, text: str, lang: str, why: str) -> dict[str, Any]"
    assert translate.words(None, tmp_path, "Done", "ar", "a card") == {"text": "Done", "cached": False, "usd": 0.0}
    assert _sig(localcounts.count) == "(home, what: str) -> None" and localcounts.count(tmp_path, "hall") is None
    assert list(tmp_path.iterdir()) == []  # nothing counted, nothing written
    with otel.span(tmp_path, "task", id="T1") as s:
        assert s is None
    assert list(tmp_path.iterdir()) == []
    assert _sig(todoactions.action_for) == "(todo: dict[str, Any], app) -> dict[str, Any] | None"
    assert todoactions.action_for({"text": "add a key"}, None) is None
    assert _sig(proofrun.prepare) == "(lab, idea: str, caps: dict[str, Any]) -> dict[str, Any]"
    assert _sig(proofrun.report) == "(lab) -> dict[str, Any]"
    with pytest.raises(NotImplementedError):
        proofrun.prepare(tmp_path, "a made-up game", {})


# -- the words stay British English -----------------------------------------------------------------------------
def test_words_are_english_until_a_table_is_filled():
    assert words.t("x") == "x" and words.t("Approve the plan", "ar") == "Approve the plan"
    assert words.t("{n} for you", n=3) == "3 for you" and words.t("{n} of {total}", n=1) == "1 of {total}"
    assert words.language(None) == "en-GB" and words.catalogue("ar") == {}
    assert words.rtl("ar") and words.rtl("he") and not words.rtl("en-GB") and not words.rtl("ja")
    assert all({"name", "own_name", "rtl"} <= set(v) for v in words.LANGS.values())
    assert _sig(words.t) == "(text: str, lang: str | None = None, **vals) -> str"


def test_the_desktops_words_seam():
    js = (STATIC / "words.js").read_text(encoding="utf-8")
    for name in ("t(text, vals)", "auto(text)", "lang()", "dir()", "locale()", "load()"):
        assert f"export {'async ' if name == 'load()' else ''}function {name}" in js, name
    assert re.search(r"export function auto\(text\) \{ return text; \}", js)  # the stub: identity
    core = (STATIC / "core.js").read_text(encoding="utf-8")
    assert 'import * as words from "./words.js";' in core and "words.auto(" in core
    assert 'WORDY = new Set(["title", "placeholder", "aria-label", "alt"])' in core
    assert "words.locale()" in core and 'toLocaleTimeString("en-GB"' not in core
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "words.load()" in app.split("S.ov = await get")[0]  # before the first draw


def test_the_phones_words_seam():
    w = (KT / "data/Words.kt").read_text(encoding="utf-8")
    assert "object Words" in w and "fun t(english: String, vararg args: Any): String" in w
    assert "val rtl: Boolean" in w and "fun use(lang: String, table: Map<String, String>)" in w
    main = (KT / "MainActivity.kt").read_text(encoding="utf-8")
    assert "LocalLayoutDirection provides if (Words.rtl) LayoutDirection.Rtl else LayoutDirection.Ltr" in main
    manifest = (ROOT / "mobile/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    assert 'android:supportsRtl="true"' in manifest


# -- the phone's new routes and the charter ---------------------------------------------------------------------
def test_the_phone_narrowing_is_in_place():
    assert set(phone.PHONE_NARROW) == {("POST", "/api/asktimer"), ("POST", "/api/board/answer-several"),
                                       ("POST", "/api/agents"), ("POST", "/api/chat/talk")}
    kt = (KT / "net/Api.kt").read_text(encoding="utf-8")
    for p in ("/api/asktimer", "/api/board/answer-several", "/api/plan/looks", "/api/documents", "/api/agents",
              "/api/chat/talk"):
        assert f'"{p}' in kt, p


def test_the_new_settings_sections_and_the_charter():
    for name in ("sound", "office", "language", "translate", "counts", "otel", "webphone", "proofrun", "todo_actions"):
        assert name in hconfig.FEATURE_SECTIONS
    assert {"sound", "office", "language", "webphone", "proofrun"} <= charter.PROTECTED_KEYS
    assert "harness/soundprice.py" in charter.NO_TOUCH_FILES and "wave9" in {r["id"] for r in charter.NEVER}
