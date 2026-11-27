"""A reply's words as they are written, kept per task for Watch and the chat (wave 8, DS-13).

``sink(root, task)`` is what ``run_agent(on_delta=...)`` is given; ``tail(root, task, since)`` is what
``GET /api/stream`` answers: ``{"text", "thinking", "at", "done"}`` (``at``: where the next read starts).

The words live in ``.harness/live/<task>.words`` beside the live commands' logs (livecmd.py): one JSON line per
piece, ``["text" | "thinking", piece]``, under a first line ``{"gen": n, "dropped": d}``. A new sink (a new
model conversation of that task: the worker, then its reviewer) starts the file again with the next ``gen``;
only the newest 64 KB are kept (``dropped``: how many characters went). ``clear`` removes the files with the
run's other live files.

``at`` is ``gen * 10**12 + position`` in the stream of every piece in the order they came, so a reader that
still holds a cursor from an older conversation starts the new one from its beginning. A reply that is still
being written is handed out up to its last space only, so a key is never split across two reads, and each read
goes through ``session.redact`` (the rule the app uses for everything it shows from a run).
"""


import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .livecmd import live_dir, safe_task

KEEP = 64 * 1024  # characters kept per task
REWRITE_AT = 2 * KEEP  # the file is cut back to KEEP once it holds this many
GEN = 10 ** 12  # at = gen * GEN + position
QUIET_S = 20.0  # nothing new for this long and the reply counts as done
HOLD_MAX = 4096  # a reply without a space for this long is handed out anyway
SETTING_LIKE = re.compile(r"(?i)(?:(?:pass|secret|token|key|auth|credential)\w*[\"']?\s*[:=]|-----BEGIN)")
_lock = threading.Lock()


def path(root, task: str) -> Path:
    return live_dir(root) / f"{safe_task(task)}.words"


def enabled(cfg: Any) -> bool:
    """``stream: {enabled: false}`` in harness.yaml turns the words-as-written off (the calls are then made
    exactly as before streaming existed). On by default."""
    try:
        from .config import section

        return section(cfg, "stream").get("enabled", True) is not False
    except Exception:  # noqa: BLE001 - an odd config never stops a run
        return True


def _read(p: Path) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}, []
    head: dict[str, Any] = {}
    rows: list[tuple[str, str]] = []
    for i, line in enumerate(lines):
        try:
            d = json.loads(line)
        except ValueError:
            continue  # a line half written as we read: the next read has it
        if i == 0 and isinstance(d, dict):
            head = d
        elif isinstance(d, list) and len(d) == 2 and d[0] in ("text", "thinking") and isinstance(d[1], str):
            rows.append((d[0], d[1]))
    return head, rows


def _write(p: Path, head: dict[str, Any], rows: list[tuple[str, str]]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    body = [json.dumps(head)] + [json.dumps([k, s], ensure_ascii=False) for k, s in rows]
    tmp.write_text("\n".join(body) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def _cut(rows: list[tuple[str, str]], keep: int) -> tuple[list[tuple[str, str]], int]:
    """The newest ``keep`` characters of the pieces, and how many characters were let go."""
    total = sum(len(s) for _, s in rows)
    drop = max(0, total - keep)
    gone = 0
    out: list[tuple[str, str]] = []
    for kind, s in rows:
        if gone + len(s) <= drop:
            gone += len(s)
            continue
        if gone < drop:
            s = s[drop - gone:]
            gone = drop
        out.append((kind, s))
    return out, gone


def sink(root, task: str) -> Callable[[str, str], None]:
    """Where ``task``'s reply pieces go (``("text" | "thinking", piece)``). Starts the task's words again."""
    p = path(root, task)
    with _lock:
        head, _ = _read(p)
        gen = (int(head.get("gen", 0) or 0) + 1) % 9000
        try:
            _write(p, {"gen": gen, "dropped": 0, "t": time.time()}, [])
        except OSError:
            pass
    state = {"size": 0, "dropped": 0}

    def keep(kind: str, piece: str) -> None:
        if kind not in ("text", "thinking") or not piece:
            return
        try:
            with _lock:
                with p.open("a", encoding="utf-8") as f:
                    f.write(json.dumps([kind, piece], ensure_ascii=False) + "\n")
                state["size"] += len(piece)
                if state["size"] >= REWRITE_AT:
                    head, rows = _read(p)
                    rows, gone = _cut(rows, KEEP)
                    state["dropped"] = int(head.get("dropped", 0) or 0) + gone
                    state["size"] = sum(len(s) for _, s in rows)
                    _write(p, {"gen": gen, "dropped": state["dropped"], "t": time.time()}, rows)
        except OSError:
            pass  # the words are a help: a full disk never stops the build

    return keep


def _safe(text: str) -> str:
    from .session import redact

    return redact(text) if text else ""


def tail(root, task: str, since: int = 0) -> dict:
    """What is new since ``since``: ``{"text", "thinking", "at", "done"}`` (and ``skipped`` when the start was
    let go). A reply quiet for 20 seconds counts as done."""
    return read(root, task, since)


def read(root, task: str, since: int = 0, done: bool | None = None) -> dict:
    """``tail``, where the caller may know better: ``done`` True when the task isn't working any more (a reply
    is then handed out to its very end)."""
    p = path(root, task)
    with _lock:
        head, rows = _read(p)
        try:
            quiet = time.time() - p.stat().st_mtime
        except OSError:
            quiet = None
    if quiet is None:
        return {"text": "", "thinking": "", "at": int(since or 0), "done": True}
    gen = int(head.get("gen", 0) or 0)
    dropped = int(head.get("dropped", 0) or 0)
    since = int(since or 0)
    pos = since % GEN if since // GEN == gen else 0  # a cursor from an older conversation: from the start
    finished = bool(done) if done is not None else quiet >= QUIET_S
    skipped = max(0, dropped - pos)
    pos = max(pos, dropped)
    # the pieces after pos, in order, kind by kind
    new: list[tuple[str, str]] = []
    at = dropped
    for kind, s in rows:
        end = at + len(s)
        if end > pos:
            new.append((kind, s[max(0, pos - at):]))
        at = end
    if not finished:  # hand out up to the last space only: a key never splits across two reads
        flat = "".join(s for _, s in new)
        cut = max(flat.rfind(" "), flat.rfind("\n"), flat.rfind("\t"))
        line_start = flat.rfind("\n") + 1
        if SETTING_LIKE.search(flat[line_start:]):  # "password: …" may span a space: keep that line whole
            cut = line_start - 1
        hold = len(flat) - (cut + 1) if cut >= 0 else len(flat)
        if 0 < hold < HOLD_MAX:
            new = _trim_end(new, hold)
    text = "".join(s for k, s in new if k == "text")
    thinking = "".join(s for k, s in new if k == "thinking")
    taken = sum(len(s) for _, s in new)
    return {"text": _safe(text), "thinking": _safe(thinking), "at": gen * GEN + pos + taken, "done": finished,
            "skipped": skipped}


def _trim_end(rows: list[tuple[str, str]], n: int) -> list[tuple[str, str]]:
    out = list(rows)
    while n > 0 and out:
        kind, s = out[-1]
        if len(s) <= n:
            n -= len(s)
            out.pop()
        else:
            out[-1] = (kind, s[:-n])
            n = 0
    return out


def clear(root, task: str | None = None) -> int:
    """Remove the words of one task, or of every task (at the end of a run, with the other live files)."""
    d = live_dir(root)
    if not d.is_dir():
        return 0
    gone = 0
    for f in d.glob(f"{safe_task(task)}.words" if task else "*.words"):
        try:
            f.unlink()
            gone += 1
        except OSError:
            pass
    return gone
