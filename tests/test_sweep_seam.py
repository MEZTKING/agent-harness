"""Wave 8, step 0: the seams the parity sweep's helpers fill.

With every stub in place and nothing using the new seams, the harness must behave exactly as it did in 1.3.0:
a bare scripted plan-and-run sends byte for byte the same requests (the golden below was recorded from the code
before the seams were added), an empty ``Toolbox.guards`` changes nothing, and ``on_delta=None`` changes nothing.

If a later change alters a prompt or a tool on purpose, write the golden again with ``UPDATE_GOLDENS=1``.
"""

import gzip
import inspect
import json
import os
import re
from pathlib import Path

import pytest

from roundtable import automation, reach
from roundtable.harness import agent as agentmod
from roundtable.harness import config as hconfig
from roundtable.harness import emulator, perms, streamlog, winshot
from roundtable.harness.agent import Budget, run_agent
from roundtable.harness.config import ModelRef, parse_config
from roundtable.harness.tools import Tool, Toolbox, ToolSpec, _obj
from roundtable.improve import charter
from roundtable.providers import base
from roundtable.providers.scripted import ScriptedProvider, reply

from .test_harness import RAW, make

GOLDEN = Path(__file__).parent / "data" / "sweep_seam_requests.json.gz"
ROOT = Path(__file__).resolve().parents[1]


def _spec(t):
    return {"name": t.name, "description": t.description, "parameters": t.parameters}


def requests_of(tmp_path, monkeypatch) -> str:
    """Every request a bare scripted plan-and-run sends, as one JSON text (the folder and dates masked). Each run
    has an app home of its own: a named agent's memory from an earlier run would change the next one's requests."""
    monkeypatch.setenv("ROUNDTABLE_HOME", str(tmp_path / "home"))
    orch, a, b, _img, _ev = make(tmp_path)
    orch.start("build a bakery site")
    assert orch.run() == "done"
    out = [{"provider": p.name, "model": c["model"], "system": c["system"], "messages": c["messages"],
            "tools": [_spec(t) for t in (c["tools"] or [])]} for p in (a, b) for c in p.calls]
    text = json.dumps(out, sort_keys=True, default=str).replace(str(tmp_path), "<tmp>")
    return re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "<date>", text)


# -- byte for byte as before ----------------------------------------------------------------------------------
def test_a_bare_plan_and_run_sends_byte_for_byte_the_same_requests_as_before(tmp_path, monkeypatch):
    got = requests_of(tmp_path, monkeypatch)
    if os.environ.get("UPDATE_GOLDENS") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_bytes(gzip.compress(got.encode("utf-8"), mtime=0))
    want = gzip.decompress(GOLDEN.read_bytes()).decode("utf-8")
    if got != want:
        (tmp_path / "got.json").write_text(got, encoding="utf-8")
    assert got == want, f"the requests changed; compare {tmp_path / 'got.json'} with the golden"


def test_guards_that_allow_everything_and_a_sink_change_no_request(tmp_path, monkeypatch):
    plain = requests_of(tmp_path / "plain", monkeypatch)
    seen = []
    real_init = Toolbox.__init__

    def with_guards(self, *a, **k):  # every toolbox the run builds gets a guard that allows everything
        real_init(self, *a, **k)
        self.guards.append(lambda name, args: seen.append(name))

    monkeypatch.setattr(Toolbox, "__init__", with_guards)
    import sys

    import roundtable.harness.orchestrator  # noqa: F401 - loaded, so every stage that binds run_agent is seen

    real_run = agentmod.run_agent
    pieces, runs = [], []

    def streamed(*a, **k):
        runs.append(1)
        return real_run(*a, **{**k, "on_delta": lambda kind, p: pieces.append(p)})

    for name, mod in list(sys.modules.items()):  # every module that took run_agent by name
        if name.startswith("roundtable.") and getattr(mod, "run_agent", None) is real_run:
            monkeypatch.setattr(mod, "run_agent", streamed)
    assert requests_of(tmp_path / "seamed", monkeypatch) == plain
    assert runs and seen and "submit_plan" in seen and pieces == []  # scripted replies without chunks stream nothing


# -- the provider seam ----------------------------------------------------------------------------------------
def test_every_chat_provider_takes_on_delta_and_defaults_it_to_none():
    from roundtable.providers.anthropic_provider import AnthropicProvider
    from roundtable.providers.cli_engine import CliEngine
    from roundtable.providers.openai_compat import OpenAICompatProvider

    for cls in (base.Provider, ScriptedProvider, AnthropicProvider, OpenAICompatProvider, CliEngine):
        p = inspect.signature(cls.chat).parameters["on_delta"]
        assert p.default is None and p.kind is inspect.Parameter.KEYWORD_ONLY, cls


def _agent(tmp_path, provider, **kw):
    cfg = parse_config(json.loads(json.dumps(RAW)))
    cfg.register("a", provider)
    box = Toolbox()
    box.add(Tool(ToolSpec("finish_task", "done", _obj({"summary": {"type": "string"}}, ["summary"])),
                 lambda a: "ok", terminal=True))
    return run_agent(cfg, ModelRef("a", "coder"), "sys", "do it", box, Budget(cfg.limits.max_cost_usd),
                     project_root=tmp_path, **kw)


def _script():
    return [reply("I will finish now."), reply(calls=[("finish_task", {"summary": "done"})])]


def test_on_delta_none_is_the_old_call_and_a_provider_without_it_still_works(tmp_path):
    class Old(base.Provider):  # a provider written before the seam: no on_delta at all
        name = "a"

        def __init__(self):
            self.script, self.calls = _script(), []

        def chat(self, model, system, messages, tools=None, max_tokens=16000, options=None):
            self.calls.append(json.dumps(messages, default=str))
            return self.script.pop(0)

    old = Old()
    r1 = _agent(tmp_path, old)
    got = []
    old2 = Old()
    r2 = _agent(tmp_path, old2, on_delta=lambda k, p: got.append(p))  # given, but the provider can't take it
    assert r1.stop == r2.stop and r1.text == r2.text and old.calls == old2.calls and got == []


def test_scripted_chunks_arrive_in_order_and_the_response_is_unchanged(tmp_path):
    plain = ScriptedProvider("a", _script())
    r1 = _agent(tmp_path, plain)
    pieces = []
    chunked = ScriptedProvider("a", _script(), chunks=4)
    r2 = _agent(tmp_path, chunked, on_delta=lambda k, p: pieces.append((k, p)))
    assert "".join(p for _, p in pieces) == "I will finish now." and all(k == "text" for k, _ in pieces)
    assert len(pieces) == 5 and r1.usage == r2.usage and r1.text == r2.text
    assert json.dumps(plain.calls, default=str) == json.dumps(chunked.calls, default=str)
    listed = ScriptedProvider("a", _script(), chunks=[[("thinking", "hm"), ("text", "I will")], []])
    seen = []
    _agent(tmp_path, listed, on_delta=lambda k, p: seen.append((k, p)))
    assert seen == [("thinking", "hm"), ("text", "I will")]
    quiet = ScriptedProvider("a", _script(), chunks=4)
    _agent(tmp_path, quiet)  # chunks but no on_delta: nothing is sent anywhere, nothing breaks


# -- Toolbox.guards -------------------------------------------------------------------------------------------
def _box():
    ran = []
    box = Toolbox()
    box.add(Tool(ToolSpec("delete_file", "d", _obj({"path": {"type": "string"}}, ["path"])),
                 lambda a: ran.append(a["path"]) or "deleted"))
    return box, ran


def test_an_empty_guard_list_changes_nothing_and_a_refusal_never_runs_the_tool():
    box, ran = _box()
    assert box.guards == [] and box.call("delete_file", {"path": "x"}) == ("deleted", False) and ran == ["x"]
    box.guards.append(lambda name, args: None)
    assert box.call("delete_file", {"path": "y"}) == ("deleted", False)
    box.guards.append(lambda name, args: f"Not allowed: {name} of {args['path']}.")
    assert box.call("delete_file", {"path": "z"}) == ("Not allowed: delete_file of z.", True) and ran == ["x", "y"]
    assert box.call("nope", {})[1] is True  # unknown tools are answered before any guard


def test_a_guard_that_breaks_refuses_rather_than_lets_the_tool_run():
    box, ran = _box()

    def broken(name, args):
        raise RuntimeError("boom")

    box.guards.append(broken)
    out, err = box.call("delete_file", {"path": "x"})
    assert err and ran == [] and "wasn't run" in out


def test_each_toolbox_has_its_own_guard_list():
    a, b = Toolbox(), Toolbox()
    a.guards.append(lambda n, x: None)
    assert b.guards == []


# -- the stubs, with their frozen signatures -------------------------------------------------------------------
def _sig(fn):
    return re.sub(r"pathlib(\._local)?\.Path", "Path", str(inspect.signature(fn)))  # 3.13 prints pathlib._local


def test_the_stubs_have_their_frozen_signatures():
    assert perms.PRESETS == ("ask_all", "careful", "free", "read_only")
    assert _sig(perms.preset_for) == "(root, cfg, role: str) -> str"
    assert _sig(perms.guard) == "(root, cfg, role: str, gate) -> Callable"
    assert _sig(streamlog.sink) == "(root, task: str) -> Callable[[str, str], NoneType]"
    assert _sig(streamlog.tail) == "(root, task: str, since: int = 0) -> dict"
    assert _sig(reach.standup) == "(ctx) -> dict"
    assert _sig(reach.poll_hooks) == "(ctx, a: dict) -> list[dict]"
    assert _sig(reach.beat) == "(hub, machine: dict) -> None"
    assert _sig(reach.normalise_hook) == "(raw: dict, a: dict) -> dict"
    assert _sig(reach.hook_words) == "(a: dict) -> str"
    assert _sig(winshot.window_picture) == "(pid: int, out: Path, wait: float = 8.0, grab=None, find=None) -> dict"
    assert _sig(emulator.ready) == "(rows, os_name) -> dict"
    assert _sig(emulator.start) == "(avd: str, sdk: Path, run=None, timeout: float = 240) -> 'Running'"


def test_the_stubs_do_nothing_yet(tmp_path):
    assert perms.preset_for(tmp_path, None, "coder") == "careful"
    # filled by p1-perms (tests/test_perms.py): a reading tool passes, a delete would wait for the owner
    assert perms.guard(tmp_path, None, "coder", None)("read_file", {"path": "x"}) is None
    # streamlog is filled (p1-chat; its own tests in tests/test_stream.py)
    # reach is filled (p1-reach; its own tests in tests/test_reach.py): with nothing to look at it does nothing
    assert reach.poll_hooks(None, {}) == [] and reach.beat(None, {}) is None
    shot = winshot.window_picture(1, tmp_path / "w.png")
    assert shot["ok"] is False and shot["file"] is None and shot["why"]
    r = emulator.ready([], "linux")
    assert r["can"] is False and r["avds"] == [] and r["why"]
    with pytest.raises(emulator.EmulatorError):
        emulator.start("Pixel", tmp_path)


@pytest.mark.parametrize("mode,preset", [("off", "free"), ("risky", "careful"), ("all", "ask_all")])
def test_preset_for_maps_todays_gate_mode(tmp_path, monkeypatch, mode, preset):
    monkeypatch.setenv("ROUNDTABLE_GATE", mode)
    assert perms.preset_for(tmp_path, None, "coder") == preset


# -- automation, config, the phone's prefixes, the charter ------------------------------------------------------
def test_automation_knows_the_new_kinds_and_the_stand_up():
    assert automation.KINDS == ("schedule", "issues", "ci", "events", "poll", "local")
    assert automation.WHATS == ("idea", "goal", "health", "backup", "learn", "standup")
    a = automation.normalise({"kind": "schedule", "when": {"kind": "weekly", "days": ["mon"], "time": "09:00"},
                              "do": {"what": "standup"}})
    assert a["do"] == {"what": "standup"} and a["name"] == "Stand-up" and automation.what_words(a)
    hooks = {"events": {"repo": "acme/shop", "events": ["push"]}, "poll": {"url": "https://example.com/s"},
             "local": {"secret": "made-up-secret-long-enough-0123456789"}}
    for kind in ("events", "poll", "local"):
        h = automation.normalise({"kind": kind, "make": "idea", "hook": hooks[kind]})
        assert h["kind"] == kind and h["name"] and automation.what_words(h)


def test_old_automations_are_saved_exactly_as_before():
    raw = {"id": "a1", "kind": "issues", "repo": "acme/shop", "label": "roundtable", "created_at": "x"}
    assert automation.normalise(raw) == {"id": "a1", "kind": "issues", "name": "Issues labelled roundtable in acme/shop",
                                         "on": True, "start_by_itself": False, "cap_usd": 0.0, "created_at": "x",
                                         "repo": "acme/shop", "label": "roundtable", "make": "idea"}


def test_the_new_kinds_call_the_reach_stubs_and_do_nothing_yet(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(reach, "poll_hooks", lambda ctx, a: calls.append(a["kind"]) or [])
    monkeypatch.setattr(reach, "standup", lambda ctx: calls.append("standup") or {})
    cfg = parse_config({**json.loads(json.dumps(RAW)), "automation": {"list": [
        {"id": "h1", "kind": "poll", "make": "idea", "hook": {"url": "https://example.com/s"}},
        {"id": "s1", "kind": "schedule", "when": {"kind": "once", "at": "2026-11-27T09:00"},
         "do": {"what": "standup"}}]}})
    from datetime import datetime, timezone

    out = automation.tick(cfg, home=tmp_path, now=datetime(2026, 11, 27, 9, 1, tzinfo=timezone.utc),
                          start=lambda *a: pytest.fail("nothing may start"))
    assert out == [] and "poll" in calls and "standup" in calls


def test_a_hook_item_is_acted_on_once(tmp_path, monkeypatch):
    item = {"key": "ev-1", "what": "idea", "title": "From outside", "text": "a quoted event"}
    monkeypatch.setattr(reach, "poll_hooks", lambda ctx, a: [item])
    started = []
    cfg = parse_config({**json.loads(json.dumps(RAW)), "automation": {"list": [{"id": "h1", "kind": "local", "make": "idea",
                                                                            "hook": {"secret": "made-up-secret-long-enough-0123456789"}}]}})
    start = lambda kind, title, target, fn: started.append(kind)  # noqa: E731
    automation.tick(cfg, home=tmp_path, start=start, projects_dir=tmp_path / "projects")
    automation.tick(cfg, home=tmp_path, start=start, projects_dir=tmp_path / "projects")
    assert started == ["plan"]


def test_the_new_settings_sections_and_the_charter():
    for name in ("board", "editor", "stream", "slash", "voice", "perms", "builders", "standup", "hooks",
                 "integrations", "winshot", "emulator"):
        assert name in hconfig.FEATURE_SECTIONS
    assert {"perms", "builders"} <= charter.PROTECTED_KEYS and "harness/perms.py" in charter.NO_TOUCH_FILES
    assert "perms" in {r["id"] for r in charter.NEVER}


def test_the_phone_may_call_the_new_feature_routes():
    kt = (ROOT / "mobile/app/src/main/java/com/meztking/roundtable/net/Api.kt").read_text(encoding="utf-8")
    block = re.search(r"FEATURE_PREFIXES = listOf\(([^)]*)\)", kt).group(1)
    for p in ("/api/board", "/api/stream", "/api/commands", "/api/ci", "/api/market", "/api/documents"):
        assert f'"{p}"' in block
