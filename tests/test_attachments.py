"""The message box: pictures and files with an idea, @file references, drafts, caps, queue and steer."""

import base64
import io
import json
import os

import pytest

from roundtable import attachments as att
from roundtable.harness.config import parse_config

from .test_harness import RAW, Brain, make
from .test_ui import app, call, wait_job  # noqa: F401  (the app fixture)

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


def images_in(messages):
    first = messages[0]["content"]
    return [b for b in first if isinstance(b, dict) and b.get("type") == "image"] if isinstance(first, list) else []


def text_of(content):
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))


class SeeingBrain(Brain):
    """Remembers the first message of every planning call."""

    def __init__(self):
        super().__init__()
        self.planner_firsts = []

    def __call__(self, model, system, messages, tools):
        if "submit_plan" in {t.name for t in tools} and messages[-1]["role"] == "user":
            self.planner_firsts.append(messages[0])
        return super().__call__(model, system, messages, tools)


@pytest.fixture(autouse=True)
def _attach_api(monkeypatch):
    """Until the coordinator adds "attachapi" to FEATURE_APIS in ui/server.py."""
    from roundtable.ui import server

    if "attachapi" not in server.FEATURE_APIS:
        monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "attachapi"))


# -- a picture reaches the planner ---------------------------------------------------------------------
def test_a_picture_with_the_idea_reaches_the_planner_as_picture_content(tmp_path):
    brain = SeeingBrain()
    orch, a, *_ = make(tmp_path, brain=brain)
    att.project_folder(orch.project.root).add("sketch.png", PNG, scope="goal", goal_index=0)
    orch.start("bakery site", require_approval=True)
    assert orch.run() == "awaiting_approval"
    first = brain.planner_firsts[0]
    [img] = images_in([first])
    assert img["media_type"] == "image/png" and base64.b64decode(img["data"]) == PNG
    assert "sketch.png" in text_of(first["content"]) and "shown below" in text_of(first["content"])
    # the conversation itself isn't changed: only the request sent
    assert all(isinstance(c["messages"][0]["content"], list) for c in a.calls if c["messages"])


def test_a_model_that_cant_see_gets_the_name_and_size():
    cfg = parse_config({**json.loads(json.dumps(RAW)), "providers": {
        **RAW["providers"], "deepseek": {"type": "openai_compat", "base_url": "https://example.invalid"},
        "claude": {"type": "anthropic"}, "or": {"type": "openai_compat", "base_url": "https://example.invalid"}}})
    assert not att.can_see(cfg, "deepseek/deepseek-v4-flash")
    assert att.can_see(cfg, "claude/claude-opus-5-5")
    assert att.can_see(cfg, "or/openai/gpt-5.1") and not att.can_see(cfg, "or/some-text-model")
    assert att.can_see(cfg, "or/some-text-model", att.Settings(vision={"text-model": True}))
    assert not att.can_see(cfg, "img/pic")  # an image maker isn't a reader


def test_blind_models_and_provider_formats(tmp_path):
    cfg = parse_config({**json.loads(json.dumps(RAW)), "providers": {
        **RAW["providers"], "deepseek": {"type": "openai_compat"}, "claude": {"type": "anthropic"},
        "oai": {"type": "openai_compat"}}})
    att.project_folder(tmp_path).add("photo.png", PNG, scope="goal")
    att.project_folder(tmp_path).add("notes.txt", b"use blue and gold", scope="note")
    text, blocks = att.attachment_content(cfg, "deepseek/deepseek-v4-flash", tmp_path)
    assert blocks == [] and "photo.png" in text and "can't see pictures" in text and "use blue and gold" in text
    _, [b] = att.attachment_content(cfg, "claude/claude-opus-5-5", tmp_path)
    assert b["type"] == "image" and b["source"]["type"] == "base64" and b["source"]["media_type"] == "image/png"
    _, [b] = att.attachment_content(cfg, "oai/gpt-5.1", tmp_path)
    assert b["type"] == "image_url" and b["image_url"]["url"].startswith("data:image/png;base64,")
    # a blind model's request stays plain text
    msgs = att.request_with_attachments(cfg, "deepseek/deepseek-v4-flash", [{"role": "user", "content": "plan"}],
                                        tmp_path, "orchestrator", {})
    assert isinstance(msgs[0]["content"], str) and "photo.png" in msgs[0]["content"]


def test_workers_can_be_left_out_and_chat_files_go_only_with_their_question(tmp_path):
    cfg = parse_config({**json.loads(json.dumps(RAW)), "attachments": {"to_workers": False}})
    f = att.project_folder(tmp_path)
    f.add("idea.png", PNG, scope="goal")
    assert att.attachment_content(cfg, "a/coder", tmp_path, "coder")[1] == []
    assert len(att.attachment_content(cfg, "a/planner", tmp_path, "orchestrator")[1]) == 1
    chat = f.add("question.png", PNG, scope="chat", pending=True)
    assert len(att.attachment_content(cfg, "a/planner", tmp_path, "orchestrator")[1]) == 2
    att.finish_chat(tmp_path, [chat["id"]])
    assert len(att.attachment_content(cfg, "a/planner", tmp_path, "orchestrator")[1]) == 1


def test_a_task_worktree_finds_its_project(tmp_path):
    wt = tmp_path / "proj" / ".harness" / "worktrees" / "T1"
    assert att.project_root_of(wt) == (tmp_path / "proj").resolve()
    assert att.project_root_of(tmp_path / "proj") == (tmp_path / "proj").resolve()


# -- @file -------------------------------------------------------------------------------------------------
def test_at_file_attaches_the_files_content(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "menu.py").write_bytes(b"PRICES = {'bun': 2}\n")
    assert att.references("Change @src/menu.py, ask me@example.com, see @src/menu.py.") == ["src/menu.py"]
    added, problems = att.attach_references(root, "Make @src/menu.py cheaper; thanks @Sam", att.project_folder(root))
    assert problems == [] and [x["ref"] for x in added] == ["src/menu.py"]
    assert att.project_folder(root).read(added[0]) == b"PRICES = {'bun': 2}\n"
    assert att.project_files(root, "men") == ["src/menu.py"]


@pytest.mark.parametrize("rel", ["../secret.txt", "/etc/passwd", "~/x", ".git/config", ".harness/project.json",
                                 "src/../../secret.txt", "C:/Windows/win.ini"])
def test_paths_outside_the_project_are_refused(tmp_path, rel):
    root = tmp_path / "proj"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text("x")
    (root / ".harness").mkdir()
    (root / ".harness" / "project.json").write_text("{}")
    (tmp_path / "secret.txt").write_text("no")
    with pytest.raises(att.AttachmentError):
        att.inside(root, rel)
    _, problems = att.attach_references(root, f"look at @{rel}", att.project_folder(root))
    assert not att.project_folder(root).items()


def test_a_link_out_of_the_project_is_refused(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("no")
    try:
        os.symlink(tmp_path / "secret.txt", root / "link.txt")
    except (OSError, NotImplementedError):
        pytest.skip("no symbolic links here")
    with pytest.raises(att.AttachmentError):
        att.inside(root, "link.txt")


# -- drafts and caps ------------------------------------------------------------------------------------------
def test_a_draft_survives(tmp_path):
    d = att.Draft(tmp_path, "new-idea")
    d.save_text("a bakery site with a menu", "steer")
    d.add("logo.png", PNG)
    again = att.Draft(tmp_path, "new-idea").view()  # as after closing and opening the app
    assert again["text"] == "a bakery site with a menu" and again["mode"] == "steer"
    [item] = again["items"]
    assert item["name"] == "logo.png" and item["kind"] == "image" and item["preview"].startswith("data:image/png")
    assert att.Draft(tmp_path, "chat:other").view()["text"] == ""
    att.Draft(tmp_path, "new-idea").clear()
    assert att.Draft(tmp_path, "new-idea").empty


def test_size_caps(tmp_path):
    s = att.Settings(max_mb=0.001, max_files=2, max_total_mb=0.002)
    f = att.Folder(tmp_path / "f")
    with pytest.raises(att.AttachmentError, match="too big"):
        f.add("big.txt", b"x" * 2000, s)
    f.add("a.txt", b"x" * 900, s)
    with pytest.raises(att.AttachmentError, match="Together"):
        f.add("b.txt", b"x" * 900 + b"y" * 300, att.Settings(max_mb=1, max_files=5, max_total_mb=0.002))
    f.add("b.txt", b"y", s)
    with pytest.raises(att.AttachmentError, match="most files"):
        f.add("c.txt", b"z", s)
    with pytest.raises(att.AttachmentError, match="empty"):
        att.Folder(tmp_path / "g").add("e.txt", b"", s)
    assert att.safe_name("../../evil/..\\x.png") == "x.png"


def test_big_pictures_are_made_smaller(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    Image.new("RGB", (3000, 1500), (200, 120, 40)).save(buf, "PNG")
    item = att.Folder(tmp_path).add("wide.png", buf.getvalue(), att.Settings(image_px=1000))
    assert (item["width"], item["height"]) == (1000, 500) and item["mime"] == "image/jpeg"


def test_a_file_comes_in_parts(tmp_path):
    data = PNG * 3
    b64 = base64.b64encode(data).decode()
    r = att.upload_part(tmp_path, "k", "p.png", b64[:40], last=False)
    r = att.upload_part(tmp_path, "k", "p.png", b64[40:], upload_id=r["upload_id"], last=True)
    assert att.Draft(tmp_path, "k").folder.read(att.Draft(tmp_path, "k").folder.items()[0]) == data
    with pytest.raises(att.AttachmentError):
        att.upload_part(tmp_path, "other", "p.png", b64, upload_id=r.get("upload_id", "nope"))


# -- steer: into the running task's next step -----------------------------------------------------------------
def test_steer_reaches_the_next_step_and_stays_put(tmp_path):
    cfg = parse_config(json.loads(json.dumps(RAW)))
    (tmp_path / ".harness").mkdir()
    state = {}
    msgs = [{"role": "user", "content": "do T1"}]
    assert att.request_with_attachments(cfg, "a/coder", msgs, tmp_path, "coder", state) == msgs
    msgs += [{"role": "assistant", "content": "", "tool_calls": []}, {"role": "tool", "content": "ok", "tool_call_id": "1"}]
    att.steer_now(tmp_path, "make the buttons gold")
    sent = att.request_with_attachments(cfg, "a/coder", msgs, tmp_path, "coder", state)
    assert "make the buttons gold" in sent[2]["content"] and msgs[2]["content"] == "ok"
    msgs += [{"role": "assistant", "content": "", "tool_calls": []}, {"role": "tool", "content": "ok2", "tool_call_id": "2"}]
    again = att.request_with_attachments(cfg, "a/coder", msgs, tmp_path, "coder", state)
    assert again[2] == sent[2] and "gold" not in again[4]["content"]  # the same earlier request every step
    # a conversation that starts later gets it as an instruction instead (queue), not as a steer
    assert "gold" not in str(att.request_with_attachments(cfg, "a/coder", msgs[:1], tmp_path, "coder", {}))


# -- through the app's API ----------------------------------------------------------------------------------------
def test_new_idea_with_a_picture_through_the_api(app):  # noqa: F811
    brain = SeeingBrain()
    app.cfg().register("a", __import__("roundtable.providers.scripted", fromlist=["x"]).ScriptedProvider("a", brain))
    call(app, "POST", "/api/attach/draft", {"key": "new-idea", "text": "a bakery site"})
    b64 = base64.b64encode(PNG).decode()
    up = call(app, "POST", "/api/attach/upload", {"key": "new-idea", "name": "shop.png", "data": b64})
    assert up["draft"]["items"][0]["name"] == "shop.png"
    assert call(app, "GET", "/api/attach/draft", key="new-idea")["text"] == "a bakery site"
    r = call(app, "POST", "/api/attach/start", {"key": "new-idea", "wizard": {"idea": {"other": "a bakery site"}}})
    assert "with 1 attached" in r["reply"]
    assert wait_job(app, r["job"]["id"])["status"] == "done"
    assert images_in([brain.planner_firsts[0]])
    assert "shop.png" in text_of(brain.planner_firsts[0]["content"])
    assert call(app, "GET", "/api/attach/draft", key="new-idea")["items"] == []  # sent: the draft is empty
    [item] = call(app, "GET", "/api/attach/list", project=r["path"])["items"]
    assert item["scope"] == "goal" and item["goal_index"] == 0


def test_notes_queue_or_steer_and_chat_through_the_api(app):  # noqa: F811
    r = call(app, "POST", "/api/attach/start", {"key": "n", "wizard": {"idea": {"other": "a tea shop"}}})
    wait_job(app, r["job"]["id"])
    path = r["path"]
    (__import__("pathlib").Path(path) / "menu.txt").write_text("green tea 2", encoding="utf-8")
    assert call(app, "GET", "/api/attach/files", project=path, q="menu")["files"] == ["menu.txt"]
    call(app, "POST", "/api/attach/draft", {"key": "note", "text": "change @menu.txt prices", "mode": "steer"})
    s = call(app, "POST", "/api/attach/send", {"key": "note", "path": path, "as": "note"})
    assert s["delivered"] == "queue" and "Nothing is working" in s["reply"]  # not running: it waits
    assert [x["ref"] for x in s["items"]] == ["menu.txt"]
    with pytest.raises(Exception):
        call(app, "GET", "/api/attach/files", project="/etc")
    c = call(app, "POST", "/api/attach/send", {"key": "chat", "path": path, "as": "chat", "text": "how is it going?"})
    assert c["delivered"] == "chat"


def test_steer_while_a_task_runs_goes_to_it_now(app):  # noqa: F811
    import threading

    r = call(app, "POST", "/api/attach/start", {"key": "s", "wizard": {"idea": {"other": "a cake shop"}}})
    wait_job(app, r["job"]["id"])
    gate = threading.Event()
    app.jobs.start("run", "busy", lambda job: gate.wait(5), target=r["path"])
    try:
        s = call(app, "POST", "/api/attach/send", {"key": "s2", "path": r["path"], "as": "note", "mode": "steer",
                                                    "text": "use pink icing"})
    finally:
        gate.set()
    assert s["delivered"] == "steer"
    [row] = att.steers(r["path"])
    assert row["text"] == "use pink icing"


def test_a_typed_new_project_with_a_file(app):  # noqa: F811
    call(app, "POST", "/api/attach/draft", {"key": "typed", "text": "a jam shop"})
    call(app, "POST", "/api/attach/upload", {"key": "typed", "name": "brief.txt",
                                              "data": base64.b64encode(b"jars, labels").decode()})
    r = call(app, "POST", "/api/attach/start", {"key": "typed", "dir": "jam", "approve": True})
    assert wait_job(app, r["job"]["id"])["result"]["status"] == "awaiting_approval"
    [item] = call(app, "GET", "/api/attach/list", project=r["path"])["items"]
    assert item["kind"] == "text" and item["name"] == "brief.txt"
