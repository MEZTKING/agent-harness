"""Wave 2's parts wired together: the coding helpers as a provider type, the new phone routes and API
modules, the daily tidy-up's settings, memory in the prompts, and where the time went on the other machine."""

import importlib

from roundtable import memory
from roundtable.harness import agent as agentmod
from roundtable.harness.agent import Budget, run_agent
from roundtable.harness.config import FEATURE_SECTIONS, PROVIDER_TYPES, ModelRef, parse_config
from roundtable.harness.tools import Tool, Workspace, _obj
from roundtable.phone import PHONE_ROUTES, phone_allowed
from roundtable.providers.base import ToolSpec
from roundtable.providers.catalog import CODING_HELPERS, PRESETS, preset_block
from roundtable.providers.cli_engine import CliEngine
from roundtable.providers.scripted import ScriptedProvider, reply
from roundtable.ui.server import FEATURE_APIS

from .test_harness import task_line


def ROLES(coder):
    return {"orchestrator": {"model": "a/x"}, "reviewer": {"model": "a/x"}, "coder": {"model": coder}}


def test_the_cli_provider_type_resolves():
    assert "cli" in PROVIDER_TYPES
    cfg = parse_config({"providers": {"a": {"type": "scripted"}, "cli": {"type": "cli", "preset": "cli", "bill": "api"}},
                        "roles": ROLES("cli/claude-code")})
    eng = cfg.provider("cli")
    assert isinstance(eng, CliEngine) and eng.name == "cli"
    assert PRESETS["cli"]["type"] == "cli" and CODING_HELPERS["cli"] is PRESETS["cli"]
    assert preset_block("cli") == {"type": "cli", "preset": "cli"}  # no key to ask for


def test_feature_api_modules_import_and_answer_their_routes():
    for name in ("whatsnewapi", "tidyapi", "searchapi", "filesapi", "attachapi"):
        assert name in FEATURE_APIS
    keys = set()
    for name in FEATURE_APIS:
        mod = importlib.import_module(f"roundtable.ui.{name}")
        keys |= set(mod.routes(object()))
    new = {("GET", "/api/whatsnew"), ("POST", "/api/whatsnew/seen"), ("GET", "/api/search"),
           ("GET", "/api/search/peek"), ("GET", "/api/memory"), ("GET", "/api/files"), ("GET", "/api/files/open"),
           ("GET", "/api/files/log"), ("POST", "/api/files/run_tests"), ("GET", "/api/attach/draft"),
           ("POST", "/api/attach/draft"), ("POST", "/api/attach/upload"), ("POST", "/api/attach/remove"),
           ("POST", "/api/attach/clear"), ("GET", "/api/attach/files"), ("GET", "/api/attach/list"),
           ("POST", "/api/attach/start"), ("POST", "/api/attach/send")}
    assert new <= PHONE_ROUTES and new <= keys  # the phone may use them, and the PC answers them
    assert all(phone_allowed(m, p) for m, p in new)
    assert not phone_allowed("POST", "/api/tidy")  # the tidy-up switch stays on the PC


def test_retention_is_a_feature_section():
    assert "retention" in FEATURE_SECTIONS
    cfg = parse_config({"providers": {"a": {"type": "scripted"}}, "roles": ROLES("a/x"),
                        "retention": {"logs_days": 30}})
    assert cfg.sections["retention"] == {"logs_days": 30}


def test_the_template_runs_three_tasks_at_once():
    from roundtable.recommended import template_raw

    assert template_raw()["limits"]["max_parallel"] == 3
    assert parse_config({"providers": {"a": {"type": "scripted"}},
                         "roles": ROLES("a/x")}).limits.max_parallel == 1


class _Gate:
    """Waits two seconds for the owner's yes (counted, not slept)."""
    waited = 0.0

    def check(self, command):
        self.waited += 2.0
        return None


def test_model_turns_carry_tokens_and_commands_carry_their_wait(tmp_path):
    from roundtable.providers.base import Usage

    calls = iter([reply(calls=[("run_command", {"command": "echo hi"})]),
                  reply(calls=[("finish_task", {"summary": "done"})])])

    def brain(model, system, messages, tools):
        r = next(calls)
        r.usage = Usage(input_tokens=100, output_tokens=20, cache_read_tokens=50, cache_write_tokens=5)
        return r

    cfg = parse_config({"providers": {"a": {"type": "scripted"}}, "roles": ROLES("a/x"),
                        "pricing": {"a/x": {"input": 1, "output": 1}}})
    cfg.register("a", ScriptedProvider("a", brain))
    ws = Workspace(tmp_path / "p", gate=_Gate())
    box = ws.toolbox()
    box.add(Tool(ToolSpec("finish_task", "finish", _obj({"summary": {"type": "string"}}, ["summary"])),
                 lambda a: "ok", terminal=True))
    events = []
    run_agent(cfg, ModelRef("a", "x"), "sys", "do it", box, Budget(5), on_event=lambda k, d: events.append((k, d)))
    turns = [d for k, d in events if k == "model_turn"]
    assert turns and all(d["input_tokens"] == 100 and d["cache_read_tokens"] == 50 for d in turns)
    cmd = next(d for k, d in events if k == "tool_call" and d["tool"] == "run_command")
    assert cmd["waited_ms"] == 2000
    done = next(d for k, d in events if k == "agent_done")
    assert done["waited_ms"] == 2000


def test_session_lines_say_which_task_and_where_the_time_went():
    from roundtable.sync import session_lines

    turn = session_lines("model_turn", {"task": "T2", "model": "a/x", "text": "", "ms": 900, "first_ms": 300,
                                        "input_tokens": 10, "output_tokens": 2, "cost": 0})
    assert turn == [{"at": turn[0]["at"], "kind": "turn", "model": "a/x", "role": "", "ms": 900, "first_ms": 300,
                     "input_tokens": 10, "output_tokens": 2, "line": "", "task": "T2"}]
    tool = session_lines("tool_call", {"task": "T2", "tool": "run_command", "args": {"command": "npm test"},
                                       "ms": 5000, "waited_ms": 4000})
    assert tool[0]["task"] == "T2" and tool[0]["ms"] == 5000 and tool[0]["waited_ms"] == 4000
    done = session_lines("agent_done", {"task": "T2", "other_ms": 120})
    assert done[0]["kind"] == "agent_done" and done[0]["other_ms"] == 120 and done[0]["task"] == "T2"


def test_memory_reaches_the_planner_and_the_workers_and_learns_from_a_rejection(tmp_path, monkeypatch):
    from roundtable.harness import gate as gatemod
    from roundtable.harness.orchestrator import Orchestrator

    monkeypatch.delenv(gatemod.ENV, raising=False)
    monkeypatch.setenv("ROUNDTABLE_HOME", str(tmp_path / "home"))
    root = tmp_path / "proj"
    memory.add_rule(root, "Always write British English in the made-up shop's pages.")
    plan = [{"id": "T1", "title": "hello", "role": "coder", "description": "create hello.txt",
             "acceptance": "it exists", "depends_on": []}]
    verdicts = iter([False, True])
    seen = []

    def brain(model, system, messages, tools):
        names = {t.name for t in tools}
        last = messages[-1]
        if "submit_plan" in names:
            seen.append(("plan", messages[0]["content"]))
            return reply("planned") if last["role"] == "tool" else reply(calls=[("submit_plan", {"tasks": plan})])
        if "submit_review" in names:
            if last["role"] == "tool":
                return reply("ok")
            ok = next(verdicts)
            return reply(calls=[("submit_review", {"approved": ok, "feedback": "fine" if ok else "Add a full stop.",
                                                     "breaks": task_line(messages)})])
        if "finish_task" not in names:
            return reply("All done.")  # the final report
        if last["role"] == "tool":
            return reply("done")
        seen.append(("work", messages[0]["content"]))
        return reply(calls=[("write_file", {"path": "hello.txt", "content": "hello."}),
                            ("finish_task", {"summary": "Wrote hello.txt with a full stop."})])

    cfg = parse_config({"providers": {"a": {"type": "scripted"}},
                        "roles": {"orchestrator": {"model": "a/p"}, "coder": {"model": "a/c"},
                                  "reviewer": {"model": "a/r"}},
                        "pricing": {f"a/{m}": {"input": 1, "output": 1} for m in "pcr"},
                        "limits": {"max_cost_usd": 5, "max_attempts_per_task": 3}})
    cfg.register("a", ScriptedProvider("a", brain))
    orch = Orchestrator(cfg, root)
    orch.start("say hello")
    orch.run()
    assert seen and all("made-up shop" in text for _, text in seen)
    assert {k for k, _ in seen} == {"plan", "work"}
    recent = memory.read(memory.project_path(root)).text()
    assert "Add a full stop." in recent  # what the reviewer first said, kept for next time


def test_agent_hands_a_cli_role_to_its_engine(monkeypatch):
    called = {}

    def fake(cfg, ref, *a, **kw):
        called["ref"] = str(ref)
        return "handed over"

    monkeypatch.setattr("roundtable.providers.cli_engine.run_cli_agent", fake)
    cfg = parse_config({"providers": {"a": {"type": "scripted"}, "cli": {"type": "cli"}}, "roles": ROLES("cli/codex")})
    assert run_agent(cfg, ModelRef("cli", "codex"), "s", "p", None, Budget(1)) == "handed over"
    assert called["ref"] == "cli/codex"
    assert agentmod  # the hook lives in agent.run_agent
