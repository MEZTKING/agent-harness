"""CI shown (ci.py): a project's newest checks from GitHub, kept a minute. A fake git and a fake GitHub; no
network, no keys."""

import json

import pytest

from roundtable import ci
from roundtable.automation import TOKEN_FALLBACKS, TOKEN_KEY
from roundtable.core import secrets as vault


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for n in (TOKEN_KEY, *TOKEN_FALLBACKS):
        monkeypatch.delenv(n, raising=False)
    vault.clear()
    ci.forget()
    yield
    vault.clear()
    ci.forget()


def git(remote="https://github.com/acme/shop.git", branch="main"):
    def run(args, root):
        return remote if args[:2] == ["remote", "get-url"] else branch
    return run


def run(i, name, status="completed", conclusion="success", at="2030-01-01T10:00:00Z", wf=None):
    return {"id": i, "name": name, "workflow_id": wf or name, "status": status, "conclusion": conclusion,
            "created_at": at, "html_url": f"https://github.com/acme/shop/actions/runs/{i}", "head_sha": "abcdef1234"}


class GH:
    def __init__(self, runs):
        self.runs, self.calls = runs, 0

    def __call__(self, url, headers):
        self.calls += 1
        assert url.startswith("https://api.github.com/repos/acme/shop/actions/runs") and "branch=main" in url
        return 200, {}, json.dumps({"workflow_runs": self.runs}).encode()


@pytest.mark.parametrize("runs,state,words", [
    ([run(1, "tests"), run(2, "build")], "passing", "Checks passing"),
    ([run(1, "tests", conclusion="failure"), run(2, "build")], "failing", "1 check failing"),
    ([run(1, "tests", at="2030-01-01T09:00:00Z", conclusion="failure"), run(3, "tests", at="2030-01-01T11:00:00Z")],
     "passing", "Checks passing"),  # a later green run of the same check means it's fixed
    ([run(1, "tests", status="in_progress", conclusion=None), run(2, "build")], "running", "Checks running"),
    ([], "none", "No checks yet"),
])
def test_ci_states(tmp_path, runs, state, words):
    vault.put(TOKEN_KEY, "made-up-key")
    d = ci.status(tmp_path, http=GH(runs), git=git())
    assert (d["state"], d["words"], d["repo"], d["branch"]) == (state, words, "acme/shop", "main")
    if state == "failing":
        assert d["failing"] == [{"name": "tests", "url": "https://github.com/acme/shop/actions/runs/1"}]


def test_ci_is_kept_for_a_minute(tmp_path):
    vault.put(TOKEN_KEY, "made-up-key")
    gh = GH([run(1, "tests")])
    ci.status(tmp_path, http=gh, git=git(), now=100.0)
    ci.status(tmp_path, http=gh, git=git(), now=150.0)
    assert gh.calls == 1
    ci.status(tmp_path, http=gh, git=git(), now=170.0)
    assert gh.calls == 2


def test_ci_without_github_or_a_key(tmp_path):
    assert ci.status(tmp_path, git=git(remote="https://gitlab.com/a/b.git"))["state"] == "not_github"
    assert ci.status(tmp_path, git=git(remote=""))["state"] == "not_github"
    d = ci.status(tmp_path, git=git())
    assert d["state"] == "no_key" and "GitHub key" in d["words"]
    assert ci.repo_of(tmp_path, git(remote="git@github.com:acme/shop.git", branch="HEAD")) == ("acme/shop", "main")


def test_ci_errors_say_so(tmp_path):
    vault.put(TOKEN_KEY, "made-up-key")
    d = ci.status(tmp_path, http=lambda url, h: (401, {}, b"{}"), git=git())
    assert d["state"] == "error" and "didn't accept" in d["detail"]
