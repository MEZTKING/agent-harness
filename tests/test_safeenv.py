"""The owner's keys never reach a process an AI worker can cause (harness/safeenv.py, core/secrets.py).

Made-up keys only; no network.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import time
from pathlib import Path

import pytest

from roundtable.core import secrets as vault
from roundtable.harness import checks, godot
from roundtable.harness.safeenv import clean_env, is_secret_name
from roundtable.harness.tools import Workspace

SRC = Path(__file__).resolve().parent.parent / "src" / "roundtable"
FAKE_MCP = str(Path(__file__).parent / "fixtures" / "fake_mcp_server.py")

KEY = "sk-made-up-0123456789abcdef"
HUB = "ghp_madeUpHubToken0123456789"
ODD = "a-value-that-is-a-stored-secret"

DUMP = "import json, os, sys\nsys.stdout.write(json.dumps(dict(os.environ)))\n"


@pytest.fixture
def owner_secrets(monkeypatch):
    """What a real start-up leaves: keys in the vault, the hub token as git settings, plus the kind of
    variables a person might have set themselves."""
    from roundtable import onphone

    vault.put("DEEPSEEK_API_KEY", KEY)
    vault.put("ROUNDTABLE_HUB_TOKEN", HUB)
    vault.set_git_env(onphone.git_auth_env("https://github.example.test/me/hub", HUB))
    monkeypatch.setenv("MY_SERVICE_TOKEN", "tok-own-environment-123")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fromTheEnvironment123")
    monkeypatch.setenv("GH_TOKEN", "ghp_fromTheEnvironment456")
    monkeypatch.setenv("SOME_DB_PASSWORD", "hunter2-hunter2")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "http.extraHeader")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "Authorization: Basic c2VjcmV0")
    monkeypatch.setenv("GIT_ASKPASS", "/made/up/askpass")
    monkeypatch.setenv("INNOCENT_NAME", ODD)
    vault.put("CUSTOM_THING", ODD)  # a stored secret, so any variable holding it goes too
    monkeypatch.setenv("RT_HARMLESS_SETTING", "kept")
    return [KEY, HUB, "tok-own-environment-123", "ghp_fromTheEnvironment123", "ghp_fromTheEnvironment456",
            "hunter2-hunter2", "c2VjcmV0", ODD]


def assert_clean(env: dict, leaked: list[str]) -> None:
    text = json.dumps(env)
    for value in leaked:
        assert value not in text, f"a secret reached the process: {value[:6]}..."
    for name in ("DEEPSEEK_API_KEY", "ROUNDTABLE_HUB_TOKEN", "MY_SERVICE_TOKEN", "GITHUB_TOKEN", "GH_TOKEN",
                 "SOME_DB_PASSWORD", "GIT_ASKPASS", "INNOCENT_NAME"):
        assert name not in env
    # git: no prompt, and the only git setting is an empty credential helper (no saved login)
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_CONFIG_COUNT"] == "1" and env["GIT_CONFIG_KEY_0"] == "credential.helper"
    assert env["GIT_CONFIG_VALUE_0"] == ""
    assert env["RT_HARMLESS_SETTING"] == "kept"
    assert "PATH" in {k.upper() for k in env}


# -- clean_env itself -----------------------------------------------------------------------------------
def test_clean_env_drops_secrets_by_name_and_by_value(owner_secrets):
    env = clean_env()
    assert_clean(env, owner_secrets)
    if os.name == "nt":  # Windows' own tools keep what they need
        assert {"SYSTEMROOT", "PATHEXT", "COMSPEC"} <= {k.upper() for k in env}


def test_extra_settings_are_added_on_top(owner_secrets):
    env = clean_env({"QT_QPA_PLATFORM": "offscreen"})
    assert env["QT_QPA_PLATFORM"] == "offscreen"
    assert_clean(env, owner_secrets)


def test_names_that_look_secret():
    for name in ("OPENAI_API_KEY", "x_token", "Client_Secret", "DB_PASSWORD", "AZURE_CREDENTIALS", "GIT_CONFIG_KEY_3",
                 "GH_TOKEN", "SSH_ASKPASS", "ROUNDTABLE_LAUNCH_TOKEN", "ANTHROPIC_API_KEY"):
        assert is_secret_name(name), name
    for name in ("PATH", "SYSTEMROOT", "PATHEXT", "HOME", "LANG", "PYTHONIOENCODING", "KEYBOARD_LAYOUT"):
        assert not is_secret_name(name), name


def test_a_providers_key_name_is_secret_once_the_config_is_read():
    from roundtable.harness.config import parse_config

    parse_config({"providers": {"x": {"type": "openai_compat", "api_key_env": "ZZ_ODDLY_NAMED"}},
                  "roles": {"orchestrator": {"model": "x/m"}, "reviewer": {"model": "x/m"}}})
    assert "ZZ_ODDLY_NAMED" in vault.names()
    assert "ZZ_ODDLY_NAMED" not in clean_env(base={"ZZ_ODDLY_NAMED": "v", "PATH": "/bin"})


# -- every process a worker can cause -------------------------------------------------------------------
def _script(tmp_path: Path) -> Path:
    p = tmp_path / "dump_env.py"
    p.write_text(DUMP, encoding="utf-8")
    return p


def test_run_command_gives_the_worker_no_keys(tmp_path, owner_secrets):
    ws = Workspace(tmp_path / "proj")
    script = _script(tmp_path)
    out = ws.run_command({"command": f'"{sys.executable}" "{script}"'})
    body = out.split("--- stdout ---\n", 1)[1].split("\n--- stderr ---", 1)[0]
    assert_clean(json.loads(body), owner_secrets)


def test_project_checks_get_no_keys_but_their_own_settings(tmp_path, owner_secrets):
    script = _script(tmp_path)
    res = checks.run(tmp_path, f'"{sys.executable}" "{script}"', env={"QT_QPA_PLATFORM": "offscreen"}, timeout=60)
    env = json.loads(res["output"])
    assert env["QT_QPA_PLATFORM"] == "offscreen" and env["PYTHONIOENCODING"] == "utf-8"
    assert_clean(env, owner_secrets)


def test_godot_runs_get_no_keys(tmp_path, owner_secrets):
    code, output = godot.run([sys.executable, str(_script(tmp_path))], timeout=60)
    assert code == 0
    assert_clean(json.loads(output), owner_secrets)


def test_an_mcp_server_gets_no_keys_but_its_own_env(tmp_path, owner_secrets):
    pytest.importorskip("mcp")
    from roundtable.harness.mcp_tools import MCPPool

    env_log = tmp_path / "env.json"
    pool = MCPPool({"editor": {"command": sys.executable, "args": [FAKE_MCP],
                               "env": {"FAKE_MCP_ENV_LOG": str(env_log), "EDITOR_MODE": "test"}}}, lambda k, d: None)
    try:
        assert pool.tools_for(["editor"])
        end = time.monotonic() + 15
        while not env_log.exists() and time.monotonic() < end:
            time.sleep(0.05)
        env = json.loads(env_log.read_text(encoding="utf-8"))
    finally:
        pool.close()
    assert env["EDITOR_MODE"] == "test"
    text = json.dumps(env)
    for value in owner_secrets:
        assert value not in text
    assert "DEEPSEEK_API_KEY" not in env and "GITHUB_TOKEN" not in env


# -- the vault ---------------------------------------------------------------------------------------
def test_vault_first_then_the_environment(monkeypatch):
    monkeypatch.setenv("RT_TEST_ONLY_KEY", "from-env")
    assert vault.get("RT_TEST_ONLY_KEY") == "from-env"  # the command line and CI keep working
    vault.put("RT_TEST_ONLY_KEY", "from-vault")
    assert vault.get("RT_TEST_ONLY_KEY") == "from-vault" and os.environ["RT_TEST_ONLY_KEY"] == "from-env"
    vault.put("RT_TEST_ONLY_KEY", "")
    assert vault.get("RT_TEST_ONLY_KEY") == "from-env" and "RT_TEST_ONLY_KEY" in vault.names()


def test_providers_read_their_key_from_the_vault(monkeypatch):
    monkeypatch.delenv("RT_TEST_PROVIDER_KEY", raising=False)
    vault.put("RT_TEST_PROVIDER_KEY", KEY)
    assert "RT_TEST_PROVIDER_KEY" not in os.environ
    from roundtable.providers import balance
    from roundtable.providers.openai_compat import OpenAICompatProvider, _expand

    p = OpenAICompatProvider("x", api_key_env="RT_TEST_PROVIDER_KEY", base_url="https://llm.example.test/v1")
    assert p.client.api_key == KEY
    assert _expand("Bearer ${RT_TEST_PROVIDER_KEY}") == f"Bearer {KEY}"
    pytest.importorskip("anthropic")
    from roundtable.providers.anthropic_provider import AnthropicProvider

    assert AnthropicProvider(api_key_env="RT_TEST_PROVIDER_KEY").client.api_key == KEY
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"balance_infos": [{"currency": "USD", "total_balance": "1.5"}]}'

    def fake_urlopen(req, timeout=0):
        seen["auth"] = req.headers.get("Authorization")
        return Resp()

    monkeypatch.setattr(balance.urllib.request, "urlopen", fake_urlopen)
    balance.read_balance({"type": "openai_compat", "base_url": "https://api.deepseek.com",
                          "api_key_env": "RT_TEST_PROVIDER_KEY"})
    assert seen["auth"] == f"Bearer {KEY}"


def test_the_phones_hub_token_stays_out_of_the_environment(tmp_path):
    from roundtable import onphone
    from roundtable.desktop import KeyStore, Paths

    paths = Paths(tmp_path / "h")
    keys = KeyStore(paths, file_only=True)
    keys.set(onphone.HUB_TOKEN, HUB)
    paths.save_settings({"hub_url": "https://github.example.test/me/hub"})
    assert onphone.use_hub_token(paths, keys)
    header = vault.git_env()["GIT_CONFIG_VALUE_0"]
    assert header not in json.dumps(dict(os.environ)) and HUB not in json.dumps(dict(os.environ))
    assert vault.git_env()["GIT_CONFIG_KEY_0"].startswith("http.https://github.example.test/")
    assert header not in json.dumps(clean_env())


def test_the_hubs_own_git_gets_its_login(tmp_path, monkeypatch):
    from roundtable.core import store

    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)

        class R:
            returncode, stdout, stderr = 0, "", ""
        return R()

    vault.set_git_env({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.extraHeader", "GIT_CONFIG_VALUE_0": "x"})
    monkeypatch.setattr(store.subprocess, "run", fake_run)
    cls = next(c for c in vars(store).values() if isinstance(c, type) and hasattr(c, "_run") and hasattr(c, "_git"))
    cls._run(["git", "status"], cwd=tmp_path)
    assert seen["env"]["GIT_CONFIG_VALUE_0"] == "x"


def test_desktop_start_up_loads_saved_keys_into_the_vault_and_shows_them_set(tmp_path, monkeypatch):
    from roundtable.desktop import KeyStore, Paths, ensure_configs
    from roundtable.routing import _key_state

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    paths = Paths(tmp_path / "home")
    ensure_configs(paths)
    KeyStore(paths, file_only=True).set("DEEPSEEK_API_KEY", KEY)
    vault.clear()  # a restart
    assert "DEEPSEEK_API_KEY" in KeyStore(paths, file_only=True).load_into_env()
    assert "DEEPSEEK_API_KEY" not in os.environ
    assert _key_state({"deepseek": {"api_key_env": "DEEPSEEK_API_KEY"}})["deepseek"]["key_set"]


# -- the guard: no process a model can cause without a chosen environment -------------------------------
SPAWNERS = {"run", "Popen", "call", "check_call", "check_output"}
# Roundtable's own commands, never anything a worker wrote: stopping a process tree on Windows
ALLOWED = {("harness/checks.py", "_kill"), ("harness/godot.py", "_kill")}
MODEL_REACHABLE = [*sorted((SRC / "harness").glob("*.py")), SRC / "sync.py", SRC / "improve" / "evaluate.py"]


def _calls_without_env(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    rel = path.relative_to(SRC).as_posix()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"
                    and node.func.attr in SPAWNERS and (rel, fn.name) not in ALLOWED
                    and not any(k.arg == "env" for k in node.keywords)):
                yield f"{rel}:{node.lineno} ({fn.name})"
        if fn.name == "_transport":  # the MCP server's environment
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "StdioServerParameters":
                    env = next((k.value for k in node.keywords if k.arg == "env"), None)
                    if not (isinstance(env, ast.Call) and getattr(env.func, "id", "") == "clean_env"):
                        yield f"{rel}:{node.lineno} (MCP server without clean_env)"


def test_every_process_a_model_can_cause_has_a_chosen_environment():
    found = [hit for path in MODEL_REACHABLE for hit in _calls_without_env(path)]
    assert not found, "these start a process with the owner's whole environment: " + ", ".join(found)
