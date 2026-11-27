"""The PC's setup: keys of every provider, the provider Test, the recommended setup and the start-up migration."""

import io
import json
import os

from roundtable.core import secrets as vault
import urllib.error
from datetime import date

import pytest
import yaml

from roundtable import desktop, recommended
from roundtable.desktop import KeyStore, Paths, ensure_configs, migrate_configs, provider_key_names
from roundtable.harness.config import load_config
from roundtable.phone import phone_allowed
from roundtable.providers import balance, manage

KEYS = ("DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "OPENFERENCE_API_KEY", "MY_PROVIDER_API_KEY")


class MemoryKeyring:
    def __init__(self):
        self.data = {}

    def get_password(self, service, name):
        return self.data.get((service, name))

    def set_password(self, service, name, value):
        self.data[(service, name)] = value

    def delete_password(self, service, name):
        self.data.pop((service, name), None)


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def paths(tmp_path):
    p = Paths(tmp_path / "home")
    ensure_configs(p)
    return p


def ui(paths, keystore):
    from roundtable.ui.server import UIApp

    app = UIApp(str(paths.hub_yaml), str(paths.harness_yaml), agent="me", projects_dir=str(paths.home / "projects"))
    app.desktop = {"paths": paths, "keys": keystore}
    return app


# -- keys ---------------------------------------------------------------------------------------------
def test_keys_have_makers_names_and_custom_keys_load_at_start_up(paths):
    assert desktop.KNOWN_KEYS["OPENROUTER_API_KEY"] == "OpenRouter"
    assert desktop.KNOWN_KEYS["OPENFERENCE_API_KEY"] == "Openference"
    manage.add_provider(paths.harness_yaml, "custom", pid="my-provider", base_url="https://llm.example.test/v1")
    kr = MemoryKeyring()
    ks = KeyStore(paths, backend=kr)
    app = ui(paths, ks)
    app.dispatch("POST", "/api/setup/keys", {}, {"keys": {"MY_PROVIDER_API_KEY": "proxy-injected"}})
    by_id = {p["id"]: p for p in app.dispatch("GET", "/api/providers", {}, {})["providers"]}
    assert by_id["my-provider"]["key_set"]  # "set" straight after Save
    keys = {k["name"]: k for k in app.dispatch("GET", "/api/setup", {}, {})["keys"]}
    assert keys["MY_PROVIDER_API_KEY"]["label"] == "my-provider" and keys["MY_PROVIDER_API_KEY"]["set"]
    assert keys["OPENROUTER_API_KEY"]["label"] == "OpenRouter"

    vault.clear()  # a restart: a new KeyStore loads every provider's key
    assert "MY_PROVIDER_API_KEY" in provider_key_names(paths)
    assert "MY_PROVIDER_API_KEY" in KeyStore(paths, backend=kr).load_into_env(provider_key_names(paths))
    by_id = {p["id"]: p for p in ui(paths, ks).dispatch("GET", "/api/providers", {}, {})["providers"]}
    assert by_id["my-provider"]["key_set"]


# -- the provider Test checks the key itself ---------------------------------------------------------------
class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_http(monkeypatch, status=200, body=None):
    seen = {}

    def urlopen(req, timeout=None):
        seen["url"], seen["auth"] = req.full_url, req.headers.get("Authorization")
        if status != 200:
            raise urllib.error.HTTPError(req.full_url, status, "no", {}, io.BytesIO(b"{}"))
        return FakeResponse(json.dumps(body or {}).encode())

    monkeypatch.setattr(balance.urllib.request, "urlopen", urlopen)
    return seen


def test_provider_test_says_plainly_when_the_key_is_missing(paths, monkeypatch):
    seen = fake_http(monkeypatch)
    r = manage.test_provider(load_config(str(paths.harness_yaml)), "openrouter")
    assert r["ok"] is False and r["missing_key"]
    assert r["error"] == "No key for OpenRouter yet: paste it under API keys, then Save."
    assert not seen  # nothing was asked without a key


def test_provider_test_checks_the_key_and_reads_the_balance(paths, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "proxy-injected")
    seen = fake_http(monkeypatch, body={"data": {"total_credits": 5.0, "total_usage": 2.69}})
    monkeypatch.setattr(manage, "provider_models", lambda cfg, pid: ["a/b", "c/d"])
    r = manage.test_provider(load_config(str(paths.harness_yaml)), "openrouter")
    assert r["ok"] and r["message"] == "OK: the key works (OpenRouter, $2.31 left)"
    assert seen["url"] == "https://openrouter.ai/api/v1/credits" and seen["auth"] == "Bearer proxy-injected"


def test_provider_test_says_when_the_key_is_refused(paths, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "proxy-injected")
    fake_http(monkeypatch, status=401)
    monkeypatch.setattr(manage, "provider_models", lambda cfg, pid: ["public/list"])  # public: proves nothing
    r = manage.test_provider(load_config(str(paths.harness_yaml)), "openrouter")
    assert r["ok"] is False and r["refused"] and "was refused" in r["error"]


def test_provider_test_other_services_use_their_model_list(paths, monkeypatch):
    from roundtable.providers.base import ProviderError

    monkeypatch.setenv("OPENFERENCE_API_KEY", "proxy-injected")
    seen = fake_http(monkeypatch)

    def refused(cfg, pid):
        raise ProviderError("openference: authentication failed (401)")

    monkeypatch.setattr(manage, "provider_models", refused)
    cfg = load_config(str(paths.harness_yaml))
    r = manage.test_provider(cfg, "openference")
    assert r["ok"] is False and r["error"].startswith("The key for Openference was refused")
    monkeypatch.setattr(manage, "provider_models", lambda cfg, pid: ["GLM-5.3"])
    assert manage.test_provider(cfg, "openference")["message"] == "OK: the key works (Openference, 1 model)"
    assert not seen  # no balance address for it


# -- the recommended setup ------------------------------------------------------------------------------------
OLD = {
    "providers": {"deepseek": {"type": "openai_compat", "base_url": "https://api.deepseek.com",
                               "api_key_env": "DEEPSEEK_API_KEY"},
                  "mine": {"type": "openai_compat", "base_url": "https://llm.example.test/v1",
                           "api_key_env": "MINE_API_KEY"}},
    "roles": {"orchestrator": {"model": "deepseek/deepseek-v4-pro"},
              "coder": {"model": "deepseek/deepseek-v4-pro"},
              "writer": {"model": "mine/writer-1", "description": "long texts"}},
    "planner_role": "orchestrator",
    "limits": {"max_cost_usd": 3},
    "improve": {"after_each_run": True},
    "hub": {"config": "elsewhere/hub.yaml", "agent": "harness"},
}


def test_use_the_recommended_setup_keeps_the_owners_other_settings(paths):
    paths.harness_yaml.write_text(yaml.safe_dump(OLD), encoding="utf-8")
    custom = paths.config / "custom.yaml"
    custom.write_text(yaml.safe_dump({"roles": {"manager": {"model": "mine/writer-1"}}}), encoding="utf-8")
    custom_before = custom.read_text(encoding="utf-8")
    app = ui(paths, KeyStore(paths, backend=MemoryKeyring()))
    before = app.dispatch("GET", "/api/setup/recommended", {}, {})
    assert not before["in_use"] and "DeepSeek writes the code" in before["summary"]
    coder = next(r for r in before["rows"] if r["role"] == "coder")
    assert coder["before"] == ["deepseek/deepseek-v4-pro"] and coder["after"][:2] == ["anthropic/claude-opus-5-5", "deepseek/deepseek-v4-flash"]
    assert [p["name"] for p in before["profiles"]] == ["budget", "balanced", "quality"]

    r = app.dispatch("POST", "/api/setup/recommended", {}, {})
    assert r["in_use"] and r["backup"].endswith(f"harness.yaml.before-{date.today().isoformat()}")
    assert yaml.safe_load(open(r["backup"], encoding="utf-8")) == OLD
    new = yaml.safe_load(paths.harness_yaml.read_text(encoding="utf-8"))
    assert new["limits"] == {"max_cost_usd": 3, "max_parallel": 3} and new["improve"] == {"after_each_run": True}
    assert new["hub"] == OLD["hub"] and new["default_profile"] == "balanced"
    assert new["roles"]["writer"] == OLD["roles"]["writer"] and "mine" in new["providers"]  # their own extras stay
    assert "deepseek-v4-pro" not in paths.harness_yaml.read_text(encoding="utf-8")
    assert custom.read_text(encoding="utf-8") == custom_before
    cfg = load_config(str(paths.harness_yaml))
    assert str(cfg.roles["manager"].models[0]) == "mine/writer-1"  # their own choice in Models still counts
    assert phone_allowed("POST", "/api/setup/recommended") and phone_allowed("GET", "/api/setup/recommended")


def test_recommended_backups_never_overwrite_each_other(paths):
    day = date(2026, 11, 26)
    recommended.apply(paths.harness_yaml, today=day)
    second = recommended.apply(paths.harness_yaml, today=day)
    assert second["backup"].endswith("harness.yaml.before-2026-11-26-2")


# -- start-up migration ----------------------------------------------------------------------------------
def hub_decisions(paths):
    from roundtable.core.config import load_config as load_hub
    from roundtable.hub.service import Hub

    hub = Hub(load_hub(str(paths.hub_yaml)))
    return [e["text"] for e in hub.journal.entries("me") if e["kind"] == "decision"]


def test_migration_replaces_an_untouched_old_template(paths, monkeypatch):
    old = "roles:\n  orchestrator: {model: anthropic/claude-fable-5-2}\n"  # stands in for an old shipped template
    monkeypatch.setattr(desktop, "OLD_TEMPLATES", desktop.OLD_TEMPLATES | {desktop._template_hash(old)})
    paths.harness_yaml.write_bytes(old.replace("\n", "\r\n").encode("utf-8"))  # as Windows wrote it
    done = migrate_configs(paths, today=date(2026, 11, 26))
    assert done and paths.harness_yaml.read_text(encoding="utf-8") == recommended.template_text()
    assert (paths.config / "harness.yaml.before-2026-11-26").exists()
    assert any("recommended setup" in t for t in hub_decisions(paths))


def test_the_shipped_0_8_0_template_is_known(paths):
    import subprocess

    old = subprocess.run(["git", "show", "3d02ca9:src/roundtable/templates/harness.example.yaml"],
                         capture_output=True, text=True, cwd=os.path.dirname(__file__))
    if old.returncode != 0:
        pytest.skip("needs the git history")
    assert desktop._template_hash(old.stdout) in desktop.OLD_TEMPLATES
    assert desktop._template_hash(recommended.template_text()) not in desktop.OLD_TEMPLATES


def test_migration_swaps_v4_pro_for_flash_in_an_edited_file(paths):
    text = "# mine\n" + yaml.safe_dump(OLD)
    paths.harness_yaml.write_text(text, encoding="utf-8")
    done = migrate_configs(paths, today=date(2026, 11, 26))
    assert done and "no DeepSeek V4 Pro" in done[0]
    new = paths.harness_yaml.read_text(encoding="utf-8")
    assert new == text.replace("deepseek-v4-pro", "deepseek-v4-flash") and new.startswith("# mine\n")
    assert (paths.config / "harness.yaml.before-2026-11-26").read_text(encoding="utf-8") == text
    decisions = hub_decisions(paths)
    assert any(t.startswith("Switched by Roundtable:") and "Why: the owner said no DeepSeek V4 Pro" in t
               for t in decisions)


def test_migration_leaves_anything_else_alone(paths):
    text = paths.harness_yaml.read_text(encoding="utf-8") + "\n# mine\n"  # the new template, edited
    paths.harness_yaml.write_text(text, encoding="utf-8")
    assert migrate_configs(paths) == []
    assert paths.harness_yaml.read_text(encoding="utf-8") == text
    assert not list(paths.config.glob("harness.yaml.before-*"))
    fresh = Paths(paths.home.parent / "fresh")
    ensure_configs(fresh)
    assert migrate_configs(fresh) == []  # a new install already has the recommended setup
