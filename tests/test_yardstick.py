"""The yardstick, reviewer tests, and learning from the panel (wave 7, d4-evidence). Made-up everything."""

import json
from pathlib import Path

import pytest
import yaml

from roundtable.harness.agent import Budget
from roundtable.harness.config import parse_config
from roundtable.harness.orchestrator import Orchestrator
from roundtable.improve import analysis, evaluate as ev, yardstick
from roundtable.improve.analysis import collect, llm_proposals, rule_proposals, stats_table
from roundtable.improve.evaluate import EvalError, evaluate
from roundtable.improve.lab import Lab, Proposal
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider, reply

from .test_harness import RAW, tool_names
from .test_improve import Judge, run_projects

CAREFUL = "CAREFUL MARKER: read the task twice, write the whole answer, then check it before finishing."


def _solution(tid):
    t = next(x for x in yardstick.load() if x.id == tid)
    out = {}
    for f in sorted((t.dir / "solution").rglob("*")):
        if f.is_file():
            rel = str(f.relative_to(t.dir / "solution"))
            out[rel[:-4] if rel.endswith(".py.txt") else rel] = f.read_text(encoding="utf-8")
    return out


TRUTH = {t.id: t for t in yardstick.load("reviewer")}


class YBrain:
    """A scripted team for the yardstick. ``good(model, system)`` says who does the work properly."""

    def __init__(self, good=lambda model, system: True, sharp=lambda model: True, planner_ok=True):
        self.good, self.sharp, self.planner_ok = good, sharp, planner_ok
        self.models = []

    def __call__(self, model, system, messages, tools):
        self.models.append(model)
        names = tool_names(tools)
        last = messages[-1]
        prompt = messages[0]["content"]
        if "submit_plan" in names:
            if last["role"] == "tool":
                return reply("planned")
            goal = prompt.split("Plan the work for goal #1: ", 1)[1].split("\n", 1)[0]
            first = goal.split(". ")[0]
            tasks = [{"id": "T1", "title": "First slice", "role": "coder", "description": f"Build: {first}.",
                      "acceptance": "It starts and shows the first screen" if self.planner_ok else "",
                      "depends_on": [], "stage": "M1"},
                     {"id": "T2", "title": "The rest", "role": "coder", "description": f"Finish: {first}.",
                      "acceptance": "Every part of the idea works" if self.planner_ok else "",
                      "depends_on": ["T1"], "stage": "M2"}]
            stages = [{"id": "M1", "title": "Slice", "shows": "it starts"},
                      {"id": "M2", "title": "All", "shows": "everything"}] if self.planner_ok else []
            return reply(calls=[("submit_plan", {"tasks": tasks, "stages": stages})])
        if "submit_review" in names:
            if last["role"] == "tool":
                return reply("ok")
            tid = prompt.split("# Task [", 1)[1].split("]", 1)[0]
            t = TRUTH.get(tid)
            if t is None or not self.sharp(model) or t.extra["truth"] == "approve":
                return reply(calls=[("submit_review", {"approved": True, "feedback": "looks right"})])
            return reply(calls=[("submit_review", {"approved": False, "breaks": t.acceptance,
                                                   "feedback": f"This line is wrong: {t.extra['planted']}"})])
        if "finish_task" in names:
            tid = prompt.split("# Your task [", 1)[1].split("]", 1)[0]
            if last["role"] == "user" and self.good(model, system):
                files = _solution(tid) if tid in {t.id for t in yardstick.load("builder")} else {"x.txt": "x"}
                return reply(calls=[("write_file", {"path": p, "content": c}) for p, c in files.items()])
            return reply(calls=[("finish_task", {"summary": f"{tid} done"})])
        if "submit_proposals" in names:
            return reply(calls=[("submit_proposals", {"proposals": []})]) if last["role"] == "user" else reply("ok")
        return reply("done")


def ycfg(tmp_path, brain, raw=RAW, improve=None):
    raw = json.loads(json.dumps(raw))
    raw["improve"] = improve or {"min_samples": 2, "yardstick_runs": 1}
    cfg = parse_config(raw)
    cfg.lab_dir = tmp_path / "lab"
    cfg.register("a", ScriptedProvider("a", brain))
    cfg.register("b", ScriptedProvider("b", brain))
    cfg.register("img", ScriptedImages())
    return cfg, Lab(cfg.lab_dir)


def test_the_set_is_sound_and_large_enough():
    assert yardstick.check_set() == []
    assert len(yardstick.load("builder")) >= 12
    reviewer = yardstick.load("reviewer")
    assert len(reviewer) == 8 and sorted(t.extra["truth"] for t in reviewer).count("reject") == 4
    assert len(yardstick.load("planner")) >= yardstick.MIN_FOR_PROMPT
    for t in yardstick.load():
        assert not any(t.dir.glob("**/test_*.py")), "the set's files must never look like the harness's own tests"


def test_which_job_and_how_many(tmp_path):
    cfg, _ = ycfg(tmp_path, YBrain())
    assert yardstick.job_for(cfg, "coder") == "builder" and yardstick.available(cfg, "coder") >= 12
    assert yardstick.job_for(cfg, "reviewer") == "reviewer" and yardstick.available(cfg, "reviewer") == 8
    assert yardstick.job_for(cfg, "orchestrator") == "planner"
    assert yardstick.available(cfg, "designer") == 0  # an image role has nothing objective to measure


def test_a_good_builder_passes_every_task_and_a_lazy_one_fails_each(tmp_path):
    good, lazy = YBrain(), YBrain(good=lambda m, s: False)
    for brain, want in ((good, True), (lazy, False)):
        cfg, _ = ycfg(tmp_path / str(want), brain)
        for t in yardstick.load("builder"):
            row = yardstick.run_one(cfg, t, "coder", Budget(5))
            assert row["passed"] is want, (t.id, row)
            assert row["steps"] >= 1 and row["cost_usd"] > 0


def test_hidden_checks_are_not_in_the_folder_while_the_builder_works(tmp_path, monkeypatch):
    seen = []
    real = Orchestrator._attempt_loop

    def spy(self, task, tasks, models, **kw):
        seen.append(sorted(p.name for p in self.project.root.iterdir()))
        out = real(self, task, tasks, models, **kw)
        seen.append(sorted(p.name for p in self.project.root.iterdir()))
        return out

    monkeypatch.setattr(Orchestrator, "_attempt_loop", spy)
    cfg, _ = ycfg(tmp_path, YBrain())
    t = next(x for x in yardstick.load("builder") if x.id == "b01-mean-bug")
    assert yardstick.run_one(cfg, t, "coder", Budget(5))["passed"]
    assert "check_mean.py" not in seen[0] and "check_mean.py" not in seen[1]


def test_an_empty_lab_can_test_a_prompt(tmp_path):
    brain = YBrain(good=lambda m, s: "CAREFUL MARKER" in s)
    cfg, lab = ycfg(tmp_path, brain)
    p = lab.add_proposal(Proposal(id="", kind="prompt", role="coder", change={"prompt_text": CAREFUL},
                                  rationale="r", risk="low", source="llm"))
    res = evaluate(cfg, lab, p, max_cost=50)
    assert res["tasks_compared"] == 0 and res["yardstick_compared"] >= yardstick.MIN_FOR_PROMPT
    y = res["yardstick"]
    assert y["current"]["passed"] == 0 and y["candidate"]["passed"] == y["n"]
    assert res["verdict"] == "better" and res["passed"]
    assert lab.proposal(p.id).status == "tested"


def test_a_prompt_change_needs_six_tasks(tmp_path, monkeypatch):
    brain = YBrain(good=lambda m, s: "CAREFUL MARKER" in s)
    cfg, lab = ycfg(tmp_path, brain)
    few = yardstick.load("builder")[:3]
    monkeypatch.setattr(yardstick, "load", lambda job=None, root=None: few if job in (None, "builder") else [])
    p = lab.add_proposal(Proposal(id="", kind="prompt", role="coder", change={"prompt_text": CAREFUL},
                                  rationale="r", risk="low"))
    res = evaluate(cfg, lab, p, max_cost=50)
    assert res["yardstick_compared"] == 3 and not res["passed"]
    assert "at least 6" in res["note"]


def test_a_candidate_reviewer_that_approves_a_planted_fault_is_vetoed(tmp_path):
    raw = json.loads(json.dumps(RAW))
    raw["roles"]["reviewer"] = {"model": "a/reviewer", "fallback": ["b/lenient"]}
    brain = YBrain(sharp=lambda model: model != "lenient")
    cfg, lab = ycfg(tmp_path, brain, raw=raw)
    p = lab.add_proposal(Proposal(id="", kind="routing", role="reviewer",
                                  change={"models": ["b/lenient", "a/reviewer"]}, rationale="cheaper", risk="low"))
    res = evaluate(cfg, lab, p, max_cost=50)  # no longer refused: tested on the reviewer's yardstick
    y = res["yardstick"]
    assert y["job"] == "reviewer" and y["n"] == 8
    assert y["current"]["passed"] == 8 and y["current"]["faults_approved"] == 0
    assert y["candidate"]["faults_approved"] == 4
    assert res["verdict"] == "vetoed" and not res["passed"] and "planted" in res["note"]

    # the other way round: a sharper reviewer is better, and nothing is vetoed
    back = lab.add_proposal(Proposal(id="", kind="routing", role="reviewer",
                                     change={"models": ["a/reviewer", "b/lenient"]}, rationale="r", risk="low"))
    cfg.roles["reviewer"].models = cfg.roles["reviewer"].models[::-1]
    res = evaluate(cfg, lab, back, max_cost=50)
    assert res["verdict"] == "better" and res["passed"] and not res["yardstick"]["veto"]


def test_a_rejection_must_quote_the_planted_line(tmp_path):
    class Vague(YBrain):
        def __call__(self, model, system, messages, tools):
            if "submit_review" in tool_names(tools) and messages[-1]["role"] == "user":
                return reply(calls=[("submit_review", {"approved": False, "feedback": "something is off"})])
            return super().__call__(model, system, messages, tools)

    cfg, _ = ycfg(tmp_path, Vague())
    fault = TRUTH["r02-even-fault"]
    row = yardstick.run_one(cfg, fault, "reviewer", Budget(5))
    assert not row["passed"] and "quoting" in row["note"]


def test_the_planner_is_checked_by_shape(tmp_path):
    for ok in (True, False):
        cfg, _ = ycfg(tmp_path / str(ok), YBrain(planner_ok=ok))
        for t in yardstick.load("planner"):
            row = yardstick.run_one(cfg, t, "orchestrator", Budget(5))
            assert row["passed"] is ok, (t.id, row)


def test_the_planner_breaking_the_dont_list_fails(tmp_path):
    t = next(x for x in yardstick.load("planner") if x.id == "p01-todo-page")
    from roundtable.harness.orchestrator import Task

    tasks = [Task(id="T1", title="Log-in page", role="coder", description="Add accounts with a log-in",
                  acceptance="You can sign in and keep items saved"),
             Task(id="T2", title="List", role="coder", description="The list itself, saved", acceptance="Items stay")]
    ok, notes = yardstick.plan_shape(t, tasks, {"stages": [{"id": "M1"}, {"id": "M2"}]})
    assert not ok and any("don't list" in n for n in notes)


def test_saved_current_results_are_reused_and_expire(tmp_path, monkeypatch):
    few = yardstick.load("builder")[:3]
    monkeypatch.setattr(yardstick, "load", lambda job=None, root=None: few)
    brain = YBrain(good=lambda m, s: "CAREFUL MARKER" in s)
    cfg, lab = ycfg(tmp_path, brain)
    p = lab.add_proposal(Proposal(id="", kind="prompt", role="coder", change={"prompt_text": CAREFUL},
                                  rationale="r", risk="low"))
    first = yardstick.run(cfg, lab, p, Budget(50), runs=1)
    assert first["reused"] == 0
    calls = len(brain.models)
    second = yardstick.run(cfg, lab, p, Budget(50), runs=1)
    assert second["reused"] == first["n"]  # the current side is not paid for again
    assert second["current"] == first["current"]
    assert len(brain.models) - calls < calls  # only the candidate ran again
    # older than 14 days: run again
    path = lab.root / yardstick.RESULTS
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    path.write_text("".join(json.dumps({**r, "at": "2020-01-01T00:00:00Z"}) + "\n" for r in rows), encoding="utf-8")
    third = yardstick.run(cfg, lab, p, Budget(50), runs=1)
    assert third["reused"] == 0
    # a different current set-up (another first model) never reuses them
    assert yardstick.fingerprint(cfg, "coder") != yardstick.fingerprint(lab.candidate_config(cfg, p), "coder")


def test_the_budget_stops_the_yardstick_and_only_whole_pairs_count(tmp_path):
    cfg, lab = ycfg(tmp_path, YBrain())
    p = Proposal(id="X", kind="routing", role="coder", change={"models": ["b/coder2"]}, rationale="r", risk="low")
    res = yardstick.run(cfg, lab, p, Budget(0.002), runs=1)
    assert res["note"].startswith("stopped early")
    assert res["n"] < len(yardstick.load("builder"))
    assert all(r["current"]["of"] == 1 and r["candidate"]["of"] == 1 for r in res["tasks"])


def test_equal_results_no_longer_pass(tmp_path):
    cfg, lab = ycfg(tmp_path, YBrain())
    p = lab.add_proposal(Proposal(id="", kind="options", role="coder", change={"options": {"effort": "low"}},
                                  rationale="r", risk="low"))
    res = evaluate(cfg, lab, p, max_cost=50)
    assert res["yardstick"]["verdict"] == "equal"
    assert res["verdict"] == "equal" and not res["passed"]


def test_a_private_repository_is_not_replayed_on_a_maker_that_has_not_seen_it(tmp_path, monkeypatch):
    cfg, lab = ycfg(tmp_path, Judge())
    run_projects(cfg, tmp_path, 1)
    meta_path = tmp_path / "p0/.harness/project.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["repository"] = {"branch": "roundtable/work", "start_branch": "main"}  # one of the owner's own apps
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    seen = [{"maker": "a"}]
    monkeypatch.setattr(ev.usage, "seen", lambda root, home=None: list(seen))
    p = lab.add_proposal(Proposal(id="", kind="routing", role="coder", change={"models": ["b/coder2"]},
                                  rationale="r", risk="low"))
    with pytest.raises(EvalError):
        evaluate(cfg, lab, p, samples=2, max_cost=5, yard=False)  # b has never seen this code
    seen.append({"maker": "b"})
    res = evaluate(cfg, lab, p, samples=2, max_cost=5, yard=False)
    assert res["tasks_compared"] >= 1


def test_the_analyst_sees_no_text_from_a_project_that_does_not_allow_its_maker(tmp_path):
    from roundtable.harness import projectsettings as ps

    prompts = []

    def analyst(model, system, messages, tools):
        if "submit_proposals" in tool_names(tools):
            prompts.append(messages[0]["content"])
            return reply(calls=[("submit_proposals", {"proposals": []})]) if messages[-1]["role"] == "user" \
                else reply("ok")
        return Judge()(model, system, messages, tools)

    cfg, lab = ycfg(tmp_path, analyst)
    run_projects(cfg, tmp_path, 2)  # the Judge rejects a/coder's work: rejection texts in both projects
    tasks_file = tmp_path / "p0/.harness/tasks.json"
    tasks = json.loads(tasks_file.read_text(encoding="utf-8"))
    for t in tasks:
        t["title"] = f"PRIVATEP0 {t['title']}"
    tasks_file.write_text(json.dumps(tasks), encoding="utf-8")
    llm_proposals(cfg, collect(lab), lab, max_cost=5)
    assert "PRIVATEP0" in prompts[-1]  # allowed: shown
    ps.update(tmp_path / "p0", {"makers_allowed": ["b"]})  # the analyst (a/planner) may not see p0
    ds = collect(lab)
    assert {r["project"] for r in ds.rejections} == {"p0", "p1"}
    llm_proposals(cfg, ds, lab, max_cost=5)
    text = prompts[-1]
    assert "PRIVATEP0" not in text and str(tmp_path / "p0") not in text
    assert "sloppy work" in text  # p1's rejections are still shown


def _reviews(proj: Path, groups):
    """Write a made-up reviews.jsonl: groups of (checker verdicts, decision)."""
    rows = []
    for i, (verdicts, decision) in enumerate(groups):
        at = f"2026-11-0{1 + i % 9}T00:00:{i:02d}Z"
        for model, ok, counted in verdicts:
            rows.append({"at": at, "task": f"T{i}", "role": "coder", "kind": "verdict", "model": model,
                         "builder_maker": "b", "approved": ok, "counted": counted, "breaks": ""})
        rows.append({"at": at, "task": f"T{i}", "role": "coder", "kind": "decision", "approved": decision})
    (proj / ".harness/reviews.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _fake_project(lab, root: Path, metrics=()):
    (root / ".harness").mkdir(parents=True)
    (root / ".harness/project.json").write_text(json.dumps({"goals": ["made up"]}), encoding="utf-8")
    (root / ".harness/tasks.json").write_text("[]", encoding="utf-8")
    (root / ".harness/metrics.jsonl").write_text("".join(json.dumps(r) + "\n" for r in metrics), encoding="utf-8")
    lab.register_project(root)


def test_rule4_moves_an_overruled_checker_to_the_back(tmp_path):
    raw = json.loads(json.dumps(RAW))
    raw["roles"]["reviewer"] = {"model": "a/reviewer", "fallback": ["b/rev2"]}
    cfg, lab = ycfg(tmp_path, YBrain(), raw=raw, improve={"min_samples": 4})
    _fake_project(lab, tmp_path / "proj")
    # a/reviewer rejects, the two others approve: the decision overrules it every time
    _reviews(tmp_path / "proj", [([("a/reviewer", False, True), ("b/rev2", True, True), ("c/x", True, True)], True)
                                 for _ in range(5)])
    ds = collect(lab)
    st = ds.checkers["a/reviewer"]
    assert st.verdicts == 5 and st.overruled == 5 and st.by_builder["b"] == {"verdicts": 5, "overruled": 5}
    found = [p for p in rule_proposals(cfg, ds) if p.role == "reviewer"]
    assert len(found) == 1 and found[0].change == {"models": ["b/rev2", "a/reviewer"]} and found[0].risk == "medium"
    assert "a/reviewer" in stats_table(ds, checkers=True)


def test_rule4_unquoted_rejections_and_not_on_thin_ledgers(tmp_path):
    raw = json.loads(json.dumps(RAW))
    raw["roles"]["reviewer"] = {"model": "a/reviewer", "fallback": ["b/rev2"]}
    cfg, lab = ycfg(tmp_path, YBrain(), raw=raw, improve={"min_samples": 4})
    _fake_project(lab, tmp_path / "proj")
    _reviews(tmp_path / "proj", [([("a/reviewer", False, "unquoted")], False) for _ in range(4)])
    ds = collect(lab)
    assert ds.checkers["a/reviewer"].unquoted_share == 1.0
    assert [p.change for p in rule_proposals(cfg, ds) if p.role == "reviewer"] == [{"models": ["b/rev2", "a/reviewer"]}]

    thin, lab2 = ycfg(tmp_path / "thin", YBrain(), raw=raw, improve={"min_samples": 4})
    _fake_project(lab2, tmp_path / "thin/proj")
    _reviews(tmp_path / "thin/proj", [([("a/reviewer", False, "unquoted")], False) for _ in range(2)])
    assert not [p for p in rule_proposals(thin, collect(lab2)) if p.role == "reviewer"]


def _tagged(model, tag, n, ok):
    return [{"task": f"{model}-{tag}-{i}", "role": "coder", "model": model, "tags": [tag],
             "outcome": "approved" if i < ok else "rejected", "cost_usd": 0.01} for i in range(n)]


def test_rule5_promotes_a_fallback_that_wins_on_three_tags(tmp_path):
    cfg, lab = ycfg(tmp_path, YBrain(), improve={"min_samples": 5})
    rows = []
    for tag in ("ui", "database", "tests"):
        rows += _tagged("a/coder", tag, 5, 2) + _tagged("b/coder2", tag, 5, 5)
    rows += _tagged("a/coder", "docs", 15, 15) + _tagged("b/coder2", "docs", 15, 0)  # overall: a looks better
    _fake_project(lab, tmp_path / "proj", rows)
    ds = collect(lab)
    found = [p for p in rule_proposals(cfg, ds) if p.role == "coder"]
    assert len(found) == 1 and found[0].change == {"models": ["b/coder2", "a/coder"]} and found[0].risk == "low"
    assert [w["tag"] for w in found[0].evidence["tags"]] == ["database", "tests", "ui"]


def test_rule5_not_on_two_tags_or_thin_ones(tmp_path):
    for rows in ([r for tag in ("ui", "database") for r in _tagged("a/coder", tag, 5, 2) + _tagged("b/coder2", tag, 5, 5)]
                 + _tagged("a/coder", "docs", 15, 15) + _tagged("b/coder2", "docs", 15, 0),
                 [r for tag in ("ui", "database", "tests") for r in _tagged("a/coder", tag, 3, 1)
                  + _tagged("b/coder2", tag, 3, 3)] + _tagged("a/coder", "docs", 15, 15) + _tagged("b/coder2", "docs", 15, 0)):
        base = tmp_path / str(len(rows))
        cfg, lab = ycfg(base, YBrain(), improve={"min_samples": 5})
        _fake_project(lab, base / "proj", rows)
        assert not [p for p in rule_proposals(cfg, collect(lab)) if p.role == "coder"]


def test_the_analyst_asks_the_charter(tmp_path, monkeypatch):
    from roundtable.improve import charter

    systems = []

    def brain(model, system, messages, tools):
        if "submit_proposals" in tool_names(tools):
            systems.append(system)
            if messages[-1]["role"] == "user":
                return reply(calls=[("submit_proposals", {"proposals": [{
                    "kind": "prompt", "role": "coder", "risk": "low", "rationale": "seen in /home/someone/secret",
                    "prompt_text": "You are careful. Never copy /home/someone/secret into anything you write."}]})])
            return reply("ok")
        return Judge()(model, system, messages, tools)

    monkeypatch.setattr(charter, "fixed_block", lambda name: "FIXED LINES" if name == "improver" else "")
    monkeypatch.setattr(charter, "scrub", lambda text, lab=None: text.replace("/home/someone/secret", "[a path]"))
    cfg, lab = ycfg(tmp_path, brain)
    run_projects(cfg, tmp_path, 1)
    got, _ = llm_proposals(cfg, collect(lab), lab, max_cost=5)
    assert systems and systems[-1].endswith("FIXED LINES")
    assert got and "/home/someone" not in got[0].rationale and "/home/someone" not in got[0].change["prompt_text"]


def test_evidence_never_changes_what_the_charter_protects(tmp_path, monkeypatch):
    """Testing and analysing never write harness.yaml or the protected parts of custom.yaml, and never apply
    anything: the yardstick and the analysis only measure."""
    from roundtable.improve import charter

    home = tmp_path / "home"
    home.mkdir()
    harness_yaml = home / "harness.yaml"
    custom_yaml = home / "custom.yaml"
    harness_yaml.write_text(yaml.safe_dump(RAW), encoding="utf-8")
    custom_yaml.write_text(yaml.safe_dump({"limits": {"max_cost_usd": 1}, "gate": {"mode": "ask"},
                                           "makers_allowed": ["a"], "providers_allowed": ["a"]}), encoding="utf-8")
    before = {p: p.read_bytes() for p in (harness_yaml, custom_yaml)}
    monkeypatch.setattr(Lab, "apply", lambda *a, **k: pytest.fail("evidence must never apply a change"))
    asked = []
    monkeypatch.setattr(charter, "check", lambda *a, **k: asked.append(a))

    brain = YBrain(good=lambda m, s: "CAREFUL MARKER" in s)
    cfg, lab = ycfg(tmp_path, brain)
    p = lab.add_proposal(Proposal(id="", kind="prompt", role="coder", change={"prompt_text": CAREFUL},
                                  rationale="r", risk="low"))
    evaluate(cfg, lab, p, max_cost=50)
    analysis.analyze(cfg, lab)
    assert {p: p.read_bytes() for p in before} == before
    assert not (lab.root / "learned.yaml").exists() and not (lab.root / "prompts").exists()
    assert [x.name for x in (lab.root / "yardstick").iterdir()] == ["results.jsonl"]
    for line in (lab.root / yardstick.RESULTS).read_text(encoding="utf-8").splitlines():
        row = json.loads(line)  # numbers and made-up ids only: nothing the owner wrote
        assert set(row) <= {"at", "task", "version", "job", "key", "side", "passed", "cost_usd", "steps", "seconds",
                            "approved", "fault_approved"}
    assert cfg.roles["coder"].prompt == "coder" and CAREFUL not in cfg.prompt_text("coder")


def test_better_on_the_yardstick_and_equal_but_dearer_on_replays_passes():
    """The plan's rule: not worse on either, better on one. Equal-but-dearer alone still fails; worse always fails."""
    p = Proposal(id="P1", kind="routing", role="coder", change={"models": ["b/coder2"]}, rationale="made up")
    yard = {"n": 12, "verdict": "better", "veto": "", "current": {"cost_usd": 0.1}, "candidate": {"cost_usd": 0.2}}
    verdict, passed, note = ev._combine(p, {"verdict": "costlier"}, yard)
    assert (verdict, passed) == ("better", True) and "more money" in note
    assert ev._combine(p, {"verdict": "costlier"}, None)[:2] == ("costlier", False)
    assert ev._combine(p, {"verdict": "worse"}, yard)[:2] == ("worse", False)
