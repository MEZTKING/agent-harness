import json

import pytest
import yaml

from roundtable.harness.config import load_config, parse_config
from roundtable.harness.orchestrator import Orchestrator
from roundtable.improve.analysis import analyze, collect, rule_proposals
from roundtable.improve.evaluate import EvalError, evaluate, find_base_commit
from roundtable.improve.lab import Lab, Proposal
from roundtable.improve.loop import cycle
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider, reply

from .test_harness import RAW, Brain, tool_names

GOOD_PROMPT = "You are a careful engineer. Always read files before editing them, and run the tests before finishing."


class Judge(Brain):
    """Reviewer approves only work written by `good_model`."""

    def __init__(self, good_model="coder2", **kw):
        super().__init__(**kw)
        self.good_model = good_model

    def __call__(self, model, system, messages, tools):
        names = tool_names(tools)
        if "submit_review" in names and messages[-1]["role"] == "user":
            ok = f"# {self.good_model}" in messages[0]["content"]
            return reply(calls=[("submit_review", {"approved": ok, "feedback": "good" if ok else "sloppy work"})])
        return super().__call__(model, system, messages, tools)


def make_cfg(tmp_path, raw=RAW, brain=None, improve=None):
    raw = json.loads(json.dumps(raw))
    raw["improve"] = improve or {"min_samples": 2}
    cfg = parse_config(raw)
    cfg.lab_dir = tmp_path / "lab"
    brain = brain or Judge()
    a, b = ScriptedProvider("a", brain), ScriptedProvider("b", brain)
    cfg.register("a", a)
    cfg.register("b", b)
    cfg.register("img", ScriptedImages())
    return cfg, Lab(cfg.lab_dir)


def run_projects(cfg, tmp_path, n=2):
    for i in range(n):
        orch = Orchestrator(cfg, tmp_path / f"p{i}")
        orch.start(f"goal {i}")
        assert orch.run() == "done"


def test_projects_register_and_base_commits_recorded(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    run_projects(cfg, tmp_path, 1)
    assert lab.projects() == [(tmp_path / "p0").resolve()]
    tasks = json.loads((tmp_path / "p0/.harness/tasks.json").read_text())
    t1 = next(t for t in tasks if t["id"] == "T1")
    assert t1["base_commit"]
    # fallback lookup for older runs without base_commit
    assert find_base_commit(tmp_path / "p0", {**t1, "base_commit": None}) == t1["base_commit"]


def test_stats_and_rule_proposal_promotes_better_fallback(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    run_projects(cfg, tmp_path, 2)  # coder rejected every time, coder2 approved
    ds = collect(lab)
    primary, fallback = ds.stats[("coder", "a/coder")], ds.stats[("coder", "b/coder2")]
    assert primary.quality == 0.0 and fallback.quality == 1.0
    assert len(ds.rejections) >= 4 and "sloppy" in ds.rejections[0]["feedback"]
    props = rule_proposals(cfg, ds)
    assert len(props) == 1
    p = props[0]
    assert p.kind == "routing" and p.role == "coder" and p.change == {"models": ["b/coder2", "a/coder"]}
    assert p.risk == "low"


def test_analyze_dedupes(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    run_projects(cfg, tmp_path, 2)
    _, first, _ = analyze(cfg, lab)
    _, second, _ = analyze(cfg, lab)
    assert len(first) == 1 and second == []


def test_apply_overlay_and_rollback(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    p1 = lab.add_proposal(Proposal(id="", kind="routing", role="coder", change={"models": ["b/coder2"]},
                                   rationale="r", risk="low"))
    p2 = lab.add_proposal(Proposal(id="", kind="prompt", role="coder", change={"prompt_text": GOOD_PROMPT},
                                   rationale="r", risk="medium"))
    v1 = lab.apply(p1, cfg)
    v2 = lab.apply(p2, cfg)
    assert (v1, v2) == (1, 2)

    fresh = parse_config(json.loads(json.dumps(RAW)))
    lab.apply_learned(fresh)
    assert [str(m) for m in fresh.roles["coder"].models] == ["b/coder2"]
    assert fresh.prompt_text("coder") == GOOD_PROMPT

    lab.rollback()  # undo the prompt only
    fresh = parse_config(json.loads(json.dumps(RAW)))
    lab.apply_learned(fresh)
    assert [str(m) for m in fresh.roles["coder"].models] == ["b/coder2"]
    assert fresh.prompt_text("coder") != GOOD_PROMPT
    assert lab.proposal(p2.id).status == "rolled_back"

    lab.rollback(1)  # back to the beginning
    fresh = parse_config(json.loads(json.dumps(RAW)))
    lab.apply_learned(fresh)
    assert [str(m) for m in fresh.roles["coder"].models] == ["a/coder", "b/coder2"]
    with pytest.raises(ValueError):
        lab.rollback()
    assert [h["event"] for h in lab.history()] == ["applied", "applied", "rolled_back", "rolled_back"]


def test_learned_overlay_loads_with_config_file(tmp_path):
    raw = json.loads(json.dumps(RAW))
    (tmp_path / "harness.yaml").write_text(yaml.safe_dump(raw))
    cfg = load_config(str(tmp_path / "harness.yaml"))
    assert cfg.lab_dir == tmp_path / ".harness-lab"
    lab = Lab(cfg.lab_dir)
    lab.apply(Proposal(id="P1", kind="routing", role="coder", change={"models": ["b/coder2", "a/coder"]},
                       rationale="r", risk="low"), cfg)
    again = load_config(str(tmp_path / "harness.yaml"))
    assert [str(m) for m in again.roles["coder"].models] == ["b/coder2", "a/coder"]
    assert yaml.safe_load((tmp_path / "harness.yaml").read_text()) == raw  # harness.yaml untouched


def test_candidate_config_does_not_touch_base(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    p = Proposal(id="X", kind="prompt", role="coder", change={"prompt_text": GOOD_PROMPT}, rationale="r")
    cand = lab.candidate_config(cfg, p)
    assert cand.prompt_text("coder") == GOOD_PROMPT
    assert cfg.prompt_text("coder") != GOOD_PROMPT
    assert cand._instances is cfg._instances


def test_proposal_validation(tmp_path):
    cfg, _ = make_cfg(tmp_path)
    bad = [
        Proposal(id="", kind="routing", role="coder", change={"models": ["zz/m"]}, rationale=""),
        Proposal(id="", kind="routing", role="ghost", change={"models": ["a/x"]}, rationale=""),
        Proposal(id="", kind="prompt", role="coder", change={"prompt_text": "short"}, rationale=""),
        Proposal(id="", kind="prompt", role="designer", change={"prompt_text": GOOD_PROMPT}, rationale=""),
        Proposal(id="", kind="magic", role="coder", change={}, rationale=""),
    ]
    for p in bad:
        with pytest.raises(ValueError):
            p.validate(cfg)


def test_replay_evaluation_prefers_better_model(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    run_projects(cfg, tmp_path, 1)
    good = lab.add_proposal(Proposal(id="", kind="routing", role="coder", change={"models": ["b/coder2"]},
                                     rationale="r", risk="low"))
    res = evaluate(cfg, lab, good, samples=2, max_cost=5)
    assert res["tasks_compared"] == 2
    assert res["current"]["approved"] == 0 and res["candidate"]["approved"] == 2
    assert res["verdict"] == "better" and res["passed"]
    assert lab.proposal(good.id).status == "tested"
    # replays never touch the real project
    assert len(json.loads((tmp_path / "p0/.harness/tasks.json").read_text())) == 3

    bad = lab.add_proposal(Proposal(id="", kind="routing", role="coder", change={"models": ["a/coder"]},
                                    rationale="r", risk="low"))
    cfg.roles["coder"].models = cfg.roles["coder"].models[1:]  # pretend coder2 is current
    res = evaluate(cfg, lab, bad, samples=1, max_cost=5)
    assert res["verdict"] == "worse" and not res["passed"]


def test_replay_guards(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    p = Proposal(id="R", kind="routing", role="coder", change={"models": ["b/coder2"]}, rationale="r")
    with pytest.raises(EvalError):
        evaluate(cfg, lab, p)  # no history yet
    rev = Proposal(id="V", kind="routing", role="reviewer", change={"models": ["b/x"]}, rationale="r")
    with pytest.raises(EvalError):
        evaluate(cfg, lab, rev)


def test_cycle_policy(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    run_projects(cfg, tmp_path, 2)
    report = cycle(cfg, lab)  # default policy: none
    assert len(report["new"]) == 1 and report["applied"] == []

    cfg.improve["auto_apply"] = "low"
    report = cycle(cfg, lab)
    assert len(report["applied"]) == 1
    assert [str(m) for m in cfg.roles["coder"].models] == ["b/coder2", "a/coder"]


def test_cycle_with_tests_and_llm_analyst(tmp_path):
    brain = Judge()

    def analyst_aware(model, system, messages, tools):
        if "submit_proposals" in tool_names(tools):
            if messages[-1]["role"] == "user":
                return reply(calls=[("submit_proposals", {"proposals": [
                    {"kind": "prompt", "role": "coder", "prompt_text": GOOD_PROMPT, "rationale": "reviews say sloppy",
                     "risk": "medium"},
                    {"kind": "routing", "role": "coder", "models": ["nope/x"], "rationale": "bad", "risk": "low"},
                ]})])
            return reply("done")
        return brain(model, system, messages, tools)

    cfg, lab = make_cfg(tmp_path, brain=analyst_aware, improve={"min_samples": 2, "auto_apply": "medium"})
    run_projects(cfg, tmp_path, 1)
    report = cycle(cfg, lab, use_llm=True, test=True, max_cost=50, samples=1)
    kinds = sorted(lab.proposal(i).source for i in report["new"])
    assert kinds == ["llm", "rules"]  # the invalid LLM proposal was dropped
    verdicts = {t["id"]: t for t in report["tested"]}
    assert len(verdicts) == 2
    rules_id = next(i for i in report["new"] if lab.proposal(i).source == "rules")
    assert verdicts[rules_id]["passed"]
    # the prompt change doesn't help this judge (it only cares about the model) -> not applied
    applied = {a["id"] for a in report["applied"]}
    assert rules_id in applied
    assert all(lab.proposal(i).status != "applied" for i in report["new"] if lab.proposal(i).source == "llm")


def test_owner_feedback_is_collected(tmp_path, capsys):
    from roundtable.harness_cli import main

    cfg, lab = make_cfg(tmp_path)
    run_projects(cfg, tmp_path, 1)
    main(["feedback", str(tmp_path / "p0"), "T1", "--bad", "ugly code"])
    ds = collect(lab)
    assert ds.owner_feedback[0]["note"] == "ugly code"
    assert ds.stats[("coder", "b/coder2")].owner_bad == 1


def test_owner_propose_cli(tmp_path, capsys):
    from roundtable.harness_cli import main

    raw = json.loads(json.dumps(RAW))
    (tmp_path / "harness.yaml").write_text(yaml.safe_dump(raw))
    cfg_path = str(tmp_path / "harness.yaml")
    main(["--config", cfg_path, "improve", "propose", "coder", "--models", "b/coder2,a/coder", "--risk", "low"])
    main(["--config", cfg_path, "improve", "propose", "coder", "--options", '{"temperature": 0.2}'])
    lab = Lab(tmp_path / ".harness-lab")
    props = {p.kind: p for p in lab.proposals()}
    assert {p.source for p in props.values()} == {"owner"}
    assert props["options"].change == {"options": {"temperature": 0.2}}
    routing = props["routing"].id
    with pytest.raises(SystemExit):  # owner routing proposal isn't rule-backed: needs a test or --force
        main(["--config", cfg_path, "improve", "apply", routing, "--skip-probe"])
    main(["--config", cfg_path, "improve", "apply", routing, "--force", "--skip-probe"])
    assert [str(m) for m in load_config(cfg_path).roles["coder"].models] == ["b/coder2", "a/coder"]


def test_rule_spots_a_fallback_that_keeps_rescuing_a_cheap_primary(tmp_path):
    from roundtable.improve.analysis import Dataset, ModelStats

    cfg, _ = make_cfg(tmp_path)
    ds = Dataset()
    # the music player's numbers: the cheap model finished 7 of 17, the fallback 4 of 4
    ds.stats[("coder", "a/coder")] = ModelStats("coder", "a/coder", attempts=17, approved=7, other_fail=10,
                                                cost=17 * 0.117, priced_attempts=17)
    ds.stats[("coder", "b/coder2")] = ModelStats("coder", "b/coder2", attempts=4, approved=4,
                                                 cost=4 * 0.19, priced_attempts=4)
    props = rule_proposals(cfg, ds)
    assert len(props) == 1 and props[0].change == {"models": ["b/coder2", "a/coder"]}
    assert "41%" in props[0].rationale and "$0.19" in props[0].rationale and "$0.28" in props[0].rationale
    ds.stats[("coder", "b/coder2")].cost = 4 * 2.0  # rescuing, but dearer per finished task: not this rule
    assert all("finished only" not in p.rationale for p in rule_proposals(cfg, ds))
