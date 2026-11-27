"""Limits per service and per job, what's left, and who has seen a project (harness/usage.py, ui/usageapi.py).

The owner: "Money is the owner's." Every project is made up, in tmp_path; the models are scripted (the maker
is the provider id); the ledger lives in a made-up app home. No network, no keys.
"""

import inspect
import json
import threading

import pytest

from roundtable import phone
from roundtable.harness import projectsettings as ps
from roundtable.harness import usage
from roundtable.harness.config import ModelRef, parse_config
from roundtable.harness.orchestrator import Orchestrator
from roundtable.providers.base import Usage
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider

from .test_harness import Brain

ONE = [{"id": "T1", "title": "one", "role": "coder", "description": "write one.txt please, secret words here",
        "acceptance": "exists", "depends_on": []}]
GOAL = "a made-up tool for counting pebbles"

# every call is 100 tokens in and 20 out: $0.12 at these prices; the planner and the reviewer are on "c"
RAW = {
    "providers": {"a": {"type": "scripted"}, "b": {"type": "scripted"}, "c": {"type": "scripted"},
                  "img": {"type": "scripted_images"}},
    "roles": {"orchestrator": {"model": "c/planner"}, "coder": {"model": "a/coder", "fallback": ["b/coder2"]},
              "reviewer": {"model": "c/reviewer"}, "designer": {"kind": "image", "model": "img/pic"}},
    "pricing": {m: {"input": 1000, "output": 1000} for m in ("c/planner", "a/coder", "b/coder2", "c/reviewer")},
    "limits": {"max_cost_usd": 50, "max_attempts_per_task": 3},
}


class NoKind(Orchestrator):
    def _kind_proof(self):
        return []  # the kind guessed for a made-up project would bring its own checks


Used = NoKind if issubclass(Orchestrator, usage.UsageStage) else type("Used", (usage.UsageStage, NoKind), {})


def build(tmp_path, cls=Used, limits=None, name="proj", settings=None):
    raw = json.loads(json.dumps(RAW))
    if limits:
        raw["usage"] = limits
    cfg = parse_config(raw)
    brain = Brain(plan=ONE)
    for p in ("a", "b", "c"):
        cfg.register(p, ScriptedProvider(p, brain))
    cfg.register("img", ScriptedImages())
    if settings:
        ps.update(tmp_path / name, settings)
    events = []
    cls.usage_home = tmp_path / "home"
    orch = cls(cfg, tmp_path / name, on_event=lambda k, d: events.append((k, d)))
    orch.budget.on_use = getattr(orch, "_usage_use", None)  # as the hooked-up Orchestrator does
    return orch, events


def go(orch):
    orch.start(GOAL)
    orch.plan()
    return orch.run()


def again(tmp_path, orch, cls=Used, name="proj"):
    """The app makes a new run after the owner's answer."""
    fresh, ev = build(tmp_path, cls=cls, name=name)
    fresh.cfg.sections = orch.cfg.sections
    fresh.base_cfg = orch.base_cfg
    return fresh, ev, fresh.run()


def lines(tmp_path):
    out = []
    for p in sorted((tmp_path / "home" / "usage").glob("*.jsonl")):
        out += [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
    return out


HOOKED = "_usage_out" in inspect.getsource(Orchestrator._attempt_loop) or "_usage_words" in inspect.getsource(
    Orchestrator._attempt_loop)


# -- a service at its limit ---------------------------------------------------------------------------------------
def test_a_capped_service_is_skipped_and_the_next_model_carries_on_saying_why(tmp_path):
    orch, events = build(tmp_path, limits={"services": {"a": {"usd_per_month": 0.10}}})
    assert go(orch) == "done"
    attempts = orch.project.tasks()[0].attempts
    assert [a["model"] for a in attempts] == ["a/coder", "b/coder2"]
    assert attempts[0]["outcome"] == "error" and "The limit you set for a this month ($0.10) is reached" in \
        attempts[0]["error"]
    caps = [d for k, d in events if k == "usage_cap"]
    assert caps == [{"task": "T1", "provider": "a", "words": "The limit you set for a this month ($0.10) is reached"}]
    assert orch._usage_blocked(ModelRef("a", "coder")) and not orch._usage_blocked(ModelRef("b", "coder2"))
    # one call on a went through before the limit was seen; none after it
    assert sum(1 for r in lines(tmp_path) if r["provider"] == "a") == 1


def test_a_service_already_at_its_limit_is_never_called(tmp_path):
    usage.record({**usage.row_for("a/coder", Usage(100, 20), 5.0, "coder", tmp_path / "other"), "role": "coder"},
                 tmp_path / "home")
    orch, events = build(tmp_path, limits={"services": {"a": {"usd_per_day": 1}}})
    assert go(orch) == "done"
    assert [a["model"] for a in orch.project.tasks()[0].attempts] == ["b/coder2"]
    assert not [r for r in lines(tmp_path) if r["provider"] == "a" and r["project"] == "proj"]


def test_with_every_service_capped_the_run_pauses_with_the_limits_words(tmp_path):
    orch, _ = build(tmp_path, limits={"services": {"a": {"usd_per_month": 0.10}, "b": {"tokens_per_day": 100}}})
    assert go(orch) == "paused"
    meta = orch.project.meta()
    assert meta["status"] == "paused" and orch.project.tasks()[0].status == "pending"
    got = orch._usage_out(["a", "b"])
    assert isinstance(got, usage.ServiceCapReached) and got.pause == "service_cap"
    assert str(got) == ("The limit you set for a this month ($0.10) is reached; "
                        "The limit you set for b today (100 tokens) is reached")
    assert orch._usage_out(["x"]) is None  # not the owner's limit: an account really ran out
    if HOOKED:
        assert meta["pause"] == "service_cap" and meta["reason"].startswith("The limit you set for a this month")


def test_the_service_card_raises_the_limit_once_and_carries_on(tmp_path):
    h = tmp_path / "harness.yaml"
    h.write_text("{}\n")
    orch, _ = build(tmp_path, limits={"services": {"a": {"usd_per_month": 0.10}, "b": {"usd_per_month": 0.10}}})
    orch.base_cfg.path = orch.cfg.path = h
    assert go(orch) == "paused"
    orch._usage_out(["a", "b"])
    orch._set_status("paused", pause="service_cap")  # what the hooked-up run writes
    card = usage.job_cap_ask(orch)
    assert card["question"].endswith("is reached. It waits for you.")
    assert [o["id"] for o in card["options"]] == ["more", "stop"] and "confirm" in card["options"][0]
    got = usage.apply_answer(orch, "service_cap", "more")
    assert got["then"] == "run" and "a's limit this month is now $0.20" in got["reply"]
    assert usage.settings(orch.cfg)["services"]["a"] == {"usd_per_month": 0.2}
    assert "service_cap" not in orch.project.meta()


# -- a job at its limit -------------------------------------------------------------------------------------------
def test_a_job_cap_pauses_mid_task_and_carry_on_gives_as_much_again_once(tmp_path):
    limits = {"jobs": {"coder": {"usd_per_project": 0.2}}}
    orch, events = build(tmp_path, limits=limits)
    assert go(orch) == "paused"
    meta = orch.project.meta()
    assert meta["pause"] == "job_cap" and orch.project.tasks()[0].status == "pending"
    assert meta["job_cap"]["allowed"] == 0.2
    card = usage.job_cap_ask(orch)
    assert card["question"].startswith("The limit you set for the Coder on this project ($0.20) is reached")
    more = card["options"][0]
    assert more["label"] == "Carry on with as much again ($0.20 more)" and "$0.20 more" in more["confirm"]
    assert card["source"]["pause"] == "job_cap"
    assert usage.apply_answer(orch, "job_cap", "more")["reply"] == \
        "Carrying on: the Coder may now use up to $0.40 on this project."
    fresh, _, status = again(tmp_path, orch)
    assert status == "paused"  # it went on to $0.40, then asked again: one "carry on" is as much again, once
    meta = fresh.project.meta()
    assert meta["job_cap"]["allowed"] == 0.4 and meta["job_cap_extra"] == {"coder": 1}
    assert usage.job_used(fresh.project.root, "coder", tmp_path / "home")["usd"] == pytest.approx(0.48)


def test_a_job_cap_in_tokens(tmp_path):
    orch, _ = build(tmp_path, limits={"jobs": {"coder": {"tokens_per_project": 200}}})
    assert go(orch) == "paused"
    assert usage.job_cap_ask(orch)["options"][0]["label"] == "Carry on with as much again (200 tokens more)"


# -- no limit set: exactly as before ------------------------------------------------------------------------------
def _shape(orch):
    tasks = [(t.id, t.status, [(a["model"], a["outcome"], sorted(a)) for a in t.attempts])
             for t in orch.project.tasks()]
    rows = [json.loads(x) for x in (orch.project.root / ".harness/metrics.jsonl").read_text().splitlines()]
    return tasks, [(r["model"], r["outcome"], sorted(r)) for r in rows], orch.budget.spent_usd


def test_with_no_limit_set_a_run_is_as_before(tmp_path):
    bare = type("Bare", (NoKind,), {"_usage_use": None, "_usage_blocked": None})  # no ledger, no limits
    before, ev1 = build(tmp_path, cls=bare, name="p1")
    after, ev2 = build(tmp_path, cls=Used, name="p2")
    assert go(before) == go(after) == "done"
    assert _shape(before) == _shape(after)
    assert [k for k, _ in ev1] == [k for k, _ in ev2]
    assert lines(tmp_path) and {r["project"] for r in lines(tmp_path)} == {"p2"}


# -- the ledger -----------------------------------------------------------------------------------------------------
def test_the_ledger_holds_numbers_and_names_only(tmp_path):
    orch, _ = build(tmp_path)
    assert go(orch) == "done"
    rows = lines(tmp_path)
    assert rows and all(set(r) == {"at", "day", "provider", "maker", "model", "role", "project", "pid", "input",
                                   "output", "usd"} for r in rows)
    text = "".join(p.read_text() for p in (tmp_path / "home" / "usage").glob("*.jsonl"))
    for secret in ("pebbles", "secret words", "write one.txt", str(tmp_path)):
        assert secret not in text
    assert {r["role"] for r in rows} >= {"orchestrator", "coder", "reviewer"}


def test_two_projects_charging_at_once_lose_no_lines(tmp_path):
    one, _ = build(tmp_path, name="p1")
    two, _ = build(tmp_path, name="p2")

    def spend(orch):
        for _ in range(300):
            orch.budget.charge(0.001, ref=ModelRef("a", "coder"), usage=Usage(10, 5), role="coder")

    usage.service_used("a", tmp_path / "home")  # a cached sum, read again only for what's added
    threads = [threading.Thread(target=spend, args=(o,)) for o in (one, two, one, two)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    rows = lines(tmp_path)
    assert len(rows) == 1200 and sum(1 for r in rows if r["project"] == "p1") == 600
    got = usage.service_used("a", tmp_path / "home")
    assert got["calls"] == 1200 and got["month_tokens"] == 1200 * 15 and got["month_usd"] == pytest.approx(1.2)
    assert usage.job_used(one.project.root, "coder", tmp_path / "home") == {"usd": pytest.approx(0.6),
                                                                           "tokens": 600 * 15}


def test_an_unpriced_call_is_counted_in_tokens(tmp_path):
    orch, _ = build(tmp_path)
    orch.budget.charge(None, ref=ModelRef("a", "coder"), usage=Usage(1000, 0), role="coder")
    got = usage.service_used("a", tmp_path / "home")
    assert got["unpriced"] == 1 and got["day_tokens"] == 1000 and got["month_usd"] == 0


# -- who has seen it ------------------------------------------------------------------------------------------------
def test_seen_lists_exactly_the_makers_used(tmp_path):
    orch, _ = build(tmp_path, limits={"services": {"a": {"usd_per_month": 0.10}}})
    assert go(orch) == "done"
    other, _ = build(tmp_path, name="other")  # another project's calls are not this one's
    other.budget.charge(0.1, ref=ModelRef("openrouter", "google/gemini-x"), usage=Usage(1, 1), role="coder")
    got = usage.seen(orch.project.root, tmp_path / "home")
    assert sorted((r["maker"], r["service"]) for r in got) == [("a", "a"), ("b", "b"), ("c", "c")]
    assert all(r["first"] <= r["last"] and r["calls"] >= 1 for r in got)
    assert [(r["maker"], r["service"]) for r in usage.seen(other.project.root, tmp_path / "home")] == \
        [("google", "openrouter")]
    words = usage.seen_view(other.project.root, tmp_path / "home")["words"]
    assert words == "Only Google has seen this project."
    assert usage.seen_view(tmp_path / "nobody", tmp_path / "home")["words"] == "No model has seen this project yet."


def test_limits_never_use_a_model_the_project_does_not_allow(tmp_path):
    # kept to service a: when a's limit is reached it pauses; it never falls to b
    orch, _ = build(tmp_path, limits={"services": {"a": {"usd_per_month": 0.10}}},
                    settings={"providers_allowed": ["a", "c"]})
    assert go(orch) == "paused"
    assert {r["provider"] for r in lines(tmp_path)} <= {"a", "c"}
    assert not callable(getattr(usage.UsageStage, "_route_models", None))


def test_usage_stage_never_uses_a_model_the_project_does_not_allow(tmp_path):
    test_limits_never_use_a_model_the_project_does_not_allow(tmp_path)


# -- the limits -----------------------------------------------------------------------------------------------------
def test_limits_are_cleaned_and_layered(tmp_path):
    assert usage.clean_limits({"services": {"a": {"usd_per_day": "2", "tokens_per_day": 0}}}) == \
        {"services": {"a": {"usd_per_day": 2.0}}, "jobs": {}}
    for bad in ({"services": {"a": {"usd_per_day": -1}}}, {"services": {"a": {"usd": 1}}},
                {"jobs": {"no good!": {"usd_per_project": 1}}}, {"jobs": {"coder": {"usd_per_project": "lots"}}}):
        with pytest.raises(ValueError):
            usage.clean_limits(bad)
    h = tmp_path / "harness.yaml"
    h.write_text("{}\n")
    cfg = parse_config({**RAW, "usage": {"services": {"a": {"usd_per_day": 1, "usd_per_month": 10}}}})
    cfg.path = h
    usage.save_limits(h, {"services": {"a": {"usd_per_month": 0, "tokens_per_day": 500}}})
    assert usage.settings(cfg)["services"]["a"] == {"usd_per_day": 1, "tokens_per_day": 500}
    assert "harness.yaml" not in [p.name for p in tmp_path.iterdir() if p.read_text() != "{}\n"]


def test_words_short_first():
    assert usage.usd(20) == "$20" and usage.usd(3.1) == "$3.10" and usage.usd(0.004) == "$0.0040"
    assert usage.tokens(2_000_000) == "2,000,000 tokens"


# -- the API --------------------------------------------------------------------------------------------------------
class App:
    def __init__(self, tmp_path, cfg, projects=()):
        self._cfg, self.home, self.projects = cfg, tmp_path / "home", list(projects)
        self.harness_config_path = cfg.path

    def cfg(self):
        return self._cfg

    def need_cfg(self):
        return self._cfg

    def _backup_home(self):
        return self.home

    def project(self, cfg, path):
        from roundtable.harness.orchestrator import Project
        from roundtable.ui.server import ApiError

        p = __import__("pathlib").Path(path).resolve()
        if p not in self.projects:
            raise ApiError("That project isn't on this computer", 404)
        return Project(p)


def test_the_api_shows_what_is_used_and_saves_limits(tmp_path):
    from roundtable.ui import usageapi
    from roundtable.ui.server import ApiError

    h = tmp_path / "harness.yaml"
    h.write_text("{}\n")
    raw = json.loads(json.dumps(RAW))
    raw["providers"]["deepseek"] = {"type": "openai_compat", "base_url": "https://api.deepseek.com"}
    raw["providers"]["claude-code"] = {"type": "cli"}
    cfg = parse_config(raw)
    cfg.path = h
    usage.record(usage.row_for("deepseek/deepseek-chat", Usage(1000, 100), 3.10, "coder", tmp_path / "p"),
                 tmp_path / "home")
    usage.record(usage.row_for("claude-code/opus", Usage(5000, 100), None, "coder", tmp_path / "p"), tmp_path / "home")
    app = App(tmp_path, cfg, [(tmp_path / "p").resolve()])
    r = usageapi.routes(app)
    got = r[("POST", "/api/usage/limits")]({"services": {"deepseek": {"usd_per_month": 20}},
                                            "jobs": {"coder": {"usd_per_project": 5}}})
    ds = next(s for s in got["services"] if s["id"] == "deepseek")
    assert ds["words"] == "DeepSeek: $3.10 of $20 this month" and ds["left"]["month_usd"] == pytest.approx(16.9)
    cc = next(s for s in got["services"] if s["id"] == "claude-code")
    assert cc["subscription"] and "can't be read" in cc["words"] and "5,100 tokens" in cc["words"]
    assert next(j for j in got["jobs"] if j["role"] == "coder")["caps"] == {"usd_per_project": 5}
    with pytest.raises(ApiError):
        r[("POST", "/api/usage/limits")]({"services": {"deepseek": {"usd_per_month": -3}}})
    assert usage.settings(cfg)["services"]["deepseek"] == {"usd_per_month": 20}  # the bad change changed nothing
    seen = r[("GET", "/api/usage/seen")]({"path": [str(tmp_path / "p")]})
    assert sorted(r["maker"] for r in seen["makers"]) == ["claude-code", "deepseek"]
    with pytest.raises(ApiError):
        r[("GET", "/api/usage/seen")]({"path": [str(tmp_path / "elsewhere")]})
    app._usage_balances = (__import__("time").time(), {"deepseek": {"amount": 14.2, "currency": "USD"}})
    view = r[("GET", "/api/usage")]({"balance": ["1"]})
    ds = next(s for s in view["services"] if s["id"] == "deepseek")
    assert ds["balance_words"] == "$14.20 left in your DeepSeek account"


def test_the_phone_can_see_usage_but_never_change_the_limits():
    assert not phone.phone_allowed("POST", "/api/usage/limits")
    assert not phone.phone_allowed("GET", "/api/usage/seen")


@pytest.mark.skipif(not HOOKED, reason="waits for the coordinator's hook-up lines (orchestrator.py, asks.py)")
def test_hooked_up_the_cards_come_through_asks(tmp_path):
    from roundtable import asks

    orch, _ = build(tmp_path, cls=NoKind, limits={"jobs": {"coder": {"usd_per_project": 0.2}}})
    assert go(orch) == "paused"
    card = next(a for a in asks.open_asks(orch) if a["kind"] == "money")
    assert card["source"]["pause"] == "job_cap"
    got = asks.answer_ask(orch, card["id"], ["more"], confirmed=True, stamp=card["stamp"])
    assert got["then"] == "run" and "$0.40" in got["reply"]
    orch2, _ = build(tmp_path, cls=NoKind, limits={"services": {"a": {"usd_per_month": 0.1},
                                                                  "b": {"usd_per_month": 0.1}}}, name="p2")
    assert go(orch2) == "paused"
    meta = orch2.project.meta()
    assert meta["pause"] == "service_cap" and meta["reason"].startswith("The limit you set for a this month ($0.10)")
    card = next(a for a in asks.open_asks(orch2) if a["kind"] == "money")
    assert "It waits for you" in card["question"]
