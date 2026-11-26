"""Repository mode (Roundtable on one of the owner's existing apps) and the project's own settings.

Every repository here is made up, in tmp_path.
"""

import json
import subprocess
import sys

import pytest
import yaml

from roundtable.harness import checks as checkslib
from roundtable.harness import projectsettings as ps
from roundtable.harness import reporules
from roundtable.harness.orchestrator import HarnessError
from roundtable.phone import phone_allowed
from roundtable.providers.scripted import reply

from .test_harness import RAW, Brain, make

PLAN = [
    {"id": "T1", "title": "fix the greeting", "role": "coder", "description": "create hello.py",
     "acceptance": "hello.py prints hi", "depends_on": []},
]


def git(root, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false",
                           *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def make_repo(tmp_path, files=None):
    """A made-up app with one commit on main, where make() puts the project (tmp_path/proj)."""
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "checkout", "-q", "-b", "main")
    (root / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    (root / "app.py").write_text("print('old')\n", encoding="utf-8")
    for rel, text in (files or {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "first")
    return root


def check_script(root, old=("tests/test_app.py::test_old",)):
    """A test command that fails on `old` always, and on test_new when hello.py says 'broken'."""
    (root / "check.py").write_text(
        "import pathlib, sys\n"
        f"bad = {list(old)!r}\n"
        "h = pathlib.Path('hello.py')\n"
        "if h.exists() and 'broken' in h.read_text(encoding='utf-8'):\n"
        "    bad.append('tests/test_app.py::test_new')\n"
        "for b in bad:\n"
        "    print('FAILED ' + b + ' - AssertionError')\n"
        "sys.exit(1 if bad else 0)\n", encoding="utf-8")
    return f'"{sys.executable}" check.py'


# -- detection, .gitignore, the branch -----------------------------------------------------------------
def test_an_existing_repository_gets_its_own_branch_and_its_gitignore_is_left_alone(tmp_path):
    root = make_repo(tmp_path)
    main_before = git(root, "rev-parse", "main")
    orch, *_ = make(tmp_path, brain=Brain(plan=PLAN))
    orch.start("Final bug fix before I ship it")
    repo = orch.project.meta()["repository"]
    assert repo["start_branch"] == "main" and repo["start_commit"] == main_before
    assert repo["branch"] == "roundtable/final-bug-fix-before-i-ship-it"
    assert (root / ".gitignore").read_text(encoding="utf-8") == "node_modules/\n"  # untouched
    assert ".harness/" in (root / ".git" / "info" / "exclude").read_text(encoding="utf-8").splitlines()
    assert (root / ".harness" / "project.yaml").is_file()
    assert orch.run() == "done"
    assert git(root, "rev-parse", "main") == main_before  # nothing landed on main
    assert git(root, "symbolic-ref", "--short", "HEAD") == repo["branch"]
    log = git(root, "log", "--oneline", repo["branch"])
    assert "[T1] fix the greeting" in log
    assert ".harness" not in git(root, "ls-files")
    assert git(root, "status", "--porcelain") == ""


def test_an_existing_branch_is_reused(tmp_path):
    root = make_repo(tmp_path)
    git(root, "branch", "roundtable/tidy-up")
    orch, *_ = make(tmp_path, brain=Brain(plan=PLAN))
    orch.start("tidy up")
    assert orch.project.meta()["repository"]["branch_reused"] is True
    assert git(root, "symbolic-ref", "--short", "HEAD") == "roundtable/tidy-up"


def test_it_never_commits_on_main_or_the_branch_it_started_from(tmp_path):
    root = make_repo(tmp_path)
    orch, *_ = make(tmp_path, brain=Brain(plan=PLAN))
    orch.start("tidy up")
    git(root, "checkout", "-q", "main")  # someone switched back by hand
    (root / "x.txt").write_text("x\n", encoding="utf-8")
    orch._git_commit("work")  # goes back to its own branch first
    assert git(root, "symbolic-ref", "--short", "HEAD") == "roundtable/tidy-up"
    assert "work" not in git(root, "log", "--oneline", "main")
    meta = orch.project.meta()
    meta["repository"]["branch"] = "main"  # a broken record can never make it commit on main
    orch.project.save_meta(meta)
    with pytest.raises(HarnessError, match="won't commit on main"):
        orch._git_commit("more")


def test_the_branch_setting_names_it(tmp_path):
    root = make_repo(tmp_path, {"roundtable.yaml": "branch: fixes/before-release\n"})
    orch, *_ = make(tmp_path, brain=Brain(plan=PLAN))
    orch.start("tidy up")
    assert git(root, "symbolic-ref", "--short", "HEAD") == "fixes/before-release"
    assert orch._card_status("planned") == "planned · branch fixes/before-release"


def test_a_new_project_works_as_before(tmp_path):
    orch, *_ = make(tmp_path, brain=Brain(plan=PLAN))
    orch.start("a bakery site")
    assert "repository" not in orch.project.meta()
    assert orch.run() == "done"
    root = orch.project.root
    assert ".harness/" in (root / ".gitignore").read_text(encoding="utf-8")
    assert "[T1]" in git(root, "log", "--oneline")
    assert orch._repo_rules_block() == ""
    assert all("The repository's own rules" not in (c["system"] or "") for c in orch.cfg.provider("a").calls)


def test_a_folder_with_git_but_no_commit_is_a_new_project(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init", "-q")
    orch, *_ = make(tmp_path, brain=Brain(plan=PLAN))
    orch.start("goal")
    assert "repository" not in orch.project.meta()
    assert ".harness/" in (root / ".gitignore").read_text(encoding="utf-8")


# -- the repository's rules -------------------------------------------------------------------------------
def test_the_repositorys_rules_reach_the_planner_critic_worker_and_reviewer(tmp_path):
    devlog = ("# Devlog\n\n## 2026-11-20 — old entry\nOLD-ENTRY\n\n## 2026-11-25 — newest entry\nNEWEST-ENTRY\n\n"
              "## 2026-11-01 — oldest\nOLDEST\n")
    make_repo(tmp_path, {"CLAUDE.md": "# Rules\nALWAYS-USE-TABS\n", "AGENTS.md": "AGENTS-RULE\n", "DEVLOG.md": devlog})
    raw = json.loads(json.dumps(RAW))
    raw["roles"]["critic"] = {"model": "a/critic"}
    raw["critic_role"] = "critic"
    orch, a, *_ = make(tmp_path, raw=raw, brain=Brain(plan=PLAN))
    orch.start("speed it up")
    assert orch.run() == "done"
    by_tool = {}
    for c in a.calls:
        for name in ("submit_plan", "submit_critique", "finish_task", "submit_review"):
            if name in {t.name for t in c["tools"] or []}:
                by_tool.setdefault(name, c)
    assert set(by_tool) == {"submit_plan", "submit_critique", "finish_task", "submit_review"}
    for c in by_tool.values():
        system = c["system"]
        assert "# The repository's own rules (follow them)" in system
        assert "ALWAYS-USE-TABS" in system and "AGENTS-RULE" in system
        assert "NEWEST-ENTRY" in system and "OLD-ENTRY" not in system and "OLDEST" not in system
        assert "never switch branches, push" in system.lower() or "Never switch branches, push" in system
    # the same block on every call (the prompt cache keeps it)
    blocks = {c["system"].split("# The repository's own rules", 1)[1] for c in a.calls
              if "# The repository's own rules" in (c["system"] or "")}
    assert len(blocks) == 1
    plan_prompt = by_tool["submit_plan"]["messages"][0]["content"]
    assert "# This is an existing app" in plan_prompt
    assert "existing app (fix, speed up, tidy)" in by_tool["submit_critique"]["messages"][0]["content"]


def test_long_rules_are_trimmed_and_keep_their_headings(tmp_path):
    body = "\n".join(f"line {i} " + "x" * 80 for i in range(400))
    text = f"# Big rules\n{body}\n## Section two\n{body}\n## Section three\nshort\n"
    out = reporules.trim(text, 3000)
    assert len(out) <= 3000
    assert "# Big rules" in out and "## Section two" in out and "## Section three" in out and "short" in out
    assert reporules.CUT in out
    make_repo(tmp_path, {"CLAUDE.md": text, "AGENTS.md": text})
    pieces = reporules.read_rules(tmp_path / "proj", ps.DEFAULT_RULES_FILES, 6000)
    assert [t for t, _ in pieces] == ["CLAUDE.md", "AGENTS.md"]
    assert sum(len(x) for _, x in pieces) <= 6000


def test_newest_entry_of_a_devlog():
    log = "# Log\n\n## 2026-01-02 first\nA\n\n## 2026-03-04 second\nB\n"
    assert reporules.newest_entry(log, "DEVLOG.md").startswith("## 2026-03-04 second")
    assert reporules.newest_entry("# Log\n\n## one\nA\n## two\nB\n", "DEVLOG.md") == "## one\nA"
    handoff = "# Handoff\n\n## State\nS\n## Next\nN\n"
    assert reporules.newest_entry(handoff, "HANDOFF.md") == handoff


# -- the project's settings -----------------------------------------------------------------------------------
def test_settings_merge_project_yaml_over_roundtable_yaml(tmp_path):
    (tmp_path / "roundtable.yaml").write_text("test: pytest -q\ntimeout: 60\nmystery: 1\n", encoding="utf-8")
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "project.yaml").write_text(
        "timeout: 120\nenv:\n  QT_QPA_PLATFORM: offscreen\nlook: off\n", encoding="utf-8")
    st = ps.load(tmp_path)
    assert st.values["test"] == "pytest -q" and st.sources["test"] == "roundtable.yaml"
    assert st.values["timeout"] == 120 and st.sources["timeout"] == ".harness/project.yaml"
    assert st.values["env"] == {"QT_QPA_PLATFORM": "offscreen"}
    assert st.values["look"] == "off"  # YAML's off (false) is understood
    assert st.values["setup"] == "" and st.sources["setup"] == "default"
    assert any("mystery" in w and "kept" in w for w in st.warnings)


def test_unknown_keys_are_kept_when_the_file_is_written(tmp_path):
    (tmp_path / ".harness").mkdir()
    (tmp_path / ".harness" / "project.yaml").write_text("later_feature: yes please\n", encoding="utf-8")
    ps.update(tmp_path, {"test": "make check"})
    raw = yaml.safe_load((tmp_path / ".harness" / "project.yaml").read_text(encoding="utf-8"))
    assert raw == {"test": "make check", "later_feature": "yes please"}
    text = (tmp_path / ".harness" / "project.yaml").read_text(encoding="utf-8")
    for s in ps.SETTINGS:  # every setting is explained in the file
        assert s.description in text


def test_wrong_settings_are_refused_in_plain_words(tmp_path):
    with pytest.raises(ValueError, match="timeout should be a whole number"):
        ps.update(tmp_path, {"timeout": "soon"})
    with pytest.raises(ValueError, match="no setting called 'colour'"):
        ps.update(tmp_path, {"colour": "red"})
    with pytest.raises(ValueError, match="look should be one of auto, on, off"):
        ps.update(tmp_path, {"look": "maybe"})
    with pytest.raises(ValueError, match="isn't a limit"):
        ps.update(tmp_path, {"limits": {"max_fun": 3}})
    with pytest.raises(ValueError, match="no profile 'Turbo'"):
        ps.update(tmp_path, {"profile": "Turbo"}, profiles=["Budget", "Quality"])
    assert not (tmp_path / ".harness" / "project.yaml").exists()  # nothing written
    ps.set_from_text(tmp_path, "env", "QT_QPA_PLATFORM=offscreen")
    ps.set_from_text(tmp_path, "env", "A=1")
    ps.set_from_text(tmp_path, "env", "A=")
    ps.set_from_text(tmp_path, "providers_allowed", "deepseek, anthropic")
    st = ps.load(tmp_path)
    assert st.values["env"] == {"QT_QPA_PLATFORM": "offscreen"}
    assert st.values["providers_allowed"] == ["deepseek", "anthropic"]
    ps.set_from_text(tmp_path, "providers_allowed", "")
    assert ps.load(tmp_path).sources["providers_allowed"] == "default"


def test_a_mistake_in_the_settings_stops_the_run_with_what_to_fix(tmp_path):
    orch, *_ = make(tmp_path, brain=Brain(plan=PLAN))
    orch.start("goal")
    (orch.project.root / ".harness" / "project.yaml").write_text("timeout: soon\n", encoding="utf-8")
    with pytest.raises(HarnessError, match="settings have a mistake: .*timeout should be a whole number"):
        orch.run()


def test_providers_allowed_keeps_roles_to_those_providers(tmp_path):
    orch, a, b, *_ = make(tmp_path, brain=Brain(plan=PLAN))
    ps.update(tmp_path / "proj", {"providers_allowed": ["a"]})
    orch, a, b, *_ = make(tmp_path, brain=Brain(plan=PLAN))
    assert [str(m) for m in orch.cfg.roles["coder"].models] == ["a/coder"]  # b/coder2 dropped
    orch.start("goal")
    assert orch.run() == "done"
    assert b.calls == []
    ps.update(tmp_path / "proj", {"providers_allowed": ["b"]})
    orch, a, b, *_ = make(tmp_path, brain=Brain(plan=PLAN))
    assert [str(m) for m in orch.cfg.roles["coder"].models] == ["b/coder2"]  # falls back to an allowed model
    orch.retry("T1")
    with pytest.raises(HarnessError, match="may only use b .*'(orchestrator|reviewer)' has no model"):
        orch.run()
    assert a.calls == []


def test_limits_and_profile_in_the_settings(tmp_path):
    raw = json.loads(json.dumps(RAW))
    raw["profiles"] = {"Budget": {"roles": {"coder": {"model": "b/coder2"}}}, "Quality": {"roles": {}}}
    orch, *_ = make(tmp_path, raw=raw)
    ps.update(tmp_path / "proj", {"limits": {"max_real_usd_per_run": 2, "max_cost_usd": 1.5}, "profile": "budget"},
              profiles=["Budget", "Quality"])
    orch, *_ = make(tmp_path, raw=raw)
    assert orch.cfg.limits.max_real_usd_per_run == 2 and orch.budget.limit_usd == 1.5
    assert orch.profile() == "Budget" and str(orch.cfg.roles["coder"].models[0]) == "b/coder2"
    orch.start("goal")
    orch.set_profile("Quality")  # the app's choice is written in the file too
    assert ps.load(orch.project.root).values["profile"] == "Quality"


# -- the checks: setup, baseline, only new failures -------------------------------------------------------------
def test_baseline_is_recorded_and_old_failures_are_not_blamed_on_the_task(tmp_path):
    root = make_repo(tmp_path)
    cmd = check_script(root)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "checks")
    (root / "setup-ran.txt").unlink(missing_ok=True)
    orch, a, *_ = make(tmp_path, brain=Brain(plan=PLAN))
    orch.start("fix it")
    ps.update(root, {"test": cmd, "env": {"ROUNDTABLE_TEST_FLAG": "1"},
                     "setup": f'"{sys.executable}" -c "open(\'setup-ran.txt\',\'a\').write(\'x\')"'})
    assert orch.run() == "done"
    meta = orch.project.meta()
    assert meta["baseline"]["passed"] is False
    assert meta["baseline"]["failing"] == ["tests/test_app.py::test_old"]
    assert meta["setup"]["passed"] is True
    assert (root / "setup-ran.txt").read_text(encoding="utf-8") == "x"
    review = next(c for c in a.calls if "submit_review" in {t.name for t in c["tools"] or []})
    prompt = review["messages"][0]["content"]
    assert "only on tests that were already failing before this run started (1 of them)" in prompt
    assert "test_old" not in prompt
    worker = next(c for c in a.calls if "finish_task" in {t.name for t in c["tools"] or []})
    assert cmd in worker["messages"][0]["content"] and "ROUNDTABLE_TEST_FLAG=1" in worker["messages"][0]["content"]
    orch.retry("T1")
    orch.run()
    assert (root / "setup-ran.txt").read_text(encoding="utf-8") == "x"  # setup runs once


class Breaker(Brain):
    """The worker breaks a test on its first attempt and fixes it on the second."""

    def __call__(self, model, system, messages, tools):
        names = {t.name for t in tools}
        if "finish_task" in names and messages[-1]["role"] == "user":
            first = "Feedback on your previous attempt" not in messages[0]["content"]
            text = "print('broken')\n" if first else "print('hi')\n"
            return reply(calls=[("write_file", {"path": "hello.py", "content": text})])
        return super().__call__(model, system, messages, tools)


def test_a_task_that_breaks_a_test_is_sent_back_with_only_the_new_failure(tmp_path):
    root = make_repo(tmp_path)
    cmd = check_script(root)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "checks")
    orch, a, *_ = make(tmp_path, brain=Breaker(plan=PLAN))
    orch.start("fix it")
    ps.update(root, {"test": cmd})
    assert orch.run() == "done"
    t1 = orch.project.tasks()[0]
    assert [x["outcome"] for x in t1.attempts] == ["rejected", "approved"]
    fb = t1.attempts[0]["review"]
    assert "tests/test_app.py::test_new" in fb and "test_old" not in fb
    reviews = [c for c in a.calls if "submit_review" in {t.name for t in c["tools"] or []}]
    assert len({c["messages"][0]["content"] for c in reviews}) == 1  # the reviewer only saw the fixed attempt


def test_compare_and_failing_names():
    out = ("FAILED tests/a.py::test_x - assert 1\nERROR tests/b.py::test_y\n"
           "FAIL: test_z (pkg.TestThing)\n")
    assert checkslib.failing_names(out) == ["tests/a.py::test_x", "tests/b.py::test_y", "pkg.TestThing.test_z"]
    base = {"passed": False, "failing": ["tests/a.py::test_x"], "names_found": True}
    now = {"passed": False, "failing": ["tests/a.py::test_x", "tests/b.py::test_y"], "names_found": True}
    assert checkslib.compare(base, now) == {"verdict": "new", "new": ["tests/b.py::test_y"], "old": ["tests/a.py::test_x"]}
    assert checkslib.compare(base, {**now, "failing": ["tests/a.py::test_x"]})["verdict"] == "old_only"
    unreadable = {"passed": False, "failing": [], "names_found": False}
    assert checkslib.compare({"passed": False, "failing": []}, unreadable)["verdict"] == "unknown"
    assert checkslib.compare({"passed": True, "failing": []}, unreadable)["verdict"] == "new"
    assert checkslib.compare(None, {"passed": True, "failing": [], "names_found": False})["verdict"] == "pass"


def test_a_command_that_takes_too_long_is_stopped(tmp_path):
    res = checkslib.run(tmp_path, f'"{sys.executable}" -c "import time; time.sleep(30)"', timeout=1)
    assert res["timed_out"] and res["seconds"] < 20


# -- the apps: the settings API ---------------------------------------------------------------------------------
def test_settings_api_reads_and_writes(tmp_path):
    from .test_ui import call

    from roundtable.improve.lab import Lab
    from roundtable.ui.server import ApiError, UIApp

    orch, *_ = make(tmp_path, brain=Brain(plan=PLAN))
    orch.start("goal")
    cfg = orch.cfg
    cfg.lab_dir = tmp_path / "lab"
    Lab(cfg.lab_dir).register_project(orch.project.root)
    app = UIApp(hub_config=str(tmp_path / "missing-hub.yaml"), harness_config=str(tmp_path / "missing.yaml"),
                projects_dir=str(tmp_path / "projects"))
    app.cfg = lambda: cfg
    app._cfg = cfg
    path = str(orch.project.root)
    got = call(app, "GET", "/api/project/settings", project=path)
    test = next(s for s in got["settings"] if s["key"] == "test")
    assert test["value"] == "" and test["source"] == "default" and test["type"] == "text" and test["description"]
    assert next(s for s in got["settings"] if s["key"] == "look")["choices"] == ["auto", "on", "off"]
    out = call(app, "POST", "/api/project/settings", {"project": path, "changes": {"test": "make check", "timeout": "60"}})
    assert {s["key"]: s["value"] for s in out["settings"]}["timeout"] == 60
    assert ps.load(orch.project.root).sources["test"] == ".harness/project.yaml"
    with pytest.raises(ApiError, match="timeout should be a whole number"):
        call(app, "POST", "/api/project/settings", {"project": path, "changes": {"timeout": "later"}})
    with pytest.raises(ApiError):
        call(app, "GET", "/api/project/settings", project=str(tmp_path / "elsewhere"))
    assert phone_allowed("GET", "/api/project/settings") and phone_allowed("POST", "/api/project/settings")


def test_settings_on_the_command_line(tmp_path, capsys):
    from roundtable.harness_cli import main

    main(["--config", str(tmp_path / "missing.yaml"), "set", str(tmp_path), "test", "python -m pytest -q"])
    main(["--config", str(tmp_path / "missing.yaml"), "settings", str(tmp_path)])
    out = capsys.readouterr().out
    assert "python -m pytest -q   (from .harness/project.yaml)" in out
    with pytest.raises(SystemExit, match="timeout should be a whole number"):
        main(["--config", str(tmp_path / "missing.yaml"), "set", str(tmp_path), "timeout", "soon"])
