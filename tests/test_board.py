"""The board (wave 8, p1-board): every task as a card, the moves the owner may make by hand, the owner's
order of ready tasks, earlier goals put away without losing a task, the plain lines for the safety check and
the summing-up, and the task worktrees panel.

Made-up projects in tmp_path, scripted models. Until the coordinator hooks the stage up it is tested as
``class O(BoardStage, Orchestrator)``.
"""

import json
import subprocess

import pytest

from roundtable.harness import boardstage, session
from roundtable.harness.boardstage import BoardStage, REFUSE
from roundtable.harness.orchestrator import HarnessError, Orchestrator
from roundtable.ui import boardapi

from .test_harness import Brain, make

BASES = (Orchestrator,) if issubclass(Orchestrator, BoardStage) else (BoardStage, Orchestrator)


class O(*BASES):
    pass


PLAN = [
    {"id": "T1", "title": "base", "role": "coder", "description": "make base", "acceptance": "ok", "depends_on": []},
    {"id": "T2", "title": "two", "role": "coder", "description": "make two", "acceptance": "ok", "depends_on": ["T1"]},
    {"id": "T3", "title": "three", "role": "coder", "description": "make three", "acceptance": "ok", "depends_on": []},
    {"id": "T4", "title": "four", "role": "coder", "description": "make four", "acceptance": "ok", "depends_on": []},
]


def board_orch(tmp_path, plan=PLAN):
    orch, *_rest = make(tmp_path, brain=Brain(plan=plan))
    o = O(orch.cfg, orch.project.root, on_event=lambda k, d: None)
    o.start("a made-up bakery site")
    o.plan()
    return o


def set_status(o, **statuses):
    tasks = o.project.tasks()
    for t in tasks:
        if t.id in statuses:
            t.status = statuses[t.id]
    o.project.save_tasks(tasks)


def col(o, tid, asks=None):
    for c in o.board(asks)["columns"]:
        if any(x["id"] == tid for x in c["cards"]):
            return c["id"]
    return None


def refused(fn, *a, **k):
    with pytest.raises(HarnessError) as e:
        fn(*a, **k)
    return str(e.value)


# -- the columns and the cards --------------------------------------------------------------------------------------
def test_cards_show_the_task_id_and_one_line_and_fold_the_rest(tmp_path):
    o = board_orch(tmp_path)
    view = o.board()
    assert [c["id"] for c in view["columns"]] == ["todo", "building", "waiting", "stuck", "done"]  # Left out only with cards
    card = view["columns"][0]["cards"][0]
    assert card["number"] == "T1" and card["title"] == "base" and card["line"]
    assert set(card["more"]) >= {"role", "tries"}
    two = next(c for c in view["columns"][0]["cards"] if c["id"] == "T2")
    assert two["line"] == "After T1"


def test_columns_follow_the_task_and_the_cards_waiting_for_the_owner(tmp_path):
    o = board_orch(tmp_path)
    set_status(o, T1="running", T2="failed", T3="failed", T4="done")
    failed_card = {"id": "task:T2", "kind": "failed", "source": {"task": "T2"}, "answer": None}
    assert col(o, "T1") == "building"
    assert col(o, "T2", [failed_card]) == "waiting" and col(o, "T3", [failed_card]) == "stuck"
    assert col(o, "T4") == "done"
    command = {"id": "command:x", "kind": "command", "task": {"id": "T1"}, "source": {}, "answer": None}
    assert col(o, "T1", [command]) == "waiting"
    assert all(c["moves"] == [] for c in o.board([command])["columns"][2]["cards"])  # answered in Needs you


# -- every allowed move ---------------------------------------------------------------------------------------------
def test_left_out_and_back(tmp_path):
    o = board_orch(tmp_path)
    r = o.move_task("T3", "left_out")
    assert r["column"] == "left_out" and col(o, "T3") == "left_out"
    assert next(t for t in o.project.tasks() if t.id == "T3").status == "done"  # the orchestrator's own skip
    assert "left_out" in [c["id"] for c in o.board()["columns"]]
    o.move_task("T3", "todo")
    assert col(o, "T3") == "todo" and "T3" not in boardstage.read_board(o.project.root)["left_out"]


def test_stuck_goes_back_to_todo_and_done_asks_first_with_its_cost(tmp_path):
    o = board_orch(tmp_path)
    set_status(o, T3="failed", T4="done")
    o.move_task("T3", "todo")
    assert col(o, "T3") == "todo"
    why = refused(o.move_task, "T4", "todo")
    assert why.startswith("Are you sure? T4 was finished: doing it again costs about $")
    o.move_task("T4", "todo", confirmed=True)
    assert col(o, "T4") == "todo"


def test_waiting_is_accepted_only_with_a_yes(tmp_path):
    o = board_orch(tmp_path)
    set_status(o, T3="failed")
    card = [{"id": "task:T3", "kind": "failed", "source": {"task": "T3"}, "answer": None}]
    assert refused(o.move_task, "T3", "done", asks=card) == REFUSE["confirm_accept"].format(id="T3")
    r = o.move_task("T3", "done", asks=card, confirmed=True)
    assert r["reply"] == "T3 is accepted as it is."
    t = next(t for t in o.project.tasks() if t.id == "T3")
    assert t.status == "done" and t.summary.startswith("Accepted by the owner")


def test_up_and_down_within_todo_is_the_order_the_run_picks_from(tmp_path):
    o = board_orch(tmp_path)
    for _ in range(3):  # T4 starts last of four
        o.move_task("T4", "up")
    todo = [c["id"] for c in o.board()["columns"][0]["cards"]]
    assert todo.index("T4") < todo.index("T3")
    ready = [t for t in o.project.tasks() if t.id in ("T1", "T3", "T4")]
    assert [t.id for t in o._board_order(ready)][0] == "T4"


# -- every refused move, with its sentence ----------------------------------------------------------------------------
def test_refused_moves_say_why_in_one_line(tmp_path):
    o = board_orch(tmp_path)
    set_status(o, T4="running", T3="done")
    assert refused(o.move_task, "T1", "building") == REFUSE["building"]
    assert refused(o.move_task, "T4", "todo") == REFUSE["running"].format(id="T4")
    assert refused(o.move_task, "T9", "todo") == REFUSE["unknown"].format(id="T9")
    assert refused(o.move_task, "T1", "todo") == REFUSE["same"].format(id="T1", column="To do")
    assert refused(o.move_task, "T1", "done").startswith("T1 can't go from To do to Done.")
    assert refused(o.move_task, "T3", "left_out").startswith("T3 can't go from Done to Left out.")
    assert refused(o.move_task, "T3", "up").startswith("T3 can't go from Done")
    assert refused(o.move_task, "T1", "up") == REFUSE["edge"].format(id="T1", end="top")
    assert refused(o.move_task, "T2", "up") == REFUSE["depends"].format(id="T2", other="T1")  # never above what it needs
    assert refused(o.move_task, "T1", "sideways") == "There's no column called 'sideways' on the board."
    for why in (REFUSE["building"], REFUSE["running"]):
        assert "\n" not in why and len(why) < 140


def test_a_move_never_changes_a_task_another_machine_has_claimed(tmp_path):
    o = board_orch(tmp_path)
    set_status(o, T3="failed")
    before = json.dumps([t.__dict__ for t in o.project.tasks()], sort_keys=True, default=str)
    claim = {"machine": "laptop-id", "machine_name": "Laptop", "state": "building"}
    for to in ("todo", "left_out", "up"):
        assert refused(o.move_task, "T3" if to == "todo" else "T1", to, claim=claim) == REFUSE["elsewhere"].format(machine="Laptop")
    assert json.dumps([t.__dict__ for t in o.project.tasks()], sort_keys=True, default=str) == before
    assert not (o.project.dir / boardstage.BOARD).exists()


def test_while_this_computer_runs_it_only_the_order_changes(tmp_path):
    o = board_orch(tmp_path)
    assert refused(o.move_task, "T3", "left_out", busy=True) == REFUSE["busy"]
    assert o.move_task("T4", "up", busy=True)["column"] == "todo"


# -- the planner's rewrite keeps the owner's order and marks --------------------------------------------------------
def test_a_rewrite_of_the_task_list_keeps_order_and_left_out(tmp_path):
    o = board_orch(tmp_path)
    for _ in range(3):  # T4 starts last of four
        o.move_task("T4", "up")
    o.move_task("T3", "left_out")
    tasks = o.project.tasks()  # what the planner's revise does: the same ids, rewritten, in its own order
    o.project.save_tasks(list(reversed(tasks)))
    view = o.board()
    todo = [c["id"] for c in view["columns"][0]["cards"]]
    assert todo.index("T4") < todo.index("T1")
    assert col(o, "T3") == "left_out"


def test_a_skip_from_the_failed_card_shows_as_left_out(tmp_path):
    o = board_orch(tmp_path)
    o.skip("T3")
    assert col(o, "T3") == "left_out"


# -- hygiene: earlier goals put away, nothing lost ---------------------------------------------------------------------
def test_archive_then_extend_keeps_every_task_readable(tmp_path):
    o = board_orch(tmp_path)
    assert o.run() == "done"
    before = {t.id for t in o.project.tasks()}
    o.cfg._instances["a"].script = Brain(plan=[
        {"id": "T5", "title": "more", "role": "coder", "description": "x", "acceptance": "y", "depends_on": ["T3"]}])
    o.extend("goal two")
    o.plan()
    got = boardstage.archive_earlier(o.project)
    live = {t.id for t in o.project.tasks()}
    kept = {r["id"] for r in boardstage.archived(o.project.root)}
    assert got["archived"] == 3 and "T3" in live  # T5 needs T3: it stays in the live list
    assert live | kept == before | {"T5"} and not live & kept  # count before equals count after
    assert boardstage.archive_path(o.project.root, 0).is_file()
    view = o.board()
    assert view["earlier"]["count"] == 3 and view["earlier"]["title"] == "Earlier work (3)"
    assert boardstage.archive_earlier(o.project)["archived"] == 0  # again: nothing more to move, nothing doubled
    assert len(boardstage.archived(o.project.root)) == 3
    assert o.run() == "done"  # the run goes on with the shorter list


def test_archive_moves_only_finished_tasks_of_earlier_goals(tmp_path):
    o = board_orch(tmp_path)
    set_status(o, T1="done", T2="failed", T3="done")
    meta = o.project.meta()
    meta["goals"].append("goal two")
    o.project.save_meta(meta)
    boardstage.archive_earlier(o.project)
    live = {t.id: t.status for t in o.project.tasks()}
    assert live == {"T1": "done", "T2": "failed", "T4": "pending"}  # T2 waits on T1; failed and to-do stay


def test_archive_does_nothing_with_one_goal(tmp_path):
    o = board_orch(tmp_path)
    set_status(o, T1="done")
    assert boardstage.archive_earlier(o.project) == {"archived": 0, "files": []}


def test_the_archive_is_read_back_before_the_list_is_shortened(tmp_path, monkeypatch):
    o = board_orch(tmp_path)
    set_status(o, T3="done")
    meta = o.project.meta()
    meta["goals"].append("two")
    o.project.save_meta(meta)
    real = json.loads
    monkeypatch.setattr(boardstage.json, "loads", lambda s, *a, **k: [] if s.lstrip().startswith("[") and '"pending"' not in s else real(s, *a, **k))
    with pytest.raises(HarnessError):
        boardstage.archive_earlier(o.project)
    monkeypatch.undo()
    assert "T3" in {t.id for t in o.project.tasks()}


# -- the run's hooks -------------------------------------------------------------------------------------------------
def test_without_board_use_the_order_and_the_run_are_as_before(tmp_path):
    o = board_orch(tmp_path)
    ready = o.project.tasks()
    assert o._board_order(ready) is ready  # no board.json: the very same list
    assert o._board_stop() is None
    assert o.run() == "done"
    assert not (o.project.dir / boardstage.BOARD).exists()


def test_the_owner_stop_pauses_before_the_next_task(tmp_path):
    o = board_orch(tmp_path)
    boardstage.request_stop(o.project.root)
    assert o._board_stop() == "paused"
    assert o.project.meta()["status"] == "paused" and o.project.meta()["pause"] == "owner_stop"
    assert o._board_stop() is None  # once


# -- looping and compacting in plain words (MD-31) ---------------------------------------------------------------------
def test_session_shows_the_breaker_and_the_summing_up_in_plain_words(tmp_path):
    rows = [{"event": "task_start", "task": "T1", "title": "x", "role": "coder", "at": "2026-11-27T10:00:00Z"},
            {"event": "breaker", "task": "T1", "action": "steer", "signal": "repeats",
             "reason": "the same edit_file call 8 times in a row", "at": "2026-11-27T10:01:00Z"},
            {"event": "compacted", "task": "T1", "tokens_before": 90000, "tokens_after": 20000, "at": "2026-11-27T10:02:00Z"},
            {"event": "breaker", "task": "T1", "action": "stop", "signal": "repeats",
             "reason": "the same edit_file call 8 times in a row", "at": "2026-11-27T10:03:00Z"}]
    t = session.tasks_from_events(rows)[0]
    lines = [s["label"] for s in t["steps"] if s["kind"] == "guard"]
    assert lines == ["Going round in circles: told to try another way", "Older steps summed up to save money",
                     "Stopped: the same thing 8 times"]
    assert session.step_line(t["steps"][0]) == "Going round in circles: told to try another way"
    assert t["now"] == "Stopped: the same thing 8 times"
    assert session.guard_line("breaker", {"action": "steer", "signal": "errors", "reason": "5 errors"}).startswith("Errors one after another")
    assert session.guard_line("breaker", {"action": "nonsense"}) == ""


# -- the worktrees panel (MD-73) --------------------------------------------------------------------------------------
def _git(cwd, *a):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@example.invalid", "PATH": "/usr/bin:/bin", "HOME": str(cwd)})


def test_worktrees_view_on_a_git_project_with_a_dirty_lane(tmp_path):
    from roundtable.harness.worktrees import Worktrees

    o = board_orch(tmp_path)
    root = o.project.root
    if not (root / ".git").exists():
        _git(root, "init", "-q", "-b", "main")
    (root / "a.txt").write_text("a\n")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-q", "-m", "base")
    trees = Worktrees(root)
    trees.add("T1", "HEAD")
    trees.add("T3", "HEAD")
    (trees.path("T1") / "a.txt").write_text("changed\n")
    o.emit("worktree_kept", {"task": "T1", "path": str(trees.path("T1")), "why": "the run stopped"})
    rows = {r["task"]: r for r in boardapi.worktree_rows(root)}
    assert rows["T1"]["unsaved"] == "yes" and rows["T3"]["unsaved"] == "no"
    assert rows["T1"]["why"] == "the run stopped" and rows["T1"]["branch"].endswith("T1")
    assert rows["T1"]["tidy"].startswith("Kept: its task isn't finished")
    assert trees.exists("T1") and trees.exists("T3")  # the panel never deletes
