"""Compaction: a long task's older steps summed up by a cheap model (plugins/builtin/compactor.py)."""

import json

from roundtable.harness.agent import Budget, run_agent
from roundtable.harness.config import ModelRef, parse_config
from roundtable.harness.tools import Tool, Toolbox, _obj
from roundtable.plugins.builtin import compactor
from roundtable.plugins.host import estimate_tokens, valid_compaction
from roundtable.providers.base import ChatResponse, ToolCall, ToolSpec, Usage
from roundtable.providers.scripted import ScriptedProvider

RAW = {
    "providers": {"a": {"type": "scripted"}, "cheap": {"type": "scripted"}},
    "roles": {"orchestrator": {"model": "a/planner"}, "reviewer": {"model": "a/planner"},
              "coder": {"model": "a/coder", "fallback": ["cheap/flash"]}},
    "pricing": {"a/coder": {"input": 1, "output": 1}, "a/planner": {"input": 1, "output": 1},
                "cheap/flash": {"input": 0.1, "output": 0.1}},
    "limits": {"max_cost_usd": 100},
    "token_saver": False,
    "compaction": {"at_tokens": 20_000, "keep_last_steps": 2},
}

TASK = ("# Project\nA made-up shop for garden gnomes.\n\n# Your task [t3] Add the basket page\nMake basket.html "
        "with a list of gnomes.\n\n# Acceptance criteria\nbasket.html lists three gnomes and a total.")
CHUNK = "x" * 16_000  # about 4,000 tokens a tool result


class Source:  # stands in for the Workspace: the files changed so far
    def __init__(self):
        self.changed: set[str] = set()
        self.last_change = None


def setup(raw=RAW, steps=25):
    cfg = parse_config(json.loads(json.dumps(raw)))
    seen: list[int] = []

    def worker(model, system, messages, tools):
        tokens = estimate_tokens(messages) + len(system) // 4
        seen.append(tokens)
        n = len(seen)
        call = ("finish", {"note": "all done"}) if n >= steps else ("write", {"path": f"src/part{n}.js", "n": n})
        return ChatResponse(text=f"step {n}", tool_calls=[ToolCall(f"w{n}", *call)], stop_reason="tool_use",
                            usage=Usage(input_tokens=tokens, output_tokens=50))

    def cheap(model, system, messages, tools):
        assert "earlier steps" in messages[0]["content"]
        return ChatResponse(text="Decisions:\n- plain HTML, no framework\nErrors and fixes:\n- none",
                            usage=Usage(input_tokens=1000, output_tokens=100))

    main, small = ScriptedProvider("a", worker), ScriptedProvider("cheap", cheap)
    cfg.register("a", main)
    cfg.register("cheap", small)
    src = Source()
    box = Toolbox(source=src)

    def write(a):
        src.changed.add(a["path"])
        return f"wrote {a['path']}\n" + CHUNK

    box.add(Tool(ToolSpec("write", "write a file", _obj({"path": {"type": "string"}}, [])), write))
    box.add(Tool(ToolSpec("finish", "done", _obj({}, [])), lambda a: "ok", terminal=True))
    return cfg, main, small, box, seen


def run(cfg, box, budget=None, events=None):
    budget = budget or Budget(100)
    log = events if events is not None else []
    res = run_agent(cfg, ModelRef.parse("a/coder"), "SYSTEM AND REPOSITORY RULES", TASK, box, budget,
                    max_steps=40, role="coder", on_event=lambda k, d: log.append((k, d)))
    return res, budget, log


def test_a_long_task_stays_under_the_limit_and_finishes():
    cfg, main, small, box, seen = setup()
    res, budget, events = run(cfg, box)
    assert res.stop == "terminal" and res.steps == 25
    compacted = [d for k, d in events if k == "compacted"]
    assert compacted and small.calls  # the cheap model wrote the summaries
    # without compaction it would reach ~100,000 tokens; with it, no call is sent past the line
    assert max(seen) < 20_000
    # the system prompt (with the repository's rules) is never touched
    assert all(c["system"] == "SYSTEM AND REPOSITORY RULES" for c in main.calls)
    first = compacted[0]
    assert first["tokens_before"] >= 20_000 > first["tokens_after"]
    assert abs(first["tokens_after"] - seen[first["step"] - 1]) < 200  # the estimate is close
    assert first["messages_after"] < first["messages_before"] and first["plugin"] == "compactor"


def test_the_summary_keeps_the_task_the_files_and_the_last_steps():
    cfg, main, small, box, seen = setup()
    run(cfg, box)
    msgs = next(c["messages"] for c in main.calls if len(c["messages"]) > 1
                and compactor.MARK in str(c["messages"][1].get("content")))
    assert msgs[0] == {"role": "user", "content": TASK}  # the task, word for word, still first
    summary = msgs[1]["content"]
    assert "The task: [t3] Add the basket page" in summary
    assert "Done when: basket.html lists three gnomes and a total." in summary
    assert "Files changed so far: src/part1.js, src/part2.js" in summary
    assert "plain HTML, no framework" in summary  # the cheap model's notes
    # the last two steps, as they were: assistant turn + its result, twice
    tail = msgs[2:]
    assert [m["role"] for m in tail] == ["assistant", "tool", "assistant", "tool"]
    assert tail[-1]["content"].startswith("wrote src/part") and CHUNK in tail[-1]["content"]


def test_tool_calls_never_part_from_their_results():
    cfg, main, small, box, seen = setup()
    run(cfg, box)
    for call in main.calls:
        msgs = call["messages"]
        pending = set()
        for m in msgs:
            if m["role"] == "tool":
                assert m["tool_call_id"] in pending
                pending.discard(m["tool_call_id"])
            else:
                assert not pending
                if m["role"] == "assistant":
                    pending = {c["id"] for c in m["tool_calls"]}
    # and the check the host makes on any compaction plugin
    old = [{"role": "user", "content": "t"},
           {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "name": "x", "arguments": {}}]},
           {"role": "tool", "tool_call_id": "1", "content": "r"},
           {"role": "assistant", "content": "", "tool_calls": [{"id": "2", "name": "x", "arguments": {}}]},
           {"role": "tool", "tool_call_id": "2", "content": "r"}]
    assert valid_compaction(old, [old[0], {"role": "user", "content": "s"}] + old[3:])
    assert not valid_compaction(old, [old[0], {"role": "user", "content": "s"}] + old[4:])  # orphan result
    assert not valid_compaction(old, old[:2] + [{"role": "user", "content": "s"}])  # call without result
    assert not valid_compaction(old, [{"role": "user", "content": "s"}] + old[3:])  # the task went


def test_split_point_is_at_a_step():
    msgs = [{"role": "user"}] + [{"role": r} for r in ["assistant", "tool", "tool", "user", "assistant", "tool",
                                                        "assistant", "tool"]]
    assert compactor.split_point(msgs, 2) == 5
    assert compactor.split_point(msgs, 3) is None  # nothing older than the kept steps
    assert compactor.split_point(msgs[:5], 1) is None


def test_off_by_setting():
    raw = {**RAW, "compaction": {**RAW["compaction"], "enabled": False}}
    cfg, main, small, box, seen = setup(raw)
    res, _, events = run(cfg, box)
    assert res.stop == "terminal" and not small.calls
    assert not [k for k, _ in events if k == "compacted"]
    assert max(seen) > 90_000  # it grew all the way
    # the app's switch (custom.yaml plugins: compactor:) wins over harness.yaml
    raw2 = {**RAW, "plugins": {"compactor": {"enabled": False}}}
    cfg2, *_ = setup(raw2)
    assert cfg2.plugin_host().get("compactor").status == "off"


def test_settings_come_from_the_compaction_section():
    cfg, *_ = setup()
    on, settings = compactor.settings_from(cfg)
    assert on and settings["at_tokens"] == 20_000 and settings["keep_last_steps"] == 2
    bare = parse_config(json.loads(json.dumps({k: v for k, v in RAW.items() if k != "compaction"})))
    on, settings = compactor.settings_from(bare)
    assert on and settings["at_tokens"] == 120_000  # on by default, at about 120,000 tokens


def test_the_cheap_model_is_picked():
    cfg, *_ = setup()
    assert compactor.pick_model(cfg, {"model": ""}, "coder", "a/coder") == "cheap/flash"  # last fallback
    assert compactor.pick_model(cfg, {"model": "a/planner"}, "coder", "a/coder") == "a/planner"
    assert compactor.pick_model(cfg, {"model": ""}, "reviewer", "a/planner") == "a/planner"  # no fallback
    raw = {**RAW, "providers": {**RAW["providers"], "deepseek": {"type": "scripted"}}}
    cfg2 = parse_config(json.loads(json.dumps(raw)))
    assert compactor.pick_model(cfg2, {"model": ""}, "reviewer", "a/planner") == compactor.CHEAP_MODEL


def test_the_summary_cost_counts_toward_the_budget():
    cfg, main, small, box, seen = setup()
    res, budget, events = run(cfg, box)
    summaries = sum(cfg.cost(ModelRef.parse("cheap/flash"), Usage(1000, 100)) for _ in small.calls)
    work = sum(d["cost"] for k, d in events if k == "model_turn")
    assert abs(budget.spent_usd - (work + summaries)) < 1e-9
    assert abs(res.cost_usd - (work + summaries)) < 1e-9
    assert abs(sum(d["cost"] for k, d in events if k == "compacted") - summaries) < 1e-6


def test_a_broken_compactor_is_switched_off_and_the_task_carries_on():
    cfg, main, small, box, seen = setup()
    small.script = lambda *a: (_ for _ in ()).throw(RuntimeError("no credit"))
    res, _, events = run(cfg, box)
    assert res.stop == "terminal"
    assert [d for k, d in events if k == "plugin_error" and d["plugin"] == "compactor"]
    assert not [k for k, _ in events if k == "compacted"]
