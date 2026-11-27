"""Coding CLIs as workers (providers/cli_engine.py), driven by a made-up CLI (tests/fixtures/fake_cli.py)."""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from roundtable.harness import gate as gatemod
from roundtable.harness.agent import Budget, BudgetExceeded
from roundtable.harness.config import ModelRef, parse_config
from roundtable.harness.tools import Tool, Workspace, _obj
from roundtable.providers import cli_engine as ce
from roundtable.providers.base import ProviderError, ToolSpec

FAKE = [sys.executable, str(Path(__file__).parent / "fixtures" / "fake_cli.py")]
RAW = {
    "providers": {"a": {"type": "scripted"}},
    "roles": {"orchestrator": {"model": "a/x"}, "coder": {"model": "a/x"}, "reviewer": {"model": "a/x"}},
    "limits": {"max_cost_usd": 5},
}
PROMPT = "# Your task [T1] Say hello\nWrite hello.py.\n\nWhen finished, call finish_task with a concise summary."


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def project(tmp_path, use_git=True):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "readme.md").write_text("made-up project\n")
    if use_git:
        git(root, "init", "-q")
        git(root, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "add", ".")
        git(root, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "start")
    return root


def setup(tmp_path, monkeypatch, raw=RAW, use_git=True, **engine_opts):
    monkeypatch.delenv(gatemod.ENV, raising=False)
    log = tmp_path / "cli.log"
    monkeypatch.setenv("FAKE_CLI_LOG", str(log))
    cfg = parse_config(json.loads(json.dumps(raw)))
    eng = ce.CliEngine(commands={"claude-code": FAKE, "codex": FAKE}, **engine_opts)
    cfg.register("cli", eng)
    root = project(tmp_path, use_git)
    ws = Workspace(root)
    return cfg, ws, log


def toolbox(ws, terminal="finish_task"):
    box = ws.toolbox()
    box.add(Tool(ToolSpec(terminal, "finish", _obj({"summary": {"type": "string"}}, ["summary"])),
                 lambda a: "recorded", terminal=True))
    return box


def run(cfg, ws, engine="claude-code", prompt=PROMPT, budget=None, events=None, **kw):
    events = events if events is not None else []
    box = kw.pop("box", None) or toolbox(ws)
    res = ce.run_cli_agent(cfg, ModelRef("cli", engine), "Be careful.", prompt, box,
                           budget or Budget(limit_usd=5), on_event=lambda k, d: events.append((k, d)), role="coder",
                           **kw)
    return res, box, events


def logged(log):
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_claude_codes_stream_becomes_steps_and_a_result(tmp_path, monkeypatch):
    cfg, ws, log = setup(tmp_path, monkeypatch)
    res, box, events = run(cfg, ws)
    kinds = [k for k, _ in events]
    assert kinds[0] == "cli_start" and kinds[-1] == "agent_done"
    turns = [d for k, d in events if k == "model_turn"]
    assert turns and turns[0]["text"] == "I'll look first." and "ms" in turns[0]
    tools = [d for k, d in events if k == "tool_call"]
    assert tools[0]["tool"] == "run_command" and tools[0]["output"] == "readme.md" and "ms" in tools[0]
    assert any(t["tool"] == "write_file" for t in tools)
    changed = [t for t in tools if t["tool"] == "file_changed"]
    assert changed[0]["args"]["path"] == "hello.py" and "+print('hello')" in changed[0]["change"]["diff"]
    assert res.stop == "terminal" and box.captured["finish_task"]["summary"] == "Added hello.py that prints hello."
    assert res.usage.input_tokens == 900 and res.usage.cache_read_tokens == 300
    assert res.cost_usd == 0.0  # the subscription pays: shown, not charged
    assert events[-1][1]["reported_usd"] == 0.0123 and events[-1][1]["billed"] == "subscription"
    assert "hello.py" in ws.changed
    argv = logged(log)[0]["argv"]
    assert argv[:4] == ["-p", "--output-format", "stream-json", "--verbose"]
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    allowed = argv[argv.index("--allowedTools") + 1]
    denied = argv[argv.index("--disallowedTools") + 1]
    assert "Edit" in allowed and "curl" not in allowed and "WebFetch" in denied and "Bash(git push:*)" in denied
    sent = logged(log)[0]["prompt"]
    assert "finish_task with" not in sent and "end with a short summary" in sent


def test_api_billing_charges_the_budget(tmp_path, monkeypatch):
    cfg, ws, _ = setup(tmp_path, monkeypatch, bill="api")
    budget = Budget(limit_usd=5)
    res, _, _ = run(cfg, ws, budget=budget)
    assert res.cost_usd == pytest.approx(0.0123) and budget.spent_usd == pytest.approx(0.0123)


def test_codex_stream_and_its_sandbox(tmp_path, monkeypatch):
    cfg, ws, log = setup(tmp_path, monkeypatch)
    res, box, events = run(cfg, ws, engine="codex@gpt-test")
    argv = logged(log)[0]["argv"]
    assert argv[:2] == ["exec", "--json"] and argv[argv.index("--sandbox") + 1] == "workspace-write"
    assert argv[argv.index("--model") + 1] == "gpt-test" and argv[-1] == "-"
    assert "Be careful." in logged(log)[0]["prompt"]  # no system flag: it rides in the prompt
    tools = [d for k, d in events if k == "tool_call"]
    assert tools[0]["tool"] == "run_command" and tools[0]["args"]["command"] == "ls"
    assert res.stop == "terminal" and box.captured["finish_task"]["summary"] == "Added hello.py."
    assert res.usage.input_tokens == 1000 and res.usage.cache_read_tokens == 200 and res.usage.output_tokens == 80


def test_a_missing_cli_says_so_and_points_at_tools(tmp_path, monkeypatch):
    cfg, ws, _ = setup(tmp_path, monkeypatch)
    cfg.register("cli", ce.CliEngine(commands={"claude-code": str(tmp_path / "no-such-claude")}))
    with pytest.raises(ce.CliMissing) as e:
        run(cfg, ws)
    assert "Claude Code isn't installed" in str(e.value) and "Tools" in str(e.value) and e.value.tool == "claude"
    assert isinstance(e.value, ProviderError)  # the orchestrator falls back to the next model


def test_not_found_anywhere(monkeypatch):
    monkeypatch.setattr(ce.shutil, "which", lambda *a, **k: None)
    import roundtable.prereq as prereq

    monkeypatch.setattr(prereq, "find", lambda *a, **k: {"state": "missing"})
    with pytest.raises(ce.CliMissing):
        ce.CliEngine().command(ce.ENGINES["codex"])


def test_an_unknown_engine_is_a_plain_error():
    with pytest.raises(ProviderError, match="cli/claude-code or cli/codex"):
        ce.engine_for("gemini-cli")


def test_the_env_has_no_keys_but_keeps_the_clis_own_login(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "made-up-key-123456")
    monkeypatch.setenv("OPENAI_API_KEY", "made-up-key-654321")
    monkeypatch.setenv("GH_TOKEN", "made-up-token-1234")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    cfg, ws, log = setup(tmp_path, monkeypatch)
    run(cfg, ws)
    env = logged(log)[0]["env"]
    assert not {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GH_TOKEN"} & set(env)
    assert "HOME" in env and "APPDATA" in env and "PATH" in env


def _pid_alive(pid):
    if sys.platform == "win32":  # os.kill(pid, 0) would end the process there
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:  # a zombie still answers kill 0 until reaped
        return Path(f"/proc/{pid}/stat").read_text().split(")")[1].split()[0] != "Z"
    except OSError:
        return True  # no /proc (macOS): it answered, so it's there


def _wait_for(path, seconds=10):
    end = time.time() + seconds
    while time.time() < end and not path.exists():
        time.sleep(0.05)
    assert path.exists()


def test_stop_kills_the_cli(tmp_path, monkeypatch):
    cfg, ws, _ = setup(tmp_path, monkeypatch)
    stop = threading.Event()
    pidfile = ws.root / "child.pid"

    def press_stop():
        _wait_for(pidfile)
        stop.set()

    threading.Thread(target=press_stop, daemon=True).start()
    t0 = time.time()
    res, _, events = run(cfg, ws, prompt=PROMPT + "\nSLEEP", stop_event=stop)
    assert time.time() - t0 < 30 and res.stop == "breaker" and "stopped" in res.breaker_reason
    assert not _pid_alive(int(pidfile.read_text()))
    assert ce.running() == 0


def test_the_runs_stop_and_money_limit_reach_the_cli(tmp_path, monkeypatch):
    cfg, ws, _ = setup(tmp_path, monkeypatch)
    budget = Budget(limit_usd=5)
    pidfile = ws.root / "child.pid"

    def spend():
        _wait_for(pidfile)
        budget.spent_usd = 6  # another task spent the rest (or the app's Stop halted the run)

    threading.Thread(target=spend, daemon=True).start()
    with pytest.raises(BudgetExceeded):
        run(cfg, ws, prompt=PROMPT + "\nSLEEP", budget=budget)
    assert not _pid_alive(int(pidfile.read_text()))


def test_stop_all_kills_every_running_cli(tmp_path, monkeypatch):
    cfg, ws, _ = setup(tmp_path, monkeypatch)
    pidfile = ws.root / "child.pid"
    out = {}

    def go():
        out["res"] = run(cfg, ws, prompt=PROMPT + "\nSLEEP")[0]

    t = threading.Thread(target=go)
    t.start()
    _wait_for(pidfile)
    assert ce.stop_all() == 1
    t.join(30)
    assert not t.is_alive() and not _pid_alive(int(pidfile.read_text()))
    assert out["res"].stop == "breaker" and "stopped" in out["res"].breaker_reason


def test_the_time_limit_stops_it(tmp_path, monkeypatch):
    cfg, ws, _ = setup(tmp_path, monkeypatch, time_limit_minutes=0.02)
    res, _, events = run(cfg, ws, prompt=PROMPT + "\nSLEEP")
    assert res.stop == "breaker" and "minute limit" in res.breaker_reason
    assert any(k == "breaker" for k, _ in events)


def test_the_breaker_stops_a_loop(tmp_path, monkeypatch):
    cfg, ws, _ = setup(tmp_path, monkeypatch)
    res, _, _ = run(cfg, ws, prompt=PROMPT + "\nLOOP")
    assert res.stop == "breaker" and "same step" in res.breaker_reason


def test_a_retry_resumes_the_same_conversation(tmp_path, monkeypatch):
    cfg, ws, log = setup(tmp_path, monkeypatch)
    run(cfg, ws)
    feedback = PROMPT + "\n\n# Feedback on your previous attempt(s) - address all of it\nSay hello again."
    res, box, _ = run(cfg, ws, prompt=feedback)
    first, second = logged(log)
    assert "--resume" not in first["argv"]
    assert second["argv"][second["argv"].index("--resume") + 1] == "sess-1"
    assert second["prompt"].startswith("# Feedback") and "Write hello.py." not in second["prompt"]
    assert res.stop == "terminal"
    saved = json.loads((ws.root / ".harness" / "cli-sessions.json").read_text())
    assert [v["session"] for k, v in saved.items() if k.startswith("T1:")] == ["sess-resumed"]


def test_a_new_task_with_the_same_id_starts_afresh(tmp_path, monkeypatch):
    cfg, ws, log = setup(tmp_path, monkeypatch)
    run(cfg, ws)
    run(cfg, ws, prompt=PROMPT.replace("Say hello", "Say goodbye"))
    assert "--resume" not in logged(log)[1]["argv"]


def test_a_worktrees_sessions_live_in_the_projects_harness(tmp_path):
    wt = tmp_path / "proj" / ".harness" / "worktrees" / "T1"
    wt.mkdir(parents=True)
    assert ce._sessions_path(wt) == tmp_path / "proj" / ".harness" / "cli-sessions.json"
    assert ce._sessions_path(tmp_path / "proj") == tmp_path / "proj" / ".harness" / "cli-sessions.json"


def test_codex_resumes_with_its_subcommand(tmp_path, monkeypatch):
    cfg, ws, log = setup(tmp_path, monkeypatch)
    run(cfg, ws, engine="codex")
    run(cfg, ws, engine="codex")
    argv = logged(log)[1]["argv"]
    assert argv[argv.index("resume") + 1] == "sess-1" and argv[-1] == "-"


def test_a_lost_conversation_starts_afresh(tmp_path, monkeypatch):
    cfg, ws, log = setup(tmp_path, monkeypatch)
    res, _, events = run(cfg, ws, prompt=PROMPT, options={"resume": "gone"})
    rows = logged(log)
    assert "--resume" in rows[0]["argv"] and "--resume" not in rows[1]["argv"]
    assert res.stop == "terminal" and any(k == "cli_note" for k, _ in events)


def test_a_failure_and_a_missing_login_are_plain(tmp_path, monkeypatch):
    cfg, ws, _ = setup(tmp_path, monkeypatch)
    with pytest.raises(ProviderError, match="stopped with an error: something broke"):
        run(cfg, ws, prompt=PROMPT + "\nFAIL")
    with pytest.raises(ProviderError, match="isn't signed in"):
        run(cfg, ws, prompt=PROMPT + "\nNOLOGIN", options={"fresh": True})


def test_it_only_builds(tmp_path, monkeypatch):
    cfg, ws, _ = setup(tmp_path, monkeypatch)
    with pytest.raises(ProviderError, match="can only build"):
        run(cfg, ws, box=toolbox(ws, terminal="submit_plan"))
    with pytest.raises(ProviderError):
        cfg.provider("cli").chat("claude-code", "", [])


def test_ask_me_first_on_everything_gives_claude_code_no_shell(tmp_path, monkeypatch):
    raw = {**RAW, "gate": {"ask_first": "all"}}
    cfg, ws, log = setup(tmp_path, monkeypatch, raw=raw)
    _, _, events = run(cfg, ws)
    argv = logged(log)[0]["argv"]
    assert "Bash" not in argv[argv.index("--allowedTools") + 1]
    start = events[0][1]
    assert start["ask_me_first"] == "all" and "can't see inside" in start["note"]


def test_changes_outside_git_are_listed(tmp_path, monkeypatch):
    cfg, ws, _ = setup(tmp_path, monkeypatch, use_git=False)
    res, _, events = run(cfg, ws)
    changed = [d["args"]["path"] for k, d in events if k == "tool_call" and d["tool"] == "file_changed"]
    assert changed == ["hello.py"] and res.stop == "terminal"


def test_a_file_already_changed_before_is_only_shown_when_the_cli_changes_it(tmp_path, monkeypatch):
    cfg, ws, _ = setup(tmp_path, monkeypatch)
    (ws.root / "notes.txt").write_text("the owner's own edit\n")
    _, _, events = run(cfg, ws)
    changed = [d["args"]["path"] for k, d in events if k == "tool_call" and d["tool"] == "file_changed"]
    assert changed == ["hello.py"]


def test_the_catalog_entry_matches_the_engines():
    from roundtable import prereq
    from roundtable.providers.catalog import CODING_HELPERS

    entry = CODING_HELPERS["cli"]
    assert entry["type"] == "cli" and entry["models"] == list(ce.ENGINES)
    for eid, tool in entry["tools"].items():
        assert ce.ENGINES[eid].tool == tool and tool in prereq.BY_ID  # the Tools page can install it


def test_a_whole_task_through_the_orchestrator_with_a_retry(tmp_path, monkeypatch):
    """Through agent.py's hook-up to cli_engine, a role naming cli/claude-code builds a task,
    is reviewed like any other helper, and the retry after a rejection resumes the same conversation."""
    from roundtable.harness import orchestrator as orchmod
    from roundtable.providers.scripted import ScriptedProvider, reply

    monkeypatch.delenv(gatemod.ENV, raising=False)
    log = tmp_path / "cli.log"
    monkeypatch.setenv("FAKE_CLI_LOG", str(log))
    raw = {"providers": {"a": {"type": "scripted"}, "cli": {"type": "scripted"}},
           "roles": {"orchestrator": {"model": "a/planner"}, "coder": {"model": "cli/claude-code"},
                     "reviewer": {"model": "a/reviewer"}},
           "pricing": {"a/planner": {"input": 1, "output": 1}, "a/reviewer": {"input": 1, "output": 1}},
           "limits": {"max_cost_usd": 5, "max_attempts_per_task": 3}}
    plan = [{"id": "T1", "title": "hello", "role": "coder", "description": "create hello.py",
             "acceptance": "prints hello", "depends_on": []}]
    verdicts = iter([False, True])

    def brain(model, system, messages, tools):
        names = {t.name for t in tools}
        last = messages[-1]
        if "submit_plan" in names:
            return reply("planned") if last["role"] == "tool" else reply(calls=[("submit_plan", {"tasks": plan})])
        if "submit_review" in names:
            if last["role"] == "tool":
                return reply("ok")
            ok = next(verdicts)
            return reply(calls=[("submit_review", {"approved": ok, "feedback": "fine" if ok else "say it twice"})])
        return reply("Final report: all done.")

    cfg = parse_config(raw)
    cfg.register("a", ScriptedProvider("a", brain))
    cfg.register("cli", ce.CliEngine(commands={"claude-code": FAKE}))  # agent.run_agent hands it to cli_engine
    events = []
    orch = orchmod.Orchestrator(cfg, tmp_path / "proj", on_event=lambda k, d: events.append((k, d)))
    orch.start("say hello")
    orch.run()
    t1 = [t for t in orch.project.tasks() if t.id == "T1"][0]
    assert t1.status == "done" and [a["outcome"] for a in t1.attempts] == ["rejected", "approved"]
    rows = logged(log)
    assert len(rows) == 2 and "--resume" not in rows[0]["argv"]
    assert rows[1]["argv"][rows[1]["argv"].index("--resume") + 1] == "sess-1"
    assert "say it twice" in rows[1]["prompt"]
    assert (orch.project.root / "hello.py").read_text() == "print('hello again')\n"
