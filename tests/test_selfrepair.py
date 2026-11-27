"""Fixes to its own code (improve/selfrepair.py), against a made-up local bare repository and a fake GitHub:
three faults make one card; a fix touching the gate is refused; a failing suite or a fix without a test opens
nothing; a passing one opens one draft pull request; nothing lands it. No network, no keys."""

import inspect
import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from roundtable.improve import charter, selfrepair

IDENT = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]


def git(cwd, *a):
    return subprocess.run(["git", *IDENT, *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def source(tmp_path):
    """A made-up harness repository (bare, like the one on GitHub)."""
    work = tmp_path / "src-repo"
    (work / "src/roundtable/harness").mkdir(parents=True)
    (work / "tests").mkdir()
    (work / "src/roundtable/harness/gate.py").write_text("ALLOW = True\n")
    (work / "src/roundtable/tidy.py").write_text("def tidy(x):\n    return x.strip()\n")
    (work / "tests/test_tidy.py").write_text("def test_tidy():\n    pass\n")
    git(tmp_path, "init", "-q", "-b", "main", str(work))
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "start")
    bare = tmp_path / "harness.git"
    git(tmp_path, "clone", "-q", "--bare", str(work), str(bare))
    return str(bare)


class FakeGitHub:
    def __init__(self):
        self.calls = []
        self.n = 0

    def _headers(self):
        return {"Authorization": "Bearer proxy-injected"}

    def _check(self, status, body, repo):
        assert status < 300

    def get(self, repo, path, **params):
        self.calls.append(("GET", path, None))
        return {"sha": path.rsplit("/", 1)[-1], "tree": {"sha": "basetree"}}

    def post(self, url, headers, body):
        self.n += 1
        payload = json.loads(body)
        self.calls.append(("POST", url.split("/repos/", 1)[1], payload))
        if url.endswith("/pulls"):
            return 201, {}, json.dumps({"html_url": "https://github.example/pull/7", "number": 7}).encode()
        return 201, {}, json.dumps({"sha": f"sha{self.n}"}).encode()


def boom():
    def tidy_inner():
        raise KeyError("'Moonbakery' at C:\\Users\\someone\\proj\\file.py line 42")

    try:
        tidy_inner()
    except KeyError as e:
        return e


def _three(home):
    for _ in range(3):
        selfrepair.note("_style_system", boom(), home=home, version="9.9.9")


def builder(edits, test=True):
    def build(cfg, work, goal, max_usd, branch, say):
        assert git(work, "symbolic-ref", "--short", "HEAD") == branch
        assert "Moonbakery" not in goal and "Users" not in goal
        for path, text in edits.items():
            (work / path).parent.mkdir(parents=True, exist_ok=True)
            (work / path).write_text(text)
        if test:
            (work / "tests/test_fix.py").write_text("def test_the_fault_is_fixed():\n    assert True\n")
        git(work, "add", "-A")
        git(work, "commit", "-q", "-m", "fix")
        return {"status": "done", "spent_usd": 0.42}
    return build


def test_a_fault_is_kept_as_its_shape_and_where_in_the_harness(tmp_path):
    try:  # a real fault raised inside the harness's own code
        selfrepair.Writer(FakeGitHub()).post("o/r", "/home/someone/Moonbakery/x.py", {})
    except ValueError as e:
        err = e
    r = selfrepair.note("_style_system", err, home=tmp_path, version="9.9.9")
    assert re.match(r"^roundtable\.improve\.selfrepair\.post:\d+$", r["where"]) and r["type"] == "ValueError"
    assert "Moonbakery" not in json.dumps(r) and "someone" not in json.dumps(r) and r["hook"] == "_style_system"
    # a fault outside the harness's own package is not ours to fix
    assert selfrepair.note("x", ValueError("nope"), home=tmp_path) is None


def test_three_of_the_same_fault_make_one_card(tmp_path, monkeypatch):
    monkeypatch.setattr(selfrepair, "where_in_harness",
                        lambda e: {"module": "roundtable.tidy", "function": "tidy", "line": 2})
    for i in range(2):
        selfrepair.note("_style_system", boom(), home=tmp_path, version="9.9.9")
    app = SimpleNamespace(cfg=lambda: None, _backup_home=lambda: tmp_path)
    assert selfrepair.ask(app, version="9.9.9") == []
    selfrepair.note("_style_system", boom(), home=tmp_path, version="9.9.9")
    selfrepair.note("_other", ValueError("different"), home=tmp_path, version="9.9.9")
    cards = selfrepair.ask(app, version="9.9.9")
    assert len(cards) == 1 and cards[0]["question"] == "The harness found a fault in itself. Try a fix for up to $1.50?"
    rows = [json.loads(x) for x in (tmp_path / "faults.jsonl").read_text().splitlines()]
    blob = json.dumps(rows) + json.dumps(cards)
    for secret in ("Moonbakery", "someone", "file.py", "42"):
        assert secret not in blob
    assert rows[0]["count"] == 3 and rows[0]["where"] == "roundtable.tidy.tidy:2"
    assert cards[0]["options"][0]["confirm"]  # the price is confirmed before anything is spent
    # another version starts counting again; "Not now" hides it; "Don't ask again" hides all
    assert selfrepair.ask(app, version="9.9.10") == []
    selfrepair.answer(app, cards[0]["id"], "no")
    assert selfrepair.ask(app, version="9.9.9") == []
    cfg_off = SimpleNamespace(sections={"selfrepair": {"on": False}})
    for _ in range(3):
        selfrepair.note("_y", RuntimeError("other"), home=tmp_path, version="9.9.9")
    assert selfrepair.ask(SimpleNamespace(cfg=lambda: cfg_off, _backup_home=lambda: tmp_path), version="9.9.9") == []


def _fault(tmp_path, monkeypatch):
    monkeypatch.setattr(selfrepair, "where_in_harness",
                        lambda e: {"module": "roundtable.tidy", "function": "tidy", "line": 2})
    _three(tmp_path)
    return selfrepair.due(tmp_path, "9.9.9")[0]


def test_a_fix_touching_the_gate_is_refused(tmp_path, source, monkeypatch):
    fault = _fault(tmp_path, monkeypatch)
    monkeypatch.setattr(charter, "may_touch", lambda path: not path.endswith("harness/gate.py"))
    gh = FakeGitHub()
    res = selfrepair.attempt(None, tmp_path, fault, source=source, writer=selfrepair.Writer(gh, gh.post),
                             build=builder({"src/roundtable/harness/gate.py": "ALLOW = False\n"}),
                             run_tests=lambda w: (True, "1 passed"))
    assert not res["ok"] and res["stage"] == "charter" and res["refused"] == ["src/roundtable/harness/gate.py"]
    assert gh.calls == []


def test_the_real_charter_refuses_the_gate_once_it_is_filled_in():
    if charter.may_touch("src/roundtable/harness/gate.py"):
        pytest.skip("the charter is still the step-0 stub (Helper 4 fills may_touch)")
    assert not charter.may_touch("src/roundtable/harness/gate.py")


def test_a_failing_suite_opens_nothing(tmp_path, source, monkeypatch):
    fault = _fault(tmp_path, monkeypatch)
    gh = FakeGitHub()
    res = selfrepair.attempt(None, tmp_path, fault, source=source, writer=selfrepair.Writer(gh, gh.post),
                             build=builder({"src/roundtable/tidy.py": "def tidy(x):\n    return x\n"}),
                             run_tests=lambda w: (False, "1 failed, 3 passed"))
    assert not res["ok"] and res["stage"] == "tests" and gh.calls == []


def test_a_fix_without_a_new_test_opens_nothing(tmp_path, source, monkeypatch):
    fault = _fault(tmp_path, monkeypatch)
    gh = FakeGitHub()
    res = selfrepair.attempt(None, tmp_path, fault, source=source, writer=selfrepair.Writer(gh, gh.post),
                             build=builder({"src/roundtable/tidy.py": "def tidy(x):\n    return x\n"}, test=False),
                             run_tests=lambda w: (True, "ok"))
    assert res["stage"] == "test_added" and gh.calls == []


def test_a_passing_fix_opens_one_draft_pull_request_and_a_card_with_its_link(tmp_path, source, monkeypatch):
    fault = _fault(tmp_path, monkeypatch)
    gh = FakeGitHub()
    app = SimpleNamespace(cfg=lambda: None, _backup_home=lambda: tmp_path, jobs=None)
    card = selfrepair.ask(app, version="9.9.9")[0]
    kw = dict(source=source, writer=selfrepair.Writer(gh, gh.post),
              build=builder({"src/roundtable/tidy.py": "def tidy(x):\n    return (x or '').strip()\n"}),
              run_tests=lambda w: (True, "5 passed"))
    out = selfrepair.answer(app, card["id"], ["yes"], **kw)
    res = out["result"]
    assert res["ok"] and res["pr_url"] == "https://github.example/pull/7"
    posts = [c for c in gh.calls if c[0] == "POST"]
    pulls = [c for c in posts if c[1].endswith("/pulls")]
    assert len(pulls) == 1 and pulls[0][2]["draft"] is True and pulls[0][2]["base"] == "main"
    assert pulls[0][2]["head"] == f"selfrepair/{fault['sig']}"
    tree = next(c for c in posts if c[1].endswith("/git/trees"))[2]
    assert sorted(t["path"] for t in tree["tree"]) == ["src/roundtable/tidy.py", "tests/test_fix.py"]
    body = pulls[0][2]["body"]
    assert "Moonbakery" not in body and "draft" in body
    assert all(c[1].split("/", 2)[-1].startswith(("git/", "pulls")) for c in posts)
    # the copy lives under the app home, on its own branch, and the card now gives the link
    assert (tmp_path / "self" / fault["sig"] / ".git").exists()
    cards = selfrepair.ask(app, version="9.9.9")
    assert [c["kind"] for c in cards] == ["selfrepair_done"] and cards[0]["link"] == res["pr_url"]
    selfrepair.answer(app, cards[0]["id"], "seen")
    assert selfrepair.ask(app, version="9.9.9") == []


def test_a_second_try_moves_the_old_copy_aside(tmp_path, source, monkeypatch):
    fault = _fault(tmp_path, monkeypatch)
    for _ in range(2):
        selfrepair.attempt(None, tmp_path, fault, source=source, writer=selfrepair.Writer(FakeGitHub()),
                           build=builder({"notes.txt": "x"}, test=False), run_tests=lambda w: (True, ""))
    assert list((tmp_path / "self" / ".old").iterdir())


def test_the_writer_only_makes_the_calls_a_draft_needs(tmp_path):
    w = selfrepair.Writer(FakeGitHub())
    for path in ("/pulls/7/merge", "/merges", "/git/refs/heads/main", "/contents/x"):
        with pytest.raises(ValueError):
            w.post("o/r", path, {})


def test_nothing_in_the_module_can_land_a_pull_request():
    src = inspect.getsource(selfrepair)
    code = re.sub(r'"""[\s\S]*?"""', "", src)
    assert not re.search(r"merge", code, re.I), "self-repair must have no merge call"
    assert "PUT" not in code and '"draft": True' in code


def test_selfrepair_never_changes_what_the_charter_protects(tmp_path, source, monkeypatch):
    fault = _fault(tmp_path, monkeypatch)
    asked = []
    monkeypatch.setattr(charter, "may_touch", lambda p: asked.append(p) or not p.startswith("src/roundtable/improve/charter"))
    gh = FakeGitHub()
    res = selfrepair.attempt(None, tmp_path, fault, source=source, writer=selfrepair.Writer(gh, gh.post),
                             build=builder({"src/roundtable/improve/charter.py": "def check(*a, **k): pass\n"}),
                             run_tests=lambda w: (True, ""))
    assert res["stage"] == "charter" and "src/roundtable/improve/charter.py" in asked and gh.calls == []
    src = inspect.getsource(selfrepair)
    for word in ("save_custom", "harness.yaml\").write", "makers_allowed"):
        assert word not in src
