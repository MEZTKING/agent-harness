"""One list of services (integrations.py) and the MCP catalogue (mcp_catalogue.json through prereq.py). Made-up
settings; no network, no keys (made-up key text is put in the vault to check it never comes out)."""

import json

import pytest

from roundtable import integrations as ig
from roundtable import prereq
from roundtable.core import secrets as vault
from roundtable.harness.config import parse_config
from roundtable.harness.safeenv import is_secret_name

FAKE_KEY = "sk-made-up-0123456789abcdef"
GH_KEY = "github_pat_made_up_0123456789"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for n in ("DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "ROUNDTABLE_GITHUB_TOKEN", "ROUNDTABLE_HUB_TOKEN", "GITHUB_TOKEN",
              "GH_TOKEN", "BRAVE_API_KEY", "TAVILY_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(n, raising=False)
    vault.clear()
    ig.forget_tests()
    yield
    vault.clear()
    ig.forget_tests()


def cfg(tmp_path):
    raw = {"providers": {"deepseek": {"type": "openai_compat", "api_key_env": "DEEPSEEK_API_KEY",
                                      "base_url": "https://api.deepseek.com"},
                         "pictures": {"type": "chat_images", "api_key_env": "OPENROUTER_API_KEY"},
                         "cli": {"type": "cli"}},
           "roles": {"orchestrator": {"model": "deepseek/deepseek-chat"}, "coder": {"model": "deepseek/deepseek-chat"},
                     "reviewer": {"model": "cli/claude-code"}, "artist": {"model": "pictures/x", "kind": "image"}}}
    return parse_config(raw, tmp_path / "harness.yaml")


LAB = ("providers: {a: {type: scripted}}\nroles: {orchestrator: {model: a/p}, coder: {model: a/c}, "
       "reviewer: {model: a/r}}\n")
SERVERS = {"servers": [{"name": "blender", "enabled": True, "jobs": ["Builder"]}]}
PLUGINS = [{"id": "notes", "name": "Notes", "enabled": True,
            "permissions": [{"id": "secrets:api.deepseek.com"}, {"id": "network"}]}]


def walk(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield path + "." + str(k), k, v
            yield from walk(v, path + "." + str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")


def test_every_service_in_one_list_with_its_state_and_who_uses_it(tmp_path):
    c = cfg(tmp_path)
    vault.put("DEEPSEEK_API_KEY", FAKE_KEY)
    d = ig.listing(c, servers=SERVERS, plugins=PLUGINS)
    rows = {r["id"]: r for r in d["rows"]}
    assert rows["provider:deepseek"]["state"] == "ready" and "Coder" in rows["provider:deepseek"]["who"]
    assert rows["provider:deepseek"]["group"] == "Models"
    assert rows["provider:pictures"]["state"] == "missing" and rows["provider:pictures"]["group"] == "Pictures"
    assert rows["provider:pictures"]["needs"] == {"slot": "OPENROUTER_API_KEY", "label": "OpenRouter", "saved": False}
    assert rows["provider:cli"]["state"] == "ready"
    assert rows["github"]["state"] == "missing"
    assert rows["websearch"]["state"] == "ready"  # works without a key
    assert rows["mcp:blender"]["who"] == ["Builder"]
    assert rows["plugin:notes:api.deepseek.com"]["state"] == "ready"  # the DeepSeek key is used for that host
    assert d["counts"]["missing"] == 2 and "2 need a key" in d["words"]
    assert d["groups"] == ["Models", "Pictures", "GitHub", "Web search", "Tool servers", "Plug-ins"]


def test_the_list_never_holds_a_key(tmp_path):
    c = cfg(tmp_path)
    vault.put("DEEPSEEK_API_KEY", FAKE_KEY)
    vault.put("ROUNDTABLE_GITHUB_TOKEN", GH_KEY)
    d = ig.listing(c, servers=SERVERS, plugins=PLUGINS)
    text = json.dumps(d)
    assert FAKE_KEY not in text and GH_KEY not in text
    for where, k, v in walk(d):  # no field that safeenv would call a secret
        assert not is_secret_name(str(k)), where


def test_a_failed_test_shows_not_answering_and_never_repeats_a_key(tmp_path):
    c = cfg(tmp_path)
    vault.put("DEEPSEEK_API_KEY", FAKE_KEY)

    def boom(cfg, name):
        raise RuntimeError(f"401 from the maker for key {FAKE_KEY}")

    r = ig.test(c, "provider:deepseek", testers={"provider": boom})
    assert not r["ok"] and FAKE_KEY not in r["words"] and "***" in r["words"]
    row = next(x for x in ig.listing(c, servers=SERVERS, plugins=PLUGINS)["rows"] if x["id"] == "provider:deepseek")
    assert row["state"] == "not_answering" and row["state_words"] == "Not answering"
    ok = ig.test(c, "provider:deepseek", testers={"provider": lambda cfg, n: (True, "It answers: 3 models offered.")})
    assert ok["ok"]
    row = next(x for x in ig.listing(c, servers=SERVERS, plugins=PLUGINS)["rows"] if x["id"] == "provider:deepseek")
    assert row["state"] == "ready" and row["words"] == "It answers: 3 models offered."
    with pytest.raises(ValueError):
        ig.test(c, "websearch")


def test_a_provider_test_lists_models_and_costs_nothing(tmp_path, monkeypatch):
    c = cfg(tmp_path)

    class P:
        def list_models(self):
            return ["a", "b"]

        def chat(self, *a, **k):
            raise AssertionError("a test never calls a model")

    monkeypatch.setattr(type(c), "provider", lambda self, name: P())
    assert ig.test(c, "provider:deepseek")["words"] == "It answers: 2 models offered."


# -- the MCP catalogue -------------------------------------------------------------------------------------------
def test_the_catalogue_is_pinned_and_offered_with_the_engines(tmp_path):
    rows = prereq.catalogue_servers("linux")
    assert len(rows) >= 9
    for x in rows:
        args = x["spec"].get("args") or []
        pkg = next((a for a in args if "@" in a[1:] or a.startswith("mcp-server-")), None)
        assert pkg and "@" in pkg[1:], (x["id"], args)  # every package carries its exact version
        assert not any(is_secret_name(k) for k in (x["spec"].get("env") or {})), x["id"]
        assert all(n in prereq.BY_ID for n in x["needs"]), x["id"]
    ids = [x["id"] for x in prereq.known_servers("linux")]
    assert ids[:3] == ["unreal", "godot", "blender"] and "filesystem" in ids and "sqlite" in ids
    win = next(x for x in prereq.catalogue_servers("windows") if x["id"] == "playwright")
    assert win["spec"]["command"] == "cmd" and win["spec"]["args"][:2] == ["/c", "npx"]


def test_a_catalogue_tick_adds_the_pinned_command(tmp_path):
    h = tmp_path / "harness.yaml"
    h.write_text(LAB, encoding="utf-8")
    out = prereq.add_server(h, known="git", os_name="linux")
    assert out["name"] == "git"
    assert out["command"] == "uvx" and out["args"] == ["mcp-server-git@2026.10.10", "--repository", "{project}"]
    view = prereq.servers_view(h)
    assert view["servers"][0]["name"] == "git"


def test_project_placeholders_are_filled_or_left_off():
    servers = {"git": {"command": "uvx", "args": ["mcp-server-git@2026.10.10", "--repository", "{project}"]},
               "db": {"command": "npx", "args": [], "env": {"DSN": "sqlite:///{project}/app.db"}},
               "time": {"command": "uvx", "args": ["mcp-server-time@2026.10.10"]}}
    filled = prereq.with_project(servers, "/tmp/shop")
    assert filled["git"]["args"][-1].endswith("shop") and "{project}" not in json.dumps(filled)
    assert filled["time"] is servers["time"]
    none = prereq.with_project(servers, None)
    assert none["git"]["enabled"] is False and none["time"].get("enabled", True)


def test_a_server_test_gets_an_empty_folder_for_project(tmp_path):
    h = tmp_path / "harness.yaml"
    h.write_text(LAB, encoding="utf-8")
    prereq.add_server(h, known="filesystem", os_name="linux")
    seen = {}

    def check(servers):
        seen.update(servers)
        return [{"ok": True, "tools": ["filesystem__read_file"]}]

    r = prereq.test_server(h, "filesystem", check=check)
    assert r["ok"] and "{project}" not in json.dumps(seen)


# -- engines that install themselves -----------------------------------------------------------------------------
def test_an_engine_offers_install_only_with_a_checked_download():
    o = prereq.engine_offer("claude-code", "windows")
    assert o["auto"] and o["via"] == "npm" and "integrity" in o["checked"] and o["tool"] == "claude"
    assert "Install it and carry on" in o["words"]
    with pytest.raises(ValueError):
        prereq.engine_offer("nope", "linux")


def test_install_and_carry_on_resumes_the_task(monkeypatch):
    calls = []
    monkeypatch.setattr(prereq, "run_install", lambda tid, line, s=None, **kw: calls.append(tid) or {"ok": True})
    from pathlib import Path

    s = prereq.System("linux", [], {}, Path("/nonexistent-home"))
    carried = []
    r = prereq.install_and_carry_on("codex", lambda x: None, lambda: carried.append(1), s=s)
    assert calls == ["codex"] and carried == [1] and r["carried_on"]
    monkeypatch.setattr(prereq, "engine_offer", lambda e, os_name=None: {"auto": False, "words": "It won't install by itself."})
    with pytest.raises(ValueError, match="by itself"):
        prereq.install_and_carry_on("codex", lambda x: None, lambda: None, s=s)
