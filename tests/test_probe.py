import json

import pytest

from agentharness.harness.config import ModelRef, parse_config
from agentharness.improve.lab import Lab, Proposal
from agentharness.improve.loop import cycle
from agentharness.improve.probe import BUILTIN, check, compare, models_in_config, run_probes
from agentharness.providers.base import ProviderError
from agentharness.providers.scripted import ScriptedImages, ScriptedProvider, reply

FIXED = '''def median(values):
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2
'''


def smart(model, system, messages, tools):
    names = {t.name for t in tools}
    prompt, last = messages[0]["content"], messages[-1]
    if "add" in names:
        return reply("6912") if last["role"] == "tool" else reply(calls=[("add", {"a": 1234, "b": 5678})])
    if "finish_task" in names:
        if last["role"] == "user":
            return reply(calls=[("write_file", {"path": "stats.py", "content": FIXED})])
        return reply(calls=[("finish_task", {"summary": "fixed"})], id_prefix="f")
    if "JSON object" in prompt:
        return reply('```json\n{"name": "Maria Lopez", "age": 34, "city": "Porto"}\n```')
    if "OK-" in prompt:
        return reply("OK-1\nOK-2\nOK-3")
    if "Pencils" in prompt:
        return reply("5 packs + 2 singles\nANSWER: $6.90")
    if "Australia" in prompt:
        return reply("Canberra")
    return reply("?")


def broken(model, system, messages, tools):
    return reply("I'd rather not.")


def make(tmp_path, behaviours):
    raw = {
        "providers": {"a": {"type": "scripted"}, "img": {"type": "scripted_images"}},
        "roles": {
            "orchestrator": {"model": "a/good"},
            "coder": {"model": "a/flaky", "fallback": ["a/good"]},
            "designer": {"kind": "image", "model": "img/pic"},
        },
    }
    cfg = parse_config(raw)
    cfg.lab_dir = tmp_path / "lab"

    def route(model, system, messages, tools):
        b = behaviours.get(model, smart)
        if isinstance(b, Exception):
            raise b
        return b(model, system, messages, tools)

    cfg.register("a", ScriptedProvider("a", route))
    cfg.register("img", ScriptedImages())
    return cfg


def test_all_builtin_probes_pass_for_a_capable_model(tmp_path):
    cfg = make(tmp_path, {})
    results = run_probes(cfg, [ModelRef("a", "good")])
    assert {r.probe for r in results} == set(BUILTIN)
    assert all(r.passed for r in results), [(r.probe, r.detail, r.error) for r in results]


def test_broken_model_fails_probes(tmp_path):
    cfg = make(tmp_path, {"flaky": broken})
    results = run_probes(cfg, [ModelRef("a", "flaky")])
    assert not any(r.passed for r in results)


def test_new_then_ok_then_regression_then_boost(tmp_path):
    behaviours = {}
    cfg = make(tmp_path, behaviours)
    models = [ModelRef("a", "flaky")]
    [rep] = check(cfg, cfg.lab_dir, models)
    assert rep.status == ["NEW"] and rep.score == 1.0
    [rep] = check(cfg, cfg.lab_dir, models)
    assert rep.status == ["OK"]

    behaviours["flaky"] = broken  # the provider silently changed the model
    [rep] = check(cfg, cfg.lab_dir, models)
    assert "REGRESSION" in rep.status and rep.bad
    assert any("usually passes" in n for n in rep.notes)

    for _ in range(4):  # it stays broken for a while: that becomes its new normal
        check(cfg, cfg.lab_dir, models)
    behaviours["flaky"] = smart  # then it's fixed
    [rep] = check(cfg, cfg.lab_dir, models)
    assert "BOOST" in rep.status and not rep.bad


def test_down_detection(tmp_path):
    cfg = make(tmp_path, {"flaky": ProviderError("503 overloaded", retryable=True)})
    [rep] = check(cfg, cfg.lab_dir, [ModelRef("a", "flaky")])
    assert rep.status == ["DOWN"] and rep.bad and "503" in rep.notes[0]


def test_slow_and_verbose_flags():
    from agentharness.improve.probe import ProbeResult

    hist = [{"run": f"r{i}", "at": f"2026-01-0{i}", "model": "a/m", "probe": "json", "passed": True,
             "seconds": 2.0, "output_tokens": 100, "error": ""} for i in range(1, 4)]
    [rep] = compare([ProbeResult("a/m", "json", True, seconds=20.0, output_tokens=500)], hist)
    assert "SLOW" in rep.status and "VERBOSE" in rep.status and not rep.bad
    [rep] = compare([ProbeResult("a/m", "json", True, seconds=0.5, output_tokens=100)], hist)
    assert rep.status == ["OK"]  # sub-5s jitter is ignored
    slow_hist = [{**h, "seconds": 30.0} for h in hist]
    [rep] = compare([ProbeResult("a/m", "json", True, seconds=8.0, output_tokens=100)], slow_hist)
    assert rep.status == ["FAST"]


def test_custom_probes_and_filter(tmp_path):
    (tmp_path / "probes.yaml").write_text(
        "- name: capital\n  prompt: What is the capital of Australia? One word.\n  expect_contains: canberra\n"
        "- name: exact\n  prompt: Say hi\n  expect_exact: hello\n")
    cfg = make(tmp_path, {})
    cfg.improve["probes_file"] = str(tmp_path / "probes.yaml")
    results = run_probes(cfg, [ModelRef("a", "good")], only=["capital", "exact"])
    assert {r.probe: r.passed for r in results} == {"capital": True, "exact": False}
    with pytest.raises(ValueError):
        run_probes(cfg, [ModelRef("a", "good")], only=["nope"])


def test_image_probe_and_model_listing(tmp_path):
    cfg = make(tmp_path, {})
    chat, image = models_in_config(cfg)
    assert [str(m) for m in chat] == ["a/good", "a/flaky"] and [str(m) for m in image] == ["img/pic"]
    results = run_probes(cfg, [], image, generate_images=True)
    assert results[0].probe == "image_generate" and results[0].passed and "png (1, 1)" in results[0].detail


def test_probes_are_recorded_in_lab(tmp_path):
    cfg = make(tmp_path, {})
    check(cfg, cfg.lab_dir, [ModelRef("a", "good")], only=["json"])
    rows = [json.loads(x) for x in (cfg.lab_dir / "probes.jsonl").read_text().splitlines()]
    assert rows[0]["model"] == "a/good" and rows[0]["probe"] == "json" and rows[0]["passed"]
    check(cfg, cfg.lab_dir, [ModelRef("a", "good")], only=["json"], save=False)
    assert len((cfg.lab_dir / "probes.jsonl").read_text().splitlines()) == 1


def test_cycle_holds_back_changes_involving_a_regressed_model(tmp_path):
    behaviours = {}
    cfg = make(tmp_path, behaviours)
    cfg.improve["auto_apply"] = "low"
    lab = Lab(cfg.lab_dir)
    for _ in range(2):
        check(cfg, cfg.lab_dir, [ModelRef("a", "flaky"), ModelRef("a", "good")])  # healthy baseline
    behaviours["flaky"] = broken
    lab.add_proposal(Proposal(id="", kind="routing", role="coder", change={"models": ["a/flaky", "a/good"]},
                              rationale="data", risk="low"))
    report = cycle(cfg, lab)
    assert report["applied"] == []
    assert "acting up" in report["skipped"][0]["reason"]

    behaviours["flaky"] = smart  # recovered
    report = cycle(cfg, lab)
    assert len(report["applied"]) == 1
