"""Wave 7, d4-tools: making a plug-in from a sentence – written by a (scripted) builder in its own folder, its
tests run only in the box, static checks, and offered only when everything passed."""

import json
import textwrap
from pathlib import Path

import pytest

from roundtable.harness.agent import Budget, BudgetExceeded
from roundtable.harness.config import parse_config
from roundtable.plugins import make, sandbox
from roundtable.plugins.api import PluginError
from roundtable.providers.scripted import ScriptedProvider, reply

from .test_harness import RAW

MOD = textwrap.dedent('''\
    """Adds VAT to a list of prices."""

    from roundtable.plugins.api import Plugin, Tool, ToolSpec, _obj


    def total_with_vat(prices, rate=0.2):
        return round(sum(prices) * (1 + rate), 2)


    def run(args):
        return str(total_with_vat([float(x) for x in args.get("prices", [])]))


    class VatPlugin(Plugin):
        def tools(self, ctx):
            return [Tool(ToolSpec("{name}", "Totals prices with VAT.", _obj({{"prices": {{"type": "array"}}}}, ["prices"])), run)]


    plugin = VatPlugin()
    ''')


def writes(*files):
    """A builder that writes ``files`` ([(path, text)]) one per turn, then finishes."""
    def script(model, system, messages, tools):
        turn = sum(1 for m in messages if m["role"] == "assistant")
        if turn < len(files):
            path, text = files[turn]
            return reply(calls=[("write_file", {"path": path, "content": text})], id_prefix=f"w{turn}")
        return reply(calls=[("finish_task", {"summary": "Wrote a VAT tool with a test."})], id_prefix="f")
    return script


def cfg_for(script):
    cfg = parse_config(json.loads(json.dumps(RAW)))
    prov = ScriptedProvider("a", script)
    cfg.register("a", prov)
    return cfg, prov


IDEA = "a tool that totals prices with VAT"
MODULE = make.module_name(make.plugin_id(IDEA))


@pytest.fixture
def box(monkeypatch):
    """The box: records what it was asked to run; passes unless told otherwise."""
    seen = {"calls": [], "ok": True}

    def trial(code, command, timeout=60):
        seen["calls"].append((Path(code), list(command)))
        return {"ok": seen["ok"], "output": "1 passed" if seen["ok"] else "1 failed"}

    monkeypatch.setattr(sandbox, "trial", trial)
    return seen


def test_a_made_plugin_that_passes_is_offered_and_its_tests_ran_in_the_box(box):
    cfg, prov = cfg_for(writes((f"{MODULE}.py", MOD.format(name="total_with_vat"))))
    got = make.draft(cfg, IDEA, Budget(limit_usd=1.0))
    assert got["offered"] and got["tests_passed"] and not got["problems"]
    assert got["tools"] == ["total_with_vat"] and got["cost_usd"] > 0
    assert [c[0] for c in box["calls"]] == [Path(got["folder"])] and box["calls"][0][1] == make.TEST_COMMAND
    assert make.is_draft(got["folder"]) and "ready" in got["words"]
    # the builder had no shell: it can only write files in its folder
    assert {t.name for t in prov.calls[0]["tools"]} == {"read_file", "write_file", "edit_file", "list_files", "finish_task"}
    files = {f["path"] for f in got["files"]}
    assert {"roundtable-plugin.toml", f"{MODULE}.py", f"tests/test_{MODULE}.py"} <= files


def test_a_made_plugin_with_a_failing_test_is_not_offered(box):
    box["ok"] = False
    cfg, _ = cfg_for(writes((f"{MODULE}.py", MOD.format(name="total_with_vat"))))
    got = make.draft(cfg, IDEA, Budget(limit_usd=1.0))
    assert not got["offered"] and not got["tests_passed"] and "didn't pass" in got["words"]


@pytest.mark.parametrize("extra, why", [
    (("roundtable-plugin.toml", None), "asks for permissions"),
    (("helper.so", "\x7fELF"), "compiled"),
    ((f"{MODULE}.py", MOD.format(name="read_file")), "already have"),
    (("notes.txt", "my key is sk-" + "a" * 40), None),
])
def test_permissions_compiled_files_and_workspace_names_are_refused(box, tmp_path, extra, why):
    path, text = extra
    files = [(f"{MODULE}.py", MOD.format(name="total_with_vat"))]
    if path == "roundtable-plugin.toml":  # the manifest asking for the internet
        files.append(("roundtable-plugin.toml", textwrap.dedent(f"""\
            id = "{make.plugin_id(IDEA)}"
            name = "Vat"
            version = "0.1.0"
            entry = "{MODULE}:plugin"
            hooks = ["tools"]
            permissions = ["network"]
            """)))
    else:
        files.append((path, text))
    if why is None:  # key-like text: the charter's scrub decides (Helper 4); with the stub it passes
        from roundtable.improve import charter

        if charter.scrub("my key is sk-" + "a" * 40) == "my key is sk-" + "a" * 40:
            pytest.skip("the charter's scrub isn't filled in on this branch")
        why = "something like a key"
    cfg, _ = cfg_for(writes(*files))
    got = make.draft(cfg, IDEA, Budget(limit_usd=1.0))
    assert not got["offered"] and any(why in p for p in got["problems"]), got["problems"]
    assert box["calls"] == []  # nothing that breaks a rule is ever run, even in the box


def test_too_many_files_or_too_big_is_refused(tmp_path):
    folder = tmp_path / "p"
    make.seed(folder, "big-one", "a big one")
    for i in range(10):
        (folder / f"f{i}.txt").write_text("x", encoding="utf-8")
    (folder / "huge.txt").write_text("y" * (make.MAX_BYTES + 1), encoding="utf-8")
    probs = make.check(folder)
    assert any("files" in p for p in probs) and any("KB" in p for p in probs)


def test_the_template_alone_passes_the_static_checks(tmp_path):
    make.seed(tmp_path / "t", "word-count", "count words")
    assert make.check(tmp_path / "t") == []
    assert make.tool_names(tmp_path / "t") == ["word_count"]


def test_the_price_is_shown_first_and_money_stops_it(box):
    cfg, _ = cfg_for(writes((f"{MODULE}.py", MOD.format(name="total_with_vat"))))
    price = make.estimate(cfg)
    assert price["usd"] and price["model"] == "a/coder" and "$" in price["words"]
    with pytest.raises(BudgetExceeded):
        make.draft(cfg, IDEA, Budget(limit_usd=0.0))
    with pytest.raises(PluginError, match="in a sentence"):
        make.draft(cfg, "tool", Budget(limit_usd=1.0))


def test_the_app_shows_the_price_then_makes_it_in_a_job_and_add_it_installs_it_asking_for_nothing(box, tmp_path):
    import time

    import yaml

    from roundtable.ui import marketapi
    from roundtable.ui.server import Jobs

    harness = tmp_path / "lab" / "harness.yaml"
    harness.parent.mkdir()
    harness.write_text(yaml.safe_dump(RAW), encoding="utf-8")
    cfg, _ = cfg_for(writes((f"{MODULE}.py", MOD.format(name="total_with_vat"))))

    class App:
        harness_config_path = str(harness)
        jobs = Jobs()

        def need_cfg(self):
            return cfg

    app = App()
    post = marketapi.routes(app)[("POST", "/api/market")]
    first = post({"action": "make", "idea": IDEA})
    assert first["price"]["usd"] and "job" not in first
    job = post({"action": "make", "idea": IDEA, "go": True})["job"]
    for _ in range(200):
        j = app.jobs.jobs[job["id"]]
        if j.status != "running":
            break
        time.sleep(0.02)
    assert j.status == "done" and j.result["offered"], j.error
    asked = post({"action": "add_made", "folder": j.result["folder"]})
    assert asked["ok"] is False and asked["needs_ok"]["permissions"] == []
    done = post({"action": "add_made", "folder": j.result["folder"], "confirmed": []})
    assert done["ok"] and done["added"]["id"] == make.plugin_id(IDEA)
    custom = yaml.safe_load((harness.parent / "custom.yaml").read_text())
    assert custom["plugins"][make.plugin_id(IDEA)]["permissions"] == []
    from roundtable.ui.server import ApiError

    with pytest.raises(ApiError, match="made here"):
        post({"action": "add_made", "folder": str(tmp_path)})


def test_the_seeded_plugin_passes_its_own_tests_in_the_real_box(tmp_path):
    """No fake here: the template's tests run inside the real box (standard library only, no pytest there)."""
    from roundtable.plugins import make, sandbox

    folder = tmp_path / "echo-words"
    make.seed(folder, "echo-words", "says the words back")
    res = sandbox.trial(folder, list(make.TEST_COMMAND))
    assert res["ok"], res["output"]
    assert "Ran 1 test" in res["output"]
