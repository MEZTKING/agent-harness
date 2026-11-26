import json
import textwrap

import pytest
import yaml

from roundtable.harness.config import load_config
from roundtable.providers import manage
from roundtable.providers.base import Provider, ProviderError
from roundtable.providers.catalog import PRESETS, preset_block, valid_provider_id

BASE = {
    "providers": {"deepseek": {"type": "openai_compat", "base_url": "https://api.deepseek.com",
                               "api_key_env": "DEEPSEEK_API_KEY"}},
    "roles": {"orchestrator": {"model": "deepseek/deepseek-v4-pro"},
              "coder": {"model": "deepseek/deepseek-v4-pro", "description": "writes code"}},
}


@pytest.fixture
def harness(tmp_path):
    p = tmp_path / "harness.yaml"
    p.write_text("# my comments stay\n" + yaml.safe_dump(BASE), encoding="utf-8")
    return p


def test_catalog_presets_are_complete():
    assert len(PRESETS) >= 18
    for pid, p in PRESETS.items():
        assert valid_provider_id(pid) and p["type"] in ("anthropic", "openai_compat", "openai_images", "retrodiffusion")
        if p["type"] == "openai_compat" and not p.get("custom"):
            assert p["base_url"].startswith(("https://", "http://localhost"))
    assert preset_block("groq") == {"type": "openai_compat", "base_url": "https://api.groq.com/openai/v1",
                                    "api_key_env": "GROQ_API_KEY", "preset": "groq"}
    assert "api_key_env" not in preset_block("ollama")
    with pytest.raises(ValueError):
        preset_block("custom")  # needs a base URL
    with pytest.raises(ValueError):
        preset_block("nope")


def test_add_assign_remove_round_trip(harness):
    before = harness.read_text(encoding="utf-8")
    manage.add_provider(harness, "openrouter")
    manage.add_provider(harness, "custom", pid="azure", base_url="https://r.openai.azure.com/openai/v1/",
                        auth_header="api-key", query={"api-version": "preview"})
    assert harness.read_text(encoding="utf-8") == before  # harness.yaml is never rewritten
    custom = yaml.safe_load((harness.parent / "custom.yaml").read_text(encoding="utf-8"))
    assert custom["providers"]["azure"]["api_key_env"] == "AZURE_API_KEY"

    manage.set_role_models(harness, "coder", ["openrouter/some/model", "deepseek/deepseek-flash"])
    manage.set_role_models(harness, "writer", ["azure/gpt-x"], description="marketing copy")
    cfg = load_config(str(harness))
    assert [str(m) for m in cfg.roles["coder"].models] == ["openrouter/some/model", "deepseek/deepseek-flash"]
    assert cfg.roles["coder"].description == "writes code"  # harness.yaml settings kept
    assert cfg.roles["writer"].description == "marketing copy"  # new role from the app
    assert cfg.providers["azure"]["auth_header"] == "api-key"

    with pytest.raises(ValueError, match="still used"):
        manage.remove_provider(harness, "openrouter")
    with pytest.raises(ValueError, match="harness.yaml"):
        manage.remove_provider(harness, "deepseek")
    with pytest.raises(ValueError):
        manage.set_role_models(harness, "coder", ["ghost/model"])  # unknown provider: rejected, nothing saved
    manage.set_role_models(harness, "coder", ["deepseek/deepseek-v4-pro"])
    manage.remove_provider(harness, "openrouter")
    ids = {p["id"]: p for p in manage.list_providers(harness)}
    assert set(ids) == {"deepseek", "azure"} and ids["azure"]["source"] == "custom.yaml"


def test_add_rejects_bad_input(harness):
    with pytest.raises(ValueError):
        manage.add_provider(harness, "groq", pid="9bad id")
    with pytest.raises(ValueError):
        manage.add_provider(harness, "groq", pid="deepseek")  # clashes with harness.yaml
    with pytest.raises(ValueError):
        manage.add_provider(harness, "plugin", pid="mine")  # needs class


def test_custom_auth_header_and_query_reach_the_wire(monkeypatch):
    httpx = pytest.importorskip("httpx2")  # the transport library of the installed openai SDK

    from roundtable.providers.openai_compat import OpenAICompatProvider

    seen = {}

    def handler(request: httpx.Request):
        seen["headers"] = dict(request.headers)
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"object": "list", "data": [{"id": "m1", "object": "model", "created": 0, "owned_by": "x"}]})

    monkeypatch.setenv("AZ_KEY", "secret-123")
    monkeypatch.setenv("TEAM", "red")
    p = OpenAICompatProvider("az", api_key_env="AZ_KEY", base_url="https://example.invalid/v1",
                             auth_header="api-key", headers={"X-Team": "${TEAM}"}, query={"api-version": "2025"})
    p.client._client = httpx.Client(transport=httpx.MockTransport(handler))
    assert p.list_models() == ["m1"]
    assert seen["headers"]["api-key"] == "secret-123"
    assert "secret-123" not in seen["headers"].get("authorization", "")  # not also sent as Bearer
    assert seen["headers"]["x-team"] == "red" and "api-version=2025" in seen["url"]


PLUGIN = textwrap.dedent('''
    from roundtable.providers.base import ChatResponse, Provider, Usage

    class EchoProvider(Provider):
        def __init__(self, name, prefix="echo: "):
            self.name, self.prefix = name, prefix

        def list_models(self):
            return ["v1"]

        def chat(self, model, system, messages, tools=None, max_tokens=16000, options=None):
            return ChatResponse(text=self.prefix + messages[-1]["content"], usage=Usage(1, 1))
''')


def test_plugin_provider(harness):
    (harness.parent / "plugins").mkdir()
    (harness.parent / "plugins" / "echo.py").write_text(PLUGIN, encoding="utf-8")
    manage.add_provider(harness, "plugin", pid="echo", **{"class": "echo.py:EchoProvider", "options": {"prefix": "> "}})
    cfg = load_config(str(harness))
    p = cfg.provider("echo")
    assert isinstance(p, Provider) and p.chat("v1", "", [{"role": "user", "content": "hi"}]).text == "> hi"
    assert manage.test_provider(cfg, "echo") == {"ok": True, "models": 1, "sample": ["v1"]}
    (harness.parent / "plugins" / "bad.py").write_text("class Nope: pass\n", encoding="utf-8")
    manage.add_provider(harness, "plugin", pid="bad", **{"class": "bad.py:Nope"})
    with pytest.raises(ProviderError, match="must subclass"):
        load_config(str(harness)).provider("bad")
    assert manage.test_provider(load_config(str(harness)), "missing")["ok"] is False


def test_live_style_test_reports_failures_cleanly(harness, monkeypatch):
    manage.add_provider(harness, "custom", pid="offline", base_url="http://127.0.0.1:9/v1")
    r = manage.test_provider(load_config(str(harness)), "offline")
    assert r["ok"] is False and "connection" in r["error"].lower()


def test_ui_endpoints(harness, tmp_path):
    from roundtable.ui.server import UIApp

    hub = tmp_path / "hub.yaml"
    hub.write_text(yaml.safe_dump({"storage": {"type": "file", "path": str(tmp_path / "hd")},
                                   "agents": {"me": {}}, "rules": []}), encoding="utf-8")
    app = UIApp(str(hub), str(harness), agent="me")
    data = app.dispatch("GET", "/api/providers", {}, {})
    assert "openrouter" in data["presets"] and [p["id"] for p in data["providers"]] == ["deepseek"]
    r = app.dispatch("POST", "/api/providers", {}, {"action": "add", "preset": "custom", "id": "local",
                                                    "base_url": "http://127.0.0.1:9/v1"})
    assert r["added"]["id"] == "local" and r["test"]["ok"] is False
    app.dispatch("POST", "/api/assign", {}, {"role": "coder", "models": "local/x, deepseek/deepseek-flash"})
    roles = {r["name"]: r for r in app.dispatch("GET", "/api/providers", {}, {})["roles"]}
    assert roles["coder"]["models"] == ["local/x", "deepseek/deepseek-flash"]
    with pytest.raises(ValueError):
        app.dispatch("POST", "/api/providers", {}, {"action": "remove", "id": "local"})  # in use
    assert json.dumps(data)  # serialisable


def test_service_error_message_is_kept():
    from roundtable.providers.openai_compat import _said

    class E:
        body = {"error": {"message": "This model is billed from your credit balance."}}
        message = "Error code: 402"

    class F:
        body = None
        message = "Error code: 500"

    assert _said(E()) == "This model is billed from your credit balance."
    assert _said(F()) == "Error code: 500"


def test_openrouter_balance_and_reported_cost():
    from roundtable.providers.balance import balance_url, parse
    from roundtable.providers.openai_compat import _reported_cost

    assert balance_url({"base_url": "https://openrouter.ai/api/v1"}) == "https://openrouter.ai/api/v1/credits"
    assert parse({"data": {"total_credits": 10, "total_usage": 2.5}}) == {"amount": 7.5, "currency": "USD"}

    class U:
        cost = 0.00026
        model_extra = {}

    class V:
        model_extra = {"cost": "0.01"}

    assert _reported_cost(U()) == 0.00026 and _reported_cost(V()) == 0.01 and _reported_cost(None) is None


def test_claude_through_a_gateway_gets_cache_marks():
    from roundtable.providers.openai_compat import _mark_cache, _needs_cache_marks

    assert _needs_cache_marks("anthropic/claude-sonnet-5.5") and _needs_cache_marks("Claude Opus 5.5")
    assert not _needs_cache_marks("deepseek-v4-flash") and not _needs_cache_marks("openai/gpt-6.1-terra")
    msgs = [{"role": "system", "content": "rules"}, {"role": "user", "content": "task"},
            {"role": "assistant", "content": "", "tool_calls": []}, {"role": "tool", "tool_call_id": "1", "content": "out"}]
    marked = _mark_cache(msgs)
    assert marked[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert marked[3]["content"][0]["text"] == "out" and marked[1]["content"] == "task"
    assert msgs[0]["content"] == "rules"  # the original is untouched


def test_openrouter_asks_for_the_cheapest_route_unless_told_otherwise():
    from roundtable.providers.openai_compat import OpenAICompatProvider

    calls = []

    class Fake:
        class chat:
            class completions:
                @staticmethod
                def create(**params):
                    calls.append(params)
                    from types import SimpleNamespace as N
                    return N(choices=[N(message=N(content="ok", tool_calls=None, model_dump=lambda **k: {}), finish_reason="stop")],
                             usage=None, provider="Wafer", model_extra={}, model="z-ai/glm-5.3")

    for routing, want in ((None, "price"), ("throughput", "throughput"), ("none", None)):
        p = OpenAICompatProvider("openrouter", api_key_env=None, base_url="https://openrouter.ai/api/v1", routing=routing)
        p.client = Fake()
        p.chat("z-ai/glm-5.3", "sys", [{"role": "user", "content": "hi"}])
        sent = calls[-1]["extra_body"].get("provider")
        assert (sent or {}).get("sort") == want and p.last_route == "Wafer"
    plain = OpenAICompatProvider("deepseek", api_key_env=None, base_url="https://api.deepseek.com")
    assert plain.routing is None


def test_deepseek_is_half_price_off_peak():
    from datetime import datetime, timezone

    from roundtable.harness.config import DEEPSEEK_PEAK, in_peak, next_offpeak, price_now

    p = {"input": 0.44, "output": 1.32, "offpeak": {"input": 0.22, "output": 0.66}, "peak_utc": DEEPSEEK_PEAK}
    peak = datetime(2026, 11, 26, 7, 30, tzinfo=timezone.utc)
    quiet = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
    assert in_peak(DEEPSEEK_PEAK, peak) and not in_peak(DEEPSEEK_PEAK, quiet)
    assert price_now(p, peak)["input"] == 0.44 and price_now(p, quiet)["input"] == 0.22
    assert next_offpeak(DEEPSEEK_PEAK, peak).strftime("%H:%M") == "10:00"
    assert next_offpeak(DEEPSEEK_PEAK, quiet) == quiet
