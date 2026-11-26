"""The token saver: big tool results are slimmed as they enter a model's conversation.

Ported from dsh-plugin-save-token 2.1.3 (``src/index.js``, MIT, Copyright (c) 2026
PlayWithAI; see THIRD_PARTY_NOTICES.md), the DeepSeek Harness plugin's
``tools/post-execute`` hook. It works the same for every provider.

What happens to one tool result (``TokenSaver.process``):

1. Small results, error results under a higher threshold, and the output of the tools
   that exist to give exact text (``read_file``, ``expand_output``) pass through.
2. A result byte-identical to one this same conversation saw within the dedupe window
   becomes a short stub pointing at the earlier one.
3. JSON holding a uniform array of objects is re-encoded losslessly in a TOON-style
   table (``name[N]{k1,k2}:`` and one row per object). Only when that doesn't apply:
   other JSON is shortened structurally, a table-like text keeps its head and tail rows
   and a stride sample of the middle with the original line numbers, and other long
   text keeps a head and tail window plus the error-like lines from what was left out.
4. The never-worse gate: a replacement is used only if it is at most ``keep_ratio_max``
   of the original's bytes, saves at least ``min_saved_bytes`` and has strictly fewer
   estimated tokens (notice included).
5. Spill before replace: the original is written to ``.harness/spill/<id>.txt`` first;
   if that write fails, nothing is replaced. The replacement says what was done and
   how to get the original back (the ``expand_output`` tool or ``read_file`` on the path).

DeepSeek's (and Anthropic's) prompt cache: a result is transformed once, as it enters,
and messages already sent are never rewritten, so the conversation's prefix stays the
same from one model call to the next and cache hits continue.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Callable

from ..providers.base import ToolSpec

EXEMPT_TOOLS = frozenset({"read_file", "expand_output"})  # their output must stay exact
SPILL_DIR = Path(".harness") / "spill"
EXPAND_MAX_CHARS = 262_144  # the most expand_output returns at once (theirs: 262144)
ERROR_LINE_RE = re.compile(
    r"(fatal|panic|traceback|exception|\berror\b|err:|fail(?:ed|ure|ing)?\b|denied|rejected|timeout|timed out"
    r"|abort|cannot|unable to|syntax error|assertion|segfault)", re.I)
PROTECTED_KEY_RE = re.compile(r"error|message|stack|fail|fatal|exception|warn", re.I)
ID_RE = re.compile(r"^[a-z0-9]{1,32}$")


@dataclass
class SaverConfig:
    """``token_saver:`` in harness.yaml (the plugin's defaults)."""

    enabled: bool = True
    dedupe_enabled: bool = True
    min_bytes: int = 1400
    error_min_bytes: int = 6000
    keep_ratio_max: float = 0.72
    min_saved_bytes: int = 500
    max_lines: int = 240
    head_lines: int = 140
    tail_lines: int = 80
    tabular_head_rows: int = 60
    tabular_tail_rows: int = 40
    tabular_stride_samples: int = 50
    long_line_chars: int = 420
    json_max_parse_bytes: int = 524_288
    dedupe_ttl_seconds: float = 90.0
    error_lines_kept: int = 25

    @classmethod
    def parse(cls, raw: Any) -> "SaverConfig":
        if raw is None:
            return cls()
        if isinstance(raw, bool):
            return cls(enabled=raw)
        if not isinstance(raw, dict):
            raise ValueError("token_saver must be true, false or a mapping of settings")
        known = {f.name: f.type for f in fields(cls)}
        unknown = sorted(set(raw) - set(known))
        if unknown:
            raise ValueError(f"token_saver: unknown setting(s) {', '.join(unknown)}")
        out = cls()
        for k, v in raw.items():
            cur = getattr(out, k)
            setattr(out, k, bool(v) if isinstance(cur, bool) else type(cur)(v))
        return out


# -- estimators (theirs: utf8Bytes, estTokens) ---------------------------------------

def utf8_bytes(s: str) -> int:
    return len(s.encode("utf-8", errors="surrogatepass"))


def est_tokens(s: str) -> int:
    """About 3.8 characters a token, CJK (and characters outside the BMP) 0.75 each."""
    if not s:
        return 0
    cjk = sum(1 for ch in s if 0x2E80 <= ord(ch) <= 0x9FFF or ord(ch) > 0xFFFF)
    return math.ceil((len(s) - cjk) / 3.8 + cjk * 0.75)


# -- TOON-style lossless encoding of a uniform JSON array ----------------------------

_BARE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")
_NUMBER = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$")


def _is_primitive(v: Any) -> bool:
    if isinstance(v, float):
        return math.isfinite(v)  # Infinity and NaN aren't JSON
    return v is None or isinstance(v, (str, int, bool))


def uniform_keys(arr: Any) -> list[str] | None:
    """The shared keys when every item is an object with the same primitive-valued keys."""
    if not isinstance(arr, list) or len(arr) < 8 or not all(isinstance(o, dict) for o in arr):
        return None
    keys = list(arr[0])
    if not keys or len(keys) > 24:
        return None
    want = set(keys)
    for o in arr:
        if len(o) != len(keys) or set(o) != want or not all(_is_primitive(v) for v in o.values()):
            return None
    return keys


def _name(s: str) -> str:
    return s if _BARE_KEY.match(s) else json.dumps(s, ensure_ascii=False)


def _cell(v: Any) -> str:
    """One value. Strings that could be misread (or hold a separator) are JSON-quoted."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    if (not v or v != v.strip() or v in ("null", "true", "false") or _NUMBER.match(v)
            or any(c in v for c in ',"\n\r\\') or any(ord(c) < 0x20 for c in v)):
        return json.dumps(v, ensure_ascii=False)
    return v


def toon_encode(arr: list[dict[str, Any]], keys: list[str], name: str | None) -> str:
    head = (_name(name) if name is not None else "") + f"[{len(arr)}]{{{','.join(_name(k) for k in keys)}}}:"
    return "\n".join([head] + [",".join(_cell(o[k]) for k in keys) for o in arr])


def _split_cells(line: str) -> list[str]:
    """Split one row on commas outside JSON-quoted cells; quoted cells keep their quotes."""
    cells, i, n = [], 0, len(line)
    while True:
        if i < n and line[i] == '"':
            _, end = json.JSONDecoder().raw_decode(line, i)
            cells.append(line[i:end])
            i = end
        else:
            j = line.find(",", i)
            j = n if j < 0 else j
            cells.append(line[i:j])
            i = j
        if i >= n:
            return cells
        i += 1  # the comma


def _uncell(c: str) -> Any:
    if c.startswith('"'):
        return json.loads(c)
    if c in ("null", "true", "false") or _NUMBER.match(c):
        return json.loads(c)
    return c


def toon_decode(text: str) -> Any:
    """Read back what ``toon_compress`` wrote (the inverse; used by tests and to prove the format)."""
    lines = text.split("\n")
    rest: dict[str, Any] | None = None
    if lines[0].startswith("{"):
        rest = json.loads(lines[0])
        lines = lines[1:]
    head = lines[0]
    m = re.match(r'^(?P<name>"(?:[^"\\]|\\.)*"|[^\[]*)\[(?P<n>\d+)\]\{(?P<keys>.*)\}:$', head)
    if not m:
        raise ValueError("not a TOON table header")
    keys = [_uncell(k) if k.startswith('"') else k for k in _split_cells(m["keys"])]
    rows = [dict(zip(keys, (_uncell(c) for c in _split_cells(ln)))) for ln in lines[1:1 + int(m["n"])]]
    if not m["name"]:
        return rows
    name = json.loads(m["name"]) if m["name"].startswith('"') else m["name"]
    return {**(rest or {}), name: rows}


def _dominant_array(parsed: Any) -> tuple[list, str | None] | None:
    if isinstance(parsed, list):
        return parsed, None
    if isinstance(parsed, dict):
        best = None
        for k, v in parsed.items():
            if isinstance(v, list) and len(v) >= 8 and (best is None or len(v) > len(best[0])):
                best = (v, k)
        return best
    return None


def toon_compress(parsed: Any) -> str | None:
    dom = _dominant_array(parsed)
    if dom is None or uniform_keys(dom[0]) is None:
        return None
    arr, name = dom
    parts = []
    if isinstance(parsed, dict):
        rest = {k: v for k, v in parsed.items() if k != name}
        if rest:
            parts.append(json.dumps(rest, ensure_ascii=False, separators=(",", ":")))
    parts.append(toon_encode(arr, uniform_keys(arr), name))
    out = "\n".join(parts)
    return out if len(out) >= 20 else None


# -- structural JSON shortening (theirs: transformValue) -------------------------------

def _shorten_value(v: Any, depth: int) -> Any:
    if depth > 6:
        return "[deep]"
    if isinstance(v, list):
        if len(v) > 10:
            kept = [_shorten_value(x, depth + 1) for x in v[:3]]
            kept.append({"__omitted__": f"+{len(v) - 5} more items"})
            kept += [_shorten_value(x, depth + 1) for x in v[-2:]]
            return kept
        return [_shorten_value(x, depth + 1) for x in v]
    if isinstance(v, dict):
        out: dict[str, Any] = {}
        for n, (k, val) in enumerate(v.items(), 1):
            if n > 30:
                out["__omitted_keys__"] = f"+{len(v) - 30} more keys"
                break
            protected = bool(PROTECTED_KEY_RE.search(str(k)))
            if isinstance(val, str) and len(val) > 400 and not protected:
                val = f"{val[:220]} ...[+{len(val) - 300} chars]... {val[-80:]}"
            elif isinstance(val, str) and protected and len(val) > 2000:
                val = f"{val[:1800]} ...[+{len(val) - 1900} chars truncated error detail]... "
            elif isinstance(val, (dict, list)):
                val = _shorten_value(val, depth + 1)
            out[k] = val
        return out
    return v


# -- line compression (theirs: compressLines and helpers) -----------------------------
# Lines travel as (original line number or None, text), so every "L61:" is the line's
# number in the original output, even after blank runs and repeats were folded.

Line = tuple[int | None, str]


def _collapse_blanks(lines: list[Line]) -> list[Line]:
    out, blanks = [], 0
    for ln in lines:
        if ln[1].strip() == "":
            blanks += 1
            if blanks >= 2:
                continue
        else:
            blanks = 0
        out.append(ln)
    return out


def _collapse_repeats(lines: list[Line]) -> list[Line]:
    out, i = [], 0
    while i < len(lines):
        j = i
        while j < len(lines) and lines[j][1] == lines[i][1]:
            j += 1
        if j - i > 4 and lines[i][1].strip():
            out += [lines[i], (None, f"[x{j - i} identical lines]")]
        else:
            out += lines[i:j]
        i = j
    return out


def _trim_long_lines(lines: list[Line], limit: int) -> list[Line]:
    out = []
    for no, t in lines:
        if len(t) > limit:
            t = f"{t[:260]} ...[+{len(t) - 360} chars]... {t[-100:]}"
        out.append((no, t))
    return out


def _profile(line: str) -> str:
    pipes, tabs = line.count("|"), line.count("\t")
    return f"p{pipes}" if pipes else (f"t{tabs}" if tabs else "x")


def looks_tabular(lines: list[str], cfg: SaverConfig) -> bool:
    """At least 70% of the non-blank lines share one pipe/tab profile.

    Unlike the original, lines with neither pipes nor tabs don't count as a profile: a
    plain log would otherwise pass as a table and lose its error-line protection.
    """
    dense = [ln for ln in lines if ln.strip()]
    if len(dense) < cfg.tabular_head_rows + cfg.tabular_tail_rows:
        return False
    counts: dict[str, int] = {}
    for ln in dense:
        p = _profile(ln)
        counts[p] = counts.get(p, 0) + 1
    counts.pop("x", None)
    best = max(counts.values(), default=0)
    return best >= len(dense) * 0.7 and best >= 12


def _numbered(ln: Line) -> str:
    return f"L{ln[0]}: {ln[1]}" if ln[0] is not None else ln[1]


def _window(lines: list[Line], cfg: SaverConfig) -> list[str]:
    """Head and tail windows, and the error-like lines of the part left out."""
    if len(lines) <= cfg.max_lines:
        return [t for _, t in lines]
    middle = lines[cfg.head_lines:len(lines) - cfg.tail_lines]
    errors = [_numbered(ln) for ln in middle if ERROR_LINE_RE.search(ln[1])][:cfg.error_lines_kept]
    out = [t for _, t in lines[:cfg.head_lines]]
    out.append(f"[... +{len(middle)} lines omitted ...]")
    if errors:
        out.append(f"[token saver kept {len(errors)} error-like lines from the omitted region:]")
        out += errors
    return out + [t for _, t in lines[len(lines) - cfg.tail_lines:]]


def _window_strided(lines: list[Line], cfg: SaverConfig) -> list[str]:
    """Head and tail rows verbatim, every n-th middle row with its original line number."""
    if len(lines) <= cfg.max_lines:
        return [t for _, t in lines]
    head_n, tail_n = cfg.tabular_head_rows, cfg.tabular_tail_rows
    middle = lines[head_n:len(lines) - tail_n]
    stride = max(1, math.ceil(len(middle) / max(1, cfg.tabular_stride_samples)))
    out = [t for _, t in lines[:head_n]]
    out.append(f"[... +{len(middle)} data rows omitted; every {stride}. row sampled below WITH original line "
               "numbers so any range can be retrieved precisely ...]")
    out += [_numbered(ln) for ln in middle[::stride]]
    return out + [t for _, t in lines[len(lines) - tail_n:]]


def compress_lines(text: str, cfg: SaverConfig) -> tuple[str, str]:
    """(shortened text, strategy) for plain text: 'table' or 'window'."""
    lines: list[Line] = list(enumerate(text.split("\n"), 1))
    lines = _trim_long_lines(_collapse_repeats(_collapse_blanks(lines)), cfg.long_line_chars)
    if looks_tabular([t for _, t in lines], cfg):
        return "\n".join(_window_strided(lines, cfg)), "table"
    return "\n".join(_window(lines, cfg)), "window"


def compress_json(text: str, cfg: SaverConfig) -> tuple[str, str] | None:
    """(re-encoded text, 'lossless' or 'json'), or None when the text isn't JSON."""
    t = text.strip()
    if len(t) > cfg.json_max_parse_bytes or t[:1] not in ("{", "["):
        return None
    try:
        parsed = json.loads(t)
    except ValueError:
        return None
    lossless = toon_compress(parsed)
    if lossless is not None:
        return lossless, "lossless"
    rebuilt = json.dumps(_shorten_value(parsed, 0), ensure_ascii=False, separators=(",", ":"))
    return (rebuilt, "json") if len(rebuilt) >= 20 else None


def build_candidate(text: str, cfg: SaverConfig) -> tuple[str, str] | None:
    """The shortened text and its strategy, lossless first; None when nothing applies."""
    cand = compress_json(text, cfg) or compress_lines(text, cfg)
    return cand if cand and len(cand[0]) >= 20 else None


def passes_gate(original: str, replacement: str, cfg: SaverConfig) -> bool:
    """Never worse: smaller enough in bytes, saves enough, and fewer estimated tokens."""
    before, after = utf8_bytes(original), utf8_bytes(replacement)
    return (after <= before * cfg.keep_ratio_max and before - after >= cfg.min_saved_bytes
            and est_tokens(replacement) < est_tokens(original))


# -- the saver itself -------------------------------------------------------------------

@dataclass
class SaverStats:
    replaced: int = 0
    deduped: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    tokens_saved: int = 0


@dataclass
class TokenSaver:
    """One per conversation (a ``run_agent`` call): dedupe only points at what that model saw."""

    cfg: SaverConfig
    project_root: Path | None  # spill files go under <root>/.harness/spill; None: never compress
    on_event: Callable[[str, dict[str, Any]], None] | None = None
    clock: Callable[[], float] = time.monotonic
    stats: SaverStats = field(default_factory=SaverStats)
    _seen: dict[str, float] = field(default_factory=dict)
    _seq: int = 0

    # -- spill ------------------------------------------------------------
    def spill_dir(self) -> Path | None:
        return (Path(self.project_root) / SPILL_DIR) if self.project_root else None

    def _new_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}{self._seq:x}{secrets.token_hex(3)}"

    def _spill(self, sid: str, text: str) -> Path | None:
        """Write the original atomically; None if that failed (then nothing is replaced)."""
        d = self.spill_dir()
        if d is None:
            return None
        path = d / f"{sid}.txt"
        tmp = d / f".{sid}.tmp"
        try:
            d.mkdir(parents=True, exist_ok=True)
            tmp.write_text(text, encoding="utf-8", errors="surrogatepass")
            os.replace(tmp, path)
            return path
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return None

    def _rel(self, path: Path) -> str:
        return path.relative_to(Path(self.project_root)).as_posix()

    # -- one tool result --------------------------------------------------
    def process(self, tool: str, args: dict[str, Any], text: str, is_error: bool = False) -> str:
        """What the model sees for this tool result (the text itself, or a slimmer stand-in)."""
        if not self.cfg.enabled or tool in EXEMPT_TOOLS or not isinstance(text, str):
            return text
        if self.cfg.dedupe_enabled and not is_error:
            stub = self._dedupe(tool, args, text)
            if stub is not None:
                return stub
        if utf8_bytes(text) <= (self.cfg.error_min_bytes if is_error else self.cfg.min_bytes):
            return text
        cand = build_candidate(text, self.cfg)
        if cand is None:
            return text
        body, strategy = cand
        sid = self._new_id("c")
        final = body + "\n\n" + self._notice(sid, strategy, text, body)
        if not passes_gate(text, final, self.cfg):
            return text
        path = self._spill(sid, text)
        if path is None:
            return text
        self._record(tool, strategy, sid, text, final)
        return final

    def _notice(self, sid: str, strategy: str, original: str, body: str) -> str:
        before, after = utf8_bytes(original), utf8_bytes(body)
        pct = round((1 - after / before) * 100)
        how = {"lossless": "losslessly re-encoded as a table (header lists the keys; quoted cells are JSON "
                           "strings); zero information loss",
               "table": "shortened: first and last rows kept, the middle sampled with original line numbers",
               "json": "shortened: long lists and strings in the JSON trimmed",
               "window": "shortened: start and end kept, error-like lines from the middle kept with line numbers",
               }[strategy]
        return (f"[saved-output #{sid} {how}. {before:,} -> {after:,} bytes (~{pct}% smaller). Need the full "
                f"original or a line range? Call expand_output with id \"{sid}\" (optionally start_line/end_line), "
                f"or read_file {SPILL_DIR.as_posix()}/{sid}.txt]")

    def _dedupe(self, tool: str, args: dict[str, Any], text: str) -> str | None:
        try:
            a = json.dumps(args, sort_keys=True, default=str)
        except (TypeError, ValueError):
            a = str(args)
        key = hashlib.sha1(f"{tool}\x00{a}\x00{text}".encode("utf-8", "surrogatepass")).hexdigest()
        now, prev = self.clock(), self._seen.get(key)
        self._seen[key] = now
        if prev is None or now - prev > self.cfg.dedupe_ttl_seconds:
            return None
        sid = self._new_id("d")
        stub = (f"[saved-output #{sid} deduped: this {tool} call returned BYTE-IDENTICAL output to the same call "
                f"{round(now - prev)}s ago, which is still in the conversation above. Use that earlier result, or "
                f"run it again if it may have changed. The full copy of this one: expand_output id \"{sid}\" or "
                f"read_file {SPILL_DIR.as_posix()}/{sid}.txt]")
        if utf8_bytes(text) - utf8_bytes(stub) <= self.cfg.min_saved_bytes or est_tokens(stub) >= est_tokens(text):
            return None
        if self._spill(sid, text) is None:
            return None
        self._record(tool, "dedupe", sid, text, stub)
        return stub

    def _record(self, tool: str, strategy: str, sid: str, original: str, shown: str) -> None:
        before, after = utf8_bytes(original), utf8_bytes(shown)
        saved = max(0, est_tokens(original) - est_tokens(shown))
        s = self.stats
        s.replaced += 1
        s.deduped += strategy == "dedupe"
        s.bytes_before += before
        s.bytes_after += after
        s.tokens_saved += saved
        if self.on_event:
            self.on_event("token_saver", {"tool": tool, "strategy": strategy, "id": sid, "bytes_before": before,
                                          "bytes_after": after, "tokens_saved_est": saved})

    # -- getting the original back ------------------------------------------
    def expand(self, a: dict[str, Any]) -> str:
        from .tools import ToolError

        sid = str(a.get("id") or "").strip().lstrip("#")
        d = self.spill_dir()
        path = d / f"{sid}.txt" if d and ID_RE.match(sid) else None
        if path is None or not path.is_file():
            raise ToolError(f"no saved output with id {sid!r}; use the id from the [saved-output #...] notice")
        text = path.read_text(encoding="utf-8", errors="replace")
        start, end = a.get("start_line"), a.get("end_line")
        if start is None and end is None:
            if len(text) <= EXPAND_MAX_CHARS:
                return text
            return (text[:EXPAND_MAX_CHARS] + f"\n[... {len(text) - EXPAND_MAX_CHARS:,} more characters; "
                    "ask for a range with start_line/end_line]")
        lines = text.split("\n")
        lo, hi = max(int(start or 1), 1), min(int(end or len(lines)), len(lines))
        return "\n".join(f"{i}\t{ln}" for i, ln in enumerate(lines[lo - 1:hi], lo)) or "(no lines in that range)"

    def tool(self):
        from .tools import Tool, _obj

        return Tool(ToolSpec(
            "expand_output",
            "Get the full original text behind a [saved-output #id] notice, or a range of its lines. Use it "
            "whenever a left-out part might hold a detail you need, instead of guessing.",
            _obj({"id": {"type": "string", "description": "the id from the notice, e.g. c1a2b3c"},
                  "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, ["id"]),
        ), self.expand)
