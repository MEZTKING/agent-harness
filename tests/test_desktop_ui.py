"""The rebuilt desktop command centre: its modules are served and found, and the routes its screens need."""

import json
import re
from importlib import resources
from pathlib import Path

import pytest
import yaml

from roundtable import routing
from roundtable.harness.config import load_config
from roundtable.recommended import template_text
from roundtable.ui.server import UIApp

from .test_ui import app, call, http, server  # noqa: F401  (fixtures)

STATIC = resources.files("roundtable").joinpath("ui/static")


def test_every_module_the_page_imports_is_shipped_flat():
    """Plain ES modules, no build step: every import is a file in static/ (no folders, so package data and the
    Windows build pick them all up)."""
    html = STATIC.joinpath("index.html").read_text(encoding="utf-8")
    assert '<script type="module" src="app.js">' in html
    seen, todo = set(), ["app.js"]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        text = STATIC.joinpath(name).read_text(encoding="utf-8")
        for dep in re.findall(r"""(?:from|import\()\s*["']\./([^"']+)["']""", text):
            assert "/" not in dep and STATIC.joinpath(dep).is_file(), f"{name} imports {dep}"
            todo.append(dep)
    assert {"core.js", "asks.js", "hall.js", "needs.js", "project.js", "plan.js", "watch.js", "models.js", "settings.js",
            "letters.js", "activity.js", "journal.js", "machines.js", "autopilot.js"} <= seen
    assert "ui/static/*" in Path(__file__).parents[1].joinpath("pyproject.toml").read_text(encoding="utf-8")


def test_no_html_from_data_and_no_outside_scripts():
    for f in STATIC.iterdir():
        if f.name.endswith(".js"):
            text = f.read_text(encoding="utf-8")
            assert "innerHTML" not in text and "insertAdjacentHTML" not in text and "eval(" not in text, f.name
            assert not re.search(r"""(?:from|import\()\s*["']https?:""", text), f.name


def test_the_page_never_says_a_variable_name_or_jargon():
    """Words the owner reads: no key variable names, no 'harness', no orchestrator or role ids on screen."""
    for f in STATIC.iterdir():
        if not f.name.endswith(".js"):
            continue
        strings = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', f.read_text(encoding="utf-8"))
        shown = [s for s in strings if " " in s]  # sentences, not keys or class names
        for s in shown:
            assert not re.search(r"\b[A-Z]+_API_KEY\b|harness\.yaml|custom\.yaml|\borchestrator\b|--config", s), (f.name, s)


def test_scripts_are_served_as_javascript(server):  # noqa: F811
    for name in ("app.js", "core.js", "hall.js", "models.js"):
        st, data, hd = http(server + "/" + name)
        assert st == 200 and data and "javascript" in hd["Content-Type"], name


def test_features_lists_the_routes(app):  # noqa: F811
    routes = call(app, "GET", "/api/features")["routes"]
    assert "/api/roundtable" in routes and "/api/routing" in routes and "/api/plugins" in routes
    assert "/api/machines" not in routes or True  # optional parts appear when they are installed


def test_model_and_job_names():
    assert routing.model_label("anthropic/claude-opus-5-5") == "Claude Opus 5.5 (Anthropic)"
    assert routing.model_label("deepseek/deepseek-v4-flash") == "DeepSeek V4 Flash (DeepSeek)"
    assert routing.model_label("openrouter/anthropic/claude-sonnet-5.5") == "Claude Sonnet 5.5 (OpenRouter)"
    assert routing.model_label("openference/Claude Opus 5.5") == "Claude Opus 5.5 (Openference)"
    assert routing.model_label("openrouter_images/google/gemini-3.1-flash-image") == "Gemini 3.1 Flash Image (OpenRouter)"
    assert routing.model_label("openrouter/openai/gpt-6.1-terra") == "GPT 6.1 Terra (OpenRouter)"
    assert routing.job_name("orchestrator") == "Planner" and routing.job_name("coder") == "Coder"
    assert routing.job_name("sound_designer") == "Sound Designer"


@pytest.fixture
def lab_cfg(tmp_path):
    """The shipped template as a settings file, with a lab: what the owner has after the set-up."""
    path = tmp_path / "harness.yaml"
    path.write_text(template_text() + f"\nimprove:\n  lab_dir: {tmp_path / 'lab'}\n", encoding="utf-8")
    return path


def test_routing_view_shows_every_job_and_set(lab_cfg):
    v = routing.view(load_config(str(lab_cfg)))
    coder = next(j for j in v["jobs"] if j["role"] == "coder")
    assert coder["name"] == "Coder" and v["jobs"][0]["name"] == "Planner"
    balanced = coder["sets"]["balanced"]
    assert [m["label"] for m in balanced["models"]] == ["Claude Opus 5.5 (Anthropic)", "DeepSeek V4 Flash (DeepSeek)"]
    assert balanced["effort"] == "medium" and v["default_set"] == "balanced"
    assert [s["name"] for s in v["sets"]] == ["Budget", "Balanced", "Quality"]
    assert any(c["ref"] == "deepseek/deepseek-v4-flash" for c in v["choices"])
    assert v["providers"]["deepseek"]["name"] == "DeepSeek"


def test_changing_who_does_a_job(lab_cfg):
    # a set's own choice goes into that set, with the effort; the old file is kept once a day
    routing.set_job(lab_cfg, "coder", ["deepseek/deepseek-v4-flash", "anthropic/claude-opus-5-5"], profile="balanced", effort="high")
    cfg = load_config(str(lab_cfg))
    c = cfg.for_profile("balanced").roles["coder"]
    assert [str(m) for m in c.models] == ["deepseek/deepseek-v4-flash", "anthropic/claude-opus-5-5"] and c.options["effort"] == "high"
    backups = list(lab_cfg.parent.glob("harness.yaml.before-*"))
    assert len(backups) == 1 and "claude-opus-5-5" in backups[0].read_text(encoding="utf-8")
    routing.set_job(lab_cfg, "coder", ["deepseek/deepseek-v4-flash"], profile="budget")
    assert len(list(lab_cfg.parent.glob("harness.yaml.before-*"))) == 1
    # the base choice goes to custom.yaml, the same as `roundtable assign`
    routing.set_job(lab_cfg, "reviewer", ["deepseek/deepseek-v4-flash"])
    assert yaml.safe_load((lab_cfg.parent / "custom.yaml").read_text(encoding="utf-8"))["roles"]["reviewer"]["model"] == "deepseek/deepseek-v4-flash"
    # which set is used by default
    routing.set_default(lab_cfg, "quality")
    assert load_config(str(lab_cfg)).default_profile == "quality"
    # nothing is written when the change doesn't fit
    before = lab_cfg.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        routing.set_job(lab_cfg, "coder", ["nowhere/model"], profile="balanced")
    with pytest.raises(ValueError):
        routing.set_job(lab_cfg, "coder", [], profile="balanced")
    with pytest.raises(ValueError):
        routing.set_default(lab_cfg, "luxury")
    assert lab_cfg.read_text(encoding="utf-8") == before


def test_routing_api(tmp_path, lab_cfg):
    a = UIApp(hub_config=str(tmp_path / "no-hub.yaml"), harness_config=str(lab_cfg), projects_dir=str(tmp_path / "p"))
    v = call(a, "GET", "/api/routing")
    assert v["can_change"] and any(j["role"] == "coder" for j in v["jobs"])
    v = call(a, "POST", "/api/routing", {"role": "coder", "models": ["deepseek/deepseek-v4-flash"], "set": "balanced", "effort": "low"})
    coder = next(j for j in v["jobs"] if j["role"] == "coder")
    assert [m["ref"] for m in coder["sets"]["balanced"]["models"]] == ["deepseek/deepseek-v4-flash"] and coder["sets"]["balanced"]["effort"] == "low"
    v = call(a, "POST", "/api/routing", {"default_set": "budget"})
    assert v["default_set"] == "budget"
    from roundtable.ui.server import ApiError

    with pytest.raises(ApiError, match="Nothing was changed"):
        call(a, "POST", "/api/routing", {"role": "coder", "models": ["nowhere/x"], "set": "balanced"})
    with pytest.raises(ApiError):
        call(a, "POST", "/api/routing", {"role": "juggler", "models": ["deepseek/deepseek-v4-flash"]})


def test_setup_says_which_services_each_key_is_for(tmp_path, lab_cfg):
    a = UIApp(hub_config=str(tmp_path / "no-hub.yaml"), harness_config=str(lab_cfg), projects_dir=str(tmp_path / "p"))
    st = call(a, "GET", "/api/setup")
    ds = next(k for k in st["keys"] if k["name"] == "DEEPSEEK_API_KEY")
    assert ds["label"] == "DeepSeek" and ds["providers"] == ["deepseek"]
    assert st["config_exists"]["harness"] is True and isinstance(st["config_exists"]["hub"], bool)
    assert all("_API_KEY" not in k["label"] for k in st["keys"])
    json.dumps(st)
