"""What I learned (improve/ledger.py, ui/learnedapi.py): plain words from numbers, an undo on each line, put
back watched again, what waits for the owner, and the phone may only undo. Made-up projects only."""

import hashlib
import json
from types import SimpleNamespace

import pytest
import yaml

from roundtable.improve import canary, charter, ledger, wallet
from roundtable.improve.lab import Lab, Proposal
from roundtable.ui import learnedapi

from .test_improve import GOOD_PROMPT, make_cfg

SECRET_PROJECT = "Moonbakery Deluxe"


@pytest.fixture(autouse=True)
def _machine(monkeypatch):
    monkeypatch.setenv("ROUNDTABLE_MACHINE", "pc-alpha")
    monkeypatch.setenv("ROUNDTABLE_MACHINE_NAME", "PC (ALPHA)")


def _routing(lab, models=("b/coder2", "a/coder")):
    p = Proposal(id="", kind="routing", role="coder", change={"models": list(models)}, risk="low",
                 rationale=f"In {SECRET_PROJECT} the task 'Bake the croissant' failed: the reviewer said 'ugly'.",
                 evidence={"primary": {"model": "a/coder", "quality": 0.6, "n": 10, "cost_per_success": 0.3},
                           "candidate": {"model": "b/coder2", "quality": 0.9, "n": 10, "cost_per_success": 0.2}},
                 test={"tasks_compared": 10, "passed": True, "verdict": "better",
                       "current": {"approved": 6, "cost_usd": 1.2, "runs": [{"task": "T9", "title": SECRET_PROJECT}]},
                       "candidate": {"approved": 9, "cost_usd": 0.8, "runs": []}})
    return lab.add_proposal(p)


def _options(lab):
    return lab.add_proposal(Proposal(id="", kind="options", role="coder", change={"options": {"effort": "high"}},
                                     risk="low", rationale=f"{SECRET_PROJECT} needed more thought"))


def _prompt(lab):
    return lab.add_proposal(Proposal(id="", kind="prompt", role="coder", change={"prompt_text": GOOD_PROMPT},
                                     risk="low", rationale=f"Learned from {SECRET_PROJECT}"))


def test_every_lines_words_come_from_numbers_and_hold_no_project_name(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    p = _routing(lab)
    lab.apply(p, cfg, reason="auto (low policy)")
    lab.apply(_options(lab), cfg)
    v = ledger.view(cfg, lab)
    first = next(x for x in v["lines"] if x["id"] == p.id)
    assert first["words"] == "Coder now starts with Coder2, then Coder: it passed 9 of 10 against 6 of 10, for $0.80 instead of $1.20."
    assert first["by"] == "by itself" and first["state"] == "on" and first["can_undo"]
    assert any(x["by"] == "you" for x in v["lines"])
    blob = json.dumps(v)
    for secret in (SECRET_PROJECT, "croissant", "ugly", "T9"):
        assert secret not in blob
    assert "runs" not in json.dumps(first["numbers"])


def test_words_without_a_test_use_the_evidence_and_options_read_plainly(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    p = _routing(lab)
    p.test = None
    lab.save_proposal(p)
    assert ledger.reason(p) == "it was approved 9 of 10 times against 6 of 10 for the one before"
    o = _options(lab)
    assert ledger.what(o, cfg).endswith("now thinks high")
    assert ledger.what(_prompt(lab), cfg).endswith("has new instructions")


def test_undo_of_one_line_leaves_the_others_and_put_back_is_watched_again(tmp_path, monkeypatch):
    cfg, lab = make_cfg(tmp_path)
    watched = []
    monkeypatch.setattr(canary, "start", lambda lab_, p, version: watched.append(p.id))
    a, b, c = _routing(lab), _options(lab), _prompt(lab)
    for p in (a, b, c):
        lab.apply(p, cfg)
    out = ledger.act(cfg, lab, {"action": "undo", "id": b.id})
    states = {x["id"]: x["state"] for x in out["lines"]}
    assert states == {a.id: "on", b.id: "undone", c.id: "on"}
    overlay, prompts = lab.learned()
    assert overlay["roles"]["coder"]["model"] == "b/coder2" and "options" not in overlay["roles"]["coder"]
    assert prompts  # the prompt change stays
    line = next(x for x in out["lines"] if x["id"] == b.id)
    assert line["why"] == "you undid it" and line["can_put_back"] and not line["can_undo"]
    watched.clear()
    out = ledger.act(cfg, lab, {"action": "put_back", "id": b.id})
    assert watched == [b.id]
    line = next(x for x in out["lines"] if x["id"] == b.id)
    assert line["state"] == "put_back" and line["can_undo"]
    assert lab.learned()[0]["roles"]["coder"]["options"] == {"effort": "high"}


def test_a_line_being_watched_says_so(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    p = _routing(lab)
    lab.apply(p, cfg)
    p = lab.proposal(p.id)
    p.watch = {"tasks": 2, "before": 0.8}
    lab.save_proposal(p)
    assert ledger.view(cfg, lab)["lines"][0]["state"] == "watching"


def test_what_waits_for_the_owner_with_why_and_apply_or_turn_down(tmp_path, monkeypatch):
    cfg, lab = make_cfg(tmp_path)
    p = _prompt(lab)
    p.role = "reviewer"
    lab.save_proposal(p)

    def check(c, proposal, lab_=None, by_owner=False):
        if proposal.role == "reviewer" and not by_owner:
            e = charter.CharterError("The checker's instructions change only with your yes.")
            e.needs_owner = True
            raise e

    monkeypatch.setattr(charter, "check", check)
    with pytest.raises(charter.CharterError):
        lab.apply(p, cfg)
    v = ledger.view(cfg, lab)
    assert [w["id"] for w in v["waiting"]] == [p.id]
    assert v["waiting"][0]["why"] == "The checker's instructions change only with your yes."
    out = ledger.act(cfg, lab, {"action": "apply", "id": p.id})
    assert out["waiting"] == [] and out["lines"][0]["state"] == "on" and out["lines"][0]["by"] == "you"
    q = _options(lab)
    monkeypatch.setattr(charter, "may_auto", lambda proposal: proposal.kind != "options")
    assert [w["id"] for w in ledger.view(cfg, lab)["waiting"]] == [q.id]
    ledger.act(cfg, lab, {"action": "turn_down", "id": q.id})
    assert lab.proposal(q.id).status == "rejected"


def test_the_never_list_is_asked_of_the_charter_and_the_wallet_has_one_line(tmp_path, monkeypatch):
    cfg, lab = make_cfg(tmp_path)
    assert ledger.view(cfg, lab)["never"] == []  # the stub has no list; nothing is copied here
    monkeypatch.setattr(charter, "never", lambda: ["Your money limits", "Which makers may see a project"],
                        raising=False)
    v = ledger.view(cfg, lab)
    assert v["never"] == ["Your money limits", "Which makers may see a project"]
    assert v["wallet"]["on"] is False and "off" in v["wallet"]["words"]
    monkeypatch.setattr(wallet, "allowance", lambda c: 2.0)
    monkeypatch.setattr(wallet, "left", lambda c, l, now=None: 1.25)
    assert ledger.view(cfg, lab)["wallet"]["words"] == "Learning by itself: $1.25 of $2.00 left this week."


def _app(cfg, lab):
    return SimpleNamespace(need_cfg=lambda: cfg, lab=lambda c: lab, hub_lock=None)


def test_the_phone_may_undo_and_nothing_else(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    a, b = _routing(lab), _options(lab)
    lab.apply(a, cfg)
    app = _app(cfg, lab)
    r = learnedapi.routes(app)
    assert set(r) == {("GET", "/api/learned"), ("POST", "/api/learned"), ("POST", "/api/learned/undo")}
    for action in ("put_back", "apply", "turn_down"):
        with pytest.raises(PermissionError):
            r[("POST", "/api/learned")]({"action": action, "id": b.id, "_via": "phone"})
    assert lab.proposal(b.id).status == "proposed"
    out = r[("POST", "/api/learned/undo")]({"id": a.id, "_via": "phone", "action": "put_back"})
    assert out["action"] == "undo" and lab.proposal(a.id).status == "rolled_back"
    out = r[("POST", "/api/learned")]({"action": "put_back", "id": a.id})  # the PC may
    assert lab.proposal(a.id).status == "applied"
    assert r[("GET", "/api/learned")]({})["counts"]["on"] == 1


def test_errors_say_what_to_do(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    with pytest.raises(ledger.LedgerError, match="Refresh"):
        ledger.act(cfg, lab, {"action": "undo", "id": "P404"})
    p = _options(lab)
    with pytest.raises(ledger.LedgerError, match="nothing to undo"):
        ledger.act(cfg, lab, {"action": "undo", "id": p.id})


def test_ledger_never_changes_what_the_charter_protects(tmp_path, monkeypatch):
    raw = {"providers": {"a": {"type": "scripted"}, "b": {"type": "scripted"}},
           "roles": {"coder": {"model": "a/coder", "fallback": ["b/coder2"]}, "reviewer": {"model": "a/reviewer"}},
           "limits": {"max_cost_usd": 5}}
    harness = tmp_path / "harness.yaml"
    harness.write_text(yaml.safe_dump(raw), encoding="utf-8")
    before = hashlib.sha256(harness.read_bytes()).hexdigest()
    cfg, lab = make_cfg(tmp_path)
    p = _routing(lab)
    lab.apply(p, cfg)
    ledger.act(cfg, lab, {"action": "undo", "id": p.id})
    refused = []

    def check(c, proposal, lab_=None, by_owner=False):
        refused.append(proposal.id)
        raise charter.CharterError("That touches your money limits.")

    monkeypatch.setattr(charter, "check", check)
    state = lab.state_id()
    with pytest.raises(charter.CharterError):
        ledger.act(cfg, lab, {"action": "put_back", "id": p.id})
    assert refused == [p.id] and lab.state_id() == state and lab.proposal(p.id).status == "rolled_back"
    assert hashlib.sha256(harness.read_bytes()).hexdigest() == before
    assert not (tmp_path / "custom.yaml").exists()
    import inspect

    src = inspect.getsource(ledger) + inspect.getsource(learnedapi)
    for word in ("save_custom", "harness.yaml\").write", "makers_allowed"):
        assert word not in src
