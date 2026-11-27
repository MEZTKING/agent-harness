"""Wave 7, d4-tools: skills – our own ten, adding one (the whole text first, files only), switching, putting
aside, and a builder getting only the skills whose tags meet its task's."""

import os
from pathlib import Path

import pytest

from roundtable import skills
from roundtable.harness.orchestrator import Orchestrator
from roundtable.harness.skillstage import SkillStage

from .test_harness import PLAN, Brain, make

BASES = (Orchestrator,) if issubclass(Orchestrator, SkillStage) else (SkillStage, Orchestrator)


class O(*BASES):
    pass


def home() -> Path:
    return Path(os.environ["ROUNDTABLE_HOME"])


GOOD = """---
name: Tidy shaders
when: Writing GLSL or Godot shaders.
tags: [shaders, graphics]
---
- Keep uniforms few and named for what they mean.
- Comment every magic number; prefer constants at the top.
"""


def write(tmp_path, text=GOOD, name="tidy-shaders"):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(text, encoding="utf-8")
    return d


def test_the_ten_skills_that_come_with_the_app_are_ours_and_short():
    got = skills.list_skills()
    assert len(got) == 10
    for s in got:
        assert s.source == "builtin" and s.enabled and s.tags and s.when
        assert len(s.text) <= 1500, s.id  # two fit in a builder's 3,000 characters
        assert "http" not in s.text
    assert {"pytest-basics", "godot4-scenes", "canvas-games", "accessible-forms"} <= {s.id for s in got}


def test_a_skill_reaches_only_tasks_with_its_tags_at_most_two_within_the_budget():
    assert [s.id for s in skills.pick(["kind:godot-game", "gdscript"])] == ["godot4-scenes"]
    assert skills.pick(["marketing"]) == []
    assert skills.pick([]) == []
    two = skills.pick(["tests", "python", "bugfix", "build"])
    assert len(two) == 2 and len(skills.block(two)) <= skills.PICK_CHARS
    assert two[0].id in ("pytest-basics", "bug-fixing", "python-package")
    assert skills.pick(["tests", "python"], chars=500) == []  # never cut to fit


def test_adding_shows_the_whole_text_and_needs_a_yes(tmp_path):
    src = write(tmp_path)
    seen = []
    with pytest.raises(skills.SkillError, match="needs your yes"):
        skills.add(src, lambda s: seen.append(s.text) or False)
    assert seen == [GOOD]
    assert "tidy-shaders" not in {s.id for s in skills.list_skills()}
    s = skills.add(src / "SKILL.md", lambda s: s.text == GOOD)
    assert s.id == "tidy-shaders" and (home() / "skills" / "tidy-shaders" / "SKILL.md").read_text() == GOOD
    assert [x.id for x in skills.pick(["shaders"])] == ["tidy-shaders"]


def test_skills_come_from_files_never_from_web_links_and_must_be_right(tmp_path):
    with pytest.raises(skills.SkillError, match="not from a web link"):
        skills.preview("https://example.org/SKILL.md")
    with pytest.raises(skills.SkillError, match="tags"):
        skills.preview(write(tmp_path, GOOD.replace("tags: [shaders, graphics]\n", ""), "a1"))
    with pytest.raises(skills.SkillError, match="6,000"):
        skills.preview(write(tmp_path, GOOD + "x" * 6000, "a2"))
    with pytest.raises(skills.SkillError, match="starts with"):
        skills.preview(write(tmp_path, "just words, no top lines at all, which is not a skill", "a3"))


def test_switching_off_and_taking_away_keep_every_file(tmp_path):
    skills.switch("godot4-scenes", False)
    assert skills.pick(["gdscript"]) == []
    assert not skills.get("godot4-scenes").enabled
    skills.switch("godot4-scenes", True)
    assert skills.pick(["gdscript"])
    with pytest.raises(skills.SkillError, match="switch it off"):
        skills.remove("godot4-scenes")
    skills.add(write(tmp_path), lambda s: True)
    moved = Path(skills.remove("tidy-shaders")["moved_to"])
    assert (moved / "SKILL.md").read_text() == GOOD and ".aside" in moved.parts
    assert "tidy-shaders" not in {s.id for s in skills.list_skills()}


def test_a_builder_gets_the_skill_that_fits_and_the_attempt_records_it(tmp_path):
    plan = [dict(PLAN[0], tags=["tests"], files=["test_hello.py"]), dict(PLAN[1])]
    orch, a, *_ = make(tmp_path, brain=Brain(plan=plan))
    orch.__class__ = O
    orch.start("a tested hello module")
    assert orch.run() == "done"
    prompts = [c["messages"][0]["content"] for c in a.calls
               if any(t.name == "finish_task" for t in (c["tools"] or [])) and "# Your task [T1]" in c["messages"][0]["content"]]
    assert prompts and "Pytest basics" in prompts[0] and "Godot" not in prompts[0]
    tasks = {t.id: t for t in orch.project.tasks()}
    assert tasks["T1"].attempts[0]["skills"] == ["pytest-basics", "bug-fixing"]  # tests + python, then tests
    assert "skills" not in tasks["T2"].attempts[0]


def test_skills_can_be_switched_off_for_every_task(tmp_path):
    orch, *_ = make(tmp_path)
    orch.__class__ = O
    orch.cfg.sections["skills"] = {"enabled": False}

    class T:
        id, tags, files = "T9", ["tests"], ["test_a.py"]

    assert orch._skills_worker_part(T()) == "" and orch._skills_attempt(T(), None) is None
