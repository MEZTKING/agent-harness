"""Words as they are written (wave 8, DS-13): the providers stream, the sink keeps them, tail hands them out.

Fake server-sent events go through each SDK's own transport (httpx2's MockTransport): no network, no keys."""

from __future__ import annotations

import json
import os
import time

import pytest

from roundtable.harness import streamlog
from roundtable.harness.agent import Budget, run_agent
from roundtable.harness.config import ModelRef, parse_config
from roundtable.harness.tools import Tool, Toolbox, ToolSpec, _obj
from roundtable.providers.base import ChatResponse, ProviderError, Usage
from roundtable.providers.scripted import ScriptedProvider, reply

httpx = pytest.importorskip("httpx2")

FAKE_KEY = "sk-" + "Z" * 30  # made up: only its shape matters


def _sse(events: list) -> bytes:
    out = []
    for e in events:
        if isinstance(e, tuple):
            out.append(f"event: {e[0]}\ndata: {json.dumps(e[1])}\n\n")
        else:
            out.append(f"data: {e if isinstance(e, str) else json.dumps(e)}\n\n")
    return "".join(out).encode()


# -- the sink and tail ------------------------------------------------------------------------------------------
def test_pieces_arrive_in_order_and_tail_reads_only_what_is_new(tmp_path):
    keep = streamlog.sink(tmp_path, "T1")
    for piece in ("Hello ", "there, ", "I am ", "building "):
        keep("text", piece)
    keep("thinking", "Let me think. ")
    a = streamlog.tail(tmp_path, "T1", 0)
    assert a["text"] == "Hello there, I am building " and a["thinking"] == "Let me think. " and not a["done"]
    keep("text", "the page.")
    b = streamlog.read(tmp_path, "T1", a["at"], done=True)
    assert b["text"] == "the page." and b["done"] and b["at"] > a["at"]
    assert streamlog.read(tmp_path, "T1", b["at"], done=True)["text"] == ""


def test_a_word_still_being_written_waits_for_its_end(tmp_path):
    keep = streamlog.sink(tmp_path, "T1")
    keep("text", "one two thr")
    a = streamlog.tail(tmp_path, "T1", 0)
    assert a["text"] == "one two "
    keep("text", "ee ")
    assert streamlog.tail(tmp_path, "T1", a["at"])["text"] == "three "


def test_key_shaped_text_never_leaves_tail_even_split_across_pieces(tmp_path):
    keep = streamlog.sink(tmp_path, "T1")
    half = len(FAKE_KEY) // 2
    keep("text", "the key is " + FAKE_KEY[:half])
    first = streamlog.tail(tmp_path, "T1", 0)
    keep("text", FAKE_KEY[half:] + " and the setting password: " + "q" * 6)
    second = streamlog.tail(tmp_path, "T1", first["at"])
    keep("text", "q" * 10 + "\nend")
    third = streamlog.read(tmp_path, "T1", second["at"], done=True)
    everything = first["text"] + second["text"] + third["text"]
    assert FAKE_KEY not in everything and FAKE_KEY[:half] not in everything
    assert "q" * 16 not in everything and "[hidden" in everything
    keep2 = streamlog.sink(tmp_path, "T2")
    keep2("thinking", f"I'll use {FAKE_KEY} here ")
    assert FAKE_KEY not in streamlog.tail(tmp_path, "T2", 0)["thinking"]


def test_a_new_conversation_starts_again_and_an_old_cursor_reads_it_from_the_start(tmp_path):
    keep = streamlog.sink(tmp_path, "T1")
    keep("text", "worker words ")
    old = streamlog.tail(tmp_path, "T1", 0)["at"]
    keep = streamlog.sink(tmp_path, "T1")  # the reviewer's turn
    keep("text", "reviewer says ok ")
    assert streamlog.tail(tmp_path, "T1", old)["text"] == "reviewer says ok "


def test_only_the_newest_64_kb_are_kept_and_clear_removes_them(tmp_path):
    keep = streamlog.sink(tmp_path, "T1")
    for i in range(3000):
        keep("text", f"line {i:05d} " + "x" * 40 + "\n")
    r = streamlog.read(tmp_path, "T1", 0, done=True)
    assert len(r["text"]) <= streamlog.REWRITE_AT and r["skipped"] > 0 and "line 02999" in r["text"]
    assert streamlog.path(tmp_path, "T1").stat().st_size < 3 * streamlog.KEEP
    assert streamlog.clear(tmp_path) == 1 and not streamlog.path(tmp_path, "T1").exists()
    assert streamlog.tail(tmp_path, "T1", 0)["done"] is True


def test_quiet_for_a_while_counts_as_done(tmp_path):
    keep = streamlog.sink(tmp_path, "T1")
    keep("text", "partial")
    p = streamlog.path(tmp_path, "T1")
    old = time.time() - streamlog.QUIET_S - 5
    os.utime(p, (old, old))
    r = streamlog.tail(tmp_path, "T1", 0)
    assert r["done"] and r["text"] == "partial"


def test_stream_can_be_switched_off_in_harness_yaml():
    on = parse_config({"providers": {"a": {"type": "scripted"}}, "roles": {"orchestrator": {"model": "a/m"}}})
    off = parse_config({"providers": {"a": {"type": "scripted"}}, "roles": {"orchestrator": {"model": "a/m"}},
                        "stream": {"enabled": False}})
    assert streamlog.enabled(on) and not streamlog.enabled(off)


# -- the scripted provider through run_agent ------------------------------------------------------------------
def _cfg():
    return parse_config({"providers": {"a": {"type": "scripted"}}, "roles": {"orchestrator": {"model": "a/m"}},
                         "pricing": {"a/m": {"input": 1.0, "output": 2.0}}})


def _box():
    box = Toolbox()
    box.add(Tool(ToolSpec("look", "look", _obj({}, [])), lambda a: "two files"))
    box.add(Tool(ToolSpec("finish", "done", _obj({"summary": {"type": "string"}}, ["summary"])),
                 lambda a: "ok", terminal=True))
    return box


def test_a_scripted_run_streams_its_words_and_costs_the_same(tmp_path):
    def run(on_delta):
        cfg = _cfg()
        p = ScriptedProvider("a", [reply("Reading the files now.", [("look", {})]), reply("All done here.", [("finish", {"summary": "s"})])],
                               chunks=5)
        cfg.register("a", p)
        budget = Budget(limit_usd=10)
        res = run_agent(cfg, ModelRef("a", "m"), "sys", "do it", _box(), budget, on_delta=on_delta)
        return res, budget, p

    plain, b1, p1 = run(None)
    keep = streamlog.sink(tmp_path, "T1")
    streamed, b2, p2 = run(keep)
    assert streamed.text == plain.text and streamed.usage == plain.usage and b1.spent_usd == b2.spent_usd
    assert p1.calls == p2.calls  # the same requests
    assert streamlog.read(tmp_path, "T1", 0, done=True)["text"] == "Reading the files now.All done here."


# -- OpenAI-compatible: fake SSE ----------------------------------------------------------------------------------
def _openai(handler):
    from roundtable.providers.openai_compat import OpenAICompatProvider

    p = OpenAICompatProvider("deepseek", api_key_env="NO_SUCH_KEY", base_url="https://example.invalid/v1")
    p.client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return p


TOOLS = [ToolSpec("write_file", "write", _obj({"path": {"type": "string"}, "content": {"type": "string"}}, ["path"]))]
WHOLE = {"id": "x", "object": "chat.completion", "created": 0, "model": "deepseek-v4-flash",
         "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
             "role": "assistant", "content": "I'll write it.", "reasoning_content": "Think first.",
             "tool_calls": [{"id": "call_1", "type": "function",
                             "function": {"name": "write_file", "arguments": "{\"path\": \"a.txt\", \"content\": \"hi\"}"}}]}}],
         "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150,
                   "prompt_tokens_details": {"cached_tokens": 20}}}


def _chunk(delta=None, finish=None, usage=None):
    d = {"id": "x", "object": "chat.completion.chunk", "created": 0, "model": "deepseek-v4-flash",
         "choices": [] if delta is None else [{"index": 0, "delta": delta, "finish_reason": finish}]}
    if usage:
        d["usage"] = usage
    return d


STREAM = [
    _chunk({"role": "assistant", "reasoning_content": "Think "}),
    _chunk({"reasoning_content": "first."}),
    _chunk({"content": "I'll "}),
    _chunk({"content": "write it."}),
    _chunk({"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "write_file", "arguments": "{\"path\": "}}]}),
    _chunk({"tool_calls": [{"index": 0, "function": {"arguments": "\"a.txt\", \"content\""}}]}),
    _chunk({"tool_calls": [{"index": 0, "function": {"arguments": ": \"hi\"}"}}]}, finish="tool_calls"),
    _chunk(None, usage=WHOLE["usage"]),
    "[DONE]",
]


def _bodies():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if body.get("stream"):
            return httpx.Response(200, content=_sse(STREAM), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=WHOLE)

    return seen, handler


def test_openai_stream_gives_the_same_response_and_usage_as_a_whole_call():
    seen, handler = _bodies()
    p = _openai(handler)
    msgs = [{"role": "user", "content": "go"}]
    whole = p.chat("deepseek-v4-flash", "sys", msgs, TOOLS)
    pieces = []
    streamed = p.chat("deepseek-v4-flash", "sys", msgs, TOOLS, on_delta=lambda k, s: pieces.append((k, s)))
    assert pieces == [("thinking", "Think "), ("thinking", "first."), ("text", "I'll "), ("text", "write it.")]
    assert streamed.text == whole.text and streamed.stop_reason == whole.stop_reason == "tool_use"
    assert [c.to_dict() for c in streamed.tool_calls] == [c.to_dict() for c in whole.tool_calls]
    assert streamed.tool_calls[0].arguments == {"path": "a.txt", "content": "hi"}
    assert streamed.usage == whole.usage == Usage(100, 30, 20, 0, None)
    assert streamed.raw == whole.raw  # replayed on the next call: reasoning_content kept
    assert seen[1]["stream"] is True and seen[1]["stream_options"] == {"include_usage": True}
    assert {k: v for k, v in seen[1].items() if k not in ("stream", "stream_options")} == seen[0]


def test_openai_without_on_delta_or_with_stream_off_sends_the_request_as_before():
    seen, handler = _bodies()
    p = _openai(handler)
    msgs = [{"role": "user", "content": "go"}]
    p.chat("deepseek-v4-flash", "sys", msgs, TOOLS)
    p.chat("deepseek-v4-flash", "sys", msgs, TOOLS, options={"stream": False}, on_delta=lambda k, s: None)
    assert seen[0] == seen[1] and "stream" not in seen[0]


def test_openai_stream_that_fails_before_any_piece_falls_back_once():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(bool(body.get("stream")))
        if body.get("stream"):
            return httpx.Response(400, json={"error": {"message": "stream_options not supported"}})
        return httpx.Response(200, json=WHOLE)

    r = _openai(handler).chat("deepseek-v4-flash", "sys", [{"role": "user", "content": "go"}], TOOLS,
                              on_delta=lambda k, s: None)
    assert calls == [True, False] and r.text == "I'll write it."


def test_openai_stream_that_breaks_after_a_piece_is_an_error_not_a_second_call():
    calls = []

    def handler(request):
        calls.append(1)
        body = _sse([_chunk({"content": "Half "}), {"error": {"message": "the server fell over"}}])
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    with pytest.raises(ProviderError):
        _openai(handler).chat("deepseek-v4-flash", "sys", [{"role": "user", "content": "go"}], on_delta=lambda k, s: None)
    assert len(calls) == 1


# -- Anthropic: fake SSE ------------------------------------------------------------------------------------------
A_WHOLE = {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
           "content": [{"type": "thinking", "thinking": "Plan it.", "signature": "sig"},
                       {"type": "text", "text": "Writing now."},
                       {"type": "tool_use", "id": "tu_1", "name": "write_file", "input": {"path": "a.txt", "content": "hi"}}],
           "stop_reason": "tool_use", "stop_sequence": None,
           "usage": {"input_tokens": 50, "output_tokens": 25, "cache_read_input_tokens": 7, "cache_creation_input_tokens": 3}}
A_STREAM = [
    ("message_start", {"type": "message_start", "message": {**A_WHOLE, "content": [], "stop_reason": None,
                                                          "usage": {"input_tokens": 50, "output_tokens": 1,
                                                                    "cache_read_input_tokens": 7, "cache_creation_input_tokens": 3}}}),
    ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "", "signature": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "Plan "}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "it."}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig"}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    ("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Writing "}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "now."}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 1}),
    ("content_block_start", {"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "id": "tu_1", "name": "write_file", "input": {}}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": "{\"path\": \"a.txt\", "}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": "\"content\": \"hi\"}"}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 2}),
    ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                       "usage": {"output_tokens": 25}}),
    ("message_stop", {"type": "message_stop"}),
]


def _anthropic(handler, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "proxy-injected")
    from roundtable.providers.anthropic_provider import AnthropicProvider

    p = AnthropicProvider(base_url="https://example.invalid")
    p.client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return p


def test_anthropic_stream_gives_the_same_response_and_usage_as_a_whole_call(monkeypatch):
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if body.get("stream"):
            return httpx.Response(200, content=_sse(A_STREAM), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=A_WHOLE)

    p = _anthropic(handler, monkeypatch)
    msgs = [{"role": "user", "content": "go"}]
    whole = p.chat("claude-sonnet-5-5", "sys", msgs, TOOLS)
    pieces = []
    streamed = p.chat("claude-sonnet-5-5", "sys", msgs, TOOLS, on_delta=lambda k, s: pieces.append((k, s)))
    assert pieces == [("thinking", "Plan "), ("thinking", "it."), ("text", "Writing "), ("text", "now.")]
    assert streamed.text == whole.text == "Writing now." and streamed.stop_reason == whole.stop_reason
    assert [c.to_dict() for c in streamed.tool_calls] == [c.to_dict() for c in whole.tool_calls]
    assert streamed.usage == whole.usage == Usage(50, 25, 7, 3, None)
    assert streamed.raw["content"][0]["signature"] == "sig"  # thinking replayed with its signature
    assert seen[1]["stream"] is True and {k: v for k, v in seen[1].items() if k != "stream"} == seen[0]


def test_anthropic_stream_that_fails_first_falls_back_once(monkeypatch):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(bool(body.get("stream")))
        if body.get("stream"):
            return httpx.Response(400, json={"type": "error", "error": {"type": "invalid_request_error", "message": "no"}})
        return httpx.Response(200, json=A_WHOLE)

    r = _anthropic(handler, monkeypatch).chat("claude-sonnet-5-5", "sys", [{"role": "user", "content": "go"}],
                                              on_delta=lambda k, s: None)
    assert calls == [True, False] and r.text == "Writing now."


def test_anthropic_without_on_delta_sends_the_request_as_before(monkeypatch):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=A_WHOLE)

    p = _anthropic(handler, monkeypatch)
    p.chat("claude-sonnet-5-5", "sys", [{"role": "user", "content": "go"}])
    p.chat("claude-sonnet-5-5", "sys", [{"role": "user", "content": "go"}], options={"stream": False},
           on_delta=lambda k, s: None)
    assert seen[0] == seen[1] and "stream" not in seen[0]


def test_a_watcher_that_breaks_never_breaks_the_reply():
    seen, handler = _bodies()

    def bad(kind, piece):
        raise RuntimeError("the page went away")

    r = _openai(handler).chat("deepseek-v4-flash", "sys", [{"role": "user", "content": "go"}], TOOLS, on_delta=bad)
    assert r.text == "I'll write it." and len(seen) == 1


def test_the_stream_route_reads_a_task_and_refuses_odd_names(tmp_path, monkeypatch):
    from roundtable.ui import server
    from roundtable.ui.server import ApiError, UIApp

    from .test_harness import make

    orch, *_ = make(tmp_path)
    orch.start("build a bakery site")
    cfg = orch.cfg
    cfg.lab_dir = tmp_path / "lab"
    orch._register_with_lab()
    app = UIApp(str(tmp_path / "missing-hub.yaml"), "missing.yaml")
    app.cfg = lambda: cfg
    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "chatapi"))
    root = orch.project.root
    keep = streamlog.sink(root, "T1")
    keep("text", f"hello {FAKE_KEY} world ")
    r = app.dispatch("GET", "/api/stream", {"path": [str(root)], "task": ["T1"], "since": ["0"]}, {})
    assert r["text"].startswith("hello [hidden") and FAKE_KEY not in r["text"] and r["done"]  # T1 isn't running
    with pytest.raises(ApiError):
        app.dispatch("GET", "/api/stream", {"path": [str(root)], "task": ["../x"]}, {})
