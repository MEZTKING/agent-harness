"""Wave 8 end to end, scripted: one made-up project goes through the new pieces together, with no network and no
keys. The checker may only read and the builder is Careful; the build's words are streamed as they are written;
a delete waits for the owner and is refused; a card is moved on the board (left out); a hand edit is made
and put back; a program on this computer starts a new idea through a local hook, which waits for the owner's OK;
and the stand-up writes its one line in the journal without calling a model."""

from __future__ import annotations

import io
import json
import threading
import time

import pytest
import yaml

from roundtable import asks as asklib
from roundtable import automation as au
from roundtable import reach
from roundtable.core.config import parse_config as parse_hub
from roundtable.core.store import FileStore
from roundtable.harness import gate as g
from roundtable.harness import streamlog
from roundtable.harness.config import parse_config
from roundtable.harness.gate import Gate
from roundtable.harness.orchestrator import Orchestrator, Project
from roundtable.hub.service import Hub
from roundtable.harness.tools import Tool, ToolSpec, _obj
from roundtable.providers.scripted import ScriptedImages, ScriptedProvider, reply

from .test_automation import PC
from .test_harness import RAW, Brain, tool_names


class SweepBrain(Brain):
    """The usual scripted plan; T1's builder also tries to delete a file, and every reviewer's tools are kept."""

    def __init__(self):
        super().__init__()
        self.review_tools: list[set[str]] = []
        self.told: list[str] = []

    def __call__(self, model, system, messages, tools):
        names = tool_names(tools)
        if "submit_review" in names and messages[-1]["role"] != "tool":
            self.review_tools.append(names)
        if "finish_task" in names and "# Your task [T1]" in messages[0]["content"]:
            n = sum(1 for m in messages if m["role"] == "assistant")
            if n == 0:
                return reply("Writing hello.py now, then tidying up.",
                             calls=[("write_file", {"path": "hello.py", "content": "print('hi')\n"})])
            if n == 1:
                return reply(calls=[("delete_file", {"path": "hello.py"})])
            if n == 2:
                self.told.append(messages[-1]["content"])
                return reply(calls=[("finish_task", {"summary": "hello.py prints hi"})])
        return super().__call__(model, system, messages, tools)


class WithDelete(Orchestrator):
    """A builder that has a tool that deletes a file (as a plug-in or a tool server would give it)."""

    def _part_tools(self, box, role):
        super()._part_tools(box, role)
        if "write_file" in box.tools and "delete_file" not in box.tools:
            ws = self.ws
            box.add(Tool(ToolSpec("delete_file", "Delete a file of the project.", _obj({"path": {"type": "string"}}, ["path"])),
                         lambda a: (ws.path(a["path"]).unlink(), "deleted")[-1]))


def refuse_every_card(root, stop, seen):
    """The owner's "Don't allow" on every card that appears, at once."""
    while not stop.is_set():
        for c in asklib.command_asks(root):
            if c["id"] not in [s["id"] for s in seen]:
                seen.append(c)
                Gate(root).answer(c["source"]["command"], g.DENY)
        time.sleep(0.01)


def test_one_project_through_every_wave_8_piece(tmp_path, monkeypatch):
    monkeypatch.setenv("ROUNDTABLE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv(g.ENV, raising=False)
    cfg = parse_config(json.loads(json.dumps(RAW)))
    brain = SweepBrain()
    cfg.register("a", ScriptedProvider("a", brain, chunks=6))  # the words come in pieces of six letters
    cfg.register("b", ScriptedProvider("b", brain))
    images = ScriptedImages()
    cfg.register("img", images)
    cfg.lab_dir = tmp_path / "lab"
    root = tmp_path / "proj"
    orch = WithDelete(cfg, root, on_event=lambda k, d: None)

    # the words as they are written, kept beside what the run writes
    pieces: list[tuple[str, str, str]] = []
    real_sink = streamlog.sink

    def sink(r, task):
        inner = real_sink(r, task)

        def take(kind, piece):
            pieces.append((task, kind, piece))
            return inner(kind, piece)
        return take
    monkeypatch.setattr(streamlog, "sink", sink)

    # plan first; the checker may only read, the builder is Careful
    orch.start("build a bakery site", require_approval=True)
    (root / ".harness" / "project.yaml").write_text(
        yaml.safe_dump({"ask_first": "off", "perms": {"coder": "careful", "reviewer": "read_only"}}), encoding="utf-8")
    assert orch.run() == "awaiting_approval"

    # the board: the logo is left out by hand before the build starts
    moved = orch.move_task("T2", "left_out")
    assert moved["column"] == "left_out"
    board = {c["id"]: [x["id"] for x in c["cards"]] for c in orch.board()["columns"]}
    assert "T2" in board.get("left_out", [])

    orch.approve()
    orch.ws.gate = Gate(root, cfg, poll=0.02, timeout=5)
    stop, seen = threading.Event(), []
    watcher = threading.Thread(target=refuse_every_card, args=(root, stop, seen), daemon=True)
    watcher.start()
    try:
        assert orch.run() == "done"
    finally:
        stop.set()
        watcher.join(2)

    # streamed: T1's words arrived in pieces, and the run's live words were cleared at the end
    t1 = "".join(p for task, kind, p in pieces if task == "T1" and kind == "text")
    assert t1.startswith("Writing hello.py now") and len([p for p in pieces if p[0] == "T1"]) > 2
    assert not list(streamlog.path(root, "T1").parent.glob("*.words"))
    # the delete waited for the owner and was refused; the file is still there
    assert [c["command"] for c in seen] == ["Delete hello.py"] or seen[0]["command"].startswith("Delete hello.py")
    assert (root / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert brain.told and "didn't allow" in brain.told[0]
    # the checker could only read: no tool that writes or runs anything was offered to it
    assert brain.review_tools and all(not ({"write_file", "edit_file", "run_command"} & t) for t in brain.review_tools)
    # the left-out logo was never drawn
    assert images.prompts == []
    board = {c["id"]: [x["id"] for x in c["cards"]] for c in orch.board()["columns"]}
    assert "T2" in board.get("left_out", [])

    # a hand edit from the app, then put back
    from roundtable.ui import server

    orch._register_with_lab()
    app = server.UIApp(str(tmp_path / "missing-hub.yaml"), "missing.yaml", projects_dir=str(tmp_path / "projects"))
    app.cfg = lambda: cfg
    d = app.dispatch("GET", "/api/files/edit", {"path": [str(root)], "file": ["hello.py"]}, {})
    app.dispatch("POST", "/api/files/save", {}, {"path": str(root), "file": "hello.py", "text": "print('bread')\n",
                                                 "base": d["base"]})
    assert (root / "hello.py").read_text(encoding="utf-8") == "print('bread')\n"
    edit = app.dispatch("GET", "/api/files/edits", {"path": [str(root)]}, {})["edits"][0]
    back = app.dispatch("POST", "/api/files/undo_edit", {}, {"path": str(root), "id": edit["id"]})
    assert back["ok"] and (root / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"

    # a program on this computer starts a new idea through a local hook; it waits for the owner's OK
    home = tmp_path / "home"
    secret = reach.new_secret()
    hook = au.add(home, {"kind": "local", "hook": {"secret": secret}, "start_by_itself": True, "cap_usd": 5})
    assert hook["start_by_itself"] is False
    body = json.dumps({"title": "Add a basket page", "text": "Customers want a basket."}).encode()
    status, _ = reach.receive(home, [hook], f"/hooks/{hook['id']}", "127.0.0.1",
                              {"Host": "127.0.0.1", "Content-Length": str(len(body)), reach.SECRET_HEADER: secret,
                               "Content-Type": "application/json"}, io.BytesIO(body))
    assert status == 202
    [r] = au.tick(cfg, home=home, machine=PC, projects_dir=tmp_path / "ideas")
    [made] = list((tmp_path / "ideas").iterdir())
    assert Project(made).meta()["goals"][0].startswith("Add a basket page")
    assert Project(made).meta()["status"] == "awaiting_approval"

    # the stand-up: one line in the journal, and no model is called for it
    class NoModel:
        def __getattr__(self, name):
            raise AssertionError("the stand-up must not call a model")

    monkeypatch.setattr(type(cfg), "provider", lambda self, name: NoModel())
    hub = Hub(parse_hub({"storage": {"type": "file", "path": "data"}, "default_policy": "allow",
                         "agents": {"me": {"repo": "me/me"}}}, tmp_path / "hub" / "hub.yaml"),
              store=FileStore(tmp_path / "hub" / "data"))
    reach.standup(au.Ctx(cfg=cfg, home=home, hub=hub, machine=PC))
    notes = hub.journal.entries("me", kinds=["note"])
    assert len(notes) == 1 and notes[0]["text"].startswith("Stand-up:")


@pytest.mark.parametrize("route", ["/api/board", "/api/stream", "/api/perms", "/api/ci", "/api/git/log"])
def test_the_phone_sees_wave_8_read_only(route):
    from roundtable.phone import phone_allowed

    assert phone_allowed("GET", route) and not phone_allowed("POST", route)
