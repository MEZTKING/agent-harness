"""The project memory and this computer's (memory.py): made-up projects only."""

from collections import Counter
from types import SimpleNamespace

from roundtable import memory


def cfg(**mem):
    return SimpleNamespace(sections={"memory": mem})


def lines(path):
    return [x for x in path.read_text(encoding="utf-8").splitlines() if x.startswith("- ")]


def test_notes_rules_and_facts_go_in_their_parts(tmp_path):
    root = tmp_path / "bakery-site"
    assert memory.add_note(root, "The menu page uses the shared header.")
    assert not memory.add_note(root, "the menu page uses the shared   header.")  # not twice
    assert memory.pin(root, "Prices are in pounds.")
    assert memory.add_rule(root, "Never change the logo.")
    text = memory.project_path(root).read_text(encoding="utf-8")
    assert text.index("## Rules") < text.index("## Pinned facts") < text.index("## Recent")
    m = memory.read(memory.project_path(root))
    assert m.notes(memory.RULES) == ["- Never change the logo."]
    assert m.notes(memory.RECENT)[0].endswith("The menu page uses the shared header.")
    assert memory.view(memory.project_path(root))["counts"] == {"rules": 1, "pinned": 1, "recent": 1}


def test_trim_moves_old_lines_word_for_word_and_never_rules(tmp_path):
    root = tmp_path / "game"
    c = cfg(budget_chars=900, pinned_chars=300)
    for i in range(6):
        memory.add_rule(root, f"Rule number {i}: keep the frame rate steady")
    written = []
    for i in range(60):
        note = f"Note {i:02d}: the level {i} door needs the blue key and a short sound"
        memory.add_note(root, note, c)
        written.append(note)
    for i in range(20):
        memory.pin(root, f"Fact {i:02d}: enemies spawn from the left edge", c)
    path = memory.project_path(root)
    arch = memory.archive_of(path)
    assert len(path.read_text(encoding="utf-8")) <= 900 + 600  # rules can't move; everything else fits
    kept = lines(path)
    archived = [x for x in arch.read_text(encoding="utf-8").splitlines() if x.startswith("- ")]
    # nothing lost: every line is in the memory or the archive, exactly once
    allofit = Counter(kept + archived)
    for note in written:
        assert sum(n for line, n in allofit.items() if line.endswith(note)) == 1
    assert all(f"- Rule number {i}: keep the frame rate steady" in kept for i in range(6))
    assert not any("Rule number" in x for x in archived)
    # oldest first: note 00 moved, the newest stayed
    assert any(x.endswith(written[0]) for x in archived)
    assert kept[-1].endswith(written[-1])


def test_owner_lines_survive_and_a_bad_file_is_left_alone(tmp_path):
    path = tmp_path / "memory.md"
    path.write_text("## My own part\n- keep me\n\n## Recent\n" + "".join(f"- old {i}\n" for i in range(50)),
                    encoding="utf-8")
    moved = memory.trim(path, cfg(budget_chars=200))
    assert moved > 0
    text = path.read_text(encoding="utf-8")
    assert "- keep me" in text and "- old 49" in text and "- old 0\n" not in text
    assert "- old 0\n" in memory.archive_of(path).read_text(encoding="utf-8")


def test_block_stays_within_budget_and_keeps_rules_and_newest(tmp_path):
    root, home = tmp_path / "shop", tmp_path / "home"
    memory.add_rule(root, "Always use British English.")
    for i in range(200):
        memory.add_note(root, f"Note {i}: the basket total rounds to pennies", cfg(budget_chars=100000))
    memory.refresh_machine(home, rows=[{"id": "git", "name": "Git", "state": "found", "version": "2.43", "where": "/usr/bin/git"},
                                       {"id": "godot", "name": "Godot", "state": "missing"}],
                           os_name="linux", which=lambda _: None)
    c = cfg(block_chars=1000)
    block = memory.memory_block(root, c, home=home)
    assert len(block) <= 1000
    assert "Always use British English." in block
    assert "Note 199:" in block and "Note 0:" not in block
    assert "Git 2.43" in block and "No Wine" in block
    assert memory.memory_block(root, cfg(enabled=False), home=home) == ""
    assert memory.memory_block(tmp_path / "empty", c, home=tmp_path / "nohome") == ""


def test_machine_memory_rewrites_tools_and_keeps_owner_lines(tmp_path):
    home = tmp_path / "home"
    rows = [{"id": "android", "name": "Android SDK", "state": "found", "where": "/opt/android-sdk"},
            {"id": "node", "name": "Node.js", "state": "old", "version": "16.0", "min_version": "18"}]
    path = memory.refresh_machine(home, rows=rows, os_name="linux", which=lambda _: None)
    memory.pin(path, "The phone is a Pixel on USB.")
    memory.refresh_machine(home, rows=rows[:1], os_name="linux", which=lambda _: None)
    text = path.read_text(encoding="utf-8")
    assert "Android SDK at /opt/android-sdk" in text and "Node.js" not in text
    assert "No system Gradle" in text and "No Wine" in text
    assert text.count("## Tools found") == 1 and "The phone is a Pixel on USB." in text
    assert memory.machine_facts(rows, os_name="windows", which=lambda _: "x") == [
        "- Has Android SDK at /opt/android-sdk", "- Has Node.js 16.0 (too old: needs 18)"]


def test_learning_from_tasks_and_answers(tmp_path):
    root = tmp_path / "app"
    fixed = {"id": "T2", "title": "Add the cart", "status": "done", "attempts": [
        {"outcome": "rejected", "review": "The total ignores the discount. Also tidy up."},
        {"outcome": "approved", "summary": "Applied the discount before tax. Tests pass."}]}
    line = memory.learn_from_task(root, fixed)
    assert "The total ignores the discount." in line and "Applied the discount before tax." in line
    assert memory.learn_from_task(root, {"title": "Easy", "status": "done", "attempts": [{"outcome": "approved"}]}) == ""
    failed = {"title": "Export", "status": "failed", "attempts": [{"outcome": "error", "error": "No Android SDK found."}]}
    assert "didn't get done: No Android SDK found." in memory.learn_from_task(root, failed)
    assert memory.learn_answer(root, "Which colour for the buttons?", "Green")
    m = memory.read(memory.project_path(root))
    assert any("Green" in x for x in m.notes(memory.PINNED)) and len(m.notes(memory.RECENT)) == 2
    assert memory.learn_from_task(root, fixed, cfg(enabled=False)) == ""


def test_save_text_from_the_app_then_trimmed(tmp_path):
    path = tmp_path / "p" / ".harness" / "memory.md"
    out = memory.save_text(path, "# Memory\n\n## Recent\n" + "".join(f"- line {i}\n" for i in range(100)),
                           cfg(budget_chars=300))
    assert out["saved"] and out["moved"] > 0 and len(path.read_text(encoding="utf-8")) <= 300
