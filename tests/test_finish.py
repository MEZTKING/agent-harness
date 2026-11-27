"""FinishStage: start the finished thing, use it, fix what breaks (made-up projects, scripted models).

The walker is a fake that really fetches the page the harness serves, so a planted bug (a button that does
nothing) is found from the files the scripted workers wrote. d2-done's gate isn't in this branch, so a small
stand-in gate (the brief's: a failed ``must`` item blocks with one card) closes the run here.
"""

import json
import shutil
import sys
import urllib.request
from pathlib import Path

import pytest

from roundtable.harness import donelist, finishstage
from roundtable.harness.config import parse_config
from roundtable.harness.finishstage import FinishStage
from roundtable.harness.orchestrator import Orchestrator
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider

from .test_harness import RAW, reply, tool_names

BROKEN = "<button>Start</button><script>/* the button does nothing */</script>"
FIXED = "<button>Start</button><p>Score: 0</p><script>/* works */</script>"
PLAN = [{"id": "T1", "title": "the game page", "role": "coder", "description": "write index.html",
         "acceptance": "it opens", "depends_on": []}]
ITEMS = [{"id": "D1", "text": "You can press Start and see your score", "how": "journey",
          "steps": ["click Start", "expect_text Score"], "must": True},
         {"id": "D2", "text": "The page opens", "how": "page_opens", "must": True}]


class FinishBrain:
    """Scripted: the planner plans, the coder writes the page (fixers write ``fix_with``), the reviewer approves,
    and when asked for fixes the planner proposes ``fixes_per_round`` tasks."""

    def __init__(self, plan=PLAN, files=None, fix_with=FIXED, fixes_per_round=1):
        self.plan = plan
        self.files = files or {"index.html": BROKEN}
        self.fix_with = fix_with
        self.fixes_per_round = fixes_per_round
        self.fix_calls = 0
        self.fix_prompts = []

    def __call__(self, model, system, messages, tools):
        names = tool_names(tools)
        last = messages[-1]
        if "submit_plan" in names:
            return reply("planned") if last["role"] == "tool" else reply(calls=[("submit_plan", {"tasks": self.plan})])
        if "submit_fixes" in names:
            if last["role"] == "tool":
                return reply("done")
            self.fix_calls += 1
            self.fix_prompts.append(messages[0]["content"])
            tasks = [{"title": f"make Start work ({n})", "role": "coder", "fixes": "D1",
                      "description": "the Start button does nothing: show the score", "files": ["index.html"]}
                     for n in range(self.fixes_per_round)]
            return reply(calls=[("submit_fixes", {"tasks": tasks})])
        if "submit_review" in names:
            if last["role"] == "tool":
                return reply("ok")
            return reply(calls=[("submit_review", {"approved": True, "feedback": "fine"})])
        if "finish_task" in names:
            prompt = messages[0]["content"]
            tid = prompt.split("# Your task [", 1)[1].split("]", 1)[0]
            if last["role"] == "user":
                if tid.startswith("F"):
                    files = {k: self.fix_with for k in self.files if k.endswith("index.html")}
                else:
                    files = self.files
                return reply(calls=[("write_file", {"path": p, "content": c}) for p, c in files.items()])
            return reply(calls=[("finish_task", {"summary": f"{tid} done"})])
        return reply("Final report: all done.")


PY_HAS_INDEX = f'"{sys.executable}" -c "import os, sys; sys.exit(0 if os.path.isfile(\'index.html\') else 1)"'


class Walker:
    """Fetches each job's page; a journey passes when the page shows "Score"."""

    def __init__(self):
        self.calls = []

    def __call__(self, jobs):
        out = []
        for j in jobs:
            page = urllib.request.urlopen(j["url"], timeout=5).read().decode()
            self.calls.append((j["id"], j["url"], j["base"]))
            Path(j["png"]).write_bytes(b"png")
            needs_score = any(s["do"] == "expect_text" for s in j["steps"])
            ok = "Score" in page or not needs_score
            out.append({"id": j["id"], "passed": ok, "failed_step": None if ok else len(j["steps"]) - 1,
                        "why": "" if ok else "Timeout 5000ms exceeded waiting for “Score”",
                        "errors": [] if ok else ["Uncaught TypeError: start is not a function"]})
        return out


class Finishing(Orchestrator):
    """FinishStage hooked up as the coordinator will, with the done list seeded the way d2-done's plan step does,
    and the brief's gate."""

    items = ITEMS
    parts = None
    cards: list

    def _done_doc(self, doc, args):
        if self.parts:
            doc["parts"] = self.parts
        for item in self.items:
            donelist.add_item(self.project.root, dict(item))

    def _done_gate(self, tasks):
        v = donelist.verdict(self.project.root)
        if v["failed"]:
            self._set_status("blocked", pause="not_finished")
            self._attention("not_finished", f"Not finished: {len(v['failed'])} thing(s) still don't work")
            return "blocked"
        return None

    def _attention(self, key, text, details=""):
        self.cards = getattr(self, "cards", []) + [key]
        super()._attention(key, text, details)


def build(tmp_path, brain, finish=None, cls=Finishing, walker=None, **limits):
    raw = dict(RAW, limits={"max_cost_usd": 5, "max_attempts_per_task": 1, **limits},
               finish=dict({"max_usd": 5}, **(finish or {})))
    cfg = parse_config(json.loads(json.dumps(raw)))
    for name in ("a", "b"):
        cfg.register(name, ScriptedProvider(name, brain))
    cfg.register("img", ScriptedImages())
    events = []
    orch = cls(cfg, tmp_path / "proj", on_event=lambda k, d: events.append((k, d)))
    orch.ws.gate = None  # no gate settings in a test
    orch.journey_walker = walker or Walker()
    orch.shot_renderer = lambda jobs: []  # no real pictures after each task here
    return orch, events


def states(orch):
    return {i["id"]: i["state"] for i in donelist.read(orch.project.root)["items"]}


# -- the planted bug ------------------------------------------------------------------------------------------
def test_a_planted_bug_is_found_fixed_and_the_second_round_ends_done(tmp_path):
    brain = FinishBrain()
    orch, events = build(tmp_path, brain)
    orch.start("a made-up counting game")
    assert orch.run() == "done"
    tasks = {t.id: t for t in orch.project.tasks()}
    assert set(tasks) == {"T1", "F1"}
    assert tasks["F1"].added_by == "finish" and tasks["F1"].fix_of == "D1" and tasks["F1"].status == "done"
    assert states(orch) == {"D1": "passed", "D2": "passed"}
    assert brain.fix_calls == 1
    # the planner saw the evidence: the step that failed and the page's error
    assert "see “Score”" in brain.fix_prompts[0] and "start is not a function" in brain.fix_prompts[0]
    assert not getattr(orch, "cards", [])  # nobody was asked
    g = finishstage.goal_state(orch.project.root, 0)
    assert g["rounds"] == 1 and g["fix_tasks"] == 1 and g["checks"] == 2
    rounds = donelist.read(orch.project.root)["rounds"]
    assert [r["passed"] for r in rounds if r["item"] == "D1"] == [False, True]
    d1 = next(i for i in donelist.read(orch.project.root)["items"] if i["id"] == "D1")
    assert d1["evidence"]["picture"].startswith(".harness/journeys/g0/main/")
    assert (orch.project.root / d1["evidence"]["picture"]).is_file()
    assert ("tasks_added", {"by": "finish", "why": "it didn't work when tried: You can press Start and see your score",
                            "fix_of": "D1", "tasks": ["F1"]}) in events


def test_a_bug_the_fixer_never_fixes_stops_after_two_rounds_at_the_gate(tmp_path):
    brain = FinishBrain(fix_with=BROKEN)
    orch, events = build(tmp_path, brain)
    orch.start("a made-up counting game")
    assert orch.run() == "blocked"
    assert brain.fix_calls == 2
    assert sorted(t.id for t in orch.project.tasks()) == ["F1", "F2", "T1"]
    assert states(orch)["D1"] == "failed" and states(orch)["D2"] == "passed"
    assert orch.cards == ["not_finished"]  # one card
    assert any(k == "finish_gave_up" and "2 fix rounds" in d["why"] for k, d in events)


def test_the_fix_task_cap_holds(tmp_path):
    brain = FinishBrain(fix_with=BROKEN, fixes_per_round=3)
    orch, events = build(tmp_path, brain, finish={"max_fix_tasks": 2})
    orch.start("a made-up counting game")
    assert orch.run() == "blocked"
    added = [t for t in orch.project.tasks() if t.added_by == "finish"]
    assert len(added) == 2 and brain.fix_calls == 1  # two allowed, all in round one; no round two
    assert any(k == "finish_gave_up" and "2 fix tasks" in d["why"] for k, d in events)


def test_the_harness_wide_cap_on_added_tasks_holds_too(tmp_path):
    brain = FinishBrain(fix_with=BROKEN, fixes_per_round=3)
    orch, events = build(tmp_path, brain, max_auto_tasks=2)
    orch.start("a made-up counting game")
    assert orch.run() == "blocked"
    assert not [t for t in orch.project.tasks() if t.added_by]  # three at once is past the cap: refused
    assert any(k == "finish_refused" for k, _ in events)


def test_the_money_cap_holds(tmp_path):
    brain = FinishBrain(fix_with=BROKEN)
    orch, events = build(tmp_path, brain, finish={"max_usd": 0.000001})
    orch.start("a made-up counting game")
    assert orch.run() == "blocked"
    assert brain.fix_calls == 1  # the first round's fix spent the allowance: no second round
    assert any(k == "finish_gave_up" and "allowed for checking and fixing is spent" in d["why"] for k, d in events)


def test_try_fixing_again_clears_the_rounds(tmp_path):
    brain = FinishBrain(fix_with=BROKEN)
    orch, _ = build(tmp_path, brain)
    orch.start("a made-up counting game")
    orch.run()
    finishstage.clear_rounds(orch.project.root)
    g = finishstage.goal_state(orch.project.root, 0)
    assert (g["rounds"], g["fix_tasks"], g["spent"]) == (0, 0, 0.0)


def test_switched_off_it_does_nothing(tmp_path):
    brain = FinishBrain()
    orch, _ = build(tmp_path, brain, finish={"enabled": False})
    orch.start("a made-up counting game")
    assert orch.run() == "done"  # nothing was tried, so nothing failed and nothing was added
    assert brain.fix_calls == 0 and states(orch) == {"D1": "open", "D2": "open"}


# -- several parts -------------------------------------------------------------------------------------------
class TwoParts(Finishing):
    parts = [{"id": "game", "name": "The game", "folder": "game"}, {"id": "site", "name": "Its web page", "folder": "site"}]
    items = [{"id": "D1", "text": "You can play the game", "how": "journey", "steps": ["click Start", "expect_text Score"],
              "part": "game"},
             {"id": "D2", "text": "The web page opens", "how": "page_opens", "part": "site"},
             {"id": "D3", "text": "The page has a download link", "how": "file_exists", "path": "*.html", "part": "site"},
             {"id": "D4", "text": "The game's check passes", "how": "command", "command": PY_HAS_INDEX,
              "part": "game"}]


def test_a_two_part_project_has_both_parts_started_and_checked(tmp_path):
    brain = FinishBrain(files={"game/index.html": FIXED, "site/index.html": "<h1>Get the game</h1>"})
    walker = Walker()
    orch, events = build(tmp_path, brain, cls=TwoParts, walker=walker)
    orch.start("a made-up game and its web page")
    assert orch.run() == "done"
    assert states(orch) == {"D1": "passed", "D2": "passed", "D3": "passed", "D4": "passed"}
    bases = {jid: base for jid, _, base in walker.calls}
    assert bases["D1"] != bases["D2"]  # each part was served from its own folder
    items = {i["id"]: i for i in donelist.read(orch.project.root)["items"]}
    assert items["D1"]["evidence"]["part"] == "game" and items["D2"]["evidence"]["part"] == "site"
    assert items["D1"]["evidence"]["picture"].startswith(".harness/journeys/g0/game/")


# -- the other ways of checking -----------------------------------------------------------------------------
class Kinds(Finishing):
    items = [{"id": "D1", "text": "The tests pass", "how": "command", "command": "exit 1"},
             {"id": "D2", "text": "There's a save file", "how": "file_exists", "path": "saves/*.json"},
             {"id": "D3", "text": "Someone played it", "how": "play"},
             {"id": "D4", "text": "You approve the colours", "how": "owner"}]


def test_commands_files_play_and_owner_items(tmp_path):
    orch, _ = build(tmp_path, FinishBrain(), cls=Kinds, finish={"rounds": 0})
    orch.start("a made-up tool")
    assert orch.run() == "blocked"
    items = {i["id"]: i for i in donelist.read(orch.project.root)["items"]}
    assert items["D1"]["state"] == "failed" and items["D1"]["evidence"]["exit_code"] == 1
    assert items["D2"]["state"] == "failed" and "No file matches saves/*.json" in items["D2"]["words"]
    assert items["D3"]["state"] == "unchecked" and items["D3"]["words"]  # nobody here could play it (playtest.py)
    assert items["D4"]["state"] == "open"  # left for the owner


def test_play_items_go_to_whoever_can_play(tmp_path):
    class Plays(Kinds):
        def _play_check(self, item):
            return {"passed": True, "words": "Played a minute: it worked.", "evidence": {"seconds": 60}}

    orch, _ = build(tmp_path, FinishBrain(), cls=Plays, finish={"rounds": 0})
    orch.start("a made-up game")
    orch.run()
    assert states(orch)["D3"] == "passed"


@pytest.mark.skipif(not shutil.which("npm"), reason="npm isn't installed here")
def test_an_app_that_will_not_start_fails_its_items_with_the_reason(tmp_path):
    files = {"package.json": json.dumps({"scripts": {"start": "python -c \"import sys; print('no such module'); sys.exit(2)\""}}),
             "src.txt": "x"}
    brain = FinishBrain(files=files)
    orch, _ = build(tmp_path, brain, finish={"rounds": 0})
    orch.start("a made-up server app")
    assert orch.run() == "blocked"
    items = {i["id"]: i for i in donelist.read(orch.project.root)["items"]}
    assert items["D1"]["state"] == "failed" and items["D1"]["words"].startswith("It didn't start: the start command ended")
    assert "no such module" in items["D1"]["evidence"]["app_output"]


def test_a_refused_start_is_unchecked_not_failed(tmp_path):
    files = {"package.json": json.dumps({"scripts": {"start": "node server.js"}})}
    orch, _ = build(tmp_path, FinishBrain(files=files), finish={"rounds": 0})
    orch.ws.allow_shell = False
    orch.start("a made-up server app")
    orch.run()
    assert states(orch) == {"D1": "unchecked", "D2": "unchecked"}


def test_the_estimate_line(tmp_path):
    orch, _ = build(tmp_path, FinishBrain())
    orch.start("a made-up counting game", require_approval=True)
    orch.plan()
    extras = orch.project.plan_doc()["estimate"]["extras"]
    e = next(x for x in extras if x["id"] == "finish")
    assert e["words"].startswith("checking it works and fixing what breaks: about $") and e["usd"] > 0
    orch2, _ = build(tmp_path / "b", FinishBrain(), finish={"max_usd": 0.0001})
    orch2.start("a made-up counting game", require_approval=True)
    orch2.plan()
    e2 = next(x for x in orch2.project.plan_doc()["estimate"]["extras"] if x["id"] == "finish")
    assert e2["usd"] <= 0.0001


def test_no_done_list_means_nothing_changes(tmp_path):
    class Bare(Orchestrator):
        def _kind_proof(self):
            return []  # no kind's checks: no done list at all

    from .test_stage_hooks import ONE
    from .test_harness import Brain

    cfg = parse_config(json.loads(json.dumps(RAW)))
    brain = Brain(plan=ONE)
    for name in ("a", "b"):
        cfg.register(name, ScriptedProvider(name, brain))
    cfg.register("img", ScriptedImages())
    events = []
    orch = Bare(cfg, tmp_path / "proj", on_event=lambda k, d: events.append((k, d)))
    orch.start("a made-up tool")
    assert orch.run() == "done"
    assert not [k for k, _ in events if k.startswith("finish_")]
    assert not finishstage.state_path(orch.project.root).exists()


@pytest.mark.parametrize("rel", ["../outside", "/etc", "game/../../x"])
def test_a_part_folder_never_leaves_the_project(tmp_path, rel):
    got = finishstage._inside(tmp_path, rel)
    assert got == tmp_path.resolve() or tmp_path.resolve() in got.parents


@pytest.mark.skipif(not shutil.which("npm"), reason="npm isn't installed here")
def test_an_app_that_starts_with_a_command_is_started_checked_and_stopped(tmp_path):
    import sys

    from roundtable.harness import livecmd

    from .test_appserver import SERVER

    files = {"package.json": json.dumps({"scripts": {"start": f'"{sys.executable}" server.py'}}),
             "server.py": SERVER, "page/index.html": FIXED}
    files["server.py"] = SERVER.replace("SimpleHTTPRequestHandler):",
                                        "SimpleHTTPRequestHandler):\n    def __init__(s, *a, **k): super().__init__(*a, directory='page', **k)")
    walker = Walker()
    orch, events = build(tmp_path, FinishBrain(files=files), walker=walker)
    orch.start("a made-up server app")
    assert orch.run() == "done"
    assert states(orch) == {"D1": "passed", "D2": "passed"}
    started = [d for k, d in events if k == "finish_app"]
    assert started and started[0]["ok"] and started[0]["command"] == "npm start"
    assert walker.calls[0][1] == started[0]["url"]  # walked on the app's own address
    assert not livecmd.running(orch.project.root)  # and stopped afterwards
    assert not appserver_port_open(started[0]["url"])


def appserver_port_open(url):
    from roundtable.harness import appserver

    return appserver.port_open(int(url.rsplit(":", 1)[1].strip("/")))


def test_an_imported_kinds_start_command_asks_first_once_per_project(tmp_path, monkeypatch):
    from roundtable.harness import gate as gatelib

    orch, _ = build(tmp_path, FinishBrain())
    orch.start("a made-up server app")
    asked = []

    def check(self, command):
        asked.append((command, self.mode()))
        return None  # the owner tapped Allow

    monkeypatch.setattr(gatelib.Gate, "check", check)
    ask = orch._finish_ask("project")
    assert orch._finish_ask("builtin") is None  # a built-in kind's command: the usual rules
    assert ask("python serve.py") is None and ask("python serve.py") is None
    assert asked == [("python serve.py", "all")]  # asked once, even with the project on "don't ask"
    assert finishstage.read_state(orch.project.root)["allowed"] == ["python serve.py"]
    monkeypatch.setattr(gatelib.Gate, "check", lambda self, c: "the owner said no")
    assert orch._finish_ask("own")("python other.py") == "the owner said no"
