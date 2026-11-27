"""What a task is about (wave 6): tags from the planner, the files' languages and the project's kind."""

from types import SimpleNamespace as NS

from roundtable.harness import tasktags


def test_work_words_come_first_then_languages_then_the_kind():
    task = NS(tags=["My Thing", "shaders", "shaders"], files=["a/b.py", "c.JS", "x.glsl", "README"])
    orch = NS(_kind=lambda: NS(id="Godot-Game"))
    assert tasktags.for_task(orch, task) == ["shaders", "my-thing", "python", "javascript", "kind:godot-game"]


def test_no_kind_no_files_no_tags():
    assert tasktags.for_task(NS(_kind=lambda: None), NS(tags=[], files=[])) == []
    assert tasktags.for_task(None, NS(tags=None, files=None)) == []

    def broken():
        raise RuntimeError("no kind")

    assert tasktags.kind_tag(NS(_kind=broken)) == ""


def test_clean_keeps_six_short_words():
    assert tasktags.clean([f"t{i}" for i in range(10)]) == [f"t{i}" for i in range(6)]
    assert tasktags.clean("Game   Logic") == ["game-logic"]


def test_plain_words():
    assert tasktags.words("game-logic") == "game logic"
    assert tasktags.words("shaders") == "shader"
    assert tasktags.words("kind:website") == "website"


def test_a_quarter_and_at_least_one_may_be_hard():
    assert [tasktags.max_hard(n) for n in (0, 1, 3, 4, 8, 9)] == [0, 1, 1, 1, 2, 2]


def test_trim_keeps_the_first_quarter():
    tasks = [NS(id=f"T{i}", hard=True, risky=i == 3, why_hard="w") for i in range(4)]
    warn = tasktags.trim_hard(tasks)
    assert [t.hard for t in tasks] == [True, False, False, False]
    assert [t.why_hard for t in tasks] == ["w", "", "", "w"]
    assert warn["tasks"] == ["T1", "T2", "T3"] and warn["by"] == "tags"
    assert tasktags.trim_hard(tasks) is None


def test_the_plan_words_list_every_work_word():
    for w in tasktags.WORK:
        assert w in tasktags.PLAN_WORDS
