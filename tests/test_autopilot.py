"""Autopilot (autopilot.py): what waits is answered with the recommendation while the owner is away, inside
its guard rails. Made-up projects, scripted models, no network."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from roundtable import asks as asklib
from roundtable import autopilot
from roundtable.harness.orchestrator import Orchestrator

from .test_asks import DOC_TASK, QUESTIONS, CardBrain, RejectBrain, add_looks, with_profiles
from .test_harness import Brain, make


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


def lab_raw(tmp_path, raw=None):
    raw = json.loads(json.dumps(raw or with_profiles()))
    raw.setdefault("improve", {})["lab_dir"] = str(tmp_path / "lab")
    return raw


def planned(tmp_path, raw=None, brain=None):
    """A project whose plan waits for the owner, registered in the lab (so autopilot sees it)."""
    orch, *_ = make(tmp_path, raw=lab_raw(tmp_path, raw), brain=brain or CardBrain())
    orch.start("bakery site", require_approval=True)
    assert orch.run() == "awaiting_approval"
    return orch


def priced(orch, cost=None):
    """The scripted picture model has no price, so plans with a picture have an unknown cost (autopilot
    leaves those for the owner). Most tests want a plan whose cost is known."""
    doc = orch.project.plan_doc()
    doc["estimate"] = {**doc["estimate"], "unpriced": []}
    if cost is not None:
        doc["estimate"]["cost_usd"] = cost
    orch.project.save_plan_doc(doc)


class Starts:
    """Records the long steps autopilot starts (the desktop app starts them as jobs)."""

    def __init__(self, do=False):
        self.calls, self.do = [], do

    def __call__(self, cfg, root, result):
        self.calls.append((root.name, result["then"]))
        if self.do:
            autopilot.finish_now(cfg, root, result)


def tick(orch, home, start=None, **kw):
    return autopilot.tick(orch.base_cfg, home=home, start=start or Starts(), **kw)


def chosen(entries):
    return [(e["ask"], e["chosen"]) for e in entries if e["kind"] == "chose"]


def left(entries):
    return [e["ask"] for e in entries if e["kind"] == "left"]


def test_off_does_nothing(tmp_path, home):
    orch = planned(tmp_path)
    assert tick(orch, home) == []
    assert asklib.open_asks(orch)[0]["id"] == "choose:C1"


def test_plan_cards_get_the_recommendation_then_the_plan_is_updated(tmp_path, home):
    typed = {"id": "Q2", "text": "Anything else to know?"}  # no answers to tap: only the owner can say
    orch = planned(tmp_path, brain=CardBrain(questions=[QUESTIONS[0], typed]))
    add_looks(orch)
    autopilot.turn_on(home=home)
    starts = Starts()
    out = tick(orch, home, starts)
    assert chosen(out) == [("choose:C1", ["a"]), ("answer:Q1", ["a"]), ("look", ["A"]), ("profile", ["balanced"]),
                           ("idea:I1", ["yes"]), ("approve", ["revise"])]
    assert left(out) == ["answer:Q2"]  # no recommended answer: it waits for the owner
    assert starts.calls == [("proj", "revise")]
    doc = orch.project.plan_doc()
    assert doc["decisions"][0]["chosen"] == "a" and doc["questions"][0]["chosen"] == ["a"]
    assert doc["look"]["chosen"] == "A" and doc["ideas"][0]["state"] == "accepted"
    assert orch.project.meta()["profile"] == "balanced"
    # every decision is in the log, in plain words, newest first; the markdown log too
    log = autopilot.entries(home)
    assert log[0]["ask"] == "approve" and log[-1]["kind"] == "on"
    assert "Autopilot chose “Pixel art” for “Which logo style?” because it's the recommended answer" in \
        next(e["text"] for e in log if e.get("ask") == "choose:C1")
    md = (home / "autopilot-log.md").read_text(encoding="utf-8")
    assert md.startswith("# What autopilot did") and "Left for you" in md and "**proj**" in md
    # a card left for the owner is written once, not on every tick
    assert left(tick(orch, home, Starts())) == []
    # the owner can still change an answer before approving
    asklib.answer_ask(orch, "choose:C1", ["b"])
    assert orch.project.plan_doc()["decisions"][0]["chosen"] == "b"


def test_then_it_approves_within_its_limit(tmp_path, home):
    orch = planned(tmp_path)
    autopilot.turn_on(home=home)
    starts = Starts(do=True)
    tick(orch, home, starts)  # answers, then updates the plan (here and now)
    ask = next(a for a in asklib.open_asks(orch) if a["kind"] == "approve")
    assert autopilot.decide(orch, ask, autopilot.load(home)) == (None, "the plan's cost isn't known, so it waits for you")
    priced(orch)
    out = tick(orch, home, starts)
    assert chosen(out) == [("approve", ["approve"])] and starts.calls[-1] == ("proj", "run")
    assert "fits what's left of autopilot's limit" in out[0]["text"]
    meta = orch.project.meta()
    assert meta["plan_approved"] and meta["status"] == "done"


def test_approve_waits_when_the_estimate_is_over_the_limit(tmp_path, home):
    orch = planned(tmp_path)
    autopilot.turn_on(cap=0.01, home=home)
    priced(orch, 0.5)
    for a in asklib.open_asks(orch):  # the owner answered the plan's questions already
        if a["kind"] != "approve":
            asklib.answer_ask(orch, a["id"], skip=True)
    out = tick(orch, home)
    assert left(out) == ["approve"] and "more than what's left of autopilot's limit ($0.01)" in out[0]["text"]
    assert not orch.project.meta().get("plan_approved")
    # and over the project's own limit
    autopilot.turn_on(cap=100, home=home)
    meta = orch.project.meta()
    meta["spent_usd"] = 4.8  # of the project's $5
    orch.project.save_meta(meta)
    out = tick(orch, home)
    assert left(out) == ["approve"] and "this project's own limit" in out[0]["text"]
    meta["spent_usd"] = 0
    orch.project.save_meta(meta)
    ask = next(a for a in asklib.open_asks(orch) if a["kind"] == "approve")
    assert autopilot.decide(Orchestrator(orch.base_cfg, orch.project.root), ask, autopilot.load(home))[0] == ["approve"]


def test_approve_prefers_half_price_before_until(tmp_path, home, monkeypatch):
    from roundtable.harness import orchestrator as orch_mod

    orch = planned(tmp_path)
    for a in asklib.open_asks(orch):
        if a["kind"] != "approve":
            asklib.answer_ask(orch, a["id"], skip=True)
    priced(orch)
    now = datetime(2030, 1, 1, 6, 0, tzinfo=timezone.utc)
    cheap = now + timedelta(hours=2)
    monkeypatch.setattr(orch_mod.Orchestrator, "cheap_start_at", lambda self: cheap)
    autopilot.turn_on(until=(now + timedelta(hours=1)).isoformat(), home=home, now=now)
    ask = next(a for a in asklib.open_asks(orch) if a["kind"] == "approve")
    assert [o["id"] for o in ask["options"]][:2] == ["approve", "approve_cheap"]
    # half price only comes after autopilot stops: it starts now
    assert autopilot.decide(orch, ask, autopilot.load(home), now)[0] == ["approve"]
    autopilot.turn_on(until=(now + timedelta(hours=3)).isoformat(), home=home, now=now)
    out = tick(orch, home, now=now)
    assert chosen(out) == [("approve", ["approve_cheap"])] and "half price" in out[0]["text"]
    assert orch.project.meta()["status"] == "waiting_cheap"


def test_a_failed_task_is_retried_once_with_the_same_models(tmp_path, home):
    raw = lab_raw(tmp_path)
    raw["roles"]["coder"]["fallback"] = []
    orch, *_ = make(tmp_path, raw=raw, brain=RejectBrain(plan=[DOC_TASK]))
    orch.start("bakery site")
    assert orch.run() == "blocked"
    ask = asklib.open_asks(orch)[0]
    assert {"stronger", "accept", "skip"} <= {o["id"] for o in ask["options"]}
    autopilot.turn_on(home=home)
    starts = Starts(do=True)
    out = tick(orch, home, starts)
    assert chosen(out) == [("task:T1", ["retry"])] and starts.calls == [("proj", "run")]
    t = orch.project.tasks()[0]
    assert t.status == "failed" and not t.stronger  # tried again with the same model, and failed again
    assert {a["model"] for a in t.attempts} == {"a/coder"}
    out = tick(orch, home, starts)
    assert left(out) == ["task:T1"] and "already tried it once more" in out[0]["text"]
    assert orch.project.tasks()[0].status == "failed"  # never accepted or skipped


def test_money_pauses_wait_for_the_owner(tmp_path, home):
    raw = lab_raw(tmp_path)
    raw["limits"]["max_cost_usd"] = 0.0001
    orch, *_ = make(tmp_path, raw=raw, brain=Brain(plan=[DOC_TASK]))
    orch.start("bakery site")
    assert orch.run() == "paused_budget"
    autopilot.turn_on(home=home)
    out = tick(orch, home)
    assert left(out) == ["money"] and "never raises a limit" in out[0]["text"]
    meta = orch.project.meta()
    assert not meta.get("budget_extra_usd") and meta["status"] == "paused_budget" and meta.get("profile") is None


def test_never_an_are_you_sure_or_a_publish(tmp_path, home):
    orch = planned(tmp_path)
    state = autopilot.load(home)

    def card(**opt):
        return {"kind": "decision", "recommended": "x", "source": {}, "options": [
            {"id": "x", "label": "Do it", "description": "", **opt}, {"id": "y", "label": "Don't", "description": ""}]}

    assert autopilot.decide(orch, card(), state)[0] == ["x"]
    assert autopilot.decide(orch, card(confirm="Spends more. Sure?"), state)[0] is None
    assert autopilot.decide(orch, card(label="Publish the release"), state)[0] is None
    assert autopilot.decide(orch, card(label="Delete the old files"), state)[0] is None
    assert autopilot.decide(orch, {**card(), "recommended": None}, state)[0] is None
    assert autopilot.decide(orch, {**card(), "kind": "something new"}, state)[0] is None


def test_an_idea_without_a_recommendation_stays_open(tmp_path, home):
    orch = planned(tmp_path)
    doc = orch.project.plan_doc()
    doc["ideas"][0]["recommended"] = False
    orch.project.save_plan_doc(doc)
    ask = next(a for a in asklib.open_asks(orch) if a["kind"] == "idea")
    assert ask["recommended"] is None
    autopilot.turn_on(home=home)
    assert "idea:I1" in left(tick(orch, home)) and orch.project.plan_doc()["ideas"][0]["state"] == "open"


def test_it_stops_at_until_and_at_its_limit(tmp_path, home):
    orch = planned(tmp_path)
    now = datetime(2030, 1, 1, 6, 0, tzinfo=timezone.utc)
    autopilot.turn_on(until="1h", home=home, now=now)
    assert autopilot.load(home)["until"] == "2030-01-01T07:00:00Z"
    assert tick(orch, home, now=now + timedelta(minutes=61)) == []
    st = autopilot.status(home)
    assert not st["on"] and "as you asked" in st["stopped"]
    assert autopilot.entries(home)[0]["kind"] == "off"
    assert asklib.open_asks(orch)[0]["answer"] is None  # nothing was answered
    autopilot.turn_on(cap=0.5, home=home)
    orch.project.append("spend.jsonl", {"at": "2999-01-01T00:00:00Z", "cost_usd": 0.6})
    assert tick(orch, home) == []
    st = autopilot.status(home)
    assert not st["on"] and "spend limit" in st["stopped"] and st["spent_usd"] == pytest.approx(0.6, abs=0.01)


def test_until_and_the_label(home):
    now = datetime(2030, 1, 1, 6, 0, tzinfo=timezone.utc)
    assert autopilot.parse_until("", now) is None and autopilot.parse_until("back", now) is None
    assert autopilot.parse_until("90m", now) == "2030-01-01T07:30:00Z"
    local = now.astimezone()
    eight = autopilot.parse_until("tonight", now)
    t = datetime.fromisoformat(eight.replace("Z", "+00:00")).astimezone()
    assert (t.hour, t.minute) == (8, 0) and t > local and t - local <= timedelta(days=1)
    assert autopilot.parse_until("8am", now) == eight == autopilot.parse_until("08:00", now)
    with pytest.raises(ValueError):
        autopilot.parse_until("25:00", now)
    with pytest.raises(ValueError):
        autopilot.parse_until("soonish", now)
    autopilot.turn_on(until="tonight", cap=2, home=home)
    assert autopilot.status(home)["label"] == "until 8am · $0.00 of $2.00"
    with pytest.raises(ValueError):
        autopilot.turn_on(cap=0, home=home)


def test_a_project_can_be_kept_off_autopilot(tmp_path, home):
    orch = planned(tmp_path)
    autopilot.turn_on(home=home)
    autopilot.set_never("proj", home=home)
    assert tick(orch, home) == [] and asklib.open_asks(orch)[0]["id"] == "choose:C1"
    autopilot.set_never("proj", False, home=home)
    assert chosen(tick(orch, home))


def test_switching_and_decisions_go_in_the_journal(tmp_path, home):
    import yaml

    from roundtable.core.config import load_config as load_hub
    from roundtable.hub.service import Hub

    from .test_hub import RAW as HUB_RAW

    hub_raw = json.loads(json.dumps(HUB_RAW))
    hub_raw["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
    (tmp_path / "hub.yaml").write_text(yaml.safe_dump(hub_raw), encoding="utf-8")
    raw = with_profiles()
    raw["hub"] = {"config": str(tmp_path / "hub.yaml"), "agent": "backend"}
    orch = planned(tmp_path, raw=raw)
    autopilot.turn_on(home=home, cfg=orch.base_cfg)
    tick(orch, home)
    hub = Hub(load_hub(str(tmp_path / "hub.yaml")))
    texts = [e["text"] for e in hub.journal.entries("backend", "backend", kinds=["decision"], limit=50)]
    assert any(t.startswith("Autopilot on") for t in texts)
    assert any("proj: Autopilot chose “Pixel art”" in t for t in texts)
    # the phone (Hub mode) reads the switch and the log from the hub
    data = json.loads((tmp_path / "hubdata" / "plans" / "autopilot.json").read_text(encoding="utf-8"))
    assert data["on"] and data["inbox"] == "backend" and data["log"][0]["project"] == "proj"
    autopilot.turn_off("you turned it off.", home, orch.base_cfg)
    texts = [e["text"] for e in hub.journal.entries("backend", "backend", kinds=["decision"], limit=50)]
    assert any(t.startswith("Autopilot off") for t in texts)


def test_the_remote_command(tmp_path, home, monkeypatch):
    from roundtable import remote

    monkeypatch.setenv("ROUNDTABLE_HOME", str(home))
    orch = planned(tmp_path)
    say = lambda **kw: remote.execute(orch.cfg, orch.project.root, {"action": "autopilot", **kw})  # noqa: E731
    assert say(state="on", until="1h", cap=1) .startswith("Autopilot on, until ")
    st = autopilot.status()
    assert st["on"] and st["spend_cap_usd"] == 1
    assert say(project="proj", never=True) == "proj is never on autopilot." and autopilot.status()["never"] == ["proj"]
    assert say() .startswith("Autopilot: until")
    assert say(on=False) == "Autopilot off." and not autopilot.status()["on"]
    assert "autopilot" not in remote.LONG


def test_the_api_and_the_desktop_tick(tmp_path, home, monkeypatch):
    from roundtable.phone import phone_allowed
    from roundtable.ui.roundtable import AutoSync, build
    from roundtable.ui.server import ApiError, UIApp

    from .test_ui import call, wait_job

    monkeypatch.setenv("ROUNDTABLE_HOME", str(home))
    orch = planned(tmp_path)
    app = UIApp(hub_config=str(tmp_path / "none.yaml"), harness_config=str(tmp_path / "missing.yaml"))
    app.cfg = lambda: orch.base_cfg
    assert call(app, "GET", "/api/autopilot")["on"] is False
    r = call(app, "POST", "/api/autopilot", {"action": "on", "until": "", "cap": 1.5})
    assert r["on"] and r["label"] == "until you're back · $0.00 of $1.50" and r["log"][0]["kind"] == "on"
    with pytest.raises(ApiError, match="spend limit"):
        call(app, "POST", "/api/autopilot", {"action": "on", "cap": -1})
    seat = next(s for s in build(app)["seats"] if s["id"] == "proj")
    assert seat["autopilot"] and build(app)["autopilot"]["on"]
    AutoSync(app).tick()  # the desktop's tick answers, and starts the plan update as a job
    job = next(j for j in app.jobs.jobs.values() if j.target == str(orch.project.root))
    assert "autopilot" in job.title and wait_job(app, job.id)["status"] == "done"
    log = call(app, "GET", "/api/autopilot")["log"]
    assert any(e.get("ask") == "choose:C1" for e in log)
    priced(orch)
    AutoSync(app).tick()  # the plan is updated: now it approves (within $1.50) and the run starts
    assert any(e.get("ask") == "approve" and e.get("chosen") == ["approve"]
               for e in call(app, "GET", "/api/autopilot")["log"])
    run = next(j for j in app.jobs.jobs.values() if j.kind == "run")
    assert wait_job(app, run.id)["result"]["reply"] == "The run ended as: done."
    call(app, "POST", "/api/autopilot", {"action": "never", "project": "proj"})
    assert not next(s for s in build(app)["seats"] if s["id"] == "proj")["autopilot"]
    assert call(app, "POST", "/api/autopilot", {"action": "off"})["on"] is False
    assert phone_allowed("GET", "/api/autopilot") and phone_allowed("POST", "/api/autopilot")


def test_the_command_line(tmp_path, home, monkeypatch, capsys):
    from roundtable.main import main

    monkeypatch.setenv("ROUNDTABLE_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    main(["autopilot", "on", "--until", "1h", "--cap", "3"])
    assert "Autopilot on, until" in capsys.readouterr().out and autopilot.status()["spend_cap_usd"] == 3
    main(["autopilot", "never", "bakery"])
    assert autopilot.status()["never"] == ["bakery"]
    main(["autopilot", "never", "bakery", "--undo"])
    main(["autopilot", "status"])
    assert "of $3.00" in capsys.readouterr().out
    main(["autopilot", "off"])
    main(["autopilot", "log"])
    out = capsys.readouterr().out
    assert "Autopilot off: you turned it off." in out and "Autopilot on" in out
