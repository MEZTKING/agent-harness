"""The proof run's pieces (wave 9): the set-up (one maker, never V4 Pro), the caps, the stop before building when the
estimate is over, the harness's own limits stopping a run, the balance read or said unreadable, the one line for
the real hub, the findings, the command line and the app's routes. Scripted providers, no network, no keys."""

from __future__ import annotations

import argparse
import json
from importlib import resources
from types import SimpleNamespace

import pytest
import yaml

from roundtable import proofrun
from roundtable.harness.config import parse_config
from roundtable.providers.scripted import ScriptedProvider

from .test_proofrun_e2e import PLAN, FakeBalance, GameBrain, lab_with, quiet  # noqa: F401  (quiet is a fixture)

SMALL = [PLAN[0], PLAN[3]]


def shipped() -> str:
    return resources.files("roundtable").joinpath("proofrun/harness.deepseek.yaml").read_text(encoding="utf-8")


# -- the set-up ------------------------------------------------------------------------------------------------
def test_the_shipped_set_up_is_one_maker_and_never_v4_pro(tmp_path):
    text = shipped()
    assert "v4-pro" not in text.lower()
    cfg = parse_config(yaml.safe_load(text), tmp_path / "harness.yaml")
    assert proofrun.problems(cfg) == []
    chat = {n: [str(m) for m in r.models] for n, r in cfg.roles.items() if r.kind == "chat"}
    assert chat and all(v == [proofrun.MODEL] for v in chat.values())  # no fallback to another maker
    for job in ("orchestrator", "critic", "designer", "scout", "coder", "tester", "reviewer"):
        assert job in chat
    assert cfg.planner_role == "orchestrator" and cfg.reviewer_role == "reviewer" and cfg.critic_role == "critic"
    assert cfg.limits.max_parallel == 3
    assert proofrun.default_idea().startswith("Lantern Run: a small browser game.")


def test_problems_catch_v4_pro_another_maker_and_profiles(tmp_path):
    raw = yaml.safe_load(shipped())
    raw["roles"]["coder"]["fallback"] = ["deepseek/deepseek-v4-pro"]
    raw["providers"]["other"] = {"type": "openai_compat", "base_url": "https://example.invalid"}
    raw["roles"]["reviewer"]["model"] = "other/some-model"
    raw["profiles"] = {"quality": {"roles": {"coder": {"model": "deepseek/deepseek-v4-flash"}}}}
    got = " ".join(proofrun.problems(parse_config(raw, tmp_path / "h.yaml")))
    assert "V4 Pro" in got and "'reviewer' must use deepseek/deepseek-v4-flash alone" in got and "'quality'" in got


def test_prepare_makes_a_lab_of_its_own_and_spends_nothing(tmp_path):
    lab = tmp_path / "lab"
    got = proofrun.prepare(lab, "A made-up game about a frog.", proofrun.caps_for(art=False))
    raw = yaml.safe_load((lab / "harness.yaml").read_text(encoding="utf-8"))
    assert raw["hub"] == {"config": str(lab.resolve() / "hub.yaml"), "agent": proofrun.HUB_AGENT}
    assert raw["improve"]["lab_dir"] == str(lab.resolve() / ".harness-lab")
    assert "artist" not in raw["roles"] and "sound" in raw["roles"]
    assert raw["limits"]["max_cost_usd"] == 2.5 and raw["sound"]["max_per_project_usd"] == 0.5
    hub = yaml.safe_load((lab / "hub.yaml").read_text(encoding="utf-8"))
    assert hub["storage"]["path"] == str(lab.resolve() / "hub-data") and list(hub["agents"]) == [proofrun.HUB_AGENT]
    assert got["caps"]["total_usd"] == 2.5 and not got["art"] and got["sound"]
    assert proofrun.read_state(lab)["phase"] == "prepared"
    assert proofrun.report(lab)["words"] == "The proof run is prepared."
    with pytest.raises(ValueError, match="idea"):
        proofrun.prepare(tmp_path / "b", "  ", {})


def test_caps_never_pass_the_owners_three_dollars():
    assert proofrun.checked_caps(None) == {"text_usd": 2.0, "art_usd": 0.5, "sound_usd": 0.5, "total_usd": 3.0}
    assert proofrun.checked_caps(proofrun.caps_for(art=False, sound=False))["total_usd"] == 2.0
    with pytest.raises(ValueError, match=r"more than the \$3.00 you allowed"):
        proofrun.checked_caps({"text_usd": 2.5})
    with pytest.raises(ValueError, match="below"):
        proofrun.checked_caps({"art_usd": -1})


def test_over_caps_says_why_in_plain_words():
    caps = proofrun.checked_caps(None)
    assert proofrun.over_caps({"text_usd": 1, "art_usd": 0.1, "sound_usd": 0, "total_usd": 1.1, "unpriced": []}, caps) == ""
    assert "no price (x/y)" in proofrun.over_caps({"unpriced": ["x/y"], "total_usd": 1}, caps)
    assert "the pictures ($0.70) is over its limit of $0.50" in proofrun.over_caps(
        {"text_usd": 1, "art_usd": 0.7, "sound_usd": 0, "total_usd": 1.7, "unpriced": []}, caps)


def test_no_report_without_a_lab(tmp_path):
    assert proofrun.report(tmp_path / "nothing") == {"ready": False, "words": "No proof run yet."}
    assert proofrun.findings({"ready": False}) == []


# -- the caps hold ---------------------------------------------------------------------------------------------
def test_an_estimate_over_the_cap_stops_before_any_build_call(tmp_path, quiet):
    brain = GameBrain(SMALL)
    lab, cfg, _, _ = lab_with(tmp_path, brain, art=False, sound=False)
    cfg.pricing[proofrun.MODEL] = {"input": 3000.0, "output": 3000.0}  # a plan that would cost far too much
    bal = FakeBalance()
    asked = []
    rep = proofrun.run(lab, cfg, yes=lambda w: asked.append(w) or True, balance=bal)
    assert rep["phase"] == "stopped" and "over its limit" in rep["stopped"] and not asked
    assert brain.builder_calls == 0  # nothing was built
    from roundtable.harness.orchestrator import Project

    assert not Project(lab / proofrun.PROJECT).meta().get("plan_approved")
    assert bal.reads == 2  # read before planning and again after
    assert proofrun.findings(rep)[0]["where"] == "before building"


class DearBrain(GameBrain):
    """The first builder's answer reads ten million words: far more than the plan said, and past the $2.00 limit
    at DeepSeek's peak price ($4.40) and at its half price off-peak ($2.20) alike."""

    def __call__(self, model, system, messages, tools):
        resp = super().__call__(model, system, messages, tools)
        if any(t.name == "finish_task" for t in tools) and messages[-1]["role"] == "user":
            from roundtable.providers.base import Usage

            resp.usage = Usage(input_tokens=10_000_000, output_tokens=10)
        return resp


@pytest.mark.parametrize("peak", [True, False])
def test_the_projects_own_limit_stops_a_scripted_run(tmp_path, quiet, monkeypatch, peak):
    # the price depends on the hour (DeepSeek's off-peak half price): the test fixes the hour both ways, so it
    # doesn't pass or fail with the clock
    from roundtable.harness import config as hconfig

    monkeypatch.setattr(hconfig, "in_peak", lambda windows, now=None: peak)
    lab, cfg, _, _ = lab_with(tmp_path, DearBrain(SMALL), art=False, sound=False)
    rep = proofrun.run(lab, cfg, yes=lambda w: True, balance=FakeBalance())
    root = lab / proofrun.PROJECT
    raw = yaml.safe_load((root / ".harness" / "project.yaml").read_text(encoding="utf-8"))
    assert raw["limits"] == {"max_cost_usd": 2.0, "max_real_usd_per_run": 2.0} and raw["checking"] == "lean"
    # the harness's own limit stopped it (autopilot's allowance, the caps' total), not the proof run; one call
    # can't be cut off halfway, so it stops at the first charge past the limit
    assert rep["status"] == "paused" and rep["pause"] == "allowance", rep["status"]
    assert "spending limit is reached" in rep["reason"]
    assert rep["tasks"]["first_time"] == []
    assert any(f["where"] == "the run" for f in proofrun.findings(rep))


def test_autopilot_in_the_lab_carries_the_caps_as_its_limit(tmp_path, quiet):
    lab, cfg, _, _ = lab_with(tmp_path, GameBrain(SMALL), art=False, sound=False)
    proofrun.run(lab, cfg, yes=lambda w: True, balance=FakeBalance())
    from roundtable.harness.orchestrator import Project

    allow = Project(lab / proofrun.PROJECT).meta()["run_allowance"]
    assert allow["cap_usd"] == 2.0 and allow["home"] == str((lab / "autopilot").resolve())
    from roundtable import autopilot

    assert not autopilot.load(lab / "autopilot")["on"]  # switched off again at the end
    assert autopilot.load()["on"] is False  # the owner's own autopilot was never touched


# -- the balance -----------------------------------------------------------------------------------------------
def test_a_balance_that_cant_be_read_is_said_not_guessed(tmp_path, quiet):
    lab, cfg, _, _ = lab_with(tmp_path, GameBrain(SMALL), art=False, sound=False)
    rep = proofrun.run(lab, cfg, yes=lambda w: True, balance=FakeBalance(readable=False))
    m = rep["money"]
    assert m["real_usd"] is None and "isn't guessed" in m["real_words"] and m["count_gap_pct"] is None
    assert m["table"][2]["usd"] is None
    assert any(f["where"] == "the real balance" for f in proofrun.findings(rep))
    assert "| The real fall in the balance | not known |" in (lab / proofrun.FINDINGS_FILE).read_text(encoding="utf-8")


def test_real_fall_only_counts_services_read_both_times():
    a = {"deepseek": {"amount": 5.0}, "x": {"amount": 1.0}}
    assert proofrun.real_fall(a, {"deepseek": {"amount": 4.25}}) == 0.75
    assert proofrun.real_fall(a, None) is None and proofrun.real_fall(None, a) is None


# -- privacy: the real hub hears one line ----------------------------------------------------------------------
def test_only_one_journal_line_reaches_the_real_hub_and_it_carries_no_project_content(tmp_path, quiet):
    from roundtable.core.config import load_config as load_hub
    from roundtable.hub.service import Hub

    real_dir = tmp_path / "real-hub"
    real_dir.mkdir()
    (real_dir / "hub.yaml").write_text(yaml.safe_dump({
        "storage": {"type": "file", "path": str(real_dir / "data")}, "default_policy": "deny",
        "agents": {"harness": {"repo": "me/made-up"}}}), encoding="utf-8")
    real = SimpleNamespace(hub={"config": str(real_dir / "hub.yaml"), "agent": "harness"})
    lab, cfg, _, _ = lab_with(tmp_path, GameBrain(SMALL), art=False, sound=False)
    rep = proofrun.run(lab, cfg, yes=lambda w: True, balance=FakeBalance(), real_hub=real)
    hub = Hub(load_hub(str(real_dir / "hub.yaml")))
    entries = hub.journal.entries("harness", "harness", limit=50)
    assert len(entries) == 1 and entries[0]["text"].startswith("Proof run done: 2 of 2 tasks passed")
    blob = "".join(p.read_text(encoding="utf-8", errors="replace") for p in (real_dir / "data").rglob("*") if p.is_file())
    for word in ("Lantern", "moth", "game.js", "index.html", "the page", proofrun.PROJECT):
        assert word not in blob
    # the run itself used the lab's own made-up hub
    lab_blob = "".join(p.read_text(encoding="utf-8", errors="replace")
                       for p in (lab / "hub-data").rglob("*") if p.is_file())
    assert proofrun.PROJECT in lab_blob
    assert rep["phase"] == "done"


def test_no_real_hub_no_line():
    assert proofrun.write_journal_line(SimpleNamespace(hub=None), {"ready": True}, []) is None


# -- findings --------------------------------------------------------------------------------------------------
def test_findings_for_a_scripted_stuck_task_and_a_wrong_estimate(tmp_path, quiet):
    brain = GameBrain(SMALL, stuck="T4")
    lab, cfg, _, _ = lab_with(tmp_path, brain, art=False, sound=False)
    rep = proofrun.run(lab, cfg, yes=lambda w: True, balance=FakeBalance())
    assert "T4" in rep["tasks"]["failed"]
    found = proofrun.findings(rep)
    where = [f["where"] for f in found]
    assert any(w.startswith("task T4") for w in where) and "the estimate" in where
    stuck = next(f for f in found if f["where"].startswith("task T4"))
    assert "unstick.py" in stuck["file"] and stuck["expected"] and stuck["happened"]
    assert any(p["where"] == "task T4" for p in rep["people"])
    md = (lab / proofrun.FINDINGS_FILE).read_text(encoding="utf-8")
    assert "**task T4 (coder)**" in md and "plans/gaps.md" in md


def test_findings_from_a_made_up_report():
    rep = {"ready": True, "phase": "done", "status": "done", "stopped": "",
           "money": {"estimate_usd": 1.0, "counted_usd": 1.1, "real_usd": 1.5, "count_gap_pct": -26.7},
           "tasks": {"failed": [], "split": ["T2"], "retried": ["T3"], "items": [{"id": "T3", "role": "coder", "attempts": 2}]},
           "people": [{"where": "a card", "what": "Left for you: “Which look?” – there's no recommended answer."}],
           "seeing": {"can_see": True}, "looks": {"words": ""}, "sounds": {"words": ""},
           "errors": [{"kind": "hub_error", "error": "offline"}, {"kind": "hub_error", "error": "offline"}]}
    where = [f["where"] for f in proofrun.findings(rep)]
    assert where == ["the harness's own count", "task T2", "task T3 (coder)", "a card", "an event (hub_error)"]


# -- the command line ------------------------------------------------------------------------------------------
def parse(argv):
    return proofrun.add_arguments(argparse.ArgumentParser()).parse_args(argv)


def test_the_command_asks_before_building_and_a_no_builds_nothing(tmp_path, quiet, monkeypatch):
    lab, cfg, _, _ = lab_with(tmp_path, GameBrain(SMALL), art=False, sound=False)
    real_plan = proofrun.plan_phase
    monkeypatch.setattr(proofrun, "plan_phase", lambda lab, cfg_=None, **kw: real_plan(lab, cfg, **kw))
    monkeypatch.setattr(proofrun, "read_balances", FakeBalance())
    said = []
    code = proofrun.main(parse(["--lab", str(lab), "--no-art", "--no-sound"]), ask=lambda q: "n", out=said.append)
    assert code == 0 and proofrun.read_state(lab)["phase"] == "estimated"
    assert any("The plan:" in s for s in said) and any("waiting for your yes" in s for s in said)
    said.clear()
    proofrun.main(parse(["--lab", str(lab), "--report"]), out=said.append)
    assert said[0].startswith("Planned and priced; waiting for your yes")


def test_the_command_takes_an_idea_from_a_file_and_prepares_a_lab(tmp_path, monkeypatch):
    idea = tmp_path / "idea.md"
    idea.write_text("A made-up game about a snail racing the rain.\n", encoding="utf-8")
    seen = {}
    monkeypatch.setattr(proofrun, "run", lambda lab, **kw: seen.update(lab=lab) or proofrun.report(lab))
    said = []
    proofrun.main(parse(["--lab", str(tmp_path / "lab"), "--idea", str(idea), "--no-art", "--yes"]), out=said.append)
    st = proofrun.read_state(tmp_path / "lab")
    assert st["idea"].startswith("A made-up game about a snail") and st["caps"]["art_usd"] == 0
    assert seen["lab"] == tmp_path / "lab"


# -- the app ---------------------------------------------------------------------------------------------------
class FakeApp:
    def __init__(self, lab):
        from roundtable.ui.server import Jobs

        self.proofrun_lab = lab
        self.jobs = Jobs()

    def cfg(self):
        return None


def wait(job_view, app, timeout=60):
    import time

    job = app.jobs.jobs[job_view["id"]]
    end = time.time() + timeout
    while job.status == "running" and time.time() < end:
        time.sleep(0.05)
    return job


def test_the_app_asks_first_then_plans_then_asks_again_before_building(tmp_path, quiet, monkeypatch):
    from roundtable.ui import proofrunapi

    lab, cfg, _, _ = lab_with(tmp_path, GameBrain(SMALL), art=False, sound=False)
    app = FakeApp(lab)
    real_plan, real_build = proofrun.plan_phase, proofrun.build_phase
    monkeypatch.setattr(proofrun, "plan_phase", lambda lab, cfg_=None, **kw: real_plan(lab, cfg, balance=FakeBalance(), **kw))
    monkeypatch.setattr(proofrun, "build_phase", lambda lab, cfg_=None, **kw: real_build(lab, cfg, balance=FakeBalance(), **kw))
    r = proofrunapi.routes(app)
    v = r[("GET", "/api/proofrun")]({})
    assert v["about"] == proofrun.ABOUT and v["phase"] == "prepared" and not v["busy"]
    q = r[("POST", "/api/proofrun/start")]({})
    assert q["confirm"] and "stops at $2.00" in q["question"]  # the lab's own caps (no pictures, no sound)
    assert proofrun.read_state(lab)["phase"] == "prepared"  # nothing happened yet
    job = wait(r[("POST", "/api/proofrun/start")]({"confirm": True})["job"], app)
    assert job.status == "done", job.error
    assert r[("GET", "/api/proofrun")]({})["phase"] == "estimated"
    q = r[("POST", "/api/proofrun/build")]({})
    assert q["confirm"] and "Build it now?" in q["question"]
    job = wait(r[("POST", "/api/proofrun/build")]({"confirm": True})["job"], app, timeout=120)
    assert job.status == "done", job.error
    v = r[("GET", "/api/proofrun")]({})
    assert v["phase"] == "done" and v["money"]["table"]
    # a new one puts the old aside, never deletes it
    assert r[("POST", "/api/proofrun/new")]({})["confirm"]
    aside = r[("POST", "/api/proofrun/new")]({"confirm": True})["aside"]
    from pathlib import Path

    assert Path(aside).is_dir()
    assert not lab.exists()


def test_the_app_refuses_to_build_without_a_priced_plan(tmp_path):
    from roundtable.ui import proofrunapi
    from roundtable.ui.server import ApiError

    app = FakeApp(tmp_path / "lab")
    with pytest.raises(ApiError, match="Press Start first"):
        proofrunapi.build(app, {"confirm": True})
    assert proofrunapi.view(app)["ready"] is False


def test_the_routes_load_as_a_feature(monkeypatch):
    from roundtable.ui import server

    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "proofrunapi"))
    got = server._feature_routes(FakeApp(None))
    assert ("GET", "/api/proofrun") in got and ("POST", "/api/proofrun/build") in got


def test_the_report_is_numbers_and_plain_sentences(tmp_path, quiet):
    lab, cfg, _, _ = lab_with(tmp_path, GameBrain(SMALL), art=False, sound=False)
    rep = proofrun.run(lab, cfg, yes=lambda w: True, balance=FakeBalance())
    json.dumps(rep)  # it can be sent as it is
    assert rep["words"].startswith("Built: 2 of 2 tasks passed")
    assert {"money", "tasks", "people", "done_list", "screenshots", "looks", "sounds", "seeing", "time"} <= set(rep)
