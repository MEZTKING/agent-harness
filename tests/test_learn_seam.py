"""Wave 7, step 0: the lab's kinds registry, undo of one change, rebuild, the state id, and the orchestrator's
new seams. The three first kinds must behave exactly as before; a bare Orchestrator must be unchanged."""

import json
from pathlib import Path

import pytest
import yaml

from roundtable.harness import config as hconfig
from roundtable.harness.config import parse_config
from roundtable.harness.orchestrator import Orchestrator
from roundtable.harness.tools import Tool, ToolSpec, _obj
from roundtable.improve import canary, charter, lab as labmod, wallet
from roundtable.improve.lab import KINDS, PROPOSAL_KINDS, STATUSES, KindSpec, Lab, Proposal, register_kind

from .test_harness import RAW, Brain
from .test_improve import GOOD_PROMPT, make_cfg

OTHER_PROMPT = ("You are a tidy engineer. Keep every change small and explain it in one line. No placeholders, no "
                "TODO stubs for required behaviour. Write the tests first and run them with run_command. Then call "
                "finish_task with what you changed.")


def _p(kind, change, role="coder", pid=""):
    return Proposal(id=pid, kind=kind, role=role, change=change, rationale="r", risk="low")


def _three(lab):
    p1 = lab.add_proposal(_p("routing", {"models": ["b/coder2", "a/coder"]}))
    p2 = lab.add_proposal(_p("options", {"options": {"temperature": 0.2}}))
    p3 = lab.add_proposal(_p("prompt", {"prompt_text": GOOD_PROMPT}))
    return p1, p2, p3


def _fresh(lab):
    cfg = parse_config(json.loads(json.dumps(RAW)))
    lab.apply_learned(cfg)
    return cfg


# -- the registry: the three first kinds, unchanged -----------------------------------------------------
def test_the_three_first_kinds_are_in_the_registry_and_the_analysts_enum_is_kept():
    assert PROPOSAL_KINDS == ("routing", "options", "prompt")
    assert set(PROPOSAL_KINDS) <= set(KINDS)
    assert all(KINDS[k].needs_role for k in PROPOSAL_KINDS)
    assert STATUSES == ("proposed", "tested", "applied", "rejected", "rolled_back", "undone", "needs_owner")


def test_old_kinds_lay_summarise_and_validate_exactly_as_before(tmp_path):
    cfg, _ = make_cfg(tmp_path)
    routing = _p("routing", {"models": ["b/coder2", "a/coder"]})
    options = _p("options", {"options": {"effort": "high"}})
    prompt = _p("prompt", {"prompt_text": GOOD_PROMPT})
    overlay, prompts = {}, {}
    for p in (routing, options, prompt):
        Lab.change_overlay(overlay, prompts, p, cfg)
    assert overlay == {"roles": {"coder": {"model": "b/coder2", "fallback": ["a/coder"], "options": {"effort": "high"}}}}
    assert prompts == {"coder": GOOD_PROMPT}
    # a prompt change alone still leaves the role's (empty) entry, as before
    o2, p2 = {}, {}
    Lab.change_overlay(o2, p2, prompt, cfg)
    assert o2 == {"roles": {"coder": {}}} and p2 == {"coder": GOOD_PROMPT}
    assert routing.summary() == "routing coder        b/coder2 -> a/coder"
    assert options.summary() == 'options coder        {"effort": "high"}'
    assert prompt.summary() == f"prompt  coder        new prompt ({len(GOOD_PROMPT)} chars)"
    msgs = {
        "unknown kind 'magic'": _p("magic", {}),
        "unknown risk 'huge'": Proposal(id="", kind="routing", role="coder", change={"models": ["a/x"]},
                                        rationale="", risk="huge"),
        "unknown role 'ghost'": _p("routing", {"models": ["a/x"]}, role="ghost"),
        "routing change needs a non-empty 'models' list": _p("routing", {"models": []}),
        "unknown provider 'zz' in 'zz/m'": _p("routing", {"models": ["zz/m"]}),
        "options change needs an 'options' object": _p("options", {"options": 3}),
        "prompt change needs a full 'prompt_text'": _p("prompt", {"prompt_text": "short"}),
        "only chat roles have prompts": _p("prompt", {"prompt_text": GOOD_PROMPT}, role="designer"),
    }
    for words, p in msgs.items():
        with pytest.raises(ValueError) as e:
            p.validate(cfg)
        assert str(e.value) == words


def test_propose_apply_and_rollback_through_the_registry_as_before(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    p1, p2, p3 = _three(lab)
    assert [lab.apply(p, cfg) for p in (p1, p2, p3)] == [1, 2, 3]
    learned = yaml.safe_load((lab.root / "learned.yaml").read_text(encoding="utf-8"))
    assert learned == {"roles": {"coder": {"model": "b/coder2", "fallback": ["a/coder"],
                                           "options": {"temperature": 0.2}}}}
    assert (lab.root / "learned.yaml").read_text(encoding="utf-8").startswith("# Learned by `roundtable improve`.")
    assert (lab.root / "prompts" / "coder.md").read_text(encoding="utf-8") == GOOD_PROMPT
    assert lab.rollback(2) == 2  # options and prompt go, routing stays
    fresh = _fresh(lab)
    assert [str(m) for m in fresh.roles["coder"].models] == ["b/coder2", "a/coder"]
    assert fresh.roles["coder"].options == {} and fresh.prompt_text("coder") != GOOD_PROMPT
    assert [lab.proposal(p.id).status for p in (p1, p2, p3)] == ["applied", "rolled_back", "rolled_back"]
    assert [h["event"] for h in lab.history()] == ["applied"] * 3 + ["rolled_back"]


def test_a_registered_kind_without_a_role_applies_and_undoes(tmp_path):
    calls = []
    register_kind(KindSpec(
        "tool-test", validate=lambda p, cfg: None, summary=lambda p: p.change["name"],
        lay=lambda overlay, prompts, p, cfg: overlay.setdefault("tools", []).append(p.change["name"]),
        on_apply=lambda lab, p, cfg: calls.append(("on", p.id)), on_undo=lambda lab, p: calls.append(("off", p.id)),
        needs_role=False))
    try:
        cfg, lab = make_cfg(tmp_path)
        p = lab.add_proposal(Proposal(id="", kind="tool-test", role="", change={"name": "count_lines"}, rationale="r"))
        p.validate(cfg)  # no role needed
        assert p.summary() == "tool-test              count_lines"
        lab.apply(p, cfg, by_owner=True)  # a kind the charter doesn't know waits for the owner's tap
        assert lab.learned()[0] == {"tools": ["count_lines"]}
        lab.undo(p.id, cfg=cfg)
        assert lab.learned()[0] == {}
        assert calls == [("on", p.id), ("off", p.id)]
    finally:
        KINDS.pop("tool-test", None)


# -- undo of one change ----------------------------------------------------------------------------------
def test_undo_of_the_middle_change_keeps_the_other_two(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    p1, p2, p3 = _three(lab)
    for p in (p1, p2, p3):
        lab.apply(p, cfg)
    v = lab.undo(p2.id, why="tasks got worse", by="watch", cfg=cfg)
    assert v == 4
    fresh = _fresh(lab)
    assert [str(m) for m in fresh.roles["coder"].models] == ["b/coder2", "a/coder"]
    assert fresh.roles["coder"].options == {}
    assert fresh.prompt_text("coder") == GOOD_PROMPT
    q = lab.proposal(p2.id)
    assert (q.status, q.undone_why) == ("undone", "tasks got worse")
    assert [lab.proposal(p.id).status for p in (p1, p3)] == ["applied", "applied"]
    row = lab.history()[-1]
    assert (row["event"], row["proposal"], row["by"], row["version"]) == ("undone", p2.id, "watch", 4)
    assert lab.is_duplicate(_p("options", {"options": {"temperature": 0.2}}))  # an undone change isn't offered again
    with pytest.raises(ValueError):
        lab.undo(p2.id, cfg=cfg)  # not applied any more


def test_the_owners_undo_is_rolled_back_and_rolling_back_the_undo_puts_it_back(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    p1, p2, p3 = _three(lab)
    for p in (p1, p2, p3):
        lab.apply(p, cfg)
    before = lab.state_id()
    v = lab.undo(p1.id, cfg=cfg)
    assert lab.proposal(p1.id).status == "rolled_back"
    assert [str(m) for m in _fresh(lab).roles["coder"].models] == ["a/coder", "b/coder2"]
    lab.rollback(v)
    assert lab.state_id() == before
    assert lab.proposal(p1.id).status == "applied"


def test_two_undos_in_turn_never_bring_the_first_back(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    a = lab.add_proposal(_p("prompt", {"prompt_text": GOOD_PROMPT}))
    b = lab.add_proposal(_p("routing", {"models": ["b/coder2"]}))
    lab.apply(a, cfg)
    lab.apply(b, cfg)
    lab.undo(a.id, by="watch", cfg=cfg)
    lab.undo(b.id, by="watch", cfg=cfg)
    fresh = _fresh(lab)
    assert fresh.prompt_text("coder") != GOOD_PROMPT
    assert [str(m) for m in fresh.roles["coder"].models] == ["a/coder", "b/coder2"]


def test_undo_keeps_changes_applied_after_an_earlier_undo(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    a = lab.add_proposal(_p("routing", {"models": ["b/coder2"]}))
    b = lab.add_proposal(_p("options", {"options": {"temperature": 0.4}}))
    lab.apply(a, cfg)
    lab.undo(a.id, cfg=cfg)
    lab.apply(b, cfg)
    c = lab.add_proposal(_p("prompt", {"prompt_text": GOOD_PROMPT}))
    lab.apply(c, cfg)
    lab.undo(b.id, cfg=cfg)
    fresh = _fresh(lab)
    assert [str(m) for m in fresh.roles["coder"].models] == ["a/coder", "b/coder2"]
    assert fresh.roles["coder"].options == {} and fresh.prompt_text("coder") == GOOD_PROMPT


# -- rebuild and the state id ----------------------------------------------------------------------------
def test_rebuild_equals_applying_in_order(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    changes = list(_three(lab))
    changes.append(lab.add_proposal(_p("prompt", {"prompt_text": OTHER_PROMPT})))  # a later prompt wins
    for p in changes:
        lab.apply(p, cfg)
    other = Lab(tmp_path / "other")
    (other.root / "prompts").mkdir(parents=True)
    (other.root / "prompts" / "stale.md").write_text("old", encoding="utf-8")  # rebuild replaces everything
    other.rebuild(changes, cfg)
    assert other.learned() == lab.learned()
    assert other.state_id() == lab.state_id()
    assert other.learned()[1] == {"coder": OTHER_PROMPT}


def test_state_id_follows_what_is_learned_not_the_files_comments(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    empty = lab.state_id()
    assert len(empty) == 12 and empty == Lab(tmp_path / "nothing").state_id()
    p = lab.add_proposal(_p("routing", {"models": ["b/coder2"]}))
    lab.apply(p, cfg)
    sid = lab.state_id()
    assert sid != empty
    f = lab.root / "learned.yaml"
    f.write_text("# a different comment\n" + f.read_text(encoding="utf-8"), encoding="utf-8")
    assert lab.state_id() == sid
    (lab.root / "prompts").mkdir(exist_ok=True)
    (lab.root / "prompts" / "coder.md").write_text(GOOD_PROMPT, encoding="utf-8")
    assert lab.state_id() != sid


# -- the proposal's new fields, history rows, the charter and the watch ----------------------------------
def test_new_proposal_fields_history_rows_and_old_files_still_read(tmp_path, monkeypatch):
    monkeypatch.setattr(labmod, "_machine", lambda: "pc-test")
    cfg, lab = make_cfg(tmp_path)
    p = lab.add_proposal(_p("routing", {"models": ["b/coder2"]}))
    lab.apply(p, cfg)
    q = lab.proposal(p.id)
    assert q.applied_at and q.machine == "pc-test" and q.watch["state"] == "watching" and q.undone_why == "" and q.origin == ""
    row = lab.history()[0]
    assert row["id"].startswith("H") and row["machine"] == "pc-test"
    old = {"id": "P1", "kind": "routing", "role": "coder", "change": {"models": ["a/x"]}, "rationale": "r",
           "status": "applied", "applied_version": 1}  # written by 1.2.0
    assert Proposal.from_dict(old).applied_at == ""


def test_the_charter_is_asked_first_and_a_tap_it_wants_is_recorded(tmp_path, monkeypatch):
    cfg, lab = make_cfg(tmp_path)
    p = lab.add_proposal(_p("prompt", {"prompt_text": GOOD_PROMPT}))
    asked = []

    def check(c, proposal, lab_=None, by_owner=False):
        asked.append(by_owner)
        if not by_owner:
            e = charter.CharterError("This needs your tap.")
            e.needs_owner = True
            raise e

    monkeypatch.setattr(charter, "check", check)
    with pytest.raises(charter.CharterError):
        lab.apply(p, cfg)
    assert lab.proposal(p.id).status == "needs_owner" and not (lab.root / "learned.yaml").exists()
    assert lab.history()[-1]["event"] == "needs_owner"
    assert lab.apply(lab.proposal(p.id), cfg, by_owner=True) == 1
    assert asked == [False, True]


def test_the_watch_starts_after_each_apply(tmp_path, monkeypatch):
    cfg, lab = make_cfg(tmp_path)
    started = []
    monkeypatch.setattr(canary, "start", lambda lab_, p, version: started.append((p.id, version)))
    p = lab.add_proposal(_p("routing", {"models": ["b/coder2"]}))
    lab.apply(p, cfg)
    assert started == [(p.id, 1)]


def test_the_stubs_keep_their_frozen_answers(tmp_path):
    from roundtable.improve import share, yardstick
    from roundtable.plugins import sandbox
    from roundtable.plugins.api import PluginError

    cfg, lab = make_cfg(tmp_path)
    p = _p("prompt", {"prompt_text": GOOD_PROMPT})
    assert charter.check(cfg, p, lab) is None and charter.may_auto(p) and not charter.may_auto(_p("tool", {}))
    # the charter is filled in (Helper 4): its own answers are in tests/test_charter.py
    assert charter.may_touch("src/x.py") and charter.fixed_block("coder") and charter.scrub("a b") == "a b"
    assert charter.diff("a", "b") == [{"op": "gone", "text": "a"}, {"op": "new", "text": "b"}]
    assert issubclass(charter.CharterError, ValueError)
    assert charter.CharterError.needs_owner is False
    assert wallet.allowance(cfg) == 0 and wallet.left(cfg, lab) == 0 and wallet.spent_today(lab) == 0
    with pytest.raises(wallet.AllowanceUsed):
        wallet.budget(cfg, lab, "test")
    assert wallet.AllowanceUsed.pause == "learning"
    cfg.improve["allowance_usd_per_week"] = 2
    assert wallet.budget(cfg, lab, "test", most=0.5).limit_usd == 0.5
    # filled by d4-evidence: an image role has no yardstick (0 tasks, run gives None); a builder has some
    assert yardstick.available(cfg, "designer") == 0 and yardstick.available(cfg, "coder") >= 12
    assert yardstick.run(cfg, lab, _p("routing", {"models": ["img/pic"]}, role="designer"), None) is None
    assert canary.check(cfg, lab) == [] and share.tick(None) == {}
    assert issubclass(sandbox.SandboxError, PluginError) and sandbox.supported()["guard"] is True
    with pytest.raises(sandbox.SandboxError):
        sandbox.start(Path("x"), None, [], tmp_path)
    assert sandbox.trial(Path("x"), ["pytest"])["ok"] is False


# -- the orchestrator's seams ---------------------------------------------------------------------------
class Seen(Brain):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.systems = []

    def __call__(self, model, system, messages, tools):
        self.systems.append(system)
        return super().__call__(model, system, messages, tools)


class Bare(Orchestrator):
    SYSTEM_PARTS = ()  # no stage's part, whichever stages are in the bases


def test_a_bare_orchestrators_system_prompts_are_as_before(tmp_path):
    brain = Seen()
    cfg, _ = make_cfg(tmp_path, brain=brain)
    orch = Bare(cfg, tmp_path / "p")
    for text in ("x", "You plan.", ""):
        assert orch._system(text, "coder") == orch._with_repo_rules(text)
    orch.start("a goal")
    assert orch.run() == "done"
    known = {orch._with_repo_rules(cfg.prompt_text(r.prompt)) for r in cfg.roles.values() if r.kind == "chat"}
    assert brain.systems and set(brain.systems) <= known | {orch._with_repo_rules(s) for s in brain.systems}
    assert cfg.prompt_text("coder") in brain.systems  # no repository rules here: the coder's prompt, byte for byte


def test_system_and_tool_parts_reach_the_models(tmp_path):
    from roundtable.harness import orchestrator as om

    class Stage:
        def _charter_system(self, name):
            return f"# Fixed lines for {name}"

        def _style_system(self, name):
            return ""

        def _recall_tools(self, role):
            return [Tool(ToolSpec("recall", "Look up what was learned.", _obj({}, [])), lambda a: "nothing"),
                     Tool(ToolSpec("read_file", "A clash: never replaces the workspace's own.", _obj({}, [])),
                          lambda a: "fake")]

    class O(Stage, om.Orchestrator):
        pass

    brain = Seen()
    cfg, _ = make_cfg(tmp_path, brain=brain)
    orch = O(cfg, tmp_path / "p")
    assert orch._system("Base", "coder") == "Base\n\n# Fixed lines for coder"
    box = orch.ws.toolbox(None)
    own = box.tools["read_file"]
    orch._part_tools(box, cfg.roles["coder"])
    assert "recall" in box.tools and box.tools["read_file"] is own
    orch.start("a goal")
    assert orch.run() == "done"
    assert any(s.endswith("# Fixed lines for coder") for s in brain.systems)
    assert any(s.endswith(f"# Fixed lines for {cfg.roles['orchestrator'].prompt}") for s in brain.systems)


def test_a_failing_hook_is_reported_to_the_fault_seam(tmp_path):
    from roundtable.harness import orchestrator as om

    faults = []

    class O(om.Orchestrator):
        SYSTEM_PARTS = ("_style_system",)  # only the broken part (the charter's own is in the bases later)

        def _style_system(self, name):
            raise RuntimeError("broken style")

        def _hook_fault(self, name, error):
            faults.append((name, str(error)))

    cfg, _ = make_cfg(tmp_path)
    orch = O(cfg, tmp_path / "p")
    assert orch._system("Base", "coder") == "Base"
    assert faults == [("_style_system", "broken style")]


def test_the_watch_runs_after_a_run_even_with_learning_off(tmp_path, monkeypatch):
    from roundtable.harness import orchestrator as om

    watched = []

    class O(om.Orchestrator):
        def _watch_after_run(self):
            watched.append(True)

    cfg, _ = make_cfg(tmp_path)
    assert not cfg.improve.get("after_each_run")
    orch = O(cfg, tmp_path / "p")
    orch.start("a goal")
    assert orch.run() == "done"
    assert watched


def test_spent_today_counts_what_learning_spent(tmp_path, monkeypatch):
    cfg, lab = make_cfg(tmp_path)
    lab.root.mkdir(parents=True)
    orch = Orchestrator(cfg, tmp_path / "p")
    base = orch._spent_today()
    monkeypatch.setattr(wallet, "spent_today", lambda lab_: 0.25)
    assert orch._spent_today() == pytest.approx(base + 0.25)


def test_the_new_parts_are_listed():
    o = Orchestrator
    assert o.SYSTEM_PARTS == ("_style_system", "_charter_system") and o.TOOL_PARTS == ("_recall_tools",)
    assert o.WORKER_PARTS[-1] == "_skills_worker_part" and o.PLAN_PARTS[-1] == "_docs_plan_part"
    assert o.ATTEMPT_PARTS[-2:] == ("_skills_attempt", "_recall_attempt")
    assert o.METRIC_PARTS[-1] == "_watch_metric"


# -- config, automation and the template ----------------------------------------------------------------
def test_feature_sections_and_custom_improve():
    for name in ("sandbox", "style", "skills", "market", "recall", "documents", "selfrepair", "learning"):
        assert name in hconfig.FEATURE_SECTIONS
    raw = {"improve": {"auto_apply": "none", "lab_dir": "./lab"}}
    out = hconfig.merge_custom(raw, {"improve": {"allowance_usd_per_week": 2, "lab_dir": "/elsewhere"}})
    assert out["improve"] == {"auto_apply": "none", "lab_dir": "./lab", "allowance_usd_per_week": 2}
    assert hconfig.merge_custom(raw, {"limits": {"max_cost_usd": 1}})["improve"] == raw["improve"]


def test_learning_is_something_an_automation_can_do():
    from roundtable import automation

    assert "learn" in automation.WHATS
    assert automation.what_words({"kind": "schedule", "do": {"what": "learn"}}).startswith("Learns")


def test_the_template_carries_the_owners_allowance_and_the_code_default_is_off(tmp_path):
    from importlib import resources

    text = resources.files("roundtable").joinpath("templates/harness.example.yaml").read_text(encoding="utf-8")
    assert yaml.safe_load(text)["improve"]["allowance_usd_per_week"] == 2
    cfg = parse_config(json.loads(json.dumps(RAW)))
    assert wallet.allowance(cfg) == 0
