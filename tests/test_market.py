"""Wave 7, d4-tools: the list of plug-ins and skills – the shipped list, refresh (only shown), install from a
pinned commit with the manifest checked against the entry, updates, taking away (moved aside), and the API."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from roundtable import skills
from roundtable.plugins import market
from roundtable.plugins.manage import NeedsOk

from .test_harness import RAW
from .test_plugins import write_plugin

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def home() -> Path:
    return Path(os.environ["ROUNDTABLE_HOME"])


def git(repo, *args):
    out = subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                          *args], capture_output=True, text=True, check=True)
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A made-up plug-in repository: commit one asks for nothing, commit two asks for the internet."""
    r = tmp_path / "made-up-plugin"
    write_plugin(r / "plugin", pid="hello-tools", module="hello_tools_mk", permissions=())
    git(tmp_path, "init", "-q", str(r))
    git(r, "add", "-A")
    git(r, "commit", "-qm", "one")
    first = git(r, "rev-parse", "HEAD")
    write_plugin(r / "plugin", pid="hello-tools", module="hello_tools_mk", permissions=("network",))
    git(r, "commit", "-qam", "two")
    return {"path": r, "first": first, "second": git(r, "rev-parse", "HEAD")}


@pytest.fixture
def harness(tmp_path):
    p = tmp_path / "lab" / "harness.yaml"
    p.parent.mkdir()
    p.write_text(yaml.safe_dump(RAW), encoding="utf-8")
    return p


def listing(repo, commit, perms=(), version="1.0.0", pid="hello-tools"):
    return market.parse({"version": 1, "updated": "2026-11-27", "entries": [
        {"id": pid, "name": "Hello tools", "blurb": "Adds a hello tool.", "kind": "plugin", "source": str(repo["path"]),
         "commit": commit, "path": "plugin", "permissions": list(perms), "version": version, "checked": "2026-11-27"}]})


def test_the_shipped_list_is_honest_about_its_size():
    cat = market.load()
    assert cat["from"] == "shipped" and len(cat["entries"]) == 10
    assert {e["kind"] for e in cat["entries"]} == {"skill"}
    assert {e["id"] for e in cat["entries"]} == {s.id for s in skills.list_skills() if s.source == "builtin"}
    v = market.view()
    assert "10 skills and 0 plug-ins" in v["words"] and "small" in v["words"]


def test_install_fetches_the_pinned_commit_and_asks_first(repo, harness):
    cat = listing(repo, repo["first"])
    asked = []
    with pytest.raises(NeedsOk):
        market.install("hello-tools", lambda m: asked.append(m.permissions) or False, harness_path=harness, catalogue=cat)
    assert asked == [[]]
    got = market.install("hello-tools", lambda m: True, harness_path=harness, catalogue=cat)
    assert got["id"] == "hello-tools"
    spec = yaml.safe_load((harness.parent / "custom.yaml").read_text())["plugins"]["hello-tools"]
    assert spec["permissions"] == [] and spec["source"] == f"{repo['path']}@{repo['first']}"
    assert not (Path(spec["path"]) / ".git").exists()


def test_an_entry_whose_manifest_asks_for_more_than_the_list_says_is_refused(repo, harness):
    cat = listing(repo, repo["second"], perms=())
    with pytest.raises(market.MarketError, match="asks for more than the list says"):
        market.install("hello-tools", lambda m: True, harness_path=harness, catalogue=cat)
    assert not (harness.parent / "custom.yaml").exists()
    ok = listing(repo, repo["second"], perms=("network",))
    assert market.install("hello-tools", lambda m: "network" in m.permissions, harness_path=harness, catalogue=ok)


def test_an_entry_that_holds_another_plugin_is_refused(repo, harness):
    cat = listing(repo, repo["first"], pid="other-tools")
    with pytest.raises(market.MarketError, match="not 'other-tools'"):
        market.install("other-tools", lambda m: True, harness_path=harness, catalogue=cat)


def test_the_list_must_name_an_exact_commit_and_a_safe_folder(repo):
    with pytest.raises(market.MarketError, match="exact commit"):
        listing(repo, "main")
    with pytest.raises(market.MarketError, match="inside the repository"):
        market.parse({"entries": [{"id": "x1", "kind": "plugin", "source": "https://example.invalid/r.git",
                                   "commit": "a" * 40, "path": "../up"}]})


def test_updates_and_taking_away_moves_the_code_aside(repo, harness):
    market.install("hello-tools", lambda m: True, harness_path=harness, catalogue=listing(repo, repo["first"]))
    newer = listing(repo, repo["first"], version="1.1.0")
    assert market.updates(harness, newer) == [{"id": "hello-tools", "name": "Hello tools", "have": "1.0.0",
                                               "newer": "1.1.0"}]
    assert market.updates(harness, listing(repo, repo["first"])) == []
    out = market.remove("hello-tools", harness_path=harness)
    assert (Path(out["moved_to"]) / "hello_tools_mk.py").is_file()
    assert "hello-tools" not in (yaml.safe_load((harness.parent / "custom.yaml").read_text()).get("plugins") or {})


def test_refresh_reads_one_fixed_address_and_is_only_shown(harness):
    urls = []
    newer = {"version": 1, "updated": "2026-12-01", "entries": [
        {"id": "pytest-basics", "name": "Pytest basics", "kind": "skill", "source": "builtin", "version": "1.0.0"}]}
    got = market.refresh(fetch=lambda u: urls.append(u) or json.dumps(newer).encode())
    assert urls == [market.REFRESH_URL] and got["from"] == "refreshed" and got["updated"] == "2026-12-01"
    assert not (harness.parent / "custom.yaml").exists()  # nothing installed because of it
    with pytest.raises(market.MarketError, match="couldn't be read"):
        market.refresh(fetch=lambda u: b"not json")
    assert market.load()["updated"] == "2026-12-01"  # a bad refresh leaves the good one


def test_a_skill_from_the_list_is_added_only_after_its_text_is_read(tmp_path):
    r = tmp_path / "skills-repo"
    (r / "tidy-shaders").mkdir(parents=True)
    (r / "tidy-shaders" / "SKILL.md").write_text(
        "---\nname: Tidy shaders\nwhen: Writing shaders.\ntags: [shaders]\n---\nKeep uniforms few and named for what "
        "they mean; comment every magic number.\n", encoding="utf-8")
    git(tmp_path, "init", "-q", str(r))
    git(r, "add", "-A")
    git(r, "commit", "-qm", "one")
    cat = market.parse({"entries": [{"id": "tidy-shaders", "name": "Tidy shaders", "kind": "skill", "source": str(r),
                                     "commit": git(r, "rev-parse", "HEAD"), "path": "tidy-shaders"}]})
    seen = []
    with pytest.raises(skills.SkillError):
        market.install("tidy-shaders", lambda s: seen.append(s.text) or False, catalogue=cat)
    assert "Keep uniforms few" in seen[0]
    assert market.install("tidy-shaders", lambda s: True, catalogue=cat)["added"]
    assert skills.get("tidy-shaders").source == "own"
    skills.switch("pytest-basics", False)
    assert market.install("pytest-basics", lambda s: True)["enabled"] is True


def test_the_api_lists_installs_after_a_yes_and_adds_a_skill_only_with_its_text_shown(repo, harness, monkeypatch):
    from roundtable.ui import marketapi

    class App:
        harness_config_path = str(harness)

    monkeypatch.setattr(market, "load", lambda home=None: {**listing(repo, repo["first"]), "from": "shipped",
                                                           "refreshed_at": ""})
    r = marketapi.routes(App())
    got = r[("GET", "/api/market")]({})
    assert got["plugins"][0]["permission_words"] == ["Nothing special"] and not got["plugins"][0]["installed"]
    post = r[("POST", "/api/market")]
    first = post({"action": "install", "id": "hello-tools"})
    assert first["ok"] is False and first["needs_ok"]["id"] == "hello-tools"
    assert post({"action": "install", "id": "hello-tools", "confirmed": []})["ok"]
    assert r[("GET", "/api/market")]({})["plugins"][0]["installed"]
    text = "---\nname: Tidy shaders\nwhen: Writing shaders.\ntags: [shaders]\n---\nKeep uniforms few and named well; comment every magic number.\n"
    shown = post({"action": "skill_add", "text": text, "name": "tidy-shaders.md"})
    assert shown["ok"] is False and shown["needs_ok"]["skill"]["text"] == text
    assert post({"action": "skill_add", "text": text + "and more", "name": "x.md",
                 "digest": shown["needs_ok"]["digest"]})["ok"] is False  # the text changed: shown again
    added = post({"action": "skill_add", "text": text, "name": "tidy-shaders.md", "digest": shown["needs_ok"]["digest"]})
    assert added["ok"] and added["added"]["id"] == "tidy-shaders"
    assert post({"action": "skill_switch", "id": "tidy-shaders", "on": False})["enabled"] is False
    assert Path(post({"action": "skill_remove", "id": "tidy-shaders"})["moved_to"]).is_dir()
    from roundtable.ui.server import ApiError

    with pytest.raises(ApiError, match="web link"):
        post({"action": "skill_add", "file": "https://example.invalid/SKILL.md"})


def test_the_market_api_joins_the_app_through_feature_apis(monkeypatch, harness):
    from roundtable.ui import server

    if "marketapi" not in server.FEATURE_APIS:
        monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "marketapi"))

    class App:
        harness_config_path = str(harness)

    got = server._feature_routes(App())
    assert {("GET", "/api/market"), ("POST", "/api/market")} <= set(got)
    assert len(got[("GET", "/api/market")]({})["skills"]) == 10
