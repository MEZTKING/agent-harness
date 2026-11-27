"""What each job may do (harness/perms.py): the four presets on scripted tasks, the order of authority, a refused
tool, "Always allow" for tools and websites, the network box, and the app's routes (ui/permsapi.py).
Made-up projects, scripted models, no network, no keys."""

import json
import os
import shutil
import subprocess
import sys

import pytest
import yaml

from roundtable import asks as asklib
from roundtable.harness import gate as g
from roundtable.harness import perms
from roundtable.harness.agent import Budget, run_agent
from roundtable.harness.config import ModelRef, parse_config
from roundtable.harness.gate import Gate
from roundtable.harness.tools import Tool, Toolbox, ToolSpec, Workspace, _obj
from roundtable.improve import charter
from roundtable.providers.scripted import ScriptedProvider, reply

from .test_gate import answer_when_asked
from .test_harness import RAW, Brain, make, tool_names


@pytest.fixture(autouse=True)
def _no_machine_choice(monkeypatch):
    monkeypatch.delenv(g.ENV, raising=False)


def project_yaml(root, **values):
    (root / ".harness").mkdir(parents=True, exist_ok=True)
    (root / ".harness" / "project.yaml").write_text(yaml.safe_dump(values), encoding="utf-8")


def with_perms(monkeypatch, orch):
    """The coordinator's hook-up, for the tests: every toolbox a job runs with is fitted to its preset first."""
    from roundtable.harness import agent as agentmod

    real = agentmod.run_agent

    def fitted(cfg, ref, system, prompt, box, *a, **k):
        perms.apply(box, orch.project.root, orch.cfg, k.get("role") or "", orch.ws.gate)
        return real(cfg, ref, system, prompt, box, *a, **k)

    for name, mod in list(sys.modules.items()):
        if name.startswith("roundtable.") and getattr(mod, "run_agent", None) is real:
            monkeypatch.setattr(mod, "run_agent", fitted)


# -- the preset and where it comes from -------------------------------------------------------------------------
def test_norm_preset_reads_names_and_todays_modes():
    assert [perms.norm_preset(v) for v in ("ask_all", "Ask every time", "careful", "risky", "off", "all", "free",
                                           "Read only", "read-only", "", None, "nonsense")] == [
        "ask_all", "ask_all", "careful", "careful", "free", "ask_all", "free", "read_only", "read_only", None, None, None]


def test_the_order_of_authority(tmp_path, monkeypatch):
    harness = tmp_path / "cfg" / "harness.yaml"
    harness.parent.mkdir()
    raw = {**json.loads(json.dumps(RAW)), "perms": {"roles": {"coder": "ask_all"}, "default": "free"},
           "gate": {"ask_first": "all"}}
    harness.write_text(yaml.safe_dump(raw), encoding="utf-8")
    cfg = parse_config(raw, harness)
    root = tmp_path / "p"
    root.mkdir()
    assert perms.explain(root, cfg, "coder") == {"preset": "ask_all", "source": "harness.yaml, for this job"}
    assert perms.preset_for(root, cfg, "reviewer") == "free"  # harness.yaml's default
    (harness.parent / "custom.yaml").write_text(yaml.safe_dump({"perms": {"default": "careful"}}), encoding="utf-8")
    assert perms.explain(root, cfg, "coder")["source"] == "this computer"
    monkeypatch.setenv(g.ENV, "all")  # the phone's "Ask me first" beats the computer's default
    assert perms.explain(root, cfg, "coder") == {"preset": "ask_all", "source": "this computer (Ask me first)"}
    (harness.parent / "custom.yaml").write_text(yaml.safe_dump({"perms": {"roles": {"coder": "read_only"}}}))
    assert perms.explain(root, cfg, "coder") == {"preset": "read_only", "source": "this computer, for this job"}
    project_yaml(root, ask_first="off")
    assert perms.explain(root, cfg, "coder") == {"preset": "free", "source": "this project"}
    project_yaml(root, ask_first="off", perms={"coder": "careful"})
    assert perms.explain(root, cfg, "coder") == {"preset": "careful", "source": "this project, for this job"}
    assert perms.preset_for(root, cfg, "reviewer") == "free"  # the job without its own choice: the project's


def test_the_default_is_careful_and_todays_modes_still_count(tmp_path, monkeypatch):
    assert perms.preset_for(tmp_path, None, "coder") == "careful"
    for mode, preset in (("off", "free"), ("risky", "careful"), ("all", "ask_all")):
        monkeypatch.setenv(g.ENV, mode)
        assert perms.preset_for(tmp_path, None, "coder") == preset


def test_a_setting_that_cant_be_read_makes_everything_wait(tmp_path):
    project_yaml(tmp_path, perms={"coder": "whatever-this-is"})
    assert perms.explain(tmp_path, None, "coder")["preset"] == "ask_all"
    (tmp_path / ".harness" / "project.yaml").write_text("perms: [not, a, table]\n")
    assert perms.preset_for(tmp_path, None, "coder") == "ask_all"
    project_yaml(tmp_path, perms={"coder": "read_only"})  # stricter than ask_all stays as it is
    assert perms.preset_for(tmp_path, None, "coder") == "read_only"


def test_perms_never_changes_what_the_charter_protects(tmp_path):
    assert "perms" in charter.PROTECTED_KEYS and "builders" in charter.PROTECTED_KEYS
    assert "harness/perms.py" in charter.NO_TOUCH_FILES and "harness/gate.py" in charter.NO_TOUCH_FILES
    assert any(n["id"] == "perms" for n in charter.NEVER)
    cfg = parse_config(json.loads(json.dumps(RAW)))
    project_yaml(tmp_path, perms={"coder": "careful", "reviewer": "ask_all"})
    cfg.learned = {"perms": {"coder": "free", "reviewer": "read_only"}}  # what learning might say
    assert perms.preset_for(tmp_path, cfg, "coder") == "careful"  # never looser
    assert perms.explain(tmp_path, cfg, "reviewer") == {"preset": "read_only", "source": "what it learned"}
    cfg.learned = {}
    cfg.kind_perms = {"default": "free", "coder": "ask_all"}  # what a project's kind might say
    assert perms.preset_for(tmp_path, cfg, "reviewer") == "ask_all"
    assert perms.explain(tmp_path, cfg, "coder") == {"preset": "ask_all", "source": "the project's kind"}


def test_a_gate_for_a_job_follows_its_preset(tmp_path):
    project_yaml(tmp_path, ask_first="off", perms={"coder": "ask_all", "checker": "read_only"})
    assert Gate(tmp_path).mode() == "off"
    assert Gate(tmp_path, role="coder").mode() == "all"
    ro = Gate(tmp_path, role="checker", poll=0.01, timeout=0.05)
    assert "Read only" in ro.check("ls")


# -- each preset on a scripted task ----------------------------------------------------------------------------
class WorkBrain(Brain):
    """T1's coder: a planned file, a file outside the plan, one command, then finishes."""

    def __init__(self, command="echo ran", **kw):
        super().__init__(plan=[{"id": "T1", "title": "hello module", "role": "coder", "description": "create hello.py",
                                "acceptance": "hello.py prints hi", "depends_on": [], "files": ["hello.py"]}], **kw)
        self.command, self.told, self.tools = command, [], []

    def __call__(self, model, system, messages, tools):
        names = tool_names(tools)
        if "finish_task" in names:
            self.tools.append(names)
            steps = [("write_file", {"path": "hello.py", "content": "print('hi')\n"}),
                     ("write_file", {"path": "notes/extra.md", "content": "more\n"}),
                     ("run_command", {"command": self.command})]
            done = sum(1 for m in messages if m["role"] == "tool")
            if messages[-1]["role"] == "tool":
                self.told.append(messages[-1]["content"])
            if done < len(steps):
                return reply(calls=[steps[done]])
            return reply(calls=[("finish_task", {"summary": "done"})])
        return super().__call__(model, system, messages, tools)


def scripted_run(tmp_path, monkeypatch, settings, brain=None, timeout=0.3):
    brain = brain or WorkBrain()
    orch, *_ = make(tmp_path, brain=brain)
    project_yaml(orch.project.root, **settings)
    orch.ws.gate = Gate(orch.project.root, orch.cfg, poll=0.02, timeout=timeout)
    with_perms(monkeypatch, orch)
    return orch, brain


def cards_seen(root, stop):
    """Every card that appears, refused at once (so a test sees what waited without waiting)."""
    import threading
    import time

    seen = []

    def watch():
        while not stop.is_set():
            for c in asklib.command_asks(root):
                if c["id"] not in [s["id"] for s in seen]:
                    seen.append(c)
                    Gate(root).answer(c["source"]["command"], g.DENY)
            time.sleep(0.01)

    t = threading.Thread(target=watch, daemon=True)
    t.start()
    return seen, t


def run_watched(orch):
    import threading

    stop = threading.Event()
    seen, t = cards_seen(orch.project.root, stop)
    orch.start("hello")
    assert orch.run() == "done"
    stop.set()
    t.join(2)
    return seen


def test_ask_every_time_holds_commands_and_changes_outside_the_plan(tmp_path, monkeypatch):
    orch, brain = scripted_run(tmp_path, monkeypatch, {"ask_first": "off", "perms": {"coder": "ask_all"}})
    seen = run_watched(orch)
    what = [c["command"] for c in seen]
    assert what == ["Write notes/extra.md", "echo ran"]  # hello.py is planned: it didn't ask
    assert "isn't one of this task's planned files" in seen[0]["detail"]
    assert (orch.project.root / "hello.py").is_file() and not (orch.project.root / "notes" / "extra.md").exists()
    assert brain.told[1].startswith("The owner didn't allow this (write notes/extra.md)")
    assert "The owner didn't allow this command" in brain.told[2]


def test_careful_holds_only_risky_commands(tmp_path, monkeypatch):
    brain = WorkBrain(command="git push nowhere-at-all")
    orch, brain = scripted_run(tmp_path, monkeypatch, {"ask_first": "off", "perms": {"coder": "careful"}}, brain)
    seen = run_watched(orch)
    assert [c["command"] for c in seen] == ["git push nowhere-at-all"]  # the files didn't ask
    assert (orch.project.root / "notes" / "extra.md").is_file()


def test_free_lets_everything_run(tmp_path, monkeypatch):
    sep = " & " if sys.platform == "win32" else "; "
    brain = WorkBrain(command=f"git push nowhere-at-all 2>&1{sep}echo ran-it")
    orch, brain = scripted_run(tmp_path, monkeypatch, {"ask_first": "all", "perms": {"coder": "free"}}, brain)
    seen = run_watched(orch)
    assert seen == [] and "ran-it" in brain.told[2]  # the project says ask all; the job's own Free wins


def test_read_only_has_no_write_or_command_tool_in_its_request(tmp_path, monkeypatch):
    orch, brain = scripted_run(tmp_path, monkeypatch, {"perms": {"coder": "read_only", "orchestrator": "read_only"}})
    seen = run_watched(orch)
    assert seen == []
    assert brain.tools and all(not ({"write_file", "edit_file", "run_command"} & names) for names in brain.tools)
    assert all("finish_task" in names and "read_file" in names for names in brain.tools)
    assert not (orch.project.root / "hello.py").exists()


def test_with_every_job_on_careful_requests_are_byte_for_byte_as_before(tmp_path, monkeypatch):
    from .test_sweep_seam import requests_of

    plain = requests_of(tmp_path / "plain", monkeypatch)
    from roundtable.harness import agent as agentmod
    from roundtable.harness.orchestrator import Orchestrator

    real = agentmod.run_agent
    fitted_roles = []

    def fitted(cfg, ref, system, prompt, box, *a, **k):
        root = box.source.root if box.source is not None else None
        perms.apply(box, root, cfg, k.get("role") or "", getattr(box.source, "gate", None))
        fitted_roles.append((k.get("role"), len(box.guards)))
        return real(cfg, ref, system, prompt, box, *a, **k)

    for name, mod in list(sys.modules.items()):
        if name.startswith("roundtable.") and getattr(mod, "run_agent", None) is real:
            monkeypatch.setattr(mod, "run_agent", fitted)
    assert Orchestrator  # loaded
    assert requests_of(tmp_path / "careful", monkeypatch) == plain
    assert fitted_roles and all(n >= 1 for _, n in fitted_roles)


# -- a refused tool ----------------------------------------------------------------------------------------------
def delete_box(root, gate, role="coder", cfg=None):
    gone = []
    box = Toolbox()
    box.add(Tool(ToolSpec("delete_file", "Delete a file.", _obj({"path": {"type": "string"}}, ["path"])),
                 lambda a: (gone.append(a["path"]), (root / a["path"]).unlink(), "deleted")[-1]))
    box.add(Tool(ToolSpec("finish_task", "Done.", _obj({"summary": {"type": "string"}}, ["summary"])),
                 lambda a: "recorded", terminal=True))
    perms.apply(box, root, cfg, role, gate)
    return box, gone


def test_a_refused_delete_returns_the_sentence_and_the_run_finishes(tmp_path):
    (tmp_path / "keep.txt").write_text("mine")
    told = []

    def brain(model, system, messages, tools):
        if messages[-1]["role"] == "tool":
            told.append(messages[-1]["content"])
            return reply(calls=[("finish_task", {"summary": "carried on"})])
        return reply(calls=[("delete_file", {"path": "keep.txt"})])

    cfg = parse_config({"providers": {"s": {"type": "scripted"}},
                        "roles": {"orchestrator": {"model": "s/m"}, "reviewer": {"model": "s/m"},
                                  "coder": {"model": "s/m"}}})
    cfg.register("s", ScriptedProvider("s", brain))
    gate = Gate(tmp_path, poll=0.02, timeout=5)
    box, gone = delete_box(tmp_path, gate)
    t, seen = answer_when_asked(tmp_path, g.DENY, note="keep it")
    res = run_agent(cfg, ModelRef("s", "m"), "sys", "go", box, Budget(limit_usd=1), require_terminal="finish_task")
    t.join(2)
    assert res.stop != "breaker" and "finish_task" in box.captured
    assert seen["card"]["command"].startswith("Delete keep.txt") and gone == []
    assert (tmp_path / "keep.txt").read_text() == "mine"
    assert told[0].startswith("The owner didn't allow this (delete keep.txt)") and "keep it" in told[0]


def test_nobody_answers_so_the_delete_isnt_done(tmp_path):
    (tmp_path / "keep.txt").write_text("mine")
    box, gone = delete_box(tmp_path, Gate(tmp_path, poll=0.01, timeout=0.05))
    out, err = box.call("delete_file", {"path": "keep.txt"})
    assert err and out.startswith("Nobody answered within") and gone == [] and (tmp_path / "keep.txt").exists()


def test_free_deletes_without_asking_and_read_only_never(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    project_yaml(tmp_path, perms={"coder": "free", "checker": "read_only"})
    box, gone = delete_box(tmp_path, Gate(tmp_path, poll=0.01, timeout=0.05))
    assert box.call("delete_file", {"path": "a.txt"}) == ("deleted", False)
    ro, _ = delete_box(tmp_path, Gate(tmp_path, poll=0.01, timeout=0.05), role="checker")
    assert "delete_file" not in ro.tools and "finish_task" in ro.tools  # cut from the request
    guard = perms.guard(tmp_path, None, "checker", Gate(tmp_path))
    assert "Read only" in guard("delete_file", {"path": "x"}) and "Read only" in guard("mcp__x__y", {})
    assert guard("read_file", {"path": "x"}) is None and guard("submit_review", {}) is None


def test_emptying_a_file_asks_like_a_delete(tmp_path):
    ws = Workspace(tmp_path)
    (tmp_path / "data.txt").write_text("precious")
    ws.gate = Gate(tmp_path, poll=0.01, timeout=0.05)
    box = perms.apply(ws.toolbox(), tmp_path, None, "coder", ws.gate)
    out, err = box.call("write_file", {"path": "data.txt", "content": ""})
    assert err and "empty the file data.txt" in out and (tmp_path / "data.txt").read_text() == "precious"
    assert box.call("write_file", {"path": "new.txt", "content": ""})[1] is False  # a new empty file is fine


def test_an_mcp_tool_allowed_once_isnt_asked_again(tmp_path):
    calls = []
    box = Toolbox()
    box.add(Tool(ToolSpec("mcp__notes__add", "[MCP server notes] add", _obj({"text": {"type": "string"}}, [])),
                 lambda a: (calls.append(a), "added")[-1]))
    gate = Gate(tmp_path, poll=0.02, timeout=5)
    perms.apply(box, tmp_path, None, "coder", gate)
    t, seen = answer_when_asked(tmp_path, g.ALLOW)
    assert box.call("mcp__notes__add", {"text": "a"}) == ("added", False)
    t.join(2)
    assert seen["card"]["command"].startswith("Use notes's tool add")
    gate.timeout = 0.05  # a second card would now time out and refuse
    assert box.call("mcp__notes__add", {"text": "b"}) == ("added", False) and len(calls) == 2
    fresh = perms.guard(tmp_path, None, "coder", Gate(tmp_path, poll=0.01, timeout=0.05))
    assert fresh("mcp__notes__add", {}).startswith("Nobody answered")  # "Allow once" was for that job only
    gate.timeout = 5
    t, _ = answer_when_asked(tmp_path, g.ALWAYS)
    assert fresh.__call__("mcp__notes__add", {}) is None
    t.join(2)
    assert perms.allowed(tmp_path)["mcp"] == ["mcp__notes__add"]
    again = perms.guard(tmp_path, None, "coder", Gate(tmp_path, poll=0.01, timeout=0.05))
    assert again("mcp__notes__add", {}) is None


def test_a_website_not_seen_before_asks_and_always_allow_keeps_it(tmp_path):
    gate = Gate(tmp_path, poll=0.02, timeout=5)
    guard = perms.guard(tmp_path, None, "coder", gate)
    t, seen = answer_when_asked(tmp_path, g.ALWAYS)
    assert guard("web_read", {"url": "https://docs.example.invalid/page"}) is None
    t.join(2)
    assert seen["card"]["command"].startswith("Read a page on docs.example.invalid")
    assert perms.allowed(tmp_path)["hosts"] == ["docs.example.invalid"]
    other = perms.guard(tmp_path, None, "coder", Gate(tmp_path, poll=0.01, timeout=0.05))
    assert other("web_read", {"url": "https://docs.example.invalid/other"}) is None
    assert other("web_read", {"url": "https://elsewhere.example.invalid/"}).startswith("Nobody answered")
    assert "isn't a web address" in other("web_read", {"url": "not a url"})
    assert other("web_search", {"query": "x"}) is None
    assert perms.forget(tmp_path, "hosts", "docs.example.invalid") and perms.allowed(tmp_path)["hosts"] == []


def test_without_a_gate_the_guard_makes_its_own_and_never_lets_a_delete_through(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "DEFAULT_TIMEOUT_MIN", 0.001)
    guard = perms.guard(tmp_path, None, "coder", None)
    assert guard("read_file", {"path": "x"}) is None
    assert guard("delete_file", {"path": "x"}).startswith("Nobody answered")


# -- commands: the job decides once, the workspace's gate doesn't ask again ----------------------------------------
def test_a_command_the_job_allowed_isnt_asked_twice(tmp_path):
    ws = Workspace(tmp_path)
    project_yaml(tmp_path, ask_first="risky", perms={"coder": "ask_all"})
    ws.gate = Gate(tmp_path, poll=0.02, timeout=5)
    box = perms.apply(ws.toolbox(), tmp_path, None, "coder", ws.gate)
    asked = []
    real_wait = ws.gate._wait_for
    ws.gate._wait_for = lambda cid, card, limit: (asked.append(card["command"]), real_wait(cid, card, limit))[-1]
    t, _ = answer_when_asked(tmp_path, g.ALLOW)
    out, err = box.call("run_command", {"command": "git push nowhere-at-all 2>&1; echo ran" if os.name != "nt"
                                        else "git push nowhere-at-all 2>&1 & echo ran"})
    t.join(2)
    assert not err and "ran" in out and len(asked) == 1  # asked once, by the job's own check


def test_cleared_is_once_this_thread_and_this_command_only(tmp_path):
    gate = Gate(tmp_path, poll=0.01, timeout=0.05)
    g.clear_once(tmp_path, "git push x")
    assert gate.check("git push y").startswith("Nobody answered")  # another command: asks (and the mark is gone)
    g.clear_once(tmp_path, "git push x")
    assert gate.check("git push x") is None
    assert gate.check("git push x").startswith("Nobody answered")  # once only


def test_a_shared_folder_is_never_deleted_unseen(tmp_path):
    root = tmp_path / "p"
    (root / ".harness").mkdir(parents=True)
    (root / ".harness" / "links.json").write_text(json.dumps({"T1": {"node_modules": str(root / "node_modules")}}))
    careful = perms.guard(root, None, "coder", Gate(root, poll=0.01, timeout=0.05))
    out = careful("run_command", {"command": "rm -rf node_modules/"})
    assert out.startswith("Nobody answered")
    assert careful("run_command", {"command": "ls node_modules"}) is None
    project_yaml(root, perms={"coder": "free"})
    free = perms.guard(root, None, "coder", Gate(root))
    assert "shared with the main project folder" in free("run_command", {"command": "rm -r ./node_modules"})


# -- the box ------------------------------------------------------------------------------------------------------
def test_the_box_words_say_plainly_where_there_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(perms, "_box_layer", lambda: "")
    assert perms._box_note("careful", {"needs_net": False}) == (
        False, "There's no box on Windows: if you allow it, it runs with this computer's full reach."
        if os.name == "nt" else
        "There's no box on this computer (bwrap isn't installed): if you allow it, it can use the internet.")
    assert perms._box_note("free", None) == (False, "")
    monkeypatch.setattr(perms, "_box_layer", lambda: "bwrap")
    if os.name != "nt":
        assert perms._box_note("ask_all", {"needs_net": False})[0] is True
        assert perms._box_note("careful", {"needs_net": True})[0] is False
        assert perms._box_note("careful", {})[0] is False  # a plan that doesn't say: as before


def test_boxed_only_wraps_the_command_just_decided(tmp_path, monkeypatch):
    assert perms.boxed("echo hi") == "echo hi"
    perms._BOX.item = ("echo hi", __import__("time").monotonic())
    assert perms.boxed("echo other") == "echo other" and perms.boxed("echo hi") == "echo hi"  # consumed
    perms._BOX.item = ("echo hi", __import__("time").monotonic())
    wrapped = perms.boxed("echo hi")
    assert wrapped.startswith("bwrap ") and "--unshare-net" in wrapped and wrapped.endswith("'echo hi'")


@pytest.mark.skipif(not (sys.platform.startswith("linux") and shutil.which("bwrap")), reason="needs bwrap")
def test_a_builder_command_runs_with_the_network_off(tmp_path):
    if not perms._box_layer():
        pytest.skip("bwrap can't make a network box here")
    root = tmp_path
    (root / ".harness").mkdir()
    (root / ".harness" / "tasks.json").write_text(json.dumps([{"id": "T1", "status": "running", "needs_net": False}]))
    gate = Gate(root, poll=0.01, timeout=0.05)
    guard = perms.guard(root, None, "coder", gate)
    cmd = "cat /proc/net/dev"
    assert guard("run_command", {"command": cmd}) is None
    res = subprocess.run(perms.boxed(cmd), shell=True, capture_output=True, text=True, timeout=30)
    names = [ln.split(":")[0].strip() for ln in res.stdout.splitlines()[2:]]
    assert res.returncode == 0 and names == ["lo"]


# -- the app's routes ----------------------------------------------------------------------------------------------
class FakeApp:
    def __init__(self, tmp_path):
        from roundtable.harness.orchestrator import Project

        self.path = tmp_path / "cfg" / "harness.yaml"
        self.path.parent.mkdir(parents=True)
        raw = json.loads(json.dumps(RAW))
        self.path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        self.proj = tmp_path / "proj"
        (self.proj / ".harness").mkdir(parents=True)
        self._Project = Project

    def cfg(self):
        from roundtable.harness.config import load_config

        return load_config(str(self.path))

    def project(self, cfg, path):
        from roundtable.ui.server import ApiError

        if os.path.realpath(path) != os.path.realpath(self.proj):
            raise ApiError("not here", 404)
        return self._Project(self.proj)


def test_the_routes_set_this_computers_and_a_projects_choice(tmp_path):
    from roundtable.ui import permsapi

    app = FakeApp(tmp_path)
    r = permsapi.routes(app)
    st = r[("GET", "/api/perms")]({})
    assert [p["id"] for p in st["presets"]] == list(perms.PRESETS)
    assert {j["job"]: j["preset"] for j in st["jobs"]}["coder"] == "careful"
    out = r[("POST", "/api/perms")]({"job": "coder", "preset": "free"})
    assert out == {"needs_sure": True, "words": permsapi.FREE_SURE}  # nothing saved yet
    assert "perms" not in (yaml.safe_load((app.path.parent / "custom.yaml").read_text()) or {}) \
        if (app.path.parent / "custom.yaml").exists() else True
    out = r[("POST", "/api/perms")]({"job": "coder", "preset": "free", "sure": True})
    assert {j["job"]: j["preset"] for j in out["jobs"]}["coder"] == "free"
    assert yaml.safe_load((app.path.parent / "custom.yaml").read_text())["perms"] == {"roles": {"coder": "free"}}
    out = r[("POST", "/api/perms")]({"job": "reviewer", "preset": "read_only", "path": str(app.proj)})
    rows = {j["job"]: j for j in out["jobs"]}
    assert rows["reviewer"]["preset"] == "read_only" and rows["reviewer"]["project"] == "read_only"
    assert yaml.safe_load((app.proj / ".harness" / "project.yaml").read_text())["perms"] == {"reviewer": "read_only"}
    out = r[("POST", "/api/perms")]({"preset": "ask_all"})
    assert out["default"] == "ask_all"
    from roundtable.ui.server import ApiError

    with pytest.raises(ApiError):
        r[("POST", "/api/perms")]({"job": "nobody", "preset": "careful"})
    with pytest.raises(ApiError):
        r[("POST", "/api/perms")]({"job": "coder", "preset": "anything"})
    with pytest.raises(ApiError):
        r[("GET", "/api/perms")]({"path": str(tmp_path / "elsewhere")})
    perms.allow(app.proj, "hosts", "a.example.invalid")
    out = r[("POST", "/api/perms/forget")]({"path": str(app.proj), "kind": "hosts", "value": "a.example.invalid"})
    assert out["allowed"]["hosts"] == []


def test_the_builders_settings_are_the_existing_keys_in_custom_yaml(tmp_path):
    from roundtable.ui import permsapi

    app = FakeApp(tmp_path)
    r = permsapi.routes(app)
    st = r[("GET", "/api/builders")]({})
    assert st["values"]["max_parallel"] == 1 and st["values"]["commands"] is True
    assert all(f["tip"] for f in st["fields"]) and any(f["more"] for f in st["fields"])
    out = r[("POST", "/api/builders")]({"max_parallel": 3, "max_steps_per_task": 60, "web_search": True,
                                       "compaction_at_tokens": 90000})
    assert out["values"]["max_parallel"] == 3 and out["values"]["max_steps_per_task"] == 60
    assert out["values"]["web_search"] is True and out["values"]["compaction_at_tokens"] == 90000
    custom = yaml.safe_load((app.path.parent / "custom.yaml").read_text())
    assert custom["limits"] == {"max_parallel": 3, "max_steps_per_task": 60}
    assert custom["websearch"] == {"enabled": True}
    assert custom["plugins"]["compactor"]["settings"] == {"at_tokens": 90000}
    from roundtable.ui.server import ApiError

    with pytest.raises(ApiError, match="between 1 and 8"):
        r[("POST", "/api/builders")]({"max_parallel": 40})
    with pytest.raises(ApiError):
        r[("POST", "/api/builders")]({})


def test_always_allow_for_a_file_holds_next_time(tmp_path):
    ws = Workspace(tmp_path)
    (tmp_path / "data.txt").write_text("precious")
    ws.gate = Gate(tmp_path, poll=0.02, timeout=5)
    box = perms.apply(ws.toolbox(), tmp_path, None, "coder", ws.gate)
    t, _ = answer_when_asked(tmp_path, g.ALWAYS)
    assert box.call("write_file", {"path": "./data.txt", "content": ""})[1] is False
    t.join(2)
    assert perms.allowed(tmp_path)["paths"] == ["data.txt"]
    (tmp_path / "data.txt").write_text("again")
    again = perms.apply(ws.toolbox(), tmp_path, None, "coder", Gate(tmp_path, poll=0.01, timeout=0.05))
    assert again.call("write_file", {"path": "data.txt", "content": ""})[1] is False
