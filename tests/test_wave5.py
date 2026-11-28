"""Wave 5 put together: every stage in the Orchestrator at once, and the hook-ups between them.

The end-to-end check: a made-up browser game with a planted bug (a Start button that does nothing) is planned
with a done list and two stages, built stage by stage, started and used by the finishing step, which finds the
bug and adds a fix; the fix passes and the run ends done with nobody asked. Scripted models, a fake walker
that really fetches the served page, no network.
"""

import json

from roundtable import asks as asklib, autopilot
from roundtable.harness import donelist, finishstage, plandoc, proof
from roundtable.harness import stages as stagelib
from roundtable.harness.config import parse_config
from roundtable.harness.orchestrator import Orchestrator
from roundtable.kinds import model as K
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider

from .test_finish import BROKEN, FIXED, Walker
from .test_harness import RAW, reply, tool_names

STAGES = [{"id": "M1", "title": "A page that opens", "shows": "the game's page with its Start button"},
          {"id": "M2", "title": "The game itself", "shows": "a game you can start"}]
PLAN = [{"id": "T1", "title": "the game page", "role": "coder", "description": "write index.html",
         "acceptance": "it opens", "depends_on": [], "stage": "M1", "files": ["index.html"]},
        {"id": "T2", "title": "the help text", "role": "coder", "description": "write help.txt",
         "acceptance": "it exists", "depends_on": [], "stage": "M2", "files": ["help.txt"]}]
DONE = [{"text": "You can press Start and see your score", "how": "journey", "must": True,
         "steps": [{"open": "/"}, {"click": "Start"}, {"expect_text": "Score"}]}]


class GameBrain:
    """The planner gives tasks, stages and a done list; T1 writes the planted bug, a fix (F…) mends it."""

    def __init__(self):
        self.order, self.fix_calls, self.plans = [], 0, 0

    def __call__(self, model, system, messages, tools):
        names = tool_names(tools)
        last = messages[-1]
        if "submit_plan" in names:
            if last["role"] == "tool":
                return reply("planned")
            self.plans += 1
            return reply(calls=[("submit_plan", {"summary": "A small browser game with a Start button.",
                                                 "tasks": PLAN, "stages": STAGES, "done_list": DONE})])
        if "submit_fixes" in names:
            if last["role"] == "tool":
                return reply("done")
            self.fix_calls += 1
            return reply(calls=[("submit_fixes", {"tasks": [{"title": "make Start show the score", "role": "coder",
                                                             "fixes": "D1", "files": ["index.html"],
                                                             "description": "Start does nothing: show the score"}]})])
        if "submit_review" in names:
            return reply("ok") if last["role"] == "tool" else reply(
                calls=[("submit_review", {"approved": True, "feedback": "fine"})])
        if "finish_task" in names:
            prompt = messages[0]["content"]
            tid = prompt.split("# Your task [", 1)[1].split("]", 1)[0]
            if last["role"] == "user":
                self.order.append(tid)
                files = {"index.html": FIXED} if tid.startswith("F") else (
                    {"index.html": BROKEN} if tid == "T1" else {"help.txt": "Press Start."})
                return reply(calls=[("write_file", {"path": p, "content": c}) for p, c in files.items()])
            return reply(calls=[("finish_task", {"summary": f"{tid} done"})])
        return reply("Final report: a small game.")


class Game(Orchestrator):
    def _attention(self, key, text, details=""):
        self.__dict__.setdefault("cards", []).append(key)
        super()._attention(key, text, details)


def build(tmp_path, brain, cls=Game):
    cfg = parse_config(json.loads(json.dumps(dict(RAW, limits={"max_cost_usd": 5, "max_attempts_per_task": 1}))))
    for name in ("a", "b"):
        cfg.register(name, ScriptedProvider(name, brain))
    cfg.register("img", ScriptedImages())
    events = []
    orch = cls(cfg, tmp_path / "proj", on_event=lambda k, d: events.append((k, d)))
    orch.ws.gate = None
    orch.journey_walker = Walker()
    orch.shot_renderer = lambda jobs: []
    return orch, events


def test_a_made_up_game_with_a_planted_bug_is_planned_built_found_fixed_and_done(tmp_path):
    brain = GameBrain()
    orch, events = build(tmp_path, brain)
    orch.start("a made-up browser game with a start button", require_approval=True)
    assert orch.run() == "awaiting_approval"
    doc = orch.project.plan_doc()
    # the plan: its done list (with the kind's own checks), its two stages, and the estimate's extra lines
    assert doc["done_list"][0]["text"] == "You can press Start and see your score"
    assert {i["by"] for i in doc["done_list"]} == {"planner", "kind"}
    assert [s["id"] for s in doc["stages"]] == ["M1", "M2"]
    extras = {e["id"]: e for e in doc["estimate"]["extras"]}
    assert {"unstick", "finish"} <= set(extras)
    assert extras["finish"]["words"].startswith("checking it works and fixing what breaks: about $")
    md = (orch.project.dir / "plan.md").read_text(encoding="utf-8")
    assert "## Done when" in md and "### Stage 1: A page that opens [M1]" in md
    orch.approve()
    assert orch.project.meta()["agreed"]["usd"] is not None
    assert orch.run() == "done"
    # built stage by stage, then the fix the finishing step asked for
    assert brain.order[:2] == ["T1", "T2"] and brain.order[2].startswith("F") and brain.fix_calls == 1
    fix = next(t for t in orch.project.tasks() if t.added_by == "finish")
    assert fix.fix_of == "D1" and fix.status == "done"
    d1 = next(i for i in donelist.read(orch.project.root)["items"] if i["id"] == "D1")
    assert d1["state"] == "passed"
    assert stagelib.read(orch.project.root)["boundaries"]["M1"]
    # nobody was asked, and the report counts what was checked
    assert "not_finished" not in getattr(orch, "cards", []) and "money" not in getattr(orch, "cards", [])
    assert not [d for k, d in events if k == "stage_error"]
    summary = donelist.summary(orch.project.root, True)
    assert summary["passed"] >= 1 and not summary["failed"]


def test_the_cards_and_answers_are_wired(tmp_path):
    assert {"not_finished", "stuck"} <= set(asklib.APPLY)
    from roundtable.harness import donestage, unstick

    assert asklib.APPLY["not_finished"].__name__ == "<lambda>" and callable(donestage.apply_not_finished)
    assert autopilot.decide(None, {"kind": "stuck", "options": []}, {}) == (None, unstick.AUTOPILOT_REASON)


def test_the_app_tab_and_the_phone_routes_are_wired():
    from roundtable.phone import PHONE_ROUTES
    from roundtable.ui import server

    assert {"doneapi", "stagesapi", "appapi"} <= set(server.FEATURE_APIS)
    assert {("GET", "/api/done"), ("GET", "/api/done/evidence"), ("GET", "/api/stages")} <= PHONE_ROUTES
    # the command is never started from the phone; only the running app's frame is seen (wave 9, view only)
    assert [r for r in PHONE_ROUTES if r[1].startswith("/api/app")] == [("GET", "/api/app/frame")]


def test_approving_before_there_is_a_plan_agrees_nothing(tmp_path):
    orch, _ = build(tmp_path, GameBrain())
    orch.start("a made-up game", require_approval=True)
    orch.approve()  # no plan yet: no estimate was seen
    assert "agreed" not in orch.project.meta()


def test_a_wrapped_site_is_still_a_website_and_native_android_is_its_own_kind():
    cat = K.load_all(None)
    goal = "Also ship the bakery site as an Android app (APK). One code base: it wraps the same index.html."
    assert K.propose(goal, cat)[0][0] == "website"
    assert K.propose("a native android app in kotlin", cat)[0][0] == "android-app"


def test_a_play_check_reads_the_done_list_and_can_make_a_kind_proven(tmp_path):
    root = tmp_path / "p"
    items = [{"id": "plays", "how": "play", "words": "Played for a minute"}]
    plan = proof.plan_for(items)
    assert plan[0]["checkable"]
    assert proof._play_passed(root, plan[0]) is None  # not played: not checked
    donelist.add_item(root, {"text": "Played for a minute", "how": "play", "kind_id": "plays"})
    donelist.record(root, "D1", True, "it worked")
    assert proof._play_passed(root, plan[0]) is True


def test_finishing_never_pays_to_fix_a_nice_to_have(tmp_path):
    class NiceOnly(Game):
        def _kind_proof(self):
            return []

        def _done_doc(self, doc, args):  # the planner's list: one nice-to-have that will fail
            donelist.add_item(self.project.root, {"id": "D1", "text": "It has a dark mode", "how": "file_exists",
                                                  "path": "dark.css", "must": False, "by": "planner"})

    brain = GameBrain()
    orch, events = build(tmp_path, brain, cls=NiceOnly)
    orch.start("a made-up tool")
    assert orch.run() == "done"
    assert next(i for i in donelist.read(orch.project.root)["items"] if i["id"] == "D1")["state"] == "failed"
    assert brain.fix_calls == 0 and not [t for t in orch.project.tasks() if t.added_by == "finish"]


def test_what_this_machine_cant_build_never_traps_the_project(tmp_path):
    """An EXE on a computer that isn't Windows: its ship item and the extra's own check are not checked, and
    neither is a must."""
    class Web(Game):
        def _kind_proof(self):
            return []

    orch, _ = build(tmp_path, GameBrain(), cls=Web)
    orch.start("a made-up tool")
    kind = K.resolve("web-app", ["exe"], catalog=K.load_all(None))
    orch._kind = lambda: kind
    donelist.add_item(orch.project.root, {"text": "The EXE was built", "how": "file_exists", "path": "dist/*.exe",
                                          "by": "kind"})
    assert orch._ship_step(orch.project.tasks()) is None
    items = {i["id"]: i for i in donelist.read(orch.project.root)["items"]}
    assert items["ship:exe"]["state"] == items["D1"]["state"] == "unchecked"
    assert not items["ship:exe"]["must"] and not items["D1"]["must"]
    assert donelist.verdict(orch.project.root)["done"]
    # and the finishing step leaves the extra's file check to the ship step
    assert "dist/*.exe" in orch._finish_shipped()


def test_try_fixing_again_clears_the_finishing_rounds(tmp_path):
    root = tmp_path / "p"
    finishstage._save_goal(root, 0, {**finishstage.goal_state(root, 0), "rounds": 2, "fix_tasks": 3})
    finishstage.clear_rounds(root)
    assert finishstage.goal_state(root, 0)["rounds"] == 0


def test_play_and_journey_pictures_are_tidied_like_the_app_pictures(tmp_path):
    import os

    from roundtable import retention

    goal = tmp_path / ".harness" / "play" / "goal-1"
    for n in range(4):
        d = goal / f"D{n}"
        d.mkdir(parents=True)
        (d / "turn-01.png").write_bytes(b"png")
        os.utime(d / "turn-01.png", (1000 + n, 1000 + n))
        os.utime(d, (1000 + n, 1000 + n))  # the folder's own date counts too (Windows times are coarse)
    sweep = retention.Sweep({**retention.settings(), "shots_keep": 2, "min_age_minutes": 0})
    sweep.goal_dirs(tmp_path / ".harness" / "play")
    assert sorted(p.name for p in goal.iterdir()) == ["D2", "D3"]  # the newest two kept


def test_the_plan_markdown_keeps_one_task_per_line_with_parts():
    class T:
        def __init__(self, i, part):
            self.id, self.status, self.title, self.role, self.part, self.stage = i, "pending", f"task {i}", "coder", part, "M1"

    doc = {"goal_index": 0, "stages": [{"id": "M1", "title": "Slice"}], "parts": [{"id": "game", "name": "Game"}]}
    md = plandoc.render_markdown({**doc, "goal": "g", "version": 1, "summary": "s"}, [T("T1", "game")])
    assert "- [T1] pending task T1 · Game (coder)" in md
