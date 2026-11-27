"""The written handover for a task that didn't finish (parity MD-24). Made-up projects in tmp_path; no models."""

import subprocess

from roundtable.harness import handoff
from roundtable.harness.orchestrator import Task


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def repo(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "user.name", "t")
    (root / ".gitignore").write_text(".harness/\n")
    (root / "app.py").write_text("print('a')\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "start")
    return root, git(root, "rev-parse", "HEAD")


def stuck_task(base=""):
    return Task(id="T7", title="save files", role="coder", description="save to disk", acceptance="the file is saved",
                base_commit=base, attempts=[
                    {"model": "a/coder", "outcome": "rejected", "summary": "wrote save()", "review": "it never closes the file"},
                    {"model": "a/coder", "outcome": "max_steps"}])


def test_write_and_read(tmp_path):
    root, base = repo(tmp_path)
    (root / "app.py").write_text("print('a')\nprint('b')\n")
    (root / "save.py").write_text("x = 1\n")
    t = stuck_task(base)
    p = handoff.write(root, t, "The file is never closed.", advice="Use a with block.")
    assert p == root / ".harness/handoffs/T7.md"
    text = handoff.read(root, "T7")
    assert text.startswith("# Handover: [T7] save files")
    assert "The file is never closed." in text and "Use a with block." in text
    assert "Attempt 1 (a/coder): rejected. It said: wrote save()" in text
    assert "The reviewer: it never closes the file" in text and "Attempt 2 (a/coder): max_steps" in text
    assert "app.py" in text and "New files: save.py" in text  # changed and new files, .harness left out
    assert "Its 'done when': the file is saved" in text
    assert "What the last review still wanted: it never closes the file" in text


def test_no_handover_and_no_git(tmp_path):
    assert handoff.read(tmp_path, "T1") == ""
    t = stuck_task()
    handoff.write(tmp_path, t, "")
    text = handoff.read(tmp_path, "T7")
    assert "It did not pass." in text and "None that git can see." in text
    assert "Advice" not in text


def test_the_worker_part_has_its_own_and_the_one_it_carries_on(tmp_path):
    t = stuck_task()
    assert handoff.worker_part(tmp_path, t) == ""
    handoff.write(tmp_path, t, "too big", advice="do the reading first")
    own = handoff.worker_part(tmp_path, t)
    assert own.startswith("# A handover from the earlier try at this task") and "do the reading first" in own
    nxt = Task(id="T8", title="second half", role="coder", description="d", handoff_from="T7")
    part = handoff.worker_part(tmp_path, nxt)
    assert part.startswith("# A handover from task T7, whose work this task carries on")
    assert "do the reading first" in part


def test_a_handover_stays_short(tmp_path):
    t = stuck_task()
    t.attempts = [{"model": "a/coder", "outcome": "rejected", "summary": "s" * 2000, "review": "r" * 2000}] * 20
    handoff.write(tmp_path, t, "why " * 3000)
    text = handoff.read(tmp_path, "T7")
    assert len(text) <= handoff.MAX_CHARS
    assert "Attempt 17" in text and "Attempt 16" not in text and "## What's left" in text  # only the last few tries


def test_odd_task_ids_make_safe_file_names(tmp_path):
    t = stuck_task()
    t.id = "../T 9"
    p = handoff.write(tmp_path, t, "x")
    assert p.parent == tmp_path / ".harness/handoffs" and p.name == ".._T_9.md"
    assert handoff.read(tmp_path, "../T 9").startswith("# Handover: [../T 9]")
