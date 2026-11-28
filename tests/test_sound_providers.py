"""The two sound adapters (wave 9) against made-up answers: no network, no keys."""

import io
import json
import urllib.error

import pytest

from roundtable.core import secrets as vault
from roundtable.harness import soundcheck
from roundtable.providers import elevenlabs_sound as el
from roundtable.providers import stable_audio as sa
from roundtable.providers.base import ProviderError

from .soundfakes import mp3, wav

SECRET = "sk-made-up-0123456789"


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code, body):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(json.dumps(body).encode()))


class Fake:
    """Answers requests from a list of (path start, answer): bytes, a dict (JSON) or an exception."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.seen = []

    def __call__(self, req, timeout):
        self.seen.append(req)
        path = req.full_url.split("://", 1)[1].split("/", 1)[1]
        for i, (start, ans) in enumerate(self.answers):
            if ("/" + path).startswith(start):
                self.answers.pop(i)
                if isinstance(ans, Exception):
                    raise ans
                return Resp(ans if isinstance(ans, bytes) else json.dumps(ans).encode())
        raise AssertionError(f"unexpected request {req.full_url}")


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setattr(vault, "get", lambda name, default=None: SECRET)


SUB = {"tier": "starter", "character_count": 1000, "character_limit": 30000}


# -- ElevenLabs ---------------------------------------------------------------------------------------------------
def test_elevenlabs_quote_is_the_documented_sum():
    p = el.ElevenLabsSoundProvider()
    assert p.quote("effects", "a jump", {"kind": "effect", "seconds": 2}) == round(2 / 60 * 0.12, 6)
    assert p.quote("music", "a tune", {"kind": "music", "seconds": 30}) == round(30 / 60 * 0.15, 6)
    assert p.quote("effects", "a jump") == round(2 / 60 * 0.12, 6)  # no length asked: the default, always explicit
    assert p.quote("effects", "x", {"seconds": 99}) == round(30 / 60 * 0.12, 6)  # clamped to what the API allows


def test_elevenlabs_effect_sends_an_explicit_length_and_the_key_in_its_header(monkeypatch):
    fake = Fake([("/v1/user/subscription", SUB), ("/v1/sound-generation", mp3(1)),
                 ("/v1/user/subscription", {**SUB, "character_count": 1300})])
    monkeypatch.setattr(el, "_urlopen", fake)
    p = el.ElevenLabsSoundProvider(usd_per_credit=0.0002)
    data, ext, usage = p.generate("effects", "the player lands a jump", {"kind": "effect", "seconds": 1, "loop": True})
    post = fake.seen[1]
    body = json.loads(post.data)
    assert body == {"text": "the player lands a jump", "duration_seconds": 1.0, "loop": True, "prompt_influence": 0.3}
    assert post.get_header("Xi-api-key") == SECRET and ext == "mp3" and data[:3] == b"ID3"
    assert usage.cost_usd == round(300 * 0.0002, 6)  # the fall in credits, not the quote
    assert soundcheck.check(data, ext, "effect", 1) == (True, "")


def test_elevenlabs_music_and_the_quote_when_credits_cant_be_read(monkeypatch):
    fake = Fake([("/v1/user/subscription", http_error(500, {})), ("/v1/music", mp3(10))])
    monkeypatch.setattr(el, "_urlopen", fake)
    p = el.ElevenLabsSoundProvider(retry_wait=0)
    data, ext, usage = p.generate("music", "a calm loop", {"kind": "music", "seconds": 12})
    assert json.loads(fake.seen[1].data) == {"prompt": "a calm loop", "music_length_ms": 12000}
    assert fake.seen[1].full_url.endswith("/v1/music?output_format=mp3_44100_128")
    assert usage.cost_usd == p.quote("music", "", {"kind": "music", "seconds": 12})


def test_elevenlabs_401_says_check_the_key_and_never_shows_it(monkeypatch):
    fake = Fake([("/v1/user/subscription", http_error(401, {})),
                 ("/v1/sound-generation", http_error(401, {"detail": {"message": f"bad key {SECRET}"}}))])
    monkeypatch.setattr(el, "_urlopen", fake)
    with pytest.raises(ProviderError) as e:
        el.ElevenLabsSoundProvider().generate("effects", "a jump")
    assert "Check the ElevenLabs key in Settings" in str(e.value) and SECRET not in str(e.value)
    assert not e.value.retryable and not e.value.out_of_credit


def test_elevenlabs_402_is_out_of_credit(monkeypatch):
    fake = Fake([("/v1/user/subscription", SUB),
                 ("/v1/sound-generation", http_error(402, {"detail": {"status": "quota_exceeded"}}))])
    monkeypatch.setattr(el, "_urlopen", fake)
    with pytest.raises(ProviderError) as e:
        el.ElevenLabsSoundProvider().generate("effects", "a jump")
    assert e.value.out_of_credit and "Top up" in str(e.value)


def test_elevenlabs_retries_once_with_the_same_request(monkeypatch):
    fake = Fake([("/v1/user/subscription", SUB), ("/v1/sound-generation", http_error(503, {})),
                 ("/v1/sound-generation", mp3(1)), ("/v1/user/subscription", SUB)])
    monkeypatch.setattr(el, "_urlopen", fake)
    el.ElevenLabsSoundProvider(retry_wait=0).generate("effects", "a jump", {"seconds": 1})
    posts = [r for r in fake.seen if r.get_method() == "POST"]
    assert len(posts) == 2 and posts[0].data == posts[1].data


def test_elevenlabs_free_tier_is_not_for_selling(monkeypatch):
    monkeypatch.setattr(el, "_urlopen", Fake([("/v1/user/subscription", {**SUB, "tier": "free"})]))
    lic = el.ElevenLabsSoundProvider().licence()
    assert lic["commercial"] is False and "free plan" in lic["words"] and lic["read_on"]
    monkeypatch.setattr(el, "_urlopen", Fake([("/v1/user/subscription", SUB)]))
    assert el.ElevenLabsSoundProvider().licence()["commercial"] is True


def test_elevenlabs_balance(monkeypatch):
    monkeypatch.setattr(el, "_urlopen", Fake([("/v1/user/subscription", SUB)]))
    assert el.ElevenLabsSoundProvider(usd_per_credit=0.0002).balance() == round(29000 * 0.0002, 6)
    assert el.ElevenLabsSoundProvider().balance() is None  # no dollars a credit: can't be told


# -- Stable Audio -------------------------------------------------------------------------------------------------
def test_stable_audio_quote_is_flat():
    p = sa.StableAudioProvider()
    assert p.quote("stable-audio-2.5", "x", {"seconds": 1}) == 0.08 == p.quote("default", "x", {"seconds": 120})
    assert p.quote("an-unknown-model", "x") is None


def test_stable_audio_form_and_the_real_charge(monkeypatch):
    fake = Fake([("/v1/user/balance", {"credits": 100}), ("/v2beta/audio/stable-audio-2.5/text-to-audio", wav(3)),
                 ("/v1/user/balance", {"credits": 92})])
    monkeypatch.setattr(sa, "_urlopen", fake)
    data, ext, usage = sa.StableAudioProvider().generate("default", "rain on a roof",
                                                         {"kind": "music", "seconds": 3, "format": "wav", "seed": 7})
    post = fake.seen[1]
    assert post.get_header("Authorization") == f"Bearer {SECRET}"
    form = post.data.decode()
    for field, value in (("prompt", "rain on a roof"), ("duration", "3"), ("output_format", "wav"), ("seed", "7")):
        assert f'name="{field}"\r\n\r\n{value}\r\n' in form
    assert ext == "wav" and usage.cost_usd == 0.08 and soundcheck.check(data, ext, "music", 3)[0]


def test_stable_audio_errors(monkeypatch):
    monkeypatch.setattr(sa, "_urlopen", Fake([("/v1/user/balance", {"credits": 5}),
                                              ("/v2beta", http_error(402, {"errors": ["insufficient credits"]}))]))
    with pytest.raises(ProviderError) as e:
        sa.StableAudioProvider().generate("default", "x")
    assert e.value.out_of_credit
    monkeypatch.setattr(sa, "_urlopen", Fake([("/v1/user/balance", {"credits": 5}),
                                              ("/v2beta", http_error(401, {"errors": [f"key {SECRET}"]}))]))
    with pytest.raises(ProviderError) as e:
        sa.StableAudioProvider().generate("default", "x")
    assert "Check the Stability key in Settings" in str(e.value) and SECRET not in str(e.value)
    fake = Fake([("/v1/user/balance", {"credits": 5}), ("/v2beta", http_error(429, {})), ("/v2beta", mp3(1)),
                 ("/v1/user/balance", {"credits": 5})])
    monkeypatch.setattr(sa, "_urlopen", fake)
    sa.StableAudioProvider(retry_wait=0).generate("default", "x", {"seconds": 1})
    assert len([r for r in fake.seen if r.get_method() == "POST"]) == 2
    monkeypatch.setattr(sa, "_urlopen", Fake([("/v1/user/balance", {"credits": 50})]))
    assert sa.StableAudioProvider().balance() == 0.5 and sa.StableAudioProvider().licence()["commercial"] is True


def test_no_key_in_any_log_line(monkeypatch, caplog):
    fake = Fake([("/v1/user/subscription", SUB), ("/v1/sound-generation", mp3(1)), ("/v1/user/subscription", SUB)])
    monkeypatch.setattr(el, "_urlopen", fake)
    with caplog.at_level("DEBUG"):
        el.ElevenLabsSoundProvider().generate("effects", "a jump")
    assert SECRET not in caplog.text


# -- the check of the file ----------------------------------------------------------------------------------------
def test_soundcheck():
    assert soundcheck.check(b"", "mp3", "effect", 1)[0] is False
    assert soundcheck.check(b"<html>nope</html>" * 10, "mp3", "effect", 1) == (False, "The file isn't an MP3 or a WAV.")
    assert soundcheck.check(wav(1, loud=False), "wav", "effect", 1) == (False, "The sound is silent.")
    assert soundcheck.check(wav(1), "wav", "effect", 1) == (True, "")
    ok, why = soundcheck.check(mp3(10), "mp3", "effect", 2)
    assert not ok and "10.0 seconds long" in why
    assert abs(soundcheck.mp3_seconds(mp3(3)) - 3) < 0.1
