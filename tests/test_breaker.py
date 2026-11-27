"""The circuit breaker on one agent loop: each signal steers, then refuses, then stops."""

import json

from roundtable.harness.agent import Budget, run_agent
from roundtable.harness.breaker import Breaker, BreakerSettings, call_key
from roundtable.harness.config import ModelRef, parse_config
from roundtable.harness.tools import Tool, Toolbox, ToolError, _obj
from roundtable.providers.base import ChatResponse, ToolCall, ToolSpec, Usage
from roundtable.providers.scripted import ScriptedProvider, reply

RAW = {
    "providers": {"a": {"type": "scripted"}},
    "roles": {"orchestrator": {"model": "a/coder"}, "coder": {"model": "a/coder"}, "reviewer": {"model": "a/coder"}},
    "pricing": {"a/coder": {"input": 1, "output": 1}},
    "limits": {"max_cost_usd": 50},
}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Source:  # stands in for the Workspace: what the last write changed
    last_change = None


def setup(script, raw=RAW, **settings):
    cfg = parse_config(json.loads(json.dumps(raw)))
    prov = ScriptedProvider("a", script)
    cfg.register("a", prov)
    clock = Clock()
    brk = Breaker(BreakerSettings(**settings), clock=clock)
    return cfg, prov, clock, brk


def box(clock, src=None):
    b = Toolbox(source=src)
    s = _obj({"x": {"type": "string"}}, [])

    def look(a):
        clock.t += 1
        return "same answer"

    def fail(a):
        raise ToolError("no such file")

    def big(a):
        return "y" * 5000

    def write(a):
        src.last_change = {"diff": "+x", "added": 1, "removed": 0}
        return "written"

    def run_command(a):
        clock.t += 20 * 60  # a twenty-minute build
        return "build ok"

    for name, fn in [("look", look), ("fail", fail), ("big", big), ("write", write), ("run_command", run_command)]:
        b.add(Tool(ToolSpec(name, name, s), fn))
    b.add(Tool(ToolSpec("finish_task", "done", _obj({"summary": {"type": "string"}}, [])), lambda a: "recorded",
               terminal=True))
    return b


def forever(name, args=None, vary=False):
    n = [0]

    def script(model, system, messages, tools):
        n[0] += 1
        return reply("", [(name, {"x": str(n[0])} if vary else (args or {"x": "1"}))], id_prefix=f"s{n[0]}-")
    return script


def run(cfg, b, brk, events=None, **kw):
    ev = events if events is not None else []
    res = run_agent(cfg, ModelRef("a", "coder"), "sys", "go", b, Budget(50), max_steps=kw.pop("max_steps", 40),
                    on_event=lambda k, d: ev.append((k, d)), breaker=brk, **kw)
    return res, ev


def trips(ev):
    return [(d["action"], d["signal"]) for k, d in ev if k == "breaker"]


def tool_msgs(res):
    return [m for m in res.messages if m["role"] == "tool"]


# -- each signal: steer, refuse, stop -------------------------------------------------------
def test_identical_calls_steer_then_refuse_then_stop():
    cfg, prov, clock, brk = setup(forever("look"), no_progress_minutes=0)
    res, ev = run(cfg, box(clock), brk)
    assert res.stop == "breaker" and "same look call" in res.breaker_reason
    assert trips(ev) == [("steer", "repeats"), ("refuse", "repeats"), ("stop", "repeats")]
    msgs = tool_msgs(res)
    assert "The harness's safety check: the same look call 8 times" in msgs[7]["content"]  # steered at the 8th
    assert "second warning" in msgs[15]["content"]  # 8 more: refused next
    assert msgs[16]["content"].startswith("Refused by the harness") and msgs[16]["is_error"]
    # the refused call doesn't count: it takes 8 real ones again to stop
    assert len(msgs) == 25 and res.steps == 25
    done = [d for k, d in ev if k == "agent_done"][0]
    assert done["stop"] == "breaker" and done["breaker"] == res.breaker_reason and len(done["breaker_trips"]) == 3


def test_an_error_storm_steers_then_refuses_then_stops():
    cfg, prov, clock, brk = setup(forever("fail", vary=True), no_progress_minutes=0)
    res, ev = run(cfg, box(clock), brk)
    assert res.stop == "breaker" and "5 tool errors in a row" in res.breaker_reason
    assert trips(ev) == [("steer", "errors"), ("refuse", "errors"), ("stop", "errors")]
    assert "Read the last error carefully" in tool_msgs(res)[4]["content"]


def test_runaway_tool_output_is_cut_and_trips():
    cfg, prov, clock, brk = setup(forever("big", vary=True), max_output_chars=1000, no_progress_minutes=0)
    res, ev = run(cfg, box(clock), brk)
    assert trips(ev) == [("steer", "output"), ("refuse", "output"), ("stop", "output")]
    first = tool_msgs(res)[0]["content"]
    assert first.startswith("y" * 1000) and "cut by the harness: 4,000 more characters" in first
    assert len(first) < 1500


def test_a_runaway_reply_trips():
    def script(model, system, messages, tools):
        return reply("z" * 2000, [("look", {"x": str(len(messages))})])
    cfg, prov, clock, brk = setup(script, max_output_chars=1000, no_progress_minutes=0)
    res, ev = run(cfg, box(clock), brk)
    assert res.stop == "breaker" and "a reply of 2,000 characters" in res.breaker_reason
    assert trips(ev) == [("steer", "output"), ("refuse", "output"), ("stop", "output")]
    assert res.steps == 3  # one level a step; stopped before the third step's tools ran
    msgs = tool_msgs(res)
    assert len(msgs) == 2 and msgs[1]["content"].startswith("Refused")


def test_the_token_cap_steers_refuses_but_lets_it_finish():
    def script(model, system, messages, tools):
        r = reply("", [("look", {"x": str(len(messages))})])
        r.usage = Usage(input_tokens=400, output_tokens=100)
        return r
    cfg, prov, clock, brk = setup(script, max_tokens_per_task=1000, no_progress_minutes=0)
    res, ev = run(cfg, box(clock), brk)
    assert trips(ev) == [("steer", "tokens"), ("refuse", "tokens"), ("stop", "tokens")]
    assert res.steps == 4 and "1,000 tokens used" in trips_reason(ev, 0)


def trips_reason(ev, i):
    return [d["reason"] for k, d in ev if k == "breaker"][i]


def test_no_progress_steers_then_refuses_then_stops():
    # different calls each time would be progress; alternating between two already seen is not
    n = [0]

    def script(model, system, messages, tools):
        n[0] += 1
        clock.t += 60  # each reply takes a minute
        return reply("", [("look", {"x": str(n[0] % 2)})], id_prefix=f"s{n[0]}-")
    cfg, prov, clock, brk = setup(script, repeats=0)
    res, ev = run(cfg, box(clock), brk, max_steps=100)
    assert trips(ev) == [("steer", "no_progress"), ("refuse", "no_progress"), ("stop", "no_progress")]
    assert "5 minutes without changing a file" in res.breaker_reason


def test_a_long_command_is_not_no_progress():
    calls = iter([("run_command", {"x": "build"})] * 3 + [("finish_task", {"summary": "built"})])
    cfg, prov, clock, brk = setup(lambda *a: reply("", [next(calls)]))
    res, ev = run(cfg, box(clock), brk)
    assert res.stop == "terminal" and trips(ev) == []
    assert clock.t - 1000 >= 60 * 60  # an hour of building, and the breaker stayed quiet


def test_a_changed_file_is_progress_and_lowers_the_level():
    src = Source()
    seq = [("look", {"x": "1"})] * 8 + [("write", {"x": "a"})] + [("look", {"x": "1"})] * 8 + [("finish_task", {})]
    calls = iter(seq)
    cfg, prov, clock, brk = setup(lambda *a: reply("", [next(calls)]), no_progress_minutes=0)
    res, ev = run(cfg, box(clock, src), brk)
    assert res.stop == "terminal"
    assert trips(ev) == [("steer", "repeats"), ("steer", "repeats")]  # the write took it back down


def test_switched_off_and_settings_from_harness_yaml():
    raw = {**RAW, "breaker": {"enabled": False}}
    cfg, prov, clock, _ = setup(forever("look"), raw=raw)
    res, ev = run(cfg, box(clock), None, max_steps=30)
    assert res.stop == "max_steps" and trips(ev) == []

    raw = {**RAW, "breaker": {"repeats": 3, "errors": "2", "max_output_chars": 50, "no_progress_minutes": 1.5,
                              "max_tokens_per_task": 0, "quiet_tools": ["run_tests"]}}
    s = BreakerSettings.from_config(parse_config(json.loads(json.dumps(raw))))
    assert (s.repeats, s.errors, s.max_output_chars, s.no_progress_minutes, s.max_tokens_per_task, s.quiet_tools) == \
        (3, 2, 50, 1.5, 0, ("run_tests",))
    d = BreakerSettings.from_config(parse_config(json.loads(json.dumps(RAW))))
    assert (d.enabled, d.repeats, d.errors, d.no_progress_minutes) == (True, 8, 5, 5.0)

    cfg, prov, clock, _ = setup(forever("look"), raw={**RAW, "breaker": {"repeats": 3, "no_progress_minutes": 0}})
    res, ev = run(cfg, box(clock), None)
    assert res.stop == "breaker" and res.steps == 10  # 3: steer; 3 more: refuse; one refused; 3 more: stop


def test_events_carry_how_long_each_call_took():
    calls = iter([("look", {"x": "1"}), ("run_command", {"x": "t"}), ("finish_task", {"summary": "s"})])
    clock = Clock()

    def script(model, system, messages, tools):
        clock.t += 2.5
        return reply("", [next(calls)])
    cfg, prov, _, _ = setup(script)
    brk = Breaker(BreakerSettings(), clock=clock)
    res, ev = run(cfg, box(clock), brk)
    turns = [d for k, d in ev if k == "model_turn"]
    tools = [d for k, d in ev if k == "tool_call"]
    assert [t["ms"] for t in turns] == [2500, 2500, 2500]
    assert [t["ms"] for t in tools] == [1000, 1_200_000, 0]
    done = [d for k, d in ev if k == "agent_done"][0]
    assert done["model_ms"] == 7500 and done["tool_ms"] == 1_201_000 and done["other_ms"] == 0
    assert done["ms"] == 1_208_500 and done["stop"] == "terminal" and "breaker" not in done
    assert (res.model_ms, res.tool_ms, res.other_ms) == (7500, 1_201_000, 0)


def test_call_key_hashes_capped_arguments():
    long_a = "cd /a/very/long/path && " * 50 + "measure 1"
    long_b = "cd /a/very/long/path && " * 50 + "measure 2"
    assert call_key("run_command", {"command": long_a}) != call_key("run_command", {"command": long_b})
    assert call_key("look", {"a": 1, "b": 2}) == call_key("look", {"b": 2, "a": 1})
    assert call_key("look", {"x": "1"}) != call_key("other", {"x": "1"})


def test_one_level_a_step_even_when_several_signals_trip():
    def script(model, system, messages, tools):
        r = ChatResponse(text="", tool_calls=[ToolCall(id=f"c{len(messages)}", name="big", arguments={"x": "1"})],
                         stop_reason="tool_use", usage=Usage(400, 100))
        return r
    cfg, prov, clock, brk = setup(script, max_output_chars=100, max_tokens_per_task=100, no_progress_minutes=0)
    res, ev = run(cfg, box(clock), brk)
    assert [a for a, _ in trips(ev)] == ["steer", "refuse", "stop"] and res.steps == 3


def test_a_reply_that_finishes_is_never_stopped():
    calls = iter([("look", {"x": "1"}), ("look", {"x": "2"}), ("look", {"x": "3"}), ("finish_task", {"summary": "ok"})])

    def script(model, system, messages, tools):
        r = reply("", [next(calls)])
        r.usage = Usage(input_tokens=400, output_tokens=100)
        return r
    cfg, _, clock, brk = setup(script, max_tokens_per_task=1000, no_progress_minutes=0)
    res, ev = run(cfg, box(clock), brk)
    assert trips(ev) == [("steer", "tokens"), ("refuse", "tokens")] and res.stop == "terminal"
    assert res.captured["finish_task"] == {"summary": "ok"}
