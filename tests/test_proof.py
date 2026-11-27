"""Proof: the app before and after every task, the tests, and a model that can see as advice (harness/proof.py)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from roundtable.harness import proof
from roundtable.harness import showit
from roundtable.harness.agent import Budget
from roundtable.harness.config import parse_config
from roundtable.harness.orchestrator import Orchestrator
from roundtable.providers.scripted import ScriptedProvider, reply

from .test_harness import RAW, tool_names
from .test_show_it import WebBrain, fake_renderer, hub_raw

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def png(colour, size=(80, 50), box=None, box_colour=(255, 0, 0)) -> bytes:
    img = Image.new("RGB", size, colour)
    if box:
        for x in range(box[0], box[2]):
            for y in range(box[1], box[3]):
                img.putpixel((x, y), box_colour)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def task(tid="T1", base=None, **kw):
    return SimpleNamespace(id=tid, title=kw.get("title", "a menu"), description=kw.get("description", "add a menu"),
                           acceptance=kw.get("acceptance", "the menu shows"), base_commit=base)


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


def repo(tmp_path):
    root = tmp_path / "bakery"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "user.name", "t")
    (root / ".gitignore").write_text(".harness/\n", encoding="utf-8")
    (root / "index.html").write_text("<title>Bakery</title>", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "one")
    return root


def counting_renderer(calls, data=None):
    def render(jobs):
        for j in jobs:
            open(j["png"], "wb").write(data or png((240, 240, 240)))
            open(j["jpg"], "wb").write(b"\xff\xd8\xff" + j["kind"].encode())
        calls.append([j["kind"] for j in jobs])
        return [{"kind": j["kind"], "errors": [], "title": "Bakery"} for j in jobs]
    return render


# -- before: reused by commit, fresh only when there are none --------------------------------------------
def test_every_shots_record_gains_its_commit_and_dirty_folders_have_none(tmp_path):
    root = repo(tmp_path)
    head = git(root, "rev-parse", "HEAD")
    rec = showit.take_shots(root, "T1", render=counting_renderer([]))
    assert rec["commit"] == head  # .harness (the pictures themselves) isn't a change
    (root / "index.html").write_text("<title>Changed</title>", encoding="utf-8")
    assert showit.take_shots(root, "T2", render=counting_renderer([]))["commit"] == ""
    assert showit.commit_of(tmp_path) == ""  # no git: no commit


def test_before_reuses_pictures_at_the_tasks_commit_and_takes_fresh_ones_otherwise(tmp_path):
    root = repo(tmp_path)
    head = git(root, "rev-parse", "HEAD")
    calls = []
    showit.take_shots(root, "T1", render=counting_renderer(calls))  # an earlier task's pictures at this commit
    got = proof.before(root, task("T2", base=head), render=counting_renderer(calls))
    assert got["reused"] is True and calls == [["desktop", "phone"]]  # no second render
    assert (proof.by_commit_dir(root, head) / "desktop.png").is_file() and got["dir"] == f"by-commit/{head}"
    again = proof.before(root, task("T3", base=head), render=counting_renderer(calls))
    assert again["reused"] is True and len(calls) == 1  # tasks starting together share one set
    # a commit nobody pictured yet: fresh pictures, kept by that commit, and the Live tab's latest left alone
    (root / "style.css").write_text("body{}", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "two")
    head2 = git(root, "rev-parse", "HEAD")
    latest_before = (showit.shots_root(root) / "latest.json").read_text(encoding="utf-8")
    fresh = proof.before(root, task("T4", base=head2), render=counting_renderer(calls))
    assert fresh["reused"] is False and fresh["commit"] == head2 and len(calls) == 2
    assert (proof.by_commit_dir(root, head2) / "shots.json").is_file()
    assert (showit.shots_root(root) / "latest.json").read_text(encoding="utf-8") == latest_before
    assert [r["task"] for r in showit.history(root)] == ["T1"]  # the by-commit sets aren't tasks


def test_before_without_a_commit_says_so(tmp_path):
    (tmp_path / "index.html").write_text("x", encoding="utf-8")
    got = proof.before(tmp_path, task(), render=counting_renderer([]))
    assert got["pictures"] == {} and "no saved version" in got["note"]


def test_take_shots_still_never_raises(tmp_path):
    root = repo(tmp_path)

    def broken(jobs):
        raise RuntimeError("the browser fell over")

    rec = showit.take_shots(root, "T1", render=broken, out_dir=proof.by_commit_dir(root, "abc"), latest=False)
    assert "fell over" in rec["failed"] and rec["pictures"] == {}
    assert not (showit.shots_root(root) / "latest.json").exists()


# -- what changed ----------------------------------------------------------------------------------------
def test_the_difference_numbers_on_made_up_pictures(tmp_path):
    a, b, c, d = (tmp_path / n for n in ("a.png", "b.png", "c.png", "d.png"))
    a.write_bytes(png((255, 255, 255)))
    b.write_bytes(png((255, 255, 255)))
    c.write_bytes(png((255, 255, 255), box=(0, 0, 40, 50)))  # the left half turned red
    d.write_bytes(png((0, 0, 0)))
    assert proof.difference(a, b) == (0.0, True)
    half, measured = proof.difference(a, c)
    assert measured and 0.45 <= half <= 0.55
    assert proof.difference(a, d)[0] == 1.0
    assert proof.change_words(0.0) == "looks the same" and proof.change_words(0.01) == "barely changed"
    assert proof.change_words(half) in ("changed (about 49%)", "changed (about 50%)", "changed (about 51%)")


def test_without_pillow_a_file_hash_says_same_or_changed(tmp_path, monkeypatch):
    a, b, c = (tmp_path / n for n in ("a.png", "b.png", "c.png"))
    a.write_bytes(b"one")
    b.write_bytes(b"one")
    c.write_bytes(b"two")
    monkeypatch.setitem(sys.modules, "PIL", None)
    assert proof.difference(a, b) == (0.0, False) and proof.difference(a, c) == (1.0, False)
    assert proof.change_words(1.0, measured=False) == "changed"


def test_pairs_put_each_picture_beside_its_before(tmp_path):
    root = tmp_path
    bdir, adir = showit.shots_root(root) / "by-commit" / "abc", showit.shots_root(root) / "T1"
    bdir.mkdir(parents=True)
    adir.mkdir(parents=True)
    (bdir / "desktop.png").write_bytes(png((255, 255, 255)))
    (adir / "desktop.png").write_bytes(png((255, 255, 255), box=(0, 0, 80, 10)))
    (adir / "dark.png").write_bytes(png((0, 0, 0)))
    prs = proof.pairs(root, {"dir": "by-commit/abc", "pictures": {"desktop": "desktop.png"}},
                      {"dir": "T1", "pictures": {"dark": "dark.png", "desktop": "desktop.png"}})
    assert [p["kind"] for p in prs] == ["desktop", "dark"]
    assert prs[0]["words"].startswith("changed") and prs[1] == {**prs[1], "before": None, "words": "new"}


# -- the tests -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("tail,want", [
    ("....\n===== 41 passed, 3 failed, 2 skipped in 1.20s =====", {"passed": 41, "failed": 3}),
    ("== 12 passed in 0.5s ==", {"passed": 12, "failed": 0}),
    ("Ran 44 tests in 0.1s\n\nFAILED (failures=2, errors=1)", {"passed": 41, "failed": 3}),
    ("Ran 7 tests in 0.1s\n\nOK", {"passed": 7, "failed": 0}),
    ("Tests:       3 failed, 41 passed, 44 total\nTime: 2s", {"passed": 41, "failed": 3}),
    ("# tests 9\n# pass 8\n# fail 1\n", {"passed": 8, "failed": 1}),
    ("test result: ok. 15 passed; 0 failed; 0 ignored", {"passed": 15, "failed": 0}),
    ("it went fine", None),
])
def test_counts_from_common_test_runners(tail, want):
    assert proof.counts(tail) == want


def test_the_tests_before_and_after_in_words():
    base = {"command": "pytest", "passed": True, "failing": [], "tail": "== 38 passed in 1s =="}
    now = {"command": "pytest", "passed": True, "failing": [], "tail": "\n".join(f"line {i}" for i in range(30))
           + "\n== 41 passed in 1s =="}
    t = proof.tests_part(base, {"verdict": "pass", "new": [], "now": now})
    assert t["words"] == "Tests: 41 pass, 3 new." and t["before"]["passed"] == 38
    assert len(t["after"]["tail"].splitlines()) == proof.TAIL_LINES and t["after"]["tail"].endswith("41 passed in 1s ==")
    broke = proof.tests_part(base, {"verdict": "new", "new": ["test_a", "test_b"],
                                    "now": {**now, "passed": False, "tail": "== 39 passed, 2 failed =="}})
    assert broke["words"] == "Tests: 39 pass, 1 new, 2 broke."
    # without the run's own output (the checks' verdict only)
    assert proof.tests_part(base, {"verdict": "pass", "new": []})["words"] == "Tests: they pass."
    assert proof.tests_part(None, None) is None


# -- the judge -------------------------------------------------------------------------------------------
def judge_setup(tmp_path, raw=None, script=None):
    cfg = parse_config(json.loads(json.dumps(raw or RAW)))
    seen = []

    def brain(model, system, messages, tools):
        seen.append({"model": model, "messages": messages, "tools": tool_names(tools)})
        return script or reply(calls=[("submit_proof", {"verdict": "shows_it", "what_changed": "the menu is there",
                                                         "problems": []})])

    cfg.register("a", ScriptedProvider("a", brain))
    cfg.register("b", ScriptedProvider("b", brain))
    root = tmp_path
    bdir, adir = showit.shots_root(root) / "by-commit" / "abc", showit.shots_root(root) / "T1"
    for d, data in ((bdir, png((255, 255, 255))), (adir, png((255, 255, 255), box=(0, 0, 80, 20)))):
        d.mkdir(parents=True)
        for k in ("desktop", "phone", "dark"):
            (d / f"{k}.png").write_bytes(data)
    before_rec = {"dir": "by-commit/abc", "pictures": {k: f"{k}.png" for k in ("desktop", "phone", "dark")}}
    after_rec = {"dir": "T1", "pictures": {k: f"{k}.png" for k in ("desktop", "phone", "dark")}}
    prs = proof.pairs(root, before_rec, after_rec)
    return cfg, seen, before_rec, after_rec, prs


def test_the_judge_looks_at_four_pictures_at_most_and_says_what_it_saw(tmp_path):
    cfg, seen, b, a, prs = judge_setup(tmp_path)
    budget = Budget(5.0)
    got = proof.judge(cfg, task(), prs, None, budget, project_root=tmp_path, before_rec=b, after_rec=a)
    assert got["looked"] and got["verdict"] == "shows_it" and got["model"] == "a/reviewer"
    assert got["words"] == "A model that can see checked: the menu is there"
    [call] = seen
    assert call["tools"] == {"submit_proof"}
    images = [c for c in call["messages"][0]["content"] if c["type"] == "image"]
    assert len(images) == 4  # three pairs, but at most four pictures
    assert budget.spent_usd == pytest.approx(got["cost_usd"]) and got["cost_usd"] > 0


def test_the_proof_role_comes_first_when_there_is_one(tmp_path):
    raw = json.loads(json.dumps(RAW))
    raw["roles"]["proof"] = {"model": "b/eyes"}
    cfg, seen, b, a, prs = judge_setup(tmp_path, raw=raw)
    got = proof.judge(cfg, task(), prs, None, Budget(5.0), project_root=tmp_path, before_rec=b, after_rec=a)
    assert got["model"] == "b/eyes"


def test_the_money_cap_holds(tmp_path):
    raw = json.loads(json.dumps(RAW))
    raw["pricing"]["a/reviewer"] = {"input": 100, "output": 100}  # $100 a million: ~$0.73 for one look
    cfg, seen, b, a, prs = judge_setup(tmp_path, raw=raw)
    got = proof.judge(cfg, task(), prs, None, Budget(5.0), project_root=tmp_path, before_rec=b, after_rec=a)
    assert not got["looked"] and got["why"] == "too_dear" and seen == []
    assert "$0.05" in got["words"]
    # cheap, but earlier tries of the task already spent the cap
    cfg2, seen2, *_ = judge_setup(tmp_path / "two")
    got2 = proof.judge(cfg2, task(), prs, None, Budget(5.0), project_root=tmp_path, before_rec=b, after_rec=a,
                       spent=0.05)
    assert got2["why"] == "too_dear" and seen2 == []
    # the run's own money is used up
    cfg3, seen3, *_ = judge_setup(tmp_path / "three")
    got3 = proof.judge(cfg3, task(), prs, None, Budget(1.0, spent_usd=1.0), project_root=tmp_path, before_rec=b,
                       after_rec=a)
    assert got3["why"] == "budget" and seen3 == []
    # fewer pictures when four cost more than the cap but one doesn't
    raw4 = json.loads(json.dumps(RAW))
    raw4["pricing"]["a/reviewer"] = {"input": 10, "output": 10}
    cfg4, seen4, *_ = judge_setup(tmp_path / "four", raw=raw4)
    got4 = proof.judge(cfg4, task(), prs, None, Budget(5.0), project_root=tmp_path, before_rec=b, after_rec=a)
    assert got4["looked"] and got4["pictures"] < 4 and got4["cost_usd"] <= 0.05


def test_with_no_model_that_can_see_the_record_says_so_honestly(tmp_path):
    raw = json.loads(json.dumps(RAW))
    raw["providers"]["ds"] = {"type": "openai_compat", "base_url": "https://example.invalid"}
    raw["roles"]["reviewer"] = {"model": "ds/deepseek-v4-flash"}
    cfg, seen, b, a, prs = judge_setup(tmp_path, raw=raw)
    got = proof.judge(cfg, task(), prs, None, Budget(5.0), project_root=tmp_path, before_rec=b, after_rec=a)
    assert not got["looked"] and seen == [] and got["words"].startswith("Nobody looked at the pictures")
    rec = proof.build(tmp_path, task(), b, a, None, got, prs)
    assert rec["words"].startswith("Nobody looked at the pictures")


def test_a_model_that_doesnt_answer_with_the_tool_is_written_down(tmp_path):
    cfg, seen, b, a, prs = judge_setup(tmp_path, script=reply("it looks fine to me"))
    got = proof.judge(cfg, task(), prs, None, Budget(5.0), project_root=tmp_path, before_rec=b, after_rec=a)
    assert not got["looked"] and got["why"] == "no_verdict"


def test_review_text_is_advice_unless_strict():
    rec = {"pairs": [{"kind": "desktop", "words": "changed (about 20%)"}],
           "judge": {"looked": True, "verdict": "does_not", "what_changed": "", "problems": ["no menu"], "pictures": 2}}
    text = proof.review_text(rec)
    assert "advice" in text and "does_not" in text and "no menu" in text and "Don't reject only because of it" in text
    assert "don't approve" in proof.review_text(rec, strict=True)


def test_settings_from_harness_yaml():
    cfg = parse_config({**json.loads(json.dumps(RAW)), "proof": {"judge": "off", "max_usd_per_task": 0.02,
                                                                   "max_pictures": 50}})
    s = proof.Settings.from_config(cfg)
    assert s.judge is False and s.max_usd_per_task == 0.02 and s.max_pictures == 8 and s.enabled
    assert proof.estimate_usd(cfg, 10) == 0.0
    assert proof.estimate_usd(parse_config(json.loads(json.dumps(RAW))), 10) == pytest.approx(0.5)


# -- a whole scripted web build, with the coordinator's hook-up lines -------------------------------------
class SeeingWebBrain(WebBrain):
    """The web page builder; the judge says the page shows (or not); the reviewer approves."""

    def __init__(self, verdict="shows_it"):
        super().__init__()
        self.verdict = verdict
        self.review_prompts = []
        self.judged = []

    def __call__(self, model, system, messages, tools):
        names = tool_names(tools)
        if "submit_proof" in names:
            self.judged.append(messages)
            return reply(calls=[("submit_proof", {"verdict": self.verdict, "what_changed": "the page is there",
                                                   "problems": [] if self.verdict == "shows_it" else ["it is blank"]})])
        if "submit_review" in names and messages[-1]["role"] == "user":
            self.review_prompts.append(messages[0]["content"])
        return super().__call__(model, system, messages, tools)


@pytest.fixture
def hooked(monkeypatch):
    """The hook-up lines the coordinator adds to orchestrator.py, until then simulated here."""
    run_task = Orchestrator._run_task
    later = Orchestrator._later_tasks_text

    def _run_task(self, task, tasks):
        self._proof_before(task)  # in _run (and worktrees._lane) before ok = self._run_task(task, tasks)
        return run_task(self, task, tasks)

    def _later_tasks_text(self, task):  # stands in for "+ self._proof_text(task, checks)" after the diff
        return self._proof_text(task) + later(self, task)

    monkeypatch.setattr(Orchestrator, "_run_task", _run_task)
    monkeypatch.setattr(Orchestrator, "_later_tasks_text", _later_tasks_text)


def build_web(tmp_path, brain, raw=RAW):
    from .test_harness import make

    orch, *_rest, events = make(tmp_path, raw=raw, brain=brain)
    calls = []
    orch.shot_renderer = fake_renderer(calls)
    orch.start("a tiny timer page")
    assert orch.run() == "done"
    return orch, events, calls


def test_a_finished_task_has_proof_with_both_sides_and_the_words(tmp_path, hooked):
    brain = SeeingWebBrain()
    orch, events, calls = build_web(tmp_path, brain)
    root = orch.project.root
    w1, w2 = proof.read(root, "W1"), proof.read(root, "W2")
    assert w1["ok"] is True and w2["ok"] is True
    # W1 started from an empty folder (no screens yet): nothing before, every picture new
    assert w1["before"] is None and all(p["words"] == "new" for p in w1["pairs"])
    # W2 started where W1 finished: W1's pictures reused as its before, so no extra render
    assert w2["before"]["reused"] is True and w2["before"]["commit"] == w2["before"]["commit"] != ""
    assert {p["kind"] for p in w2["pairs"]} == {"desktop", "phone", "dark"}
    assert next(p for p in w2["pairs"] if p["kind"] == "dark")["words"] == "new"
    assert len(calls) == 2  # one render per task: the review's pictures are the task's pictures
    assert w2["words"] == "A model that can see checked: the page is there."
    assert w2["judge"]["model"] == "a/reviewer" and len(brain.judged) == 2
    # the verdict reached the review prompt as advice
    assert all("# Proof: the app before and after this task" in p and "shows_it" in p for p in brain.review_prompts)
    # the Live tab's pictures are the approved ones, with their commit
    latest = showit.latest(root)
    assert latest["task"] == "W2" and latest["commit"]
    assert any(k == "proof" and d["task"] == "W2" for k, d in events)


def test_the_judge_never_fails_a_task_by_itself(tmp_path, hooked):
    brain = SeeingWebBrain(verdict="does_not")
    orch, events, _ = build_web(tmp_path, brain)
    assert [t.status for t in orch.project.tasks()] == ["done", "done"]
    rec = proof.read(orch.project.root, "W1")
    assert rec["judge"]["verdict"] == "does_not" and "doesn't think it shows: it is blank" in rec["words"]
    assert "Don't reject only because of it" in brain.review_prompts[0]


def test_strict_proof_tells_the_reviewer(tmp_path, hooked):
    brain = SeeingWebBrain(verdict="does_not")
    raw = {**json.loads(json.dumps(RAW)), "proof": {"strict": True}}
    build_web(tmp_path, brain, raw=raw)
    assert "strict proof" in brain.review_prompts[0]


def test_proof_off_leaves_show_it_as_it_was(tmp_path, hooked):
    brain = SeeingWebBrain()
    raw = {**json.loads(json.dumps(RAW)), "proof": {"enabled": False}}
    orch, _, calls = build_web(tmp_path, brain, raw=raw)
    assert proof.read(orch.project.root, "W1") is None and brain.judged == [] and len(calls) == 2
    assert all("# Proof" not in p for p in brain.review_prompts)


def test_without_the_hook_up_a_finished_task_still_gets_its_after_side(tmp_path):
    orch, _, calls = build_web(tmp_path, WebBrain())
    rec = proof.read(orch.project.root, "W2")
    assert rec["after"]["pictures"] and rec["words"].startswith("Nobody looked at the pictures")


def test_the_hub_carries_the_proof_words(tmp_path, hooked):
    from .test_harness import make

    orch, *_rest, events = make(tmp_path, raw=hub_raw(tmp_path), brain=SeeingWebBrain())
    orch.shot_renderer = fake_renderer()
    orch.start("a tiny timer page")
    assert orch.run() == "done"
    hub = orch._hub()
    latest = hub.store.read_json(f"plans/shots/{orch._hub_name()}/latest.json")
    assert latest["proof"]["words"] == "A model that can see checked: the page is there."
    assert latest["history"][0]["proof"] == latest["proof"]["words"]


# -- the API ---------------------------------------------------------------------------------------------
def test_the_api_gives_one_tasks_proof_and_the_list(tmp_path, hooked, monkeypatch):
    import yaml

    from roundtable.ui import server
    from roundtable.ui.server import ApiError, UIApp

    from .test_hub import RAW as HUB_RAW

    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "proofapi"))
    h = json.loads(json.dumps(HUB_RAW))
    h["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
    (tmp_path / "hub.yaml").write_text(yaml.safe_dump(h), encoding="utf-8")
    orch, _, _ = build_web(tmp_path, SeeingWebBrain())
    cfg = orch.cfg
    cfg.lab_dir = tmp_path / "lab"
    orch._register_with_lab()
    app = UIApp(str(tmp_path / "hub.yaml"), "missing.yaml", agent="backend")
    app.cfg = lambda: cfg
    path = str(orch.project.root)
    one = app.dispatch("GET", "/api/proof", {"path": [path], "task": ["W2"], "inline": ["1"]}, {})
    assert one["found"] and one["words"].startswith("A model that can see checked")
    assert set(one["images"]["before"]) == {"desktop", "phone"} and one["images"]["after"]["dark"].startswith("data:image/")
    listing = app.dispatch("GET", "/api/proof/list", {"path": [path]}, {})
    assert [i["task"] for i in listing["items"]] == ["W2", "W1"] and listing["items"][0]["verdict"] == "shows_it"
    none = app.dispatch("GET", "/api/proof", {"path": [path], "task": ["W9"]}, {})
    assert none["found"] is False and "once the task is finished" in none["words"]
    with pytest.raises(ApiError):
        app.dispatch("GET", "/api/proof", {"path": [path], "task": ["../x"]}, {})
    with pytest.raises(ApiError):
        app.dispatch("GET", "/api/proof", {"path": [str(tmp_path / "elsewhere")], "task": ["W1"]}, {})
    assert "/api/proof" in app.dispatch("GET", "/api/features", {}, {})["routes"]


# -- a kind's proof list ---------------------------------------------------------------------------------
KIND_PROOF = [
    {"id": "starts", "how": "page_opens", "words": "It opens with no errors"},
    {"id": "tests", "how": "command", "command": "npm test", "optional": True, "words": "Its tests pass"},
    {"id": "plays", "how": "play", "seconds": 60, "status": "not_yet", "words": "Played for a minute"},
    {"id": "looks", "how": "pictures", "words": "It looks like the idea"},
    {"id": "starts", "how": "page_opens", "words": "a duplicate is dropped"},
    "not an item",
]


def test_plan_for_takes_a_kinds_proof_list():
    plan = proof.plan_for(KIND_PROOF)
    assert [p["id"] for p in plan] == ["starts", "tests", "plays", "looks"]
    assert plan[1]["optional"] and plan[1]["command"] == "npm test" and plan[2]["seconds"] == 60
    assert [p["checkable"] for p in plan] == [True, True, False, True]
    assert proof.plan_for(None) == [] and proof.plan_for([{"how": "page_opens"}]) == []


def test_proof_lines_from_a_record():
    plan = proof.plan_for(KIND_PROOF)
    rec = {"after": {"pictures": {"desktop": "desktop.png"}, "errors": []},
           "judge": {"looked": True, "verdict": "shows_it"},
           "tests": {"command": "npm test", "verdict": "pass", "after": {"ok": True}}}
    lines = proof.lines(plan, rec)
    assert [ln["passed"] for ln in lines] == [True, True, None, True]
    assert proof.all_passed(lines)  # "plays" is not yet: it doesn't count, and isn't passed either
    assert proof.lines_text(lines) == ("It opens with no errors ✓ · Its tests pass ✓ · Played for a minute – not "
                                       "checked yet · It looks like the idea ✓")
    broken = proof.lines(plan, {**rec, "after": {"pictures": {"desktop": "d.png"}, "errors": ["boom"]}})
    assert broken[0]["passed"] is False and not proof.all_passed(broken)
    other_cmd = proof.lines(plan, {**rec, "tests": {**rec["tests"], "command": "pytest"}})
    assert other_cmd[1]["passed"] is None
    assert not proof.all_passed(proof.lines(plan, {}))


def test_a_kinds_plan_is_used_when_the_orchestrator_has_one(tmp_path, hooked, monkeypatch):
    monkeypatch.setattr(Orchestrator, "_kind_proof", lambda self: KIND_PROOF, raising=False)
    orch, _, _ = build_web(tmp_path, SeeingWebBrain())
    rec = proof.read(orch.project.root, "W1")
    # W1's page errors (the fake renderer reports one on the phone) mean "opens with no errors" failed
    assert [ln["id"] for ln in rec["lines"]] == ["starts", "tests", "plays", "looks"]
    assert rec["lines"][0]["passed"] is False and rec["lines"][3]["passed"] is True
