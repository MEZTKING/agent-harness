"""What models write, read in the owner's language (translate.py): priced first, kept, charged once, refused for a
project that allows no model, and the automatic kind stopped by its daily allowance. Whole tables are made in
checked batches. Made-up projects, scripted models, nothing touches the network."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from roundtable import translate as tr
from roundtable import words as W
from roundtable.harness import projectsettings as ps
from roundtable.harness.config import parse_config
from roundtable.providers.scripted import ScriptedProvider, reply
from roundtable.ui import server


def _cfg(brain):
    raw = {"providers": {"a": {"type": "scripted"}, "b": {"type": "scripted"}},
           "roles": {"orchestrator": {"model": "a/planner"}, "coder": {"model": "a/coder"},
                     "reviewer": {"model": "b/reviewer"}},
           "pricing": {"a/planner": {"input": 5, "output": 5}, "a/coder": {"input": 3, "output": 3},
                       "b/reviewer": {"input": 1, "output": 1}}}
    cfg = parse_config(raw)
    for n in ("a", "b"):
        cfg.register(n, ScriptedProvider(n, brain))
    return cfg


def project(root):
    (root / ".harness").mkdir(parents=True)
    (root / ".harness" / "project.json").write_text(json.dumps({"name": "Made-up game"}), encoding="utf-8")
    return root


class Brain:
    def __init__(self, text="ترجمة"):
        self.calls, self.text = [], text

    def __call__(self, model, system, messages, tools):
        self.calls.append((model, system, messages[0]["content"]))
        if messages[-1]["role"] == "tool":
            return reply("done")
        return reply(calls=[("submit_translation", {"text": self.text})])


def test_the_price_comes_first_and_nothing_is_sent(tmp_path):
    brain = Brain()
    cfg = _cfg(brain)
    p = tr.price(cfg, "The tests pass now.", "ar")
    assert p is not None and p > 0 and not brain.calls
    assert tr.price(cfg, "anything", "en-GB") == 0.0 and tr.price(cfg, "  ", "ar") == 0.0
    assert tr.price(SimpleNamespace(roles={}), "x", "ar") is None and tr.price(None, "x", "ar") is None


def test_translated_once_kept_and_free_the_second_time(tmp_path):
    brain = Brain()
    cfg = _cfg(brain)
    root = project(tmp_path / "game")
    first = tr.words(cfg, root, "The tests pass now.", "ar", "a review")
    assert first["text"] == "ترجمة" and not first["cached"] and first["usd"] > 0
    assert len(brain.calls) == 1 and brain.calls[0][0] == "reviewer"  # the cheapest
    assert "Arabic" in brain.calls[0][1] and "Darkness Harness" in brain.calls[0][1]
    again = tr.words(cfg, root, "The tests pass now.", "ar", "a review")
    assert again == {"text": "ترجمة", "cached": True, "usd": 0.0} and len(brain.calls) == 1
    assert len(list((root / ".harness" / "translations").glob("*.json"))) == 1


def test_english_needs_no_call(tmp_path):
    brain = Brain()
    assert tr.words(_cfg(brain), project(tmp_path / "g"), "Hello", "en-GB", "a card") == {
        "text": "Hello", "cached": False, "usd": 0.0}
    assert not brain.calls


def test_the_project_s_allowed_makers_are_obeyed(tmp_path):
    brain = Brain()
    cfg = _cfg(brain)
    root = project(tmp_path / "shut")
    ps.update(root, {"makers_allowed": ["anthropic"]})
    with pytest.raises(tr.TranslateError, match="No model this project allows"):
        tr.words(cfg, root, "A secret plan.", "ar", "a card")
    assert not brain.calls


def test_the_automatic_kind_is_off_by_default_then_stops_at_its_allowance(tmp_path):
    brain = Brain()
    cfg = _cfg(brain)
    root = project(tmp_path / "game")
    with pytest.raises(tr.TranslateError, match="Switch it on"):
        tr.words(cfg, root, "Because the logo was blurry.", "ar", "auto: a card's reason")
    W.save_settings(auto_reasons=True, allowance_usd=0.5)
    out = tr.words(cfg, root, "Because the logo was blurry.", "ar", "auto: a card's reason")
    assert out["usd"] > 0 and tr.spent_today() == pytest.approx(out["usd"])
    W.save_settings(allowance_usd=tr.spent_today())  # used up
    with pytest.raises(tr.TranslateError, match="allowance"):
        tr.words(cfg, root, "Another reason.", "ar", "auto: a card's reason")
    assert len(brain.calls) == 1
    tapped = tr.words(cfg, root, "Another reason.", "ar", "a card's reason")  # a tap isn't the automatic kind
    assert tapped["usd"] > 0 and tr.spent_today() == pytest.approx(out["usd"])


def test_the_route_prices_first_then_translates(tmp_path, monkeypatch):
    from roundtable.ui import wordsapi

    brain = Brain()
    cfg = _cfg(brain)
    root = project(tmp_path / "game")
    app = server.UIApp.__new__(server.UIApp)
    app.need_cfg = lambda: cfg
    app.project = lambda c, path: SimpleNamespace(root=root)
    with pytest.raises(server.ApiError, match="nothing to translate"):
        wordsapi.translate(app, {"path": "x", "text": " "})
    first = wordsapi.translate(app, {"path": "x", "text": "It works.", "why": "a review", "lang": "ar"})
    assert first["text"] == "" and first["price_usd"] > 0 and first["words"].startswith("About $") and not brain.calls
    done = wordsapi.translate(app, {"path": "x", "text": "It works.", "why": "a review", "lang": "ar", "confirm": True})
    assert done["text"] == "ترجمة" and len(brain.calls) == 1
    again = wordsapi.translate(app, {"path": "x", "text": "It works.", "why": "a review", "lang": "ar"})
    assert again["cached"] and again["text"] == "ترجمة" and len(brain.calls) == 1


# -- whole tables ---------------------------------------------------------------------------------------------------
class TableBrain:
    """Answers each numbered line with "AR:" in front, keeping holes; or, when told, loses a hole once."""

    def __init__(self, lose_once=False):
        self.calls, self.lose = 0, lose_once

    def __call__(self, model, system, messages, tools):
        if messages[-1]["role"] == "tool":
            return reply("done")
        self.calls += 1
        lines = [ln for ln in messages[0]["content"].splitlines() if ln[:1].isdigit()]
        items = []
        for ln in lines:
            n, _, s = ln.partition(". ")
            text = "AR:" + s
            if self.lose and "{" in s:
                text = "AR"
            items.append({"n": int(n), "text": text})
        self.lose = False
        return reply(calls=[("submit_translation", {"items": items})])


def test_a_table_is_priced_first_then_made_in_checked_batches(tmp_path):
    brain = TableBrain(lose_once=True)
    cfg = _cfg(brain)
    sentences = ["Done", "Approve the plan", "{n} tasks left", "Hello {name}"]
    quote = tr.table(cfg, "ar", sentences)
    assert quote["table"] == {} and quote["price"]["usd"] > 0 and brain.calls == 0
    r = tr.table(cfg, "ar", sentences, confirm=True, log=lambda s: None)
    assert brain.calls == 2  # the batch that lost a hole was asked again
    assert r["table"]["Hello {name}"] == "AR:Hello {name}" and r["left"] == [] and r["usd"] > 0
    assert r["table"]["@meta"]["by"] == "model" and r["table"]["@meta"]["rtl"] is True
    assert W.problems(r["table"]) == []


def test_a_batch_that_comes_back_in_english_is_refused():
    asked = [f"Sentence number {i}" for i in range(10)]
    assert tr.check_batch(asked, {s: s for s in asked})
    assert not tr.check_batch(asked, {s: "AR " + s for s in asked})


def test_the_english_table_is_what_the_shipped_tables_are_made_from():
    got = tr.english()
    assert len(got) > 1000 and "Try again" in got
    assert not any(s.startswith("@") for s in got)
