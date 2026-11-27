"""Wave 7, Helper 4: the owner's house style (parity MD-27) in every system prompt, and its API."""

import json

import pytest
import yaml

from roundtable.harness import housestyle
from roundtable.harness.charterstage import CharterStage
from roundtable.harness.orchestrator import Orchestrator
from roundtable.improve import charter

from .test_harness import RAW, Brain
from .test_improve import make_cfg


class Seen(Brain):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.systems = []

    def __call__(self, model, system, messages, tools):
        self.systems.append(system)
        return super().__call__(model, system, messages, tools)


def _staged():
    return type("O", (Orchestrator,) if issubclass(Orchestrator, CharterStage) else (CharterStage, Orchestrator), {})


def _run(tmp_path, cls, style=None, name="p"):
    brain = Seen()
    cfg, _ = make_cfg(tmp_path, brain=brain)
    if style is not None:
        cfg.sections["style"] = style
    orch = cls(cfg, tmp_path / name)
    orch.start("a goal")
    assert orch.run() == "done"
    return cfg, brain.systems


def test_the_house_style_reaches_planner_worker_and_reviewer(tmp_path):
    mine = "Write like a friendly baker: warm, short, no jargon."
    cfg, systems = _run(tmp_path, _staged(), {"on": True, "text": mine})
    part = f"{housestyle.HEADING}\n{mine}"
    for prompt in ("orchestrator", "coder", "reviewer"):
        base = cfg.prompt_text(prompt)
        got = [s for s in systems if s.startswith(base)]
        assert got, prompt
        assert all(part in s and charter.fixed_block(prompt) in s for s in got), prompt


def test_off_means_byte_for_byte_as_before_but_the_fixed_rules_stay(tmp_path):
    _, bare = _run(tmp_path, Orchestrator, name="a")
    _, staged = _run(tmp_path, _staged(), {"on": False}, name="b")
    block = charter.fixed_block("")
    assert [f"{s}\n\n{block}" for s in bare] == staged


def test_the_default_style_is_on_and_short(tmp_path):
    cfg, _ = make_cfg(tmp_path)
    assert housestyle.settings(cfg) == {"on": True, "text": housestyle.DEFAULT_TEXT}
    assert housestyle.block(cfg) == f"{housestyle.HEADING}\n{housestyle.DEFAULT_TEXT}"
    assert len(housestyle.DEFAULT_TEXT) < 120
    assert housestyle.block(None) and housestyle.settings(None)["on"] is True


def test_clean_keeps_the_shape_and_the_limit():
    assert housestyle.clean({"on": "no"})["on"] is False
    assert housestyle.clean({"text": "  Plain.\n\n\n\nShort.​ "})["text"] == "Plain.\n\nShort."
    with pytest.raises(ValueError, match="1200"):
        housestyle.clean({"text": "x" * 1201})
    with pytest.raises(ValueError):
        housestyle.clean({"text": 5})
    with pytest.raises(ValueError):
        housestyle.clean("on")


def test_custom_yaml_wins_and_is_read_again_when_it_changes(tmp_path):
    harness = tmp_path / "harness.yaml"
    harness.write_text(yaml.safe_dump({**RAW, "style": {"text": "From harness.yaml."}}), encoding="utf-8")
    cfg, _ = make_cfg(tmp_path)
    cfg.path = harness
    cfg.sections["style"] = {"text": "From harness.yaml."}
    assert housestyle.settings(cfg)["text"] == "From harness.yaml."
    housestyle.save(harness, {"text": "From the app."})
    assert housestyle.settings(cfg)["text"] == "From the app."
    housestyle.save(harness, {"on": False})
    assert housestyle.block(cfg) == "" and housestyle.settings(cfg)["text"] == "From the app."
    housestyle.save(harness, {"reset": True})
    assert housestyle.settings(cfg) == {"on": True, "text": housestyle.DEFAULT_TEXT}
    assert yaml.safe_load(harness.read_text(encoding="utf-8"))["style"] == {"text": "From harness.yaml."}


# -- the API --------------------------------------------------------------------------------------------
@pytest.fixture
def app(tmp_path, monkeypatch):
    from roundtable.ui import server
    from roundtable.ui.server import UIApp

    from .test_hub import RAW as HUB_RAW

    hub_raw = json.loads(json.dumps(HUB_RAW))
    hub_raw["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
    (tmp_path / "hub.yaml").write_text(yaml.safe_dump(hub_raw), encoding="utf-8")
    (tmp_path / "harness.yaml").write_text(yaml.safe_dump(RAW), encoding="utf-8")
    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "styleapi"))
    return UIApp(str(tmp_path / "hub.yaml"), str(tmp_path / "harness.yaml"), agent="backend")


def test_the_style_api_through_the_server(app, tmp_path):
    from roundtable.ui.server import ApiError

    got = app.dispatch("GET", "/api/style", {}, {})
    assert got["on"] is True and got["text"] == housestyle.DEFAULT_TEXT and got["max_chars"] == 1200
    assert got["words"] == "Agents write for you in the usual house style."
    got = app.dispatch("POST", "/api/style", {}, {"text": "Short and kind."})
    assert got["text"] == "Short and kind." and "your own house style" in got["words"]
    assert yaml.safe_load((tmp_path / "custom.yaml").read_text(encoding="utf-8"))["style"]["text"] == "Short and kind."
    with pytest.raises(ApiError, match="Nothing was changed"):
        app.dispatch("POST", "/api/style", {}, {"text": "x" * 2000})
    assert app.dispatch("POST", "/api/style", {}, {"on": False})["words"] == "Agents write in their own way."
    assert app.dispatch("POST", "/api/style", {}, {"reset": True})["text"] == housestyle.DEFAULT_TEXT
    assert "/api/style" in app.dispatch("GET", "/api/features", {}, {})["routes"]


def test_the_charter_api_lists_what_it_can_never_change(app):
    got = app.dispatch("GET", "/api/charter", {}, {})
    assert got["words"] and {r["id"] for r in got["never"]} >= {"gate", "money", "privacy", "style"}
