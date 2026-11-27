"""Roundtable Hold becomes Darkness Harness (1.0.0) and nobody loses anything.

Data folders are picked legacy first (never moved), keys are read from the old place and written to the
new, the updater finds the installer under either name, and the names machines read stay exactly as
they were. Made-up folders and keys only.
"""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

from roundtable import brand, desktop, remote, updater
from roundtable.desktop import KeyStore, Paths, pick_home
from roundtable.core import secrets as vault

ROOT = Path(__file__).resolve().parents[1]


class MemoryKeyring:
    def __init__(self):
        self.data = {}

    def get_password(self, service, name):
        return self.data.get((service, name))

    def set_password(self, service, name, value):
        self.data[(service, name)] = value

    def delete_password(self, service, name):
        self.data.pop((service, name), None)


# -- folders: legacy first, never moved ------------------------------------------------------------------
def test_pick_home_old_only_new_only_both_neither(tmp_path):
    new, old = tmp_path / "DarknessHarness", tmp_path / "RoundtableHold"
    assert pick_home(new, old) == new  # neither: the new name (made later)
    old.mkdir()
    (old / "config").mkdir()
    assert pick_home(new, old) == old  # an installed Roundtable Hold keeps its folder
    new.mkdir()
    assert pick_home(new, old) == old  # an empty new folder left behind doesn't count
    (new / "config").mkdir()
    assert pick_home(new, old) == new  # both in use: the new one
    import shutil
    shutil.rmtree(old)
    assert pick_home(new, old) == new  # new only
    assert (new / "config").is_dir()


def _home(monkeypatch, platform, tmp_path):
    monkeypatch.delenv("ROUNDTABLE_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return desktop.app_home()


def test_app_home_on_windows(monkeypatch, tmp_path):
    assert _home(monkeypatch, "win32", tmp_path) == tmp_path / "Roaming" / "DarknessHarness"
    old = tmp_path / "Roaming" / "RoundtableHold"
    (old / "hub-data").mkdir(parents=True)
    (old / "marker.txt").write_text("mine", encoding="utf-8")
    assert _home(monkeypatch, "win32", tmp_path) == old
    # nothing was moved or copied
    assert (old / "marker.txt").read_text(encoding="utf-8") == "mine"
    assert not (tmp_path / "Roaming" / "DarknessHarness").exists()


def test_app_home_on_linux(monkeypatch, tmp_path):
    assert _home(monkeypatch, "linux", tmp_path) == tmp_path / "config" / "darkness-harness"
    (tmp_path / "config" / "roundtable-hold").mkdir(parents=True)
    assert _home(monkeypatch, "linux", tmp_path) == tmp_path / "config" / "roundtable-hold"


def test_roundtable_home_still_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("ROUNDTABLE_HOME", str(tmp_path / "chosen"))
    (tmp_path / "Roaming" / "RoundtableHold").mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert desktop.app_home() == tmp_path / "chosen"


def test_paths_use_the_old_folder(monkeypatch, tmp_path):
    old = tmp_path / "Roaming" / "RoundtableHold"
    (old / "config").mkdir(parents=True)
    _home(monkeypatch, "win32", tmp_path)
    assert Paths().home == old and Paths().hub_yaml == old / "config" / "hub.yaml"


def test_default_projects_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / "Documents").mkdir()
    assert desktop.default_projects_dir() == tmp_path / "Documents" / "Darkness Projects"
    (tmp_path / "Documents" / "Roundtable Projects").mkdir()
    assert desktop.default_projects_dir() == tmp_path / "Documents" / "Roundtable Projects"


# -- keys: read from the old service, written to the new ---------------------------------------------
def test_keys_read_from_the_old_service_and_written_to_the_new(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    kr = MemoryKeyring()
    kr.set_password("Roundtable Hold", "DEEPSEEK_API_KEY", "made-up-old")
    ks = KeyStore(Paths(tmp_path / "home"), backend=kr)
    assert ks.get("DEEPSEEK_API_KEY") == "made-up-old"
    # copied forward, and the old entry is kept (a reinstalled 0.x still finds it)
    assert kr.data[("Darkness Harness", "DEEPSEEK_API_KEY")] == "made-up-old"
    assert kr.data[("Roundtable Hold", "DEEPSEEK_API_KEY")] == "made-up-old"
    ks.set("DEEPSEEK_API_KEY", "made-up-new")
    assert kr.data[("Darkness Harness", "DEEPSEEK_API_KEY")] == "made-up-new"
    assert kr.data[("Roundtable Hold", "DEEPSEEK_API_KEY")] == "made-up-old"  # never rewritten
    assert ks.get("DEEPSEEK_API_KEY") == "made-up-new"
    vault.clear()
    assert KeyStore(Paths(tmp_path / "home"), backend=kr).load_into_env() == ["DEEPSEEK_API_KEY"]
    assert vault.get("DEEPSEEK_API_KEY") == "made-up-new"
    vault.clear()


def test_a_removed_key_does_not_come_back_from_the_old_service(tmp_path):
    kr = MemoryKeyring()
    kr.set_password("Roundtable Hold", "OPENAI_API_KEY", "made-up")
    ks = KeyStore(Paths(tmp_path / "home"), backend=kr)
    ks.set("OPENAI_API_KEY", "")
    assert ks.get("OPENAI_API_KEY") is None and not kr.data
    vault.clear()


def test_new_keys_only_in_the_new_service(tmp_path):
    kr = MemoryKeyring()
    KeyStore(Paths(tmp_path / "home"), backend=kr).set("GEMINI_API_KEY", "made-up")
    assert list(kr.data) == [("Darkness Harness", "GEMINI_API_KEY")]
    vault.clear()


def test_a_broken_old_service_is_no_key(tmp_path):
    class Picky(MemoryKeyring):
        def get_password(self, service, name):
            if service == "Roundtable Hold":
                raise RuntimeError("locked")
            return super().get_password(service, name)

    assert KeyStore(Paths(tmp_path / "home"), backend=Picky()).get("DEEPSEEK_API_KEY") is None


# -- the updater finds the installer under either name -------------------------------------------------
def _asset(name):
    return {"name": name, "browser_download_url": f"https://dl/{name}"}


def test_installer_picked_from_both_names():
    both = [_asset("RoundtableMobile-1.0.0-test.apk"), _asset("RoundtableHold-Setup-1.0.0.exe"),
            _asset("DarknessMobile-1.0.0-test.apk"), _asset("DarknessHarness-Setup-1.0.0.exe")]
    assert updater.pick_installer(both)["name"] == "DarknessHarness-Setup-1.0.0.exe"
    assert updater.pick_installer(both[:2])["name"] == "RoundtableHold-Setup-1.0.0.exe"
    assert updater.pick_installer([_asset("RoundtableHold.exe"), _asset("Other-setup.exe")])["name"] == "Other-setup.exe"
    assert updater.pick_installer([_asset("RoundtableHold.exe"), _asset("DarknessMobile-1.0.0-test.apk")]) is None
    assert updater.pick_installer([]) is None


def test_latest_release_and_check_with_the_new_name(monkeypatch):
    rel = {"tag_name": "v1.0.0", "body": "- Roundtable Hold is now Darkness Harness. Everything you have stays.",
           "assets": [_asset("RoundtableMobile-1.0.0-test.apk"), _asset("DarknessHarness-Setup-1.0.0.exe")]}
    got = updater.latest_release(lambda url: rel)
    assert got["version"] == "1.0.0" and got["url"] == "https://dl/DarknessHarness-Setup-1.0.0.exe"
    monkeypatch.setattr(updater, "latest_release", lambda fetch=None: got)
    st = updater.check(info=updater.InstallInfo("app", version="0.12.0"))
    assert st.available and st.message.startswith("Darkness Harness 1.0.0 is available")


def test_an_old_updater_would_find_the_new_installer():
    """0.x's rule, copied from its updater: the first asset with "setup" in its name ending .exe."""
    def old_rule(assets):
        return next((a for a in assets if a["name"].lower().endswith("setup.exe")
                     or ("setup" in a["name"].lower() and a["name"].lower().endswith(".exe"))), None)

    release = [_asset("DarknessMobile-1.0.0-test.apk"), _asset("RoundtableMobile-1.0.0-test.apk"),
               _asset("DarknessHarness-Setup-1.0.0.exe")]
    assert old_rule(release)["name"] == "DarknessHarness-Setup-1.0.0.exe"


def test_installer_prefixes_follow_the_brand():
    assert updater.INSTALLER_PREFIX == "DarknessHarness-Setup-"
    assert updater.LEGACY_INSTALLER_PREFIX == "RoundtableHold-Setup-"


# -- the old-name starter -------------------------------------------------------------------------------
def _starter():
    spec = importlib.util.spec_from_file_location("old_name_starter", ROOT / "packaging" / "old_name_starter.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_starter_opens_the_new_exe(tmp_path, monkeypatch):
    mod = _starter()
    assert mod.NEW_EXE == brand.EXE
    assert mod.main([], here=str(tmp_path)) == 2  # no new exe beside it: nothing to start
    (tmp_path / brand.EXE).write_text("", encoding="utf-8")
    calls = []
    monkeypatch.setattr(mod.subprocess, "call", lambda cmd: calls.append(("wait", cmd)) or 0)
    monkeypatch.setattr(mod.subprocess, "Popen", lambda cmd, **kw: calls.append(("start", cmd)))
    assert mod.main(["--self-test"], here=str(tmp_path)) == 0
    assert mod.main(["--browser"], here=str(tmp_path)) == 0
    target = str(tmp_path / brand.EXE)
    assert calls == [("wait", [target, "--self-test"]), ("start", [target, "--browser"])]


def test_the_starter_uses_the_standard_library_only():
    text = (ROOT / "packaging" / "old_name_starter.py").read_text(encoding="utf-8")
    imports = set(re.findall(r"^(?:import|from)\s+(\w+)", text, re.M))
    assert imports <= {"os", "subprocess", "sys"}


# -- packaging carries the new names and clears the old ones ---------------------------------------------
def test_installer_script():
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    assert '#define AppExe "DarknessHarness.exe"' in iss and '#define LegacyExe "RoundtableHold.exe"' in iss
    assert "OutputBaseFilename=DarknessHarness-Setup-{#AppVersion}" in iss
    assert 'Source: "..\\dist\\DarknessHarness\\*"' in iss
    deleted = re.search(r"^\[InstallDelete\](.*?)\n\[", iss, re.S | re.M).group(1)
    for leftover in ("{app}\\{#LegacyExe}", "{autoprograms}\\{#LegacyName}\\{#LegacyName}.lnk",
                     "{autodesktop}\\{#LegacyName}.lnk"):
        assert leftover in deleted
    assert "Check: ShouldRelaunch" in iss and 'Filename: "{app}\\{#AppExe}"; Flags: nowait; Check' in iss
    assert "UsePreviousGroup=no" in iss
    assert "UsePreviousAppDir=no" not in iss  # an upgrade stays in the old install folder


def test_pyinstaller_spec_builds_both_exes():
    spec = (ROOT / "packaging" / "roundtable.spec").read_text(encoding="utf-8")
    assert f'NAME = "{brand.EXE.removesuffix(".exe")}"' in spec
    assert f'LEGACY_NAME = "{brand.LEGACY_EXE.removesuffix(".exe")}"' in spec
    assert "old_name_starter.py" in spec and "COLLECT(exe, starter_exe" in spec


def test_workflow_ships_both_apk_names_and_tests_the_upgrade():
    yml = (ROOT / ".github" / "workflows" / "app.yml").read_text(encoding="utf-8")
    assert 'DarknessMobile-$version-test.apk' in yml and 'RoundtableMobile-$version-test.apk' in yml
    assert "dist/DarknessMobile-*-test.apk" in yml and "dist/RoundtableMobile-*-test.apk" in yml
    assert "upgrade-test:" in yml and "needs: [windows-app, upgrade-test, android-apk]" in yml
    assert "RoundtableHold-Setup-" in yml and "dist/DarknessHarness-Setup-*.exe" in yml


# -- the names machines read never change -----------------------------------------------------------------
def test_guard_names_machines_read():
    """If this fails, an installed copy, a paired phone or the hub would break. Don't change these."""
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    assert re.search(r"^AppId=\{\{6C3E4E2A-6F3B-4C55-9F7E-52B1D1A0C0DE\}$", iss, re.M), "the installer's AppId changed"
    gradle = (ROOT / "mobile" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    assert 'applicationId = "com.meztking.roundtable"' in gradle, "the phone's applicationId changed"
    assert 'namespace = "com.meztking.roundtable"' in gradle
    assert 'applicationIdSuffix = ".debug"' in gradle
    assert remote.PREFIX == "roundtable:", "the hub command prefix changed"
    phone = (ROOT / "src" / "roundtable" / "phone.py").read_text(encoding="utf-8")
    assert 'f"roundtable://pair?v=1&' in phone, "the pair-link scheme changed"
    releases = (ROOT / "mobile" / "app" / "src" / "main" / "java" / "com" / "meztking" / "roundtable" / "update"
                / "Releases.kt").read_text(encoding="utf-8")
    assert 'const val UPDATE_REPO = "MEZTKING/agent-harness"' in releases, "the phone's UPDATE_REPO changed"
    assert updater.RELEASES_API == "https://api.github.com/repos/MEZTKING/agent-harness/releases/latest"
    assert updater.DIST == "roundtable-hold"
    assert desktop.LEGACY_APP_NAME == "RoundtableHold" and desktop.LEGACY_KEYRING_SERVICE == "Roundtable Hold"
    assert brand.LEGACY_EXE == "RoundtableHold.exe"


@pytest.mark.parametrize("name", ["test_passage"])
def test_no_secret_or_real_key_in_this_file(name):
    text = Path(__file__).read_text(encoding="utf-8")
    assert not re.search(r"sk-[A-Za-z0-9]{16,}", text)
