"""Show it (pictures of the app after each approved task) and the Live and Session views."""

import json
import os
import urllib.error
import urllib.request

import pytest
import yaml

from roundtable.harness import session as sessionlib
from roundtable.harness import showit
from roundtable.providers.scripted import reply

from .test_harness import RAW, Brain, make, tool_names

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
FAKE_KEY = "sk-" + "abcdefghijklmnopqrstuvwxyz0123"
PAGE = "<!doctype html><html><head><title>Tiny Timer</title><link rel=stylesheet href=style.css></head><body>ok</body></html>"
WEB_PLAN = [
    {"id": "W1", "title": "the page", "role": "coder", "description": "make index.html", "acceptance": "it opens",
     "depends_on": []},
    {"id": "W2", "title": "dark mode", "role": "coder", "description": "add dark mode", "acceptance": "dark works",
     "depends_on": ["W1"]},
]
WORK = {
    "W1": [("I'll start with the page.", "write_file", {"path": "index.html", "content": PAGE}),
           ("", "write_file", {"path": "style.css", "content": "body { color: red; }\n"}),
           ("", "edit_file", {"path": "style.css", "old_text": "color: red;", "new_text": "color: navy;\n  margin: 0;"}),
           ("", "write_file", {"path": "img/logo.svg", "content": "<svg xmlns='http://www.w3.org/2000/svg'/>"}),
           ("Checking it runs.", "run_command", {"command": f"echo token={FAKE_KEY} && echo fine"})],
    "W2": [("", "edit_file", {"path": "style.css", "old_text": "margin: 0;",
                              "new_text": "margin: 0; }\n@media (prefers-color-scheme: dark) { body { color: white;"})],
}


class WebBrain(Brain):
    """A coder that builds a tiny web page step by step; the reviewer approves."""

    def __init__(self):
        super().__init__(plan=WEB_PLAN)

    def __call__(self, model, system, messages, tools):
        if "finish_task" not in tool_names(tools):
            return super().__call__(model, system, messages, tools)
        tid = messages[0]["content"].split("# Your task [", 1)[1].split("]", 1)[0]
        done = sum(1 for m in messages if m["role"] == "tool")
        steps = WORK[tid]
        if done < len(steps):
            text, name, args = steps[done]
            return reply(text, calls=[(name, args)])
        return reply(calls=[("finish_task", {"summary": f"{tid} built"})])


def fake_renderer(calls=None):
    def render(jobs):
        for j in jobs:
            open(j["png"], "wb").write(PNG)
            open(j["jpg"], "wb").write(b"\xff\xd8\xff" + j["kind"].encode())
        if calls is not None:
            calls.append(jobs)
        return [{"kind": j["kind"], "errors": ["Uncaught TypeError: x is undefined"] if j["kind"] == "phone" else [],
                 "title": "Tiny Timer"} for j in jobs]
    return render


def hub_raw(tmp_path):
    from .test_hub import RAW as HUB_RAW

    raw = json.loads(json.dumps(HUB_RAW))
    raw["storage"] = {"type": "file", "path": str(tmp_path / "hubdata")}
    raw["agents"]["proj"] = {"description": "the project"}
    (tmp_path / "hub.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    hraw = json.loads(json.dumps(RAW))
    hraw["hub"] = {"config": str(tmp_path / "hub.yaml"), "agent": "harness"}
    return hraw


def built(tmp_path, raw=RAW, render=None, **over):
    raw = json.loads(json.dumps(raw))
    raw.update(over)
    orch, *_rest, events = make(tmp_path, raw=raw, brain=WebBrain())
    calls = []
    orch.shot_renderer = render or fake_renderer(calls)
    orch.start("a tiny timer page")
    assert orch.run() == "done"
    return orch, events, calls


def test_pictures_after_each_approved_task_saved_and_announced(tmp_path):
    orch, events, calls = built(tmp_path)
    root = orch.project.root
    shots = root / ".harness" / "shots"
    for tid in ("W1", "W2"):
        rec = json.loads((shots / tid / "shots.json").read_text(encoding="utf-8"))
        assert rec["task"] == tid and rec["title"] == "Tiny Timer" and rec["entry"] == "index.html"
        assert rec["errors"] == ["Uncaught TypeError: x is undefined"]
        assert (shots / tid / "desktop.png").read_bytes() == PNG and (shots / tid / "phone.png").is_file()
    # dark only once the page answers the computer's dark mode (W2 added it)
    assert [j["kind"] for j in calls[0]] == ["desktop", "phone"]
    assert [j["kind"] for j in calls[1]] == ["desktop", "phone", "dark"]
    assert calls[1][0]["width"] == 1280 and calls[1][1]["height"] == 844 and calls[1][2]["dark"] is True
    assert calls[0][0]["url"].startswith("http://127.0.0.1:") and calls[0][0]["url"].endswith("/index.html")
    assert json.loads((shots / "latest.json").read_text(encoding="utf-8"))["task"] == "W2"
    shot_events = [d for k, d in events if k == "shots"]
    assert [d["task"] for d in shot_events] == ["W1", "W2"] and shot_events[1]["pictures"] == ["desktop", "phone", "dark"]


def test_the_static_server_really_serves_the_folder_while_pictures_are_taken(tmp_path):
    seen = {}

    def render(jobs):
        with urllib.request.urlopen(jobs[0]["url"]) as r:
            seen["page"] = r.read().decode()
            seen["type"] = r.headers["Content-Type"]
        try:
            urllib.request.urlopen(jobs[0]["base"] + ".harness/project.json")
        except urllib.error.HTTPError as e:
            seen["hidden"] = e.code
        return fake_renderer()(jobs)

    built(tmp_path, render=render)
    assert "Tiny Timer" in seen["page"] and seen["type"].startswith("text/html") and seen["hidden"] == 404


def test_off_or_no_screens_means_no_pictures(tmp_path):
    orch, events, calls = built(tmp_path / "a", show_it="off")
    assert not calls and not (orch.project.root / ".harness" / "shots").exists()
    assert not [k for k, _ in events if k == "shots"]
    # a project without screens (no page, has_ui not set): nothing either
    orch2, *_r, events2 = make(tmp_path / "b")
    seen = []
    orch2.shot_renderer = fake_renderer(seen)
    orch2.start("a python greeter")
    assert orch2.run() == "done"
    assert not seen and not [k for k, _ in events2 if k == "shots"]


def test_a_renderer_failure_is_written_down_not_fatal(tmp_path):
    def broken(jobs):
        raise RuntimeError("chromium crashed")

    orch, events, _ = built(tmp_path, render=broken)
    rec = json.loads((orch.project.root / ".harness" / "shots" / "W1" / "shots.json").read_text(encoding="utf-8"))
    assert "chromium crashed" in rec["failed"] and rec["pictures"] == {}
    assert all(t.status == "done" for t in orch.project.tasks())
    assert "chromium crashed" in next(d for k, d in events if k == "shots")["note"]


def test_without_playwright_it_says_so(tmp_path, monkeypatch):
    from roundtable.harness import look

    monkeypatch.setattr(look, "renderer", lambda: None)
    (tmp_path / "index.html").write_text(PAGE, encoding="utf-8")
    rec = showit.take_shots(tmp_path, "T1")
    assert "Playwright isn't installed" in rec["note"] and rec["pictures"] == {}


def test_without_a_workspace_a_start_command_is_not_run_and_the_page_still_shown(tmp_path):
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "index.html").write_text(PAGE, encoding="utf-8")
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}}), encoding="utf-8")
    rec = showit.take_shots(tmp_path, "T1", render=fake_renderer())
    assert rec["entry"] == "public/index.html" and rec["note"] == "" and "desktop" in rec["pictures"]
    assert "started" not in rec  # starting it needs the task's workspace (the gate): test_appserver.py


def test_pictures_go_to_the_hub_and_old_ones_are_pruned(tmp_path, monkeypatch):
    monkeypatch.setattr(showit, "HUB_KEEP", 1)
    orch, *_ = built(tmp_path, raw=hub_raw(tmp_path))
    hub = tmp_path / "hubdata" / "plans" / "shots" / "proj"
    latest = json.loads((hub / "latest.json").read_text(encoding="utf-8"))
    assert latest["task"] == "W2" and latest["pictures"] == {"desktop": "latest-desktop.jpg", "phone": "latest-phone.jpg",
                                                             "dark": "latest-dark.jpg"}
    assert (hub / "latest-desktop.jpg").read_bytes().startswith(b"\xff\xd8\xff")
    assert [h["task"] for h in latest["history"]] == ["W2"]
    assert (hub / "W2-desktop.jpg").is_file() and not (hub / "W1-desktop.jpg").exists()  # pruned
    sess = json.loads((hub / "session.json").read_text(encoding="utf-8"))
    assert sess["task"]["id"] == "W2" and sess["task"]["status"] == "done"
    lines = [s["line"] for s in sess["task"]["steps"]]
    assert any(ln.startswith("● Edit style.css") for ln in lines)
    w1 = sessionlib.hub_session(orch.project.root, "p")  # only the latest task; no contents, no keys
    assert "margin" not in json.dumps(sess) and FAKE_KEY not in json.dumps(w1)


def test_the_hub_keeps_the_latest_set_plus_one_per_task(tmp_path):
    from roundtable.core.store import FileStore

    store = FileStore(tmp_path / "hub")
    root = tmp_path / "proj"
    (root).mkdir()
    (root / "index.html").write_text(PAGE, encoding="utf-8")
    prev = None
    for i in range(1, 25):
        rec = showit.take_shots(root, f"T{i}", render=fake_renderer())
        files = showit.hub_files(root, rec, prev, "plans/shots/p")
        store.write_json(files, "x")
        prev = store.read_json("plans/shots/p/latest.json")
    names = sorted(p.name for p in (tmp_path / "hub" / "plans" / "shots" / "p").iterdir())
    assert len([n for n in names if n.startswith("T")]) == showit.HUB_KEEP
    assert "T24-desktop.jpg" in names and "T4-desktop.jpg" not in names and "T5-desktop.jpg" in names
    assert len(prev["history"]) == showit.HUB_KEEP


def test_safe_path_refuses_climbing_out_hidden_files_and_links(tmp_path):
    root = tmp_path / "proj"
    (root / "css").mkdir(parents=True)
    (root / "css" / "a.css").write_text("x", encoding="utf-8")
    (root / ".env").write_text("KEY=1", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("no", encoding="utf-8")
    assert showit.safe_path(root, "css/a.css") == (root / "css" / "a.css").resolve()
    for bad in ("../secret.txt", "css/../../secret.txt", "/etc/passwd", str(tmp_path / "secret.txt"), "C:/x",
                ".env", ".harness/project.json", "css\\..\\..\\secret.txt", "", "nope.css"):
        assert showit.safe_path(root, bad) is None, bad
    if hasattr(os, "symlink"):
        os.symlink(tmp_path / "secret.txt", root / "link.txt")
        os.symlink(tmp_path, root / "up")
        assert showit.safe_path(root, "link.txt") is None and showit.safe_path(root, "up/secret.txt") is None
    assert showit.content_type(root / "x.js").startswith("text/javascript")
    assert showit.content_type(root / "x.svg").startswith("image/svg+xml")
    assert showit.content_type(root / "x.woff2") == "font/woff2" and showit.content_type(root / "x.wasm") == "application/wasm"


# -- the desktop app's routes ------------------------------------------------------------------
def ui_for(orch, tmp_path):
    from roundtable.ui.server import UIApp

    app = UIApp(None, "missing.yaml")
    orch.cfg.lab_dir = tmp_path / "lab"
    orch.base_cfg.lab_dir = tmp_path / "lab"
    app.cfg = lambda: orch.cfg
    orch._register_with_lab()
    return app


def test_the_preview_server_serves_only_the_projects_files_with_the_right_types(tmp_path):
    orch, *_ = built(tmp_path)
    app = ui_for(orch, tmp_path)
    root = orch.project.root
    (tmp_path / "outside.txt").write_text("private", encoding="utf-8")
    if hasattr(os, "symlink"):
        os.symlink(tmp_path / "outside.txt", root / "sneaky.txt")
    app.preview.start()
    try:
        live = app.dispatch("GET", "/api/project/live", {"path": [str(root)]}, {})
        assert live["entry"] == "index.html" and live["preview"].endswith("/index.html")
        assert live["latest"]["task"] == "W2" and [h["task"] for h in live["history"]] == ["W2", "W1"]
        base = live["preview"].rsplit("/", 1)[0] + "/"
        with urllib.request.urlopen(base + "index.html") as r:
            assert r.headers["Content-Type"] == "text/html; charset=utf-8"
            assert "frame-ancestors" in r.headers["Content-Security-Policy"]
        with urllib.request.urlopen(base + "style.css") as r:
            assert r.headers["Content-Type"].startswith("text/css")
        with urllib.request.urlopen(base + "img/logo.svg") as r:
            assert r.headers["Content-Type"].startswith("image/svg+xml")
        for bad in ("../outside.txt", "%2e%2e/outside.txt", "sneaky.txt", ".harness/project.json", ".git/config",
                    "..%2f..%2foutside.txt"):
            with pytest.raises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(base + bad)
            assert e.value.code == 404, bad
        with pytest.raises(urllib.error.HTTPError):  # an unknown project key
            urllib.request.urlopen(app.preview.origin + "/0000000000000000/index.html")
        inline = app.dispatch("GET", "/api/project/live", {"path": [str(root)], "inline": ["1"]}, {})
        assert inline["images"]["desktop"].startswith("data:image/jpeg;base64,")
    finally:
        app.preview.stop()


def test_raw_pictures_and_downloads(tmp_path):
    orch, *_ = built(tmp_path)
    app = ui_for(orch, tmp_path)
    root = str(orch.project.root)
    (orch.project.root / "dist").mkdir()
    (orch.project.root / "dist" / "app.apk").write_bytes(b"PK apk")
    body, ctype, headers = app.raw("shot", {"path": [root], "task": ["W1"], "name": ["desktop.png"]})
    assert body == PNG and ctype == "image/png" and "sandbox" in headers["Content-Security-Policy"]
    body, ctype, headers = app.raw("file", {"path": [root], "name": ["dist/app.apk"]})
    assert ctype == "application/octet-stream" and headers["Content-Disposition"].startswith("attachment")
    _, ctype, headers = app.raw("file", {"path": [root], "name": ["index.html"]})  # never shown as a page here
    assert ctype == "application/octet-stream"
    for kind, q in (("shot", {"task": ["../.."], "name": ["project.json"]}), ("file", {"name": ["../x"]}),
                    ("shot", {"task": [".."], "name": ["shots/W1/desktop.png"]})):
        with pytest.raises(FileNotFoundError):
            app.raw(kind, {"path": [root], **q})


def test_the_session_view_has_steps_diffs_outputs_and_hides_keys(tmp_path):
    orch, *_ = built(tmp_path)
    app = ui_for(orch, tmp_path)
    root = str(orch.project.root)
    s = app.dispatch("GET", "/api/project/session", {"path": [root]}, {})
    w1 = s["tasks"][0]
    assert w1["id"] == "W1" and w1["status"] == "done" and w1["cost"] > 0
    kinds = [st["kind"] for st in w1["steps"]]
    assert kinds[0] == "attempt" and "review" in kinds and "shots" in kinds and "finish" in kinds
    say = next(st for st in w1["steps"] if st["kind"] == "say")
    assert say["text"] == "I'll start with the page." and say["who"] == "worker" and say["cost"] > 0
    edit = next(st for st in w1["steps"] if st.get("label") == "Edit style.css")
    assert "-body { color: red; }" in edit["diff"] and "+  margin: 0;" in edit["diff"] and edit["detail"] == "+2 −1"
    write = next(st for st in w1["steps"] if st.get("label") == "Write index.html")
    assert write["detail"].startswith("+1") and "+<!doctype html>" in write["diff"]
    run = next(st for st in w1["steps"] if st.get("tool") == "run_command")
    assert run["detail"] == "passed" and "fine" in run["output"]
    text = json.dumps(s)
    assert FAKE_KEY not in text and "[hidden: looks like a key]" in run["output"]
    review = next(st for st in w1["steps"] if st["kind"] == "review")
    assert review["approved"] is True
    paths = {o["path"]: o for o in s["outputs"]}
    assert paths["img/logo.svg"]["kind"] == "image" and paths["img/logo.svg"]["task"] == "W1"
    assert any(o["path"] == "img/logo.svg" for o in w1["outputs"])
    # the cheap cursor: nothing new means a tiny answer
    again = app.dispatch("GET", "/api/project/session", {"path": [root], "since": [str(s["cursor"])]}, {})
    assert again == {"cursor": s["cursor"], "changed": False}
    compact = app.dispatch("GET", "/api/project/session", {"path": [root], "compact": ["1"]}, {})
    assert compact["task"]["id"] == "W2" and all("line" in st for st in compact["task"]["steps"])


def test_older_events_without_a_kept_diff_still_show_one():
    step = sessionlib.tool_step({"tool": "edit_file", "args": {"path": "a.js", "old_text": "x = 1", "new_text": "x = 2"},
                                 "error": False, "result": "edited a.js"})
    assert step["label"] == "Edit a.js" and "-x = 1" in step["diff"] and step["detail"] == "+1 −1"
    failed = sessionlib.tool_step({"tool": "run_command", "args": {"command": "npm test"}, "error": False,
                                   "result": "exit code: 1\n--- stdout ---\nboom"})
    assert failed["detail"] == "failed (exit 1)" and failed["error"] is True
    assert sessionlib.redact("api_key: abcdefghijklmnop1234") == "api_key: [hidden: looks like a key]"


def test_the_seat_shows_the_newest_picture_and_the_phone_may_ask(tmp_path):
    from roundtable.phone import phone_allowed
    from roundtable.ui.roundtable import run_seat

    orch, *_ = built(tmp_path)
    app = ui_for(orch, tmp_path)
    seat = run_seat(app, orch.project.root)
    assert seat["shot"]["task"] == "W2" and seat["shot"]["url"].startswith("/raw/shot?") and "desktop.jpg" in seat["shot"]["url"]
    assert phone_allowed("GET", "/api/project/live") and phone_allowed("GET", "/api/project/session")


def test_show_it_setting():
    from roundtable.harness.config import parse_config

    assert parse_config(json.loads(json.dumps(RAW))).show_it == "auto"
    assert parse_config({**json.loads(json.dumps(RAW)), "show_it": False}).show_it == "off"
    with pytest.raises(ValueError):
        parse_config({**json.loads(json.dumps(RAW)), "show_it": "sometimes"})


def test_pictures_taken_in_the_same_second_keep_their_order(tmp_path):
    from roundtable.harness import showit

    for i, task in enumerate(["W1", "W2", "W3"], 1):
        d = showit.shots_root(tmp_path) / task
        d.mkdir(parents=True)
        (d / "shots.json").write_text(json.dumps({"task": task, "at": "2026-11-26T15:00:00Z", "seq": i}), encoding="utf-8")
    assert [r["task"] for r in showit.history(tmp_path)] == ["W3", "W2", "W1"]
    assert showit._next_seq(tmp_path) == 4


def test_take_pictures_now_for_a_project_built_before_pictures(tmp_path, monkeypatch):
    """A finished project with no pictures: the owner's "Take pictures now" (remote ``show_it``) takes them
    after the newest finished task and publishes the hub's live files."""
    import shutil

    from roundtable import remote
    from roundtable.harness.orchestrator import Orchestrator

    orch, *_ = built(tmp_path, raw=hub_raw(tmp_path))
    shutil.rmtree(orch.project.root / ".harness" / "shots")
    shutil.rmtree(tmp_path / "hubdata" / "plans" / "shots")
    monkeypatch.setattr(Orchestrator, "shot_renderer", staticmethod(fake_renderer()), raising=False)
    text = remote.execute(orch.cfg, orch.project.root, {"action": "show_it"})
    assert text.startswith("Took 3 pictures") and not remote.is_trouble(text)
    hub = tmp_path / "hubdata" / "plans" / "shots" / "proj"
    assert json.loads((hub / "latest.json").read_text(encoding="utf-8"))["task"] == "W2"
    assert (hub / "session.json").is_file() and (hub / "latest-desktop.jpg").is_file()
    assert "show_it" in remote.LONG


def test_take_pictures_now_says_why_not(tmp_path):
    orch, *_r, _events = make(tmp_path)
    r = orch.show_it_now()
    assert not r["ok"] and r["reply"].startswith("Couldn't take pictures: no task")
