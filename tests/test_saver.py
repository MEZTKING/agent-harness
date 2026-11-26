import json

import pytest

from roundtable.harness.config import parse_config
from roundtable.harness.saver import (
    SaverConfig, TokenSaver, build_candidate, est_tokens, toon_compress, toon_decode,
)
from roundtable.harness.tools import ToolError, Workspace
from roundtable.providers.scripted import reply

from .test_harness import RAW, Brain, make


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def saver(tmp_path, **cfg):
    events = []
    clock = Clock()
    s = TokenSaver(SaverConfig(**cfg), tmp_path, on_event=lambda k, d: events.append((k, d)), clock=clock)
    return s, events, clock


def pipe_table(rows=400):
    head = "| id | model | input | output |\n|----|-------|-------|--------|"
    body = "\n".join(f"| {i} | made-up-model-{i:03d} | {i * 0.013:.3f} | {i * 0.051:.3f} |" for i in range(rows))
    return head + "\n" + body


def uniform_json(n=300):
    items = [{"model": f"maker/model-{i}", "input": round(i * 0.01, 2), "output": i * 3, "cached": i % 2 == 0,
              "note": None if i % 3 else f"tier, \"{i}\"\nline two", "code": f"{i:03d}"} for i in range(n)]
    return {"object": "list", "data": items}


def spilled(tmp_path, out):
    sid = out.split("[saved-output #", 1)[1].split(" ", 1)[0]
    return sid, (tmp_path / ".harness" / "spill" / f"{sid}.txt")


def test_pipe_table_keeps_head_tail_and_numbered_samples(tmp_path):
    s, events, _ = saver(tmp_path)
    text = pipe_table()
    out = s.process("run_command", {"command": "prices"}, text)
    assert "[saved-output #" in out and len(out) < len(text) * 0.72
    lines = text.split("\n")
    assert out.startswith("\n".join(lines[:60]))
    assert "\n".join(lines[-40:]) in out
    assert f"L61: {lines[60]}" in out  # the first sampled middle row, with its original line number
    sid, path = spilled(tmp_path, out)
    assert path.read_text(encoding="utf-8") == text
    assert events[0][0] == "token_saver" and events[0][1]["strategy"] == "table"
    assert events[0][1]["tokens_saved_est"] > 0 and s.stats.tokens_saved == events[0][1]["tokens_saved_est"]


def test_uniform_json_is_lossless_and_decodes_back():
    data = uniform_json()
    text = json.dumps(data, indent=2)
    cand = build_candidate(text, SaverConfig())
    assert cand and cand[1] == "lossless"
    assert cand[0].splitlines()[1].startswith("data[300]{model,input,output,cached,note,code}:")
    assert toon_decode(cand[0]) == data
    arr = data["data"]
    assert toon_decode(toon_compress(arr)) == arr  # a bare array round-trips too
    tricky = [{"a": v, "b": "x"} for v in ["", " pad", "1.5", "true", "null", "-0", "01", "a,b", "\\", "é"]]
    assert toon_decode(toon_compress(tricky)) == tricky


def test_uniform_json_through_the_saver_says_zero_loss(tmp_path):
    s, events, _ = saver(tmp_path)
    text = json.dumps(uniform_json(), indent=2)
    out = s.process("run_command", {}, text)
    assert "zero information loss" in out and events[0][1]["strategy"] == "lossless"
    assert toon_decode(out.split("\n\n[saved-output", 1)[0]) == uniform_json()


def test_long_log_keeps_its_error_lines(tmp_path):
    s, _, _ = saver(tmp_path)
    lines = [f"step {i}: compiling module_{i} ok" for i in range(1000)]
    lines[500] = "Traceback (most recent call last): ValueError in module_500"
    lines[700] = "ERROR: connection timed out"
    out = s.process("run_command", {}, "\n".join(lines))
    assert "[saved-output #" in out
    assert "L501: Traceback (most recent call last)" in out and "L701: ERROR: connection timed out" in out
    assert "step 300:" not in out


def test_small_output_passes_through(tmp_path):
    s, events, _ = saver(tmp_path)
    assert s.process("run_command", {}, "exit code: 0\nall good") == "exit code: 0\nall good"
    assert not events and not (tmp_path / ".harness").exists()


def test_would_be_worse_passes_through(tmp_path):
    s, events, _ = saver(tmp_path)
    text = "\n".join(f"line {i} " + "x" * 20 for i in range(230))  # long, but under max_lines: nothing to cut
    assert s.process("run_command", {}, text) == text
    assert not events


def test_error_output_uses_the_higher_threshold(tmp_path):
    s, _, _ = saver(tmp_path)
    small = "\n".join(f"d{i:04d}" for i in range(990))  # 5,939 bytes: over min_bytes, under error_min_bytes
    assert s.process("run_command", {}, small, is_error=True) == small
    assert "[saved-output #" in s.process("run_command", {"n": 1}, small)
    big = "\n".join(f"d{i:04d}" for i in range(2000))
    assert "[saved-output #" in s.process("run_command", {"n": 2}, big, is_error=True)


def test_dedupe_within_and_after_the_ttl(tmp_path):
    s, events, clock = saver(tmp_path)
    text = "\n".join(f"file_{i}.py" for i in range(150))  # under max_lines: not compressed
    assert s.process("list_files", {}, text) == text
    clock.t += 30
    stub = s.process("list_files", {}, text)
    assert "BYTE-IDENTICAL" in stub and "30s ago" in stub
    sid, path = spilled(tmp_path, stub)
    assert path.read_text(encoding="utf-8") == text and events[-1][1]["strategy"] == "dedupe"
    clock.t += 91
    assert s.process("list_files", {}, text) == text  # the window passed
    assert s.process("list_files", {"path": "src"}, text) == text  # other arguments: another call


def test_spill_failure_means_no_compression(tmp_path):
    (tmp_path / ".harness").write_text("not a directory", encoding="utf-8")
    s, events, _ = saver(tmp_path)
    text = pipe_table()
    assert s.process("run_command", {}, text) == text
    assert not events
    assert TokenSaver(SaverConfig(), None).process("run_command", {}, text) == text


def test_read_tool_and_expand_output_are_exempt(tmp_path):
    s, events, _ = saver(tmp_path)
    text = pipe_table()
    assert s.process("read_file", {"path": "t.md"}, text) == text
    assert s.process("expand_output", {"id": "c1"}, text) == text
    assert not events


def test_turned_off(tmp_path):
    s, _, _ = saver(tmp_path, enabled=False)
    assert s.process("run_command", {}, pipe_table()) == pipe_table()
    assert parse_config({**RAW, "token_saver": False}).token_saver.enabled is False
    cfg = parse_config({**RAW, "token_saver": {"min_bytes": 2000}}).token_saver
    assert cfg.enabled and cfg.min_bytes == 2000 and cfg.keep_ratio_max == 0.72
    with pytest.raises(ValueError):
        parse_config({**RAW, "token_saver": {"min_byte": 2000}})


def test_expand_output_returns_the_original_and_a_range(tmp_path):
    s, _, _ = saver(tmp_path)
    text = pipe_table()
    sid, _ = spilled(tmp_path, s.process("run_command", {}, text))
    assert s.expand({"id": sid}) == text
    part = s.expand({"id": sid, "start_line": 100, "end_line": 102})
    lines = text.split("\n")
    assert part == "\n".join(f"{i}\t{lines[i - 1]}" for i in (100, 101, 102))
    with pytest.raises(ToolError):
        s.expand({"id": "../../etc"})
    ws = Workspace(tmp_path)  # the path in the notice is readable with read_file, but not writable
    assert lines[0] in ws.read_file({"path": f".harness/spill/{sid}.txt", "end_line": 1})
    with pytest.raises(ToolError):
        ws.write_file({"path": f".harness/spill/{sid}.txt", "content": "x"})


def test_token_estimate_counts_cjk_heavier():
    assert est_tokens("") == 0
    assert est_tokens("a" * 38) == 10
    assert est_tokens("漢" * 4) == 3


class BigTableBrain(Brain):
    """The worker runs a command that prints a big table, then finishes."""

    def __init__(self):
        super().__init__(plan=[{"id": "T1", "title": "prices", "role": "coder", "description": "list prices",
                                "acceptance": "listed", "depends_on": []}])
        self.seen = []

    def __call__(self, model, system, messages, tools):
        names = {t.name for t in tools}
        if "finish_task" in names:
            self.seen.append([dict(m) for m in messages])
            if messages[-1]["role"] == "user":
                assert "expand_output" in names
                return reply(calls=[("run_command", {"command": "python make_table.py"})])
            return reply(calls=[("finish_task", {"summary": "listed"})])
        return super().__call__(model, system, messages, tools)


def test_end_to_end_the_next_call_sees_the_marker_not_the_table(tmp_path):
    brain = BigTableBrain()
    orch, a, b, img, events = make(tmp_path, brain=brain)
    root = orch.project.root
    root.mkdir(parents=True, exist_ok=True)
    (root / "make_table.py").write_text(
        "print('| id | name | price |')\n"
        "for i in range(400):\n    print(f'| {i} | it{i} | {i * 0.25:.2f} |')\n", encoding="utf-8")
    orch.start("price list")
    assert orch.run() == "done"
    tool_msg = brain.seen[-1][-1]
    assert tool_msg["role"] == "tool" and "[saved-output #" in tool_msg["content"]
    sid = tool_msg["content"].split("[saved-output #", 1)[1].split(" ", 1)[0]
    original = (root / ".harness" / "spill" / f"{sid}.txt").read_text(encoding="utf-8")
    assert all(f"| {i} | it{i} |" in original for i in range(400))
    assert sum(f"| {i} | it{i} |" in tool_msg["content"] for i in range(400)) < 200
    assert len(tool_msg["content"]) < len(original) * 0.72
    saved = [d for k, d in events if k == "token_saver"]
    assert saved and saved[0]["tool"] == "run_command"
    rows = [json.loads(ln) for ln in (orch.project.dir / "metrics.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["saved_tokens_est"] == saved[0]["tokens_saved_est"] > 0
    assert orch.project.saved_tokens_est() == saved[0]["tokens_saved_est"]
    logged = [json.loads(ln) for ln in (orch.project.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(r["event"] == "token_saver" for r in logged)
