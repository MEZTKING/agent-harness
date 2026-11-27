"""Stages and parts (harness/stages.py): a working slice first, several parts in their own folders, who changes
which file. Made-up projects in tmp_path, scripted models, no network."""

import json
import subprocess
import threading

import pytest

from roundtable.harness import stages as st
from roundtable.harness.config import parse_config
from roundtable.harness.orchestrator import Orchestrator, Task
from roundtable.harness.stages import StagesStage
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider

from .test_harness import RAW, reply, task_line
from .test_parallel import raw as parallel_raw
from .test_parallel import tid_of


class O(Orchestrator):
    """The full Orchestrator: the after-task hook and the stop at a boundary are hooked up in the run."""


STAGES = [{"id": "M1", "title": "A first slice", "shows": "a page that opens"},
          {"id": "M2", "title": "The middle", "shows": "the buttons work"},
          {"id": "M3", "title": "Polish", "shows": "it looks finished"}]


def t(tid, stage="", files=None, deps=(), part="", **kw):
    d = {"id": tid, "title": f"task {tid}", "role": "coder", "description": f"write {tid}", "acceptance": "exists",
         "depends_on": list(deps), "files": files if files is not None else [f"{tid.lower()}.txt"]}
    if stage:
        d["stage"] = stage
    if part:
        d["part"] = part
    d.update(kw)
    return d


class StageBrain:
    """Plans with stages and parts; a revision gives back the tasks not done yet. Workers write their task's
    files (``writes`` overrides); ``reject`` sends a task back once."""

    def __init__(self, plan, stages=STAGES, parts=None, writes=None, reject=(), revised=None):
        self.plan, self.stages, self.parts = plan, stages, parts
        self.writes = writes or {}
        self.reject = set(reject)
        self.rejected = set()
        self.revised = revised
        self.plans = 0
        self.prompts = {}
        self.lock = threading.Lock()
        self.active = set()
        self.together = []

    def submission(self, prompt):
        tasks = self.plan
        if self.plans > 1:  # a revision: the tasks not done yet
            marker = "Already done or in progress, don't repeat (you may depend on them): "
            done = set(prompt.split(marker, 1)[1].split(". ", 1)[0].split(", ")) if marker in prompt else set()
            tasks = [dict(x) for x in (self.revised or self.plan) if x["id"] not in done]
        args = {"tasks": tasks}
        if self.stages is not None:
            args["stages"] = self.stages
        if self.parts is not None:
            args["parts"] = self.parts
        return args

    def __call__(self, model, system, messages, tools):
        names = {x.name for x in tools}
        last = messages[-1]
        tid = tid_of(messages)
        if "submit_plan" in names:
            if last["role"] == "tool":
                return reply("planned")
            self.plans += 1
            return reply(calls=[("submit_plan", self.submission(messages[0]["content"]))])
        if "submit_review" in names:
            if last["role"] == "tool":
                return reply("ok")
            with self.lock:
                self.active.discard(tid)
            if tid in self.reject and tid not in self.rejected:
                self.rejected.add(tid)
                return reply(calls=[("submit_review", {"approved": False, "feedback": "the page is blank",
                                                         "breaks": task_line(messages)})])
            return reply(calls=[("submit_review", {"approved": True, "feedback": "fine"})])
        if "finish_task" in names:
            if last["role"] == "user":
                with self.lock:
                    self.prompts[tid] = messages[0]["content"]
                    if self.active:
                        self.together.append((tid, sorted(self.active)))
                    self.active.add(tid)
                task = next((x for x in self.plan + (self.revised or []) if x["id"] == tid), None)
                files = self.writes.get(tid) or [f for f in (task or {}).get("files") or [f"{tid.lower()}.txt"]
                                                 if "*" not in f]
                calls = [("write_file", {"path": f, "content": f"{tid} {n}\n"}) for n, f in enumerate(files)]
                return reply(calls=calls[:1]) if len(calls) == 1 else reply(calls=calls)
            return reply(calls=[("finish_task", {"summary": f"{tid} done"})])
        return reply("Final report: all done.")


def build(tmp_path, brain, raw=RAW, cls=O, name="proj"):
    cfg = parse_config(json.loads(json.dumps(raw)))
    for p in ("a", "b"):
        cfg.register(p, ScriptedProvider(p, brain))
    cfg.register("img", ScriptedImages())
    events = []
    orch = cls(cfg, tmp_path / name, on_event=lambda k, d: events.append((k, d)))
    return orch, events


def starts(events):
    return [d["task"] for k, d in events if k == "task_start"]


def named(events, kind):
    return [d for k, d in events if k == kind]


# -- pure parts -------------------------------------------------------------------------------------------------
def test_stages_and_parts_are_tidied():
    s = st.clean_stages([{"id": "M1", "title": "slice", "shows": "it opens"}, {"id": "M1", "title": "again"},
                         "just words", 7, {"title": ""}, {"id": "M9", "title": "too many"}])
    assert [x["id"] for x in s] == ["M1", "M2", "M3", "M4"] and s[2]["title"] == "just words"
    assert st.clean_parts([{"id": "main", "name": "It", "folder": "."}]) == []  # one part at the top: no parts
    parts = st.clean_parts([{"id": "game", "name": "Game", "folder": "./game/"},
                            {"id": "site", "name": "Web page", "folder": "../outside", "kind": "website"}])
    assert parts == [{"id": "game", "name": "Game", "folder": "game"},
                     {"id": "site", "name": "Web page", "folder": ".", "kind": "website"}]
    assert st.clean_folder("C:/Windows") == "." and st.clean_folder("/etc") == "."


def test_overlap_rules():
    assert st.patterns_overlap("game.js", "game.js")
    assert st.patterns_overlap("src/*.js", "src/game.js")
    assert st.patterns_overlap("src/", "src/game.js") and st.patterns_overlap("src", "src/a/b.js")
    assert not st.patterns_overlap("src/game.js", "src/game.css")
    tasks = [Task.from_dict(x) for x in (t("T4", "M1", ["game.js"]), t("T7", "M1", ["game.js", "b.js"]),
                                         t("T8", "M1", ["game.js"], deps=["T4"]), t("T9", "M2", ["game.js"]))]
    warn = st.overlaps(tasks, STAGES)
    texts = [w["text"] for w in warn]
    assert "T4 and T7 both change game.js: they'll run one after the other" in texts
    assert not any("T4 and T8" in x for x in texts)  # already in order
    assert not any("T9" in x for x in texts)  # another stage
    assert all(w["by"] == "stages" for w in warn)


def test_a_sloppy_plan_is_repaired_not_refused():
    a = Task.from_dict(t("A", "M7"))
    b = Task.from_dict(t("B", "", added_by="unstick"))
    assert st.stage_of(a, STAGES) == "M3"  # unknown: the last stage
    assert st.stage_of(b, STAGES) == ""  # added along the way: never held
    assert st.stage_of(a, []) == ""
    parts = [{"id": "game", "folder": "game"}, {"id": "site", "folder": "site"}]
    g = Task.from_dict(t("G", "M1", ["main.js", "game/x.js", "site/shared.css"], part="game"))
    assert st.files_of(g, parts) == ["game/main.js", "game/x.js", "site/shared.css"]
    assert st.outside_plan(["game/*.js"], ["game/a.js", "README.md", ".harness/x.json"]) == ["README.md"]


def test_the_markdown_has_a_heading_per_stage_and_is_as_before_without():
    tasks = [Task.from_dict(t("A", "M1")), Task.from_dict(t("B", "M2", part="game")),
             Task.from_dict(t("Z", "", added_by="finish"))]
    plain = st.markdown({}, tasks[:1])
    assert plain == ["## Tasks", "- [A] pending task A (coder)", ""]
    doc = {"stages": STAGES, "parts": [{"id": "game", "name": "Game", "folder": "game"}], "goal_index": 0}
    md = "\n".join(st.markdown(doc, tasks))
    assert "### Stage 1: A first slice [M1]" in md and "At the end you can try: a page that opens" in md
    assert "- [B] pending task B · Game (coder)" in md and "### Added along the way" in md
    assert "Parts: Game (in game/)" in md


# -- one task at a time ------------------------------------------------------------------------------------------
PLAN3 = [t("C1", "M3"), t("B1", "M2"), t("A1", "M1"), t("B2", "M2")]


def test_a_three_stage_plan_runs_stage_by_stage(tmp_path):
    orch, events = build(tmp_path, StageBrain(PLAN3))
    orch.start("a made-up page")
    assert orch.run() == "done"
    order = starts(events)
    assert order[0] == "A1" and set(order[1:3]) == {"B1", "B2"} and order[3] == "C1"
    assert [d["stage"] for d in named(events, "stage_done")] == ["M1", "M2"]
    rec = st.read(orch.project.root)
    assert set(rec["boundaries"]) == {"M1", "M2"} and not any(b["replanned"] for b in rec["boundaries"].values())
    journal = [d for k, d in events if k == "stage_done"]
    assert journal[0]["shows"] == "a page that opens"
    doc = orch.project.plan_doc()
    assert [s["id"] for s in doc["stages"]] == ["M1", "M2", "M3"]
    assert "plan_revised" not in [k for k, _ in events]  # no lessons: no re-plan


def test_a_plan_with_no_stages_runs_exactly_as_before(tmp_path):
    plan = [t("C1", files=[]), t("B1", files=[]), t("A1", files=[])]
    orch, events = build(tmp_path, StageBrain(plan, stages=None))
    orch.start("a made-up page")
    assert orch.run() == "done"
    assert starts(events) == ["C1", "B1", "A1"]
    doc = orch.project.plan_doc()
    assert "stages" not in doc and "parts" not in doc and "warnings" not in doc
    assert st.read(orch.project.root)["boundaries"] == {}
    assert not named(events, "stage_error")


def test_the_boundary_runs_once_and_survives_a_restart(tmp_path):
    brain = StageBrain(PLAN3)
    orch, events = build(tmp_path, brain)
    orch.start("a made-up page")
    assert orch.run(max_tasks=1) == "paused"
    assert starts(events) == ["A1"] and [d["stage"] for d in named(events, "stage_done")] == ["M1"]
    again, events2 = build(tmp_path, brain)  # a new run of the app
    assert again.run() == "done"
    assert [d["stage"] for d in named(events2, "stage_done")] == ["M2"]  # M1's step never ran twice
    notes = (again.project.dir / "events.jsonl").read_text(encoding="utf-8").count('"event": "stage_done"')
    assert notes == 2


def test_a_stage_with_lessons_gets_one_replan_that_keeps_done_tasks(tmp_path):
    revised = [t("B1", "M2", description="write B1, keeping the page from A1"), t("B2", "M2"), t("C1", "M3")]
    brain = StageBrain(PLAN3, reject=["A1"], revised=revised)
    orch, events = build(tmp_path, brain)
    orch.start("a made-up page")
    assert orch.run() == "done"
    replans = named(events, "stage_replanned")
    assert [r["stage"] for r in replans] == ["M1"]  # M2 had no lessons
    doc = orch.project.plan_doc()
    assert [h.get("by") for h in doc["history"]].count("harness") == 1
    assert "A1 (task A1) needed 2 goes: the page is blank" in next(h["change"] for h in doc["history"] if h.get("by") == "harness")
    tasks = {x.id: x for x in orch.project.tasks()}
    assert tasks["A1"].status == "done" and len(tasks["A1"].attempts) == 2
    assert tasks["B1"].description == "write B1, keeping the page from A1" and tasks["B1"].status == "done"
    assert brain.plans == 2
    assert st.read(orch.project.root)["boundaries"]["M1"]["replanned"] is True
    assert [s["id"] for s in doc["stages"]] == ["M1", "M2", "M3"]


def test_a_replan_that_fails_is_written_down_and_the_run_carries_on(tmp_path):
    class Broken(O):
        def revise_plan(self, *a, **k):
            raise RuntimeError("the planner is away")

    orch, events = build(tmp_path, StageBrain(PLAN3, reject=["A1"]), cls=Broken)
    orch.start("a made-up page")
    assert orch.run() == "done"
    assert any(d["stage"] == "_stage_boundary" for d in named(events, "stage_error"))
    assert "the planner is away" in st.read(orch.project.root)["boundaries"]["M1"]["replan_error"]


def test_stage_stop_each_waits_for_the_owner_once(tmp_path):
    orch, events = build(tmp_path, StageBrain(PLAN3))
    orch.start("a made-up page")
    (orch.project.dir).mkdir(parents=True, exist_ok=True)
    (orch.project.dir / "project.yaml").write_text("stage_stop: each\n", encoding="utf-8")
    assert orch._stage_stop_setting() == "each"
    assert orch.run() == "paused"  # the run's hook-up hands out "paused" once
    assert starts(events) == ["A1"]
    assert orch._stage_stop() is None
    assert orch.project.meta()["pause"] == "stage"
    assert st.read(orch.project.root)["boundaries"]["M1"]["stopped"] is True
    again, events2 = build(tmp_path, StageBrain(PLAN3))
    again.run()
    assert starts(events2)[:2] in (["B1", "B2"], ["B2", "B1"])  # M1's stop is passed; it stops after M2
    assert st.read(again.project.root)["boundaries"]["M1"]["resumed"]


def test_the_stop_hook_gives_paused_once(tmp_path):
    orch, _ = build(tmp_path, StageBrain(PLAN3))
    orch.start("a made-up page")
    orch._stages_stop = "paused"
    assert orch._stage_stop() == "paused" and orch.project.meta()["pause"] == "stage"
    assert orch._stage_stop() is None


def test_files_changed_outside_the_plan_are_noted_never_failed(tmp_path):
    plan = [t("A1", "M1", ["page.html"]), t("B1", "M2", ["b1.txt"])]
    orch, events = build(tmp_path, StageBrain(plan, writes={"A1": ["page.html", "notes.md"]}))
    orch.start("a made-up page")
    assert orch.run() == "done"
    strays = named(events, "files_strayed")
    assert [(d["task"], d["files"]) for d in strays] == [("A1", ["notes.md"])]
    assert st.read(orch.project.root)["strayed"]["A1"]["files"] == ["notes.md"]
    assert named(events, "stage_replanned")  # a lesson: files outside the plan


def test_an_unknown_stage_is_repaired_to_the_last(tmp_path):
    plan = [t("A1", "M1"), t("X1", "M9"), t("B1", "M2")]
    orch, _ = build(tmp_path, StageBrain(plan, stages=STAGES[:2]))
    orch.start("a made-up page")
    orch.plan()
    tasks = {x.id: x for x in orch.project.tasks()}
    assert tasks["X1"].stage == "M2"
    md = st.markdown(orch.project.plan_doc(), orch.project.tasks())
    assert md.index("- [X1] pending task X1 (coder)") > md.index("### Stage 2: The middle [M2]")


def test_the_worker_hears_its_stage_part_and_files(tmp_path):
    parts = [{"id": "game", "name": "Game", "folder": "game/"}, {"id": "site", "name": "Web page", "folder": "site"}]
    plan = [t("G1", "M1", ["index.html", "main.js"], part="game"), t("S1", "M1", ["index.html"], part="site"),
            t("G2", "M2", ["main.js"], part="game", deps=["G1"])]
    brain = StageBrain(plan, stages=STAGES[:2], parts=parts,
                       writes={"G1": ["game/index.html", "game/main.js"], "S1": ["site/index.html"],
                               "G2": ["game/main.js"]})
    orch, events = build(tmp_path, brain)
    orch.start("a made-up game and its web page")
    assert orch.run() == "done"
    tasks = {x.id: x for x in orch.project.tasks()}
    assert tasks["G1"].files == ["game/index.html", "game/main.js"] and tasks["S1"].files == ["site/index.html"]
    p = brain.prompts["G1"]
    assert "This task is in stage M1 of 2, “A first slice”" in p and "working slice" in p
    assert "Part: Game, in the folder game/" in p and "Your files: game/index.html, game/main.js" in p
    assert (orch.project.root / "game" / "main.js").is_file() and (orch.project.root / "site" / "index.html").is_file()
    assert not named(events, "files_strayed")
    doc = orch.project.plan_doc()
    assert [x["folder"] for x in doc["parts"]] == ["game", "site"]
    assert "warnings" not in doc  # game/index.html and site/index.html are different files


def test_the_planner_is_asked_for_stages_parts_and_files(tmp_path):
    seen = []
    brain = StageBrain(PLAN3)

    def spy(model, system, messages, tools):
        seen.append((messages[0]["content"], tools))
        return brain(model, system, messages, tools)

    orch, _ = build(tmp_path, spy)
    orch.start("a made-up page")
    orch.plan()
    prompt, tools = next((p, ts) for p, ts in seen if any(x.name == "submit_plan" for x in ts))
    assert "# Stages, parts and files" in prompt and "working slice" in prompt
    schema = next(x for x in tools if x.name == "submit_plan").parameters
    assert {"stages", "parts"} <= set(schema["properties"])
    task = schema["properties"]["tasks"]["items"]["properties"]
    assert task["size"]["enum"] == ["small", "medium", "large"] and "files" in task


# -- warnings -----------------------------------------------------------------------------------------------------
def test_warnings_are_made_and_carried_across_a_revision(tmp_path):
    plan = [t("T4", "M1", ["game.js"]), t("T7", "M1", ["game.js"]), t("T8", "M2", ["big/*"], size="large")]
    orch, _ = build(tmp_path, StageBrain(plan))
    orch.start("a made-up game", require_approval=True)
    orch.plan()
    doc = orch.project.plan_doc()
    texts = [w["text"] for w in doc["warnings"]]
    assert "T4 and T7 both change game.js: they'll run one after the other" in texts
    assert any(x.startswith("T8 is planned as a large task") for x in texts)
    doc["warnings"].append({"id": "other", "by": "someone-else", "text": "kept"})
    orch.project.save_plan_doc(doc)
    orch.revise_plan("make it smaller")
    doc = orch.project.plan_doc()
    texts = [w["text"] for w in doc["warnings"]]
    assert "T4 and T7 both change game.js: they'll run one after the other" in texts and "kept" in texts
    assert texts.count("T4 and T7 both change game.js: they'll run one after the other") == 1
    assert doc["version"] == 2 and [s["id"] for s in doc["stages"]] == ["M1", "M2", "M3"]


# -- several at once ----------------------------------------------------------------------------------------------
def test_the_parallel_loop_runs_stage_by_stage(tmp_path):
    brain = StageBrain(PLAN3)
    orch, events = build(tmp_path, brain, raw=parallel_raw(3))
    orch.start("a made-up page")
    assert orch.run() == "done"
    rows = [json.loads(x) for x in (orch.project.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    seq = [(r["event"], r.get("task")) for r in rows if r["event"] in ("task_start", "merged", "lane_start")]
    started = [x[1] for x in seq if x[0] == "task_start"] or [x[1] for x in seq if x[0] == "lane_start"]
    assert started[0] == "A1" and started[-1] == "C1"
    merged = [x[1] for x in seq if x[0] == "merged"]
    assert merged.index("A1") < merged.index("B1") < merged.index("C1")
    assert [d["stage"] for d in named(events, "stage_done")] == ["M1", "M2"]
    assert not [x for x in brain.together if x[0] in ("B1", "B2") and "A1" in x[1]]
    assert not [x for x in brain.together if x[0] == "C1"]


def test_two_overlapping_ready_tasks_never_run_together(tmp_path):
    plan = [t("T4", "M1", ["game.js"]), t("T7", "M1", ["game.js"]), t("T9", "M1", ["other.js"])]
    brain = StageBrain(plan, stages=STAGES[:1], writes={"T4": ["game.js"], "T7": ["game.js"]})
    orch, events = build(tmp_path, brain, raw=parallel_raw(3))
    orch.start("a made-up game")
    assert orch.run() == "done"
    assert not [x for x in brain.together if {x[0], *x[1]} >= {"T4", "T7"}]
    assert any(set(d["tasks"]) == {"T7"} for d in named(events, "files_wait"))
    assert {x.status for x in orch.project.tasks()} == {"done"}


# -- the API ------------------------------------------------------------------------------------------------------
def test_the_api_gives_the_stages(tmp_path, monkeypatch):
    import yaml

    from roundtable.ui import server
    from roundtable.ui.server import UIApp

    from .test_hub import RAW as HUB_RAW

    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "stagesapi"))
    h = json.loads(json.dumps(HUB_RAW))
    h["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
    (tmp_path / "hub.yaml").write_text(yaml.safe_dump(h), encoding="utf-8")
    orch, _ = build(tmp_path, StageBrain(PLAN3))
    cfg = orch.cfg
    cfg.lab_dir = tmp_path / "lab"
    orch.start("a made-up page")
    orch.run(max_tasks=1)
    orch._register_with_lab()
    app = UIApp(str(tmp_path / "hub.yaml"), "missing.yaml", agent="backend")
    app.cfg = lambda: cfg
    got = app.dispatch("GET", "/api/stages", {"path": [str(orch.project.root)]}, {})
    assert [(s["id"], s["state"], s["done"], s["total"]) for s in got["stages"]] == [
        ("M1", "done", 1, 1), ("M2", "now", 0, 2), ("M3", "waiting", 0, 1)]
    assert got["stages"][0]["ready_at"] and got["words"] == "Stage 2 of 3: The middle – then you can try the buttons work."
    assert got["files"]["A1"] == ["a1.txt"] and got["parts"] == [] and got["warnings"] == []
    assert "/api/stages" in app.dispatch("GET", "/api/features", {}, {})["routes"]


def test_the_desktop_module_parses_and_groups(tmp_path):
    import shutil

    node = shutil.which("node")
    if not node:
        pytest.skip("no node here")
    from importlib import resources

    src = resources.files("roundtable").joinpath("ui/static/stages.js").read_text(encoding="utf-8")
    body = src.split("\n", 1)[1] if src.startswith("//") else src
    body = "\n".join(ln for ln in body.splitlines() if not ln.startswith("import "))
    stub = ("const h = () => ({}); const get = async () => ({}); const q = () => ''; const has = async () => false;"
            "const fill = () => {};\n")
    test = ("\nconst tasks = [{id:'C1',stage:'M3'},{id:'A1',stage:'M1'},{id:'Z',stage:''},{id:'B1',stage:'M2'}];\n"
            "const g = groupByStage(tasks, [{id:'M1',title:'One'},{id:'M2',title:'Two'},{id:'M3',title:'Three'}]);\n"
            "console.log(JSON.stringify(g.map(x => [x.id, x.tasks.map(t => t.id)])));\n"
            "console.log(JSON.stringify(groupByStage(tasks, []).map(x => [x.id, x.tasks.length])));\n")
    f = tmp_path / "s.mjs"
    f.write_text(stub + body + test, encoding="utf-8")
    out = subprocess.run([node, str(f)], capture_output=True, text=True, timeout=60, check=False)
    assert out.returncode == 0, out.stderr
    lines = out.stdout.strip().splitlines()
    assert json.loads(lines[0]) == [["M1", ["A1"]], ["M2", ["B1"]], ["M3", ["C1"]], ["", ["Z"]]]
    assert json.loads(lines[1]) == [["", 4]]
