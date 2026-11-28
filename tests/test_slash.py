"""``/`` commands (wave 8, DS-16, DS-83): each does what a button does; spending or deleting asks first; slow ones
come back at once as a job. Made-up projects, scripted models."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from roundtable.harness import slash
from roundtable.harness.slash import COMMANDS, DO, SlashError

from .test_harness import make


def wait(app, view, s: float = 20.0):
    jid = view["id"] if isinstance(view, dict) else view.id
    end = time.time() + s
    while time.time() < end:
        j = app.jobs.jobs[jid]
        if j.status != "running":
            return j
        time.sleep(0.02)
    raise AssertionError("the job didn't end")


@pytest.fixture
def chat_app(tmp_path, monkeypatch):
    """A finished made-up project (T1–T3 done) behind the desktop's API, with chatapi in it."""
    from roundtable.ui import server
    from roundtable.ui.server import UIApp

    monkeypatch.setenv("ROUNDTABLE_HOME", str(tmp_path / "home"))
    orch, *_ = make(tmp_path)
    orch.start("build a bakery site")
    assert orch.run() == "done"
    cfg = orch.cfg
    cfg.lab_dir = tmp_path / "lab"
    orch._register_with_lab()
    app = UIApp(str(tmp_path / "missing-hub.yaml"), "missing.yaml")
    app.cfg = lambda: cfg
    app.projects_dir = tmp_path / "projects"
    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "chatapi"))
    return app, orch.project.root


def cmd(app, root, line, confirmed=False, route="/api/commands/pc"):
    return app.dispatch("POST", route, {}, {"path": str(root), "line": line, "confirmed": confirmed})


def test_parse_and_the_table():
    assert slash.parse("/goal a shop page") == ("goal", "a shop page")
    assert slash.parse("/RUN") == ("run", "")
    assert slash.parse("just words") == ("", "just words")
    assert slash.parse("//not a command") == ("", "//not a command")
    assert set(COMMANDS) == set(DO)
    for name in ("plan", "run", "next", "stop", "retry", "skip", "undo", "goal", "compact", "model", "test", "search",
                 "board", "help"):
        assert name in COMMANDS


def test_the_menu_lists_every_command(chat_app):
    app, root = chat_app
    got = app.dispatch("GET", "/api/commands", {"path": [str(root)]}, {})["commands"]
    names = [c["name"] for c in got]
    assert names[:len(COMMANDS)] == list(COMMANDS)
    by = {c["name"]: c for c in got}
    assert by["run"]["confirm"] and by["undo"]["confirm"] and not by["board"]["confirm"]
    assert by["test"]["pc_only"] and by["compact"]["slow"]
    assert "/goal <what to build next>" in cmd(app, root, "/help")["reply"]


def test_every_command_maps_to_the_action_a_button_does(chat_app, monkeypatch):
    """Each command calls the very function the app's button route calls (recorded here instead of run)."""
    from roundtable.ui import filesapi, rewindapi, searchapi

    app, root = chat_app
    seen = []
    job = {"id": "j1", "status": "running"}
    monkeypatch.setattr(app, "project_action", lambda b: seen.append(("project_action", b)) or (job if b["action"] in ("run", "extend") else {"ok": True}))
    monkeypatch.setattr(app, "plan_post", lambda b: seen.append(("plan_post", b)) or (job if b["action"] == "revise" else {"profile": b.get("name")}))
    monkeypatch.setattr(filesapi, "run_tests", lambda a, b: seen.append(("run_tests", b)) or job)
    monkeypatch.setattr(searchapi, "run_search", lambda a, q: seen.append(("run_search", q)) or {"hits": [{"title": "logo"}]})
    monkeypatch.setattr(rewindapi, "do", lambda a, b: seen.append(("rewind", b)) or {"ok": True, "words": "Undone."})
    p = str(root)
    assert cmd(app, root, "/plan bigger buttons", True)["job"] == job
    assert cmd(app, root, "/run", True)["job"] == job
    assert cmd(app, root, "/next", True)["job"] == job
    assert cmd(app, root, "/retry T1")["reply"].startswith("T1")
    assert cmd(app, root, "/skip t3")["reply"].startswith("T3")
    assert cmd(app, root, "/undo", True)["reply"] == "Undone."
    assert cmd(app, root, "/goal a prices page", True)["job"] == job
    assert cmd(app, root, "/model quality")["reply"].endswith("quality setting.")
    assert cmd(app, root, "/test")["job"] == job
    assert "logo" in cmd(app, root, "/search logo")["reply"]
    assert cmd(app, root, "/board")["open"] == "board"
    assert seen == [
        ("plan_post", {"path": p, "action": "revise", "text": "bigger buttons"}),
        ("project_action", {"path": p, "action": "run"}),
        ("project_action", {"path": p, "action": "run", "max_tasks": 1}),
        ("project_action", {"path": p, "action": "retry", "task": "T1"}),
        ("project_action", {"path": p, "action": "skip", "task": "T3"}),
        ("rewind", {"path": p, "task": "T3", "mode": "undo_task", "stamp": seen[5][1]["stamp"]}),
        ("project_action", {"path": p, "action": "extend", "goal": "a prices page"}),
        ("plan_post", {"path": p, "action": "profile", "name": "quality"}),
        ("run_tests", {"path": p}),
        ("run_search", {"q": ["logo"], "limit": ["8"]}),
    ]
    assert seen[5][1]["stamp"]  # the undo carries the preview's stamp, as the History page's button does


def test_a_spending_command_asks_first_and_does_nothing_until_confirmed(chat_app, monkeypatch):
    app, root = chat_app
    called = []
    monkeypatch.setattr(app, "project_action", lambda b: called.append(b) or {"id": "j"})
    for line in ("/run", "/next", "/goal more pages", "/plan", "/compact"):
        r = cmd(app, root, line)
        assert r["confirm"] and "spend" in r["confirm"] or "model call" in r["confirm"], line
        assert "job" not in r
    assert called == []
    assert "estimate" in cmd(app, root, "/run")["confirm"] or "spends" in cmd(app, root, "/run")["confirm"]


def test_undo_shows_what_it_takes_out_then_really_undoes(chat_app):
    app, root = chat_app
    first = cmd(app, root, "/undo T3")
    assert first["confirm"] and "taken out" in first["confirm"] and (root / "test_hello.py").exists()
    r = cmd(app, root, "/undo T3", True)
    assert r["reply"] and not (root / "test_hello.py").exists()


def test_the_phone_cant_run_programs_on_the_pc(chat_app):
    from roundtable.ui.server import ApiError

    app, root = chat_app
    with pytest.raises(ApiError, match="only in the PC's own app"):
        cmd(app, root, "/test", route="/api/commands")
    assert cmd(app, root, "/board", route="/api/commands")["open"] == "board"


def test_unknown_commands_and_missing_words_say_what_to_do(chat_app):
    from roundtable.ui.server import ApiError

    app, root = chat_app
    with pytest.raises(ApiError, match="There's no /fly"):
        cmd(app, root, "/fly")
    with pytest.raises(ApiError, match="Say which task"):
        cmd(app, root, "/skip")
    with pytest.raises(ApiError, match="no task T9"):
        cmd(app, root, "/retry T9")
    with pytest.raises(ApiError, match="No task has stopped"):
        cmd(app, root, "/retry")


def test_stop_stops_a_tasks_running_command(chat_app, monkeypatch):
    from roundtable.harness import livecmd

    app, root = chat_app
    stopped = []
    monkeypatch.setattr(livecmd, "running", lambda r: [{"task": "T2", "n": 1}])
    monkeypatch.setattr(livecmd, "stop", lambda r, t, n=None: stopped.append((t, n)) or 1)
    assert cmd(app, root, "/stop")["reply"].startswith("Stopped 1 command")
    assert stopped == [("T2", 1)]
    monkeypatch.setattr(livecmd, "running", lambda r: [])
    assert "Nothing was running" in cmd(app, root, "/stop")["reply"]


def test_compact_is_a_job_that_keeps_the_old_messages(chat_app):
    from roundtable.harness.orchestrator import Orchestrator

    app, root = chat_app
    orch = Orchestrator(app.cfg(), root)
    for i in range(4):
        orch.ask(f"question {i}")
    before = orch.chat_history(100)
    r = cmd(app, root, "/compact", True)
    assert r["job"]["status"] == "running" or r["job"]["status"] == "done"  # comes back at once
    j = wait(app, r["job"])
    assert j.status == "done", j.error
    after = orch.chat_history(100)
    assert after[0].get("summary") and after[0]["text"].startswith("Summary of the chat so far")
    assert len(after) == 5
    old = [json.loads(x) for x in (orch.project.dir / "chat-old.jsonl").read_text(encoding="utf-8").splitlines()]
    assert old == before[:len(before) - 4]


def test_a_slow_command_never_holds_the_request(chat_app, monkeypatch):
    """A /test that takes long: the request answers at once with the job, and the job carries on (DS-83)."""
    from roundtable.ui import filesapi

    app, root = chat_app
    gate = []

    def slow(a, b):
        def run(job):
            while not gate:
                time.sleep(0.01)
            return {"ok": True}

        return a.jobs.start("tests", "slow tests", run, target=str(root)).view()

    monkeypatch.setattr(filesapi, "run_tests", slow)
    t0 = time.time()
    r = cmd(app, root, "/test")
    assert time.time() - t0 < 2 and r["job"]["status"] == "running"
    gate.append(1)
    assert wait(app, r["job"]).status == "done"


def test_skills_by_name_ask_the_next_tasks_to_use_them(chat_app, monkeypatch):
    from roundtable.harness.orchestrator import Orchestrator

    app, root = chat_app
    monkeypatch.setattr(slash, "_skills", lambda: {"tidy-css": SimpleNamespace(id="tidy-css", name="Tidy CSS")})
    names = [c["name"] for c in slash.table(app, str(root))]
    assert "tidy-css" in names
    r = cmd(app, root, "/tidy-css keep it short")
    assert "Tidy CSS" in r["reply"]
    guide = Orchestrator(app.cfg(), root).project.meta()["guidance"][-1]["text"]
    assert "Tidy CSS" in guide and "keep it short" in guide


def test_a_plugins_commands_ask_first_and_run_as_a_job(chat_app, monkeypatch):
    from roundtable.ui.server import ApiError

    app, root = chat_app
    ran = []
    monkeypatch.setattr(slash, "_plugins", lambda a: {"lint": {"check": lambda ctx, argv: ran.append(argv) or "all clean"}})

    class Host:
        def get(self, pid):
            return SimpleNamespace(id=pid)

        def context(self, p):
            return None

    monkeypatch.setattr(type(app.cfg()), "plugin_host", lambda self: Host())
    assert cmd(app, root, "/lint check src")["confirm"]
    assert ran == []
    with pytest.raises(ApiError, match="only in the PC's own app"):
        cmd(app, root, "/lint check", True, route="/api/commands")
    r = cmd(app, root, "/lint check src", True)
    assert wait(app, r["job"]).result == {"reply": "all clean"} and ran == [["src"]]
    with pytest.raises(ApiError, match="Say which of its commands"):
        cmd(app, root, "/lint", True)


def test_no_project_no_command(chat_app):
    from roundtable.ui.server import ApiError

    app, _ = chat_app
    with pytest.raises(ApiError, match="Open a project first"):
        app.dispatch("POST", "/api/commands/pc", {}, {"path": "", "line": "/run", "confirmed": True})
    with pytest.raises(SlashError):
        slash.run(app, "", "not a command")


def test_talk_is_a_chat_message_and_reads_back_the_answers_card(tmp_path, monkeypatch):
    """1.5.0: the microphone's words go through the chat (chat.reply, aloud): the answer to read out, and the
    card it offers as the action (a tap still runs it). Voice never offers undoing a task."""
    from .chatworld import World

    w = World(tmp_path, monkeypatch, answers=["Three tasks are done.", "T2 stopped on the logo.\nAction: /retry T2",
                                              "Sure.\nAction: /undo T3", "Building.\nAction: /run"])
    talk = lambda text: w.app.dispatch("POST", "/api/chat/talk", {}, {"path": str(w.root), "text": text})  # noqa: E731
    r = talk("how is it going?")
    assert r["reply"] == "Three tasks are done." and r["action"] is None
    assert "read aloud" in w.model.sent[0]["messages"][0]["content"]
    assert [x["text"] for x in w.lines()][:2] == ["how is it going?", "Three tasks are done."]  # the chat keeps it
    r = talk("what's wrong?")
    assert r["reply"] == "T2 stopped on the logo."
    assert {k: r["action"][k] for k in ("line", "words", "confirm")} == {"line": "/retry T2",
                                                                        "words": COMMANDS["retry"][0], "confirm": False}
    assert r["action"]["chat"] == w.chat and r["action"]["card"]
    assert talk("undo it")["action"] is None  # not offered by voice
    assert talk("go")["action"]["confirm"] is True
    with pytest.raises(Exception):
        talk("")


def test_the_chats_new_commands_do_what_remote_py_does(chat_app, monkeypatch):
    """1.5.0: the commands the phone's letters could do, each through the function a button or remote.py calls."""
    from roundtable.harness.orchestrator import Orchestrator

    app, root = chat_app
    p = str(root)
    seen = []
    job = {"id": "j1"}
    monkeypatch.setattr(app, "plan_post", lambda b: seen.append(("plan_post", b)) or (job if b["action"] == "looks"
                                                                                       else {"pending": 1}))
    monkeypatch.setattr(app, "project_action", lambda b: seen.append(("project_action", b)) or job)
    assert "1 change waits" in cmd(app, root, "/answer Q1 blue and gold")["reply"]
    assert cmd(app, root, "/choose D1 b")["reply"].startswith("Saved")
    assert cmd(app, root, "/looks warmer", True)["job"] == job
    assert cmd(app, root, "/pictures")["job"] == job
    assert seen == [("plan_post", {"path": p, "action": "answer", "question": "Q1", "text": "blue and gold"}),
                    ("plan_post", {"path": p, "action": "choose", "decision": "D1", "option": "b"}),
                    ("plan_post", {"path": p, "action": "looks", "text": "warmer"}),
                    ("project_action", {"path": p, "action": "show_it"})]
    assert "Noted" in cmd(app, root, "/note use British spelling")["reply"]
    assert Orchestrator(app.cfg(), root).project.meta()["guidance"][-1]["text"] == "use British spelling"
    for line in ("/approve at most $2", "/build accepted at most $2", "/accept T1", "/looks", "/new a recipe app"):
        got = cmd(app, root, line)
        assert got.get("confirm") and "job" not in got, line  # spends: asks first
    assert cmd(app, root, "/autopilot status")["reply"].startswith("Autopilot")
    assert cmd(app, root, "/autopilot on").get("confirm")
    from roundtable.ui.server import ApiError

    with pytest.raises(ApiError, match="which question"):
        cmd(app, root, "/answer Q1")
    with pytest.raises(ApiError, match="which to-do"):
        cmd(app, root, "/todo T1")


def test_build_with_a_limit_runs_the_accepted_ideas_and_stops_at_it(tmp_path, monkeypatch):
    from .chatworld import World

    w = World(tmp_path, monkeypatch, plan=True)
    w.app.dispatch("POST", "/api/commands/pc", {}, {"path": str(w.root), "line": "/build accepted at most $0.0002",
                                                    "confirmed": True})
    for j in list(w.app.jobs.jobs.values()):
        wait(w.app, j.view())
    j = next(iter(w.app.jobs.jobs.values()))
    assert j.status == "done" and j.result["status"] != "done", j.error
    assert w.orch.project.meta()["plan_approved"] is True
