"""OpenTelemetry on this computer only (wave 9, MD-64): spans in a file, the helpers' telemetry on 127.0.0.1."""

import json
import time
import urllib.error
import urllib.request

import pytest

from roundtable import otel, retention
from roundtable.harness import usage


def _lines(home):
    return [json.loads(ln) for f in sorted((home / "traces").glob("*.jsonl")) for ln in f.read_text().splitlines()]


def _spans(home):
    return [sp for rec in _lines(home) for rs in rec["resourceSpans"] for ss in rs["scopeSpans"] for sp in ss["spans"]]


def test_while_off_a_span_does_nothing(tmp_path):
    with otel.span(tmp_path, "task", id="T1") as s:
        assert s is None
    assert list(tmp_path.iterdir()) == []


def test_spans_nest_and_are_written_in_the_otlp_shape(tmp_path):
    otel.save(tmp_path, traces=True)
    with otel.span(tmp_path, "task", task="T1", project="abc123") as t:
        with otel.span(tmp_path, "model", model="deepseek-v4-flash", tokens=120):
            pass
        with otel.span(tmp_path, "tool", tool="write_file") as tool:
            tool.error("the file is read-only")
    rec = _lines(tmp_path)[0]
    assert rec["resourceSpans"][0]["resource"]["attributes"][0] == {"key": "service.name",
                                                                       "value": {"stringValue": "darkness-harness"}}
    spans = {s["name"]: s for s in _spans(tmp_path)}
    assert set(spans) == {"task", "model", "tool"}
    assert spans["model"]["parentSpanId"] == spans["tool"]["parentSpanId"] == t.span_id
    assert "parentSpanId" not in spans["task"]
    assert len({s["traceId"] for s in spans.values()}) == 1 and len(t.trace_id) == 32
    assert spans["tool"]["status"]["code"] == 2 and spans["task"]["status"] == {"code": 1}
    assert int(spans["task"]["endTimeUnixNano"]) >= int(spans["model"]["endTimeUnixNano"])
    assert {"key": "tokens", "value": {"intValue": "120"}} in spans["model"]["attributes"]
    tl = otel.trace(tmp_path, t.trace_id)
    assert [s["depth"] for s in tl["spans"]] == [0, 1, 1]
    assert otel.traces(tmp_path, project="abc123")[0]["task"] == "T1"
    assert otel.traces(tmp_path, project="another") == []


def test_an_error_inside_the_block_marks_the_span_and_still_raises(tmp_path):
    otel.save(tmp_path, traces=True)
    with pytest.raises(RuntimeError):
        with otel.span(tmp_path, "task"):
            raise RuntimeError("broke")
    assert _spans(tmp_path)[0]["status"]["code"] == 2


KEYISH = "sk-" + "a1B2c3D4" * 5


def test_no_key_shaped_text_is_kept(tmp_path):
    otel.save(tmp_path, traces=True)
    with otel.span(tmp_path, "model", api_key=KEYISH, DEEPSEEK_API_KEY="x", note=f"called with {KEYISH}",
                   header="Bearer abcdefghijklmnop", token_count=5) as s:
        s.error(f"401 for key {KEYISH}")
    raw = "".join(f.read_text() for f in (tmp_path / "traces").iterdir())
    assert KEYISH not in raw and "abcdefghijklmnop" not in raw and "DEEPSEEK_API_KEY" not in raw
    assert "api_key" not in raw  # a secret-shaped name is dropped unless it is a count
    assert '"key":"token_count","value":{"intValue":"5"}' in raw
    assert "[hidden]" in raw


def test_an_outside_collector_needs_the_warning_and_is_only_called_when_set(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(otel, "_send", lambda address, record: sent.append((address, record)))
    otel.save(tmp_path, traces=True)
    with otel.span(tmp_path, "task"):
        pass
    time.sleep(0.1)
    assert sent == []  # nothing typed: nothing goes anywhere
    with pytest.raises(ValueError, match="Tick the box"):
        otel.save(tmp_path, collector="https://collector.example")
    with pytest.raises(ValueError):
        otel.save(tmp_path, collector="ftp://x", collector_warned=True)
    otel.save(tmp_path, collector="https://collector.example/", collector_warned=True)
    with otel.span(tmp_path, "task", restricted=True):  # a project with an allowed list of services
        with otel.span(tmp_path, "model"):
            pass
    with otel.span(tmp_path, "task"):
        pass
    for _ in range(50):
        if sent:
            break
        time.sleep(0.02)
    time.sleep(0.1)
    assert len(sent) == 1 and sent[0][0] == "https://collector.example"
    assert sent[0][1]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["name"] == "task"
    otel.save(tmp_path, collector="")
    assert otel.settings(tmp_path)["collector"] == ""


def test_a_hand_edited_collector_without_the_warning_is_ignored(tmp_path):
    (tmp_path / "otel.json").write_text(json.dumps({"traces": True, "collector": "https://x.example"}))
    assert otel.settings(tmp_path)["collector"] == ""


def test_old_trace_files_go_through_retentions_sweep(tmp_path):
    folder = tmp_path / "traces"
    folder.mkdir()
    old, new = folder / "2026-10-01.jsonl", folder / "2026-11-27.jsonl"
    old.write_text("{}\n")
    new.write_text("{}\n")
    now = time.time()
    import os

    os.utime(old, (now - 40 * 86400, now - 40 * 86400))
    os.utime(new, (now - 2 * 86400, now - 2 * 86400))
    sweep = retention.Sweep({**retention.DEFAULTS, "traces_days": 14})
    otel.tidy_traces(sweep, tmp_path)
    assert not old.exists() and new.exists() and sweep.result.removed[0].what == "traces"


# -- the receiver ------------------------------------------------------------------------------------------------
def _claude_logs(driven=False, tokens=(100, 40)):
    res = [{"key": "service.name", "value": {"stringValue": "claude-code"}}]
    if driven:
        res.append({"key": "roundtable.driven", "value": {"stringValue": "true"}})
    return {"resourceLogs": [{"resource": {"attributes": res}, "scopeLogs": [{"logRecords": [
        {"attributes": [{"key": "event.name", "value": {"stringValue": "api_request"}},
                        {"key": "input_tokens", "value": {"intValue": str(tokens[0])}},
                        {"key": "output_tokens", "value": {"intValue": str(tokens[1])}},
                        {"key": "cache_read_tokens", "value": {"intValue": "10"}},
                        {"key": "model", "value": {"stringValue": "a-model"}}]},
        {"attributes": [{"key": "event.name", "value": {"stringValue": "user_prompt"}},
                        {"key": "prompt", "value": {"stringValue": "secret words"}}]}]}]}]}


def _codex_logs():
    return {"resourceLogs": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "codex_cli_rs"}}]},
                              "scopeLogs": [{"logRecords": [{"attributes": [
                                  {"key": "event.name", "value": {"stringValue": "codex.sse_event"}},
                                  {"key": "input_token_count", "value": {"intValue": "7"}},
                                  {"key": "output_token_count", "value": {"intValue": "3"}}]}]}]}]}


def test_the_helpers_tokens_go_into_the_ledger_and_driven_runs_are_not_counted_twice(tmp_path):
    otel.take_in(tmp_path, "/v1/logs", _claude_logs())
    otel.take_in(tmp_path, "/v1/logs", _claude_logs(driven=True))
    otel.take_in(tmp_path, "/v1/logs", _codex_logs())
    rows = [json.loads(ln) for f in (tmp_path / "usage").glob("*.jsonl") for ln in f.read_text().splitlines()]
    assert [(r["model"], r["input"], r["output"], r["provider"], r["usd"]) for r in rows] == [
        ("claude-code", 110, 40, "cli", 0.0), ("codex", 7, 3, "cli", 0.0)]
    assert "secret words" not in json.dumps(rows)
    assert usage.service_used("cli", tmp_path)["month_tokens"] == 160


def _post(port, path, body: bytes, kind="application/json"):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, method="POST",
                                 headers={"Content-Type": kind})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


@pytest.fixture
def receiver(tmp_path):
    otel.save(tmp_path, receiver=True)
    r = otel.Receiver(tmp_path)
    assert r.start(port=0) and r.httpd.server_address[0] == "127.0.0.1"
    yield r
    r.stop()


def test_the_receiver_takes_json_on_loopback_and_refuses_too_much(receiver, tmp_path):
    assert _post(receiver.port, "/v1/logs", json.dumps(_claude_logs()).encode()) == 200
    assert _post(receiver.port, "/v1/metrics", b'{"resourceMetrics": []}') == 200
    assert _post(receiver.port, "/v1/logs", b"\x0a\x01", "application/x-protobuf") == 415
    assert _post(receiver.port, "/v1/logs", b"not json") == 400
    assert _post(receiver.port, "/v1/other", b"{}") == 404
    assert _post(receiver.port, "/v1/logs", b"{" + b" " * (otel.MAX_BODY + 1) + b"}") in (413, 400)
    assert usage.service_used("cli", tmp_path)["month_tokens"] == 150


def test_the_receiver_refuses_a_sender_that_isnt_this_computer(receiver, monkeypatch):
    assert otel.loopback("127.0.0.1") and otel.loopback("::1") and not otel.loopback("192.168.1.20")
    monkeypatch.setattr(otel, "loopback", lambda a: False)
    assert _post(receiver.port, "/v1/logs", json.dumps(_claude_logs()).encode()) == 403


def test_the_receiver_doesnt_start_while_off(tmp_path):
    r = otel.Receiver(tmp_path)
    assert r.start(port=0) is False and r.httpd is None


def test_helper_spans_join_the_trace_files_without_their_secrets(tmp_path):
    body = {"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "codex"}}]},
                               "scopeSpans": [{"spans": [{"traceId": "a" * 32, "spanId": "b" * 16, "name": "turn",
                                                          "startTimeUnixNano": "1", "endTimeUnixNano": "2",
                                                          "attributes": [{"key": "auth_header", "value": {"stringValue": "x"}}]}]}]}]}
    assert otel.take_in(tmp_path, "/v1/traces", body)["spans"] == 1
    raw = "".join(f.read_text() for f in (tmp_path / "traces").iterdir())
    assert "auth_header" not in raw and otel.traces(tmp_path)[0]["service"] == "codex"


# -- the API ---------------------------------------------------------------------------------------------------------
@pytest.fixture
def app(tmp_path, monkeypatch):
    from roundtable.ui import server
    from roundtable.ui.server import UIApp

    monkeypatch.setattr(server, "FEATURE_APIS", (*server.FEATURE_APIS, "otelapi"))
    a = UIApp(None, "missing.yaml")
    a._backup_home = lambda: tmp_path
    yield a
    if getattr(a, "_otel_receiver", None):
        a._otel_receiver.stop()


def test_the_settings_card_switches_and_refuses_a_collector_without_the_warning(app, tmp_path):
    v = app.dispatch("GET", "/api/otel", {}, {})
    assert v["traces"] is False and v["receiver"]["on"] is False and v["collector"] == ""
    assert app.dispatch("POST", "/api/otel", {}, {"traces": True})["traces"] is True
    with pytest.raises(ValueError, match="Tick the box"):
        app.dispatch("POST", "/api/otel", {}, {"collector": "https://c.example"})
    v = app.dispatch("POST", "/api/otel", {}, {"receiver": True, "receiver_port": 40000 + (hash(str(tmp_path)) % 2000)})
    assert v["receiver"]["on"] and (v["receiver"]["running"] or v["receiver"]["error"])
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" in v["helpers"]["claude-code"]
    app.dispatch("POST", "/api/otel", {}, {"receiver": False})
    assert app._otel_receiver.httpd is None
    assert app.dispatch("GET", "/api/otel/traces", {}, {})["traces"] == []
    with pytest.raises(FileNotFoundError):
        app.dispatch("GET", "/api/otel/trace", {"id": ["nope"]}, {})


def test_none_of_it_is_a_phone_route():
    from roundtable.phone import phone_allowed

    for m, p in (("GET", "/api/otel"), ("POST", "/api/otel"), ("GET", "/api/otel/traces"), ("GET", "/api/otel/trace")):
        assert not phone_allowed(m, p)


def test_a_project_with_an_allowed_list_is_restricted():
    assert otel.restricted({"providers_allowed": ["deepseek"]}) and otel.restricted({"makers_allowed": ["x"]})
    assert not otel.restricted({}) and not otel.restricted(None)
