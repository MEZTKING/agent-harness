import json
import subprocess

import pytest

from roundtable.harness import look as looklib
from roundtable.harness import plandoc
from roundtable.harness.orchestrator import HarnessError
from roundtable.providers.scripted import reply

from .test_harness import RAW, tool_names
from .test_plan import DOC, PlanBrain, make

FONTS = ["Fraunces", "Space Grotesk", "DM Serif Display"]
ACCENTS = [("#8a3b12", "#e8a36b"), ("#1f5f4a", "#6fd1a8"), ("#5b2a86", "#c9a2f0")]
NAMES = ["Old Record Shop", "Night Bus Neon", "Paper Lantern Calm"]


def direction(i, **over):
    light_accent, dark_accent = ACCENTS[i]
    d = {
        "id": "ABC"[i], "name": NAMES[i], "mood": "Warm and a little dusty, like a shop you return to.",
        "palette": {
            "light": {"background": "#fbf7f0", "surface": "#ffffff", "text": "#1d1a16", "muted": "#6b645a",
                      "accent": light_accent, "accent_text": "#ffffff", "extra": [{"name": "Vinyl", "hex": "#2b2b2b"}]},
            "dark": {"background": "#15130f", "surface": "#221f1a", "text": "#f3ede2", "muted": "#a39b8e",
                     "accent": dark_accent, "accent_text": "#15130f"}},
        "fonts": {"display": {"family": FONTS[i], "fallbacks": "Georgia, serif", "google": True, "weights": [400, 700]},
                  "body": {"family": "Work Sans", "fallbacks": "system-ui, sans-serif", "google": True}},
        "shapes": {"radius": "4px", "borders": "hairline 1px ink", "density": "comfortable"},
        "motion": "Slow fades, nothing bounces.",
        "signature": "Track numbers set like a record sleeve's side A and side B.",
        "never": ["never use pure black", "never round the buttons fully"],
        "mockup_html": f"<!doctype html><html><body style='background:#fbf7f0'><h1>Side {'ABC'[i]}</h1></body></html>",
    }
    d.update(over)
    return d


class LookBrain(PlanBrain):
    """A planner that says the project has screens, and a designer whose first answers get sent back."""

    def __init__(self, bad_first=True, has_ui=True):
        super().__init__()
        self.bad_first = bad_first
        self.has_ui = has_ui
        self.design_prompts, self.design_tool_results, self.design_calls = [], [], 0

    def __call__(self, model, system, messages, tools):
        names = tool_names(tools)
        if "submit_plan" in names and messages[-1]["role"] == "user":
            resp = super().__call__(model, system, messages, tools)
            resp.tool_calls[0].arguments["has_ui"] = self.has_ui
            return resp
        if "submit_looks" in names:
            return self.design(messages)
        return super().__call__(model, system, messages, tools)

    def design(self, messages):
        last = messages[-1]
        if last["role"] == "tool":
            self.design_tool_results.append(str(last.get("content")))
            if "accepted" in str(last.get("content")):
                return reply("done")
        else:
            self.design_prompts.append(messages[0]["content"])
        self.design_calls += 1
        prompt = messages[0]["content"]
        if "Send it back as one direction" in prompt:  # the owner's note on the chosen look
            return reply(calls=[("submit_looks", {"directions": [direction(1, id="B", name="Night Bus Ember",
                                                                            signature="warmer neon")]})])
        looks = [direction(i) for i in range(3)]
        tries = sum(1 for r in self.design_tool_results if "rejected" in r)
        if self.bad_first and tries == 0:
            looks[1]["palette"]["light"]["accent"] = "blue"
        elif self.bad_first and tries == 1:
            looks[2]["palette"]["light"]["text"] = "#cccccc"  # pale grey text on cream: unreadable
        return reply(calls=[("submit_looks", {"directions": looks})])


@pytest.fixture(autouse=True)
def no_pictures(monkeypatch):
    monkeypatch.setattr(looklib, "renderer", lambda: None)


def planned(tmp_path, brain=None, raw=None, **kw):
    brain = brain or LookBrain(**kw)
    orch, a, *_ = make(tmp_path, brain=brain, **({"raw": raw} if raw else {}))
    orch.start("a music player", require_approval=True)
    orch.run()
    return orch, a, brain


def test_contrast():
    assert round(looklib.contrast("#000000", "#ffffff")) == 21
    assert looklib.contrast("#777", "#777") == 1


def test_first_plan_of_an_app_gets_looks_and_bad_ones_are_sent_back(tmp_path):
    orch, _, brain = planned(tmp_path)
    look = orch.project.plan_doc()["look"]
    assert [d["id"] for d in look["directions"]] == ["A", "B", "C"] and look["chosen"] is None
    assert "use a hex colour" in brain.design_tool_results[0]
    assert "contrast" in brain.design_tool_results[1] and "4.5:1" in brain.design_tool_results[1]
    assert brain.design_calls == 3  # the third one was accepted and ended the call
    assert (orch.project.dir / "look" / "B.html").read_text().startswith("<!doctype html>")
    assert "mockup_html" not in look["directions"][0] and look["directions"][0]["mockup"] == ".harness/look/A.html"
    assert look["pictures"] == {} and "skipped" in look["render_note"]
    doc = orch.project.plan_doc()
    assert plandoc.open_items(doc)["choices"] == 2  # the logo choice and the look
    assert "1 choice, a look to choose" in plandoc.summary_line(doc)
    assert doc["has_ui"] is True
    assert "music player" in brain.design_prompts[0] or "bakery" in brain.design_prompts[0]


def test_no_looks_without_screens_or_when_off(tmp_path):
    orch, *_ = planned(tmp_path / "a", has_ui=False)
    assert "look" not in orch.project.plan_doc()
    raw = json.loads(json.dumps(RAW))
    raw["look_stage"] = False  # how YAML reads `look_stage: off`
    orch, *_ = planned(tmp_path / "b", raw=raw)
    assert orch.cfg.look_stage == "off" and "look" not in orch.project.plan_doc()


def test_validation_rules():
    good = [direction(i) for i in range(3)]
    assert len(looklib.validate_looks(good, 3)) == 3
    cases = [
        (lambda x: x[1].update(name=x[0]["name"]), "same name"),
        (lambda x: x[1]["fonts"]["display"].update(family="Fraunces"), "same display font"),
        (lambda x: x[2]["palette"]["light"].update(accent="#8b3c14"), "nearly the same accent"),
        (lambda x: x[0]["palette"]["dark"].update(accent_text="#e0a070"), "contrast"),
        (lambda x: x[0]["shapes"].update(radius="soft"), "CSS length"),
        (lambda x: x[0].update(mockup_html="<html><script src='https://x.test/a.js'></script></html>"), "scripts"),
        (lambda x: x[0].pop("signature"), "'signature' is missing"),
    ]
    for change, message in cases:
        looks = json.loads(json.dumps(good))
        change(looks)
        with pytest.raises(ValueError, match=message):
            looklib.validate_looks(looks, 3)
    with pytest.raises(ValueError, match="exactly 3"):
        looklib.validate_looks(good[:2], 3)


def test_looks_used_in_other_projects_are_in_the_designer_prompt(tmp_path):
    from roundtable.improve.lab import Lab

    other = tmp_path / "other"
    (other / ".harness").mkdir(parents=True)
    (other / ".harness" / "project.json").write_text("{}")
    (other / ".harness" / "plan.json").write_text(json.dumps({"look": {
        "chosen": "A", "directions": [looklib.validate_looks([direction(0)], 1)[0]]}}))
    brain = LookBrain(bad_first=False, has_ui=False)
    orch, *_ = make(tmp_path, brain=brain)
    orch.cfg.lab_dir = tmp_path / "lab"
    Lab(orch.cfg.lab_dir).register_project(other)
    orch.start("a music player", require_approval=True)
    orch.run()
    orch.look("like an old record shop")
    prompt = brain.design_prompts[-1]
    assert "Looks already used in the owner's other projects" in prompt
    assert "other: Old Record Shop (accents #8a3b12, #e8a36b; display font Fraunces)" in prompt
    assert "like an old record shop" in prompt and "unless the owner's starting point asks" in prompt
    assert orch.project.plan_doc()["look"]["brief"] == "like an old record shop"


def test_choosing_a_look_writes_the_design_file_and_a_restyle_task(tmp_path):
    orch, a, brain = planned(tmp_path, bad_first=False)
    with pytest.raises(HarnessError):
        orch.plan_update("look", id="Z")
    r = orch.plan_update("look", id="b")
    doc = orch.project.plan_doc()
    assert doc["look"]["chosen"] == "B" and r["open"]["choices"] == 1
    assert any(p["key"] == "look" and "Night Bus Neon" in p["text"] for p in doc["pending"])
    # screens were already built by a finished task: the look must restyle them
    tasks = orch.project.tasks()
    tasks[0].status = "done"
    orch.project.save_tasks(tasks)
    (orch.project.root / "index.html").write_text("<style>body { color: #123456; font-family: Arial; }</style>\n")
    calls = brain.design_calls
    orch.revise_plan()
    assert brain.design_calls == calls  # no note: no designer call
    root = orch.project.root
    design = (root / "design" / "DESIGN.md").read_text()
    assert design.startswith("# The look: Night Bus Neon") and "Use only these tokens" in design
    assert "| Accent | `--color-accent` | #1f5f4a | #6fd1a8 |" in design and "never use pure black" in design
    css = (root / "design" / "tokens.css").read_text()
    assert "@media (prefers-color-scheme: dark)" in css and "--color-accent: #6fd1a8;" in css
    assert "family=Space+Grotesk:wght@400;700&family=Work+Sans&display=swap" in css and "--color-vinyl" in css
    log = subprocess.run(["git", "log", "--oneline"], cwd=root, capture_output=True, text=True).stdout
    assert "Design: the look 'Night Bus Neon'" in log
    restyle = [t for t in orch.project.tasks() if t.title == "Restyle the app in the chosen look"]
    assert len(restyle) == 1 and restyle[0].role == "coder" and restyle[0].depends_on == [] and restyle[0].status == "pending"
    doc = orch.project.plan_doc()
    assert doc["look"]["applied"] == "B" and doc["pending"] == []
    assert "Look (owner's choice): Night Bus Neon" in plandoc.context_text(doc)

    # every task and review is told the design file and what the check found
    prompt = orch._worker_prompt(restyle[0], orch.project.tasks(), [])
    assert "# The design file (design/DESIGN.md)" in prompt and "Night Bus Neon" in prompt
    orch._review(restyle[0], "restyled")
    review_prompt = a.calls[-1]["messages"][0]["content"]
    assert "# The design file" in review_prompt and "index.html:1 (colour)" in review_prompt
    assert "index.html:1 (font)" in review_prompt and "Reject the task" in review_prompt


def test_a_note_with_the_choice_asks_the_designer_once(tmp_path):
    orch, _, brain = planned(tmp_path, bad_first=False)
    orch.plan_update("look", id="B", note="the second, but warmer")
    calls = brain.design_calls
    r = orch.apply_look()
    assert brain.design_calls == calls + 1 and "the second, but warmer" in brain.design_prompts[-1]
    assert r["name"] == "Night Bus Ember" and r["task"] is None  # nothing built yet: no restyle task
    design = (orch.project.root / "design" / "DESIGN.md").read_text()
    assert "Night Bus Ember" in design and "the second, but warmer" in design
    orch.apply_look()
    assert brain.design_calls == calls + 1  # the same note isn't sent twice


def test_check_tokens(tmp_path):
    (tmp_path / "design").mkdir()
    (tmp_path / "design" / "tokens.css").write_text(":root { --color-accent: #ff0000; font-family: X; }")
    (tmp_path / "app.css").write_text("#main { color: var(--color-text); }\n.a { background: #fff; }\n"
                                      "h1 { font-family: var(--font-display); }\np { font-family: Georgia; }\n")
    (tmp_path / "app.js").write_text("el.style.color = '#abcdef';\nlocation.hash = '#add';\n")
    (tmp_path / "Main.kt").write_text("val c = Color(0xFF112233)\n")
    for skip in ("node_modules/x.css", ".git/y.css", ".harness/look/A.html", "tests/z.css", "app.test.js"):
        (tmp_path / skip).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / skip).write_text("a { color: #000; }")
    found = {(f["path"], f["line"], f["kind"]) for f in looklib.check_tokens(tmp_path)}
    assert found == {("app.css", 2, "colour"), ("app.css", 4, "font"), ("app.js", 1, "colour"), ("Main.kt", 1, "colour")}
    assert "app.css:2 (colour)" in looklib.findings_text(looklib.check_tokens(tmp_path))
    assert looklib.findings_text([]) == ""


def test_markdown_shows_the_looks_with_ids(tmp_path):
    doc = plandoc.doc_from_submission(DOC, "a music player", 0)
    looks = looklib.validate_looks([direction(i) for i in range(3)], 3)
    doc["look"] = {"directions": looks, "chosen": "C", "note": "brighter", "pictures": {"A": ["A.png", "A-phone.png"]}}
    md = plandoc.render_markdown(doc)
    assert "## Look" in md and "### Old Record Shop {A}" in md and "### Paper Lantern Calm (chosen) {C}" in md
    assert "![A: Old Record Shop](look/A.png)" in md and "(look/B.png)" not in md
    assert "Accent: #8a3b12 (light), #e8a36b (dark)" in md and "Signature: Track numbers" in md
    assert "The owner's note: brighter" in md
    assert "](looks/proj/A.png)" in plandoc.render_markdown(doc, image_base="looks/proj/")
    kept = plandoc.carry_over(plandoc.doc_from_submission(DOC, "a music player", 0), doc)
    assert kept["look"]["chosen"] == "C"  # a revision keeps the looks


def test_remote_look_actions(tmp_path):
    from roundtable import remote

    orch, _, brain = planned(tmp_path, bad_first=False)
    assert "looks" in remote.LONG
    text = remote.execute(orch.cfg, orch.project.root, {"action": "look", "id": "A", "note": "less brown"})
    assert "1 change(s) waiting" in text
    doc = orch.project.plan_doc()
    assert doc["look"]["chosen"] == "A" and doc["look"]["note"] == "less brown"
    text = remote.execute(orch.cfg, orch.project.root, {"action": "looks", "text": "a night bus"})
    assert text.startswith("New looks to choose from: A Old Record Shop, B Night Bus Neon")
    assert orch.project.plan_doc()["look"]["chosen"] is None and "a night bus" in brain.design_prompts[-1]


def test_pictures_are_skipped_cleanly_without_playwright(tmp_path, monkeypatch):
    monkeypatch.undo()  # the real renderer() this time, with nothing installed
    monkeypatch.setattr(looklib.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(looklib.shutil, "which", lambda name: None)
    assert looklib.renderer() is None
    (tmp_path / "A.html").write_text("<html><body>hi</body></html>")
    r = looklib.render_mockups(tmp_path, ["A"])
    assert r["pictures"] == {} and "Playwright isn't installed" in r["note"]
    monkeypatch.setattr(looklib, "renderer", lambda: "node")
    monkeypatch.setattr(looklib, "_render_node", lambda jobs: (_ for _ in ()).throw(RuntimeError("no browser")))
    r = looklib.render_mockups(tmp_path, ["A"])
    assert r["pictures"] == {} and "pictures failed: no browser" in r["note"]


def test_server_plan_route_takes_the_look_choice_and_shows_pictures(tmp_path):
    import time

    from roundtable.ui.server import UIApp

    orch, _, brain = planned(tmp_path, bad_first=False)
    app = UIApp(None, "missing.yaml")
    app.cfg = lambda: orch.cfg
    orch.cfg.lab_dir = tmp_path / "lab"
    orch._register_with_lab()
    path = str(orch.project.root)
    r = app.dispatch("POST", "/api/plan", {}, {"path": path, "action": "look", "id": "C", "note": "calmer"})
    assert r["pending"] == 1 and orch.project.plan_doc()["look"]["chosen"] == "C"
    (orch.project.dir / "look" / "A.png").write_bytes(b"\x89PNG fake")
    doc = orch.project.plan_doc()
    doc["look"]["pictures"] = {"A": ["A.png"]}
    orch.project.save_plan_doc(doc)
    got = app.dispatch("GET", "/api/plan/looks", {"path": [path]}, {})
    assert got["pictures"]["A"]["desktop"].startswith("data:image/png;base64,")
    job = app.dispatch("POST", "/api/plan", {}, {"path": path, "action": "looks", "text": "bolder"})
    for _ in range(200):
        j = app.dispatch("GET", f"/api/jobs/{job['id']}", {}, {})
        if j["status"] != "running":
            break
        time.sleep(0.05)
    assert j["status"] == "done", (j.get("error"), j.get("lines"))
    assert len(j["result"]["looks"]) == 3 and "bolder" in brain.design_prompts[-1]


def test_pictures_go_to_the_hub_next_to_the_plan(tmp_path):
    import yaml

    from .test_hub import RAW as HUB_RAW

    raw = json.loads(json.dumps(HUB_RAW))
    raw["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
    raw["agents"]["proj"] = {"description": "the project"}
    (tmp_path / "hub.yaml").write_text(yaml.safe_dump(raw))
    hraw = json.loads(json.dumps(RAW))
    hraw["hub"] = {"config": str(tmp_path / "hub.yaml"), "agent": "harness"}
    orch, *_ = planned(tmp_path, raw=hraw, bad_first=False)
    (orch.project.dir / "look" / "A.png").write_bytes(b"\x89PNG desktop")
    (orch.project.dir / "look" / "A-phone.png").write_bytes(b"\x89PNG phone")
    doc = orch.project.plan_doc()
    doc["look"]["pictures"] = {"A": ["A.png", "A-phone.png"]}
    orch.project.save_plan_doc(doc)
    orch._publish_plan()
    hub = tmp_path / "hubdata" / "plans"
    assert (hub / "looks" / "proj" / "A.png").read_bytes() == b"\x89PNG desktop"
    assert (hub / "looks" / "proj" / "A-phone.png").read_bytes() == b"\x89PNG phone"
    page = (hub / "proj.md").read_text()
    assert "![A: Old Record Shop](looks/proj/A.png)" in page and "a look to choose" in page


def test_design_role_defaults():
    from roundtable.harness.config import parse_config

    base = {"providers": {"a": {"type": "scripted"}}, "roles": {"orchestrator": {"model": "a/p"}}}
    assert parse_config(base).design_role == "orchestrator"
    base["roles"]["designer"] = {"model": "a/d"}
    assert parse_config(base).design_role == "designer"
    base["roles"]["designer"]["kind"] = "image"
    assert parse_config(base).design_role == "orchestrator"
    with pytest.raises(ValueError):
        parse_config({**base, "look_stage": "sometimes"})


@pytest.mark.skipif(looklib.renderer() is None, reason="Playwright isn't installed here")
def test_a_real_picture(tmp_path, monkeypatch):
    monkeypatch.undo()
    (tmp_path / "A.html").write_text("<!doctype html><html><body style='background:#8a3b12'>hi</body></html>")
    r = looklib.render_mockups(tmp_path, ["A"])
    assert r["pictures"] == {"A": ["A.png", "A-phone.png"]}, r["note"]
    assert (tmp_path / "A.png").read_bytes().startswith(b"\x89PNG")


def test_no_second_restyle_when_the_planner_already_planned_the_look(tmp_path):
    from roundtable.harness.lookstage import RESTYLE_TITLE
    from roundtable.harness.orchestrator import Task

    orch, a, brain = planned(tmp_path, bad_first=False)
    tasks = orch.project.tasks()
    tasks[0].status = "done"
    tasks.append(Task(id="T99", title="Wire the Night Bus Neon tokens", role="coder",
                      description="link design/tokens.css everywhere", acceptance="ok"))
    orch.project.save_tasks(tasks)
    (orch.project.root / "index.html").write_text("<style>body { color: #123456; }</style>\n")
    d = {"name": "Night Bus Neon", "signature": "a glow"}
    assert orch._restyle_task(d) is None
    assert not any(t.title == RESTYLE_TITLE for t in orch.project.tasks())
