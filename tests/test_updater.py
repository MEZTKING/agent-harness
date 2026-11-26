import subprocess
import sys

import pytest

from roundtable import updater
from roundtable.updater import InstallInfo, UpdateError, check, install_info, update


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                   cwd=cwd, check=True, capture_output=True)


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "STATE_FILE", tmp_path / "state" / "update-check.json")
    monkeypatch.delenv("ROUNDTABLE_NO_UPDATE_CHECK", raising=False)


def test_file_url_to_path():
    from pathlib import Path

    from roundtable.updater import _file_url_to_path

    here = Path.cwd().resolve()
    assert Path(_file_url_to_path(here.as_uri())) == here  # round-trips on Windows and POSIX


def test_install_kinds_from_direct_url():
    git = install_info({"url": "https://github.com/x/y", "vcs_info": {"vcs": "git", "commit_id": "abc",
                                                                     "requested_revision": "main"}}, version="1")
    assert (git.kind, git.url, git.ref, git.commit) == ("git", "https://github.com/x/y", "main", "abc")
    assert install_info({"url": "file:///nope", "dir_info": {}}, version="1").kind == "other"


class FakeRunner:
    def __init__(self, heads):
        self.heads, self.calls = heads, []

    def __call__(self, cmd, cwd=None, timeout=600):
        self.calls.append(cmd)
        if cmd[:2] == ["git", "ls-remote"]:
            return subprocess.CompletedProcess(cmd, 0, f"{self.heads}\trefs/heads/main\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")


def test_git_install_check_and_update():
    info = InstallInfo("git", url="https://github.com/x/y", ref="main", commit="old1234")
    run = FakeRunner("new5678")
    st = check(info=info, runner=run)
    assert st.available and "old1234"[:7] in st.message
    st = update(info=info, runner=run, log=lambda *_: None)
    pip = next(c for c in run.calls if "pip" in c)
    assert pip[0] == sys.executable and "roundtable-hold @ git+https://github.com/x/y@main" in pip
    assert not st.available and st.latest == "new5678"
    run2 = FakeRunner("same999")
    st = update(info=InstallInfo("git", url="u", ref="main", commit="same999"), runner=run2, log=lambda *_: None)
    assert not any("pip" in c for c in run2.calls)  # nothing to do


def test_other_install_is_explained():
    st = check(info=InstallInfo("other"))
    assert "reinstall" in st.message and not st.available
    with pytest.raises(UpdateError):
        update(info=InstallInfo("other"), log=lambda *_: None)


def test_editable_update_end_to_end_with_real_git(tmp_path):
    remote = tmp_path / "remote.git"
    _git("init", "-q", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    dev = tmp_path / "dev"
    _git("clone", "-q", str(remote), str(dev), cwd=tmp_path)
    (dev / "a.txt").write_text("v1", encoding="utf-8")
    _git("add", ".", cwd=dev)
    _git("commit", "-qm", "v1", cwd=dev)
    _git("push", "-q", "origin", "HEAD:main", cwd=dev)
    user = tmp_path / "user"
    _git("clone", "-q", str(remote), str(user), cwd=tmp_path)

    (dev / "a.txt").write_text("v2", encoding="utf-8")  # a new release lands upstream
    _git("commit", "-qam", "add dragons", cwd=dev)
    _git("push", "-q", "origin", "HEAD:main", cwd=dev)

    pip_calls = []

    def runner(cmd, cwd=None, timeout=600):
        if "pip" in cmd:  # don't really reinstall in tests
            pip_calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)

    info = install_info({"url": user.as_uri(), "dir_info": {"editable": True}}, version="1", runner=runner)
    assert info.kind == "editable" and info.ref == "main" and info.commit
    assert check(info=info, runner=runner).available

    (user / "a.txt").write_text("my local hack", encoding="utf-8")  # uncommitted change: refuse
    with pytest.raises(UpdateError, match="uncommitted"):
        update(info=info, runner=runner, log=lambda *_: None)
    _git("checkout", "a.txt", cwd=user)

    lines = []
    st = update(info=info, runner=runner, log=lines.append)
    assert (user / "a.txt").read_text(encoding="utf-8") == "v2"
    assert any("add dragons" in c for c in st.changes)
    assert pip_calls and pip_calls[0][-2:] == ["-e", str(user)]
    assert any("Restart" in ln for ln in lines)


def test_cached_notice_checks_at_most_daily(monkeypatch):
    calls = {"n": 0}
    info = InstallInfo("git", url="u", ref="main", commit="aaa1111")
    monkeypatch.setattr(updater, "install_info", lambda runner=None: info)

    def fake_check(ref=None, info=None, runner=None, timeout=30):
        calls["n"] += 1
        return updater.UpdateStatus(info, latest="bbb2222", available=True)

    monkeypatch.setattr(updater, "check", fake_check)
    assert "roundtable update" in updater.cached_notice(now=1000.0)
    assert "roundtable update" in updater.cached_notice(now=2000.0)  # cached: no network
    assert calls["n"] == 1
    updater.cached_notice(now=1000.0 + updater.CHECK_EVERY + 1)
    assert calls["n"] == 2
    monkeypatch.setenv("ROUNDTABLE_NO_UPDATE_CHECK", "1")
    assert updater.cached_notice(now=10**9) is None


def test_notice_never_breaks_commands(monkeypatch):
    monkeypatch.setattr(updater, "install_info", lambda runner=None: (_ for _ in ()).throw(OSError("boom")))
    assert updater.cached_notice() is None


def test_the_two_version_numbers_match():
    """The installer checks roundtable.__version__; pyproject.toml is what pip and the phone read."""
    import re
    from pathlib import Path

    import roundtable

    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version = "([^"]+)"', text, re.M).group(1) == roundtable.__version__
