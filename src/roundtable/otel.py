"""OpenTelemetry on this computer only (wave 9, MD-64).

The owner's answer (27 November 2026): traces in a file the app shows; the coding helpers' own telemetry taken
in on 127.0.0.1; an outside collector only if the owner types its address, with a warning.

* **Spans.** :func:`span` wraps a task, a model call or a tool call. Each finished span is one line in
  ``<home>/traces/<day>.jsonl`` in the OTLP JSON shape (``{"resourceSpans": [...]}``), so any OpenTelemetry
  tool can read the file. Spans nest by themselves (a model call inside a task is its child). Off until the
  owner turns on "Keep a timeline of each run" (``<home>/otel.json`` ``traces: true``); while off, a span does
  nothing at all and writes nothing.
* **What a span holds.** Its name, start and end, ok or failed, and short attributes: numbers, yes/no and
  names under 200 characters. Never a prompt, a file's contents or a key: an attribute whose name looks like
  a secret (safeenv's pattern) is dropped unless it is a count, a value that looks like a key is replaced
  by ``[hidden]``.
* **The receiver** (:class:`Receiver`, off by default): OTLP over HTTP with JSON on ``127.0.0.1`` only, at
  most 1 MB a request. Claude Code's and Codex's own telemetry, when they are pointed at it, lands here: their
  log events with token counts become lines in the usage ledger (``harness/usage.py``, service ``cli``), so
  their tokens show beside everything else; their spans join the trace files. A sender that isn't this
  computer is refused. Runs the harness itself drives are already in the ledger: telemetry marked
  ``roundtable.driven=true`` is not counted twice.
* **An outside collector** only when the owner types its address and ticks the warning ("task names and
  timings will go to that address"). Never for a project with an allowed list of services or makers: a span
  marked ``restricted`` (and every span inside it) stays here.
* **Old traces** are removed by retention's sweep (:func:`tidy_traces`, ``retention.traces_days``).
"""

from __future__ import annotations

import contextvars
import ipaddress
import json
import queue
import re
import secrets
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

FILE = "otel.json"
FOLDER = "traces"
SCOPE = "darkness-harness"
RECEIVER_PORT = 4318  # OTLP over HTTP's usual port (verify on the owner's PC that nothing else holds it)
MAX_BODY = 1_000_000
TRACES_DAYS = 14
ATTR_MAX = 200
WARNING = "Task names and timings will go to that address."
_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH", re.I)
# a value shaped like a key: sk-…, a long run of letters, digits and -_ with no spaces, or a bearer header
_KEYISH = re.compile(r"(?:sk|pk|rk|ghp|gho|github_pat|xox[abp])[-_][A-Za-z0-9_-]{8,}|Bearer\s+\S{8,}|"
                     r"[A-Za-z0-9_\-]{32,}")
_LOCK = threading.Lock()
_CURRENT: contextvars.ContextVar["Span | None"] = contextvars.ContextVar("otel_span", default=None)
_SETTINGS: dict[str, tuple[float, dict[str, Any]]] = {}  # file -> (mtime, settings)


# -- the owner's switches ------------------------------------------------------------------------------------------
def _home(home) -> Path:
    if home is None:
        from .desktop import app_home

        return app_home()
    return Path(home)


def settings(home) -> dict[str, Any]:
    """{traces, receiver, receiver_port, collector}: everything off unless the owner turned it on."""
    p = _home(home) / FILE
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return {"traces": False, "receiver": False, "receiver_port": RECEIVER_PORT, "collector": ""}
    have = _SETTINGS.get(str(p))
    if have and have[0] == mtime:
        return dict(have[1])
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    try:
        port = int(raw.get("receiver_port") or RECEIVER_PORT)
    except (TypeError, ValueError):
        port = RECEIVER_PORT
    out = {"traces": bool(raw.get("traces")), "receiver": bool(raw.get("receiver")),
           "receiver_port": port if 0 <= port < 65536 else RECEIVER_PORT,
           "collector": str(raw.get("collector") or "") if raw.get("collector_warned") else ""}
    _SETTINGS[str(p)] = (mtime, out)
    return dict(out)


def enabled(home) -> bool:
    return settings(home)["traces"]


def clean_collector(address: str) -> str:
    """An http(s) address with a host, or "" to take it away. Raises ValueError in plain words."""
    a = str(address or "").strip().rstrip("/")
    if not a:
        return ""
    from urllib.parse import urlparse

    u = urlparse(a)
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise ValueError("Type the collector's address as http://… or https://…, with no name or password in it.")
    return a


def save(home, *, traces: bool | None = None, receiver: bool | None = None, receiver_port: int | None = None,
         collector: str | None = None, collector_warned: bool = False) -> dict[str, Any]:
    p = _home(home) / FILE
    with _LOCK:
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            raw = raw if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            raw = {}
        if traces is not None:
            raw["traces"] = bool(traces)
        if receiver is not None:
            raw["receiver"] = bool(receiver)
        if receiver_port is not None:
            port = int(receiver_port)
            if not 1024 <= port < 65536:
                raise ValueError("Choose a port between 1024 and 65535.")
            raw["receiver_port"] = port
        if collector is not None:
            address = clean_collector(collector)
            if address and not collector_warned:
                raise ValueError(f"Tick the box first: {WARNING}")
            raw["collector"], raw["collector_warned"] = address, bool(address)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(raw, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(p)
        _SETTINGS.pop(str(p), None)
    return settings(home)


# -- what a span may hold ------------------------------------------------------------------------------------------
def _value(v: Any) -> dict[str, Any] | None:
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if v is None:
        return None
    text = str(v)
    text = _KEYISH.sub("[hidden]", text)
    return {"stringValue": text[:ATTR_MAX]}


def clean_attrs(attrs: dict[str, Any]) -> list[dict[str, Any]]:
    """OTLP attributes from keyword arguments: secret-named ones dropped, key-shaped values hidden."""
    out = []
    for k, v in sorted(attrs.items()):
        k = str(k)[:64]
        if _SECRET_NAME.search(k) and (isinstance(v, bool) or not isinstance(v, (int, float))):
            continue  # a secret-shaped name keeps only a count ("input_tokens": 120), never words
        val = _value(v)
        if val is not None:
            out.append({"key": k, "value": val})
    return out


def _plain(value: dict[str, Any]) -> Any:
    for k in ("stringValue", "boolValue", "doubleValue"):
        if k in value:
            return value[k]
    if "intValue" in value:
        try:
            return int(value["intValue"])
        except (TypeError, ValueError):
            return 0
    return None


def plain_attrs(attrs: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for a in attrs or []:
        if isinstance(a, dict) and isinstance(a.get("value"), dict):
            out[str(a.get("key"))] = _plain(a["value"])
    return out


def restricted(values: dict[str, Any] | None) -> bool:
    """A project whose own settings limit its services or makers: its spans never leave this computer."""
    v = values or {}
    return bool(v.get("providers_allowed") or v.get("makers_allowed"))


# -- spans -----------------------------------------------------------------------------------------------------------
class Span:
    def __init__(self, home: Path, name: str, attrs: dict[str, Any], parent: "Span | None"):
        self.home, self.name = home, str(name)[:80]
        self.parent = parent
        self.trace_id = parent.trace_id if parent else secrets.token_hex(16)
        self.span_id = secrets.token_hex(8)
        self.restricted = bool(attrs.pop("restricted", False)) or bool(parent and parent.restricted)
        self.attrs = dict(attrs)
        self.start_ns = time.time_ns()
        self.end_ns = 0
        self.failed = ""

    def set(self, key: str, value: Any) -> None:
        self.attrs[str(key)] = value

    def error(self, words: str) -> None:
        self.failed = str(words)[:ATTR_MAX]

    def otlp(self) -> dict[str, Any]:
        sp: dict[str, Any] = {"traceId": self.trace_id, "spanId": self.span_id, "name": self.name, "kind": 1,
                              "startTimeUnixNano": str(self.start_ns), "endTimeUnixNano": str(self.end_ns),
                              "attributes": clean_attrs(self.attrs),
                              "status": ({"code": 2, "message": _value(self.failed)["stringValue"]} if self.failed
                                         else {"code": 1})}
        if self.parent:
            sp["parentSpanId"] = self.parent.span_id
        if self.restricted:
            sp["attributes"].append({"key": "restricted", "value": {"boolValue": True}})
        return envelope([sp])


def envelope(spans: list[dict[str, Any]], service: str = SCOPE) -> dict[str, Any]:
    return {"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]},
                               "scopeSpans": [{"scope": {"name": SCOPE}, "spans": spans}]}]}


def _day_file(home: Path, ns: int | None = None) -> Path:
    when = datetime.fromtimestamp((ns or time.time_ns()) / 1e9)
    return home / FOLDER / f"{when:%Y-%m-%d}.jsonl"


def write(home: Path, record: dict[str, Any]) -> None:
    f = _day_file(home)
    f.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
    with _LOCK:
        with open(f, "a", encoding="utf-8") as out:
            out.write(line)


def here() -> Path | None:
    """The folder of the span now open (a task's), so the model and tool spans inside it go to the same file."""
    s = _CURRENT.get()
    return s.home if s is not None else None


@contextmanager
def span(home, name: str, **attrs):
    """One span around the ``with`` block. Yields a :class:`Span` (``.set``, ``.error``), or None while traces
    are off (then nothing is written). Never raises on its own account."""
    try:
        h = _home(home)
        on = enabled(h)
    except Exception:  # noqa: BLE001 - bookkeeping never stops a run
        on = False
    if not on:
        yield None
        return
    s = Span(h, name, attrs, _CURRENT.get())
    token = _CURRENT.set(s)
    try:
        yield s
    except BaseException as e:
        s.error(f"{type(e).__name__}: {e}")
        raise
    finally:
        _CURRENT.reset(token)
        s.end_ns = time.time_ns()
        try:
            record = s.otlp()
            write(h, record)
            if not s.restricted:
                forward(h, record)
        except Exception:  # noqa: BLE001
            pass


# -- an outside collector, only when the owner typed one --------------------------------------------------------------
_OUT: "queue.Queue[tuple[str, dict[str, Any]]]" = queue.Queue(maxsize=1000)
_SENDER: threading.Thread | None = None


def _send(address: str, record: dict[str, Any]) -> None:
    import urllib.request

    req = urllib.request.Request(address + "/v1/traces", data=json.dumps(record).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=5).close()


def _drain() -> None:
    while True:
        address, record = _OUT.get()
        try:
            _send(address, record)
        except Exception:  # noqa: BLE001 - a collector that's away just misses those spans
            pass


def forward(home: Path, record: dict[str, Any]) -> bool:
    """Queue one span for the owner's own collector, if they typed one. Returns True when queued."""
    global _SENDER
    address = settings(home)["collector"]
    if not address:
        return False
    with _LOCK:
        if _SENDER is None or not _SENDER.is_alive():
            _SENDER = threading.Thread(target=_drain, daemon=True, name="otel-forward")
            _SENDER.start()
    try:
        _OUT.put_nowait((address, record))
    except queue.Full:
        return False
    return True


# -- reading the files back (the timeline) ---------------------------------------------------------------------------
def _read_spans(home: Path, days: int = 2) -> list[dict[str, Any]]:
    folder = home / FOLDER
    try:
        files = sorted(folder.glob("*.jsonl"))[-max(1, days):]
    except OSError:
        return []
    out = []
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for ln in lines:
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            for rs in rec.get("resourceSpans") or []:
                svc = plain_attrs((rs.get("resource") or {}).get("attributes")).get("service.name", "")
                for ss in rs.get("scopeSpans") or []:
                    for sp in ss.get("spans") or []:
                        out.append({**sp, "service": svc})
    return out


def _row(sp: dict[str, Any]) -> dict[str, Any]:
    start, end = int(sp.get("startTimeUnixNano") or 0), int(sp.get("endTimeUnixNano") or 0)
    return {"id": sp.get("spanId"), "parent": sp.get("parentSpanId") or "", "name": sp.get("name", ""),
            "start_ms": start // 1_000_000, "ms": max(0, (end - start) // 1_000_000),
            "ok": (sp.get("status") or {}).get("code") != 2,
            "error": (sp.get("status") or {}).get("message", ""), "attrs": plain_attrs(sp.get("attributes")),
            "service": sp.get("service", "")}


def traces(home, project: str = "", days: int = 2, limit: int = 20) -> list[dict[str, Any]]:
    """The newest traces, one row each: {id, name, start_ms, ms, spans, ok}. ``project``: a project id
    (usage.project_id) to keep only that project's."""
    by: dict[str, list[dict[str, Any]]] = {}
    for sp in _read_spans(_home(home), days):
        by.setdefault(str(sp.get("traceId")), []).append(_row(sp))
    out = []
    for tid, rows in by.items():
        root = next((r for r in rows if not r["parent"]), min(rows, key=lambda r: r["start_ms"]))
        if project and str(root["attrs"].get("project") or "") != project:
            continue
        start = min(r["start_ms"] for r in rows)
        end = max(r["start_ms"] + r["ms"] for r in rows)
        out.append({"id": tid, "name": root["name"], "task": root["attrs"].get("task", ""), "start_ms": start,
                    "ms": end - start, "spans": len(rows), "ok": all(r["ok"] for r in rows),
                    "service": root["service"]})
    out.sort(key=lambda r: -r["start_ms"])
    return out[:limit]


def trace(home, trace_id: str, days: int = 2) -> dict[str, Any]:
    """{id, spans: [{id, parent, name, start_ms, ms, offset_ms, depth, ok, error, attrs}]}, in time order."""
    rows = [_row(sp) for sp in _read_spans(_home(home), days) if str(sp.get("traceId")) == str(trace_id)]
    if not rows:
        raise FileNotFoundError("That run's timeline has gone (old timelines are tidied up after two weeks).")
    start = min(r["start_ms"] for r in rows)
    ids = {r["id"]: r for r in rows}

    def depth(r, seen=0):
        p = ids.get(r["parent"])
        return 0 if not p or seen > 20 else 1 + depth(p, seen + 1)

    for r in rows:
        r["offset_ms"], r["depth"] = r["start_ms"] - start, depth(r)
    rows.sort(key=lambda r: (r["start_ms"], r["depth"]))
    return {"id": trace_id, "ms": max(r["offset_ms"] + r["ms"] for r in rows), "spans": rows}


def tidy_traces(sweep, home, days: float | None = None) -> None:
    """retention's step: day files older than ``days`` go through the sweep's own ``remove``."""
    folder = _home(home) / FOLDER
    if not folder.is_dir():
        return
    keep = float(days if days is not None else (getattr(sweep, "limits", {}) or {}).get("traces_days", TRACES_DAYS))
    for f in sorted(folder.glob("*.jsonl")):
        if sweep.older_than(f, keep):
            sweep.remove("traces", f, folder)


# -- the coding helpers' own telemetry, on 127.0.0.1 -------------------------------------------------------------------
def loopback(address: str) -> bool:
    try:
        return ipaddress.ip_address(str(address).split("%")[0]).is_loopback
    except ValueError:
        return False


def _num(v: Any) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _helper(resource: dict[str, Any], attrs: dict[str, Any]) -> str | None:
    svc = str(resource.get("service.name") or attrs.get("service.name") or "").lower()
    if "claude" in svc:
        return "claude-code"
    if "codex" in svc:
        return "codex"
    return None


def usage_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Ledger lines from an OTLP logs body: Claude Code's ``api_request`` events and Codex's completed responses
    with token counts (event and attribute names as their docs gave them; verify at implementation)."""
    from .harness import makers
    from .harness.usage import _now

    rows = []
    for rl in body.get("resourceLogs") or []:
        res = plain_attrs((rl.get("resource") or {}).get("attributes"))
        if str(res.get("roundtable.driven") or "").lower() in ("true", "1"):
            continue  # a run the harness drove: already in the ledger
        for sl in rl.get("scopeLogs") or []:
            for lr in sl.get("logRecords") or []:
                a = plain_attrs(lr.get("attributes"))
                tool = _helper(res, a)
                event = str(a.get("event.name") or (lr.get("body") or {}).get("stringValue") or "")
                if not tool:
                    continue
                if tool == "claude-code" and event.endswith("api_request"):
                    inp = _num(a.get("input_tokens")) + _num(a.get("cache_read_tokens")) + _num(a.get("cache_creation_tokens"))
                    out = _num(a.get("output_tokens"))
                elif tool == "codex" and ("input_token_count" in a or "output_token_count" in a):
                    inp, out = _num(a.get("input_token_count")), _num(a.get("output_token_count"))
                else:
                    continue
                if not inp and not out:
                    continue
                at, day = _now()
                rows.append({"at": at, "day": day, "provider": "cli", "maker": makers.maker(f"cli/{tool}"),
                             "model": tool, "role": "own_use", "project": "", "pid": "", "input": inp,
                             "output": out, "usd": 0.0})  # their own subscription: no money of the harness's
    return rows


def take_in(home, path: str, body: dict[str, Any], record: Callable[..., None] | None = None) -> dict[str, Any]:
    """One OTLP JSON request: logs into the ledger, spans into the trace files, metrics accepted and dropped."""
    h = _home(home)
    counted = kept = 0
    if path == "/v1/logs":
        from .harness import usage

        put = record or usage.record
        for row in usage_rows(body):
            put(row, h)
            counted += 1
    elif path == "/v1/traces":
        for rs in body.get("resourceSpans") or []:
            res = plain_attrs((rs.get("resource") or {}).get("attributes"))
            svc = str(res.get("service.name") or "helper")[:60]
            spans = []
            for ss in rs.get("scopeSpans") or []:
                for sp in ss.get("spans") or []:
                    if isinstance(sp, dict):
                        clean = {k: sp[k] for k in ("traceId", "spanId", "parentSpanId", "name", "kind",
                                                    "startTimeUnixNano", "endTimeUnixNano", "status") if k in sp}
                        clean["attributes"] = clean_attrs(plain_attrs(sp.get("attributes")))
                        spans.append(clean)
            if spans:
                write(h, envelope(spans, svc))
                kept += len(spans)
    elif path != "/v1/metrics":
        raise FileNotFoundError(path)
    return {"counted": counted, "spans": kept}


def make_receiver_handler(home: Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "darkness-otel"

        def log_message(self, fmt, *args):
            pass

        def _answer(self, status: int, data: dict[str, Any]) -> None:
            raw = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self._answer(405, {"error": "Send telemetry with POST."})

        def do_POST(self):
            if not loopback(self.client_address[0]):
                return self._answer(403, {"error": "Only programs on this computer may send telemetry here."})
            length = _num(self.headers.get("Content-Length"))
            if length > MAX_BODY:
                return self._answer(413, {"error": "Too big: at most 1 MB a request."})
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._answer(415, {"error": "Send it as JSON (OTEL_EXPORTER_OTLP_PROTOCOL=http/json)."})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
                take_in(home, self.path.split("?")[0], body)
            except FileNotFoundError:
                return self._answer(404, {"error": "Use /v1/logs, /v1/traces or /v1/metrics."})
            except ValueError:
                return self._answer(400, {"error": "That isn't OTLP JSON."})
            self._answer(200, {})

    return Handler


class Receiver:
    """The receiver on 127.0.0.1, started when the owner turns it on (``start`` is a no-op while it is off)."""

    def __init__(self, home=None):
        self.home = _home(home)
        self.httpd: ThreadingHTTPServer | None = None
        self.error = ""

    @property
    def port(self) -> int:
        return self.httpd.server_address[1] if self.httpd else 0

    def start(self, port: int | None = None) -> bool:
        s = settings(self.home)
        if not s["receiver"] or self.httpd:
            return bool(self.httpd)
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", s["receiver_port"] if port is None else port),
                                        make_receiver_handler(self.home))
        except OSError as e:
            self.error = (f"Couldn't listen on port {s['receiver_port']} ({e}): choose another port, or close what "
                          "uses it.")
            return False
        httpd.daemon_threads = True
        self.httpd, self.error = httpd, ""
        threading.Thread(target=httpd.serve_forever, daemon=True, name="otel-receiver").start()
        return True

    def stop(self) -> None:
        httpd, self.httpd = self.httpd, None
        if httpd:
            httpd.shutdown()
            httpd.server_close()

    def status(self) -> dict[str, Any]:
        return {"running": bool(self.httpd), "port": self.port, "error": self.error,
                "endpoint": f"http://127.0.0.1:{self.port}" if self.httpd else ""}


def helper_settings(port: int) -> dict[str, dict[str, str]]:
    """What the coding helpers need to send here (shown on the card; set on the PC by an agent, never a key)."""
    endpoint = f"http://127.0.0.1:{port or RECEIVER_PORT}"
    return {"claude-code": {"CLAUDE_CODE_ENABLE_TELEMETRY": "1", "OTEL_LOGS_EXPORTER": "otlp",
                            "OTEL_EXPORTER_OTLP_PROTOCOL": "http/json", "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint},
            "codex": {"otel.exporter": f'{{ otlp-http = {{ endpoint = "{endpoint}/v1/logs", protocol = "json" }} }}'}}

