"""Plugins in their own box (plugins/sandbox.py, boxworker.py, guard.py, boxapi.py)."""

import inspect
import json
import os
import sys
import textwrap
import time
from pathlib import Path

import pytest
import yaml

from roundtable.harness.agent import Budget, run_agent
from roundtable.harness.config import ModelRef, load_config
from roundtable.harness.safeenv import is_secret_name
from roundtable.plugins import api, boxapi, guard, manage, sandbox
from roundtable.plugins.builtin import BUILTINS
from roundtable.plugins.host import Loaded, PluginHost, load_builtin, load_installed, plugins_home
from roundtable.plugins.manifest import parse_manifest

from .test_harness import RAW
from .test_plugins import cfg_with, echo_box, two_steps

needs_unix = pytest.mark.skipif(os.name == "nt", reason="the made-up programs here are Unix ones")


def plugin_dir(tmp_path: Path, body: str, pid="boxy", hooks=("on_tool_result",), permissions=(), module=None,
               extra="") -> Path:
    module = module or pid.replace("-", "_") + "_mod"
    d = tmp_path / f"code-{pid}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "roundtable-plugin.toml").write_text(textwrap.dedent(f"""
        id = "{pid}"
        name = "{pid.title()}"
        version = "1.0.0"
        description = "A made-up plugin."
        entry = "{module}:P"
        hooks = {json.dumps(list(hooks))}
        permissions = {json.dumps(list(permissions))}
    """) + extra, encoding="utf-8")
    (d / f"{module}.py").write_text("from roundtable.plugins.api import Plugin, Tool, ToolSpec, ToolError, _obj\n"
                                    + textwrap.dedent(body), encoding="utf-8")
    return d


def boxed(tmp_path, body, granted=(), **kw) -> Loaded:
    d = plugin_dir(tmp_path, body, permissions=granted, **kw)
    pid = kw.get("pid", "boxy")
    item = load_installed(pid, {"path": str(d), "enabled": True, "permissions": list(granted)})
    assert item.status == "on", item.problem
    assert item.boxed and isinstance(item.obj, sandbox.BoxedPlugin)
    return item


def host_with(cfg, *items):
    host = PluginHost([*(load_builtin(m, cfg) for m in BUILTINS), *items], cfg)
    cfg._shared["plugin_host"] = host
    return host


def result_of(item, text, **kw):
    """(ok, text, message) of one on_tool_result through a host."""
    cfg, _ = cfg_with(two_steps)
    host = host_with(cfg, item)
    seen = []
    conv = host.conversation(emit=lambda k, d: seen.append((k, d)), **kw)
    out = conv.on_tool_result("t", {}, text, False)
    msg = next((d["message"] for k, d in seen if k == "plugin_error"), "")
    host.close()
    return item.id not in host.off_this_run, out, msg


TRIES = """
import os, sys
class P(Plugin):
    def on_tool_result(self, ctx, tool, args, text, is_error):
        what = text
        try:
            if what == "socket":
                import socket
                socket.create_connection(("192.0.2.1", 80), timeout=1)
            elif what == "urllib":
                import urllib.request
                urllib.request.urlopen("http://192.0.2.1/", timeout=1)
            elif what == "folder":
                open(os.path.expanduser("~/../made-up-secret.txt")).read()
            elif what == "write":
                open(ctx.data_dir.parent / "someone-else.txt", "w").write("x")
            elif what == "subprocess":
                import subprocess
                subprocess.run([sys.executable, "-c", "pass"])
            elif what == "system":
                os.system("true")
            elif what == "multiprocessing":
                import multiprocessing.util as mu
                mu.spawnv_passfds(os.fsencode(sys.executable), [os.fsencode(sys.executable), b"-c", b"pass"], [])
            elif what == "ctypes":
                import ctypes
            elif what == "secrets":
                import roundtable.core.secrets
            elif what == "gc":
                import gc
                gc.get_objects()
            elif what == "chdir":
                os.chdir("/")
            elif what == "folderfd":
                os.open(os.path.dirname(os.__file__), os.O_RDONLY)
            elif what == "link":
                os.symlink("/", "escape")
        except Exception as e:
            if os.environ.get("RAISE") or what in ("ctypes", "secrets"):
                raise
            return "caught " + type(e).__name__   # caught: the box still reports it
        return "did " + what
"""


@pytest.mark.parametrize("what,words", [
    ("socket", "go on the internet"), ("urllib", "go on the internet"), ("folder", "outside its own folder"),
    ("write", "change a file outside its own folder"), ("subprocess", "run another program"),
    ("system", "run another program"), ("multiprocessing", "run another program"),
    ("ctypes", "compiled code"), ("secrets", "rest of the harness"), ("gc", "look inside the box"),
    ("chdir", "move out of its own folder"), ("folderfd", "open a folder outside"),
    ("link", "make a link"),
])
def test_each_way_out_is_refused_the_plugin_is_off_and_the_owner_reads_why(tmp_path, what, words):
    item = boxed(tmp_path, TRIES)
    ok, out, msg = result_of(item, what)
    assert not ok and out == what  # the text passes unchanged; the plugin is off for this run
    assert words in msg and "Boxy" in msg and "switched off until this run ends" in msg


def test_a_refusal_in_the_middle_of_a_run_and_the_run_carries_on(tmp_path):
    item = boxed(tmp_path, TRIES)
    cfg, _ = cfg_with(two_steps)
    host = host_with(cfg, item)
    events = []
    host.begin_run()
    res = run_agent(cfg, ModelRef("a", "coder"), "sys", "go", echo_box("socket"), Budget(5),
                    on_event=lambda k, d: events.append((k, d)))
    assert res.stop == "done" and item.id in host.off_this_run
    assert "go on the internet" in host.off_this_run[item.id]
    host.begin_run()  # the next run: a fresh box, another chance
    assert host.conversation().on_tool_result("t", {}, "hello", False) == "did hello"
    host.close()


def test_its_own_folder_and_temp_files_are_fine(tmp_path):
    item = boxed(tmp_path, """
        import tempfile, sqlite3, shutil, os
        class P(Plugin):
            def on_tool_result(self, ctx, tool, args, text, is_error):
                (ctx.data_dir / "notes").mkdir(exist_ok=True)
                (ctx.data_dir / "notes" / "a.txt").write_text(text)
                with tempfile.NamedTemporaryFile("w", delete=False) as f:
                    f.write("t")
                db = sqlite3.connect(str(ctx.data_dir / "x.db")); db.execute("create table if not exists t(x)"); db.close()
                shutil.rmtree(ctx.data_dir / "notes")
                import json, mimetypes, zoneinfo, logging, asyncio
                asyncio.run(asyncio.sleep(0))
                ctx.log.info("logged")
                return text.upper() + str(os.getcwd() == str(ctx.data_dir))
    """)
    assert result_of(item, "fine")[:2] == (True, "FINETrue")


def test_a_plugin_with_compiled_parts_is_refused_at_add_and_named(tmp_path, harness):
    d = plugin_dir(tmp_path, "class P(Plugin): pass\n", pid="native-bits")
    (d / ".deps").mkdir()
    (d / ".deps" / "_speed.cpython-313-x86_64-linux-gnu.so").write_bytes(b"\x7fELF")
    asked = []
    with pytest.raises(api.PluginError, match=r"compiled parts \(\.deps/_speed"):
        manage.add_plugin(harness, str(d), lambda m: asked.append(m) or True)
    assert not asked and not (Path(os.environ["ROUNDTABLE_HOME"]) / "plugin-code" / "native-bits").exists()
    # one that asks to run programs may have them
    (d / "roundtable-plugin.toml").write_text((d / "roundtable-plugin.toml").read_text().replace(
        "permissions = []", 'permissions = ["shell"]'), encoding="utf-8")
    manage.add_plugin(harness, str(d), lambda m: True)
    # and at load: a compiled file that turned up later stops it
    item = load_installed("boxy", {"path": str(plugin_dir(tmp_path, "class P(Plugin): pass\n")), "enabled": True})
    assert item.status == "on"
    item.obj.stop()
    (Path(item.path) / "evil.pyd").write_bytes(b"MZ")
    item = load_installed("boxy", {"path": item.path, "enabled": True})
    assert item.status == "broken" and "evil.pyd" in item.problem


@pytest.fixture
def harness(tmp_path):
    p = tmp_path / "lab" / "harness.yaml"
    p.parent.mkdir()
    p.write_text(yaml.safe_dump(RAW), encoding="utf-8")
    return p


SLEEPY = """
import time, os
class P(Plugin):
    def on_tool_result(self, ctx, tool, args, text, is_error):
        if text == "sleep":
            time.sleep(30)
        if text == "crash":
            os._exit(3)
        if text == "big":
            return "x" * (9 * 1024 * 1024)
        ctx.state["n"] = ctx.state.get("n", 0) + 1
        return f"{text}{ctx.state['n']}:{os.getpid()}"
"""


def test_a_hook_that_sleeps_is_stopped_at_its_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "HOOK_SECONDS", 1.0)
    item = boxed(tmp_path, SLEEPY)
    t = time.monotonic()
    ok, out, msg = result_of(item, "sleep")
    assert time.monotonic() - t < 10 and not ok and out == "sleep"
    assert "took longer than 1 seconds" in msg and "stopped by its box" in msg


def test_a_crash_restarts_once_then_it_stays_off(tmp_path):
    item = boxed(tmp_path, SLEEPY)
    ctx = PluginHost([item]).context(item)
    first = item.obj.on_tool_result(ctx, "t", {}, "a", False)
    with pytest.raises(sandbox.SandboxError, match="stopped unexpectedly"):
        item.obj.on_tool_result(ctx, "t", {}, "crash", False)
    again = item.obj.on_tool_result(ctx, "t", {}, "a", False)  # started once more, its state gone
    assert again.startswith("a1:") and again != first
    with pytest.raises(sandbox.SandboxError):
        item.obj.on_tool_result(ctx, "t", {}, "crash", False)
    with pytest.raises(sandbox.SandboxError, match="stopped twice"):
        item.obj.on_tool_result(ctx, "t", {}, "a", False)
    item.obj.stop()  # a new run: a fresh start
    assert item.obj.on_tool_result(ctx, "t", {}, "a", False).startswith("a1:")
    with pytest.raises(sandbox.SandboxError, match="8 MB"):
        item.obj.on_tool_result(ctx, "t", {}, "big", False)
    item.obj.stop()


SAME = """
class P(Plugin):
    def on_tool_result(self, ctx, tool, args, text, is_error):
        ctx.state["seen"] = ctx.state.get("seen", 0) + 1
        return f"{tool}:{args.get('n')}:{text}:{is_error}:{ctx.state['seen']}:{ctx.settings.get('greeting')}"

    def before_model_call(self, ctx, role, model, system, messages):
        return system + " (checked)", messages + [{"role": "user", "content": f"{role}/{model}"}]

    def after_model_call(self, ctx, role, model, response, usage):
        ctx.emit("seen", {"text": response.text, "tokens": usage.input_tokens + usage.output_tokens,
                          "calls": [c.name for c in response.tool_calls]})

    def on_event(self, ctx, kind, data):
        ctx.emit("event", {"kind": kind, "task": data.get("task")})

    def tools(self, ctx):
        def add(a):
            if a.get("x") is None:
                raise ToolError("x is needed")
            return str(a["x"] + 1)
        return [Tool(ToolSpec("add_one", "adds one", _obj({"x": {"type": "integer"}}, ["x"])), add)]

    def commands(self):
        return {"say": lambda ctx, argv: print("said", *argv) or 0}

    def routes(self):
        return {"GET stats": lambda ctx, q, body: {"q": q.get("w")}, "POST made": lambda ctx, q, body: (201, body)}
"""
SAME_HOOKS = ("on_tool_result", "before_model_call", "after_model_call", "on_event", "tools", "commands", "routes")


def test_the_same_plugin_gives_the_same_results_boxed_and_in_the_app(tmp_path, capsys):
    from roundtable.providers.base import ChatResponse, ToolCall, Usage

    d = plugin_dir(tmp_path, SAME, hooks=SAME_HOOKS, extra='[settings.greeting]\ntype = "string"\n'
                                                            'default = "hi"\n')
    answers = {}
    for trusted in (False, True):
        item = load_installed("boxy", {"path": str(d), "enabled": True, "trusted": trusted})
        assert item.status == "on" and item.boxed is (not trusted), item.problem
        cfg, _ = cfg_with(two_steps)
        host = host_with(cfg, item)
        seen = []
        conv = host.conversation(emit=lambda k, v: seen.append((k, v)), role="coder")
        got = [conv.on_tool_result("grep", {"n": 2}, "found", True), conv.on_tool_result("grep", {}, "x", False)]
        got.append(conv.before_model_call("a/m", "sys", [{"role": "user", "content": "go"}]))
        conv.after_model_call("a/m", ChatResponse("ok", [ToolCall("1", "add_one", {"x": 1})]), Usage(3, 4))
        host.notify("task_start", {"task": "T1"}, emit=lambda k, v: seen.append((k, v)))
        tool = [t for t in conv.tools() if t.spec.name == "add_one"][0]
        got += [tool.spec.parameters, tool.fn({"x": 41})]
        with pytest.raises(Exception, match="x is needed"):
            tool.fn({})
        got.append(host.commands("boxy")["say"](host.context(item), ["there"]))
        got.append(capsys.readouterr().out)
        got += [host.route("GET", "boxy", "stats", {"w": "y"}), host.route("POST", "boxy", "made", {}, {"a": 1}),
                host.route("GET", "boxy", "nope")]
        got.append([v for k, v in seen if k == "plugin"])
        assert not host.off_this_run, host.off_this_run
        answers[trusted] = got
        host.close()
    assert answers[False] == answers[True]
    assert answers[False][0] == "grep:2:found:True:1:hi" and answers[False][1].endswith(":2:hi")
    assert answers[False][2] == ("sys (checked)", [{"role": "user", "content": "go"},
                                                    {"role": "user", "content": "coder/a/m"}])
    assert answers[False][4] == "42" and answers[False][6] == "said there\n"
    assert answers[False][7] == (200, {"q": "y"}) and answers[False][8] == (201, {"a": 1})
    assert {"plugin": "boxy", "kind": "seen", "text": "ok", "tokens": 7, "calls": ["add_one"]} in answers[False][10]


def test_the_box_holds_no_keys_and_none_of_the_harness(tmp_path, monkeypatch):
    monkeypatch.setenv("MADE_UP_API_KEY", "sk-made-up-123456")
    monkeypatch.setenv("SOME_TOKEN", "tok-made-up-123456")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:1")
    monkeypatch.setenv("PYTHONPATH", "/somewhere")
    item = boxed(tmp_path, """
        import os, sys, json
        class P(Plugin):
            def on_tool_result(self, ctx, tool, args, text, is_error):
                try:
                    import roundtable.core.secrets
                    harness = "importable"
                except ImportError as e:
                    harness = str(e)
                try:
                    import yaml
                    third = "yaml"
                except ImportError:
                    third = "no yaml"
                return json.dumps({"env": dict(os.environ), "harness": harness, "third": third,
                                   "api": __import__("roundtable.plugins.api").plugins.api.BOXED})
    """)
    _, out, _ = result_of(item, "x")
    got = json.loads(out)
    assert not [k for k in got["env"] if is_secret_name(k)]
    assert not [k for k in got["env"] if k.upper().endswith("_PROXY") or k == "PYTHONPATH"]
    assert "rest of the harness" in got["harness"] and got["third"] == "no yaml" and got["api"] is True
    assert got["env"]["TMPDIR"].startswith(str(plugins_home() / "boxy"))


@needs_unix
def test_each_permission_opens_only_its_own_door(tmp_path):
    other = tmp_path / "elsewhere.txt"
    other.write_text("outside", encoding="utf-8")
    project = tmp_path / "proj"
    (project / ".git").mkdir(parents=True)
    (project / "main.py").write_text("print('hi')", encoding="utf-8")
    (project / ".env").write_text("SECRET=1", encoding="utf-8")
    (project / ".git" / "config").write_text("[remote]", encoding="utf-8")
    body = f"""
        import os, sys, socket, subprocess
        class P(Plugin):
            def on_tool_result(self, ctx, tool, args, text, is_error):
                if text == "network":
                    socket.socket(socket.AF_INET, socket.SOCK_STREAM).close()
                elif text == "files":
                    return open({str(other)!r}).read()
                elif text == "shell":
                    return str(subprocess.run([sys.executable, "-c", "print(1)"], capture_output=True).stdout)
                elif text.startswith("project"):
                    return open(os.path.join(str(ctx.project_root), text.split(":")[1])).read()
                return "ok"
    """
    tries = ["network", "files", "shell", "project:main.py"]
    for perm in ("network", "files", "shell", "project:read"):
        item = boxed(tmp_path, body, granted=[perm], pid=f"door-{perm.split(':')[0]}")
        for t in tries:
            ok, out, msg = result_of(item, t, project_root=project)
            opens = t.split(":")[0] == perm.split(":")[0] or (perm == "files" and t.startswith("project"))
            assert ok == opens, (perm, t, msg)
            if ok and t == "files":
                assert out == "outside"
        for private in (".env", ".git/config"):
            ok, out, msg = result_of(item, f"project:{private}", project_root=project)
            assert ok == (perm == "files"), (perm, private)  # any folder means any folder
            assert ok or "private file in the project" in msg or "outside its own folder" in msg


def test_secrets_host_goes_through_the_parent_and_the_key_never_enters_the_box(tmp_path, monkeypatch):
    from roundtable.core import secrets as vault

    vault.put("MADE_UP_KEY", "mk-123456789")
    try:
        cfg, _ = cfg_with(two_steps, {**RAW, "providers": {**RAW["providers"], "made": {
            "type": "openai_compat", "base_url": "https://api.made-up.example/v1", "api_key_env": "MADE_UP_KEY"}}})
        sent = []

        class Resp:
            status = 200
            headers = {"X-Echo": "Bearer mk-123456789"}

            def read(self, n):
                return json.dumps(sent[-1]["headers"]).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(req, timeout):
            sent.append({"url": req.full_url, "headers": dict(req.header_items())})
            return Resp()

        real = sandbox.secret_request

        def fake(cfg_, granted, method, url, headers=None, body=None, timeout=30, **_):
            return real(cfg_, granted, method, url, headers, body, timeout, opener=opener)

        monkeypatch.setattr(sandbox, "secret_request", fake)
        item = boxed(tmp_path, """
            import os
            class P(Plugin):
                def on_tool_result(self, ctx, tool, args, text, is_error):
                    r = ctx.http("GET", text, headers={"Authorization": "Bearer stolen?"})
                    assert "mk-123456789" not in repr(r) and "mk-123456789" not in repr(dict(os.environ))
                    return r["body"] + "|" + r["headers"]["X-Echo"]
        """, granted=["secrets:api.made-up.example"])
        host = host_with(cfg, item)
        conv = host.conversation()
        out = conv.on_tool_result("t", {}, "https://api.made-up.example/v1/x", False)
        assert not host.off_this_run, host.off_this_run
        assert sent[-1]["headers"]["Authorization"] == "Bearer mk-123456789"  # added outside the box
        assert "[your key]" in out and "mk-123456789" not in out and "stolen" not in json.dumps(sent)
        for bad, words in (("https://elsewhere.example/", "only use saved keys for: api.made-up.example"),
                           ("http://api.made-up.example/", "only https")):
            with pytest.raises(api.PluginError, match=words):
                fake(cfg, item.granted, "GET", bad)
        host.close()
    finally:
        vault.put("MADE_UP_KEY", None)


def test_trusted_runs_the_old_way_built_ins_are_untouched_and_the_api_asks_first(tmp_path, harness):
    d = plugin_dir(tmp_path, "class P(Plugin):\n    pass\n", pid="trust-me", hooks=())
    manage.add_plugin(harness, str(d), lambda m: True)
    rows = {p["id"]: p for p in manage.list_plugins(harness)}
    assert rows["trust-me"]["boxed"] and not rows["trust-me"]["trusted"]
    assert rows["trust-me"]["box_words"].startswith("Runs in its own box: no internet, no other programs")
    assert not rows["token-saver"]["boxed"] and "Comes with the harness" in rows["token-saver"]["box_words"]
    status, body = manage.api("POST", "", body={"action": "trust", "id": "trust-me"}, harness_path=harness)
    assert body["ok"] is False and "outside its box" in body["needs_sure"]["warning"]
    status, body = manage.api("POST", "", body={"action": "trust", "id": "trust-me", "sure": True},
                              harness_path=harness)
    assert body["ok"] and body["trusted"]
    host = load_config(str(harness)).plugin_host()
    p = host.get("trust-me")
    assert p.status == "on" and p.trusted and not p.boxed and not isinstance(p.obj, sandbox.BoxedPlugin)
    assert all(not b.boxed for b in host.plugins if b.builtin)
    assert manage.list_plugins(harness)[-1]["box_words"].startswith("Trusted")
    manage.api("POST", "", body={"action": "trust", "id": "trust-me", "trusted": False}, harness_path=harness)
    assert load_config(str(harness)).plugin_host().get("trust-me").boxed
    with pytest.raises(api.PluginError, match="always runs as the app"):
        manage.set_trusted(harness, "token-saver", True, sure=True)


def test_two_hundred_tool_results_through_a_box_in_under_two_seconds(tmp_path):
    item = boxed(tmp_path, """
        class P(Plugin):
            def on_tool_result(self, ctx, tool, args, text, is_error):
                return text + "."
    """)
    cfg, _ = cfg_with(two_steps)
    conv = host_with(cfg, item).conversation()
    conv.on_tool_result("t", {}, "warm", False)
    t = time.monotonic()
    for i in range(200):
        assert conv.on_tool_result("t", {"i": i}, "y" * 2000, False).endswith(".")
    assert time.monotonic() - t < 2.0
    cfg.plugin_host().close()


def test_a_tool_that_breaks_a_rule_switches_the_plugin_off_and_says_so(tmp_path):
    item = boxed(tmp_path, """
        import socket
        class P(Plugin):
            def tools(self, ctx):
                return [Tool(ToolSpec("fetch", "fetches", _obj({}, [])), lambda a: str(socket.socket()))]
    """, hooks=("tools",))
    cfg, _ = cfg_with(two_steps)
    host = host_with(cfg, item)
    seen = []
    tool = host.conversation(emit=lambda k, v: seen.append((k, v))).tools()[0]
    with pytest.raises(Exception, match="was stopped: it tried to go on the internet"):
        tool.fn({})
    assert item.id in host.off_this_run and any(k == "plugin_error" for k, _ in seen)
    with pytest.raises(Exception, match="switched off until this run ends"):
        tool.fn({})
    host.close()


# -- trial ------------------------------------------------------------------------------------
def test_trial_runs_a_plugins_own_tests_in_the_box(tmp_path):
    d = plugin_dir(tmp_path, "class P(Plugin):\n    pass\ndef double(x):\n    return 2 * x\n", pid="tried")
    (d / "test_tried.py").write_text(textwrap.dedent("""
        import unittest, tried_mod
        class T(unittest.TestCase):
            def test_double(self):
                self.assertEqual(tried_mod.double(2), 4)
                open("written-here.txt", "w").write("fine")
    """), encoding="utf-8")
    res = sandbox.trial(d, ["python", "-m", "unittest", "-q"], timeout=60)
    assert res["ok"], res["output"]
    assert "OK" in res["output"] and not (d / "written-here.txt").exists()  # a throwaway copy
    (d / "test_net.py").write_text("import socket\nsocket.socket()\n", encoding="utf-8")
    res = sandbox.trial(d, ["python", "test_net.py"], timeout=60)
    assert not res["ok"] and "go on the internet" in res["output"]
    res = sandbox.trial(d, ["python", "-c", "import time; time.sleep(30)"], timeout=1)
    assert not res["ok"] and "Stopped after 1 seconds" in res["output"]
    assert not sandbox.trial(d, ["bash", "-c", "true"])["ok"]
    assert not sandbox.trial(d, ["python", "-c", "raise SystemExit(2)"])["ok"]


# -- the operating system layer --------------------------------------------------------------------
def test_supported_says_what_this_computer_enforces():
    s = sandbox.supported()
    assert s["guard"] is True and s["words"].startswith(sandbox.WORDS)
    assert set(s) >= {"guard", "os_net", "os_proc", "words"}
    if os.name == "nt":
        assert "not proof against one written to break out" in s["words"]


@pytest.mark.skipif(sandbox.os_layer() not in ("bwrap", "unshare"), reason="no bwrap or unshare here")
def test_linux_cuts_the_internet_itself(tmp_path):
    import subprocess

    prefix = sandbox.os_prefix([], tmp_path)
    code = "import socket\ntry:\n    socket.create_connection(('192.0.2.1', 80), timeout=2)\nexcept OSError as e:\n" \
           "    print('cut', e.errno)\n"
    out = subprocess.run([*prefix, sys.executable, "-I", "-S", "-c", code], capture_output=True, text=True,
                         timeout=30)
    assert out.stdout.startswith("cut"), out
    assert sandbox.os_prefix(["network"], tmp_path, layer="unshare") == []


@pytest.mark.skipif(sandbox.os_layer() != "bwrap", reason="no bwrap here")
def test_bwrap_hides_other_files(tmp_path):
    item = boxed(tmp_path, """
        import os
        class P(Plugin):
            def on_tool_result(self, ctx, tool, args, text, is_error):
                return str(os.path.exists(text))
    """)
    ctx = PluginHost([item]).context(item)
    assert item.obj.on_tool_result(ctx, "t", {}, str(tmp_path), False) == "False"
    item.obj.stop()


def test_bwrap_command_binds_only_its_places(tmp_path):
    args = sandbox.os_prefix([], tmp_path / "data", tmp_path / "code", [str(tmp_path / "proj")], layer="bwrap")
    assert "--unshare-net" in args and args[-1] == "--" and ["--bind", "/", "/"] != args[1:4]
    joined = " ".join(args)
    assert f"--ro-bind {tmp_path / 'code'}" in joined and f"--bind {tmp_path / 'data'}" in joined
    assert f"--ro-bind-try {tmp_path / 'proj'}" in joined and os.path.expanduser("~") + " " not in joined
    assert "--unshare-net" not in sandbox.os_prefix(["network"], tmp_path, layer="bwrap")
    assert ["--bind", "/", "/"] == sandbox.os_prefix(["files"], tmp_path, layer="bwrap")[9:12]


@pytest.mark.skipif(os.name != "nt", reason="Windows only")
def test_windows_job_object_allows_one_process(tmp_path):
    item = boxed(tmp_path, TRIES)
    assert item.obj.box._h.get("job")
    os.environ["RAISE"] = ""
    ok, _out, msg = result_of(item, "subprocess")
    assert not ok and "run another program" in msg


# -- the rules on their own -----------------------------------------------------------------------
def test_the_rules_for_places(tmp_path):
    data, code, proj = tmp_path / "data", tmp_path / "code", tmp_path / "proj"
    for d in (data, code, proj / ".git", proj / "src"):
        d.mkdir(parents=True)
    (tmp_path / "outside.txt").write_text("x")
    os.symlink(tmp_path / "outside.txt", data / "sneaky") if os.name != "nt" else None
    r = guard.Rules(data, [code], [])
    assert r.may_read(data / "a") is None and r.may_read(code / "m.py") is None
    assert "outside its own folder" in r.may_read(tmp_path / "outside.txt")
    assert "outside" in (r.may_write(code / "m.py") or "")
    if os.name != "nt":
        assert r.may_read(data / "sneaky") is not None  # a link out of its folder leads nowhere
    assert "compiled" in r.may_write(data / "x.so") and "compiled" in r.may_write(data / "x.pyd")
    assert r.decide("open", (str(code), "r", 0)) is not None  # a folder handle outside its folder
    assert r.decide("os.chdir", (3,)) is not None and r.decide("os.chdir", (str(data),)) is None
    assert r.decide("socket.__new__", (None, 1, 1, 0)) is None  # a local pair (asyncio)
    assert r.decide("socket.connect", (None, "\0hidden")) is not None
    assert r.decide("socket.connect", (None, str(tmp_path / "other.sock"))) is not None
    assert r.decide("import", ("ctypes",)) == ("run compiled code (ctypes)", True)
    assert r.decide("import", ("json",)) is None and r.decide("os.kill", (os.getpid(), 0)) is None
    assert r.decide("os.kill", (1, 9)) is not None
    p = guard.Rules(data, [code], ["project:read"])
    assert p.may_read(proj / "src" / "a.py") is not None  # not until a call names the project
    p.allow_project(proj)
    assert p.may_read(proj / "src" / "a.py") is None
    assert "private" in p.may_read(proj / ".git" / "config") and "private" in p.may_read(proj / "src" / ".env")
    assert "private" in p.may_read(proj / "id_rsa")
    assert guard.Rules(data, [], ["files"]).may_read(tmp_path / "outside.txt") is None
    assert guard.Rules(data, [], ["files"]).may_write(data / "x.so") is not None  # files alone isn't shell


def test_copies_stay_in_step():
    from roundtable import search

    assert guard.SECRET_NAME.pattern == search.SECRET_NAME.pattern
    assert (boxapi.API_VERSION, boxapi.HOOKS, boxapi.PERMISSIONS) == (api.API_VERSION, api.HOOKS, api.PERMISSIONS)
    for hook in api.HOOKS:
        assert str(inspect.signature(getattr(boxapi.Plugin, hook))) == str(inspect.signature(getattr(api.Plugin, hook)))
    assert boxapi._obj({"a": {}}, ["a"]) == api._obj({"a": {}}, ["a"])
    assert [f.name for f in __import__("dataclasses").fields(boxapi.Usage)] == \
        [f.name for f in __import__("dataclasses").fields(__import__("roundtable.providers.base").providers.base.Usage)]


def test_manifest_takes_a_tool_time_limit_and_project_read():
    m = parse_manifest({"id": "slow-one", "name": "S", "entry": "x:y", "tool_timeout": 200,
                        "permissions": ["project:read"]})
    assert m.tool_timeout == 200 and m.view()["permissions"][0]["words"] == "Can read the project it is helping with"
    with pytest.raises(api.PluginError, match="between 1 and 300"):
        parse_manifest({"id": "slow-one", "name": "S", "entry": "x:y", "tool_timeout": 900})


def test_sandbox_never_changes_what_the_charter_protects(tmp_path, harness):
    protected = {"limits": {"daily_usd": 3}, "gate": {"mode": "ask"}, "usage": {"x": 1}, "tandem": {"on": True},
                 "providers": {"p": {"type": "scripted"}}, "makers_allowed": ["a"], "providers_allowed": ["a"]}
    (harness.parent / "custom.yaml").write_text(yaml.safe_dump(protected), encoding="utf-8")
    before = harness.read_bytes()
    d = plugin_dir(tmp_path, "class P(Plugin):\n    pass\n", pid="charter-check", hooks=())
    manage.add_plugin(harness, str(d), lambda m: True)
    manage.set_trusted(harness, "charter-check", True, sure=True)
    manage.set_trusted(harness, "charter-check", False)
    manage.set_enabled(harness, "charter-check", False)
    manage.remove_plugin(harness, "charter-check")
    after = yaml.safe_load((harness.parent / "custom.yaml").read_text(encoding="utf-8"))
    assert harness.read_bytes() == before
    assert {k: after.get(k) for k in protected} == protected


def test_windows_pipes_only_its_own(tmp_path):
    r = guard.Rules(tmp_path, [], [])
    own = rf"\\.\pipe\python-pipe-{os.getpid()}-3"
    assert r.decide("_winapi.CreateFile", (own, 0xC0000000, 0, 3, 0)) is None
    assert r.decide("_winapi.CreateFile", (r"\\.\pipe\docker_engine", 0xC0000000, 0, 3, 0)) is not None


def test_a_plugin_flooding_the_harness_is_stopped_not_waited_on(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "MOST_ASKS", 50)
    item = boxed(tmp_path, """
        class P(Plugin):
            def on_tool_result(self, ctx, tool, args, text, is_error):
                for i in range(10_000):
                    ctx.emit("spam", {"i": i})
                return text
    """)
    ok, out, msg = result_of(item, "x")
    assert not ok and out == "x" and "more than 50 messages" in msg
