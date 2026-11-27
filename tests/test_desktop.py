import json
import os

from roundtable.core import secrets as vault

import pytest
import yaml

from roundtable import desktop, updater
from roundtable.desktop import KeyStore, Paths, ensure_configs, start_server
from roundtable.updater import InstallInfo, UpdateError, _parse_version, check, latest_release


class MemoryKeyring:
    def __init__(self):
        self.data = {}

    def get_password(self, service, name):
        return self.data.get((service, name))

    def set_password(self, service, name, value):
        self.data[(service, name)] = value

    def delete_password(self, service, name):
        self.data.pop((service, name), None)


@pytest.fixture
def paths(tmp_path):
    return Paths(tmp_path / "home")


def test_keystore_secure_backend(paths, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    kr = MemoryKeyring()
    ks = KeyStore(paths, backend=kr)
    assert ks.secure
    ks.set("DEEPSEEK_API_KEY", "  sk-123 ")
    assert kr.data[(desktop.KEYRING_SERVICE, "DEEPSEEK_API_KEY")] == "sk-123"
    # in Roundtable's in-memory vault, never os.environ (workers' commands would inherit it)
    assert vault.get("DEEPSEEK_API_KEY") == "sk-123" and "DEEPSEEK_API_KEY" not in os.environ
    assert not (paths.config / "keys.json").exists()  # never written to a file
    vault.clear()
    assert KeyStore(paths, backend=kr).load_into_env() == ["DEEPSEEK_API_KEY"]
    assert vault.get("DEEPSEEK_API_KEY") == "sk-123" and "DEEPSEEK_API_KEY" not in os.environ
    ks.set("DEEPSEEK_API_KEY", "")
    assert ks.get("DEEPSEEK_API_KEY") is None and vault.get("DEEPSEEK_API_KEY") is None


def test_keystore_file_fallback_and_env_wins(paths, monkeypatch):
    ks = KeyStore(paths, backend=None)
    ks.backend = None
    assert not ks.secure
    ks.set("OPENAI_API_KEY", "sk-file")
    assert json.loads((paths.config / "keys.json").read_text(encoding="utf-8")) == {"OPENAI_API_KEY": "sk-file"}
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    vault.clear()  # a restart
    assert KeyStore(paths, backend=None).load_into_env() == []  # an explicit env var is not overridden
    assert vault.get("OPENAI_API_KEY") == "from-env"


def test_first_run_creates_working_configs(paths):
    ensure_configs(paths)
    hub = yaml.safe_load(paths.hub_yaml.read_text(encoding="utf-8"))
    assert hub["storage"]["type"] == "file" and "me" in hub["agents"]
    assert "roles:" in paths.harness_yaml.read_text(encoding="utf-8")
    before = paths.harness_yaml.read_text(encoding="utf-8")
    paths.harness_yaml.write_text(before + "\n# mine\n", encoding="utf-8")
    ensure_configs(paths)  # never overwrites the user's files
    assert paths.harness_yaml.read_text(encoding="utf-8").endswith("# mine\n")


def test_connect_hub_validates(paths, monkeypatch):
    ensure_configs(paths)
    with pytest.raises(ValueError):
        desktop.connect_github_hub(paths, "not a url")
    monkeypatch.setattr(desktop, "git_version", lambda: None)
    with pytest.raises(RuntimeError, match="Git for Windows"):
        desktop.connect_github_hub(paths, "https://github.com/x/y")


def test_connect_hub_clones_and_keeps_repo_agents(paths, tmp_path):
    import subprocess

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(remote), str(seed)], check=True, capture_output=True)
    (seed / "hub.yaml").write_text(yaml.safe_dump({"agents": {"me": {}, "mygame": {"description": "a game"}},
                                                   "rules": [{"from": "*", "to": "*", "allow": ["read_card"]}]}), encoding="utf-8")
    g = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run(g + ["add", "."], cwd=seed, check=True)
    subprocess.run(g + ["commit", "-qm", "hub"], cwd=seed, check=True)
    subprocess.run(["git", "push", "-q", "origin", "HEAD:main"], cwd=seed, check=True, capture_output=True)
    ensure_configs(paths)
    # connect_github_hub only accepts https/git@ URLs, so pre-clone the local remote where it expects the clone
    subprocess.run(["git", "clone", "-q", str(remote), str(paths.home / "hub-repo")], check=True, capture_output=True)
    desktop.connect_github_hub(paths, "https://github.com/you/agent-hub-data", log=lambda *_: None)
    cfg = yaml.safe_load(paths.hub_yaml.read_text(encoding="utf-8"))
    assert cfg["storage"]["type"] == "git" and cfg["storage"]["path"].endswith("hub-repo")
    assert "mygame" in cfg["agents"]


def _api(base, path, body=None):
    import urllib.request

    req = urllib.request.Request(base + path, method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "X-Agent-Hub": "1"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_app_server_setup_flow(paths, monkeypatch, tmp_path):
    import urllib.error  # noqa: F401  (used in _api)

    for k in desktop.KNOWN_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(desktop.Path, "home", lambda: tmp_path / "userhome")
    ensure_configs(paths)
    ks = KeyStore(paths, backend=MemoryKeyring())
    httpd, app = start_server(paths, ks)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        status, st = _api(base, "/api/setup")
        assert status == 200 and st["desktop"] and not st["setup_done"] and st["secure_keys"]
        assert {k["name"] for k in st["keys"]} >= set(desktop.KNOWN_KEYS)
        status, st = _api(base, "/api/setup/keys", {"keys": {"DEEPSEEK_API_KEY": "sk-x"}})
        assert next(k for k in st["keys"] if k["name"] == "DEEPSEEK_API_KEY")["set"]
        assert _api(base, "/api/setup/keys", {"keys": {"bad name; rm": "x"}})[0] == 400
        projects = tmp_path / "MyProjects"
        status, st = _api(base, "/api/setup/done", {"projects_dir": str(projects), "agent": "me"})
        assert st["setup_done"] and projects.is_dir()
        assert paths.load_settings()["setup_done"]
        # settings: config editing with validation and backup
        status, cfg = _api(base, "/api/config?which=harness")
        assert status == 200 and "roles:" in cfg["text"]
        status, res = _api(base, "/api/config", {"which": "harness", "text": "roles: [broken"})
        assert status == 400 and "not saved" in res["error"]
        status, res = _api(base, "/api/config", {"which": "harness", "text": cfg["text"] + "\n# edited\n"})
        assert status == 200 and paths.harness_yaml.read_text(encoding="utf-8").endswith("# edited\n")
        assert (paths.config / "harness.yaml.bak").exists()
        status, res = _api(base, "/api/setup/hub", {"mode": "local"})
        assert res["hub"]["mode"] == "file"
    finally:
        httpd.shutdown()


def test_self_test_passes(paths, monkeypatch):
    monkeypatch.setattr(desktop, "KeyStore", lambda p: KeyStore(p, backend=MemoryKeyring()))
    assert desktop.self_test(paths) == 0
    assert json.loads((paths.logs / "self-test.json").read_text(encoding="utf-8"))["ok"]


def test_release_updater_for_installed_app(monkeypatch):
    assert _parse_version("v0.10.0") > _parse_version("0.9.9") > _parse_version("0.3.0")
    rel = {"tag_name": "v0.4.0", "html_url": "https://github.com/x/releases/v0.4.0", "body": "- new thing\n- fix",
           "assets": [{"name": "RoundtableHold-Setup-0.4.0.exe", "browser_download_url": "https://dl/x.exe"}]}
    monkeypatch.setattr(updater, "latest_release", lambda fetch=None: latest_release(lambda url: rel))
    st = check(info=InstallInfo("app", version="0.3.0"))
    assert st.available and "0.4.0" in st.message and st.install.path == "https://dl/x.exe"
    assert st.changes == ["- new thing", "- fix"]
    assert not check(info=InstallInfo("app", version="0.4.0")).available
    monkeypatch.setattr(updater, "latest_release",
                        lambda fetch=None: latest_release(lambda url: {**rel, "assets": []}))
    assert not check(info=InstallInfo("app", version="0.3.0")).available  # no installer attached yet

    def offline(url):
        raise OSError("no network")

    with pytest.raises(UpdateError):
        latest_release(offline)
