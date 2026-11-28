import json
import subprocess
from importlib import resources

import pytest
import yaml

from roundtable.harness.config import ModelRef, parse_config
from roundtable.harness.orchestrator import Orchestrator, _validate_plan
from roundtable.harness.tools import ToolError, Workspace
from roundtable.providers.anthropic_provider import _to_anthropic_messages
from roundtable.providers.base import ProviderError, Usage
from roundtable.providers.openai_compat import _to_openai_messages
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider, reply

RAW = {
    "providers": {"a": {"type": "scripted"}, "b": {"type": "scripted"}, "img": {"type": "scripted_images"}},
    "roles": {
        "orchestrator": {"model": "a/planner"},
        "coder": {"model": "a/coder", "fallback": ["b/coder2"], "description": "writes code"},
        "reviewer": {"model": "a/reviewer"},
        "designer": {"kind": "image", "model": "img/pic"},
    },
    "pricing": {"a/planner": {"input": 1, "output": 1}, "a/coder": {"input": 1, "output": 1},
                "b/coder2": {"input": 1, "output": 1}, "a/reviewer": {"input": 1, "output": 1}},
    "limits": {"max_cost_usd": 5, "max_attempts_per_task": 3},
}

PLAN = [
    {"id": "T1", "title": "hello module", "role": "coder", "description": "create hello.py",
     "acceptance": "hello.py prints hi", "depends_on": []},
    {"id": "T2", "title": "logo", "role": "designer", "description": "a bakery logo",
     "acceptance": "png exists", "depends_on": [], "output_path": "assets/logo.png"},
    {"id": "T3", "title": "tests", "role": "coder", "description": "add test", "acceptance": "tests pass",
     "depends_on": ["T1"]},
]


def tool_names(tools):
    return {t.name for t in tools}


def task_line(messages):
    """The task's own description line from a review prompt: what a scripted rejection quotes (the panel
    counts a rejection only when it quotes the line it breaks)."""
    return messages[0]["content"].split("\n", 2)[1]


class Brain:
    """Scripted multi-role behaviour keyed on which terminal tool is offered."""

    def __init__(self, reject_first=False, plan=None):
        self.reject_first = reject_first
        self.reviews = 0
        self.plan = plan or PLAN
        self.worker_turns = {}

    def __call__(self, model, system, messages, tools):
        names = tool_names(tools)
        last = messages[-1]
        if "submit_plan" in names:
            if last["role"] == "tool":
                return reply("planned")
            return reply(calls=[("submit_plan", {"tasks": self.plan})])
        if "submit_review" in names:
            if last["role"] == "tool":
                return reply("ok")
            self.reviews += 1
            if self.reject_first and self.reviews == 1:
                return reply(calls=[("submit_review", {"approved": False, "feedback": "missing newline",
                                                     "breaks": task_line(messages)})])
            return reply(calls=[("submit_review", {"approved": True, "feedback": "looks good"})])
        if "finish_task" in names:
            prompt = messages[0]["content"]
            tid = prompt.split("# Your task [", 1)[1].split("]", 1)[0]
            n = self.worker_turns.get(tid, 0)
            self.worker_turns[tid] = n + 1
            if last["role"] == "user":
                fname = "hello.py" if tid == "T1" else "test_hello.py"
                return reply(calls=[("write_file", {"path": fname, "content": f"print('hi')  # {model}\n"})])
            return reply(calls=[("finish_task", {"summary": f"{tid} done by {model}"})])
        return reply("Final report: all done.")


def make(tmp_path, raw=RAW, brain=None, b_brain=None):
    cfg = parse_config(json.loads(json.dumps(raw)))
    brain = brain or Brain()
    a = ScriptedProvider("a", brain)
    b = ScriptedProvider("b", b_brain or brain)
    img = ScriptedImages()
    cfg.register("a", a)
    cfg.register("b", b)
    cfg.register("img", img)
    events = []
    orch = Orchestrator(cfg, tmp_path / "proj", on_event=lambda k, d: events.append((k, d)))
    return orch, a, b, img, events


def test_template_config_is_valid():
    raw = yaml.safe_load(resources.files("roundtable").joinpath("templates/harness.example.yaml").read_text(encoding="utf-8"))
    cfg = parse_config(raw)
    assert cfg.roles["coder"].models == [ModelRef("anthropic", "claude-opus-5-5"), ModelRef("deepseek", "deepseek-v4-flash")]
    assert cfg.roles["illustrator"].kind == "image" and cfg.roles["illustrator"].review is False
    assert "deepseek-v4-pro" not in resources.files("roundtable").joinpath("templates/harness.example.yaml").read_text(
        encoding="utf-8")  # the owner's rule: no DeepSeek V4 Pro for now
    assert set(cfg.profiles) == {"budget", "balanced", "quality"} and cfg.default_profile == "balanced"
    for name in [None, *cfg.profiles]:  # a DeepSeek key alone is enough: every chat role can end on DeepSeek
        c = cfg.for_profile(name)
        for role in c.roles.values():
            if role.kind == "chat":
                assert any(m.provider == "deepseek" for m in role.models), (name, role.name)
    assert cfg.design_role == "designer" and cfg.roles["designer"].kind == "chat" and cfg.look_stage == "auto"
    assert cfg.scout_role == "scout" and cfg.roles["scout"].kind == "chat" and cfg.limits.max_scout_steps == 30
    assert cfg.cost(ModelRef("anthropic", "claude-opus-5-5"), Usage(1_000_000, 0)) == 4.0
    assert cfg.cost(ModelRef("deepseek", "deepseek-v4-flash"), Usage(1_000_000, 0)) > 0


def test_config_errors():
    with pytest.raises(ValueError):
        parse_config({"roles": {"orchestrator": {"model": "no-slash"}}})
    with pytest.raises(ValueError):
        parse_config({"providers": {"a": {"type": "scripted"}}, "roles": {"orchestrator": {"model": "zz/m"}}})
    with pytest.raises(ValueError):
        parse_config({"roles": {"coder": {"model": "a/b"}}})  # no planner role


def test_full_project_run(tmp_path):
    orch, a, b, img, events = make(tmp_path)
    orch.start("build a bakery site")
    assert orch.run() == "done"

    tasks = {t.id: t for t in orch.project.tasks()}
    assert all(t.status == "done" for t in tasks.values())
    root = orch.project.root
    assert (root / "hello.py").read_text(encoding="utf-8").startswith("print('hi')")
    assert (root / "assets/logo.png").read_bytes().startswith(b"\x89PNG")
    assert img.prompts == ["a bakery logo"]
    assert "Final report" in (root / ".harness/summary.md").read_text(encoding="utf-8")
    # T3 ran after T1 and saw T1's summary
    t3_prompt = next(c["messages"][0]["content"] for c in a.calls if "# Your task [T3]" in c["messages"][0]["content"])
    assert "T1 done by coder" in t3_prompt
    # one commit per task, .harness ignored
    log = subprocess.run(["git", "log", "--oneline"], cwd=root, capture_output=True, text=True).stdout
    assert "[T1] hello module" in log and "[T3] tests" in log
    assert ".harness/" in (root / ".gitignore").read_text(encoding="utf-8")
    # spend tracked and metrics written
    meta = orch.project.meta()
    assert meta["status"] == "done" and meta["spent_usd"] > 0
    metrics = [json.loads(line) for line in (root / ".harness/metrics.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {m["task"] for m in metrics} == {"T1", "T2", "T3"}


def test_review_rejection_feeds_back_and_retries(tmp_path):
    orch, a, *_ = make(tmp_path, brain=Brain(reject_first=True))
    orch.start("goal")
    assert orch.run() == "done"
    t1 = next(t for t in orch.project.tasks() if t.id == "T1")
    assert [x["outcome"] for x in t1.attempts] == ["rejected", "approved"]
    retry_prompts = [c["messages"][0]["content"] for c in a.calls if "# Your task [T1]" in c["messages"][0]["content"]]
    assert any("missing newline" in p for p in retry_prompts)


def test_provider_error_falls_back(tmp_path):
    brain = Brain()

    def flaky(model, system, messages, tools):
        if model == "coder":
            raise ProviderError("down", retryable=True)
        return brain(model, system, messages, tools)

    orch, a, b, *_ = make(tmp_path, brain=flaky, b_brain=brain)
    orch.start("goal")
    assert orch.run() == "done"
    t1 = next(t for t in orch.project.tasks() if t.id == "T1")
    assert [x["outcome"] for x in t1.attempts] == ["error", "approved"]
    assert "coder2" in t1.summary


def test_all_models_fail_blocks_then_retry(tmp_path):
    brain = Brain()
    broken = {"on": True}

    def flaky(model, system, messages, tools):
        if model in ("coder", "coder2") and broken["on"]:
            raise ProviderError("down")
        return brain(model, system, messages, tools)

    orch, *_ = make(tmp_path, brain=flaky, b_brain=flaky)
    orch.start("goal")
    assert orch.run() == "blocked"
    statuses = {t.id: t.status for t in orch.project.tasks()}
    assert statuses["T1"] == "failed" and statuses["T3"] == "pending"
    broken["on"] = False
    orch.retry("T1")
    assert orch.run() == "done"


def test_approval_gate(tmp_path):
    orch, a, *_ = make(tmp_path)
    orch.start("goal", require_approval=True)
    assert orch.run() == "awaiting_approval"
    assert len(orch.project.tasks()) == 3
    assert all(t.status == "pending" for t in orch.project.tasks())
    orch.approve()
    assert orch.run() == "done"


def test_budget_pauses_and_resumes(tmp_path):
    raw = json.loads(json.dumps(RAW))
    raw["limits"]["max_cost_usd"] = 0.0004  # ~3 scripted calls: stops mid-project
    orch, *_ = make(tmp_path, raw=raw)
    orch.start("goal")
    assert orch.run() == "paused_budget"
    assert orch.project.meta()["status"] == "paused_budget"
    orch.cfg.limits.max_cost_usd = 100
    orch.budget.limit_usd = 100
    assert orch.run() == "done"


def test_money_and_budget_todos_close_when_the_run_goes_on(tmp_path):
    """A pause for money raises a high to-do for the owner; it must not stay open once the run carries on
    and finishes (the music player kept two stale "high" items on the phone)."""
    orch, *_ = make(tmp_path)
    opened, closed = [], []
    orch._journal = lambda kind, text, **kw: (opened.append(text), f"id{len(opened)}")[1]
    orch._journal_close = lambda entry_id, note="": closed.append(entry_id)
    orch.start("goal")
    orch._attention("money", "this run has spent $1.00 of real credit")
    orch._attention("budget", "paused at the budget limit")
    assert orch.run() == "done"
    assert {"id1", "id2"} <= set(closed)
    assert not orch.project.meta().get("journal_todos")


def test_extend_adds_goal_and_tasks(tmp_path):
    orch, *_ = make(tmp_path)
    orch.start("goal one")
    assert orch.run() == "done"
    orch.cfg._instances["a"].script = Brain(plan=[
        {"id": "T4", "title": "more", "role": "coder", "description": "x", "acceptance": "y", "depends_on": ["T3"]}])
    orch.extend("goal two")
    assert orch.run() == "done"
    tasks = orch.project.tasks()
    # wave 8: goal one's finished tasks go to the archive, except those a remaining task still needs
    from roundtable.harness import boardstage

    assert [t.id for t in tasks] == ["T1", "T3", "T4"]
    assert [r["id"] for r in boardstage.archived(orch.project.root)] == ["T2"]
    assert tasks[-1].goal_index == 1


def test_plan_validation():
    cfg = parse_config(json.loads(json.dumps(RAW)))
    ok = _validate_plan(PLAN, cfg.roles, [])
    assert [t.id for t in ok] == ["T1", "T2", "T3"]
    bad_role = [{**PLAN[0], "role": "wizard"}]
    cycle = [{**PLAN[0], "depends_on": ["T3"]}, PLAN[2]]
    dup = [PLAN[0], PLAN[0]]
    missing = [{**PLAN[0], "depends_on": ["T9"]}]
    for bad in (bad_role, cycle, dup, missing, []):
        with pytest.raises(ValueError):
            _validate_plan(bad, cfg.roles, [])


def test_bad_plan_is_corrected(tmp_path):
    attempts = []

    class Fixer(Brain):
        def __call__(self, model, system, messages, tools):
            if "submit_plan" in tool_names(tools) and messages[-1]["role"] == "user":
                return reply(calls=[("submit_plan", {"tasks": [{**PLAN[0], "role": "wizard"}]})])
            if "submit_plan" in tool_names(tools) and messages[-1]["role"] == "tool" and messages[-1]["is_error"]:
                attempts.append(messages[-1]["content"])
                return reply(calls=[("submit_plan", {"tasks": [PLAN[0]]})], id_prefix="d")
            return super().__call__(model, system, messages, tools)

    orch, *_ = make(tmp_path, brain=Fixer())
    orch.start("goal")
    assert orch.run() == "done"
    assert "unknown role" in attempts[0]


def test_workspace_sandboxing(tmp_path):
    ws = Workspace(tmp_path, allow_shell=False)
    with pytest.raises(ToolError):
        ws.path("../outside.txt")
    with pytest.raises(ToolError):
        ws.path(".harness/tasks.json")
    box = ws.toolbox()
    assert "run_command" not in box.tools
    out, err = box.call("write_file", {"path": "a/b.txt", "content": "x\ny\n"})
    assert not err
    out, err = box.call("edit_file", {"path": "a/b.txt", "old_text": "y", "new_text": "z"})
    assert not err and (tmp_path / "a/b.txt").read_text(encoding="utf-8") == "x\nz\n"
    out, err = box.call("read_file", {"path": "../../etc/passwd"})
    assert err
    out, err = box.call("nope", {})
    assert err


def test_run_command(tmp_path):
    ws = Workspace(tmp_path, command_timeout=5)
    out = ws.run_command({"command": "echo hello && exit 3"})
    assert "exit code: 3" in out and "hello" in out


def test_anthropic_message_conversion():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "1", "name": "x", "arguments": {}}, {"id": "2", "name": "y", "arguments": {"a": 1}}],
         "raw": {"provider": "anthropic", "content": [{"type": "thinking", "thinking": "", "signature": "s"},
                                                      {"type": "tool_use", "id": "1", "name": "x", "input": {}}]}},
        {"role": "tool", "tool_call_id": "1", "name": "x", "content": "r1", "is_error": False},
        {"role": "tool", "tool_call_id": "2", "name": "y", "content": "", "is_error": True},
        {"role": "assistant", "content": "from deepseek", "tool_calls": [], "raw": {"provider": "deepseek", "message": {}}},
    ]
    out = _to_anthropic_messages(msgs)
    assert out[1]["content"][0]["type"] == "thinking"  # raw blocks replayed unchanged
    assert out[2]["role"] == "user" and [b["tool_use_id"] for b in out[2]["content"]] == ["1", "2"]
    assert out[2]["content"][1]["is_error"] is True
    assert out[3] == {"role": "assistant", "content": [{"type": "text", "text": "from deepseek"}]}


def test_openai_message_conversion():
    native = {"role": "assistant", "content": "", "reasoning_content": "hmm",
              "tool_calls": [{"id": "1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]}
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "name": "x", "arguments": {}}],
         "raw": {"provider": "deepseek", "message": native}},
        {"role": "tool", "tool_call_id": "1", "name": "x", "content": "r"},
        {"role": "assistant", "content": "claude said", "tool_calls": [{"id": "9", "name": "z", "arguments": {"q": 1}}],
         "raw": {"provider": "anthropic", "content": []}},
    ]
    out = _to_openai_messages("sys", msgs, "deepseek")
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[2] is native  # same provider: native replay keeps reasoning_content
    assert out[3] == {"role": "tool", "tool_call_id": "1", "content": "r"}
    assert out[4]["tool_calls"][0]["function"] == {"name": "z", "arguments": '{"q": 1}'}


def test_retrodiffusion_adapter(monkeypatch):
    import base64

    from roundtable.providers.retrodiffusion import RetroDiffusionProvider

    png = base64.b64encode(b"\x89PNG fake").decode()
    calls = []
    polls = {"n": 0}

    def fake_request(self, method, path, body=None, headers=None):
        calls.append((method, path, body, headers))
        if path == "/styles/selector":
            return {"styles": [{"prompt_style": "rd_lite__default", "min_width": 16, "max_width": 512,
                                "min_height": 16, "max_height": 512, "require_input_image": None},
                               {"prompt_style": "rd_tile__single_tile", "min_width": 16, "max_width": 64,
                                "min_height": 16, "max_height": 64, "require_input_image": None}]}
        if method == "POST" and body.get("check_cost"):
            return {"balance_cost": 0.05, "base64_images": [], "model": "check_cost"}
        if method == "POST":
            return {"status": "accepted", "task_id": "t1"}
        polls["n"] += 1
        if polls["n"] < 2:
            return {"status": "running"}
        return {"status": "succeeded", "result": {"base64_images": [png], "balance_cost": 0.05}}

    monkeypatch.setattr(RetroDiffusionProvider, "_request", fake_request)
    p = RetroDiffusionProvider(poll_interval=0)
    data, ext, usage = p.generate("rd_lite__default", "a knight",
                                  {"style": "rd_tile__single_tile", "width": 200, "height": 8, "remove_bg": True})
    assert data == b"\x89PNG fake" and ext == "png" and usage.cost_usd == 0.05
    submit = next(c for c in calls if c[0] == "POST")
    assert submit[2]["prompt_style"] == "rd_tile__single_tile"
    assert (submit[2]["width"], submit[2]["height"]) == (64, 16)  # clamped to the style's limits
    assert submit[2]["remove_bg"] is True and "Idempotency-Key" in submit[3]
    assert p.check_cost("rd_lite__default", "x") == 0.05
    with pytest.raises(ProviderError):
        p.generate("rd_nope__x", "x")
    # exact provider cost flows into the budget
    cfg = parse_config({"providers": {"rd": {"type": "retrodiffusion"}}, "roles": {
        "orchestrator": {"model": "rd/x"}}})
    assert cfg.cost(ModelRef("rd", "rd_lite__default"), usage) == 0.05


def test_planner_image_options_reach_provider(tmp_path):
    plan = [{"id": "T1", "title": "hero", "role": "designer", "description": "pixel knight", "acceptance": "png",
             "depends_on": [], "output_path": "assets/hero.png",
             "image_options": {"style": "rd_core__platformer", "width": 48, "remove_bg": True}}]
    raw = json.loads(json.dumps(RAW))
    raw["roles"]["designer"]["options"] = {"width": 64, "height": 64}
    orch, a, b, img, events = make(tmp_path, raw=raw, brain=Brain(plan=plan))
    seen = {}
    orig = img.generate

    def spy(model, prompt, options=None):
        seen.update(options or {})
        return orig(model, prompt, options)

    img.generate = spy
    orch.start("goal")
    assert orch.run() == "done"
    # "record" is where a provider says how it made a picture see-through (wave 8); the rest are the options
    assert {k: v for k, v in seen.items() if k != "record"} == {"width": 48, "height": 64,
                                                               "style": "rd_core__platformer", "remove_bg": True}


def test_missing_claude_key_gives_a_clear_error(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", "/nonexistent-home-for-test")  # no `ant` profile on disk
    from roundtable.providers.anthropic_provider import AnthropicProvider

    p = AnthropicProvider(api_key_env="RT_TEST_NO_SUCH_KEY")
    with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"):
        p.chat("claude-opus-5-5", "sys", [{"role": "user", "content": "hi"}], max_tokens=10)


def test_out_of_steps_without_fallback_carries_on_once(tmp_path):
    raw = json.loads(json.dumps(RAW))
    raw["roles"]["coder"].pop("fallback")
    raw["limits"]["max_steps_per_task"] = 3

    class Slow(Brain):
        def __call__(self, model, system, messages, tools):
            if "finish_task" in tool_names(tools):
                prompt = messages[0]["content"]
                if "# Your task [T1]" in prompt and "ran out of steps" not in prompt:
                    return reply(calls=[("write_file", {"path": "hello.py", "content": "print('hi')\n"})])
            return super().__call__(model, system, messages, tools)

    orch, *_ = make(tmp_path, raw=raw, brain=Slow(plan=PLAN[:1]))
    orch.start("goal")
    assert orch.run() == "done"
    t1 = orch.project.tasks()[0]
    assert [x["outcome"] for x in t1.attempts] == ["max_steps", "approved"]


def test_cache_hits_cost_a_tenth_unless_priced():
    cfg = parse_config(json.loads(json.dumps(RAW)))
    assert cfg.cost(ModelRef("a", "coder"), Usage(0, 0, cache_read_tokens=1_000_000)) == pytest.approx(0.1)
    cfg.pricing["a/coder"]["cache_read"] = 0.5
    assert cfg.cost(ModelRef("a", "coder"), Usage(0, 0, cache_read_tokens=1_000_000)) == pytest.approx(0.5)


def test_real_balance_noted_at_start_and_end(tmp_path, monkeypatch):
    from roundtable.providers import balance

    assert balance.balance_url({"base_url": "https://api.deepseek.com/v1"}) == "https://api.deepseek.com/user/balance"
    assert balance.balance_url({"base_url": "https://example.com"}) is None
    assert balance.parse({"balance_infos": [{"currency": "USD", "total_balance": "2.96"}]}) == {
        "amount": 2.96, "currency": "USD"}
    left = iter([3.00, 2.95])
    monkeypatch.setattr(balance, "balances", lambda cfg, names=None: {"a": {"amount": next(left), "currency": "USD"}})
    orch, *_ = make(tmp_path)
    orch.start("goal")
    events = []
    orch._listener = lambda k, d: events.append((k, d))
    assert orch.run() == "done"
    rows = [json.loads(x) for x in (orch.project.root / ".harness/balance.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["phase"] for r in rows] == ["start", "end"] and rows[1]["real_usd"] == pytest.approx(0.05)
    assert any(k == "real_cost" for k, _ in events)


def test_task_that_keeps_running_out_of_steps_is_split_once(tmp_path):
    raw = json.loads(json.dumps(RAW))
    raw["roles"]["coder"].pop("fallback")
    raw["limits"]["max_steps_per_task"] = 2

    class Big(Brain):
        def __call__(self, model, system, messages, tools):
            if "finish_task" in tool_names(tools) and "# Your task [T1]" in messages[0]["content"]:
                return reply(calls=[("write_file", {"path": "big.py", "content": "x = 1\n"})])  # never finishes
            return super().__call__(model, system, messages, tools)

    brain = Big(plan=PLAN[:1])
    orch, a, *_ = make(tmp_path, raw=raw, brain=brain)
    orch.start("goal")
    orch.plan()  # T1 is planned before the planner's answer changes
    brain.plan = [{"id": "T2", "title": "first half", "role": "coder", "description": "finish big.py",
                   "acceptance": "done", "depends_on": []}]
    assert orch.run() == "done"
    tasks = {t.id: t for t in orch.project.tasks()}
    assert "T1" not in tasks and tasks["T2"].status == "done"
    assert json.loads((orch.project.root / ".harness/split.json").read_text(encoding="utf-8")) == ["T1"]
    revise = next(c for c in a.calls if "submit_plan" in tool_names(c["tools"] or [])
                  and "ran out of steps" in c["messages"][0]["content"])
    assert "Replace it with 2 to 4 smaller tasks" in revise["messages"][0]["content"]


def test_run_pauses_when_real_spend_reaches_its_limit(tmp_path, monkeypatch):
    from roundtable.providers import balance

    left = iter([3.00, 3.00, 1.90, 1.90])
    monkeypatch.setattr(balance, "balances", lambda cfg, names=None: {"a": {"amount": next(left, 1.9), "currency": "USD"}})
    raw = json.loads(json.dumps(RAW))
    raw["limits"]["max_real_usd_per_run"] = 1.0
    orch, *_ = make(tmp_path, raw=raw)
    orch.start("goal")
    assert orch.run() == "paused"
    assert sum(t.status == "done" for t in orch.project.tasks()) == 1


def test_out_of_credit_pauses_the_run_instead_of_failing_the_task(tmp_path):
    class Broke(Brain):
        def __call__(self, model, system, messages, tools):
            if "finish_task" in tool_names(tools):
                raise ProviderError("a: out of credit for coder - top up your balance with a", out_of_credit=True)
            return super().__call__(model, system, messages, tools)

    brain = Broke(plan=PLAN[:1])
    orch, *_ = make(tmp_path, brain=brain, b_brain=brain)
    orch.start("goal")
    assert orch.run() == "paused"
    t1 = orch.project.tasks()[0]
    assert t1.status == "pending" and t1.attempts == []
    assert orch.project.meta()["status"] == "paused"


def test_real_money_limit_is_checked_inside_a_long_task(tmp_path, monkeypatch):
    from roundtable.providers import balance

    left = iter([3.00, 3.00] + [1.50] * 50)  # start, the check before the task, then inside it
    monkeypatch.setattr(balance, "balances", lambda cfg, names=None: {"a": {"amount": next(left), "currency": "USD"}})
    raw = json.loads(json.dumps(RAW))
    raw["limits"]["max_real_usd_per_run"] = 1.0
    orch, *_ = make(tmp_path, raw=raw, brain=Brain(plan=PLAN[:1]))
    orch.start("goal")
    orch.plan()
    orch.approve()
    orch.REAL_CHECK_SECONDS = 0  # look at the balance on every charge
    assert orch.run() == "paused_budget"
    assert orch.project.tasks()[0].status == "pending"


def test_reviewer_is_told_what_later_tasks_will_do(tmp_path):
    orch, a, *_ = make(tmp_path)
    orch.start("goal")
    orch.plan()
    tasks = orch.project.tasks()
    text = orch._later_tasks_text(tasks[0])
    assert "Still to come" in text and "[T3] tests" in text and "[T1]" not in text


def test_after_a_rejection_the_next_reviewer_model_judges(tmp_path):
    raw = json.loads(json.dumps(RAW))
    raw["roles"]["reviewer"]["fallback"] = ["b/strong-reviewer"]
    raw["tandem"] = {"default": "lean"}  # one reviewer, as before 1.2.0 (the panel picks by maker: test_panel.py)
    raw["pricing"]["b/strong-reviewer"] = {"input": 1, "output": 1}
    orch, a, b, *_ = make(tmp_path, raw=raw, brain=Brain(reject_first=True, plan=PLAN[:1]))
    orch.start("goal")
    assert orch.run() == "done"
    judged_by = [c["model"] for c in a.calls + b.calls if "submit_review" in tool_names(c["tools"] or [])
                 and c["messages"][-1]["role"] == "user"]
    assert judged_by == ["reviewer", "strong-reviewer"]


def test_run_stops_at_half_its_money_with_nothing_finished(tmp_path, monkeypatch):
    from roundtable.providers import balance

    left = iter([3.00, 3.00, 2.40])  # start, before T1, after T1 failed
    monkeypatch.setattr(balance, "balances", lambda cfg, names=None: {"a": {"amount": next(left, 2.4), "currency": "USD"}})
    raw = json.loads(json.dumps(RAW))
    raw["roles"]["coder"].pop("fallback")
    raw["limits"].update({"max_real_usd_per_run": 1.0, "max_steps_per_task": 1, "split_stuck_tasks": False})

    class Stuck(Brain):
        def __call__(self, model, system, messages, tools):
            if "finish_task" in tool_names(tools):
                return reply(calls=[("write_file", {"path": "x.py", "content": "x\n"})])
            return super().__call__(model, system, messages, tools)

    two = [PLAN[0], {**PLAN[0], "id": "T9", "title": "other", "depends_on": []}]
    orch, *_ = make(tmp_path, raw=raw, brain=Stuck(plan=two))
    orch.start("goal")
    orch.plan()
    orch.approve()
    assert orch.run() == "paused"
    assert [t.status for t in orch.project.tasks()] == ["failed", "pending"]


def test_workers_may_write_throwaway_scripts_in_harness_scratch(tmp_path):
    ws = Workspace(tmp_path)
    assert ws.path(".harness/scratch/smoke.mjs") == (tmp_path / ".harness/scratch/smoke.mjs").resolve()
    with pytest.raises(ToolError):
        ws.path(".harness/project.json")


def test_owner_can_accept_a_rejected_task_as_it_is(tmp_path):
    from roundtable.harness.orchestrator import HarnessError

    orch, *_ = make(tmp_path, brain=Brain(plan=PLAN[:1]))
    orch.start("goal")
    orch.plan()
    (orch.project.root / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    tasks = orch.project.tasks()
    tasks[0].status = "failed"
    orch.project.save_tasks(tasks)
    orch.accept("T1", "the checker said the work was fine")
    t = orch.project.tasks()[0]
    assert t.status == "done" and t.summary.startswith("Accepted by the owner: the checker")
    log = subprocess.run(["git", "log", "--oneline"], cwd=orch.project.root, capture_output=True, text=True).stdout
    assert "accepted by the owner" in log
    with pytest.raises(HarnessError):
        orch.accept("T1")


def test_real_money_is_checked_sooner_when_spending_fast(tmp_path, monkeypatch):
    from roundtable.providers import balance

    left = iter([3.00, 3.00] + [1.50] * 50)
    monkeypatch.setattr(balance, "balances", lambda cfg, names=None: {"a": {"amount": next(left), "currency": "USD"}})
    raw = json.loads(json.dumps(RAW))
    raw["limits"]["max_real_usd_per_run"] = 0.000001  # a tenth of it is counted on the first charge
    orch, *_ = make(tmp_path, raw=raw, brain=Brain(plan=PLAN[:1]))
    orch.start("goal")
    orch.plan()
    orch.approve()
    orch.REAL_CHECK_SECONDS = 10 ** 6  # the minute rule alone would never look
    assert orch.run() == "paused_budget"


def test_big_files_come_back_as_an_outline_and_a_start(tmp_path):
    ws = Workspace(tmp_path)
    body = "\n".join(f"function f{i}() {{ return {i}; }}" if i % 50 == 0 else f"  // line {i}" for i in range(1, 2001))
    (tmp_path / "big.js").write_text(body, encoding="utf-8")
    out = ws.read_file({"path": "big.js"})
    assert "has 2000 lines" in out and "50\tfunction f50()" in out and "# Lines 1-120" in out and len(out) < len(body) / 3
    part = ws.read_file({"path": "big.js", "start_line": 1000, "end_line": 1005})
    assert part.startswith("1000\t") and "1005\t" in part
    capped = ws.read_file({"path": "big.js", "start_line": 1, "end_line": 2000})
    assert "stopped at line 600 of 2000" in capped
    (tmp_path / "small.js").write_text("a\nb\n", encoding="utf-8")
    assert ws.read_file({"path": "small.js"}) == "1\ta\n2\tb"
