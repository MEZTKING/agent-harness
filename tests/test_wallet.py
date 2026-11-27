"""The learning allowance (improve/wallet.py), the cycle on it (improve/loop.py, wallet=True), its schedule and
its API (ui/walletapi.py). Made-up projects and scripted models; no network, no keys, no real money."""

import json
import threading
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from roundtable import automation as au
from roundtable.harness import usage
from roundtable.harness.agent import BudgetExceeded
from roundtable.improve import charter, wallet
from roundtable.improve.lab import Lab, Proposal
from roundtable.improve.loop import cycle
from roundtable.providers.base import Usage

from .test_improve import GOOD_PROMPT, make_cfg, run_projects

PC = {"id": "pc-desk", "name": "PC (DESK)", "kind": "pc"}
PHONE = {"id": "phone-1a2b3c", "name": "Phone", "kind": "phone"}


def t(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


class Counting:
    """Wraps a scripted brain and counts every model call."""

    def __init__(self, inner):
        self.inner, self.calls = inner, 0

    def __call__(self, *a):
        self.calls += 1
        return self.inner(*a)


def ledger_rows(home=None):
    d = usage.ledger_dir(home)
    return [json.loads(ln) for f in sorted(d.glob("*.jsonl")) for ln in f.read_text().splitlines()] if d.is_dir() else []


# -- the allowance and the ledger ------------------------------------------------------------------------------
def test_allowance_off_by_default_spends_nothing_and_has_no_schedule(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    assert wallet.allowance(cfg) == 0 and wallet.left(cfg, lab) == 0
    with pytest.raises(wallet.AllowanceUsed):
        wallet.budget(cfg, lab, "replay")
    assert wallet.automation(cfg) is None
    assert wallet.used_words(cfg, lab) == "Learning by itself is off"


def test_allowance_off_the_wallet_cycle_makes_no_paid_call(tmp_path):
    from .test_improve import Judge

    brain = Counting(Judge())
    cfg, lab = make_cfg(tmp_path, brain=brain, improve={"min_samples": 2, "auto_apply": "low"})
    run_projects(cfg, tmp_path, 2)
    lab.add_proposal(Proposal(id="", kind="prompt", role="coder", change={"prompt_text": GOOD_PROMPT},
                              rationale="r", risk="medium", source="llm"))
    before = brain.calls
    report = cycle(cfg, lab, use_llm=True, test=True, wallet=True, probe=True)
    assert brain.calls == before  # no test, no probe, no analyst
    assert not (lab.root / wallet.LEDGER).exists()
    # the free rules still ran; the apply waits, because its health check would cost money
    assert len(report["new"]) == 1 and report["applied"] == []
    assert report["stopped"] == wallet.OFF_WORDS


def test_command_line_cycle_is_as_before(tmp_path):
    cfg, lab = make_cfg(tmp_path)
    run_projects(cfg, tmp_path, 2)
    cfg.improve["auto_apply"] = "low"
    report = cycle(cfg, lab)
    assert len(report["applied"]) == 1 and "stopped" not in report


def test_ledger_lines_hold_numbers_only_and_the_week_rolls_over(tmp_path):
    cfg, lab = make_cfg(tmp_path, improve={"allowance_usd_per_week": 2})
    monday = t("2026-11-23T12:00:00Z")
    wallet.charge(lab, "replay", 0.5, "P1", now=monday)
    wallet.charge(lab, "analyst", 0.25, now=monday + timedelta(days=1))
    assert wallet.left(cfg, lab, now=monday) == pytest.approx(1.25)
    assert wallet.left(cfg, lab, now=monday + timedelta(days=7)) == pytest.approx(2.0)  # nothing rolls over
    row = wallet.lines(lab)[0]
    assert set(row) == {"at", "week", "what", "proposal", "usd", "machine"}
    assert wallet.charge(lab, "replay", 0) is None


def test_two_threads_lose_no_lines(tmp_path):
    cfg, lab = make_cfg(tmp_path, improve={"allowance_usd_per_week": 100})
    b = wallet.budget(cfg, lab, "replay")

    def spend():
        for _ in range(100):
            b.charge(0.001)

    threads = [threading.Thread(target=spend) for _ in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(wallet.lines(lab)) == 400
    assert wallet.spent_week(lab) == pytest.approx(0.4)


def test_usage_ledger_line_says_learning_and_holds_no_text(tmp_path):
    cfg, lab = make_cfg(tmp_path, improve={"allowance_usd_per_week": 2})
    b = wallet.budget(cfg, lab, "analyst")
    b.charge(0.01, ref="a/coder", usage=Usage(input_tokens=10, output_tokens=5), role="coder")
    rows = [r for r in ledger_rows() if r["project"] == "(learning)"]
    assert len(rows) == 1
    r = rows[0]
    assert r["usd"] == 0.01 and r["model"] == "coder" and r["pid"] == "learning"
    assert all(not isinstance(v, str) or len(v) < 40 for v in r.values())  # names and numbers, no text


def test_budget_never_goes_past_what_is_left_and_says_so(tmp_path):
    cfg, lab = make_cfg(tmp_path, improve={"allowance_usd_per_week": 2})
    b = wallet.budget(cfg, lab, "replay", most=5)
    assert b.limit_usd == pytest.approx(2.0)
    b.charge(2.0)
    with pytest.raises(wallet.AllowanceUsed) as e:
        b.check()
    assert str(e.value) == "Learning has used this week's $2; it carries on next week."
    with pytest.raises(wallet.AllowanceUsed):
        wallet.budget(cfg, lab, "replay")
    small = make_cfg(tmp_path / "x", improve={"allowance_usd_per_week": 2})[0]
    b2 = wallet.budget(small, Lab(tmp_path / "x" / "lab"), "probe", most=0.1)
    b2.charge(0.1)
    with pytest.raises(BudgetExceeded) as e2:
        b2.check()
    assert not isinstance(e2.value, wallet.AllowanceUsed)  # only the step's own cap: the week goes on


def test_the_day_limit_stops_it(tmp_path):
    cfg, lab = make_cfg(tmp_path, improve={"allowance_usd_per_week": 5})
    cfg.limits.max_usd_per_day = 1.0
    wallet.charge(lab, "replay", 1.0)
    assert wallet.spent_today(lab) == pytest.approx(1.0)
    with pytest.raises(wallet.AllowanceUsed) as e:
        wallet.budget(cfg, lab, "replay")
    assert "Today's spending limit" in str(e.value)
    cfg.limits.max_usd_per_day = 1.5
    assert wallet.budget(cfg, lab, "replay").limit_usd == pytest.approx(0.5)


def test_other_machines_spending_counts_when_sharing_knows_it(tmp_path, monkeypatch):
    from roundtable.improve import share

    cfg, lab = make_cfg(tmp_path, improve={"allowance_usd_per_week": 2})
    monkeypatch.setattr(share, "others_spent", lambda lab, week: 1.5, raising=False)
    assert wallet.left(cfg, lab) == pytest.approx(0.5)


# -- the cycle on the wallet --------------------------------------------------------------------------------------
def test_a_cycle_stops_at_the_cap_mid_test_and_says_so(tmp_path):
    cfg, lab = make_cfg(tmp_path, improve={"min_samples": 2, "allowance_usd_per_week": 2})
    run_projects(cfg, tmp_path, 1)
    for ref in list(cfg.pricing):
        cfg.pricing[ref] = {"input": 200_000, "output": 200_000}  # a few calls use the whole $2
    p = lab.add_proposal(Proposal(id="", kind="routing", role="coder", change={"models": ["b/coder2"]},
                                  rationale="r", risk="low", source="llm"))
    report = cycle(cfg, lab, test=True, wallet=True, samples=3)
    assert report["stopped"] == "Learning has used this week's $2; it carries on next week."
    assert lab.proposal(p.id).status == "proposed" and lab.proposal(p.id).test is None
    assert report["tested"] == []
    assert wallet.left(cfg, lab) == 0
    spent = wallet.spent_week(lab)
    assert spent == pytest.approx(report["spent_usd"]) and spent >= 2.0
    learning = sum(float(r["usd"] or 0) for r in ledger_rows() if r["project"] == "(learning)")
    assert learning == pytest.approx(spent)  # the wallet and the usage ledger agree
    again = cycle(cfg, lab, test=True, wallet=True)  # the rest of the week: nothing paid
    assert again["stopped"] and wallet.spent_week(lab) == pytest.approx(spent)


def test_a_wallet_cycle_tests_then_applies_within_the_allowance(tmp_path):
    cfg, lab = make_cfg(tmp_path, improve={"min_samples": 2, "allowance_usd_per_week": 5, "auto_apply": "low"})
    run_projects(cfg, tmp_path, 1)
    p = lab.add_proposal(Proposal(id="", kind="routing", role="coder", change={"models": ["b/coder2"]},
                                  rationale="r", risk="low", source="llm"))
    report = cycle(cfg, lab, test=True, wallet=True, samples=1, probe=False)
    assert [x["id"] for x in report["tested"]] == [p.id]
    assert lab.proposal(p.id).status == "applied"
    assert lab.proposal(p.id).watch["state"] == "watching"
    assert report["spent_usd"] > 0 and wallet.lines(lab)[0]["proposal"] == p.id


def test_no_second_change_by_itself_while_the_job_is_watched(tmp_path):
    cfg, lab = make_cfg(tmp_path, improve={"allowance_usd_per_week": 2, "auto_apply": "low"})
    first = lab.add_proposal(Proposal(id="", kind="routing", role="coder", change={"models": ["b/coder2"]},
                                      rationale="r", risk="low"))
    lab.apply(first, cfg)
    second = lab.add_proposal(Proposal(id="", kind="routing", role="coder", change={"models": ["a/coder"]},
                                       rationale="r", risk="low"))
    report = cycle(cfg, lab, wallet=True, probe=False)
    assert report["applied"] == [] and lab.proposal(second.id).status == "proposed"
    assert any("still being watched" in s["reason"] for s in report["skipped"])


def test_the_charter_has_the_first_word(tmp_path, monkeypatch):
    cfg, lab = make_cfg(tmp_path, improve={"allowance_usd_per_week": 2, "auto_apply": "medium"})
    p = lab.add_proposal(Proposal(id="", kind="routing", role="coder", change={"models": ["b/coder2"]},
                                  rationale="r", risk="low"))
    monkeypatch.setattr(charter, "may_auto", lambda prop: False)
    assert cycle(cfg, lab, wallet=True, probe=False)["applied"] == []
    assert lab.proposal(p.id).status == "proposed"


def test_the_analyst_waits_for_twenty_new_judged_tasks(tmp_path):
    cfg, lab = make_cfg(tmp_path, improve={"min_samples": 2, "allowance_usd_per_week": 2})
    run_projects(cfg, tmp_path, 1)
    due, why = wallet.analyst_due(cfg, lab)
    assert not due and "20 new judged tasks" in why
    report = cycle(cfg, lab, use_llm=True, wallet=True, probe=False)
    assert "analyst" in report and report["analyst_cost_usd"] == 0


def test_loop_never_changes_what_the_charter_protects(tmp_path):
    """A full wallet cycle (rules, tests, applies) and the allowance's own save never write harness.yaml, nor the
    protected parts of custom.yaml."""
    cfg, lab = make_cfg(tmp_path, improve={"min_samples": 2, "allowance_usd_per_week": 5, "auto_apply": "medium"})
    harness = tmp_path / "harness.yaml"
    harness.write_text("roles: {}\nimprove: {}\n", encoding="utf-8")
    custom = tmp_path / "custom.yaml"
    protected = {"limits": {"max_usd_per_day": 3}, "usage": {"services": {"a": {"usd_per_day": 1}}},
                 "gate": {"x": 1}, "tandem": {"y": 2}, "providers": {"a": {"type": "scripted"}},
                 "makers_allowed": ["a"], "providers_allowed": ["a"]}
    custom.write_text(yaml.safe_dump(protected), encoding="utf-8")
    before_h = harness.read_bytes()
    run_projects(cfg, tmp_path, 2)
    lab.add_proposal(Proposal(id="", kind="routing", role="coder", change={"models": ["b/coder2"]},
                              rationale="r", risk="low", source="llm"))
    cycle(cfg, lab, test=True, wallet=True, samples=1, probe=False)
    wallet.save_allowance(harness, 2)
    assert harness.read_bytes() == before_h
    after = yaml.safe_load(custom.read_text(encoding="utf-8"))
    for k, v in protected.items():
        assert after[k] == v, k
    assert after["improve"]["allowance_usd_per_week"] == 2
    assert not any(p.name in ("harness.yaml", "custom.yaml") for p in lab.root.rglob("*"))


# -- the owner's figure ------------------------------------------------------------------------------------------
def test_save_allowance_picks_low_once_and_refuses_nonsense(tmp_path):
    harness = tmp_path / "harness.yaml"
    harness.write_text("roles: {}\n", encoding="utf-8")
    mine = wallet.save_allowance(harness, "2")
    assert mine == {"allowance_usd_per_week": 2.0, "auto_apply": "low"}
    (tmp_path / "custom.yaml").write_text(yaml.safe_dump({"improve": {"allowance_usd_per_week": 2,
                                                                       "auto_apply": "none"}}))
    assert wallet.save_allowance(harness, 0)["auto_apply"] == "none"  # the owner's own choice stays
    for bad in ("lots", -1, 1000):
        with pytest.raises(ValueError):
            wallet.save_allowance(harness, bad)


# -- the schedule ------------------------------------------------------------------------------------------------
def test_the_learning_automation_is_there_only_with_an_allowance(tmp_path):
    cfg, lab = make_cfg(tmp_path, improve={"allowance_usd_per_week": 2})
    a = wallet.automation(cfg)
    assert a["do"] == {"what": "learn"} and a["when"]["days"] == ["sun"] and a["when"]["time"] == "03:00"
    assert a["name"] == "Learning" and a["source"] == "builtin"
    assert "Learning" in wallet.money_words(cfg, lab)


def _hooked(monkeypatch):
    """What the coordinator's hook-up in automation.every() does: the built-in learning automation appended."""
    real = au.every

    def every(cfg, home):
        extra = wallet.automation(cfg)
        return real(cfg, home) + ([extra] if extra else [])

    monkeypatch.setattr(au, "every", every)


def test_two_machines_one_runs_the_learning_slot(tmp_path, monkeypatch):
    from .test_automation import Hub

    _hooked(monkeypatch)
    cfg, lab = make_cfg(tmp_path, improve={"allowance_usd_per_week": 2})
    ran = []
    monkeypatch.setattr(wallet, "run_cycle", lambda c, l, on_event=None: ran.append(1) or {"new": [], "applied": []})
    hub_root = tmp_path / "hub"
    sunday = datetime(2026, 11, 29, 3, 5).astimezone().astimezone(timezone.utc)
    pc = au.tick(cfg, hub=Hub(hub_root), home=tmp_path / "pc", now=sunday, machine=PC)
    phone = au.tick(cfg, hub=Hub(hub_root), home=tmp_path / "phone", now=sunday, machine=PHONE)
    assert [r["text"] for r in pc] == ["Learning started."] and phone == []
    assert ran == [1]
    st = au.load_state(tmp_path / "pc", PC)["learning"]
    assert st["last_result"].startswith("Learning:")


def test_learning_never_runs_while_a_project_is_building(tmp_path, monkeypatch):
    cfg, lab = make_cfg(tmp_path, improve={"allowance_usd_per_week": 2})
    run_projects(cfg, tmp_path, 1)
    ran = []
    monkeypatch.setattr(wallet, "run_cycle", lambda c, l, on_event=None: ran.append(1) or {})
    ctx = au.Ctx(cfg=cfg, home=tmp_path / "home", busy=lambda root: True, machine=PC)
    out = wallet.job(ctx, wallet.automation(cfg))(lambda s: None)
    assert ran == [] and "waits" in out["text"]


# -- the API -----------------------------------------------------------------------------------------------------------
class App:
    def __init__(self, cfg):
        self._cfg = cfg

    def cfg(self):
        return self._cfg


def test_wallet_api_view_and_the_owners_confirm(tmp_path, monkeypatch):
    from roundtable import phone
    from roundtable.ui import server, walletapi

    cfg, lab = make_cfg(tmp_path)
    harness = tmp_path / "harness.yaml"
    harness.write_text("roles: {}\n", encoding="utf-8")
    cfg.path = harness
    app = App(cfg)
    r = walletapi.routes(app)
    v = r[("GET", "/api/learning/wallet")]({})
    assert v["on"] is False and v["words"] == "Learning by itself is off" and v["lines"] == []
    q = r[("POST", "/api/learning/allowance")]({"usd": 2})
    assert q["confirm"] and "$2 a week" in q["question"]
    assert not (tmp_path / "custom.yaml").exists()  # nothing changed without the confirm
    r[("POST", "/api/learning/allowance")]({"usd": 2, "confirm": True})
    assert yaml.safe_load((tmp_path / "custom.yaml").read_text())["improve"]["allowance_usd_per_week"] == 2
    cfg.improve["allowance_usd_per_week"] = 2
    wallet.charge(lab, "replay", 0.42)
    v = r[("GET", "/api/learning/wallet")]({})
    assert v["words"] == "Learning: $0.42 of $2 this week" and v["next_run"]
    with pytest.raises(server.ApiError):
        r[("POST", "/api/learning/allowance")]({"usd": "lots", "confirm": True})
    assert ("POST", "/api/learning/allowance") not in set(phone.PHONE_ROUTES)  # PC only
    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "walletapi"))
    assert ("GET", "/api/learning/wallet") in server._feature_routes(app)
