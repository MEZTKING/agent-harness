"""Wave 7 end to end (1.3.0, "it learns"), scripted, no network, no keys, no real money.

With the owner's learning allowance at $2 a week, the scheduled learning job (the same one Sunday's slot runs):
  1. the watch undoes a planted bad change by itself (the work it led to fell clearly),
  2. tests a waiting proposal on the yardstick, paid from the wallet and within it,
  3. applies it, because it passed and is a low-risk change the owner's "low" policy allows;
then the ledger shows both lines, each with its button (Undo, or Put back), the wallet's total equals the usage
ledger's "(learning)" lines, and the charter refuses a prompt that drops a protected line, even from the owner.
"""

import json
from datetime import timedelta

import pytest

from roundtable import automation as au
from roundtable.harness import usage
from roundtable.improve import canary, charter, ledger, wallet
from roundtable.improve.lab import Proposal

from .test_canary import T0, add_rows, iso, project
from .test_improve import GOOD_PROMPT
from .test_yardstick import YBrain, ycfg

PC = {"id": "pc-desk", "name": "PC (DESK)", "kind": "pc"}


def _learning_rows():
    d = usage.ledger_dir(None)
    rows = [json.loads(ln) for f in sorted(d.glob("*.jsonl")) for ln in f.read_text().splitlines()] if d.is_dir() else []
    return [r for r in rows if r.get("project") == "(learning)"]


def test_a_week_of_learning_on_two_dollars(tmp_path):
    # the coder's backup (b/coder2) does the practice tasks properly; its first model (a/coder) doesn't
    brain = YBrain(good=lambda model, system: model == "coder2")
    cfg, lab = ycfg(tmp_path, brain, improve={"allowance_usd_per_week": 2, "auto_apply": "low", "min_samples": 2,
                                              "yardstick_runs": 1, "probe_before_apply": False})
    assert wallet.allowance(cfg) == 2 and wallet.automation(cfg)["do"]["what"] == "learn"

    # a planted bad change, applied by itself last week: the planner's work fell from 90% to 20% after it
    root = project(lab, tmp_path / "shop")
    add_rows(root, "orchestrator", ["approved"] * 9 + ["rejected"], T0 - timedelta(days=1))
    bad = lab.add_proposal(Proposal(id="", kind="options", role="orchestrator", change={"options": {"temperature": 1.2}},
                                    rationale="made up", risk="low", source="rules"))
    lab.apply(bad, cfg, reason="auto (low policy)")
    bad = lab.proposal(bad.id)
    bad.watch["since"] = iso(T0)
    bad.watch["before"] = canary.summary([r for r in canary.rows(lab, "orchestrator") if r["at"] <= iso(T0)][-30:])
    lab.save_proposal(bad)
    add_rows(root, "orchestrator", ["rejected", "approved", "rejected", "rejected", "rejected"], T0 + timedelta(hours=1))

    # a waiting proposal: the coder starts with its backup
    good = lab.add_proposal(Proposal(id="", kind="routing", role="coder", change={"models": ["b/coder2", "a/coder"]},
                                     rationale="made up", risk="low", source="llm"))

    # Sunday's slot: the learning automation's own job
    ctx = au.Ctx(cfg=cfg, home=tmp_path / "home", busy=lambda root: False, machine=PC)
    said = []
    out = wallet.job(ctx, wallet.automation(cfg))(said.append)

    # 1. the watch undid the planted change by itself
    b = lab.proposal(bad.id)
    assert b.status == "undone" and b.watch["state"] == "undone" and "fell" in b.undone_why
    # 2. the waiting proposal was tested on the yardstick, paid from the wallet
    g = lab.proposal(good.id)
    y = g.test["yardstick"]
    assert y["n"] >= 12 and y["candidate"]["passed"] > y["current"]["passed"] and g.test["passed"], g.test
    spent = wallet.spent_week(lab)
    assert 0 < spent <= 2 and wallet.left(cfg, lab) == pytest.approx(2 - spent)
    assert {line["what"] for line in wallet.lines(lab)} == {"yardstick"}
    # 3. ...and applied, as the owner's "low" policy allows; it is watched now
    assert g.status == "applied" and g.watch["state"] == "watching"
    assert [a["id"] for a in out["report"]["applied"]] == [good.id]
    lab.apply_learned(cfg)
    assert [str(m) for m in cfg.roles["coder"].models][:2] == ["b/coder2", "a/coder"]
    assert "temperature" not in (cfg.roles["orchestrator"].options or {})  # the undone change is gone

    # the ledger: both lines, from numbers, each with its button
    v = ledger.view(cfg, lab)
    lines = {x["id"]: x for x in v["lines"]}
    assert lines[good.id]["state"] == "watching" and lines[good.id]["can_undo"] and lines[good.id]["by"] == "by itself"
    assert "passed" in lines[good.id]["words"]
    assert lines[bad.id]["state"] == "undone" and lines[bad.id]["can_put_back"] and not lines[bad.id]["can_undo"]
    assert v["never"] == charter.never()

    # the wallet and the usage ledger agree, and the usage lines hold numbers only
    learning = _learning_rows()
    assert learning and sum(float(r.get("usd") or r.get("cost_usd") or 0) for r in learning) == pytest.approx(spent)
    assert "made up" not in json.dumps(learning)

    # the charter refuses a prompt that drops a protected line, even with the owner's tap
    dropped = GOOD_PROMPT.replace(" and run them with run_command", "")
    assert charter.KEEP["coder"][0] not in dropped
    p = lab.add_proposal(Proposal(id="", kind="prompt", role="coder", change={"prompt_text": dropped},
                                  rationale="made up", risk="low", source="llm"))
    before = lab.state_id()
    with pytest.raises(charter.CharterError) as e:
        lab.apply(p, cfg, by_owner=True)
    assert "run them with run_command" in str(e.value) and lab.state_id() == before
    # the owner's Undo on the applied line works too, and leaves the earlier undo as it was
    ledger.act(cfg, lab, {"action": "undo", "id": good.id})
    assert lab.proposal(good.id).status == "rolled_back" and lab.proposal(bad.id).status == "undone"
    assert said  # the job said what it did, for the Automations page
