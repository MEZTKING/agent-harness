"""Wave 7, d4-tools: the lab's "tool" and "kind" kinds – drafted only with the learning allowance, never applied
without the owner's tap, installed boxed asking for nothing, undone by switching off (files kept); kind tweaks
limited to don't lines, task notes and proof lines that run nothing."""

import json
import os
import textwrap
from pathlib import Path

import pytest
import yaml

from roundtable.harness.config import load_config
from roundtable.improve import charter, loop, toolkind, wallet, yardstick
from roundtable.improve.lab import KINDS, Lab, Proposal
from roundtable.plugins import make, sandbox
from roundtable.providers.scripted import ScriptedProvider

from .test_harness import RAW
from .test_make_plugin import IDEA, MOD, MODULE, writes

PROTECTED = ("limits", "gate", "usage", "tandem", "providers", "makers_allowed", "providers_allowed")


def home() -> Path:
    return Path(os.environ["ROUNDTABLE_HOME"])


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """A harness.yaml with a lab and $2 a week for learning; a scripted builder; a box that passes."""
    root = tmp_path / "lab"
    root.mkdir()
    raw = {**json.loads(json.dumps(RAW)), "lab_dir": "lab-data", "improve": {"allowance_usd_per_week": 2}}
    (root / "harness.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    (root / "custom.yaml").write_text(yaml.safe_dump({"limits": {"max_cost_usd": 3}, "gate": {"mode": "ask"}}),
                                      encoding="utf-8")
    ran = []
    monkeypatch.setattr(sandbox, "trial", lambda code, command, timeout=60: ran.append(Path(code)) or
                        {"ok": True, "output": "1 passed"})

    def cfg_with(script=None):
        cfg = load_config(str(root / "harness.yaml"))
        prov = ScriptedProvider("a", script or writes((f"{MODULE}.py", MOD.format(name="total_with_vat"))))
        cfg.register("a", prov)
        return cfg, prov

    cfg, prov = cfg_with()
    return {"root": root, "cfg": cfg, "prov": prov, "lab": Lab(cfg.lab_dir), "ran": ran, "cfg_with": cfg_with}


def protected_state(root):
    custom = yaml.safe_load((root / "custom.yaml").read_text(encoding="utf-8")) or {}
    return (root / "harness.yaml").read_bytes(), {k: custom.get(k) for k in PROTECTED}


def test_both_kinds_register_and_need_no_role():
    assert KINDS["tool"].needs_role is False and KINDS["kind"].needs_role is False
    assert KINDS["tool"].on_apply and KINDS["tool"].on_undo and KINDS["kind"].on_undo


def test_with_no_wallet_money_no_tool_is_drafted(setup):
    cfg, lab = setup["cfg"], setup["lab"]
    cfg.improve["allowance_usd_per_week"] = 0
    with pytest.raises(wallet.AllowanceUsed):
        toolkind.propose_tool(cfg, lab, IDEA)
    assert setup["prov"].calls == [] and lab.proposals() == [] and setup["ran"] == []


def test_a_drafted_tool_waits_for_the_owner_and_is_never_auto_applied(setup, monkeypatch):
    cfg, lab = setup["cfg"], setup["lab"]
    paid = []
    real = wallet.budget
    monkeypatch.setattr(wallet, "budget", lambda c, l, what, most=None: paid.append(what) or real(c, l, what, most))
    p = toolkind.propose_tool(cfg, lab, IDEA)
    assert paid == ["tool"]  # unattended money only from the wallet
    assert p.kind == "tool" and p.status == "needs_owner" and p.risk == "high"
    assert p.change["tools"] == ["total_with_vat"] and setup["ran"] == [Path(p.change["folder"])]
    assert p.test["passed"] is False and "practice tasks" in p.test["why"]  # no yardstick on this branch: said so
    assert charter.may_auto(p) is False
    for policy in ("none", "low", "medium", "high"):
        assert not loop.auto_apply_allowed(p, policy)
    cfg.improve["auto_apply"] = "medium"
    report = loop.cycle(cfg, lab, probe=False)
    assert report["applied"] == [] and lab.proposal(p.id).status == "needs_owner"
    assert not (yaml.safe_load((setup["root"] / "custom.yaml").read_text()) or {}).get("plugins")


def test_a_failing_draft_is_not_proposed(setup, monkeypatch):
    monkeypatch.setattr(sandbox, "trial", lambda code, command, timeout=60: {"ok": False, "output": "1 failed"})
    lab = setup["lab"]
    assert toolkind.propose_tool(setup["cfg"], lab, IDEA) is None
    assert lab.proposals() == []
    rows = [json.loads(x) for x in (lab.root / "history.jsonl").read_text().splitlines()]
    assert rows[-1]["event"] == "tool_not_offered"


def test_the_yardstick_tries_it_with_its_own_plugin_host(setup, monkeypatch):
    cfg, lab = setup["cfg"], setup["lab"]
    seen = {}

    def run(c, l, proposal, budget, runs=2, on_event=None):
        cand = toolkind.candidate_for(l, c, proposal)
        seen["cand"] = cand
        return {"n": 2, "current": {"passed": 1}, "candidate": {"passed": 2}, "veto": "", "verdict": "better",
                "passed": True}

    monkeypatch.setattr(yardstick, "available", lambda c, role: 2)
    monkeypatch.setattr(yardstick, "run", run)
    host_before = cfg.plugin_host()
    p = toolkind.propose_tool(cfg, lab, IDEA)
    assert p.test["verdict"] == "better" and p.status == "needs_owner"
    cand = seen["cand"]
    assert cand._shared is not cfg._shared and cfg.plugin_host() is host_before
    entry = cand.plugins[make.plugin_id(IDEA)]
    assert entry["permissions"] == [] and entry["path"] == p.change["folder"]
    assert make.plugin_id(IDEA) not in (cfg.plugins or {})


def test_applying_installs_it_asking_for_nothing_and_undo_switches_it_off_keeping_the_files(setup):
    cfg, lab, root = setup["cfg"], setup["lab"], setup["root"]
    before = protected_state(root)
    p = toolkind.propose_tool(cfg, lab, IDEA)
    lab.apply(p, cfg, by_owner=True)
    pid = make.plugin_id(IDEA)
    custom = yaml.safe_load((root / "custom.yaml").read_text())
    spec = custom["plugins"][pid]
    assert spec["enabled"] is True and spec["permissions"] == [] and "trusted" not in spec
    code = Path(spec["path"])
    assert (code / f"{MODULE}.py").is_file()
    assert lab.proposal(p.id).evidence["installed"]["id"] == pid
    lab.undo(p.id, why="not useful", cfg=cfg)
    spec = yaml.safe_load((root / "custom.yaml").read_text())["plugins"][pid]
    assert spec["enabled"] is False and (code / f"{MODULE}.py").is_file() and Path(p.change["folder"]).is_dir()
    assert lab.proposal(p.id).status == "rolled_back"
    assert protected_state(root) == before


# -- kind tweaks ----------------------------------------------------------------------------------------------
def tweak(extra, kind_id="website"):
    return Proposal(id="", kind="kind", role="", change={"kind_id": kind_id, "extra": extra}, rationale="r",
                    risk="high")


@pytest.mark.parametrize("extra, why", [
    ({"proof": [{"id": "x", "how": "command", "words": "It builds", "command": "rm -rf /"}]}, "command"),
    ({"proof": [{"id": "x", "how": "page_opens", "words": "Opens", "command": "echo hi"}]}, "command"),
    ({"ship": {"build": "make"}}, "only add"),
    ({"start": {"command": "npm start"}}, "only add"),
    ({"needs": ["node"]}, "only add"),
    ({"plan": {"questions": []}}, "don't lines"),
])
def test_a_kind_tweak_with_a_command_or_a_recipe_is_refused(setup, extra, why):
    with pytest.raises(ValueError, match=why):
        tweak(extra).validate(setup["cfg"])


def test_a_good_kind_tweak_is_read_by_resolve_and_undo_puts_it_aside(setup):
    cfg, lab = setup["cfg"], setup["lab"]
    from roundtable import kinds as kindlib

    base = kindlib.resolve("website", home=home())
    p = lab.add_proposal(tweak({"plan": {"dont": [{"text": "Don't hide the menu on phones", "why": "rejected twice"}]},
                                "proof": [{"id": "learned-opens", "how": "page_opens", "words": "The home page opens"}]}))
    q = lab.add_proposal(tweak({"task": "Check the page at phone width before finishing."}))
    lab.apply(p, cfg, by_owner=True)
    lab.apply(q, cfg, by_owner=True)
    k = toolkind.resolve_with_tweaks("website", home=home())
    donts = [d["text"] for d in k.spec["plan"]["dont"]]
    assert "Don't hide the menu on phones" in donts and len(donts) == len((base.spec.get("plan") or {}).get("dont") or []) + 1
    assert any(pr["id"] == "learned-opens" for pr in k.spec["proof"])
    assert any(e["id"] == "learned-website" and "phone width" in e["task"] for e in k.extras)
    assert not any("command" in pr for pr in k.spec["proof"] if pr.get("from") == "learned-website")
    # the built-in file is never touched; the extra is in the owner's own folder
    extra = toolkind.extra_dir("website")
    assert home() in extra.parents and (extra / "extra.yaml").is_file()
    lab.undo(p.id, cfg=cfg)
    k = toolkind.resolve_with_tweaks("website", home=home())
    assert "Don't hide the menu on phones" not in [d["text"] for d in (k.spec.get("plan") or {}).get("dont") or []]
    assert any("phone width" in e["task"] for e in k.extras)
    lab.undo(q.id, cfg=cfg)
    k = toolkind.resolve_with_tweaks("website", home=home())
    assert not any(e["id"] == "learned-website" for e in k.extras) and not extra.exists()
    assert any((home() / "kinds" / ".learned-aside").iterdir())  # moved aside, never deleted


def test_a_tweak_for_a_kind_that_isnt_there_is_refused(setup):
    with pytest.raises(ValueError, match="no kind"):
        tweak({"task": "Be careful."}, kind_id="spaceship").validate(setup["cfg"])


def test_tools_never_changes_what_the_charter_protects(setup):
    cfg, lab, root = setup["cfg"], setup["lab"], setup["root"]
    before = protected_state(root)
    p = toolkind.propose_tool(cfg, lab, IDEA)
    lab.apply(p, cfg, by_owner=True)
    t = lab.add_proposal(tweak({"task": "Check the page at phone width before finishing."}))
    lab.apply(t, cfg, by_owner=True)
    lab.undo(t.id, cfg=cfg)
    lab.undo(p.id, cfg=cfg)
    assert protected_state(root) == before
    assert not (lab.root / "learned.yaml").is_file() or "plugins" not in (yaml.safe_load(
        (lab.root / "learned.yaml").read_text()) or {})


def test_the_same_idea_is_never_drafted_or_paid_for_twice(setup):
    cfg, lab, prov = setup["cfg"], setup["lab"], setup["prov"]
    assert toolkind.propose_tool(cfg, lab, IDEA)
    calls = len(prov.calls)
    assert toolkind.propose_tool(cfg, lab, "  " + IDEA + " ") is None
    assert len(prov.calls) == calls and len(lab.proposals()) == 1
